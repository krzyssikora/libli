"""6a: the three migrations run both ways on PostgreSQL with a populated row in
every question table (the pending-trigger-events failure needs real rows)."""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from courses.models import DragToImageQuestionElement
from courses.richtext import CONCRETE_QUESTION_MODELS
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _restore_head():
    yield
    call_command("migrate", "courses", verbosity=0)  # even after a failure


def test_round_trip_with_every_question_type():
    unit = make_quiz_unit()
    rows = []
    for model in CONCRETE_QUESTION_MODELS:
        if model is DragToImageQuestionElement:
            q = DragToImageQuestionElementFactory(**attempts(5))
        else:
            q = model.objects.create(stem="x", **attempts(5))
        add_element(unit, q)
        rows.append((model, q.pk))

    executor = MigrationExecutor(connection)
    executor.migrate(
        [("courses", "0069_imageelement_float_right")]
    )  # back through 0072..0070
    executor.loader.build_graph()
    call_command("migrate", "courses", verbosity=0)  # forward to HEAD again

    for model, pk in rows:
        q = model.objects.get(pk=pk)
        assert (q.attempts_mode, q.attempts_limit) == ("limited", 5), model
