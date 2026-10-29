import sqlite3
from datetime import date

import pytest
from pydantic import ValidationError

from regulation_analyst.errors import ResearchError
from regulation_analyst.models import Bundle, Company, Fact
from regulation_analyst.store import Store


def test_reimport_is_idempotent_and_version_stable(store, demo_bundle):
    writer = Store(store.path, readonly=False)
    before = writer.version
    result = writer.import_bundle(demo_bundle)
    assert not any(result["inserted"].values())
    assert writer.version == before


def test_existing_ids_cannot_change(store, demo_bundle):
    changed = demo_bundle.model_copy(deep=True)
    changed.facts[0] = changed.facts[0].model_copy(update={"raw_value": "1"})
    with pytest.raises(ResearchError, match="Immutable ID collision"):
        Store(store.path, readonly=False).import_bundle(changed)
    assert store.record("facts", demo_bundle.facts[0].id).raw_value == "1,53,670"


def test_bad_reference_rolls_back_entire_import(store):
    before = store.version
    incoming = Bundle(
        description="Invalid synthetic import",
        companies=[Company(id="new", name="New")],
        facts=[
            Fact(
                id="bad",
                company_id="new",
                metric="revenue",
                definition="revenue.operations.v1",
                fiscal_year=2025,
                period_start=date(2024, 4, 1),
                period_end=date(2025, 3, 31),
                basis="Ind AS",
                raw_value="1",
                unit="INR_crore",
                evidence_id="missing",
            )
        ],
    )
    with pytest.raises(ResearchError, match="Missing evidence"):
        Store(store.path, readonly=False).import_bundle(incoming)
    assert store.version == before
    assert "new" not in [c.id for c in store.records("companies")]


def test_query_connection_is_enforced_read_only(store):
    with store.connection() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM facts")


def test_wrong_company_evidence_is_rejected(tmp_path, synthetic_bundle):
    bundle = synthetic_bundle(
        [{"metric": "revenue", "raw_value": "100"}], companies=("alpha", "beta")
    )
    bundle.facts[0] = bundle.facts[0].model_copy(update={"company_id": "beta"})
    with pytest.raises(ResearchError, match="company differs"):
        Store(tmp_path / "test.db", readonly=False).import_bundle(bundle)


def test_restated_and_original_views_respect_publication_cutoff(tmp_path, synthetic_bundle):
    writer = Store(tmp_path / "test.db", readonly=False)
    original = synthetic_bundle(
        [{"id": "original", "metric": "revenue", "raw_value": "100"}], published="2025-05-01"
    )
    writer.import_bundle(original)
    revision = synthetic_bundle(
        [
            {
                "id": "revised",
                "metric": "revenue",
                "raw_value": "90",
                "revision": "restated",
                "supersedes": "original",
            }
        ],
        published="2026-05-01",
        document_id="later-report",
    )
    writer.import_bundle(revision)
    assert writer.select_fact("alpha", "revenue", 2025).raw_value == "90"
    assert (
        writer.select_fact("alpha", "revenue", 2025, policy="originally_reported").raw_value
        == "100"
    )
    assert (
        writer.select_fact("alpha", "revenue", 2025, known_on=date(2025, 6, 1)).raw_value == "100"
    )
    with pytest.raises(ResearchError, match="No consolidated"):
        writer.select_fact("alpha", "revenue", 2025, known_on=date(2025, 4, 1))


def test_unlinked_conflicting_values_are_ambiguous(tmp_path, synthetic_bundle):
    writer = Store(tmp_path / "test.db", readonly=False)
    writer.import_bundle(synthetic_bundle([{"id": "one", "metric": "revenue", "raw_value": "100"}]))
    writer.import_bundle(
        synthetic_bundle(
            [{"id": "two", "metric": "revenue", "raw_value": "99"}], document_id="another-report"
        )
    )
    with pytest.raises(ResearchError) as error:
        writer.select_fact("alpha", "revenue", 2025)
    assert error.value.status == "ambiguous"


def test_unknown_publication_is_excluded_from_historical_research(service):
    result = service.call(
        "get_table", company="Infosys", years=[2025], metrics=["revenue"], known_on="2026-10-27"
    )
    assert result.status == "not_found"


def test_source_has_pdf_index_separate_from_printed_page(store):
    source = store.source("ev-infosys-indas-2025-revenue")
    assert source["url"].endswith("#page=346")
    assert source["locator"]["printed_page"] == "374"
    assert source["sha256"] is None
    assert source["integrity"] == "remote_reference_only"


def test_unknown_import_fields_are_rejected():
    with pytest.raises(ValidationError):
        Bundle.model_validate({"description": "test", "auto_accept_unreviewed": True})


def test_short_year_is_not_mislabeled_as_annual(synthetic_bundle):
    with pytest.raises(ValidationError):
        synthetic_bundle(
            [{"metric": "revenue", "raw_value": "1", "period_start": date(2025, 1, 1)}]
        )
