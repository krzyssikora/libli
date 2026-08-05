import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TABS_JS = ROOT / "courses/static/courses/js/tabs.js"
GALLERY_JS = ROOT / "courses/static/courses/js/gallery.js"
EDITOR_JS = ROOT / "courses/static/courses/js/editor.js"
CSS = ROOT / "courses/static/courses/css/courses.css"
TEMPLATES = ROOT / "templates/courses"


def test_tabs_js_is_multi_instance_and_idempotent():
    js = TABS_JS.read_text(encoding="utf-8")
    assert "querySelectorAll" in js  # no module singleton
    assert "tabsReady" in js  # re-entry guard
    assert "isConnected" in js  # detached-container check


def test_tabs_js_namespaces_dom_ids_with_the_element_id():
    """A bare tab_id is unique only within one element; two tabs elements on one
    page may share one. Unnamespaced ids => duplicate DOM ids and cross-talk."""
    js = TABS_JS.read_text(encoding="utf-8")
    assert "tabsEid" in js or "data-tabs-eid" in js


def test_tabs_js_hides_panels_with_the_hidden_attribute_not_inline_display():
    js = TABS_JS.read_text(encoding="utf-8")
    assert "hidden" in js
    assert "style.display" not in js  # inline display:none would defeat @media print


def test_tabs_js_dispatches_the_reveal_event():
    assert "libli:reveal" in TABS_JS.read_text(encoding="utf-8")


def test_gallery_js_listens_for_reveal_and_remeasures():
    """Without this, a gallery in a non-default tab renders a collapsed frame the
    first time a student opens that tab -- and every other test still passes."""
    js = GALLERY_JS.read_text(encoding="utf-8")
    assert "libli:reveal" in js


def test_every_surface_that_renders_the_student_template_loads_tabs_js():
    for name in ["lesson_unit.html", "quiz_unit.html", "manage/editor/editor.html"]:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "courses/js/tabs.js" in html, f"{name} never loads tabs.js"


def test_editor_reinitialises_tabs_after_a_fragment_swap():
    js = EDITOR_JS.read_text(encoding="utf-8")
    assert "libliInitTabs" in js


def test_every_tabs_class_the_js_emits_is_styled():
    """table_editor.js once drifted from editor.css and shipped unstyled, permanently
    visible handles. Pin the contract for tabs.js too."""
    js = TABS_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js))
    assert emitted, "expected tabs.js to assign tabs__* classes"
    for cls in sorted(emitted):
        first = cls.split()[0]
        msg = f"courses.css never styles .{first} (emitted by tabs.js)"
        assert f".{first}" in css, msg


TABS_I18N_TEMPLATES = [  # the SAME three paths the loads-tabs-js test walks
    TEMPLATES / "lesson_unit.html",
    TEMPLATES / "quiz_unit.html",
    TEMPLATES / "manage/editor/editor.html",
]
CAROUSEL_I18N_KEYS = ["carouselNav", "prevSlide", "nextSlide", "goToSlide", "slidePos"]


@pytest.mark.parametrize("path", TABS_I18N_TEMPLATES)
def test_every_tabs_i18n_template_carries_every_carousel_key(path):
    """The literal is duplicated in three templates. A template missing a key does NOT
    fall back to English: tabs.js reads `window.TABS_I18N || {…}`, so the defaults
    object is used only when the global is ENTIRELY absent — a partial object yields
    undefined and throws on .replace."""
    html = path.read_text(encoding="utf-8")
    for key in CAROUSEL_I18N_KEYS:
        assert f"{key}:" in html, f"{path.name} is missing TABS_I18N.{key}"


def test_the_carousel_gate_class_is_added_after_show_zero():
    """The gate must go on LAST. .tabs--js is applied before the branch is entered, so
    gating on it would leave a half-initialised carousel blank rather than stacked."""
    js = TABS_JS.read_text(encoding="utf-8")
    assert 'classList.add("tabs--carousel")' in js
    assert js.index("show(0)") < js.index('classList.add("tabs--carousel")'), (
        "the gate class must be added after show(0) succeeds"
    )


def test_the_error_bail_clears_inert_aria_hidden_and_both_classes():
    """A class gate closes only the CSS half. inert/aria-hidden are JS-written
    ATTRIBUTES — no class can un-apply them, and the rest-init loop sets both on every
    section before show(0) runs.

    Sliced from `function bail`, NOT from the first `catch` token: bail() is DEFINED
    above the try/catch, so a catch-anchored slice would contain only `bail();` and
    none of the statements below — the assertion would fail on correct code."""
    js = TABS_JS.read_text(encoding="utf-8")
    # Bounded at `var nav = null` for the same reason the teardown assertion is: an
    # unbounded slice would be satisfied by any future helper appended below
    # initCarousel that happens to clear aria-hidden, letting an emptied bail() pass.
    body = js[js.index("function bail") : js.index("var nav = null")]
    assert 'removeAttribute("inert")' in body
    assert 'removeAttribute("aria-hidden")' in body
    assert 'classList.remove("tabs--js")' in body
    assert 'classList.remove("tabs--carousel")' in body
    assert "bail();" in js[js.index("} catch (") :]  # …and the catch actually calls it


def test_the_error_bail_tears_down_the_measurement_wiring():
    js = TABS_JS.read_text(encoding="utf-8")
    # BOUNDED slice, not to end-of-file: `scheduleMeasure` contains a
    # character-identical `teardownMeasure();` call, so an unbounded slice is satisfied
    # by that one alone and Step 6's mutant stays green. bail() ends where the nav
    # declarations begin.
    body = js[js.index("function bail") : js.index("var nav = null")]
    assert "teardownMeasure();" in body


def test_every_new_carousel_class_is_a_single_token_literal():
    r"""The drift guard is re.findall(r'className = "([\w-]*tabs__[\w-]+)"'). A space is
    not in [\w-], so a base+modifier literal matches NOTHING and both classes ship
    unguarded. Also: no classList.add for a styled base class."""
    js = TABS_JS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js))
    for cls in [
        "tabs__cbar",
        "tabs__cprev",
        "tabs__cnext",
        "tabs__dots",
        "tabs__dot",
        "tabs__status",
    ]:
        assert cls in emitted, f"{cls} is invisible to the style-drift guard"
