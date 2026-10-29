import json
from importlib.resources import files

import pytest
from pydantic import ValidationError

from regulation_analyst.errors import ResearchError
from regulation_analyst.experiments import (
    Benchmark,
    Case,
    evaluate_parser,
    run_experiment,
    score_case,
    wilson,
)
from regulation_analyst.models import Bundle
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


def one_case(**updates):
    base = {
        "id": "one",
        "question": "Infosys revenue FY25",
        "category": "fact_lookup",
        "split": "development",
        "source_group": "infosys-source",
        "review_status": "source_crosschecked",
        "reviewer": "test labels",
        "expected_status": "ok",
        "answerable": True,
        "company_ids": ["infosys"],
        "gold_numbers": [
            {
                "id": "revenue",
                "value": "162990",
                "unit": "INR_crore",
                "fact_id": "infosys-indas-2025-revenue",
                "evidence_ids": ["ev-infosys-indas-2025-revenue"],
                "derivation": "Independently inspected source cell",
                "tolerance": "0",
            }
        ],
    }
    return Case.model_validate({**base, **updates})


def benchmark(cases):
    return Benchmark(
        name="Controlled protocol evaluation", purpose="Unit tests, not model quality", cases=cases
    )


def test_score_separates_numeric_presence_accuracy_and_citations(store):
    result = {
        "status": "ok",
        "data": {
            "numbers": [
                {
                    "slot_id": "revenue",
                    "value": "162990",
                    "unit": "INR_crore",
                    "evidence_ids": ["invented"],
                }
            ]
        },
    }
    score = score_case(store, one_case(), result)
    assert score["numeric_slots"][0]["correct"]
    assert score["citation_resolution"] == 0
    assert not score["automatic_checks_passed"]
    result["data"]["numbers"][0].update(value="NaN", evidence_ids=["ev-infosys-indas-2025-revenue"])
    score = score_case(store, one_case(), result)
    assert score["numeric_slots"][0]["present"]
    assert not score["numeric_slots"][0]["correct"]
    assert (
        score_case(store, one_case(), {"status": "not_found", "data": {}})["numeric_slots"][0][
            "present"
        ]
        is False
    )


def test_split_leakage_and_unreviewed_holdout_are_rejected(service, tmp_path):
    first, held_out = one_case(), one_case(id="held", split="held_out")
    with pytest.raises(ValidationError, match="leak"):
        benchmark([first, held_out])
    with pytest.raises(ResearchError, match="independently reviewed"):
        run_experiment(
            service, benchmark([held_out]), split="held_out", output=tmp_path / "report.json"
        )


def test_fixed_tool_experiment_and_all_research_labels(store, tmp_path):
    writable = Store(store.path, readonly=False)
    fixtures = files("regulation_analyst").joinpath("fixtures")
    writable.import_bundle(
        Bundle.model_validate_json(fixtures.joinpath("research-expansion.json").read_text())
    )
    spec = Benchmark.model_validate_json(fixtures.joinpath("research-benchmark.json").read_text())
    assert len(spec.cases) >= 150
    report = run_experiment(ResearchService(writable), spec, output=tmp_path / "report.json")
    assert report["cases_executed"] == len(spec.cases)
    assert report["automatic_checks_passed"] == len(spec.cases)
    assert report["numeric"]["present"] == report["numeric"]["correct"]
    assert report["usage"] is None
    assert (tmp_path / "report.md").is_file()
    narrative = [r for r in report["results"] if r["score"]["required_claims"]]
    assert all(r["score"]["end_to_end_correct"] is None for r in narrative)


def test_live_conditions_fail_explicitly_without_model_or_archives(service, tmp_path):
    with pytest.raises(ResearchError, match="configured live model"):
        run_experiment(
            service, benchmark([one_case()]), mode="agent", output=tmp_path / "report.json"
        )

    class NeverCalled:
        identity = "controlled-test-double"

        def respond(self, *args, **kwargs):
            raise AssertionError("Do not call a model without source archives")

    report = run_experiment(
        service,
        benchmark([one_case()]),
        mode="flat_rag",
        provider=NeverCalled(),
        archive=tmp_path / "archives",
        artifacts=tmp_path / "extractions",
        output=tmp_path / "report.json",
    )
    assert report["cases_blocked"] == 1
    assert report["cases_executed"] == 0
    assert report["automatic_pass_rate"] is None
    assert report["numeric"]["expected"] == 1
    assert report["numeric"]["coverage"] == 0


def test_parser_and_retrieval_metrics_are_separate(store):
    artifact = {
        "source_sha256": "test",
        "parser": "controlled",
        "parser_version": "1",
        "pages": [
            {"pdf_page": 1, "tables": [{"id": "p1-t1", "rows": [["2024", "2025"], ["90", "100"]]}]}
        ],
    }
    labels = [
        {"pdf_page": 1, "table_id": "p1-t1", "row": 1, "column": 1, "raw_value": "100"},
        {"pdf_page": 1, "table_id": "p1-t1", "row": 1, "column": 0, "raw_value": "100"},
    ]
    assert evaluate_parser(artifact, labels)["cell_exact_match"] == 0.5
    result = {
        "status": "not_found",
        "data": {},
        "retrieved_pages": [
            {"document_id": "wrong", "pdf_page": 1},
            {"document_id": "infosys-ar25", "pdf_page": 346},
        ],
    }
    retrieval = score_case(store, one_case(), result)["retrieval"]
    assert retrieval["page_recall_at_k"] == 1
    assert retrieval["reciprocal_rank"] == 0.5
    assert retrieval["complete_evidence_set"]
    assert wilson(0, 0) is None


def test_successful_rag_protocol_uses_same_pages_and_different_representations(
    service, tmp_path, monkeypatch
):
    from regulation_analyst import experiments

    pages = [
        {
            "document_id": "infosys-ar25",
            "pdf_page": 346,
            "evidence_ids": ["ev-infosys-indas-2025-revenue"],
            "source_sha256": "test-only",
            "text": "Revenue 162990 FY2025",
            "tables": [{"rows": [["FY", "Revenue"], ["2025", "162990"]]}],
        }
    ]
    monkeypatch.setattr(experiments, "rag_pages", lambda *args: pages)

    class ControlledRAG:
        identity = "controlled-test-double:not-live"

        def __init__(self):
            self.contexts = []

        def respond(self, messages, tools, **kwargs):
            self.contexts.append(json.loads(messages[1]["content"])["sources"])
            answer = {
                "status": "ok",
                "numbers": [
                    {
                        "slot_id": "revenue",
                        "value": "162990",
                        "unit": "INR_crore",
                        "evidence_ids": ["ev-infosys-indas-2025-revenue"],
                    }
                ],
                "narrative": "Controlled response",
                "evidence_ids": [],
            }
            return {
                "output": [
                    {
                        "type": "function_call",
                        "name": "submit_answer",
                        "arguments": json.dumps(answer),
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            }

    provider = ControlledRAG()
    for mode in ("flat_rag", "layout_rag"):
        report = run_experiment(
            service,
            benchmark([one_case()]),
            mode=mode,
            provider=provider,
            output=tmp_path / (mode + ".json"),
        )
        assert report["automatic_checks_passed"] == 1
        assert report["usage"]["total_tokens"] == 30
    assert "Structured tables" not in provider.contexts[0][0]["content"]
    assert "Structured tables" in provider.contexts[1][0]["content"]
