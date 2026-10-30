import json
import sqlite3
from datetime import date

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from regulation_analyst.errors import ResearchError
from regulation_analyst.models import Bundle, Evidence
from regulation_analyst.providers import OpenAIProvider, UsageBudget, image_input
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store

GATES = ["grounding", "period_unit", "identities"]


def automate(bundle: Bundle, method="automated_extraction", ids=None) -> Bundle:
    """Relabel synthetic evidence as pipeline output. Values stay synthetic."""
    evidence = []
    for item in bundle.evidence:
        if ids is None or item.id in ids:
            data = item.model_dump() | {
                "review_method": method,
                "reviewer": "pipeline:test",
                "checks": GATES,
                "resolution_note": "Selected the consolidated column"
                if method == "llm_resolved"
                else "",
            }
            item = Evidence.model_validate(data)
        evidence.append(item)
    return bundle.model_copy(update={"evidence": evidence})


def evidence(**overrides):
    base = dict(
        id="ev",
        document_id="doc",
        pdf_page=1,
        section="Statement",
        review_method="human_review",
        reviewer="Reviewer",
        reviewed_on=date(2026, 10, 30),
    )
    return Evidence(**(base | overrides))


def test_trust_labels_require_matching_provenance():
    assert evidence().trust == "reviewed"
    assert evidence(review_method="automated_extraction", checks=GATES).trust == "automated"
    assert (
        evidence(review_method="llm_resolved", checks=GATES, resolution_note="Cell r3c2").trust
        == "llm_resolved"
    )
    with pytest.raises(ValidationError, match="validation gates"):
        evidence(review_method="automated_extraction")
    with pytest.raises(ValidationError, match="resolution note"):
        evidence(review_method="llm_resolved", checks=GATES)
    with pytest.raises(ValidationError, match="resolution note"):
        evidence(review_method="automated_extraction", checks=GATES, resolution_note="x")
    with pytest.raises(ValidationError, match="resolution note"):
        evidence(resolution_note="Reviewed values never carry one")


def test_automated_facts_fill_gaps_and_are_labelled(tmp_path, synthetic_bundle):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    store.import_bundle(automate(synthetic_bundle([{"metric": "revenue", "raw_value": "100"}])))
    service = ResearchService(Store(store.path))

    table = service.get_table("alpha", ["FY25"], ["revenue"])
    assert table.status == "ok"
    source = table.data["facts"][0]["source"]
    assert source["trust"] == "automated"
    assert source["citation"].endswith("(unreviewed: automated extraction)")

    strict = service.get_table("alpha", ["FY25"], ["revenue"], trust="reviewed_only")
    assert strict.status == "not_found"
    assert "No reviewed consolidated" in strict.data["missing"][0]["reason"]
    invalid = service.call("get_table", company="alpha", years=["FY25"], trust="everything")
    assert invalid.status == "invalid_request"


def test_reviewed_fact_outranks_conflicting_automated_value(tmp_path, synthetic_bundle):
    rows = [
        {"id": "reviewed-revenue", "metric": "revenue", "raw_value": "100"},
        {"id": "auto-revenue", "metric": "revenue", "raw_value": "999"},
    ]
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    store.import_bundle(automate(synthetic_bundle(rows), "llm_resolved", {"ev-auto-revenue"}))
    fact = Store(store.path).select_fact("alpha", "revenue", 2025)
    assert fact.id == "reviewed-revenue"


def test_answer_text_discloses_automated_evidence(tmp_path, synthetic_bundle):
    rows = [
        {"metric": "revenue", "raw_value": "200"},
        {"metric": "profit_owners", "raw_value": "30"},
    ]
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    store.import_bundle(automate(synthetic_bundle(rows), "llm_resolved"))
    result = ResearchService(Store(store.path)).answer_question("alpha net margin FY25")
    assert result.status == "ok"
    assert "| alpha | net margin | 15.00% [1] |" in result.data["answer"]
    assert "unreviewed: LLM-resolved" in result.data["answer"]


def test_ingestion_jobs_upsert_and_stay_out_of_corpus_version(tmp_path):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    before = store.version
    store.record_job("Wipro", "FY25-annual-report", "discover", "running")
    store.record_job(
        "Wipro", "FY25-annual-report", "acquire", "needs_manual_pdf", {"url": "https://x"}
    )
    store.record_job("Wipro", "FY24-annual-report", "import", "done")
    jobs = Store(store.path).jobs("Wipro")
    assert [(j["item"], j["stage"], j["status"]) for j in jobs] == [
        ("FY24-annual-report", "import", "done"),
        ("FY25-annual-report", "acquire", "needs_manual_pdf"),
    ]
    assert jobs[1]["detail"] == {"url": "https://x"}
    assert store.version == before
    with pytest.raises(ResearchError):
        store.record_job("Wipro", "x", "teleport", "done")
    with pytest.raises(ResearchError):
        Store(store.path).record_job("Wipro", "x", "import", "done")


def test_version_one_database_reads_and_migrates(tmp_path, demo_bundle):
    path = tmp_path / "old.sqlite3"
    Store(path, readonly=False).import_bundle(demo_bundle)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE ingestion_jobs")
        conn.execute("PRAGMA user_version = 1")
    old = Store(path)
    assert old.jobs() == []
    assert old.select_fact("infosys", "revenue", 2025).company_id == "infosys"
    Store(path, readonly=False).record_job("infosys", "x", "import", "done")
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


class Identity(BaseModel):
    name: str
    nse_symbol: str | None


def respond_with(payload, usage=None, status="completed", requests=None):
    def handler(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": status,
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {"type": "message", "content": [{"type": "output_text", "text": payload}]},
                ],
                "usage": usage or {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_structured_output_is_schema_bound_and_budgeted():
    requests = []
    budget = UsageBudget(120)
    with respond_with('{"name": "Wipro Limited", "nse_symbol": "WIPRO"}', requests=requests) as c:
        provider = OpenAIProvider(model="controlled-model", api_key="k", client=c)
        result = provider.structured(
            "Identify",
            [{"type": "input_text", "text": "Wipro"}],
            Identity,
            web_search=True,
            budget=budget,
        )
        assert result == Identity(name="Wipro Limited", nse_symbol="WIPRO")
        body = requests[-1]
        assert body["store"] is False
        assert body["tools"] == [{"type": "web_search"}]
        schema = body["text"]["format"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert schema["schema"]["required"] == ["name", "nse_symbol"]
        assert budget.usage["total_tokens"] == 50

        provider.structured("Identify", [], Identity, budget=budget)
        assert requests[-1]["max_output_tokens"] == 70
        assert budget.remaining == 20
        provider.structured("Identify", [], Identity, budget=budget)
        with pytest.raises(ResearchError, match="token budget"):
            provider.structured("Identify", [], Identity, budget=budget)


@pytest.mark.parametrize(
    ("payload", "status", "message"),
    [
        ('{"name": "Wipro"}', "completed", "schema"),
        ("not json", "completed", "schema"),
        ('{"name": "Wipro", "nse_symbol": null}', "incomplete", "incomplete"),
    ],
)
def test_structured_output_rejects_invalid_responses(payload, status, message):
    with respond_with(payload, status=status) as client:
        provider = OpenAIProvider(model="controlled-model", api_key="k", client=client)
        with pytest.raises(ResearchError, match=message):
            provider.structured("Identify", [], Identity)


def test_image_input_accepts_only_png():
    part = image_input(b"\x89PNG\r\n\x1a\nrest")
    assert part["type"] == "input_image"
    assert part["image_url"].startswith("data:image/png;base64,")
    with pytest.raises(ResearchError):
        image_input(b"%PDF-1.7")
