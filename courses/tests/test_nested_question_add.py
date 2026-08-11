"""`element_add` accepts the widened question types into a container.

These cases are what actually pin the form-key alias against the endpoint that
consults it. The drift test in test_nesting_rule.py checks only that the map's values
land in NESTABLE_TYPE_KEYS: an alias keyed on an add-menu CARD name
(`choice-single -> choice`) is equally well-formed and would simply never be
consulted, because element_add reads the two choice CARD names to seed `multiple` and
then collapses both to type_key="choicequestion" before calling resolve_scope. Only a
request that travels the real endpoint sees the difference.

`element_add` creates NO Element row. It validates the type, resolves the scope and
returns _render_open_form(...) -- an empty editor form fragment; the row is created
later by element_save. So every assertion below is on the RETURNED FRAGMENT, exactly
as tests/test_tabs_registry.py's nested-add tests are.

The quiz-400 companion at the bottom of this file is the same POST against a quiz
unit. It could not be written alongside the cases above: element_add 400s on nesting
only when resolve_scope raises, and `choicequestion -> choice` is nestable, the
callout is a registered container and the child lands at depth 2 -- so before the
lesson-only gate landed that POST returned 200.
"""

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _managed(client):
    """A course whose OWNER is logged in. can_manage_course grants on ownership; a
    plain make_teacher(client) would get a 403 from every manage view.

    Copied from tests/test_tabs_registry.py, where it is a module-local helper and
    not importable. make_course_with_unit builds a LESSON unit.
    """
    owner = make_login(client, "owner")
    return make_course_with_unit(owner=owner)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("add_type", "expect_multiple"),
    [
        ("choice-single", "False"),
        ("choice-multi", "True"),
        ("shorttextquestion", None),
        ("shortnumericquestion", None),
    ],
)
def test_nested_add_of_a_widened_question_type_opens_its_form(
    client, add_type, expect_multiple
):
    course, unit = _managed(client)  # a LESSON unit
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=unit, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "type": add_type,
            "unit": unit.pk,
            "parent": join.pk,
            "tab": CalloutElement.SLOT_ID,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    # The scope survives into the form's hidden fields, so the eventual element_save
    # lands the child in this callout rather than silently at top level.
    assert f'name="parent" value="{join.pk}"' in html
    assert f'name="tab" value="{CalloutElement.SLOT_ID}"' in html
    if expect_multiple is not None:
        # The ONLY thing distinguishing the two choice cards at this endpoint:
        # element_add passes initial={"multiple": ...} into the opened form.
        #
        # `multiple` is a HiddenInput (element_forms.py), rendered by
        # _edit_choicequestion.html as {{ form.multiple }} -- so the markup is
        # <input type="hidden" name="multiple" value="True"> and there is NO
        # `checked` attribute anywhere. Django emits type/name/value contiguously.
        assert f'name="multiple" value="{expect_multiple}"' in html
        # Both cards collapse to the same form key before resolve_scope sees them.
        assert 'name="type" value="choicequestion"' in html
    else:
        assert f'name="type" value="{add_type}"' in html


@pytest.mark.django_db
def test_nested_add_of_a_widened_question_creates_no_element_row(client):
    """The endpoint is render-only. Pinning it keeps the assertions above honest:
    read as "the add succeeded", they would invite a later `Element.objects.get(...)`
    that could only ever fail."""
    course, unit = _managed(client)
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=unit, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "type": "choice-single",
            "unit": unit.pk,
            "parent": join.pk,
            "tab": CalloutElement.SLOT_ID,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert not Element.objects.filter(parent=join).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "add_type",
    ["choice-single", "choice-multi", "shorttextquestion", "shortnumericquestion"],
)
def test_nested_add_of_a_widened_question_type_is_400_in_a_quiz(client, add_type):
    """The quiz companion of the parametrized acceptance test above -- one per card,
    because element_add rewrites `type` for the two choice cards before resolve_scope
    ever sees it, and only a per-card POST proves each rewrite still reaches the
    gate."""
    course, _lesson = _managed(client)
    quiz = make_quiz_unit(course=course)
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=quiz, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "type": add_type,
            "unit": quiz.pk,
            "parent": join.pk,
            "tab": CalloutElement.SLOT_ID,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_a_non_question_nested_add_still_opens_its_form_in_a_quiz(client):
    """The control for the four 400s above. Nesting itself is untouched in a quiz --
    only questions are refused -- so a text card must still open its form."""
    course, _lesson = _managed(client)
    quiz = make_quiz_unit(course=course)
    callout = CalloutElement.objects.create(kind="example")
    join = Element.objects.create(unit=quiz, content_object=callout)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "type": "text",
            "unit": quiz.pk,
            "parent": join.pk,
            "tab": CalloutElement.SLOT_ID,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert f'name="parent" value="{join.pk}"' in resp.content.decode()
