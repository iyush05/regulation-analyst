---
name: regulation-analyst
description: Research Indian company financials and dated SEBI or RBI provisions using the connected Regulation Analyst service, with source citations, comparable accounting bases, and reproducible calculations.
---

# Regulation Analyst

Requires access to the Regulation Analyst MCP server. Use this skill for research on its
imported corpus. It does not provide live market prices, investment recommendations, or
complete current-law coverage.

If the research tools are unavailable, read [connection guidance](references/connection.md)
and explain the missing connection. Agensi supplies these instructions; the research server
is a separate service. Do not substitute invented tool results or ask for credentials in chat.

## Research workflow

1. Establish the company, fiscal years, metric, accounting scope and basis. Use
   `list_companies`, `check_coverage` and `list_metrics` to inspect actual coverage and
   definitions. A company appearing in the list does not mean every year or metric exists.
2. For supported financial questions, `answer_question` returns a server-rendered answer
   with calculation lineage. For custom research, use `get_table` for reported facts and
   `calculate` with the registered formula and ordered fact IDs. Use `compare_companies`
   for comparisons. Read [tool guidance](references/tool-guide.md) when assembling calls.
3. Keep company, fiscal year, scope, basis and restatement policy consistent. State any
   defaults used. Monetary values are normalized to INR crore; preserve the returned units.
   Distinguish percentage changes from percentage-point or basis-point changes.
4. Inspect source trust. Disclose automated or LLM-resolved extraction; use
   `trust="reviewed_only"` when the user requires reviewed evidence. Do not silently relax
   that filter to fill a gap. Reviewed records are not a certification of independent audit.
5. For management explanations, use `search_filings` and cite the relevant passages.
   Separate management statements from your interpretation; missing commentary is a gap.
6. For regulations, establish an explicit ISO `as_of` date and relevant entity type before
   using `search_regulations`. Report effective and verified-through limits. A historical
   result is not proof of current applicability.
7. Resolve supporting evidence with `get_source` as needed. Retain source URLs, document
   titles, page/cell references and evidence IDs supplied by the service. Do not create
   source-page image links when archives are unavailable.

Return a direct answer, supporting figures or passages, citations, and material coverage
or trust limitations. Use the [report template](templates/research-report.md) for longer
reports. Preserve `partial`, missing or conflicting evidence in the answer. If the service
is unavailable, report that limitation rather than manufacturing an answer from its corpus.

The hosted tools are read-only. Ask the service operator to add missing filings; this skill
does not authorize ingestion. The server validates its calculations and rendered results;
additional prose written by the buyer's agent is outside that validation boundary.
