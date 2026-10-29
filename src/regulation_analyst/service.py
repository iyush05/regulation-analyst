"""Research operations shared by the CLI, reference workflow, and MCP server."""

from datetime import date

from .errors import ResearchError
from .metrics import FORMULAS, calculate
from .models import Result, year_number
from .store import Store


class ResearchService:
    def __init__(self, store: Store, retriever=None):
        self.store = store
        self.retriever = retriever

    def result(self, status, message, **data):
        return Result(status=status, message=message, corpus_version=self.store.version, data=data)

    @staticmethod
    def validate_selection(scope, basis, policy, trust="allow_automated"):
        if scope not in ("consolidated", "standalone"):
            raise ResearchError("invalid_request", "Scope must be consolidated or standalone")
        if basis not in ("Ind AS", "IFRS"):
            raise ResearchError("invalid_request", "Accounting basis must be Ind AS or IFRS")
        if policy not in ("latest_available", "originally_reported"):
            raise ResearchError("invalid_request", "Unknown restatement policy")
        if trust not in ("reviewed_only", "allow_automated"):
            raise ResearchError("invalid_request", "Trust must be reviewed_only or allow_automated")

    def call(self, operation: str, **kwargs) -> Result:
        operations = {
            "list_companies": self.list_companies,
            "get_table": self.get_table,
            "calculate": self.calculate,
            "search_filings": self.search_filings,
            "compare_companies": self.compare_companies,
            "search_regulations": self.search_regulations,
            "get_source": self.get_source,
            "answer_question": self.answer_question,
            "list_metrics": self.list_metrics,
        }
        if operation not in operations:
            return self.result("invalid_request", f"Unknown operation: {operation}")
        try:
            return operations[operation](**kwargs)
        except ResearchError as exc:
            return self.result(exc.status, str(exc))
        except (ValueError, TypeError) as exc:
            return self.result("invalid_request", str(exc))

    def list_companies(self) -> Result:
        facts = self.store.records("facts")
        companies = []
        for company in self.store.records("companies"):
            covered = [f for f in facts if f.company_id == company.id]
            companies.append(
                {
                    **company.model_dump(),
                    "fiscal_years": sorted({f.fiscal_year for f in covered}),
                    "bases": sorted({f.basis for f in covered}),
                    "fact_count": len(covered),
                }
            )
        return self.result("ok", "Coverage is limited to imported records", companies=companies)

    def list_metrics(self) -> Result:
        return self.result(
            "ok",
            "Versioned calculation registry",
            formulas=FORMULAS,
            reported_metrics=[
                "revenue",
                "operating_profit",
                "profit_owners",
                "profit_total",
                "equity_owners",
            ],
        )

    def get_table(
        self,
        company: str,
        years: list[str | int],
        metrics: list[str] | None = None,
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on: str | None = None,
        trust="allow_automated",
    ) -> Result:
        self.validate_selection(scope, basis, policy, trust)
        company_id = self.store.resolve_company(company).id
        if not years or len(years) > 20:
            raise ResearchError("invalid_request", "Request between 1 and 20 fiscal years")
        metrics = metrics or ["revenue", "operating_profit", "profit_owners"]
        if not metrics or len(metrics) > 10:
            raise ResearchError("invalid_request", "Request between 1 and 10 metrics")
        rows, missing = [], []
        for year in dict.fromkeys(year_number(y) for y in years):
            for metric in dict.fromkeys(metrics):
                try:
                    fact = self.store.select_fact(
                        company_id,
                        metric,
                        year,
                        scope=scope,
                        basis=basis,
                        policy=policy,
                        known_on=date.fromisoformat(known_on) if known_on else None,
                        trust=trust,
                    )
                    rows.append(self.store.fact_data(fact))
                except ResearchError as exc:
                    missing.append(
                        {
                            "metric": metric,
                            "fiscal_year": year,
                            "status": exc.status,
                            "reason": str(exc),
                        }
                    )
        status = (
            "partial"
            if rows and missing
            else "ok"
            if rows
            else ("ambiguous" if any(m["status"] == "ambiguous" for m in missing) else "not_found")
        )
        return self.result(
            status,
            "Financial facts in INR crore; each source states its trust level",
            facts=rows,
            missing=missing,
            scope=scope,
            basis=basis,
            restatement_policy=policy,
            known_on=known_on,
            trust=trust,
        )

    def calculate(self, formula: str, fact_ids: list[str]) -> Result:
        return self.result(
            "ok",
            "Calculated from referenced source facts",
            calculation=calculate(self.store, formula, fact_ids),
        )

    def get_source(self, evidence_id: str) -> Result:
        return self.result(
            "ok", "Source locator and review metadata", source=self.store.source(evidence_id)
        )

    def search_filings(
        self,
        query: str,
        company: str | None = None,
        year: str | int | None = None,
        document_type: str | None = None,
        known_on: str | None = None,
        limit: int = 8,
    ) -> Result:
        if self.retriever:
            hits = self.retriever.search(
                query,
                kind="passages",
                limit=limit,
                company_id=self.store.resolve_company(company).id if company else None,
                year=year_number(year) if year is not None else None,
                document_type=document_type,
                known_on=known_on,
            )
            return self.result(
                "ok" if hits else "not_found",
                "Hybrid search over reviewed passages",
                passages=hits,
                retrieval_method="bm25_dense_rrf",
            )
        hits = self.store.search_passages(
            query,
            company_id=self.store.resolve_company(company).id if company else None,
            year=year_number(year) if year is not None else None,
            kind=document_type,
            limit=limit,
            known_on=date.fromisoformat(known_on) if known_on else None,
        )
        return self.result(
            "ok" if hits else "not_found",
            "BM25 search over reviewed passages",
            passages=hits,
            retrieval_method="sqlite_fts5_bm25",
        )

    def search_regulations(
        self,
        query: str,
        as_of: str,
        authority: str | None = None,
        entity_type: str | None = None,
        known_on: str | None = None,
        limit: int = 8,
    ) -> Result:
        if self.retriever:
            hits = self.retriever.search(
                query,
                kind="provisions",
                limit=limit,
                as_of=as_of,
                authority=authority,
                entity_type=entity_type,
                known_on=known_on,
            )
        else:
            hits = self.store.search_provisions(
                query,
                as_of=date.fromisoformat(as_of),
                authority=authority,
                entity_type=entity_type,
                limit=limit,
                known_on=date.fromisoformat(known_on) if known_on else None,
            )
        return self.result(
            "ok" if hits else "not_found",
            "Provisions verified for the requested date"
            if hits
            else "No matching provision within verified temporal coverage; "
            "current law is not inferred",
            provisions=hits,
            as_of=as_of,
            entity_type=entity_type,
        )

    def metric_for_year(
        self,
        company: str,
        metric: str,
        year: int,
        *,
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on=None,
        trust="allow_automated",
    ) -> dict:
        self.validate_selection(scope, basis, policy, trust)
        company_id = self.store.resolve_company(company).id
        filters = dict(
            scope=scope,
            basis=basis,
            policy=policy,
            known_on=date.fromisoformat(known_on) if known_on else None,
            trust=trust,
        )
        needed = {
            "operating_margin": ["operating_profit", "revenue"],
            "net_margin": ["profit_owners", "revenue"],
            "roe": ["profit_owners", "equity_owners", "equity_owners"],
        }.get(metric)
        if needed:
            years = [year, year - 1, year] if metric == "roe" else [year] * len(needed)
            facts = [
                self.store.select_fact(company_id, m, y, **filters)
                for m, y in zip(needed, years, strict=True)
            ]
            calculation = calculate(self.store, metric, [f.id for f in facts])
            value, unit = calculation["value"], calculation["unit"]
        else:
            facts = [self.store.select_fact(company_id, metric, year, **filters)]
            calculation = None
            value, unit = self.store.fact_data(facts[0])["value"], "INR_crore"
        return {
            "company_id": company_id,
            "metric": metric,
            "fiscal_year": year,
            "period_start": str(facts[0].period_start) if facts[0].period_start else None,
            "period_end": str(facts[0].period_end),
            "value": value,
            "unit": unit,
            "definition": calculation["formula_id"] if calculation else facts[0].definition,
            "facts": [self.store.fact_data(f) for f in facts],
            "calculation": calculation,
        }

    def compare_companies(
        self,
        metric: str,
        companies: list[str],
        years: list[str | int],
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on: str | None = None,
        trust="allow_automated",
    ) -> Result:
        self.validate_selection(scope, basis, policy, trust)
        if not 2 <= len(companies) <= 10 or not 1 <= len(years) <= 10:
            raise ResearchError(
                "invalid_request", "Compare 2–10 distinct companies across 1–10 years"
            )
        ids = [self.store.resolve_company(c).id for c in companies]
        if len(set(ids)) != len(ids):
            raise ResearchError("invalid_request", "Comparison companies must be distinct")
        rows, missing = [], []
        for year in dict.fromkeys(year_number(y) for y in years):
            period_rows = []
            for company in ids:
                try:
                    period_rows.append(
                        self.metric_for_year(
                            company,
                            metric,
                            year,
                            scope=scope,
                            basis=basis,
                            policy=policy,
                            known_on=known_on,
                            trust=trust,
                        )
                    )
                except ResearchError as exc:
                    missing.append(
                        {
                            "company_id": company,
                            "fiscal_year": year,
                            "status": exc.status,
                            "reason": str(exc),
                        }
                    )
            if (
                len(
                    {
                        (r["period_start"], r["period_end"], r["unit"], r["definition"])
                        for r in period_rows
                    }
                )
                > 1
            ):
                raise ResearchError("ambiguous", "Comparison periods or definitions do not align")
            rows.extend(period_rows)
        return self.result(
            "partial" if rows and missing else "ok" if rows else "not_found",
            "Aligned financial comparison; missing companies are not substituted",
            rows=rows,
            missing=missing,
            metric=metric,
            scope=scope,
            basis=basis,
        )

    def answer_question(
        self,
        question: str,
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on: str | None = None,
        trust="allow_automated",
    ) -> Result:
        from .answering import answer

        self.validate_selection(scope, basis, policy, trust)
        return answer(
            self,
            question,
            scope=scope,
            basis=basis,
            policy=policy,
            known_on=known_on,
            trust=trust,
        )
