"""Read-only MCP adapter using the official Python SDK."""

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .models import Basis, Policy, Result, Scope, Trust
from .service import ResearchService
from .store import Store


def create_server(database: str | Path, *, retriever=None, ingestor=None) -> FastMCP:
    service = ResearchService(Store(database, readonly=True), retriever=retriever)
    server = FastMCP(
        "Regulation Analyst",
        instructions=(
            "Research only the imported corpus. First inspect list_companies and list_metrics. "
            "Each source states its trust level; disclose automated or LLM-resolved values. "
            "Use get_table for numbers and calculate for arithmetic. Never mix companies, years, "
            "scope, or accounting basis. Cite evidence IDs and source URLs. Regulatory research "
            "requires an as_of date and applicability checks. "
            "Report missing or conflicting evidence. "
            "No investment recommendations. answer_question is a deterministic reference workflow; "
            "external client prose is outside its validation guarantee."
        ),
        log_level="WARNING",
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=annotations)
    def list_companies() -> Result:
        """List exact company aliases and imported financial coverage."""
        return service.call("list_companies")

    @server.tool(annotations=annotations)
    def list_metrics() -> Result:
        """List supported facts, formula IDs, and required calculation input ordering."""
        return service.call("list_metrics")

    @server.tool(annotations=annotations)
    def get_table(
        company: str,
        years: list[str],
        metrics: list[str] | None = None,
        scope: Scope = "consolidated",
        basis: Basis = "Ind AS",
        policy: Policy = "latest_available",
        known_on: str | None = None,
        trust: Trust = "allow_automated",
    ) -> Result:
        """Fetch reviewed annual financial facts with cell-level citations; years like FY25."""
        return service.call(
            "get_table",
            company=company,
            years=years,
            metrics=metrics,
            scope=scope,
            basis=basis,
            policy=policy,
            known_on=known_on,
            trust=trust,
        )

    @server.tool(annotations=annotations)
    def calculate(formula: str, fact_ids: list[str]) -> Result:
        """Compute a registry formula from ordered fact IDs. Arbitrary expressions are forbidden."""
        return service.call("calculate", formula=formula, fact_ids=fact_ids)

    @server.tool(annotations=annotations)
    def search_filings(
        query: str,
        company: str | None = None,
        year: str | None = None,
        document_type: Literal["annual_report", "transcript", "filing"] | None = None,
        known_on: str | None = None,
        limit: int = 8,
    ) -> Result:
        """Search reviewed passages with company/year/document filters; hybrid when configured."""
        return service.call(
            "search_filings",
            query=query,
            company=company,
            year=year,
            document_type=document_type,
            known_on=known_on,
            limit=limit,
        )

    @server.tool(annotations=annotations)
    def compare_companies(
        metric: str,
        companies: list[str],
        years: list[str],
        scope: Scope = "consolidated",
        basis: Basis = "Ind AS",
        policy: Policy = "latest_available",
        known_on: str | None = None,
        trust: Trust = "allow_automated",
    ) -> Result:
        """Compare compatible annual metrics. Missing companies remain explicit gaps."""
        return service.call(
            "compare_companies",
            metric=metric,
            companies=companies,
            years=years,
            scope=scope,
            basis=basis,
            policy=policy,
            known_on=known_on,
            trust=trust,
        )

    @server.tool(annotations=annotations)
    def search_regulations(
        query: str,
        as_of: str,
        authority: Literal["SEBI", "RBI"] | None = None,
        entity_type: str | None = None,
        known_on: str | None = None,
        limit: int = 8,
    ) -> Result:
        """Search provisions effective and verified on an ISO date; no assumption of current law."""
        return service.call(
            "search_regulations",
            query=query,
            as_of=as_of,
            authority=authority,
            entity_type=entity_type,
            known_on=known_on,
            limit=limit,
        )

    @server.tool(annotations=annotations)
    def check_coverage(company: str, years: list[str] | None = None) -> Result:
        """Imported fiscal years and line items for a company, with how they were verified."""
        return service.call("check_coverage", company=company, years=years)

    if ingestor is not None:

        @server.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
            )
        )
        def ingest_company(company: str, years: list[str]) -> dict:
            """Find, download, validate, and import a listed company's annual reports (FY25 style
            years, at most three). Slow; writes automatically extracted facts to the corpus."""
            if not 1 <= len(years) <= 3:
                return {"status": "invalid_request", "message": "Request one to three years"}
            return ingestor(company, years)

    @server.tool(annotations=annotations)
    def get_source(evidence_id: str) -> Result:
        """Resolve an evidence ID to its source page, table cell, and review metadata."""
        return service.call("get_source", evidence_id=evidence_id)

    @server.tool(annotations=annotations)
    def answer_question(
        question: str,
        scope: Scope = "consolidated",
        basis: Basis = "Ind AS",
        policy: Policy = "latest_available",
        known_on: str | None = None,
        trust: Trust = "allow_automated",
    ) -> Result:
        """Run the bounded reference workflow and return a cited answer with calculation lineage."""
        return service.call(
            "answer_question",
            question=question,
            scope=scope,
            basis=basis,
            policy=policy,
            known_on=known_on,
            trust=trust,
        )

    @server.resource("research://coverage")
    def coverage() -> str:
        """Available reviewed companies and fiscal years, not market-wide coverage."""
        return service.list_companies().model_dump_json(indent=2)

    return server
