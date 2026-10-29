from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from regulation_analyst.errors import ResearchError
from regulation_analyst.metrics import DEFINITIONS, calculate
from regulation_analyst.models import REPORTED_METRICS, Fact
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store

# Synthetic values, unrelated to any real company.
FY25 = {
    "revenue": "1000",
    "other_income": "50",
    "profit_before_tax": "200",
    "finance_costs": "20",
    "depreciation_amortisation": "40",
    "profit_owners": "150",
    "operating_cash_flow": "180",
    "capex": "60",
    "borrowings_current": "30",
    "borrowings_noncurrent": "70",
    "equity_owners": "500",
    "total_assets": "900",
    "current_assets": "400",
    "current_liabilities": "250",
}


def rows(company="alpha", year=2025, values=FY25, prefix=""):
    return [
        {
            "id": f"{prefix}{company}-{metric}-{year}",
            "company_id": company,
            "fiscal_year": year,
            "metric": metric,
            "raw_value": raw,
        }
        for metric, raw in values.items()
    ]


@pytest.fixture
def expanded(tmp_path, synthetic_bundle):
    data = rows() + rows(year=2024, values={"profit_owners": "120", "equity_owners": "400"})
    data += rows(year=2023, values={"equity_owners": "300"})
    data += [
        {"id": "alpha-eps-2025", "metric": "eps_basic", "raw_value": "12.50"},
        {"id": "alpha-eps-2024", "metric": "eps_basic", "raw_value": "10.00", "fiscal_year": 2024},
    ]
    for row in data:
        if row["metric"] == "eps_basic":
            row["unit"] = "INR_per_share"
    writer = Store(tmp_path / "expanded.sqlite3", readonly=False)
    writer.import_bundle(synthetic_bundle(data))
    return ResearchService(Store(writer.path))


def exact(value: str) -> Fraction:
    return Fraction(Decimal(value))


@pytest.mark.parametrize(
    "metric,expected,unit",
    [
        ("operating_profit_derived", Fraction(170), "INR_crore"),
        ("operating_margin_derived", Fraction(17), "percent"),
        ("ebitda", Fraction(210), "INR_crore"),
        ("ebitda_margin", Fraction(21), "percent"),
        ("debt_to_equity", Fraction(1, 5), "times"),
        ("roce", Fraction(220, 650) * 100, "percent"),
        ("interest_coverage", Fraction(11), "times"),
        ("free_cash_flow", Fraction(120), "INR_crore"),
        ("current_ratio", Fraction(8, 5), "times"),
        ("net_margin", Fraction(15), "percent"),
        ("roe", Fraction(150, 450) * 100, "percent"),
    ],
)
def test_derived_measures_match_independent_fractions(expanded, metric, expected, unit):
    row = expanded.metric_for_year("alpha", metric, 2025)
    assert row["unit"] == unit
    assert abs(exact(row["value"]) - expected) < Fraction(1, 10**25)
    assert row["calculation"]["input_fact_ids"] == [f["id"] for f in row["facts"]]


def test_operating_margin_falls_back_to_uniform_derivation(expanded):
    row = expanded.metric_for_year("alpha", "operating_margin", 2025)
    assert row["definition"] == "operating_margin_derived.v1"
    assert exact(row["value"]) == 17
    with pytest.raises(ResearchError, match="not an alternative"):
        expanded.metric_for_year("alpha", "net_margin", 2025, variant="ebitda")


def test_comparison_realigns_mixed_operating_profit_definitions(tmp_path, synthetic_bundle):
    beta = dict(FY25, operating_profit="180", revenue="900")
    data = rows() + rows(company="beta", values=beta)
    writer = Store(tmp_path / "compare.sqlite3", readonly=False)
    writer.import_bundle(synthetic_bundle(data, companies=("alpha", "beta")))
    service = ResearchService(Store(writer.path))

    # Alone, beta uses its reported operating profit.
    alone = service.metric_for_year("beta", "operating_margin", 2025)
    assert alone["definition"] == "operating_margin.v1"
    assert exact(alone["value"]) == 20

    result = service.compare_companies("operating_margin", ["alpha", "beta"], ["FY25"])
    assert result.status == "ok"
    assert {r["definition"] for r in result.data["rows"]} == {"operating_margin_derived.v1"}
    values = {r["company_id"]: exact(r["value"]) for r in result.data["rows"]}
    assert values["alpha"] == 17
    assert abs(values["beta"] - Fraction(170, 900) * 100) < Fraction(1, 10**25)


def test_per_share_values_keep_their_dimension(expanded):
    row = expanded.metric_for_year("alpha", "eps_basic", 2025)
    assert (row["value"], row["unit"]) == ("12.50", "INR_per_share")
    answer = expanded.answer_question("alpha EPS FY25")
    assert answer.status == "ok"
    assert "12.50 INR per share" in answer.data["answer"]
    growth = expanded.answer_question("alpha EPS growth FY24 to FY25")
    assert growth.data["changes"][0]["calculation"]["display_value"] == "25.00"


def test_roe_change_is_calculated_from_six_facts(expanded):
    result = expanded.answer_question("alpha ROE change FY24 to FY25")
    assert result.status == "ok"
    calc = result.data["changes"][0]["calculation"]
    assert calc["formula_id"] == "roe_change_pp.v1"
    assert len(calc["input_fact_ids"]) == 6
    expected = Fraction(150, 450) * 100 - Fraction(120, 350) * 100
    assert abs(exact(calc["value"]) - expected) < Fraction(1, 10**25)
    assert calc["unit"] == "percentage_points"


def test_ratio_answers_render_units(expanded):
    answer = expanded.answer_question("alpha debt to equity FY25")
    assert "| FY2025 | 0.20x |" in answer.data["answer"]
    margin = expanded.answer_question("alpha EBITDA margin FY25")
    assert "| FY2025 | 21.00% |" in margin.data["answer"]
    cagr = expanded.call("answer_question", question="alpha EBITDA CAGR FY24 to FY25")
    assert cagr.status == "out_of_scope"


def ids(service, year, *metrics):
    return [f"alpha-{m}-{year}" for m in metrics]


def test_formula_inputs_are_checked(expanded):
    store = expanded.store
    with pytest.raises(ResearchError, match="in that order"):
        calculate(store, "interest_coverage", ids(expanded, 2025, "finance_costs", "revenue"))
    with pytest.raises(ResearchError, match="same fiscal year"):
        calculate(
            store,
            "debt_to_equity",
            [
                "alpha-borrowings_current-2025",
                "alpha-borrowings_noncurrent-2025",
                "alpha-equity_owners-2024",
            ],
        )
    with pytest.raises(ResearchError, match="expects 4"):
        calculate(store, "ebitda", ids(expanded, 2025, "revenue"))


def test_zero_or_negative_denominators_are_undefined(tmp_path, synthetic_bundle):
    data = rows(values=dict(FY25, finance_costs="0", capex="(5)"))
    writer = Store(tmp_path / "zero.sqlite3", readonly=False)
    writer.import_bundle(synthetic_bundle(data))
    service = ResearchService(Store(writer.path))
    with pytest.raises(ResearchError) as error:
        service.metric_for_year("alpha", "interest_coverage", 2025)
    assert error.value.status == "undefined"
    with pytest.raises(ResearchError, match="non-negative outflow"):
        service.metric_for_year("alpha", "free_cash_flow", 2025)


def fact(**overrides):
    base = dict(
        id="f",
        company_id="alpha",
        metric="revenue",
        definition=DEFINITIONS["revenue"],
        fiscal_year=2025,
        period_start=date(2024, 4, 1),
        period_end=date(2025, 3, 31),
        basis="Ind AS",
        raw_value="1",
        unit="INR_crore",
        evidence_id="e",
    )
    return Fact(**(base | overrides))


def test_fact_units_and_periods_follow_the_metric_catalogue():
    assert fact(metric="eps_diluted", unit="INR_per_share").unit == "INR_per_share"
    with pytest.raises(ValidationError, match="Per-share"):
        fact(metric="eps_basic")
    with pytest.raises(ValidationError, match="Per-share"):
        fact(unit="INR_per_share")
    with pytest.raises(ValidationError, match="instant"):
        fact(metric="total_assets")
    assert fact(metric="total_assets", period_kind="instant", period_start=None)


def test_registry_lists_every_reported_metric(expanded):
    data = expanded.list_metrics().data
    assert set(data["reported_metrics"]) == set(REPORTED_METRICS) == set(DEFINITIONS)
    assert data["derived_metrics"]["roe"]["year_offsets"] == [0, -1, 0]
    assert data["fallbacks"] == {"operating_margin": "operating_margin_derived"}
