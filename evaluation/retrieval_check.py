"""A first measurement of retrieval quality, before any agent exists.

Each gold question lists the section that holds the answer. The script runs
the question through the three retrieval modes and reports, for each mode:

- hit@k: the share of questions where the right section is in the top k.
- MRR:   mean reciprocal rank. 1.0 means the right section is always first,
         0.5 means it is second on average, 0 means it was not found.

This is the seed of the full evaluation in Phase 6, and it is the first
ablation: the same questions, with one part of the system switched off.

Run:  .venv/bin/python -m evaluation.retrieval_check
"""

from app.rag.index import get_index

K = 5

# (question as an employee would ask it, sections that count as a correct find)
GOLD = [
    ("How much is the home office stipend?", ["POL-007#6.1"]),
    ("How many days a year can I work from another country?", ["POL-005#5.1"]),
    ("Can I work from my parents' house in Spain for a month?", ["POL-005#5.1", "POL-005#5.2"]),
    ("Which countries am I never allowed to work from?", ["POL-006#7", "POL-005#5.4"]),
    ("How much notice do I need to give for a week of vacation?", ["POL-002#3.2"]),
    ("Can I take time off in my first two months?", ["POL-002#5"]),
    ("I lost my laptop, what do I do?", ["POL-006#8.2", "POL-006#8.3", "POL-008#7.4"]),
    ("When does my health insurance start?", ["POL-009#3.1"]),
    ("Do contractors get paid holidays?", ["POL-001#3.4"]),
    ("What hotel price is allowed in London?", ["POL-007#4.2", "POL-025#4.4"]),
    ("When do I get my referral bonus?", ["POL-021#4.2"]),
    ("What happens to my unused vacation when I quit?", ["POL-002#10", "POL-018#6.2"]),
    ("Can I take a day off to sit a certification exam?", ["POL-016#3.1", "POL-016#3.2"]),
    ("How do I change the bank account my salary goes to?", ["POL-014#3.4"]),
    ("What do I get for five years at the company?", ["POL-023#4.1"]),
    ("Can my manager see my medical information?", ["POL-013#7.2", "POL-006#3.5", "POL-020#4.2"]),
    ("Can I work from Portugal for six weeks?", ["POL-005#5.1", "POL-005#5.2", "POL-005#5.3", "POL-005#9"]),
    ("Can I get reimbursed for the cost of a certificate for professional development?", ["POL-016#2.2", "POL-016#2.4", "POL-009#7.1", "POL-007#7"]),
    ("Can I get a laptop upgrade if my current one is slow?", ["POL-008#4"]),
    ("Can I get additional time off if I am out of days left for the year?", ["POL-002#4.2", "POL-010#7.1"]),
    # Your turn: add three questions of your own here, in the same shape.
]


def reciprocal_rank(found: list[str], wanted: list[str]) -> float:
    for rank, chunk_id in enumerate(found, start=1):
        if chunk_id in wanted:
            return 1.0 / rank
    return 0.0


def main() -> None:
    index = get_index()
    print(f"{len(index.chunks)} chunks, {len(GOLD)} questions, k = {K}\n")
    print(f"{'mode':<10}{'hit@' + str(K):>8}{'MRR':>8}")

    misses: dict[str, list[str]] = {}
    for mode in ("keyword", "vector", "hybrid"):
        ranks = []
        for question, wanted in GOLD:
            found = [hit.chunk.chunk_id for hit in index.search(question, k=K, mode=mode)]
            ranks.append(reciprocal_rank(found, wanted))
            if ranks[-1] == 0:
                misses.setdefault(mode, []).append(question)
        hit_rate = sum(1 for r in ranks if r > 0) / len(ranks)
        print(f"{mode:<10}{hit_rate:>8.2f}{sum(ranks) / len(ranks):>8.2f}")

    for mode, questions in misses.items():
        print(f"\nMissed by {mode}:")
        for question in questions:
            print(f"  - {question}")


if __name__ == "__main__":
    main()
