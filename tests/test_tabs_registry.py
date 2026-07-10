import pytest
from django.urls import reverse
from django.utils.translation import activate

from courses.models import Element
from courses.models import TabsElement
from courses.templatetags.courses_manage_extras import element_summary
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_element_summary_pluralises_tabs_not_class_name():
    el = TabsElement(data=TabsElement.default_data())
    assert element_summary(el) == "2 tabs"
    one = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "A"}]})
    assert element_summary(one) == "1 tab"
    assert "TabsElement" not in element_summary(el)


def test_element_summary_polish_plural_forms():
    activate("pl")
    try:
        five = TabsElement(
            data={"tabs": [{"id": f"t{i:06x}", "label": "x"} for i in range(5)]}
        )
        assert "TabsElement" not in element_summary(five)
    finally:
        activate("en")


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
        {"type": "choicequestion"},  # question inside a tab
        {"type": "slidebreak"},  # slide break inside a tab
        {"type": "tabs"},  # tabs inside a tab
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
