"""Source-level invariants for builder.js.

The detail panel is a scroll container (builder.css). Every content swap must reset
scrollTop, or the next unit's panel opens scrolled part-way down. Rather than trust
nine call sites to each remember, all writes funnel through setPanel() — and this test
is what actually enforces that, since a grep in a spec is not run by CI.
"""

import re
from pathlib import Path

BUILDER_JS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "builder.js"
)

# `panel.innerHTML` followed by `=` but not `==`/`===`. The line-10 read
# (`var neutralPanel = panel.innerHTML;`) has no following `=`, so it is excluded
# naturally rather than special-cased.
ASSIGNMENT = re.compile(r"panel\.innerHTML\s*=(?!=)")


def test_exactly_one_panel_innerhtml_assignment():
    source = BUILDER_JS.read_text(encoding="utf-8")
    hits = ASSIGNMENT.findall(source)
    assert len(hits) == 1, (
        f"expected exactly 1 panel.innerHTML assignment (inside setPanel), found "
        f"{len(hits)}. Route every panel write through setPanel() so scrollTop resets."
    )


def test_setpanel_resets_scrolltop():
    source = BUILDER_JS.read_text(encoding="utf-8")
    assert "function setPanel(" in source, "setPanel() helper is missing"
    # Regex over the helper's body rather than splitting on "\n  }" — that heuristic
    # assumes the closing brace is exactly two spaces deep and breaks silently on any
    # reformatting, turning a real invariant into a false pass.
    assert re.search(
        r"function setPanel\([^)]*\)\s*\{[^}]*scrollTop\s*=\s*0", source
    ), "setPanel() must reset panel.scrollTop to 0"
