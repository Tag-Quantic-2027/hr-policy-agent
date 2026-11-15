"""See the MCP servers the way the agent sees them.

Discovery (what tools exist, and what the model is told about each):
    .venv/bin/python -m scripts.mcp_demo

A few real tool calls, signed in as one employee:
    .venv/bin/python -m scripts.mcp_demo E1008
"""

import asyncio
import json
import sys

from app.main import create_app
from app.mcp_client import SERVERS, connect


async def discover(app) -> None:
    for server in SERVERS:
        async with connect(app, server) as client:
            tools = (await client.list_tools()).tools
        print(f"\n=== MCP server: {server} ({len(tools)} tools) ===")
        for tool in tools:
            inputs = ", ".join(tool.input_schema.get("properties", {})) or "none"
            print(f"\n{tool.name}")
            print(f"  inputs: {inputs}")
            print(f"  description: {tool.description.strip().splitlines()[0]}")


async def call(client, name: str, arguments: dict) -> None:
    result = await client.call_tool(name, arguments)
    print(f"\n--> {name}({json.dumps(arguments)})")
    if result.is_error:
        print(f"<-- ERROR: {result.content[0].text}")
    else:
        print("<-- " + json.dumps(result.structured_content, indent=2)[:900])


async def demo(app, employee_id: str) -> None:
    print(f"Signed in as {employee_id}")
    async with connect(app, "hr", employee_id) as client:
        await call(client, "check_pto_balance", {})
        await call(client, "check_pto_balance", {"employee_id": "E1000"})  # someone else: should be refused
        await call(
            client,
            "check_policy_compliance",
            {"request_type": "international_remote_work", "start_date": "2027-04-05", "working_days": 10, "country": "Portugal"},
        )


async def main() -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        if len(sys.argv) > 1:
            await demo(app, sys.argv[1])
        else:
            await discover(app)


if __name__ == "__main__":
    asyncio.run(main())
