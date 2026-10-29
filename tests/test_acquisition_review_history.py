import copy
import hashlib
from datetime import date
from pathlib import Path

import httpx
import pymupdf
import pytest

from regulation_analyst.acquisition import SourceRequest, acquire
from regulation_analyst.errors import ResearchError
from regulation_analyst.ingestion import extract_pdf
from regulation_analyst.models import Bundle, Document, Evidence, Provision
from regulation_analyst.review import (
    MappingPlan,
    Reconciliation,
    approve_candidates,
    build_candidates,
)
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


def example_pdf(path):
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=240)
        page.insert_text((30, 25), "Consolidated Ind AS (INR crore)")
        xs, ys = [30, 180, 280, 370], [40, 70, 100, 130]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for r, values in enumerate(
            [
                ["Metric", "FY2025", "FY2024"],
                ["Revenue", "100", "90"],
                ["Operating profit", "25", "18"],
            ]
        ):
            for c, value in enumerate(values):
                page.insert_text((xs[c] + 5, ys[r] + 20), value, fontsize=10)
        document.save(path)


def mapping():
    return MappingPlan.model_validate(
        {
            "company": {"id": "sample", "name": "Synthetic Sample"},
            "document": {
                "id": "sample-report",
                "title": "Synthetic report",
                "url": "https://www.infosys.com/test.pdf",
                "kind": "annual_report",
                "company_id": "sample",
                "reporting_year": 2025,
                "captured_on": "2025-06-01",
            },
            "tables": [
                {
                    "page": 1,
                    "table_id": "p1-t1",
                    "title": "Consolidated P&L",
                    "unit": "INR_crore",
                    "unit_evidence": "INR crore",
                    "scope": "consolidated",
                    "basis": "Ind AS",
                    "columns": [{"column": 1, "fiscal_year": 2025, "header_text": "FY2025"}],
                    "rows": [
                        {"row": 1, "metric": "revenue", "label": "Revenue"},
                        {"row": 2, "metric": "operating_profit", "label": "Operating profit"},
                    ],
                }
            ],
        }
    )


def test_pdf_archive_extract_map_review_import_query(tmp_path):
    pdf = tmp_path / "source.pdf"
    example_pdf(pdf)
    archived = acquire(
        SourceRequest(id="sample", url="https://www.infosys.com/test.pdf"),
        tmp_path / "archive",
        local_pdf=pdf,
    )
    assert archived["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    artifact = extract_pdf(archived["snapshot_path"], tmp_path / "extract")
    candidates = build_candidates(
        Path(artifact["artifact_directory"]) / "extraction.json", mapping()
    )
    assert candidates["status"] == "review_required"
    with pytest.raises(ValueError):
        Bundle.model_validate(candidates["bundle"])
    approved = approve_candidates(
        candidates,
        reviewer="Synthetic test reviewer",
        method="visual_review",
        reviewed_on=date(2025, 6, 1),
        expected_digest=candidates["candidate_sha256"],
    )
    store = Store(tmp_path / "research.sqlite3", readonly=False)
    store.import_bundle(approved)
    answer = ResearchService(store).answer_question("Sample operating margin FY25")
    assert answer.status == "ok"
    assert answer.data["rows"][0]["calculation"]["display_value"] == "25.00"
    assert answer.data["sources"][0]["integrity"] == "local_snapshot"


def test_review_rejects_swapped_year_unit_and_changed_candidate(tmp_path):
    pdf = tmp_path / "source.pdf"
    example_pdf(pdf)
    artifact = extract_pdf(pdf, tmp_path / "extract")
    path = Path(artifact["artifact_directory"]) / "extraction.json"
    plan = mapping()
    plan.tables[0].columns[0].fiscal_year = 2024
    with pytest.raises(ResearchError, match="year"):
        build_candidates(path, plan)
    plan = mapping()
    plan.tables[0].unit = "INR_lakh"
    with pytest.raises(ResearchError, match="unit"):
        build_candidates(path, plan)
    candidate = build_candidates(path, mapping())
    candidate["bundle"]["facts"][0]["raw_value"] = "999"
    with pytest.raises(ResearchError, match="digest"):
        approve_candidates(
            candidate,
            reviewer="test",
            method="visual_review",
            reviewed_on=date(2025, 6, 1),
            expected_digest=candidate["candidate_sha256"],
        )


def test_failed_reconciliation_blocks_promotion_and_cells_have_precise_boxes(tmp_path):
    pdf = tmp_path / "source.pdf"
    example_pdf(pdf)
    artifact = extract_pdf(pdf, tmp_path / "extract")
    plan = mapping()
    plan.tables[0].reconciliations = [Reconciliation(total_row=1, component_rows=[2])]
    candidate = build_candidates(Path(artifact["artifact_directory"]) / "extraction.json", plan)
    assert candidate["diagnostics"][0]["issue"] == "reconciliation_failed"
    table = artifact["pages"][0]["tables"][0]
    assert candidate["bundle"]["evidence"][0]["bbox"] == table["row_cell_boxes"][1][1]
    assert candidate["bundle"]["evidence"][0]["bbox"] != table["bbox"]
    with pytest.raises(ResearchError, match="diagnostics"):
        approve_candidates(
            candidate,
            reviewer="test",
            method="visual_review",
            reviewed_on=date(2025, 6, 1),
            expected_digest=candidate["candidate_sha256"],
        )


@pytest.mark.parametrize("tolerance", ["NaN", "Infinity", "-1", "not-a-number"])
def test_reconciliation_rejects_invalid_tolerances(tolerance):
    with pytest.raises(ValueError):
        Reconciliation(total_row=1, component_rows=[2], tolerance_crore=tolerance)


def test_ocr_dependency_failure_and_archive_tampering_are_explicit(tmp_path, monkeypatch):
    pdf = tmp_path / "source.pdf"
    example_pdf(pdf)

    def unavailable(*args, **kwargs):
        raise RuntimeError("No Tesseract data")

    monkeypatch.setattr(pymupdf.Pixmap, "pdfocr_tobytes", unavailable)
    with pytest.raises(ResearchError, match="OCR unavailable"):
        extract_pdf(pdf, tmp_path / "ocr", ocr=True)
    assert not list((tmp_path / "ocr").glob("*/extraction.json"))
    artifact = extract_pdf(pdf, tmp_path / "extract")
    (Path(artifact["artifact_directory"]) / "original.pdf").write_bytes(b"changed")
    with pytest.raises(ResearchError, match="integrity"):
        extract_pdf(pdf, tmp_path / "extract")


@pytest.mark.parametrize("mode", ["html", "large", "hash", "redirect"])
def test_download_rejects_bad_payloads_and_official_domain_redirect(tmp_path, mode):
    def handler(request):
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.org/evil.pdf"})
        return httpx.Response(
            200, content=b"<html>challenge</html>" if mode == "html" else b"%PDF-test" * 10
        )

    request = SourceRequest(
        id="source",
        url="https://www.infosys.com/source.pdf",
        max_bytes=20 if mode == "large" else 1000,
        expected_sha256="0" * 64 if mode == "hash" else None,
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ResearchError),
    ):
        acquire(request, tmp_path, client=client)
    assert not list(tmp_path.glob("*/original.pdf"))
    assert not list(tmp_path.glob(".download-*"))


def history_bundle():
    docs, evidence, provisions = [], [], []
    for rid, published, effective, through, prior in [
        ("v1", "2024-01-01", "2024-01-01", "2026-12-31", None),
        ("v2", "2025-02-01", "2025-03-01", "2025-12-31", "v1"),
    ]:
        docs.append(
            Document(
                id="doc-" + rid,
                title="Synthetic circular",
                url="https://www.rbi.org.in/test",
                kind="regulation",
                published_on=date.fromisoformat(published),
                captured_on=date(2026, 10, 27),
            )
        )
        evidence.append(
            Evidence(
                id="ev-" + rid,
                document_id="doc-" + rid,
                section="Clause 1",
                review_method="source_text_crosscheck",
                reviewer="Synthetic test fixture",
                reviewed_on=date(2026, 10, 27),
            )
        )
        provisions.append(
            Provision(
                id=rid,
                evidence_id="ev-" + rid,
                authority="RBI",
                instrument="Synthetic test KYC",
                clause="1",
                text="Synthetic customer verification " + rid,
                representation="reviewed_summary",
                entity_types=["banks"],
                effective_from=date.fromisoformat(effective),
                verified_through=date.fromisoformat(through),
                supersedes=prior,
            )
        )
    return Bundle(
        description="Synthetic version history",
        documents=docs,
        evidence=evidence,
        provisions=provisions,
    )


def test_version_boundaries_publication_cutoffs_and_no_old_version_resurrection(tmp_path):
    store = Store(tmp_path / "history.sqlite3", readonly=False)
    store.import_bundle(history_bundle())

    def search(day, **kwargs):
        return store.search_provisions("verification", as_of=date.fromisoformat(day), **kwargs)

    assert search("2025-02-28")[0]["id"] == "v1"
    assert search("2025-03-01")[0]["id"] == "v2"
    assert search("2026-01-01") == []
    assert search("2025-03-01", known_on=date(2025, 1, 31))[0]["id"] == "v1"
    assert search("2025-03-01", entity_type="broker") == []
    assert store.import_bundle(history_bundle())["inserted"]["provisions"] == 0


def test_conflicting_regulation_and_invalid_revision_fail_closed(tmp_path):
    bundle = history_bundle()
    data = bundle.model_dump(mode="json")
    invalid = copy.deepcopy(data)
    invalid["provisions"][1]["clause"] = "different"
    store = Store(tmp_path / "history.sqlite3", readonly=False)
    with pytest.raises(ResearchError, match="same clause"):
        store.import_bundle(Bundle.model_validate(invalid))
    data["provisions"][1]["supersedes"] = None
    store.import_bundle(Bundle.model_validate(data))
    with pytest.raises(ResearchError, match="Conflicting"):
        store.search_provisions("verification", as_of=date(2025, 4, 1))
