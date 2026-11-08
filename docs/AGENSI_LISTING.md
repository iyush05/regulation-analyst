# Regulation Analyst — listing draft

**Name:** Regulation Analyst (check uniqueness when submitting)

**Summary:** Research Indian company financials and dated SEBI/RBI provisions with source
citations, comparable accounting bases and reproducible calculations. Requires a separate
Regulation Analyst MCP connection and an operator-issued research credential.

**Description:** Get source-backed answers from an imported research corpus. Compare company
financials, compute supported ratios, retrieve management commentary and investigate dated
regulatory provisions. The service supplies fact IDs, calculation lineage and source
references so you can inspect the evidence behind an answer.

The skill guides your agent through coverage checks, accounting selections, registered
calculations and citation handling. It discloses automatically extracted facts and reports
missing evidence. Its read-only tools cannot add filings or change the research database.

**Needs access to:** Regulation Analyst MCP,
`https://regulation-analyst-api.onrender.com/mcp/`, with an operator-issued research credential.
Agensi delivers the skill separately. Buying this skill does not automatically provision
backend access. Confirm access arrangements with the creator before purchasing.

**Compatibility:** An MCP client supporting Streamable HTTP and configured bearer headers.
OAuth-only connectors are not supported by the initial release. No local Python installation
is required for a buyer using the hosted endpoint.

**Suggested categories:** Research & Analysis; Finance & Accounting; Legal & Compliance.

**Suggested tags:** Indian equities, financial research, annual reports, citations, SEBI, RBI.

**Use cases:** Compare compatible company margins; trace calculated ratios to reported facts;
retrieve management explanations; research a provision on an explicit historical date.

**Limitations:** Coverage depends on the imported company/year/metric records. There is no
live price feed, investment recommendation service or guarantee of complete current law.
Automated extraction is not independent human review. Source-page images require archived
PDFs. Client-authored prose is outside the server renderer's validation boundary. Queries
reach the separately hosted research service; the pilot offers a shared corpus and no private
uploads. Research access has per-credential request limits.

**Before submitting:** Decide pricing and access provisioning, supply the creator's support
contact, check payout readiness if paid, and upload branding if desired. Run a live example
such as “How did Infosys operating margin change from FY24 to FY25?” and paste its actual
full result into the demonstration field. Do not substitute a fabricated demonstration.

This draft is not a claim that the new endpoint is already deployed or that paid-access
provisioning is complete. Submit after the checks in [AGENSI_SETUP.md](AGENSI_SETUP.md).
