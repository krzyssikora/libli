"""Migration 0066: stored blank answers lose the sanitiser's HTML entities.

The builder forms sanitise a stem BEFORE fillblank.parse() pulls the {{answers}} out
of it, so every answer written through the editor was stored HTML-escaped: `{{<}}`
became the answer `&lt;`, which no student can type, so the blank could never be
marked correct. parse() now decodes; this migration repairs what is already stored.

transaction=True is MANDATORY: these tests unapply and re-apply a migration, which
cannot run inside the test's atomic block. The `finally` restore targets the
migration graph HEAD (a bare `migrate courses`), never the pinned AFTER name.
"""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("courses", "0065_question_blank_stem_cleanup")]
AFTER = [("courses", "0066_blank_answers_unescape")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor


@pytest.mark.django_db(transaction=True)
def test_0066_decodes_entities_in_every_stored_answer_kind():
    try:
        old = _migrate(BEFORE).loader.project_state(BEFORE).apps
        gate = old.get_model("courses", "FillGateElement").objects.create(
            stem="x ￿0￿ ￿1￿", answers=[["&lt;", "mniej"], ["a &amp; b"]]
        )
        plain_gate = old.get_model("courses", "FillGateElement").objects.create(
            stem="x ￿0￿", answers=[["4", "four"]]
        )
        fb = old.get_model("courses", "FillBlankQuestionElement").objects.create(
            stem="x ￿0￿"
        )
        blank = old.get_model("courses", "Blank").objects.create(
            question=fb, accepted="&gt;\nx&lt;1", order=0
        )
        df = old.get_model("courses", "DragFillBlankQuestionElement").objects.create(
            stem="x ￿0￿"
        )
        drag = old.get_model("courses", "DragBlank").objects.create(
            question=df, correct_token="&lt;", order=0
        )

        new = _migrate(AFTER).loader.project_state(AFTER).apps
        Gate = new.get_model("courses", "FillGateElement")
        assert Gate.objects.get(pk=gate.pk).answers == [["<", "mniej"], ["a & b"]]
        assert Gate.objects.get(pk=plain_gate.pk).answers == [["4", "four"]]
        assert (
            new.get_model("courses", "Blank").objects.get(pk=blank.pk).accepted
            == ">\nx<1"
        )
        assert (
            new.get_model("courses", "DragBlank").objects.get(pk=drag.pk).correct_token
            == "<"
        )
    finally:
        call_command("migrate", "courses", verbosity=0)
