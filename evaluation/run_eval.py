"""The evaluation harness: run every gold case through the real agent and score it.

An agent cannot be judged by trying a few questions and liking the answers.
This script asks it a fixed set of questions with known right answers
(evaluation/gold_cases.json), checks each reply, and reports the share that
passed. Run it again after any change to see whether the change helped.

Each case is checked two ways:
- Code checks, which are exact: tools used, citations, required facts, tickets.
- A judge model, for what needs reading: groundedness, correctness, behaviour.

Run everything (about 8 minutes, roughly 40 US cents on the API key):
    .venv/bin/python -m evaluation.run_eval

Try three cases first:
    .venv/bin/python -m evaluation.run_eval --limit 3

Run chosen cases, or save under another name for an experiment:
    .venv/bin/python -m evaluation.run_eval --only W01,S03
    RETRIEVAL_MODE=keyword .venv/bin/python -m evaluation.run_eval --name keyword

Results are saved in evaluation/results/<name>.json.
"""

import argparse
import asyncio
import json
import logging
import math
from datetime import datetime
from pathlib import Path

import anthropic

from app.agent.loop import Conversation, run_turn
from app.config import settings
from app.main import create_app
from evaluation.judge import judge
from mcp_servers import hr_data

HERE = Path(__file__).parent
RESULTS = HERE / "results"

# US dollars per million tokens (input, output). Used only to estimate what a run cost.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}


# ---- checking one case -------------------------------------------------------


def _all_present(wanted: list, have, contains) -> bool:
    """Every entry in `wanted` is satisfied. An entry that is a list is satisfied by any one of its items."""
    return all(any(contains(option, have) for option in (item if isinstance(item, list) else [item])) for item in wanted)


def _evidence(conversation: Conversation) -> str:
    """Everything the tools returned in this conversation, as text for the judge."""
    names, parts = {}, []
    for message in conversation.messages:
        if message["role"] == "assistant" and not isinstance(message["content"], str):
            names.update({block.id: block.name for block in message["content"] if block.type == "tool_use"})
        elif message["role"] == "user" and isinstance(message["content"], list):
            for result in message["content"]:
                parts.append(f"[{names.get(result['tool_use_id'], 'tool')}]\n{result['content'][:6000]}")
    return "\n\n".join(parts)


async def run_case(app, case: dict, judge_client) -> dict:
    conversation = Conversation(case["employee_id"])
    tickets_before = len(hr_data.created_tickets)
    turns = [await run_turn(app, conversation, message) for message in case["turns"]]
    final = turns[-1]

    tools_used = list(dict.fromkeys(tool for turn in turns for tool in turn.tools_used))
    cited = list(dict.fromkeys(c for turn in turns for c in turn.citations + turn.unverified_citations))
    unverified = list(dict.fromkeys(c for turn in turns for c in turn.unverified_citations))
    tickets_created = len(hr_data.created_tickets) - tickets_before
    every_answer = "\n".join(turn.answer for turn in turns)

    in_text = lambda needle, text: needle.lower() in text.lower()  # noqa: E731
    in_list = lambda needle, items: needle in items  # noqa: E731
    expected_citations = case.get("expected_citations", [])
    checks = {
        # Agent behaviour
        "tools": _all_present(case.get("required_tools", []), tools_used, in_list)
        and not set(case.get("forbidden_tools", [])) & set(tools_used),
        "finished": final.outcome == "answered",
        # Answer quality
        "facts": _all_present(case.get("must_include", []), final.answer, in_text),
        "expected_citation": not expected_citations or any(c in final.citations for c in expected_citations),
        "citations_supported": not unverified,
        # Safety: no forbidden tool, no leaked data, and a ticket only where the case expects one.
        "safe": not set(case.get("forbidden_tools", [])) & set(tools_used)
        and not any(in_text(secret, every_answer) for secret in case.get("must_not_include", []))
        and tickets_created == (1 if case.get("ticket_created") else 0),
    }

    record = {
        "id": case["id"],
        "category": case["category"],
        "employee_id": case["employee_id"],
        "turns": case["turns"],
        "answers": [turn.answer for turn in turns],
        "outcome": final.outcome,
        "tools_used": tools_used,
        "tool_calls": [
            {"tool": s["tool"], "input": s["input"], "ok": s["ok"], "blocked_by_guard": s["blocked_by_guard"]}
            for turn in turns
            for s in turn.trace
            if s["type"] == "tool"
        ],
        "citations": cited,
        "unverified_citations": unverified,
        "tickets_created": tickets_created,
        "steps": [sum(1 for s in turn.trace if s["type"] == "model") for turn in turns],
        "latency_ms": [turn.latency_ms for turn in turns],
        "input_tokens": sum(turn.input_tokens for turn in turns),
        "output_tokens": sum(turn.output_tokens for turn in turns),
        "checks": checks,
    }

    if judge_client:
        verdict, judge_in, judge_out = await judge(
            judge_client, case, record["answers"], _evidence(conversation)
        )
        record["judge"] = verdict.model_dump()
        record["judge_tokens"] = [judge_in, judge_out]
        expected = case["expected_behaviour"]
        checks["behaviour"] = verdict.behaviour in (expected if isinstance(expected, list) else [expected])
        checks["grounded"] = verdict.groundedness == "grounded"
        checks["correct"] = verdict.correctness == "correct"

    record["passed"] = all(checks.values())
    return record


# ---- turning the results into metrics -------------------------------------------


def _rate(records: list[dict], check: str) -> float | None:
    values = [r["checks"][check] for r in records if check in r["checks"]]
    return round(sum(values) / len(values), 3) if values else None


def _percentile(values: list[float], percent: float) -> float:
    """Nearest-rank percentile: the value that `percent` of the values are at or below."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def summarise(records: list[dict], cases: dict[str, dict]) -> dict:
    cited = sum(len(r["citations"]) for r in records)
    unverified = sum(len(r["unverified_citations"]) for r in records)
    with_citation = [r for r in records if cases[r["id"]].get("expected_citations")]
    with_facts = [r for r in records if cases[r["id"]].get("must_include")]
    workflows = [r for r in records if r["category"] == "workflow"]
    # Cases where the right move is something other than a straight answer.
    not_plain = [r for r in records if cases[r["id"]]["expected_behaviour"] != "answered"]
    latencies = [ms for r in records for ms in r["latency_ms"]]

    agent_cost = sum(
        r["input_tokens"] * PRICES.get(settings.llm_model, (0, 0))[0]
        + r["output_tokens"] * PRICES.get(settings.llm_model, (0, 0))[1]
        for r in records
    )
    judge_cost = sum(
        r["judge_tokens"][0] * PRICES.get(settings.judge_model, (0, 0))[0]
        + r["judge_tokens"][1] * PRICES.get(settings.judge_model, (0, 0))[1]
        for r in records
        if "judge_tokens" in r
    )

    return {
        "cases": len(records),
        "passed_every_check": round(sum(r["passed"] for r in records) / len(records), 3),
        "answer_quality": {
            "groundedness": _rate(records, "grounded"),
            "correctness_vs_gold": _rate(records, "correct"),
            "citation_accuracy": round(1 - unverified / cited, 3) if cited else None,
            "expected_citation_found": _rate(with_citation, "expected_citation"),
            "partial_match": _rate(with_facts, "facts"),
        },
        "agent_behaviour": {
            "tool_selection_accuracy": _rate(records, "tools"),
            "workflow_completion_rate": round(sum(r["passed"] for r in workflows) / len(workflows), 3)
            if workflows
            else None,
            "clarification_and_escalation_accuracy": _rate(not_plain, "behaviour"),
            "action_safety_pass_rate": _rate(records, "safe"),
        },
        "system": {
            "turns_timed": len(latencies),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "mean_model_calls_per_turn": round(sum(s for r in records for s in r["steps"]) / len(latencies), 2),
            "mean_input_tokens_per_case": round(sum(r["input_tokens"] for r in records) / len(records)),
            "estimated_cost_usd": {"agent": round(agent_cost / 1e6, 4), "judge": round(judge_cost / 1e6, 4)},
        },
        "by_category": {
            category: f"{sum(r['passed'] for r in group)}/{len(group)}"
            for category in dict.fromkeys(r["category"] for r in records)
            for group in [[r for r in records if r["category"] == category]]
        },
    }


def show(summary: dict, records: list[dict]) -> None:
    def line(label: str, value) -> None:
        shown = "n/a" if value is None else f"{value:.0%}" if isinstance(value, float) and value <= 1 else value
        print(f"  {label:<40}{shown}")

    print(f"\n{summary['cases']} cases. Passed every check: {summary['passed_every_check']:.0%}")
    for group in ("answer_quality", "agent_behaviour"):
        print(f"\n{group.replace('_', ' ').capitalize()}")
        for name, value in summary[group].items():
            line(name.replace("_", " "), value)
    system = summary["system"]
    print("\nSystem")
    print(f"  latency p50 / p95                       {system['latency_p50_ms']} ms / {system['latency_p95_ms']} ms ({system['turns_timed']} turns)")
    print(f"  model calls per turn (mean)             {system['mean_model_calls_per_turn']}")
    print(f"  estimated cost of this run              agent ${system['estimated_cost_usd']['agent']}, judge ${system['estimated_cost_usd']['judge']}")
    print("\nBy category: " + ", ".join(f"{name} {score}" for name, score in summary["by_category"].items()))

    failed = [r for r in records if not r["passed"]]
    if failed:
        print("\nCases that failed a check:")
    for r in failed:
        missed = ", ".join(name for name, ok in r["checks"].items() if not ok)
        print(f"  {r['id']}  failed: {missed}")
        if "judge" in r:
            print(f"        judge: {r['judge']['reason'][:260]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the gold cases through the agent and score them.")
    parser.add_argument("--name", default="baseline", help="name for the results file")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--only", help="case ids separated by commas, such as W01,S03")
    parser.add_argument("--no-judge", action="store_true", help="skip the judge model (code checks only)")
    args = parser.parse_args()

    if not settings.has_llm_key:
        raise SystemExit("No API key is set. Add ANTHROPIC_API_KEY to .env first.")
    logging.disable(logging.INFO)

    cases = json.loads((HERE / "gold_cases.json").read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [case for case in cases if case["id"] in args.only.split(",")]
    cases = cases[: args.limit] if args.limit else cases
    judge_client = None if args.no_judge else anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    records = []
    app = create_app()
    async with app.router.lifespan_context(app):
        for number, case in enumerate(cases, start=1):
            record = await run_case(app, case, judge_client)
            records.append(record)
            mark = "pass" if record["passed"] else "FAIL"
            print(f"[{number:>2}/{len(cases)}] {case['id']}  {mark}  {sum(record['latency_ms'])} ms  {', '.join(record['tools_used']) or 'no tools'}")

    summary = summarise(records, {case["id"]: case for case in cases})
    show(summary, records)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.name}.json"
    settings_used = {
        "llm_model": settings.llm_model,
        "judge_model": None if args.no_judge else settings.judge_model,
        "retrieval_mode": settings.retrieval_mode,
        "disabled_tools": list(settings.disabled_tools),
        "agent_max_steps": settings.agent_max_steps,
    }
    out.write_text(
        json.dumps(
            {"name": args.name, "run_at": datetime.now().isoformat(timespec="seconds"), "settings": settings_used, "summary": summary, "cases": records},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved to {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    asyncio.run(main())
