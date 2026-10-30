import hashlib
import json
import subprocess
import sys

import anyio
import pymupdf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from regulation_analyst.ingestion import extract_pdf


def test_actual_pdf_table_extraction_preserves_columns_and_needs_review(tmp_path):
    original = tmp_path / "table.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=240)
        xs, ys = [30, 180, 280, 370], [40, 70, 100, 130]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for row, values in enumerate(
            [["Metric", "FY2025", "FY2024"], ["Revenue", "100", "90"], ["Profit", "25", "18"]]
        ):
            for column, value in enumerate(values):
                page.insert_text((xs[column] + 5, ys[row] + 20), value, fontsize=10)
        document.save(original)
    result = extract_pdf(original, tmp_path / "extractions")
    assert result["status"] == "review_required"
    assert result["source_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    page = result["pages"][0]
    assert page["review_status"] == "pending"
    assert page["tables"][0]["rows"] == [
        ["Metric", "FY2025", "FY2024"],
        ["Revenue", "100", "90"],
        ["Profit", "25", "18"],
    ]
    assert len(page["tables"][0]["cell_boxes"]) == 9
    assert extract_pdf(original, tmp_path / "extractions")["created_at"] == result["created_at"]


def test_image_only_page_is_flagged_instead_of_fabricating_values(tmp_path):
    original = tmp_path / "scan.pdf"
    with pymupdf.open() as drawing:
        page = drawing.new_page()
        page.insert_text((30, 30), "Revenue 100")
        raster = page.get_pixmap().tobytes("png")
    with pymupdf.open() as scanned:
        page = scanned.new_page()
        page.insert_image(page.rect, stream=raster)
        scanned.save(original)
    result = extract_pdf(original, tmp_path / "extractions")
    assert not result["pages"][0]["tables"]
    assert result["pages"][0]["issues"][0].startswith("ocr_required")


def test_cli_emits_machine_readable_results(store):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "regulation_analyst",
            "--db",
            str(store.path),
            "--json",
            "ask",
            "Infosys revenue FY25",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["data"]["rows"][0]["value"] == "162990"


def test_real_mcp_stdio_handshake_schema_tool_call_and_resource(store, tmp_path):
    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "regulation_analyst", "--db", str(store.path), "serve"],
        )
        with (tmp_path / "mcp-stderr.log").open("w") as errors:
            with anyio.fail_after(20):
                async with stdio_client(parameters, errlog=errors) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        names = {tool.name for tool in tools.tools}
                        assert names == {
                            "list_companies",
                            "list_metrics",
                            "get_table",
                            "calculate",
                            "search_filings",
                            "compare_companies",
                            "search_regulations",
                            "get_source",
                            "answer_question",
                            "check_coverage",
                        }
                        # ingest_company exists only with serve --allow-ingest.
                        assert all(tool.annotations.readOnlyHint for tool in tools.tools)
                        assert all(tool.outputSchema for tool in tools.tools)
                        answer = await session.call_tool(
                            "answer_question", {"question": "Infosys operating margin FY25"}
                        )
                        assert not answer.isError
                        assert answer.structuredContent["status"] == "ok"
                        assert (
                            answer.structuredContent["data"]["rows"][0]["calculation"][
                                "display_value"
                            ]
                            == "21.12"
                        )
                        unsupported = await session.call_tool(
                            "calculate", {"formula": "eval", "fact_ids": []}
                        )
                        assert unsupported.structuredContent["status"] == "invalid_request"
                        resource = await session.read_resource("research://coverage")
                        assert "infosys" in resource.contents[0].text

    anyio.run(run)
