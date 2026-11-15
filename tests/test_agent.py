"""Tests for the agent loop, with a scripted model in place of Claude.

The real model costs money and gives different words each time, so it cannot
be used in tests that must pass every time. Here the "model" is a script: a
list of replies handed out in order. Everything else is real: the loop, the
MCP servers, the tools and the data. That lets us test what our code must
guarantee whatever the model says: the trace, the retry, the step limit and
the ticket confirmation guard.

How well the real model behaves is measured separately, in Phase 6.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from mcp import Client

from app.agent.loop import Conversation, run_turn
from app.config import settings
from app.main import create_app
from mcp_servers import hr_data


def _reply(blocks: list, stop_reason: str) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=100, output_tokens=20)
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


def say(text: str) -> SimpleNamespace:
    """A final answer."""
    return _reply([SimpleNamespace(type="text", text=text)], "end_turn")


def use(name: str, **arguments) -> SimpleNamespace:
    """A request to call one tool."""
    block = SimpleNamespace(type="tool_use", id=f"call_{name}", name=name, input=arguments)
    return _reply([block], "tool_use")


class ScriptedModel:
    """Stands in for the Anthropic client: `messages.create` returns the next scripted reply.

    A reply may be a function. It is then called with the request, so it can
    read what the tools returned, as the real model would.
    """

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.messages = self

    async def create(self, **request):
        # Keep a copy of the conversation as it was at this moment: the loop adds to it afterwards.
        request = {**request, "messages": list(request["messages"])}
        self.requests.append(request)
        reply = self.replies.pop(0)
        return reply(request) if callable(reply) else reply


@asynccontextmanager
async def running_app():
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


def last_tool_result(request: dict) -> dict:
    """What the most recent tool returned, as the model sees it."""
    return json.loads(request["messages"][-1]["content"][0]["content"])


def confirm_latest_ticket(request: dict) -> SimpleNamespace:
    """The scripted model confirming whatever ticket was just previewed."""
    token = last_tool_result(request)["confirmation_token"]
    return use("create_mock_hr_ticket", confirmation_token=token)


PROPOSE = use(
    "create_mock_hr_ticket", category="PTO Request", summary="Five days of PTO from March 15, 2027", priority="P3"
)


# ---- the loop ---------------------------------------------------------------


async def test_policy_question_uses_search_only_and_checks_the_citation():
    model = ScriptedModel(
        use("search_policy_documents", query="home office stipend amount"),
        say("The stipend is paid once (POL-007 section 6.1)."),
    )
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "How much is the home office stipend?", model)

    assert result.outcome == "answered"
    assert result.tools_used == ["search_policy_documents"]
    assert result.citations == ["POL-007 section 6.1"]
    assert result.unverified_citations == []
    assert [step["type"] for step in result.trace] == ["model", "tool", "model"]
    assert "POL-007 section 6.1" in result.trace[1]["citations"]


async def test_the_model_is_sent_the_discovered_tools_and_who_is_signed_in():
    model = ScriptedModel(say("Hello."))
    async with running_app() as app:
        await run_turn(app, Conversation("E1008"), "Hi", model)

    request = model.requests[0]
    assert len(request["tools"]) == 9
    assert all("ctx" not in tool["input_schema"].get("properties", {}) for tool in request["tools"])
    context = request["system"][1]["text"]
    assert "E1008" in context and hr_data.TODAY.isoformat() in context


async def test_multi_step_request_runs_tools_on_both_servers_in_order():
    model = ScriptedModel(
        use("lookup_employee_profile"),
        use(
            "check_policy_compliance",
            request_type="international_remote_work",
            start_date="2027-04-05",
            working_days=10,
            country="Portugal",
        ),
        use("search_policy_documents", query="international remote work annual limit"),
        say("You need extra approval (POL-005 section 5.3)."),
    )
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "Can I work from Portugal for two weeks?", model)

    tools = [step for step in result.trace if step["type"] == "tool"]
    assert [(step["server"], step["tool"]) for step in tools] == [
        ("hr", "lookup_employee_profile"),
        ("hr", "check_policy_compliance"),
        ("policy", "search_policy_documents"),
    ]
    assert tools[1]["summary"] == "outcome: allowed_with_extra_approval"
    assert result.input_tokens == 400 and result.output_tokens == 80


async def test_an_unsupported_citation_sends_the_model_back_to_read_the_section():
    model = ScriptedModel(
        say("You may work abroad for 20 days (POL-005 section 5.1)."),  # cited without reading anything
        use("get_policy_section", doc_id="POL-005", section="5.1"),
        say("You may work abroad for up to 20 working days a year (POL-005 section 5.1)."),
    )
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "How long can I work abroad?", model)

    assert [step["type"] for step in result.trace] == ["model", "guard", "model", "tool", "model"]
    assert result.trace[1]["unsupported"] == ["POL-005 section 5.1"]
    assert "Automatic check" in model.requests[1]["messages"][-1]["content"]
    assert result.citations == ["POL-005 section 5.1"] and result.unverified_citations == []
    assert result.answer.startswith("You may work abroad for up to")  # the corrected reply, not the first


async def test_a_citation_that_is_still_unsupported_after_the_check_is_flagged():
    wrong = say("You get 30 days of leave (POL-099 section 1.1).")
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "How much leave do I get?", ScriptedModel(wrong, wrong))

    assert len([step for step in result.trace if step["type"] == "guard"]) == 1  # the check runs once only
    assert result.citations == []
    assert result.unverified_citations == ["POL-099 section 1.1"]


# ---- failures ---------------------------------------------------------------


async def test_a_refusal_is_passed_to_the_model_and_not_retried():
    model = ScriptedModel(use("check_pto_balance", employee_id="E1000"), say("I can't show you that."))
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "What is the CEO's PTO balance?", model)

    step = result.trace[1]
    assert step["ok"] is False and step["attempts"] == 1
    assert "may not see" in step["summary"]
    # The model was told about the refusal as an error result.
    assert model.requests[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_a_breakdown_is_retried_once_and_then_succeeds(monkeypatch):
    real_call, failures = Client.call_tool, {"left": 1}

    async def flaky(self, name, arguments=None, **kwargs):
        if failures["left"]:
            failures["left"] -= 1
            raise TimeoutError("simulated timeout")
        return await real_call(self, name, arguments, **kwargs)

    monkeypatch.setattr(Client, "call_tool", flaky)
    model = ScriptedModel(use("check_pto_balance"), say("Here is your balance."))
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "What is my PTO balance?", model)

    assert result.trace[1]["ok"] is True and result.trace[1]["attempts"] == 2


async def test_a_tool_that_stays_down_gives_the_model_a_clear_message(monkeypatch):
    async def down(self, name, arguments=None, **kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(Client, "call_tool", down)
    model = ScriptedModel(use("check_pto_balance"), say("I could not check your balance just now."))
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "What is my PTO balance?", model)

    assert result.outcome == "answered"  # the turn still ends with an answer, not a crash
    assert result.trace[1]["ok"] is False and result.trace[1]["attempts"] == 2
    assert "unavailable" in model.requests[1]["messages"][-1]["content"][0]["content"]


async def test_the_step_limit_stops_a_model_that_never_answers():
    model = ScriptedModel(*[use("check_pto_balance")] * settings.agent_max_steps)
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "What is my PTO balance?", model)

    assert result.outcome == "step_limit"
    assert len([step for step in result.trace if step["type"] == "model"]) == settings.agent_max_steps


async def test_a_model_outage_gives_a_plain_message_and_leaves_the_conversation_clean():
    class BrokenModel(ScriptedModel):
        async def create(self, **request):
            raise ConnectionError("simulated outage")

    conversation = Conversation("E1008")
    async with running_app() as app:
        result = await run_turn(app, conversation, "Hi", BrokenModel())

    assert result.outcome == "error" and "went wrong" in result.answer
    assert conversation.messages == []


# ---- the ticket confirmation guard -------------------------------------------


async def test_a_ticket_cannot_be_previewed_and_confirmed_in_the_same_turn():
    before = len(hr_data.created_tickets)
    model = ScriptedModel(PROPOSE, confirm_latest_ticket, say("Shall I create this ticket?"))
    async with running_app() as app:
        result = await run_turn(app, Conversation("E1008"), "Open a PTO ticket for March 15", model)

    confirm = [step for step in result.trace if step["type"] == "tool"][1]
    assert confirm["blocked_by_guard"] is True and confirm["ok"] is False
    assert len(hr_data.created_tickets) == before  # nothing was created


async def test_a_ticket_is_created_after_the_employee_replies():
    before = len(hr_data.created_tickets)
    conversation = Conversation("E1008")
    async with running_app() as app:
        first = await run_turn(
            app, conversation, "Open a PTO ticket for March 15", ScriptedModel(PROPOSE, say("Shall I create it?"))
        )
        token = [step for step in first.trace if step["type"] == "tool"][0]["summary"]
        assert token == "status: confirmation_required"
        assert len(hr_data.created_tickets) == before

        # A new turn: the employee has now seen the preview and answered.
        token = json.loads(conversation.messages[2]["content"][0]["content"])["confirmation_token"]
        second = await run_turn(
            app,
            conversation,
            "Yes, go ahead",
            ScriptedModel(use("create_mock_hr_ticket", confirmation_token=token), say("Done.")),
        )

    created = [step for step in second.trace if step["type"] == "tool"][0]
    assert created["ok"] is True and created["summary"] == "status: created"
    assert len(hr_data.created_tickets) == before + 1
    assert hr_data.created_tickets[-1]["employee_id"] == "E1008"
