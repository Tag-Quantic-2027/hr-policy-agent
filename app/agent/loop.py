"""The agent loop.

An agent is a model that chooses its own next step, run in a loop by ordinary
code. One turn of this agent goes:

    1. Send the model the conversation so far and the list of tools.
    2. The model replies with either a final answer, or a request to call
       one or more tools.
    3. If it asked for tools, our code runs them, adds the results to the
       conversation, and goes back to step 1.
    4. If it gave an answer, or the step limit is reached, stop.

The model never runs anything. It only writes "please call this tool with
these inputs". Our code decides whether to do it. That is where the two
guards in this file sit: the step limit and the ticket confirmation.

Every model call and tool call is recorded in a trace, so a person can see
how an answer was reached.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import anthropic
from fastapi import FastAPI

from app.agent.prompts import system_prompt
from app.agent.toolbox import Toolbox, ToolOutcome
from app.config import settings

MAX_TOKENS = 8000  # the most the model may write in one reply, including its private reasoning
NOT_CONFIRMED = (
    "Not done. The employee has not seen this preview yet. Show it to them, ask whether to go ahead, "
    "and confirm only after they say yes in a new message."
)
CITATION_CHECK = (
    "[Automatic check, not from the employee] Your reply cited {missing}, but no tool has returned "
    "that text in this conversation. Read each one with get_policy_section and then give your reply "
    "again in full, or give it again without those citations and without the claims that depended on them."
)
CITATION = re.compile(r"(POL-\d{3})[ ,]+(?:sections?|§)\s*(\d+(?:\.\d+)*)")


@dataclass
class Conversation:
    """One employee's chat. Kept in memory by whoever calls run_turn."""

    employee_id: str
    messages: list[dict] = field(default_factory=list)  # everything the model is shown, in order
    evidence: set[str] = field(default_factory=set)  # every citation a tool has returned so far
    session_id: str = ""  # names this conversation to the HR server, which keeps mock tickets per conversation


@dataclass
class TurnResult:
    answer: str
    outcome: str  # "answered", "step_limit", "cut_short", "refused" or "error"
    trace: list[dict]
    citations: list[str]  # cited in the answer and returned by a tool
    unverified_citations: list[str]  # cited in the answer but never returned by a tool
    tools_used: list[str]
    latency_ms: int
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


def _citations(text: str) -> list[str]:
    """Every citation in a piece of text, as "POL-005 section 5.1", in order, without repeats."""
    found = [f"{doc} section {section}" for doc, section in CITATION.findall(text)]
    return list(dict.fromkeys(found))


def _evidence(value: Any) -> list[str]:
    """Collect the citations a tool returned: every field named "citation", at any depth."""
    if isinstance(value, dict):
        own = _citations(str(value.get("citation", "")))
        return own + [c for item in value.values() for c in _evidence(item)]
    if isinstance(value, list):
        return [c for item in value for c in _evidence(item)]
    return []


def _is_supported(citation: str, evidence: set[str]) -> bool:
    """True if a tool returned this section, or a subsection of it (5 is supported by 5.1)."""
    return citation in evidence or any(seen.startswith(citation + ".") for seen in evidence)


def _summary(ok: bool, text: str, data: dict | None) -> str:
    """One line for the trace."""
    if not ok or data is None:
        return text[:200]
    if "results" in data:
        return f"{data['result_count']} sections: " + ", ".join(r["citation"] for r in data["results"])
    for key in ("outcome", "status"):
        if key in data:
            return f"{key}: {data[key]}"
    return "returned: " + ", ".join(list(data)[:8])


async def run_turn(app: FastAPI, conversation: Conversation, user_message: str, llm=None) -> TurnResult:
    """Answer one message from the employee. `llm` is replaced by a fake in tests."""
    started = time.perf_counter()
    trace: list[dict] = []
    tokens = {"input": 0, "output": 0}

    def finish(answer: str, outcome: str) -> TurnResult:
        cited = _citations(answer)
        return TurnResult(
            answer=answer,
            outcome=outcome,
            trace=trace,
            citations=[c for c in cited if _is_supported(c, conversation.evidence)],
            unverified_citations=[c for c in cited if not _is_supported(c, conversation.evidence)],
            tools_used=list(dict.fromkeys(s["tool"] for s in trace if s["type"] == "tool")),
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=tokens["input"],
            output_tokens=tokens["output"],
        )

    if llm is None:
        if not settings.has_llm_key:
            return finish("The assistant is not set up yet: no API key is configured.", "error")
        llm = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    checkpoint = len(conversation.messages)  # where to rewind to if this turn breaks
    conversation.messages.append({"role": "user", "content": user_message})
    # Tickets previewed during this turn. The employee has not seen them yet, so they cannot be confirmed yet.
    previewed_this_turn: set[str] = set()
    citation_check_used = False

    try:
        async with Toolbox(app, conversation.employee_id, conversation.session_id) as toolbox:
            system = system_prompt(conversation.employee_id, toolbox.server_instructions)

            for step in range(1, settings.agent_max_steps + 1):
                # ---- 1. ask the model what to do next -------------------------------
                asked = time.perf_counter()
                response = await llm.messages.create(
                    model=settings.llm_model,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    tools=toolbox.definitions,
                    messages=conversation.messages,
                )
                # The whole reply goes back into the conversation, not only its text,
                # so the model's tool requests stay matched to the results that follow.
                conversation.messages.append({"role": "assistant", "content": response.content})

                text = "\n".join(block.text for block in response.content if block.type == "text").strip()
                requests = [block for block in response.content if block.type == "tool_use"]
                # Input read from or written to the prompt cache is reported separately, so add it in.
                usage = response.usage
                tokens["input"] += usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                tokens["input"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
                tokens["output"] += response.usage.output_tokens
                trace.append(
                    {
                        "type": "model",
                        "step": step,
                        "said": text,
                        "asked_for": [block.name for block in requests],
                        "stop_reason": response.stop_reason,
                        "duration_ms": round((time.perf_counter() - asked) * 1000),
                    }
                )

                # ---- 2. no tool requests: this is the final answer ------------------
                if response.stop_reason != "tool_use":
                    if response.stop_reason == "refusal":
                        return finish(text or "I can't help with that request.", "refused")
                    if response.stop_reason == "max_tokens":
                        return finish(text + "\n\n(This answer was cut short because it was too long.)", "cut_short")

                    # Guard: a citation must point at text a tool returned. If one does not, the
                    # model gets one chance to read the section or drop the citation.
                    missing = [c for c in _citations(text) if not _is_supported(c, conversation.evidence)]
                    if missing and not citation_check_used and step < settings.agent_max_steps:
                        citation_check_used = True
                        trace.append({"type": "guard", "step": step, "guard": "citation_check", "unsupported": missing})
                        conversation.messages.append(
                            {"role": "user", "content": CITATION_CHECK.format(missing=", ".join(missing))}
                        )
                        continue
                    return finish(text, "answered")

                # ---- 3. run each tool the model asked for ---------------------------
                results = []
                for block in requests:
                    token = block.input.get("confirmation_token")
                    blocked = bool(token) and token in previewed_this_turn
                    if blocked:
                        # Guard: a preview and its confirmation can never happen in the same turn.
                        outcome = ToolOutcome("agent", False, NOT_CONFIRMED, None, 0, 0)
                    else:
                        outcome = await toolbox.call(block.name, block.input)
                    ok, shown, data = outcome.ok, outcome.text, outcome.data

                    if data and data.get("status") == "confirmation_required":
                        previewed_this_turn.add(data["confirmation_token"])
                    returned = _evidence(data) if ok else _citations(shown)
                    conversation.evidence.update(returned)

                    trace.append(
                        {
                            "type": "tool",
                            "step": step,
                            "server": outcome.server,
                            "tool": block.name,
                            "input": block.input,
                            "ok": ok,
                            "blocked_by_guard": blocked,
                            "attempts": outcome.attempts,
                            "duration_ms": outcome.duration_ms,
                            "summary": _summary(ok, shown, data),
                            "citations": returned,
                        }
                    )
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": shown, "is_error": not ok}
                    )

                # ---- 4. give the results to the model and go round again ------------
                conversation.messages.append({"role": "user", "content": results})

            # The loop ended without an answer: the step limit stopped it.
            answer = (
                "I could not finish working this out within my step limit, so I do not have a reliable "
                "answer. Please ask again with a narrower question, or contact People Operations."
            )
            conversation.messages.append({"role": "assistant", "content": answer})
            return finish(answer, "step_limit")

    except Exception as error:  # the model service or an MCP server could not be reached at all
        del conversation.messages[checkpoint:]  # forget the broken turn so the next one starts clean
        trace.append({"type": "error", "error": type(error).__name__, "detail": str(error)[:300]})
        return finish(
            "Something went wrong on my side and I could not answer. Please try again in a moment.",
            "error",
        )
