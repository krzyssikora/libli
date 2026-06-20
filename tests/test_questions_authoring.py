import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _save_payload(unit, *, multiple, rows, element="new"):
    """rows: list of (text, correct_bool)."""
    data = {
        "ctx": "editor",
        "type": "choicequestion",
        "element": element,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "stem": "<p>Pick</p>",
        "explanation": "",
        # The exact wire shape Django's HiddenInput emits for a BooleanField — single
        # posts the literal "False" (NOT empty), which is what exposes the bool("False")
        # parsing trap; the create path must coerce it via the form's BooleanField.
        "multiple": "True" if multiple else "False",
        "choices-TOTAL_FORMS": str(len(rows)),
        "choices-INITIAL_FORMS": "0",
        "choices-MIN_NUM_FORMS": "0",
        "choices-MAX_NUM_FORMS": "1000",
    }
    for i, (text, correct) in enumerate(rows):
        data[f"choices-{i}-text"] = text
        if correct:
            data[f"choices-{i}-is_correct"] = "on"
    return data


@pytest.mark.django_db
def test_add_choicequestion_is_render_only(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "choice-single", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert (
        b"choices-TOTAL_FORMS" in resp.content
    )  # the formset's management form rendered
    assert Element.objects.filter(unit=unit).count() == 0  # nothing persisted


@pytest.mark.django_db
def test_save_creates_question_and_choices_atomically(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(unit, multiple=False, rows=[("4", True), ("5", False)]),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ChoiceQuestionElement.objects.get()
    assert (
        q.multiple is False
    )  # also guards the bool("False") wire-shape trap (see below)
    assert q.choices.count() == 2
    assert Element.objects.filter(unit=unit, object_id=q.pk).count() == 1


@pytest.mark.django_db
def test_single_choice_not_mis_saved_as_multiple(client):
    # Regression for the hidden-BooleanField wire shape: HiddenInput renders
    # value="False" for a single-choice add, and bool("False") is True — the create path
    # must coerce via the form's BooleanField, not bool(post_data.get("multiple")).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(unit, multiple=False, rows=[("4", True), ("5", False)]),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert ChoiceQuestionElement.objects.get().multiple is False


@pytest.mark.django_db
def test_save_invalid_formset_returns_422_and_persists_nothing(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(unit, multiple=False, rows=[("only one", True)]),  # < 2 choices
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert ChoiceQuestionElement.objects.count() == 0  # atomic rollback
    assert Choice.objects.count() == 0
    # the 422 re-render of a SINGLE-choice create must show RADIO correct-markers —
    # guards the bool("False") wire-shape trap in _render_open_form's bound branch. In
    # single mode the is_correct markers are the only radios on the page, so if the trap
    # mis-set is_multiple=True they'd render as checkboxes and no radio would appear.
    # (Don't assert "no checkbox" — the can_delete DELETE inputs are always checkboxes.)
    assert b'type="radio"' in resp.content


@pytest.mark.django_db
def test_editor_shows_single_vs_multiple_choice_heading(client):
    # The editor must say WHICH kind of element is being edited (a choice question
    # renders no other visible type cue), distinguishing single from multiple.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    add_url = reverse("courses:manage_element_add", kwargs={"slug": course.slug})
    single = client.post(
        add_url,
        {"type": "choice-single", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b'class="editor-form__type"' in single.content
    assert b"Single choice" in single.content
    multi = client.post(
        add_url,
        {"type": "choice-multi", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"Multiple choice" in multi.content


@pytest.mark.django_db
def test_editor_shows_type_heading_for_non_choice(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "math", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b'class="editor-form__type"' in resp.content
    assert b"Math" in resp.content


def test_element_type_label_humanises_question_types():
    from courses.templatetags.courses_manage_extras import element_type_label

    class _CT:
        def __init__(self, model):
            self.model = model

    assert str(element_type_label(_CT("choicequestionelement"))) == "Choice"
    assert str(element_type_label(_CT("shorttextquestionelement"))) == "Short text"
    # unknown models still fall back to the raw model name
    assert str(element_type_label(_CT("textelement"))) == "Text"


@pytest.mark.django_db
def test_edit_cannot_flip_multiple_via_tampered_post(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    q = ChoiceQuestionElement.objects.create(stem="<p>q</p>", multiple=False)
    a = Choice.objects.create(question=q, text="a", is_correct=True)
    b = Choice.objects.create(question=q, text="b", is_correct=False)
    el = Element.objects.create(unit=unit, content_object=q)
    unit.refresh_from_db()
    payload = _save_payload(
        unit, multiple=True, rows=[("a", True), ("b", True)], element=str(el.pk)
    )
    payload["choices-INITIAL_FORMS"] = "2"
    payload["choices-0-id"] = a.pk
    payload["choices-1-id"] = b.pk
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        payload,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    # multiple is pinned server-side → still single → "two correct" is invalid → 422
    assert resp.status_code == 422
    q.refresh_from_db()
    assert q.multiple is False
    # atomic rollback: the stored choices are untouched by the rejected edit
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.is_correct is True and b.is_correct is False
    assert q.choices.count() == 2
