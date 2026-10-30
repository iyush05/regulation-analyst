"""HTTP API: auth, read endpoints, background jobs, uploads, page images. Synthetic data."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from test_agent_ingest import Model, done
from test_autoextract import report
from test_pipeline import AR25

from regulation_analyst.api import Settings, create_app
from regulation_analyst.errors import ResearchError

TOKEN = "test-token-0123456789"


def no_model():
    raise ResearchError("invalid_request", "Set OPENAI_API_KEY and an explicit model name")


@pytest.fixture
def api(tmp_path, store):
    pdf = report(tmp_path / "ar.pdf").read_bytes()
    refused = set()

    def handler(request):
        if str(request.url) in refused:
            return httpx.Response(403, text="Access Denied")
        return httpx.Response(200, content=pdf)

    settings = Settings(
        database=store.path,
        token=TOKEN,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
    )

    def build(provider_factory=no_model):
        app = create_app(
            settings,
            provider_factory=provider_factory,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        return client

    build.refused, build.pdf = refused, pdf
    return build


def wait(client, job):
    for _ in range(600):
        current = client.get(f"/api/jobs/{job['id']}").json()
        if current["status"] in ("done", "failed"):
            return current
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_token_is_required_except_for_health(api):
    client = api()
    assert client.get("/api/health").json()["status"] == "ok"
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/companies").status_code == 401
    wrong = anonymous.get("/api/companies", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert client.get("/api/companies").status_code == 200


def test_read_endpoints_return_rendered_answers_and_coverage(api):
    client = api()
    asked = client.post(
        "/api/ask", json={"question": "Infosys operating margin FY24 to FY25"}
    ).json()
    assert asked["status"] == "ok"
    assert "| infosys | operating margin |" in asked["data"]["answer"]
    coverage = client.get("/api/companies/Infosys/coverage", params={"years": ["FY25"]}).json()
    assert coverage["data"]["covered"] is True
    assert (
        client.post(
            "/api/compare", json={"metric": "revenue", "companies": ["Infosys"], "years": ["FY25"]}
        ).status_code
        == 422
    )
    assert client.post("/api/ask", json={"question": ""}).status_code == 422


def test_ingest_job_imports_and_reports_progress(api):
    client = api()
    job = client.post(
        "/api/ingest",
        json={"company": "Synthetic Industries Limited", "years": ["FY25"], "urls": {"FY25": AR25}},
    )
    assert job.status_code == 202
    finished = wait(client, job.json())
    assert finished["status"] == "done", finished["error"]
    assert finished["result"]["filings"][0]["status"] == "imported"
    assert {p["item"] for p in finished["progress"]} >= {"company", "FY2025-annual-report"}
    assert client.get("/api/companies/Synthetic Industries/coverage").json()["status"] == "ok"


def test_refused_download_resumes_from_an_upload_and_pages_render(api):
    client = api()
    api.refused.add(AR25)
    request = {"company": "Synthetic Industries Limited", "years": ["FY25"], "urls": {"FY25": AR25}}
    blocked = wait(client, client.post("/api/ingest", json=request).json())
    assert blocked["result"]["filings"][0]["status"] == "needs_manual_pdf"

    not_pdf = client.post(
        "/api/ingest/upload",
        data={"company": request["company"], "years": "FY25"},
        files={"file": ("ar.pdf", b"<html>challenge</html>", "application/pdf")},
    )
    assert not_pdf.status_code == 422
    uploaded = client.post(
        "/api/ingest/upload",
        data={"company": request["company"], "years": "FY25"},
        files={"file": ("tata ar 2024-25.pdf", api.pdf, "application/pdf")},
    )
    resumed = wait(client, uploaded.json())
    assert resumed["result"]["filings"][0]["status"] == "imported", resumed

    table = client.post("/api/ask", json={"question": "Synthetic Industries revenue FY25"}).json()
    evidence_id = table["data"]["rows"][0]["facts"][0]["evidence_id"]
    image = client.get(f"/api/sources/{evidence_id}/page.png")
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    reviewed = client.get("/api/sources/ev-infosys-indas-2025-revenue/page.png")
    assert reviewed.status_code == 404  # Remote reference only; no archived copy.


def test_agent_runs_as_a_job_and_needs_a_configured_model(api, store):
    assert api().post("/api/agent", json={"question": "Infosys revenue FY25"}).status_code == 503

    model = Model(
        store,
        [
            ("get_table", {"company": "Infosys", "years": ["FY25"], "metrics": ["revenue"]}),
            ("finish", done(fact_ids=["infosys-indas-2025-revenue"])),
        ],
    )
    client = api(provider_factory=lambda: model)
    finished = wait(
        client, client.post("/api/agent", json={"question": "Infosys revenue FY25"}).json()
    )
    assert finished["status"] == "done", finished["error"]
    assert "₹1,62,990 cr" in finished["result"]["data"]["answer"]
