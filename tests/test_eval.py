"""Tests for the evaluation set and the scoring code. No model is called.

A gold case with a typo in it (a tool name that does not exist, a citation to
a section that is not in the corpus) would fail every time and look like the
agent's fault. These tests catch that kind of mistake before any money is spent.
"""

import json

from app.rag.index import PolicyIndex
from evaluation.judge import Behaviour
from evaluation.run_eval import HERE, _all_present, _percentile, summarise
from mcp_servers import hr_data

CASES = json.loads((HERE / "gold_cases.json").read_text(encoding="utf-8"))["cases"]
TOOLS = {
    "search_policy_documents",
    "get_policy_section",
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "check_policy_compliance",
    "draft_hr_email",
    "create_mock_hr_ticket",
    "list_my_tickets",
}
REAL_CITATIONS = {chunk.citation for chunk in PolicyIndex.from_corpus().chunks}


def _flat(items: list) -> list[str]:
    return [option for item in items for option in (item if isinstance(item, list) else [item])]


def test_the_set_has_20_to_30_cases_with_unique_ids():
    ids = [case["id"] for case in CASES]
    assert 20 <= len(CASES) <= 32
    assert len(set(ids)) == len(ids)


def test_the_set_covers_every_kind_of_request_the_brief_asks_for():
    categories = {case["category"] for case in CASES}
    assert categories == {"policy", "multi_document", "tool", "workflow", "ambiguous", "out_of_scope", "safety"}


def test_every_case_refers_only_to_things_that_exist():
    behaviours = set(Behaviour.__args__)
    for case in CASES:
        assert case["employee_id"] in hr_data.EMPLOYEES, case["id"]
        assert case["turns"] and case["gold_answer"], case["id"]
        assert set(_flat(case.get("required_tools", []))) <= TOOLS, case["id"]
        assert set(case.get("forbidden_tools", [])) <= TOOLS, case["id"]
        assert set(case.get("expected_citations", [])) <= REAL_CITATIONS, case["id"]
        assert set(_flat([case["expected_behaviour"]])) <= behaviours, case["id"]


def test_any_of_matching():
    in_list = lambda needle, items: needle in items  # noqa: E731
    assert _all_present(["a", ["b", "c"]], ["a", "c"], in_list)
    assert not _all_present(["a", ["b", "c"]], ["a"], in_list)
    assert _all_present([], [], in_list)


def test_percentile_is_nearest_rank():
    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    assert _percentile(values, 50) == 500
    assert _percentile(values, 95) == 1000
    assert _percentile([42], 95) == 42


def _record(case_id: str, category: str, **checks) -> dict:
    defaults = {"tools": True, "finished": True, "facts": True, "expected_citation": True, "citations_supported": True, "safe": True}
    checks = {**defaults, **checks}
    return {
        "id": case_id,
        "category": category,
        "checks": checks,
        "passed": all(checks.values()),
        "citations": ["POL-001 section 1", "POL-001 section 2"],
        "unverified_citations": [] if checks["citations_supported"] else ["POL-001 section 2"],
        "latency_ms": [1000],
        "steps": [2],
        "input_tokens": 1000,
        "output_tokens": 100,
    }


def test_summary_counts_the_right_cases_for_each_metric():
    cases = {
        "A": {"expected_behaviour": "answered", "expected_citations": ["x"], "must_include": ["y"]},
        "B": {"expected_behaviour": "answered"},
        "C": {"expected_behaviour": "refused_access"},
    }
    records = [
        _record("A", "workflow", citations_supported=False),
        _record("B", "workflow", tools=False),
        _record("C", "safety", behaviour=True),
    ]
    summary = summarise(records, cases)

    assert summary["cases"] == 3
    assert summary["passed_every_check"] == 0.333
    assert summary["agent_behaviour"]["tool_selection_accuracy"] == 0.667
    assert summary["agent_behaviour"]["workflow_completion_rate"] == 0.0
    assert summary["agent_behaviour"]["clarification_and_escalation_accuracy"] == 1.0  # only case C counts
    assert summary["answer_quality"]["citation_accuracy"] == 0.833  # 5 of 6 citations were supported
    assert summary["by_category"] == {"workflow": "0/2", "safety": "1/1"}
