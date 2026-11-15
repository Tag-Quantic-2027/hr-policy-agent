"""MCP server 2 of 2: HR records and mock HR actions.

The important idea in this file is identity. Every tool here acts for one
signed-in employee, and the server needs to know who that is.

The model is never asked. A model can be talked into saying "I am the CEO".
Instead, the agent's own code attaches two HTTP headers to every call:

    X-Employee-Id      who is signed in (chosen in the web page, not by the model)
    X-Internal-Token   a secret that proves the call comes from our agent

The tools read those headers through `ctx`, which the SDK passes in. The
model never sees `ctx` and cannot set it: it is not part of the tool schema.

A tool that fails raises ToolError. The SDK turns that into a normal tool
result marked is_error, with the message as its text. The agent shows that
message to the model, which can then explain the problem to the employee.
"""

import hmac
from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.config import settings
from mcp_servers import compliance, hr_data

server = MCPServer(
    "hr",
    instructions=(
        "Read the signed-in employee's HR records and prepare mock HR actions. "
        f"Today's date is {hr_data.TODAY.isoformat()}."
    ),
)


def _requester(ctx: Context) -> str:
    """Work out who is signed in, from the request headers. Never from the model."""
    headers = ctx.headers or {}
    if not hmac.compare_digest(headers.get("x-internal-token", ""), settings.mcp_internal_token):
        raise ToolError("This HR server only accepts calls from the HR assistant.")
    employee_id = headers.get("x-employee-id", "")
    if employee_id not in hr_data.EMPLOYEES:
        raise ToolError("No employee is signed in, so HR records cannot be read.")
    return employee_id


def _run(function, *args) -> dict[str, Any]:
    """Call a function from hr_data or compliance, turning its errors into tool errors."""
    try:
        return function(*args)
    except hr_data.HRError as error:
        raise ToolError(str(error)) from None


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{value!r} is not a date. Use the form YYYY-MM-DD, such as 2027-03-15.") from None


@server.tool()
def lookup_employee_profile(ctx: Context, employee_id: str = "") -> dict[str, Any]:
    """Get an employee's profile: role, department, employment type, manager, office,
    country, work arrangement, start date, data access level and probation status.

    Use this first whenever the answer depends on who is asking, for example
    whether they are a contractor, on probation, or where they are employed.
    Also returns today's date (as_of_date).

    Args:
        employee_id: Leave empty for the signed-in employee. A manager may give the
            id of a direct report and receives a limited set of fields.
    """
    requester = _requester(ctx)
    return _run(hr_data.profile, requester, employee_id or requester)


@server.tool()
def check_pto_balance(ctx: Context, employee_id: str = "") -> dict[str, Any]:
    """Get an employee's paid time off balance: annual entitlement, days accrued,
    carried over, used, pending and available, and the international remote
    working days used this year.

    Args:
        employee_id: Leave empty for the signed-in employee. A manager may give the
            id of a direct report.
    """
    requester = _requester(ctx)
    return _run(hr_data.pto_balance, requester, employee_id or requester)


@server.tool()
def lookup_benefits_status(ctx: Context) -> dict[str, Any]:
    """Get the signed-in employee's own benefits: health plan and coverage start,
    election status, retirement contribution, wellness allowance and learning
    budget remaining. Nobody else's benefits can be read, including by a manager.
    """
    requester = _requester(ctx)
    return _run(hr_data.benefits_status, requester, requester)


@server.tool()
def check_policy_compliance(
    ctx: Context,
    request_type: Literal["pto", "international_remote_work"],
    start_date: str,
    working_days: float,
    country: str = "",
) -> dict[str, Any]:
    """Check a planned request by the signed-in employee against the policy rules,
    using their real records. Returns an outcome (allowed, allowed_with_extra_approval
    or not_allowed), each rule checked with its policy citation, and who must approve.

    Use this instead of working out dates, balances or limits yourself.
    - "pto": eligibility, probation, balance, notice period, blackout periods.
    - "international_remote_work": eligibility, data access level, restricted
      countries, the 20 working day annual limit, notice period.

    Args:
        request_type: "pto" or "international_remote_work".
        start_date: First day off or first day abroad, as YYYY-MM-DD.
        working_days: Number of working days requested. Six weeks is 30 working days.
        country: The country to work from. Needed for international_remote_work only.
    """
    requester = _requester(ctx)
    first_day = _date(start_date)
    if first_day < hr_data.TODAY:
        raise ToolError(f"{start_date} is in the past. Today is {hr_data.TODAY.isoformat()}.")
    if not 0 < working_days <= 260:
        raise ToolError("working_days must be more than 0 and no more than 260.")
    if request_type == "pto":
        return _run(compliance.check_pto_request, requester, first_day, working_days)
    if not country.strip():
        raise ToolError("Give the country for an international remote work check.")
    return _run(compliance.check_international_remote_work, requester, country, first_day, working_days)


@server.tool()
def draft_hr_email(
    ctx: Context, recipient: Literal["manager", "people_operations"], subject: str, body: str
) -> dict[str, Any]:
    """Prepare an email draft from the signed-in employee to their manager or to
    People Operations. Fills in the names and addresses and adds a greeting and
    signature. This never sends anything: the employee sends the draft themselves.

    Args:
        recipient: "manager" or "people_operations".
        subject: The subject line.
        body: The message, without a greeting or signature.
    """
    requester = _requester(ctx)
    return _run(hr_data.draft_email, requester, recipient, subject, body)


@server.tool()
def create_mock_hr_ticket(
    ctx: Context,
    category: str = "",
    summary: str = "",
    priority: Literal["P1", "P2", "P3"] = "P3",
    confirmation_token: str = "",
) -> dict[str, Any]:
    """Create an HR ticket for the signed-in employee. This is a two-step action.

    Step 1: call with category, summary and priority. Nothing is created. You get
    a preview and a confirmation_token. Show the preview to the employee and ask
    whether to go ahead.
    Step 2: only after the employee clearly says yes, call again with just the
    confirmation_token. The ticket is then created exactly as previewed.

    Never do step 2 without the employee's agreement in the conversation.

    Args:
        category: One of: Accommodation Request, Benefits Question, Equipment Request,
            Expense Question, Learning, Leave Request, Onboarding, Payroll Question,
            Policy Question, PTO Request, Relocation, Wellness, Work Arrangement Change,
            Work From Anywhere, Workplace Concern.
        summary: What is being requested, with dates and amounts where relevant.
        priority: P3 for normal requests, P2 for urgent, P1 only where a policy says so.
        confirmation_token: The token from step 1. Give it only in step 2.
    """
    requester = _requester(ctx)
    if confirmation_token:
        return _run(hr_data.confirm_ticket, requester, confirmation_token)
    return _run(hr_data.propose_ticket, requester, category, summary, priority)

@server.tool()
def list_my_tickets(ctx: Context) -> dict[str, Any]:
    """List the signed-in employee's own HR tickets, with their status.

    Use this when the employee asks about a request they already made, or
    before proposing a new ticket, to check that one does not already exist
    for the same thing. Returns ticket_count and the list of tickets.
    It takes no arguments: it only ever shows the tickets of the person
    signed in, never anyone else's. It reads only and changes nothing.
    """
    requester = _requester(ctx)
    return _run(hr_data.my_tickets, requester)
