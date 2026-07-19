import logging
import re

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MediaAsset
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.views import save_element_state
from tests.factories import make_course_with_unit
from tests.factories import make_student
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db  # ensure module has DB access for the tests below

IN_SCOPE = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ExtendedResponseQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
    ChoiceGridQuestionElement,
    MultiGridQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    DragFillBlankQuestionElement,
]
DEFERRED = []  # all widget types enabled this slice; base-invariant note is below


def test_base_default_is_false():
    assert QuestionElement.RESTORABLE_IN_LESSON is False


@pytest.mark.parametrize("cls", IN_SCOPE)
def test_in_scope_types_are_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is True


# test_deferred_types_are_not_restorable removed: DEFERRED is now empty (all five
# widget types enabled this slice), so a parametrize over it would iterate nothing
# and pass vacuously. The base-invariant intent it guarded still lives in
# test_base_default_is_false above, which protects future QuestionElement subclasses.


def test_save_helper_stores_and_deletes():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    save_element_state(user, unit, 7, {"answer": "x"})
    up = UnitProgress.objects.get(student=user, unit=unit)
    assert up.element_state == {"7": {"answer": "x"}}

    save_element_state(user, unit, 7, None)
    up.refresh_from_db()
    assert "7" not in up.element_state


def test_save_helper_delete_does_not_spawn_a_row():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    # No UnitProgress row exists yet; deleting a key must NOT create one.
    save_element_state(user, unit, 7, None)
    assert not UnitProgress.objects.filter(student=user, unit=unit).exists()


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _add(unit, obj):
    return Element.objects.create(unit=unit, content_object=obj)


def _enrolled(client):
    student = make_student(client, "qr_save")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return student, course, unit


def test_check_persists_shorttext_envelope_fragment_path(client):
    # JS-fragment path (X-Requested-With: fetch) — exercises the branch the lesson UI
    # actually uses, pinning that the save runs before the _wants_fragment split.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(
        _check_url(unit, row.pk), {"answer": "paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "paris"}}


def test_check_persists_fillblank_list_envelope(client):
    from courses.models import Blank

    student, course, unit = _enrolled(client)
    obj = FillBlankQuestionElement.objects.create(stem="Cap is {{paris}}.")
    Blank.objects.create(question=obj, order=1, accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"blank": ["paris"]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": ["paris"]}}


def test_check_persists_shortnumeric_envelope(client):
    student, course, unit = _enrolled(client)
    obj = ShortNumericQuestionElement.objects.create(stem="Q", value=42, tolerance=0)
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "42"})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "42"}}


def test_check_persists_choice_sorted_pk_list(client):
    student, course, unit = _enrolled(client)
    obj = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    c1 = Choice.objects.create(question=obj, text="a", is_correct=True)
    c2 = Choice.objects.create(question=obj, text="b", is_correct=True)
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"choice": [str(c2.pk), str(c1.pk)]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": sorted([c1.pk, c2.pk])}}


def test_empty_answer_deletes_key(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": "paris"}}
    )
    client.post(_check_url(unit, row.pk), {"answer": "   "})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(row.pk) not in up.element_state


def test_matchpair_check_persists_slot_list(client):
    # MatchPair is now in-scope: a non-empty check persists the slot list envelope.
    student, course, unit = _enrolled(client)
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    row = _add(unit, q)
    resp = client.post(
        _check_url(unit, row.pk), {"slot": ["cardiac"]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": ["cardiac"]}}


def test_nojs_path_also_persists(client):
    # No X-Requested-With header -> the no-JS full-page re-render path.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "paris"})  # no fetch header
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "paris"}}


def test_start_fresh_clears_question_blob(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "paris"})
    assert UnitProgress.objects.get(student=student, unit=unit).element_state
    client.post(
        reverse(
            "courses:progress_reset", kwargs={"slug": course.slug, "node_pk": unit.pk}
        )
    )
    up = UnitProgress.objects.filter(student=student, unit=unit).first()
    assert not (up and up.element_state.get(str(row.pk)))


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed(unit, student, obj, blob):
    row = Element.objects.create(unit=unit, content_object=obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): blob}
    )
    return row


def test_restore_shorttext_fills_value_and_verdict(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    _seed(unit, student, obj, {"answer": "paris"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="paris"' in body
    assert "question__verdict is-correct" in body


def test_restore_choice_checks_inputs(client):
    student, course, unit = _enrolled(client)
    obj = ChoiceQuestionElement.objects.create(stem="Q", multiple=False)
    c1 = Choice.objects.create(question=obj, text="a", is_correct=True)
    Choice.objects.create(question=obj, text="b", is_correct=False)
    _seed(unit, student, obj, {"answer": [c1.pk]})
    body = client.get(_lesson_url(unit)).content.decode()
    # the correct choice's radio is checked
    assert re.search(rf'value="{c1.pk}"[^>]*checked', body) or re.search(
        rf'checked[^>]*value="{c1.pk}"', body
    )


def test_restore_extendedresponse_incorrect_shows_guide_not_keywords(client):
    student, course, unit = _enrolled(client)
    obj = ExtendedResponseQuestionElement.objects.create(
        stem="Q", required_keywords="mitochondria"
    )
    _seed(unit, student, obj, {"answer": "totally unrelated text"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert "totally unrelated text" in body  # textarea refilled
    assert "question__reveal-guide" in body  # no-JS neutral guide
    assert "question__reveal-keywords" not in body  # NOT the per-keyword list


def test_corrupt_blob_is_fail_open(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    _seed(unit, student, obj, {"answer": {"unexpected": "dict-not-a-str"}})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert 'value="paris"' not in resp.content.decode()  # rendered un-restored


def test_corrupt_blob_logs_the_failure(client, caplog):
    # The fail-open restore path must not be SILENT: a malformed stored blob that
    # makes rehydrate/mark raise is logged (mirrors courses.state.validate_state's
    # logger.exception convention). Falsifiable: delete the logger.exception in
    # render_element's except and this goes RED.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    _seed(unit, student, obj, {"answer": {"unexpected": "dict-not-a-str"}})
    with caplog.at_level(logging.ERROR, logger="courses.templatetags.courses_extras"):
        resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert "practice-state restore failed" in caplog.text


def test_matchpair_malformed_blob_is_fail_open(client):
    # A structurally-wrong blob (list-of-lists, not slot strings) must not 500 and must
    # not emit a verdict — the render_element try/except logs and falls through.
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    MatchPair.objects.create(question=obj, left="Heart", right="cardiac")
    _seed(unit, student, obj, {"answer": [[0, 1]]})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert "question__verdict" not in resp.content.decode()


def test_restore_shortnumeric_fills_value(client):
    student, course, unit = _enrolled(client)
    obj = ShortNumericQuestionElement.objects.create(stem="Q", value=42, tolerance=0)
    _seed(unit, student, obj, {"answer": "42"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="42"' in body
    assert "question__verdict is-correct" in body


def test_restore_fillblank_fills_each_blank(client):
    # render_fill_blanks emits an <input name="blank"> only per U+FFFF token, and a
    # plain model create runs NO tokenizer (the {{..}}->token conversion happens in
    # courses.fillblank.parse, used by the builder form — not at .objects.create).
    # So seed the tokenized stem via parse(), else no input renders and value=
    # is absent.
    from courses.fillblank import parse
    from courses.models import Blank

    student, course, unit = _enrolled(client)
    # parse() -> (token_stem, blanks)
    token_stem, _blanks = parse("The capital is {{paris}}.")
    obj = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=obj, order=1, accepted="paris")
    _seed(unit, student, obj, {"answer": ["paris"]})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="paris"' in body  # the blank input is refilled with the stored value
    assert "question__verdict is-correct" in body


def test_editor_preview_does_not_restore(client):
    # Guard 4 (absent element_state) is the SOLE exclusion for the editor preview,
    # which renders in mode="lesson". Render the author's preview of a unit that has
    # a stored answer FOR ANOTHER STUDENT; the preview context carries no
    # element_state, so nothing restores.
    author = make_student(client, "qr_author")
    course, unit = make_course_with_unit(owner=author)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=obj)
    other = make_verified_user()
    UnitProgress.objects.create(
        student=other, unit=unit, element_state={str(row.pk): {"answer": "paris"}}
    )
    # The editor｜preview page (courses/urls.py:207); its kwarg is `pk`, not node_pk.
    preview_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    body = client.get(preview_url).content.decode()
    # author preview never restores another user's answer
    assert 'value="paris"' not in body


def test_render_element_prefers_live_kwargs_over_stale_blob(client):
    # Direct render_element call: the checked element's STORED blob says "STALE" but
    # the live kwargs (as check_answer's no-JS path would pass them) say "paris".
    # feedback_for_pk == row.pk marks this element as the one being checked live, so
    # the restore branch must be skipped and the live kwargs must win. Unlike the
    # end-to-end check_answer route, this bypasses save_element_state entirely, so a
    # stale blob can genuinely differ from the live answer -- deleting the
    # `element.pk != feedback_for_pk` guard makes this go RED (restore branch
    # overwrites the live kwargs with "STALE").
    from courses.templatetags.courses_extras import render_element

    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=obj)
    ctx = {"element_state": {row.pk: {"answer": "STALE"}}}
    html = render_element(
        ctx,
        row,
        feedback_for_pk=row.pk,
        submitted_values="paris",
        mark_result=obj.mark("paris"),
        mode="lesson",
    )
    assert "paris" in html and "STALE" not in html


def _image(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _seed_choicegrid(unit, student, *, chosen="B"):
    """One 1-row matrix: columns A,B; row correct=A. Seed the student's chosen
    column (default 'B' -> wrong, so the restore signal is the `checked` cell,
    not a verdict)."""
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    col_b = GridColumn.objects.create(question=q, label="B")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    picked = col_a if chosen == "A" else col_b
    row = _seed(unit, student, q, {"answer": [picked.pk]})
    return q, row, col_a, col_b


def _seed_multigrid(unit, student):
    """One 1-row multi-select grid: columns A,B; row correct={A}. Seed chosen={A}."""
    q = MultiGridQuestionElement.objects.create(stem="Q")
    col_a = MultiGridColumn.objects.create(question=q, label="A")
    col_b = MultiGridColumn.objects.create(question=q, label="B")
    r = MultiGridRow.objects.create(question=q, statement="r1")
    r.correct_columns.add(col_a)
    row = _seed(unit, student, q, {"answer": [[col_a.pk]]})
    return q, row, col_a, col_b


# The drag/matchpair restore tests seed a WRONG-but-in-pool answer (a distractor /
# a swapped token), NOT the correct one. A distractor still renders `<option
# value="X" selected>`, so the restore signal is decoupled from any
# correct-verdict rendering path -- only _seed_choicegrid needs the same care (it
# already seeds "B", the wrong column).
def _seed_matchpair(unit, student, *, chosen="renal"):  # "renal": in-pool distractor
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    row = _seed(unit, student, q, {"answer": [chosen]})
    return q, row


def _seed_dragfill(unit, student, *, chosen="Rome"):  # "Rome": in-pool distractor
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is ￿0￿", distractors="Rome"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    row = _seed(unit, student, q, {"answer": [chosen]})
    return q, row


def _seed_dragimage(unit, student, *, answer=("Lung", "Heart")):
    # swapped -> both wrong, both in pool
    course = unit.course
    q = DragToImageQuestionElement.objects.create(
        media=_image(course), alt="Diagram", distractors="Liver"
    )
    DragZone.objects.create(
        question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0
    )
    DragZone.objects.create(
        question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1
    )
    row = _seed(unit, student, q, {"answer": list(answer)})
    return q, row


def test_restore_choicegrid_checks_chosen_cell(client):
    student, course, unit = _enrolled(client)
    _q, _row, _col_a, col_b = _seed_choicegrid(unit, student, chosen="B")
    body = client.get(_lesson_url(unit)).content.decode()
    # the student's chosen column is checked
    assert f'value="{col_b.pk}" checked' in body


def test_restore_multigrid_checks_chosen_cell(client):
    student, course, unit = _enrolled(client)
    _q, _row, col_a, _col_b = _seed_multigrid(unit, student)
    body = client.get(_lesson_url(unit)).content.decode()
    assert f'value="{col_a.pk}" checked' in body


def test_restore_matchpair_selects_chosen_option(client):
    student, course, unit = _enrolled(client)
    _seed_matchpair(unit, student, chosen="renal")  # wrong-but-in-pool distractor
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="renal" selected' in body


def test_restore_dragfill_selects_chosen_option(client):
    student, course, unit = _enrolled(client)
    _seed_dragfill(unit, student, chosen="Rome")  # wrong-but-in-pool distractor
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="Rome" selected' in body


def test_restore_dragimage_selects_both_slots(client):
    student, course, unit = _enrolled(client)
    # swapped -> both wrong, both in pool
    _seed_dragimage(unit, student, answer=("Lung", "Heart"))
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="Lung" selected' in body
    assert 'value="Heart" selected' in body
