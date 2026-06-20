import pytest

from courses import dnd
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement


@pytest.mark.django_db
def test_build_pool_dedups_by_normalized_text_first_wins_and_sorts():
    # "Paris" (correct) before "  paris  " (distractor): normalize-equal → first wins.
    q = DragFillBlankQuestionElement.objects.create(
        stem="￿0￿", distractors="Rome\n  paris  \nMadrid"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    pool = dnd.build_pool(q)
    # Deduped: the correct-token "Paris" survives, the "  paris  " distractor is
    # dropped.
    assert "Paris" in pool
    assert "  paris  " not in pool
    assert (
        sorted(pool, key=lambda s: s.strip().casefold()) == pool
    )  # deterministic order
    assert set(pool) == {"Paris", "Rome", "Madrid"}


@pytest.mark.django_db
def test_build_pool_drops_blank_distractor_lines():
    q = DragFillBlankQuestionElement.objects.create(
        stem="￿0￿", distractors="\n\nRome\n  \n"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    assert set(dnd.build_pool(q)) == {"Paris", "Rome"}
