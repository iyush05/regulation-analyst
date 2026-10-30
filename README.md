# Regulation Analyst

Source-backed research on Indian company financials and dated financial regulations.
Financial answers use immutable table facts, Decimal calculations, and page citations.
The application runs locally through a CLI or a read-only MCP server.

The implementation includes a bounded model agent, hybrid retrieval, reviewed table imports,
regulation version resolution, and four experiment runners. The current corpus and labels
are source-crosschecked development material. **Live model quality, independent review, and
complete three-company coverage are not established.** See the [completion matrix](docs/COMPLETION_STATUS.md).

## Quick start

Python 3.13 is the tested runtime. The prepared workspace already has `.venv` installed:

```sh
.venv/bin/regulation-analyst load-corpus
.venv/bin/regulation-analyst ask "How did Infosys operating margin change from FY23 to FY25 and what did management say?"
.venv/bin/regulation-analyst ask "Compare Infosys and TCS net margin FY23 to FY25"
.venv/bin/python scripts/demo.py
```

For a new environment:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
```

`uv sync` is also supported when package resolution is available. `requirements-dev.lock`
records the tested environment; it is not a universal cross-platform `uv.lock`.

Global options go before the command: `--db`, `--json`, `--hybrid-index`. The default database
is `data/research.sqlite3`; `REGULATION_ANALYST_DB` can override it. `demo` imports the original
14-fact regression fixture. `load-corpus` also adds the research expansion, for 33 financial facts,
3 management passages, and 3 narrowly dated regulatory provisions across 10 documents.

## What works

- **Ingestion:** official PDF acquisition or local input, SHA-256 archives, layout-aware
  PyMuPDF tables and cell boxes, page renders, configurable table strategy, optional Tesseract OCR.
- **Review:** declarative row/year/unit mappings, optional total reconciliations, pending candidates,
  digest-bound review decisions, and atomic imports. Extraction never silently promotes a fact.
- **Financial data:** explicit company, period, scope, basis, original units, definitions,
  restatements, and publication cutoffs. Monetary values normalize to INR crore.
- **Calculations:** operating/net margins, growth, CAGR, margin change in points/basis points,
  and ROE from opening/closing owners' equity. Every calculation preserves its inputs.
- **Retrieval:** filtered BM25; optional real OpenAI/local embeddings, persistent SQLite cosine
  index, reciprocal-rank fusion, and local cross-encoder reranking. Stale indexes are rejected.
- **Answers:** deterministic reference workflow or bounded OpenAI Responses tool agent.
  Agent output selects returned evidence IDs; the server renders facts, recomputed calculations,
  and reviewed narrative records. Model-authored numerical prose is not accepted.
- **Regulations:** effective dates, verified-through bounds, publication cutoffs, explicit
  clause replacement chains, applicability filters, and conflicting-version rejection.
- **Integration:** nine read-only MCP tools shared with the CLI; no arbitrary shell/SQL tools.
- **Evaluation:** 32 smoke cases and 168 development research cases, parser-cell scoring,
  retrieval metrics, numeric coverage/accuracy, citation checks, and A/B/C/D runners.

## Corpus coverage

| Company / authority | Included evidence | Explicit gaps |
|---|---|---|
| Infosys | Ind AS revenue, operating profit, owners' and total profit FY23–FY25; owners' equity FY23–FY25; IFRS revenue/profit FY23–FY25; FY25 call commentary | Opening equity for FY23 ROE; earlier call explanations; verified publication dates for PDFs |
| TCS | Ind AS revenue, owners' and total profit, owners' equity FY23–FY25; FY25 management press release | Operating-profit definition alignment; earlier calls; opening equity for FY23 ROE |
| HCLTech | FY25 management press-release summary and acquisition manifests | Financial PDF ingestion blocked by source access in this environment |
| SEBI | Historical commencement and material-event deadline clauses verified for 2023-07-15 | Subsequent amendments and current-law coverage |
| RBI | KYC amendment commencement verified for 2025-06-12 | Complete KYC history and current-law coverage |

PDF values are source-text crosschecked, **not independently human-audited**. Official PDFs
could be inspected through browsing but not downloaded to the local shell; existing records
therefore disclose `remote_reference_only`. Signature dates are not invented publication dates.
TCS reported FY24 owners' profit is retained; adjusted figures excluding its legal settlement
are not substituted. [Source audit](docs/SOURCES.md).

## Model and search configuration

The fixed workflow and BM25 require no API key. Export configuration from your own environment;
[.env.example](.env.example) documents the variables. The program does not auto-load `.env`.

```sh
# Set OPENAI_API_KEY and REGULATION_AGENT_MODEL outside the command/history as appropriate.
.venv/bin/regulation-analyst --json agent "Infosys operating margin FY24 to FY25 and management explanation"

# Explicit embedding calls; index construction can incur provider charges.
export REGULATION_EMBEDDING_PROVIDER=openai
export REGULATION_EMBEDDING_MODEL=text-embedding-3-small
.venv/bin/regulation-analyst index --output data/vectors.sqlite3
.venv/bin/regulation-analyst --hybrid-index data/vectors.sqlite3 search "profitability pressure" --company Infosys --year FY25
```

For local embeddings/reranking, install `.[local-search]`, supply already-downloaded model
directories, and configure their revisions. Model directory bytes are fingerprinted. Remote
model code and implicit downloads are disabled. Missing weights fail explicitly; no pseudo
embeddings replace them. A remote embedding alias is identified by its configured name; use
stable provider model IDs and rebuild after provider changes.

Agent budgets cover iterations, tool calls, context size, tokens, and elapsed time between
requests; each request also has an HTTP timeout. No automatic retries are made. Network timeout
semantics can make wall-clock stopping approximate. Run logs contain the question, selection,
model, corpus hash, tool arguments/results, usage, and outcome; they never include API headers.
Generated relevance/completeness is not independently verified. Research-only refusal rules
are a product boundary, not a legal compliance certification.

## Ingest a company

`ingest` finds a company's annual reports, downloads them with a plain request, and maps them
into review candidates. Sites that refuse automated downloads are not worked around: their
links open in your browser instead. Save those PDFs into `data/inbox/` and rerun the same
command (or pass `--watch-minutes 10` to wait); files are matched by name, or by company name
and fiscal year in their first pages.

```sh
# Discovery uses web search: export OPENAI_API_KEY and REGULATION_AGENT_MODEL first.
.venv/bin/regulation-analyst ingest "Wipro" --years FY24 FY25
# Without a key, give the official links yourself:
.venv/bin/regulation-analyst ingest "Wipro Limited" --years FY25 --url FY25=https://www.wipro.com/.../ar.pdf
```

Links must be on the company's own domain or BSE/NSE; aggregators are rejected. Progress is
kept in the database, so reruns reuse discovery and skip finished steps; `--remap` re-maps
archived reports with current rules.

Mapped facts are imported only after validation gates: the value is printed at the cited cell
of the archived PDF, its year and revision fit the report, accounting identities hold within
rounding (total income = revenue + other income; profit = profit before tax − tax), it agrees
with other reports of the same year, and it is plausible (signs, magnitudes, unit errors).
Comparative columns are cross-checks only; each year comes from its own report, and a later
restatement is recorded as a warning. With `--llm-resolve`, the model may re-point a failing
line item to another row of the same table; the value is re-read from that cell and all gates
re-run. Everything else goes to `artifacts/candidates/*-queue.json` for review. Imported facts
are labelled `automated_extraction` or `llm_resolved`; answers mark them as unreviewed, reviewed
facts take precedence, and `--trust reviewed_only` excludes them. Use `--no-import` to gate only.

## Acquire, extract, map, review

Source request manifests are in [sources/](sources/). Acquire one document at a time through
permitted official access, or supply the official local PDF:

```sh
.venv/bin/regulation-analyst acquire sources/infosys-consolidated24.json --local-pdf /path/to/consolidated.pdf
.venv/bin/regulation-analyst extract /path/to/consolidated.pdf --pages 12 79
# For scans: add --ocr --table-strategy text after installing Tesseract traineddata.
```

Extraction artifacts preserve original bytes, parser version/settings, tables, coordinates,
and page renderings. Scans remain flagged when OCR is not requested; unavailable OCR fails
with setup instructions. [examples/table-mapping.json](examples/table-mapping.json) is a
**synthetic template**, not a mapping for an actual Infosys report. Adapt it to inspected cells:

```sh
.venv/bin/regulation-analyst map-table /path/to/extraction.json /path/to/mapping.json --output artifacts/candidate.json
# Inspect the source page/rendering, mappings, values and diagnostics first.
.venv/bin/regulation-analyst review artifacts/candidate.json --reviewer "Your name" --method visual_review --reviewed-on 2026-10-27 --expected-digest INSPECTED_CANDIDATE_SHA256 --output artifacts/reviewed.json
.venv/bin/regulation-analyst import artifacts/reviewed.json
```

For a full annual report, `automap` finds the statement pages and writes the mapping for you.
Rules choose rows; with `--llm` the configured model may choose row indexes for items the
rules missed, never values. Inspect the candidates and report, then use `review` and `import`:

```sh
.venv/bin/regulation-analyst automap /path/to/annual-report.pdf --company-id wipro \
  --company-name "Wipro Limited" --document-id wipro-ar25 --title "Wipro Annual Report 2024-25" \
  --url https://www.wipro.com/.../annual-report.pdf --reporting-year 2025 --output artifacts/candidates
```

The review command records a human/admin assertion; it cannot prove that someone actually
inspected the source. It refuses changed candidates, unresolved diagnostics, and empty bundles.
Optional `reconciliations` specify a total row, component rows, and a tolerance in crore.
Rows/columns are zero-based; PDF pages are one-based. [Full import contract](docs/IMPORTS.md).

## MCP

Initialize the database, then configure your MCP client with absolute paths:

```json
{
  "mcpServers": {
    "regulation-analyst": {
      "command": "/ABSOLUTE/PATH/regulation-analyst/.venv/bin/regulation-analyst",
      "args": ["--db", "/ABSOLUTE/PATH/regulation-analyst/data/research.sqlite3", "serve"]
    }
  }
}
```

Tools: `list_companies`, `list_metrics`, `get_table`, `calculate`, `search_filings`,
`compare_companies`, `search_regulations`, `get_source`, `answer_question`.
The `research://coverage` resource reports coverage. Supply global `--hybrid-index` and provider
environment configuration to enable hybrid search in MCP. SQLite research connections use
`mode=ro`; ingestion stays outside MCP. The external host supplies its own agent. Its prose is
outside the server renderer's validation boundary. The separately bounded agent runs via CLI.

## Evaluation and verification

```sh
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
# Keep the original smoke corpus isolated from the expanded corpus:
.venv/bin/regulation-analyst --db data/smoke.sqlite3 demo
.venv/bin/regulation-analyst --db data/smoke.sqlite3 evaluate --output artifacts/smoke.json
.venv/bin/regulation-analyst experiment --output artifacts/fixed-tools-development.json
.venv/bin/regulation-analyst evaluate-parser /path/to/extraction.json /path/to/gold-cells.json
```

The 168-case matrix uses independent Decimal expressions for gold calculations, source IDs,
answerability/status labels, and explicit citation requirements. Cases are systematically
varied and correlated; all are development cases. The schema rejects source/evidence leakage
across splits and refuses held-out reporting without independently reviewed labels.

With a configured model, run `experiment --mode flat_rag`, `layout_rag`, or `agent`, optionally
with `--max-cases`. RAG conditions require local official archives for eligible documents; both
rank the same raw pages, then differ in whether table rows are supplied. Agent final answers
are rendered from canonical evidence. Fixed tools use no model, so model cost comparisons
must acknowledge that difference. Missing prerequisites are reported as blocked cases.

JSON/Markdown reports include numeric accuracy **and coverage**, citation resolution and gold
coverage, page recall/MRR where page retrieval ran, latency, actual token usage when available,
and descriptive confidence intervals. Semantic faithfulness and narrative completeness remain
manual review fields. There is **no measured live RAG-versus-agent improvement claim** yet.

## Design and remaining release gates

- [Completion plan](docs/COMPLETION_PLAN.md)
- [Completion matrix and remaining inputs](docs/COMPLETION_STATUS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Runtime and evaluation details](docs/OPERATIONS.md)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)
- [Sentence Transformers cross-encoders](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)

PyMuPDF is the selected parser. A second Docling/vision backend and a difficult-page parser
comparison are deferred until real archived failure examples are available. Review dependency
and source-content licenses before redistributing packaged software or full documents.
