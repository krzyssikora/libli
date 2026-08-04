"""Depth threading through the editor row recursion and the add-menu.

RENDER SCOPE IS PART OF EVERY ASSERTION HERE.

`_editor_scope.html` renders the TOP-LEVEL add-menu unconditionally, and after this
slice that menu still carries all three container cards (its depth is 0, and
0 < max_nest_depth - 1). So on an unscoped whole-page render:

* a NEGATIVE assertion (`'data-add-type="tabs"' not in html`) fails against a CORRECT
  implementation -- the top-level card is always there;
* a POSITIVE assertion passes no matter what the nested menu emits, including under
  the mutant the test is supposed to kill.

Every test below therefore names one of:

1. a direct `render_to_string(".../_add_menu.html", {...})` -- exactly one menu; or
2. a **pk-keyed** slice of a page/fragment render (`_menu_block`). Keyed by pk, never
   by depth: the rendered menu carries only `data-add-menu data-parent="<pk>"
   data-tab="<slot>"`, so nothing in the HTML encodes depth and a
   `_menu_at_depth(html, depth=N)` helper cannot be implemented at all; or
3. a pk-keyed ABSENCE assertion on a page render, where `_menu_block`'s `html.index()`
   would raise `ValueError` instead of asserting anything.
"""

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from courses.models import SpoilerElement
from courses.tests.test_nesting_rule import _mk
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


# --- fixtures -------------------------------------------------------------------


@pytest.fixture
def lesson(client):
    """(course, unit) for a LESSON unit, with a Platform Admin logged in.

    LESSON, not quiz: the Spoiler card and the fill-blank card both sit inside
    `{% if not unit_is_quiz %}` in _add_menu.html.
    """
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _page(client, course, unit):
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    return resp.content.decode()


def _tab(join, index=0):
    return join.content_object.data["tabs"][index]["id"]


def _menu_block(html, join_pk, tab_id):
    """The one add-menu belonging to (join_pk, tab_id), sliced out of a render.

    Keyed by PK, not by depth: the rendered menu carries only
    `data-add-menu data-parent="<pk>" data-tab="<slot>"` -- nothing encodes depth.
    Bounded to the NEXT `addwrap` token, which starts the next add-menu wrapper; this
    wrapper's own two `addwrap` occurrences (`class="addwrap addwrap--nested"`) sit
    BEFORE the marker, so the window holds exactly this one menu.
    """
    start = html.index(f'data-parent="{join_pk}" data-tab="{tab_id}"')
    end = html.find("addwrap", start + 1)
    return html[start : end if end != -1 else len(html)]


CONTAINER_CARDS = ("tabs", "twocolumn", "spoiler", "callout")


# --- tests ----------------------------------------------------------------------


def test_top_level_menu_still_offers_containers(client, lesson):
    """The depth-SEEDING regression.

    An unseeded `depth` resolves to '' and smartif swallows the `str < int`
    TypeError, so every predicate is False and the container cards vanish from the
    TOP-LEVEL menu -- silently, with a `depth` seed apparently present.

    SCOPE: page render of a unit with NO container element, so the ONLY add-menu on
    the page is the top-level one and the positive assertion cannot be satisfied by
    some other menu.
    """
    course, unit = lesson
    _mk(unit, "text")  # a leaf so the page is not the empty-state
    html = _page(client, course, unit)
    assert html.count("data-add-menu") == 1  # exactly the top-level menu
    for t in CONTAINER_CARDS:
        assert f'data-add-type="{t}"' in html, t


def test_depth_1_nested_menu_offers_containers(client, lesson):
    """POSITIVE requirement -- the ACCEPT case for the SECOND container level.
    A container added here lands at depth 2, which builder clause 4 accepts.

    LESSON unit: the Spoiler card sits inside `{% if not unit_is_quiz %}`.

    SCOPE 2: the nested menu of the depth-1 tabs element only. The top-level menu
    always carries these cards, so a whole-page assertion would pass under this
    test's own mutant.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    menu = _menu_block(_page(client, course, unit), top.pk, _tab(top))
    for t in CONTAINER_CARDS:
        assert f'data-add-type="{t}"' in menu, t


def test_depth_2_nested_menu_offers_containers(client, lesson):
    """POSITIVE requirement -- the ACCEPT case for the THIRD container level, and the
    assertion that the user's canonical shape is reachable through the UI at all. A
    container added here lands at depth 3, which builder clause 4 accepts.

    This is the ONLY test that kills the container-card off-by-one tightening
    (`{% if depth < max_nest_depth|add:-2 %}`): at depth 1 that mutant still emits the
    cards (1 < 2), so `test_depth_1_nested_menu_offers_containers` stays green.

    SCOPE 2: the nested menu of the depth-2 tabs element only.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab=_tab(top))
    menu = _menu_block(_page(client, course, unit), mid.pk, _tab(mid))
    for t in CONTAINER_CARDS:
        assert f'data-add-type="{t}"' in menu, t


def test_depth_3_nested_menu_hides_containers_but_keeps_leaves(client, lesson):
    """A container child of a depth-3 container would land at depth 4 -- clause 4
    rejects it, so the card must go. Leaves stay: they land at depth 4, which is legal.

    SCOPE 2 is MANDATORY here: on a whole-page render the top-level menu's own Tabs
    card makes the negative assertion fail against a CORRECT implementation.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab=_tab(top))
    deep = _mk(unit, "tabs", parent=mid, tab=_tab(mid))
    menu = _menu_block(_page(client, course, unit), deep.pk, _tab(deep))
    for t in CONTAINER_CARDS:
        assert f'data-add-type="{t}"' not in menu, t
    assert 'data-add-type="callout"' not in menu  # now a CONTAINER, depth-guarded
    assert 'data-add-type="text"' in menu  # a real leaf still offered


def test_no_add_menu_inside_a_depth_4_element(client, lesson):
    """The depth-4 container MUST be a TABS element, matching the `:91` mutant.
    _element_row.html includes _add_menu.html at four sites -- tabs, two-column,
    spoiler and callout -- so a spoiler, two-column or callout fixture would leave
    the named mutant green and this row vacuous.

    ORM-constructed: clause 4 makes a depth-4 container unreachable through
    resolve_scope. Defence in depth -- do not delete as dead.

    SCOPE 3: neither mandated scope works. Scope 1 renders _add_menu.html itself and
    can never show the ABSENCE of the include; `_menu_block` uses `html.index()`,
    which raises ValueError rather than asserting absence. Use the pk-keyed page
    assertion, plus a positive check that the depth-4 ROW is rendered so absence is
    not merely absence-of-everything.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab=_tab(top))
    third = _mk(unit, "tabs", parent=mid, tab=_tab(mid))
    deep = _mk(unit, "tabs", parent=third, tab=_tab(third))
    html = _page(client, course, unit)
    assert f'data-element="{deep.pk}"' in html  # the depth-4 row IS rendered
    # ...and it still renders its SLOTS. Guarding the whole `resolved_tabs` loop instead
    # of just the add-menu include would leave the row visible while silently dropping
    # its tabs and every child row under them -- a legacy/imported depth-5 tree would
    # then be uneditable and invisible to its author while students still see it.
    #
    # The EDITOR-ONLY form of the marker is mandatory. A bare `data-tab-id="..."` is
    # emitted by the student tabselement.html too (`.tabs__panel`), and this page
    # carries a live-preview pane that renders that template all the way down -- so the
    # bare assertion would pass on the preview alone and stay green under its own
    # mutant. `<details class="tabs-rows"` exists only in _element_row.html.
    assert f'<details class="tabs-rows" data-tab-id="{_tab(deep)}"' in html
    assert f'data-parent="{deep.pk}"' not in html  # ...but it offers no add-menu


def test_nested_spoiler_renders_children_and_menu(client, lesson):
    """A spoiler inside a tab: before this task it fell to the leaf `{% else %}`
    branch (`el.parent_id is None` on the spoiler branch), so its children were
    invisible and it had no add-menu -- an author could not reach depth 3 through a
    spoiler at all.

    SCOPE 2 for the menu; the child row is asserted by its own pk.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    sp = _mk(unit, "spoiler", parent=top, tab=_tab(top))
    child = _mk(unit, "text", parent=sp, tab=SpoilerElement.SLOT_ID)
    html = _page(client, course, unit)
    assert "el-row--spoiler" in html  # the spoiler branch, not the leaf branch
    assert f'data-element="{child.pk}"' in html  # its depth-3 child row is rendered
    menu = _menu_block(html, sp.pk, SpoilerElement.SLOT_ID)
    assert 'data-add-type="text"' in menu  # a depth-3 leaf is still offerable
    assert 'data-add-type="tabs"' in menu  # ...and so is a THIRD container level


def test_cap_agreement_cards(client, lesson, monkeypatch):
    """The container-card guard must read `max_nest_depth`, not a literal `3`.

    THE PATCH VALUE MUST NEVER EQUAL THE REAL CAP. `builder.MAX_NEST_DEPTH` is 4, so
    patching to 4 would patch to the real value: both halves would then measure the
    same tree, the test would still PASS, and it would prove nothing. Patch to 5, one
    past the cap, and re-verify the named mutant if the cap ever moves again.

    PAGE render both times -- a direct `render_to_string` would put max_nest_depth
    into the context by hand and make the monkeypatch inert, so the second assertion
    would fail against a correct implementation. The whole point is that the value
    reaches the template THROUGH the view.

    BRACKET the change: the depth-3 menu LACKS the cards at the real cap and GAINS
    them at 5. Asserting only the patched side passes vacuously, because the
    top-level menu satisfies it unconditionally.

    SCOPE 2 both times.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab=_tab(top))
    deep = _mk(unit, "tabs", parent=mid, tab=_tab(mid))
    at_cap = _menu_block(_page(client, course, unit), deep.pk, _tab(deep))
    assert 'data-add-type="tabs"' not in at_cap

    monkeypatch.setattr("courses.builder.MAX_NEST_DEPTH", 5)
    raised = _menu_block(_page(client, course, unit), deep.pk, _tab(deep))
    assert 'data-add-type="tabs"' in raised


def test_cap_agreement_include(client, lesson, monkeypatch):
    """The include guard is the likelier slip -- three sites, not one. The fixture's
    deepest container is a TABS element, matching the `:91` mutant.

    THE PATCH VALUE MUST NEVER EQUAL THE REAL CAP -- see test_cap_agreement_cards.
    Patch to 5, and keep the fixture one level deeper than the cap allows.

    SCOPE 3: pk-keyed presence assertion on a page render. With the cap raised to 5
    the depth-4 tabs element MUST get its own add-menu back.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab=_tab(top))
    third = _mk(unit, "tabs", parent=mid, tab=_tab(mid))
    deep = _mk(unit, "tabs", parent=third, tab=_tab(third))

    # At the real cap the depth-4 row has NO menu: without this the test could pass
    # under a mutant that emits the menu unconditionally.
    assert f'data-parent="{deep.pk}"' not in _page(client, course, unit)

    monkeypatch.setattr("courses.builder.MAX_NEST_DEPTH", 5)
    html = _page(client, course, unit)
    assert f'data-parent="{deep.pk}"' in html


def test_fragment_swap_still_emits_menu_and_cards(client, lesson):
    """Every add/save/move/delete returns through `_render_editor_fragments`. If
    `max_nest_depth` lands only in `_editor_page` the first page load looks perfect
    and every later fragment swap silently drops both the nested menu and its cards.

    SCOPE 2, applied to the FRAGMENT body rather than a page render.
    """
    course, unit = lesson
    top = _mk(unit, "tabs")
    tab = _tab(top)
    child = _mk(unit, "text", parent=top, tab=tab)
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {
            "element": str(child.pk),
            "unit": str(unit.pk),
            "unit_token": unit.updated.isoformat(),
            "ctx": "editor",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-scope="editor"' in html  # it really is the editor fragment
    menu = _menu_block(html, top.pk, tab)
    for t in CONTAINER_CARDS:
        assert f'data-add-type="{t}"' in menu, t


def test_top_level_lesson_menu_has_exactly_one_fillblank_card():
    """`_add_menu.html`'s in-spoiler fill-blank card becomes `{% if nested %}`.
    Deleting that guard outright duplicates the Questions group's own fill-blank card
    in every NON-nested menu.

    SCOPE 1 (mandatory): after the change EVERY nested menu emits a fill-blank card
    -- measured count 6 on a lesson page carrying tabs plus a nested spoiler -- so an
    unscoped page render fails against correct code AND under its own mutant, making
    the RED verification meaningless. Render the TOP-LEVEL menu directly: `nested` is
    falsy, so a correct implementation emits 1 and the mutant emits 2.

    `unit_is_quiz` is absent (falsy) -> the Interactive group renders, which is where
    the guarded card lives. That is the lesson case.
    """
    html = render_to_string(
        "courses/manage/editor/_add_menu.html", {"depth": 0, "max_nest_depth": 4}
    )
    assert html.count('data-add-type="fillblankquestion"') == 1
