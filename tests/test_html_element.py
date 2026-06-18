import pytest
from django.template import Context
from django.template import Template
from django.urls import reverse

from courses.models import ELEMENT_MODELS
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import HtmlElement
from tests.factories import make_pa


def test_htmlelement_in_element_models():
    assert "htmlelement" in ELEMENT_MODELS


@pytest.mark.django_db
def test_htmlelement_stores_raw_html_unsanitized():
    el = HtmlElement.objects.create(html="<script>alert(1)</script><b>x</b>")
    el.refresh_from_db()
    # Containment is the iframe, not sanitization — markup is stored verbatim.
    assert el.html == "<script>alert(1)</script><b>x</b>"


@pytest.mark.django_db
def test_course_and_unit_html_fields_default_empty():
    course = Course.objects.create(title="C", slug="c")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    assert course.html_css == "" and course.html_js == ""
    assert unit.html_seed_js == ""


@pytest.mark.django_db
def test_htmlelement_cascades_join_row_on_delete():
    course = Course.objects.create(title="C", slug="c2")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    el = HtmlElement.objects.create(html="<p>hi</p>")
    Element.objects.create(unit=unit, content_object=el)
    assert Element.objects.count() == 1
    el.delete()  # concrete-first delete cascades the join row via GenericRelation
    assert Element.objects.count() == 0


@pytest.mark.django_db
def test_htmlelement_editor_delete_removes_concrete_and_join():
    # Spec §8.1: exercise the REAL editor delete path (builder.delete_element,
    # which deletes concrete-first + compacts ordering), not just bare .delete().
    from courses import builder

    course = Course.objects.create(title="C", slug="c-del")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    join = Element.objects.create(
        unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>")
    )
    unit.refresh_from_db()
    builder.delete_element(course, join.pk, unit.updated.isoformat())
    assert HtmlElement.objects.count() == 0
    assert Element.objects.count() == 0


def _render_tag(element):
    tpl = Template("{% load courses_extras %}{% render_element el %}")
    return tpl.render(Context({"el": element}))


@pytest.mark.django_db
def test_render_emits_locked_down_iframe():
    course = Course.objects.create(title="C", slug="c-r1", html_css=".q{color:red}")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
        html_seed_js="var SEED=1;",
    )
    el = HtmlElement.objects.create(html="<b>hi</b>")
    join = Element.objects.create(unit=unit, content_object=el)

    out = _render_tag(join)
    assert 'sandbox="allow-scripts"' in out
    assert "allow-same-origin" not in out
    assert 'referrerpolicy="no-referrer"' in out
    assert "srcdoc=" in out
    assert 'class="html-el"' in out


@pytest.mark.django_db
def test_srcdoc_is_attribute_escaped_no_breakout():
    course = Course.objects.create(title="C", slug="c-r2")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    # Author content with a double-quote + a </script> + an ampersand.
    el = HtmlElement.objects.create(html='<i a="x">&</i><script>"</script>')
    join = Element.objects.create(unit=unit, content_object=el)
    out = _render_tag(join)
    # The raw, unescaped author markup must NOT appear verbatim in the page
    # (it is attribute-escaped inside srcdoc).
    assert '<i a="x">' not in out
    assert "&quot;" in out  # the double-quote was escaped


@pytest.mark.django_db
def test_render_element_other_types_unchanged():
    from courses.models import TextElement

    course = Course.objects.create(title="C", slug="c-r3")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    te = TextElement.objects.create(body="<p>plain</p>")
    join = Element.objects.create(unit=unit, content_object=te)
    out = _render_tag(join)
    assert "plain" in out
    assert "srcdoc=" not in out  # text element is not iframed


@pytest.mark.django_db
def test_course_css_propagates_on_next_render():
    course = Course.objects.create(title="C", slug="c-prop", html_css=".q{color:red}")
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    join = Element.objects.create(
        unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>")
    )
    assert ".q{color:red}" in _render_tag(join)
    course.html_css = ".q{color:blue}"
    course.save(update_fields=["html_css"])
    join.refresh_from_db()
    assert ".q{color:blue}" in _render_tag(join)  # element row untouched


@pytest.mark.django_db
def test_html_form_registered_and_plain():
    from courses.element_forms import FORM_FOR_TYPE
    from courses.element_forms import HtmlElementForm

    assert FORM_FOR_TYPE["html"] is HtmlElementForm
    # Plain ModelForm: constructs with no course=/unit= kwargs.
    form = HtmlElementForm()
    assert list(form.fields) == ["html"]


@pytest.mark.django_db
def test_add_and_save_html_element(client):
    user = make_pa(client)  # logs the client in as a Platform Admin
    course = Course.objects.create(title="C", slug="c-add", owner=user)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    # Open the add form for the html type (render-only).
    add_url = reverse("courses:manage_element_add", kwargs={"slug": course.slug})
    r = client.post(
        add_url, {"unit": unit.pk, "type": "html"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert b'name="html"' in r.content  # textarea rendered

    # Persist (create-on-first-save via element=new).
    save_url = reverse("courses:manage_element_save", kwargs={"slug": course.slug})
    r = client.post(
        save_url,
        {
            "unit": unit.pk,
            "type": "html",
            "element": "new",
            "html": "<button id=b>go</button>",
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert r.status_code == 200
    assert HtmlElement.objects.filter(html="<button id=b>go</button>").exists()


@pytest.mark.django_db
def test_course_form_has_html_css_js_fields():
    from courses.forms import CourseForm

    form = CourseForm()
    assert "html_css" in form.fields
    assert "html_js" in form.fields
    # persists through the form
    form = CourseForm(
        data={
            "title": "C",
            "slug": "c-form",
            "language": "en",
            "overview": "",
            "visibility": "assigned",
            "html_css": ".q{color:red}",
            "html_js": "var X=1;",
        }
    )
    assert form.is_valid(), form.errors
    course = form.save()
    assert course.html_css == ".q{color:red}" and course.html_js == "var X=1;"


@pytest.mark.django_db
def test_lesson_sets_has_html():
    from django.test import Client

    from courses.models import Enrollment

    c = Client()
    user = make_pa(c)
    course = Course.objects.create(title="C", slug="c-les", owner=user)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    Enrollment.objects.get_or_create(student=user, course=course)
    Element.objects.create(
        unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>")
    )
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    r = c.get(url)
    assert r.status_code == 200
    assert r.context["has_html"] is True


@pytest.mark.django_db
def test_lesson_html_render_query_count_invariant(client):
    # The real guarantee: rendering MORE HTML elements must NOT add per-element
    # unit/course FK queries. Compare a 1-element page vs a 3-element page and
    # assert the query count is identical (select_related("unit__course") folds
    # the FK chain in; prefetch_related("content_object") is one query per type,
    # independent of element count).
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from courses.models import Enrollment

    user = make_pa(client)

    def build(slug, n):
        course = Course.objects.create(title="C", slug=slug, owner=user)
        unit = ContentNode.objects.create(
            course=course,
            kind=ContentNode.Kind.UNIT,
            title="U",
            unit_type=ContentNode.UnitType.LESSON,
        )
        Enrollment.objects.get_or_create(student=user, course=course)
        for i in range(n):
            Element.objects.create(
                unit=unit, content_object=HtmlElement.objects.create(html=f"<p>{i}</p>")
            )
        return reverse(
            "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
        )

    url1 = build("c-q1", 1)
    url3 = build("c-q3", 3)
    # Warm the process-global ContentType cache for BOTH models the lesson view
    # looks up (has_math → MathElement, has_html → HtmlElement). Otherwise the
    # FIRST captured request pays an uncached CT SELECT the second doesn't, making
    # len(q1) == len(q3)+1 in isolated runs (e.g. the `-k has_html` invocation).
    from django.contrib.contenttypes.models import ContentType

    from courses.models import MathElement

    ContentType.objects.get_for_model(MathElement)
    ContentType.objects.get_for_model(HtmlElement)
    with CaptureQueriesContext(connection) as q1:
        assert client.get(url1).status_code == 200
    with CaptureQueriesContext(connection) as q3:
        assert client.get(url3).status_code == 200
    assert len(q3) == len(q1), f"per-element queries leaked: {len(q1)} vs {len(q3)}"


@pytest.mark.django_db
def test_lesson_loads_html_js_only_when_has_html(client):
    from courses.models import Enrollment
    from courses.models import TextElement

    user = make_pa(client)
    # course WITH an html element
    c1 = Course.objects.create(title="A", slug="c-js-1", owner=user)
    u1 = ContentNode.objects.create(
        course=c1,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    Enrollment.objects.get_or_create(student=user, course=c1)
    Element.objects.create(
        unit=u1, content_object=HtmlElement.objects.create(html="<p>x</p>")
    )
    # course WITHOUT
    c2 = Course.objects.create(title="B", slug="c-js-2", owner=user)
    u2 = ContentNode.objects.create(
        course=c2,
        kind=ContentNode.Kind.UNIT,
        title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    Enrollment.objects.get_or_create(student=user, course=c2)
    Element.objects.create(
        unit=u2, content_object=TextElement.objects.create(body="<p>x</p>")
    )

    r1 = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": c1.slug, "node_pk": u1.pk})
    )
    r2 = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": c2.slug, "node_pk": u2.pk})
    )
    assert b"html_element.js" in r1.content
    assert b"html_element.js" not in r2.content
