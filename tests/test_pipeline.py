"""Company ingestion flow with controlled discovery and HTTP. All values are synthetic."""

import json
from pathlib import Path

import httpx
import pytest
from test_autoextract import report

from regulation_analyst.cli import main
from regulation_analyst.errors import ResearchError
from regulation_analyst.pipeline import (
    CompanyMatch,
    FilingLink,
    find_annual_reports,
    identify,
    ingest,
    official_domain,
)
from regulation_analyst.store import Store

COMPANY = {
    "legal_name": "Synthetic Industries Limited",
    "aliases": ["Synthetic"],
    "nse_symbol": "SYNIND",
    "bse_code": "500001",
    "website_domain": "https://www.synthetic.example/investors",
    "fiscal_year_end_month": 3,
}
AR25 = "https://www.synthetic.example/files/ar-2024-25.pdf"
AR24 = "https://investors.synthetic.example/ar-2023-24.pdf"


class Discovery:
    """Controlled stand-in for web-search discovery; it records every request."""

    identity = "controlled:discovery"

    def __init__(self, matches=(COMPANY,), filings=None):
        self.matches, self.calls = list(matches), []
        self.filings = filings or [
            {"fiscal_year": 2025, "url": AR25, "title": "Annual Report 2024-25"},
            {"fiscal_year": 2024, "url": AR24, "title": "Annual Report 2023-24"},
        ]

    def structured(self, instructions, content, schema, *, web_search=False, budget=None):
        assert web_search
        self.calls.append(schema.__name__)
        if schema.__name__ == "CompanyMatches":
            return schema.model_validate({"matches": self.matches})
        return schema.model_validate({"filings": self.filings})


class Refuses:
    identity = "controlled:refuses"

    def structured(self, *args, **kwargs):
        raise AssertionError("Discovery must be reused, not repeated")


def site(pdf_bytes, refused=(AR24,)):
    def handler(request):
        if str(request.url) in refused:
            return httpx.Response(403, text="Access Denied")
        return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def paths(tmp_path):
    return {
        "archive": tmp_path / "archive",
        "inbox": tmp_path / "inbox",
        "extractions": tmp_path / "extractions",
        "candidates": tmp_path / "candidates",
        # Layout reading by the model is tested in test_llm_layout; these doubles only discover.
        "layout": "rules",
    }


def test_domains_and_links_are_restricted_to_official_sources():
    assert official_domain("https://www.Wipro.com/investors") == "wipro.com"
    with pytest.raises(ResearchError):
        official_domain("www.screener.in")
    with pytest.raises(ResearchError):
        official_domain("not a domain")

    aggregator = dict(COMPANY, website_domain="moneycontrol.com", legal_name="Wrong")
    assert [m.legal_name for m in identify(Discovery([aggregator, COMPANY]), "x")] == [
        "Synthetic Industries Limited"
    ]

    match = CompanyMatch.model_validate(dict(COMPANY, website_domain="synthetic.example"))
    links = Discovery(
        filings=[
            {"fiscal_year": 2025, "url": "https://evil.example/ar.pdf", "title": "Other site"},
            {"fiscal_year": 2025, "url": "http://synthetic.example/ar.pdf", "title": "No TLS"},
            {"fiscal_year": 2025, "url": AR25, "title": "Kept"},
            {"fiscal_year": 2025, "url": AR24, "title": "Duplicate year"},
            {"fiscal_year": 2019, "url": AR25, "title": "Not requested"},
            {
                "fiscal_year": 2024,
                "url": "https://www.bseindia.com/xml-data/corpfiling/ar.pdf",
                "title": "Exchange copy",
            },
        ]
    )
    found = find_annual_reports(links, match, [2024, 2025])
    assert found == [
        FilingLink(
            fiscal_year=2024,
            url="https://www.bseindia.com/xml-data/corpfiling/ar.pdf",
            title="Exchange copy",
        ),
        FilingLink(fiscal_year=2025, url=AR25, title="Kept"),
    ]


def test_blocked_download_opens_browser_then_inbox_completes_ingestion(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    fy25 = report(tmp_path / "fy25.pdf").read_bytes()
    opened = []
    first = ingest(
        store,
        "Synthetic",
        ["FY24", "FY25"],
        provider=Discovery(),
        client=site(fy25),
        opener=opened.append,
        **paths,
    )
    status = {f["fiscal_year"]: f["status"] for f in first["filings"]}
    assert status == {2024: "needs_manual_pdf", 2025: "imported"}
    assert opened == [AR24]
    assert first["company"]["id"] == "synind"
    fy25_item = next(f for f in first["filings"] if f["fiscal_year"] == 2025)
    candidate = json.loads(open(fy25_item["candidates"][0]).read())
    revenue = next(
        f
        for f in candidate["bundle"]["facts"]
        if f["metric"] == "revenue" and f["scope"] == "consolidated" and f["fiscal_year"] == 2025
    )
    assert revenue["raw_value"] == "1,62,990"
    assert candidate["bundle"]["documents"][0]["url"] == AR25

    # The user saves the FY24 report under a browser-chosen name; content identifies it.
    paths["inbox"].mkdir(exist_ok=True)
    report(paths["inbox"] / "download (1).pdf", year=2024)
    second = ingest(
        store, "Synthetic", ["FY24", "FY25"], provider=Refuses(), opener=opened.append, **paths
    )
    assert {f["fiscal_year"]: f["status"] for f in second["filings"]} == {
        2024: "imported",
        2025: "imported",
    }
    assert opened == [AR24]
    assert not list(paths["inbox"].glob("*.pdf"))
    assert len(list((paths["inbox"] / "processed").glob("*.pdf"))) == 1
    jobs = {j["item"]: j["status"] for j in store.jobs("synthetic")}
    assert jobs == {
        "company": "done",
        "FY2024-annual-report": "done",
        "FY2025-annual-report": "done",
    }


def test_unrelated_inbox_files_are_left_alone(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    paths["inbox"].mkdir()
    report(paths["inbox"] / "other.pdf", year=2022)
    result = ingest(
        store,
        "Synthetic",
        ["FY24"],
        provider=Discovery(),
        manual=True,
        opener=lambda url: None,
        **paths,
    )
    assert result["filings"][0]["status"] == "needs_manual_pdf"
    assert (paths["inbox"] / "other.pdf").exists()


def test_discovery_needs_a_model_or_explicit_links(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    with pytest.raises(ResearchError, match="OPENAI_API_KEY"):
        ingest(store, "Synthetic", ["FY25"], **paths)
    twins = [COMPANY, dict(COMPANY, legal_name="Synthetic Holdings", nse_symbol="SYNHLD")]
    with pytest.raises(ResearchError, match="not unique") as error:
        ingest(store, "Synthetic", ["FY25"], provider=Discovery(twins), **paths)
    assert error.value.status == "ambiguous"
    with pytest.raises(ResearchError, match="official domain"):
        ingest(
            store,
            "Synthetic",
            ["FY25"],
            urls={"FY25": "https://www.screener.in/ar.pdf"},
            manual=True,
            **paths,
        )


def test_cli_with_explicit_links_and_inbox_needs_no_model(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    args = [
        "--db",
        str(tmp_path / "db.sqlite3"),
        "ingest",
        "Synthetic Industries Limited",
        "--years",
        "FY25",
        "--url",
        f"FY25={AR25}",
        "--manual",
        "--no-browser",
        "--inbox",
        str(inbox),
        "--archive",
        str(tmp_path / "archive"),
        "--extractions",
        str(tmp_path / "extractions"),
        "--output",
        str(tmp_path / "candidates"),
    ]
    assert main(args) == 0
    waiting = json.loads(capsys.readouterr().out)
    assert waiting["status"] == "partial"
    assert "FY2025" in waiting["next_step"]
    report(inbox / "ar-2024-25.pdf")
    assert main(args) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["status"] == "ok"
    assert done["filings"][0]["status"] == "imported"


def test_remap_replaces_candidates_without_downloading(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    fy25 = report(tmp_path / "fy25.pdf").read_bytes()
    first = ingest(store, "Synthetic", ["FY25"], provider=Discovery(), client=site(fy25), **paths)
    old = first["filings"][0]["candidates"]
    again = ingest(store, "Synthetic", ["FY25"], provider=Refuses(), remap=True, **paths)
    item = again["filings"][0]
    assert item["status"] == "imported"
    assert item["candidates"] == old
    assert all(open(path).read() for path in item["candidates"])


def test_oversized_report_is_reported_per_filing_not_fatal(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    fy25 = report(tmp_path / "fy25.pdf")
    limit = fy25.stat().st_size - 1
    first = ingest(
        store,
        "Synthetic",
        ["FY25"],
        provider=Discovery(),
        client=site(fy25.read_bytes(), refused=()),
        opener=lambda url: None,
        max_bytes=limit,
        **paths,
    )
    assert first["filings"][0]["status"] == "needs_manual_pdf"
    assert "size limit" in first["filings"][0]["download_error"]

    # The saved copy is still too large: reported for that filing, left in the inbox.
    paths["inbox"].mkdir(exist_ok=True)
    saved = paths["inbox"] / "ar-2024-25.pdf"
    saved.write_bytes(fy25.read_bytes())
    second = ingest(
        store, "Synthetic", ["FY25"], provider=Refuses(), manual=True, max_bytes=limit, **paths
    )
    assert second["filings"][0]["status"] == "needs_manual_pdf"
    assert "size limit" in second["filings"][0]["inbox_error"]
    assert saved.exists()

    third = ingest(store, "Synthetic", ["FY25"], provider=Refuses(), manual=True, **paths)
    assert third["filings"][0]["status"] == "imported"
    assert "inbox_error" not in third["filings"][0]
    assert not saved.exists()


def test_remap_into_another_folder_never_deletes_the_originals(tmp_path, paths):
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    fy25 = report(tmp_path / "fy25.pdf").read_bytes()
    first = ingest(store, "Synthetic", ["FY25"], provider=Discovery(), client=site(fy25), **paths)
    (filing,) = first["filings"]
    originals = [*filing["candidates"], filing["report"], filing["queue"]]
    assert filing["queue"].endswith("synind-annual-report-fy2025-queue.json")

    elsewhere = {**paths, "candidates": tmp_path / "elsewhere"}
    again = ingest(store, "Synthetic", ["FY25"], provider=Refuses(), remap=True, **elsewhere)
    assert all(Path(p).is_file() for p in originals)
    assert again["filings"][0]["candidates"][0].startswith(str(tmp_path / "elsewhere"))


def test_downloads_report_progress_and_give_up_when_throttled(tmp_path, paths, monkeypatch):
    from regulation_analyst import acquisition
    from regulation_analyst.acquisition import SourceRequest, acquire

    clock = iter(range(0, 1000, 2))  # Each reading of the clock advances two seconds.
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(clock))
    body = b"%PDF-1.7\n" + b"x" * 400_000

    def slow_site(request):
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})

    seen = []
    with pytest.raises(ResearchError, match="Download too slow") as error:
        acquire(
            SourceRequest(id="slow", url=AR25),
            tmp_path / "archive",
            client=httpx.Client(transport=httpx.MockTransport(slow_site)),
            extra_domains=("synthetic.example",),
            on_progress=lambda size, total: seen.append((size, total)),
            max_seconds=5,
        )
    assert "throttling automated downloads" in str(error.value)
    assert seen and seen[0] == (65536, len(body))
    assert not list((tmp_path / "archive").glob(".download-*"))  # No partial file left.

    store = Store(tmp_path / "db.sqlite3", readonly=False)
    result = ingest(
        store,
        "Synthetic",
        ["FY25"],
        provider=Discovery(),
        client=httpx.Client(transport=httpx.MockTransport(slow_site)),
        opener=lambda url: None,
        download_seconds=5,
        **paths,
    )
    (filing,) = result["filings"]
    assert filing["status"] == "needs_manual_pdf"
    assert "Download too slow" in filing["download_error"]


def test_slow_downloads_finish_by_default(tmp_path, paths, monkeypatch):
    from regulation_analyst import acquisition

    clock = iter(range(0, 100_000, 60))  # A minute passes on every chunk.
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(clock))
    store = Store(tmp_path / "db.sqlite3", readonly=False)
    pdf = report(tmp_path / "fy25.pdf").read_bytes()
    result = ingest(
        store, "Synthetic", ["FY25"], provider=Discovery(), client=site(pdf, refused=()), **paths
    )
    assert result["filings"][0]["status"] == "imported"
