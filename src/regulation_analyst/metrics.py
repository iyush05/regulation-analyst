"""Versioned formulas bound to evidence IDs. No eval, SQL, or model arithmetic."""

import hashlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .errors import ResearchError
from .numbers import PRECISION, decimal_text, display, normalize
from .store import Store, canonical

DEFINITIONS = {
    "revenue": "revenue.operations.v1",
    "other_income": "income.other.v1",
    "total_income": "income.total.v1",
    "operating_profit": "operating_profit.excluding_other_income.v1",
    "finance_costs": "expense.finance_costs.v1",
    "depreciation_amortisation": "expense.depreciation_amortisation_impairment.v1",
    "profit_before_tax": "profit.before_tax.v1",
    "tax_expense": "expense.tax_total.v1",
    "profit_owners": "profit.attributable_to_owners.v1",
    "profit_total": "profit.including_noncontrolling_interests.v1",
    "eps_basic": "eps.basic.v1",
    "eps_diluted": "eps.diluted.v1",
    "operating_cash_flow": "cash_flow.net_from_operating_activities.v1",
    # Stored as the positive magnitude of purchases of PPE and intangible assets.
    "capex": "capex.purchase_ppe_intangibles_outflow.v1",
    "equity_owners": "equity.attributable_to_owners.v1",
    "non_controlling_interest": "equity.non_controlling_interests.v1",
    "total_assets": "assets.total.v1",
    "current_assets": "assets.current_total.v1",
    "current_liabilities": "liabilities.current_total.v1",
    "borrowings_current": "borrowings.current.v1",
    "borrowings_noncurrent": "borrowings.noncurrent.v1",
    "cash_and_equivalents": "cash.and_cash_equivalents.v1",
}
FORMULAS = {
    "operating_margin": {
        "inputs": ["operating_profit", "revenue"],
        "formula": "operating_profit / revenue * 100",
        "unit": "percent",
    },
    "net_margin": {
        "inputs": ["profit_owners", "revenue"],
        "formula": "profit_owners / revenue * 100",
        "unit": "percent",
    },
    "growth_percent": {
        "inputs": ["earlier", "later"],
        "formula": "(later / earlier - 1) * 100",
        "unit": "percent",
    },
    "cagr": {
        "inputs": ["earlier", "later"],
        "formula": "((later / earlier) ** (1 / elapsed_years) - 1) * 100",
        "unit": "percent",
    },
    "margin_change_pp": {
        "inputs": ["earlier_profit", "earlier_revenue", "later_profit", "later_revenue"],
        "formula": "(later_profit / later_revenue - earlier_profit / earlier_revenue) * 100",
        "unit": "percentage_points",
    },
    "margin_change_bps": {
        "inputs": ["earlier_profit", "earlier_revenue", "later_profit", "later_revenue"],
        "formula": "(later_profit / later_revenue - earlier_profit / earlier_revenue) * 10000",
        "unit": "basis_points",
    },
    "roe": {
        "inputs": ["profit_owners", "opening_equity", "closing_equity"],
        "formula": "profit_owners / ((opening_equity + closing_equity) / 2) * 100",
        "unit": "percent",
    },
    "roe_change_pp": {
        "inputs": [
            "earlier_profit",
            "earlier_opening_equity",
            "earlier_closing_equity",
            "later_profit",
            "later_opening_equity",
            "later_closing_equity",
        ],
        "formula": "later_roe - earlier_roe (each profit_owners / average owners' equity) * 100",
        "unit": "percentage_points",
    },
}
# Same-year measures over reported line items. Input names are the required metrics, in order.
# Operating profit here excludes other income and is derived identically for every company;
# exceptional items remain inside profit before tax.
SAME_YEAR = {
    "operating_profit_derived": (
        ["profit_before_tax", "finance_costs", "other_income"],
        "profit_before_tax + finance_costs - other_income",
        "INR_crore",
        lambda v: v["profit_before_tax"] + v["finance_costs"] - v["other_income"],
        [],
    ),
    "operating_margin_derived": (
        ["profit_before_tax", "finance_costs", "other_income", "revenue"],
        "(profit_before_tax + finance_costs - other_income) / revenue * 100",
        "percent",
        lambda v: (
            (v["profit_before_tax"] + v["finance_costs"] - v["other_income"]) / v["revenue"] * 100
        ),
        ["revenue"],
    ),
    "ebitda": (
        ["profit_before_tax", "finance_costs", "other_income", "depreciation_amortisation"],
        "profit_before_tax + finance_costs - other_income + depreciation_amortisation",
        "INR_crore",
        lambda v: (
            v["profit_before_tax"]
            + v["finance_costs"]
            - v["other_income"]
            + v["depreciation_amortisation"]
        ),
        [],
    ),
    "ebitda_margin": (
        [
            "profit_before_tax",
            "finance_costs",
            "other_income",
            "depreciation_amortisation",
            "revenue",
        ],
        "(profit_before_tax + finance_costs - other_income + depreciation_amortisation)"
        " / revenue * 100",
        "percent",
        lambda v: (
            (
                v["profit_before_tax"]
                + v["finance_costs"]
                - v["other_income"]
                + v["depreciation_amortisation"]
            )
            / v["revenue"]
            * 100
        ),
        ["revenue"],
    ),
    "debt_to_equity": (
        ["borrowings_current", "borrowings_noncurrent", "equity_owners"],
        "(borrowings_current + borrowings_noncurrent) / equity_owners",
        "times",
        lambda v: (v["borrowings_current"] + v["borrowings_noncurrent"]) / v["equity_owners"],
        ["equity_owners"],
    ),
    "roce": (
        ["profit_before_tax", "finance_costs", "total_assets", "current_liabilities"],
        "(profit_before_tax + finance_costs) / (total_assets - current_liabilities) * 100",
        "percent",
        lambda v: (
            (v["profit_before_tax"] + v["finance_costs"])
            / (v["total_assets"] - v["current_liabilities"])
            * 100
        ),
        [],
    ),
    "interest_coverage": (
        ["profit_before_tax", "finance_costs"],
        "(profit_before_tax + finance_costs) / finance_costs",
        "times",
        lambda v: (v["profit_before_tax"] + v["finance_costs"]) / v["finance_costs"],
        ["finance_costs"],
    ),
    "free_cash_flow": (
        ["operating_cash_flow", "capex"],
        "operating_cash_flow - capex",
        "INR_crore",
        lambda v: v["operating_cash_flow"] - v["capex"],
        [],
    ),
    "current_ratio": (
        ["current_assets", "current_liabilities"],
        "current_assets / current_liabilities",
        "times",
        lambda v: v["current_assets"] / v["current_liabilities"],
        ["current_liabilities"],
    ),
}
for _name, (_inputs, _formula, _unit, _, _) in SAME_YEAR.items():
    FORMULAS[_name] = {"inputs": _inputs, "formula": _formula, "unit": _unit}
# Single-year measures that metric_for_year can answer: formula -> (input metrics, year offsets).
DERIVED_METRICS = {
    "operating_margin": (["operating_profit", "revenue"], [0, 0]),
    "net_margin": (["profit_owners", "revenue"], [0, 0]),
    "roe": (["profit_owners", "equity_owners", "equity_owners"], [0, -1, 0]),
    **{name: (spec[0], [0] * len(spec[0])) for name, spec in SAME_YEAR.items()},
}
# Reported operating profit definitions differ between companies; this is the uniform fallback.
FALLBACKS = {"operating_margin": "operating_margin_derived"}


def _require(condition, message):
    if not condition:
        raise ResearchError("invalid_request", message)


def _positive(value: Decimal, label: str):
    if value <= 0:
        raise ResearchError("undefined", f"{label} must be positive for this metric definition")


def calculate(store: Store, formula: str, fact_ids: list[str]) -> dict:
    if formula not in FORMULAS:
        raise ResearchError(
            "invalid_request", f"Unknown formula; choose from {', '.join(FORMULAS)}"
        )
    spec = FORMULAS[formula]
    _require(
        len(fact_ids) == len(spec["inputs"]),
        f"{formula} expects {len(spec['inputs'])} ordered fact IDs",
    )
    facts = [store.record("facts", fact_id) for fact_id in fact_ids]
    _require(
        len({(f.company_id, f.scope, f.basis) for f in facts}) == 1,
        "Calculation inputs must share company, scope, and accounting basis",
    )
    for fact in facts:
        _require(
            fact.definition == DEFINITIONS[fact.metric],
            f"Unsupported metric definition: {fact.definition}",
        )
    values = [normalize(f.raw_value, f.unit) for f in facts]
    elapsed = None

    def margin_pair(profit, revenue, p_value, r_value):
        _require(
            profit.metric in ("operating_profit", "profit_owners") and revenue.metric == "revenue",
            "A margin requires operating profit or owners' profit, followed by revenue",
        )
        _require(
            (profit.period_start, profit.period_end) == (revenue.period_start, revenue.period_end),
            "Margin numerator and denominator must cover the same period",
        )
        _positive(r_value, "Revenue")
        return p_value / r_value

    def ordered_periods(earlier, later):
        _require(
            earlier.period_end < later.period_end,
            "Supply the earlier period before the later period",
        )
        _require(
            (earlier.period_end.month, earlier.period_end.day)
            == (later.period_end.month, later.period_end.day),
            "Fiscal year ends must align",
        )

    def roe(triple, amounts):
        _require(
            [f.metric for f in triple] == ["profit_owners", "equity_owners", "equity_owners"],
            "ROE requires owners' profit and opening/closing owners' equity",
        )
        _require(
            triple[1].period_end == triple[0].period_start - timedelta(days=1)
            and triple[2].period_end == triple[0].period_end,
            "ROE equity dates must bracket the profit period",
        )
        average = (amounts[1] + amounts[2]) / 2
        _positive(average, "Average equity")
        return amounts[0] / average * 100

    def same_year(items):
        flows = {(f.period_start, f.period_end) for f in items if f.period_kind == "annual"}
        ends = {f.period_end for f in items}
        _require(
            len(flows) <= 1 and len(ends) == 1,
            "Inputs must cover the same fiscal year; balances are taken at its end",
        )

    with localcontext() as ctx:
        ctx.prec = PRECISION
        try:
            if formula in ("operating_margin", "net_margin"):
                _require(
                    [f.metric for f in facts] == spec["inputs"],
                    "Wrong metric inputs for the requested margin",
                )
                value = margin_pair(*facts, *values) * 100
            elif formula in ("growth_percent", "cagr"):
                _require(facts[0].metric == facts[1].metric, "Growth must compare the same metric")
                ordered_periods(*facts)
                elapsed = facts[1].fiscal_year - facts[0].fiscal_year
                _positive(values[0], "Starting value")
                if formula == "cagr":
                    _positive(values[1], "Ending value")
                    value = ((values[1] / values[0]) ** (Decimal(1) / elapsed) - 1) * 100
                else:
                    value = (values[1] / values[0] - 1) * 100
            elif formula.startswith("margin_change"):
                _require(
                    facts[0].metric == facts[2].metric,
                    "Both margins must use the same profit definition",
                )
                ordered_periods(facts[0], facts[2])
                old = margin_pair(facts[0], facts[1], values[0], values[1])
                new = margin_pair(facts[2], facts[3], values[2], values[3])
                value = (new - old) * (10000 if formula.endswith("bps") else 100)
            elif formula == "roe":
                value = roe(facts, values)
            elif formula == "roe_change_pp":
                ordered_periods(facts[0], facts[3])
                value = roe(facts[3:], values[3:]) - roe(facts[:3], values[:3])
            else:
                inputs, _, _, compute, positive = SAME_YEAR[formula]
                _require(
                    [f.metric for f in facts] == inputs,
                    f"{formula} requires {', '.join(inputs)} in that order",
                )
                same_year(facts)
                named = dict(zip(inputs, values, strict=True))
                for label in positive:
                    _positive(named[label], label.replace("_", " ").capitalize())
                if formula == "free_cash_flow":
                    _require(named["capex"] >= 0, "Capex is stored as a non-negative outflow")
                if formula == "roce":
                    _positive(
                        named["total_assets"] - named["current_liabilities"], "Capital employed"
                    )
                value = compute(named)
        except (InvalidOperation, OverflowError) as exc:
            raise ResearchError(
                "undefined", "Calculation exceeds supported decimal precision"
            ) from exc
    payload = {
        "formula_id": formula + ".v1",
        "formula": spec["formula"],
        "input_fact_ids": fact_ids,
        "inputs": [
            {"name": name, **store.fact_data(fact)}
            for name, fact in zip(spec["inputs"], facts, strict=True)
        ],
        "value": decimal_text(value),
        "display_value": display(value),
        "unit": spec["unit"],
        "precision_digits": PRECISION,
        "rounding": "ROUND_HALF_UP; display only, 2 decimal places",
        "elapsed_years": elapsed,
        "corpus_version": store.version,
    }
    return {"id": "calc:" + hashlib.sha256(canonical(payload).encode()).hexdigest()[:24], **payload}
