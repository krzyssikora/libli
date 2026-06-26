import pytest
from django.urls import reverse

from courses.models import Blank
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _check_url(course, unit, el):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )


@pytest.mark.django_db
def test_shorttext_initial_render_has_input_no_answer_leak(client):
    course, unit = _enrolled_unit(client)
    q = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    Element.objects.create(unit=unit, content_object=q)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="answer"' in body
    assert "Paris" not in body  # accepted answer never in the initial render


@pytest.mark.django_db
def test_shorttext_check_answer_fragment(client):
    course, unit = _enrolled_unit(client)
    q = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    wrong = client.post(url, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-incorrect" in wrong.content
    assert b"Paris" in wrong.content  # reveal shown on a wrong answer
    ok = client.post(url, {"answer": " paris "}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-correct" in ok.content
    assert b"Paris" not in ok.content  # fully-correct suppresses the reveal


@pytest.mark.django_db
def test_shortnumeric_check_answer_fragment(client):
    from decimal import Decimal

    course, unit = _enrolled_unit(client)
    q = ShortNumericQuestionElement.objects.create(
        stem="<p>Pi?</p>", value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    assert (
        b"is-correct"
        in client.post(url, {"answer": "3,15"}, HTTP_X_REQUESTED_WITH="fetch").content
    )
    assert (
        b"is-incorrect"
        in client.post(url, {"answer": "9"}, HTTP_X_REQUESTED_WITH="fetch").content
    )


@pytest.mark.django_db
def test_shorttext_no_js_repopulates_only_answered(client):
    course, unit = _enrolled_unit(client)
    q1 = ShortTextQuestionElement.objects.create(stem="<p>A?</p>", accepted="x")
    q2 = ShortTextQuestionElement.objects.create(stem="<p>B?</p>", accepted="y")
    el1 = Element.objects.create(unit=unit, content_object=q1)
    Element.objects.create(unit=unit, content_object=q2)
    resp = client.post(_check_url(course, unit, el1), {"answer": "myguess"})  # no-JS
    body = resp.content.decode()
    assert "lesson-unit__title" in body  # whole page
    assert body.count("myguess") == 1  # only the answered question repopulates


def _fillblank_in_unit(unit):
    q = FillBlankQuestionElement.objects.create(stem="The capital is ￿0￿.")
    Blank.objects.create(question=q, accepted="Paris")
    return q, Element.objects.create(unit=unit, content_object=q)


@pytest.mark.django_db
def test_fillblank_initial_render_has_input_no_leak(client):
    course, unit = _enrolled_unit(client)
    q, el = _fillblank_in_unit(unit)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="blank"' in body
    assert "￿" not in body  # tokens never reach the client
    assert "Paris" not in body  # accepted answer not leaked initially


@pytest.mark.django_db
def test_fillblank_check_answer_fragment_correct_and_partial(client):
    course, unit = _enrolled_unit(client)
    q = FillBlankQuestionElement.objects.create(stem="￿0￿ and ￿1￿")
    Blank.objects.create(question=q, accepted="a")
    Blank.objects.create(question=q, accepted="b")
    el = Element.objects.create(unit=unit, content_object=q)
    url = _check_url(course, unit, el)
    ok = client.post(url, {"blank": ["a", "b"]}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-correct" in ok.content
    partial = client.post(url, {"blank": ["a", "WRONG"]}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"is-incorrect" in partial.content
    assert b"answer-correct" in partial.content  # the right gap still marked


@pytest.mark.django_db
def test_post_submit_reveals_only_answered_across_types(client):
    course, unit = _enrolled_unit(client)
    answered = ShortTextQuestionElement.objects.create(stem="<p>A?</p>", accepted="x")
    other = ShortTextQuestionElement.objects.create(stem="<p>B?</p>", accepted="secret")
    el = Element.objects.create(unit=unit, content_object=answered)
    Element.objects.create(unit=unit, content_object=other)
    # Answer WRONG so the reveal renders (fully-correct suppresses it now).
    resp = client.post(_check_url(course, unit, el), {"answer": "wrong"})  # no-JS
    body = resp.content.decode()
    assert "is-incorrect" in body  # the answered question revealed
    assert "secret" not in body  # the OTHER question's accepted answer stays hidden
    assert body.count("question__reveal-text") == 1  # exactly one reveal block
