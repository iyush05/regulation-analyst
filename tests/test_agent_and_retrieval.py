"""Controlled model/vector protocol tests; these are not live quality measurements."""

import json
from datetime import date

import httpx
import pytest

from regulation_analyst.agent import Budgets, run_agent, tool_schemas
from regulation_analyst.errors import ResearchError
from regulation_analyst.metrics import calculate
from regulation_analyst.models import Bundle, Document, Evidence, Passage
from regulation_analyst.providers import OpenAIProvider
from regulation_analyst.retrieval import HybridRetriever, build_index, unit_vector
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


class ScriptedProvider:
    identity = "controlled-test-double:not-a-live-model"

    def __init__(self, calls):
        self.calls = iter(calls)
        self.messages = []

    def respond(self, messages, tools, **kwargs):
        self.messages = list(messages)
        name, arguments = next(self.calls)
        return {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "name": name,
                    "call_id": str(len(messages)),
                    "arguments": json.dumps(arguments),
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


def finish(**updates):
    return {
        "fact_ids": [],
        "calculation_ids": [],
        "passage_ids": [],
        "provision_ids": [],
        "gaps": [],
        **updates,
    }


def test_agent_multistep_recomputes_and_renders_citations(service, tmp_path):
    facts = ["infosys-indas-2025-operating_profit", "infosys-indas-2025-revenue"]
    result = calculate(service.store, "operating_margin", facts)
    provider = ScriptedProvider(
        [
            (
                "get_table",
                {
                    "company": "Infosys",
                    "years": ["FY25"],
                    "metrics": ["operating_profit", "revenue"],
                },
            ),
            ("calculate", {"formula": "operating_margin", "fact_ids": facts}),
            (
                "search_filings",
                {
                    "query": "margin",
                    "company": "Infosys",
                    "year": "FY25",
                    "document_type": "transcript",
                },
            ),
            (
                "finish",
                finish(
                    calculation_ids=[result["id"]], passage_ids=["passage-infosys-call25-margin"]
                ),
            ),
        ]
    )
    answer = run_agent(
        service,
        "Infosys operating margin FY25 and management explanation",
        provider,
        log_dir=tmp_path,
    )
    assert answer.status == "ok", answer.message
    assert "21.12" in answer.data["answer"]
    assert "#page=346" in answer.data["answer"]
    assert answer.data["calculations"][0] == result
    assert len(answer.data["claims"]) == 2
    outputs = [m["output"] for m in provider.messages if m.get("type") == "function_call_output"]
    assert outputs
    # The model sees IDs, values, units, and trust; locators stay with the server's ledger.
    assert all('"source"' not in output and "#page=" not in output for output in outputs)
    assert any('"trust":"reviewed"' in output for output in outputs)
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert "#page=" in json.dumps(report["trace"])
    assert report["usage"]["total_tokens"] == 60
    assert report["model"].startswith("controlled-test-double")


@pytest.mark.parametrize(
    "call,expected",
    [
        (("finish", finish(fact_ids=["made-up"])), "never returned"),
        (
            ("calculate", {"formula": "operating_margin", "fact_ids": ["x", "y"]}),
            "previously retrieved",
        ),
        (("run_shell", {"command": "echo test"}), "unauthorized"),
        (("search_regulations", {"query": "KYC", "as_of": "2025-06-12"}), "explicit question date"),
        (
            ("get_table", {"company": "TCS", "years": ["FY25"], "metrics": ["revenue"]}),
            "outside the question",
        ),
    ],
)
def test_agent_rejects_invalid_evidence_and_calls(service, tmp_path, call, expected):
    answer = run_agent(service, "Infosys revenue FY25", ScriptedProvider([call]), log_dir=tmp_path)
    assert answer.status == "invalid_request"
    assert expected in answer.message


def test_agent_budget_and_advice_boundary(service, tmp_path):
    provider = ScriptedProvider([("list_companies", {})] * 5)
    result = run_agent(
        service,
        "Infosys revenue FY25",
        provider,
        budgets=Budgets(max_iterations=2),
        log_dir=tmp_path,
    )
    assert result.status == "not_found" and "iteration budget" in result.message
    result = run_agent(service, "Should I buy Infosys?", provider, log_dir=tmp_path)
    assert result.status == "out_of_scope"


def test_agent_rejects_wrong_year_and_altered_fact_values(service, tmp_path, monkeypatch):
    provider = ScriptedProvider(
        [("get_table", {"company": "Infosys", "years": ["FY24"], "metrics": ["revenue"]})]
    )
    answer = run_agent(service, "Infosys revenue FY25", provider, log_dir=tmp_path)
    assert answer.status == "invalid_request" and "fiscal year" in answer.message
    original_call = service.call

    def altered(operation, **kwargs):
        result = original_call(operation, **kwargs)
        if operation == "get_table":
            result.data["facts"][0]["value"] = "999"
        return result

    monkeypatch.setattr(service, "call", altered)
    provider = ScriptedProvider(
        [("get_table", {"company": "Infosys", "years": ["FY25"], "metrics": ["revenue"]})]
    )
    answer = run_agent(service, "Infosys revenue FY25", provider, log_dir=tmp_path)
    assert answer.status == "invalid_request" and "altered" in answer.message


def test_every_tool_schema_is_strict():
    for tool in tool_schemas():
        assert tool["strict"] is True
        schema = tool["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_provider_http_protocol_no_key_in_error():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]
                },
            )
        return httpx.Response(401, text="private-secret")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIProvider(model="controlled-model", api_key="private-secret", client=client)
        assert provider.embed(["a", "b"]) == [[1, 0], [0, 1]]
        with pytest.raises(ResearchError) as error:
            provider.respond([], [], max_output_tokens=100, timeout=1)
        assert "private-secret" not in str(error.value)
        assert requests[-1]["store"] is False


class ControlledVectors:
    identity = "controlled-vectors:v1:not-semantic-quality"

    def embed(self, texts):
        return [[1.0, 0.0] if "margin" in text.casefold() else [0.0, 1.0] for text in texts]


def test_real_sqlite_index_fusion_filtering_and_stale_model(store, tmp_path):
    index = tmp_path / "vectors.sqlite3"
    embedder = ControlledVectors()
    build_index(store, index, embedder)
    retriever = HybridRetriever(store, index, embedder)
    hits = retriever.search("margin", company_id="infosys", year=2025, document_type="transcript")
    assert hits[0]["id"] == "passage-infosys-call25-margin"
    assert hits[0]["retrieval"]["ranks"] == {"lexical": 1, "dense": 1}
    assert retriever.search("margin", company_id="tcs") == []
    assert retriever.search("margin", year=2024) == []
    assert (
        retriever.search("margin", known_on="2025-12-31") == []
    )  # Unknown publication dates excluded.
    service = ResearchService(store, retriever)
    assert (
        service.search_filings("margin", company="Infosys").data["retrieval_method"]
        == "bm25_dense_rrf"
    )
    embedder.identity = "different-model"
    with pytest.raises(ResearchError, match="stale"):
        retriever.search("margin")


def test_index_stale_corpus_and_reranker(store, tmp_path):
    index, embedder = tmp_path / "vectors.sqlite3", ControlledVectors()
    build_index(store, index, embedder)

    class Reranker:
        identity = "controlled-reranker"

        def score(self, query, texts):
            return [0.8] * len(texts)

    retriever = HybridRetriever(store, index, embedder, Reranker())
    assert retriever.search("margin")[0]["retrieval"]["rerank_score"] == 0.8
    writable = Store(store.path, readonly=False)
    writable.import_bundle(
        Bundle(
            description="test",
            documents=[
                Document(
                    id="new-doc",
                    title="Test",
                    url="https://example.org/test.pdf",
                    kind="transcript",
                    company_id="infosys",
                    reporting_year=2025,
                    captured_on=date(2026, 1, 1),
                )
            ],
            evidence=[
                Evidence(
                    id="new-ev",
                    document_id="new-doc",
                    pdf_page=1,
                    section="Test",
                    review_method="source_text_crosscheck",
                    reviewer="test",
                    reviewed_on=date(2026, 1, 1),
                )
            ],
            passages=[
                Passage(
                    id="new-passage",
                    evidence_id="new-ev",
                    company_id="infosys",
                    fiscal_year=2025,
                    text="Synthetic margin commentary",
                    representation="excerpt",
                )
            ],
        )
    )
    with pytest.raises(ResearchError, match="stale"):
        retriever.search("margin")


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan")], [float("inf")], [True, 1]])
def test_invalid_vectors_fail_closed(vector):
    with pytest.raises(ResearchError):
        unit_vector(vector)
