"""Several assertions here check a button is ABSENT and would stay green if the
tag emitted nothing at all. The pairing is what makes them non-vacuous: every
absence assertion but one sits in a test that ALSO asserts a button present
somewhere the rule allows. The mutant, named once for the file: make the tag
render nothing -> eight of the nine tests go RED, and only
test_no_paste_buttons_render_when_nothing_is_marked (the one absence-only test)
stays green.
"""

import re

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _mark(client, course, unit, element):
    unit.refresh_from_db()
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element.pk, "unit": unit.pk, "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _editor(client, course, unit):
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()


def _slot_section(body, marker):
    """The markup of ONE container slot: from its data-tab-id/data-column-id
    attribute to the end of its <details>.

    A fixed-width window does NOT work here. The paste tag is invoked AFTER the
    add-menu include on the same template line, and _add_menu.html renders ~8.7 kB
    (still several kB nested, where only the Questions group is hidden) -- so the
    paste form starts thousands of characters past the marker. A 1500-char slice
    would make every presence assertion fail against a correct implementation and,
    worse, every ABSENCE assertion pass regardless of what the tag emits.

    LIMITATION: this stops at the FIRST `</details>`, so it truncates early if
    anchored on a slot that itself holds a nested container. One fixture here DOES
    have such a slot -- the columns test nests a two-column element inside the
    outer tabs' first slot -- and stays safe only because it anchors on
    `data-column-id`, never on the enclosing `data-tab-id`. Never anchor on that
    outer slot; if you must, count opening tags instead of widening the window.
    """
    at = body.index(marker)
    end = body.index("</details>", at)
    return body[at:end]


def test_no_paste_buttons_render_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _tabs(unit)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste"' not in body


def test_the_top_level_slot_offers_its_buttons(client):
    """The key-shape failure is silent and closed -- a mismatched key makes EVERY
    paste button disappear, which reads as "the feature is broken" rather than as a
    bug in a key. This is the test that catches it."""
    course, unit = _seed(client)
    dest, _slots = _tabs(unit)
    subject = _text(unit, parent=dest, tab=_slots[0])
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste"' in body
    assert 'name="mode" value="move"' in body
    assert 'name="mode" value="copy"' in body


def test_the_marked_elements_own_slot_offers_copy_but_not_move(client):
    """Clause 5, rendered. A copy into your own slot is a meaningful sibling copy;
    a move there is "send myself to the end of my own group"."""
    course, unit = _seed(client)
    subject = _text(unit)  # top level, so the top-level slot is its own
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)
    top = body[body.index('class="addwrap"') :]

    assert 'value="copy"' in top
    # The top-level slot's own move button is gone; any move button still on the
    # page belongs to a different slot.
    assert 'value="move"' not in top[: top.index("</form>", top.index('value="copy"'))]


def test_a_slot_that_fails_the_rule_renders_no_buttons(client):
    """A slidebreak is non-nestable, so no container slot may take it -- but the
    top-level slot still may, which is what keeps this from being vacuous."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    sb = Element.objects.create(
        unit=unit, content_object=SlideBreakElement.objects.create()
    )
    _mark(client, course, unit, sb)

    body = _editor(client, course, unit)

    section = _slot_section(body, f'data-tab-id="{slots[0]}"')
    assert 'data-op="element-paste"' not in section
    assert 'data-op="element-paste"' in body  # the top-level slot still offers them


def test_a_columns_slot_gets_its_own_key_not_the_enclosing_tabs_one(client):
    """The `:132` condition binds `column`, NOT `tab`. Nested inside a tabs element
    the recursive include passes no `only`, so a copied `tab.id` silently names the
    enclosing TAB and matches nothing -- and the clip_active disjunct hides that
    until the render AFTER a paste."""
    course, unit = _seed(client)
    outer, oslots = _tabs(unit)
    cols_obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols = Element.objects.create(
        unit=unit, content_object=cols_obj, parent=outer, tab_id=oslots[0]
    )
    col_ids = [c["id"] for c in cols_obj.data["columns"]]
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    for cid in col_ids:
        section = _slot_section(body, f'data-column-id="{cid}"')
        assert 'data-op="element-paste"' in section, cid
    assert cols.pk


def test_a_spoiler_slot_offers_its_buttons(client):
    course, unit = _seed(client)
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    # Assert on a SPOILER-SPECIFIC marker, not merely on a paste form appearing
    # somewhere after "el-row__spoiler": that slice runs to the end of the document
    # and always contains the top-level slot's own form (rendered after the element
    # list), so a bare substring check passes even when the spoiler site emits
    # nothing -- which is exactly the key-shape defect this test exists to catch,
    # since that site passes `obj.SLOT_ID` rather than `tab.id`.
    assert f'name="tab" value="{SpoilerElement.SLOT_ID}"' in body
    at = body.index(f'name="tab" value="{SpoilerElement.SLOT_ID}"')
    form = body[body.rindex("<form", 0, at) : at]
    assert 'data-op="element-paste"' in form
    assert sp.pk


def test_a_callout_slot_offers_its_buttons(client):
    """#214 made Callout a container, so its slot is a fifth paste site. This is
    the test that catches that site being dropped from the template.

    Scoped to the callout ROW, not searched for globally: CalloutElement.SLOT_ID
    and SpoilerElement.SLOT_ID are the SAME constant (SINGLE_SLOT_ID == "only"),
    so a global search for `value="only"` would be satisfied by a spoiler's form
    and pass for the wrong container.
    """
    from courses.models import CalloutElement

    course, unit = _seed(client)
    callout = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    # Assert on the form's OWN scope fields rather than slicing the row. The
    # callout branch emits `<li class="empty-state">` inside its nested <ol>
    # BEFORE the add-menu/paste site, so a slice to the first `</li>` stops short
    # of the form entirely. The parent pk is unambiguous where the slot id is not.
    assert f'name="parent" value="{callout.pk}"' in body
    at = body.index(f'name="parent" value="{callout.pk}"')
    form = body[body.rindex("<form", 0, at) : body.index("</form>", at)]
    assert 'data-op="element-paste"' in form
    assert f'name="tab" value="{CalloutElement.SLOT_ID}"' in form


def test_a_padded_slot_renders_no_paste_button(client):
    """The enumerator's NON-destructive normalizer and the renderer's destructive
    one diverge for a tabs element with fewer than MIN_TABS stored tabs: the
    renderer pads with a freshly minted id that is not in the enumerated set. That
    fails CLOSED -- no button on the padding slot -- which is what this pins.

    The stored id must match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`) or save()
    replaces it and the test loses its anchor. The minted padding id is not known
    in advance, so it is read back out of the rendered DOM rather than guessed.
    """
    import re as _re

    course, unit = _seed(client)
    thin = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "A"}]})
    join = Element.objects.create(unit=unit, content_object=thin)
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    # Match the EDITOR's <details> only. `data-tab-id` is also emitted by the
    # preview pane (the `data-tab-id` attribute in `tabselement.html`), which
    # _editor_scope.html renders after the editor -- and because normalize_data
    # mints a fresh padding id on EVERY call, the preview's padding id differs
    # from the editor's. A bare attribute regex therefore harvests a phantom id
    # that has no <details> after it, and _slot_section's index() raises.
    rendered = _re.findall(r'<details class="tabs-rows" data-tab-id="([^"]+)"', body)
    assert "t000001" in rendered  # the stored slot survived
    minted = [t for t in rendered if t != "t000001"]
    assert minted, "the renderer must have padded to MIN_TABS"

    # The stored slot offers its buttons; every minted padding slot offers none.
    assert 'data-op="element-paste"' in _slot_section(body, 'data-tab-id="t000001"')
    for mid in minted:
        assert 'data-op="element-paste"' not in _slot_section(
            body, f'data-tab-id="{mid}"'
        ), mid
    assert join.pk


def test_the_form_carries_the_scope_and_a_csrf_token(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)
    at = body.index('data-op="element-paste"')
    form = body[at : at + 900]

    assert "csrfmiddlewaretoken" in form
    assert 'name="mode"' in form
    assert 'name="unit_token"' in form


def test_every_container_renders_open_while_a_mark_is_pending(client):
    """A legal target could otherwise hide inside a collapsed tab. This test lives
    in THIS task, not with the paste-button tests: the `{% elif clip_active %}`
    disjunct it depends on is added in Step 5 below, so at the end of the previous
    task only `forloop.first` is open and this would be RED for a correct
    implementation."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    _text(unit, parent=dest, tab=slots[1])
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    for sid in slots:
        marker = f'data-tab-id="{sid}"'
        tag = body[body.index(marker) : body.index(marker) + 200]
        assert " open" in tag, sid
        assert "data-force-open" in tag, sid


def test_every_row_offers_a_select_control(client):
    """The control lives in the shared partial, which all seven branches include,
    so one edit covers them all -- assert a NESTED row too, or a regression that
    drops the partial from one branch ships green."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    _text(unit, parent=dest, tab=slots[0], body="<p>nested</p>")

    body = _editor(client, course, unit)

    assert body.count('data-op="element-clip"') >= 2
    at = body.index('data-op="element-clip"')
    form = body[at : at + 700]
    assert "csrfmiddlewaretoken" in form
    assert 'name="action" value="select"' in form


def test_the_marked_row_carries_its_modifier_at_every_depth(client):
    """Seven edits, not one: the <li class="el-row..."> tag is written out
    separately in every branch of _element_row.html, and #214 added a seventh."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    nested = _text(unit, parent=dest, tab=slots[0], body="<p>nested</p>")

    _mark(client, course, unit, nested)
    body = _editor(client, course, unit)

    at = body.index(f'data-element="{nested.pk}"')
    opening = body[body.rindex("<li", 0, at) : at]
    assert "el-row--marked" in opening


def test_a_marked_container_row_carries_the_modifier_too(client):
    course, unit = _seed(client)
    dest, _slots = _tabs(unit)

    _mark(client, course, unit, dest)
    body = _editor(client, course, unit)

    at = body.index(f'data-element="{dest.pk}"')
    opening = body[body.rindex("<li", 0, at) : at]
    assert "el-row--marked" in opening


def test_a_marked_callout_row_carries_the_modifier(client):
    """The seventh `<li>` branch, added by #214. The other two modifier tests mark
    a plain text row and a tabs row, so without this one the callout branch can
    ship unmarked with the suite green.
    """
    from courses.models import CalloutElement

    course, unit = _seed(client)
    callout = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )

    _mark(client, course, unit, callout)
    body = _editor(client, course, unit)

    at = body.index(f'data-element="{callout.pk}"')
    opening = body[body.rindex("<li", 0, at) : at]
    assert "el-row--marked" in opening
    # The branch's own class must survive the edit -- pasting the plain branch's
    # markup here would delete it, and #214's styling depends on it.
    assert "el-row--callout" in opening


def test_the_banner_names_the_marked_element_inside_the_swapped_pane(client):
    """applyFragments replaces only the two [data-scope] panes, so a banner in
    editor.html's chrome would render once on page load and then never reflect a
    select, a cancel or a paste."""
    course, unit = _seed(client)
    subject = _text(unit)
    subject.title = "My favourite paragraph"
    subject.save(update_fields=["title"])

    resp = _mark(client, course, unit, subject)
    body = resp.content.decode()

    assert 'id="clip-banner"' in body
    # BRACKETED by the editor pane, not merely "after its opening tag": a banner
    # rendered inside [data-scope="preview"] would also satisfy a bare > test.
    assert body.index('data-scope="editor"') < body.index('id="clip-banner"')
    assert body.index('id="clip-banner"') < body.index('data-scope="preview"')
    assert "My favourite paragraph" in body
    assert 'data-op="element-clip"' in body
    assert 'value="cancel"' in body


def test_the_banner_falls_back_to_the_type_summary_when_the_title_is_empty(client):
    """Element.title is routinely empty, so a naive label renders `"" is selected`."""
    course, unit = _seed(client)
    subject = _text(unit, body="<p>Some prose here</p>")
    assert subject.title == ""

    resp = _mark(client, course, unit, subject)
    body = resp.content.decode()
    start = body.index("clip-banner__label")
    banner = body[start : start + 400]

    assert banner.strip() != ""
    assert "Some prose" in banner or "Text" in banner


def test_no_banner_renders_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'id="clip-banner"' not in body


# ── the per-row "paste before this element" button ─────────────────────────
# Marker: data-op="element-paste-before", distinct from the slot buttons'
# data-op="element-paste".


def _row_section(body, pk):
    """The markup of ONE element row: from its data-element attribute to the next
    row's.

    Same shape of limitation as _slot_section: a row holding NESTED rows would be
    truncated at its first child, so anchor only on leaf rows -- which every
    fixture below does.
    """
    at = body.index(f'data-element="{pk}"')
    nxt = body.find('data-element="', at + 1)
    return body[at:] if nxt == -1 else body[at:nxt]


def test_no_paste_before_button_renders_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _text(unit)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste-before"' not in body


def test_every_other_row_in_the_marked_elements_own_slot_offers_paste_before(client):
    """Clause 5 rendered the other way round: the marked element's OWN slot is
    exactly where a positional move is wanted, and exactly where the slot-level
    move button is (correctly) absent."""
    course, unit = _seed(client)
    first = _text(unit, body="<p>1</p>")
    second = _text(unit, body="<p>2</p>")
    subject = _text(unit, body="<p>s</p>")
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    for anchor in (first, second):
        section = _row_section(body, anchor.pk)
        assert 'data-op="element-paste-before"' in section
        assert f'name="before" value="{anchor.pk}"' in section


def test_the_marked_rows_own_paste_before_button_is_absent(client):
    """Pasting an element above itself is the service's 400. The row that carries
    the mark must not offer it in the first place."""
    course, unit = _seed(client)
    first = _text(unit, body="<p>1</p>")
    subject = _text(unit, body="<p>s</p>")
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste-before"' in _row_section(body, first.pk)
    assert 'data-op="element-paste-before"' not in _row_section(body, subject.pk)


def test_the_row_directly_below_the_mark_offers_no_paste_before(client):
    """Landing above your own next sibling leaves the order exactly as it is, so
    the button would spend a full re-render to change nothing."""
    course, unit = _seed(client)
    first = _text(unit, body="<p>1</p>")
    subject = _text(unit, body="<p>s</p>")
    below = _text(unit, body="<p>b</p>")
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste-before"' in _row_section(body, first.pk)
    assert 'data-op="element-paste-before"' not in _row_section(body, below.pk)


def test_a_non_nestable_mark_offers_no_paste_before_on_a_nested_row(client):
    """The derived slot faces the same rules the posted one does: a slidebreak may
    not be nested, so a row inside a tabs slot must not offer to take it -- while a
    top-level row still does, which is what keeps the absence non-vacuous."""
    course, unit = _seed(client)
    top = _text(unit, body="<p>1</p>")
    dest, slots = _tabs(unit)
    nested = _text(unit, parent=dest, tab=slots[0], body="<p>n</p>")
    sb = Element.objects.create(
        unit=unit, content_object=SlideBreakElement.objects.create()
    )
    _mark(client, course, unit, sb)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste-before"' in _row_section(body, top.pk)
    assert 'data-op="element-paste-before"' not in _row_section(body, nested.pk)


def test_the_editor_page_leaks_no_raw_template_comment(client):
    """Django's {# #} does NOT span lines: a comment written across two lines
    renders BOTH lines as literal text. Here that put "{# Only while a mark is
    pending..." into every element row's control bar, on every editor page, while
    all nine tests above stayed green -- they assert what IS in the markup and
    never that nothing extra is.

    Cheap and general on purpose: it guards the whole editor page, not this one
    template, because the next multi-line comment will be somewhere else."""
    course, unit = _seed(client)
    _text(unit)
    dest, slots = _tabs(unit)
    _text(unit, parent=dest, tab=slots[0])

    assert "{#" not in _editor(client, course, unit)


def _unit(course, title, unit_type="lesson", parent=None, kind="unit"):
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title
    )


def _banner(body):
    start = body.index('id="clip-banner"')
    return body[start : body.index('class="pane-body"', start)]


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


def test_the_destination_offers_copy_controls_and_no_move_controls(client):
    """D7. Paired with presence assertions, so an empty tag cannot pass it."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _tabs(y)
    _text(y)
    _mark(client, course, x, subject)

    body = _editor(client, course, y)

    assert "Copy before this element" in body
    assert 'value="copy"' in body
    assert "Move before this element" not in body
    assert "Move here" not in body
    for form in re.findall(
        r'<form[^>]*data-op="element-paste-before"[^>]*>.*?</form>', body, flags=re.S
    ):
        assert 'name="mode" value="copy"' in form


def test_the_source_rows_keep_move_before_only(client):
    """D4. The POSTED mode is asserted, not just the label: the label comes from
    `{% if mode == "copy" %}`, so a hard-coded hidden input would keep it.

    Mutant: hard-code `value="copy"` in _paste_before_button.html's mode input ->
    RED here; hard-code `value="move"` -> RED on the destination test above."""
    course, x = _seed(client)
    _unit(course, "Y")
    _text(x)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert "Move before this element" in body
    assert "Copy before this element" not in body
    forms = re.findall(
        r'<form[^>]*data-op="element-paste-before"[^>]*>.*?</form>', body, flags=re.S
    )
    assert forms  # the loop below cannot pass on zero forms
    for form in forms:
        assert 'name="mode" value="move"' in form


def test_the_destination_banner_links_back_to_the_source(client):
    course, x = _seed(client)
    x.title = "SourceUnitTitle"
    x.save()
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, y))
    # ONLY the "from" part: the unit list below it also links X with X's title,
    # so a whole-banner assertion would pass whatever the from-link points at.
    start = banner.index("clip-banner__from")
    from_part = banner[start : banner.index("<details", start)]

    assert f'href="{_editor_url(course, x)}"' in from_part
    assert "SourceUnitTitle" in from_part
    assert f'href="{_editor_url(course, y)}"' not in from_part


def test_the_source_banner_has_no_from_link(client):
    course, x = _seed(client)
    _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert "clip-banner__from" not in body


def test_the_unit_list_links_every_other_unit_and_not_the_current_one(client):
    """Mutant: render the current unit as a link too -> RED."""
    course, x = _seed(client)
    x.title = "CurrentUnit"
    x.save()
    y = _unit(course, "OtherUnit")
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, x))

    assert f'href="{_editor_url(course, y)}"' in banner
    assert f'href="{_editor_url(course, x)}"' not in banner
    assert 'aria-current="page"' in banner
    assert "CurrentUnit" in banner


def test_a_one_unit_course_renders_no_unit_list(client):
    """Mutant: drop the `{% if copy_units_available %}` guard -> RED."""
    course, x = _seed(client)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert 'id="clip-banner"' in body
    assert "clip-banner__units" not in body


def test_the_unit_list_handles_an_irregular_course(client):
    course, x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    under_part = _unit(course, "UnderPart", parent=part)
    _unit(course, "EmptySectionE", kind="section", unit_type="", parent=part)
    other_root = _unit(course, "OtherRoot")  # neither source nor current
    subject = _text(x)
    _mark(client, course, x, subject)
    y = _unit(course, "RootY")

    body = _editor(client, course, y)
    # The <details> part only: the "from" link above it also carries X's href.
    start = body.index("clip-banner__units")
    banner = body[start : body.index('class="pane-body"', start)]

    assert f'href="{_editor_url(course, other_root)}"' in banner  # root-level
    assert "EmptySectionE" not in banner  # a unit-less container is omitted
    # D13: the part is collapsed (no `open`) and its rows load on expand.
    assert '<details class="clip-banner__group" data-units-url=' in banner
    assert f'href="{_editor_url(course, under_part)}"' not in banner
    level = client.get(
        reverse("courses:manage_copy_units", kwargs={"slug": course.slug}),
        {"parent": part.pk},
    ).content.decode()
    assert f'href="{_editor_url(course, under_part)}"' in level


def test_the_path_to_the_current_unit_is_open_and_other_containers_are_not(client):
    """Mutant: render every container open ({% elif True %} in
    _copy_units_node.html) -> RED on the sibling assertions."""
    course, x = _seed(client)
    part = _unit(course, "PathPart", kind="part", unit_type="")
    chapter = _unit(course, "PathChapter", kind="chapter", unit_type="", parent=part)
    here = _unit(course, "HereUnit", parent=chapter)
    sibling = _unit(course, "SiblingPart", kind="part", unit_type="")
    hidden = _unit(course, "HiddenUnit", parent=sibling)
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, here))

    assert banner.count('<details class="clip-banner__group" open') == 2
    assert 'aria-current="page"' in banner and "HereUnit" in banner
    assert "SiblingPart" in banner  # its row is there, collapsed
    assert "HiddenUnit" not in banner
    assert f'href="{_editor_url(course, hidden)}"' not in banner


def test_nothing_fits_is_said_out_loud(client):
    """Mutant: drop the clip_nothing_fits paragraph -> RED."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    box = Element.objects.create(
        unit=x, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=x,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _mark(client, course, x, box)

    body = _editor(client, course, quiz)

    assert "Nothing can be pasted into this unit." in body
    assert 'data-op="element-paste"' not in body


def test_the_banner_is_a_div_between_the_pane_head_and_the_error_slot(client):
    """Asserted on a 422 render, so the error slot really exists to order against."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    dest = Element.objects.create(
        unit=quiz, content_object=CalloutElement.objects.create(kind="example")
    )
    subject = Element.objects.create(
        unit=quiz,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
    )
    _mark(client, course, quiz, subject)
    quiz.refresh_from_db()

    resp = client.post(  # a question into a quiz container: 422 question_in_quiz
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": dest.pk,
            "tab": CalloutElement.SLOT_ID,
            "mode": "move",
            "element": subject.pk,
            "unit": quiz.pk,
            "unit_token": quiz.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    body = resp.content.decode()

    assert '<div id="clip-banner" class="clip-banner">' in body
    head_end = body.index("pane-head__count")
    banner = body.index('id="clip-banner"')
    error = body.index('id="editor-error"')
    pane_body = body.index('class="pane-body"')
    assert head_end < banner < error < pane_body


def test_no_emoji_or_text_glyph_icons_remain_on_paste_controls(client):
    """D9. Mutant: restore 📋 in _paste_buttons.html -> RED."""
    course, x = _seed(client)
    _tabs(x)
    _text(x)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)
    scope = body[body.index('data-scope="editor"') : body.index('data-scope="preview"')]

    assert "📋" not in scope
    assert "⧉" not in scope
    assert '<use href="#ed-paste-move"/>' in scope  # slot move + move-before
    assert '<use href="#ed-paste-copy"/>' in scope  # slot copy + Duplicate
    for form in re.findall(
        r'<form[^>]*data-op="element-(?:paste|paste-before|duplicate)"[^>]*>.*?</form>',
        scope,
        flags=re.S,
    ):
        assert '<use href="#ed-paste-' in form
