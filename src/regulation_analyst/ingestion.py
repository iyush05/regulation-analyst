"""Local PDF extraction into a review artifact, never directly into accepted facts."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .errors import ResearchError

AMOUNT = re.compile(r"^\(?[+\-−]?\d[\d,]*(?:\.\d+)?\)?$|^[-–—]$")
YEAR = re.compile(r"^(?:19|20)\d{2}$")
# A year ending a date ("March 31, 2025") is header text, never an amount.
DATE_PART = re.compile(
    r"^\d{1,2}(?:st|nd|rd|th)?,?$|^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I
)


def _union(words):
    return [
        min(w[0] for w in words),
        min(w[1] for w in words),
        max(w[2] for w in words),
        max(w[3] for w in words),
    ]


def _column_headers(words, lefts, anchors, label_end, cells, boxes):
    """Place year headers over their columns; returns the words that remain label text.

    Words split into groups at wide gaps. A group right of the label area that states a year
    goes to the column it overlaps most, so a title's year never dates a column.
    """
    groups = [[words[0]]]
    for word in words[1:]:
        if word[0] - groups[-1][-1][2] > 6:
            groups.append([word])
        else:
            groups[-1].append(word)
    label = []
    for group in groups:
        x0, x1 = group[0][0], max(w[2] for w in group)
        text = " ".join(w[4] for w in group)
        overlaps = [
            (min(x1, anchor) - max(x0, left), i)
            for i, (left, anchor) in enumerate(zip(lefts, anchors, strict=True))
        ]
        overlap, column = max(overlaps)
        # A header that is only a date may start left of the amounts (e.g. Wipro's cash flow
        # "March 31, 2025"); anything else that starts in the label area stays label text.
        date_only = re.fullmatch(
            r"(?:\w+\s+)?\d{1,2}(?:st|nd|rd|th)?[\s.,/-]*\w*[\s.,/-]*(?:19|20)\d{2}|"
            r"\w+\s+\d{1,2},?\s+(?:19|20)\d{2}|(?:FY\s*)?(?:19|20)\d{2}",
            text,
            re.I,
        )
        if (
            (x0 >= label_end - 2 or date_only)
            and re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)
            and overlap > 0
            and not cells[column + 1]
        ):
            cells[column + 1], boxes[column + 1] = text, _union(group)
        else:
            label.extend(group)
    return label


def rows_table(page, number: int) -> dict | None:
    """Statement table from text lines: a label, then amounts aligned on right edges.

    Financial statements are often typeset without rules, where table detectors split labels
    mid-word. Each visual line keeps its words whole; trailing amounts are assigned to column
    anchors found by clustering right edges. Lines whose amounts do not align stay as text.
    """
    lines = []
    for word in sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        middle = (word[1] + word[3]) / 2
        if lines and abs(lines[-1][0] - middle) <= 3:
            lines[-1][1].append(word)
        else:
            lines.append((middle, [word]))
    parsed = []
    for _, words in lines:
        words = sorted(words, key=lambda w: w[0])
        amounts = []
        while words and AMOUNT.match(words[-1][4]):
            if YEAR.match(words[-1][4]) and len(words) > 1 and DATE_PART.match(words[-2][4]):
                break
            amounts.insert(0, words.pop())
        parsed.append((words, amounts))
    edges = sorted(a[2] for _, amounts in parsed for a in amounts)
    clusters = []
    for edge in edges:
        if clusters and edge - clusters[-1][-1] <= 12:
            clusters[-1].append(edge)
        else:
            clusters.append([edge])
    anchors = [sum(c) / len(c) for c in clusters if len(c) >= 3]
    if len(anchors) < 2:
        return None
    # Each column spans from its leftmost aligned amount to its right-edge anchor.
    lefts = [
        min(
            (a[0] for _, amounts in parsed for a in amounts if abs(a[2] - anchor) <= 15),
            default=anchor,
        )
        for anchor in anchors
    ]
    label_end = min(lefts)
    rows, boxes = [], []
    for words, amounts in parsed:
        # Leading numbers that do not align belong to the label, e.g. notes "2.4.2 and 2.21";
        # prose ending in numbers aligns nowhere and stays text.
        for start in range(len(amounts) + 1):
            cells, cell_boxes = [""] * (len(anchors) + 1), [None] * (len(anchors) + 1)
            placed = True
            for amount in amounts[start:]:
                distance, column = min((abs(a - amount[2]), i) for i, a in enumerate(anchors))
                if distance > 15 or cells[column + 1]:
                    placed = False
                    break
                cells[column + 1], cell_boxes[column + 1] = amount[4], list(amount[:4])
            if placed:
                words = words + amounts[:start]
                break
        if words and not any(cells[1:]):
            words = _column_headers(words, lefts, anchors, label_end, cells, cell_boxes)
        if words:
            cells[0], cell_boxes[0] = " ".join(w[4] for w in words), _union(words)
        if not any(cells):
            continue
        if (
            rows
            and not any(rows[-1][1:])
            and any(cells[1:])
            and cells[0][:1].islower()
            and boxes[-1][0]
        ):
            # A wrapped label continues on the line that carries its amounts.
            cells[0] = rows[-1][0] + " " + cells[0]
            cell_boxes[0] = _union([boxes[-1][0], cell_boxes[0] or boxes[-1][0]])
            rows.pop()
            boxes.pop()
        rows.append(cells)
        boxes.append(cell_boxes)
    if sum(1 for row in rows if sum(bool(c) for c in row[1:]) >= 2) < 3:
        return None
    return {
        "id": f"p{number}-r1",
        "bbox": list(page.rect),
        "row_count": len(rows),
        "column_count": len(anchors) + 1,
        "headers": [],
        "rows": rows,
        "cell_boxes": [],
        "row_cell_boxes": boxes,
    }


def quiet_pymupdf():
    """Route PyMuPDF notices to logging; on stdout they would corrupt the CLI's JSON."""
    import pymupdf

    pymupdf.set_messages(pylogging=True, pylogging_name="pymupdf")
    pymupdf.no_recommend_layout()  # A plain print() otherwise, outside the message system.


def extract_pdf(
    source: str | Path,
    output_dir: str | Path,
    pages: list[int] | None = None,
    *,
    ocr: bool = False,
    language: str = "eng",
    table_strategy: str = "lines",
) -> dict:
    import pymupdf

    quiet_pymupdf()

    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ResearchError("invalid_request", "Supply an existing local PDF")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = sorted(set(pages)) if pages else None
    if table_strategy not in ("lines", "lines_strict", "text", "rows"):
        raise ResearchError("invalid_request", "Unknown table detection strategy")
    settings = {
        "extractor_version": 2,
        "pages": selected,
        "ocr": ocr,
        "language": language,
        "table_strategy": table_strategy,
        "parser_version": pymupdf.VersionBind,
    }
    fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    artifact_id = digest + "-" + fingerprint
    destination = root / artifact_id
    if (destination / "extraction.json").exists():
        cached = json.loads((destination / "extraction.json").read_text())
        if hashlib.sha256((destination / "original.pdf").read_bytes()).hexdigest() != digest:
            raise ResearchError("invalid_request", "Cached source snapshot failed integrity check")
        return cached
    temporary = Path(tempfile.mkdtemp(prefix=".extract-", dir=root))
    try:
        with pymupdf.open(source) as document:
            if document.is_encrypted:
                raise ResearchError(
                    "invalid_request", "Encrypted PDFs require a separately decrypted local copy"
                )
            selected = selected or list(range(1, len(document) + 1))
            if not selected or any(page < 1 or page > len(document) for page in selected):
                raise ResearchError(
                    "invalid_request", "PDF page numbers are one-based and must exist"
                )
            output_pages = []
            for number in selected:
                page = document[number - 1]
                ocr_document = None
                if ocr:
                    try:
                        # A searchable temporary PDF lets table detection use the OCR text.
                        pixmap = page.get_pixmap(dpi=200, alpha=False)
                        ocr_document = pymupdf.open("pdf", pixmap.pdfocr_tobytes(language=language))
                        extraction_page = ocr_document[0]
                    except Exception as exc:
                        raise ResearchError(
                            "not_found",
                            "OCR unavailable: install Tesseract language data and "
                            "set TESSDATA_PREFIX; the original PDF remains unchanged",
                        ) from exc
                else:
                    extraction_page = page
                text = extraction_page.get_text("text", sort=True)
                blocks = [
                    {"bbox": list(b[:4]), "text": b[4]}
                    for b in extraction_page.get_text("blocks", sort=True)
                    if b[6] == 0
                ]
                tables, issues = [], []
                if not text.strip():
                    issues.append("ocr_required: page has no embedded text; no OCR was attempted")
                elif table_strategy == "rows":
                    table = rows_table(extraction_page, number)
                    tables = [table] if table else []
                else:
                    try:
                        for index, table in enumerate(
                            extraction_page.find_tables(strategy=table_strategy).tables
                        ):
                            tables.append(
                                {
                                    "id": f"p{number}-t{index + 1}",
                                    "bbox": list(table.bbox),
                                    "row_count": table.row_count,
                                    "column_count": table.col_count,
                                    "headers": table.header.names,
                                    "rows": table.extract(),
                                    "cell_boxes": [
                                        list(cell) if cell else None for cell in table.cells
                                    ],
                                    "row_cell_boxes": [
                                        [list(cell) if cell else None for cell in row.cells]
                                        for row in table.rows
                                    ],
                                }
                            )
                    except Exception as exc:
                        issues.append(
                            f"table_detection_failed: {type(exc).__name__}; manual review required"
                        )
                image_name = f"page-{number}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(temporary / image_name)
                output_pages.append(
                    {
                        "pdf_page": number,
                        "pdf_page_label": page.get_label(),
                        "text": text,
                        "blocks": blocks,
                        "tables": tables,
                        "rendering": image_name,
                        "issues": issues,
                        "review_status": "pending",
                    }
                )
                if ocr_document:
                    ocr_document.close()
            artifact = {
                "application_version": __version__,
                "schema_version": 1,
                "source_sha256": digest,
                "source_name": source.name,
                "snapshot": "original.pdf",
                "parser": "pymupdf",
                "parser_version": pymupdf.VersionBind,
                "parser_settings": settings,
                "created_at": datetime.now(UTC).isoformat(),
                "page_count": len(document),
                "pages": output_pages,
                "status": "review_required",
                "artifact_directory": str(destination),
            }
        shutil.copyfile(source, temporary / "original.pdf")
        (temporary / "extraction.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False)
        )
        os.rename(temporary, destination)
        return artifact
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
