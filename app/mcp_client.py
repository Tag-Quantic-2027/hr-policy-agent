"""How this app talks to its MCP servers.

`connect` opens an MCP client to one server. Everything that needs a tool
goes through here: the health check now, the agent loop in the next phase.

Two ways to reach a server, chosen by settings:
- URL blank (the default): the server runs inside this same service. Requests
  are passed straight to it in memory, still as Streamable HTTP messages.
- URL set (MCP_POLICY_URL or MCP_HR_URL): the server runs somewhere else and
  is reached over the network. No other code changes.

The identity headers are added here, by our code. See mcp_servers/hr_server.py.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx2
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import settings

SERVERS = ("policy", "hr")
_LOCAL = "http://127.0.0.1:8000"  # only a label for in-memory requests: nothing listens here


@asynccontextmanager
async def connect(
    app: FastAPI, server: str, employee_id: str = "", session_id: str = ""
) -> AsyncIterator[Client]:
    headers = {}
    if server == "hr":
        headers = {
            "X-Internal-Token": settings.mcp_internal_token,
            "X-Employee-Id": employee_id,
            # Which conversation this is. Mock tickets are kept per conversation.
            "X-Session-Id": session_id,
        }

    url = settings.mcp_policy_url if server == "policy" else settings.mcp_hr_url
    if url:
        http = httpx2.AsyncClient(headers=headers, timeout=30)
    else:
        url = f"{_LOCAL}/"
        transport = httpx2.ASGITransport(app=app.state.mcp_apps[server])
        http = httpx2.AsyncClient(transport=transport, base_url=_LOCAL, headers=headers, timeout=30)

    async with http, Client(streamable_http_client(url, http_client=http)) as client:
        yield client
