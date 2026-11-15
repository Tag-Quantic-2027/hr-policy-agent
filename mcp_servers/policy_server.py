"""MCP server 1 of 2: the policy library.

What an MCP server is: a small program that offers tools over a standard
protocol. Each tool has a name, a description, and a schema for its inputs.
A client (our agent) first asks "what tools do you have?" (discovery), then
calls them by name. The agent never imports this file. It only knows what
the server tells it over the protocol.

How a tool is defined here:
- The function name becomes the tool name.
- The docstring becomes the description. The model reads it to decide when
  to use the tool, so it is written for the model, like a prompt.
- The type hints become the input schema, which the SDK builds and checks.

This server has no access rules. Policies are published to every employee.
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.rag.index import get_index

server = MCPServer(
    "policy",
    instructions="Search and read the Fernhill Technologies HR policies. Cite the citation field of what you use.",
)


def _section(chunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "citation": chunk.citation,
        "doc_id": chunk.doc_id,
        "doc_title": chunk.doc_title,
        "section": chunk.section,
        "section_title": chunk.section_title,
        "parent_section_title": chunk.parent_title,
        "effective_date": chunk.effective_date,
        "source_file": chunk.source_file,
        "text": chunk.text,
    }


@server.tool()
def search_policy_documents(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search the HR policy library and return the most relevant policy sections.

    Use this for any question about company rules: time off, leave, remote work,
    expenses, benefits, equipment, pay, conduct and similar. Each result is one
    numbered section, with its full text and a citation such as "POL-005 section 5.1".

    Tips: search with the words a policy would use ("negative PTO balance",
    "unpaid personal leave") as well as the employee's own words. If the results
    do not answer the question, search again with different wording before
    concluding that the policies do not cover it.

    Args:
        query: What to look for, as a question or as key words.
        top_k: How many sections to return, from 1 to 10.
    """
    hits = get_index().search(query, k=max(1, min(top_k, 10)))
    return {
        "query": query,
        "result_count": len(hits),
        "results": [{**_section(hit.chunk), "score": hit.score} for hit in hits],
    }


@server.tool()
def get_policy_section(doc_id: str, section: str) -> dict[str, Any]:
    """Read one policy section in full, by policy id and section number.

    Use this when you already know which section you need, for example when a
    search result or another tool refers to "POL-006 section 7".

    Args:
        doc_id: The policy id, such as "POL-005".
        section: The section number, such as "5" or "5.3".
    """
    doc_id, section = doc_id.strip().upper(), section.strip().rstrip(".")
    chunks = get_index().chunks
    in_document = [chunk for chunk in chunks if chunk.doc_id == doc_id]
    if not in_document:
        return {"found": False, "message": f"There is no policy with the id {doc_id}."}

    # A long section is stored as several parts. A section with subsections has its text in them.
    parts = [c for c in in_document if c.section == section] or [
        c for c in in_document if c.section.startswith(section + ".")
    ]
    if not parts:
        return {
            "found": False,
            "message": f"{doc_id} has no section {section}.",
            "sections_in_document": list(dict.fromkeys(c.section for c in in_document)),
        }
    return {"found": True, "doc_id": doc_id, "requested_section": section, "parts": [_section(c) for c in parts]}
