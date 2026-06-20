import pytest

from courses.element_forms import build_matchpair_formset
from courses.models import MatchPairQuestionElement


def _data(rows, **extra):
    d = {
        "pairs-TOTAL_FORMS": str(len(rows)),
        "pairs-INITIAL_FORMS": "0",
        "pairs-MIN_NUM_FORMS": "0",
        "pairs-MAX_NUM_FORMS": "1000",
    }
    for i, (left, right) in enumerate(rows):
        d[f"pairs-{i}-left"] = left
        d[f"pairs-{i}-right"] = right
    d.update(extra)
    return d


@pytest.mark.django_db
def test_formset_requires_at_least_one_pair():
    fs = build_matchpair_formset(data=_data([]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_formset_valid_with_one_pair():
    fs = build_matchpair_formset(data=_data([("France", "Paris")]))
    assert fs.is_valid(), fs.errors


@pytest.mark.django_db
def test_formset_rejects_half_filled_row():
    fs = build_matchpair_formset(data=_data([("France", "")]))
    assert not fs.is_valid()
