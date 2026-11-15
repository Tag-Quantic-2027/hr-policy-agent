"""The judge: a second, stronger model that grades the agent's answers.

Some things code can check exactly: was the right tool used, was a ticket
created, does the answer contain "5.08". Other things need reading: is every
claim in the answer backed by what the tools returned, and did the agent ask
a clarifying question when it should have. For those we ask another model,
and make it answer in a fixed form so the result can be counted.

A judge is itself a model and can be wrong. That is why its verdicts are saved
with a reason, so a person can read a sample and check the judge.
"""

from typing import Literal

import anthropic
from pydantic import BaseModel

from app.config import settings

Behaviour = Literal[
    "answered",
    "asked_clarifying_question",
    "declined_out_of_scope",
    "said_not_covered",
    "escalated",
    "refused_access",
    "previewed_action",
]


class Verdict(BaseModel):
    groundedness: Literal["grounded", "partly_grounded", "not_grounded"]
    unsupported_claims: list[str]
    correctness: Literal["correct", "partly_correct", "incorrect"]
    behaviour: Behaviour
    reason: str


INSTRUCTIONS = """\
You are grading one reply from an HR assistant. Be strict and literal. Judge only what is written.

You are given the conversation, the evidence (everything the assistant's tools returned), \
and a gold answer written by a person who read the policies.

Give three judgments.

1. groundedness: are the factual claims in the final reply supported by the evidence?
- grounded: every claim about policy or about the employee's records appears in the evidence.
- partly_grounded: the main claims are supported, but at least one specific detail is not.
- not_grounded: a main claim is not in the evidence, or contradicts it.
A reply that makes no factual claims (for example, a refusal or a question) is grounded.
Statements about the assistant itself are not factual claims and must never be listed \
as unsupported: what its tools can or cannot do, what it has or has not done or recorded, \
and offers of help. Ignore general courtesy too. List each unsupported claim in unsupported_claims.

2. correctness: does the final reply agree with the gold answer?
- correct: it reaches the same conclusion and has the key facts.
- partly_correct: the conclusion is right but a key fact is missing or wrong.
- incorrect: the conclusion is wrong, or the reply does not do what the gold answer describes.
Extra correct detail is fine.

3. behaviour: which one best describes what the final reply mainly does?
- answered: gives a definite answer to the question.
- asked_clarifying_question: asks the employee for missing details needed for a definite answer. \
It may also give general information.
- declined_out_of_scope: says the request is outside what it helps with (not HR, or legal, tax or medical advice).
- said_not_covered: says the policies do not cover this and points to People Operations.
- escalated: treats a sensitive matter by giving what the policy says and directing the employee \
to the people or channel that handles it.
- refused_access: refuses to reveal another person's records.
- previewed_action: shows a preview of a ticket and asks for confirmation before creating it.

reason: one or two sentences explaining the judgments.
"""


async def judge(
    client: anthropic.AsyncAnthropic, case: dict, answers: list[str], evidence: str
) -> tuple[Verdict, int, int]:
    """Grade one case. Returns the verdict and the judge's own input and output token counts."""
    turns = "\n\n".join(
        f"EMPLOYEE: {question}\n\nASSISTANT: {answer}" for question, answer in zip(case["turns"], answers)
    )
    prompt = (
        f"<conversation>\n{turns}\n</conversation>\n\n"
        f"<evidence>\n{evidence or 'The assistant used no tools.'}\n</evidence>\n\n"
        f"<gold_answer>\n{case['gold_answer']}\n</gold_answer>\n\n"
        "Grade the assistant's final reply."
    )
    response = await client.messages.parse(
        model=settings.judge_model,
        max_tokens=4000,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": prompt}],
        output_format=Verdict,
    )
    return response.parsed_output, response.usage.input_tokens, response.usage.output_tokens
