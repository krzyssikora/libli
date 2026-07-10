import re
from pathlib import Path

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
