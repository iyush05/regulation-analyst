from decimal import Decimal
from fractions import Fraction

import pytest

from regulation_analyst.errors import ResearchError
from regulation_analyst.metrics import calculate
from regulation_analyst.numbers import normalize, parse_number


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,62,990", "162990"),
        ("162,990", "162990"),
        ("(1,272)", "-1272"),
        ("−25.50", "-25.50"),
        ("0", "0"),
    ],
)
def test_explicit_financial_numbers(raw, expected):
    assert parse_number(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw", ["—", "-", "", "N/A", "1,2,3", "12,34", "NaN", "Infinity", "1e6", "(-2)", "₹ 100"]
)
def test_missing_and_malformed_numbers_are_not_zero(raw):
    with pytest.raises(ValueError):
        parse_number(raw)


def test_floats_are_not_accepted():
    with pytest.raises(ValueError):
        parse_number(0.1)


@pytest.mark.parametrize(
    "raw,unit",
    [("100", "INR_crore"), ("10,000", "INR_lakh"), ("1,000", "INR_million"), ("1000000000", "INR")],
)
def test_unit_equivalence(raw, unit):
    assert normalize(raw, unit) == Decimal("100")


def test_reported_margin_is_recomputed_from_both_cells(store):
    result = calculate(
        store,
        "operating_margin",
        ["infosys-indas-2025-operating_profit", "infosys-indas-2025-revenue"],
    )
    independent = Fraction(34424, 162990) * 100
    assert abs(Fraction(result["value"]) - independent) < Fraction(1, 10**30)
    assert result["display_value"] == "21.12"
    assert result["inputs"][0]["source"]["locator"]["pdf_page"] == 346
    assert result["input_fact_ids"] == [x["id"] for x in result["inputs"]]


def test_net_margin_rejects_total_profit_instead_of_owners_profit(store):
    with pytest.raises(ResearchError, match="Wrong metric"):
        calculate(
            store, "net_margin", ["infosys-indas-2025-profit_total", "infosys-indas-2025-revenue"]
        )


def test_mixed_accounting_basis_is_rejected(store):
    with pytest.raises(ResearchError, match="accounting basis"):
        calculate(
            store, "net_margin", ["infosys-ifrs-2025-profit_owners", "infosys-indas-2025-revenue"]
        )


def test_wrong_year_denominator_is_rejected(store):
    with pytest.raises(ResearchError, match="same period"):
        calculate(
            store,
            "operating_margin",
            ["infosys-indas-2025-operating_profit", "infosys-indas-2024-revenue"],
        )


def test_cagr_counts_intervals_and_uses_unrounded_values(synthetic_store):
    store = synthetic_store(
        [
            {"id": "old", "metric": "revenue", "fiscal_year": 2023, "raw_value": "100"},
            {"id": "new", "metric": "revenue", "fiscal_year": 2025, "raw_value": "121"},
        ]
    )
    result = calculate(store, "cagr", ["old", "new"])
    assert Decimal(result["value"]) == Decimal("10")
    assert result["elapsed_years"] == 2
    with pytest.raises(ResearchError, match="earlier period"):
        calculate(store, "cagr", ["new", "old"])


@pytest.mark.parametrize("value", ["0", "-100"])
def test_undefined_denominator_abstains(synthetic_store, value):
    store = synthetic_store(
        [
            {"id": "profit", "metric": "operating_profit", "raw_value": "20"},
            {"id": "revenue", "metric": "revenue", "raw_value": value},
        ]
    )
    with pytest.raises(ResearchError) as error:
        calculate(store, "operating_margin", ["profit", "revenue"])
    assert error.value.status == "undefined"


def test_mixed_units_calculate_correctly(synthetic_store):
    store = synthetic_store(
        [
            {
                "id": "profit",
                "metric": "operating_profit",
                "raw_value": "2,500",
                "unit": "INR_lakh",
            },
            {"id": "revenue", "metric": "revenue", "raw_value": "1,000", "unit": "INR_million"},
        ]
    )
    assert calculate(store, "operating_margin", ["profit", "revenue"])["display_value"] == "25.00"


def test_margin_pp_and_basis_points_are_distinct(synthetic_store):
    store = synthetic_store(
        [
            {"id": "p1", "metric": "operating_profit", "fiscal_year": 2024, "raw_value": "22.1"},
            {"id": "r1", "metric": "revenue", "fiscal_year": 2024, "raw_value": "100"},
            {"id": "p2", "metric": "operating_profit", "raw_value": "19.4"},
            {"id": "r2", "metric": "revenue", "raw_value": "100"},
        ]
    )
    assert (
        calculate(store, "margin_change_pp", ["p1", "r1", "p2", "r2"])["display_value"] == "-2.70"
    )
    assert (
        calculate(store, "margin_change_bps", ["p1", "r1", "p2", "r2"])["display_value"]
        == "-270.00"
    )


def test_roe_requires_bracketing_owners_equity(synthetic_store):
    store = synthetic_store(
        [
            {"id": "profit", "metric": "profit_owners", "raw_value": "30"},
            {"id": "opening", "metric": "equity_owners", "fiscal_year": 2024, "raw_value": "100"},
            {"id": "closing", "metric": "equity_owners", "raw_value": "200"},
        ]
    )
    assert calculate(store, "roe", ["profit", "opening", "closing"])["display_value"] == "20.00"
    with pytest.raises(ResearchError, match="bracket"):
        calculate(store, "roe", ["profit", "closing", "opening"])


def test_cross_company_arithmetic_is_rejected(synthetic_store):
    store = synthetic_store(
        [
            {
                "id": "profit",
                "metric": "operating_profit",
                "raw_value": "20",
                "company_id": "alpha",
            },
            {"id": "revenue", "metric": "revenue", "raw_value": "100", "company_id": "beta"},
        ],
        companies=("alpha", "beta"),
    )
    with pytest.raises(ResearchError, match="company"):
        calculate(store, "operating_margin", ["profit", "revenue"])


def test_arbitrary_code_is_not_a_formula(store):
    with pytest.raises(ResearchError, match="Unknown formula"):
        calculate(store, "__import__('os').system('id')", [])
