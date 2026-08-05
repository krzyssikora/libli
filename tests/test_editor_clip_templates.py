"""Several assertions here check a button is ABSENT and would stay green if the
tag emitted nothing at all. The pairing is what makes them non-vacuous: every
absence assertion but one sits in a test that ALSO asserts a button present
somewhere the rule allows. The mutant, named once for the file: make the tag
render nothing -> eight of the nine tests go RED, and only
test_no_paste_buttons_render_when_nothing_is_marked (the one absence-only test)
stays green.
"""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

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
    banner = body[body.index('id="clip-banner"') : body.index('id="clip-banner"') + 400]

    assert banner.strip() != ""
    assert "Some prose" in banner or "Text" in banner


def test_no_banner_renders_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'id="clip-banner"' not in body
