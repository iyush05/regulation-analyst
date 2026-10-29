"""Filtered BM25 + dense cosine retrieval, RRF fusion, and optional cross-encoding."""

import json
import math
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from .errors import ResearchError
from .store import Store, canonical


def unit_vector(values: list[float], dimension: int | None = None) -> list[float]:
    if not values or (dimension is not None and len(values) != dimension):
        raise ResearchError("invalid_request", "Embedding dimensions do not match")
    if any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
        for x in values
    ):
        raise ResearchError("invalid_request", "Embedding contains invalid values")
    norm = math.sqrt(sum(x * x for x in values))
    if norm == 0 or not math.isfinite(norm):
        raise ResearchError("invalid_request", "Embedding has invalid magnitude")
    return [x / norm for x in values]


def build_index(store: Store, path: str | Path, embedder) -> dict:
    version = store.version
    records = [
        (kind, record) for kind in ("passages", "provisions") for record in store.records(kind)
    ]
    if not records:
        raise ResearchError("not_found", "No reviewed passages or provisions to index")
    vectors = embedder.embed([record.text for _, record in records])
    if len(vectors) != len(records):
        raise ResearchError("invalid_request", "Embedding response count differs from corpus")
    dimension = len(vectors[0])
    vectors = [unit_vector(vector, dimension) for vector in vectors]
    if version != store.version:
        raise ResearchError("invalid_request", "Corpus changed during index construction; rebuild")
    metadata = {
        "schema_version": 1,
        "corpus_version": version,
        "model": embedder.identity,
        "dimension": dimension,
        "records": len(records),
        "metric": "cosine",
    }
    destination = Path(path).expanduser().resolve()
    if destination == store.path:
        raise ResearchError(
            "invalid_request", "Vector index must be separate from the research database"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".index-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with sqlite3.connect(temporary) as conn:
            conn.execute("CREATE TABLE metadata (payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE vectors (id TEXT PRIMARY KEY, kind TEXT, vector TEXT)")
            conn.execute("INSERT INTO metadata VALUES (?)", (canonical(metadata),))
            conn.executemany(
                "INSERT INTO vectors VALUES (?, ?, ?)",
                [
                    (record.id, kind, canonical(vector))
                    for (kind, record), vector in zip(records, vectors, strict=True)
                ],
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "ok", "index": str(destination), **metadata}


class HybridRetriever:
    def __init__(self, store: Store, path: str | Path, embedder, reranker=None):
        self.store, self.path, self.embedder, self.reranker = (
            store,
            Path(path).resolve(),
            embedder,
            reranker,
        )

    def eligible(
        self,
        kind: str,
        *,
        company_id=None,
        year=None,
        document_type=None,
        known_on=None,
        as_of=None,
        authority=None,
        entity_type=None,
    ) -> dict:
        cutoff = date.fromisoformat(known_on) if known_on else None
        effective = date.fromisoformat(as_of) if as_of else None
        eligible = {}
        visible = (
            self.store.regulation_versions(as_of=effective, known_on=cutoff)
            if kind == "provisions" and effective
            else {}
        )
        documents = {d.id: d for d in self.store.records("documents")}
        evidence = {e.id: e for e in self.store.records("evidence")}
        for record in self.store.records(kind):
            document = documents[evidence[record.evidence_id].document_id]
            if cutoff and (not document.published_on or document.published_on > cutoff):
                continue
            if kind == "passages":
                if company_id and record.company_id != company_id:
                    continue
                if year is not None and record.fiscal_year != year:
                    continue
                if document_type and document.kind != document_type:
                    continue
            else:
                if not effective:
                    raise ResearchError("invalid_request", "Regulation retrieval requires as_of")
                if record.id not in visible:
                    continue
                if (
                    record.effective_from > effective
                    or record.verified_through < effective
                    or record.effective_to
                    and record.effective_to <= effective
                ):
                    continue
                if authority and record.authority != authority:
                    continue
                if entity_type and entity_type.casefold() not in {
                    x.casefold() for x in record.entity_types
                }:
                    continue
            eligible[record.id] = record
        return eligible

    def search(self, query: str, *, kind="passages", limit=8, **filters) -> list[dict]:
        if kind not in ("passages", "provisions") or not 1 <= limit <= 50 or not query.strip():
            raise ResearchError("invalid_request", "Invalid retrieval kind, limit, or empty query")
        if not self.path.is_file():
            raise ResearchError(
                "not_found", "Build a vector index before enabling hybrid retrieval"
            )
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as conn:
            metadata = json.loads(conn.execute("SELECT payload FROM metadata").fetchone()[0])
            if (
                metadata["corpus_version"] != self.store.version
                or metadata["model"] != self.embedder.identity
            ):
                raise ResearchError(
                    "invalid_request", "Vector index is stale or uses a different model; rebuild"
                )
            vectors = conn.execute(
                "SELECT id, vector FROM vectors WHERE kind=?", (kind,)
            ).fetchall()
        eligible = self.eligible(kind, **filters)
        if kind == "provisions":
            self.store.check_regulation_conflicts(list(eligible), eligible)
        if not eligible:
            return []
        query_vector = unit_vector(self.embedder.embed([query])[0], metadata["dimension"])
        dense = sorted(
            [
                (
                    record_id,
                    sum(
                        x * y
                        for x, y in zip(
                            query_vector,
                            unit_vector(json.loads(vector), metadata["dimension"]),
                            strict=True,
                        )
                    ),
                )
                for record_id, vector in vectors
                if record_id in eligible
            ],
            key=lambda pair: (-pair[1], pair[0]),
        )[:50]
        cutoff = date.fromisoformat(filters["known_on"]) if filters.get("known_on") else None
        if kind == "passages":
            lexical = self.store.search_passages(
                query,
                company_id=filters.get("company_id"),
                year=filters.get("year"),
                kind=filters.get("document_type"),
                known_on=cutoff,
                limit=50,
            )
        else:
            lexical = self.store.search_provisions(
                query,
                as_of=date.fromisoformat(filters["as_of"]),
                authority=filters.get("authority"),
                entity_type=filters.get("entity_type"),
                known_on=cutoff,
                limit=50,
            )
        ranks = {}
        for channel, ids in (
            ("lexical", [item["id"] for item in lexical]),
            ("dense", [item[0] for item in dense]),
        ):
            for rank, record_id in enumerate(ids, 1):
                if record_id in eligible:
                    ranks.setdefault(record_id, {})[channel] = rank
        fused = sorted(
            ranks, key=lambda rid: (-sum(1 / (60 + r) for r in ranks[rid].values()), rid)
        )[:50]
        scores = {}
        if self.reranker and fused:
            predicted = self.reranker.score(query, [eligible[rid].text for rid in fused])
            if len(predicted) != len(fused) or not all(math.isfinite(x) for x in predicted):
                raise ResearchError("invalid_request", "Reranker returned invalid scores")
            scores = dict(zip(fused, predicted, strict=True))
            fused.sort(key=lambda rid: (-scores[rid], rid))
        return [
            {
                **eligible[rid].model_dump(mode="json"),
                "source": self.store.source(eligible[rid].evidence_id),
                "retrieval": {
                    "ranks": ranks[rid],
                    "rrf_score": sum(1 / (60 + r) for r in ranks[rid].values()),
                    "dense_score": dict(dense).get(rid),
                    "rerank_score": scores.get(rid),
                    "embedding_model": self.embedder.identity,
                    "reranker": self.reranker.identity if self.reranker else None,
                },
            }
            for rid in fused[:limit]
        ]
