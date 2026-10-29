# Reviewed bundle contract

The executable schema is `src/regulation_analyst/models.py`; `fixtures/demo.json` is a complete
small example. Unknown fields are rejected. Top-level collections are `companies`, `documents`,
`evidence`, `facts`, `passages`, and `provisions`, with `schema_version: 1` and a description.

IDs are globally unique. Imports append records atomically and are idempotent. Existing IDs
cannot be changed. Referenced records can be in the bundle or already in the database.

## Sources and evidence

Document URLs must use HTTPS. Source documents carry company, kind, reporting year,
publication date if verified, capture date, and optional local snapshot path plus SHA-256.
Snapshot paths and hashes must be supplied together; bytes are verified during import.
Use absolute snapshot paths if the application will be launched from different directories.

Evidence uses **one-based** PDF page numbers. The separate printed page label can describe a
spread. Financial facts require a table, row, and column; a bounding box is optional and must
not be invented if the source was checked through text alone. Record the actual review
method, reviewer, and review date. `source_text_crosscheck` is not an independent human audit.

## Financial records

Supported raw measures are revenue, operating profit excluding other income, profit
attributable to owners, total profit including non-controlling interests, and owners' equity.
Exact calculation-compatible definition IDs are in `metrics.DEFINITIONS`.

All current monetary units are INR: `INR`, `INR_lakh`, `INR_million`, and `INR_crore`.
Foreign-currency and per-share amounts must not be relabeled as these units.

Annual flows need complete start/end dates. Equity needs `period_kind: instant` and a null
start. `fiscal_year` is the calendar year of period end, matched against the company's fiscal
end month/day. Nonstandard short reporting years need a future schema extension.

`revision` is `reported`, `comparative`, or `restated`. A correction can set `supersedes` to a
prior fact with the same identity. This relationship does not erase the old record. Historical
queries filter by verified publication dates first, then resolve the eligible revision chain.

## Passages and regulations

Passages distinguish `excerpt` and `reviewed_summary`; keep speaker identity and management/
analyst role where applicable. Topics determine whether a reviewed management summary can
be used for a specific financial metric in the reference answer.

Regulatory provisions identify authority, instrument, clause, applicable entity types,
effective interval, and `verified_through`. The upper effective bound is exclusive; the
verification bound is inclusive. An open-ended effective interval never overrides the
verification bound. Provision entity types are explicit labels, not a general legal inference
system. `amends` remains descriptive. `supersedes` identifies an imported prior provision of
the same authority, instrument, clause, and applicability. Effective dates must increase;
publication dates must be verified and chronological. An explicit prior end must match its
replacement's start. Query resolution refuses conflicting active versions and never revives
an old version when the replacement's verification coverage expires.

Reviewers must verify applicability, completeness, amendment effects, and source terms. The
importer validates data consistency, not whether a legal interpretation is correct.

## Extraction mappings and review candidates

`map-table` accepts a `MappingPlan`: a company, source document, and explicit table mappings.
Each table identifies the one-based PDF page, extracted table ID, monetary unit and its source
text, scope/basis, and row/column mappings. `column` and `header_row` are zero-based; header rows
default to zero. The specified header cell must contain the declared four-digit fiscal year.
Rows identify an approved metric and a label present in the source row. Per-cell bounding boxes
are retained when available; legacy extraction artifacts fall back to the table box.

Optional reconciliations sum distinct component rows against a total row for each mapped year.
Totals cannot include themselves. Tolerances are explicit finite, nonnegative amounts in crore.
Failed or missing cells produce diagnostics that block approval. Review must still confirm
scope, accounting basis, period, definition, restatements, OCR accuracy, and source applicability.

Candidates contain a digest and pending review metadata that cannot pass the accepted `Bundle`
schema. `review` requires the inspected digest, reviewer, method and date, writes a new approved
bundle, and refuses to overwrite an existing output file. `import` separately validates the full
reference graph and archived source hash before committing. A review command records an assertion;
it is not independent proof that the source was actually reviewed.
