import pytest

from courses import dnd
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory

pytestmark = pytest.mark.django_db


def _q(labels, distractors=""):
    q = DragToImageQuestionElementFactory(distractors=distractors)
    for i, lab in enumerate(labels):
        DragZoneFactory(question=q, correct_label=lab, order=i)
    return q


def test_mark_all_correct():
    q = _q(["A", "B"])
    r = q.mark(["A", "B"])
    assert r.correct and r.fraction == 1.0


def test_mark_partial():
    q = _q(["A", "B"])
    r = q.mark(["A", "wrong"])
    assert not r.correct and r.fraction == 0.5


def test_mark_distractor_and_forged_score_wrong():
    q = _q(["A", "B"], distractors="D")
    assert q.mark(["D", "ZZZ"]).fraction == 0.0


def test_mark_reusable_label_satisfies_two_zones():
    q = _q(["A", "A"])
    assert q.mark(["A", "A"]).fraction == 1.0


def test_mark_short_list_treats_missing_as_unfilled():
    q = _q(["A", "B"])
    assert q.mark(["A"]).fraction == 0.5  # no IndexError


def test_render_zone_selects_emits_one_select_per_zone_with_badge():
    q = _q(["A", "B"], distractors="D")
    html = str(dnd.render_zone_selects(list(q.zones.all()), dnd.build_pool(q)))
    assert html.count('name="slot"') == 2
    assert "— choose —" in html
    # badge numbers present
    assert ">1<" in html and ">2<" in html


def test_render_zone_selects_preselects_chosen():
    q = _q(["A", "B"])
    zones = list(q.zones.all())
    html = str(dnd.render_zone_selects(zones, dnd.build_pool(q), ["B", ""]))
    assert '<option value="B" selected>' in html
