"""Verbatim management commentary from the MD&A section of an archived annual report.

Passages are excerpts copied from the page's text blocks, read column by column so two-column
layouts are not interleaved. Tables, headers, and page furniture are dropped. Each passage
cites its page and paragraph box and is imported as automated extraction; nothing is
paraphrased, so answers can quote management without a model writing explanations.
"""

import re
from datetime import date
from pathlib import Path

from .models import Bundle, Company, Document, Evidence, Passage
from .review import squash

SECTION = "Management's discussion and analysis"
HEADING = re.compile(r"management.{0,3}s? discussion (?:and|&) analysis")
# Titles that start the section after MD&A in Indian annual reports.
NEXT_SECTION = re.compile(
    r"corporate governance|board.{0,3}s report|directors.{0,3} report|business responsibility|"
    r"independent auditor|financial statements|shareholder information|notice of"
)
MIN_WORDS, MAX_WORDS = 25, 220
TOPICS = {
    "revenue": ["revenue", "top line", "topline", "sales"],
    "constant_currency": ["constant currency"],
    "operating_margin": ["operating margin", "operating profit", "ebit margin"],
    "net_margin": ["net profit", "net margin", "profit after tax", "profit for the year"],
    "ebitda": ["ebitda"],
    "segments": [
        "segment",
        "vertical",
        "financial services",
        "retail",
        "communication",
        "manufacturing",
        "energy",
        "hi-tech",
        "life sciences",
        "commercial vehicle",
        "passenger vehicle",
        "jaguar",
    ],
    "geography": ["north america", "europe", "india", "rest of the world", "geograph"],
    "costs": ["cost", "expense", "compensation", "wage", "salary"],
    "employees": ["attrition", "headcount", "employees", "utilization"],
    "deals": ["deal", "contract", "order book", "tcv"],
    "guidance": ["outlook", "guidance", "expect"],
    "cash_flow": ["cash flow", "free cash", "capital expenditure", "capex"],
    "debt": ["borrowing", "debt", "leverage"],
    "risks": ["risk", "uncertain"],
}


def heading_text(page) -> str:
    return squash(" ".join(page.get_text("text", sort=True).split("\n")[:12]))[:400]


def locate_section(pdf) -> list[int]:
    """One-based pages of the MD&A: the longest run of pages carrying its heading, extended
    over untitled continuation pages until the next section begins."""
    hits = [
        number for number, page in enumerate(pdf, start=1) if HEADING.search(heading_text(page))
    ]
    runs, current = [], []
    for number in hits:
        if current and number - current[-1] > 2:
            runs.append(current)
            current = []
        current.append(number)
    if current:
        runs.append(current)
    if not runs:
        return []
    run = max(runs, key=len)
    if len(run) < 2:
        return []
    last = run[-1]
    for number in range(run[-1] + 1, min(run[-1] + 3, len(pdf) + 1)):
        if NEXT_SECTION.search(heading_text(pdf[number - 1])):
            break
        last = number
    return list(range(run[0], last + 1))


def is_prose(text: str) -> bool:
    words = text.split()
    if len(words) < 6:
        return False
    digits = sum(ch.isdigit() for ch in text)
    letters = sum(ch.isalpha() for ch in text)
    return letters > 0 and digits / (letters + digits) < 0.25


def is_heading(text: str) -> bool:
    """A short title such as "1. Revenue" or "Results of our operations"."""
    words = text.split()
    letters = sum(ch.isalpha() for ch in text)
    digits = sum(ch.isdigit() for ch in text)
    return (
        not re.match(r"particulars\b|\(?in [₹`]|fy\s?\d", text, re.I)  # Table column headers.
        and 1 <= len(words) <= 8
        and not text.endswith((".", ",", ";"))
        and letters > 2 * digits
        and (text[:1].isupper() or text[:1].isdigit())
    )


def clean(text: str) -> str:
    text = text.replace("\t", " ").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # Rejoin words hyphenated at line ends.
    return " ".join(text.split())


def reading_order(page) -> list[tuple]:
    """Text blocks ordered column by column, then top to bottom within each column."""
    blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0 and b[4].strip()]
    width = page.rect.width
    starts = sorted({round(b[0]) for b in blocks})
    columns = []
    for x in starts:
        if not columns or x - columns[-1] > width * 0.2:
            columns.append(x)

    def column(block):
        return max(i for i, x in enumerate(columns) if block[0] >= x - 5) if columns else 0

    return sorted(blocks, key=lambda b: (column(b), b[1]))


def page_passages(page, number: int) -> list[dict]:
    """Paragraph-sized verbatim chunks; a short heading opens the chunk that follows it."""
    chunks, current, boxes, heading = [], [], [], None

    def flush():
        nonlocal current, boxes
        text = " ".join(current)
        if len(text.split()) >= MIN_WORDS:
            chunks.append(
                {
                    "page": number,
                    "text": text,
                    "bbox": [
                        min(b[0] for b in boxes),
                        min(b[1] for b in boxes),
                        max(b[2] for b in boxes),
                        max(b[3] for b in boxes),
                    ],
                }
            )
        current, boxes = [], []

    previous_column_x = None
    for block in reading_order(page):
        text = clean(block[4])
        words = len(text.split())
        if is_heading(text):
            flush()
            heading = text  # A section title such as "1. Revenue".
            continue
        if not is_prose(text):
            heading = None  # A table sat between the title and any later paragraph.
            continue
        new_column = previous_column_x is not None and abs(block[0] - previous_column_x) > 100
        if new_column or len(" ".join(current).split()) + words > MAX_WORDS:
            flush()
        if not current and heading:
            current.append(heading)
            boxes.append(block[:4])
            heading = None
        current.append(text)
        boxes.append(block[:4])
        previous_column_x = block[0]
    flush()
    return chunks


def topics_of(text: str) -> list[str]:
    lowered = text.casefold()
    return [topic for topic, words in TOPICS.items() if any(w in lowered for w in words)]


def extract_commentary(
    pdf_path: str | Path, company: Company, document: Document, reviewer="pipeline:commentary"
) -> tuple[Bundle | None, dict]:
    """Passages and evidence for the report's MD&A; also a short report for the job log."""
    import pymupdf

    with pymupdf.open(Path(pdf_path).expanduser().resolve()) as pdf:
        pages = locate_section(pdf)
        chunks = [c for number in pages for c in page_passages(pdf[number - 1], number)]
        # Cleaned like the passages, so words hyphenated across lines still match.
        page_text = {n: squash(clean(pdf[n - 1].get_text("text"))) for n in pages}
    evidence, passages = [], []
    for index, chunk in enumerate(chunks, start=1):
        # Grounding: every word of the excerpt must be printed on the cited page.
        if not all(word in page_text[chunk["page"]] for word in squash(chunk["text"]).split()):
            continue
        rid = f"{document.id}-mdna-p{chunk['page']}-{index}"
        evidence.append(
            Evidence(
                id=f"ev-{rid}",
                document_id=document.id,
                pdf_page=chunk["page"],
                section=SECTION,
                bbox=tuple(chunk["bbox"]),
                excerpt=chunk["text"][:200],
                review_method="automated_extraction",
                reviewer=reviewer,
                reviewed_on=date.today(),
                checks=["grounding", "section"],
            )
        )
        passages.append(
            Passage(
                id=f"passage-{rid}",
                evidence_id=f"ev-{rid}",
                company_id=company.id,
                fiscal_year=document.reporting_year,
                text=chunk["text"],
                representation="excerpt",
                speaker=SECTION,
                speaker_role="management",
                topics=topics_of(chunk["text"]),
            )
        )
    report = {"section_pages": pages, "passages": len(passages)}
    if not passages:
        return None, report
    bundle = Bundle(
        description=f"Verbatim MD&A excerpts from {document.title}",
        companies=[company],
        documents=[document],
        evidence=evidence,
        passages=passages,
    )
    return bundle, report
