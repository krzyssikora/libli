"""A stylesheet cross-reference must name a SELECTOR, never a line number.

WHY THIS EXISTS. This repo treats rationale comments as load-bearing, and many of
them point at a rule in another sheet. Pointing by ordinal does not survive
contact with the codebase: any diff that inserts a line above the target silently
rots every citation below it, in files the diff never touched, and nothing goes
red. AUDITED 2026-09-02 across the 101 live-code stylesheet citations that then
existed: 27 were provably stale (a named selector that was NOT within six lines
of the cited number), 13 were still correct, and 61 named nothing concrete enough
to check. Three measured examples, written here in words BECAUSE the test below
forbids the literal form: `textarea { resize: vertical }` was cited at app.css
line 150 and had moved to 196; `.visually-hidden` was cited at line 1330 of the
same sheet and had moved to 1414; `.callout__heading` was cited at courses.css
line 1966 and had moved to 2255, a drift of 289 lines.

courses.css already carried two comments recording that they had DELETED their
own numerals for exactly this reason ("the numeral this comment used to carry was
nine lines stale", "... was 35 lines stale"). This test makes that convention the
rule instead of a habit.

WHAT TO WRITE INSTEAD. Name the sheet and the selector:

    /* ... mirrors courses.css's `.unit-foot` ... */
    /* app.css declares `textarea { resize: vertical }`, which overrides ... */

A selector is greppable, and it moves with the rule it names.

SCOPE, and its two deliberate limits:

* Stylesheets only. The same rot affects `<module>.py:<line>`, `<file>.js:<line>`,
  `<template>.html:<line>` and bare self-references like "the block at :1834" --
  372 of those remained when this test was written. They are a larger cleanup and
  are NOT covered here; extending this test is the natural way to take them on,
  one population at a time. Do not add an allowlist to make a bulk exemption:
  teach this detector, or convert the citations.
* `docs/superpowers/specs/` is excluded (659 citations). Those are dated design
  records of what was true when written; re-pointing them would falsify the
  account rather than repair it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# `<name>.css:<digits>`, optionally a range. Built without a literal example of
# the offending form anywhere in this file -- a doc-string sample would make the
# test fail on itself.
CITATION = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\.css:\d+")

SEARCHED_SUFFIXES = {".css", ".py", ".js", ".html"}
SKIPPED_TOP_LEVEL = {
    ".venv",  # third-party
    ".git",
    ".claude",  # worktrees of this same repo
    "staticfiles",  # collectstatic output, a copy of the sources
    "node_modules",
    "media",  # uploaded content
    "docs",  # dated design records; see the module docstring
}


def _searched_files():
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in SEARCHED_SUFFIXES or not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in SKIPPED_TOP_LEVEL:
            continue
        yield relative, path


def test_no_stylesheet_is_cited_by_line_number():
    offenders = []
    for relative, path in _searched_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for hit in CITATION.finditer(line):
                offenders.append(f"{relative.as_posix()}:{number}: {hit.group(0)}")

    assert not offenders, (
        "stylesheet cross-references must name a selector, not a line number -- "
        "an insertion anywhere above the target rots these silently, in files the "
        "diff never touches. Replace each with the sheet plus the selector it "
        "means (see this module's docstring):\n  " + "\n  ".join(offenders)
    )


def test_the_scan_actually_reaches_the_stylesheets():
    """Without this the test above is green on a broken walk -- an empty file
    list has no offenders either. Pins the corpus, not just the verdict."""
    searched = {relative.as_posix() for relative, _ in _searched_files()}

    for expected in (
        "core/static/core/css/app.css",
        "core/static/core/css/tokens.css",
        "courses/static/courses/css/courses.css",
        "notes/static/notes/css/notes.css",
        "tests/test_stale_rationale_comments.py",
    ):
        assert expected in searched, f"{expected} was not scanned"

    stylesheets = [name for name in searched if name.endswith(".css")]
    assert len(stylesheets) >= 10, f"only {len(stylesheets)} stylesheets scanned"
