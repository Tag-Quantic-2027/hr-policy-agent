"""Stage 1 of retrieval: load every policy file into one common shape.

The corpus has four formats (Markdown, HTML, plain text, PDF). Each format has
its own loader, and every loader returns the same thing: a PolicyDocument with
metadata and a list of numbered Sections. Everything after this file can
ignore the original format.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader


@dataclass
class Section:
    """One numbered section of a policy, such as "5.3 Requests above the limit"."""

    number: str  # "5" or "5.3"
    title: str
    parent_number: str = ""  # "5" for section 5.3, empty for a top-level section
    parent_title: str = ""
    blocks: list[str] = field(default_factory=list)  # paragraphs, lists and tables


@dataclass
class PolicyDocument:
    doc_id: str
    title: str
    owner: str
    effective_date: str
    version: str
    source_file: str
    sections: list[Section]


# "5. Title" is a top-level heading, "5.3 Title" is a subsection heading.
TOP_HEADING = re.compile(r"^(\d{1,2})\.\s+(\S.{1,90})$")
SUB_HEADING = re.compile(r"^(\d{1,2}\.\d{1,2})\s+([A-Z].{1,90})$")


class _SectionBuilder:
    """Collects headings and text, in reading order, into a list of Sections."""

    def __init__(self) -> None:
        self.sections: list[Section] = []
        self._top: Section | None = None

    def top(self, number: str, title: str) -> None:
        self._top = Section(number=number, title=title.strip())
        self.sections.append(self._top)

    def sub(self, number: str, title: str) -> None:
        parent = self._top
        self.sections.append(
            Section(
                number=number,
                title=title.strip(),
                parent_number=parent.number if parent else "",
                parent_title=parent.title if parent else "",
            )
        )

    def text(self, block: str) -> None:
        block = block.strip()
        if block and self.sections:  # text before the first heading is the disclaimer: skip it
            self.sections[-1].blocks.append(block)

    def next_top_number(self) -> int:
        return int(self._top.number) + 1 if self._top else 1

    def done(self) -> list[Section]:
        # A top-level section with subsections often has no text of its own. Drop the empty ones.
        return [s for s in self.sections if s.blocks]


def _paragraphs(lines: list[str]) -> list[str]:
    """Group lines into blocks separated by blank lines."""
    blocks, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.rstrip())
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _document(meta: dict[str, str], path: Path, sections: list[Section]) -> PolicyDocument:
    return PolicyDocument(
        doc_id=meta["doc_id"],
        title=meta["title"],
        owner=meta.get("owner", ""),
        effective_date=meta.get("effective_date", ""),
        version=meta.get("version", ""),
        source_file=path.name,
        sections=sections,
    )


def load_markdown(path: Path) -> PolicyDocument:
    """Markdown: metadata between '---' lines, headings marked with ## and ###."""
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    meta = dict(line.split(": ", 1) for line in front.strip().splitlines())

    builder = _SectionBuilder()
    for block in _paragraphs(body.splitlines()):
        if block.startswith("### ") and (m := SUB_HEADING.match(block[4:])):
            builder.sub(*m.groups())
        elif block.startswith("## ") and (m := TOP_HEADING.match(block[3:])):
            builder.top(*m.groups())
        elif not block.startswith("# "):  # the single # line is the document title
            builder.text(block)
    return _document(meta, path, builder.done())


def load_html(path: Path) -> PolicyDocument:
    """HTML: metadata in <meta> tags, headings in <h2> and <h3>, plus page noise to remove."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    meta = {tag["name"]: tag["content"] for tag in soup.find_all("meta") if tag.get("name")}
    meta["title"] = soup.title.get_text(strip=True)

    # Navigation, footers, scripts and styles are not policy text.
    for noise in soup.find_all(["nav", "footer", "script", "style"]):
        noise.decompose()

    builder = _SectionBuilder()
    for tag in soup.body.find_all(["h2", "h3", "p", "ul", "ol", "table"]):
        text = tag.get_text(" ", strip=True)
        if tag.name == "h2" and (m := TOP_HEADING.match(text)):
            builder.top(*m.groups())
        elif tag.name == "h3" and (m := SUB_HEADING.match(text)):
            builder.sub(*m.groups())
        elif tag.name in ("ul", "ol"):
            builder.text("\n".join(f"- {li.get_text(' ', strip=True)}" for li in tag.find_all("li")))
        elif tag.name == "table":
            rows = [
                " | ".join(cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"]))
                for row in tag.find_all("tr")
            ]
            builder.text("\n".join(rows))
        elif tag.name == "p":
            builder.text(text)
    return _document(meta, path, builder.done())


def _load_plain_lines(meta: dict[str, str], lines: list[str], path: Path, join_wrapped: bool) -> PolicyDocument:
    """Shared by the text and PDF loaders: headings are found by their numbering.

    A line only counts as a top-level heading if its number is the next one in
    sequence. That stops a body line that happens to start with "3. " from
    being mistaken for a heading.
    """
    builder = _SectionBuilder()
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        if join_wrapped:  # PDF text is broken at the page width: rejoin it, keeping bullets apart
            block, parts = "", []
            for line in pending:
                if line.startswith("- "):
                    parts.append(block)
                    block = line
                else:
                    block = f"{block} {line}".strip()
            parts.append(block)
            for part in parts:
                builder.text(part)
        else:
            for block in _paragraphs(pending):
                builder.text(block)
        pending.clear()

    for line in lines:
        stripped = line.strip()
        top = TOP_HEADING.match(stripped)
        sub = SUB_HEADING.match(stripped)
        if top and int(top.group(1)) == builder.next_top_number() and not stripped.endswith("."):
            flush()
            builder.top(top.group(1), _title_case(top.group(2)))
        elif sub and not stripped.endswith(".") and sub.group(1).split(".")[0] == str(builder.next_top_number() - 1):
            flush()
            builder.sub(*sub.groups())
        else:
            pending.append(line)
    flush()
    return _document(meta, path, builder.done())


def _title_case(heading: str) -> str:
    """Turn "PURPOSE AND SCOPE" into "Purpose and Scope". Other headings are left alone."""
    if not heading.isupper():
        return heading
    small = {"and", "of", "the", "to", "in", "for", "a", "an", "or", "on"}
    words = heading.lower().split()
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def _split_header(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Read the 'KEY: value' lines at the top of a text or PDF policy."""
    meta, index = {}, 0
    while index < len(lines) and re.match(r"^[A-Za-z_]+: ", lines[index]):
        key, value = lines[index].split(": ", 1)
        meta[key.lower()] = value.strip()
        index += 1
    return meta, lines[index:]


def load_text(path: Path) -> PolicyDocument:
    """Plain text: 'DOC_ID: ...' header lines, headings in capitals with numbers."""
    meta, body = _split_header(path.read_text(encoding="utf-8").splitlines())
    return _load_plain_lines(meta, body, path, join_wrapped=False)


def load_pdf(path: Path) -> PolicyDocument:
    """PDF: extract the text of each page, then treat it like plain text."""
    lines: list[str] = []
    for page in PdfReader(path).pages:
        lines.extend(page.extract_text().splitlines())
    meta, body = _split_header(lines)
    return _load_plain_lines(meta, body, path, join_wrapped=True)


LOADERS = {".md": load_markdown, ".html": load_html, ".txt": load_text, ".pdf": load_pdf}


def load_corpus(corpus_dir: Path) -> list[PolicyDocument]:
    """Load every policy in the folder, in file name order."""
    return [
        LOADERS[path.suffix](path)
        for path in sorted(corpus_dir.iterdir())
        if path.suffix in LOADERS and path.name.startswith("POL-")
    ]
