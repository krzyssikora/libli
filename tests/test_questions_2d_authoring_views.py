import pytest
from django.urls import reverse

from courses.models import ContentNode, DragFillBlankQuestionElement
from tests.factories import ContentNodeFactory, CourseFactory, make_pa


@pytest.mark.django_db
def test_element_add_opens_dragfill_form_not_400(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "dragfillblankquestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'name="slot"' not in resp.content  # authoring form, not the student widget
    assert b'name="stem"' in resp.content


@pytest.mark.django_db
def test_element_add_opens_matchpair_formset(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "matchpairquestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"pairs-TOTAL_FORMS" in resp.content  # the inline formset rendered


@pytest.mark.django_db
def test_matchpair_save_invalid_rerenders_formset_422(client):
    # §4.4 "re-bind on 422": a valid host form + invalid formset (zero pairs) must
    # re-render the bound MatchPair formset, not 400/500. Pins the e.formset path.
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "matchpairquestion",
            "unit": unit.pk,
            "element": "new",
            "unit_token": unit.updated.isoformat(),
            "stem": "<p>m</p>",
            "marking_mode": "A",
            "pairs-TOTAL_FORMS": "0",
            "pairs-INITIAL_FORMS": "0",
            "pairs-MIN_NUM_FORMS": "0",
            "pairs-MAX_NUM_FORMS": "1000",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert b"pairs-TOTAL_FORMS" in resp.content  # formset re-rendered (bound), not dropped
