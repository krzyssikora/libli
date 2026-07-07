"""Backwards-compatible shim. The trusted-markdown renderer moved to core.help
(the shared home for the in-app help system). Both names are re-exported so
existing integrations imports keep resolving:
  - integrations/views.py imports render_markdown_doc
  - integrations/tests/test_guide_content.py imports DOCS_ROOT
Tests that need to redirect the docs root must monkeypatch core.help.DOCS_ROOT
(this module only re-binds the name once, at import)."""

from core.help import DOCS_ROOT  # noqa: F401
from core.help import render_markdown_doc  # noqa: F401
