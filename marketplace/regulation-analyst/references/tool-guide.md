# Research tool guide

Use the connected server's schemas as the authoritative argument contract.

| Tool | Use |
| --- | --- |
| `list_companies` | Discover company identifiers, aliases and imported years |
| `check_coverage(company, years)` | Inspect available metrics and verification levels by year/basis/scope |
| `list_metrics` | Read metric names, formula IDs, input ordering and required year offsets |
| `get_table(company, years, metrics)` | Fetch reported facts and their IDs; years such as `FY25` |
| `calculate(formula, fact_ids)` | Compute a registered formula from ordered fact IDs |
| `compare_companies(metric, companies, years)` | Compare compatible reported or derived metrics |
| `search_filings(query, company, year)` | Find management passages and other imported narrative |
| `search_regulations(query, as_of, authority, entity_type)` | Find dated provisions within their verification limits |
| `get_source(evidence_id)` | Resolve citations and source trust metadata |
| `answer_question(question)` | Run the deterministic reference workflow and obtain its rendered answer |

Financial selections default to consolidated, Ind AS, latest available revisions, and
allowing automated facts. Use `scope`, `basis`, `policy` and `trust` explicitly when those
choices matter. The alternative revision policy is `originally_reported`; `known_on` limits
publication knowledge where supported and is distinct from a regulation's `as_of` date.

Results include a status, message, corpus version and data. Inspect the status even if
the MCP request succeeded: transport success does not establish a complete research result.

Example: for Infosys operating margin FY24–FY25, first check coverage. Use
`answer_question` for the supported question, or inspect `list_metrics`, retrieve the required
reported facts and pass their IDs in the specified order to `calculate`. Retain returned
lineage and citations. Never supply model-estimated values as substitutes for fact IDs.

For ROE, opening equity may require the prior fiscal year. For comparisons, do not replace
reported owners' profit with an adjusted figure or switch between IFRS and Ind AS silently.
