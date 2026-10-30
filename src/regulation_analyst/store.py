"""Immutable reviewed records in SQLite. Query connections are genuinely read-only."""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .errors import ResearchError
from .models import (
    REVIEWED_METHODS,
    Bundle,
    Company,
    Document,
    Evidence,
    Fact,
    Passage,
    Provision,
)
from .numbers import decimal_text, indian, normalize, normalized_unit, resolution

MODELS = {
    "companies": Company,
    "documents": Document,
    "evidence": Evidence,
    "facts": Fact,
    "passages": Passage,
    "provisions": Provision,
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, company_id TEXT REFERENCES companies(id),
    kind TEXT NOT NULL, published_on TEXT, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
    metric TEXT NOT NULL, fiscal_year INTEGER NOT NULL, scope TEXT NOT NULL, basis TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES evidence(id), payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS facts_lookup ON facts(company_id, metric, fiscal_year, scope, basis);
CREATE TABLE IF NOT EXISTS passages (
    id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence(id),
    company_id TEXT REFERENCES companies(id), fiscal_year INTEGER, payload TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(id UNINDEXED, text, topics);
CREATE TABLE IF NOT EXISTS provisions (
    id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence(id),
    authority TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
    verified_through TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS provision_fts USING fts5(id UNINDEXED, text, clause);
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    company TEXT NOT NULL, item TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
    detail TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (company, item)
);
PRAGMA user_version = 2;
"""
SCHEMA_VERSIONS = (1, 2)
JOB_STAGES = ("discover", "acquire", "extract", "map", "validate", "resolve", "import")
JOB_STATUSES = (
    "pending",
    "running",
    "done",
    "needs_manual_pdf",
    "review_required",
    "failed",
)
TRUST_LABELS = {"automated": "automated extraction", "llm_resolved": "LLM-resolved"}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def date_text(value: date | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else date.fromisoformat(value).isoformat()


def fts_query(query: str) -> str:
    # Treat user text only as terms, never as FTS operators or SQL syntax.
    stop = {"the", "a", "an", "what", "was", "were", "is", "of", "for", "in", "and", "did", "how"}
    terms = list(
        dict.fromkeys(t.lower() for t in re.findall(r"\w+", query) if t.lower() not in stop)
    )
    if not terms:
        raise ResearchError("invalid_request", "Supply at least one searchable term")
    if len(terms) > 80:
        raise ResearchError("invalid_request", "Search query exceeds 80 terms")
    return " OR ".join('"' + term + '"' for term in terms)


class Store:
    def __init__(self, path: str | Path, *, readonly: bool = True):
        self.path = Path(path).expanduser().resolve()
        self.readonly = readonly
        if readonly:
            if not self.path.is_file():
                raise ResearchError(
                    "not_found", "Database does not exist; run the demo or import command first"
                )
            with self.connection() as conn:
                if conn.execute("PRAGMA user_version").fetchone()[0] not in SCHEMA_VERSIONS:
                    raise ResearchError("invalid_request", "Unsupported database schema version")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection(write=True) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, *SCHEMA_VERSIONS):
                    raise ResearchError("invalid_request", "Unsupported database schema version")
                conn.executescript(SCHEMA)

    @contextmanager
    def connection(self, *, write=False):
        if write and self.readonly:
            raise ResearchError("invalid_request", "Research connections cannot mutate the corpus")
        uri = self.path.as_uri() + ("?mode=rwc" if write else "?mode=ro")
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @property
    def version(self) -> str:
        digest = hashlib.sha256()
        with self.connection() as conn:
            for table in MODELS:
                for row in conn.execute(f"SELECT payload FROM {table} ORDER BY id"):
                    digest.update(table.encode() + b"\0" + row[0].encode() + b"\n")
        return digest.hexdigest()[:16]

    def records(self, table: str):
        if table not in MODELS:
            raise ValueError("Unknown record type")
        with self.connection() as conn:
            return [
                MODELS[table].model_validate_json(r[0])
                for r in conn.execute(f"SELECT payload FROM {table} ORDER BY id")
            ]

    def record(self, table: str, record_id: str):
        if table not in MODELS:
            raise ValueError("Unknown record type")
        with self.connection() as conn:
            row = conn.execute(f"SELECT payload FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ResearchError("not_found", f"No {table} record with ID {record_id}")
        return MODELS[table].model_validate_json(row[0])

    def resolve_company(self, query: str) -> Company:
        needle = query.strip().casefold()
        matches = [
            c
            for c in self.records("companies")
            if needle in {s.casefold() for s in [c.id, c.name, *c.aliases]}
        ]
        if len(matches) != 1:
            raise ResearchError(
                "ambiguous" if matches else "not_found",
                f"Company {query!r} is ambiguous or not covered; use list_companies",
            )
        return matches[0]

    def record_job(self, company: str, item: str, stage: str, status: str, detail=None):
        """Track resumable ingestion progress. Jobs are operational state, not corpus records."""
        if stage not in JOB_STAGES or status not in JOB_STATUSES:
            raise ResearchError("invalid_request", "Unknown ingestion stage or status")
        with self.connection(write=True) as conn:
            conn.execute(
                "INSERT INTO ingestion_jobs VALUES (?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(company, item) DO UPDATE SET stage=excluded.stage, "
                "status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at",
                (company, item, stage, status, canonical(detail or {})),
            )

    def jobs(self, company: str | None = None) -> list[dict]:
        with self.connection() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] < 2:
                return []
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE ? IS NULL OR company=? ORDER BY company, item",
                (company, company),
            ).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]

    def import_bundle(self, bundle: Bundle) -> dict:
        """Validate the full merged graph, then atomically append immutable records."""
        if self.readonly:
            raise ResearchError("invalid_request", "Cannot import through a read-only store")
        merged = {name: {item.id: item for item in self.records(name)} for name in MODELS}
        for name in MODELS:
            for item in getattr(bundle, name):
                old = merged[name].get(item.id)
                if old is not None and old != item:
                    raise ResearchError("invalid_request", f"Immutable ID collision: {item.id}")
                merged[name][item.id] = item
        all_ids = [key for group in merged.values() for key in group]
        if len(all_ids) != len(set(all_ids)):
            raise ResearchError("invalid_request", "IDs must be unique across all record types")
        self._validate_graph(merged)
        inserted = dict.fromkeys(MODELS, 0)
        with self.connection(write=True) as conn:
            for name in MODELS:
                for item in getattr(bundle, name):
                    data = item.model_dump(mode="json")
                    existing = conn.execute(
                        f"SELECT payload FROM {name} WHERE id=?", (item.id,)
                    ).fetchone()
                    if existing:
                        if MODELS[name].model_validate_json(existing[0]) != item:
                            raise ResearchError(
                                "invalid_request", f"Immutable ID collision: {item.id}"
                            )
                        continue
                    values = {"id": item.id, "payload": canonical(data)}
                    columns = {
                        "companies": [],
                        "documents": ["company_id", "kind", "published_on"],
                        "evidence": ["document_id"],
                        "facts": [
                            "company_id",
                            "metric",
                            "fiscal_year",
                            "scope",
                            "basis",
                            "evidence_id",
                        ],
                        "passages": ["evidence_id", "company_id", "fiscal_year"],
                        "provisions": [
                            "evidence_id",
                            "authority",
                            "effective_from",
                            "effective_to",
                            "verified_through",
                        ],
                    }[name]
                    values.update({column: data[column] for column in columns})
                    conn.execute(
                        f"INSERT INTO {name} ({','.join(values)}) "
                        f"VALUES ({','.join('?' for _ in values)})",
                        list(values.values()),
                    )
                    if name == "passages":
                        conn.execute(
                            "INSERT INTO passage_fts VALUES (?, ?, ?)",
                            (item.id, item.text, " ".join(item.topics)),
                        )
                    elif name == "provisions":
                        conn.execute(
                            "INSERT INTO provision_fts VALUES (?, ?, ?)",
                            (item.id, item.text, item.clause),
                        )
                    inserted[name] += 1
        return {"inserted": inserted, "corpus_version": self.version}

    @staticmethod
    def _validate_graph(graph):
        def required(group, key):
            if key not in graph[group]:
                raise ResearchError("invalid_request", f"Missing {group} reference: {key}")
            return graph[group][key]

        for document in graph["documents"].values():
            if document.company_id:
                required("companies", document.company_id)
            if document.snapshot_path:
                path = Path(document.snapshot_path)
                if (
                    not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256
                ):
                    raise ResearchError(
                        "invalid_request", f"Snapshot missing or hash mismatch: {document.id}"
                    )
        for evidence in graph["evidence"].values():
            required("documents", evidence.document_id)
        for fact in graph["facts"].values():
            company = required("companies", fact.company_id)
            evidence = required("evidence", fact.evidence_id)
            document = required("documents", evidence.document_id)
            if document.company_id != fact.company_id:
                raise ResearchError(
                    "invalid_request", "Fact company differs from its source document"
                )
            if (
                not evidence.table
                or not evidence.row
                or not evidence.column
                or not evidence.pdf_page
            ):
                raise ResearchError(
                    "invalid_request", "Financial facts require a PDF page, table, row, and column"
                )
            if (fact.period_end.month, fact.period_end.day) != (
                company.fiscal_end_month,
                company.fiscal_end_day,
            ):
                raise ResearchError(
                    "invalid_request", "Fact period does not match the company fiscal calendar"
                )
            if document.published_on and document.published_on < fact.period_end:
                raise ResearchError(
                    "invalid_request", "A historical fact cannot precede its period end"
                )
            if fact.supersedes:
                prior = required("facts", fact.supersedes)
                keys = (
                    "company_id",
                    "metric",
                    "fiscal_year",
                    "scope",
                    "basis",
                    "definition",
                    "period_start",
                    "period_end",
                )
                if any(getattr(prior, key) != getattr(fact, key) for key in keys):
                    raise ResearchError(
                        "invalid_request", "A revision must preserve the identity of the fact"
                    )
                seen = {fact.id}
                cursor = prior
                while cursor:
                    if cursor.id in seen:
                        raise ResearchError("invalid_request", "Cyclic fact revisions")
                    seen.add(cursor.id)
                    cursor = required("facts", cursor.supersedes) if cursor.supersedes else None
        for passage in graph["passages"].values():
            evidence = required("evidence", passage.evidence_id)
            document = required("documents", evidence.document_id)
            if passage.company_id != document.company_id:
                raise ResearchError(
                    "invalid_request", "Passage company differs from source document"
                )
        for provision in graph["provisions"].values():
            evidence = required("evidence", provision.evidence_id)
            if required("documents", evidence.document_id).kind != "regulation":
                raise ResearchError(
                    "invalid_request", "A provision must reference a regulatory document"
                )
            if provision.supersedes:
                prior = required("provisions", provision.supersedes)

                def identity(p):
                    return (p.authority, p.instrument, p.clause, sorted(p.entity_types))

                if identity(prior) != identity(provision):
                    raise ResearchError(
                        "invalid_request",
                        "Provision revisions must identify the same clause and entities",
                    )
                if provision.effective_from <= prior.effective_from:
                    raise ResearchError(
                        "invalid_request", "Provision revision effective dates must increase"
                    )
                if prior.effective_to and prior.effective_to != provision.effective_from:
                    raise ResearchError(
                        "invalid_request", "Explicit provision end disagrees with its replacement"
                    )
                old_doc = required("documents", required("evidence", prior.evidence_id).document_id)
                new_doc = required("documents", evidence.document_id)
                if not old_doc.published_on or not new_doc.published_on:
                    raise ResearchError(
                        "invalid_request", "Versioned provisions require verified publication dates"
                    )
                if new_doc.published_on < old_doc.published_on:
                    raise ResearchError(
                        "invalid_request", "Provision publication chronology is reversed"
                    )

    def source(self, evidence_id: str) -> dict:
        evidence = self.record("evidence", evidence_id)
        document = self.record("documents", evidence.document_id)
        link = document.url.split("#")[0]
        if evidence.pdf_page:
            link += f"#page={evidence.pdf_page}"
        location = evidence.section
        if evidence.pdf_page:
            location = f"PDF p. {evidence.pdf_page}"
            if evidence.printed_page:
                location += f" (printed p. {evidence.printed_page})"
        citation = f"[{document.title}, {location}]({link})"
        if evidence.trust in TRUST_LABELS:
            citation += f" (unreviewed: {TRUST_LABELS[evidence.trust]})"
        return {
            "evidence_id": evidence.id,
            "document_id": document.id,
            "title": document.title,
            "url": link,
            "location": location,
            "citation": citation,
            "trust": evidence.trust,
            "published_on": document.published_on.isoformat() if document.published_on else None,
            "reporting_year": document.reporting_year,
            "integrity": "local_snapshot" if document.sha256 else "remote_reference_only",
            "sha256": document.sha256,
            "locator": evidence.model_dump(mode="json"),
        }

    def fact_data(self, fact: Fact) -> dict:
        return {
            **fact.model_dump(mode="json"),
            "value": decimal_text(normalize(fact.raw_value, fact.unit)),
            "normalized_unit": normalized_unit(fact.unit),
            "source": self.source(fact.evidence_id),
            "warnings": self.fact_warnings(fact),
        }

    def fact_warnings(self, fact: Fact) -> list[dict]:
        """Comparability notes derived from stored facts, so import order never matters.

        A later report printing a different value for the same fact is a restatement. A
        statement that reports profit from discontinued operations presents revenue for
        continuing operations only, while its total profit includes that amount.
        """
        label = f"{fact.company_id} {fact.metric} FY{fact.fiscal_year}"
        unit = "INR per share" if fact.unit == "INR_per_share" else "crore"
        with self.connection() as conn:
            own = conn.execute(
                "SELECT d.id, json_extract(d.payload, '$.reporting_year') FROM evidence e "
                "JOIN documents d ON d.id=e.document_id WHERE e.id=?",
                (fact.evidence_id,),
            ).fetchone()
            same = conn.execute(
                "SELECT f.payload, json_extract(d.payload, '$.reporting_year'), "
                "json_extract(d.payload, '$.title') FROM facts f "
                "JOIN evidence e ON e.id=f.evidence_id JOIN documents d ON d.id=e.document_id "
                "WHERE f.company_id=? AND f.fiscal_year=? AND f.scope=? AND f.basis=? "
                "AND f.id<>? AND (f.metric=? OR (f.metric='profit_discontinued' AND d.id=?))",
                (
                    fact.company_id,
                    fact.fiscal_year,
                    fact.scope,
                    fact.basis,
                    fact.id,
                    fact.metric,
                    own[0],
                ),
            ).fetchall()
        warnings = []
        amount = normalize(fact.raw_value, fact.unit)
        step = resolution(fact.raw_value, fact.unit)
        restated = set()
        for payload, year, title in same:
            other = Fact.model_validate_json(payload)
            other_amount = normalize(other.raw_value, other.unit)
            if other.metric == fact.metric:
                later = year is not None and own[1] is not None and year > own[1]
                differs = abs(other_amount - amount) > step + resolution(
                    other.raw_value, other.unit
                )
                if later and differs and other_amount not in restated:
                    restated.add(other_amount)
                    warnings.append(
                        {
                            "kind": "restated",
                            "text": f"{label} was restated as {indian(other_amount)} {unit} "
                            f"in {title}",
                        }
                    )
            elif other_amount != 0:
                discontinued = indian(other_amount)
                if fact.metric in ("revenue", "other_income", "total_income"):
                    warnings.append(
                        {
                            "kind": "continuing_only",
                            "text": f"{label} covers continuing operations only; the same "
                            f"statement reports {discontinued} crore profit from discontinued "
                            "operations",
                        }
                    )
                elif fact.metric in ("profit_total", "profit_owners"):
                    warnings.append(
                        {
                            "kind": "includes_discontinued",
                            "text": f"{label} includes {discontinued} crore profit from "
                            "discontinued operations",
                        }
                    )
        return warnings

    def select_fact(
        self,
        company_id: str,
        metric: str,
        year: int,
        *,
        scope="consolidated",
        basis="Ind AS",
        policy="latest_available",
        known_on: date | None = None,
        trust="allow_automated",
    ) -> Fact:
        if policy not in ("latest_available", "originally_reported"):
            raise ResearchError("invalid_request", "Unknown restatement policy")
        if trust not in ("reviewed_only", "allow_automated"):
            raise ResearchError("invalid_request", "Unknown trust policy")
        cutoff = date_text(known_on)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT f.payload, json_extract(e.payload, '$.review_method') FROM facts f "
                "JOIN evidence e ON e.id=f.evidence_id "
                "JOIN documents d ON d.id=e.document_id "
                "WHERE f.company_id=? AND f.metric=? AND f.fiscal_year=? "
                "AND f.scope=? AND f.basis=? "
                "AND (? IS NULL OR (d.published_on IS NOT NULL AND d.published_on <= ?))",
                (company_id, metric, year, scope, basis, cutoff, cutoff),
            ).fetchall()
        # Reviewed evidence outranks automated extraction, which only fills gaps; among automated
        # facts, a year's own report outranks comparative columns printed in other reports.
        reviewed = [row for row in rows if row[1] in REVIEWED_METHODS]
        automated = [Fact.model_validate_json(row[0]) for row in rows if row not in reviewed]
        if reviewed or trust == "reviewed_only":
            candidates = [Fact.model_validate_json(row[0]) for row in reviewed]
        else:
            candidates = [f for f in automated if f.revision != "comparative"] or automated
        if policy == "originally_reported":
            candidates = [
                f
                for f in candidates
                if f.revision == "reported" and self.source(f.evidence_id)["reporting_year"] == year
            ]
        else:
            superseded = {f.supersedes for f in candidates if f.supersedes}
            candidates = [f for f in candidates if f.id not in superseded]
        if not candidates:
            qualifier = " reviewed" if trust == "reviewed_only" else ""
            raise ResearchError(
                "not_found",
                f"No{qualifier} {scope} {basis} {metric} for {company_id} FY{year} under {policy}",
            )
        identities = {
            (normalize(f.raw_value, f.unit), f.definition, f.period_start, f.period_end)
            for f in candidates
        }
        if len(identities) > 1:
            raise ResearchError(
                "ambiguous",
                f"Conflicting values or definitions for {metric} FY{year}; review required",
            )
        # Equivalent duplicates can be resolved deterministically without inventing a revision.
        return sorted(
            candidates, key=lambda f: (self.source(f.evidence_id)["published_on"] or "", f.id)
        )[-1]

    def search_passages(
        self,
        query: str,
        *,
        company_id=None,
        year=None,
        kind=None,
        known_on: date | None = None,
        limit=8,
    ) -> list[dict]:
        if not 1 <= limit <= 50:
            raise ResearchError("invalid_request", "limit must be between 1 and 50")
        cutoff = date_text(known_on)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT p.payload, bm25(passage_fts) AS score FROM passage_fts "
                "JOIN passages p ON p.id=passage_fts.id JOIN evidence e ON e.id=p.evidence_id "
                "JOIN documents d ON d.id=e.document_id WHERE passage_fts MATCH ? "
                "AND (? IS NULL OR p.company_id=?) AND (? IS NULL OR p.fiscal_year=?) "
                "AND (? IS NULL OR d.kind=?) "
                "AND (? IS NULL OR (d.published_on IS NOT NULL AND d.published_on<=?)) "
                "ORDER BY score, p.id LIMIT ?",
                (
                    fts_query(query),
                    company_id,
                    company_id,
                    year,
                    year,
                    kind,
                    kind,
                    cutoff,
                    cutoff,
                    limit,
                ),
            ).fetchall()
        return [
            {
                **json.loads(row[0]),
                "bm25_score": row[1],
                "source": self.source(json.loads(row[0])["evidence_id"]),
            }
            for row in rows
        ]

    def search_provisions(
        self,
        query: str,
        *,
        as_of: date,
        authority=None,
        entity_type=None,
        known_on: date | None = None,
        limit=8,
    ) -> list[dict]:
        if not 1 <= limit <= 50:
            raise ResearchError("invalid_request", "limit must be between 1 and 50")
        cutoff, effective = date_text(known_on), date_text(as_of)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT p.payload, bm25(provision_fts) AS score FROM provision_fts "
                "JOIN provisions p ON p.id=provision_fts.id JOIN evidence e ON e.id=p.evidence_id "
                "JOIN documents d ON d.id=e.document_id WHERE provision_fts MATCH ? "
                "AND p.effective_from<=? AND (p.effective_to IS NULL OR p.effective_to>?) "
                "AND p.verified_through>=? AND (? IS NULL OR p.authority=?) "
                "AND (? IS NULL OR (d.published_on IS NOT NULL AND d.published_on<=?)) "
                "ORDER BY score, p.id",
                (
                    fts_query(query),
                    effective,
                    effective,
                    effective,
                    authority,
                    authority,
                    cutoff,
                    cutoff,
                ),
            ).fetchall()
        results = []
        visible = self.regulation_versions(as_of=as_of, known_on=known_on)
        for row in rows:
            item = json.loads(row[0])
            if item["id"] not in visible:
                continue
            if entity_type and entity_type.casefold() not in {
                x.casefold() for x in item["entity_types"]
            }:
                continue
            results.append(
                {**item, "bm25_score": row[1], "source": self.source(item["evidence_id"])}
            )
        self.check_regulation_conflicts([item["id"] for item in results], visible)
        return results[:limit]

    def regulation_versions(self, *, as_of: date, known_on: date | None = None) -> dict:
        """Resolve replacement boundaries before verification; never revive expired history."""
        visible = {}
        for record in self.records("provisions"):
            source = self.source(record.evidence_id)
            if known_on and (
                not source["published_on"] or source["published_on"] > date_text(known_on)
            ):
                continue
            if record.effective_from <= as_of:
                visible[record.id] = record
        replaced = {p.supersedes for p in visible.values() if p.supersedes}
        return {
            rid: p
            for rid, p in visible.items()
            if rid not in replaced
            and (p.effective_to is None or as_of < p.effective_to)
            and as_of <= p.verified_through
        }

    @staticmethod
    def check_regulation_conflicts(matched_ids: list[str], visible: dict):
        for rid in matched_ids:
            match = visible[rid]
            for other in visible.values():
                if other.id == rid:
                    continue
                if (match.authority, match.instrument, match.clause) == (
                    other.authority,
                    other.instrument,
                    other.clause,
                ) and set(match.entity_types) & set(other.entity_types):
                    raise ResearchError(
                        "ambiguous",
                        "Conflicting active provision versions; review the amendment history",
                    )
