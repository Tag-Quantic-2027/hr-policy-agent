"""Talk to the agent in the terminal and watch its trace.

Start a chat signed in as one employee:
    .venv/bin/python -m scripts.chat E1008

Or ask one question and exit:
    .venv/bin/python -m scripts.chat E1008 "Can I work from Portugal for six weeks from April 5?"

Type your question and press Return. Type "quit" to stop.
Each model step and tool call is printed before the answer.
"""

import asyncio
import json
import logging
import sys

from app.agent.loop import Conversation, TurnResult, run_turn
from app.main import create_app


def show(result: TurnResult) -> None:
    for step in result.trace:
        if step["type"] == "model":
            wants = ", ".join(step["asked_for"]) or "nothing: it is ready to answer"
            print(f"\n[step {step['step']}] model ({step['duration_ms']} ms) asks for: {wants}")
            if step["said"] and step["asked_for"]:
                print(f"    says: {step['said'][:300]}")
        elif step["type"] == "tool":
            status = "BLOCKED BY GUARD" if step["blocked_by_guard"] else "ok" if step["ok"] else "FAILED"
            tries = f", {step['attempts']} attempts" if step["attempts"] > 1 else ""
            print(f"    tool  {step['server']}.{step['tool']}({json.dumps(step['input'])})")
            print(f"          {status} ({step['duration_ms']} ms{tries}): {step['summary']}")
        elif step["type"] == "guard":
            print(f"    GUARD citation check: {', '.join(step['unsupported'])} was cited but never returned by a tool.")
            print("          The model was asked to read it or remove it.")
        else:
            print(f"\n[error] {step['error']}: {step['detail']}")

    print(f"\n{result.answer}\n")
    print(
        f"-- outcome: {result.outcome} | {result.latency_ms} ms | "
        f"{result.input_tokens} tokens in, {result.output_tokens} out"
    )
    print(f"-- citations checked against tool results: {', '.join(result.citations) or 'none'}")
    if result.unverified_citations:
        print(f"-- WARNING, cited but never returned by a tool: {', '.join(result.unverified_citations)}")


async def main() -> None:
    logging.disable(logging.INFO)  # hide the MCP library's own log lines
    if len(sys.argv) < 2:
        sys.exit('Give an employee id, for example:  .venv/bin/python -m scripts.chat E1008')
    conversation = Conversation(employee_id=sys.argv[1])
    question = " ".join(sys.argv[2:])

    app = create_app()
    async with app.router.lifespan_context(app):
        if question:
            show(await run_turn(app, conversation, question))
            return
        print(f"Signed in as {conversation.employee_id}. Type a question, or quit.")
        while True:
            message = (await asyncio.to_thread(input, "\nyou> ")).strip()
            if message.lower() in ("quit", "exit", ""):
                break
            show(await run_turn(app, conversation, message))


if __name__ == "__main__":
    asyncio.run(main())
