# Notes for ai-tooling.md

Running notes on what the AI coding tool (Claude Code) did well and badly. To be turned into `ai-tooling.md` in Phase 8.

## Went well

- Phase 1: expanded the corpus from 13 to 26 policies and wrote a test that checks every cross-reference between policies points at a real section.
- Phase 2: measured retrieval before building the agent (hit@5 and MRR for keyword, vector, hybrid), which gave the first ablation for free.
- Phase 3: the installed MCP SDK was version 2, where `FastMCP` no longer exists. The tool read the installed package instead of writing code from memory, so the servers worked on the first run.
- Phase 3: proposed keeping rule arithmetic (business days, balances) in code and identity in HTTP headers, not in the model.
- Phase 4: tested the agent loop with a scripted model, so the guards (step limit, retry, ticket confirmation) are tested without API cost and pass every time.
- Phase 4: the search that missed "out of days left for the year" in Phase 2 is found by the live agent, because the prompt tells the model to search with policy wording. It searched for "negative PTO balance ... unpaid leave".
- Phase 5: built the chat page as one HTML file with no framework, then drove it in a real browser (a live question, the ticket yes button, a phone-sized screen) before calling it done.
- Phase 6: the first full evaluation run exposed real faults that hand testing had missed: answers citing sections the agent had only seen mentioned, and a refused request offered as an "exception" option. Both were fixed (a citation check in code, a prompt rule, and a clearer message from the compliance tool).
- Phase 6: a test checks the gold cases themselves (tool names, employee ids and cited sections all exist), so a typo in a gold case cannot be mistaken for an agent failure.

## Went badly, or needed a human

- Phase 2: the student's first gold labels pointed at the wrong sections. The tool caught it, but only a person reading the policy can decide what the right answer is.
- Phase 2: the search missed "out of days left for the year" (the policy says "negative balance"). Kept as a known miss to measure against later.
- Phase 3: a careless find-and-replace in the test file broke 11 tests twice before it was fixed. The servers were fine. The mistake was in the tool's own editing.
- Phase 3: an async test fixture failed on teardown with the MCP session manager. Replaced with a helper that starts a fresh app per test.
- Phase 4: the first system prompt said the assistant "cannot see other employees' records", which contradicted the manager rule in the code. A live test as a manager exposed it. The prompt now tells the model to call the tool and report what it returns.
- Phase 4: the first token count ignored cached input, so it under-reported by about four times. Found by comparing two live runs.
- Phase 4: the tool's instructions were too short for the student twice ("fix the test" without saying which line). Exact line-by-line steps worked.
- Phase 5: the example questions stayed on screen after the first message, because a CSS rule overrode the `hidden` attribute. Only the browser check showed it. The tests passed throughout.
- Phase 4: the student did not follow the written explanation of why a tool question needs two model calls. Text alone did not teach it. The trace panel in the web page is the next attempt.
- Phase 6: results vary from run to run. The ticket workflow passed in run 1, failed in run 2 (the model wrote a preview without calling the tool) and passed in run 3 after a prompt rule. One run per setting is a small sample, so a difference of one or two cases is noise.
- Phase 6: the prompt was tuned on the same 29 cases it is scored on, over three runs (69%, 72%, 86% passing every check). There is no held-out set, so the final number is optimistic. New cases written by the student are the fairest test.
- Phase 6: the judge model was too strict at first. It marked statements about the assistant's own tools as "unsupported claims". Its instructions were changed between runs, which also moves the groundedness number.
- Phase 6: about one US dollar of API spend across three full runs and several small rechecks, started without asking the student for a budget first.

## Human decisions

- Corpus size (student asked for a much larger corpus than the first draft).
- Which gold questions to add, and keeping hard ones that fail.
- Phase 4: the model chooses the tools, with limits in code. A failed tool is retried once, then the answer says what could not be checked. Past cases are limited to the employee's own tickets.
- Phase 3 exercise: the student wrote the `list_my_tickets` tool and fixed the discovery test.

## Phase 7: CI/CD and deployment

- Worked well: Claude Code rehearsed the CI run before anything was pushed. It copied only the files git would commit into an empty folder, installed from scratch with no API key, and ran every workflow step and the Render build command there. That showed the workflow would pass on a clean machine.
- Worked well: it measured memory before choosing the deployment settings (about 160 MB keyword, about 420 MB hybrid, against Render's 512 MB) instead of guessing.
- Worked well: it checked Render's current documentation for the `autoDeployTrigger: checksPass` setting instead of relying on memory. The older `autoDeploy` field it might have used is deprecated.
- Needed care: the tool noticed the `gh` command line was signed in to the wrong GitHub account for this project. Pushing would have gone to the professional account.
- Limit: it could not create the GitHub repository, the Render service or any key itself. Those steps were done by hand.
