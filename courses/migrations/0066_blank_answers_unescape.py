import html

from django.db import migrations


def unescape_answers(apps, schema_editor):
    """Decode the HTML entities the stem sanitiser left in stored blank answers.

    The builder forms sanitised a stem BEFORE fillblank.parse() extracted its
    {{answers}}, so `{{<}}` was stored as the answer `&lt;` -- which no student can
    type, so the blank could never be marked correct. parse() now decodes; this
    repairs what is already stored. html.unescape leaves plain text (including a
    lone `&`) unchanged, so an unaffected answer is a no-op."""
    FillGateElement = apps.get_model("courses", "FillGateElement")
    for gate in FillGateElement.objects.exclude(answers=[]).only("pk", "answers"):
        fixed = [[html.unescape(a) for a in alts] for alts in gate.answers or []]
        if fixed != gate.answers:
            FillGateElement.objects.filter(pk=gate.pk).update(answers=fixed)

    for model_name, field in (("Blank", "accepted"), ("DragBlank", "correct_token")):
        model = apps.get_model("courses", model_name)
        for pk, value in model.objects.filter(
            **{f"{field}__contains": "&"}
        ).values_list("pk", field):
            fixed = html.unescape(value)
            if fixed != value:
                model.objects.filter(pk=pk).update(**{field: fixed})


class Migration(migrations.Migration):
    dependencies = [("courses", "0065_question_blank_stem_cleanup")]
    # Reverse is a no-op: re-escaping would re-break every repaired answer.
    operations = [migrations.RunPython(unescape_answers, migrations.RunPython.noop)]
