from django.db import migrations

from courses.migrations_support import body_is_empty_ish

# Inlined, NEVER derived from the live registry: a migration must not depend on
# today's set of question types.
QUESTION_MODELS = (
    "ChoiceQuestionElement",
    "ShortTextQuestionElement",
    "ExtendedResponseQuestionElement",
    "ShortNumericQuestionElement",
    "FillBlankQuestionElement",
    "DragFillBlankQuestionElement",
    "MatchPairQuestionElement",
    "ChoiceGridQuestionElement",
    "MultiGridQuestionElement",
    "DragToImageQuestionElement",
)
FIELDS = ("stem", "explanation")


def clear_blank_stems(apps, schema_editor):
    """Clear a question stem/explanation that carries no visible content (the RTE's
    cleared `<p><br></p>`), matching what QuestionElement.save() now stores. Such a
    stem rendered as a blank line above the answer controls."""
    for name in QUESTION_MODELS:
        model = apps.get_model("courses", name)
        for field in FIELDS:
            pks = [
                pk
                for pk, value in model.objects.exclude(**{field: ""}).values_list(
                    "pk", field
                )
                if body_is_empty_ish(value)
            ]
            if pks:
                model.objects.filter(pk__in=pks).update(**{field: ""})


class Migration(migrations.Migration):
    dependencies = [("courses", "0064_divider_element_choice")]
    # Reverse is a no-op: the cleared values rendered nothing visible.
    operations = [migrations.RunPython(clear_blank_stems, migrations.RunPython.noop)]
