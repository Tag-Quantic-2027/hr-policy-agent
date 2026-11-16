# Demo video script

A plan for the 7 to 10 minute recorded demo. The target is about 9 minutes. The "Say" lines are suggestions: put them in your own words.

## What the brief requires

- 7 to 10 minutes, screen capture with voiceover.
- You on camera, showing your government ID.
- The **deployed** application carrying out two agentic tasks end to end.
- For each task, explain the tool names, the arguments, the outputs, the retrieved citations and the final answer or action.
- A quick walkthrough of design, deployment, CI/CD and evaluation results.

## Before you record

1. Wake the service about 5 minutes before: open https://hr-policy-agent-dc9l.onrender.com and wait for the page. This can take a minute.
2. Ask one policy question, such as "How much is the home office stipend?", and wait for the answer. The first answer after waking is slow because the search model is loading.
3. Reload the page so the chat is empty. Keep **E1008 Liam Tremblay** selected.
4. Open these in browser tabs, in this order:
   - The deployed app
   - `design-and-evaluation.md` on GitHub, scrolled to the architecture diagram
   - https://hr-policy-agent-dc9l.onrender.com/health
   - The GitHub Actions page of the repository
   - `render.yaml` on GitHub
   - `evaluation/results/REPORT.md` on GitHub
5. Have your ID within reach.
6. Do not record more than 15 minutes after the warm-up, or the service will be asleep again.

Answers take about 10 seconds each on the free plan. Talk through the trace while you wait instead of sitting silent.

## The script

### 1. Introduction (0:00 to 0:30) — camera on

- Show your face and your ID.
- **Say:** your name, that this is the AI Engineering Techniques and Architectures project, and that it is an agentic HR assistant for a made-up company called Fernhill Technologies, with synthetic data.

### 2. Architecture (0:30 to 1:30) — the diagram tab

Point at each box as you name it.

- **Say:** The employee's question goes to a FastAPI web app. A hand-written agent loop sends it to Claude with a list of tools. The model chooses the tools, and my code runs them.
- **Say:** The tools live on two MCP servers over Streamable HTTP. The policy server searches 26 policy documents with keyword and vector search. The HR server reads mock employee records and prepares mock actions.
- **Say:** The agent discovers the tools from the servers on every turn. There is no tool list in the agent's code.
- **Say:** Anything that must always hold is code, not prompt: who is signed in, who may see which record, date and balance arithmetic, and ticket confirmation.

### 3. Task 1: remote work eligibility (1:30 to 3:45) — the app tab

Type or click: **Can I work from Portugal for six weeks starting April 5, 2027?**

While it runs:

- **Say:** This needs the employee's own records and the policy, so one search is not enough.

When the answer appears, open **How this answer was reached** and go through the trace line by line:

| Point at | Say |
|---|---|
| `lookup_employee_profile`, no arguments | It first checks who is asking. There are no arguments because identity comes from my code in an HTTP header, not from the model |
| `check_policy_compliance` with `international_remote_work`, `2027-04-05`, `30`, `Portugal` | The model turned "six weeks" into 30 working days and called the rule check. The arithmetic happens in code on the server |
| Its result, `not_allowed` | Liam has already used 12 international days. 12 plus 30 is 42, above the 40-day maximum |
| `get_policy_section` with `POL-005`, `5.3` | It then reads the exact policy section so it can explain the rule and cite it |

Then the answer:

- **Say:** The answer is no, with the numbers, a citation to POL-005 section 5.3, and alternatives the policy supports. Open **Sources** to show the snippet behind the citation.
- **Say:** Every citation is checked in code against what the tools returned.

If the model also calls `search_policy_documents`, that is fine. Say that the model chooses its tools, so the exact sequence can vary.

### 4. Task 2: PTO request with a ticket (3:45 to 6:00) — the app tab

Type or click: **I want to take 3 days of PTO starting March 15, 2027. Can I? If so, please open a ticket for it.**

Go through the trace:

| Point at | Say |
|---|---|
| `check_policy_compliance` with `pto`, `2027-03-15`, `3` | It checks eligibility, probation, balance, notice and blackout periods against Liam's records. The result is allowed, with manager approval |
| `list_my_tickets` | It checks that a ticket for this does not already exist |
| `create_mock_hr_ticket` with category, summary and priority | This is step one of two. It returns a preview and a confirmation token. Nothing has been created |

- **Say:** The agent stops here and asks me. Creating a ticket is an action, so it needs my explicit yes. My code also blocks a preview and a confirmation in the same turn, so the model cannot skip this.

Click **Yes, create it**. In the new trace:

| Point at | Say |
|---|---|
| `create_mock_hr_ticket` with only `confirmation_token` | Step two. The ticket is created exactly as previewed, and I get its id |

- **Say:** The ticket is a mock action. It lives in memory and nothing is sent anywhere.

### 5. A guardrail (6:00 to 6:30) — the app tab

Ask: **What is the PTO balance of Dana Okafor (E1007)?**

- Point at `check_pto_balance` with `employee_id: E1007` in the trace, with the label "refused or failed".
- **Say:** The model did ask for Dana's balance, and the HR server refused. The access rule is code on the server: you can see your own records, a manager can see a direct report's profile and PTO, and nobody else can see anything. The model cannot get around it, because who is signed in comes from my code.

Skip this section if you are running long.

### 6. Deployment (6:30 to 7:15) — the health tab, then `render.yaml`

- Show `/health`. **Say:** The health check connects to both MCP servers and lists their tools, so "ok" means the whole service works.
- Show `render.yaml`. **Say:** It is one free Render web service. The build installs the packages and builds the search index. The API key is set in Render's dashboard and is not in the repository.
- **Say:** The free plan sleeps after 15 minutes. I measured a cold start of about 43 seconds, and warm answers of about 10 seconds, because the free plan has a tenth of a processor. This is documented in `deployed.md`.

### 7. CI/CD (7:15 to 7:45) — the Actions tab

- Open the latest green run and show the steps.
- **Say:** Every push and pull request runs these checks with no API key: an import check, a real server start, MCP tool discovery, and 78 tests. The agent tests use a scripted model.
- **Say:** Render deploys only after these checks pass. That is the `checksPass` line in `render.yaml`.

### 8. Evaluation (7:45 to 9:00) — the report tab

- **Say:** I wrote 29 gold cases in seven categories: policy, multi-document, tool, workflow, ambiguous, out of scope and safety. Each runs through the real agent and is scored by exact code checks and by a judge model.
- Point at the baseline column. **Say:** 86% of cases passed every check. Citation accuracy, tool selection, workflow completion and action safety were all 100%. Groundedness was 90%. Latency on my laptop was 5 seconds at the median.
- Point at `before_fixes`. **Say:** The first run passed 69%. It found real faults, such as citing sections the agent had never read, which I fixed.
- Point at the two ablation columns. **Say:** I ran two ablations. Turning off vector search made no measurable difference, because the agent rewrites questions into policy wording. Hiding the compliance tool kept answers mostly correct but made them slower and less complete.
- **Say:** The limits are one run per setting, no held-out set, and a judge that is itself a model.

### 9. Close (9:00 to 9:15) — camera on

- **Say:** The repository has the code, the design and evaluation document, the AI tooling notes and the deployed address. Thank you.

## If something goes wrong while recording

| Problem | What to do |
|---|---|
| The page takes a minute to load | The service fell asleep. Say that this is the documented cold start, or stop and warm it up again |
| "The demo has reached its daily limit" | The 300-requests-a-day cap was hit. Record the next day, or raise `DAILY_CHAT_LIMIT` in Render |
| The agent asks for confirmation a second time instead of creating the ticket | This happened once in the evaluation. Say yes again, or reload the page and repeat the task |
| The tool sequence differs from this script | Describe what the trace actually shows. The model chooses its tools |
