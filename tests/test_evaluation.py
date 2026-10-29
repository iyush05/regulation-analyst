import json
from importlib.resources import files

from regulation_analyst.evaluation import evaluate


def test_development_benchmark_passes_without_claiming_held_out_accuracy(service):
    report = evaluate(service, files("regulation_analyst").joinpath("fixtures/benchmark.json"))
    assert report["questions"] == 32
    assert report["failed"] == 0, [r for r in report["results"] if not r["passed"]]
    assert report["numeric_slots"]["coverage"] == 1
    assert "Development smoke" in report["limitations"]


def test_numeric_error_and_missing_answer_are_scored_separately(service, tmp_path):
    specification = {
        "name": "synthetic evaluator check",
        "purpose": "test scorer",
        "cases": [
            {
                "id": "wrong-number",
                "category": "numeric",
                "operation": "get_table",
                "arguments": {"company": "Infosys", "years": [2025], "metrics": ["revenue"]},
                "expected_status": "ok",
                "checks": [{"path": "data.facts.0.value", "decimal": "999"}],
            },
            {
                "id": "missing-number",
                "category": "numeric",
                "operation": "get_table",
                "arguments": {"company": "TCS", "years": [2025], "metrics": ["revenue"]},
                "expected_status": "ok",
                "checks": [{"path": "data.facts.0.value", "decimal": "999"}],
            },
        ],
    }
    path = tmp_path / "checks.json"
    path.write_text(json.dumps(specification))
    report = evaluate(service, path)
    assert report["failed"] == 2
    assert report["numeric_slots"] == {
        "expected": 2,
        "present": 1,
        "correct": 0,
        "accuracy_when_present": 0,
        "coverage": 0.5,
    }
