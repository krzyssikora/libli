import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
EDITOR_HTML = ROOT / "templates/courses/manage/editor/editor.html"
BASE_SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
TABS_EDITOR_JS = ROOT / "courses/static/courses/js/tabs_editor.js"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"


# Symbols live in TWO files: `ed-*` (rich-text toolbar) in editor.html, `bi-*` (generic
# up/down/trash) in _icon_sprite.html. The tabs editor uses bi-* for reorder/delete, the
# same as _edit_gallery.html. Union both, or a valid bi-* ref reads as undefined.
def _sprite_symbols():
    text = EDITOR_HTML.read_text(encoding="utf-8") + BASE_SPRITE.read_text(
        encoding="utf-8"
    )
    return set(re.findall(r'<symbol id="([\w-]+)"', text))


def _render_form(instance):
    form = FORM_FOR_TYPE["tabs"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_tabs.html", {"form": form, "type_key": "tabs"}
    )


def test_new_tabs_form_renders_two_label_rows():
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert "data-tabs-editor" in html
    assert html.count("data-tab-row") == 2


def test_each_row_round_trips_its_id_as_a_hidden_field():
    """Ids in, ids out. Without this the delete diff sees every old id as removed
    and destroys every child, and save() mints fresh ids for the survivors."""
    el = TabsElement(
        data={
            "tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]
        }
    )
    html = _render_form(el)
    assert 'data-tab-id="taaaaaa"' in html
    assert 'data-tab-id="tbbbbbb"' in html


def test_element_row_renders_nested_children_indented():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child body"),
        parent=join,
        tab_id=tab,
    )
    # depth/max_nest_depth are INTEGERS and both are required: the add-menu include
    # is guarded by `depth < max_nest_depth`, and a missing (or string) value makes
    # smartif evaluate False, dropping the nested menu this test asserts on.
    html = render_to_string(
        "courses/manage/editor/_element_row.html",
        {
            "el": join,
            "obj": obj,
            "unit": unit,
            "open_form_pk": "",
            "depth": 1,
            "max_nest_depth": 4,
        },
    )
    assert "element-list--nested" in html
    assert "child body" in html  # the child's own row
    assert f'data-parent="{join.pk}"' in html  # nested add menu carries scope
    assert f'data-tab="{tab}"' in html


def test_nested_add_menu_offers_only_nestable_types():
    """Depth-3 slice: a nested menu at depth 1 now DOES offer the Tabs card -- a
    container added there lands at depth 2, which builder clause 4 accepts. The
    question/structure cards stay blocked (they are not nestable at any depth).

    depth/max_nest_depth are INTEGERS: `depth="1"` would bind a string and smartif
    swallows the `str < int` TypeError, so every guard would silently read False.
    """
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {
            "nested": True,
            "parent": join.pk,
            "tab": obj.data["tabs"][0]["id"],
            "depth": 1,
            "max_nest_depth": 4,
        },
    )
    for blocked in ["slidebreak", "extendedresponsequestion"]:
        assert blocked not in html
    assert 'data-add-type="tabs"' in html  # INVERTED: legal at depth 1
    assert 'data-add-type="text"' in html
    assert 'data-add-type="gallery"' in html
    # INVERTED by the question widening. The context above passes no `unit_is_quiz`,
    # which is falsy, so the `{% if nested and not unit_is_quiz %}` group renders.
    assert 'data-add-type="choice-single"' in html


def test_nested_add_menu_hides_the_questions_group_in_a_quiz():
    """The nested Questions group is gated `nested and not unit_is_quiz`. Rendering
    the partial twice -- once without `unit_is_quiz` (above) and once with it True --
    is what makes the guard's SECOND half falsifiable; dropping `and not
    unit_is_quiz` leaves the sibling test green.

    depth/max_nest_depth are INTEGERS: `depth="1"` would bind a string and smartif
    swallows the `str < int` TypeError, so every guard would silently read False.
    """
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {
            "nested": True,
            "unit_is_quiz": True,
            "parent": join.pk,
            "tab": obj.data["tabs"][0]["id"],
            "depth": 1,
            "max_nest_depth": 4,
        },
    )
    # Bare substrings, so each also covers the card's `#el-*` icon href.
    for blocked in [
        "choice-single",
        "choice-multi",
        "shorttextquestion",
        "shortnumericquestion",
        "fillblankquestion",
    ]:
        assert blocked not in html, blocked
    assert 'data-add-type="text"' in html  # the rest of the menu is untouched


def test_tabs_editor_icons_resolve_to_sprite_symbols():
    """Icon-only buttons fail silently (blank) on a typo'd href, so pin every ref."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    refs = set(re.findall(r'use href="#((?:ed|bi)-[\w-]+)"', html))
    assert refs, "expected the tabs editor to use sprite icons, not glyphs"
    assert refs <= _sprite_symbols(), f"undefined symbols: {refs - _sprite_symbols()}"


def test_tabs_editor_js_icon_refs_resolve_too():
    used = set(
        re.findall(r'"((?:ed|bi)-[\w-]+)"', TABS_EDITOR_JS.read_text(encoding="utf-8"))
    )
    assert used <= _sprite_symbols(), f"undefined symbols: {used - _sprite_symbols()}"


def test_served_tabs_form_carries_the_bounds_the_js_reads(client):
    """tabs_editor.js reads data-min-tabs/data-max-tabs to disable add/remove at the
    bounds. Rendering the partial directly leaves them blank and every partial test
    still passes, so assert them on the SERVED form, where the wiring actually lives."""
    from django.urls import reverse

    from tests.factories import make_login

    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    html = resp.content.decode()
    assert 'data-min-tabs="2"' in html
    assert 'data-max-tabs="10"' in html
    assert 'maxlength="80"' in html


def test_editor_css_styles_every_tabs_editor_class():
    """The table slice shipped unstyled, permanently-visible handles because
    table_editor.js drifted from editor.css. Pin the same contract here.

    tabs_editor.js builds a new row by CLONING an existing one rather than assigning
    className, so scanning the JS alone matches nothing and the guard would pass
    vacuously. The classes live in the server-rendered partial -- scan that too.
    """
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    partial = (ROOT / "templates/courses/manage/editor/_edit_tabs.html").read_text(
        encoding="utf-8"
    )
    css = EDITOR_CSS.read_text(encoding="utf-8")

    emitted = set(re.findall(r'className = "(tabs-editor__[\w-]+)"', js))
    for attr in re.findall(r'class="([^"]*)"', partial):
        emitted.update(c for c in attr.split() if c.startswith("tabs-editor__"))

    assert emitted, (
        "expected tabs-editor__* classes in tabs_editor.js or _edit_tabs.html"
    )
    for cls in sorted(emitted):
        assert f".{cls}" in css, f"editor.css never styles .{cls}"


def _served_tabs_form(client):
    """The tabs editor partial as the server renders it for a NEW element -- so
    form.editor_display is "tabs" and the label-position row is expected hidden.
    Assert on the SERVED form, not a hand-instantiated one: the wiring lives in the
    response. Lifted from test_served_tabs_form_carries_the_bounds_the_js_reads."""
    from django.urls import reverse

    from tests.factories import make_login

    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    return resp.content.decode()


def test_tabs_editor_renders_both_setting_selects(client):
    html = _served_tabs_form(client)
    assert "data-tab-display" in html
    assert "data-tab-label-pos" in html
    # No name= : the hidden name="data" field is the sole authoritative input.
    assert 'name="display"' not in html
    assert 'name="label_pos"' not in html


def test_every_choice_label_renders_as_non_empty_option_text(client):
    """Has teeth: goes RED if someone reintroduces a hand-written label map that
    drifts from DISPLAY_CHOICES. (Asserting DISPLAYS == the tuple's values would be
    tautological -- it is derived from it one line below.)"""
    html = _served_tabs_form(client)
    # Assert the full <option> pattern, NOT a bare f">{label}<": the served fragment
    # also carries `<p class="editor-form__type">Tabs</p>` from _host_form.html
    # (editor_title == "Tabs"), so a bare-substring check for the "Tabs" label passes
    # even with no <option> at all. The recorded bare-substring trap, in person.
    for value, text in TabsElement.DISPLAY_CHOICES + TabsElement.LABEL_POS_CHOICES:
        assert f'value="{value}"' in html and f">{text}</option>" in html, (
            f"missing option for {value!r}/{text!r}"
        )


def test_tabs_mode_renders_the_label_position_row_hidden_from_first_paint(client):
    """Server-rendered, not JS-only: a JS-only toggle means the row flashes visible
    until wire() runs, and this assertion would have nothing to assert."""
    html = _served_tabs_form(client)  # a fresh element defaults to display=tabs
    # AFTER the marker: the template emits
    # `data-tab-label-pos-row {% if %}hidden{% endif %}`, so looking at the text
    # before it would fail against a correct implementation.
    assert "hidden" in html.split("data-tab-label-pos-row", 1)[1][:80]


def test_editor_css_pairs_a_hidden_rule_for_every_flex_setting_row():
    """A [hidden] row that is display:flex stays visible -- the UA rule loses to any
    author `display` regardless of specificity. Same trap editor.css records for
    .view-toggle."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert ".tabs-editor__setting[hidden]" in css
    assert "display: none" in css.split(".tabs-editor__setting[hidden]")[1][:80]


def test_serialize_reads_both_select_elements():
    """The no-op re-save defect lives in serialize(). The e2e catches it in seconds of
    wall-clock; this catches a later refactor in milliseconds."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    start = js.index("function serialize")
    body = js[start : js.index("function refreshControlState")]
    assert "display:" in body and "label_pos:" in body
    assert "displaySel.value" in body and "labelPosSel.value" in body


def _decl_block(css, selector):
    """Slice the declaration block for an exact selector (see tests/test_tabs_css.py
    for why line matching is not sufficient)."""
    i = css.index("\n" + selector + " {")
    open_brace = css.index("{", i)
    return css[open_brace + 1 : css.index("}", open_brace)]


def test_the_counter_is_removed_from_layout_when_hidden():
    """`.tabs-editor__row` is `display: flex; gap: var(--space-2)`, so a third flex
    item contributes a SECOND gap even while empty -- every row would permanently
    lose that much input width, for every author, below the threshold, and with JS
    disabled. The base rule declares `display: inline-flex`, which beats the UA
    `[hidden] { display: none }` regardless of specificity, so the paired rule is
    load-bearing rather than belt-and-braces."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert ".el-editor--tabs .tabs-editor__count[hidden]" in css
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__count[hidden]")
    assert "display: none" in block


def test_the_counter_states_are_styled_and_at_cap_is_not_colour_alone():
    """A colour-only at-cap state is invisible to a colour-blind author. --danger is
    the token (a hard stop, not a caution); --text-tertiary is banned because it
    fails AA at body size."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    base = _decl_block(css, ".el-editor--tabs .tabs-editor__count")
    near = _decl_block(css, ".el-editor--tabs .tabs-editor__count.is-near")
    at_cap = _decl_block(css, ".el-editor--tabs .tabs-editor__count.is-at-cap")

    # The token caution is recorded AT BODY SIZE, so the size must be pinned or the
    # contrast claim is being judged against a different WCAG threshold.
    assert "font-size" in base, "counter size must be declared, not inherited"
    assert near.strip(), ".is-near carries no declarations"
    assert "--danger" in at_cap
    assert "font-weight" in at_cap, "at-cap must carry a non-colour signal too"
    assert "--text-tertiary" not in at_cap


def test_the_live_region_is_clip_based_never_display_none():
    """The region must stay in the a11y and text trees so aria-live announces it and
    Playwright can read it. display:none would make it a silently dead channel."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__status")
    assert "position: absolute" in block
    assert "clip:" in block
    assert "display: none" not in block


def test_the_label_input_has_a_non_zero_width_floor():
    """Adding a fourth fixed row item plus a second gap shrinks the label input at
    exactly the moment the author is typing a long label.

    Extract the VALUE and compare it. A plain `"min-width" in block` check stays
    green against the mutant, because `min-width: 0` is also a min-width declaration
    -- and so does the obvious-looking negative lookahead
    `re.search(r"min-width:\\s*(?!0\\b)", block)`: `\\s*` backtracks to zero
    characters, the lookahead is then evaluated at the SPACE rather than at the `0`,
    and it trivially succeeds. That form matches "min-width: 0;" and is completely
    inert. Verified by running it.
    """
    css = EDITOR_CSS.read_text(encoding="utf-8")
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__label")
    m = re.search(r"min-width:\s*([^;}]+)", block)
    assert m, "label input declares no min-width at all"
    assert m.group(1).strip() not in ("0", "0px"), (
        "label input has no non-zero min-width floor"
    )


def test_the_cap_message_rides_on_a_data_msg_attribute():
    """JS-built strings cannot call {% trans %}; tabs_editor.js reads them via
    label(root, key, fallback) off the [data-tabs-editor] root. Without the attribute
    the helper silently returns its English fallback forever."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert "data-msg-cap=" in html
    assert "{n}" in html and "{max}" in html


def test_each_row_carries_a_hidden_aria_hidden_counter():
    """Rendered empty and hidden: a server-rendered value is wrong the instant the
    author types, and `hidden` keeps the no-JS editor unchanged in layout too.
    aria-hidden because a bare "64/80" with no label is noise -- the live region is
    the announcement channel and it says what it means."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert html.count("data-tab-num") == 2
    assert html.count('class="tabs-editor__count"') == 2
    # Pin the WHOLE tag, in a fixed attribute order. Counting `hidden` or
    # `aria-hidden="true"` separately is not enough: `hidden` is the load-bearing
    # attribute (the no-JS layout and the "no permanent 0/80" argument both rest on
    # it) and a count of stray attributes elsewhere in the partial would mask its
    # removal. Keep Step 4's markup in exactly this order.
    span = '<span class="tabs-editor__count" data-tab-num aria-hidden="true" hidden>'
    assert html.count(span) == 2
    # The existing count assertion must not move.
    assert html.count("data-tab-row") == 2

    # POSITION, not just presence. The tag check above fixes the span's attributes and
    # their order but says nothing about where it sits: moving it after
    # .tabs-editor__ctl leaves every assertion above green, and the spec requires it
    # BETWEEN the input and the controls.
    first_row = html[: html.index("data-tab-row", html.index("data-tab-row") + 1)]
    assert (
        first_row.index("data-tab-label-input")
        < first_row.index("tabs-editor__count")
        < first_row.index("tabs-editor__ctl")
    )


def test_exactly_one_live_region_renders_outside_the_row_list():
    """One per EDITOR, not per row. A per-row region hidden below the threshold is
    inserted into the a11y tree already containing its text, which assistive tech
    generally does not announce -- dropping the announcement on exactly the case that
    matters most (one input event jumping straight to the cap).

    The placement check slices the list forward. Do NOT use
    `html.index("data-tab-cap") > html.rindex("</ol>")`: in the SERVED render
    (_served_tabs_form) the open form is emitted as the last <li> inside
    _editor_scope.html's own top-level <ol class="element-list">, whose </ol> follows
    data-tab-cap -- so that form goes RED against a correct implementation.
    """
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert html.count("data-tab-cap") == 1
    assert 'aria-live="polite"' in html
    assert 'class="tabs-editor__status"' in html

    start = html.index("data-tab-list")
    assert "data-tab-cap" not in html[start : html.index("</ol>", start)], (
        "the live region must sit outside [data-tab-list], not inside a row"
    )


def _slice(js, start_anchor, end_anchor):
    """Slice between two anchors, asserting each occurs exactly once first.

    Anchor uniqueness is not pedantry. The wire() tail is
    `refreshControlState(); syncLabelPosRow(); if (hidden.value === "") serialize();`
    -- but `refreshControlState();` occurs 3x in this file and `syncLabelPosRow();`
    2x, and both appear BEFORE the add handler. Choosing either as the tail marker
    inverts the add slice into a ValueError or an empty string, on which a
    "last index" comparison passes vacuously. Only `if (hidden.value === "")` is
    unique.
    """
    assert js.count(start_anchor) == 1, f"anchor not unique: {start_anchor}"
    assert js.count(end_anchor) == 1, f"anchor not unique: {end_anchor}"
    return js[js.index(start_anchor) : js.index(end_anchor)]


def test_refresh_count_is_the_last_statement_at_every_call_site():
    """The counter is an affordance, never a dependency -- true only if a throw
    inside it cannot abort the authoritative work. In wire()'s tail this is sharpest:
    on the ADD path `hidden.value` starts "", so a throw above
    `if (hidden.value === "") serialize();` would submit an EMPTY data field.
    """
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    tail = 'if (hidden.value === "")'

    slices = {
        "input handler": _slice(
            js, 'rows.addEventListener("input"', 'rows.addEventListener("click"'
        ),
        "add handler": _slice(js, 'addBtn.addEventListener("click"', tail),
        "init": _slice(js, tail, "function initTabsEditor"),
    }
    for name, body in slices.items():
        assert "refreshCount(" in body, f"{name}: no refreshCount call"
        assert body.rindex("refreshCount(") > body.rindex("serialize("), (
            f"{name}: refreshCount must come after serialize()"
        )
        assert "function refreshCount(" not in body, (
            f"{name}: the declaration must sit outside this slice, or the ordering "
            "assertion is satisfied vacuously by the declaration itself"
        )


def test_the_cap_phrase_substitutes_every_placeholder_occurrence():
    """String.replace with a string pattern replaces only the FIRST occurrence, and a
    translation may legitimately repeat a token. This static check is the only thing
    enforcing it: both catalogs contain each token exactly once, so a .replace chain
    produces an identical string and no behavioural assertion can tell the
    difference. Note tabs.js:275-276 uses the rejected form -- do not copy it."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    assert '.replace("{n}"' not in js
    assert '.replace("{max}"' not in js
    assert '.split("{n}")' in js and '.split("{max}")' in js


def test_the_js_fallback_matches_the_trans_msgid_byte_for_byte():
    """These two literals are written by DIFFERENT tasks with no shared memory, and
    the spec calls their identity load-bearing: when data-msg-cap is missing, label()
    falls back to the JS literal, so a stray en dash or a dropped space would make
    the degraded path render a different string from the normal one. Nothing else
    connects them."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    partial = (ROOT / "templates/courses/manage/editor/_edit_tabs.html").read_text(
        encoding="utf-8"
    )

    msgid = re.search(r"data-msg-cap=\"\{% trans '([^']+)' %\}\"", partial)
    fallback = re.search(r'label\(editor, "cap", "([^"]+)"\)', js)
    assert msgid, "no data-msg-cap {% trans %} in the partial"
    assert fallback, 'no label(editor, "cap", ...) fallback in the JS'
    assert msgid.group(1) == fallback.group(1), (
        f"msgid {msgid.group(1)!r} != JS fallback {fallback.group(1)!r}"
    )


def test_the_reorder_branches_only_clear_the_region():
    """Reorder RENUMBERS rows, so a phrase naming "Tab 2" would describe a different
    tab -- and worse, the stale text would suppress the next announcement via the
    change-guard. But the rows themselves move intact, so no refreshCount is needed
    or permitted here (the ordering test exempts this handler)."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    # End anchor is addBtn.addEventListener("click" -- NOT "if (addBtn)", which
    # occurs TWICE (`if (addBtn) addBtn.disabled = ...` in refreshControlState, and
    # `if (addBtn) {` before the add handler). _slice's uniqueness assertion would
    # fail on it against a correct build.
    click = _slice(
        js, 'rows.addEventListener("click"', 'addBtn.addEventListener("click"'
    )
    # Slice the two branches SEPARATELY. Slicing `up` to the end of the click handler
    # would include the down branch, so deleting the clear from only the up branch
    # would leave the down branch's call inside the slice and the mutant could not
    # go RED.
    up = click[click.index("[data-tab-up]") : click.index("[data-tab-down]")]
    down = click[click.index("[data-tab-down]") :]
    for name, branch in (("up", up), ("down", down)):
        assert "insertBefore" in branch, f"{name}: no insertBefore"
        assert "clearCapRegion()" in branch, f"{name}: region not cleared"
        assert "refreshCount(" not in branch, f"{name}: must not call refreshCount"


def test_the_cap_phrase_resolves_to_polish():
    """A .po-only change ships English to Polish users with every test green. This is
    the assertion that catches it -- and catches a fuzzy pre-fill left in place."""
    from django.utils import translation

    with translation.override("pl"):
        html = _render_form(TabsElement(data=TabsElement.default_data()))

    start = html.index("data-msg-cap=")
    value = html[start : html.index(">", start)]
    assert "limit reached" not in value, "data-msg-cap is still English under pl"
    assert "{n}" in value and "{max}" in value, (
        "both placeholders must survive translation as literal tokens"
    )
