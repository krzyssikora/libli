import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Author-facing modules where `keep` is the correct rule (see spec section 2's
# export row, pinned by KEEP1). Excluding only views_manage.py would be green
# TODAY but would push the next implementer to pass viewer= in the exporter and
# silently drop drafts from archives.
AUTHOR_FACING = {
    "courses/views_manage.py",
    "courses/views_analytics.py",
    "courses/views_review.py",
    "courses/views_export.py",
    "courses/views_transfer.py",
    "courses/views_media.py",
}

CALL = re.compile(r"get_node_or_404\s*\(")


def test_every_student_facing_call_passes_viewer():
    """ACC6. viewer=None means "skip the check", so forgetting it fails
    SILENTLY. This is the only test covering call sites that do not exist
    yet, which is the entire point.

    Scans the WHOLE file text (not line-by-line): `viewer=request.user`
    pushes most of these calls past ruff's 88-column limit, so
    `ruff format` wraps them across several lines and a line-by-line scan
    would never see `viewer=` on the same line as the call. This is the
    scanner's own documented fallback for a call that spans lines.
    """
    offenders = []
    for path in list(ROOT.glob("*/views.py")) + list(ROOT.glob("*/views_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in AUTHOR_FACING:
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for match in CALL.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            # Match the CALL, not the bare name: the `from courses.access
            # import get_node_or_404` line must not count as a violation
            # (CALL already requires a following "(", which the import
            # statement never has). Still skip a commented-out call.
            if lines[lineno - 1].strip().startswith("#"):
                continue
            tail = text[match.start() :]
            depth, chunk = 0, []
            for ch in tail:
                chunk.append(ch)
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0 and ch == ")":
                    break
            if "viewer=" not in "".join(chunk):
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, (
        "These get_node_or_404 calls must pass viewer=request.user. If the "
        "file is an AUTHOR-facing surface (builder, export, analytics, "
        "review, media), add it to AUTHOR_FACING above instead:\n  "
        + "\n  ".join(offenders)
    )
