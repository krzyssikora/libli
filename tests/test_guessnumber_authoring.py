from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import GuessNumberElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_manage_element_add_renders_the_edit_partial_200(client):
    # element_add -> _host_form -> _edit_guessnumber. Row/palette tests never
    # reach this path; the reveal-gate partial was missed exactly this way,
    # 500ing TemplateDoesNotExist on the first palette click (fixed in PR #100).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "guessnumber", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"data-rte-source" in resp.content


def test_element_save_creates_the_element(client):
    # element_add is render-only; manage_element_save is the real create path,
    # and it exercises save_element's generic `else` branch — the reason the
    # form must be a ModelForm (spec §2.3.2).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "guessnumber",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),  # MANDATORY: save_element runs
            "element": "new",  # _check_token(unit.updated, ...)
            "stem": "{{42}}",  # and a missing token raises
            "tolerance": "",  # ConflictError -> 302, creating
            "success_message": "",  # NOTHING while the test passes.
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = GuessNumberElement.objects.get()
    assert el.target == Decimal("42")


def test_editor_loads_the_enhancer_script(client):
    # editor.html forgetting the <script> shipped gallery and reveal-gate with a
    # dead preview. Guard it.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert "guessnumber.js" in resp.content.decode()


def test_palette_card_present(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert 'data-add-type="guessnumber"' in resp.content.decode()


def test_each_rte_field_has_its_own_toolbar_wrapper(client):
    # wireRte resolves a toolbar via closest(".el-editor--text"); two RTE fields
    # sharing one wrapper means one Bold click mutates both surfaces.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    html = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "guessnumber", "unit": unit.pk},
    ).content.decode()
    assert html.count("el-editor--text") == 2
    assert html.count("data-rte-toolbar") == 2
    assert html.count("data-rte-source") == 2
