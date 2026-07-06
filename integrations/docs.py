"""Render a trusted, repo-authored markdown doc to HTML. Content is NOT user
input (fixed paths only), so no sanitization is applied. Fail-loud on a missing
file: a missing static asset is a packaging/deploy bug, not a runtime condition."""

from pathlib import Path

import markdown

# integrations/docs.py -> parent is the app dir; its parent is the repo root,
# which holds docs/.
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"


def render_markdown_doc(rel_path):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["fenced_code", "tables"])
