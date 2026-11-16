# CLAUDE.md

Quantic MSAIE project: an agentic HR assistant (policy RAG + MCP tools + deployment + evals). The requirements and rubric are in `Project Brief.pdf` (git-ignored, Quantic copyright). Target: rubric score 5.

## How to work here

- This project is also a teaching tool. Explain the agent concept before the code, show the trace, and leave a small piece for the student to write or change in each phase. The student should be able to explain the agent loop, the MCP servers and the eval harness line by line.
- Explain steps plainly. Terminal commands one line at a time, each in its own code block.
- Python: Homebrew `python3.12`, virtual environment in `.venv`.
- Commit or push only when asked. GitHub account for this repo: **Tag-Quantic-2027** (not the professional account). The repo must be shared with `quantic-grader`.
- Keys are created and pasted by the student into `.env`. Never ask for a key in chat. All settings are read in `app/config.py` and nowhere else.
- Keep notes for `ai-tooling.md` as work happens: what the AI tools did well and badly.

## Decisions so far

- LLM: Claude through the Anthropic API on the student's key; model set by `LLM_MODEL`.
- Orchestration: hand-written agent loop, no framework.
- MCP: two servers (policy, HR data) over Streamable HTTP, run inside the one service by default, splittable through `MCP_POLICY_URL` and `MCP_HR_URL`.
- The MCP server code lives in `mcp_servers/`, not `mcp/`, because a local folder named `mcp` would shadow the installed `mcp` package.
- Embeddings: Chroma's built-in ONNX MiniLM model (no PyTorch) to fit Render's 512 MB free tier.
- Retrieval: one chunk per numbered policy section, keyword (BM25) plus vector search merged with reciprocal rank fusion; mode set by `RETRIEVAL_MODE`.
- MCP SDK is version 2 (`mcp==2.3.0`): the server class is `MCPServer` (not `FastMCP`) and the client is `mcp.Client`. Check the installed package before using older examples.
- Identity: the signed-in employee reaches the HR server in an `X-Employee-Id` header set by our code, with an `X-Internal-Token` secret. The model never supplies who is asking. Access rules are in `mcp_servers/hr_data.py`.
- Tickets are two-step: propose returns a token, confirm creates. Mock tickets live in memory only.
- `POST /api/demo/reset` (the "Clear my demo tickets" button) removes the mock tickets one employee created, so the ticket task can be repeated. It is a page route, not an MCP tool, so the model cannot call it.
- Rule arithmetic (dates, balances, limits) is code in `mcp_servers/compliance.py`, not left to the model.
- Agent: `run_turn()` in `app/agent/loop.py` runs one employee message. It discovers tools through `app/agent/toolbox.py` on every turn (no hard-coded tool list), keeps a trace, and returns a `TurnResult`. The system prompt is `app/agent/prompts.py`.
- The model picks the tools. Code enforces: the step limit (`AGENT_MAX_STEPS`), one retry for a tool breakdown and none for a refusal, and that a ticket cannot be previewed and confirmed in the same turn.
- Citations in an answer are checked against the citations tools returned. If one is unsupported, the loop sends the model back once to read the section or drop the citation (a `guard` step in the trace). Any still unsupported are reported as `unverified_citations`, not removed.
- Agent tests use a scripted model (`tests/test_agent.py`), never the real API. Live behaviour is checked with `scripts.chat` and measured in Phase 6.
- Web app: `POST /chat` takes `{employee_id, message, conversation_id}` and returns the answer, trace, checked citations, source snippets and `awaiting_confirmation`. The page is one file, `app/static/index.html`, plain JavaScript, no build step.
- Sign-in is a picker of the synthetic employees (`GET /api/employees`), standing in for a real login. Conversations are kept in memory by id and belong to one employee.
- `DAILY_CHAT_LIMIT` caps chat requests per day because the deployed demo is public and spends the student's API key.
- Evaluation: 29 gold cases in `evaluation/gold_cases.json` (policy, multi-document, tool, workflow, ambiguous, out-of-scope, safety). `evaluation/run_eval.py` runs them through the real agent, applies exact code checks and a judge model (`evaluation/judge.py`, structured output), and saves `evaluation/results/<name>.json`. `evaluation/report.py` compares runs.
- Ablations are run by environment variable, not code changes: `RETRIEVAL_MODE=keyword` and `DISABLED_TOOLS=check_policy_compliance`.
- A citation counts as supported only if a tool returned that section. A section merely mentioned inside another section's text does not count.
- The app is built by `create_app()` in `app/main.py`. Tests start it with its lifespan so the MCP servers run. Tests use keyword retrieval (`tests/conftest.py`).
- CI: `.github/workflows/ci.yml` runs on every push to main and every pull request, with no API key: import check, a real server start checked by `scripts/check_deployment.py`, MCP discovery (`scripts.mcp_demo`), then the tests.
- Deployment: `render.yaml` (Render Blueprint, free plan, one service). `autoDeployTrigger: checksPass` means Render deploys only after CI passes. The build command runs one hybrid search so the vector index and embedding model are built during the build.
- The embedding model is downloaded into `.model_cache/` in the project (git-ignored), not the home folder, so Render's build ships it to the running service.
- Memory measured locally: about 160 MB with keyword retrieval, about 420 MB with hybrid. Render's free tier has 512 MB. `RETRIEVAL_MODE=keyword` is the fallback if the deployed service runs out of memory.
- All data is synthetic. No real people or companies.

## Commands

- Run tests: `.venv/bin/pytest -q`
- Run the app: `.venv/bin/uvicorn app.main:app --reload`, then open http://localhost:8000
- Search the corpus: `.venv/bin/python -m app.rag.index "your question"`
- Measure retrieval: `.venv/bin/python -m evaluation.retrieval_check`
- Run the evaluation (uses the API key, about 40 cents): `.venv/bin/python -m evaluation.run_eval` (`--limit 3` to try it, `--only W01,S03` for chosen cases, `--name x` to save an experiment)
- Compare evaluation runs: `.venv/bin/python -m evaluation.report`
- Chat with the agent and see its trace: `.venv/bin/python -m scripts.chat E1008` (add a question in quotes to ask once and exit; this uses the API key)
- See the MCP tools as the agent does: `.venv/bin/python -m scripts.mcp_demo` (add an employee id such as `E1008` to make sample calls)
- Check a running or deployed service and time it: `.venv/bin/python -m scripts.check_deployment http://localhost:8000` (add `--chat 10` to time real answers; that uses the API key)
- Rebuild the PDFs: `.venv/bin/python scripts/build_policy_pdf.py`
