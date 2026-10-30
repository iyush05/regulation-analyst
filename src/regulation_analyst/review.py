"""Declarative table mappings and explicit promotion of reviewed extraction candidates."""

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ResearchError
from .metrics import DEFINITIONS
from .models import REPORTED_METRICS, Basis, Bundle, Company, Document, Scope
from .numbers import normalize
from .store import canonical


def squash(text) -> str:
    """Case- and whitespace-insensitive form; PDF cells wrap labels across lines."""
    return " ".join(str(text or "").split()).casefold()


def header_identifies_year(header: str, fiscal_year: int) -> bool:
    """A four-digit year, or a span such as 2024-25 that ends in the fiscal year."""
    if re.search(rf"(?<!\d){fiscal_year}(?!\d)", header):
        return True
    return any(
        int(start) + 1 == fiscal_year and int(end) == fiscal_year % 100
        for start, end in re.findall(r"(?<!\d)(\d{4})\s*[-–/]\s*(\d{2})(?!\d)", header)
    )


class ColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: int = Field(ge=0)
    # None: the year header sits above the detected table, in its external header names.
    header_row: int | None = Field(default=0, ge=0)
    fiscal_year: int = Field(ge=1900, le=2200)
    header_text: str = Field(min_length=1)
    revision: Literal["reported", "comparative", "restated"] = "reported"


class RowMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row: int = Field(ge=0)
    metric: str
    label: str = Field(min_length=1)
    definition: str | None = None
    # EPS rows sit in monetary tables but are stated per share.
    unit: Literal["INR_per_share"] | None = None


class TableMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    table_id: str
    printed_page: str | None = None
    title: str = Field(min_length=1)
    unit: Literal["INR", "INR_lakh", "INR_million", "INR_crore"]
    unit_evidence: str = Field(min_length=1)
    # Continuation pages often omit the unit line; it may be cited from an extracted page.
    unit_evidence_page: int | None = Field(default=None, ge=1)
    scope: Scope
    basis: Basis
    columns: list[ColumnMapping] = Field(min_length=1)
    rows: list[RowMapping] = Field(min_length=1)
    reconciliations: list["Reconciliation"] = Field(default_factory=list)


class Reconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_row: int = Field(ge=0)
    component_rows: list[int] = Field(min_length=1, max_length=100)
    tolerance_crore: str = "0"

    @field_validator("tolerance_crore")
    @classmethod
    def finite_tolerance(cls, value):
        try:
            tolerance = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Reconciliation tolerance must be a decimal") from exc
        if not tolerance.is_finite() or tolerance < 0:
            raise ValueError("Reconciliation tolerance must be nonnegative and finite")
        return value

    @model_validator(mode="after")
    def component_identity(self):
        if (
            any(row < 0 for row in self.component_rows)
            or len(set(self.component_rows)) != len(self.component_rows)
            or self.total_row in self.component_rows
        ):
            raise ValueError(
                "Reconciliation components must be distinct nonnegative rows excluding the total"
            )
        return self

    @classmethod
    def validate_tolerance(cls, value):
        return Decimal(cls.finite_tolerance(value))


class MappingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: Company
    document: Document
    tables: list[TableMapping] = Field(min_length=1)


def build_candidates(extraction_file: str | Path, mapping: MappingPlan) -> dict:
    path = Path(extraction_file).expanduser().resolve()
    artifact = json.loads(path.read_text())
    snapshot = path.parent / artifact["snapshot"]
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if digest != artifact["source_sha256"]:
        raise ResearchError(
            "invalid_request", "Extraction source hash no longer matches the original PDF"
        )
    if mapping.document.company_id != mapping.company.id:
        raise ResearchError("invalid_request", "Mapping company and document must match")
    pages = {p["pdf_page"]: p for p in artifact["pages"]}
    evidence, facts, diagnostics = [], [], []
    for table_map in mapping.tables:
        page = pages.get(table_map.page)
        if not page:
            raise ResearchError("invalid_request", f"Page {table_map.page} was not extracted")
        tables = {table["id"]: table for table in page["tables"]}
        table = tables.get(table_map.table_id)
        if not table:
            raise ResearchError("invalid_request", f"Missing extracted table {table_map.table_id}")
        unit_page = pages.get(table_map.unit_evidence_page or table_map.page)
        if not unit_page:
            raise ResearchError("invalid_request", "Unit evidence page was not extracted")
        if table_map.unit_evidence.casefold() not in unit_page["text"].casefold():
            raise ResearchError(
                "invalid_request", "Unit evidence is not present on the mapped source page"
            )
        unit_word = {"INR_crore": "crore", "INR_lakh": "lakh", "INR_million": "million"}
        if (
            table_map.unit != "INR"
            and unit_word[table_map.unit] not in table_map.unit_evidence.casefold()
        ):
            raise ResearchError("invalid_request", "Declared unit disagrees with unit evidence")
        if table_map.unit == "INR" and any(
            word in table_map.unit_evidence.casefold() for word in unit_word.values()
        ):
            raise ResearchError(
                "invalid_request", "Scaled monetary units cannot be mapped as unscaled INR"
            )
        for column in table_map.columns:
            for reconciliation in table_map.reconciliations:
                if any(row < 0 for row in reconciliation.component_rows):
                    raise ResearchError("invalid_request", "Reconciliation rows cannot be negative")
                tolerance = Reconciliation.validate_tolerance(reconciliation.tolerance_crore)
                try:
                    total = normalize(
                        table["rows"][reconciliation.total_row][column.column], table_map.unit
                    )
                    parts = sum(
                        (
                            normalize(table["rows"][row][column.column], table_map.unit)
                            for row in reconciliation.component_rows
                        ),
                        Decimal(0),
                    )
                    if abs(total - parts) > tolerance:
                        diagnostics.append(
                            {
                                "table": table_map.table_id,
                                "column": column.column,
                                "issue": "reconciliation_failed",
                                "total": str(total),
                                "component_sum": str(parts),
                            }
                        )
                except (IndexError, ValueError, TypeError):
                    diagnostics.append(
                        {
                            "table": table_map.table_id,
                            "column": column.column,
                            "issue": "reconciliation_cell_missing_or_invalid",
                        }
                    )
            try:
                header_value = str(
                    (
                        table["headers"]
                        if column.header_row is None
                        else table["rows"][column.header_row]
                    )[column.column]
                    or ""
                )
            except IndexError as exc:
                raise ResearchError(
                    "invalid_request", "Mapped header cell is outside the table"
                ) from exc
            if squash(column.header_text) not in squash(header_value):
                raise ResearchError(
                    "invalid_request", "Mapped year header is not in the source table column"
                )
            if not header_identifies_year(column.header_text, column.fiscal_year):
                raise ResearchError(
                    "invalid_request",
                    "Mapped header must explicitly identify the four-digit fiscal year",
                )
            end = date(
                column.fiscal_year, mapping.company.fiscal_end_month, mapping.company.fiscal_end_day
            )
            start = date(column.fiscal_year - 1, end.month, end.day) + timedelta(days=1)
            for row_map in table_map.rows:
                if row_map.metric not in DEFINITIONS:
                    raise ResearchError(
                        "invalid_request", f"Unsupported mapped metric {row_map.metric}"
                    )
                try:
                    row = table["rows"][row_map.row]
                    raw = row[column.column]
                except IndexError as exc:
                    raise ResearchError(
                        "invalid_request", "Mapped cell lies outside the extracted table"
                    ) from exc
                if not any(squash(row_map.label) in squash(cell) for cell in row):
                    raise ResearchError(
                        "invalid_request", "Mapped row label is absent from the source row"
                    )
                try:
                    normalize(raw, table_map.unit)
                except (ValueError, TypeError):
                    diagnostics.append(
                        {
                            "table": table_map.table_id,
                            "row": row_map.row,
                            "column": column.column,
                            "issue": "missing_or_invalid_number",
                            "raw": raw,
                        }
                    )
                    continue
                suffix = (
                    f"{mapping.document.id}-{table_map.table_id}-"
                    f"{row_map.metric}-{column.fiscal_year}"
                )
                eid, fid = "ev-" + suffix, "fact-" + suffix
                evidence.append(
                    {
                        "id": eid,
                        "document_id": mapping.document.id,
                        "pdf_page": table_map.page,
                        "printed_page": table_map.printed_page,
                        "section": table_map.title,
                        "table": table_map.title,
                        "row": row_map.label,
                        "column": column.header_text,
                        "bbox": (
                            table["row_cell_boxes"][row_map.row][column.column]
                            if table.get("row_cell_boxes")
                            else table.get("bbox")
                        ),
                        "review_method": "pending",
                        "reviewer": "pending",
                        "reviewed_on": None,
                    }
                )
                instant = REPORTED_METRICS.get(row_map.metric, ("annual",))[0] == "instant"
                facts.append(
                    {
                        "id": fid,
                        "company_id": mapping.company.id,
                        "metric": row_map.metric,
                        "definition": row_map.definition or DEFINITIONS[row_map.metric],
                        "fiscal_year": column.fiscal_year,
                        "period_start": None if instant else start.isoformat(),
                        "period_end": end.isoformat(),
                        "period_kind": "instant" if instant else "annual",
                        "scope": table_map.scope,
                        "basis": table_map.basis,
                        "raw_value": raw,
                        "unit": row_map.unit or table_map.unit,
                        "evidence_id": eid,
                        "revision": column.revision,
                    }
                )
    document = mapping.document.model_dump(mode="json")
    document.update(sha256=digest, snapshot_path=str(snapshot))
    bundle = {
        "schema_version": 1,
        "description": "Mapped candidates awaiting explicit source review",
        "companies": [mapping.company.model_dump(mode="json")],
        "documents": [document],
        "evidence": evidence,
        "facts": facts,
        "passages": [],
        "provisions": [],
    }
    candidate = {
        "status": "review_required",
        "source_sha256": digest,
        "parser": artifact["parser"],
        "parser_version": artifact["parser_version"],
        "mapping": mapping.model_dump(mode="json"),
        "bundle": bundle,
        "diagnostics": diagnostics,
    }
    candidate["candidate_sha256"] = hashlib.sha256(canonical(candidate).encode()).hexdigest()
    return candidate


def approve_candidates(
    candidate: dict, *, reviewer: str, method: str, reviewed_on: date, expected_digest: str
) -> Bundle:
    if (
        method not in ("source_text_crosscheck", "visual_review", "human_review")
        or not reviewer.strip()
    ):
        raise ResearchError(
            "invalid_request", "An explicit reviewer and supported review method are required"
        )
    original = {k: v for k, v in candidate.items() if k != "candidate_sha256"}
    actual = hashlib.sha256(canonical(original).encode()).hexdigest()
    if expected_digest != actual or candidate.get("candidate_sha256") != actual:
        raise ResearchError(
            "invalid_request", "Review digest differs from the candidate that was inspected"
        )
    if candidate["diagnostics"]:
        raise ResearchError(
            "invalid_request", "Resolve extraction diagnostics before approving this bundle"
        )
    if not candidate["bundle"]["facts"]:
        raise ResearchError("invalid_request", "An empty candidate cannot be approved")
    if reviewed_on > date.today():
        raise ResearchError("invalid_request", "Review date cannot be in the future")
    bundle = json.loads(json.dumps(candidate["bundle"]))
    for evidence in bundle["evidence"]:
        evidence.update(
            reviewer=reviewer, review_method=method, reviewed_on=reviewed_on.isoformat()
        )
    bundle["description"] = f"Explicitly reviewed mapping; candidate SHA-256 {actual}"
    return Bundle.model_validate(bundle)
