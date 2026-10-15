import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from core.middleware import LANGUAGE_SESSION_KEY
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import ShortTextQuestionElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import UnitProgress
from courses.models import VideoElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _login(client, course):
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student


def _reset_url(course, unit):
    return reverse("courses:progress_reset", args=[course.slug, unit.pk])


def test_lesson_page_links_to_the_reset_interstitial(client):
    # PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears
    # in data-reset-href of the INACTIVE control. Active-ness is pinned by the
    # _control() tests below.
    # Now seeds a state-bearing element: the link is gated on the unit CONTAINING a
    # type that can persist practice state (spec D1). No MarkDoneItem rows needed --
    # the flag is type-based, not content-based.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_hides_the_reset_link_on_a_unit_with_no_stateful_element(client):
    # A text/video-only unit can hold nothing element_state ever stores, so reset is a
    # guaranteed no-op there and the link is not offered (spec §Purpose).
    course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    body = r.content.decode()
    # The positive anchor matters: "URL absent" is also satisfied by a 302 to login, a
    # 403, a 404 or a 500 -- i.e. by every failure mode of the FIXTURE rather than of
    # the condition under test.
    assert r.status_code == 200
    assert reverse("courses:complete", args=[course.slug, unit.pk]) in body
    assert _reset_url(course, unit) not in body


def test_lesson_page_shows_the_reset_link_for_an_element_nested_in_a_tab(client):
    # PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears
    # in data-reset-href of the INACTIVE control. Active-ness is pinned by the
    # _control() tests below.
    # Children of a Tabs join row keep their own `unit` FK, so the flag's query is FLAT
    # (not parent__isnull=True). Scoping it to top level would hide the link on a unit
    # whose only interactive content lives inside a tab.
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=MarkDoneElement.objects.create(prompt="P"),
        parent=join,
        tab_id=tab_id,
    )
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_shows_the_reset_link_on_a_question_only_unit(client):
    # PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears
    # in data-reset-href of the INACTIVE control. Active-ness is pinned by the
    # _control() tests below.
    # Covers the RESTORABLE_IN_LESSON half of the union. Every other render-level test
    # uses the validator half, so without this a bad implementation could drop questions
    # entirely and stay green. Seed NOTHING else -- the question must be the only
    # interactive element for this test's falsification to bite.
    course, unit = make_course_with_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q", accepted="x"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def _save_work(student, unit):
    # A non-empty blob is all the outline gate reads; its shape is irrelevant there.
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={"1": {"items": []}}
    )


def _chapter_unit(course, title):
    # published=True: this fixture predates migration 0057, whose model default
    # (published=False) would otherwise leave this raw-created unit -- and so
    # the now-empty chapter above it -- invisible to the enrolled STUDENT this
    # test logs in as. ContentNodeFactory opts into True for exactly this
    # reason (see its docstring); a raw .objects.create() call must do the
    # same to keep representing student-visible content.
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title=title
    )
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title=f"{title} unit",
        published=True,
    )
    return ch, unit


def test_outline_links_to_the_course_level_reset(client):
    course, unit = make_course_with_unit()
    _save_work(_login(client, course), unit)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset_course", args=[course.slug])
        in r.content.decode()
    )


def test_outline_offers_no_reset_to_a_student_with_no_saved_work(client):
    # A fresh student has nothing to clear, so neither the course-level nor any
    # per-container "Start fresh" is offered. Completion alone does not count:
    # the reset leaves `completed` untouched.
    course, unit = make_course_with_unit()
    ch, ch_unit = _chapter_unit(course, "c")
    student = _login(client, course)
    UnitProgress.objects.create(student=student, unit=ch_unit, completed=True)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    body = r.content.decode()
    # Positive anchor: the chapter rendered, so its link's absence is the gate's.
    assert r.status_code == 200
    assert f'data-node="{ch.pk}"' in body
    assert reverse("courses:progress_reset_course", args=[course.slug]) not in body
    assert "outline-node__reset" not in body


def test_outline_offers_reset_only_on_containers_above_saved_work(client):
    course, _unit = make_course_with_unit()
    ch_a, unit_a = _chapter_unit(course, "a")
    ch_b, _unit_b = _chapter_unit(course, "b")
    _save_work(_login(client, course), unit_a)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    body = r.content.decode()
    assert f'data-node="{ch_b.pk}"' in body
    assert reverse("courses:progress_reset", args=[course.slug, ch_a.pk]) in body
    assert reverse("courses:progress_reset", args=[course.slug, ch_b.pk]) not in body
    assert reverse("courses:progress_reset_course", args=[course.slug]) in body


def test_outline_ignores_saved_work_in_a_unit_the_student_cannot_see(client):
    # The interstitial counts only visible units, so state stranded in a draft
    # would offer a reset that reports "nothing to clear".
    course, _unit = make_course_with_unit()
    ch, _visible = _chapter_unit(course, "c")
    hidden = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="draft",
        published=False,
    )
    _save_work(_login(client, course), hidden)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    body = r.content.decode()
    assert f'data-node="{ch.pk}"' in body
    assert reverse("courses:progress_reset", args=[course.slug, ch.pk]) not in body
    assert reverse("courses:progress_reset_course", args=[course.slug]) not in body


def test_outline_links_reset_per_grouping_node(client):
    course, _unit = make_course_with_unit()
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    # published=True: this fixture predates migration 0057, whose model default
    # (published=False) would otherwise leave this raw-created unit -- and so
    # the now-empty chapter above it -- invisible to the enrolled STUDENT this
    # test logs in as. ContentNodeFactory opts into True for exactly this
    # reason (see its docstring); a raw .objects.create() call must do the
    # same to keep representing student-visible content.
    ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="u",
        published=True,
    )
    _save_work(_login(client, course), ch.children.get())
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset", args=[course.slug, ch.pk])
        in r.content.decode()
    )


def test_editor_preview_markdone_is_inert(client):
    """Drive the REAL preview view as the course author.

    Calling el.render(..., slug=None, node_pk=None) directly would only prove that
    `{% url ... as %}` swallows NoReverseMatch -- it hand-passes the very Nones it
    claims to discover, so it would stay green even if _preview.html's context GAINED
    slug/node_pk. The claim under test is about the preview VIEW's context.
    """
    from django.urls import reverse

    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    author = make_verified_user(username="prevauth", email="prevauth@school.edu")
    course, unit = make_course_with_unit(owner=author)
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")
    client.force_login(author)
    r = client.get(reverse("courses:manage_editor", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # eid is NON-zero here (the preview passes real join rows). What makes it inert is
    # the absent slug/node_pk -> empty save_url -> markdone.js no-ops on fetch("").
    assert 'data-markdone-url=""' in r.content.decode()
    # The [S1] entry asks for both halves: empty save_url AND no row created/written.
    from courses.models import UnitProgress

    assert not UnitProgress.objects.filter(unit=unit).exists()


def test_reset_link_survives_the_no_js_check_answer_rerender(client):
    """The flag must reach the POST re-render path, not just the GET.

    A missing context variable renders as FALSE in Django with no error, so a future
    render site built with a hand-assembled context would drop the link silently. Only
    a test catches that.
    """
    # PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears
    # in data-reset-href of the INACTIVE control. Active-ness is pinned by the
    # _control() tests below.
    course, unit = make_course_with_unit()
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="x")
    q_row = add_element(unit, q)
    # A MarkDoneElement beside the question so Task 2's question-only falsification
    # (restricting the filter to the validator half) does NOT co-fire this test.
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)

    # No X-Requested-With header -> _wants_fragment is False -> the full-page re-render
    # branch. The answer must be NON-EMPTY: an empty one takes the clear branch instead
    # of the store branch, exercising a different path while still returning 200.
    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, q_row.pk]),
        {"answer": "x"},
    )
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_views_calls_the_state_helper_rather_than_an_inlined_list(client, monkeypatch):
    """Proves the C1 -> C2 seam is live.

    Every other test here stays green if build_lesson_context hand-inlines the 18
    names, because the inlined list would be correct today. The drift shows up only
    when a 19th type ships: the derivation test goes RED, the author updates both it
    and state.py, and a stale list in views.py silently keeps the new type hidden.
    """
    # PRESENCE only (spec 2026-10-15 D1'): with no stored state the URL appears
    # in data-reset-href of the INACTIVE control. Active-ness is pinned by the
    # _control() tests below.
    from courses import state

    monkeypatch.setattr(state, "stateful_element_model_names", lambda: ("textelement",))
    course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    _login(client, course)

    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # A text-only unit now matches, because the helper says textelement is stateful.
    assert _reset_url(course, unit) in r.content.decode()


def test_an_orphaned_blob_does_not_bring_the_reset_link_back(client):
    """Pins the accepted cost of D1, in BOTH directions.

    Deleting a unit's last state-bearing element strands the student's stored blob:
    the unit page no longer offers to clear it (the outline's container/course resets
    still do). That is deliberate -- capability, not stored state.
    Presence is still capability-only under the 2026-10-15 revision (D1');
    enabled-ness now reads stored state (D2), but only INSIDE the capability
    gate, so an orphaned blob on a non-capability unit still renders no
    control. This test pins that.
    """
    course, unit = make_course_with_unit()
    # The SURVIVOR is a VideoElement, not a TextElement: the spec's scenario is an
    # author deleting the last STATEFUL element from a unit that still holds content,
    # and a video keeps Task 2's "textelement" falsification from firing this test.
    add_element(unit, VideoElement.objects.create(url="https://example.com/embed/x"))
    md = MarkDoneElement.objects.create(prompt="P")
    md_row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    # STR key, DICT value, and an ENROLLED student: build_lesson_context drops every
    # non-dict value and every non-int-coercible key, and never populates state at all
    # without a UnitProgress row. Get any of that wrong and the falsification below
    # silently passes without ever having fired.
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(md_row.pk): {"items": [item.pk]}},
    )
    md.delete()  # cascades the join row; the blob survives
    client.force_login(student)

    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert UnitProgress.objects.get(student=student, unit=unit).element_state != {}
    assert _reset_url(course, unit) not in r.content.decode()


def _control(body):
    """The ONE unit-head reset control, parsed -- never a substring check: the reset
    URL also appears in data-reset-href, so `url in body` passes in BOTH states."""
    soup = BeautifulSoup(body, "html.parser")
    found = soup.select(".lesson-unit__head .lesson-unit__reset")
    assert len(found) == 1, f"expected exactly one control, found {len(found)}"
    return found[0]


def _lesson(client, course, unit):
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    return r.content.decode()


def _expected_href(course, unit):
    return (
        _reset_url(course, unit)
        + "?next="
        + reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    )


def test_capability_unit_without_state_renders_inactive_control(client):
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    a = _control(_lesson(client, course, unit))
    assert not a.has_attr("href")
    assert a["aria-disabled"] == "true"
    assert a["role"] == "link"
    assert a["title"] == "Nothing to clear yet"
    assert a.has_attr("data-reset-control")
    assert a["data-reset-href"] == _expected_href(course, unit)
    assert not a.has_attr("tabindex")
    assert a.get_text(strip=True) == "Start fresh"


def test_capability_unit_with_state_renders_todays_active_link(client):
    course, unit = make_course_with_unit()
    md = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")
    student = _login(client, course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [item.pk]}}
    )
    a = _control(_lesson(client, course, unit))
    assert a["href"] == _expected_href(course, unit)
    for attr in (
        "aria-disabled",
        "role",
        "title",
        "data-reset-control",
        "data-reset-href",
    ):
        assert not a.has_attr(attr), attr
    assert a["class"] == ["btn", "btn--ghost", "btn--small", "lesson-unit__reset"]


def test_orphaned_blob_on_capability_unit_is_active(client):
    # Review Focus 4: a blob for a DELETED element on a unit that still has a
    # capability element is real stored state -- the reset clears it -- so ACTIVE.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    student = _login(client, course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={"999999": {"items": [1]}}
    )
    a = _control(_lesson(client, course, unit))
    assert a["href"] == _expected_href(course, unit)


def test_previewer_without_state_sees_inactive_control(client):
    # Review Focus 1: a non-enrolled viewer who can access the course (the owner).
    owner = make_verified_user()
    course, unit = make_course_with_unit(owner=owner)
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    client.force_login(owner)
    a = _control(_lesson(client, course, unit))
    assert a["aria-disabled"] == "true"
    assert not a.has_attr("href")


def test_previewer_with_state_sees_active_control(client):
    # Review Focus 1, other half: the non-enrolled `.filter().first()` read branch
    # (views.py build_lesson_context) feeds element_state for a previewer too.
    owner = make_verified_user()
    course, unit = make_course_with_unit(owner=owner)
    md = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")
    UnitProgress.objects.create(
        student=owner,
        unit=unit,
        element_state={str(row.pk): {"items": [item.pk]}},
    )
    client.force_login(owner)
    a = _control(_lesson(client, course, unit))
    assert a["href"] == _expected_href(course, unit)
    assert not a.has_attr("aria-disabled")


def test_active_after_no_js_markdone_post(client):
    # Review Focus 2: the no-JS form posts, redirects to the unit page, and the
    # server render must now be ACTIVE.
    course, unit = make_course_with_unit()
    md = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, md)
    item = MarkDoneItem.objects.create(element=md, content="a")
    _login(client, course)
    r = client.post(
        reverse("courses:element_state_save", args=[course.slug, unit.pk]),
        {"element": row.pk, "item": [item.pk]},
        follow=True,
    )
    assert r.status_code == 200
    a = _control(r.content.decode())
    assert a["href"] == _expected_href(course, unit)


def test_no_js_check_answer_rerender_shows_active_control(client):
    # Review Focus 3, render half (header half lives in test_state_saved_header.py).
    course, unit = make_course_with_unit()
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    right = Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    row = Element.objects.create(unit=unit, content_object=q)
    _login(client, course)
    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, row.pk]),
        {"choice": [right.pk]},
    )
    assert r.status_code == 200
    a = _control(r.content.decode())
    assert a["href"] == _expected_href(course, unit)


def test_inactive_title_is_translated_in_polish(client):
    from django.utils import translation

    with translation.override("pl"):
        got = translation.gettext("Nothing to clear yet")
    assert got == "Nie ma nic do wyczyszczenia"


def test_inactive_title_renders_in_polish(client):
    # The catalog test above cannot see a template msgid typo; this renders it.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    # force_login stamps the user's language into the session, which the
    # SessionLocaleMiddleware prefers over Accept-Language: set it AFTER login.
    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()
    url = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    r = client.get(url)
    assert r.status_code == 200
    assert _control(r.content.decode())["title"] == "Nie ma nic do wyczyszczenia"
