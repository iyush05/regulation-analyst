"""Layout benchmark: how many key figures each extraction layout gets right, across companies.

Every report runs through the same path as ingestion (automap, then validation gates without
the resolver, so layout reading is measured on its own). Only figures the gates accept count.
A wrong accepted figure is the critical failure; a figure the gates queue is a safe miss.
"""

import json
import time
from datetime import date
from pathlib import Path

from .autoextract import automap
from .errors import ResearchError
from .gates import entries_of, gate
from .models import Company, Document
from .numbers import normalize, resolution
from .providers import UsageBudget


def score_report(gold: dict, accepted: list[dict], queued: list[dict]) -> dict:
    """Per-metric outcome against gold values for the reported fiscal year."""
    found = {
        f["metric"]: f
        for f in accepted
        if f["scope"] == "consolidated"
        and f["basis"] == "Ind AS"
        and f["fiscal_year"] == gold["fiscal_year"]
        and f["revision"] == "reported"
    }
    blocked = {
        q["metric"]
        for q in queued
        if q["scope"] == "consolidated" and q["fiscal_year"] == gold["fiscal_year"]
    }
    outcomes = {}
    for metric, raw in gold["values"].items():
        if raw is None:
            continue
        unit = "INR_per_share" if metric.startswith("eps_") else gold["unit"]
        expected = normalize(raw, unit)
        fact = found.get(metric)
        if fact is None:
            outcomes[metric] = {"outcome": "queued" if metric in blocked else "missing"}
            continue
        actual = normalize(fact["raw_value"], fact["unit"])
        tolerance = resolution(raw, unit) + resolution(fact["raw_value"], fact["unit"])
        outcomes[metric] = {
            "outcome": "correct" if abs(actual - expected) <= tolerance else "wrong",
            "expected": raw,
            "extracted": fact["raw_value"],
        }
    return outcomes


def run_one(report: dict, pdf: Path, layout: str, work: Path, provider, max_tokens: int) -> dict:
    company = Company(id=report["id"], name=report["company"])
    document = Document(
        id=f"bench-{report['id']}-fy{report['fiscal_year']}",
        title=f"{report['company']} annual report FY{report['fiscal_year']}",
        url=report["url"],
        kind="annual_report",
        company_id=report["id"],
        reporting_year=report["fiscal_year"],
        captured_on=date.today(),
    )
    budget = UsageBudget(max_tokens) if provider else None
    started = time.monotonic()
    try:
        mapped = automap(
            pdf,
            company,
            document,
            work / "extractions",
            provider=provider,
            budget=budget,
            layout=layout,
        )
    except ResearchError as exc:
        return {
            "id": report["id"],
            "error": str(exc)[:300],
            "metrics": score_report(report, [], []),
        }
    entries = [e for c in mapped["candidates"] for e in entries_of(c)]
    accepted, queued = [], []
    for candidate, extraction in zip(
        mapped["candidates"], mapped["report"]["extractions"], strict=True
    ):
        result = gate(candidate, extraction=extraction["extraction"], others=entries)
        if result["bundle"] is not None:
            accepted += [f.model_dump(mode="json") for f in result["bundle"].facts]
        queued += result["queued"]
    return {
        "id": report["id"],
        "layout": mapped["report"].get("layout", layout),
        "seconds": round(time.monotonic() - started, 1),
        "usage": budget.usage if budget else None,
        **({"agreement": mapped["report"]["agreement"]} if "agreement" in mapped["report"] else {}),
        # In auto mode a failed model call keeps the rules result; say so in the report.
        **({"error": mapped["report"]["model_error"]} if "model_error" in mapped["report"] else {}),
        "metrics": score_report(report, accepted, queued),
    }


def run_layout_benchmark(
    gold_path: str | Path,
    archive: str | Path,
    layout: str,
    work: str | Path,
    *,
    provider=None,
    max_tokens: int = 200_000,
    only: list[str] | None = None,
) -> dict:
    gold = json.loads(Path(gold_path).read_text())
    work = Path(work)
    results = []
    for report in gold["reports"]:
        if only and report["id"] not in only:
            continue
        pdf = Path(archive) / report["sha256"] / "original.pdf"
        if not pdf.is_file():
            results.append({"id": report["id"], "error": f"Archived PDF not found: {pdf}"})
            continue
        results.append(run_one(report, pdf, layout, work, provider, max_tokens))
    tally = {"correct": 0, "wrong": 0, "missing": 0, "queued": 0}
    per_metric: dict[str, dict] = {}
    for result in results:
        for metric, outcome in result.get("metrics", {}).items():
            tally[outcome["outcome"]] += 1
            per_metric.setdefault(metric, dict.fromkeys(tally, 0))[outcome["outcome"]] += 1
    scored = sum(tally.values())
    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) for r in results)
    return {
        "layout": layout,
        "label_source": gold["label_source"],
        "reports": len(results),
        "gold_values": scored,
        "correct": tally["correct"],
        "wrong": tally["wrong"],
        "queued_by_gates": tally["queued"],
        "missing": tally["missing"],
        "accuracy": round(tally["correct"] / scored, 3) if scored else None,
        "wrong_rate_of_accepted": round(tally["wrong"] / (tally["correct"] + tally["wrong"]), 3)
        if tally["correct"] + tally["wrong"]
        else None,
        "seconds": round(sum(r.get("seconds", 0) for r in results), 1),
        "total_tokens": tokens,
        "per_metric": per_metric,
        "results": results,
    }


def markdown(report: dict) -> str:
    lines = [
        f"# Layout benchmark: {report['layout']}",
        "",
        f"Gold labels: {report['label_source']}.",
        "",
        f"- Reports: {report['reports']}, gold values: {report['gold_values']}",
        f"- Correct: {report['correct']} ({report['accuracy']:.0%})"
        if report["accuracy"] is not None
        else "- Correct: 0",
        f"- Wrong and accepted (critical): {report['wrong']}",
        f"- Blocked by validation gates: {report['queued_by_gates']}",
        f"- Not extracted: {report['missing']}",
        f"- Time: {report['seconds']} s; model tokens: {report['total_tokens']:,}",
        "",
        "| Company | Correct | Wrong | Blocked | Missing | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in report["results"]:
        outcomes = [o["outcome"] for o in result.get("metrics", {}).values()]
        wrong = [
            f"{m}: {o['extracted']} vs {o['expected']}"
            for m, o in result.get("metrics", {}).items()
            if o["outcome"] == "wrong"
        ]
        lines.append(
            f"| {result['id']} | {outcomes.count('correct')} | {outcomes.count('wrong')} | "
            f"{outcomes.count('queued')} | {outcomes.count('missing')} | "
            f"{'; '.join(wrong) or result.get('error', '')} |"
        )
    lines += ["", "| Metric | Correct | Wrong | Blocked | Missing |", "|---|---:|---:|---:|---:|"]
    for metric, counts in report["per_metric"].items():
        lines.append(
            f"| {metric} | {counts['correct']} | {counts['wrong']} | {counts['queued']} | "
            f"{counts['missing']} |"
        )
    return "\n".join(lines) + "\n"
