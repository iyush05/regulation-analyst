"""Explicit model configuration; no implicit downloads, credentials, or paid calls."""

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .errors import ResearchError

T = TypeVar("T", bound=BaseModel)


def model_fingerprint(path: str) -> str:
    digest = hashlib.sha256()
    root = Path(path).resolve()
    files = sorted(file for file in root.rglob("*") if file.is_file())
    if not files:
        raise ResearchError("not_found", "Local model directory is empty")
    for file in files:
        digest.update(str(file.relative_to(root)).encode() + b"\0")
        with file.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def strict_schema(value):
    """Adapt a Pydantic JSON schema to OpenAI strict mode: closed objects, all keys required."""
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items() if key != "default"}
    if result.get("type") == "object":
        result["additionalProperties"] = False
        result["required"] = list(result.get("properties", {}))
    return result


def image_input(png: bytes, detail: str = "high") -> dict:
    """A page rendering as a Responses API input part."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ResearchError("invalid_request", "Page image input must be PNG bytes")
    encoded = base64.b64encode(png).decode()
    return {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{encoded}",
        "detail": detail,
    }


def output_text(response: dict) -> str:
    return "".join(
        part.get("text", "")
        for item in response.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


class UsageBudget:
    """Token ceiling shared by every model call in one ingestion run."""

    def __init__(self, max_total_tokens: int):
        if max_total_tokens < 1:
            raise ResearchError("invalid_request", "Token budget must be positive")
        self.max_total_tokens = max_total_tokens
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    @property
    def remaining(self) -> int:
        return self.max_total_tokens - self.usage["total_tokens"]

    def check(self):
        if self.remaining <= 0:
            raise ResearchError("not_found", "Ingestion stopped at its model token budget")

    def record(self, response: dict):
        for key in self.usage:
            self.usage[key] += int(response.get("usage", {}).get(key, 0))


class OpenAIProvider:
    def __init__(
        self, *, model: str, api_key: str | None = None, client: httpx.Client | None = None
    ):
        self.model = model
        self.key = api_key or os.environ.get("OPENAI_API_KEY")
        if not model or not self.key:
            raise ResearchError("invalid_request", "Set OPENAI_API_KEY and an explicit model name")
        self.client = client
        self.identity = f"openai:{model}"

    def request(self, endpoint: str, body: dict, timeout: float = 45) -> dict:
        if endpoint not in ("responses", "embeddings"):
            raise ResearchError("invalid_request", "Unsupported model endpoint")
        owned = self.client is None
        client = self.client or httpx.Client(follow_redirects=False)
        try:
            response = client.post(
                f"https://api.openai.com/v1/{endpoint}",
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, **body},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Do not expose provider bodies, headers, or potentially sensitive input.
            raise ResearchError(
                "not_found", f"Model request failed ({type(exc).__name__})"
            ) from exc
        finally:
            if owned:
                client.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            result = self.request("embeddings", {"input": batch, "encoding_format": "float"})
            items = sorted(result.get("data", []), key=lambda item: item["index"])
            if [item["index"] for item in items] != list(range(len(batch))):
                raise ResearchError(
                    "invalid_request", "Embedding response omitted or duplicated inputs"
                )
            vectors.extend(item["embedding"] for item in items)
        return vectors

    def respond(
        self, messages: list, tools: list, *, max_output_tokens: int, timeout: float
    ) -> dict:
        return self.request(
            "responses",
            {
                "input": messages,
                "tools": tools,
                "store": False,
                "parallel_tool_calls": False,
                "max_output_tokens": max_output_tokens,
            },
            timeout=timeout,
        )

    def structured(
        self,
        instructions: str,
        content: list[dict],
        schema: type[T],
        *,
        max_output_tokens: int = 2000,
        timeout: float = 90,
        web_search: bool = False,
        budget: UsageBudget | None = None,
    ) -> T:
        """One schema-constrained response. Output failing the schema is rejected, not repaired."""
        if budget:
            budget.check()
            max_output_tokens = min(max_output_tokens, budget.remaining)
        response = self.request(
            "responses",
            {
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "tools": [{"type": "web_search"}] if web_search else [],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema.__name__,
                        "schema": strict_schema(schema.model_json_schema()),
                        "strict": True,
                    }
                },
                "store": False,
                "max_output_tokens": max_output_tokens,
            },
            timeout=timeout,
        )
        if budget:
            budget.record(response)
        if response.get("status") == "incomplete":
            raise ResearchError("not_found", "Model response was incomplete")
        try:
            return schema.model_validate(json.loads(output_text(response)))
        except (ValueError, ValidationError) as exc:
            raise ResearchError(
                "invalid_request", "Model output did not match the required schema"
            ) from exc


class LocalEmbeddings:
    def __init__(self, path: str, revision: str):
        if not Path(path).is_dir() or not revision:
            raise ResearchError(
                "not_found", "Supply a local embedding model directory and pinned revision"
            )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ResearchError(
                "not_found", "Install the local-search extra and local model weights"
            ) from exc
        self.model = SentenceTransformer(path, local_files_only=True, trust_remote_code=False)
        self.identity = f"sentence-transformers:{revision}:{model_fingerprint(path)}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


class CrossEncoderReranker:
    def __init__(self, path: str, revision: str):
        if not Path(path).is_dir() or not revision:
            raise ResearchError(
                "not_found", "Supply a local reranker directory and pinned revision"
            )
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ResearchError(
                "not_found", "Install the local-search extra and local reranker weights"
            ) from exc
        self.model = CrossEncoder(path, local_files_only=True, trust_remote_code=False)
        self.identity = f"cross-encoder:{revision}:{model_fingerprint(path)}"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(value) for value in self.model.predict([(query, text) for text in texts])]


def embedding_provider():
    backend = os.environ.get("REGULATION_EMBEDDING_PROVIDER", "openai")
    if backend == "openai":
        return OpenAIProvider(model=os.environ.get("REGULATION_EMBEDDING_MODEL", ""))
    if backend == "local":
        return LocalEmbeddings(
            os.environ.get("REGULATION_EMBEDDING_MODEL", ""),
            os.environ.get("REGULATION_EMBEDDING_REVISION", ""),
        )
    raise ResearchError("invalid_request", "Embedding provider must be openai or local")
