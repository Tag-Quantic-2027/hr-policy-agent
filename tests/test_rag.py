"""Tests for loading, chunking and keyword search.

These tests use keyword search only, so they need no embedding model and no
network. Vector and hybrid search are measured by evaluation/retrieval_check.py.
"""

from app.config import CORPUS_DIR
from app.rag.chunking import MAX_WORDS, chunk_corpus
from app.rag.index import PolicyIndex, tokenize
from app.rag.loaders import load_corpus

DOCS = load_corpus(CORPUS_DIR)
CHUNKS = chunk_corpus(DOCS)
BY_ID = {chunk.chunk_id: chunk for chunk in CHUNKS}
INDEX = PolicyIndex(CHUNKS)


def test_every_policy_loads_with_metadata_and_sections():
    assert len(DOCS) == 26
    for doc in DOCS:
        assert doc.doc_id == doc.source_file[:7]
        assert doc.title and doc.effective_date and doc.version
        assert len(doc.sections) >= 10, doc.doc_id


def test_all_four_formats_produce_sections():
    formats = {doc.source_file.rsplit(".", 1)[1] for doc in DOCS}
    assert formats == {"md", "html", "txt", "pdf"}


def test_chunk_ids_are_unique_and_chunks_are_not_too_long():
    assert len(BY_ID) == len(CHUNKS)
    for chunk in CHUNKS:
        assert len(chunk.text.split()) <= MAX_WORDS * 1.5, chunk.chunk_id


def test_known_rules_land_in_the_expected_section():
    assert "20 working days" in BY_ID["POL-005#5.1"].text  # Markdown
    assert "Belarus" in BY_ID["POL-006#7"].text  # PDF
    assert "10 business days" in BY_ID["POL-008#8.1"].text  # plain text
    assert "16 weeks" in BY_ID["POL-010#4.1"].text  # HTML


def test_html_page_noise_is_removed():
    for chunk in CHUNKS:
        assert "HR portal home" not in chunk.text
        assert "Internal use only" not in chunk.text


def test_chunk_carries_its_citation_and_context():
    chunk = BY_ID["POL-005#5.3"]
    assert chunk.citation == "POL-005 section 5.3"
    assert chunk.search_text.startswith("POL-005 Working From Another Location Policy > 5. International Remote Work")


def test_long_tables_are_split_with_their_header_repeated():
    parts = [chunk for chunk in CHUNKS if chunk.chunk_id.startswith("POL-026#5")]
    assert len(parts) > 1
    assert all(part.text.splitlines()[0].startswith("| Request | Who approves") for part in parts[:2])


def test_tokenizer_keeps_policy_ids_whole():
    assert "pol-007" in tokenize("What does POL-007 say?")


def test_keyword_search_finds_the_stipend_rule():
    found = [hit.chunk.chunk_id for hit in INDEX.search("home office stipend amount", k=5, mode="keyword")]
    assert "POL-007#6.1" in found
