"""A question stem or explanation carrying no visible content must be stored as "".

Same defect as test_blank_richtext_body.py, on the question side: clearing the
stem RTE with Ctrl+A + Delete leaves `<p><br></p>` behind, `sanitize_html` keeps it
verbatim, and the student page renders an empty paragraph -- a blank line above a
choice question's options. `QuestionElement.save()` is the one choke point every
question type goes through (no subclass overrides it), so the guard lives there.
"""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from courses.models import ChoiceQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.sanitize import sanitize_html

BLANK = ["<p><br></p>", "<p></p>", "<div><br></div>", "<br>", "<p>&nbsp;</p>", "   "]
KEPT = ["<p>Hello</p>", "<p>\\(x^2\\)</p>", "<p>Hello</p><p><br></p>"]
MODELS = [ChoiceQuestionElement, ShortTextQuestionElement]
FIELDS = ["stem", "explanation"]


@pytest.mark.django_db
@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", BLANK)
def test_blank_value_is_stored_as_empty_string(model, field, value):
    obj = model.objects.create(**{field: value})
    obj.refresh_from_db()
    assert getattr(obj, field) == ""


@pytest.mark.django_db
@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", KEPT)
def test_value_with_visible_content_is_left_alone(model, field, value):
    obj = model.objects.create(**{field: value})
    obj.refresh_from_db()
    assert getattr(obj, field) == sanitize_html(value) != ""


@pytest.mark.django_db
def test_clearing_an_existing_stem_stores_empty_string():
    """The reported gesture is an UPDATE: type a stem, save, clear it, save again."""
    obj = ChoiceQuestionElement.objects.create(stem="<p>Something</p>")
    obj.stem = "<p><br></p>"
    obj.save()
    obj.refresh_from_db()
    assert obj.stem == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model",
    [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        ExtendedResponseQuestionElement,
    ],
    ids=lambda m: m.__name__,
)
def test_blank_stem_renders_no_stem_box(model):
    """Storing "" is only half the fix: an unconditional `.question__stem` div
    still carries its margin-bottom, leaving a gap above the answer controls.
    These four templates used to render it unguarded; the rest already guard on
    `{% if el.stem %}`."""
    obj = model.objects.create(stem="<p><br></p>")
    assert "question__stem" not in obj.render()
    obj = model.objects.create(stem="<p>Ask</p>")
    assert '<div class="question__stem"><p>Ask</p></div>' in obj.render()


BEFORE = [("courses", "0064_divider_element_choice")]
AFTER = [("courses", "0065_question_blank_stem_cleanup")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor


@pytest.mark.django_db(transaction=True)
def test_0065_clears_existing_blank_stems_and_explanations():
    """Historical models have no custom save(), so rows created through BEFORE's
    app registry keep the raw `<p><br></p>` -- exactly what production holds.
    Restores to the graph HEAD, never the pinned AFTER name."""
    try:
        old = _migrate(BEFORE).loader.project_state(BEFORE).apps
        OldChoice = old.get_model("courses", "ChoiceQuestionElement")
        OldShort = old.get_model("courses", "ShortTextQuestionElement")
        blank = OldChoice.objects.create(stem="<p><br></p>", explanation="<br>")
        kept = OldChoice.objects.create(stem="<p>Keep</p>", explanation="<p>Why</p>")
        other_type = OldShort.objects.create(stem="<p></p>")

        new = _migrate(AFTER).loader.project_state(AFTER).apps
        NewChoice = new.get_model("courses", "ChoiceQuestionElement")
        NewShort = new.get_model("courses", "ShortTextQuestionElement")
        row = NewChoice.objects.get(pk=blank.pk)
        assert (row.stem, row.explanation) == ("", "")
        row = NewChoice.objects.get(pk=kept.pk)
        assert (row.stem, row.explanation) == ("<p>Keep</p>", "<p>Why</p>")
        assert NewShort.objects.get(pk=other_type.pk).stem == ""
    finally:
        call_command("migrate", "courses", verbosity=0)
