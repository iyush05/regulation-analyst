"""Local PDF extraction into a review artifact, never directly into accepted facts."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .errors import ResearchError


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

    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ResearchError("invalid_request", "Supply an existing local PDF")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = sorted(set(pages)) if pages else None
    if table_strategy not in ("lines", "lines_strict", "text"):
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
