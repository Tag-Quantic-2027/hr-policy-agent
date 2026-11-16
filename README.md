# HR Policy Agent

An agentic HR assistant for a made-up company, Fernhill Technologies. An employee signs in and asks a question. The agent decides what it needs, calls tools on two MCP servers (one searches 26 HR policies, one reads mock HR records and prepares mock actions), and replies with an answer that cites the policy sections it used. Every answer comes with a trace of the tool calls behind it.

Built for the Quantic MSAIE project "AI Engineering Techniques and Architectures". All people, records and policies are synthetic.

- **Deployed application:** https://hr-policy-agent-dc9l.onrender.com
- **Health check:** https://hr-policy-agent-dc9l.onrender.com/health

The deployed service sleeps after 15 minutes without visitors. If the page takes up to a minute to load, it is waking up. See [deployed.md](deployed.md).

## Documents

| File | Contents |
|---|---|
| [design-and-evaluation.md](design-and-evaluation.md) | Architecture, design choices, tool schemas, guardrails, the two demo tasks, evaluation results |
| [deployed.md](deployed.md) | Deployed addresses, cold and warm start timings, Render settings |
| [ai-tooling.md](ai-tooling.md) | Which AI coding tools were used, what worked and what did not |
| [evaluation/results/REPORT.md](evaluation/results/REPORT.md) | The evaluation table for every run |

## What it can do

| Ask | What happens |
|---|---|
| "How much is the home office stipend?" | One policy search, a cited answer |
| "Can I work from Portugal for six weeks starting April 5, 2027?" | Profile lookup, a rule check against the employee's records, the policy section read, a cited answer with alternatives |
| "I want 3 days of PTO from March 15, 2027. If I can, open a ticket." | Rule check, a ticket preview, and the ticket is created only after you say yes |
| The same ticket request a second time | The agent finds the existing ticket and does not open a duplicate. **Clear my demo tickets** (top right) removes it so the task can be run again |
| "What is the PTO balance of Dana Okafor?" | Refused: an employee may see only their own records |
| "What's a good recipe for banana bread?" | Declined as outside HR |

The two workflow rows are the demo tasks. Their expected tool calls are in [design-and-evaluation.md](design-and-evaluation.md#8-the-two-demo-tasks).

## Repository layout

| Path | Contents |
|---|---|
| `app/main.py` | The web app: chat page, `POST /chat`, `GET /health`, and both MCP servers mounted |
| `app/agent/` | The agent loop (`loop.py`), tool discovery and calling (`toolbox.py`), the system prompt (`prompts.py`) |
| `app/mcp_client.py` | How the app connects to an MCP server |
| `app/rag/` | Loading the policy files, chunking, and the search index |
| `app/config.py` | Every setting, read from environment variables in this one file |
| `mcp_servers/` | The two MCP servers and their tools, the access rules and the rule checks |
| `corpus/` | 26 policy documents in Markdown, HTML, plain text and PDF |
| `mock_data/` | Synthetic employees, PTO balances, benefits, offices and tickets |
| `evaluation/` | 29 gold cases, the evaluation runner, the judge, and saved results |
| `tests/` | 76 automated tests. None needs an API key |
| `scripts/` | Terminal chat, MCP demo, deployment check |
| `.github/workflows/ci.yml` | Continuous integration |
| `render.yaml` | The Render deployment |

The MCP code is in `mcp_servers/`, not `mcp/`, because a local folder named `mcp` would hide the installed `mcp` package from Python.

## Setup

You need Python 3.12 and an Anthropic API key.

Create the virtual environment:

```bash
python3.12 -m venv .venv
```

Install the dependencies:

```bash
.venv/bin/pip install -r requirements-dev.txt
```

Copy the example settings file:

```bash
cp .env.example .env
```

Open `.env` and paste your key after `ANTHROPIC_API_KEY=`. The file is git-ignored. Every other setting has a working default and is explained in `.env.example`.

## Run it locally

Start the app:

```bash
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000, choose an employee, and ask a question. The first policy search downloads a small embedding model (about 80 MB) into `.model_cache/` and builds the vector index in `.chroma/`. That happens once.

Other ways in:

| Purpose | Command |
|---|---|
| Run the tests (no key needed) | `.venv/bin/pytest -q` |
| Chat in the terminal and see the trace | `.venv/bin/python -m scripts.chat E1008` |
| See the MCP tools as the agent sees them | `.venv/bin/python -m scripts.mcp_demo` |
| Make sample MCP tool calls | `.venv/bin/python -m scripts.mcp_demo E1008` |
| Search the policies directly | `.venv/bin/python -m app.rag.index "your question"` |
| Check a running or deployed service | `.venv/bin/python -m scripts.check_deployment http://localhost:8000` |

### Use the API directly

`POST /chat` takes the employee, the message and, for a follow-up, the conversation id from the previous reply:

```bash
curl -s -X POST http://localhost:8000/chat -H 'content-type: application/json' -d '{"employee_id": "E1008", "message": "Can I work from Portugal for six weeks starting April 5, 2027?"}'
```

The reply contains `answer`, `citations`, `sources` (the policy snippets behind the citations), `trace` (each model step and tool call with its arguments and result summary), `tools_used`, `outcome`, `awaiting_confirmation` and `conversation_id`.

## Evaluation

The evaluation runs 29 gold cases through the real agent and scores them with exact code checks and a judge model. One full run takes about 8 minutes and costs about 35 US cents.

| Purpose | Command |
|---|---|
| Full run | `.venv/bin/python -m evaluation.run_eval` |
| Try three cases first | `.venv/bin/python -m evaluation.run_eval --limit 3` |
| Chosen cases | `.venv/bin/python -m evaluation.run_eval --only W01,S03` |
| Ablation: keyword search only | `RETRIEVAL_MODE=keyword .venv/bin/python -m evaluation.run_eval --name keyword_only` |
| Ablation: hide the compliance tool | `DISABLED_TOOLS=check_policy_compliance .venv/bin/python -m evaluation.run_eval --name no_compliance_tool` |
| Compare all saved runs | `.venv/bin/python -m evaluation.report` |
| Measure retrieval alone (free) | `.venv/bin/python -m evaluation.retrieval_check` |

Results are saved in `evaluation/results/`. The headline figures and how to read them are in [design-and-evaluation.md](design-and-evaluation.md#9-evaluation).

Reproducibility: chunking is deterministic (one chunk per numbered policy section), the mock data is fixed to one date (February 1, 2027), and dependency versions are pinned. The model's answers are not deterministic, so evaluation figures move by a case or two between runs.

## Deployment

The service runs on Render's free plan from [render.yaml](render.yaml).

1. In Render, choose New, then Blueprint, and select this repository.
2. Paste the Anthropic API key when Render asks for `ANTHROPIC_API_KEY`. It is stored in Render only.
3. Render builds and starts the service.

After that, deployment is automatic and gated:

1. A push to `main` runs the GitHub Actions workflow: install, import check, a real server start, MCP tool discovery, and the test suite.
2. Render deploys only when those checks pass (`autoDeployTrigger: checksPass`).

Settings, memory use and cold start timings are in [deployed.md](deployed.md).

## Secrets

The API key is read from the `ANTHROPIC_API_KEY` environment variable in `app/config.py` and nowhere else. It is in `.env` locally and in the Render dashboard when deployed. It is never committed, and `/health` reports only whether a key is set.
