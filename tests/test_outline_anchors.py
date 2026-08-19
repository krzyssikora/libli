from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

APP_CSS = (
    Path(__file__).resolve().parent.parent
    / "core"
    / "static"
    / "core"
    / "css"
    / "app.css"
)


def test_outline_rows_carry_a_node_id(client):
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    html = client.get(
        reverse("courses:course_outline", kwargs={"slug": course.slug})
    ).content.decode()
    assert f'id="node-{chapter.pk}"' in html
    assert f'id="node-{unit.pk}"' in html


def test_target_highlight_is_scoped_to_the_row_not_the_li():
    # A non-unit <li> contains the nested <ul> of every descendant, so a bare
    # `li:target { background: ... }` would tint a whole part's subtree. The id goes
    # on the <li> (it is the scroll target); the highlight goes on the row inside it.
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".outline-node:target > .outline-node__head" in css
    # After the collapsible change the selector above is inert cover for the
    # unreachable childless branch; every REAL container renders its head as the
    # <summary> of a <details>, so this twin is the live rule. Without it the
    # permalink highlight silently never lands.
    assert ".outline-node:target > .outline-node__group > .outline-node__head" in css
    assert ".outline-node:target > .outline-unit" in css
    assert "\n.outline-node:target {" not in css, "highlight must not target the <li>"


def test_outline_li_has_scroll_margin():
    # Scoped to the rule, not the file: a bare `"scroll-margin-top" in css` would pass
    # on any unrelated occurrence in a 3000-line stylesheet -- including before this
    # change was made at all.
    # Anchored on a NEWLINE: the bare substring ".outline-node {" already matches the
    # pre-existing `.outline-tree > ul > .outline-node {` rule (app.css:504), so an
    # unanchored split lands on that block and the assertion fails even after the work
    # is done correctly. Measured: "\n.outline-node {" is absent today and appears only
    # once the new standalone rule is added -- so this still falsifies.
    css = APP_CSS.read_text(encoding="utf-8")
    assert "\n.outline-node {" in css
    block = css.split("\n.outline-node {", 1)[1].split("}", 1)[0]
    assert "scroll-margin-top" in block
