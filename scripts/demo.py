"""Create a reproducible, offline demonstration using the reviewed research corpus."""

import json
from importlib.resources import files
from pathlib import Path

from regulation_analyst.models import Bundle
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


def main():
    root = Path(__file__).resolve().parents[1]
    store = Store(root / "data/research.sqlite3", readonly=False)
    for name in ("demo.json", "research-expansion.json"):
        store.import_bundle(
            Bundle.model_validate_json(
                files("regulation_analyst").joinpath("fixtures", name).read_text()
            )
        )
    service = ResearchService(Store(store.path))
    question = (
        "How did Infosys operating margin change from FY23 to FY25 and what did management say?"
    )
    answer = service.answer_question(question)
    comparison = service.answer_question("Compare Infosys and TCS net margin FY23 to FY25")
    output = root / "artifacts/demo"
    output.mkdir(parents=True, exist_ok=True)
    (output / "research.json").write_text(
        json.dumps(
            {
                "question": question,
                "answer": answer.model_dump(mode="json"),
                "comparison": comparison.model_dump(mode="json"),
            },
            indent=2,
        )
        + "\n"
    )
    (output / "research.md").write_text(
        question + "\n\n" + answer.data["answer"] + "\n\n" + comparison.data["answer"] + "\n"
    )
    print(answer.data["answer"])
    print(f"\nSaved demo artifacts in {output}")


if __name__ == "__main__":
    main()
