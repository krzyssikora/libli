import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils.safestring import SafeString

from courses import fillblank
from courses.models import Element
from courses.models import SwitchGridElement
from courses.templatetags.courses_extras import render_switch_grid

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _grid():
    return SwitchGridElement.objects.create(
        prompt="Fix operators",
        lines=[
            {"stem": "intro static", "cyclers": []},
            {
                "stem": f"3 {_tok(0)} 3 = 9",
                "cyclers": [{"options": ["+", "-", "x"], "answer": 2}],
            },
        ],
    )


def test_render_emits_data_line_for_every_line_including_static():
    html = render_switch_grid(_grid(), eid=1)
    assert isinstance(html, SafeString)
    assert 'data-line="0"' in html  # static line still gets a container
    assert 'data-line="1"' in html


def test_render_embeds_full_option_set_but_not_answer():
    html = render_switch_grid(_grid(), eid=1)
    assert "switchgrid__option" in html
    for opt in ("+", "-", "x"):
        assert opt in html
    assert 'data-cycler="0"' in html
    assert "answer" not in html.lower()  # correct index never emitted


def test_render_shows_prompt_and_confirm():
    html = render_switch_grid(_grid(), eid=1)
    assert "Fix operators" in html
    assert "switchgrid__confirm" in html
    assert "switchgrid__summary" in html


def test_render_emits_i18n_summary_message_attrs():
    html = render_switch_grid(_grid(), eid=1)
    assert "data-success-msg=" in html  # JS reads these instead of hardcoding EN
    assert "data-retry-msg=" in html


def test_has_switch_grid_flag_when_nested_in_tab():
    # A switch grid nested inside a tab must still arm switchgrid.js. The flag is a
    # flat node.elements query (NOT scoped to parent__isnull=True), mirroring the
    # gate flags, so a nested self-check is detected -- else it ships silently
    # un-enhanced (no Check wiring) inside the tab.
    from courses.models import TabsElement
    from courses.views import build_lesson_context
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    grid = _grid()
    Element.objects.create(unit=unit, content_object=grid, parent=join, tab_id=tab_id)
    user = make_verified_user(username="student_ctx_grid_nested")
    ctx = build_lesson_context(unit, user)
    assert ctx["has_switch_grid"] is True


def test_render_via_model_render_method():
    # render() must resolve its join pk and produce the widget (moved from Task 2
    # per the ordering fix -- needs this task's template). Attach a join-row so
    # render()'s eid is non-zero, mirroring test_switchgate_context.py's helper.
    from tests.factories import make_course_with_unit

    el = _grid()
    _course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=el.pk,
    )
    html = el.render()
    assert 'class="switchgrid"' in html
