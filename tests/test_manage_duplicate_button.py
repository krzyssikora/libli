import re
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import translation

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _builder_html(client, course):
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": course.slug}))
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
    # The tree's icons are CSS masks, not sprite <use> references -- see the
    # .icm block in builder.css for why. The class IS the icon here.
    assert "icm--duplicate" in html


def test_duplicate_button_only_on_units(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, title="U1")  # a unit
    ContentNode.objects.create(course=course, kind="chapter", title="Chap")  # not
    html = _builder_html(client, course)
    assert html.count('data-op="duplicate"') == 1  # only the unit


def test_every_tree_icon_class_has_a_mask_declared():
    """The rendered class is the only thing that makes a tree icon visible.

    Replaces the old `id="bi-duplicate"` sprite-symbol check: the tree no longer
    references the sprite, so that assertion could pass while every button in
    the tree rendered blank. A class with no matching `--icm` declaration is
    exactly that failure, and it is invisible to any HTML-only assertion.
    """
    css = (
        Path(settings.BASE_DIR) / "courses/static/courses/css/builder.css"
    ).read_text(encoding="utf-8")
    used = set()
    for name in ("_tree_node.html", "_move_buttons.html", "_tree_toggle.html"):
        html = (Path(settings.BASE_DIR) / "templates/courses/manage" / name).read_text(
            encoding="utf-8"
        )
        used.update(re.findall(r"icm--[a-z]+", html))
    assert used, "no masked icons found -- the scan is looking at the wrong files"
    for cls in sorted(used):
        assert re.search(rf"\.{cls} *{{[^}}]*--icm:", css), f"{cls} declares no mask"


def test_duplicate_label_translated_pl():
    with translation.override("pl"):
        assert translation.gettext("Duplicate") == "Duplikuj"
