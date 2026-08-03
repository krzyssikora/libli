import re
from pathlib import Path

import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"
SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
MATH_JS = ROOT / "courses/static/courses/js/math.js"


def test_empty_tabs_still_render_a_label_and_panel_each():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=obj)
    html = obj.render()
    assert html.count("data-tab-panel") == 2
    assert html.count("data-tab-label") == 2


def test_child_renders_inside_its_panel():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][1]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>nested</p>"),
        parent=join,
        tab_id=tab,
    )
    html = obj.render()
    panel = html.split(f'data-tab-id="{tab}"')[1]
    assert "nested" in panel


def test_a_label_carrying_markup_renders_escaped():
    """THE barrier that lets `sanitize_label` keep a label verbatim (so LaTeX with a
    `<` survives): the template escapes it. Mutant: mark the label `|safe` in
    tabselement.html and this goes red."""
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "<img src=x onerror=alert(1)>"},
                {"id": "t000002", "label": r"\(a<b\)"},
            ]
        }
    )
    Element.objects.create(unit=unit, content_object=obj)
    html = obj.render()
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    # The LaTeX survives the round trip, escaped rather than eaten.
    assert r"\(a&lt;b\)" in html


def test_root_carries_the_join_row_pk_for_dom_id_namespacing():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    assert f'data-tabs-eid="{join.pk}"' in obj.render(element=join)


def test_courses_css_defines_the_tabs_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".el--tabs",
        ".tabs__strip",
        ".tabs__panel",
        ".tabs__panel-label",
        ".tabs__tab",
        ".tabs__scroller",
        ".tabs__chev",
    ]:
        assert cls in css, f"missing tabs class: {cls}"


def _print_block():
    """The @media print body for .el--tabs. Split on the literal brace so a prose
    comment merely mentioning "@media print" cannot masquerade as the rule. The
    stylesheet now carries more than one @media print block (the crumb breadcrumbs'
    own block was inserted earlier in the file), so pick the chunk that actually
    contains the tabs selectors rather than just the first split."""
    css = CSS.read_text(encoding="utf-8")
    for chunk in css.split("@media print {")[1:]:
        if ".el--tabs" in chunk[:1200]:
            return chunk[:1200]
    raise AssertionError("no @media print block found for .el--tabs")


def _screen_label_rule():
    """The rule that hides the per-panel labels on screen once JS enhances."""
    css = CSS.read_text(encoding="utf-8")
    line = next(ln for ln in css.splitlines() if ".tabs--js .tabs__panel-label" in ln)
    return {
        p.split(":")[0].strip()
        for p in line.split("{")[1].split("}")[0].split(";")
        if ":" in p
    }


def test_print_stylesheet_reveals_hidden_panels_and_labels():
    """Print happens AFTER enhancement, so both reveals need !important or the
    screen-hiding rules win and the printed lesson silently loses content."""
    block = _print_block()
    assert '[role="tabpanel"][hidden]' in block
    assert "display: block !important" in block
    assert ".tabs__panel-label" in block
    assert block.count("!important") >= 3


def test_print_label_reveal_resets_every_property_the_screen_rule_sets():
    """A half-reset is the silent failure: leave white-space:nowrap and overflow:hidden
    standing, and a long tab label clips in print despite display:block !important."""
    block = _print_block()
    label_rule = next(
        ln
        for ln in block.splitlines()
        if ".tabs__panel-label" in ln and "!important" in ln
    )
    for prop in _screen_label_rule():
        assert f"{prop}:" in label_rule, (
            f"print label reveal never resets '{prop}' (set by the screen sr-only rule)"
        )


def test_sprite_defines_el_tabs_at_16x16():
    sprite = SPRITE.read_text(encoding="utf-8")
    m = re.search(r'<symbol id="el-tabs" viewBox="([^"]+)"', sprite)
    assert m, "sprite is missing an #el-tabs symbol"
    assert m.group(1) == "0 0 16 16"  # match every sibling el-* symbol
    symbol = sprite.split('id="el-tabs"')[1].split("</symbol>")[0]
    assert 'fill="currentColor"' in symbol  # fill not stroke (table slice got wrong)


def test_math_js_scopes_inline_rendering_to_tabs():
    assert ".el--tabs" in MATH_JS.read_text(encoding="utf-8")
