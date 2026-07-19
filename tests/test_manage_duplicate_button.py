from django.urls import reverse
from django.utils import translation

from courses.models import ContentNode, Element, TextElement
from tests.factories import ContentNodeFactory, CourseFactory, make_login


def _builder_html(client, course):
    resp = client.get(
        reverse("courses:manage_builder", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 200
    return resp.content.decode()


def test_duplicate_button_present_for_unit(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(course=course, title="U1")
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>x</p>")
    )
    html = _builder_html(client, course)
    assert 'data-op="duplicate"' in html
    assert "#bi-duplicate" in html


def test_duplicate_button_only_on_units(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, title="U1")  # a unit
    ContentNode.objects.create(course=course, kind="chapter", title="Chap")  # not
    html = _builder_html(client, course)
    assert html.count('data-op="duplicate"') == 1  # only the unit


def test_bi_duplicate_symbol_defined(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, title="U1")
    html = _builder_html(client, course)
    assert 'id="bi-duplicate"' in html


def test_duplicate_label_translated_pl():
    with translation.override("pl"):
        assert translation.gettext("Duplicate") == "Duplikuj"
