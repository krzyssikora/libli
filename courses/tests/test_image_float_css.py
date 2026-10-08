import re
from pathlib import Path

from courses.sanitize import ALLOWED_TAGS

REPO = Path(__file__).resolve().parents[2]
RAW = (REPO / "courses/static/courses/css/courses.css").read_text(encoding="utf-8")
NOTES = (REPO / "notes/static/notes/css/notes.css").read_text(encoding="utf-8")


def _strip(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


CSS = _strip(RAW)
# The whole feature lives between two marker comments (Task 6 Step 3); slice on the
# RAW text, where the markers still exist, then strip comments.
_START = RAW.rindex("/*", 0, RAW.index('=== Image "Float right"'))  # whole header
BLOCK = _strip(RAW[_START : RAW.index('=== end Image "Float right" ===')])


def _rules(css):
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_no_container_queries():
    assert "container-type" not in CSS and "@container" not in CSS


def test_every_rule_but_the_clears_is_keyed_on_the_float_class():
    for sel, body in _rules(BLOCK):
        if body.strip() == "clear: right;":
            continue
        assert "el--image--float" in sel, sel


def test_quiz_selectors_carry_the_quiz_scope():
    for sel, _ in _rules(CSS):
        for part in sel.split(","):
            if "section[data-element-id]" in part:
                assert ".quiz .slide > section[data-element-id]" in part, part


def test_heading_clear_lists_every_allowed_heading():
    allowed = sorted(t for t in ALLOWED_TAGS if re.fullmatch(r"h[1-6]", t))
    m = re.search(r"\.el--text :is\(([^)]*)\)", CSS)
    assert sorted(x.strip() for x in m.group(1).split(",")) == allowed


def test_print_unfloat_class_list_matches_notes_print_rule():
    notes = re.search(r"\.block-notes__pop:not\(:has\(([^)]*)\)\)", NOTES).group(1)
    want = sorted(c.strip() for c in notes.split(","))
    # Per alternative list, not the union: a class dropped from ONE of the many
    # copies would still be in the set and leave a union check green.
    groups = re.findall(r":not\(:has\(([^()]*\.block-notes__pop [^()]*)\)\)", CSS)
    assert groups, "no print un-float list found"
    for g in groups:
        got = sorted(c.strip() for c in g.split(","))
        assert got == [f".block-notes__pop {c}" for c in want], g


def test_no_nested_has():
    for sel, _ in _rules(CSS):
        for m in re.finditer(r":has\(", sel):
            depth, i = 1, m.end()
            while depth:
                ch = sel[i]
                if sel.startswith(":has(", i):
                    raise AssertionError(f"nested :has() in {sel}")
                depth += ch == "("
                depth -= ch == ")"
                i += 1
