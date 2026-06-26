import pytest

from courses.element_forms import FORM_FOR_TYPE


def _form(key, data):
    return FORM_FOR_TYPE[key](data=data)


@pytest.mark.django_db
def test_shorttext_form_requires_one_accepted_line():
    assert _form(
        "shorttextquestion", {"stem": "<p>q</p>", "accepted": "Paris"}
    ).is_valid()
    bad = _form("shorttextquestion", {"stem": "<p>q</p>", "accepted": "   \n  "})
    assert not bad.is_valid() and "accepted" in bad.errors


@pytest.mark.django_db
def test_shortnumeric_form_accepts_comma_decimal_and_rejects_negative_tolerance():
    from decimal import Decimal

    ok = _form(
        "shortnumericquestion",
        {"stem": "<p>q</p>", "value": "3,14", "tolerance": "0,01"},
    )
    assert ok.is_valid()
    assert ok.cleaned_data["value"] == Decimal("3.14")
    assert ok.cleaned_data["tolerance"] == Decimal("0.01")
    bad = _form("shortnumericquestion", {"stem": "<p>q</p>", "value": "abc"})
    assert not bad.is_valid() and "value" in bad.errors
    neg = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "-1"}
    )
    assert not neg.is_valid() and "tolerance" in neg.errors


@pytest.mark.django_db
def test_fillblank_form_parses_markers_and_rewrites_stem():
    f = _form("fillblankquestion", {"stem": "<p>The capital is {{Paris|paris}}.</p>"})
    assert f.is_valid(), f.errors
    assert f.parsed_blanks == [["Paris", "paris"]]
    assert "{{" not in f.cleaned_data["stem"]  # stem rewritten to a token
    assert "￿0￿" in f.cleaned_data["stem"]


@pytest.mark.django_db
def test_fillblank_edit_form_prefills_author_markers_not_tokens():
    # Editing a saved fill-blank shows {{answer}}, never the opaque ￿n￿ tokens.
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    q = FillBlankQuestionElement.objects.create(
        stem="Stolica Polski to ￿0￿ a Francji to ￿1￿"
    )
    Blank.objects.create(question=q, accepted="Warszawa")
    Blank.objects.create(question=q, accepted="Paris\nparis")
    initial = FORM_FOR_TYPE["fillblankquestion"](instance=q).initial["stem"]
    assert "￿" not in initial
    assert "{{Warszawa}}" in initial
    assert "{{Paris|paris}}" in initial


@pytest.mark.django_db
def test_dragfill_edit_form_prefills_author_markers_not_tokens():
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement

    q = DragFillBlankQuestionElement.objects.create(stem="Drag ￿0￿ then ￿1￿")
    DragBlank.objects.create(question=q, correct_token="alpha")
    DragBlank.objects.create(question=q, correct_token="beta")
    initial = FORM_FOR_TYPE["dragfillblankquestion"](instance=q).initial["stem"]
    assert "￿" not in initial
    assert "{{alpha}}" in initial
    assert "{{beta}}" in initial


@pytest.mark.django_db
def test_fillblank_form_rejects_stem_without_markers():
    f = _form("fillblankquestion", {"stem": "<p>no blanks here</p>"})
    assert not f.is_valid() and "stem" in f.errors


@pytest.mark.django_db
def test_fillblank_form_strips_forged_sentinel_from_author_stem():
    # An author pasting a literal U+FFFF token cannot forge a placeholder.
    f = _form("fillblankquestion", {"stem": "<p>forged ￿0￿ then {{real}}</p>"})
    assert f.is_valid(), f.errors
    assert f.parsed_blanks == [["real"]]
    # exactly one token (index 0), the real blank — the forged one was stripped
    assert f.cleaned_data["stem"].count("￿") == 2
