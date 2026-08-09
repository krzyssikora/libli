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
    ok = _form(
        "shortnumericquestion",
        {"stem": "<p>q</p>", "value": "3,14", "tolerance": "0,01"},
    )
    assert ok.is_valid()
    assert ok.cleaned_data["value"] == "3.14"
    assert ok.cleaned_data["tolerance"] == "0.01"
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


@pytest.mark.django_db
def test_shortnumeric_form_stores_canonical_text():
    ok = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "3/2", "tolerance": "0"}
    )
    assert ok.is_valid(), ok.errors
    assert ok.cleaned_data["value"] == "3/2"
    assert ok.cleaned_data["tolerance"] == ""

    comma = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1,5", "tolerance": ""}
    )
    assert comma.is_valid()
    assert comma.cleaned_data["value"] == "1.5"


@pytest.mark.django_db
def test_shortnumeric_form_unparseable_tolerance_is_a_field_error_not_a_typeerror():
    # canonical_tolerance_text returns None for BOTH negative and unparseable, so
    # the negative re-derivation runs on "abc" too — and None < 0 raises TypeError.
    bad = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "abc"}
    )
    assert not bad.is_valid()
    assert "tolerance" in bad.errors

    zero_denominator = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "1/0"}
    )
    assert not zero_denominator.is_valid()
    assert "tolerance" in zero_denominator.errors


@pytest.mark.django_db
def test_shortnumeric_form_negative_tolerance_keeps_its_own_message():
    neg = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1", "tolerance": "-1"}
    )
    assert not neg.is_valid()
    assert any("negative" in str(e).lower() for e in neg.errors["tolerance"])


@pytest.mark.django_db
def test_shortnumeric_form_distinguishes_the_two_length_failures():
    # 64 chars: passes MaxLengthValidator, canonical form is 65 -> custom message.
    overflow = _form(
        "shortnumericquestion",
        {"stem": "<p>q</p>", "value": "." + "1" * 63, "tolerance": ""},
    )
    assert not overflow.is_valid()
    assert any("too long" in str(e).lower() for e in overflow.errors["value"])

    # >64 chars: never reaches clean_value -> Django's built-in message.
    too_many = _form(
        "shortnumericquestion", {"stem": "<p>q</p>", "value": "1" * 70, "tolerance": ""}
    )
    assert not too_many.is_valid()
    assert any("64 characters" in str(e) for e in too_many.errors["value"])


@pytest.mark.django_db
def test_shortnumeric_editor_round_trips_a_fraction_and_a_tolerance():
    from courses.element_forms import ShortNumericQuestionElementForm
    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(
        stem="?", value="3/2", tolerance="0.1"
    )
    form = ShortNumericQuestionElementForm(instance=q)
    assert form["value"].value() == "3/2"
    # Defect 3: this rendered "0.10000000" before, so inserting a digit made nine
    # decimal places and DecimalValidator refused the edit.
    assert form["tolerance"].value() == "0.1"

    # The user's exact reported sequence: change 0.1 to 0.01.
    edited = ShortNumericQuestionElementForm(
        {
            "stem": "<p>?</p>",
            "value": "3/2",
            "tolerance": "0.01",
            "marking_mode": q.marking_mode,
            "max_attempts": q.max_attempts,
            "max_marks": q.max_marks,
            "explanation": "",
        },
        instance=q,
    )
    assert edited.is_valid(), edited.errors


@pytest.mark.django_db
def test_guess_number_tolerance_error_text_is_unchanged():
    # Guards against a blanket find-replace of the msgid shared with :340.
    # The FORM_FOR_TYPE key is "guessnumber" — NOT "guessnumberquestion". The
    # "*question" suffix exists only for choicequestion / shorttextquestion /
    # shortnumericquestion / ...; the wrong key raises KeyError, which would make
    # this test error rather than pin anything.
    bad = _form(
        "guessnumber",
        {"stem": "<p>Guess {{5}}</p>", "tolerance": "abc", "success_message": ""},
    )
    assert not bad.is_valid()
    assert any("3.14 or 3,14" in str(e) for e in bad.errors["tolerance"])
