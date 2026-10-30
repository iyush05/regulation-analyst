"""Verbatim MD&A extraction from generated reports. All text is synthetic."""

import pymupdf
import pytest
from test_autoextract import COMPANY, DOCUMENT, PROFIT_LOSS, page
from test_pipeline import AR25, Discovery, site

from regulation_analyst.commentary import extract_commentary, locate_section, page_passages
from regulation_analyst.store import Store

LEFT = (
    "The increase in revenue was primarily attributable to higher realization from "
    "value-based selling and automation benefits, partially offset by lower volumes in "
    "the year. Revenue growth in reported terms includes the impact of currency movements."
)
RIGHT = (
    "Our revenues for fiscal 2025 in constant currency grew by 4.2 percent. Financial "
    "services clients increased spending on cloud programs during the second half, while "
    "retail clients remained cautious about discretionary projects through the year."
)
CONTINUED = (
    "Operating margin improved as utilization rose and subcontracting costs declined. "
    "Management expects pricing discipline and automation to support margins next year, "
    "although wage increases and large deal transition costs remain headwinds for us."
)


def mdna_page(document, header: bool, left: list[str], right: list[str], table=False):
    p = document.new_page(width=595, height=842)
    if header:
        p.insert_text((40, 40), "Statutory reports", fontsize=8)
        p.insert_text((40, 56), "Management's discussion and analysis", fontsize=12)
    y = 90
    for text in left:
        p.insert_textbox(pymupdf.Rect(40, y, 285, y + 120), text, fontsize=9)
        y += 130
    y = 90
    if table:
        p.insert_text((310, y), "FY25 2,10,000 FY24 1,98,000 Growth 6.1", fontsize=9)
        y += 30
    for text in right:
        p.insert_textbox(pymupdf.Rect(310, y, 555, y + 120), text, fontsize=9)
        y += 130


def annual_report(path):
    with pymupdf.open() as document:
        cover = document.new_page(width=595, height=842)
        cover.insert_text((40, 40), "Contents", fontsize=12)
        mdna_page(document, True, ["1. Revenue", LEFT], [RIGHT], table=True)
        mdna_page(document, False, [CONTINUED], [])  # Untitled continuation page.
        mdna_page(document, True, [CONTINUED.replace("next year", "in the medium term")], [])
        governance = document.new_page(width=595, height=842)
        governance.insert_text((40, 56), "Corporate governance report", fontsize=12)
        page(
            document,
            "Consolidated Statement of Profit and Loss for the year ended March 31, 2025",
            "(In ₹ crore, except per equity share data)",
            PROFIT_LOSS,
        )
        auditor = document.new_page(width=595, height=842)
        auditor.insert_textbox(
            pymupdf.Rect(40, 40, 555, 200),
            "Other information comprises the Management Discussion and Analysis and the "
            "Board's Report but does not include the financial statements.",
            fontsize=9,
        )
        document.save(path)
    return path


def test_section_is_the_longest_heading_run_up_to_the_next_section(tmp_path):
    with pymupdf.open(annual_report(tmp_path / "ar.pdf")) as pdf:
        assert locate_section(pdf) == [2, 3, 4]


def test_columns_are_read_in_order_and_tables_skipped(tmp_path):
    with pymupdf.open(annual_report(tmp_path / "ar.pdf")) as pdf:
        texts = [chunk["text"] for chunk in page_passages(pdf[1], 2)]
    assert texts == [f"1. Revenue {LEFT}", RIGHT]  # Left column first, heading attached.


def test_passages_are_verbatim_cited_and_labelled(tmp_path):
    bundle, report = extract_commentary(annual_report(tmp_path / "ar.pdf"), COMPANY, DOCUMENT)
    assert report == {"section_pages": [2, 3, 4], "passages": 4}
    passage = next(p for p in bundle.passages if "constant currency" in p.text)
    assert passage.text == RIGHT
    assert passage.representation == "excerpt" and passage.speaker_role == "management"
    assert {"revenue", "constant_currency", "segments"} <= set(passage.topics)
    assert passage.fiscal_year == 2025
    evidence = next(e for e in bundle.evidence if e.id == passage.evidence_id)
    assert (evidence.pdf_page, evidence.section) == (2, "Management's discussion and analysis")
    assert evidence.review_method == "automated_extraction"
    assert evidence.checks == ["grounding", "section"]


def test_ingest_imports_commentary_that_answers_why_questions(tmp_path):
    pdf = annual_report(tmp_path / "ar.pdf").read_bytes()
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    from regulation_analyst.pipeline import ingest
    from regulation_analyst.service import ResearchService

    result = ingest(
        store,
        "Synthetic",
        ["FY25"],
        provider=Discovery(),
        client=site(pdf, refused=()),
        archive=tmp_path / "archive",
        inbox=tmp_path / "inbox",
        extractions=tmp_path / "extractions",
        candidates=tmp_path / "candidates",
    )
    (filing,) = result["filings"]
    assert filing["commentary"] == {"section_pages": [2, 4], "passages": 4, "imported": 4}
    service = ResearchService(Store(store.path))
    found = service.search_filings("constant currency", company="Synthetic", year="FY25")
    assert found.data["passages"][0]["text"] == RIGHT
    answer = service.answer_question("Synthetic revenue FY25 and why did it change?")
    assert answer.data["commentary"][0]["text"] in (f"1. Revenue {LEFT}", RIGHT)
    assert "Management's explanation is quoted below." in answer.data["answer"]
    assert AR25 in result["filings"][0]["url"]


@pytest.mark.parametrize(
    "text", ["Particulars Standalone Consolidated", "FY25 FY24", "(In ₹ crore)"]
)
def test_table_headers_are_not_headings(text):
    from regulation_analyst.commentary import is_heading

    assert not is_heading(text)
    assert is_heading("1. Revenue") and is_heading("Results of our operations")
