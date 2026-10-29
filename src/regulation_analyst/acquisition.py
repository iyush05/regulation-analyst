"""Explicit acquisition of individual official documents with bounded, hashed archives."""

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .errors import ResearchError

OFFICIAL_DOMAINS = (
    "infosys.com",
    "tcs.com",
    "hcltech.com",
    "sebi.gov.in",
    "rbi.org.in",
    "bseindia.com",
    "nseindia.com",
)


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$")
    url: str
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_bytes: int = Field(default=50_000_000, ge=1, le=200_000_000)


def validate_official_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)
    ):
        raise ResearchError(
            "invalid_request",
            "Acquisition requires an HTTPS URL on a supported official source domain",
        )
    return url


def acquire(
    source: SourceRequest,
    archive: str | Path,
    *,
    local_pdf: str | Path | None = None,
    client: httpx.Client | None = None,
) -> dict:
    validate_official_url(source.url)
    root = Path(archive).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=".download-", dir=root)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    final_url = source.url
    owned_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    try:
        with os.fdopen(handle, "wb") as target:

            def consume(chunks):
                nonlocal size
                for chunk in chunks:
                    size += len(chunk)
                    if size > source.max_bytes:
                        raise ResearchError(
                            "invalid_request", "Source exceeds the configured download size limit"
                        )
                    digest.update(chunk)
                    target.write(chunk)

            if local_pdf:
                with Path(local_pdf).expanduser().open("rb") as incoming:
                    consume(iter(lambda: incoming.read(65536), b""))
            else:
                for _ in range(4):
                    validate_official_url(final_url)
                    with client.stream(
                        "GET",
                        final_url,
                        headers={"User-Agent": "RegulationAnalyst/0.2 source-archive"},
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ResearchError(
                                    "not_found", "Official source redirect has no location"
                                )
                            final_url = urljoin(final_url, location)
                            continue
                        response.raise_for_status()
                        consume(response.iter_bytes(chunk_size=65536))
                        break
                else:
                    raise ResearchError("not_found", "Official source exceeded the redirect limit")
        with temporary.open("rb") as downloaded:
            if b"%PDF-" not in downloaded.read(1024):
                raise ResearchError(
                    "invalid_request",
                    "Source did not return a PDF; HTML challenge pages are not accepted",
                )
        sha256 = digest.hexdigest()
        if source.expected_sha256 and source.expected_sha256 != sha256:
            raise ResearchError("invalid_request", "Source hash differs from the pinned manifest")
        directory = root / sha256
        directory.mkdir(exist_ok=True)
        destination = directory / "original.pdf"
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != sha256:
                raise ResearchError(
                    "invalid_request", "Existing archive bytes do not match their content address"
                )
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        metadata = {
            "id": source.id,
            "url": source.url,
            "resolved_url": final_url,
            "sha256": sha256,
            "bytes": size,
            "snapshot_path": str(destination),
            "acquired_at": datetime.now(UTC).isoformat(),
            "method": "local_file" if local_pdf else "official_https",
        }
        metadata_file = directory / f"{source.id}.json"
        if not metadata_file.exists():
            metadata_file.write_text(json.dumps(metadata, indent=2) + "\n")
        return metadata
    except httpx.HTTPError as exc:
        raise ResearchError(
            "not_found",
            f"Source acquisition failed ({type(exc).__name__}); "
            "provide an official local PDF or restore network access",
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
        if owned_client:
            client.close()
