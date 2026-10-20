"""Map max_attempts onto the attempts_mode/attempts_limit pair (spec 2026-10-20 §3.3).

FROZEN: historical models only. Never import courses.models or anything that does
(courses.quiz included) -- the live code will change, and a live
QuestionElement.__subclasses__() would make a future question type raise
LookupError on every fresh migrate. The reverse step therefore restates the
three-step rule inline, on literal strings.
"""

from django.db import migrations
from django.db.models import F


def _question_models(apps):
    # Historical models drop the abstract base: find the tables by the field.
    return [
        m
        for m in apps.get_app_config("courses").get_models()
        if any(f.name == "max_attempts" for f in m._meta.get_fields())
    ]


def forwards(apps, schema_editor):
    for model in _question_models(apps):
        # 1 = the old default, 0 = a limit that could never be answered (D9).
        model.objects.filter(max_attempts__in=[0, 1]).update(
            attempts_mode="inherit", attempts_limit=None
        )
        model.objects.filter(max_attempts__isnull=True).update(
            attempts_mode="unlimited", attempts_limit=None
        )
        model.objects.filter(max_attempts__gte=2).update(
            attempts_mode="limited", attempts_limit=F("max_attempts")
        )
    apps.get_model("courses", "ContentNode").objects.update(
        attempts_mode="inherit", attempts_limit=None
    )
    apps.get_model("courses", "Course").objects.update(
        attempts_mode="limited", attempts_limit=1
    )


def _effective(question, unit):
    # The spec §4 rule, restated on literals (see the module docstring).
    if question.attempts_mode == "limited":
        return question.attempts_limit
    if question.attempts_mode == "unlimited":
        return None
    if unit is None:  # a question row with no Element join
        return 1
    if unit.unit_type == "quiz":
        if unit.attempts_mode == "limited":
            return unit.attempts_limit
        if unit.attempts_mode == "unlimited":
            return None
    course = unit.course
    return None if course.attempts_mode == "unlimited" else course.attempts_limit


def backwards(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Element = apps.get_model("courses", "Element")
    ContentNode = apps.get_model("courses", "ContentNode")
    units = {u.pk: u for u in ContentNode.objects.select_related("course")}
    for model in _question_models(apps):
        ct = ContentType.objects.filter(
            app_label="courses", model=model._meta.model_name
        ).first()
        unit_of = (
            {}
            if ct is None
            else dict(
                Element.objects.filter(content_type=ct).values_list(
                    "object_id", "unit_id"
                )
            )
        )
        for q in model.objects.only("pk", "attempts_mode", "attempts_limit"):
            q.max_attempts = _effective(q, units.get(unit_of.get(q.pk)))
            q.save(update_fields=["max_attempts"])


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("courses", "0070_attempts_fields"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
