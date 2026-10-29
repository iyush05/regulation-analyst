from copy import deepcopy

import pytest

from regulation_analyst.answering import validate_rows
from regulation_analyst.errors import ResearchError
from regulation_analyst.service import ResearchService


def test_margin_change_and_management_answer_is_grounded(service):
    result = service.call(
        "answer_question",
        question="How did Infosys operating margin change from FY24 to FY25 "
        "and what did management say?",
    )
    assert result.status == "ok"
    assert len(result.data["rows"]) == 2
    assert result.data["changes"][0]["calculation"]["display_value"] == "0.46"
    assert result.data["commentary"][0]["speaker"] == "Jayesh Sanghrajka"
    assert result.data["validation"] == "passed"
    assert all(claim["evidence_ids"] for claim in result.data["claims"])
    assert "#page=346" in result.data["answer"]
    assert "#page=6" in result.data["answer"]


def test_three_year_ifrs_net_margin(service):
    result = service.call("answer_question", question="Infosys IFRS net margin FY23 to FY25")
    assert result.status == "ok"
    assert [row["fiscal_year"] for row in result.data["rows"]] == [2023, 2024, 2025]
    assert [row["calculation"]["display_value"] for row in result.data["rows"]] == [
        "16.42",
        "17.07",
        "16.39",
    ]


def test_no_operating_commentary_used_to_explain_net_margin(service):
    result = service.call(
        "answer_question", question="Explain Infosys net margin FY25 with management commentary"
    )
    assert result.status == "partial"
    assert not result.data["commentary"]
    assert "No management commentary" in result.data["missing"][0]["reason"]


@pytest.mark.parametrize(
    "question,status",
    [
        ("Should I buy Infosys?", "out_of_scope"),
        ("Infosys Q4 operating margin FY25", "out_of_scope"),
        ("Infosys EBITDA FY25", "out_of_scope"),
        ("Infosys margin FY25", "ambiguous"),
        ("Infosys revenue for the last three years", "ambiguous"),
        ("Infosys revenue FY26", "not_found"),
        ("Infosys standalone revenue FY25", "not_found"),
        ("Compare Infosys and Wipro operating margin FY25", "ambiguous"),
        ("Infosys revenue and net profit FY25", "ambiguous"),
        ("Infosys revenue FY25 to FY23", "invalid_request"),
    ],
)
def test_missing_or_unsupported_requests_do_not_generate_numbers(service, question, status):
    result = service.call("answer_question", question=question)
    assert result.status == status
    assert not result.data.get("rows")


def test_missing_year_does_not_shorten_requested_range_silently(service):
    result = service.call("answer_question", question="Infosys operating margin FY23 to FY25")
    assert result.status == "partial"
    assert result.data["missing"][0]["fiscal_year"] == 2023


def test_missing_company_is_visible_in_comparison(service):
    result = service.call(
        "compare_companies", metric="operating_margin", companies=["Infosys", "TCS"], years=["FY25"]
    )
    assert result.status == "partial"
    assert len(result.data["rows"]) == 1
    assert result.data["missing"][0]["company_id"] == "tcs"


def test_comparison_aligns_same_metric_and_period(synthetic_store):
    store = synthetic_store(
        [
            {"id": "a-p", "metric": "operating_profit", "raw_value": "20", "company_id": "alpha"},
            {"id": "a-r", "metric": "revenue", "raw_value": "100", "company_id": "alpha"},
            {"id": "b-p", "metric": "operating_profit", "raw_value": "30", "company_id": "beta"},
            {"id": "b-r", "metric": "revenue", "raw_value": "100", "company_id": "beta"},
        ],
        companies=("alpha", "beta"),
    )
    result = ResearchService(store).call(
        "compare_companies", metric="operating_margin", companies=["alpha", "beta"], years=[2025]
    )
    assert result.status == "ok"
    assert [r["calculation"]["display_value"] for r in result.data["rows"]] == ["20.00", "30.00"]


def test_tampered_answer_number_fails_validation(service, store):
    result = service.call("answer_question", question="Infosys operating margin FY25")
    rows = deepcopy(result.data["rows"])
    rows[0]["value"] = "99.99"
    with pytest.raises(ResearchError, match="differs from its calculation"):
        validate_rows(store, rows, result.data["calculations"])


def test_tampered_calculation_lineage_fails_validation(service, store):
    result = service.call("answer_question", question="Infosys operating margin FY25")
    calculations = deepcopy(result.data["calculations"])
    calculations[0]["inputs"][0]["value"] = "99.99"
    with pytest.raises(ResearchError) as error:
        validate_rows(store, result.data["rows"], calculations)
    assert error.value.status == "invalid_request"


def test_search_filters_prevent_wrong_year_and_company_hits(service):
    good = service.call("search_filings", query="operating margin", company="Infosys", year="FY25")
    assert len(good.data["passages"]) == 1
    for filters in ({"company": "TCS", "year": "FY25"}, {"company": "Infosys", "year": "FY24"}):
        result = service.call("search_filings", query="operating margin", **filters)
        assert result.status == "not_found"


def test_fts_operators_are_treated_as_literal_terms(service):
    result = service.call(
        "search_filings", query='margin" OR *; DROP TABLE facts; --', company="Infosys"
    )
    assert result.status in ("ok", "not_found")
    assert service.store.records("facts")


@pytest.mark.parametrize(
    "as_of,status",
    [
        ("2025-06-11", "not_found"),
        ("2025-06-12", "ok"),
        ("2025-06-13", "not_found"),
        ("2026-10-27", "not_found"),
    ],
)
def test_regulations_respect_verified_coverage(service, as_of, status):
    result = service.call(
        "search_regulations", query="KYC commencement", as_of=as_of, authority="RBI"
    )
    assert result.status == status


def test_regulation_does_not_apply_to_arbitrary_company_type(service):
    result = service.call(
        "search_regulations", query="KYC", as_of="2025-06-12", entity_type="IT company"
    )
    assert result.status == "not_found"


def test_regulatory_question_requires_date(service):
    assert service.call("answer_question", question="What are RBI KYC rules?").status == "ambiguous"
    result = service.call("answer_question", question="RBI KYC commencement as of 2025-06-12")
    assert result.status == "ok"
    assert "Paragraph 3(ii)" in result.data["answer"]


def test_ratio_cagr_is_not_silently_replaced_by_margin_change(service):
    result = service.call("answer_question", question="Infosys operating margin CAGR FY24 to FY25")
    assert result.status == "out_of_scope"


@pytest.mark.parametrize("filters", [{"scope": "group"}, {"basis": "US GAAP"}, {"policy": "guess"}])
def test_invalid_selection_is_not_mislabeled_as_missing_data(service, filters):
    result = service.call("get_table", company="Infosys", years=[2025], **filters)
    assert result.status == "invalid_request"


def test_tampered_company_identity_is_rejected(service, store):
    result = service.call("answer_question", question="Infosys operating margin FY25")
    rows = deepcopy(result.data["rows"])
    rows[0]["company_id"] = "tcs"
    with pytest.raises(ResearchError, match="identity"):
        validate_rows(store, rows, result.data["calculations"])
