"""Rule checks for the two requests employees make most: PTO and working abroad.

Why this is code and not left to the language model: these rules involve
counting business days, comparing balances and checking lists. A model can
get arithmetic wrong and still sound confident. Code gets it right every
time and gives the same answer every time, which also makes it testable.

The model's job is to decide when to call this, and to explain the result.
Every check names the policy section it comes from, so the model can cite it.

Each check has one of three results:
    pass            the rule is met
    extra_approval  allowed only with an approval beyond the manager's
    fail            not allowed
The overall outcome is the worst result among the checks.
"""

from datetime import date, timedelta

from mcp_servers import hr_data
from mcp_servers.hr_data import TODAY

# POL-006 section 7. A test checks this list against the policy text, so the two cannot drift apart.
RESTRICTED_LOCATIONS = ("Belarus", "Cuba", "Iran", "North Korea", "Russia", "Syria", "Venezuela")

INTERNATIONAL_DAY_LIMIT = 20  # POL-005 section 5.1
INTERNATIONAL_EXCEPTION_LIMIT = 40  # POL-005 section 5.3
BLACKOUT_BUSINESS_DAYS = {"Finance": 10, "Sales": 5}  # POL-002 section 6

_RANK = {"pass": 0, "extra_approval": 1, "fail": 2}
_OUTCOME = {0: "allowed", 1: "allowed_with_extra_approval", 2: "not_allowed"}


def _check(rule: str, result: str, detail: str, citation: str) -> dict:
    return {"rule": rule, "result": result, "detail": detail, "citation": citation}


def _report(request_type: str, employee: dict, checks: list[dict], approvals: list[str], **extra) -> dict:
    worst = max(_RANK[c["result"]] for c in checks)
    return {
        "request_type": request_type,
        "employee_id": employee["employee_id"],
        "as_of_date": TODAY.isoformat(),
        "outcome": _OUTCOME[worst],
        "checks": checks,
        # Approvals only matter if the request is allowed at all.
        "approvals_required": [] if worst == 2 else list(dict.fromkeys(approvals)),
        "note": "Business days are counted as Monday to Friday. Company holidays are not subtracted.",
        **extra,
    }


def _blackout_dates(department: str, year: int) -> set[date]:
    """The last N business days of each fiscal quarter for this department."""
    blackout: set[date] = set()
    for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
        current, found = date(year, month, day), 0
        while found < BLACKOUT_BUSINESS_DAYS.get(department, 0):
            if hr_data.is_business_day(current):
                blackout.add(current)
                found += 1
            current -= timedelta(days=1)
    return blackout


def check_pto_request(employee_id: str, first_day: date, working_days: float) -> dict:
    employee = hr_data.get_employee(employee_id)
    balance = hr_data.PTO.get(employee_id)
    checks: list[dict] = []

    if balance is None:
        kind = employee["employment_type"]
        section = "3.4" if kind == "contractor" else "3.3"
        checks.append(
            _check("eligibility", "fail", f"{kind.capitalize()}s do not accrue PTO.", f"POL-001 section {section}")
        )
        return _report("pto", employee, checks, [])
    checks.append(_check("eligibility", "pass", "Full-time and part-time employees accrue PTO.", "POL-002 section 2"))

    dates = hr_data.working_dates(first_day, working_days)
    approvals = ["manager" if employee["manager_id"] else "People Operations (no assigned manager, POL-002 section 3.5)"]

    # Probation: no PTO in the first 60 calendar days, limited PTO from day 61 to day 90.
    employed = hr_data.days_employed(employee, first_day)
    in_probation = employed < hr_data.PROBATION_DAYS
    if employed < 60:
        checks.append(
            _check(
                "probation",
                "extra_approval",
                f"The first day off falls on day {employed + 1} of employment. PTO cannot be taken in the first "
                "60 calendar days unless the manager and People Operations both approve an exception in writing. "
                "Exceptions are normally only for commitments disclosed before accepting the offer.",
                "POL-002 section 5",
            )
        )
        approvals.append("People Operations (written exception)")
    elif in_probation:
        checks.append(
            _check(
                "probation",
                "pass",
                "Between day 61 and day 90, PTO may be taken with manager approval, up to the accrued balance.",
                "POL-002 section 5",
            )
        )
    else:
        checks.append(_check("probation", "pass", "The probationary period is complete.", "POL-002 section 5"))

    # Balance: up to the available balance, or up to 3 days negative after probation.
    available = balance["available_days"]
    after = round(available - working_days, 2)
    if after >= 0:
        checks.append(
            _check("balance", "pass", f"{available} days available, {after} left after this request.", "POL-002 section 4.2")
        )
    elif available < 0:
        checks.append(
            _check(
                "balance",
                "fail",
                f"The balance is already negative ({available} days). No further PTO can be approved "
                "while the balance is negative.",
                "POL-002 section 4.2",
            )
        )
    elif after >= -3 and not in_probation:
        checks.append(
            _check(
                "balance",
                "extra_approval",
                f"{available} days available. This request would take the balance to {after} days. A manager may "
                "approve a negative balance of up to 3 days, repaid by future accruals.",
                "POL-002 section 4.2",
            )
        )
    else:
        reason = "A negative balance is not permitted during probation." if in_probation else (
            "That is more than the 3 days negative a manager may approve."
        )
        checks.append(
            _check(
                "balance",
                "fail",
                f"{available} days available. This request would take the balance to {after} days. {reason}",
                "POL-002 section 5" if in_probation else "POL-002 section 4.2",
            )
        )

    # Notice: depends on the length of the absence.
    needed = 3 if working_days <= 2 else 10 if working_days <= 5 else 20
    given = hr_data.business_days_until(first_day)
    if working_days > 5:
        approvals.append("department director (more than 5 consecutive working days)")
    if given >= needed:
        checks.append(
            _check("notice", "pass", f"{given} business days of notice given, {needed} needed.", "POL-002 section 3.2")
        )
    else:
        checks.append(
            _check(
                "notice",
                "extra_approval",
                f"{given} business days of notice given, {needed} needed. This is a short-notice request. "
                "The manager may approve it as an exception if team coverage allows. State the reason.",
                "POL-002 section 3.3",
            )
        )

    # Blackout periods for Finance and Sales.
    department = employee["department"]
    blackout = set().union(*(_blackout_dates(department, year) for year in {d.year for d in dates}))
    clash = sorted(d for d in dates if d in blackout)
    if clash:
        checks.append(
            _check(
                "blackout",
                "extra_approval",
                f"{len(clash)} of the requested days fall in the {department} blackout period "
                f"({clash[0].isoformat()} to {clash[-1].isoformat()}). The department director must also approve.",
                "POL-002 section 6",
            )
        )
        approvals.append("department director (blackout period)")
    else:
        checks.append(_check("blackout", "pass", "No requested day falls in a blackout period.", "POL-002 section 6"))

    return _report(
        "pto", employee, checks, approvals, first_day=dates[0].isoformat(), last_day=dates[-1].isoformat()
    )


def check_international_remote_work(employee_id: str, country: str, first_day: date, working_days: float) -> dict:
    employee = hr_data.get_employee(employee_id)
    balance = hr_data.PTO.get(employee_id, {})
    country = country.strip()
    checks: list[dict] = []
    approvals = ["manager", 'People Operations (ticket in the category "Work From Anywhere")']

    # Eligibility for the Work From Anywhere program: four conditions.
    problems = []
    if not hr_data.is_staff(employee):
        problems.append(f"{employee['employment_type']}s are not eligible")
    if hr_data.on_probation(employee, first_day):
        problems.append("the probationary period will not be complete on the first day")
    if employee["work_arrangement"] == "office_based":
        problems.append("office-based employees are not eligible")
    if employee["on_performance_plan"]:
        problems.append("employees on a performance improvement plan are not eligible")
    checks.append(
        _check(
            "eligibility",
            "fail" if problems else "pass",
            ("Not eligible: " + "; ".join(problems) + ".") if problems else "Meets the Work From Anywhere conditions.",
            "POL-005 section 3",
        )
    )

    # Data access level.
    level = employee["data_access_level"]
    if level == "Restricted":
        checks.append(
            _check(
                "data_access",
                "fail",
                "Employees with Restricted data access may not work internationally. The only alternative is "
                "for the department director to arrange temporary removal of Restricted access.",
                "POL-005 section 6",
            )
        )
    else:
        extra = " The VPN and device rules in POL-006 section 6 apply." if level == "Confidential" else ""
        checks.append(
            _check("data_access", "pass", f"{level} access permits international remote work.{extra}", "POL-005 section 6")
        )

    # The country itself.
    if country.lower() in (name.lower() for name in RESTRICTED_LOCATIONS):
        checks.append(
            _check(
                "location",
                "fail",
                f"{country} is on the Restricted Locations List. No exception is available.",
                "POL-005 section 5.4 and POL-006 section 7",
            )
        )
    elif country.lower() == employee["country_of_employment"].lower():
        checks.append(
            _check(
                "location",
                "pass",
                f"{country} is the employee's country of employment, so this is domestic remote work, "
                "not international. See POL-005 section 4.",
                "POL-005 section 5.1",
            )
        )
    else:
        checks.append(
            _check("location", "pass", f"{country} is not on the Restricted Locations List.", "POL-006 section 7")
        )

    # The annual limit of working days.
    used = balance.get("international_working_days_used_ytd", 0)
    total = used + working_days
    exception = total > INTERNATIONAL_DAY_LIMIT
    if not exception:
        checks.append(
            _check(
                "annual_limit",
                "pass",
                f"{used} days used this year plus {working_days:g} requested is {total:g} of {INTERNATIONAL_DAY_LIMIT}.",
                "POL-005 section 5.1",
            )
        )
    elif total <= INTERNATIONAL_EXCEPTION_LIMIT:
        over = total - INTERNATIONAL_DAY_LIMIT
        checks.append(
            _check(
                "annual_limit",
                "extra_approval",
                f"{used} days used this year plus {working_days:g} requested is {total:g}, which is {over:g} over the "
                f"limit of {INTERNATIONAL_DAY_LIMIT}. This is an exception request. Exceptions are rare. The usual "
                f"alternatives are to work the first {INTERNATIONAL_DAY_LIMIT - used:g} days and take PTO or unpaid "
                "leave for the rest, or to shorten the stay.",
                "POL-005 section 5.3",
            )
        )
        approvals += ["department director", "Chief People Officer (after a tax and legal review)"]
    else:
        checks.append(
            _check(
                "annual_limit",
                "fail",
                f"{used} days used this year plus {working_days:g} requested is {total:g}. Exceptions are never "
                f"approved for more than {INTERNATIONAL_EXCEPTION_LIMIT} working days in a calendar year, so this "
                f"request cannot be approved, even as an exception. The most that can still be requested this year "
                f"is {max(0, INTERNATIONAL_DAY_LIMIT - used):g} working days within the standard limit, or "
                f"{max(0, INTERNATIONAL_EXCEPTION_LIMIT - used):g} as an exception request.",
                "POL-005 section 5.3",
            )
        )

    # Notice before departure.
    needed = 30 if exception else 15
    given = hr_data.business_days_until(first_day)
    checks.append(
        _check(
            "notice",
            "pass" if given >= needed else "fail",
            f"{given} business days before departure, {needed} needed for the ticket.",
            "POL-005 section 5.3" if exception else "POL-005 section 5.2",
        )
    )

    return _report(
        "international_remote_work",
        employee,
        checks,
        approvals,
        country=country,
        international_days_used_this_year=used,
    )
