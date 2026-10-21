# Attempts Defaults (course → quiz → question) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-question `max_attempts` with a course default, overridable per quiz unit and per question (inherit / limited / unlimited at each level), with an optional "reset overrides" choice at course and quiz level.

**Architecture:** Each level stores `attempts_mode` + `attempts_limit`; one resolver in `courses/quiz.py` (`effective_max_attempts`) is the only reader the quiz path uses. `courses/attempts.py` is the single home of input parsing, the author-facing messages, override counting and the bulk reset. `max_attempts` is removed last (migration 0072), after every reader, form and the transfer format have moved, so any straggler fails loudly.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, factory_boy, Playwright (e2e), gettext (pl).

**Spec:** `docs/superpowers/specs/2026-10-20-attempts-defaults-design.md` — read it in full first. Its §1 owner-decision table (D1–D13, P1–P11) is **protected**: if anything in this plan seems to contradict a protected row, the spec row wins and the conflict is reported to the owner, not resolved by the implementer.

## Global Constraints

- Modes: `inherit` | `limited` | `unlimited`; the course allows only `limited` | `unlimited` (P2).
- Nothing set anywhere resolves to **1** (P1). Course default: `limited`, 1.
- `MAX_ATTEMPTS_LIMIT = 32767`.
- Only `[A]` auto-marked questions in **quiz** units use attempts (P3); the unit step of the resolver applies only when `unit.unit_type == "quiz"`.
- Raising a limit never unlocks a `locked` response (D13). No response row is ever written by this feature.
- Messages, verbatim:
  - `"Choose one of the attempts options."`
  - `"Enter a number of attempts, or choose another option."`
  - `"At most 32767 attempts. For no limit, choose 'Unlimited'."`
  - `"0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'."`
  - `"0 isn't a limit. To use the course's setting, choose 'Same as course'."`
  - `"0 isn't a limit. Choose 'Unlimited' or a number from 1."` (course level)
  - inherit labels: `"Same as quiz (currently: %(value)s)"`, `"Same as course (currently: %(value)s)"`, value `"unlimited"` when None.
- Reset radio POST values: `keep` / `reset`; anything else (or missing) = Keep.
- `FORMAT_VERSION` 17 → 18.
- Test runs: start the test-DB container first; `uv run pytest <paths>` — **never pass `-q`** (addopts already has it); e2e needs `-m e2e`; never two pytest runs against the same test DB at once; grep the pytest summary line, don't trust the exit code alone.
- Every new test must be shown RED against a mutant chosen from the failure mode it guards (each task names the mutant). Revert a mutant **by hand**, never with `git checkout` (it destroys uncommitted work).
- Code style: one `from x import y` per line (repo convention); comments explain *why*; Django template comments `{# #}` are single-line only — use `{% comment %}` for multi-line.

## Review Focus

1. **An untouched question after deploy** (inherit everywhere, course default) allows exactly one attempt, as before — pinned in Task 2 (`test_untouched_question_still_gets_one_attempt`).
2. **Junk left in a hidden limit box** (`-1`, `99999`, `abc`) after switching to *Unlimited* / *Same as …* must save, not 422 — pinned in Tasks 4, 5, 6.
3. **Editing a lesson question / lesson unit that carries a dormant override** must not touch it — pinned in Tasks 4 and 5.
4. **Importing an old (v≤17) archive** maps attempts exactly like the migration and is not rejected — pinned in Task 7.
5. **An editor left open while a reset runs** gets the stale-token conflict instead of silently re-posting the old override — pinned in Task 6.

---

## File map

| File | Responsibility |
|---|---|
| `courses/models.py` | `AttemptsMode`, `MAX_ATTEMPTS_LIMIT`, the new fields on `Course` / `ContentNode` / `QuestionElement`, the constraints (Task 8) |
| `courses/migrations/0070_attempts_fields.py` | add fields (auto-generated) |
| `courses/migrations/0071_attempts_data.py` | data mapping + reverse (hand-written, historical models only) |
| `courses/migrations/0072_attempts_constraints.py` | remove `max_attempts`, add constraints (auto-generated, Task 8) |
| `courses/quiz.py` | resolvers + readers |
| `courses/attempts.py` (new) | parsing, messages, form-field builders, counts, resets |
| `courses/element_forms.py` | `_MarkingFieldsMixin`, `marking_kwargs`, 10 `Meta.fields` |
| `courses/builder.py` | `save_element` passes `unit=`; `rename_node` attempts + reset |
| `courses/views.py`, `courses/views_manage.py`, `courses/views_analytics.py` | readers; settings save paths; editor context |
| `courses/forms.py` | `CourseForm` attempts fields + reset choice |
| `courses/admin.py` | read-only attempts fields |
| `courses/transfer/{export,payloads,schema,importer}.py` | format v18 |
| `templates/courses/manage/editor/_marking_fields.html`, `_unit_settings.html` | UI |
| `courses/static/courses/css/courses.css` | CSS-only reveal of the limit input |
| `locale/pl/LC_MESSAGES/django.po/.mo` | translations |
| `tests/factories.py` | `attempts(n)` helper |

---

### Task 1: Fields, data migration and the resolver

**Files:**
- Modify: `courses/models.py` (new enum + constant before `class Course`; fields on `Course`, `ContentNode`, `QuestionElement` — **keep `max_attempts` for now**)
- Create: `courses/migrations/0070_attempts_fields.py` (generated), `courses/migrations/0071_attempts_data.py`
- Modify: `courses/quiz.py` (three resolvers)
- Modify: `tests/factories.py` (`attempts()` helper)
- Test: `tests/test_attempts_resolver.py`, `tests/test_attempts_migration.py`

**Interfaces:**
- Produces: `courses.models.AttemptsMode` (`INHERIT="inherit"`, `LIMITED="limited"`, `UNLIMITED="unlimited"`), `courses.models.MAX_ATTEMPTS_LIMIT = 32767`; fields `attempts_mode` (CharField, max_length 9) / `attempts_limit` (PositiveSmallIntegerField, null) on all three levels; `courses.quiz.effective_course_attempts(course) -> int | None`, `effective_unit_attempts(unit) -> tuple[int | None, str]` (source `"quiz"` / `"course"`), `effective_max_attempts(question, unit) -> int | None`; `tests.factories.attempts(n) -> dict`.

- [ ] **Step 1: Write the failing resolver tests** — `tests/test_attempts_resolver.py`:

```python
"""The three-level attempts resolver (spec 2026-10-20 §4)."""

import pytest

from courses.models import ShortTextQuestionElement
from courses.quiz import effective_course_attempts
from courses.quiz import effective_max_attempts
from courses.quiz import effective_unit_attempts
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _q(mode="inherit", limit=None):
    # Unsaved is enough: the resolver only reads attributes.
    return ShortTextQuestionElement(
        stem="x", accepted="a", attempts_mode=mode, attempts_limit=limit
    )


# ((course mode, limit), (unit mode, limit), (question mode, limit), expected)
CASES = [
    (("limited", 1), ("inherit", None), ("inherit", None), 1),
    (("limited", 4), ("inherit", None), ("inherit", None), 4),
    (("unlimited", None), ("inherit", None), ("inherit", None), None),
    (("limited", 4), ("limited", 2), ("inherit", None), 2),
    (("limited", 4), ("unlimited", None), ("inherit", None), None),
    (("unlimited", None), ("limited", 2), ("inherit", None), 2),
    (("limited", 4), ("limited", 2), ("limited", 7), 7),
    (("limited", 4), ("limited", 2), ("unlimited", None), None),
    (("unlimited", None), ("unlimited", None), ("limited", 3), 3),
]


@pytest.mark.parametrize("course_kw,unit_kw,q_kw,expected", CASES)
def test_resolution_matrix(course_kw, unit_kw, q_kw, expected):
    course = CourseFactory(attempts_mode=course_kw[0], attempts_limit=course_kw[1])
    unit = make_quiz_unit(
        course=course, attempts_mode=unit_kw[0], attempts_limit=unit_kw[1]
    )
    assert effective_max_attempts(_q(*q_kw), unit) == expected


def test_nothing_set_anywhere_resolves_to_one():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    add_element(unit, q)
    assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    assert effective_max_attempts(q, unit) == 1


def test_lesson_unit_override_is_skipped():
    course = CourseFactory(attempts_mode="limited", attempts_limit=4)
    lesson = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        attempts_mode="limited",
        attempts_limit=2,
    )
    assert effective_unit_attempts(lesson) == (4, "course")
    assert effective_max_attempts(_q(), lesson) == 4


def test_unit_source_word():
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    assert effective_unit_attempts(make_quiz_unit(course=course)) == (None, "course")
    overriding = make_quiz_unit(
        course=course, attempts_mode="limited", attempts_limit=3
    )
    assert effective_unit_attempts(overriding) == (3, "quiz")
    assert effective_course_attempts(course) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_attempts_resolver.py`
Expected: FAIL — `ImportError: cannot import name 'effective_course_attempts'` (and unknown field kwargs).

- [ ] **Step 3: Add the enum, constant and fields** in `courses/models.py`.

Directly above `class Course(models.Model):`:

```python
class AttemptsMode(models.TextChoices):
    """How one level (course / quiz unit / question) sets quiz attempts (spec
    2026-10-20). INHERIT defers to the level above; the course has no level above,
    so a DB constraint (Task 8) forbids INHERIT there."""

    INHERIT = "inherit", _("Same as the level above")
    LIMITED = "limited", _("Limited")
    UNLIMITED = "unlimited", _("Unlimited")


# PositiveSmallIntegerField's own maximum: the range the old per-question limit
# accepted, so every stored value migrates, round-trips and stays editable (§3.1).
MAX_ATTEMPTS_LIMIT = 32767
```

In `Course`, after `color_bands`:

```python
    # Course-wide default for quiz questions (spec 2026-10-20). Never INHERIT.
    attempts_mode = models.CharField(
        max_length=9, choices=AttemptsMode.choices, default=AttemptsMode.LIMITED
    )
    attempts_limit = models.PositiveSmallIntegerField(null=True, blank=True, default=1)
```

In `ContentNode`, after `html_seed_js`:

```python
    # Quiz-level attempts override (spec 2026-10-20); dormant unless
    # unit_type == quiz, like `obligatory` on non-units.
    attempts_mode = models.CharField(
        max_length=9, choices=AttemptsMode.choices, default=AttemptsMode.INHERIT
    )
    attempts_limit = models.PositiveSmallIntegerField(null=True, blank=True)
```

In `QuestionElement`, directly below `max_attempts` (which stays until Task 8):

```python
    # Question-level attempts override (spec 2026-10-20). Replaces max_attempts,
    # which is removed in migration 0072 once nothing reads it.
    attempts_mode = models.CharField(
        max_length=9, choices=AttemptsMode.choices, default=AttemptsMode.INHERIT
    )
    attempts_limit = models.PositiveSmallIntegerField(null=True, blank=True)
```

- [ ] **Step 4: Generate migration 0070**

Run: `uv run python manage.py makemigrations courses --name attempts_fields`
Expected: `courses/migrations/0070_attempts_fields.py` with exactly 24 `AddField` operations (2 each on `course`, `contentnode` and the 10 question models). Read the file: no other operations, and no import from `courses.*`. If anything else appears, stop and investigate (model drift on master).

- [ ] **Step 5: Add the resolvers** to `courses/quiz.py`. Add `from courses.models import AttemptsMode` and `from courses.models import ContentNode` to the imports, then after `reveal_list_template`:

```python
def effective_course_attempts(course):
    """int >= 1, or None for unlimited: the course level alone (spec §4)."""
    if course.attempts_mode == AttemptsMode.UNLIMITED:
        return None
    return course.attempts_limit


def effective_unit_attempts(unit):
    """(value, source) for a question that inherits in `unit`: value int >= 1 or
    None (unlimited); source "quiz" when the unit decides, else "course". The unit
    step applies ONLY to a quiz unit: a lesson's dormant override (left by a
    quiz -> lesson switch, or imported) is skipped (spec §4 step 2)."""
    if unit.unit_type == ContentNode.UnitType.QUIZ:
        if unit.attempts_mode == AttemptsMode.LIMITED:
            return unit.attempts_limit, "quiz"
        if unit.attempts_mode == AttemptsMode.UNLIMITED:
            return None, "quiz"
    return effective_course_attempts(unit.course), "course"


def effective_max_attempts(question, unit):
    """THE attempts limit the quiz enforces: int >= 1, or None for unlimited.
    question -> unit -> course; steps 2-3 live in effective_unit_attempts so the
    editor's "Same as …" label and enforcement cannot disagree."""
    if question.attempts_mode == AttemptsMode.LIMITED:
        return question.attempts_limit
    if question.attempts_mode == AttemptsMode.UNLIMITED:
        return None
    return effective_unit_attempts(unit)[0]
```

- [ ] **Step 6: Add the test helper** to `tests/factories.py` (next to `add_element`):

```python
def attempts(n):
    """A question's OWN attempts setting as model kwargs (spec 2026-10-20): an int
    n >= 1 -> limited n; None -> unlimited; 0 -> inherit (D9, as migration 0071
    maps it -- `limited` 0 would violate the DB constraint). The drop-in
    replacement for the removed `max_attempts=n`."""
    if n is None:
        return {"attempts_mode": "unlimited", "attempts_limit": None}
    if n == 0:
        return {"attempts_mode": "inherit", "attempts_limit": None}
    return {"attempts_mode": "limited", "attempts_limit": n}
```

- [ ] **Step 7: Run the resolver tests** — `uv run pytest tests/test_attempts_resolver.py` → PASS.

- [ ] **Step 8: Prove the resolver tests bite.** Mutant A: delete the `if unit.unit_type == ContentNode.UnitType.QUIZ:` guard (dedent its body) → `test_lesson_unit_override_is_skipped` must FAIL. Mutant B: in `effective_max_attempts`, return `effective_unit_attempts(unit)[0]` first → matrix rows 7–9 FAIL. Revert both by hand; re-run → PASS.

- [ ] **Step 9: Write the failing migration tests** — `tests/test_attempts_migration.py`:

```python
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
```

If the historical `ContentNode` / `Element` create fails on `OrderField` (`order` NOT NULL), pass `order=0` explicitly in `_quiz_tree`, `_join` and the `Node.objects.create` calls — do not change the migration to suit the test.

- [ ] **Step 10: Run to verify it fails** — `uv run pytest tests/test_attempts_migration.py` → FAIL: `0071_attempts_data` is not a known node (`NodeNotFoundError` / `KeyError`).

- [ ] **Step 11: Write `courses/migrations/0071_attempts_data.py`** by hand:

```python
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
```

- [ ] **Step 12: Run the migration tests** — `uv run pytest tests/test_attempts_migration.py` → PASS. Then `uv run python manage.py migrate courses` (dev DB) → applies 0070, 0071.

- [ ] **Step 13: Prove they bite.** Mutant C: in `forwards`, change `max_attempts__in=[0, 1]` to `max_attempts=1` → `test_forwards_maps_every_old_value` FAILS on key `0`. Mutant D: in `_effective`, delete the `if unit.unit_type == "quiz":` line (dedent) → backwards test FAILS on the lesson row (9 ≠ 3). Revert by hand; re-run → PASS.

- [ ] **Step 14: Commit**

```bash
git add courses/models.py courses/quiz.py courses/migrations/0070_attempts_fields.py courses/migrations/0071_attempts_data.py tests/factories.py tests/test_attempts_resolver.py tests/test_attempts_migration.py
git commit -m "feat(attempts): course/quiz/question attempts fields, data migration, resolver"
```

---

### Task 2: Switch every quiz reader to the resolver (+ model-kwarg test sweep)

**Files:**
- Modify: `courses/quiz.py` (`locked_after`, `quiz_feedback_context`, `ephemeral_quiz_feedback`)
- Modify: `courses/views.py` (`build_quiz_context` ~1544, `_quiz_render_feedback` ~1658, previewer ~1768, gate ~1811, lock ~1844, Show-answer comment ~1794)
- Modify: `courses/views_manage.py` (`element_try` ~2807/2810)
- Modify: `courses/views_analytics.py` (`_quiz_answer_rows` ~412)
- Modify: every test that creates questions with `max_attempts=` or calls the three helpers (sweep below)
- Test: `tests/test_attempts_readers.py`, `tests/test_quiz_lock_rule_parity.py`

**Interfaces:**
- Consumes: Task 1 resolvers, `tests.factories.attempts`.
- Produces: `locked_after(question, result, attempt_count, *, unit)`, `quiz_feedback_context(question, response, *, unit, result=None, validation=False)`, `ephemeral_quiz_feedback(question, answer, attempt, *, unit, reveal=False)`. `unit` is keyword-only and REQUIRED on all three.

- [ ] **Step 1: Write the failing reader tests** — `tests/test_attempts_readers.py`:

```python
"""Every quiz reader enforces the RESOLVED limit (spec §4, §5.5, D13)."""

from types import SimpleNamespace

import pytest

from courses.models import Course
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.quiz import quiz_feedback_context
from courses.views_analytics import _quiz_answer_rows
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

LOCKED = b"data-quiz-locked"


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _setup(client, *, course_kw=None, unit_kw=None):
    user = make_login(client, "stu")
    course = CourseFactory(**(course_kw or {}))
    unit = make_quiz_unit(course=course, **(unit_kw or {}))
    EnrollmentFactory(student=user, course=course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    return user, unit, add_element(unit, q)  # q inherits


def _wrong(client, unit, el):
    return client.post(_url(unit, el), {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")


def test_untouched_question_still_gets_one_attempt(client):
    _user, unit, el = _setup(client)
    assert LOCKED in _wrong(client, unit, el).content


def test_inherited_quiz_limit_two(client):
    _user, unit, el = _setup(
        client, unit_kw={"attempts_mode": "limited", "attempts_limit": 2}
    )
    assert LOCKED not in _wrong(client, unit, el).content
    assert LOCKED in _wrong(client, unit, el).content
    assert _wrong(client, unit, el).status_code == 409  # 3rd refused


def test_inherited_unlimited_never_locks(client):
    _user, unit, el = _setup(
        client, course_kw={"attempts_mode": "unlimited", "attempts_limit": None}
    )
    for _ in range(5):
        assert LOCKED not in _wrong(client, unit, el).content


@pytest.mark.parametrize("level", ["course", "unit", "question"])
def test_raising_a_limit_does_not_unlock(client, level):
    """D13, at every level (spec §7.3)."""
    _user, unit, el = _setup(client)
    _wrong(client, unit, el)  # locks at the default 1
    if level == "course":
        Course.objects.filter(pk=unit.course.pk).update(attempts_limit=3)
    elif level == "unit":
        type(unit).objects.filter(pk=unit.pk).update(
            attempts_mode="limited", attempts_limit=3
        )
    else:
        type(el.content_object).objects.filter(pk=el.object_id).update(
            attempts_mode="limited", attempts_limit=3
        )
    assert _wrong(client, unit, el).status_code == 409
    assert QuestionResponse.objects.get(element=el).locked is True


def test_lowered_then_raised_limit_reopens(client):
    """§5.5: blocked only by a LOWERED limit = locked False, key never shown."""
    _user, unit, el = _setup(
        client, course_kw={"attempts_mode": "limited", "attempts_limit": 3}
    )
    _wrong(client, unit, el)
    _wrong(client, unit, el)
    Course.objects.filter(pk=unit.course.pk).update(attempts_limit=1)
    assert _wrong(client, unit, el).status_code == 409  # gate refuses
    r = QuestionResponse.objects.get(element=el)
    assert (r.locked, r.attempt_count) == (False, 2)
    page = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/")
    assert b"Paris" not in page.content  # the key was not revealed
    # Show answer is still offered: the student is NOT locked, only gated. (Use
    # the reveal-button marker the existing reveal tests assert on, e.g. in
    # tests/test_quiz_reveal_flow.py, if `name="reveal"` is not it.)
    assert b'name="reveal"' in page.content
    Course.objects.filter(pk=unit.course.pk).update(attempts_limit=3)
    assert LOCKED in _wrong(client, unit, el).content  # 3rd attempt, now the last
    assert QuestionResponse.objects.get(element=el).attempt_count == 3


def test_attempts_left_uses_the_resolved_limit():
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    q = ShortTextQuestionElement(stem="x", accepted="a", max_marks=1)
    stand_in = SimpleNamespace(locked=False, attempt_count=1, revealed_at=None)
    ctx = quiz_feedback_context(q, stand_in, unit=unit, result=None)
    assert ctx["attempts_left"] == 2


def test_analytics_attempt_max_is_resolved(client):
    user, unit, el = _setup(
        client, unit_kw={"attempts_mode": "limited", "attempts_limit": 4}
    )
    _wrong(client, unit, el)
    _wrong(client, unit, el)
    sub = QuizSubmission.objects.get(student=user, unit=unit)
    (row,) = _quiz_answer_rows(unit, sub)
    assert (row["attempt_count"], row["attempt_max"]) == (2, 4)
```

Before running, check the quiz page URL against `courses/urls.py` (`quiz_unit` route) and adjust the literal in `test_lowered_then_raised_limit_reopens` if it differs.

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_readers.py` → FAIL (the readers still read `max_attempts`, which defaults to 1: `test_inherited_quiz_limit_two` / `unlimited` / `lowered…` fail; `quiz_feedback_context` rejects `unit=`).

- [ ] **Step 3: Update `courses/quiz.py`.** Add `from courses.models import AttemptsMode` already done in Task 1. Then:

`quiz_feedback_context` — signature `def quiz_feedback_context(question, response, *, unit, result=None, validation=False):`; add to the docstring: "`unit` resolves the attempts limit (spec 2026-10-20 §4)." Replace the last block:

```python
    limit = effective_max_attempts(question, unit)
    if limit is not None and not response.locked:
        ctx["attempts_left"] = max(0, limit - response.attempt_count)
    return ctx
```

`locked_after` — signature `def locked_after(question, result, attempt_count, *, unit):`; replace the docstring paragraph about `max_attempts is not None` with:

```
    The limit is the RESOLVED one (effective_max_attempts: question -> quiz ->
    course). `limit is not None` is mandatory: None means UNLIMITED, and without
    the guard this raises
    TypeError: '>=' not supported between 'int' and 'NoneType'.
```

and the body's return:

```python
    limit = effective_max_attempts(question, unit)
    return bool(result.correct) or (limit is not None and attempt_count >= limit)
```

`ephemeral_quiz_feedback` — signature `def ephemeral_quiz_feedback(question, answer, attempt, *, unit, reveal=False):`; the internal call becomes `locked = locked_after(question, result, attempt, unit=unit)`.

- [ ] **Step 4: Update the callers.**

`courses/views.py`:
- `build_quiz_context`: `fb_ctx = quiz_feedback_context(q, r, unit=node, result=result)`
- `_quiz_render_feedback`: `fb_ctx = quiz_feedback_context(question, response, unit=node, result=result, validation=validation)`
- previewer branch: `ephemeral_quiz_feedback(question, question.build_answer(request.POST), attempt, unit=node, reveal=reveal)`
- import `effective_max_attempts` from `courses.quiz` (one-per-line), and the gate:

```python
        if revealed_result is None:
            limit = effective_max_attempts(question, node)
            if response.locked or (
                limit is not None and response.attempt_count >= limit
            ):
                return _quiz_locked_response(request, slug, node_pk)
```

- lock: `response.locked = locked_after(question, result, response.attempt_count, unit=node)`
- the Show-answer comment: replace "an author may lower max_attempts below the student's count" with "an author may lower the effective attempts limit below the student's count".

`courses/views_manage.py` `element_try`: `ephemeral_quiz_feedback(question, answer, attempt, unit=el.unit, reveal=reveal)` and `quiz_feedback_context(question, stand_in, unit=el.unit, result=result, validation=validation)`.

`courses/views_analytics.py` `_quiz_answer_rows`: `limit = effective_max_attempts(question, unit)` (import it from `courses.quiz`).

- [ ] **Step 5: Run the new tests** — `uv run pytest tests/test_attempts_readers.py` → PASS.

- [ ] **Step 5b: Prove the tests that already passed before the change bite.** `test_untouched_question_still_gets_one_attempt` — Mutant W: make `effective_course_attempts` return `None` → FAILS (never locks). `test_raising_a_limit_does_not_unlock` — Mutant X: in `quiz_answer`, before the gate, add `if response.locked and response.attempt_count < (effective_max_attempts(question, node) or 10**6): response.locked = False` → FAILS. Revert both by hand.

- [ ] **Step 6: Parity cases.** In `tests/test_quiz_lock_rule_parity.py`:
- import `attempts` from `tests.factories`;
- `_question`: `max_attempts=max_attempts` → `**attempts(max_attempts)`;
- give `_persisted_locked` and `_ephemeral_locked` a keyword `unit_kw=None` and build the unit with `make_quiz_unit(**(unit_kw or {}))`; add a `q_kw=None` keyword to `_question` used instead of `attempts(max_attempts)` when given;
- add:

```python
# Inheriting questions: the limit comes from the QUIZ unit (spec 2026-10-20).
INHERIT_CASES = [
    ({"attempts_mode": "limited", "attempts_limit": 2}, "London", 1, False),
    ({"attempts_mode": "limited", "attempts_limit": 2}, "London", 2, True),
    ({"attempts_mode": "unlimited", "attempts_limit": None}, "London", 5, False),
]


@pytest.mark.django_db
@pytest.mark.parametrize("unit_kw,answer,attempts,expected", INHERIT_CASES)
def test_both_paths_agree_when_inheriting(client, unit_kw, answer, attempts, expected):
    kw = {
        "marking_mode": "A",
        "max_attempts": None,  # ignored: q_kw below wins
        "answer": answer,
        "attempts": attempts,
        "unit_kw": unit_kw,
        "q_kw": {"attempts_mode": "inherit", "attempts_limit": None},
    }
    assert _persisted_locked(client, **kw) is expected
    assert _ephemeral_locked(client, **kw) is expected
```

(thread `q_kw` through both helpers into `_question`). Run `uv run pytest tests/test_quiz_lock_rule_parity.py` → PASS. Mutant E: in `ephemeral_quiz_feedback` replace the `locked_after(...)` call with the old inline rule `bool(result and result.correct) or (question.max_attempts is not None and attempt >= question.max_attempts)` → the persisted and ephemeral paths disagree on the inherit cases and they FAIL. Revert by hand.

- [ ] **Step 7: Sweep the model-kwarg uses in tests.** List them:

`grep -rn "max_attempts" --include=*.py tests courses/tests integrations | grep -v "MAX_ATTEMPTS\|dead_after"`

Rules (apply to every hit that is NOT a form-POST dict key `"max_attempts": …` and NOT a direct form construction — those belong to Task 4 — and NOT transfer payload dicts — Task 7):
1. `Model.objects.create(..., max_attempts=X)` / `Model(..., max_attempts=X)` / factory calls → `**attempts(X)` (import `attempts` from `tests.factories`). `X` may be a variable or `None`.
2. Kit helpers doing `kw.setdefault("max_attempts", N)` (e.g. `tests/reveal_pr2_kit.py`, `tests/reveal_pr3_kit.py`) → `kw.update(attempts(kw.pop("max_attempts", N)))` — keeps every `kit(max_attempts=…)` call site valid.
3. Local test helpers whose parameter is named `max_attempts` keep the parameter; only the model call inside changes (rule 1).
4. Assertions reading `q.max_attempts` → assert `(q.attempts_mode, q.attempts_limit)`.
5. Direct calls of `locked_after(` / `quiz_feedback_context(` / `ephemeral_quiz_feedback(` in tests (`grep -rn "locked_after(\|quiz_feedback_context(\|ephemeral_quiz_feedback(" tests courses/tests`) gain `unit=`: a real `make_quiz_unit()` when the test has DB access, otherwise `SimpleNamespace(unit_type="quiz", attempts_mode="inherit", attempts_limit=None, course=SimpleNamespace(attempts_mode="limited", attempts_limit=1))` with a one-line comment saying why.
6. e2e seeds (`tests/test_e2e_*.py`) follow rule 1 too — including helpers that DEFAULT to 0 (`_seed_matrix(..., max_attempts=0)` in `tests/test_e2e_choicegrid.py`, `_seed_multigrid(..., max_attempts=0)` in `tests/test_e2e_multigrid.py`; find others with `grep -rn "max_attempts=0" tests`): `attempts(0)` gives inherit, matching D9.
7. POST dicts built FROM a question's field (e.g. `tests/test_e2e_questions_2dii.py` ~664, `str(q.max_attempts)`) → post `q.attempts_mode` and `"" if q.attempts_limit is None else str(q.attempts_limit)` under the two new keys. Find them with `grep -rn "\.max_attempts" tests courses/tests`.

8. A dict built for a model create (e.g. `tests/test_e2e_questions_2diii.py` ~106, `kwargs["max_attempts"] = max_attempts`) → `kwargs.update(attempts(max_attempts))`.
9. Attribute assignments that LOWER/RAISE a stored limit (`q.max_attempts = X` then `q.save()` / `save(update_fields=["max_attempts"])`) → `q.attempts_mode, q.attempts_limit = attempts(X)["attempts_mode"], attempts(X)["attempts_limit"]` and `update_fields=["attempts_mode", "attempts_limit"]`. Known sites: `tests/test_analytics_student_quiz.py` ~643, `tests/test_quiz_reveal_flow.py` ~131. These are dangerous: after Task 8 the old assignment sets a plain attribute that `save()` ignores, so the test passes while testing nothing.

**Leave for later tasks** (convert them there, not here): any assertion whose value travels through the **question form** (Task 4 — e.g. `tests/test_quiz_authoring.py` ~23, which POSTs `"max_attempts": 2` and asserts the saved value) or through the **transfer / paste / duplicate** path (Task 7 — e.g. `tests/test_builder_paste_element.py` ~762–774, which asserts the copy's attempts). Until those tasks land, the form and the importer still write only `max_attempts`, so converting the assertion now makes it fail for no sweep reason. Note each deferred site in the task's commit message so Tasks 4 and 7 pick them up.

Do it file by file; do not script it blind (scripted edits fail silently — read every `git diff`).

- [ ] **Step 8: Run the touched test files** (not the whole suite — scope test runs narrowly): run each modified non-e2e test file listed by `git diff --name-only -- tests courses/tests`, in chunks of ~10 files per command. For each modified helper module that holds no tests (e.g. `tests/reveal_pr2_kit.py`, `tests/reveal_pr3_kit.py`), also run the test files that import it: `grep -rl "reveal_pr2_kit\|reveal_pr3_kit" tests | grep -v "capture_\|e2e"`. Expected: all PASS. A failure here is a sweep mistake or a reader you missed — read it, don't "fix" the expectation.

- [ ] **Step 9: Commit**

```bash
git add -A courses tests
git commit -m "feat(attempts): quiz readers enforce the resolved course/quiz/question limit"
```

---

### Task 3: `courses/attempts.py` — parsing, messages, counts, resets

**Files:**
- Create: `courses/attempts.py`
- Test: `tests/test_attempts_module.py`

**Interfaces:**
- Consumes: `AttemptsMode`, `MAX_ATTEMPTS_LIMIT`, `effective_*` (Task 1), `courses.richtext.CONCRETE_QUESTION_MODELS`.
- Produces (exact names later tasks use):
  - constants `QUESTION_MODES = UNIT_MODES = ("inherit", "limited", "unlimited")`, `COURSE_MODES = ("limited", "unlimited")`
  - `MSG_CHOOSE`, `MSG_ENTER`, `MSG_CAP`, `ZERO_MESSAGES = {"quiz": …, "course": …, "course_level": …}` (lazy)
  - `parse_attempts(mode, raw_limit, *, allowed_modes, zero_message) -> (mode, limit)`; raises `ValidationError` with `code="attempts_mode"` or `code="attempts_limit"`, nothing else
  - `inherit_label(source, value) -> str`
  - `count_question_overrides(unit_pks) -> int` (`[A]` only, non-inherit)
  - `reset_question_rows(unit_pks) -> set[int]` (all marking modes; returns touched unit pks)
  - `reset_quiz_overrides(unit) -> int` (pre-update `[A]` count; caller holds the unit lock)
  - `course_override_counts(course) -> (quizzes, questions)` (no locks; for display)
  - `reset_course_overrides(course) -> (quizzes, questions)` (locks quiz units in pk order FIRST; caller holds a transaction and writes the Course row AFTER)
  - `quiz_keep_label(n)`, `course_keep_label(quizzes, questions)`, `quiz_reset_message(n)`, `course_reset_message(quizzes, questions)` → `str`

- [ ] **Step 1: Write the failing tests** — `tests/test_attempts_module.py`:

```python
"""courses.attempts: one home for parsing, wording, counting and resetting."""

import pytest
from django.core.exceptions import ValidationError

from courses import attempts as A
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_quiz_unit

ZERO = "zero!"


def _parse(mode, raw):
    return A.parse_attempts(
        mode, raw, allowed_modes=A.QUESTION_MODES, zero_message=ZERO
    )


@pytest.mark.parametrize(
    "mode,raw,want",
    [
        ("inherit", "", ("inherit", None)),
        ("unlimited", "-1", ("unlimited", None)),  # hidden junk is harmless
        ("inherit", "abc", ("inherit", None)),
        ("unlimited", "99999", ("unlimited", None)),
        ("limited", "3", ("limited", 3)),
        ("limited", " 7 ", ("limited", 7)),
        ("limited", "32767", ("limited", 32767)),
    ],
)
def test_parse_accepts(mode, raw, want):
    assert _parse(mode, raw) == want


@pytest.mark.parametrize(
    "mode,raw,code,message",
    [
        ("", "3", "attempts_mode", A.MSG_CHOOSE),
        ("bogus", "3", "attempts_mode", A.MSG_CHOOSE),
        (None, "3", "attempts_mode", A.MSG_CHOOSE),
        ("limited", "", "attempts_limit", A.MSG_ENTER),
        ("limited", "  ", "attempts_limit", A.MSG_ENTER),
        ("limited", "abc", "attempts_limit", A.MSG_ENTER),
        ("limited", "2.5", "attempts_limit", A.MSG_ENTER),
        ("limited", "-1", "attempts_limit", A.MSG_ENTER),
        ("limited", "0", "attempts_limit", ZERO),
        ("limited", "00", "attempts_limit", ZERO),
        ("limited", "32768", "attempts_limit", A.MSG_CAP),
        ("limited", "9" * 50, "attempts_limit", A.MSG_CAP),
    ],
)
def test_parse_rejects(mode, raw, code, message):
    with pytest.raises(ValidationError) as exc:
        _parse(mode, raw)
    assert exc.value.code == code
    assert exc.value.messages == [str(message)]


def test_course_modes_reject_inherit():
    with pytest.raises(ValidationError):
        A.parse_attempts(
            "inherit", "", allowed_modes=A.COURSE_MODES, zero_message=ZERO
        )


def test_inherit_labels():
    assert A.inherit_label("quiz", 3) == "Same as quiz (currently: 3)"
    assert A.inherit_label("course", None) == "Same as course (currently: unlimited)"


@pytest.mark.parametrize(
    "q,n,want",
    [
        (0, 3, "Settings saved. 3 questions now use the course setting."),
        (1, 0, "Settings saved. 1 quiz now uses the course setting."),
        (2, 41, "Settings saved. 2 quizzes and 41 questions now use the course setting."),
        (0, 0, "Settings saved."),
    ],
)
def test_course_reset_message(q, n, want):
    assert A.course_reset_message(q, n) == want


def test_quiz_messages_and_labels():
    assert A.quiz_reset_message(0) == "Settings saved."
    assert A.quiz_reset_message(1) == "Settings saved. 1 question now uses the quiz setting."
    assert A.quiz_keep_label(5) == "Keep questions' own settings (5 questions)"
    assert A.course_keep_label(0, 41) == "Keep specific settings (41 questions have their own)"
    assert A.course_keep_label(1, 0) == "Keep specific settings (1 quiz has its own)"


def _q(unit, *, marking="A", own=None):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **(own or {})
    )
    add_element(unit, q)
    return q


@pytest.mark.django_db
def test_counts_only_auto_overrides():
    unit = make_quiz_unit()
    _q(unit, own=attempts(3))
    _q(unit, own=attempts(None))
    _q(unit, marking="N", own=attempts(2))  # [N]: not counted
    _q(unit)  # inherit: not counted
    c = ChoiceQuestionElement.objects.create(stem="?", **attempts(4))
    add_element(unit, c)  # a second table
    assert A.count_question_overrides([unit.pk]) == 3


@pytest.mark.django_db
def test_quiz_reset_scope_and_count():
    unit = make_quiz_unit()
    other = make_quiz_unit(course=unit.course)
    a = _q(unit, own=attempts(3))
    n = _q(unit, marking="N", own=attempts(2))
    keep = _q(other, own=attempts(5))
    assert A.reset_quiz_overrides(unit) == 1  # [A] count, before the update
    for q in (a, n):
        q.refresh_from_db()
        assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    keep.refresh_from_db()
    assert keep.attempts_limit == 5


@pytest.mark.django_db
def test_course_reset_scope_counts_and_bumps():
    course = CourseFactory()
    qa = make_quiz_unit(course=course, attempts_mode="limited", attempts_limit=2)
    qb = make_quiz_unit(course=course)  # inherit; only its questions override
    qc = make_quiz_unit(course=course)  # nothing to reset
    lesson = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson",
        attempts_mode="limited", attempts_limit=5,
    )
    in_a = _q(qa, own=attempts(3))
    in_b1 = _q(qb, own=attempts(4))
    in_b2 = _q(qb, own=attempts(None))
    in_b_n = _q(qb, marking="N", own=attempts(2))
    in_lesson = _q(lesson, own=attempts(7))
    before = {u.pk: u.updated for u in (qa, qb, qc, lesson)}

    assert A.course_override_counts(course) == (1, 3)
    assert A.reset_course_overrides(course) == (1, 3)

    for q in (in_a, in_b1, in_b2, in_b_n):
        q.refresh_from_db()
        assert q.attempts_mode == "inherit"
    in_lesson.refresh_from_db()
    assert in_lesson.attempts_limit == 7  # P9
    after = {u.pk: u.updated for u in ContentNode.objects.filter(pk__in=before)}
    assert after[qa.pk] > before[qa.pk]
    assert after[qb.pk] > before[qb.pk]  # question-only reset: explicit bump
    assert after[qc.pk] == before[qc.pk]
    assert after[lesson.pk] == before[lesson.pk]
    lesson.refresh_from_db()
    assert lesson.attempts_limit == 5
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_module.py` → FAIL: `ImportError: cannot import name 'attempts' from 'courses'`.

- [ ] **Step 3: Write `courses/attempts.py`:**

```python
"""Attempts settings (spec 2026-10-20): the ONE home of input parsing, the
author-facing wording, override counting and the bulk reset, shared by the
question form, the quiz settings save (builder.rename_node) and CourseForm."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from courses.models import MAX_ATTEMPTS_LIMIT
from courses.models import AttemptsMode
from courses.models import ContentNode
from courses.models import Element
from courses.models import QuestionElement

QUESTION_MODES = ("inherit", "limited", "unlimited")
UNIT_MODES = QUESTION_MODES
COURSE_MODES = ("limited", "unlimited")  # P2: the course has no level above

MSG_CHOOSE = _("Choose one of the attempts options.")
MSG_ENTER = _("Enter a number of attempts, or choose another option.")
MSG_CAP = _("At most 32767 attempts. For no limit, choose 'Unlimited'.")
# D9: the 0 message names the option actually on screen.
ZERO_MESSAGES = {
    "quiz": _("0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'."),
    "course": _(
        "0 isn't a limit. To use the course's setting, choose 'Same as course'."
    ),
    "course_level": _("0 isn't a limit. Choose 'Unlimited' or a number from 1."),
}


def parse_attempts(mode, raw_limit, *, allowed_modes, zero_message):
    """(mode, limit) from posted strings (spec §5.1/§5.2). limit is None unless the
    mode is limited, so a hidden-but-posted number is dropped, never validated.
    Raises ValidationError ONLY -- no int() on unchecked input can escape."""
    if not isinstance(mode, str) or mode not in allowed_modes:
        raise ValidationError(MSG_CHOOSE, code="attempts_mode")
    if mode != AttemptsMode.LIMITED:
        return mode, None
    text = raw_limit.strip() if isinstance(raw_limit, str) else ""
    if not text.isdecimal():  # "", "abc", "2.5", "-1"
        raise ValidationError(MSG_ENTER, code="attempts_limit")
    # Length first: int() of a huge digit string is slow and capped by CPython.
    if len(text) > len(str(MAX_ATTEMPTS_LIMIT)) or int(text) > MAX_ATTEMPTS_LIMIT:
        raise ValidationError(MSG_CAP, code="attempts_limit")
    limit = int(text)
    if limit == 0:
        raise ValidationError(zero_message, code="attempts_limit")
    return mode, limit


def inherit_label(source, value):
    """The *inherit* option label, showing the value it resolves to (P7)."""
    shown = str(value) if value is not None else gettext("unlimited")
    if source == "quiz":
        return gettext("Same as quiz (currently: %(value)s)") % {"value": shown}
    return gettext("Same as course (currently: %(value)s)") % {"value": shown}


def _question_models():
    # Derived, never hand-written: a new question type is covered automatically.
    from courses.richtext import CONCRETE_QUESTION_MODELS

    return CONCRETE_QUESTION_MODELS


def _questions_in(model, unit_pks):
    # Question rows reach their unit only through the generic Element join.
    ct = ContentType.objects.get_for_model(model)
    return model.objects.filter(
        pk__in=Element.objects.filter(
            unit_id__in=unit_pks, content_type=ct
        ).values("object_id")
    )


def count_question_overrides(unit_pks):
    """[A] questions with their own setting -- the only ones attempts affect (P3)."""
    return sum(
        _questions_in(model, unit_pks)
        .filter(marking_mode=QuestionElement.MarkingMode.AUTO)
        .exclude(attempts_mode=AttemptsMode.INHERIT)
        .count()
        for model in _question_models()
    )


def reset_question_rows(unit_pks):
    """Set every non-inherit question row in `unit_pks` to inherit ([N]/[R]
    included -- harmless). Returns the pks of units that had one (spec §5.4)."""
    touched = set()
    for model in _question_models():
        ct = ContentType.objects.get_for_model(model)
        ids = list(
            _questions_in(model, unit_pks)
            .exclude(attempts_mode=AttemptsMode.INHERIT)
            .values_list("pk", flat=True)
        )
        if not ids:
            continue
        touched |= set(
            Element.objects.filter(
                unit_id__in=unit_pks, content_type=ct, object_id__in=ids
            ).values_list("unit_id", flat=True)
        )
        model.objects.filter(pk__in=ids).update(
            attempts_mode=AttemptsMode.INHERIT, attempts_limit=None
        )
    return touched


def reset_quiz_overrides(unit):
    """Quiz-level reset. The caller (rename_node) holds the unit's row lock and its
    save(update_fields=[..., "updated"]) bumps the unit, so no bump here."""
    count = count_question_overrides([unit.pk])
    reset_question_rows([unit.pk])
    return count


def _quiz_units(course):
    return ContentNode.objects.filter(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ,
    )


def course_override_counts(course):
    """(quizzes, questions) with their own setting, for the reset choice (no locks)."""
    pks = list(_quiz_units(course).values_list("pk", flat=True))
    quizzes = (
        _quiz_units(course).exclude(attempts_mode=AttemptsMode.INHERIT).count()
    )
    return quizzes, count_question_overrides(pks)


def reset_course_overrides(course):
    """Course-level reset (spec §5.3/§5.4). The caller holds a transaction and must
    write the Course row AFTER this returns: the global lock order is quiz units
    (pk order), then course -- the order builder ops already use. Every later
    query scopes by the pks the locking SELECT returned, never a fresh
    unit_type filter, so a concurrent lesson -> quiz toggle cannot slip in."""
    units = list(
        _quiz_units(course).select_for_update().order_by("pk").only("pk", "attempts_mode")
    )
    pks = [u.pk for u in units]
    overriding = [u.pk for u in units if u.attempts_mode != AttemptsMode.INHERIT]
    questions = count_question_overrides(pks)
    touched = reset_question_rows(pks) | set(overriding)
    if overriding:
        ContentNode.objects.filter(pk__in=overriding).update(
            attempts_mode=AttemptsMode.INHERIT, attempts_limit=None
        )
    if touched:
        # Explicit: `updated` is auto_now and QuerySet.update() never applies it.
        # The bump turns an open editor's next save into the stale-token
        # "changed elsewhere" response instead of silently undoing the reset.
        ContentNode.objects.filter(pk__in=touched).update(updated=timezone.now())
    return len(overriding), questions


def _what(quizzes, questions):
    """'2 quizzes and 41 questions'; a zero part is omitted (spec §5.4)."""
    parts = []
    if quizzes:
        parts.append(
            ngettext("%(n)d quiz", "%(n)d quizzes", quizzes) % {"n": quizzes}
        )
    if questions:
        parts.append(
            ngettext("%(n)d question", "%(n)d questions", questions)
            % {"n": questions}
        )
    return gettext(" and ").join(parts)


def course_keep_label(quizzes, questions):
    return ngettext(
        "Keep specific settings (%(what)s has its own)",
        "Keep specific settings (%(what)s have their own)",
        quizzes + questions,
    ) % {"what": _what(quizzes, questions)}


def quiz_keep_label(n):
    return ngettext(
        "Keep questions' own settings (%(n)d question)",
        "Keep questions' own settings (%(n)d questions)",
        n,
    ) % {"n": n}


def course_reset_message(quizzes, questions):
    if not quizzes and not questions:
        return gettext("Settings saved.")
    return ngettext(
        "Settings saved. %(what)s now uses the course setting.",
        "Settings saved. %(what)s now use the course setting.",
        quizzes + questions,
    ) % {"what": _what(quizzes, questions)}


def quiz_reset_message(n):
    if not n:
        return gettext("Settings saved.")
    return ngettext(
        "Settings saved. %(n)d question now uses the quiz setting.",
        "Settings saved. %(n)d questions now use the quiz setting.",
        n,
    ) % {"n": n}
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_attempts_module.py` → PASS.

- [ ] **Step 5: Prove they bite.** Mutant F: remove `.filter(marking_mode=…AUTO)` from `count_question_overrides` → `test_counts_only_auto_overrides` FAILS (4 ≠ 3). Mutant G: delete the explicit `updated` bump → `after[qb.pk] > before[qb.pk]` FAILS. Mutant H: replace `if not text.isdecimal()` with a `try: int(text)` → the `"2.5"`/`"-1"` cases change code/message and FAIL. Revert each by hand.

- [ ] **Step 6: Commit**

```bash
git add courses/attempts.py tests/test_attempts_module.py
git commit -m "feat(attempts): shared parsing, wording, override counts and resets"
```

---

### Task 4: Question editor — form, template, dispatch (+ form/POST test sweep)

**Files:**
- Modify: `courses/element_forms.py` (`_MarkingFieldsMixin`, `marking_kwargs`, the 10 question forms' `Meta.fields`)
- Modify: `courses/builder.py` `save_element` (7 direct question-form constructions ~1509–1693 + the generic `else` ~1841)
- Modify: `courses/views_manage.py` `_render_open_form` (~2337), `element_form` (~2701)
- Modify: `templates/courses/manage/editor/_marking_fields.html`
- Modify: `courses/static/courses/css/courses.css` (reveal rule), `courses/static/courses/css/editor.css` (wrapper layout)
- Modify: tests that construct question forms or POST `max_attempts` (sweep)
- Test: `tests/test_attempts_question_form.py`

**Interfaces:**
- Consumes: Task 3 (`parse_attempts`, `inherit_label`, `ZERO_MESSAGES`, `MSG_CHOOSE`, `QUESTION_MODES`), Task 1 (`effective_unit_attempts`).
- Produces: every `_MarkingFieldsMixin` form requires keyword `unit=`; `courses.element_forms.marking_kwargs(form_cls, unit) -> dict`. Question POST keys `attempts_mode` / `attempts_limit`.

- [ ] **Step 1: Write the failing tests** — `tests/test_attempts_question_form.py`:

```python
"""Question editor attempts field (spec 2026-10-20 §5.1)."""

import pytest
from django.urls import reverse

from courses import attempts as A
from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ShortTextQuestionElementForm
from courses.element_forms import _MarkingFieldsMixin
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

QUESTION_FORMS = [f for f in FORM_FOR_TYPE.values() if issubclass(f, _MarkingFieldsMixin)]


def _data(**over):
    d = {
        "stem": "Capital?",
        "explanation": "",
        "accepted": "Paris",
        "marking_mode": "A",
        "max_marks": "1",
    }
    d.update(over)
    return d


def _bound(unit, instance=None, **over):
    return ShortTextQuestionElementForm(data=_data(**over), instance=instance, unit=unit)


def test_ten_question_forms():
    assert len(QUESTION_FORMS) == 10


@pytest.mark.parametrize("FormCls", QUESTION_FORMS)
def test_every_question_form_exposes_both_fields_in_a_quiz(FormCls):
    # DragToImage's _CourseScopedMediaForm defaults course=None, so all ten
    # construct with unit= alone.
    form = FormCls(unit=make_quiz_unit())
    assert {"attempts_mode", "attempts_limit"} <= set(form.fields)
    assert "max_attempts" not in form.fields


def test_unit_is_required():
    with pytest.raises(TypeError):
        ShortTextQuestionElementForm()


def test_inherit_label_names_its_source():
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    choices = dict(ShortTextQuestionElementForm(unit=unit).fields["attempts_mode"].choices)
    assert choices["inherit"] == "Same as quiz (currently: 3)"
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    form = ShortTextQuestionElementForm(unit=make_quiz_unit(course=course))
    assert dict(form.fields["attempts_mode"].choices)["inherit"] == (
        "Same as course (currently: unlimited)"
    )


def test_limit_input_has_no_min_or_max():
    html = str(ShortTextQuestionElementForm(unit=make_quiz_unit())["attempts_limit"])
    assert "min=" not in html and "max=" not in html


def test_saves_limited():
    form = _bound(make_quiz_unit(), attempts_mode="limited", attempts_limit="4")
    assert form.is_valid(), form.errors
    q = form.save()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 4)


@pytest.mark.parametrize("junk", ["-1", "99999", "abc"])
@pytest.mark.parametrize("mode", ["unlimited", "inherit"])
def test_hidden_junk_is_harmless(mode, junk):
    form = _bound(make_quiz_unit(), attempts_mode=mode, attempts_limit=junk)
    assert form.is_valid(), form.errors
    q = form.save()
    assert (q.attempts_mode, q.attempts_limit) == (mode, None)


@pytest.mark.parametrize(
    "unit_kw,raw,field,message",
    [
        ({}, "", "attempts_limit", A.MSG_ENTER),
        ({}, "0", "attempts_limit", A.ZERO_MESSAGES["course"]),
        ({"attempts_mode": "limited", "attempts_limit": 2}, "0", "attempts_limit",
         A.ZERO_MESSAGES["quiz"]),
        ({}, "40000", "attempts_limit", A.MSG_CAP),
    ],
)
def test_limit_errors(unit_kw, raw, field, message):
    form = _bound(make_quiz_unit(**unit_kw), attempts_mode="limited", attempts_limit=raw)
    assert not form.is_valid()
    assert form.errors[field] == [str(message)]


@pytest.mark.parametrize("mode", ["", "bogus"])
def test_mode_errors(mode):
    form = _bound(make_quiz_unit(), attempts_mode=mode, attempts_limit="3")
    assert form.errors["attempts_mode"] == [str(A.MSG_CHOOSE)]


def test_absent_mode_keeps_stored_values():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", **attempts(3))
    form = _bound(unit, instance=q)  # no attempts keys posted
    assert form.is_valid(), form.errors
    form.save()
    q.refresh_from_db()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 3)


def test_lesson_question_ignores_crafted_attempts_keys():
    lesson = ContentNodeFactory(kind="unit", unit_type="lesson")
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", **attempts(3))
    form = _bound(lesson, instance=q, attempts_mode="unlimited", attempts_limit="")
    assert "attempts_mode" not in form.fields
    assert form.is_valid(), form.errors
    form.save()
    q.refresh_from_db()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 3)


def test_editor_renders_the_select(client):
    make_pa(client)
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    el = add_element(unit, q)
    url = reverse("courses:manage_element_form", kwargs={"slug": unit.course.slug, "pk": el.pk})
    html = client.get(url).content.decode()
    assert 'name="attempts_mode"' in html
    assert "Same as course (currently: 1)" in html
    assert "data-attempts-limit" in html
```

Check the URL name for `element_form` in `courses/urls.py` and adjust `manage_element_form` if different.

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_question_form.py` → FAIL (`max_attempts` still a form field; `unit=` rejected).

- [ ] **Step 3: Rewrite `_MarkingFieldsMixin`** in `courses/element_forms.py` (add imports, one per line: `from django.core.exceptions import ValidationError`, `from courses import attempts as attempts_rules`, `from courses.models import ContentNode`, `from courses.quiz import effective_unit_attempts`):

```python
class _MarkingFieldsMixin:
    """Marking fields for every question form, and the owner of the attempts pair.

    marking_mode / max_marks have model defaults: omitted from POST (non-quiz forms
    hide them), construct_instance skips them and the defaults apply. Zero-rejection
    for max_marks is the model's MinValueValidator via _post_clean().

    The attempts pair is different (spec 2026-10-20 §5.1). `attempts_limit` has NO
    model default, so Django's omitted-field rule would write NULL over a stored
    limit -- `limited` + NULL violates the DB constraint (500). So both attempts
    fields are REMOVED unless the unit is a quiz and, when bound, the mode key was
    posted: a removed field never reaches cleaned_data, so construct_instance
    leaves the stored values alone (lesson questions, crafted POSTs).

    `unit` is required, with no None fallback: a missed construction site must be a
    TypeError, not a silently wrong "Same as …" label."""

    def __init__(self, *args, unit, **kwargs):
        super().__init__(*args, **kwargs)
        self.unit = unit
        for field_name in ("marking_mode", "max_marks"):
            if field_name in self.fields:
                self.fields[field_name].required = False
                self.fields[field_name].widget.attrs["class"] = "input"
        posted = not self.is_bound or self.add_prefix("attempts_mode") in self.data
        if unit.unit_type != ContentNode.UnitType.QUIZ or not posted:
            self.fields.pop("attempts_mode", None)
            self.fields.pop("attempts_limit", None)
            return
        value, self._attempts_source = effective_unit_attempts(unit)
        # Replacing the auto-generated fields keeps their position (Meta.fields
        # order: mode before limit, which clean_attempts_limit relies on).
        self.fields["attempts_mode"] = forms.ChoiceField(
            label=_("Attempts"),
            choices=[
                ("inherit", attempts_rules.inherit_label(self._attempts_source, value)),
                ("limited", _("Limited to…")),
                ("unlimited", _("Unlimited")),
            ],
            error_messages={
                "required": attempts_rules.MSG_CHOOSE,
                "invalid_choice": attempts_rules.MSG_CHOOSE,
            },
            widget=forms.Select(attrs={"class": "input"}),
        )
        # A plain CharField: no min/max widget attrs (the browser would block 0
        # with its own text and the D9 message would never show) and no validators
        # (a hidden, irrelevant value must not 422 on an invisible field).
        self.fields["attempts_limit"] = forms.CharField(
            required=False,
            label=_("Number of attempts"),
            help_text=attempts_rules.ZERO_MESSAGES[self._attempts_source],
            widget=forms.TextInput(attrs={"class": "input", "inputmode": "numeric"}),
        )

    def clean_attempts_limit(self):
        mode = self.cleaned_data.get("attempts_mode")
        if mode is None:  # the mode failed; its own field carries the error
            return None
        return attempts_rules.parse_attempts(
            mode,
            self.cleaned_data.get("attempts_limit"),
            allowed_modes=attempts_rules.QUESTION_MODES,
            zero_message=attempts_rules.ZERO_MESSAGES[self._attempts_source],
        )[1]


def marking_kwargs(form_cls, unit):
    """{"unit": unit} for a question form, else {}: the shared FORM_FOR_TYPE
    dispatch passes it so non-question forms are unchanged (spec §5.1)."""
    return {"unit": unit} if issubclass(form_cls, _MarkingFieldsMixin) else {}
```

Note `clean_attempts_limit` returns `parse_attempts(...)[1]`; `parse_attempts` raises `ValidationError`, which Django attaches to `attempts_limit` (the mode is already valid at that point, so only `attempts_limit` codes can occur).

If a circular import appears (`courses.quiz` → … → `courses.element_forms`), move the two attempts imports inside `__init__` / `clean_attempts_limit` with a comment saying why.

- [ ] **Step 4: `Meta.fields`** — in each of the 10 question forms replace `"max_attempts",` with `"attempts_mode",` and `"attempts_limit",` (in that order, same position). Verify: `grep -n "max_attempts" courses/element_forms.py` → no hits.

- [ ] **Step 5: Pass `unit` at every construction site.**
- `courses/builder.py` `save_element`: add `unit=unit` to the `ChoiceQuestionElementForm`, `FillBlankQuestionElementForm`, `DragFillBlankQuestionElementForm`, `MatchPairQuestionElementForm`, `ChoiceGridQuestionElementForm`, `MultiGridQuestionElementForm` and `DragToImageQuestionElementForm` constructions; in the generic `else` branch:

```python
        from courses.element_forms import marking_kwargs

        extra = {"course": course} if type_key in COURSE_SCOPED_TYPE_KEYS else {}
        form_cls = FORM_FOR_TYPE[type_key]
        extra.update(marking_kwargs(form_cls, unit))
        form = form_cls(data=post_data, files=files, instance=instance, **extra)
```
- `courses/views_manage.py` `_render_open_form`: after building `extra`, `extra.update(marking_kwargs(FORM_FOR_TYPE[type_key], unit))` (import `marking_kwargs` next to `FORM_FOR_TYPE`); `element_form`: `extra.update(marking_kwargs(FORM_FOR_TYPE[type_key], el.unit))`.
- Confirm none is left: `grep -rnE "(ChoiceQuestion|ShortTextQuestion|ShortNumericQuestion|FillBlankQuestion|DragFillBlankQuestion|MatchPairQuestion|ChoiceGridQuestion|MultiGridQuestion|DragToImageQuestion|ExtendedResponseQuestion)ElementForm\(" courses | grep -vE ":\s*class "` — every remaining production hit passes `unit=` (or goes through `marking_kwargs`).

- [ ] **Step 6: Template** — in `templates/courses/manage/editor/_marking_fields.html` replace the three `max_attempts` lines with:

```django
      {% if "attempts_mode" in form.fields %}
      <label class="el-editor__label" for="{{ form.attempts_mode.id_for_label }}">{{ form.attempts_mode.label }}</label>
      {{ form.attempts_mode }}
      {% for e in form.attempts_mode.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
      <div class="attempts-limit" data-attempts-limit>
        <label class="el-editor__label" for="{{ form.attempts_limit.id_for_label }}">{{ form.attempts_limit.label }}</label>
        {{ form.attempts_limit }}
        <p class="helptext">{{ form.attempts_limit.help_text }}</p>
        {% for e in form.attempts_limit.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
      </div>
      {% endif %}
```

- [ ] **Step 7: CSS reveal** — append to `courses/static/courses/css/courses.css` (loaded by both the editor and the course form):

```css
/* Attempts (spec 2026-10-20 §5.1): the limit input shows only while "Limited to…"
   is selected. CSS-only on purpose -- nothing to re-run after an editor fragment
   swap or a 422 re-render. Scoped per <form>: the editor page holds several. */
form:has(select[name="attempts_mode"] option[value="limited"]:not(:checked))
  :is([data-attempts-limit], [data-field="attempts_limit"]) {
  display: none;
}
```

And give the wrapper its own layout in `courses/static/courses/css/editor.css`, next to the `[data-marks-fields]` rule (it is one grid item there, so its label/input/help would otherwise stack with no gap):

```css
/* Must stay LESS specific than the courses.css :has() hide rule, which has to win
   whenever "Limited to…" is not selected. */
.el-editor__marking-fields [data-attempts-limit] { display: grid; gap: var(--space-3); }
```

Check the spacing in the Task 10 screenshots. Then run every CSS source test: `uv run pytest $(ls tests/test_*css*.py)` → PASS (a new rule can duplicate text marker tests partition on).

- [ ] **Step 8: Run the new tests** — `uv run pytest tests/test_attempts_question_form.py` → PASS.

- [ ] **Step 9: Prove they bite.** Mutant I: in the mixin, drop the `or not posted` clause → `test_absent_mode_keeps_stored_values` FAILS (or 500s on the constraint once Task 8 lands — either way RED). Mutant J: give `attempts_limit` back `PositiveSmallIntegerField` semantics (`forms.IntegerField(min_value=0)`) → `test_hidden_junk_is_harmless["abc"]` and `test_limit_input_has_no_min_or_max` FAIL. Mutant K: drop `"attempts_limit"` from one form's `Meta.fields` → its parametrised exposure test FAILS. Revert each by hand.

- [ ] **Step 10: Sweep form constructions and POST dicts in tests.**
- `grep -rnE "QuestionElementForm\(" tests courses/tests` — add `unit=` (a `make_quiz_unit()` for quiz-behaviour tests; the existing test's unit where it has one). `tests/test_questions_forms.py::test_marking_widgets_have_input_class` iterates `("marking_mode", "max_attempts", "max_marks")` — change it to `("marking_mode", "attempts_mode", "max_marks")` and build forms with `unit=make_quiz_unit()`.
- `grep -rn "\"max_attempts\"" tests courses/tests` — every POST dict entry: `"max_attempts": "N"` (N ≥ 1) → `"attempts_mode": "limited", "attempts_limit": "N"`; `"max_attempts": ""` → `"attempts_mode": "unlimited"`; `"max_attempts": "0"` (e.g. `tests/test_save_choicegrid.py` ×3, `tests/test_save_multigrid.py` ×3, `tests/test_grid_questions_nesting.py`) → `"attempts_mode": "inherit"` (D9 — `limited` 0 is now a form error). **Grep, don't recall**: a stale key is silently ignored and the question saves as inherit (spec §7.1). Leave transfer payload dicts for Task 7.
- Forms built through the dispatch table are invisible to the grep above: `grep -rnE "FORM_FOR_TYPE\[[^]]*\]\(" tests courses/tests` — every hit that resolves to a question type gets `unit=` (or `**marking_kwargs(form_cls, unit)` when the key is a variable). Known site: `tests/test_questions_2b_forms.py` (~7, ~56, ~70).
- `tests/test_questions_2dii_form.py` (~19) has the same `("marking_mode", "max_attempts", "max_marks")` loop — same fix as above.
- Convert the form-path assertions Task 2 deferred (its commit message lists them, e.g. `tests/test_quiz_authoring.py`).
- Run every file the sweep touched (chunks of ~10) → PASS.

- [ ] **Step 11: Commit**

```bash
git add -A courses templates tests
git commit -m "feat(attempts): question editor Attempts select with inherit label"
```

---

### Task 5: Quiz settings — select, reset choice, save path

**Files:**
- Modify: `courses/builder.py` (`rename_node`)
- Modify: `courses/views_manage.py` (`node_rename`, `_editor_page`, new `_unit_settings_values`)
- Modify: `templates/courses/manage/editor/_unit_settings.html`
- Test: `tests/test_attempts_quiz_settings.py`

**Interfaces:**
- Consumes: Task 3 (`parse_attempts`, `UNIT_MODES`, `ZERO_MESSAGES["course"]`, `reset_quiz_overrides`, `count_question_overrides`, `quiz_keep_label`, `quiz_reset_message`, `inherit_label`), Task 1 (`effective_course_attempts`).
- Produces: `rename_node(..., attempts_mode=_UNSET, attempts_limit=_UNSET, reset_question_attempts=_UNSET)`; on a reset the returned node carries `attempts_reset_count: int`. `_editor_page(..., settings_post=None)`; context key `unit_settings` (dict).

- [ ] **Step 1: Write the failing tests** — `tests/test_attempts_quiz_settings.py`:

```python
"""Quiz-level attempts (spec 2026-10-20 §5.2)."""

import pytest
from django.urls import reverse

from courses import attempts as A
from courses.models import ContentNode
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _post(client, unit, *, follow=False, **over):
    data = {
        "node": unit.pk,
        "token": unit.updated.isoformat(),
        "has_settings": "1",
        "ctx": "editor",
        "title": unit.title,
        "html_seed_js": "",
    }
    data.update(over)
    return client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": unit.course.slug}),
        data,
        follow=follow,
    )


def _q(unit, *, marking="A", own=None):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **(own or {})
    )
    add_element(unit, q)
    return q


def test_saves_quiz_limit(client):
    make_pa(client)
    unit = make_quiz_unit()
    assert _post(client, unit, attempts_mode="limited", attempts_limit="3").status_code == 302
    unit.refresh_from_db()
    assert (unit.attempts_mode, unit.attempts_limit) == ("limited", 3)


def test_hidden_junk_saves_null(client):
    make_pa(client)
    unit = make_quiz_unit()
    _post(client, unit, attempts_mode="unlimited", attempts_limit="abc")
    unit.refresh_from_db()
    assert (unit.attempts_mode, unit.attempts_limit) == ("unlimited", None)


@pytest.mark.parametrize(
    "mode,raw,message",
    [
        ("limited", "abc", A.MSG_ENTER),
        ("limited", "2.5", A.MSG_ENTER),
        ("limited", "", A.MSG_ENTER),
        ("limited", "0", A.ZERO_MESSAGES["course"]),
        ("limited", "40000", A.MSG_CAP),
        ("bogus", "3", A.MSG_CHOOSE),
    ],
)
def test_422_messages(client, mode, raw, message):
    make_pa(client)
    unit = make_quiz_unit()
    resp = _post(client, unit, attempts_mode=mode, attempts_limit=raw)
    assert resp.status_code == 422
    assert str(message).replace("'", "&#x27;") in resp.content.decode()


def test_422_keeps_every_posted_value(client):
    make_pa(client)
    unit = make_quiz_unit()
    _q(unit, own=attempts(4))  # makes the reset radios appear
    resp = _post(
        client,
        unit,
        title="New title",
        html_seed_js="{ seed: 42 }",
        attempts_mode="limited",
        attempts_limit="0",
        attempts_reset="reset",
    )
    html = resp.content.decode()
    assert resp.status_code == 422
    assert '<details class="unit-settings" open' in html
    assert "{ seed: 42 }" in html and 'value="New title"' in html
    assert '<option value="limited" selected' in html
    assert 'value="reset" checked' in html
    assert "Same as course (currently: 1)" in html


def test_overriding_quiz_label_shows_the_course_value(client):
    """Spec §4/§7.4: the quiz select resolves the COURSE, never the quiz itself."""
    make_pa(client)
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    url = reverse("courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk})
    html = client.get(url).content.decode()
    assert "Same as course (currently: 1)" in html
    assert "(currently: 3)" not in html


def test_lesson_settings_and_plain_rename_keep_dormant_override(client):
    make_pa(client)
    lesson = ContentNodeFactory(
        kind="unit", unit_type="lesson", attempts_mode="limited", attempts_limit=2
    )
    assert _post(client, lesson).status_code == 302  # no attempts keys
    lesson.refresh_from_db()
    url = reverse("courses:manage_node_rename", kwargs={"slug": lesson.course.slug})
    client.post(url, {"node": lesson.pk, "token": lesson.updated.isoformat(), "title": "T"})
    lesson.refresh_from_db()
    assert (lesson.attempts_mode, lesson.attempts_limit) == ("limited", 2)


def test_crafted_attempts_post_against_a_lesson_is_rejected(client):
    make_pa(client)
    lesson = ContentNodeFactory(
        kind="unit", unit_type="lesson", attempts_mode="limited", attempts_limit=2
    )
    q = _q(lesson, own=attempts(5))
    resp = _post(client, lesson, attempts_mode="unlimited", attempts_reset="reset")
    assert resp.status_code == 422
    lesson.refresh_from_db()
    q.refresh_from_db()
    assert (lesson.attempts_limit, q.attempts_limit) == (2, 5)


def test_reset_clears_this_quiz_only_and_reports_the_auto_count(client):
    make_pa(client)
    unit = make_quiz_unit()
    other = make_quiz_unit(course=unit.course)
    a1, a2 = _q(unit, own=attempts(3)), _q(unit, own=attempts(None))
    n = _q(unit, marking="N", own=attempts(2))
    elsewhere = _q(other, own=attempts(5))
    resp = _post(
        client, unit, attempts_mode="limited", attempts_limit="4",
        attempts_reset="reset", follow=True,
    )
    for q in (a1, a2, n):
        q.refresh_from_db()
        assert q.attempts_mode == "inherit"
    elsewhere.refresh_from_db()
    assert elsewhere.attempts_limit == 5
    assert "Settings saved. 2 questions now use the quiz setting." in resp.content.decode()


def test_keep_changes_nothing_and_shows_no_message(client):
    make_pa(client)
    unit = make_quiz_unit()
    q = _q(unit, own=attempts(3))
    resp = _post(
        client, unit, attempts_mode="limited", attempts_limit="4",
        attempts_reset="keep", follow=True,
    )
    q.refresh_from_db()
    assert q.attempts_limit == 3
    assert "Settings saved" not in resp.content.decode()
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_quiz_settings.py` → FAIL.

- [ ] **Step 3: `rename_node`** (`courses/builder.py`). New keyword parameters `attempts_mode=_UNSET, attempts_limit=_UNSET, reset_question_attempts=_UNSET`. After the `if node.kind == ContentNode.Kind.UNIT:` block and before `node.full_clean()`:

```python
    attempts_given = any(
        v is not _UNSET for v in (attempts_mode, attempts_limit, reset_question_attempts)
    )
    if attempts_given:
        from courses import attempts as attempts_rules  # function-local, as above

        # P9: only a quiz carries attempts. The view only posts them for a quiz;
        # this guard is what makes a crafted POST against a lesson harmless.
        if node.unit_type != ContentNode.UnitType.QUIZ:
            raise ValidationError(gettext_lazy("Attempts can only be set on a quiz."))
        node.attempts_mode, node.attempts_limit = attempts_rules.parse_attempts(
            attempts_mode,
            attempts_limit,
            allowed_modes=attempts_rules.UNIT_MODES,
            zero_message=attempts_rules.ZERO_MESSAGES["course"],
        )
        fields += ["attempts_mode", "attempts_limit"]
        if reset_question_attempts is True:
            # Inside this transaction, under the row lock _locked_node took; the
            # save below bumps `updated`, so open editors see a stale token.
            node.attempts_reset_count = attempts_rules.reset_quiz_overrides(node)
```

(`node.unit_type` is a non-unit's `None`, so the guard also covers containers.)

- [ ] **Step 4: `node_rename` and `_editor_page`** (`courses/views_manage.py`; add `from django.contrib import messages` and `from courses import attempts as attempts_rules`, one per line).

In `node_rename`, before the `try:`:

```python
    # Attempts ride the settings form only, and only a quiz renders the select:
    # absent keys stay _UNSET so a lesson save or a plain rename never touches a
    # dormant override (spec §5.2).
    attempts_posted = is_settings and "attempts_mode" in request.POST
```

and add to the `rename_node(...)` call:

```python
            attempts_mode=request.POST.get("attempts_mode")
            if attempts_posted
            else builder_svc._UNSET,
            attempts_limit=request.POST.get("attempts_limit", "")
            if attempts_posted
            else builder_svc._UNSET,
            reset_question_attempts=(request.POST.get("attempts_reset") == "reset")
            if attempts_posted
            else builder_svc._UNSET,
```

In the `ValidationError` branch: `return _editor_page(request, unit, error=msg, status=422, settings_post=request.POST if is_settings else None)`. On success, before `if to_editor:`:

```python
    if attempts_posted and request.POST.get("attempts_reset") == "reset":
        messages.success(
            request,
            attempts_rules.quiz_reset_message(getattr(node, "attempts_reset_count", 0)),
        )
```

Add above `_editor_page`:

```python
def _unit_settings_values(unit, post=None):
    """What the unit settings form shows: stored values, or -- on a 422 -- the
    posted ones, so an attempts error never discards another edit such as the
    seed JS (spec §5.2). Counts and labels always come from the DB."""
    if post is None:
        vals = {
            "title": unit.title,
            "published": unit.published,
            "obligatory": unit.obligatory,
            "html_seed_js": unit.html_seed_js,
            "attempts_mode": unit.attempts_mode,
            "attempts_limit": "" if unit.attempts_limit is None else str(unit.attempts_limit),
            "attempts_reset": "keep",
            "open": False,
        }
    else:
        vals = {
            "title": post.get("title", ""),
            "published": "published" in post,
            "obligatory": "obligatory" in post,
            "html_seed_js": post.get("html_seed_js", ""),
            "attempts_mode": post.get("attempts_mode", unit.attempts_mode),
            "attempts_limit": post.get("attempts_limit", ""),
            "attempts_reset": post.get("attempts_reset", "keep"),
            "open": True,
        }
    if unit.unit_type == ContentNode.UnitType.QUIZ:
        from courses.quiz import effective_course_attempts

        n = attempts_rules.count_question_overrides([unit.pk])
        vals["inherit_label"] = attempts_rules.inherit_label(
            "course", effective_course_attempts(unit.course)
        )
        vals["zero_help"] = attempts_rules.ZERO_MESSAGES["course"]
        vals["override_count"] = n
        vals["keep_label"] = attempts_rules.quiz_keep_label(n)
    return vals
```

`_editor_page` gains `settings_post=None` and adds `"unit_settings": _unit_settings_values(unit, settings_post),` to its context.

- [ ] **Step 5: Template** — rewrite `templates/courses/manage/editor/_unit_settings.html` to read `unit_settings` (keep every existing element, class and hidden input; the token still comes from `unit.updated`):

```django
{% load i18n %}
<details class="unit-settings"{% if unit_settings.open %} open{% endif %}>
  <summary class="unit-settings__summary">
    <span class="unit-settings__label">{% trans "Settings" %}</span>
  </summary>
  <form class="form" method="post" action="{% url 'courses:manage_node_rename' slug=course.slug %}">
    {% csrf_token %}
    <input type="hidden" name="node" value="{{ unit.pk }}">
    <input type="hidden" name="token" value="{{ unit.updated.isoformat }}">
    <input type="hidden" name="has_settings" value="1">
    <input type="hidden" name="ctx" value="editor">
    <label>{% trans "Title" %} <input type="text" name="title" value="{{ unit_settings.title }}" required></label>
    <label><input type="checkbox" name="published"{% if unit_settings.published %} checked{% endif %}> {% trans "Published" %}</label>
    <label><input type="checkbox" name="obligatory"{% if unit_settings.obligatory %} checked{% endif %}> {% trans "Obligatory" %}</label>
    {% if unit.unit_type == "quiz" %}
    <div class="unit-settings__attempts">
      <label for="unit-attempts-mode">{% trans "Attempts per question" %}</label>
      <select id="unit-attempts-mode" name="attempts_mode" class="input">
        <option value="inherit"{% if unit_settings.attempts_mode == "inherit" %} selected{% endif %}>{{ unit_settings.inherit_label }}</option>
        <option value="limited"{% if unit_settings.attempts_mode == "limited" %} selected{% endif %}>{% trans "Limited to…" %}</option>
        <option value="unlimited"{% if unit_settings.attempts_mode == "unlimited" %} selected{% endif %}>{% trans "Unlimited" %}</option>
      </select>
      <div class="attempts-limit" data-attempts-limit>
        <label for="unit-attempts-limit">{% trans "Number of attempts" %}</label>
        <input id="unit-attempts-limit" class="input" type="text" inputmode="numeric" name="attempts_limit" value="{{ unit_settings.attempts_limit }}">
        <p class="helptext">{{ unit_settings.zero_help }}</p>
      </div>
      {% if unit_settings.override_count %}
      <div class="unit-settings__reset" role="radiogroup">
        <label><input type="radio" name="attempts_reset" value="keep"{% if unit_settings.attempts_reset != "reset" %} checked{% endif %}> {{ unit_settings.keep_label }}</label>
        <label><input type="radio" name="attempts_reset" value="reset"{% if unit_settings.attempts_reset == "reset" %} checked{% endif %}> {% trans "Make all questions in this quiz use the quiz setting" %}</label>
      </div>
      {% endif %}
    </div>
    {% endif %}
    <label class="unit-seed">{% trans "Unit JS (seed)" %}
      <div class="code-field" data-code-field style="--code-field-rows: 6">
        <div class="code-field__gutter" aria-hidden="true"></div>
        <div class="code-field__area"><textarea name="html_seed_js" rows="6" spellcheck="false" autocomplete="off" wrap="off" placeholder="{}">{{ unit_settings.html_seed_js }}</textarea></div>
      </div>
    </label>
    <p class="helptext unit-seed__help">
      {% trans "A JavaScript object exposed to this unit's HTML elements as window.SEED — for example { table_answers: { 220: [3, -2, -5] } }. The course JS reads it; there is no localStorage in the sandbox." %}
    </p>
    <button class="btn btn--small" type="submit">{% trans "Save settings" %}</button>
  </form>
</details>
```

Keep the existing `{% trans %}` seed help text byte-identical (it has a catalog entry). Make sure the test's `'<option value="limited" selected'` matches the rendered whitespace; if Django renders the attribute differently, adjust the assertion to the real markup, not the template.

- [ ] **Step 6: Run** — `uv run pytest tests/test_attempts_quiz_settings.py` → PASS. Also run the existing tests that touch the settings form, chosen by CONTENT not name: `uv run pytest $(grep -rln "has_settings\|unit-settings\|html_seed_js\|node_rename" tests | grep -v e2e)` → PASS (they read the old `unit.*` values; `unit_settings` must reproduce them).

- [ ] **Step 7: Prove they bite.** Mutant L: drop the `node.unit_type != QUIZ` guard in `rename_node` → the crafted-lesson test FAILS. Mutant M: in `_unit_settings_values` use stored values on the 422 path (`post=None` always) → `test_422_keeps_every_posted_value` FAILS. Mutant Y: `attempts_posted = is_settings` (drop the key check) → `test_lesson_settings_and_plain_rename_keep_dormant_override` FAILS (422: lesson guard). Mutant Z: in `parse_attempts` return `raw_limit` unparsed for non-limited modes → `test_hidden_junk_saves_null` FAILS. Mutant AA: in `_unit_settings_values` use `effective_unit_attempts(unit)[0]` instead of `effective_course_attempts(unit.course)` → `test_overriding_quiz_label_shows_the_course_value` FAILS. Revert each by hand.

- [ ] **Step 8: Commit**

```bash
git add courses/builder.py courses/views_manage.py templates/courses/manage/editor/_unit_settings.html tests/test_attempts_quiz_settings.py
git commit -m "feat(attempts): quiz settings attempts select and question reset"
```

---

### Task 6: Course settings — default, reset choice, locking

**Files:**
- Modify: `courses/forms.py` (`CourseForm`)
- Modify: `courses/views_manage.py` (`course_edit`)
- Test: `tests/test_attempts_course_settings.py`

**Interfaces:**
- Consumes: Task 3 (`parse_attempts`, `COURSE_MODES`, `ZERO_MESSAGES["course_level"]`, `MSG_CHOOSE`, `course_override_counts`, `reset_course_overrides`, `course_keep_label`, `course_reset_message`).
- Produces: `CourseForm` fields `attempts_mode`, `attempts_limit`, and (edit, overrides exist) `attempts_reset` (`"keep"` / `"reset"` in `cleaned_data`).

Spec gap, decided here: when a bound course POST carries **no** `attempts_mode` key (e.g. an older client or a test that posts only the other fields) the attempts fields are dropped and the stored values kept — the same "absent = keep" rule §5.1 sets for questions. An empty or unknown posted value still gets `MSG_CHOOSE`.

- [ ] **Step 1: Write the failing tests** — `tests/test_attempts_course_settings.py`:

```python
"""Course-level attempts default and reset (spec 2026-10-20 §5.3/§5.4)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from courses import attempts as A
from courses.forms import CourseForm
from courses.models import ContentNode
from courses.models import ShortTextQuestionElement
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _form_data(course, **over):
    form = CourseForm(instance=course)
    data = {}
    for name, field in form.fields.items():
        value = form[name].value()
        if value is None:
            continue
        data[name] = [str(v) for v in value] if isinstance(value, (list, tuple)) else value
    data.update(over)
    return data


def _post(client, course, **over):
    url = reverse("courses:manage_course_edit", kwargs={"slug": course.slug})
    return client.post(url, _form_data(course, **over), follow=True)


def _q(unit, own, marking="A"):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **own
    )
    add_element(unit, q)
    return q


def test_saves_course_default(client):
    make_pa(client)
    course = CourseFactory()
    _post(client, course, attempts_mode="limited", attempts_limit="3")
    course.refresh_from_db()
    assert (course.attempts_mode, course.attempts_limit) == ("limited", 3)


def test_course_cannot_inherit_and_zero_has_the_course_message():
    course = CourseFactory()
    form = CourseForm(_form_data(course, attempts_mode="inherit"), instance=course)
    assert form.errors["attempts_mode"] == [str(A.MSG_CHOOSE)]
    form = CourseForm(_form_data(course, attempts_mode="limited", attempts_limit="0"), instance=course)
    assert form.errors["attempts_limit"] == [str(A.ZERO_MESSAGES["course_level"])]


def test_hidden_junk_saves_null():
    course = CourseFactory()
    form = CourseForm(
        _form_data(course, attempts_mode="unlimited", attempts_limit="abc"), instance=course
    )
    assert form.is_valid(), form.errors
    c = form.save()
    assert (c.attempts_mode, c.attempts_limit) == ("unlimited", None)


def test_absent_keys_keep_stored_values():
    course = CourseFactory(attempts_mode="limited", attempts_limit=5)
    data = _form_data(course)
    data.pop("attempts_mode")
    data.pop("attempts_limit")
    form = CourseForm(data, instance=course)
    assert form.is_valid(), form.errors
    c = form.save()
    assert (c.attempts_mode, c.attempts_limit) == ("limited", 5)


def test_reset_choice_only_when_overrides_exist():
    course = CourseFactory()
    assert "attempts_reset" not in CourseForm(instance=course).fields
    assert "attempts_reset" not in CourseForm().fields  # create
    _q(make_quiz_unit(course=course), attempts(3))
    field = CourseForm(instance=course).fields["attempts_reset"]
    assert dict(field.widget.choices)["keep"] == "Keep specific settings (1 question has its own)"


def test_reset_end_to_end(client):
    make_pa(client)
    course = CourseFactory()
    qa = make_quiz_unit(course=course, attempts_mode="limited", attempts_limit=2)
    qb = make_quiz_unit(course=course)
    _q(qa, attempts(3))
    _q(qb, attempts(4))
    _q(qb, attempts(None))
    resp = _post(client, course, attempts_mode="limited", attempts_limit="3", attempts_reset="reset")
    assert "Settings saved. 1 quiz and 3 questions now use the course setting." in resp.content.decode()
    assert not ContentNode.objects.filter(course=course).exclude(attempts_mode="inherit").exists()


def test_keep_shows_no_message_and_changes_nothing(client):
    make_pa(client)
    course = CourseFactory()
    q = _q(make_quiz_unit(course=course), attempts(3))
    resp = _post(client, course, attempts_reset="keep")
    q.refresh_from_db()
    assert q.attempts_limit == 3
    assert "Settings saved" not in resp.content.decode()


def test_invalid_post_keeps_the_reset_pick(client):
    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))
    url = reverse("courses:manage_course_edit", kwargs={"slug": course.slug})
    resp = client.post(url, _form_data(course, attempts_mode="limited", attempts_limit="0", attempts_reset="reset"))
    assert resp.status_code == 200
    # Django's RadioSelect puts id= between value= and checked: parse, don't substring.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.content, "html.parser")
    assert soup.select_one('input[name="attempts_reset"][value="reset"]').has_attr("checked")


def test_units_are_locked_before_any_question_or_course_write(client):
    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))
    with CaptureQueriesContext(connection) as ctx:
        _post(client, course, attempts_reset="reset")
    sqls = [q["sql"] for q in ctx.captured_queries]

    def first(pred):
        return next(i for i, s in enumerate(sqls) if pred(s))

    lock = first(lambda s: 'FROM "courses_contentnode"' in s and "FOR UPDATE" in s)
    q_write = first(lambda s: s.startswith('UPDATE "courses_') and "questionelement" in s)
    c_write = first(lambda s: s.startswith('UPDATE "courses_course"'))
    assert lock < q_write and lock < c_write


def test_dormant_lesson_override_survives_reset_and_revives_as_quiz(client):
    """Accepted consequence of P9 (spec §5.4): not "fixed"."""
    from courses.quiz import effective_unit_attempts
    from tests.factories import ContentNodeFactory

    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))  # makes the reset choice appear
    lesson = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson",
        attempts_mode="limited", attempts_limit=2,
    )
    _post(client, course, attempts_reset="reset")
    ContentNode.objects.filter(pk=lesson.pk).update(unit_type="quiz")
    lesson.refresh_from_db()
    assert effective_unit_attempts(lesson) == (2, "quiz")


def test_reset_is_atomic_with_the_course_save(client, monkeypatch):
    make_pa(client)
    course = CourseFactory()
    q = _q(make_quiz_unit(course=course), attempts(3))

    def boom(self, commit=True):
        raise RuntimeError("save failed")

    monkeypatch.setattr(CourseForm, "save", boom)
    with pytest.raises(RuntimeError):
        _post(client, course, attempts_reset="reset")
    q.refresh_from_db()
    assert q.attempts_limit == 3  # rolled back


def test_stale_editor_save_is_refused_after_a_reset(client):
    make_pa(client)
    course = CourseFactory()
    unit = make_quiz_unit(course=course)  # own mode inherit
    q = _q(unit, attempts(3))
    el = q.elements.get()
    stale_token = unit.updated.isoformat()
    _post(client, course, attempts_reset="reset")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "unit": unit.pk, "element": el.pk, "type": "shorttextquestion",
            "unit_token": stale_token, "el_title": "",
            "stem": "x", "explanation": "", "accepted": "a",
            "marking_mode": "A", "max_marks": "1",
            "attempts_mode": "limited", "attempts_limit": "3",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    q.refresh_from_db()
    assert q.attempts_mode == "inherit"  # the reset was not silently undone
```

Check the URL name for `element_save` and the `type` POST key in `courses/urls.py` / the view (~2590) and adjust.

- [ ] **Step 1b: Add the course-reset D13 case** to the same file: a question at `attempts(1)` that an enrolled student has exhausted (one wrong answer → locked) stays locked after a course reset POST to `limited 3` — the next answer POST (fetch) is 409 and `QuestionResponse.locked is True`.

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_course_settings.py` → FAIL.

- [ ] **Step 3: `CourseForm`** (`courses/forms.py`; add `from courses import attempts as attempts_rules`). Add `"attempts_mode", "attempts_limit"` to `Meta.fields` after `"external_id"`, and declared fields at class level:

```python
    attempts_mode = forms.ChoiceField(
        label=_("Attempts per question"),
        choices=[("limited", _("Limited to…")), ("unlimited", _("Unlimited"))],
        error_messages={
            "required": attempts_rules.MSG_CHOOSE,
            "invalid_choice": attempts_rules.MSG_CHOOSE,
        },
    )
    # Plain CharField: no min/max attrs, no validators -- see _MarkingFieldsMixin.
    attempts_limit = forms.CharField(
        required=False,
        label=_("Number of attempts"),
        help_text=attempts_rules.ZERO_MESSAGES["course_level"],
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )
```

At the end of `__init__`:

```python
        # Absent = keep, as for question forms (spec §5.1): a POST without the
        # mode key never touches the stored default.
        if self.is_bound and "attempts_mode" not in self.data:
            self.fields.pop("attempts_mode")
            self.fields.pop("attempts_limit")
        elif self.instance.pk:
            quizzes, questions = attempts_rules.course_override_counts(self.instance)
            if quizzes or questions:
                # A CharField, not a ChoiceField: anything but "reset" means Keep
                # (P8), which a ChoiceField would turn into an "invalid choice".
                self.fields["attempts_reset"] = forms.CharField(
                    required=False,
                    initial="keep",
                    label=_("Specific settings"),
                    widget=forms.RadioSelect(
                        choices=[
                            ("keep", attempts_rules.course_keep_label(quizzes, questions)),
                            ("reset", _("Make every quiz and question use the course setting")),
                        ]
                    ),
                )
                keys = list(self.fields)
                keys.insert(keys.index("attempts_limit") + 1, keys.pop(keys.index("attempts_reset")))
                self.order_fields(keys)
```

and the field cleaners:

```python
    def clean_attempts_limit(self):
        mode = self.cleaned_data.get("attempts_mode")
        if mode is None:
            return None
        return attempts_rules.parse_attempts(
            mode,
            self.cleaned_data.get("attempts_limit"),
            allowed_modes=attempts_rules.COURSE_MODES,
            zero_message=attempts_rules.ZERO_MESSAGES["course_level"],
        )[1]

    def clean_attempts_reset(self):
        return "reset" if self.cleaned_data.get("attempts_reset") == "reset" else "keep"
```

(These are field-level cleaners, so `clean()`'s early return for an unchanged structure cannot skip them.)

- [ ] **Step 4: `course_edit`** (`courses/views_manage.py`; add `from django.db import transaction` if absent):

```python
        if form.is_valid():
            reset = form.cleaned_data.get("attempts_reset") == "reset"
            with transaction.atomic():
                # Quiz units BEFORE the Course row: builder ops lock a unit and
                # then write the course, so this is the one global order (§5.3).
                counts = attempts_rules.reset_course_overrides(course) if reset else None
                course = form.save()
            if counts is not None:
                messages.success(request, attempts_rules.course_reset_message(*counts))
            return redirect("courses:manage_course_edit", slug=course.slug)  # new slug
```

`course_create` is unchanged: a new course has no overrides, so its form never has `attempts_reset`.

- [ ] **Step 5: Run** — `uv run pytest tests/test_attempts_course_settings.py` → PASS; then the existing course-form tests, chosen by content: `uv run pytest $(grep -rln "CourseForm\|manage_course_edit\|manage_course_create\|course_form.html" tests | grep -v e2e)` → PASS (they post without `attempts_mode`; absent = keep).

(The course-reset D13 test is in Step 1b.)

- [ ] **Step 6: Prove they bite.** Mutant N: call `form.save()` before `reset_course_overrides` → the lock-order test FAILS. Mutant O: move the reset outside the `atomic()` block → the atomic test FAILS. Mutant P: remove the explicit `updated` bump in `reset_course_overrides` → `test_stale_editor_save_is_refused_after_a_reset` FAILS (200, override re-written). Mutant AB: at the end of `reset_course_overrides`, add `QuestionResponse.objects.filter(element__unit_id__in=pks, locked=True).update(locked=False)` → the Step 1b D13 case FAILS (200, not 409). Revert each by hand.

- [ ] **Step 7: `ContentNode.updated` reader audit** (spec §5.4). Re-run `grep -rn "\.updated\b" --include=*.py --include=*.html courses templates scripts | grep -v /tests/` and confirm, for each reader, that a reset bump is right. Known readers: the optimistic-concurrency tokens (`_check_token` in `builder.py`, `data-updated` / hidden `token` inputs in editor templates) — the bump is the point; LAL "no hand edit" evidence (`updated == created`, `scripts/lal_import/lesson.py`) — a reset IS an edit of the unit's questions, so marking the unit touched is correct. The spec also names **author live-view links** and **unit-progress staleness**: find their code (`grep -rn "updated" courses/views*.py courses/rollups.py templates/courses`) and decide each. The PR paragraph gives a one-line verdict for EVERY spec-named reader plus any extra one the grep finds; if any reader would be wrong, stop and report it to the owner.

- [ ] **Step 8: Commit**

```bash
git add courses/forms.py courses/views_manage.py tests/test_attempts_course_settings.py
git commit -m "feat(attempts): course default and course-wide reset with unit-first locking"
```

---

### Task 7: Transfer format 18

**Files:**
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION = 18`, `check_attempts_pair`, node + course key lists and `setdefault`s)
- Modify: `courses/transfer/payloads.py` (`Q_KEYS`, `_check_question_fields`, `_upgrade_legacy_data`)
- Modify: `courses/transfer/export.py` (`_question_fields`, `_node_dict`, course head)
- Modify: `courses/transfer/importer.py` (`_q_kwargs`, `_create_nodes`, course create)
- Modify: transfer tests that build question payloads (`q_fields` in `tests/test_transfer_validation.py`, others by grep)
- Test: `tests/test_attempts_transfer.py`

**Interfaces:**
- Consumes: `MAX_ATTEMPTS_LIMIT` (Task 1).
- Produces: archive keys `attempts_mode` / `attempts_limit` on questions, nodes and (course archives) the course; `schema.check_attempts_pair(mode, limit, *, allowed, what)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_attempts_transfer.py`:

```python
"""Archive format 18: attempts at all three levels (spec 2026-10-20 §6)."""

import io

import pytest

from courses.models import ShortTextQuestionElement
from courses.transfer.export import build_export
from courses.transfer.export import write_archive
from courses.transfer.payloads import validate_element_data
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_quiz_unit
from tests.test_transfer_import import _import_zip
from tests.test_transfer_validation import base_course_doc
from tests.test_transfer_validation import node
from tests.test_transfer_validation import q_fields

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _short_text_el(eid, unit, **data_over):
    data = {**q_fields(), "accepted": "Paris", "case_sensitive": False}
    data.update(data_over)
    return {"id": eid, "unit": unit, "title": "", "type": "short_text",
            "data": data, "parent": None, "tab": ""}


def test_version_is_18():
    assert FORMAT_VERSION == 18


def test_round_trip_keeps_all_three_levels():
    course = CourseFactory(attempts_mode="limited", attempts_limit=3)
    unit = make_quiz_unit(course=course, attempts_mode="unlimited", attempts_limit=None)
    add_element(unit, ShortTextQuestionElement.objects.create(stem="a", accepted="x", **attempts(5)))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="b", accepted="x"))
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    new = _import_zip(buf, UserFactory())
    assert (new.attempts_mode, new.attempts_limit) == ("limited", 3)
    nu = new.nodes.get(kind="unit")
    assert (nu.attempts_mode, nu.attempts_limit) == ("unlimited", None)
    got = sorted(
        (e.content_object.stem, e.content_object.attempts_mode, e.content_object.attempts_limit)
        for e in nu.elements.all()
    )
    assert got == [("a", "limited", 5), ("b", "inherit", None)]


@pytest.mark.parametrize(
    "old,want",
    [(1, ("inherit", None)), (0, ("inherit", None)), (None, ("unlimited", None)), (5, ("limited", 5))],
)
def test_legacy_question_mapping(old, want):
    el = _short_text_el("e1", "u1")
    del el["data"]["attempts_mode"], el["data"]["attempts_limit"]
    el["data"]["max_attempts"] = old
    validate_element_data(el, {}, format_version=17)
    assert (el["data"]["attempts_mode"], el["data"]["attempts_limit"]) == want
    assert "max_attempts" not in el["data"]  # mutated in place for the commit


@pytest.mark.parametrize("bad", [True, "3", -1])
def test_hostile_legacy_value_is_a_transfer_error(bad):
    el = _short_text_el("e1", "u1")
    del el["data"]["attempts_mode"], el["data"]["attempts_limit"]
    el["data"]["max_attempts"] = bad
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=17)


def test_modern_version_none_is_not_remapped():
    el = _short_text_el("e1", "u1")
    el["data"]["max_attempts"] = 3  # a stray legacy key in a modern payload
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=None)


def test_legacy_nodes_and_course_get_defaults():
    doc = base_course_doc(nodes=[node("u1", unit_type="quiz")])
    validate_document(doc, kind="course", format_version=17)
    assert (doc["nodes"][0]["attempts_mode"], doc["nodes"][0]["attempts_limit"]) == ("inherit", None)
    assert (doc["course"]["attempts_mode"], doc["course"]["attempts_limit"]) == ("limited", 1)


@pytest.mark.parametrize(
    "mode,limit",
    [("bogus", None), ("limited", None), ("limited", 0), ("limited", 32768),
     ("limited", True), ("inherit", 3), ("unlimited", 3)],
)
def test_invalid_question_pairs_rejected(mode, limit):
    el = _short_text_el("e1", "u1", attempts_mode=mode, attempts_limit=limit)
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=18)


def test_course_cannot_inherit():
    doc = base_course_doc()
    doc["course"].update(attempts_mode="inherit", attempts_limit=None)
    with pytest.raises(TransferError):
        validate_document(doc, kind="course", format_version=18)


def test_exporter_writes_null_for_non_limited():
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    _manifest, document, _media, _problems = build_export(course)
    assert document["course"]["attempts_limit"] is None
```

The cross-COURSE copy path is the sub-tree import (`import_subtree` with a `target_course`); `duplicate_unit` only copies within one course, so it cannot show "resolves at the destination". Append to `tests/test_attempts_transfer.py`:

```python
from courses.quiz import effective_max_attempts
from courses.transfer.export import write_archive_from
from tests.test_transfer_subtree import _import_subtree_zip


def _unit_archive(unit, *, legacy):
    manifest, document, media, _problems = build_export(unit.course, unit)
    if legacy:  # rewrite to the v17 shape: the pair becomes max_attempts 1
        manifest["format_version"] = 17
        for el in document["elements"]:
            d = el["data"]
            if "attempts_mode" in d:
                del d["attempts_mode"], d["attempts_limit"]
                d["max_attempts"] = 1
        for nd in document["nodes"]:
            del nd["attempts_mode"], nd["attempts_limit"]
    buf = io.BytesIO()
    write_archive_from(manifest, document, media, buf)
    buf.seek(0)
    return buf


@pytest.mark.parametrize("legacy", [True, False])
def test_subtree_import_inherits_from_the_target_course(legacy):
    """P10/P11: an inheriting question (a v17 `max_attempts: 1`, or a modern
    inherit) resolves against the TARGET course, not the source."""
    src = CourseFactory(attempts_mode="limited", attempts_limit=4)
    unit = make_quiz_unit(course=src)
    add_element(unit, ShortTextQuestionElement.objects.create(stem="a", accepted="x"))
    target = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    grafted = _import_subtree_zip(_unit_archive(unit, legacy=legacy), target, None, UserFactory())
    q = grafted.elements.get().content_object
    assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    assert effective_max_attempts(q, grafted) is None  # target's unlimited
```

Plus one modern case where the copy must KEEP own modes:

```python
def test_subtree_import_keeps_own_modes():
    src = CourseFactory()
    unit = make_quiz_unit(course=src, attempts_mode="limited", attempts_limit=2)
    add_element(unit, ShortTextQuestionElement.objects.create(stem="own", accepted="x", **attempts(5)))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="inh", accepted="x"))
    target = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    grafted = _import_subtree_zip(_unit_archive(unit, legacy=False), target, None, UserFactory())
    assert (grafted.attempts_mode, grafted.attempts_limit) == ("limited", 2)
    by_stem = {e.content_object.stem: e.content_object for e in grafted.elements.all()}
    assert (by_stem["own"].attempts_mode, by_stem["own"].attempts_limit) == ("limited", 5)
    assert effective_max_attempts(by_stem["inh"], grafted) == 2  # the copied quiz's own 2
```

If `build_export(course, unit)` / `write_archive_from` take other argument shapes, follow `tests/test_transfer_subtree.py::_archive_of`. Mutant V: in `_upgrade_legacy_attempts` map `old <= 1` to `("limited", old)` → the `legacy=True` case FAILS (limited 1, resolves to 1, not None).

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_attempts_transfer.py` → FAIL (`FORMAT_VERSION == 17`).

- [ ] **Step 3: `schema.py`.** `FORMAT_VERSION = 18`. Add:

```python
ATTEMPTS_MODES = ("inherit", "limited", "unlimited")


def check_attempts_pair(mode, limit, *, allowed, what):
    """Spec 2026-10-20 §6: `attempts_limit` is null unless the mode is limited, and
    then an int in 1..MAX_ATTEMPTS_LIMIT. isinstance-first, so a hostile value is
    a TransferError, never a 500."""
    from courses.models import MAX_ATTEMPTS_LIMIT

    if not isinstance(mode, str) or mode not in allowed:
        _err(_("%(what)s: unknown attempts mode."), what=what)
    if mode == "limited":
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_ATTEMPTS_LIMIT
        ):
            _err(
                _("%(what)s: the attempts limit must be a whole number from 1 to %(max)d."),
                what=what,
                max=MAX_ATTEMPTS_LIMIT,
            )
    elif limit is not None:
        _err(_("%(what)s: an attempts limit is only allowed with the limited mode."), what=what)
```

In `validate_document`, course branch: before the course `_exact_keys`, `if isinstance(c, dict): c.setdefault("attempts_mode", "limited"); c.setdefault("attempts_limit", 1)` (v≤17 had none — same optional-key pattern as `link_nodes`, with its isinstance guard), add both keys to the list, and after the bool checks: `check_attempts_pair(c["attempts_mode"], c["attempts_limit"], allowed=("limited", "unlimited"), what=_("course"))`. Node loop: next to `nd.setdefault("published", True)` add `nd.setdefault("attempts_mode", "inherit")` and `nd.setdefault("attempts_limit", None)`; add both keys to the node `_exact_keys` list; after `_claim_id`: `check_attempts_pair(nd["attempts_mode"], nd["attempts_limit"], allowed=ATTEMPTS_MODES, what=_("node"))`.

- [ ] **Step 4: `payloads.py`.** `Q_KEYS = ["stem", "explanation", "marking_mode", "attempts_mode", "attempts_limit", "max_marks"]`. In `_check_question_fields` replace the `check_int_or_null(data["max_attempts"], …)` line with `check_attempts_pair(data["attempts_mode"], data["attempts_limit"], allowed=ATTEMPTS_MODES, what=elid)` (import both from `courses.transfer.schema`). Extend `_upgrade_legacy_data` — keep its image branch exactly, restructured so both upgrades run:

```python
# FORMAT_VERSION at which a question's max_attempts became the attempts pair.
ATTEMPTS_PAIR_VERSION = 18


def _upgrade_legacy_attempts(data, format_version):
    """v<=17 question: rename + value-map max_attempts exactly like migration 0071
    (1 and 0 -> inherit, null -> unlimited, n >= 2 -> limited n). The value is
    checked first, so a bool/str/negative is a TransferError, never a 500. Keyed on
    the PRESENCE of max_attempts, not on a hand-written list of question types:
    no other type ever had the key, and a stray one is still rejected by
    _exact_keys. None (in-instance paths) means modern: nothing to map."""
    if format_version is None or not isinstance(format_version, int):
        return
    if format_version >= ATTEMPTS_PAIR_VERSION or "max_attempts" not in data:
        return
    old = check_int_or_null(data.pop("max_attempts"), "max_attempts")
    if old is None:
        data["attempts_mode"], data["attempts_limit"] = "unlimited", None
    elif old <= 1:
        data["attempts_mode"], data["attempts_limit"] = "inherit", None
    else:
        data["attempts_mode"], data["attempts_limit"] = "limited", old
```

and call it from `_upgrade_legacy_data` before the image-only early return (`data = el.get("data"); if isinstance(data, dict): _upgrade_legacy_attempts(data, format_version)`). Update that function's docstring to say it now runs two upgrades.

- [ ] **Step 5: export / importer.**
- `export._question_fields`: `"attempts_mode": q.attempts_mode, "attempts_limit": q.attempts_limit,` in place of `max_attempts`.
- `export._node_dict`: add `"attempts_mode": node.attempts_mode, "attempts_limit": node.attempts_limit,`.
- export course head: add `"attempts_mode": course.attempts_mode, "attempts_limit": course.attempts_limit,`.
- `importer._q_kwargs`: `"attempts_mode": data["attempts_mode"], "attempts_limit": data["attempts_limit"],`.
- `importer._create_nodes`: pass `attempts_mode=nd["attempts_mode"], attempts_limit=nd["attempts_limit"]`.
- `importer.import_course` `work()`: pass `attempts_mode=c["attempts_mode"], attempts_limit=c["attempts_limit"]` to `Course(...)`.

- [ ] **Step 6: Sweep transfer test payloads.** `q_fields` in `tests/test_transfer_validation.py` → `"attempts_mode": "inherit", "attempts_limit": None` instead of `"max_attempts": 1`. Then `grep -rn "max_attempts" tests/test_transfer* tests/test_*transfer* tests/test_link_transfer.py tests/test_export_depth3.py courses/tests` and convert each the same way — including `courses/tests/test_nested_question_transfer.py` (~238): its shared `fill_blank` payload feeds a v11, a v12 AND a `format_version=None` test; convert it to `"attempts_mode": "inherit", "attempts_limit": None` (the v11/v12 tests stay valid: the legacy upgrade only fires when `max_attempts` is present). Left as is, the None-version guard would still get its `TransferError` — from `_exact_keys`, not from the nested-question rule — and go blind while staying green (a dict key `"max_attempts": N` → the mapped pair per the §3.3 table). An export-output assertion such as `assert data["max_attempts"] == 1` (`tests/test_transfer_export.py` ~120) → assert `(data["attempts_mode"], data["attempts_limit"])` equals the question's stored pair. Convert the transfer/paste/duplicate assertions Task 2 deferred (its commit message lists them, e.g. `tests/test_builder_paste_element.py`). Bump the version pins: `grep -rn "FORMAT_VERSION == 17" tests` (today `tests/test_link_transfer.py`, `tests/test_table_transfer.py`, `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py`) → `== 18`, following how the previous bump updated them (`git log -S "FORMAT_VERSION == 17" --oneline`); also scan `tests/test_transfer_schema.py` for other `17` literals tied to the current version. Run all transfer test files plus the paste/duplicate ones: `uv run pytest $(ls tests/test_*transfer*.py tests/test_export_depth3.py tests/test_link_transfer.py tests/test_builder_paste_element.py)` → PASS.

- [ ] **Step 7: Run** — `uv run pytest tests/test_attempts_transfer.py tests/test_transfer_subtree.py` → PASS.

- [ ] **Step 8: Prove they bite.** Mutant Q: in `_upgrade_legacy_attempts` map `old <= 1` to `limited` → mapping cases 1/0 FAIL. Mutant R: drop the `setdefault`s for nodes → `test_legacy_nodes_and_course_get_defaults` FAILS with "missing the key". Mutant S: in `check_attempts_pair` drop the `isinstance(limit, bool)` clause → the `True` case FAILS. Revert by hand.

- [ ] **Step 9: Commit**

```bash
git add courses/transfer tests
git commit -m "feat(transfer): format 18 carries attempts at course, quiz and question level"
```

---

### Task 8: Remove `max_attempts`; constraints; admin; guards

**Files:**
- Modify: `courses/models.py` (drop `max_attempts`; `Meta.constraints` on `QuestionElement`, `ContentNode`, `Course`)
- Create: `courses/migrations/0072_attempts_constraints.py` (generated)
- Modify: `courses/admin.py`
- Test: `tests/test_attempts_constraints.py`, `tests/test_attempts_migration_populated.py`, `tests/test_attempts_no_stragglers.py`

**Interfaces:**
- Consumes: everything above (no runtime code may still read `max_attempts`).
- Produces: DB constraints named `courses_<model>_att_lim` (question tables, class-interpolated), `courses_contentnode_att_lim`, `courses_course_att_lim`.

- [ ] **Step 1: Write the failing tests.**

`tests/test_attempts_constraints.py`:

```python
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
        ContentNode.objects.filter(pk=unit.pk).update(attempts_mode=mode, attempts_limit=limit)


@pytest.mark.parametrize("mode,limit", BAD_PAIRS + [("inherit", None)])
def test_course_table_rejects(mode, limit):
    course = CourseFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Course.objects.filter(pk=course.pk).update(attempts_mode=mode, attempts_limit=limit)


def test_constraint_names_fit_postgres():
    for model in [*CONCRETE_QUESTION_MODELS, ContentNode, Course]:
        names = [c.name for c in model._meta.constraints if "att" in c.name]
        assert names, model
        assert all(len(n.encode()) <= 63 for n in names), names


def test_admin_cannot_edit_attempts():
    for admin_cls in (CourseAdmin, ContentNodeAdmin):
        assert {"attempts_mode", "attempts_limit"} <= set(admin_cls.readonly_fields)
```

(If `model.objects.create(stem="x")` fails for a type with another required field, give `_row` a branch for it — do not loosen the constraint test.)

`tests/test_attempts_no_stragglers.py`:

```python
"""max_attempts is gone everywhere it could silently survive (spec §4)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = (
    "courses.migrations.0070_attempts_fields",
    "courses.migrations.0071_attempts_data",
    "courses.migrations.0072_attempts_constraints",
)


# The ONE legitimate mention: the v<=17 archive upgrade must name the legacy key.
ALLOWED = {"courses/transfer/payloads.py"}


def test_no_production_reader_or_template_mentions_max_attempts():
    hits = []
    for base in ("courses", "templates", "integrations"):
        for path in (ROOT / base).rglob("*"):
            if path.suffix not in {".py", ".html", ".js"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if "/migrations/" in rel or "/tests/" in rel or rel in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "max_attempts" in text:  # webhook delivery uses MAX_ATTEMPTS (upper)
                hits.append(rel)
    assert hits == []


def test_attempts_migrations_import_no_live_code():
    code = (
        "import importlib, sys\n"
        f"for m in {MIGRATIONS!r}: importlib.import_module(m)\n"
        "print('courses.models' in sys.modules, 'courses.quiz' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False False", out.stdout + out.stderr
```

`tests/test_attempts_migration_populated.py`:

```python
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
    executor.migrate([("courses", "0069_imageelement_float_right")])  # back through 0072..0070
    executor.loader.build_graph()
    call_command("migrate", "courses", verbosity=0)  # forward to HEAD again

    for model, pk in rows:
        q = model.objects.get(pk=pk)
        assert (q.attempts_mode, q.attempts_limit) == ("limited", 5), model
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_attempts_constraints.py tests/test_attempts_no_stragglers.py` → FAIL (no constraints; `models.py` still has `max_attempts`; 0072 missing).

- [ ] **Step 3: Models.** Delete `max_attempts` (and its comment) from `QuestionElement`, and reword the Task 1 comment above `attempts_mode` to "Question-level attempts override (spec 2026-10-20)." (it names the removed field, which the straggler test forbids). Constraints:

`QuestionElement.Meta`:

```python
    class Meta:
        abstract = True
        constraints = [
            # Spec 2026-10-20 §3.2. %(class)s-interpolated (declared on the abstract
            # base) with a short suffix: the longest prefix,
            # courses_extendedresponsequestionelement_, is 40 bytes and Postgres
            # silently truncates names past 63.
            models.CheckConstraint(
                condition=(
                    models.Q(attempts_mode="limited", attempts_limit__gte=1)
                    | models.Q(
                        attempts_mode__in=["inherit", "unlimited"],
                        attempts_limit__isnull=True,
                    )
                ),
                name="%(app_label)s_%(class)s_att_lim",
            )
        ]
```

`ContentNode.Meta` — add the same `CheckConstraint` named `"courses_contentnode_att_lim"` to its existing `constraints` list (create the list / `Meta` if absent; read the class first). `Course.Meta` (add a `Meta` if absent):

```python
        constraints = [
            # No INHERIT: the course is the top level (P2, spec §3.2).
            models.CheckConstraint(
                condition=(
                    models.Q(attempts_mode="limited", attempts_limit__gte=1)
                    | models.Q(attempts_mode="unlimited", attempts_limit__isnull=True)
                ),
                name="courses_course_att_lim",
            )
        ]
```

- [ ] **Step 4: Generate 0072** — `uv run python manage.py makemigrations courses --name attempts_constraints`. Expected: 10 `RemoveField` (`max_attempts`) + 12 `AddConstraint`. Read it: no other operations, no `courses.*` import. Apply: `uv run python manage.py migrate courses`.

- [ ] **Step 5: Admin** — `CourseAdmin` and `ContentNodeAdmin` get `readonly_fields = ("attempts_mode", "attempts_limit")` with a comment: "Edited only through the attempts forms, which own the nulling rule (spec §4); a raw admin edit would hit the DB constraint."

- [ ] **Step 6: Run** — `uv run pytest tests/test_attempts_constraints.py tests/test_attempts_no_stragglers.py tests/test_attempts_migration_populated.py tests/test_attempts_migration.py` → PASS. Then check the TESTS too (the straggler test skips them): `grep -rln "max_attempts" tests courses/tests integrations | grep -v "test_attempts_migration\|test_attempts_transfer\|test_attempts_no_stragglers"` must list only files whose hits are the unrelated webhook `MAX_ATTEMPTS` / `dead_after_max_attempts`, or a legacy-archive payload that is validated ONLY at a version ≤ 17 (a payload shared with a v18 / `None` test does not qualify) — read every other hit and convert it. A straggler hit means a reader/template/comment was missed: fix it (rewrite prose in terms of the effective limit), never whitelist it.

- [ ] **Step 7: Prove they bite.** Mutant T: make the question constraint's second `Q` also allow `attempts_limit__gte=1` → `("inherit", 3)` cases FAIL. Mutant U: add `from courses.quiz import effective_max_attempts` to the top of `0071_attempts_data.py` → the no-import test FAILS. Revert by hand (and re-run `migrate` if you touched a migration).

- [ ] **Step 8: Full test run in chunks** (the whole suite is OOM-killed in one go). Start the test DB container; run the non-e2e suite in ~4 chunks (e.g. `tests/test_[a-f]*.py`, `tests/test_[g-p]*.py`, `tests/test_[q-z]*.py`, `courses/tests integrations`), one at a time. Expected: all PASS; grep each summary line. Any failure: read it (a missed sweep site is the usual cause).

- [ ] **Step 8b: Run the e2e files the sweeps touched.** `git diff --name-only master -- 'tests/test_e2e_*.py'` lists them (14 files mention attempts). Run them with `uv run pytest -m e2e <files>` in chunks of 3–4 files, one chunk at a time (e2e is TRUNCATE-bound; `-n 2` at most), and grep each summary line. Any failure: compare against master before blaming the diff (e2e flakes under load), then fix the sweep site.

- [ ] **Step 9: Commit**

```bash
git add courses/models.py courses/migrations/0072_attempts_constraints.py courses/admin.py tests/test_attempts_constraints.py tests/test_attempts_no_stragglers.py tests/test_attempts_migration_populated.py
git commit -m "feat(attempts): drop max_attempts; DB constraints; read-only admin"
```

---

### Task 9: Polish translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo`
- Modify: `locale/en/LC_MESSAGES/django.po`, `django.mo` (the repo keeps en in step — see commits `4b3fb424`, `1a310859`; en msgstrs stay empty by design, as `tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid` documents)

- [ ] **Step 1:** `uv run python manage.py makemessages -l pl -l en` (check the repo's usual flags in those earlier i18n commits, e.g. `--no-location`, and use the same).
- [ ] **Step 2:** Translate every new msgid. **Clear every `#, fuzzy` pre-fill on these entries — both the flag and the guessed msgstr** (makemessages often pre-fills a wrong translation). Proposed Polish (owner to confirm in review):

| msgid | msgstr |
|---|---|
| Attempts | Próby |
| Attempts per question | Liczba prób na pytanie |
| Number of attempts | Liczba prób |
| Limited to… | Ograniczona do… |
| Unlimited | Bez limitu |
| unlimited | bez limitu |
| Same as quiz (currently: %(value)s) | Jak w quizie (obecnie: %(value)s) |
| Same as course (currently: %(value)s) | Jak w kursie (obecnie: %(value)s) |
| Choose one of the attempts options. | Wybierz jedną z opcji liczby prób. |
| Enter a number of attempts, or choose another option. | Wpisz liczbę prób albo wybierz inną opcję. |
| At most 32767 attempts. For no limit, choose 'Unlimited'. | Najwyżej 32767 prób. Aby nie ograniczać prób, wybierz „Bez limitu”. |
| 0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'. | 0 nie jest limitem. Aby użyć ustawienia quizu, wybierz „Jak w quizie”. |
| 0 isn't a limit. To use the course's setting, choose 'Same as course'. | 0 nie jest limitem. Aby użyć ustawienia kursu, wybierz „Jak w kursie”. |
| 0 isn't a limit. Choose 'Unlimited' or a number from 1. | 0 nie jest limitem. Wybierz „Bez limitu” albo liczbę od 1. |
| Attempts can only be set on a quiz. | Liczbę prób można ustawić tylko w quizie. |
| Specific settings | Własne ustawienia |
| Make every quiz and question use the course setting | Ustaw wszystkim quizom i pytaniom ustawienie kursu |
| Make all questions in this quiz use the quiz setting | Ustaw wszystkim pytaniom w tym quizie ustawienie quizu |
| Settings saved. | Zapisano ustawienia. |
| " and " | " i " |
| %(n)d quiz / quizzes | %(n)d quiz · %(n)d quizy · %(n)d quizów |
| %(n)d question / questions | %(n)d pytanie · %(n)d pytania · %(n)d pytań |
| Keep specific settings (%(what)s has its own / have their own) | Zachowaj własne ustawienia (%(what)s ma własne) · (… mają własne) · (… ma własne) |
| Keep questions' own settings (%(n)d question/s) | Zachowaj własne ustawienia pytań (%(n)d pytanie) · (%(n)d pytania) · (%(n)d pytań) |
| Settings saved. %(what)s now uses / use the course setting. | Zapisano ustawienia. %(what)s korzysta teraz z ustawienia kursu. · … korzystają … · … korzysta … |
| Settings saved. %(n)d question now uses / questions now use the quiz setting. | Zapisano ustawienia. %(n)d pytanie korzysta teraz z ustawienia quizu. · %(n)d pytania korzystają … · %(n)d pytań korzysta … |
| Same as the level above / Limited (model labels) | Jak poziom wyżej / Ograniczona |
| the three transfer messages (`%(what)s: …`) | translate in the same register as the neighbouring transfer messages |

Polish plural order in this catalog: `msgstr[0]` one, `[1]` few (2–4), `[2]` many — confirm against the `Plural-Forms` header.

- [ ] **Step 3:** Delete EVERY `#~` (obsolete) entry makemessages produced in both catalogs, `Max attempts` included — `tests/test_i18n_po_health.py::test_no_obsolete_entries` fails on any. `uv run python manage.py compilemessages -l pl -l en`.
- [ ] **Step 4:** Verify no fuzzy entries remain among the new msgids (CRLF-safe — `grep $` anchors fail on CRLF .po files): `uv run python -c "import polib,sys; po=polib.pofile('locale/pl/LC_MESSAGES/django.po'); bad=[e.msgid for e in po.fuzzy_entries() if 'ttempt' in e.msgid or 'Same as' in e.msgid or 'Settings saved' in e.msgid]; print(bad); sys.exit(bool(bad))"` (if `polib` is unavailable, read the entries by eye). Run the i18n tests: `uv run pytest $(ls tests/test_*i18n*.py tests/test_*locale*.py 2>/dev/null)` → PASS.
- [ ] **Step 5: Commit** — `git add locale && git commit -m "i18n: attempts defaults strings (pl translated, en in step)"`.

---

### Task 10: e2e and screenshots

**Files:**
- Create: `tests/test_e2e_attempts.py`

- [ ] **Step 1: Write the e2e tests** (mirror the harness in `tests/test_e2e_quiz.py`: `pytestmark = pytest.mark.e2e`, the `_allow_async_unsafe` fixture, `_login` via the allauth form; author = a PA via the same group mechanism the other authoring e2e files use — copy their author helper). Four tests:

1. `test_course_reset_through_the_ui` — seed a quiz with one short-text question `**attempts(2)`; author opens the course edit page, sets *Attempts per question* = Limited to… 3, picks "Make every quiz and question use the course setting", saves; assert the success message is visible. A fresh enrolled student answers wrong 3 times (each accepted — feedback appears, not the locked 409 reload) and the 4th attempt is refused (input disabled / `data-quiz-locked`).
2. `test_question_override_beats_unlimited_quiz` — quiz unit set to Unlimited in the editor's Settings panel (open the `<details>`, choose Unlimited, save); a question keeps `**attempts(2)`; the student is locked after 2 wrong answers.
3. `test_zero_shows_the_d9_message` — author edits a quiz question, selects *Limited to…*, types `0`, saves; the D9 message ("0 isn't a limit. To use the course's setting, choose 'Same as course'.") is visible next to the field — proves the browser did not swallow it (no `min`).
4. `test_limit_input_reveals_after_a_fragment_swap` — author saves any element (fragment swap), opens a question form, the number input is hidden while *Same as course* is selected, selecting *Limited to…* makes it visible (`expect(locator).to_be_visible()`), selecting *Unlimited* hides it again.

Sync on conditions (`expect(...)`), never `sleep`; assert on what the user sees.

- [ ] **Step 2: Run** — `uv run pytest -m e2e tests/test_e2e_attempts.py` → PASS. Prove one bites: temporarily delete the CSS rule from Task 4 → test 4 FAILS (input visible while inherit is selected). Restore by hand.

- [ ] **Step 3: Screenshots** (not committed; tracked screenshot dirs must not change — check `git status` after). With a dev server and seeded data, capture light **and** dark (`page.emulate_media(color_scheme="dark")`): the question editor with the Attempts select (inherit and limited states), the quiz Settings panel with the reset radios, the course form with the reset choice. Save under the session scratchpad, judge dark separately (contrast of the help text and radios), and send them to the owner.

- [ ] **Step 4: Commit** — `git add tests/test_e2e_attempts.py && git commit -m "test(e2e): attempts defaults through the real UI"`.

---

### Task 11: Wrap-up

- [ ] **Step 1: Merge guard** — `git fetch origin && git log origin/master --oneline -5`; check open branches/PRs (`gh pr list`) for another `FORMAT_VERSION = 18`: `gh pr list --json headRefName --jq '.[].headRefName' | while read b; do git show "origin/$b:courses/transfer/schema.py" 2>/dev/null | grep -q "FORMAT_VERSION = 18" && echo "$b"; done`. Any hit: stop and tell the owner (identical-line bumps merge silently).
- [ ] **Step 2: Lint** — `uv run ruff check --no-cache .` and `uv run ruff format --check .` → clean.
- [ ] **Step 3: Spec status** — change the spec's status line to "implemented on `feat/attempts-defaults`" and commit.
- [ ] **Step 4:** Use superpowers:finishing-a-development-branch (PR description includes the Task 6 Step 7 `updated`-reader audit and the deploy note: migrations 0070–0072 run on deploy; no FORMAT_VERSION collision checked).
