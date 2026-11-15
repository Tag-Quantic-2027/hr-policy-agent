"""Checks that the mock data is internally consistent.

An agent that reasons over broken data gives wrong answers that look like
agent bugs. These tests catch data mistakes before they reach the agent.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "mock_data"


def load(name: str, key: str) -> list[dict]:
    return json.loads((DATA / name).read_text())[key]


EMPLOYEES = {e["employee_id"]: e for e in load("employees.json", "employees")}
PTO = {p["employee_id"]: p for p in load("pto_balances.json", "pto_balances")}
BENEFITS = {b["employee_id"]: b for b in load("benefits_elections.json", "benefits_elections")}
OFFICES = {o["office_id"] for o in load("offices.json", "offices")}
TICKETS = load("tickets.json", "tickets")


def test_every_manager_and_office_exists():
    for e in EMPLOYEES.values():
        assert e["office_id"] in OFFICES
        if e["manager_id"] is not None:
            assert e["manager_id"] in EMPLOYEES


def test_emails_use_the_reserved_example_domain():
    for e in EMPLOYEES.values():
        assert e["email"].endswith("@fernhill.example")


def test_pto_available_matches_its_parts():
    for p in PTO.values():
        expected = p["accrued_ytd_days"] + p["carryover_days"] - p["used_ytd_days"] - p["pending_days"]
        assert abs(expected - p["available_days"]) < 0.01, p["employee_id"]


def test_carryover_never_exceeds_five_days():
    assert all(p["carryover_days"] <= 5 for p in PTO.values())


def test_only_employees_have_pto_and_benefits():
    for emp_id, e in EMPLOYEES.items():
        is_employee = e["employment_type"] in ("full_time", "part_time")
        assert (emp_id in PTO) == is_employee, emp_id
        assert (emp_id in BENEFITS) == is_employee, emp_id


def test_tickets_belong_to_real_employees():
    assert all(t["employee_id"] in EMPLOYEES for t in TICKETS)
