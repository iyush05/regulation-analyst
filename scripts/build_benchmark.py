"""Author development labels with Decimal formulas independent of production metrics.

These systematically varied fact/period/formula cases are correlated. They are not
an independently reviewed held-out set and must not be described as one.
"""

import json
from decimal import Decimal, localcontext
from itertools import combinations
from pathlib import Path

from regulation_analyst.experiments import Benchmark

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "src/regulation_analyst/fixtures"
records = [
    json.loads((FIXTURES / name).read_text()) for name in ("demo.json", "research-expansion.json")
]
facts = {f["id"]: f for bundle in records for f in bundle["facts"]}
lookup = {(f["company_id"], f["basis"], f["fiscal_year"], f["metric"]): f for f in facts.values()}
cases = []
labels = {
    "revenue": "revenue",
    "operating_profit": "operating profit",
    "profit_owners": "net profit",
    "profit_total": "profit including non-controlling interests",
    "equity_owners": "equity attributable to owners",
    "net_margin": "net margin",
    "operating_margin": "operating margin",
    "roe": "return on equity",
}


def number(fid):
    return Decimal(facts[fid]["raw_value"].replace(",", ""))


def fact_gold(fact):
    return {
        "id": fact["id"],
        "value": str(number(fact["id"])),
        "unit": "INR_crore",
        "fact_id": fact["id"],
        "evidence_ids": [fact["evidence_id"]],
        "derivation": "Direct source-cell transcription in INR crore",
        "tolerance": "0",
    }


def calc_gold(formula, ids, elapsed=None):
    values = [number(fid) for fid in ids]
    with localcontext() as context:
        context.prec = 50
        if formula in ("net_margin", "operating_margin"):
            value = values[0] * Decimal(100) / values[1]
            derivation = f"{values[0]} * 100 / {values[1]}"
        elif formula == "roe":
            value = values[0] * 200 / (values[1] + values[2])
            derivation = f"{values[0]} * 200 / ({values[1]} + {values[2]})"
        elif formula == "growth_percent":
            value = (values[1] - values[0]) * 100 / values[0]
            derivation = f"({values[1]} - {values[0]}) * 100 / {values[0]}"
        elif formula == "cagr":
            value = ((values[1] / values[0]).ln() / Decimal(elapsed)).exp() * 100 - 100
            derivation = f"100 * exp(ln({values[1]} / {values[0]}) / {elapsed}) - 100"
        else:
            value = 100 * (values[2] * values[1] - values[0] * values[3]) / (values[3] * values[1])
            derivation = (
                f"100 * ({values[2]} * {values[1]} - {values[0]} * {values[3]}) / "
                f"({values[3]} * {values[1]})"
            )
    return {
        "id": formula + ":" + ":".join(ids),
        "value": str(value),
        "unit": "percentage_points" if formula == "margin_change_pp" else "percent",
        "formula": formula,
        "input_fact_ids": ids,
        "evidence_ids": [facts[fid]["evidence_id"] for fid in ids],
        "derivation": derivation,
        "tolerance": "0.01",
    }


def add(question, category, gold=None, companies=None, basis="Ind AS", status="ok", **extra):
    cases.append(
        {
            "id": f"research-{len(cases) + 1:03d}",
            "question": question,
            "category": category,
            "split": "development",
            "source_group": "small-corpus-connected-source-group",
            "review_status": "source_crosschecked",
            "reviewer": "coding-assistant; independent review pending",
            "expected_status": status,
            "answerable": status in ("ok", "partial"),
            "selection": {"basis": basis},
            "company_ids": companies or [],
            "gold_numbers": gold or [],
            "notes": "Development label; not independently reviewed. "
            "Related source/period cases are correlated.",
            **extra,
        }
    )


for fact in facts.values():
    add(
        f"What was {fact['company_id']} {labels[fact['metric']]} "
        f"FY{fact['fiscal_year']} under {fact['basis']}?",
        "fact_lookup",
        [fact_gold(fact)],
        [fact["company_id"]],
        fact["basis"],
    )

ratio_series = {}
for company, basis in sorted({(f["company_id"], f["basis"]) for f in facts.values()}):
    for year in (2023, 2024, 2025):
        for metric, profit in (
            ("net_margin", "profit_owners"),
            ("operating_margin", "operating_profit"),
            ("roe", "profit_owners"),
        ):
            keys = [(company, basis, year, profit), (company, basis, year, "revenue")]
            if metric == "roe":
                keys = [
                    (company, basis, year, profit),
                    (company, basis, year - 1, "equity_owners"),
                    (company, basis, year, "equity_owners"),
                ]
            if not all(key in lookup for key in keys):
                continue
            ids = [lookup[key]["id"] for key in keys]
            gold = calc_gold(metric, ids)
            ratio_series[company, basis, year, metric] = gold
            add(
                f"Calculate {company} {labels[metric]} FY{year} under {basis}.",
                "numeric_calculation",
                [gold],
                [company],
                basis,
            )
    for metric in labels:
        covered = [year for year in (2023, 2024, 2025) if (company, basis, year, metric) in lookup]
        for earlier, later in combinations(covered, 2):
            endpoints = [lookup[company, basis, y, metric] for y in (earlier, later)]
            for formula in ("growth_percent", "cagr"):
                gold = [fact_gold(f) for f in endpoints] + [
                    calc_gold(formula, [f["id"] for f in endpoints], later - earlier)
                ]
                add(
                    f"{company} {labels[metric]} {'CAGR' if formula == 'cagr' else 'growth'} "
                    f"between FY{earlier} and FY{later} under {basis}.",
                    "numeric_calculation",
                    gold,
                    [company],
                    basis,
                )
    for metric in ("net_margin", "operating_margin"):
        covered = [
            year for year in (2023, 2024, 2025) if (company, basis, year, metric) in ratio_series
        ]
        for earlier, later in combinations(covered, 2):
            endpoints = [ratio_series[company, basis, y, metric] for y in (earlier, later)]
            ids = [fid for gold in endpoints for fid in gold["input_fact_ids"]]
            add(
                f"How did {company} {labels[metric]} change "
                f"between FY{earlier} and FY{later} under {basis}?",
                "multi_document",
                endpoints + [calc_gold("margin_change_pp", ids)],
                [company],
                basis,
            )

for metric in ("revenue", "profit_owners", "profit_total", "equity_owners", "net_margin", "roe"):
    for year in (2023, 2024, 2025):
        keys = [(company, "Ind AS", year, metric) for company in ("infosys", "tcs")]
        pool = ratio_series if metric in ("net_margin", "roe") else lookup
        if all(key in pool for key in keys):
            gold = [pool[key] if pool is ratio_series else fact_gold(pool[key]) for key in keys]
            add(
                f"Compare Infosys and TCS {labels[metric]} FY{year}.",
                "multi_document",
                gold,
                ["infosys", "tcs"],
            )

challenges = [
    ("Infosys EBITDA margin FY25", "out_of_scope"),
    ("Infosys EPS FY25", "out_of_scope"),
    ("Infosys quarterly revenue FY25", "out_of_scope"),
    ("Infosys revenue forecast FY26", "out_of_scope"),
    ("Should I buy Infosys?", "out_of_scope"),
    ("Should I sell TCS?", "out_of_scope"),
    ("Infosys price target FY25", "out_of_scope"),
    ("Infosys revenue", "ambiguous"),
    ("Infosys operating margin FY25 to FY23", "invalid_request"),
    ("Infosys revenue FY25 and FY24 under US GAAP", "out_of_scope"),
    ("UncoveredCompany revenue FY25", "not_found"),
    ("HCLTech revenue FY25", "not_found"),
    ("Infosys standalone revenue FY25", "not_found"),
    ("TCS operating margin FY25", "not_found"),
    ("Infosys revenue FY19", "not_found"),
    ("Infosys return on equity FY23", "not_found"),
    ("TCS return on equity FY23", "not_found"),
    ("Infosys net margin CAGR FY23 to FY25", "out_of_scope"),
    ("RBI KYC commencement", "ambiguous"),
    ("RBI KYC commencement as of 2026-10-27", "not_found"),
    ("SEBI material event deadlines as of 2026-10-27", "not_found"),
]
for question, status in challenges:
    add(question, "challenge", status=status)

add(
    "Infosys operating margin FY25 and management explanation",
    "multi_document",
    [ratio_series["infosys", "Ind AS", 2025, "operating_margin"]],
    ["infosys"],
    gold_evidence_ids=["ev-infosys-call25-margin"],
    required_claims=[
        "Management's explanation is attributed to the CFO "
        "and does not imply independent causal proof."
    ],
)
add(
    "SEBI material event deadlines as of 2023-07-15",
    "fact_lookup",
    gold_evidence_ids=["ev-sebi-material-events-20230713-deadlines"],
    required_claims=[
        "Distinguish board meeting, internal-event and external-event deadlines "
        "and specific Schedule III timelines."
    ],
)
add(
    "RBI KYC commencement as of 2025-06-12",
    "fact_lookup",
    gold_evidence_ids=["ev-rbi-kyc-20250612-effective"],
    required_claims=[
        "Report the amendment commencement without inferring present-day KYC obligations."
    ],
)
benchmark = Benchmark.model_validate(
    {
        "schema_version": 2,
        "name": "Research development matrix",
        "purpose": "Source-crosschecked development labels; no independent review, "
        "held-out split, or live model result claimed.",
        "cases": cases,
    }
)
(FIXTURES / "research-benchmark.json").write_text(benchmark.model_dump_json(indent=2) + "\n")
print(f"Wrote {len(cases)} development cases")
