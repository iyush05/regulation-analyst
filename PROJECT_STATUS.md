# Regulation Analyst: Project Overview and Implementation Status

Reviewed: 30 October 2026 · Application version: 0.2.0

## 1. Project introduction and context

Regulation Analyst is a local research assistant for Indian company financials and dated financial regulations. It helps a researcher look up reported figures, calculate financial metrics, compare companies, find management commentary, and retrieve regulatory provisions with their source references.

Financial reports contain tables with different units, accounting bases, reporting periods, and definitions. Regulations also change over time. A useful answer must therefore establish which evidence applies before calculating or explaining anything. This project addresses that problem by storing explicit financial facts and source locations, using deterministic Decimal arithmetic, and resolving regulations against effective dates and verified coverage.

For example, a researcher can ask how Infosys operating margin changed from FY23 to FY25, request an Infosys–TCS net-margin comparison, or search the imported RBI KYC material for a specified date. Supported answers retain their source citations and calculation inputs. Missing or conflicting evidence produces an explicit gap or refusal.

The current application is a Python package accessed through a command-line interface (CLI) or a read-only Model Context Protocol (MCP) server. It offers both a deterministic answering workflow and an optional model-driven tool agent. Its initial research scope is Infosys, TCS, and HCLTech for FY23–FY25, plus narrow historical SEBI and RBI material.

**Current position:** the core local research workflows are implemented and tested. Complete three-company financial coverage, independently reviewed evaluation, and measured live-model performance remain unfinished. The project is a working research application with outstanding data and validation work.

## 2. How the project works

1. Acquire an official PDF or supply a local copy, then archive its bytes and SHA-256 hash.
2. Extract page text, tables, cell coordinates, and page images; optionally use OCR for scans.
3. Map inspected cells to financial records and resolve validation diagnostics.
4. Record an explicit review decision and import the resulting bundle into SQLite.
5. Retrieve reviewed facts, passages, or dated regulatory provisions.
6. Calculate supported metrics and render answers with evidence references.
7. Evaluate extraction, retrieval, calculations, citations, and experiment outcomes.

The default financial selection is consolidated Ind AS. Scope, accounting basis, revision policy, and publication cutoff can be supplied explicitly. Monetary values normalize to INR crore while retaining original strings and units.

The main technologies are Python, Pydantic, SQLite/FTS5, PyMuPDF, HTTPX, and the MCP Python SDK. Optional model capabilities use OpenAI adapters or locally supplied Sentence Transformers models. Python 3.13 is the documented tested runtime; package metadata permits Python 3.11 and later.

## 3. What is already implemented

### 3.1 Data model, persistence, and provenance

- Typed records for companies, documents, evidence, financial facts, narrative passages, and regulatory provisions.
- Company aliases and fiscal calendars; explicit financial periods, accounting bases, scopes, units, and metric definitions.
- Source URLs, publication/capture metadata, PDF and printed page references, sections, table/row/column locations, and optional bounding boxes.
- Review identity, method, and date attached to evidence.
- Immutable records: identical imports are idempotent; changing an existing record requires a new identity and appropriate revision relationship.
- Cross-record validation and atomic imports that roll back invalid bundles.
- Original-versus-restated selection and publication-cutoff filtering. Unknown publication dates are excluded from cutoff-dependent research.
- Read-only research database connections and a corpus fingerprint for reproducibility.

Implementation: [models.py](src/regulation_analyst/models.py), [store.py](src/regulation_analyst/store.py).

### 3.2 Source acquisition and PDF extraction

- Manifest-driven acquisition from supported official HTTPS domains, including redirect checks, download limits, PDF checks, and optional expected hashes.
- Local PDF acquisition when direct downloads are unavailable.
- Content-addressed archives with acquisition metadata and integrity checks when existing archive bytes are reused.
- PyMuPDF extraction of text, layout-aware tables, individual cell boxes, and page renderings.
- Page selection and configurable table strategies: `lines`, `lines_strict`, and `text`.
- Parser version/settings and source identity retained in extraction artifacts.
- Optional Tesseract-backed OCR, with explicit failure when required OCR support is unavailable.

Implementation: [acquisition.py](src/regulation_analyst/acquisition.py), [ingestion.py](src/regulation_analyst/ingestion.py). Source request manifests are in [sources/](sources/).

### 3.3 Mapping, review, and import workflow

- Declarative mappings from extracted rows and columns to metrics, periods, units, and evidence.
- Diagnostics for invalid or inconsistent mappings.
- Optional total-versus-components reconciliation with an explicit tolerance.
- Pending candidates kept separate from importable reviewed facts.
- Digest-bound review decisions: changed candidates, unresolved diagnostics, and empty bundles cannot be approved through the review workflow.
- CLI commands to map, review, and import without modifying application code.
- Example mapping and parser-label files, plus a documented import contract.

A recorded review is an assertion by the reviewer; the software cannot prove that the source was actually inspected. The example table mapping is synthetic and must be adapted to real extracted cells.

Implementation: [review.py](src/regulation_analyst/review.py), [import documentation](docs/IMPORTS.md).

### 3.4 Financial calculations and comparisons

- Explicit number parsing and Decimal calculations; malformed or missing values are not silently treated as zero.
- Unit normalization to INR crore.
- Seven registered formulas: operating margin, net margin, growth percentage, CAGR, margin change in percentage points, margin change in basis points, and ROE.
- Net margin based on profit attributable to owners; ROE based on opening and closing owners' equity.
- Period, company, accounting-basis, and definition checks before arithmetic.
- Rejection of invalid denominators, incompatible inputs, and arbitrary expressions.
- Full calculation inputs, formulas, unrounded results, display values, and citations preserved.
- Company comparisons aligned by requested years and metric definitions, with explicit missing-data reporting.

Implementation: [numbers.py](src/regulation_analyst/numbers.py), [metrics.py](src/regulation_analyst/metrics.py), [service.py](src/regulation_analyst/service.py).

### 3.5 Retrieval and search

- SQLite FTS5/BM25 search over reviewed passages and provisions.
- Company, year, document-type, publication-date, authority, entity-type, and regulatory-date filters where applicable.
- OpenAI and local embedding adapters.
- Persistent normalized vectors and exact cosine search in a separate SQLite index.
- Reciprocal-rank fusion of lexical and dense candidates.
- Optional local cross-encoder reranking.
- Corpus/model fingerprint validation, stale-index rejection, and invalid-vector checks.
- Local model byte fingerprints, with implicit model downloads and remote model code disabled.
- Retrieval provenance and ranking scores returned with results.

These paths are implemented and covered by controlled tests. Their actual semantic quality has not been established using live embeddings or a real reranker.

Implementation: [providers.py](src/regulation_analyst/providers.py), [retrieval.py](src/regulation_analyst/retrieval.py).

### 3.6 Deterministic answers and bounded model agent

- A deterministic `ask` workflow for supported annual financial questions, comparisons, changes, management commentary, and dated regulatory searches.
- Question routing, company/year recognition, evidence-gap reporting, and explicit unsupported-request handling.
- An optional OpenAI Responses tool loop with strict argument schemas and a fixed set of research operations.
- Limits on iterations, tool calls, context, tokens, elapsed time, and individual HTTP requests; no hidden automatic retries.
- An evidence ledger that accepts only retrieved evidence and recomputes calculations before final rendering.
- Server-rendered financial values and reviewed narrative records selected by ID.
- Run logs containing model/corpus identity, tool calls/results, usage, timing, and outcomes without API headers.
- Research-only handling for investment-recommendation requests.

The deterministic workflow handles one requested metric at a time and up to three companies. Agent protocol tests use controlled responses; successful live-model behavior is still unmeasured. Canonical rendering does not establish that an answer is complete or that a management explanation proves causation.

Implementation: [answering.py](src/regulation_analyst/answering.py), [agent.py](src/regulation_analyst/agent.py).

### 3.7 Regulatory version handling

- Effective dates, verified-through bounds, publication cutoffs, and entity applicability.
- Explicit provision replacement chains with chronology and identity validation.
- Date-specific version selection and rejection of overlapping, conflicting versions.
- Protection against incorrectly reviving an older provision after its replacement expires.
- Explicit gaps for dates outside imported and verified coverage.

The resolver is implemented; the actual imported regulatory history remains narrow. It does not establish current-law coverage.

Implementation: [store.py](src/regulation_analyst/store.py), [service.py](src/regulation_analyst/service.py).

### 3.8 CLI and MCP integration

The CLI implements:

| Purpose | Commands |
|---|---|
| Database and corpus | `init`, `demo`, `load-corpus`, `import`, `coverage`, `metrics` |
| Source preparation | `acquire`, `extract`, `map-table`, `review` |
| Research | `ask`, `agent`, `table`, `compare`, `calculate`, `search`, `regulations`, `source` |
| Retrieval setup | `index` |
| Evaluation | `evaluate`, `experiment`, `evaluate-parser` |
| MCP integration | `serve` |

The MCP server exposes nine read-only tools: `list_companies`, `list_metrics`, `get_table`, `calculate`, `search_filings`, `compare_companies`, `search_regulations`, `get_source`, and `answer_question`. It also exposes the `research://coverage` resource.

CLI and MCP share the research service. Ingestion stays outside MCP, and tools do not expose arbitrary SQL or shell access. An external MCP host controls its own generated prose; that prose is outside this application's answer-rendering checks.

Implementation: [cli.py](src/regulation_analyst/cli.py), [mcp_server.py](src/regulation_analyst/mcp_server.py).

### 3.9 Evaluation, tests, and developer tooling

- A 32-case development smoke benchmark.
- A 168-case research development benchmark: 35 fact lookups, 82 numerical cases, 30 multi-document cases, and 21 challenge cases.
- Gold values with independent Decimal derivations, tolerances, evidence IDs, answerability/status labels, and source groups.
- Split-leakage checks and a requirement for independently reviewed labels before held-out reporting.
- Four experiment runners: A — flattened-text RAG; B — layout-aware RAG; C — fixed tools; D — adaptive agent.
- Matched page retrieval for A/B, differing in whether extracted table rows accompany text.
- Numeric accuracy and coverage, citation resolution and gold coverage, parser-cell scoring, and page recall/MRR/complete-evidence recall where page retrieval runs.
- JSON/Markdown reports, latency, actual token usage when returned, descriptive confidence intervals, and optional cost estimation through the Python runner's price arguments.
- Tests for calculations, immutability, revisions, research answers, PDF extraction, acquisition/review, regulatory history, retrieval, agent protocols, experiments, and MCP stdio integration.
- Dependency metadata, a tested dependency lock file, Ruff configuration, GitHub Actions verification workflow, corpus/benchmark builders, and an offline demo script with saved outputs.

Implementation: [evaluation.py](src/regulation_analyst/evaluation.py), [experiments.py](src/regulation_analyst/experiments.py), [tests/](tests/), [scripts/](scripts/), [CI workflow](.github/workflows/ci.yml).

## 4. Current bundled data coverage

The demo and research-expansion fixtures together contain **3 company records, 10 documents, 39 evidence records, 33 financial facts, 3 management passages, and 3 regulatory provisions**. Company registration does not imply complete financial coverage.

| Company / authority | Available evidence | Missing coverage |
|---|---|---|
| Infosys | FY23–FY25 consolidated Ind AS revenue, operating profit, owners' and total profit, and owners' equity; IFRS revenue/profit; FY25 call commentary | Opening equity for FY23 ROE, earlier management explanations, verified PDF publication dates, local official PDF archives |
| TCS | FY23–FY25 consolidated Ind AS revenue, owners' and total profit, and owners' equity; FY25 management press-release material | Comparable operating-profit definition and facts, opening equity for FY23 ROE, earlier calls, verified PDF publication dates, local official PDF archives |
| HCLTech | FY25 management press-release summary and financial-source acquisition manifests | Reviewed financial tables for FY23–FY25, opening equity, broader commentary, completed source acquisition |
| SEBI | Two historical provisions concerning commencement and material-event deadlines, verified for 2023-07-15 | Subsequent amendments, broader applicability review, and current-law coverage |
| RBI | One KYC amendment commencement provision, verified for 2025-06-12 | Complete KYC history, broader substantive coverage, and current-law coverage |

The financial values are source-text crosschecked, not independently human-audited. Existing documentation identifies unarchived PDF records as `remote_reference_only`. Signature dates are not treated as verified publication dates. See [the source audit](docs/SOURCES.md).

## 5. What is still left to implement or complete

### 5.1 Concrete implementation gaps

| Remaining work | Current behavior | Completion condition |
|---|---|---|
| ROE change calculation | Individual annual ROE values are supported; the deterministic workflow explicitly reports that ROE change is not implemented. | Define the intended change measure, implement its formula and answer routing, preserve input lineage, and test valid/missing-equity cases. |
| Regulatory source snapshots for RAG baselines | The RAG page builder skips regulation documents; there is no regulatory HTML snapshot pipeline. | Archive dated regulatory sources with provenance and supply them to A/B under matching retrieval conditions, then validate regulatory baseline cases. |
| Resumable acquisition, if retaining the original plan's requirement | Acquisition streams a fresh download and reuses completed content-addressed archives; interrupted transfers are not resumed. | Implement and test safe partial-download continuation, or explicitly remove resumable transfer from the acceptance target. |

### 5.2 Data acquisition and corpus completion

- [ ] Obtain and locally archive the official PDFs backing the included financial evidence; verify their hashes and source mappings.
- [ ] Acquire and review HCLTech financial tables covering FY23–FY25.
- [ ] Align operating-profit definitions before enabling currently unsupported cross-company operating-margin comparisons.
- [ ] Add opening owners' equity needed for FY23 ROE and any other requested period lacking a valid opening balance.
- [ ] Add earlier management transcripts and explanations across the covered companies and years.
- [ ] Verify publication dates where reliable evidence exists; retain uncertainty where it does not.
- [ ] Expand SEBI/RBI amendment histories, applicability metadata, and verified dates using actual sources.
- [ ] Independently review financial cells, narrative summaries, and regulatory records.

These tasks mostly use existing acquisition, mapping, review, and import commands. They require source access and review work rather than replacement of the core pipeline. Previous project documentation records download/DNS and HCLTech source-access failures; those historical blockers were not re-tested for this status document.

### 5.3 Parser and OCR validation

- [ ] Install usable Tesseract language data and execute real scanned-document extraction.
- [ ] Collect difficult official pages and independently label their cells.
- [ ] Measure extraction accuracy for merged cells, complex headers, multiline labels, and scanned tables.
- [ ] Inspect failure cases and improve extraction/mapping where measured errors warrant changes.
- [ ] Decide whether a second parser, such as Docling or a vision backend, is justified by those failures. No second backend is implemented; the current roadmap deliberately defers it.

### 5.4 Live retrieval and model validation

- [ ] Configure a live agent model and credentials for the existing provider adapter.
- [ ] Configure real embeddings or supply pinned local weights; optionally supply a reranker.
- [ ] Build and evaluate a real vector index against independently labeled relevant evidence.
- [ ] Exercise actual multi-step agent behavior, evidence selection, incomplete-answer handling, budgets, and provider failures.
- [ ] Measure narrative relevance/completeness and inspect unsupported causal interpretations through independent review.

Model adapters and orchestration are already present. Controlled protocol tests do not substitute for these runs.

### 5.5 Benchmark and comparative research completion

- [ ] Expand source diversity before creating a held-out set.
- [ ] Independently review benchmark labels and required narrative claims.
- [ ] Reconcile the original target of 180 questions—50 lookup, 50 numerical, 50 multi-document, and 30 challenge—with the current 168 development cases.
- [ ] Create and freeze the proposed 60-development/120-held-out split, or document a revised design. Renaming correlated existing cases as held-out is insufficient.
- [ ] Run A/B/C/D on a frozen corpus with matched model/settings where applicable; resolve archive and regulatory-baseline gaps first.
- [ ] Record manual semantic review and human review effort alongside automated scores.
- [ ] Compare numerical error rates, answer coverage, citations, retrieval, latency, and actual usage/cost; inspect errors before publishing performance claims.

There is currently no measured live RAG-versus-agent improvement result. The fixed-tool condition uses no model, which must be acknowledged in cost and latency comparisons.

### 5.6 Release evidence and demonstration

- [ ] Confirm the checked-in CI workflow executes successfully in hosted CI.
- [ ] Exercise a specific intended MCP desktop/client integration beyond the existing stdio protocol test.
- [ ] Record an end-to-end demonstration using the completed corpus and chosen runtime.
- [ ] Publish reproducible measured results with the remaining limitations and source/review provenance.
- [ ] Review dependency and source-content licenses before redistributing packaged software or full source documents, as called out in the README.

### 5.7 Scope boundaries and optional extensions

The current reference workflow excludes quarterly/TTM analysis, forecasts, EPS, EBITDA, unsupported accounting bases, investment recommendations, and CAGR of ratios. Broader question routing and additional metrics would require deliberate scope expansion and appropriate source coverage.

There is no web frontend or hosted multi-user application in this workspace. Neither is a completion requirement in the existing local CLI/MCP roadmap. A separate vector database is also optional: SQLite exact cosine search is the implemented design for this corpus. These extensions should not be confused with the outstanding validation gates above.

## 6. Verification evidence and its limits

| Check | Evidence available |
|---|---|
| Automated test suite | Re-run for this review: **118 passed**, with five SWIG-related deprecation warnings and no failures. |
| Bundled corpus and benchmark counts | Recounted directly from the JSON fixtures for this document. |
| Smoke benchmark | Existing [smoke report](artifacts/smoke.json): **32/32** cases passed; **13/13** expected numeric slots present and correct. |
| Fixed-tool research benchmark | Existing [development report](artifacts/fixed-tools-development.json): **168/168** automatic checks passed; **318/318** expected numeric slots present and correct. |
| Lint and formatting | Previously recorded as passing in [completion status](docs/COMPLETION_STATUS.md); not re-run for this documentation change. |
| Live agent/RAG, real embedding/reranking quality, real OCR accuracy, independent held-out performance | Not established by the checked-in evidence. |

The saved benchmark reports are existing execution artifacts, not new live-model experiments from this review. All bundled research cases are development cases. Their automatic pass rate does not establish independent generalization, narrative faithfulness, or legal completeness.

## 7. Recommended order for the remaining work

1. Complete official source archives and the missing financial/regulatory corpus; arrange independent source review.
2. Resolve the explicit calculation and regulatory-baseline implementation gaps needed by the intended evaluation scope.
3. Validate real PDF/OCR extraction and real embedding/reranking behavior.
4. Independently review and freeze a sufficiently diverse benchmark and held-out split.
5. Run live agent and A/B/C/D experiments, review errors and narrative quality, and publish the measured results.
6. Verify the intended MCP client and hosted CI, then record the final demonstration.

For operational commands and detailed contracts, see the [README](README.md), [architecture](docs/ARCHITECTURE.md), [operations guide](docs/OPERATIONS.md), [original completion plan](docs/COMPLETION_PLAN.md), and [completion matrix](docs/COMPLETION_STATUS.md).
