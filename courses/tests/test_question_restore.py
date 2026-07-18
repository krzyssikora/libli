import re

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
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
]
DEFERRED = [
    ChoiceGridQuestionElement,
    MultiGridQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    DragFillBlankQuestionElement,
]


def test_base_default_is_false():
    assert QuestionElement.RESTORABLE_IN_LESSON is False


@pytest.mark.parametrize("cls", IN_SCOPE)
def test_in_scope_types_are_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is True


@pytest.mark.parametrize("cls", DEFERRED)
def test_deferred_types_are_not_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is False


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


def test_deferred_type_persists_nothing(client):
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    row = _add(unit, obj)
    # POST a NON-empty answer for the deferred type: MatchPair.build_answer is
    # post.getlist("slot") (models.py:1761), so {"slot": ["x"]} yields ["x"], not
    # empty. This matters for falsification — with the scope gate deleted, an empty
    # answer would still hit the delete branch and store nothing (false GREEN); a
    # non-empty one takes the store branch and a row appears (true RED).
    # Uses the fragment path (fetch header): the no-JS path calls
    # full_lesson_render_context -> build_lesson_context, which unconditionally
    # get_or_creates a UnitProgress row for seen-tracking (views.py:359) regardless
    # of this feature -- that would confound the assertion below with an unrelated
    # side effect. The fragment branch has no such side effect.
    resp = client.post(
        _check_url(unit, row.pk), {"slot": ["x"]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    # isolate the scope-gate signal from any mark() error
    assert resp.status_code == 200
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


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


def test_deferred_hand_forged_blob_does_not_restore(client):
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    _seed(unit, student, obj, {"answer": [[0, 1]]})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    # Un-restored: the feedback partial is included only when element.pk ==
    # feedback_for_pk (matchpairquestionelement.html:19). A restored deferred blob
    # would emit a verdict; assert none — this is what goes RED if the restore-side
    # scope gate is deleted.
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
