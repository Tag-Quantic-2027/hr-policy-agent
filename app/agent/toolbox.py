"""The agent's hands: discover the MCP tools, then call them.

The Toolbox is the only place where the agent touches MCP. It does three jobs:

1. Discovery. On opening, it connects to each MCP server, asks for its tools,
   and turns each one into the shape the Claude API expects. The agent has no
   tool list of its own: add a tool to a server and the model sees it.
2. Calling. `call` routes a tool name to the server that owns it.
3. Failure handling. A breakdown (timeout, dropped connection) is retried
   once. A refusal ("you may not see that record") is a real answer and is
   never retried.
"""

import json
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from app.config import settings
from app.mcp_client import SERVERS, connect

RETRIES = 1  # extra attempts after a breakdown


@dataclass
class ToolOutcome:
    """What happened when one tool was called."""

    server: str
    ok: bool  # False when the tool refused or broke down
    text: str  # what the model is shown
    data: dict[str, Any] | None  # the structured result, for the trace
    attempts: int
    duration_ms: int


class Toolbox:
    def __init__(self, app: FastAPI, employee_id: str, session_id: str = "") -> None:
        self._app = app
        self._employee_id = employee_id
        self._session_id = session_id
        self._stack = AsyncExitStack()
        self._clients: dict[str, Any] = {}
        self._owner: dict[str, str] = {}  # tool name -> server name
        self.definitions: list[dict] = []  # the tool list sent to the model
        self.server_instructions: list[str] = []

    async def __aenter__(self) -> "Toolbox":
        for server in SERVERS:
            # The employee id travels in a header on this connection. See app/mcp_client.py.
            client = await self._stack.enter_async_context(
                connect(self._app, server, self._employee_id, self._session_id)
            )
            self._clients[server] = client
            self.server_instructions.append(client.instructions or "")
            for tool in (await client.list_tools()).tools:
                if tool.name in settings.disabled_tools:
                    continue  # an evaluation experiment: see how the agent does without this tool
                self._owner[tool.name] = server
                self.definitions.append(
                    {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                )
        return self

    async def __aexit__(self, *error) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict) -> ToolOutcome:
        started = time.perf_counter()
        server = self._owner.get(name, "")

        def outcome(ok: bool, text: str, data: dict | None, attempts: int) -> ToolOutcome:
            return ToolOutcome(server, ok, text, data, attempts, round((time.perf_counter() - started) * 1000))

        if not server:
            return outcome(False, f"There is no tool named {name}.", None, 0)

        for attempt in range(1, RETRIES + 2):
            try:
                result = await self._clients[server].call_tool(name, arguments)
            except Exception as error:  # a breakdown: the call never got an answer
                failure = type(error).__name__
                continue
            text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
            if result.is_error:  # the tool answered, and the answer is no
                return outcome(False, text, None, attempt)
            data = result.structured_content
            return outcome(True, text or json.dumps(data), data, attempt)

        return outcome(
            False,
            f"The {name} tool is unavailable right now ({failure}). It was tried {RETRIES + 1} times. "
            "Answer with what you have and tell the employee which part could not be checked.",
            None,
            RETRIES + 1,
        )
