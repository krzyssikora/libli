import pytest
from django.urls import reverse
from django.utils.translation import override

from courses.models import Element
from courses.models import TabsElement
from courses.templatetags.courses_manage_extras import element_summary
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def test_element_summary_pluralises_tabs_not_class_name():
    # element_summary() translates at call time, so this assertion is only meaningful
    # under a pinned locale. LocaleMiddleware leaves whatever language the last test
    # client request negotiated active on the thread (tests/test_i18n_catalog.py leaves
    # "pl"), which would otherwise make this pass or fail on test ordering alone.
    with override("en"):
        el = TabsElement(data=TabsElement.default_data())
        assert element_summary(el) == "2 tabs"
        one = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "A"}]})
        assert element_summary(one) == "1 tab"
        assert "TabsElement" not in element_summary(el)


def test_element_summary_polish_plural_forms():
    # override() restores whatever language was active on exit; activate("en") in a
    # finally would instead force "en" onto every later test in the process.
    with override("pl"):
        five = TabsElement(
            data={"tabs": [{"id": f"t{i:06x}", "label": "x"} for i in range(5)]}
        )
        assert "TabsElement" not in element_summary(five)


def _managed(client):
    """A course whose OWNER is logged in. can_manage_course grants on ownership;
    a plain make_teacher(client) would get a 403 from every manage view."""
    owner = make_login(client, "owner")
    return make_course_with_unit(owner=owner)


def test_add_tabs_renders_the_editor_form(client):
    course, unit = _managed(client)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"data-tabs-editor" in resp.content


def test_nested_add_embeds_parent_and_tab_as_hidden_fields(client):
    course, unit = _managed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab = tabs.data["tabs"][1]["id"]
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "parent": join.pk, "tab": tab},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert f'name="parent" value="{join.pk}"' in html
    assert f'name="tab" value="{tab}"' in html


@pytest.mark.parametrize(
    "post",
    [
        # `slidebreak` is NOT in element_add's allow-tuple at all, so it 400s at the
        # "bad type" check before resolve_scope ever runs -- unconditionally, in every
        # unit type. `choicequestion` used to sit here; it now reaches resolve_scope
        # and is accepted in a lesson (see the test below).
        {"type": "slidebreak"},  # slide break inside a tab
        {"type": "extendedresponsequestion"},  # a question left OUT of the widening
    ],
)
def test_nested_add_of_a_blocked_type_is_400(client, post):
    course, unit = _managed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"unit": unit.pk, "parent": join.pk, "tab": tabs.data["tabs"][0]["id"], **post},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400


def test_nested_add_of_a_question_is_200_in_a_lesson(client):
    """`choicequestion` into a tab on a LESSON unit. Was the [post0] case of the
    parametrized 400 above, whose own view comment named it "the case here that
    reliably reaches resolve_scope and proves nesting is blocked".

    Its quiz-400 companion is the test below.
    """
    course, unit = _managed(client)  # make_course_with_unit -> a LESSON
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "unit": unit.pk,
            "parent": join.pk,
            "tab": tabs.data["tabs"][0]["id"],
            "type": "choicequestion",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200


def test_nested_add_of_a_question_is_400_in_a_quiz(client):
    """The endpoint half of the lesson-only rule: the SAME POST as the test above,
    differing only in the unit's type. element_add turns resolve_scope's NestingError
    into a 400, so this is the crafted-POST path the hidden add-menu group does not
    close."""
    course, _lesson = _managed(client)
    quiz = make_quiz_unit(course=course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=quiz, content_object=tabs)
    payload = {
        "unit": quiz.pk,
        "parent": join.pk,
        "tab": tabs.data["tabs"][0]["id"],
    }
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {**payload, "type": "choicequestion"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400
    # Not "every nested add into a quiz 400s": a text child still opens its form, so
    # the 400 above really is the question clause and not a broken fixture.
    ok = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {**payload, "type": "text"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert ok.status_code == 200


def test_nested_add_of_a_container_type_is_200(client):
    # Depth-3 slice: a tabs card inside a top-level tabs element lands at depth 2,
    # so the add form renders instead of 400ing.
    course, unit = _managed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "unit": unit.pk,
            "parent": join.pk,
            "tab": tabs.data["tabs"][0]["id"],
            "type": "tabs",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200


def test_parent_without_tab_is_400(client):
    course, unit = _managed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "parent": join.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400


def test_invalid_nested_create_keeps_scope_across_the_422_retry(client):
    """A validation error on a nested create must not silently move the element to top
    level when the author fixes it and resubmits."""
    course, unit = _managed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab = tabs.data["tabs"][1]["id"]
    save_url = reverse("courses:manage_element_save", kwargs={"slug": course.slug})
    unit.refresh_from_db()

    bad = client.post(
        save_url,
        {
            "type": "iframe",
            "unit": unit.pk,
            "element": "new",
            "url": "",
            "unit_token": unit.updated.isoformat(),
            "parent": join.pk,
            "tab": tab,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert bad.status_code == 422
    html = bad.content.decode()
    assert f'name="parent" value="{join.pk}"' in html  # scope survived the error
    assert f'name="tab" value="{tab}"' in html

    unit.refresh_from_db()
    good = client.post(
        save_url,
        {
            "type": "iframe",
            "unit": unit.pk,
            "element": "new",
            "url": "https://www.geogebra.org/m/abc",
            "title": "t",
            "unit_token": unit.updated.isoformat(),
            "parent": join.pk,
            "tab": tab,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert good.status_code == 200
    child = Element.objects.get(content_type__model="iframeelement")
    assert child.parent_id == join.pk and child.tab_id == tab  # NOT top level
