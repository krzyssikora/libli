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
