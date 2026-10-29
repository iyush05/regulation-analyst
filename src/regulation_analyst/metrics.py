"""Versioned formulas bound to evidence IDs. No eval, SQL, or model arithmetic."""

import hashlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext

from .errors import ResearchError
from .numbers import PRECISION, decimal_text, display, normalize
from .store import Store, canonical

DEFINITIONS = {
    "revenue": "revenue.operations.v1",
    "operating_profit": "operating_profit.excluding_other_income.v1",
    "profit_owners": "profit.attributable_to_owners.v1",
    "profit_total": "profit.including_noncontrolling_interests.v1",
    "equity_owners": "equity.attributable_to_owners.v1",
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
}


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
            else:
                _require(
                    [f.metric for f in facts]
                    == ["profit_owners", "equity_owners", "equity_owners"],
                    "ROE requires owners' profit and opening/closing owners' equity",
                )
                _require(
                    facts[1].period_end == facts[0].period_start - timedelta(days=1)
                    and facts[2].period_end == facts[0].period_end,
                    "ROE equity dates must bracket the profit period",
                )
                average = (values[1] + values[2]) / 2
                _positive(average, "Average equity")
                value = values[0] / average * 100
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
