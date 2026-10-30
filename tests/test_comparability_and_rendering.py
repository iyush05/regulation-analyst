"""Restatement and discontinued-operations warnings, fact tiers, and answer rendering.
All values are synthetic."""

from decimal import Decimal

import pytest

from regulation_analyst.agent import FinishArgs, Ledger, Selection
from regulation_analyst.models import Bundle, Evidence
from regulation_analyst.numbers import indian
from regulation_analyst.render import change_text, value_text
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


def automated(bundle: Bundle, reporting_year: int) -> Bundle:
    """Relabel a synthetic bundle as pipeline output from the given year's report."""
    evidence = [
        Evidence.model_validate(
            e.model_dump()
            | {"review_method": "automated_extraction", "reviewer": "test", "checks": ["grounding"]}
        )
        for e in bundle.evidence
    ]
    documents = [
        d.model_copy(
            update={
                "reporting_year": reporting_year,
                "url": f"https://example.org/report-{reporting_year}.pdf",
            }
        )
        for d in bundle.documents
    ]
    return bundle.model_copy(update={"evidence": evidence, "documents": documents})


@pytest.fixture
def restated(tmp_path, synthetic_bundle):
    """FY24 as originally reported; the FY25 report restates FY24 and has discontinued ops."""
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    fy24 = [
        {"id": "r24-revenue", "metric": "revenue", "raw_value": "1,000", "fiscal_year": 2024},
        {"id": "r24-profit", "metric": "profit_owners", "raw_value": "100", "fiscal_year": 2024},
    ]
    fy25 = [
        {"id": "r25-revenue", "metric": "revenue", "raw_value": "1,100"},
        {"id": "r25-profit", "metric": "profit_owners", "raw_value": "121"},
        {"id": "r25-disc", "metric": "profit_discontinued", "raw_value": "11"},
        {
            "id": "c24-revenue",
            "metric": "revenue",
            "raw_value": "950",
            "fiscal_year": 2024,
            "revision": "comparative",
        },
        {
            "id": "c23-equity",
            "metric": "equity_owners",
            "raw_value": "400",
            "fiscal_year": 2023,
            "revision": "comparative",
        },
    ]
    store.import_bundle(automated(synthetic_bundle(fy24, document_id="ar24"), 2024))
    # Imported second on purpose: warnings must not depend on import order.
    store.import_bundle(automated(synthetic_bundle(fy25, document_id="ar25"), 2025))
    return ResearchService(Store(store.path))


def test_own_report_outranks_comparatives_which_only_fill_gaps(restated):
    store = restated.store
    assert store.select_fact("alpha", "revenue", 2024).id == "r24-revenue"
    assert store.select_fact("alpha", "equity_owners", 2023).id == "c23-equity"


def test_restatement_and_discontinued_operations_warn(restated):
    fy24 = restated.metric_for_year("alpha", "net_margin", 2024)
    assert [w["kind"] for w in fy24["calculation"]["warnings"]] == ["restated"]
    assert "restated as 950 crore" in fy24["calculation"]["warnings"][0]["text"]

    fy25 = restated.metric_for_year("alpha", "net_margin", 2025)
    kinds = [w["kind"] for w in fy25["calculation"]["warnings"]]
    assert kinds == ["includes_discontinued", "continuing_only", "mixed_basis"]
    assert (
        "includes 11 crore profit from discontinued operations"
        in (fy25["calculation"]["warnings"][0]["text"])
    )


def test_ask_answer_shows_warnings_sources_once_and_specific_gaps(restated):
    answer = restated.answer_question("alpha net margin change FY24 to FY25").data["answer"]
    assert "| alpha | net margin | 10.00% [1] | 11.00% [2] |" in answer
    assert "- alpha FY24→FY25: 1.00 pp (margin change pp)" in answer
    assert "**Warnings**" in answer and "not comparable" in answer
    assert answer.count("](https://example.org/report-2024.pdf#page=2)") == 1

    gaps = restated.answer_question("alpha operating margin FY25").data["answer"]
    assert "No consolidated Ind AS operating_profit for alpha FY2025" in gaps


def test_agent_summary_table_has_change_column_and_gap_reasons(restated):
    store = restated.store
    ledger = Ledger(store, Selection(), {"alpha"}, [2024, 2025])
    ids = []
    for _year, revenue, profit in (
        (2024, "r24-revenue", "r24-profit"),
        (2025, "r25-revenue", "r25-profit"),
    ):
        result = restated.call("calculate", formula="net_margin", fact_ids=[profit, revenue])
        ledger.absorb(result.model_dump(mode="json")["data"])
        ids.append(result.data["calculation"]["id"])
    table = restated.call("get_table", company="alpha", years=["FY25"], metrics=["finance_costs"])
    ledger.absorb(table.model_dump(mode="json")["data"])
    rendered = ledger.render(
        FinishArgs(fact_ids=[], calculation_ids=ids, passage_ids=[], provision_ids=[], gaps=[])
    )["answer"]
    assert "| Company | Measure | FY24 | FY25 | Change FY24→FY25 |" in rendered
    assert "| alpha | net margin | 10.00% [1] | 11.00% [2] | +1.00 pp |" in rendered
    assert "- No consolidated Ind AS finance_costs for alpha FY2025" in rendered
    assert "restated as 950 crore" in rendered


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        ("439695", "INR_crore", "₹4,39,695 cr"),
        ("-3851.64", "INR_crore", "₹-3,851.64 cr"),
        ("6.3293", "percent", "6.33%"),
        ("0.538", "times", "0.54x"),
        ("64.5", "INR_per_share", "₹64.50/share"),
    ],
)
def test_value_formatting(value, unit, text):
    assert value_text(value, unit) == text


def test_changes_and_indian_grouping():
    assert change_text("7.17", "6.33", "percent") == "-0.84 pp"
    assert change_text("1.16", "0.54", "times") == "-0.62x"
    assert change_text("100", "125", "INR_crore") == "+25.00%"
    assert change_text("5", "5", "percent") == "0.00 pp"
    assert indian(Decimal("1234567890.5")) == "1,23,45,67,890.50"


def test_calculated_measures_are_explained_not_reported_missing(tmp_path, synthetic_bundle):
    from test_expanded_metrics import rows

    store = Store(tmp_path / "e.sqlite3", readonly=False)
    store.import_bundle(synthetic_bundle(rows()))
    service = ResearchService(Store(store.path))
    table = service.call(
        "get_table", company="alpha", years=["FY25"], metrics=["ebitda", "finance_costs"]
    )
    assert table.status == "ok" and table.data["missing"] == []
    (note,) = table.data["derived"]
    assert "ebitda is calculated, not reported" in note["note"]
    assert "'profit_before_tax', 'finance_costs', 'other_income'" in note["note"]

    ledger = Ledger(service.store, Selection(), {"alpha"}, [2025])
    # A stale gap, as when a model first asked for EBITDA as if it were printed.
    ledger.absorb({"missing": [{"metric": "ebitda", "fiscal_year": 2025, "reason": "No ebitda"}]})
    inputs = ["profit_before_tax", "finance_costs", "other_income", "depreciation_amortisation"]
    ids = [f"alpha-{m}-2025" for m in inputs]
    calc = service.call("calculate", formula="ebitda", fact_ids=ids)
    ledger.absorb(
        service.call("get_table", company="alpha", years=["FY25"], metrics=inputs).model_dump(
            mode="json"
        )["data"]
    )
    ledger.absorb(calc.model_dump(mode="json")["data"])
    rendered = ledger.render(
        FinishArgs(
            fact_ids=ids,
            calculation_ids=[calc.data["calculation"]["id"]],
            passage_ids=[],
            provision_ids=[],
            gaps=["missing_financial_data"],
        )
    )["answer"]
    assert "| alpha | ebitda | ₹210 cr [1] |" in rendered
    assert (
        "Method: ebitda = profit_before_tax + finance_costs - other_income + "
        "depreciation_amortisation. Calculated by the system from reported figures"
    ) in rendered
    assert "Gaps" not in rendered
