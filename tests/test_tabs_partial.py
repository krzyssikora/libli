import re
from pathlib import Path

import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from courses.templatetags.courses_manage_extras import element_summary
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"
SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
MATH_JS = ROOT / "courses/static/courses/js/math.js"


def _unit():
    return make_course_with_unit()[1]


def _strip_tab_ids(html):
    """Tab ids are minted randomly per element, so two renders never match literally."""
    return re.sub(r"t[0-9a-f]{6}", "TID", html)


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
    # Keep the original split token AND the [1:] -- dropping either would admit the
    # stylesheet's pre-@media-print prefix as a candidate chunk.
    for chunk in css.split("@media print {")[1:]:
        if ".el--tabs" in chunk[:1200]:
            # Clip at the media block's closing brace, NOT at a character count: past
            # that brace the chunk is ordinary SCREEN css, and a fixed window would let
            # the carousel's screen rules satisfy a "the print block contains ..."
            # assertion -- a silent green with no print reset at all. Precedent:
            # courses/tests/test_reveal_scope_agreement.py::_print_block.
            m = re.search(r"(.*?)\n\}", chunk, re.S)
            assert m, "could not find the closing brace of the .el--tabs print block"
            return m.group(1)
    raise AssertionError("no @media print block found for .el--tabs")


def _screen_label_rule():
    """The rule that hides the per-panel labels on screen once JS enhances.
    Matched by [data-display="tabs"] + .tabs__panel-label rather than by the old
    ".tabs--js .tabs__panel-label" substring: the rule now takes an explicit child
    chain (so it cannot reach a carousel nested inside a tabs panel), which the old
    matcher could never find."""
    css = CSS.read_text(encoding="utf-8")
    line = next(
        ln
        for ln in css.splitlines()
        if '[data-display="tabs"]' in ln and ".tabs__panel-label" in ln
    )
    decls = line.split("{")[1].split("}")[0]
    props = {p.split(":")[0].strip() for p in decls.split(";") if p.strip()}
    assert props, (
        "the screen label rule must stay on ONE physical line, declarations included"
    )
    assert {"position", "clip"} <= props, f"unexpected screen label rule: {props}"
    return props


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


@pytest.mark.django_db
def test_render_emits_both_data_attributes():
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel", "label_pos": "below"}
    )
    Element.objects.create(unit=_unit(), content_object=obj)
    html = obj.render()
    assert 'data-display="carousel"' in html
    assert 'data-label-pos="below"' in html


@pytest.mark.django_db
def test_the_stage_wrapper_is_present_in_both_modes():
    for display in ("tabs", "carousel"):
        obj = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": display}
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        assert 'class="tabs__stage"' in obj.render()


@pytest.mark.django_db
def test_markup_is_identical_between_modes_apart_from_the_two_attributes():
    """This is what pins the no-JS and print fallback: the server emits ONE layout."""
    rendered = {}
    for display in ("tabs", "carousel"):
        obj = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": display}
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        rendered[display] = obj.render().replace(f'data-display="{display}"', "DISPLAY")
    # tab ids are random per element; normalise them before comparing
    assert _strip_tab_ids(rendered["tabs"]) == _strip_tab_ids(rendered["carousel"])


@pytest.mark.django_db
def test_the_caption_node_is_present_in_all_three_label_positions():
    """Hidden by CSS, never omitted -- dropping it would strip the title from print."""
    for pos in ("above", "below", "hidden"):
        obj = TabsElement.objects.create(
            data={
                **TabsElement.default_data(),
                "display": "carousel",
                "label_pos": pos,
            }
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        assert obj.render().count("data-tab-label") == 2


@pytest.mark.django_db
def test_render_calls_the_destructive_normalizer_exactly_once(monkeypatch):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=_unit(), content_object=obj)
    calls = []
    original = TabsElement.normalize_data
    monkeypatch.setattr(
        TabsElement,
        "normalize_data",
        staticmethod(lambda d: (calls.append(1), original(d))[1]),
    )
    obj.render()
    assert len(calls) == 1, (
        "render must read the enums via display_settings(), not normalize_data"
    )


@pytest.mark.django_db
def test_a_nested_instance_emits_its_own_stage_and_sections():
    """Both directions. The failure modes are CSS-selector defects (a descendant
    selector blanking the inner element; the outer sr-only rule clipping an inner
    carousel's captions), so the structural precondition -- two independent
    stage>section chains -- is worth pinning cheaply."""
    for outer_display, inner_display in (
        ("carousel", "tabs"),
        ("tabs", "carousel"),
        ("carousel", "carousel"),  # the spec names this one explicitly
    ):
        unit = _unit()
        outer = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": outer_display}
        )
        outer_join = Element.objects.create(unit=unit, content_object=outer)
        tab_id = outer.normalized_data["tabs"][0]["id"]
        inner = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": inner_display}
        )
        Element.objects.create(
            unit=unit, content_object=inner, parent=outer_join, tab_id=tab_id
        )
        html = outer.render(element=outer_join)
        assert html.count('class="tabs__stage"') == 2  # one per instance
        assert html.count("data-tab-panel") == 4  # 2 sections x 2 instances
        # Count both attributes rather than asserting == 1 on the inner value: the
        # carousel-in-carousel case has outer and inner sharing it.
        expected = 2 if outer_display == inner_display else 1
        assert html.count(f'data-display="{inner_display}"') == expected


def test_carousel_print_reset_is_present_and_fully_important():
    """Printing a carousel must not silently lose every slide but the current one.
    A human running print preview is not a defence against a later tidy-up."""
    block = _print_block()
    assert '[data-display="carousel"]' in block

    # WHICH properties, not just "all of them carry !important": a section reset written
    # as `{ position: static !important; }` alone passes an important-only check, while
    # the screen rule's `opacity: 0` still applies in print and the carousel loses every
    # slide but the current one -- the exact content loss this test exists to prevent.
    def _props(subject):
        line = next(
            ln
            for ln in block.splitlines()
            if '[data-display="carousel"]' in ln
            and ln.split("{")[0].rstrip().endswith(subject)
        )
        decls = line.split("{")[1].split("}")[0]
        return {d.split(":")[0].strip() for d in decls.split(";") if d.strip()}

    assert {"position", "min-height"} <= _props(".tabs__stage")
    assert {"position", "opacity", "display"} <= _props(".tabs__section")
    for line in block.splitlines():
        if '[data-display="carousel"]' not in line or "{" not in line:
            continue  # a comment mentioning the attribute would IndexError on the split
        decls = line.split("{")[1].split("}")[0]
        for decl in [d for d in decls.split(";") if d.strip()]:
            assert "!important" in decl, (
                f"print reset declaration lacks !important: {decl.strip()}"
            )


def test_every_slide_hiding_rule_carries_the_carousel_gate():
    """The gate must be .tabs--carousel (added only after a successful show(0)), never
    .tabs--js (added before the branch is even entered) -- otherwise a throw part-way
    through init leaves every slide at opacity 0 with nothing to re-show it: blank.

    Keyed on the selector SUBJECT plus the opacity/pointer-events pair unique to the
    slide rule. A substring predicate would flag the legitimate tabs-mode label rule,
    which also contains ".tabs__section" and "position: absolute" on one line."""
    css = CSS.read_text(encoding="utf-8")
    matched = False
    for line in css.splitlines():
        if "{" not in line:
            continue
        selector, decls = line.split("{", 1)
        if not selector.rstrip().endswith(".tabs__section"):
            continue
        if "opacity: 0" in decls and "pointer-events: none" in decls:
            matched = True
            assert ".tabs--carousel" in selector, (
                f"slide rule missing the gate: {selector.strip()}"
            )
    assert matched, "no carousel slide rule found at all"


def test_the_hidden_caption_rule_declares_only_properties_print_resets():
    """label_pos:"hidden" is screen-only -- the unscoped !important print reveal must
    undo it. That reveal resets exactly seven properties, so a modern sr-only idiom
    (clip-path: inset(50%), or margin/border/padding) would NOT be undone and a printed
    carousel would silently lose every caption."""
    css = CSS.read_text(encoding="utf-8")
    line = next(
        ln
        for ln in css.splitlines()
        if '[data-label-pos="hidden"]' in ln and ".tabs__panel-label" in ln
    )
    decls = line.split("{")[1].split("}")[0]
    props = {p.split(":")[0].strip() for p in decls.split(";") if p.strip()}
    assert props, "the hidden-caption rule must stay on ONE physical line"
    seven = {
        "position",
        "width",
        "height",
        "clip",
        "overflow",
        "white-space",
        "display",
    }
    assert props <= seven, f"not undone by the print reveal: {props - seven}"


def test_carousel_rules_use_child_combinators():
    """A descendant selector would match a NESTED tabs element's sections and render it
    completely blank (the inner instance hides panels with `hidden`, never adds
    .is-active to a section, so nothing restores opacity)."""
    css = CSS.read_text(encoding="utf-8")
    matched = False
    nav = (
        ".tabs__cbar",
        ".tabs__cprev",
        ".tabs__cnext",
        ".tabs__dots",
        ".tabs__dot",
        ".tabs__status",
    )
    subjects = (".tabs__section", ".tabs__panel", ".tabs__panel-label", ".tabs__stage")
    for line in css.splitlines():
        if "{" not in line:
            continue
        selector = line.split("{")[0]
        # Mode-scoped rules only, by EITHER token -- keying solely on .tabs--carousel
        # would skip the four rules the spec identifies as the hazard: the two
        # tabs-mode rules scoped by [data-display="tabs"], and the two attribute-only
        # carousel rules (caption typography, panel spacing). Any of them can regress
        # to a descendant selector and blank a nested carousel's captions or
        # double-pad its panels.
        if ".tabs--carousel" not in selector and "[data-display=" not in selector:
            continue
        if any(n in selector for n in nav):
            continue  # nav styling may stay descendant-scoped; it cannot blank a slide
        if not any(x in selector for x in subjects):
            continue
        # Pin the FULL chain per subject. `"> .tabs__stage" in selector` alone passes
        # for `> .tabs__stage .tabs__section` -- a descendant selector that still
        # reaches a NESTED instance's sections and blanks them, i.e. exactly the hazard.
        if ".tabs__panel-label" in selector:
            need = "> .tabs__stage > .tabs__section > .tabs__panel-label"
        elif ".tabs__panel" in selector:
            need = "> .tabs__stage > .tabs__section > .tabs__panel"
        elif ".tabs__section" in selector:
            need = "> .tabs__stage > .tabs__section"
        else:
            need = "> .tabs__stage"
        matched = True
        assert need in selector, f"missing child chain ({need}): {selector.strip()}"
    assert matched, "no mode-scoped slide/caption rule found at all"


@pytest.mark.django_db
def test_a_carousel_summary_names_the_mode():
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel"}
    )
    assert "carousel" in element_summary(obj).lower()


@pytest.mark.django_db
def test_a_tabs_summary_is_byte_identical_to_todays():
    """The change must not regress every existing element's row."""
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    assert element_summary(obj) == "2 tabs"


@pytest.mark.django_db
def test_the_polish_plural_still_resolves_and_the_suffix_translates():
    """This edit wraps the ONE expression carrying Polish's three plural forms. The
    suffix must not break them, and must itself translate."""
    from django.utils import translation

    with translation.override("pl"):
        for n in (1, 2, 5):
            tabs = [{"id": f"t{i:06x}", "label": f"T{i}"} for i in range(n)]
            obj = TabsElement.objects.create(data={"tabs": tabs})
            assert str(n) in element_summary(obj)
        carousel = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": "carousel"}
        )
        assert "karuzela" in element_summary(carousel)
