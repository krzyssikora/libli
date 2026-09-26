import pytest

from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement


@pytest.mark.django_db
def test_dragfill_expected_tokens_in_order():
    q = DragFillBlankQuestionElement.objects.create(stem="￿0￿ ￿1￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    # The U+FFFF token sentinel must survive QuestionElement.save()'s sanitize_html
    # (nh3.clean) — render_selects/mark depend on it, exactly as fill-blank does.
    q.refresh_from_db()
    assert "￿0￿" in q.stem and "￿1￿" in q.stem
    assert q.expected_tokens() == ["Paris", "Madrid"]
    # PR 3 (spec 2026-09-25 §8): replaces the old REVEAL_TEMPLATE string -- the
    # in-place view replaced the list (test_only_extended_response_keeps_an_
    # answer_list is the registry guard).
    assert q.REVEAL_TEMPLATE is None


@pytest.mark.django_db
def test_matchpair_expected_tokens_are_right_in_order():
    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    assert q.expected_tokens() == ["Paris", "Madrid"]
    assert [p.left for p in q.pairs.all()] == ["France", "Spain"]
    # PR 3 (spec 2026-09-25 §8): replaces the old REVEAL_TEMPLATE string -- the
    # in-place view replaced the list (test_only_extended_response_keeps_an_
    # answer_list is the registry guard).
    assert q.REVEAL_TEMPLATE is None
