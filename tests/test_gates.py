"""Validation gates, the row-only LLM resolver, and trust-labelled import. Synthetic values."""

import copy
import json

import pymupdf
from test_autoextract import COMPANY, DOCUMENT, PROFIT_LOSS, page, report

from regulation_analyst.autoextract import automap
from regulation_analyst.gates import gate, import_new
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store

GROSS = ["Other income (gross)", "", "4,000", "5,000"]


def statement(path, rows):
    with pymupdf.open() as document:
        page(
            document,
            "Consolidated Statement of Profit and Loss for the year ended March 31, 2025",
            "(In ₹ crore, except per equity share data)",
            rows,
        )
        document.save(path)
    return path


def mapped(tmp_path, rows=None, pdf=None):
    pdf = pdf or statement(tmp_path / "pl.pdf", rows)
    result = automap(pdf, COMPANY, DOCUMENT, tmp_path / "extract")
    (candidate,) = result["candidates"]
    (extraction,) = result["report"]["extractions"]
    return candidate, extraction["extraction"]


def trap_rows():
    rows = list(PROFIT_LOSS)
    rows.insert(2, GROSS)  # Above "Other income, net"; the label rule takes the first match.
    return rows


class Resolver:
    """Controlled model double that re-points line items to given rows."""

    identity = "controlled:resolver"

    def __init__(self, rows):
        self.rows, self.requests = rows, []

    def structured(self, instructions, content, schema, **kwargs):
        request = json.loads(content[0]["text"])
        self.requests.append(request)
        assert content[1]["type"] == "input_image"
        return schema.model_validate(
            {
                "corrections": [
                    {"metric": metric, "row": row, "reason": "Net other income is the line item"}
                    for metric, row in self.rows.items()
                    if metric in request["line_items"]
                ]
            }
        )


def test_clean_statement_passes_every_applicable_gate(tmp_path):
    candidate, extraction = mapped(tmp_path, PROFIT_LOSS)
    result = gate(candidate, extraction=extraction)
    assert result["queued"] == []
    bundle = result["bundle"]
    facts = {f.metric: f for f in bundle.facts}
    assert {f.revision for f in bundle.facts} == {"reported"}  # Comparatives are not imported.
    assert result["comparatives_corroborating"] == len(bundle.facts)
    evidence = {e.id: e for e in bundle.evidence}
    revenue = evidence[facts["revenue"].evidence_id]
    assert revenue.review_method == "automated_extraction"
    assert revenue.checks == ["grounding", "identities", "period_unit", "plausibility"]
    assert "identities" not in evidence[facts["eps_basic"].evidence_id].checks


def test_identity_failure_is_queued_without_a_model(tmp_path):
    candidate, extraction = mapped(tmp_path, trap_rows())
    result = gate(candidate, extraction=extraction)
    queued = {q["metric"] for q in result["queued"]}
    assert queued == {"revenue", "other_income", "total_income"}
    detail = result["queued"][0]["failed"][0]["detail"]
    assert "total_income 166590 ≠ + revenue 162990 + other_income 4000" in detail
    assert "profit_total" in {f.metric for f in result["bundle"].facts}


def test_resolver_repoints_a_row_and_gates_rerun(tmp_path):
    candidate, extraction = mapped(tmp_path, trap_rows())
    rows = json.loads(open(extraction).read())["pages"][0]["tables"][0]["rows"]
    net = next(i for i, row in enumerate(rows) if row[0].startswith("Other income, net"))
    resolver = Resolver({"other_income": net})
    result = gate(candidate, extraction=extraction, provider=resolver)
    assert result["queued"] == []
    assert result["llm_resolved"] == [
        f["id"]
        for f in candidate["bundle"]["facts"]
        if f["metric"] == "other_income" and f["revision"] == "reported"
    ]
    facts = {f.metric: f for f in result["bundle"].facts}
    assert facts["other_income"].raw_value == "3,600"
    evidence = {e.id: e for e in result["bundle"].evidence}
    resolved = evidence[facts["other_income"].evidence_id]
    assert resolved.review_method == "llm_resolved"
    assert resolved.row == "Other income, net"
    assert "row 2 -> 3" in resolved.resolution_note
    assert "identities" in resolved.checks
    assert evidence[facts["revenue"].evidence_id].review_method == "automated_extraction"
    request = resolver.requests[0]
    assert set(request["line_items"]) == {"revenue", "other_income", "total_income"}
    assert "values" not in json.dumps(request["line_items"])


def test_resolver_cannot_rescue_with_heading_rows_or_invented_values(tmp_path):
    candidate, extraction = mapped(tmp_path, trap_rows())
    heading = 5  # "Expenses": no amount in the year column.
    result = gate(candidate, extraction=extraction, provider=Resolver({"other_income": heading}))
    assert {q["metric"] for q in result["queued"]} == {"revenue", "other_income", "total_income"}
    assert result["llm_resolved"] == []


def test_ungrounded_and_implausible_values_are_queued(tmp_path):
    candidate, extraction = mapped(tmp_path, PROFIT_LOSS)
    tampered = copy.deepcopy(candidate)
    for fact in tampered["bundle"]["facts"]:
        if fact["metric"] == "finance_costs" and fact["revision"] == "reported":
            fact["raw_value"] = "417"  # Not what the cited cell prints.
    result = gate(tampered, extraction=extraction)
    (queued,) = result["queued"]
    assert (queued["metric"], queued["failed"][0]["gate"]) == ("finance_costs", "grounding")

    negative = [
        [r[0], r[1], "(4,812)", r[3]] if r[0].startswith("Depreciation") else r for r in PROFIT_LOSS
    ]
    (tmp_path / "neg").mkdir()
    candidate, extraction = mapped(tmp_path / "neg", negative)
    result = gate(candidate, extraction=extraction)
    failures = {q["metric"]: q["failed"][0] for q in result["queued"]}
    assert failures["depreciation_amortisation"]["gate"] == "plausibility"


def test_disagreeing_with_a_reported_figure_blocks_import(tmp_path, synthetic_bundle):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    store.import_bundle(
        synthetic_bundle(
            [{"metric": "revenue", "raw_value": "1,00,000", "company_id": "synthetic"}],
            companies=("synthetic",),
        )
    )
    candidate, extraction = mapped(tmp_path, PROFIT_LOSS)
    result = gate(candidate, extraction=extraction, store=store)
    queued = {q["metric"]: q["failed"] for q in result["queued"]}
    assert queued["revenue"] == [
        {"gate": "cross_document", "detail": "1,62,990 vs reported 100000"}
    ]


def test_import_is_idempotent_and_refuses_changed_records(tmp_path):
    pdf = report(tmp_path / "ar.pdf")
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    candidate, extraction = mapped(tmp_path, pdf=pdf)
    bundle = gate(candidate, extraction=extraction, store=store)["bundle"]
    first = import_new(store, bundle)
    assert first["inserted"] == len(bundle.facts) and first["conflicts"] == []
    assert import_new(store, bundle)["inserted"] == 0

    changed = bundle.model_copy(deep=True)
    fact = changed.facts[0]
    changed.facts[0] = fact.model_copy(update={"raw_value": "1"})
    assert import_new(store, changed)["conflicts"] == [fact.id]

    service = ResearchService(Store(store.path))
    row = service.metric_for_year("synthetic", "ebitda_margin", 2025)
    sources = {f["source"]["trust"] for f in row["facts"]}
    assert sources == {"automated"}
    answer = service.answer_question("Synthetic revenue FY25")
    assert "(unreviewed: automated extraction)" in answer.data["answer"]
    assert (
        service.call(
            "answer_question", question="Synthetic revenue FY25", trust="reviewed_only"
        ).status
        == "not_found"
    )
