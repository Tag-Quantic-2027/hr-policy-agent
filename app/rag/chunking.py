"""Stage 2 of retrieval: cut each policy into chunks the agent can cite.

Chunking strategy: one chunk per numbered section. A policy section is one
rule ("5.3 Requests above the limit"), so cutting at section headings keeps
each rule whole and gives every chunk an exact citation. Cutting every N
characters would split rules in half and lose the section number.

Two details matter:

1. Each chunk starts with a context line (policy, parent section, section).
   A section called "4.1 Limit" means nothing on its own. With the context
   line, both the search and the model know it is the limit for domestic
   remote work in POL-005.
2. A section longer than MAX_WORDS is split between paragraphs, and a long
   table is split between rows with its header row repeated, so no part
   loses its column names.
"""

from dataclasses import asdict, dataclass

from app.rag.loaders import PolicyDocument, Section

MAX_WORDS = 220  # most sections are under 150 words, so only a few are ever split


@dataclass
class Chunk:
    chunk_id: str  # "POL-005#5.3", or "POL-001#7-2" for the second part of a split section
    doc_id: str
    doc_title: str
    section: str  # "5.3"
    section_title: str
    parent_title: str
    effective_date: str
    source_file: str
    text: str  # the section text only: this is what is shown as the snippet
    search_text: str  # context line plus text: this is what is indexed

    @property
    def citation(self) -> str:
        return f"{self.doc_id} section {self.section}"

    def metadata(self) -> dict[str, str]:
        """Everything except the two text fields, for storing next to the vector."""
        data = asdict(self)
        del data["text"], data["search_text"]
        return data


def _words(text: str) -> int:
    return len(text.split())


def _is_table(block: str) -> bool:
    lines = block.splitlines()
    return len(lines) > 2 and all(" | " in line or line.startswith("|") for line in lines)


def _split_long_block(block: str) -> list[str]:
    """Split one oversized block between its lines. Tables keep their header."""
    lines = block.splitlines()
    if len(lines) < 2:
        return [block]  # a single very long paragraph: keep it whole
    header: list[str] = []
    if _is_table(block):
        header_rows = 2 if set(lines[1]) <= set("|- :") else 1  # Markdown tables have a |---| row
        header, lines = lines[:header_rows], lines[header_rows:]

    parts, current = [], list(header)
    for line in lines:
        if _words("\n".join(current + [line])) > MAX_WORDS and len(current) > len(header):
            parts.append("\n".join(current))
            current = list(header)
        current.append(line)
    parts.append("\n".join(current))
    return parts


def _split_section(section: Section) -> list[str]:
    """Return the section text as one or more parts of at most MAX_WORDS words."""
    blocks: list[str] = []
    for block in section.blocks:
        blocks.extend(_split_long_block(block) if _words(block) > MAX_WORDS else [block])

    parts, current = [], []
    for block in blocks:
        if current and _words("\n\n".join(current + [block])) > MAX_WORDS:
            parts.append("\n\n".join(current))
            current = []
        current.append(block)
    parts.append("\n\n".join(current))
    return parts


def chunk_document(doc: PolicyDocument) -> list[Chunk]:
    chunks = []
    for section in doc.sections:
        path = [f"{doc.doc_id} {doc.title}"]
        if section.parent_title:
            path.append(f"{section.parent_number}. {section.parent_title}")
        path.append(f"{section.number} {section.title}")
        context = " > ".join(path)

        for index, text in enumerate(_split_section(section), start=1):
            suffix = "" if index == 1 else f"-{index}"
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#{section.number}{suffix}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    section=section.number,
                    section_title=section.title,
                    parent_title=section.parent_title,
                    effective_date=doc.effective_date,
                    source_file=doc.source_file,
                    text=text,
                    search_text=f"{context}\n\n{text}",
                )
            )
    return chunks


def chunk_corpus(docs: list[PolicyDocument]) -> list[Chunk]:
    return [chunk for doc in docs for chunk in chunk_document(doc)]
