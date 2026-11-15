"""Render the plain-text policy source into a PDF for the corpus.

Why this exists: the brief asks the ingestion pipeline to handle more than one
file format. Some policies are published as PDFs so the pipeline has real PDFs to
parse. Each text source in scripts/pdf_source/ becomes one PDF in corpus/, so
the PDFs can be rebuilt exactly.

Run:  .venv/bin/python scripts/build_policy_pdf.py
Needs: fpdf2 (a development-only dependency).
"""

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "scripts" / "pdf_source"
OUTPUT_DIR = ROOT / "corpus"


def header_value(lines: list[str], key: str) -> str:
    """Read one 'key: value' line from the top of a source file."""
    for line in lines:
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def build(source: Path) -> Path:
    """Render one text source to a PDF with the same file name in corpus/."""
    output = OUTPUT_DIR / f"{source.stem}.pdf"
    lines = source.read_text(encoding="utf-8").splitlines()
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=22, top=20, right=22)
    pdf.add_page()

    for raw in lines:
        line = raw.rstrip()
        if not line:
            pdf.ln(3)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 18)
            pdf.multi_cell(0, 9, line[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, line[3:], new_x="LMARGIN", new_y="NEXT")
        elif line.startswith("### "):
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, line[4:], new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 10.5)
            pdf.multi_cell(0, 5.5, line, new_x="LMARGIN", new_y="NEXT")

    # Fixed metadata so rebuilding the PDF does not change the file for no reason.
    pdf.set_title(header_value(lines, "title"))
    pdf.set_author(f"Fernhill Technologies {header_value(lines, 'owner')} (fictional)")
    pdf.output(str(output))
    return output


if __name__ == "__main__":
    for source in sorted(SOURCE_DIR.glob("*.txt")):
        path = build(source)
        print(f"Wrote {path.relative_to(ROOT)}")
