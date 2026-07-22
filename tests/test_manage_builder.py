import re

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_builder_requires_manage_access(client):
    make_login(client, "stranger")
    CourseFactory(slug="c1")
    assert (
        client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"})).status_code
        == 403
    )


@pytest.mark.django_db
def test_builder_renders_tree_with_scope_and_token(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, title="Foundations"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        title="Integers",
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="top"' in body
    assert "Foundations" in body and "Integers" in body
    assert "data-updated=" in body


@pytest.mark.django_db
def test_builder_links_to_media_library(client):
    # The media library page is otherwise reachable only by typing the URL; the course
    # panel must link it so it can't go orphaned again.
    owner = make_login(client, "owner")
    CourseFactory(slug="c1", owner=owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    media_url = reverse("courses:manage_media", kwargs={"slug": "c1"})
    assert f'href="{media_url}"' in resp.content.decode()


@pytest.mark.django_db
def test_empty_course_shows_empty_state(client):
    owner = make_login(client, "owner")
    CourseFactory(slug="c1", owner=owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert b"No children yet." in resp.content


@pytest.mark.django_db
def test_node_panel_for_unit_shows_settings(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Integers"
    )
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"Integers" in resp.content
    assert b"obligatory" in resp.content.lower()


@pytest.mark.django_db
def test_node_panel_idor_404_before_403(client):
    owner = make_login(client, "owner")
    CourseFactory(slug="a", owner=owner)  # course A exists; its slug is used below
    course_b = CourseFactory(slug="b", owner=owner)
    unit_b = ContentNodeFactory(course=course_b, kind="unit", unit_type="lesson")
    # pair course A's slug with course B's node pk -> 404 (not 403)
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "a", "pk": unit_b.pk})
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_rename_node_persists_html_seed_js():
    from courses import builder

    course = CourseFactory(slug="cseed")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")
    builder.rename_node(
        course,
        unit.pk,
        "U",
        unit.updated.isoformat(),
        unit_type="lesson",
        obligatory=False,
        html_seed_js="window.SEED={a:1};",
    )
    unit.refresh_from_db()
    assert unit.html_seed_js == "window.SEED={a:1};"


@pytest.mark.django_db
def test_editor_renders_unit_settings_form(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="cedset", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="U", html_seed_js="{a:1}"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "cedset", "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="html_seed_js"' in body  # seed editable on the editor page now
    assert 'name="unit_type"' in body
    assert "{a:1}" in body  # current seed shown


@pytest.mark.django_db
def test_editor_settings_save_persists_and_redirects(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="cedsave", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "cedsave"}),
        {
            "node": unit.pk,
            "token": unit.updated.isoformat(),
            "has_settings": "1",
            "ctx": "editor",
            "title": "U2",
            "unit_type": "quiz",
            "html_seed_js": "{x:9}",
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "courses:manage_editor", kwargs={"slug": "cedsave", "pk": unit.pk}
    )
    unit.refresh_from_db()
    assert unit.title == "U2"
    assert unit.unit_type == "quiz"
    assert unit.html_seed_js == "{x:9}"


@pytest.mark.django_db
def test_builder_unit_panel_is_readonly(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="cropanel", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "cropanel", "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="html_seed_js"' not in body  # seed moved to the editor
    assert 'data-op="settings"' not in body  # settings form removed from the builder


RENAME_FORM_RE = re.compile(r'<form class="tree__rename".*?</form>', re.DOTALL)


def _rename_form(html):
    m = RENAME_FORM_RE.search(html)
    assert m, "no .tree__rename form found in the builder page"
    return m.group(0)


@pytest.mark.django_db
# unit_type MUST be None for non-units: ContentNodeFactory defaults it to "lesson"
# and creates via objects.create() (no full_clean), so a kind="part" row would persist
# with a unit_type and then 422 on rename -- ContentNode.clean() raises "Only units may
# have a unit_type." (models.py:246). The repo documents this trap at
# tests/test_e2e_transfer.py:128-133.
@pytest.mark.parametrize(
    "kind,unit_type",
    [("part", None), ("chapter", None), ("section", None), ("unit", "lesson")],
)
def test_every_tree_row_title_is_an_editable_form(client, kind, unit_type):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    node = ContentNodeFactory(
        course=course, kind=kind, unit_type=unit_type, parent=None, title="Fractions"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    assert 'data-op="rename"' in form
    assert f'name="node" value="{node.pk}"' in form
    assert f'name="token" value="{node.updated.isoformat()}"' in form
    assert 'class="tree__title"' in form
    assert 'name="title"' in form
    assert 'value="Fractions"' in form
    assert "required" in form
    assert 'maxlength="200"' in form
    assert 'autocomplete="off"' in form
    assert 'spellcheck="false"' in form
    # data-select had exactly two readers (the click branch and refreshPanel); both are
    # removed by this change, so it must not be carried on ~800 rows for nothing.
    assert "data-select" not in resp.content.decode()


@pytest.mark.django_db
def test_tree_title_has_a_static_accessible_name_and_a_title_tooltip(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Fractions"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    assert 'aria-label="Title"' in form
    assert 'title="Fractions"' in form


@pytest.mark.django_db
def test_hidden_rename_submit_is_out_of_the_tab_order(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Fractions"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    form = _rename_form(resp.content.decode())
    # .visually-hidden uses the clip pattern, which keeps the element FOCUSABLE --
    # without tabindex="-1" every row would gain a second tab stop. Asserted per
    # attribute so a harmless reorder doesn't fail a test that is about tab order.
    btn = re.search(r"<button[^>]*>", form)
    assert btn, "the rename form must contain a submit button"
    assert 'class="visually-hidden"' in btn.group(0)
    assert 'type="submit"' in btn.group(0)
    assert 'tabindex="-1"' in btn.group(0)


@pytest.mark.django_db
def test_node_panel_no_longer_offers_a_rename_form(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    node = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="P"
    )
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": node.pk}),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert 'data-op="rename"' not in resp.content.decode()


def test_rename_form_partial_is_deleted():
    from pathlib import Path

    p = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "courses"
        / "manage"
        / "_rename_form.html"
    )
    assert not p.exists(), "_rename_form.html is dead code once the panel form is gone"
