"""Reproduce the source-crosschecked expansion; independent human review remains pending.

Values were checked against official PDF text on 2026-10-27. This is data authoring,
not automatic extraction. No publication date is inferred from a signature date.
"""

import json
from pathlib import Path

from regulation_analyst.metrics import DEFINITIONS
from regulation_analyst.models import Bundle

ROOT = Path(__file__).resolve().parents[1]
bundle = {
    "schema_version": 1,
    "description": "Official-source text crosschecks; "
    "no independent human audit or local archives yet",
    "documents": [],
    "evidence": [],
    "facts": [],
}


def document(rid, company, year, url, kind="annual_report"):
    bundle["documents"].append(
        {
            "id": rid,
            "title": f"{company.title()} consolidated Ind AS financial statements FY{year}",
            "url": url,
            "kind": kind,
            "company_id": company,
            "reporting_year": year,
            "captured_on": "2026-10-27",
            "published_on": None,
            "notes": "Official standalone financial-statements PDF. Signature date is not "
            "treated as verified publication date. Remote reference only; "
            "independent human audit pending.",
        }
    )


def fact(company, year, metric, value, doc, page, printed, row, revision):
    rid = f"{company}-indas-{year}-{metric}"
    eid = "ev-" + rid
    instant = metric == "equity_owners"
    bundle["evidence"].append(
        {
            "id": eid,
            "document_id": doc,
            "pdf_page": page,
            "printed_page": str(printed),
            "section": "Consolidated Balance Sheet"
            if instant
            else "Consolidated Statement of Profit and Loss",
            "table": "Consolidated Balance Sheet"
            if instant
            else "Consolidated Statement of Profit and Loss",
            "row": row,
            "column": f"As at March 31, {year}" if instant else f"Year ended March 31, {year}",
            "review_method": "source_text_crosscheck",
            "reviewer": "coding-assistant; independent human review pending",
            "reviewed_on": "2026-10-27",
        }
    )
    bundle["facts"].append(
        {
            "id": rid,
            "company_id": company,
            "metric": metric,
            "definition": DEFINITIONS[metric],
            "fiscal_year": year,
            "period_start": None if instant else f"{year - 1}-04-01",
            "period_end": f"{year}-03-31",
            "period_kind": "instant" if instant else "annual",
            "scope": "consolidated",
            "basis": "Ind AS",
            "raw_value": str(value),
            "unit": "INR_crore",
            "evidence_id": eid,
            "revision": revision,
        }
    )


document(
    "infosys-consolidated24",
    "infosys",
    2024,
    "https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/2023-24/consolidated.pdf",
)
document(
    "infosys-consolidated25",
    "infosys",
    2025,
    "https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/2024-25/consolidated.pdf",
)
for metric, value, row in [
    ("revenue", 146767, "Revenue from operations"),
    ("operating_profit", 30905, "Operating profit"),
    ("profit_owners", 24095, "Profit attributable to: Owners of the Company"),
    ("profit_total", 24108, "Profit for the year"),
]:
    fact("infosys", 2023, metric, value, "infosys-consolidated24", 79, 365, row, "comparative")
for year, value, doc, printed in [
    (2023, 75407, "infosys-consolidated24", 298),
    (2024, 88116, "infosys-consolidated25", 303),
    (2025, 95818, "infosys-consolidated25", 303),
]:
    fact(
        "infosys",
        year,
        "equity_owners",
        value,
        doc,
        12,
        printed,
        "Total equity attributable to equity holders of the Company",
        "reported" if year == 2025 else "comparative",
    )
for year in (2024, 2025):
    document(
        f"tcs-consolidated{year}",
        "tcs",
        year,
        "https://www.tcs.com/content/dam/tcs/investor-relations/financial-statements/"
        f"{year - 1}-{str(year)[2:]}/q4/IND%20AS/Consolidated.pdf",
        "filing",
    )
for year, revenue, owners, total, equity in [
    (2023, 225458, 42147, 42303, 90424),
    (2024, 240893, 45908, 46099, 90489),
    (2025, 255324, 48553, 48797, 94756),
]:
    doc = "tcs-consolidated2024" if year == 2023 else "tcs-consolidated2025"
    revision = "reported" if year == 2025 else "comparative"
    for metric, value, row in [
        ("revenue", revenue, "Revenue from operations"),
        (
            "profit_owners",
            owners,
            "Profit for the year attributable to: Shareholders of the Company",
        ),
        ("profit_total", total, "PROFIT FOR THE YEAR"),
    ]:
        fact("tcs", year, metric, value, doc, 2, 2, row, revision)
    fact(
        "tcs",
        year,
        "equity_owners",
        equity,
        doc,
        1,
        1,
        "Equity attributable to shareholders of the Company",
        revision,
    )
bundle["passages"] = []
bundle["provisions"] = []
for company, url, published, speaker, summary, topics in [
    (
        "tcs",
        "https://www.tcs.com/who-we-are/newsroom/press-release/tcs-financial-results-q4-fy-2025",
        "2025-04-10",
        "Samir Seksaria",
        "The CFO credited disciplined execution and operational rigor with defending margins, "
        "while the company continued investing in talent, capabilities, "
        "innovation, and infrastructure.",
        ["operating_margin", "net_margin"],
    ),
    (
        "hcltech",
        "https://www.hcltech.com/en-us/press-releases/hcltech-delivers-another-year-industry-leading-growth",
        "2025-04-22",
        "C Vijayakumar",
        "The CEO linked strong quarterly bookings to AI offerings and the integrated go-to-market "
        "organization, while describing a cautious approach to short-term uncertainty.",
        ["revenue"],
    ),
]:
    rid = company + "-fy25-management-release"
    bundle["documents"].append(
        {
            "id": rid,
            "title": company.title() + " FY25 results press release",
            "url": url,
            "kind": "filing",
            "company_id": company,
            "reporting_year": 2025,
            "published_on": published,
            "captured_on": "2026-10-27",
            "notes": "Official press release, not an earnings-call transcript. "
            "HTML section citation.",
        }
    )
    bundle["evidence"].append(
        {
            "id": "ev-" + rid,
            "document_id": rid,
            "section": speaker + " management statement",
            "review_method": "source_text_crosscheck",
            "reviewer": "coding-assistant; independent human review pending",
            "reviewed_on": "2026-10-27",
        }
    )
    bundle["passages"].append(
        {
            "id": "passage-" + rid,
            "evidence_id": "ev-" + rid,
            "company_id": company,
            "fiscal_year": 2025,
            "text": summary,
            "representation": "reviewed_summary",
            "speaker": speaker,
            "speaker_role": "management",
            "topics": topics,
        }
    )

rid = "sebi-material-events-20230713"
bundle["documents"].append(
    {
        "id": rid,
        "title": "SEBI material-event disclosures circular, July 13, 2023",
        "url": "https://www.sebi.gov.in/sebi_data/attachdocs/jul-2023/1689245602256.pdf",
        "kind": "regulation",
        "published_on": "2023-07-13",
        "captured_on": "2026-10-27",
        "notes": "Narrow historical coverage at commencement only; "
        "subsequent amendments not audited.",
    }
)
for suffix, clause, page, text in [
    (
        "commencement",
        "Paragraph 5",
        1,
        "The circular concerning material-event disclosures under Regulations 30 "
        "and 30A takes effect on July 15, 2023.",
    ),
    (
        "deadlines",
        "Annexure II, paragraph 1",
        18,
        "For material events under Regulation 30(6), disclosure to exchanges must be prompt. "
        "The outer limits stated here are thirty minutes after the relevant board meeting closes, "
        "twelve hours for events originating within the entity, "
        "and twenty-four hours for externally "
        "originating events. Specific Schedule III deadlines take precedence where provided.",
    ),
]:
    eid = "ev-" + rid + "-" + suffix
    bundle["evidence"].append(
        {
            "id": eid,
            "document_id": rid,
            "pdf_page": page,
            "printed_page": str(page),
            "section": clause,
            "review_method": "source_text_crosscheck",
            "reviewer": "coding-assistant; independent human review pending",
            "reviewed_on": "2026-10-27",
        }
    )
    bundle["provisions"].append(
        {
            "id": "provision-" + rid + "-" + suffix,
            "evidence_id": eid,
            "authority": "SEBI",
            "instrument": "SEBI/HO/CFD/CFD-PoD-1/P/CIR/2023/123",
            "clause": clause,
            "text": text,
            "representation": "reviewed_summary",
            "entity_types": ["listed entities"],
            "effective_from": "2023-07-15",
            "verified_through": "2023-07-15",
        }
    )
Bundle.model_validate(bundle)
(ROOT / "src/regulation_analyst/fixtures/research-expansion.json").write_text(
    json.dumps(bundle, indent=2) + "\n"
)
print(f"Wrote {len(bundle['facts'])} additional facts from {len(bundle['documents'])} documents")
