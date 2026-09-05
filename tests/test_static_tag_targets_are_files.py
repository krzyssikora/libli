"""Every `{% static %}` target must resolve to a FILE that exists.

Production uses CompressedManifestStaticFilesStorage; its manifest maps source
paths to hashed names and contains an entry **per file**. `{% static %}` on a
path with no manifest entry raises

    ValueError: Missing staticfiles manifest entry for '<path>'

at RENDER time -- a 500, not a build failure, so collectstatic and the deploy
both go green and only the page breaks. Locally the same template is fine:
config/settings/local.py swaps in the plain StaticFilesStorage, which has no
manifest and happily returns a URL for anything, including a DIRECTORY.

That divergence is what shipped a unit editor that 500s on every page on
libli.pl while passing every local check: `MFE.fontsDirectory` was set from
`{% static 'courses/vendor/mathlive/fonts' %}` -- a directory. It went
unnoticed until the first content was imported, because an empty deployment has
no unit to open.

`finders.find()` is the same lookup collectstatic uses to locate sources, so a
target it cannot find has no manifest entry either; and a target it resolves to
a directory has none, since the manifest only ever lists files.
"""

import re
from pathlib import Path

import pytest
from django.contrib.staticfiles import finders

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIRS = [
    ROOT / "templates",
    ROOT / "courses" / "templates",
    ROOT / "core" / "templates",
]

# `{% static 'x' %}` / `{% static "x" %}`. Deliberately literal-only: a tag
# taking a variable cannot be resolved statically, and is left to runtime.
STATIC_TAG = re.compile(r"""\{%\s*static\s+(['"])(?P<target>[^'"]+)\1""")


def _static_references():
    for base in TEMPLATE_DIRS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for m in STATIC_TAG.finditer(text):
                line = text[: m.start()].count("\n") + 1
                yield path.relative_to(ROOT), line, m.group("target")


def test_there_are_static_references_to_check():
    """Guard the guard: a broken regex would make every assertion below vacuous."""
    refs = list(_static_references())
    assert len(refs) > 20, f"only {len(refs)} static tags found; the scanner is broken"


@pytest.mark.parametrize(
    "relpath,line,target",
    [pytest.param(p, ln, t, id=f"{p}:{ln}:{t}") for p, ln, t in _static_references()],
)
def test_static_target_resolves_to_an_existing_file(relpath, line, target):
    found = finders.find(target)
    assert found is not None, (
        f"{relpath}:{line} references {target!r}, which no staticfiles finder can "
        "locate. It gets no manifest entry, so this template raises "
        "'Missing staticfiles manifest entry' at render time in production."
    )
    assert Path(found).is_file(), (
        f"{relpath}:{line} references {target!r}, which resolves to a DIRECTORY "
        f"({found}). The staticfiles manifest lists files only, so production "
        "raises 'Missing staticfiles manifest entry' when this template renders, "
        "while the plain local storage returns a URL and hides it. Point the tag "
        "at a real file and derive the directory from it."
    )
