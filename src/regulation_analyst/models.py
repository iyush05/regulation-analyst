"""Reviewed import contract. Raw parser output must not masquerade as reviewed facts."""

import re
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .numbers import parse_number

Scope = Literal["consolidated", "standalone"]
Basis = Literal["Ind AS", "IFRS"]
Policy = Literal["latest_available", "originally_reported"]
Trust = Literal["reviewed_only", "allow_automated"]
ReviewMethod = Literal[
    "source_text_crosscheck",
    "visual_review",
    "human_review",
    "automated_extraction",
    "llm_resolved",
]
REVIEWED_METHODS = ("source_text_crosscheck", "visual_review", "human_review")
# Reported line items: (period kind, unit kind). Derived measures live in metrics.FORMULAS.
REPORTED_METRICS = {
    "revenue": ("annual", "monetary"),
    "other_income": ("annual", "monetary"),
    "total_income": ("annual", "monetary"),
    "operating_profit": ("annual", "monetary"),
    "finance_costs": ("annual", "monetary"),
    "depreciation_amortisation": ("annual", "monetary"),
    "profit_before_tax": ("annual", "monetary"),
    "tax_expense": ("annual", "monetary"),
    "profit_total": ("annual", "monetary"),
    "profit_owners": ("annual", "monetary"),
    "profit_discontinued": ("annual", "monetary"),
    "eps_basic": ("annual", "per_share"),
    "eps_diluted": ("annual", "per_share"),
    "operating_cash_flow": ("annual", "monetary"),
    "capex": ("annual", "monetary"),
    "equity_owners": ("instant", "monetary"),
    "non_controlling_interest": ("instant", "monetary"),
    "total_assets": ("instant", "monetary"),
    "current_assets": ("instant", "monetary"),
    "current_liabilities": ("instant", "monetary"),
    "borrowings_current": ("instant", "monetary"),
    "borrowings_noncurrent": ("instant", "monetary"),
    "cash_and_equivalents": ("instant", "monetary"),
}
Metric = Literal[tuple(REPORTED_METRICS)]
Unit = Literal["INR_crore", "INR_lakh", "INR_million", "INR", "INR_per_share"]
Status = Literal[
    "ok", "partial", "not_found", "ambiguous", "invalid_request", "undefined", "out_of_scope"
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9_.:-]+$")


class Company(Record):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    fiscal_end_month: int = Field(default=3, ge=1, le=12)
    fiscal_end_day: int = Field(default=31, ge=1, le=31)

    @property
    def names(self) -> list[str]:
        """Names a user may write: ID, legal name with or without its suffix, and aliases."""
        short = re.sub(
            r"[\s,]+(?:private\s+)?(?:limited|ltd\.?|pvt\.?\s+ltd\.?)$", "", self.name, flags=re.I
        )
        return list(dict.fromkeys([self.id, self.name, short, *self.aliases]))


class Document(Record):
    title: str = Field(min_length=1)
    url: str
    kind: Literal["annual_report", "transcript", "regulation", "filing"]
    company_id: str | None = None
    reporting_year: int | None = Field(default=None, ge=1900, le=2200)
    published_on: date | None = None
    captured_on: date
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str | None = None
    notes: str = ""

    @field_validator("url")
    @classmethod
    def source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("A source must have an HTTPS URL without embedded credentials")
        return value

    @model_validator(mode="after")
    def dates_and_snapshot(self):
        if self.published_on and self.published_on > self.captured_on:
            raise ValueError("Publication cannot follow capture")
        if bool(self.sha256) != bool(self.snapshot_path):
            raise ValueError("A snapshot requires both a path and its SHA-256")
        if self.kind != "regulation" and not self.company_id:
            raise ValueError("A company document requires company_id")
        return self


class Evidence(Record):
    document_id: str
    pdf_page: int | None = Field(default=None, ge=1)
    printed_page: str | None = None
    section: str = Field(min_length=1)
    table: str | None = None
    row: str | None = None
    column: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    excerpt: str = ""
    review_method: ReviewMethod
    reviewer: str = Field(min_length=1)
    reviewed_on: date
    # Validation gates passed before an automated import; empty for human-reviewed evidence.
    checks: list[str] = Field(default_factory=list)
    resolution_note: str = ""

    @model_validator(mode="after")
    def locator(self):
        if self.printed_page and self.pdf_page is None:
            raise ValueError("Printed PDF pages also require the one-based PDF page")
        if self.bbox and (self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]):
            raise ValueError("Invalid source bounding box")
        return self

    @model_validator(mode="after")
    def trust_record(self):
        if self.review_method in REVIEWED_METHODS:
            if self.resolution_note:
                raise ValueError("Only LLM-resolved evidence carries a resolution note")
        else:
            if not self.checks:
                raise ValueError("Automated evidence must record the validation gates it passed")
            if (self.review_method == "llm_resolved") != bool(self.resolution_note):
                raise ValueError("LLM-resolved evidence, and only it, requires a resolution note")
        return self

    @property
    def trust(self) -> str:
        if self.review_method in REVIEWED_METHODS:
            return "reviewed"
        return "automated" if self.review_method == "automated_extraction" else "llm_resolved"


class Fact(Record):
    company_id: str
    metric: Metric
    definition: str = Field(min_length=1)
    fiscal_year: int = Field(ge=1900, le=2200)
    period_start: date | None
    period_end: date
    period_kind: Literal["annual", "instant"] = "annual"
    scope: Scope = "consolidated"
    basis: Basis
    raw_value: str
    unit: Unit
    evidence_id: str
    revision: Literal["reported", "comparative", "restated"] = "reported"
    supersedes: str | None = None

    @field_validator("raw_value")
    @classmethod
    def explicit_number(cls, value: str) -> str:
        parse_number(value)
        return value

    @model_validator(mode="after")
    def period(self):
        if self.period_end.year != self.fiscal_year:
            raise ValueError("fiscal_year is the calendar year in which the period ends")
        if self.period_kind == "annual":
            if (
                self.period_start is None
                or not 364 <= (self.period_end - self.period_start).days <= 365
            ):
                raise ValueError("Annual facts require a complete 365/366-day reporting period")
        elif self.period_start is not None:
            raise ValueError("Point-in-time facts must not have period_start")
        kind, unit_kind = REPORTED_METRICS[self.metric]
        if (kind == "instant") != (self.period_kind == "instant"):
            raise ValueError("Balance-sheet items are instant facts; income measures are flows")
        if (unit_kind == "per_share") != (self.unit == "INR_per_share"):
            raise ValueError("Per-share metrics, and only they, use INR_per_share")
        if self.supersedes == self.id:
            raise ValueError("A fact cannot supersede itself")
        return self


class Passage(Record):
    evidence_id: str
    company_id: str | None = None
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)
    text: str = Field(min_length=1)
    representation: Literal["excerpt", "reviewed_summary"]
    speaker: str | None = None
    speaker_role: Literal["management", "analyst", "other"] | None = None
    topics: list[str] = Field(default_factory=list)


class Provision(Record):
    evidence_id: str
    authority: Literal["SEBI", "RBI"]
    instrument: str = Field(min_length=1)
    clause: str = Field(min_length=1)
    text: str = Field(min_length=1)
    representation: Literal["excerpt", "reviewed_summary"]
    entity_types: list[str] = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None
    verified_through: date
    amends: str | None = None
    supersedes: str | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.supersedes == self.id:
            raise ValueError("A provision cannot supersede itself")
        if self.verified_through < self.effective_from:
            raise ValueError("Verification must cover the effective date")
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("effective_to is exclusive and must follow effective_from")
        return self


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    description: str
    companies: list[Company] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    provisions: list[Provision] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [
            item.id
            for name in ("companies", "documents", "evidence", "facts", "passages", "provisions")
            for item in getattr(self, name)
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("Record IDs must be globally unique within a bundle")
        return self


class Result(BaseModel):
    status: Status
    message: str
    corpus_version: str
    data: dict = Field(default_factory=dict)


def year_number(value: str | int) -> int:
    text = str(value).strip().upper()
    if not re.fullmatch(r"(?:FY)?(?:\d{2}|\d{4})", text):
        raise ValueError("Use a fiscal year such as FY25 or 2025")
    year = int(text.removeprefix("FY"))
    year = year + 2000 if year < 100 else year
    if not 1900 <= year <= 2200:
        raise ValueError("Fiscal year outside supported range")
    return year
