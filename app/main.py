"""The web application: the chat page, the chat endpoint, the two MCP servers and a health check.

Routes:
    GET  /               the chat page (one HTML file, app/static/index.html)
    GET  /api/employees  the people you can sign in as (a stand-in for a real login)
    POST /chat           one message in, one answer with its trace out
    POST /api/demo/reset remove the mock tickets one employee created, so a demo can be repeated
    GET  /health         is the service up, and can it reach its MCP servers
    /mcp/policy/, /mcp/hr/   the MCP servers themselves

Both MCP servers are mounted inside this one service. One service fits a free
hosting tier. Because the agent only ever talks to them through the MCP
protocol, either one can later be moved to its own service by setting a URL,
with no code change.
"""

import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.loop import Conversation, run_turn
from app.config import ROOT, settings
from app.mcp_client import SERVERS, connect
from mcp_servers import hr_data, hr_server, policy_server

MAX_CONVERSATIONS = 200  # kept in memory; the oldest is dropped when this is reached
MAX_SOURCES = 8


class ChatRequest(BaseModel):
    employee_id: str
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = ""  # empty starts a new conversation


class ResetRequest(BaseModel):
    employee_id: str


async def _sources(app: FastAPI, citations: list[str]) -> list[dict]:
    """The policy text behind each citation in an answer, fetched through the policy MCP server."""
    sources = []
    async with connect(app, "policy") as client:
        for citation in citations[:MAX_SOURCES]:
            doc_id, _, section = citation.partition(" section ")
            result = await client.call_tool("get_policy_section", {"doc_id": doc_id, "section": section})
            found = result.structured_content or {}
            if found.get("found"):
                part = found["parts"][0]
                sources.append(
                    {
                        "citation": citation,
                        "doc_title": part["doc_title"],
                        "section_title": part["section_title"],
                        "source_file": part["source_file"],
                        "snippet": part["text"][:400],
                    }
                )
    return sources


def create_app(llm=None) -> FastAPI:
    """Build the app. `llm` replaces the real model in tests."""
    # Each server becomes a small web app that speaks Streamable HTTP.
    # stateless_http: every request stands alone, so a restart loses nothing.
    # json_response: one plain JSON reply per request, which is all these tools need.
    mcp_apps = {
        name: module.server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
        for name, module in (("policy", policy_server), ("hr", hr_server))
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start both servers when the app starts, and stop them when it stops.
        async with AsyncExitStack() as stack:
            for module in (policy_server, hr_server):
                await stack.enter_async_context(module.server.session_manager.run())
            yield

    app = FastAPI(title="HR Policy Agent", lifespan=lifespan)
    app.state.mcp_apps = mcp_apps
    app.state.llm = llm
    app.state.conversations = {}  # conversation id -> Conversation
    app.state.served = {"day": date.today(), "count": 0}
    for name, mcp_app in mcp_apps.items():
        app.mount(f"/mcp/{name}", mcp_app)

    @app.get("/", include_in_schema=False)
    async def page() -> FileResponse:
        return FileResponse(ROOT / "app" / "static" / "index.html")

    @app.get("/api/employees")
    async def employees() -> list[dict]:
        # The sign-in picker. In a real system this would be the company login.
        # Only what the picker shows is returned: no records.
        return [
            {
                "employee_id": e["employee_id"],
                "full_name": e["full_name"],
                "job_title": e["job_title"],
                "employment_type": e["employment_type"],
            }
            for e in hr_data.EMPLOYEES.values()
        ]

    @app.post("/api/demo/reset")
    async def reset_demo(body: ResetRequest, request: Request) -> dict:
        # Tickets live in memory until the service restarts. Without this, a ticket
        # made in one demo run is still there in the next, and the agent (correctly)
        # declines to open a duplicate. Only assistant-made mock tickets are removed.
        # This is a route for the page, not an MCP tool: the model cannot call it.
        # It reaches the ticket store directly, so it needs the HR server in this service.
        if body.employee_id not in hr_data.EMPLOYEES:
            raise HTTPException(400, "Unknown employee id.")
        removed = hr_data.clear_created_tickets(body.employee_id)
        conversations = request.app.state.conversations
        for key in [k for k, c in conversations.items() if c.employee_id == body.employee_id]:
            del conversations[key]  # an old conversation would still remember the ticket
        return {"employee_id": body.employee_id, "tickets_removed": removed}

    @app.post("/chat")
    async def chat(body: ChatRequest, request: Request) -> dict:
        state = request.app.state
        if body.employee_id not in hr_data.EMPLOYEES:
            raise HTTPException(400, "Unknown employee id.")

        # A daily cap, because every request spends money on the API key.
        if state.served["day"] != date.today():
            state.served.update(day=date.today(), count=0)
        if state.served["count"] >= settings.daily_chat_limit:
            raise HTTPException(429, "The demo has reached its daily limit. Please try again tomorrow.")
        state.served["count"] += 1

        # Find the conversation, or start one. A conversation belongs to one employee.
        conversation = state.conversations.get(body.conversation_id)
        conversation_id = body.conversation_id
        if conversation is None or conversation.employee_id != body.employee_id:
            if len(state.conversations) >= MAX_CONVERSATIONS:
                del state.conversations[next(iter(state.conversations))]
            conversation_id = uuid.uuid4().hex
            conversation = state.conversations[conversation_id] = Conversation(body.employee_id)

        result = await run_turn(request.app, conversation, body.message.strip(), state.llm)

        # Is a ticket preview waiting for the employee's yes or no?
        tool_steps = [step for step in result.trace if step["type"] == "tool" and step["ok"]]
        awaiting = bool(tool_steps) and tool_steps[-1]["summary"] == "status: confirmation_required"
        try:
            sources = await _sources(request.app, result.citations)
        except Exception:  # the answer still stands if its snippets cannot be fetched
            sources = []
        return {
            "conversation_id": conversation_id,
            **result.to_dict(),
            "sources": sources,
            "awaiting_confirmation": awaiting,
        }

    @app.get("/health")
    async def health(request: Request) -> dict:
        # A real check: connect to each MCP server and ask it to list its tools.
        mcp, healthy = {}, True
        for name in SERVERS:
            try:
                async with connect(request.app, name) as client:
                    tools = (await client.list_tools()).tools
                mcp[name] = {"status": "ok", "tools": [tool.name for tool in tools]}
            except Exception as error:  # report any failure instead of crashing the health check
                mcp[name] = {"status": "error", "detail": type(error).__name__}
                healthy = False
        return {
            "status": "ok" if healthy else "degraded",
            # Reports whether a key is present, never the key itself.
            "llm_key_configured": settings.has_llm_key,
            "llm_model": settings.llm_model,
            "mcp": mcp,
        }

    return app


app = create_app()
