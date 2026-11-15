# Deployed service

- **Application:** https://hr-policy-agent-dc9l.onrender.com
- **Health check:** https://hr-policy-agent-dc9l.onrender.com/health
- **Host:** Render, free plan, one web service. The web app, the agent and both MCP servers run in that one service.

The health check connects to both MCP servers and lists their tools, so `"status": "ok"` means the whole service is working, not only that the web server is up. It also reports whether an API key is set, never the key itself.

## How to use it

Open the application address, choose an employee in the sign-in picker (it stands in for a real login), and ask a question. All employees and records are synthetic.

The demo is public and spends a private API key, so it answers at most 300 chat requests a day (`DAILY_CHAT_LIMIT`). After that it replies with a "daily limit" message until the next day.

## Cold starts

Render's free plan puts a service to sleep after 15 minutes without visitors. The next visitor waits while it starts again.

| Situation | Measured |
|---|---|
| Cold start: first reply from `/health` after the service had been idle for 18 minutes | 42.5 s |
| First chat answer after a cold start (loads the embedding model) | 23.9 s |
| Warm `/health` | p50 about 240 ms, p95 about 350 ms |
| Warm chat answers, 10 questions | p50 10.3 s, p95 22.3 s |
| The same agent on a laptop, 29 evaluation cases | p50 5.1 s, p95 8.9 s |

Measured on 15 November 2026 with `scripts/check_deployment.py`. The cold start was measured once, so treat it as "about 40 to 60 seconds", not an exact figure.

**What to expect:** if the page takes up to a minute to load, the service was asleep. Wait for it, then the first question takes about 25 seconds and later ones about 10.

**Why warm answers are slower than on a laptop:** the free plan gives the service a tenth of one processor. Each policy search turns the question into an embedding for the vector half of hybrid search, and that takes about 5 seconds there against a few hundredths of a second on a laptop. Questions that need no policy search, such as a PTO balance, take about 3 seconds.

## Settings on Render

Set in `render.yaml`, except the key, which is pasted into the Render dashboard and is not in the repository.

| Variable | Value | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | set in the dashboard | the model |
| `LLM_MODEL` | `claude-haiku-5-5` | the model the agent reasons with |
| `RETRIEVAL_MODE` | `hybrid` | keyword plus vector search. Uses about 420 MB of the plan's 512 MB. Changing it to `keyword` uses about 160 MB and removes the 5 second search delay |
| `DAILY_CHAT_LIMIT` | `300` | caps daily spending |
| `PYTHON_VERSION` | `3.12.16` | matches local development and CI |

## How a deployment happens

1. A push to `main` starts the GitHub Actions workflow (`.github/workflows/ci.yml`).
2. Render waits for it (`autoDeployTrigger: checksPass` in `render.yaml`). If any check fails, nothing is deployed and the running version stays.
3. Render's build installs the packages and runs one search, which builds the vector index and downloads the embedding model, so no visitor waits for that.

To check the deployed service from a terminal:

```
.venv/bin/python -m scripts.check_deployment https://hr-policy-agent-dc9l.onrender.com
```
