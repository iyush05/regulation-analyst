"""The agent adding a missing company through ingest_company. Controlled model and HTTP."""

import json

import httpx
import pytest
from test_autoextract import report
from test_pipeline import AR25, Discovery

from regulation_analyst.agent import run_agent, tool_schemas
from regulation_analyst.answering import answer as ask
from regulation_analyst.metrics import calculate
from regulation_analyst.models import Company
from regulation_analyst.pipeline import agent_ingestor
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store

QUESTION = "What was Synthetic Industries' net margin in FY25?"


class Model:
    """Scripted tool calls; callables build arguments from the corpus at call time, as a real
    model would read IDs from earlier tool results."""

    identity = "controlled-test-double:not-a-live-model"

    def __init__(self, store, steps):
        self.store, self.steps, self.messages = store, iter(steps), []

    def respond(self, messages, tools, **kwargs):
        self.messages, self.tools = list(messages), [t["name"] for t in tools]
        name, arguments = next(self.steps)
        if callable(arguments):
            arguments = arguments(self.store)
        return {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "name": name,
                    "call_id": str(len(messages)),
                    "arguments": json.dumps(arguments),
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


def done(**updates):
    return {
        "fact_ids": [],
        "calculation_ids": [],
        "passage_ids": [],
        "provision_ids": [],
        "gaps": [],
    } | updates


def margin_inputs(store):
    return [store.select_fact("synind", metric, 2025).id for metric in ("profit_owners", "revenue")]


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / "db.sqlite3"
    Store(database, readonly=False)
    pdf = report(tmp_path / "ar.pdf").read_bytes()
    paths = {
        "archive": tmp_path / "archive",
        "inbox": tmp_path / "inbox",
        "extractions": tmp_path / "extractions",
        "candidates": tmp_path / "candidates",
    }

    def ingestor(refused=()):
        def handler(request):
            if str(request.url) in refused:
                return httpx.Response(403, text="Access Denied")
            return httpx.Response(200, content=pdf)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return agent_ingestor(database, Discovery(), client=client, **paths)

    return database, ingestor


def test_agent_ingests_a_missing_company_then_answers_from_it(setup, tmp_path):
    database, ingestor = setup
    service = ResearchService(Store(database))
    model = Model(
        service.store,
        [
            ("check_coverage", {"company": "Synthetic Industries", "years": ["FY25"]}),
            ("ingest_company", {"company": "Synthetic Industries", "years": ["FY25"]}),
            (
                "get_table",
                {
                    "company": "Synthetic Industries",
                    "years": ["FY25"],
                    "metrics": ["revenue", "profit_owners"],
                },
            ),
            (
                "calculate",
                lambda store: {"formula": "net_margin", "fact_ids": margin_inputs(store)},
            ),
            (
                "finish",
                lambda store: done(
                    calculation_ids=[calculate(store, "net_margin", margin_inputs(store))["id"]]
                ),
            ),
        ],
    )
    result = run_agent(service, QUESTION, model, log_dir=tmp_path / "runs", ingestor=ingestor())
    assert result.status == "ok", result.message
    assert "ingest_company" in model.tools
    answer = result.data["answer"]
    assert "| synind | net margin | 16.81% [1] |" in answer  # 27,400 / 1,62,990
    assert "unreviewed: automated extraction" in answer
    log = json.loads(open(result.data["run_log"]).read())
    (ingestion,) = log["ingestions"]
    assert ingestion["status"] == "ok" and ingestion["seconds"] >= 0
    # Coverage was checked before ingestion, when the company was unknown.
    assert log["trace"][0]["result"]["data"]["covered"] is False


def test_ingestion_is_not_offered_unless_enabled(setup, tmp_path):
    database, _ = setup
    service = ResearchService(Store(database))
    assert "ingest_company" not in {t["name"] for t in tool_schemas()}
    assert "ingest_company" in {t["name"] for t in tool_schemas(ingest=True)}
    model = Model(
        service.store,
        [("ingest_company", {"company": "Synthetic Industries", "years": ["FY25"]})],
    )
    result = run_agent(service, QUESTION, model, log_dir=tmp_path / "runs")
    assert result.status == "invalid_request"
    assert "unauthorized tool" in result.message
    assert "ingest_company" not in model.tools


def test_ingestion_years_must_come_from_the_question(setup, tmp_path):
    database, ingestor = setup
    service = ResearchService(Store(database))
    model = Model(
        service.store,
        [("ingest_company", {"company": "Synthetic Industries", "years": ["FY21"]})],
    )
    result = run_agent(service, QUESTION, model, log_dir=tmp_path / "runs", ingestor=ingestor())
    assert "years must come from the question" in result.message


def test_blocked_download_becomes_a_specific_gap(setup, tmp_path):
    database, ingestor = setup
    service = ResearchService(Store(database))
    model = Model(
        service.store,
        [
            ("ingest_company", {"company": "Synthetic Industries", "years": ["FY25"]}),
            ("finish", done(gaps=["missing_financial_data"])),
        ],
    )
    result = run_agent(
        service,
        QUESTION,
        model,
        log_dir=tmp_path / "runs",
        ingestor=ingestor(refused=(AR25,)),
    )
    assert result.status == "not_found"
    assert "could not be downloaded automatically: save " + AR25 in result.data["answer"]


def test_coverage_reports_years_and_trust(setup):
    database, ingestor = setup
    ingestor()("Synthetic Industries", ["FY25"])
    service = ResearchService(Store(database))
    coverage = service.check_coverage("Synthetic Industries", ["FY25", "FY23"])
    assert coverage.status == "partial"
    assert coverage.data["missing_years"] == [2023]
    fy25 = coverage.data["years"][2025]["consolidated Ind AS"]
    assert "revenue" in fy25["metrics"] and fy25["trust"] == {"automated": len(fy25["metrics"])}
    assert service.check_coverage("Unknown Co").data["covered"] is False


def test_company_names_tolerate_legal_suffixes():
    names = Company(id="wipro", name="Wipro Limited", aliases=["WIPRO"]).names
    assert names == ["wipro", "Wipro Limited", "Wipro", "WIPRO"]
    assert Company(id="a", name="Acme Pvt. Ltd.").names[2] == "Acme"


def test_ask_suggests_the_ingest_command(service):
    found = ask(
        service,
        "Infosys revenue FY19",
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on=None,
    )
    assert 'regulation-analyst ingest "Infosys Limited" --years FY19' in found.data["answer"]
