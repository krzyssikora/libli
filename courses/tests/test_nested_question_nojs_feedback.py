"""No-JS feedback for a question nested in a container, across all five containers.

THE CONTRACT: a question nested inside any of the five containers gets the same
no-JS verdict its top-level twin gets, including for a BLANK answer.

check_answer's no-JS path re-renders the whole lesson with a page-level
`feedback_for_pk` / `mark_result`, and _lesson_article.html:39 hands those to every
TOP-LEVEL element. Reaching a nested one used to be impossible, because THREE layers
each dropped the values: render_element's non-question branch called the container's
`render()` with only (element, state, slug, node_pk); the container's `render()`
builds a FRESH context dict (a container render is a CONTEXT BARRIER); and the
container template's bare `{% render_element child %}` reads nothing the barrier did
not re-emit. Forwarding at the template layer ALONE is a proven no-op, verified by
mutation -- which is why the fix re-emits a `page` dict at the barrier instead.

Before the fix, a nested question showed feedback only via the practice-state RESTORE
branch (courses_extras.py:55-85), which needs a STORED answer -- and a blank answer
stores nothing (views.py:1059-1060 clears the key instead). That is why the BLANK
case is the one that proves the fix: the non-blank case below was already green
through the restore branch and proves nothing about the seam.

Falsification history: replacing `answer_is_empty(answer)` at views.py:1060 with
`False` (so a blank answer is stored) made the old absence test RED for every
container, pinning the mechanism rather than the symptom -- and is exactly the
one-liner the spec rejects, since storing a deliberately blanked answer would make
it come back as "Incorrect" after reload for TOP-LEVEL questions too. An earlier
draft asserted `data-question="{pk}"` and passed vacuously -- that attribute is bare
and carries no pk -- which is why the structural guards below assert the nested
question really rendered.
"""

import pytest
from django.urls import reverse

from courses.models import BeforeAfterElement
from courses.models import Blank
from courses.models import CalloutElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db

VERDICT = "question__verdict"


def _fill_blank():
    q = FillBlankQuestionElement.objects.create(stem="Cap is {{paris}}.")
    Blank.objects.create(question=q, order=1, accepted="paris")
    return q


# name -> (build_container() -> (concrete, slot_id), child wrapper class).
# The wrapper class is the structural guard: it proves the container rendered the
# child at all, so `VERDICT not in body` cannot pass because nothing was there.
def _callout():
    return CalloutElement.objects.create(kind="example"), CalloutElement.SLOT_ID


def _spoiler():
    return SpoilerElement.objects.create(label="s"), SpoilerElement.SLOT_ID


def _tabs():
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    return obj, obj.data["tabs"][0]["id"]


def _two_column():
    obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    return obj, obj.data["columns"][0]["id"]


def _before_after():
    # AFTER slot deliberately: resolved_slots() APPENDS a child with an unrecognised
    # tab_id to the `before` bucket, so a before-slot fixture would still render even
    # if the slot id were wrong -- the after slot is the one that proves the wiring.
    return BeforeAfterElement.objects.create(), BeforeAfterElement.AFTER_SLOT_ID


CONTAINERS = [
    pytest.param(_callout, "callout__child", id="callout"),
    pytest.param(_spoiler, "spoiler__child", id="spoiler"),
    pytest.param(_tabs, "tabs__child", id="tabs"),
    pytest.param(_two_column, "twocolumn__child", id="two_column"),
    pytest.param(_before_after, "ba__child", id="before_after"),
]


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


@pytest.fixture
def scene(client):
    """A lesson with the SAME question type at top level and inside a container.

    Same type on both sides deliberately: the only difference under test is the
    nesting, so a type-specific render quirk cannot be mistaken for the seam.
    Returns a builder so each parametrized case picks its own container.
    """
    student = make_student(client, "njs")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    top_row = add_element(unit, _fill_blank())

    def build(make_container):
        concrete, slot_id = make_container()
        container_row = add_element(unit, concrete)
        nested_row = Element.objects.create(
            unit=unit,
            content_object=_fill_blank(),
            parent=container_row,
            tab_id=slot_id,
        )
        return nested_row

    return student, unit, top_row, build


def test_top_level_blank_answer_shows_feedback(scene, client):
    """The control: no-JS + blank answer at TOP level does render a verdict."""
    _student, unit, top_row, _build = scene
    body = client.post(_check_url(unit, top_row.pk), {"blank": [""]}).content.decode()
    assert VERDICT in body


@pytest.mark.parametrize(("make_container", "child_class"), CONTAINERS)
def test_nested_blank_answer_shows_feedback(scene, client, make_container, child_class):
    """The contract: the same blank answer, nested, renders its verdict too.

    The guard assertions are kept from the absence-era version: they prove the nested
    question really rendered, so a 404, a redirect, or a container that never rendered
    its child cannot be mistaken for a working seam.
    """
    _student, unit, _top, build = scene
    nested_row = build(make_container)

    resp = client.post(_check_url(unit, nested_row.pk), {"blank": [""]})
    assert resp.status_code == 200
    body = resp.content.decode()
    # BOTH questions really are on the page -- the nested one rendered, and now it
    # renders WITH its result.
    assert body.count("el--fillblank") == 2
    assert child_class in body
    assert VERDICT in body


@pytest.mark.parametrize(("make_container", "child_class"), CONTAINERS)
def test_nested_non_blank_answer_does_show_feedback(
    scene, client, make_container, child_class
):
    """The mechanism: a NON-blank nested answer gets a verdict -- but only because
    check_answer persisted it first and the restore branch re-marked it, not because
    the container forwarded the live result."""
    _student, unit, _top, build = scene
    nested_row = build(make_container)

    body = client.post(
        _check_url(unit, nested_row.pk), {"blank": ["paris"]}
    ).content.decode()
    assert child_class in body
    assert VERDICT in body
