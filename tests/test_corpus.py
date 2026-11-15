"""Checks that the policy corpus is internally consistent.

The policies point at each other ("see POL-005 section 5.3"). If one of those
pointers is wrong, the agent will follow it, find nothing, and look broken.
These tests catch a bad pointer before the agent ever sees it.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

CORPUS = Path(__file__).resolve().parent.parent / "corpus"

# A heading looks like "## 5. Title", "5.3 Title", "5. TITLE" or "5.3 Title" in a PDF.
HEADING = re.compile(r"(?m)^\s*(?:#+\s*)?(\d+(?:\.\d+)?)\.?\s+[A-Z]")
# A pointer looks like "POL-005 section 5.3" or "POL-007 sections 2.2 and 2.3".
POINTER = re.compile(r"(POL-\d{3}),? sections? ([\d.]+(?:(?:,| and| to) [\d.]+)*)")


def read_text(path: Path) -> str:
    """Return the plain text of one policy file, whatever its format."""
    if path.suffix == ".pdf":
        return "\n".join(page.extract_text() for page in PdfReader(path).pages)
    if path.suffix == ".html":
        return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text("\n")
    return path.read_text(encoding="utf-8")


TEXTS = {path.name[:7]: read_text(path) for path in sorted(CORPUS.iterdir()) if path.name.startswith("POL-")}
SECTIONS = {doc_id: set(HEADING.findall(text)) for doc_id, text in TEXTS.items()}


def test_every_policy_has_a_unique_id():
    files = [p for p in CORPUS.iterdir() if p.name.startswith("POL-")]
    assert len(files) == len(TEXTS)


def test_corpus_uses_more_than_one_format():
    formats = {p.suffix for p in CORPUS.iterdir() if p.name.startswith("POL-")}
    assert {".md", ".html", ".txt", ".pdf"} <= formats


def test_corpus_is_within_the_size_the_brief_asks_for():
    pages = sum(len(text.split()) for text in TEXTS.values()) / 500
    assert 30 <= pages <= 120


def test_every_policy_mentioned_exists():
    for doc_id, text in TEXTS.items():
        for mentioned in set(re.findall(r"POL-\d{3}", text)):
            assert mentioned in TEXTS, f"{doc_id} mentions {mentioned}, which does not exist"


def test_every_section_pointer_lands_on_a_real_section():
    for doc_id, text in TEXTS.items():
        for target, numbers in POINTER.findall(text):
            for number in re.findall(r"\d+(?:\.\d+)?", numbers):
                assert number in SECTIONS[target], f"{doc_id} points at {target} section {number}"
