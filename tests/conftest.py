from datetime import date
from importlib.resources import files

import pytest

from regulation_analyst.metrics import DEFINITIONS
from regulation_analyst.models import Bundle, Company, Document, Evidence, Fact
from regulation_analyst.service import ResearchService
from regulation_analyst.store import Store


@pytest.fixture
def demo_bundle():
    return Bundle.model_validate_json(
        files("regulation_analyst").joinpath("fixtures/demo.json").read_text()
    )


@pytest.fixture
def store(tmp_path, demo_bundle):
    writable = Store(tmp_path / "research.sqlite3", readonly=False)
    writable.import_bundle(demo_bundle)
    return Store(writable.path)


@pytest.fixture
def service(store):
    return ResearchService(store)


@pytest.fixture
def synthetic_bundle():
    """Synthetic values, explicitly unrelated to any real company."""

    def make(rows, companies=("alpha",), published="2025-05-01", document_id="synthetic-report"):
        firms = [
            Company(id=c, name=f"Synthetic {c.title()}", aliases=[c.upper()]) for c in companies
        ]
        docs, evidence, facts = [], [], []
        for company in companies:
            docs.append(
                Document(
                    id=f"{document_id}-{company}",
                    title="Synthetic test report",
                    url="https://example.org/synthetic.pdf",
                    kind="annual_report",
                    company_id=company,
                    reporting_year=2025,
                    published_on=date.fromisoformat(published) if published else None,
                    captured_on=date(2026, 10, 27),
                )
            )
        for index, row in enumerate(rows):
            data = dict(row)
            year = data.pop("fiscal_year", 2025)
            company = data.pop("company_id", companies[0])
            metric = data["metric"]
            fid = data.pop("id", f"synthetic-{index}")
            eid = "ev-" + fid
            evidence.append(
                Evidence(
                    id=eid,
                    document_id=f"{document_id}-{company}",
                    pdf_page=2,
                    printed_page="1",
                    section="Synthetic financial statements",
                    table="Synthetic table",
                    row=metric,
                    column=str(year),
                    review_method="human_review",
                    reviewer="Synthetic test fixture",
                    reviewed_on=date(2026, 10, 27),
                )
            )
            instant = metric == "equity_owners"
            defaults = dict(
                id=fid,
                company_id=company,
                fiscal_year=year,
                definition=DEFINITIONS[metric],
                evidence_id=eid,
                period_kind="instant" if instant else "annual",
                period_start=None if instant else date(year - 1, 4, 1),
                period_end=date(year, 3, 31),
                basis="Ind AS",
                unit="INR_crore",
            )
            defaults.update(data)
            facts.append(Fact(**defaults))
        return Bundle(
            description="Synthetic regression fixtures, not company data",
            companies=firms,
            documents=docs,
            evidence=evidence,
            facts=facts,
        )

    return make


@pytest.fixture
def synthetic_store(tmp_path, synthetic_bundle):
    def make(rows, **kwargs):
        store = Store(tmp_path / "synthetic.sqlite3", readonly=False)
        store.import_bundle(synthetic_bundle(rows, **kwargs))
        return store

    return make
