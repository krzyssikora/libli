"""In-app help system: trusted-markdown renderer + role-aware topic registry.

Content is repo-authored (fixed paths only), never user input, so the renderer
applies no sanitization. A missing file is a packaging/deploy bug — fail loud."""

from pathlib import Path

import markdown

# core/help.py -> parent is the app dir; its parent is the repo root, which
# holds docs/.
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"


def render_markdown_doc(rel_path):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["fenced_code", "tables"])
