"""Tests for the web endpoints: the chat page, the sign-in list and POST /chat.

The model is scripted, as in test_agent.py. Everything else is real, so these
tests go the whole way: HTTP request, agent loop, MCP servers, tools, response.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_agent import PROPOSE, ScriptedModel, say, use


def post(client: TestClient, message: str, employee_id: str = "E1008", conversation_id: str = ""):
    return client.post(
        "/chat", json={"employee_id": employee_id, "message": message, "conversation_id": conversation_id}
    )


def test_the_chat_page_is_served():
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Fernhill HR Assistant" in response.text


def test_the_sign_in_list_gives_names_but_no_records():
    with TestClient(create_app()) as client:
        people = client.get("/api/employees").json()
    assert len(people) == 23
    assert set(people[0]) == {"employee_id", "full_name", "job_title", "employment_type"}


def test_chat_returns_the_answer_its_trace_and_the_policy_text_behind_it():
    model = ScriptedModel(
        use("search_policy_documents", query="home office stipend amount"),
        say("The stipend is paid once (POL-007 section 6.1)."),
    )
    with TestClient(create_app(model)) as client:
        body = post(client, "How much is the home office stipend?").json()

    assert body["outcome"] == "answered"
    assert body["answer"].startswith("The stipend")
    assert [step["type"] for step in body["trace"]] == ["model", "tool", "model"]
    assert body["citations"] == ["POL-007 section 6.1"]
    source = body["sources"][0]
    assert source["citation"] == "POL-007 section 6.1" and source["source_file"].startswith("POL-007")
    assert "stipend" in source["snippet"].lower()
    assert body["awaiting_confirmation"] is False


def test_a_conversation_continues_and_a_ticket_waits_for_a_yes():
    model = ScriptedModel(PROPOSE, say("Shall I create it?"), say("No problem, nothing was created."))
    with TestClient(create_app(model)) as client:
        first = post(client, "Open a PTO ticket for March 15").json()
        assert first["awaiting_confirmation"] is True

        second = post(client, "No, cancel", conversation_id=first["conversation_id"]).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert second["awaiting_confirmation"] is False
    # The second request carried the whole first exchange: question, tool call, tool result, answer.
    assert len(model.requests[2]["messages"]) == 5


def test_a_conversation_cannot_be_continued_as_a_different_employee():
    model = ScriptedModel(say("Hello Liam."), say("Hello Dana."))
    with TestClient(create_app(model)) as client:
        first = post(client, "Hi", "E1008").json()
        second = post(client, "Hi", "E1007", first["conversation_id"]).json()

    assert second["conversation_id"] != first["conversation_id"]
    assert len(model.requests[1]["messages"]) == 1  # nothing carried over from Liam's chat


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"employee_id": "E9999", "message": "Hi"}, 400),  # nobody by that id
        ({"employee_id": "E1008", "message": ""}, 422),  # empty
        ({"employee_id": "E1008", "message": "x" * 2001}, 422),  # too long
    ],
)
def test_bad_requests_are_rejected_before_the_model_is_called(payload, status):
    model = ScriptedModel()
    with TestClient(create_app(model)) as client:
        assert client.post("/chat", json=payload).status_code == status
    assert model.requests == []


def test_the_daily_limit_stops_further_requests():
    model = ScriptedModel(say("Hello."))
    with TestClient(create_app(model)) as client:
        client.app.state.served["count"] = 10**6
        response = post(client, "Hi")
    assert response.status_code == 429
    assert model.requests == []


def test_clearing_demo_tickets_removes_only_that_employees_created_tickets():
    from mcp_servers import hr_data

    def make(employee_id):
        token = hr_data.propose_ticket(employee_id, "PTO Request", "3 days of PTO from March 15, 2027", "P3")
        return hr_data.confirm_ticket(employee_id, token["confirmation_token"])["ticket"]

    mine, theirs = make("E1008"), make("E1007")
    seed_before = len([t for t in hr_data.SEED_TICKETS if t["employee_id"] == "E1008"])
    hr_data.propose_ticket("E1008", "PTO Request", "a preview still waiting for a yes", "P3")
    try:
        with TestClient(create_app(ScriptedModel([]))) as client:
            body = client.post("/api/demo/reset", json={"employee_id": "E1008"}).json()
            assert body["tickets_removed"] >= 1
            assert client.post("/api/demo/reset", json={"employee_id": "nobody"}).status_code == 400
        assert mine not in hr_data.created_tickets
        assert theirs in hr_data.created_tickets
        assert hr_data.my_tickets("E1008")["ticket_count"] == seed_before  # seed tickets untouched
        assert not [p for p in hr_data._pending.values() if p["employee_id"] == "E1008"]
        # A new ticket never reuses an id that is still in use.
        assert make("E1008")["ticket_id"] != theirs["ticket_id"]
    finally:
        hr_data.clear_created_tickets("E1008")
        hr_data.clear_created_tickets("E1007")
