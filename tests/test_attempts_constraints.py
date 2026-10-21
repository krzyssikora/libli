"""The attempts pair is enforced by the DB on every table (spec §3.2)."""

import pytest
from django.db import IntegrityError
from django.db import transaction

from courses.admin import ContentNodeAdmin
from courses.admin import CourseAdmin
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragToImageQuestionElement
from courses.richtext import CONCRETE_QUESTION_MODELS
from tests.factories import CourseFactory
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

BAD_PAIRS = [("limited", None), ("limited", 0), ("inherit", 3), ("unlimited", 3)]


def _row(model):
    if model is DragToImageQuestionElement:
        return DragToImageQuestionElementFactory()
    return model.objects.create(stem="x")


@pytest.mark.parametrize("model", CONCRETE_QUESTION_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("mode,limit", BAD_PAIRS)
def test_question_tables_reject(model, mode, limit):
    obj = _row(model)
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.filter(pk=obj.pk).update(attempts_mode=mode, attempts_limit=limit)


@pytest.mark.parametrize("mode,limit", BAD_PAIRS)
def test_unit_table_rejects(mode, limit):
    unit = make_quiz_unit()
    with pytest.raises(IntegrityError), transaction.atomic():
        ContentNode.objects.filter(pk=unit.pk).update(
            attempts_mode=mode, attempts_limit=limit
        )


@pytest.mark.parametrize("mode,limit", BAD_PAIRS + [("inherit", None)])
def test_course_table_rejects(mode, limit):
    course = CourseFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Course.objects.filter(pk=course.pk).update(
            attempts_mode=mode, attempts_limit=limit
        )


def test_constraint_names_fit_postgres():
    for model in [*CONCRETE_QUESTION_MODELS, ContentNode, Course]:
        names = [c.name for c in model._meta.constraints if "att" in c.name]
        assert names, model
        assert all(len(n.encode()) <= 63 for n in names), names


def test_admin_cannot_edit_attempts():
    for admin_cls in (CourseAdmin, ContentNodeAdmin):
        assert {"attempts_mode", "attempts_limit"} <= set(admin_cls.readonly_fields)
