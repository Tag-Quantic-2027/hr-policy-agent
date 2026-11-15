"""Stage 3 of retrieval: index the chunks and search them.

Two searches run side by side:

- Keyword search (BM25) scores a chunk by the words it shares with the
  question. It is exact: "blackout" finds the blackout rule. It is also
  blind: "time off" does not find "PTO".
- Vector search turns the question and every chunk into a list of numbers
  (an embedding) that captures meaning, and finds the chunks whose numbers
  are closest. It finds "PTO" for "time off", but can miss exact terms.

Hybrid search merges the two ranked lists with reciprocal rank fusion (RRF):
each chunk earns 1 / (RRF_K + rank) from each list it appears in, and the
totals decide the final order. A chunk both searches like rises to the top.

Run a search from the terminal:
    .venv/bin/python -m app.rag.index "can I work from Portugal for six weeks"
"""

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.config import CHROMA_DIR, CORPUS_DIR, MODEL_DIR, settings
from app.rag.chunking import Chunk, chunk_corpus
from app.rag.loaders import load_corpus

RRF_K = 60  # the standard constant: larger values flatten the difference between ranks
CANDIDATES = 20  # how many results each search contributes before the merge
COLLECTION = "policies"

STOPWORDS = set(
    "a an and are as at be by can do does for from how i if in is it may me my of on or "
    "the to what when where which who will with you your".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase words for keyword search. "POL-007" stays one token."""
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
    return [w for w in words if w not in STOPWORDS]


@dataclass
class Hit:
    """One search result, with enough detail to show in the trace."""

    chunk: Chunk
    score: float
    keyword_rank: int | None  # position in the keyword results, or None if absent
    vector_rank: int | None  # position in the vector results, or None if absent


class PolicyIndex:
    def __init__(self, chunks: list[Chunk], chroma_dir: Path = CHROMA_DIR) -> None:
        self.chunks = chunks
        self.by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self._bm25 = BM25Okapi([tokenize(chunk.search_text) for chunk in chunks])
        self._chroma_dir = chroma_dir
        self._collection = None  # opened on first vector search, so keyword search needs no model

    @classmethod
    def from_corpus(cls, corpus_dir: Path = CORPUS_DIR, chroma_dir: Path = CHROMA_DIR) -> "PolicyIndex":
        return cls(chunk_corpus(load_corpus(corpus_dir)), chroma_dir)

    # ---- keyword search -------------------------------------------------

    def keyword_search(self, query: str, limit: int) -> list[str]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        return [self.chunks[i].chunk_id for i in ranked[:limit] if scores[i] > 0]

    # ---- vector search --------------------------------------------------

    def _fingerprint(self) -> str:
        """Changes whenever any chunk changes, so a stale index is rebuilt."""
        digest = hashlib.sha256()
        for chunk in self.chunks:
            digest.update(chunk.chunk_id.encode())
            digest.update(chunk.search_text.encode())
        return digest.hexdigest()

    def _open_collection(self):
        """Open the Chroma collection, embedding the chunks first if the corpus changed."""
        if self._collection is not None:
            return self._collection

        import chromadb  # imported here so keyword-only use never loads the embedding model
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        # Chroma downloads its embedding model to the home folder by default. Keeping it inside
        # the project means the copy downloaded while Render builds is there when the app runs.
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = MODEL_DIR / ONNXMiniLM_L6_V2.MODEL_NAME

        client = chromadb.PersistentClient(path=str(self._chroma_dir))
        fingerprint = self._fingerprint()
        existing = {c.name: c for c in client.list_collections()}
        if COLLECTION in existing and (existing[COLLECTION].metadata or {}).get("fingerprint") == fingerprint:
            self._collection = existing[COLLECTION]
            return self._collection

        if COLLECTION in existing:
            client.delete_collection(COLLECTION)
        # No embedding function is named, so Chroma uses its built-in ONNX MiniLM model.
        collection = client.create_collection(
            COLLECTION, metadata={"fingerprint": fingerprint, "hnsw:space": "cosine"}
        )
        for start in range(0, len(self.chunks), 100):
            batch = self.chunks[start : start + 100]
            collection.add(
                ids=[c.chunk_id for c in batch],
                documents=[c.search_text for c in batch],
                metadatas=[c.metadata() for c in batch],
            )
        self._collection = collection
        return collection

    def vector_search(self, query: str, limit: int) -> list[str]:
        result = self._open_collection().query(query_texts=[query], n_results=limit)
        return result["ids"][0]

    # ---- the search the agent uses --------------------------------------

    def search(self, query: str, k: int | None = None, mode: str | None = None) -> list[Hit]:
        k = k or settings.retrieval_top_k
        mode = mode or settings.retrieval_mode
        if mode not in ("hybrid", "vector", "keyword"):
            raise ValueError(f"Unknown retrieval mode: {mode}")

        keyword_ids = self.keyword_search(query, CANDIDATES) if mode in ("hybrid", "keyword") else []
        vector_ids = self.vector_search(query, CANDIDATES) if mode in ("hybrid", "vector") else []
        keyword_rank = {chunk_id: rank for rank, chunk_id in enumerate(keyword_ids, start=1)}
        vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, start=1)}

        # Reciprocal rank fusion. With one list only, this simply keeps that list's order.
        scores: dict[str, float] = {}
        for ranks in (keyword_rank, vector_rank):
            for chunk_id, rank in ranks.items():
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)

        best = sorted(scores, key=scores.get, reverse=True)[:k]
        return [
            Hit(self.by_id[cid], round(scores[cid], 5), keyword_rank.get(cid), vector_rank.get(cid))
            for cid in best
        ]


_index: PolicyIndex | None = None


def get_index() -> PolicyIndex:
    """The one shared index for the running app, built on first use."""
    global _index
    if _index is None:
        _index = PolicyIndex.from_corpus()
    return _index


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "How much is the home office stipend?"

    # Given a chunk id such as "POL-008#4", print that one section in full and stop.
    if re.fullmatch(r"POL-\d{3}#[\d.]+(-\d+)?", question):
        chunk = get_index().by_id.get(question)
        print(chunk.search_text if chunk else f"No chunk with the id {question}")
        sys.exit()

    print(f"Question: {question}\n")
    for hit in get_index().search(question):
        print(f"{hit.score:.4f}  keyword #{hit.keyword_rank}  vector #{hit.vector_rank}  {hit.chunk.citation}")
        print(f"        {hit.chunk.section_title}: {hit.chunk.text[:110].replace(chr(10), ' ')}...")
