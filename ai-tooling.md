# AI tooling

How AI tools were used to build this project, what worked and what did not.

## Tools used

| Tool | Used for |
|---|---|
| Claude Code (Anthropic's coding agent, in its desktop app) | Planning the phases, writing most of the code, tests and policy documents, running and checking them, and drafting the documentation |
| Claude Haiku through the Anthropic API | The model inside the product: it is the agent's reasoning model |
| Claude Sonnet through the Anthropic API | The judge model in the evaluation |

Most of the code in this repository was written by Claude Code under my direction. I did not hand-write most of it.

## How I worked with it

The project was built in nine phases: setup, corpus and mock data, retrieval, MCP servers, agent loop, web app, evaluation, CI/CD and deployment, documentation. I asked Claude Code to treat the project as a way to teach me how agents are built, so each phase followed the same pattern:

1. It explained the concept in plain language before writing code.
2. It built the phase and ran it, showing the output or the trace.
3. It left a small piece for me to write or change myself.
4. I decided when to move on.

A file of standing instructions, `CLAUDE.md`, records the decisions made so far and the rules for working in the repository, such as never asking for an API key in chat and committing only when asked. Claude Code reads it at the start of every session, which kept decisions consistent across sessions.

## What I did myself

- Chose the scope: a much larger corpus than the first draft, and which gold questions to add, including hard ones that fail.
- Made the design decisions when asked: the model chooses the tools with limits in code, a failed tool is retried once, and the deployed demo keeps hybrid search even though it is slower.
- Wrote the `list_my_tickets` MCP tool and its description, and fixed the tool discovery test to include it.
- Wrote a rule in the system prompt about acknowledging an employee who sounds stressed, and tested it.
- Ran the step-limit experiment (`AGENT_MAX_STEPS=1`) to see the guard stop the agent.
- Ran both ablation runs and read the results.
- Wrote the step in the CI workflow that runs the tests, and pushed it.
- Created the API key, the GitHub repository settings and the Render service, and pasted the key into Render myself. The key was never typed into the chat.

## What worked well

- **Reading the installed package instead of writing from memory.** The MCP SDK installed was version 2, where the `FastMCP` class from most online examples no longer exists. Claude Code read the installed package first, so the servers worked on the first run.
- **Measuring before choosing.** It measured retrieval (keyword, vector, hybrid) before the agent existed, measured memory before choosing deployment settings, and timed the deployed service before recommending a search mode.
- **Testing the agent without the API.** It proposed a scripted stand-in for the model, so the guards in the loop (step limit, retry, ticket confirmation, citation check) are tested for free and pass every time.
- **Keeping rules in code.** It proposed putting date and balance arithmetic, identity and access rules in code, and leaving only judgment to the model.
- **Checking in a real browser.** After building the chat page it opened the page, asked a live question, pressed the ticket confirmation button and tried a phone-sized screen. That found a fault the tests could not see.
- **The evaluation found real faults.** The first full run passed 69% of cases and exposed answers citing sections the agent had never read, and a refused request offered as an "exception". Both were fixed and measured again.
- **Rehearsing CI before pushing.** It copied only the files git would commit into an empty folder, installed from scratch with no API key, and ran every workflow step and the Render build command there.
- **Checking current documentation.** For the Render setting that gates deployment on CI, it read Render's documentation instead of relying on memory. The older setting is deprecated.

## What did not work well

- **Careless edits.** A find-and-replace in a test file broke 11 tests twice before it was fixed. The product code was fine. The mistake was in the tool's own editing.
- **A prompt that contradicted the code.** The first system prompt said the assistant "cannot see other employees' records", which contradicted the rule that a manager may see a direct report's PTO. Only a live test as a manager exposed it.
- **Wrong numbers.** The first token count ignored cached input and under-reported by about four times. It was found by comparing two live runs.
- **Instructions that were too short for me.** Twice it told me to "fix the test" without saying which file, which line or what to type. Exact line-by-line steps worked. Vague ones did not.
- **An explanation that did not land.** I did not follow its written explanation of why a tool question needs at least two model calls. The trace panel in the web page explained it better than the text did.
- **Spending without asking.** It ran about one US dollar of evaluation runs before asking me for a budget.
- **Tuning on the test set.** The prompt was improved over three runs on the same 29 cases it is scored on (69%, 72%, 86%). There is no held-out set, so the final figure is optimistic. Claude Code pointed this out itself, after the fact.
- **A judge that was too strict.** The judge model first marked statements about the assistant's own tools as unsupported claims. Its instructions were changed between runs, which also moved the groundedness figure.
- **Things it could not do.** It could not create the GitHub repository settings, the Render service or the API key. It also nearly pushed to my other GitHub account, and my own first push failed for the same reason: two accounts on one machine.
- **Sandbox limits.** Its built-in preview could not start the app from my Documents folder, so it ran the server another way.

## What only a person could decide

- What the right answer to a gold question is. My first gold labels pointed at the wrong policy sections. The tool noticed they looked wrong, but someone had to read the policy to decide.
- Whether a failing evaluation case is the agent's fault, the gold answer's fault or the judge's fault.
- Trade-offs with no measured winner, such as keeping hybrid search on the deployed demo.

## My own view

- I was surprised at how easy it was to work with Claude Code. Providing the frame of the project, completing tasks, changing anything, and making decisions was incredibly quick and easy to execute.
- In some of the more technical tasks, particularly the RRF_K value, I needed quite a bit of explaining before I understood what it does. I now understand that hybrid search produces two ranked lists, one from keyword search and one from vector search, and each policy section scores 1 / (RRF_K + its rank) from each list it appears in. A small RRF_K lets the top result of one list dominate. A large one flattens the difference between ranks, so a section that both lists agree on wins over a section that only one list ranks first. We kept the standard value of 60.
- In this process I was very happy to learn more about tool calling. In the past I thought the tools agents used were ready-made open source tools. In fact the developer writes each tool, its description and its arguments before the agent runs, and the agent only chooses which to call. I found this very interesting and see it opens a whole bunch of possibilities.
- If I were to approach this assignment again, I would like to explore the use of open source LLMs, in case I need it in a professional setting in the future.


## Responsibility

AI tools wrote most of this code, but I am responsible for it. I ran the tests, the evaluation and the deployed service myself, and I can explain the agent loop, the MCP servers and the evaluation harness.
