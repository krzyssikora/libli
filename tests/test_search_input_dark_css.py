"""Every <input type="search"> in a template must be themed.

app.css's global form-control rule covers `input[type=text|email|password|url],
select, textarea` -- NOT `type=search`. An unthemed search box keeps the UA's
white fill while inheriting dark mode's near-white --text-primary, so the typed
query is invisible (measured ~1.05:1 on the builder filter; seen again on the
student course catalog). Each search box is themed by a scoped rule instead:
either its container (`.catalog__field input[type="search"] { background: ... }`)
or its own class (`.input { background: ... }`).

The covered classes are DERIVED from the CSS, never pinned, so a new search box
dropped into an unthemed container turns this test red.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "node_modules", "staticfiles", ".git", ".worktrees"}


def _files(pattern):
    return [
        p
        for p in ROOT.rglob(pattern)
        if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
    ]


def _themed_classes():
    """(container classes, own classes) whose rule sets a background."""
    containers, own = set(), set()
    for css_file in _files("*.css"):
        if "vendor" in css_file.parts or css_file.name.endswith(".min.css"):
            continue
        css = re.sub(r"/\*.*?\*/", "", css_file.read_text(encoding="utf-8"), flags=re.S)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if not re.search(r"(^|;|\s)background(-color)?\s*:", body):
                continue
            for sel in selectors.split(","):
                sel = sel.strip()
                m = re.fullmatch(r'.*?\.([\w-]+)\s+input\[type="?search"?\]', sel)
                if m:
                    containers.add(m.group(1))
                m = re.fullmatch(r"\.([\w-]+)", sel)
                if m:
                    own.add(m.group(1))
    return containers, own


def _search_inputs():
    for tpl in _files("*.html"):
        if "templates" not in tpl.parts:
            continue
        soup = BeautifulSoup(tpl.read_text(encoding="utf-8"), "html.parser")
        for inp in soup.find_all("input", attrs={"type": "search"}):
            yield tpl.relative_to(ROOT).as_posix(), inp


def test_derivation_finds_the_known_rules():
    # Guards the guard: if the regexes stop matching, every input would look
    # uncovered -- or, worse, the sets could be empty while the template scan
    # also finds nothing. Pin that both sides actually see something.
    containers, own = _themed_classes()
    assert "catalog__field" in containers
    assert "builder__filter" in containers
    assert "input" in own
    assert sum(1 for _ in _search_inputs()) >= 5


def test_every_search_input_is_themed():
    containers, own = _themed_classes()
    uncovered = []
    for path, inp in _search_inputs():
        if own.intersection(inp.get("class") or []):
            continue
        ancestors = {c for parent in inp.parents for c in (parent.get("class") or [])}
        if containers.intersection(ancestors):
            continue
        uncovered.append(f"{path}: {inp}")
    assert not uncovered, (
        "search inputs with no themed rule -- white box in dark mode. Add the "
        "container to the filter-bar search rule in core/css/app.css:\n"
        + "\n".join(uncovered)
    )
