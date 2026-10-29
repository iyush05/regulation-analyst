# Runtime and evaluation operations

## Modes and trust boundaries

`ask` is the deterministic reference workflow. `agent` uses the configured OpenAI Responses
model to select tools, followed by server rendering from an evidence ledger. `serve` exposes
read-only tools to an external MCP host; that host controls its own generation and safeguards.
No server-side model agent is silently invoked by a normal MCP lookup.

The provider adapters use the official Responses/function-call and embeddings endpoints via
HTTPX. API keys are read from environment variables and are not written into run logs. Tool
schemas forbid extra properties; optional values are nullable in strict model-facing schemas.
Only known tools are dispatched. Financial selection policy is locked to the caller's scope,
basis, and publication cutoff (explicit scope/basis in the question is respected). Fiscal-year
and recognized-company mismatches are rejected; ROE can retrieve the previous year's equity.

The final agent tool supplies only IDs and enumerated evidence gaps. Financial values are
loaded again from the corpus; calculation objects are recomputed. Narratives are the exact
reviewed excerpts/summaries selected by ID. This prevents arbitrary generated numeric or
causal prose. It does not prove that every requested subquestion was answered, that the source
is correct, or that a management assertion establishes causation.

Tool/model failures fail closed. There are no hidden retries. Iteration/tool/context/token
limits are checked between requests and before accepting output. HTTP timeouts are also
applied; they are not a hard process-level wall-clock deadline. Run logs under `artifacts/runs`
contain questions and retrieved material, so treat them like research records.

## Hybrid search

1. Build the index from reviewed passages and provisions, using actual configured embeddings.
2. Store normalized vectors and a manifest in a separate SQLite file. Research DB writes are
   not needed for search. The index path cannot equal the research DB path.
3. At query time, reject corpus/model mismatches. Local model file bytes are fingerprinted;
   remote provider model identity uses its configured model name.
4. Filter eligible records by company/year/document/publication cutoff or legal effective date,
   verified interval, authority, and entity type before dense scoring.
5. Retrieve up to 50 lexical and 50 dense candidates; fuse ranks using `1 / (60 + rank)`.
6. Optionally score the best 50 with the configured local cross-encoder; return the requested
   top results with ranks, cosine/RRF/reranker scores, model identity, and citations.

Embedding/reranker scores are ranking signals, not calibrated truth probabilities. Missing
weights, stale indexes, and malformed/zero/NaN vectors produce explicit errors. Rebuild after
imports, revisions, model changes, or a known remote model update.

## Regulation replacement records

`Provision.supersedes` is an explicit ID link. `amends` remains descriptive source metadata;
it is not treated as a traversable relationship. Replacement records must share authority,
instrument, clause, and entity labels; effective dates must increase and publication dates
must be verified and chronological. An explicit prior end date must match the replacement.

At query time, resolve replacements visible at the requested publication cutoff before
checking verification coverage. An expired replacement never makes an older version reappear.
Unlinked overlapping versions of the same clause/applicability are ambiguous. No missing
amendment, publication date, or entity applicability is inferred. Database records remain
immutable; added optional payload fields are compared through typed models, preserving old
imports without changing stored bytes or requiring a SQL migration.

## Experiments

- A (`flat_rag`): BM25 over archived PDF page text; model reads flattened page text.
- B (`layout_rag`): identical candidates/ranks; model additionally sees extracted table rows.
- C (`fixed_tools`): deterministic financial selection plus calculator and source rendering.
- D (`agent`): configured model selects tools; validated ledger renders the answer.

A/B require original local PDFs. Archive manifests can supply source snapshots without
rewriting immutable historical corpus documents. A single matching document-ID manifest and
exact source URL are required; bytes must match the archive hash. Company HTML management
summaries are supplied identically to A/B as reviewed narrative context. HTML regulation
snapshots are not implemented for the RAG baselines; these cases remain blocked there.

The runner writes JSON and Markdown. Gold numeric labels identify either a fact or a named
formula with ordered input IDs, expected value/unit, tolerance, evidence IDs, and a human-readable
independent derivation. The builder uses 50-digit Decimal expressions independent of the
production formula functions. This is arithmetic independence, not independent human review.

Citation resolution checks IDs; gold citation coverage compares expected evidence. Neither
establishes semantic entailment. Narrative `required_claims` remain manual review items, and
end-to-end correctness is unset for those cases. Retrieval page recall, MRR, and complete-set
recall are measured only where a ranked page list exists. They are not fabricated for direct
table lookup. Parser scoring uses separately supplied cell labels.

All 168 bundled cases are development cases sharing a small corpus. The schema forbids gold
evidence/source-group leakage across declared splits; the runner requires independent-review
status for held-out reporting. Independent review status is an administrative assertion that
must be backed by a real review process. Confidence intervals are descriptive because related
cases are correlated. Configure price inputs through `run_experiment` to estimate cost from
actual returned token usage; no current model prices are hardcoded.

## Reproduce artifacts

```sh
.venv/bin/python scripts/build_research_bundle.py
.venv/bin/python scripts/build_benchmark.py
.venv/bin/regulation-analyst load-corpus
.venv/bin/regulation-analyst experiment --output artifacts/fixed-tools-development.json
.venv/bin/python scripts/demo.py
```

The data builders document source crosschecks; rerunning them is not a new source verification.
Use a separate database for the original smoke fixture because expanded coverage intentionally
changes its missing-data expectations.
