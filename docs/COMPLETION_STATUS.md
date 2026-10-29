# Completion status

This records what was implemented and what was actually exercised. The project is runnable;
its complete portfolio validation is not finished. No credentials, human reviews, local source
archives, or live model results have been invented.

| Area | Implementation | Execution / remaining gate |
|---|---|---|
| Source acquisition | Official-domain HTTPS, redirects checked, size limits, hashes, local PDF mode | Local/HTTP-protocol tests pass; shell DNS prevents live official downloads |
| PDF ingestion | PyMuPDF layout tables, cells, page images, parser/settings fingerprint | Actual generated PDF tests pass; difficult real-PDF benchmark pending |
| OCR | Searchable temporary OCR PDF; configurable language/table strategy | Tesseract data unavailable here; real OCR accuracy unmeasured |
| Review/import | Declarative mapping, unit/year checks, total reconciliation, digest-bound review, immutable import | Local PDF → extraction → candidate → review → query integration passes |
| Retrieval | BM25, real embedding adapters, persistent cosine index, RRF, optional cross-encoder, stale-index checks | SQLite/filter/fusion/protocol tests pass; actual embedding/reranking quality requires API key or weights |
| Agent | OpenAI Responses loop, strict tools, budgets, evidence ledger, recomputation, server rendering, run logs | Controlled protocol tests pass; live model run requires configuration |
| Regulations | Explicit replacement relationships, chronology/applicability checks, temporal resolution, conflict refusal | Synthetic before/after tests pass; only narrow actual SEBI/RBI dates are crosschecked |
| Corpus | 33 facts; Infosys and TCS FY23–FY25; 3 management passages; 3 regulatory clauses; 10 documents | HCLTech financial tables, broader call coverage, opening equity, archive hashes, and publication-date audit remain |
| Evaluation | Four executable conditions; strict gold schema; numeric/citation/retrieval/parser metrics; reports | 168 development cases / 318 numeric slots; no independently reviewed held-out set or live A/B/D runs |
| MCP / CLI | Shared read-only tools; optional hybrid search; all admin workflows via CLI | Real stdio handshake/tools/resource integration tested; specific desktop-client UI not exercised |
| Documentation / demonstration | Setup, examples, manifests, architecture, offline demo script, CI | Local commands exercised; hosted CI and a screen recording are not claimed |

## Evidence from this workspace

- Installed package: `regulation-analyst 0.2.0`; offline editable build succeeded.
- Automated tests: 118 passed, including an actual MCP stdio handshake and PDF extraction.
- Ruff lint and formatting checks pass.
- Original isolated smoke suite: 32/32 cases passed in final verification.
- Research development matrix: 168 automatic checks pass; 318/318 expected numeric slots
  present and correct at their declared tolerances. Labels are assistant-authored and
  source-crosschecked, not independently reviewed.
- Model/vector doubles are labeled as such in tests. Their results are not semantic benchmarks.
- `artifacts/fixed-tools-development.json` and `.md` hold the executed development report.
- `artifacts/demo/research.json` and `.md` hold the cited example and comparison.

## Inputs needed to finish the external validation

1. Configure `OPENAI_API_KEY` and an explicit `REGULATION_AGENT_MODEL` for live agent/baseline runs.
   Configure embeddings or provide pinned local weights; optionally provide a reranker.
2. Restore permitted shell source access or place official PDFs locally. Use `sources/` manifests
   with `acquire --local-pdf`, then review mappings and imports. HCLTech's official financial PDFs
   were discoverable but inaccessible through the available download paths.
3. Install Tesseract traineddata to measure OCR, then label real difficult-page cells.
4. Have an independent reviewer audit source cells, narrative summaries, regulation histories,
   and gold labels. Add distinct source groups before freezing a held-out split.
5. Run all configured experiment conditions on a frozen corpus and inspect errors before making
   any resume claim about reducing numerical errors.

## Plan adjustments

- Exact cosine search in SQLite replaces a separate vector database for this small corpus.
- PyMuPDF is the implemented parser; speculative Docling/vision integration was not added
  without difficult-page archives and a way to validate it.
- The available evidence supports 168 development cases. The proposed 180-case / 120-held-out
  target remains a research gate; relabeling correlated development cases would not satisfy it.
- Actual legal coverage remains narrow. A functioning version resolver does not establish a
  complete or current legal history.
