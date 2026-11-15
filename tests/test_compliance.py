"""Tests for the rule checks and access rules, called directly as plain Python.

Each case is one of the people in mock_data/README.md who exist to test a rule.
"""

from datetime import date

import pytest

from app.config import CORPUS_DIR
from app.rag.chunking import chunk_corpus
from app.rag.loaders import load_corpus
from mcp_servers import compliance, hr_data


def results(report: dict) -> dict[str, str]:
    return {check["rule"]: check["result"] for check in report["checks"]}


def test_ordinary_pto_request_is_allowed_with_manager_approval():
    report = compliance.check_pto_request("E1007", date(2027, 3, 1), 3)
    assert report["outcome"] == "allowed" and report["approvals_required"] == ["manager"]


def test_new_starter_cannot_take_pto_in_the_first_60_days():
    report = compliance.check_pto_request("E1015", date(2027, 2, 15), 0.5)  # started January 11
    assert results(report)["probation"] == "extra_approval"
    assert "People Operations (written exception)" in report["approvals_required"]


def test_contractor_has_no_pto():
    report = compliance.check_pto_request("E1012", date(2027, 3, 1), 1)
    assert report["outcome"] == "not_allowed" and report["checks"][0]["citation"] == "POL-001 section 3.4"


def test_negative_balance_blocks_more_pto():
    assert results(compliance.check_pto_request("E1010", date(2027, 3, 1), 1))["balance"] == "fail"


def test_short_notice_and_long_absence_need_more_approval():
    report = compliance.check_pto_request("E1000", date(2027, 2, 3), 6)  # two days away, six days long
    assert results(report)["notice"] == "extra_approval"
    assert any("director" in approval for approval in report["approvals_required"])


def test_finance_blackout_needs_the_director():
    report = compliance.check_pto_request("E1009", date(2027, 3, 24), 2)  # last 10 business days of Q1
    assert results(report)["blackout"] == "extra_approval"


def test_international_days_over_twenty_is_an_exception_and_over_forty_is_refused():
    # E1008 has already used 12 of 20 days.
    within = compliance.check_international_remote_work("E1008", "Portugal", date(2027, 4, 5), 8)
    over = compliance.check_international_remote_work("E1008", "Portugal", date(2027, 4, 5), 10)
    far_over = compliance.check_international_remote_work("E1008", "Portugal", date(2027, 4, 5), 30)
    assert (within["outcome"], over["outcome"], far_over["outcome"]) == (
        "allowed",
        "allowed_with_extra_approval",
        "not_allowed",
    )
    assert any("Chief People Officer" in approval for approval in over["approvals_required"])


@pytest.mark.parametrize("employee_id", ["E1012", "E1016", "E1019", "E1021", "E1015"])
def test_people_who_are_not_eligible_to_work_abroad(employee_id):
    # contractor, intern, office-based, on a performance plan, on probation
    report = compliance.check_international_remote_work(employee_id, "Spain", date(2027, 3, 1), 5)
    assert report["outcome"] == "not_allowed"


def test_restricted_country_is_refused_and_the_list_matches_the_policy():
    report = compliance.check_international_remote_work("E1007", "russia", date(2027, 4, 5), 5)
    assert results(report)["location"] == "fail"

    section = next(c for c in chunk_corpus(load_corpus(CORPUS_DIR)) if c.chunk_id == "POL-006#7")
    in_policy = [line[2:].split(" Access")[0].strip() for line in section.text.splitlines() if line.startswith("- ")]
    assert sorted(in_policy) == sorted(compliance.RESTRICTED_LOCATIONS)


def test_access_rules():
    assert hr_data.check_access("E1007", "E1007", "benefits") == "self"
    assert hr_data.check_access("E1004", "E1007", "pto") == "manager"
    with pytest.raises(hr_data.AccessDenied):
        hr_data.check_access("E1004", "E1007", "benefits")  # a manager never sees benefits
    with pytest.raises(hr_data.AccessDenied):
        hr_data.check_access("E1003", "E1007", "profile")  # the manager's manager is not the manager
    with pytest.raises(hr_data.AccessDenied):
        hr_data.check_access("E1001", "E1007", "profile")  # even the Chief People Officer, through the assistant


def test_business_day_counting():
    assert hr_data.TODAY == date(2027, 2, 1)  # a Monday
    assert hr_data.business_days_until(date(2027, 2, 4)) == 3  # Monday, Tuesday, Wednesday
    assert hr_data.business_days_until(date(2027, 2, 8)) == 5  # the weekend does not count
