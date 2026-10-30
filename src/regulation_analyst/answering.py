"""Conservative, deterministic reference workflow; MCP clients supply their own LLM."""

import re

from .errors import ResearchError
from .metrics import DERIVED_METRICS, calculate
from .models import REPORTED_METRICS
from .render import Sources, assemble, bullets, name, summarize, value_text, year_table

ALIASES = {
    "operating_margin": ["operating margin", "operating margins"],
    "net_margin": ["net margin", "net margins", "net profit margin"],
    "roe": ["roe", "return on equity"],
    "operating_profit": ["operating profit", "operating income"],
    "profit_owners": ["net profit", "profit attributable to owners"],
    "profit_total": ["total profit", "profit including non-controlling interests"],
    "revenue": ["revenue", "revenues", "sales"],
    "equity_owners": ["equity attributable to owners"],
    "other_income": ["other income"],
    "total_income": ["total income"],
    "finance_costs": ["finance costs", "finance cost", "interest expense"],
    "depreciation_amortisation": ["depreciation", "depreciation and amortisation"],
    "profit_before_tax": ["profit before tax", "pbt"],
    "tax_expense": ["tax expense"],
    "profit_discontinued": [
        "discontinued operations profit",
        "profit from discontinued operations",
    ],
    "eps_basic": ["eps", "basic eps", "earnings per share"],
    "eps_diluted": ["diluted eps", "diluted earnings per share"],
    "operating_cash_flow": ["operating cash flow", "cash flow from operations"],
    "capex": ["capex", "capital expenditure"],
    "non_controlling_interest": ["non-controlling interest", "minority interest"],
    "total_assets": ["total assets"],
    "current_assets": ["current assets"],
    "current_liabilities": ["current liabilities"],
    "borrowings_current": ["current borrowings", "short-term borrowings"],
    "borrowings_noncurrent": ["non-current borrowings", "long-term borrowings"],
    "cash_and_equivalents": ["cash and cash equivalents"],
    "ebitda": ["ebitda"],
    "ebitda_margin": ["ebitda margin", "ebitda margins"],
    "debt_to_equity": ["debt to equity", "debt-to-equity", "debt equity ratio"],
    "roce": ["roce", "return on capital employed"],
    "interest_coverage": ["interest coverage", "interest coverage ratio"],
    "free_cash_flow": ["free cash flow", "fcf"],
    "current_ratio": ["current ratio"],
}


def contains(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE) is not None


def parse_years(question: str) -> list[int]:
    matches = list(re.finditer(r"\bFY\s*['’]?\s*(20\d{2}|\d{2})\b", question, re.IGNORECASE))
    years = [int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1]) for m in matches]
    if len(matches) == 2 and re.fullmatch(
        r"\s*(?:to|through|[-–—])\s*", question[matches[0].end() : matches[1].start()]
    ):
        if years[0] >= years[1] or years[1] - years[0] > 9:
            raise ResearchError(
                "invalid_request", "Use an increasing fiscal-year range of at most 10 years"
            )
        years = list(range(years[0], years[1] + 1))
    if not years:
        raise ResearchError(
            "ambiguous",
            "Specify fiscal years, for example FY23 to FY25; "
            "latest years are not inferred from corpus coverage",
        )
    if len(set(years)) > 10:
        raise ResearchError("invalid_request", "At most 10 fiscal years per question")
    return sorted(set(years))


def validate_rows(store, rows: list[dict], calculations: list[dict]):
    """Recompute financial outputs from canonical records before rendering."""
    for row in rows:
        for fact in row["facts"]:
            canonical = store.fact_data(store.record("facts", fact["id"]))
            if canonical != fact:
                raise ResearchError(
                    "invalid_request", "Financial evidence was altered after retrieval"
                )
        first = row["facts"][0]
        if any(
            row[key] != first[key]
            for key in ("company_id", "fiscal_year", "period_start", "period_end")
        ):
            raise ResearchError("invalid_request", "Answer identity differs from its source facts")
        if row["calculation"]:
            if row["value"] != row["calculation"]["value"]:
                raise ResearchError("invalid_request", "Answer value differs from its calculation")
            calculation = row["calculation"]
            if calculation not in calculations:
                raise ResearchError(
                    "invalid_request", "Answer calculation is absent from the trace"
                )
        elif row["value"] != row["facts"][0]["value"]:
            raise ResearchError("invalid_request", "Answer value differs from its source fact")
    for result in calculations:
        recomputed = calculate(
            store, result["formula_id"].removesuffix(".v1"), result["input_fact_ids"]
        )
        if recomputed != result:
            raise ResearchError("invalid_request", "Calculation lineage failed verification")


def answer(service, question: str, *, scope, basis, policy, known_on, trust="allow_automated"):
    if not question.strip() or len(question) > 2000:
        raise ResearchError("invalid_request", "Question must contain 1–2000 characters")
    text = question.casefold()
    if re.search(r"\b(?:us\s+gaap|uk\s+gaap)\b", text):
        raise ResearchError("out_of_scope", "Only Ind AS and IFRS accounting bases are supported")
    if re.search(r"\b(?:buy|sell|hold|price target|stock pick|investment recommendation)\b", text):
        return service.result(
            "out_of_scope",
            "This assistant supports source-backed research, not investment recommendations",
        )
    if re.search(r"\b(?:rbi|sebi|regulation|kyc|circular)\b", text):
        match = re.search(r"\b(?:as of|on)\s+(\d{4}-\d{2}-\d{2})\b", text)
        if not match:
            raise ResearchError(
                "ambiguous",
                "Regulatory questions require an explicit date, for example as of 2025-06-12",
            )
        authority = "RBI" if contains(text, "rbi") else "SEBI" if contains(text, "sebi") else None
        result = service.search_regulations(
            question, as_of=match[1], authority=authority, known_on=known_on
        )
        parts = [result.message]
        for provision in result.data["provisions"]:
            parts.append(
                f"{provision['authority']} · {provision['clause']} · "
                f"applies to {', '.join(provision['entity_types'])}: "
                f"{provision['text']} {provision['source']['citation']}"
            )
        return result.model_copy(
            update={
                "data": {
                    **result.data,
                    "answer": "\n\n".join(parts),
                    "sources": [p["source"] for p in result.data["provisions"]],
                    "claims": [
                        {
                            "kind": "regulatory",
                            "provision_id": p["id"],
                            "evidence_ids": [p["evidence_id"]],
                        }
                        for p in result.data["provisions"]
                    ],
                    "workflow": "deterministic_reference",
                }
            }
        )
    if re.search(r"\b(?:q[1-4]|quarterly|quarter|ttm|forecast)\b", text):
        raise ResearchError(
            "out_of_scope",
            "The reference workflow currently covers annual historical metrics in list_metrics",
        )
    if "standalone" in text:
        scope = "standalone"
    if "ifrs" in text:
        basis = "IFRS"
    elif "ind as" in text:
        basis = "Ind AS"
    companies = [
        c
        for c in service.store.records("companies")
        if any(contains(text, name) for name in c.names)
    ]
    if not companies:
        raise ResearchError(
            "not_found",
            "Name a covered company; use list_companies to inspect coverage. To add an Indian "
            'listed company: regulation-analyst ingest "<company>" --years FY24 FY25',
        )
    if len(companies) > 3:
        raise ResearchError(
            "out_of_scope", "The reference workflow supports up to three companies per question"
        )
    if re.search(r"\b(?:compare|versus|vs)\b", text) and len(companies) < 2:
        raise ResearchError("ambiguous", "Name at least two covered companies for comparison")
    years = parse_years(question)
    # Longest matching phrase wins only when all other matches are contained within it.
    matches = [
        (metric, phrase)
        for metric, phrases in ALIASES.items()
        for phrase in phrases
        if contains(text, phrase)
    ]
    if not matches:
        raise ResearchError(
            "ambiguous", "Specify a metric such as operating margin, net margin, revenue, or ROE"
        )
    longest = max(matches, key=lambda item: len(item[1]))
    if any(metric != longest[0] and phrase not in longest[1] for metric, phrase in matches):
        raise ResearchError(
            "ambiguous",
            "Ask for one metric at a time in the reference workflow; "
            "tools support broader research",
        )
    metric = longest[0]
    if contains(text, "cagr") and metric in DERIVED_METRICS:
        raise ResearchError(
            "out_of_scope", "CAGR of a ratio or derived measure is not a supported definition"
        )
    if known_on:
        from datetime import date

        date.fromisoformat(known_on)
    filters = dict(scope=scope, basis=basis, policy=policy, known_on=known_on, trust=trust)
    rows, missing, traces = [], [], []
    for year in years:
        found, absent = service.aligned_rows([c.id for c in companies], metric, year, **filters)
        rows.extend(found)
        missing.extend(absent)
        traces.extend(
            {
                "operation": "get_table",
                "company_id": r["company_id"],
                "year": year,
                "metric": metric,
            }
            for r in found
        )
    if not rows:
        status = "ambiguous" if any(m["status"] == "ambiguous" for m in missing) else "not_found"
        return service.result(
            status,
            "The requested financial evidence is not available",
            missing=missing,
            answer="Not found in the corpus. "
            + "; ".join(m["reason"] for m in missing)
            + ". To import these years: regulation-analyst ingest "
            + " ".join(
                f'"{c.name}" --years ' + " ".join(f"FY{y % 100:02d}" for y in years)
                for c in companies[:1]
            ),
        )
    for year in years:
        comparable = [r for r in rows if r["fiscal_year"] == year]
        if len({(r["period_start"], r["period_end"], r["definition"]) for r in comparable}) > 1:
            raise ResearchError("ambiguous", "Company periods or metric definitions do not align")
    calculations = [r["calculation"] for r in rows if r["calculation"]]
    changes = []
    wants_change = any(
        contains(text, phrase)
        for phrase in ["change", "changed", "growth", "cagr", "increase", "decrease"]
    )
    if wants_change and len(years) >= 2:
        for company in companies:
            endpoints = [
                next(
                    (r for r in rows if r["company_id"] == company.id and r["fiscal_year"] == y),
                    None,
                )
                for y in (years[0], years[-1])
            ]
            if not all(endpoints):
                continue
            ids = [f["id"] for row in endpoints for f in row["facts"]]
            definitions = {row["definition"] for row in endpoints}
            if len(definitions) > 1:
                missing.append(
                    {"reason": f"{company.name} {metric} definitions differ between endpoints"}
                )
                continue
            if metric in ("operating_margin", "net_margin") and not any(
                d.startswith("operating_margin_derived") for d in definitions
            ):
                formula = "margin_change_pp"
            elif metric == "roe":
                formula = "roe_change_pp"
            elif metric in REPORTED_METRICS:
                formula = "cagr" if contains(text, "cagr") else "growth_percent"
            else:
                missing.append(
                    {
                        "reason": f"Change in {metric.replace('_', ' ')} is not implemented; "
                        "individual values are provided"
                    }
                )
                continue
            try:
                calculation = calculate(service.store, formula, ids)
                calculations.append(calculation)
                changes.append(
                    {
                        "company_id": company.id,
                        "from_year": years[0],
                        "to_year": years[-1],
                        "calculation": calculation,
                    }
                )
            except ResearchError as exc:
                missing.append({"reason": str(exc), "status": exc.status})
    elif wants_change:
        missing.append({"reason": "Change requires at least two explicit fiscal years"})
    commentary = []
    wants_commentary = any(
        contains(text, word)
        for word in ["management", "explain", "explanation", "why", "said", "say"]
    )
    if wants_commentary:
        for company in companies:
            # Call transcripts first; else management's discussion in the annual report.
            hits = []
            for kind in ("transcript", "annual_report"):
                hits = [
                    hit
                    for hit in service.search_filings(
                        # Explanations use causal wording; it ranks them above passing mentions.
                        metric.replace("_", " ")
                        + " increase decrease growth primarily attributable due driven",
                        company=company.id,
                        year=years[-1],
                        document_type=kind,
                        limit=8,
                        known_on=known_on,
                    ).data["passages"]
                    if hit["speaker_role"] == "management" and metric in hit["topics"]
                ]
                if hits:
                    break
            supported = hits
            commentary.extend(supported[:2])
            if not supported:
                missing.append(
                    {
                        "reason": f"No management commentary on {metric} "
                        f"for {company.name} FY{years[-1]}"
                    }
                )
    validate_rows(service.store, rows, calculations)
    sources = {fact["evidence_id"]: fact["source"] for row in rows for fact in row["facts"]}
    sources.update({p["evidence_id"]: p["source"] for p in commentary})
    cited = Sources()
    table = {}
    for row in rows:
        table.setdefault((row["company_id"], name(metric), row["unit"]), {})[row["fiscal_year"]] = (
            row["value"],
            [f["source"] for f in row["facts"]],
        )
    change_lines = [
        f"- {change['company_id']} FY{change['from_year'] % 100:02d}→FY"
        f"{change['to_year'] % 100:02d}: "
        f"{value_text(change['calculation']['value'], change['calculation']['unit'])} "
        f"({name(change['calculation']['formula_id'])})"
        for change in changes
    ]
    commentary_lines = [
        f"- FY{p['fiscal_year'] % 100:02d} {p['speaker']} "
        f"({p['representation'].replace('_', ' ')}): {p['text']} {cited.cite(p['source'])}"
        for p in commentary
    ]
    if commentary and len(years) > 1:
        commentary_lines.append(
            f"- Commentary coverage is limited to FY{years[-1] % 100:02d}; "
            "earlier explanations are not in this result."
        )
    notes = [w["text"] for c in calculations for w in c["warnings"]]
    notes += [w["text"] for row in rows for f in row["facts"] for w in f["warnings"]]
    method = (
        ["Method: " + "; ".join(dict.fromkeys(c["formula"] for c in calculations)) + "."]
        if calculations
        else []
    )
    names = {c.id: c.short_name for c in companies}
    series: dict[tuple, dict] = {}
    for row in rows:
        series.setdefault((row["company_id"], metric, row["unit"]), {})[row["fiscal_year"]] = row[
            "value"
        ]
    paragraph = summarize(
        [(names.get(c, c), m, u, v) for (c, m, u), v in series.items()],
        automated=any(f["source"]["trust"] != "reviewed" for row in rows for f in row["facts"]),
        warnings=bool(notes),
        gaps=[m["reason"] for m in missing],
        commentary=bool(commentary),
    )
    answer_text = assemble(
        [
            ("", [paragraph]),
            ("", [f"{name(metric).capitalize()} · {scope} · {basis} · {name(policy)}"]),
            ("", year_table("Measure", table, years, cited, False)),
            ("Change", change_lines),
            ("", method),
            ("Management commentary", commentary_lines),
            ("Warnings", bullets(notes)),
            ("Gaps", bullets(m["reason"] for m in missing)),
        ],
        cited,
    )
    claims = [
        {
            "kind": "financial",
            "company_id": row["company_id"],
            "fiscal_year": row["fiscal_year"],
            "metric": metric,
            "value": row["value"],
            "evidence_ids": [f["evidence_id"] for f in row["facts"]],
            "calculation_id": row["calculation"]["id"] if row["calculation"] else None,
        }
        for row in rows
    ]
    claims.extend(
        {"kind": "management_commentary", "evidence_ids": [p["evidence_id"]], "passage_id": p["id"]}
        for p in commentary
    )
    return service.result(
        "partial" if missing else "ok",
        "Answer assembled from reviewed evidence and verified calculations",
        answer=answer_text,
        rows=rows,
        changes=changes,
        commentary=commentary,
        calculations=calculations,
        sources=list(sources.values()),
        claims=claims,
        missing=missing,
        trace=traces,
        workflow="deterministic_reference",
        validation="passed",
        scope=scope,
        basis=basis,
        policy=policy,
        known_on=known_on,
        trust=trust,
    )
