"""Migration 0071: max_attempts -> attempts_mode/attempts_limit and back (spec §3.3)."""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "courses"
BEFORE = "0069_imageelement_float_right"
FIELDS = "0070_attempts_fields"
DATA = "0071_attempts_data"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


@pytest.fixture(autouse=True)
def _restore_head():
    # Teardown, not a last line: a failing assertion (or a deliberate mutant run)
    # must not leave the test DB at 0069/0070 for every later test in the process.
    yield
    call_command("migrate", APP, verbosity=0)  # the graph HEAD, never a pinned name


def _quiz_tree(apps, slug, *, course_kw=None, unit_kw=None, unit_type="quiz"):
    Course = apps.get_model(APP, "Course")
    Node = apps.get_model(APP, "ContentNode")
    course = Course.objects.create(title="M", slug=slug, **(course_kw or {}))
    unit = Node.objects.create(
        course=course, kind="unit", unit_type=unit_type, title="Q", **(unit_kw or {})
    )
    return course, unit


def _join(apps, unit, q):
    CT = apps.get_model("contenttypes", "ContentType")
    Element = apps.get_model(APP, "Element")
    ct, _ = CT.objects.get_or_create(app_label=APP, model=q._meta.model_name)
    Element.objects.create(unit=unit, content_type=ct, object_id=q.pk)


def test_forwards_maps_every_old_value():
    old = _migrate(BEFORE)
    ST = old.get_model(APP, "ShortTextQuestionElement")
    _course, unit = _quiz_tree(old, "mig-att-fwd")
    rows = {}
    for v in (1, 0, None, 5):
        q = ST.objects.create(stem="x", accepted="a", max_attempts=v)
        _join(old, unit, q)
        rows[v] = q.pk

    new = _migrate(DATA)
    NST = new.get_model(APP, "ShortTextQuestionElement")
    got = {
        v: (NST.objects.get(pk=pk).attempts_mode, NST.objects.get(pk=pk).attempts_limit)
        for v, pk in rows.items()
    }
    assert got == {
        1: ("inherit", None),
        0: ("inherit", None),  # D9
        None: ("unlimited", None),
        5: ("limited", 5),
    }
    course = new.get_model(APP, "Course").objects.get(slug="mig-att-fwd")
    assert (course.attempts_mode, course.attempts_limit) == ("limited", 1)
    node = new.get_model(APP, "ContentNode").objects.get(pk=unit.pk)
    assert (node.attempts_mode, node.attempts_limit) == ("inherit", None)
    # P4: under the migrated defaults (course limited 1, unit inherit) every old
    # value but 0 resolves to itself; 0 resolves to the course default, 1.
    effective = {1: 1, None: None, 5: 5}
    for v, want in effective.items():
        mode, limit = got[v]
        resolved = limit if mode == "limited" else (None if mode == "unlimited" else 1)
        assert resolved == want
    assert got[0][0] == "inherit"  # 0 -> course default (1), separately pinned


def test_backwards_writes_effective_values():
    new = _migrate(DATA)
    ST = new.get_model(APP, "ShortTextQuestionElement")
    _course, quiz = _quiz_tree(
        new, "mig-att-back", course_kw={"attempts_mode": "limited", "attempts_limit": 3}
    )
    Node = new.get_model(APP, "ContentNode")
    lesson = Node.objects.create(
        course=quiz.course,
        kind="unit",
        unit_type="lesson",
        title="L",
        attempts_mode="limited",
        attempts_limit=9,  # dormant: must be skipped
    )
    unl = Node.objects.create(
        course=quiz.course,
        kind="unit",
        unit_type="quiz",
        title="U",
        attempts_mode="unlimited",
    )
    cases = {}

    def add(unit, mode, limit, want):
        q = ST.objects.create(
            stem="x", accepted="a", attempts_mode=mode, attempts_limit=limit
        )
        if unit is not None:
            _join(new, unit, q)
        cases[q.pk] = want

    add(quiz, "inherit", None, 3)  # course
    add(lesson, "inherit", None, 3)  # lesson override skipped
    add(quiz, "limited", 5, 5)
    add(quiz, "unlimited", None, None)
    add(unl, "inherit", None, None)  # quiz unit unlimited
    add(None, "inherit", None, 1)  # no Element row -> 1

    old = _migrate(FIELDS)
    OST = old.get_model(APP, "ShortTextQuestionElement")
    assert {pk: OST.objects.get(pk=pk).max_attempts for pk in cases} == cases
