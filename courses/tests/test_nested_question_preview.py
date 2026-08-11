"""The editor preview posts a NESTED question's Check to its own try endpoint.

`_preview.html` reverses `courses:manage_element_try` per TOP-LEVEL element and hands
it down as `action_url`. A container's `render()` is a context barrier, so that kwarg
never reached a nested child: it rendered with `action_url=None` and fell through to
`QuestionElement.render`'s default -- the STUDENT `courses:check_answer` URL. An author
clicking Check in their own preview hit the student path and persisted practice state
against their own account.

The fix crosses the barrier with a FLAG, never the URL. `try_url` is reversed against
the PARENT's pk, so forwarding it would post the child's answer to the parent's
endpoint -- a different wrong answer to the same question. `editor_preview=True` rides
the `page` dict into the child's context and `render_element` reverses the child's OWN
try URL on the far side.

Test 1 drives the REAL editor page. `render_to_string` on the partial would need
`unit`, `preview_elements` and `editor_preview` seeded by hand and would never exercise
`_preview.html`'s `{% url %}` -- i.e. it could not fail for the reason the bug exists.

Falsification history: defaulting `render_element`'s `editor_preview` parameter to
`False` instead of `None` turns its context fallback into dead code (`False is None` is
never true), so the flag never reaches the `page` dict. Test 1 goes RED with the
STUDENT check_answer URL as the form action -- the original bug, exactly.
"""

import re

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db

# The choicequestion.html form opens
# `<form class="question__form" method="post" data-question-inline\n action="...">`,
# i.e. the attribute is on the NEXT line. A single-line pattern would find nothing and
# every assertion below would fail against a CORRECT implementation.
_FORM_ACTION = re.compile(r'data-question-inline\s+action="([^"]*)"')


def _managed(client):
    """A course whose OWNER is logged in. can_manage_course grants on ownership; a
    plain make_teacher(client) would get a 403 from every manage view.

    Copied from tests/test_tabs_registry.py, where it is a module-local helper and not
    importable. make_course_with_unit builds a LESSON unit.
    """
    owner = make_login(client, "owner")
    return make_course_with_unit(owner=owner)


def _choice_question():
    q = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    Choice.objects.create(question=q, text="right", is_correct=True)
    Choice.objects.create(question=q, text="wrong", is_correct=False)
    return q


def test_a_nested_questions_preview_form_posts_to_its_own_try_endpoint(client):
    course, unit = _managed(client)
    callout_row = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(kind="example")
    )
    nested_row = Element.objects.create(
        unit=unit,
        content_object=_choice_question(),
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()

    actions = _FORM_ACTION.findall(body)
    # The callout is not a question, so the nested child owns the only question form
    # on the page. Pinned so a future preview change cannot make the three assertions
    # below silently inspect somebody else's form.
    assert len(actions) == 1
    action = actions[0]

    student_url = reverse(
        "courses:check_answer",
        kwargs={
            "slug": course.slug,
            "node_pk": unit.pk,
            "element_pk": nested_row.pk,
        },
    )
    parent_url = reverse(
        "courses:manage_element_try",
        kwargs={"slug": course.slug, "pk": callout_row.pk},
    )
    own_url = reverse(
        "courses:manage_element_try",
        kwargs={"slug": course.slug, "pk": nested_row.pk},
    )

    # THREE distinct facts, because two of them are the actual bug and one alone
    # would leave the other reachable:
    # 1. not the STUDENT endpoint -- the original defect, which persists practice
    #    state against the author's own account;
    assert action != student_url
    # 2. not the PARENT's try URL -- what a "just forward action_url" fix produces;
    #    the child's answer would be graded against the callout's pk;
    assert action != parent_url
    # 3. and positively the child's own try URL, so 1 and 2 cannot both pass by the
    #    action having been dropped entirely.
    assert action == own_url


def test_element_try_choice_rerender_carries_the_manage_endpoint(client):
    """DEFENCE IN DEPTH ONLY -- a MARKUP assertion with no user-facing meaning.

    `element_try`'s choice branch re-renders the whole element so inline per-option
    feedback lands in the choices list. editor.js reads the action off the LIVE form
    node and swaps only `innerHTML`, so the attribute in this response is DISCARDED and
    no author can observe a wrong post either way. Asserted anyway because a
    manage-gated fragment should not ship a student endpoint in its markup at all.
    """
    course, unit = _managed(client)
    question = _choice_question()
    row = Element.objects.create(unit=unit, content_object=question)
    right = question.choices.get(is_correct=True)
    try_url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": row.pk}
    )

    resp = client.post(try_url, {"choice": [right.pk]})
    assert resp.status_code == 200
    body = resp.content.decode()

    assert _FORM_ACTION.findall(body) == [try_url]
    assert (
        reverse(
            "courses:check_answer",
            kwargs={
                "slug": course.slug,
                "node_pk": unit.pk,
                "element_pk": row.pk,
            },
        )
        not in body
    )
