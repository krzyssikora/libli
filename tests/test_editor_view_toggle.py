from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.fixture
def editor_html(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, TextElement.objects.create(body="<p>Hello world</p>"))
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    return resp.content.decode("utf-8")


@pytest.mark.django_db
def test_view_toggle_renders_three_buttons(editor_html):
    assert "data-view-toggle" in editor_html
    for mode in ("editor", "split", "preview"):
        assert f'data-view="{mode}"' in editor_html


@pytest.mark.django_db
def test_view_toggle_hidden_by_default(editor_html):
    # The wrapper is rendered hidden so no-JS users never see a dead control.
    assert 'class="view-toggle"' in editor_html
    assert "hidden" in editor_html.split('class="view-toggle"')[1][:40]


@pytest.mark.django_db
def test_split_is_default_active(editor_html):
    assert "is-mode-split" in editor_html
    # The split button is the pressed/active one by default.
    split_btn = (
        editor_html.split('data-view="split"')[0][-120:]
        + editor_html.split('data-view="split"')[1][:120]
    )
    assert 'aria-pressed="true"' in split_btn
    assert "is-active" in split_btn


@pytest.mark.django_db
def test_prepaint_script_present(editor_html):
    assert "libli-editor-view" in editor_html


@pytest.mark.django_db
def test_preview_has_inner_wrapper(editor_html):
    assert 'class="prev-inner"' in editor_html
    assert "Hello world" in editor_html  # content still renders inside it


EDITOR_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "editor.css"
)


def test_editor_css_defines_width_model_and_toggle():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    # Page breaks the app cap, scoped to the editor page only.
    assert "body.editor-page .app-main" in css
    assert "102rem" in css
    # Single 70rem breakpoint governs split's two columns.
    assert "min-width: 70rem" in css
    assert ".editor-grid.is-mode-split" in css
    # Solo hide-rules.
    assert ".editor-grid.is-mode-editor .preview-pane" in css
    assert ".editor-grid.is-mode-preview .editor-pane" in css
    # The [hidden] override is REQUIRED because .view-toggle carries a flex display
    # that would otherwise beat the UA [hidden]{display:none} rule.
    assert ".view-toggle[hidden]" in css
    # Preview reserves its scrollbar so content stays a true 46rem.
    assert "scrollbar-gutter" in css
    assert ".prev-inner" in css


def test_editor_css_has_no_stale_stacking_breakpoints():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    # The old 720/900 stacking rules are folded into the single-column base.
    assert "max-width: 900px" not in css
