"""Drift guard (spec D5): every client-side practice-state writer announces a STORED
save with `libli:state-saved`, and only after the response says something is stored.

PLACEMENT, not presence: a bare `"libli:state-saved" in src` passes on a dispatch in a
dead branch or above the fetch. Each writer's dispatch is matched together with its
guard, and must come after that file's fetch(.

BLIND SPOTS, stated honestly: a widget posting to element_state_save through a
differently named attribute, a template-injected URL, or a new server route writing
state from a different endpoint is not caught. The dispatch's placement INSIDE the
correct callback is approximated by "after fetch( + adjacent to its guard". For
question.js, a VERBATIM move of the guarded dispatch below `return r.text()` is caught
here; a relocation that rewrites the guard (e.g. threading a flag into the second
.then) is caught ONLY by the inline-choice e2e in
tests/test_e2e_start_fresh_activation.py. A tripwire, not a proof.
"""

import re
from pathlib import Path

from courses.views import STATE_SAVED_HEADER

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "courses" / "static" / "courses" / "js"
EVENT = "libli:state-saved"
DISPATCH = re.escape(f'document.dispatchEvent(new CustomEvent("{EVENT}"))')


def _strip_js_comments(source):
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", source)


def _src(name):
    src = _strip_js_comments((JS / name).read_text(encoding="utf-8"))
    assert len(src) > 200, f"comment stripping ate {name}"
    return src


# The guarded dispatch, per write site: the guard must sit IMMEDIATELY before the
# dispatch, so deleting the guard (unconditional dispatch) fails the match.
ECHO_GUARD = (
    r"if \(data && data\.state && "
    r"Object\.keys\(data\.state\)\.length\) \{\s*"
)
GUARDED = {
    "state.js": ECHO_GUARD + DISPATCH,
    "reveal.js": ECHO_GUARD + DISPATCH,
    "markdone.js": r"if \(Object\.keys\(blob\)\.length\) \{\s*" + DISPATCH,
    "question.js": r"if \(r\.ok && r\.headers\.get\("
    + re.escape(f'"{STATE_SAVED_HEADER}"')
    + r"\)\) \{\s*"
    + DISPATCH,
}

STATE_URL_SHAPES = re.compile(
    r"dataset\.stateUrl"
    r'|getAttribute\("data-state-url"\)'
    r'|getAttribute\("data-markdone-url"\)'
)


def test_each_writer_dispatches_exactly_once_behind_its_guard_after_fetch():
    for name, pattern in GUARDED.items():
        src = _src(name)
        assert src.count(f'new CustomEvent("{EVENT}"') == 1, name
        m = re.search(pattern, src)
        assert m, f"{name}: guarded dispatch not found (guard removed or renamed?)"
        fetch_at = src.find("fetch(")
        assert fetch_at != -1, name
        assert m.start() > fetch_at, f"{name}: dispatch sits above fetch(("


def test_question_js_dispatches_before_returning_the_text():
    src = _src("question.js")
    m = re.search(GUARDED["question.js"], src)
    assert m
    assert m.start() < src.find("return r.text()"), (
        "dispatch must be in the FIRST .then"
    )


def test_writer_set_is_exactly_the_known_files():
    found = {
        p.name
        for p in JS.glob("*.js")
        if STATE_URL_SHAPES.search(_strip_js_comments(p.read_text(encoding="utf-8")))
    }
    assert found == {"state.js", "reveal.js", "markdone.js"}, found
    # question.js writes through check_answer's form.action, so no URL shape names it:
    # pin it to that write shape instead (its dispatch is pinned in GUARDED above).
    assert "fetch(form.action" in _src("question.js")


def test_listener_listens_for_the_same_name_and_restores_the_contract():
    src = _src("reset_control.js")
    assert f'addEventListener("{EVENT}"' in src
    assert '[data-reset-control][aria-disabled="true"]' in src
    assert 'getAttribute("data-reset-href")' in src
    for attr in ("aria-disabled", "role", "title"):
        assert f'removeAttribute("{attr}")' in src, attr


def test_reset_control_script_only_on_lesson_page_and_before_the_writers():
    lesson = (ROOT / "templates/courses/lesson_unit.html").read_text(encoding="utf-8")
    tag = "{% static 'courses/js/reset_control.js' %}"
    at = lesson.find(tag)
    assert at != -1
    # gated on the same condition as the control itself
    line_start = lesson.rfind("\n", 0, at)
    assert "{% if has_stateful_elements %}" in lesson[line_start:at]
    # Belt-and-braces, not a hard correctness need: every dispatch fires in a fetch
    # .then, i.e. after all deferred scripts in practice. Listener-first (spec §5)
    # closes the theoretical gap of a save resolving between two deferred scripts.
    for writer in ("question.js", "state.js", "reveal.js", "markdone.js"):
        assert at < lesson.find(f"courses/js/{writer}"), writer
    results = (ROOT / "templates/courses/quiz_results.html").read_text(encoding="utf-8")
    assert "reset_control.js" not in results
