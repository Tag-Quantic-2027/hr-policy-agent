"""The HR records, the access rules, and the mock ticket system.

This file is plain Python with no MCP in it. The MCP server in hr_server.py
is a thin layer on top: it works out who is asking, then calls a function
here. Keeping the rules in plain functions means they can be tested directly
and read without knowing anything about MCP.

Three ideas live here:

1. The fixed clock. TODAY is the as_of_date in the data (February 1, 2027),
   so answers do not change from one day to the next.
2. Access rules. Who may read whose record is decided here, in code, from
   POL-020 sections 4 and 9. It is never left to the language model.
3. Two-step tickets. A ticket is first proposed, then confirmed with a token.
   One call can never create a ticket.
"""

import json
import math
import secrets
from datetime import date, timedelta

from app.config import MOCK_DATA_DIR


def _load(name: str) -> tuple[dict, list[dict]]:
    data = json.loads((MOCK_DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return data["_meta"], data[name]


_meta, _employees = _load("employees")
EMPLOYEES = {e["employee_id"]: e for e in _employees}
PTO = {p["employee_id"]: p for p in _load("pto_balances")[1]}
BENEFITS = {b["employee_id"]: b for b in _load("benefits_elections")[1]}
OFFICES = {o["office_id"]: o for o in _load("offices")[1]}
SEED_TICKETS = _load("tickets")[1]

TODAY = date.fromisoformat(_meta["as_of_date"])
PROBATION_DAYS = 90  # POL-001 section 4


class HRError(Exception):
    """A problem the caller should be told about in plain words."""


class AccessDenied(HRError):
    pass


# ---- dates ---------------------------------------------------------------


def is_business_day(day: date) -> bool:
    """Monday to Friday. Company holidays are not subtracted (a known simplification)."""
    return day.weekday() < 5


def business_days_until(day: date) -> int:
    """Business days of notice: the weekdays from TODAY up to the day before `day`."""
    count, current = 0, TODAY
    while current < day:
        count += is_business_day(current)
        current += timedelta(days=1)
    return count


def working_dates(first_day: date, working_days: float) -> list[date]:
    """The dates a request covers: `working_days` weekdays starting at `first_day`."""
    dates, current = [], first_day
    while len(dates) < max(1, math.ceil(working_days)):  # a half day still uses one date
        if is_business_day(current):
            dates.append(current)
        current += timedelta(days=1)
    return dates


# ---- employees -------------------------------------------------------------


def get_employee(employee_id: str) -> dict:
    if employee_id not in EMPLOYEES:
        raise HRError(f"There is no employee with the id {employee_id}.")
    return EMPLOYEES[employee_id]


def is_staff(employee: dict) -> bool:
    """Full-time and part-time employees. Contractors and interns are not staff."""
    return employee["employment_type"] in ("full_time", "part_time")


def days_employed(employee: dict, on: date = TODAY) -> int:
    return (on - date.fromisoformat(employee["start_date"])).days


def on_probation(employee: dict, on: date = TODAY) -> bool:
    return is_staff(employee) and days_employed(employee, on) < PROBATION_DAYS


# ---- access rules ----------------------------------------------------------

# What a manager may see about a direct report (POL-020 section 4.2).
MANAGER_FIELDS = (
    "employee_id",
    "full_name",
    "job_title",
    "department",
    "employment_type",
    "work_arrangement",
    "office_id",
    "start_date",
)


def relationship(requester_id: str, target_id: str) -> str:
    """How the person asking relates to the person asked about."""
    if requester_id == target_id:
        return "self"
    if get_employee(target_id)["manager_id"] == requester_id:
        return "manager"
    return "none"


def check_access(requester_id: str, target_id: str, record: str) -> str:
    """Return the relationship if access is allowed, otherwise raise AccessDenied.

    record is "profile", "pto" or "benefits".
    - Your own records: always allowed (POL-020 section 4.1).
    - Your direct report: profile and PTO only, never benefits (section 4.2).
    - Anyone else: never (section 9).
    """
    get_employee(requester_id)
    who = relationship(requester_id, target_id)
    if who == "self" or (who == "manager" and record in ("profile", "pto")):
        return who
    if who == "manager":
        raise AccessDenied(
            "A manager may not see a direct report's benefits elections (POL-020 section 4.2)."
        )
    raise AccessDenied(
        f"{requester_id} may not see the {record} record of {target_id}. The assistant reads only "
        "the signed-in employee's own records, and limited fields for a manager's direct reports "
        "(POL-020 section 9)."
    )


# ---- reading records -------------------------------------------------------


def profile(requester_id: str, target_id: str) -> dict:
    who = check_access(requester_id, target_id, "profile")
    employee = get_employee(target_id)
    if who == "manager":
        return {"viewed_as": "manager", **{field: employee[field] for field in MANAGER_FIELDS}}

    manager = EMPLOYEES.get(employee["manager_id"] or "")
    office = OFFICES[employee["office_id"]]
    start = date.fromisoformat(employee["start_date"])
    return {
        "viewed_as": "self",
        **employee,
        "manager_name": manager["full_name"] if manager else None,
        "office_city": office["city"],
        "holiday_calendar": office["holiday_calendar"],
        "as_of_date": TODAY.isoformat(),
        "days_employed": days_employed(employee),
        "completed_years_of_service": (TODAY - start).days // 365,
        "on_probation": on_probation(employee),
        "probation_ends": (start + timedelta(days=PROBATION_DAYS)).isoformat() if is_staff(employee) else None,
    }


def pto_balance(requester_id: str, target_id: str) -> dict:
    who = check_access(requester_id, target_id, "pto")
    employee = get_employee(target_id)
    if target_id not in PTO:
        return {
            "employee_id": target_id,
            "has_pto": False,
            "reason": f"{employee['employment_type']} workers do not accrue PTO (POL-001 section 3).",
        }
    return {"viewed_as": who, "has_pto": True, "as_of_date": TODAY.isoformat(), **PTO[target_id]}


def benefits_status(requester_id: str, target_id: str) -> dict:
    check_access(requester_id, target_id, "benefits")
    employee = get_employee(target_id)
    if target_id not in BENEFITS:
        return {
            "employee_id": target_id,
            "has_benefits": False,
            "reason": f"{employee['employment_type']} workers are not eligible for company benefits "
            "(POL-009 section 2).",
        }
    return {"has_benefits": True, "as_of_date": TODAY.isoformat(), **BENEFITS[target_id]}


# ---- email drafts ----------------------------------------------------------


def draft_email(requester_id: str, recipient: str, subject: str, body: str) -> dict:
    """Wrap the text in a greeting and signature. Nothing is ever sent."""
    sender = get_employee(requester_id)
    if recipient == "manager":
        manager = EMPLOYEES.get(sender["manager_id"] or "")
        if manager is None:
            # POL-002 section 3.5: with no assigned manager, requests go to People Operations.
            recipient = "people_operations"
        else:
            to_name, to_email = manager["full_name"], manager["email"]
    if recipient == "people_operations":
        to_name, to_email = "People Operations", "people.operations@fernhill.example"
    elif recipient != "manager":
        raise HRError('recipient must be "manager" or "people_operations".')

    greeting = to_name.split()[0] if recipient == "manager" else to_name
    return {
        "status": "draft_only_not_sent",
        "from": sender["email"],
        "to": to_email,
        "to_name": to_name,
        "subject": subject.strip(),
        "body": f"Hi {greeting},\n\n{body.strip()}\n\nThanks,\n{sender['full_name']}",
        "note": "This is a draft. The assistant cannot send email. The employee sends it themselves.",
    }


# ---- mock tickets ----------------------------------------------------------

TICKET_CATEGORIES = (
    "Accommodation Request",
    "Benefits Question",
    "Equipment Request",
    "Expense Question",
    "Learning",
    "Leave Request",
    "Onboarding",
    "Payroll Question",
    "Policy Question",
    "PTO Request",
    "Relocation",
    "Wellness",
    "Work Arrangement Change",
    "Work From Anywhere",
    "Workplace Concern",
)
PRIORITIES = ("P1", "P2", "P3")

# Kept in memory only. Restarting the service clears them, and the seed file is never changed.
_pending: dict[str, dict] = {}
created_tickets: list[dict] = []
# ticket id -> the conversation that created it. A mock ticket is shown only in
# the conversation that made it, so a new conversation always starts with the
# seed tickets alone. Otherwise a ticket from one visitor's (or one rehearsal's)
# chat would still be there for the next, and the agent would decline to open it again.
_ticket_session: dict[str, str] = {}
MAX_CREATED_TICKETS = 500  # the oldest are dropped, so a public demo cannot fill memory


def my_tickets(requester_id: str, session_id: str = "") -> dict:
    """The signed-in employee's own tickets: the seed ones plus any created in this conversation."""
    get_employee(requester_id)
    created_here = [t for t in created_tickets if _ticket_session.get(t["ticket_id"], "") == session_id]
    tickets = [t for t in SEED_TICKETS + created_here if t["employee_id"] == requester_id]
    return {"employee_id": requester_id, "ticket_count": len(tickets), "tickets": tickets}


def propose_ticket(requester_id: str, category: str, summary: str, priority: str) -> dict:
    """Step 1: check the ticket and hand back a token. Nothing is created yet."""
    get_employee(requester_id)
    if category not in TICKET_CATEGORIES:
        raise HRError(f"Unknown category {category!r}. Use one of: {', '.join(TICKET_CATEGORIES)}.")
    if priority not in PRIORITIES:
        raise HRError(f"Unknown priority {priority!r}. Use one of: {', '.join(PRIORITIES)}.")
    if len(summary.strip()) < 10:
        raise HRError("The summary is too short. Say what is being requested, with dates if any.")

    token = secrets.token_hex(4)
    preview = {
        "employee_id": requester_id,
        "category": category,
        "priority": priority,
        "summary": summary.strip(),
    }
    _pending[token] = preview
    return {
        "status": "confirmation_required",
        "confirmation_token": token,
        "preview": preview,
        "message": "No ticket exists yet. Show this preview to the employee. Only if they say yes, "
        "call the tool again with this confirmation_token.",
    }


def _next_ticket_number() -> int:
    """One more than the highest number in use, so an id is never given out twice."""
    return max([6000] + [int(t["ticket_id"][2:]) for t in created_tickets]) + 1


def clear_created_tickets(requester_id: str) -> int:
    """Remove the tickets this employee created through the assistant, and any
    previews waiting for a yes. Seed tickets are never touched. Returns how many
    tickets were removed.

    This exists for the demo: a ticket made in one run would otherwise still be
    there in the next, and the agent would rightly refuse to open a duplicate.
    """
    get_employee(requester_id)
    kept = [t for t in created_tickets if t["employee_id"] != requester_id]
    removed = len(created_tickets) - len(kept)
    for ticket in created_tickets:
        if ticket["employee_id"] == requester_id:
            _ticket_session.pop(ticket["ticket_id"], None)
    created_tickets[:] = kept  # changed in place: other code holds a reference to this list
    for token in [k for k, preview in _pending.items() if preview["employee_id"] == requester_id]:
        del _pending[token]
    return removed


def confirm_ticket(requester_id: str, token: str, session_id: str = "") -> dict:
    """Step 2: create exactly the ticket that was proposed. A token works once."""
    preview = _pending.get(token)
    if preview is None or preview["employee_id"] != requester_id:
        raise HRError("That confirmation token is not valid. Propose the ticket again.")
    del _pending[token]

    ticket = {
        "ticket_id": f"T-{_next_ticket_number()}",
        **preview,
        "status": "open",
        "created_date": TODAY.isoformat(),
        "created_via_assistant": True,
    }
    created_tickets.append(ticket)
    _ticket_session[ticket["ticket_id"]] = session_id
    for old in created_tickets[:-MAX_CREATED_TICKETS]:
        _ticket_session.pop(old["ticket_id"], None)
    del created_tickets[:-MAX_CREATED_TICKETS]
    return {"status": "created", "ticket": ticket, "note": "Mock action: stored in memory only."}
