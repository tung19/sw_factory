"""area.web.upload — turn an uploaded requirement document into intake artifacts.

The user uploads their requirement as PDF / Word / Markdown (plus an optional
typed description). We parse each file to text and save it under
workspace/.area/uploads/<name>/ as .md, so `area intake <dir>` can ingest it
(and the combined text is also returned so a `run` job can use it as the
requirement). PDF via pypdf, .docx via python-docx; text formats pass through.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from area._util import safe_name
from area.web.jobs import WORKSPACE

UPLOAD_DIR = WORKSPACE / ".area" / "uploads"
_TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ".yaml", ".yml", ".json", ""}


def parse_file(filename: str, data: bytes) -> str:
    """Extract plain text from an uploaded requirement file."""
    ext = Path(filename).suffix.lower()
    if ext in _TEXT_EXTS:
        return data.decode("utf-8", errors="ignore")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((pg.extract_text() or "") for pg in reader.pages).strip()
        except Exception as e:  # noqa: BLE001
            return f"[could not parse PDF {filename}: {e}]"
    if ext in (".docx", ".dotx"):
        try:
            import docx

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except Exception as e:  # noqa: BLE001
            return f"[could not parse Word {filename}: {e}]"
    # Unknown binary: best-effort decode.
    return data.decode("utf-8", errors="ignore")


def save_intake(
    name: str, files: list[tuple[str, bytes]], description: str = ""
) -> dict[str, Any]:
    """Parse uploads + description into an intake artifact dir.

    Returns {dir, files, text, chars}: `dir` feeds `area intake`, `text` is the
    combined requirement a `run` job can use instead.
    """
    name = safe_name(name)
    d = UPLOAD_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    parts: list[str] = []
    for fn, data in files:
        text = parse_file(fn, data)
        base = safe_name(Path(fn).stem) or "doc"
        out = d / f"{base}.md"
        # avoid clobbering two uploads that sanitize to the same name
        i = 2
        while out.exists() and out.name not in saved:
            out = d / f"{base}-{i}.md"
            i += 1
        out.write_text(text)
        saved.append(out.name)
        parts.append(f"=== {fn} ===\n{text}")
    if description and description.strip():
        (d / "_description.md").write_text(description.strip())
        saved.append("_description.md")
        parts.append(f"=== description ===\n{description.strip()}")
    combined = "\n\n".join(parts).strip()
    return {"dir": str(d), "files": saved, "text": combined, "chars": len(combined)}
