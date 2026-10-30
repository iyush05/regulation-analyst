"""Model-led layout reading with code verification. Controlled model; synthetic values."""

from datetime import date

import pymupdf
import pytest
from test_autoextract import YEARS_PL, page

from regulation_analyst.autoextract import automap
from regulation_analyst.benchmark import score_report
from regulation_analyst.errors import ResearchError
from regulation_analyst.models import Company, Document

# Labels the label rules do not recognise.
UNUSUAL = [
    YEARS_PL,
    ["Income from sale of products and services", "21", "1,62,990", "1,53,670"],
    ["Other income, net", "22", "3,600", "4,711"],
    ["Total income", "", "1,66,590", "1,58,381"],
    ["Earnings before taxes", "", "37,000", "35,000"],
    ["Total tax expense", "", "9,500", "8,300"],
    ["Net income for the year", "", "27,500", "26,700"],
]
COMPANY = Company(id="unusual", name="Unusual Industries Limited")
DOCUMENT = Document(
    id="unusual-ar25",
    title="Unusual annual report 2024-25",
    url="https://example.org/unusual.pdf",
    kind="annual_report",
    company_id="unusual",
    reporting_year=2025,
    captured_on=date(2025, 6, 1),
)


def report_pdf(path):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), "Contents", fontsize=12)
        page(
            document,
            "Consolidated Statement of Profit and Loss for the year ended March 31, 2025",
            "(In ₹ crore)",
            UNUSUAL,
        )
        page(document, "Notes to the consolidated financial statements", "(In ₹ crore)", UNUSUAL)
        document.save(path)
    return path


class Reader:
    """Reads labels like a model would, plus deliberately wrong claims code must reject."""

    identity = "controlled:layout-reader"

    def __init__(self):
        self.calls = []

    def structured(self, instructions, content, schema, **kwargs):
        import json

        self.calls.append(schema.__name__)
        request = json.loads(content[0]["text"])
        if schema.__name__ == "StatementPages":
            return schema.model_validate(
                {
                    "pages": [
                        {"page": 2, "statement": "profit_loss", "scope": "consolidated"},
                        # A notes page: no statement title, not a continuation. Rejected.
                        {"page": 3, "statement": "profit_loss", "scope": "consolidated"},
                        {"page": 99, "statement": "balance_sheet", "scope": "consolidated"},
                    ]
                }
            )
        rows = {int(i): cells for i, cells in request["rows"].items()}

        def find(prefix):  # Labels may wrap across lines; match on their start.
            return next(i for i, cells in rows.items() if " ".join(cells).startswith(prefix[:12]))

        header = next(i for i, cells in rows.items() if "Year ended March 31, 2025" in cells)
        return schema.model_validate(
            {
                "columns": [
                    {"column": c, "header_row": header, "fiscal_year": int(cell[-4:])}
                    for c, cell in enumerate(rows[header])
                    if cell.endswith(("2025", "2024"))
                ]
                # The label column's header says "Particulars", not a year. Rejected.
                + [{"column": 0, "header_row": header, "fiscal_year": 2023}],
                "rows": [
                    {"metric": "revenue", "row": find("Income from sale of products and services")},
                    {"metric": "profit_before_tax", "row": find("Earnings before taxes")},
                    {"metric": "profit_total", "row": find("Net income for the year")},
                    {"metric": "tax_expense", "row": find("Total tax expense")},
                    # The year header row has no amounts in the chosen columns. Rejected.
                    {"metric": "other_income", "row": header},
                    {"metric": "total_assets", "row": find("Total income")},  # Not a P&L item.
                ],
            }
        )


def facts(result):
    return {
        (f["metric"], f["fiscal_year"]): f["raw_value"]
        for c in result["candidates"]
        for f in c["bundle"]["facts"]
    }


def test_rules_miss_unusual_labels(tmp_path):
    rules = automap(report_pdf(tmp_path / "ar.pdf"), COMPANY, DOCUMENT, tmp_path / "x")
    assert ("revenue", 2025) not in facts(rules)


def test_model_reads_the_layout_and_code_rejects_unsupported_choices(tmp_path):
    reader, pdf = Reader(), report_pdf(tmp_path / "ar.pdf")
    result = automap(
        pdf,
        COMPANY,
        DOCUMENT,
        tmp_path / "x",
        provider=reader,
        layout="llm",
    )
    mapped = facts(result)
    assert mapped[("revenue", 2025)] == "1,62,990"
    assert mapped[("revenue", 2024)] == "1,53,670"
    assert mapped[("profit_before_tax", 2025)] == "37,000"
    assert mapped[("profit_total", 2025)] == "27,500"
    assert not any(year == 2023 for _, year in mapped)
    assert "other_income" not in {m for m, _ in mapped}
    assert "total_assets" not in {m for m, _ in mapped}
    assert [p["page"] for p in result["report"]["located"]] == [2]
    assert {p["method"] for p in result["report"]["provenance"]} == {"llm"}

    # Decisions are cached by file, model, and prompt version: a rerun asks nothing.
    again = Reader()
    automap(
        pdf,
        COMPANY,
        DOCUMENT,
        tmp_path / "x",
        provider=again,
        layout="llm",
    )
    assert again.calls == []


def test_auto_uses_the_model_only_when_rules_miss_core_items(tmp_path):
    reader = Reader()
    result = automap(
        report_pdf(tmp_path / "ar.pdf"),
        COMPANY,
        DOCUMENT,
        tmp_path / "x",
        provider=reader,
        layout="auto",
    )
    assert result["report"]["layout"] == "llm"
    with pytest.raises(ResearchError, match="needs a configured model"):
        automap(report_pdf(tmp_path / "b.pdf"), COMPANY, DOCUMENT, tmp_path / "y", layout="llm")


def test_scoring_separates_wrong_from_blocked_and_missing():
    gold = {
        "fiscal_year": 2025,
        "unit": "INR_million",
        "values": {
            "revenue": "1,000.0",
            "profit_total": "200",
            "eps_basic": "4.5",
            "tax_expense": None,
        },
    }
    accepted = [
        {
            "metric": "revenue",
            "scope": "consolidated",
            "basis": "Ind AS",
            "fiscal_year": 2025,
            "revision": "reported",
            "raw_value": "100.00",
            "unit": "INR_crore",
        },
        {
            "metric": "profit_total",
            "scope": "consolidated",
            "basis": "Ind AS",
            "fiscal_year": 2025,
            "revision": "reported",
            "raw_value": "210",
            "unit": "INR_million",
        },
    ]
    queued = [{"metric": "eps_basic", "scope": "consolidated", "fiscal_year": 2025}]
    outcomes = {m: o["outcome"] for m, o in score_report(gold, accepted, queued).items()}
    assert outcomes == {"revenue": "correct", "profit_total": "wrong", "eps_basic": "queued"}
