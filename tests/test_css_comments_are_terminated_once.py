"""A CSS comment must not contain the sequence that ends it.

WHY THIS EXISTS. CSS comments do not nest and have no escape. The FIRST closing
sequence ends the comment, wherever it appears -- including in the middle of a
sentence. This repo writes long rationale comments that name selectors and class
stems, and a stem written as a glob (`ta-*` followed immediately by `/va-*`) puts
that sequence inside the prose. Everything after it is then parsed as CSS: the
parser reads tokens as a selector prelude until it meets the next `{`, which
belongs to the FOLLOWING RULE, so that rule gets an unparseable selector and is
discarded whole. The comment still LOOKS like a comment in the editor, the
stylesheet still validates as a whole, and nothing goes red.

FOUND 2026-09-09, by measuring a layout bug, at two sites:

* `courses.css` -- the fill-in table's block comment described it as a twin of
  `.el--table` sharing the alignment class stems, writing the two stems as a
  glob pair. It swallowed `.filltable { margin: var(--space-4) 0; }`, so the
  fill-in table had NO vertical margins at all. Combined with the notes rail's
  deliberate -1rem pull on `.block-notes` -- which assumes each block's content
  ends with a 1rem bottom margin that collapses out to the section -- the section
  came out 16px SHORTER than its own content, and the next block's 16px
  `margin-top` cancelled exactly against that deficit. Reported from prod: the
  fill-in table's Check button sat flush against the spoiler pill below it, at a
  measured gap of 0.0px.
* `editor.css` -- the gallery editor's comment named the two icon-sprite stems
  the same way, swallowing `.el-editor--gallery { display: grid; ... }`.

WHAT TO WRITE INSTEAD. Put a space between the star and the slash (`ta-* / va-*`),
or drop the glob and name the stems in words. Either keeps the sentence readable
and the comment closed exactly once.

HOW IT DETECTS. Not by pattern-matching the prose -- an early terminator is
indistinguishable from an intended one by looking at the text around it. The
signal is structural: scan comment-open to comment-close, then look at what
follows. If another closing sequence appears BEFORE the next opening one, the
first comment ended somewhere its author did not intend, because a stylesheet
outside a comment has no reason to carry one. That test is exact, needs no
allowlist, and cannot be satisfied by rewording.

SCOPE. Project stylesheets only. Vendored sheets (KaTeX, MathLive) are minified
third-party output, are not maintained here, and are skipped -- their own comment
handling is not this repo's to police.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Built from fragments so this module does not contain the offending shape and
# fail against itself -- the same defence the sibling citation lint uses.
OPEN = "/" + "*"
CLOSE = "*" + "/"

SKIPPED_TOP_LEVEL = {
    ".venv",
    ".git",
    ".claude",  # worktrees of this same repo
    "staticfiles",  # collectstatic output, a copy of the sources
    "node_modules",
    "media",
}
# Vendored, minified, not ours to police.
SKIPPED_PARTS = {"vendor"}


def _stylesheets():
    for path in sorted(ROOT.rglob("*.css")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in SKIPPED_TOP_LEVEL:
            continue
        if SKIPPED_PARTS & set(relative.parts):
            continue
        yield relative, path


def _offenders(text):
    """Yield (line, ended_at, stray_at) for each comment that closes early.

    Walks comment by comment. After a comment closes, a further closing sequence
    reached before the next opening one can only mean the comment just walked
    ended before its author's own terminator.
    """
    index = 0
    while True:
        start = text.find(OPEN, index)
        if start == -1:
            return
        end = text.find(CLOSE, start + 2)
        if end == -1:
            yield (text.count("\n", 0, start) + 1, "unterminated", "")
            return
        next_open = text.find(OPEN, end + 2)
        stray = text.find(CLOSE, end + 2)
        if stray != -1 and (next_open == -1 or stray < next_open):
            yield (
                text.count("\n", 0, start) + 1,
                text[max(0, end - 40) : end + 2].strip(),
                text[max(0, stray - 50) : stray + 2].strip(),
            )
        index = end + 2


def test_no_css_comment_closes_before_its_author_meant_it_to():
    offenders = []
    for relative, path in _stylesheets():
        text = path.read_text(encoding="utf-8")
        for line, ended, stray in _offenders(text):
            offenders.append(
                f"{relative.as_posix()}:{line}\n"
                f"      closed at: ...{ended}\n"
                f"      leaving:   ...{stray}"
            )

    assert not offenders, (
        "a CSS comment closed before its author's own terminator, so the prose "
        "after it is being parsed as CSS and the NEXT RULE is silently "
        "discarded. Put a space between the star and the slash, or name the "
        "stems in words (see this module's docstring):\n  " + "\n  ".join(offenders)
    )


def test_the_scan_actually_reaches_the_stylesheets():
    """Without this the test above is green on a broken walk.

    Pins BOTH sheets the original defect was found in, so a walk that silently
    stops covering `courses/static` keeps this file honest. An empty corpus has
    no offenders either, which is exactly how this lint would fail open.
    """
    found = {relative.as_posix() for relative, _ in _stylesheets()}
    assert "courses/static/courses/css/courses.css" in found
    assert "courses/static/courses/css/editor.css" in found
    assert "core/static/core/css/app.css" in found
    assert len(found) >= 10, f"expected the project's stylesheets, walked {found}"


def test_the_detector_fires_on_the_shape_it_exists_to_catch():
    """The walk above must actually detect the defect, not merely run.

    Built from the real courses.css sentence that caused it. Without this, a
    detector that never fires is indistinguishable from a clean repo.
    """
    broken = (
        OPEN + " --- Fill-in table. Structurally a twin of\n"
        "   .el--table (same border/ta-*" + CLOSE + "va-* rules, renamed) wrapped\n"
        "   in a .filltable root. --- " + CLOSE + "\n"
        ".filltable { margin: 1rem 0; }\n"
    )
    assert list(_offenders(broken)), "detector missed the shape it was built for"

    repaired = broken.replace("ta-*" + CLOSE + "va-*", "ta-* / va-*")
    assert not list(_offenders(repaired)), "detector fires on the repaired form"
