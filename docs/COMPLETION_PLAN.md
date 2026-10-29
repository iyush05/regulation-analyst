# Completion plan

Requested: finish the remaining research assistant, beginning with a concrete plan.
Baseline: 81 tests, a read-only MCP server, deterministic reference answers, 14 financial
facts, one management passage, one narrowly dated RBI record, and 32 development cases.

Execution outcome: see [the completion matrix](COMPLETION_STATUS.md) for implemented work,
118 passing tests, 168 development benchmark cases, and the remaining external validation gates.
The plan below preserves the initial target; the matrix documents justified adjustments.

This plan distinguishes implementation, actual execution, source review, and independent
human verification. A feature is not validated merely because an adapter exists or a mocked
test passes. External dependencies remain visible in the release report.

## 1. Ingestion, review, and reproducibility

- Add a source manifest and bounded official-source acquisition with hashes and resumable
  content-addressed archives. Existing local files must also be supported.
- Preserve parser version, parser settings, source hash, page coordinates, and review history.
- Add selectable PyMuPDF/Docling extraction, explicit OCR support, and a path for difficult
  pages. Missing optional dependencies must produce actionable errors.
- Add declarative table-to-fact mappings, validation/reconciliation diagnostics, candidate
  generation, and explicit review decisions before promotion to the research corpus.
- Add parser evaluation against labeled cell tuples. Keep automatic and reviewed results separate.

Acceptance: a local PDF can be acquired/imported, extracted, mapped, reviewed, and queried
without editing application code. Incorrect period/unit mappings and unreviewed values are rejected.

## 2. Expand and audit the corpus

- Cover Infosys, TCS, and HCLTech across FY23–FY25 with official financial statements and
  management commentary. Include opening equity when evaluating ROE.
- Prefer original annual reports; explicitly identify comparative disclosures and any
  fallback to official financial-results documents.
- Verify source locations, basis, definitions, and publication dates where available.
- Keep every publication-date uncertainty and unarchived source visible. Do not fabricate hashes.
- Add narrow SEBI disclosure and RBI KYC histories with actual applicability boundaries.

Acceptance: each company has an explicit coverage matrix; supported comparisons use aligned
periods and definitions; uncovered measures or dates produce evidence gaps. Independent human
review is a separate release gate and cannot be self-certified by the coding assistant.

## 3. Hybrid retrieval and reranking

- Add real embedding providers, a persistent vector index, and model/corpus fingerprint checks.
- Combine filtered BM25 and dense candidates using reciprocal rank fusion.
- Add an optional cross-encoder reranker and preserve scores and candidate provenance.
- Apply identical company/year/document/date filters to lexical and dense retrieval.
- Add retrieval evaluation: page recall@k, reciprocal rank, and complete evidence-set recall.

Implementation decision: use an exact cosine index persisted in SQLite for this small corpus.
It keeps deployment local and provides a genuine dense-search implementation without a second
database service. Keep the embedding/index interfaces replaceable if Qdrant becomes necessary.

Acceptance: configured embeddings can build and reopen an index; stale model/corpus indexes
are rejected; fusion and filtering pass tests. Live semantic quality requires actual model
weights or an embedding API and must not be inferred from deterministic test vectors.

## 4. Bounded research agent

- Add configurable model access and schema-constrained tool calls over the existing service.
- Keep research tools read-only; prevent recursive agent invocation and arbitrary tool execution.
- Bound iterations, tool calls, output/context size, elapsed time, and retries.
- Track tool results in an evidence ledger. Final financial claims must reference facts or
  recorded calculations; calculations are independently recomputed before rendering.
- Bind narrative claims to retrieved evidence and record semantic-verification status.
- Persist run IDs, model/configuration/corpus versions, tool traces, timing, and token usage.
- Preserve the deterministic reference workflow as the fixed-tool baseline.

Acceptance: the agent handles multi-step lookup/calculation/commentary questions when a model
is configured; invented evidence, altered numbers, invalid tools, and budget overruns fail
closed. Protocol tests use controlled model responses and are labeled separately from live runs.

## 5. Regulatory history and source consistency

- Add explicit provision-version relationships and validate instrument/clause identity,
  amendment chronology, overlapping effective intervals, and applicability metadata.
- Resolve the requested effective date and publication cutoff without filling unknown history.
- Return conflicting or incomplete histories as unresolved evidence.
- Preserve existing databases and immutable records through compatible schema changes or migrations.

Acceptance: before/after amendment cases resolve correctly; future publication, wrong entity
type, unknown coverage, and conflicting versions cannot silently produce a legal conclusion.

## 6. Benchmark and comparative experiments

- Extend the benchmark schema with gold evidence, required claims, independent numeric
  calculations, answerability, source groups, split, review status, and tolerances.
- Build toward 180 questions: 50 lookup, 50 numerical, 50 multi-document, 30 challenge cases;
  maintain 60 development and 120 held-out questions grouped to reduce leakage.
- Avoid padding the set with paraphrases of the same facts. Unverified labels remain drafts.
- Implement A: flattened-text RAG; B: layout-aware RAG; C: fixed tools; D: adaptive agent.
- Hold corpus, model, scope, and experiment configuration constant where relevant.
- Report numeric correctness plus answer coverage, retrieval, citation resolution/coverage,
  semantic review, latency, usage/cost when configured, and human review effort.
- Produce reproducible JSON/Markdown reports and confidence intervals with explicit sample sizes.

Acceptance: all experiment modes have executable runners and provenance-rich outputs. Only
executed, reviewed experiments may support portfolio claims. Never substitute fixture/mocked
performance for real LLM results or label assistant-authored questions independently reviewed.

## 7. Release checks and documentation

- Extend CLI/MCP interfaces, examples, environment configuration, dependency groups, and CI.
- Add an end-to-end demonstration script and generated sample output.
- Run relevant unit/integration tests, lint, formatting, import/extraction checks, and the
  executable evaluation suites available in this environment.
- Publish a completion matrix distinguishing implemented, executed, externally blocked,
  and awaiting independent review. Update the architecture and roadmap to the final code.

## Current environment dependencies

- Shell HTTPS downloads currently fail DNS resolution; the browsing tool can read official
  sources, but it does not provide local PDF archives or model weights.
- No OpenAI/Anthropic credentials or local model weights were found.
- No local Ollama or Tesseract executable was found.
- The user has been asked which model runtime to target. The implementation can proceed
  with configurable providers while a preference is pending; live runs require configuration.

Proceed with all independent implementation and source research. Recheck actual capabilities
when configuration changes. Do not treat elapsed time as credentials, approval, or verification.
