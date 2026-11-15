"""Put the saved evaluation runs side by side.

Each run of evaluation.run_eval saves a file in evaluation/results/. This
script reads them all and prints one table, with the baseline first, so an
experiment (an "ablation": the same test with one part changed or removed)
can be compared with it at a glance.

Run:  .venv/bin/python -m evaluation.report
It also writes the table to evaluation/results/REPORT.md.
"""

import json

from evaluation.run_eval import RESULTS

ROWS = [
    ("Passed every check", lambda s: s["passed_every_check"]),
    ("Groundedness", lambda s: s["answer_quality"]["groundedness"]),
    ("Correctness against gold", lambda s: s["answer_quality"]["correctness_vs_gold"]),
    ("Citation accuracy", lambda s: s["answer_quality"]["citation_accuracy"]),
    ("Expected citation found", lambda s: s["answer_quality"]["expected_citation_found"]),
    ("Partial match on gold facts", lambda s: s["answer_quality"]["partial_match"]),
    ("Tool selection accuracy", lambda s: s["agent_behaviour"]["tool_selection_accuracy"]),
    ("Workflow completion rate", lambda s: s["agent_behaviour"]["workflow_completion_rate"]),
    ("Clarification and escalation accuracy", lambda s: s["agent_behaviour"]["clarification_and_escalation_accuracy"]),
    ("Action safety pass rate", lambda s: s["agent_behaviour"]["action_safety_pass_rate"]),
    ("Latency p50 (ms)", lambda s: s["system"]["latency_p50_ms"]),
    ("Latency p95 (ms)", lambda s: s["system"]["latency_p95_ms"]),
    ("Model calls per turn", lambda s: s["system"]["mean_model_calls_per_turn"]),
    ("Input tokens per case", lambda s: s["system"]["mean_input_tokens_per_case"]),
]


def _cell(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}" if isinstance(value, float) and value <= 1 else str(value)


def main() -> None:
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RESULTS.glob("*.json"))]
    if not runs:
        raise SystemExit("No results yet. Run:  .venv/bin/python -m evaluation.run_eval")
    runs.sort(key=lambda run: run["name"] != "baseline")  # baseline first

    lines = ["# Evaluation results", ""]
    for run in runs:
        settings = run["settings"]
        hidden = ", ".join(settings["disabled_tools"]) or "none"
        lines.append(
            f"- **{run['name']}**: {run['summary']['cases']} cases, run {run['run_at']}. Model {settings['llm_model']}, "
            f"judge {settings['judge_model']}, retrieval {settings['retrieval_mode']}, tools hidden: {hidden}."
        )
    lines += ["", "| Metric | " + " | ".join(run["name"] for run in runs) + " |", "|---|" + "---:|" * len(runs)]
    for label, pick in ROWS:
        lines.append(f"| {label} | " + " | ".join(_cell(pick(run["summary"])) for run in runs) + " |")

    lines += ["", "## Cases that failed a check", ""]
    for run in runs:
        failed = [case for case in run["cases"] if not case["passed"]]
        lines.append(f"**{run['name']}**: " + ("none" if not failed else ""))
        for case in failed:
            missed = ", ".join(name for name, ok in case["checks"].items() if not ok)
            lines.append(f"- {case['id']} ({case['category']}): {missed}")
        lines.append("")

    text = "\n".join(lines)
    (RESULTS / "REPORT.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
