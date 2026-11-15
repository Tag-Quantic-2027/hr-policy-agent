"""Tests that go through the real MCP layer: discovery, then tool calls.

Each test starts the app, opens an MCP client the same way the agent will,
and talks to the servers over the protocol. Nothing here imports a tool
function directly, so a passing test proves the MCP layer works end to end.
"""

from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.main import create_app
from app.mcp_client import connect


@asynccontextmanager
async def session(server: str, employee_id: str = ""):
    """Start the app and open an MCP client to one of its servers."""
    app = create_app()
    async with app.router.lifespan_context(app), connect(app, server, employee_id) as client:
        yield client


# ---- discovery -------------------------------------------------------------


async def test_discovery_lists_eight_tools_with_descriptions_and_schemas():
    names = []
    for server in ("policy", "hr"):
        async with session(server, "E1007") as client:
            for tool in (await client.list_tools()).tools:
                names.append(tool.name)
                assert len(tool.description) > 40, tool.name
                assert tool.input_schema["type"] == "object"
                # The identity context is never part of what the model can fill in.
                assert "ctx" not in tool.input_schema.get("properties", {})
    assert sorted(names) == [
        "check_policy_compliance",
        "check_pto_balance",
        "create_mock_hr_ticket",
        "draft_hr_email",
        "get_policy_section",
	"list_my_tickets",
        "lookup_benefits_status",
        "lookup_employee_profile",
        "search_policy_documents",
    ]


# ---- policy server ---------------------------------------------------------


async def test_search_returns_sections_with_citations():
    async with session("policy") as client:
        result = await client.call_tool("search_policy_documents", {"query": "home office stipend amount"})
    assert not result.is_error
    hits = result.structured_content["results"]
    assert "POL-007 section 6.1" in [hit["citation"] for hit in hits]
    assert all(hit["text"] and hit["source_file"] and hit["effective_date"] for hit in hits)


async def test_get_policy_section_reads_a_section_and_handles_a_wrong_one():
    async with session("policy") as client:
        found = (await client.call_tool("get_policy_section", {"doc_id": "POL-005", "section": "5.1"})).structured_content
        missing = (await client.call_tool("get_policy_section", {"doc_id": "POL-005", "section": "99"})).structured_content
    assert found["found"] and "20 working days" in found["parts"][0]["text"]
    assert not missing["found"] and "5.1" in missing["sections_in_document"]


# ---- HR server: identity and access ----------------------------------------


async def test_employee_reads_their_own_pto_balance():
    async with session("hr", "E1008") as client:
        result = await client.call_tool("check_pto_balance", {})
    assert result.structured_content["international_working_days_used_ytd"] == 12


async def test_employee_cannot_read_a_colleagues_records():
    async with session("hr", "E1008") as client:
        result = await client.call_tool("check_pto_balance", {"employee_id": "E1007"})
    assert result.is_error
    assert "POL-020" in result.content[0].text


async def test_manager_sees_limited_fields_for_a_direct_report():
    async with session("hr", "E1004") as client:  # E1004 manages E1007
        profile = (await client.call_tool("lookup_employee_profile", {"employee_id": "E1007"})).structured_content
    assert profile["viewed_as"] == "manager"
    assert "data_access_level" not in profile and "email" not in profile


async def test_calls_without_a_signed_in_employee_are_refused():
    async with session("hr", "") as client:
        result = await client.call_tool("check_pto_balance", {})
    assert result.is_error and "signed in" in result.content[0].text


async def test_calls_without_the_internal_token_are_refused():
    # Someone who reaches the HR server directly cannot simply claim to be the CEO.
    app = create_app()
    headers = {"X-Employee-Id": "E1000", "X-Internal-Token": "a-guess"}
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app.state.mcp_apps["hr"]), base_url="http://127.0.0.1:8000", headers=headers
    )
    async with app.router.lifespan_context(app), http:
        async with Client(streamable_http_client("http://127.0.0.1:8000/", http_client=http)) as client:
            result = await client.call_tool("check_pto_balance", {})
    assert result.is_error and "only accepts calls from the HR assistant" in result.content[0].text


# ---- HR server: checks and actions -----------------------------------------


async def test_compliance_check_blocks_restricted_data_access_abroad():
    async with session("hr", "E1009") as client:  # Noor Haddad: Restricted access
        result = await client.call_tool(
            "check_policy_compliance",
            {"request_type": "international_remote_work", "start_date": "2027-04-05", "working_days": 5, "country": "Spain"},
        )
    report = result.structured_content
    assert report["outcome"] == "not_allowed"
    failed = [check for check in report["checks"] if check["result"] == "fail"]
    assert [check["citation"] for check in failed] == ["POL-005 section 6"]


async def test_a_bad_date_gives_a_helpful_error_not_a_crash():
    async with session("hr", "E1007") as client:
        result = await client.call_tool(
            "check_policy_compliance", {"request_type": "pto", "start_date": "next Friday", "working_days": 1}
        )
    assert result.is_error and "YYYY-MM-DD" in result.content[0].text


async def test_ticket_needs_two_steps_and_a_token_works_once():
    async with session("hr", "E1007") as client:
        proposal = (
            await client.call_tool(
                "create_mock_hr_ticket",
                {"category": "PTO Request", "summary": "Three days of PTO from March 1 to March 3, 2027."},
            )
        ).structured_content
        assert proposal["status"] == "confirmation_required"

        token = proposal["confirmation_token"]
        created = (await client.call_tool("create_mock_hr_ticket", {"confirmation_token": token})).structured_content
        assert created["status"] == "created" and created["ticket"]["employee_id"] == "E1007"

        again = await client.call_tool("create_mock_hr_ticket", {"confirmation_token": token})
        assert again.is_error


async def test_email_draft_is_addressed_to_the_manager_and_never_sent():
    async with session("hr", "E1007") as client:
        draft = (
            await client.call_tool(
                "draft_hr_email", {"recipient": "manager", "subject": "PTO in March", "body": "May I take March 1 to 3 off?"}
            )
        ).structured_content
    assert draft["status"] == "draft_only_not_sent"
    assert draft["to"] == "caleb.oyelaran@fernhill.example" and draft["body"].startswith("Hi Caleb,")
