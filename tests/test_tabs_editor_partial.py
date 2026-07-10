import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
EDITOR_HTML = ROOT / "templates/courses/manage/editor/editor.html"
BASE_SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
TABS_EDITOR_JS = ROOT / "courses/static/courses/js/tabs_editor.js"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"


# Symbols live in TWO files: `ed-*` (rich-text toolbar) in editor.html, `bi-*` (generic
# up/down/trash) in _icon_sprite.html. The tabs editor uses bi-* for reorder/delete, the
# same as _edit_gallery.html. Union both, or a valid bi-* ref reads as undefined.
def _sprite_symbols():
    text = EDITOR_HTML.read_text(encoding="utf-8") + BASE_SPRITE.read_text(
        encoding="utf-8"
    )
    return set(re.findall(r'<symbol id="([\w-]+)"', text))


def _render_form(instance):
    form = FORM_FOR_TYPE["tabs"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_tabs.html", {"form": form, "type_key": "tabs"}
    )


def test_new_tabs_form_renders_two_label_rows():
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert "data-tabs-editor" in html
    assert html.count("data-tab-row") == 2


def test_each_row_round_trips_its_id_as_a_hidden_field():
    """Ids in, ids out. Without this the delete diff sees every old id as removed
    and destroys every child, and save() mints fresh ids for the survivors."""
    el = TabsElement(
        data={
            "tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]
        }
    )
    html = _render_form(el)
    assert 'data-tab-id="taaaaaa"' in html
    assert 'data-tab-id="tbbbbbb"' in html


def test_element_row_renders_nested_children_indented():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child body"),
        parent=join,
        tab_id=tab,
    )
    html = render_to_string(
        "courses/manage/editor/_element_row.html",
        {"el": join, "obj": obj, "unit": unit, "open_form_pk": ""},
    )
    assert "element-list--nested" in html
    assert "child body" in html  # the child's own row
    assert f'data-parent="{join.pk}"' in html  # nested add menu carries scope
    assert f'data-tab="{tab}"' in html


def test_nested_add_menu_offers_only_nestable_types():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {"nested": True, "parent": join.pk, "tab": obj.data["tabs"][0]["id"]},
    )
    for blocked in ["choice-single", "slidebreak", 'data-add-type="tabs"']:
        assert blocked not in html
    assert 'data-add-type="text"' in html
    assert 'data-add-type="gallery"' in html


def test_tabs_editor_icons_resolve_to_sprite_symbols():
    """Icon-only buttons fail silently (blank) on a typo'd href, so pin every ref."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    refs = set(re.findall(r'use href="#((?:ed|bi)-[\w-]+)"', html))
    assert refs, "expected the tabs editor to use sprite icons, not glyphs"
    assert refs <= _sprite_symbols(), f"undefined symbols: {refs - _sprite_symbols()}"


def test_tabs_editor_js_icon_refs_resolve_too():
    used = set(
        re.findall(r'"((?:ed|bi)-[\w-]+)"', TABS_EDITOR_JS.read_text(encoding="utf-8"))
    )
    assert used <= _sprite_symbols(), f"undefined symbols: {used - _sprite_symbols()}"


def test_served_tabs_form_carries_the_bounds_the_js_reads(client):
    """tabs_editor.js reads data-min-tabs/data-max-tabs to disable add/remove at the
    bounds. Rendering the partial directly leaves them blank and every partial test
    still passes, so assert them on the SERVED form, where the wiring actually lives."""
    from django.urls import reverse

    from tests.factories import make_login

    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    html = resp.content.decode()
    assert 'data-min-tabs="2"' in html
    assert 'data-max-tabs="10"' in html
    assert 'maxlength="80"' in html


def test_editor_css_styles_every_tabs_editor_class():
    """The table slice shipped unstyled, permanently-visible handles because
    table_editor.js drifted from editor.css. Pin the same contract here.

    tabs_editor.js builds a new row by CLONING an existing one rather than assigning
    className, so scanning the JS alone matches nothing and the guard would pass
    vacuously. The classes live in the server-rendered partial -- scan that too.
    """
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    partial = (ROOT / "templates/courses/manage/editor/_edit_tabs.html").read_text(
        encoding="utf-8"
    )
    css = EDITOR_CSS.read_text(encoding="utf-8")

    emitted = set(re.findall(r'className = "(tabs-editor__[\w-]+)"', js))
    for attr in re.findall(r'class="([^"]*)"', partial):
        emitted.update(c for c in attr.split() if c.startswith("tabs-editor__"))

    assert emitted, (
        "expected tabs-editor__* classes in tabs_editor.js or _edit_tabs.html"
    )
    for cls in sorted(emitted):
        assert f".{cls}" in css, f"editor.css never styles .{cls}"
