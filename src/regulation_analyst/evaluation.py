"""Small development regression runner. It does not claim semantic faithfulness scores."""

import json
import statistics
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from .service import ResearchService


def _lookup(payload, path: str):
    for key in path.split("."):
        payload = payload[int(key)] if isinstance(payload, list) else payload[key]
    return payload


def evaluate(service: ResearchService, benchmark: str | Path) -> dict:
    specification = json.loads(Path(benchmark).read_text())
    results, latencies = [], []
    numeric_total = numeric_present = numeric_correct = 0
    for case in specification["cases"]:
        start = perf_counter()
        result = service.call(case["operation"], **case["arguments"]).model_dump(mode="json")
        elapsed = (perf_counter() - start) * 1000
        latencies.append(elapsed)
        failures = []
        if result["status"] != case["expected_status"]:
            failures.append(f"status: expected {case['expected_status']}, got {result['status']}")
        for check in case.get("checks", []):
            numeric = "decimal" in check
            if numeric:
                numeric_total += 1
            try:
                actual = _lookup(result, check["path"])
                if numeric:
                    numeric_present += 1
                    expected = Decimal(check["decimal"])
                    passed = abs(Decimal(str(actual)) - expected) <= Decimal(
                        check.get("tolerance", "0")
                    )
                    numeric_correct += int(passed)
                else:
                    passed = actual == check["equals"]
                if not passed:
                    failures.append(f"{check['path']}: unexpected value {actual!r}")
            except (KeyError, IndexError, TypeError, ValueError, ArithmeticError):
                failures.append(f"{check['path']}: missing or invalid result")
        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "passed": not failures,
                "failures": failures,
                "latency_ms": round(elapsed, 3),
                "actual_status": result["status"],
            }
        )
    passed = sum(item["passed"] for item in results)
    return {
        "benchmark": specification["name"],
        "purpose": specification["purpose"],
        "corpus_version": service.store.version,
        "questions": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "numeric_slots": {
            "expected": numeric_total,
            "present": numeric_present,
            "correct": numeric_correct,
            "accuracy_when_present": numeric_correct / numeric_present if numeric_present else None,
            "coverage": numeric_present / numeric_total if numeric_total else None,
        },
        "latency_ms": {"median": round(statistics.median(latencies), 3) if latencies else None},
        "limitations": "Development smoke cases only; no held-out, retrieval-recall, "
        "or semantic-faithfulness claim.",
        "results": results,
    }
