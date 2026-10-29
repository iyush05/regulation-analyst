"""Local command-line interface. MCP uses the same research service."""

import argparse
import json
import os
import sys
from datetime import date
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from .errors import ResearchError
from .models import Bundle
from .service import ResearchService
from .store import Store


def parser():
    root = argparse.ArgumentParser(description="Traceable research on Indian company financials")
    root.add_argument(
        "--db", default=os.environ.get("REGULATION_ANALYST_DB", "data/research.sqlite3")
    )
    root.add_argument("--json", action="store_true", help="Emit the complete structured answer")
    root.add_argument(
        "--hybrid-index", type=Path, help="Enable configured embeddings and hybrid retrieval"
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create an empty research database")
    commands.add_parser("demo", help="Import the small source-checked Infosys demonstration bundle")
    commands.add_parser(
        "load-corpus", help="Import the demo plus the official-source research expansion"
    )
    commands.add_parser("coverage", help="Inspect reviewed company coverage")
    commands.add_parser("metrics", help="Inspect supported metric definitions")
    commands.add_parser("serve", help="Run read-only MCP over stdio")
    imp = commands.add_parser(
        "import", help="Validate and atomically import a reviewed JSON bundle"
    )
    imp.add_argument("bundle", type=Path)
    ask = commands.add_parser("ask", help="Run the deterministic reference answering workflow")
    ask.add_argument("question")
    agent = commands.add_parser(
        "agent", help="Run the bounded model agent with canonical evidence validation"
    )
    agent.add_argument("question")
    agent.add_argument("--model", default=os.environ.get("REGULATION_AGENT_MODEL", ""))
    agent.add_argument("--log-dir", type=Path, default=Path("artifacts/runs"))
    agent.add_argument("--max-tool-calls", type=int, default=24)
    agent.add_argument("--max-seconds", type=float, default=180)
    index = commands.add_parser(
        "index", help="Build a real embedding index using the configured provider"
    )
    index.add_argument("--output", type=Path, default=Path("data/vectors.sqlite3"))
    table = commands.add_parser("table", help="Fetch source-backed financial facts")
    table.add_argument("company")
    table.add_argument("--years", nargs="+", required=True)
    table.add_argument("--metrics", nargs="+")
    compare = commands.add_parser("compare", help="Compare aligned annual metrics")
    compare.add_argument("metric")
    compare.add_argument("--companies", nargs="+", required=True)
    compare.add_argument("--years", nargs="+", required=True)
    for p in (ask, agent, table, compare):
        p.add_argument("--scope", choices=["consolidated", "standalone"], default="consolidated")
        p.add_argument("--basis", choices=["Ind AS", "IFRS"], default="Ind AS")
        p.add_argument(
            "--policy",
            choices=["latest_available", "originally_reported"],
            default="latest_available",
        )
        p.add_argument(
            "--known-on", help="Only sources with verified publication dates by YYYY-MM-DD"
        )
        p.add_argument(
            "--trust",
            choices=["allow_automated", "reviewed_only"],
            default="allow_automated",
            help="Exclude automated and LLM-resolved facts with reviewed_only",
        )
    calc = commands.add_parser("calculate", help="Apply a registry formula to ordered fact IDs")
    calc.add_argument("formula")
    calc.add_argument("fact_ids", nargs="+")
    search = commands.add_parser("search", help="BM25 search over reviewed filing passages")
    search.add_argument("query")
    search.add_argument("--company")
    search.add_argument("--year")
    search.add_argument("--document-type", choices=["annual_report", "transcript", "filing"])
    search.add_argument("--known-on")
    search.add_argument("--limit", type=int, default=8)
    regulations = commands.add_parser(
        "regulations", help="Search within verified temporal coverage"
    )
    regulations.add_argument("query")
    regulations.add_argument("--as-of", required=True)
    regulations.add_argument("--authority", choices=["SEBI", "RBI"])
    regulations.add_argument("--entity-type")
    regulations.add_argument("--known-on")
    source = commands.add_parser("source", help="Resolve a source locator")
    source.add_argument("evidence_id")
    extract = commands.add_parser(
        "extract", help="Extract a local PDF into a pending review artifact"
    )
    extract.add_argument("pdf", type=Path)
    extract.add_argument("--output", type=Path, default=Path("artifacts/extractions"))
    extract.add_argument("--pages", nargs="+", type=int)
    extract.add_argument(
        "--ocr", action="store_true", help="OCR selected pages using installed Tesseract data"
    )
    extract.add_argument("--language", default="eng")
    extract.add_argument(
        "--table-strategy", choices=["lines", "lines_strict", "text"], default="lines"
    )
    acquire = commands.add_parser(
        "acquire", help="Archive one official PDF from a manifest or local file"
    )
    acquire.add_argument("manifest", type=Path)
    acquire.add_argument("--archive", type=Path, default=Path("data/sources"))
    acquire.add_argument("--local-pdf", type=Path)
    mapping = commands.add_parser(
        "map-table", help="Map extracted cells into pending fact candidates"
    )
    mapping.add_argument("extraction", type=Path)
    mapping.add_argument("mapping", type=Path)
    mapping.add_argument("--output", type=Path, required=True)
    review = commands.add_parser("review", help="Record your review and write an importable bundle")
    review.add_argument("candidate", type=Path)
    review.add_argument("--reviewer", required=True)
    review.add_argument(
        "--method",
        choices=["source_text_crosscheck", "visual_review", "human_review"],
        required=True,
    )
    review.add_argument("--reviewed-on", type=date.fromisoformat, required=True)
    review.add_argument("--expected-digest", required=True)
    review.add_argument("--output", type=Path, required=True)
    evaluation = commands.add_parser(
        "evaluate", help="Run the explicitly labeled development smoke benchmark"
    )
    evaluation.add_argument("--benchmark", type=Path)
    evaluation.add_argument("--output", type=Path)
    experiment = commands.add_parser(
        "experiment", help="Run a provenance-rich comparative benchmark"
    )
    experiment.add_argument("--benchmark", type=Path)
    experiment.add_argument(
        "--mode", choices=["flat_rag", "layout_rag", "fixed_tools", "agent"], default="fixed_tools"
    )
    experiment.add_argument("--split", choices=["development", "held_out"], default="development")
    experiment.add_argument("--include-drafts", action="store_true")
    experiment.add_argument("--model", default=os.environ.get("REGULATION_AGENT_MODEL", ""))
    experiment.add_argument("--max-cases", type=int)
    experiment.add_argument("--output", type=Path, default=Path("artifacts/experiment.json"))
    experiment.add_argument("--archive", type=Path, default=Path("data/sources"))
    experiment.add_argument("--artifacts", type=Path, default=Path("artifacts/extractions"))
    parser_eval = commands.add_parser(
        "evaluate-parser", help="Compare extracted cells with independent gold labels"
    )
    parser_eval.add_argument("extraction", type=Path)
    parser_eval.add_argument("labels", type=Path)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in ("init", "demo", "load-corpus", "import"):
            store = Store(args.db, readonly=False)
            if args.command == "init":
                payload = {
                    "status": "ok",
                    "database": str(store.path),
                    "corpus_version": store.version,
                }
            else:
                path = (
                    files("regulation_analyst").joinpath("fixtures/demo.json")
                    if args.command in ("demo", "load-corpus")
                    else args.bundle
                )
                bundle = Bundle.model_validate_json(path.read_text())
                payload = {"status": "ok", **store.import_bundle(bundle)}
                if args.command == "load-corpus":
                    expansion = files("regulation_analyst").joinpath(
                        "fixtures/research-expansion.json"
                    )
                    payload = {
                        "status": "ok",
                        "demo": payload,
                        **store.import_bundle(Bundle.model_validate_json(expansion.read_text())),
                    }
        elif args.command == "evaluate-parser":
            from .experiments import evaluate_parser

            payload = {
                "status": "ok",
                **evaluate_parser(
                    json.loads(args.extraction.read_text()), json.loads(args.labels.read_text())
                ),
            }
        elif args.command == "acquire":
            from .acquisition import SourceRequest, acquire

            payload = {
                "status": "ok",
                **acquire(
                    SourceRequest.model_validate_json(args.manifest.read_text()),
                    args.archive,
                    local_pdf=args.local_pdf,
                ),
            }
        elif args.command in ("map-table", "review"):
            from .review import MappingPlan, approve_candidates, build_candidates

            if args.command == "map-table":
                payload = build_candidates(
                    args.extraction, MappingPlan.model_validate_json(args.mapping.read_text())
                )
            else:
                bundle = approve_candidates(
                    json.loads(args.candidate.read_text()),
                    reviewer=args.reviewer,
                    method=args.method,
                    reviewed_on=args.reviewed_on,
                    expected_digest=args.expected_digest,
                )
                payload = bundle.model_dump(mode="json")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as output:
                output.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            payload = {
                "status": "review_required" if args.command == "map-table" else "ok",
                "output": str(args.output),
                "candidate_sha256": payload.get("candidate_sha256"),
                "diagnostics": payload.get("diagnostics", []),
            }
        elif args.command == "extract":
            from .ingestion import extract_pdf

            artifact = extract_pdf(
                args.pdf,
                args.output,
                args.pages,
                ocr=args.ocr,
                language=args.language,
                table_strategy=args.table_strategy,
            )
            payload = {
                key: artifact[key]
                for key in ("status", "artifact_directory", "source_sha256", "page_count")
            }
            payload["extracted_pages"] = len(artifact["pages"])
        elif args.command == "serve":
            from .mcp_server import create_server

            create_server(args.db, retriever=make_retriever(Store(args.db), args.hybrid_index)).run(
                transport="stdio"
            )
            return 0
        else:
            store = Store(args.db)
            service = ResearchService(store, retriever=make_retriever(store, args.hybrid_index))
            if args.command == "experiment":
                from .experiments import Benchmark, run_experiment
                from .providers import OpenAIProvider

                path = args.benchmark or files("regulation_analyst").joinpath(
                    "fixtures/research-benchmark.json"
                )
                report = run_experiment(
                    service,
                    Benchmark.model_validate_json(path.read_text()),
                    mode=args.mode,
                    provider=OpenAIProvider(model=args.model)
                    if args.mode != "fixed_tools"
                    else None,
                    split=args.split,
                    include_drafts=args.include_drafts,
                    output=args.output,
                    archive=args.archive,
                    artifacts=args.artifacts,
                    max_cases=args.max_cases,
                )
                print(
                    json.dumps(
                        {key: value for key, value in report.items() if key != "results"}, indent=2
                    )
                )
                return (
                    0
                    if report["cases_blocked"] == 0
                    and report["automatic_checks_passed"] == report["cases_executed"]
                    else 1
                )
            if args.command == "index":
                from .providers import embedding_provider
                from .retrieval import build_index

                payload = build_index(store, args.output, embedding_provider())
                print(json.dumps(payload, indent=2))
                return 0
            if args.command == "agent":
                from .agent import Budgets, Selection, run_agent
                from .providers import OpenAIProvider

                result = run_agent(
                    service,
                    args.question,
                    OpenAIProvider(model=args.model),
                    budgets=Budgets(
                        max_tool_calls=args.max_tool_calls, max_seconds=args.max_seconds
                    ),
                    log_dir=args.log_dir,
                    selection=Selection(
                        scope=args.scope,
                        basis=args.basis,
                        policy=args.policy,
                        known_on=args.known_on,
                        trust=args.trust,
                    ),
                )
                print(
                    result.model_dump_json(indent=2)
                    if args.json
                    else result.data.get("answer", result.message)
                )
                return 0 if result.status in ("ok", "partial") else 2
            if args.command == "evaluate":
                from .evaluation import evaluate

                benchmark = args.benchmark or files("regulation_analyst").joinpath(
                    "fixtures/benchmark.json"
                )
                payload = evaluate(service, benchmark)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return 0 if payload["failed"] == 0 else 1
            operations = {
                "coverage": "list_companies",
                "metrics": "list_metrics",
                "ask": "answer_question",
                "table": "get_table",
                "compare": "compare_companies",
                "calculate": "calculate",
                "search": "search_filings",
                "regulations": "search_regulations",
                "source": "get_source",
            }
            kwargs = {
                key: value
                for key, value in vars(args).items()
                if key not in ("command", "db", "json", "hybrid_index")
            }
            result = service.call(operations[args.command], **kwargs)
            payload = result.model_dump(mode="json")
            if args.command == "ask" and not args.json:
                print(result.data.get("answer", result.message))
                return 0 if result.status in ("ok", "partial") else 2
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload.get("status") in ("ok", "partial", "review_required") else 2
    except (ResearchError, ValidationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": getattr(exc, "status", "invalid_request"), "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


def make_retriever(store, index):
    if index is None:
        return None
    from .providers import CrossEncoderReranker, embedding_provider
    from .retrieval import HybridRetriever

    reranker_path = os.environ.get("REGULATION_RERANKER_PATH")
    reranker = (
        CrossEncoderReranker(reranker_path, os.environ.get("REGULATION_RERANKER_REVISION", ""))
        if reranker_path
        else None
    )
    return HybridRetriever(store, index, embedding_provider(), reranker)


if __name__ == "__main__":
    raise SystemExit(main())
