"""Plain text extraction for v1 ingestion formats — docs/02-access-control-and-rag.md §5
(no ML parsing model; standard libraries only, per the scope decision recorded there)."""

import io

from docx import Document as DocxDocument
from pypdf import PdfReader


def extract_text(content: bytes, content_type: str) -> str:
    if content_type == "pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if content_type == "docx":
        doc = DocxDocument(io.BytesIO(content))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if content_type in ("md", "txt"):
        return content.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported content_type: {content_type}")


def infer_content_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".docx"):
        return "docx"
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "md"
    if lower.endswith(".txt"):
        return "txt"
    raise ValueError(f"Unsupported file extension: {filename}")
