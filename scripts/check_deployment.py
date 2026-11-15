"""Check a running copy of the service from the outside, the way a visitor reaches it.

The tests start the app inside Python. This script does what they cannot: it
talks to a real server over the network. CI uses it to prove the app really
starts. You use it to check the deployed service and to time it.

Check a server on your own machine (start it first with uvicorn):
    .venv/bin/python -m scripts.check_deployment http://localhost:8000

Check the deployed service, and time five warm requests:
    .venv/bin/python -m scripts.check_deployment https://your-service.onrender.com

Also time real chat answers (this spends a little of the API key, about 1 cent for 10):
    .venv/bin/python -m scripts.check_deployment https://your-service.onrender.com --chat 10

A free Render service goes to sleep after 15 minutes without visitors. The
first request after that wakes it up, which is the "cold start". So the first
number this script prints is a cold start only if the service was asleep.
"""

import sys
import time

import httpx

WAIT_FOR_START = 120  # seconds to keep trying before giving up on the first reply
QUESTIONS = [
    "How much is the home office stipend?",
    "What is my PTO balance?",
    "How many days of PTO can I carry over into next year?",
    "Can I work from Portugal for two weeks from April 5?",
    "Who approves an expense over the usual limit?",
]


def timed_get(client: httpx.Client, path: str) -> tuple[httpx.Response, int]:
    started = time.perf_counter()
    response = client.get(path)
    return response, round((time.perf_counter() - started) * 1000)


def first_reply(client: httpx.Client) -> tuple[dict, int]:
    """Ask /health until the service answers. Returns the reply and how long the wait was."""
    started = time.perf_counter()
    while True:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return response.json(), round((time.perf_counter() - started) * 1000)
            problem = f"HTTP {response.status_code}"
        except httpx.HTTPError as error:
            problem = type(error).__name__
        if time.perf_counter() - started > WAIT_FOR_START:
            sys.exit(f"FAILED: no healthy reply after {WAIT_FOR_START} seconds ({problem}).")
        time.sleep(2)


def percentile(values: list[int], percent: int) -> int:
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * percent // 100) - 1)]  # nearest rank


def main() -> None:
    arguments = sys.argv[1:]
    if not arguments or arguments[0].startswith("-"):
        sys.exit("Give the address, for example:  .venv/bin/python -m scripts.check_deployment http://localhost:8000")
    chats = int(arguments[arguments.index("--chat") + 1]) if "--chat" in arguments else 0

    with httpx.Client(base_url=arguments[0].rstrip("/"), timeout=90) as client:
        # ---- 1. is it up, and how long did the first reply take? ---------------
        health, waited = first_reply(client)
        print(f"First reply from /health after {waited} ms (a cold start if the service was asleep).")

        # ---- 2. can the service reach both MCP servers and list their tools? ---
        failures = []
        if health["status"] != "ok":
            failures.append(f"status is {health['status']}")
        for server, expected_tool in (("policy", "search_policy_documents"), ("hr", "check_pto_balance")):
            found = health["mcp"].get(server, {})
            print(f"  MCP server {server}: {found.get('status')}, {len(found.get('tools', []))} tools")
            if expected_tool not in found.get("tools", []):
                failures.append(f"{server} server did not list {expected_tool}")
        print(f"  API key configured: {health['llm_key_configured']}, model: {health['llm_model']}")

        # ---- 3. the chat page loads -------------------------------------------
        page, _ = timed_get(client, "/")
        if page.status_code != 200 or "<html" not in page.text.lower():
            failures.append("the chat page did not load")
        if failures:
            sys.exit("FAILED: " + "; ".join(failures))

        # ---- 4. warm timings ---------------------------------------------------
        warm = [timed_get(client, "/health")[1] for _ in range(5)]
        print(f"Warm /health, 5 requests: p50 {percentile(warm, 50)} ms, p95 {percentile(warm, 95)} ms")

        if chats:
            timings = []
            for number in range(chats):
                question = QUESTIONS[number % len(QUESTIONS)]
                started = time.perf_counter()
                reply = client.post("/chat", json={"employee_id": "E1008", "message": question})
                took = round((time.perf_counter() - started) * 1000)
                outcome = reply.json().get("outcome") if reply.status_code == 200 else f"HTTP {reply.status_code}"
                print(f"  [{number + 1}/{chats}] {took} ms  {outcome}  {question}")
                if outcome == "answered":
                    timings.append(took)
            if timings:
                print(
                    f"Warm /chat, {len(timings)} answered: "
                    f"p50 {percentile(timings, 50)} ms, p95 {percentile(timings, 95)} ms"
                )

    print("OK")


if __name__ == "__main__":
    main()
