import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _editor(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode(), course


def test_dialog_is_rendered_with_the_picker_url(client):
    html, course = _editor(client)
    assert 'class="link-dialog"' in html
    assert reverse("courses:manage_link_picker", kwargs={"slug": course.slug}) in html


def test_dialog_is_not_inside_any_data_scope(client):
    # editor.js REPLACES the [data-scope] panes and re-runs libliInitRte. Dropped
    # inside one, the <dialog> and every listener bound to it at load are destroyed on
    # the first save -- an intermittent dead toolbar button that is painful to
    # attribute.
    #
    # Assert the DOM invariant, not source ordering: _editor_scope.html itself includes
    # _preview.html, so a future edit that moves the include INTO a swapped pane would
    # leave editor.html's tag order unchanged and keep a text-ordering check green
    # while reintroducing exactly this bug.
    from bs4 import BeautifulSoup

    html, _course = _editor(client)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(".link-dialog")
    assert node is not None, "dialog partial is not rendered at all"
    for parent in node.parents:
        assert not parent.get("data-scope"), (
            "the dialog must not sit inside a [data-scope] pane"
        )


def test_editor_loads_both_js_modules(client):
    html, _course = _editor(client)
    assert "link_apply.js" in html
    assert "link_dialog.js" in html


def test_tree_mount_is_a_named_tree(client):
    # role="tree" and the aria-label must live on the SAME element -- the mount div.
    # Delete either and every treeitem becomes an orphan with no owning tree, and
    # nothing else in the suite notices.
    html, _course = _editor(client)
    from bs4 import BeautifulSoup

    mount = BeautifulSoup(html, "html.parser").select_one("[data-link-tree]")
    assert mount is not None
    assert mount.get("role") == "tree"
    assert (mount.get("aria-label") or "").strip()


def test_dialog_buttons_are_type_button(client):
    # editor.html is full of forms; a form-associated bare <button> defaults to
    # type="submit", so Insert would POST the element form.
    html, _course = _editor(client)
    start = html.index('class="link-dialog"')
    end = html.index("</dialog>", start)
    block = html[start:end]
    assert "<button" in block
    assert block.count("<button") == block.count('type="button"')
