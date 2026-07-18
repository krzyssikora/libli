# Help Screenshot Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the plumbing that lets in-app `/help/` topics carry real, deterministic, committed screenshots — a rich idempotent demo seed, a render-time `static:` image rewrite, a committed static home, a deterministic Playwright capture harness — and prove it end-to-end by illustrating the Course-builder topic with one committed screenshot.

**Architecture:** Enrich the existing `courses` `seed_demo_course` management command into the deterministic capture fixture (users, diverse leaf elements, a graded quiz, a group with grades, and a materialized demo image). Add a `static:` sentinel rewrite to `core/help.py` so topic markdown can reference committed images that resolve through Django `static()` (manifest-safe). Capture the builder page with a non-`test_`-prefixed Playwright module that regenerates the PNG into an app static dir. Prove the pipeline with fast, non-e2e tests.

**Tech Stack:** Django, pytest + pytest-django, pytest-playwright (sync API, Chromium), Python `markdown`, allauth, WhiteNoise (prod static).

## Global Constraints

- **Idempotent seed:** re-running `seed_demo_course` must add no rows and change no file identity. Every new row uses `get_or_create` on a natural/unique key or an existence guard; no bare `create()` for repeatable data.
- **Seed must NOT import from `tests/`** — management commands ship without test code. Reuse production helpers: `accounts.emails.ensure_verified_primary_email`, `accounts.services.set_user_role`, `institution.roles.seed_roles` / `COURSE_ADMIN`.
- **Single password constant:** define `DEMO_PASSWORD = "demo-pass-123"` once at module level in the command; reuse for every demo user (do not import `TEST_PASSWORD`; avoid scattering new literals — GitGuardian).
- **Determinism knobs (capture):** viewport `1280×800`; light theme (seed `User.theme="light"` **and** `page.emulate_media(color_scheme="light")`); English (`User.language="en"`, no language switch); `page.emulate_media(reduced_motion="reduce")`; navigate via the fixed slug `demo-course`; capture is an **element-clipped** `locator("section.builder").screenshot()`; output path anchored to `settings.BASE_DIR`.
- **Static home:** committed screenshots live under `core/static/core/img/help/`. Topics reference them only via the `static:` sentinel (never a hardcoded `/static/…` URL).
- **Capture isolation:** the capture module is `tests/capture_help_screenshots.py` (no `test_` prefix, one `test_`-named function inside). It must never run in the unit CI job (`pytest -n auto`, bare) or the e2e job (`pytest -m e2e`), but must be collectable via `pytest tests/capture_help_screenshots.py`. Do **not** mark it `@pytest.mark.e2e` (that would make the explicit-path run deselect it under the default `-m 'not e2e'`).
- **Tooling:** run everything through `uv run` (ruff/pytest/manage are not on PATH otherwise). Before each commit run **`uv run ruff check --fix <files>` FIRST** (ruff's `I`/isort with `force-single-line` sorts new imports into their stdlib/django/first-party groups — `ruff format` does **not** sort imports), **then** `uv run ruff format <files>`. New imports may be pasted in any position; `--fix` reorders them, so the "Lint + commit" steps below use this `--fix`-first order.
- **CRLF-safe:** all files are CRLF in the working tree. Never anchor a grep on `$` or `\n`; use `\r?\n`. Locate code by searching quoted strings, not line numbers.
- **No new element MODEL:** we reuse existing element classes, so the `ELEMENT_MODELS`/transfer-schema count asserts are untouched. Adding a help topic image needs no registry bump.
- **i18n:** seed data strings and help markdown are not gettext catalog entries; no `.po` change is expected. If any translatable string is nonetheless touched, run `uv run python manage.py makemessages -a --no-obsolete` and reconcile.

---

## Task 1: `static:` sentinel rewrite in the help renderer

**Files:**
- Modify: `core/help.py` (`render_markdown_doc`)
- Test: `tests/test_help.py`

**Interfaces:**
- Produces: `resolve_static_srcs(html: str) -> str` — rewrites `src="static:REL"` → `src="{static('REL')}"` via `django.templatetags.static.static`, leaving all other `src` values untouched.
- Produces: `render_markdown_doc(rel_path, *, resolve_static: bool = True) -> str` — same as today, plus the rewrite (skippable for the coverage scan in Task 7).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_help.py`:

```python
def test_resolve_static_srcs_rewrites_only_sentinel():
    from core.help import resolve_static_srcs

    html = (
        '<img alt="a" src="static:core/img/help/x.png" />'
        '<img alt="b" src="/already/abs.png" />'
        '<img alt="c" src="https://ex.com/y.png" />'
    )
    out = resolve_static_srcs(html)
    assert 'src="/static/core/img/help/x.png"' in out  # test uses plain storage
    assert 'static:core/img/help/x.png' not in out
    assert 'src="/already/abs.png"' in out
    assert 'src="https://ex.com/y.png"' in out


def test_render_markdown_doc_can_skip_static_rewrite(tmp_path, monkeypatch):
    import core.help as help_mod

    monkeypatch.setattr(help_mod, "DOCS_ROOT", tmp_path)
    (tmp_path / "d.md").write_text("![a](static:core/img/help/x.png)\n", encoding="utf-8")

    resolved = help_mod.render_markdown_doc("d.md")
    assert 'src="/static/core/img/help/x.png"' in resolved

    raw = help_mod.render_markdown_doc("d.md", resolve_static=False)
    assert "static:core/img/help/x.png" in raw
    assert "/static/core/img/help/x.png" not in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_help.py::test_resolve_static_srcs_rewrites_only_sentinel tests/test_help.py::test_render_markdown_doc_can_skip_static_rewrite -v`
Expected: FAIL (`ImportError: cannot import name 'resolve_static_srcs'` / unexpected `resolve_static` kwarg).

- [ ] **Step 3: Implement the rewrite in `core/help.py`**

Add near the top (after the existing imports):

```python
import re

from django.templatetags.static import static

# Rewrites `src="static:REL"` (our repo-authored sentinel) to the static()-resolved
# URL. Manifest-safe: static() consults the staticfiles manifest in production, so a
# committed image resolves to its content-hashed name. Only the `static:` sentinel is
# touched; ordinary/external src values pass through unchanged.
_STATIC_SRC = re.compile(r'src="static:([^"]+)"')


def resolve_static_srcs(html):
    return _STATIC_SRC.sub(lambda m: f'src="{static(m.group(1))}"', html)
```

Then change `render_markdown_doc`:

```python
def render_markdown_doc(rel_path, *, resolve_static=True):
    text = (DOCS_ROOT / rel_path).read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["fenced_code", "tables"])
    return resolve_static_srcs(html) if resolve_static else html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_help.py -v`
Expected: PASS (all existing help tests plus the two new ones).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix core/help.py tests/test_help.py
uv run ruff format core/help.py tests/test_help.py
git add core/help.py tests/test_help.py
git commit -m "feat(help): static: sentinel rewrite in the markdown renderer"
```

---

## Task 2: Seed — verified Course-Admin owner + students

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py`
- Test: `tests/test_seed_demo_course.py`

**Interfaces:**
- Produces (in the command): `DEMO_PASSWORD` constant; `_user(username, display_name, *, email, is_staff=False, role=None)` returning a `User` with a verified primary `EmailAddress`; a Course-Admin user `demo_teacher` set as `demo_course.owner`; students `demo_student`, `demo_s1`, `demo_s2`, `demo_s3` (each verified). These users + `course` are consumed by Tasks 3–5.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_seed_demo_course.py`:

```python
@pytest.mark.django_db
def test_seed_creates_verified_ca_owner_and_students():
    from django.contrib.auth import get_user_model
    from allauth.account.models import EmailAddress
    from courses.models import Course

    call_command("seed_demo_course")
    User = get_user_model()

    teacher = User.objects.get(username="demo_teacher")
    assert teacher.is_staff is True
    assert teacher.theme == "light"
    assert teacher.language == "en"
    assert EmailAddress.objects.filter(
        user=teacher, verified=True, primary=True
    ).exists()

    course = Course.objects.get(slug="demo-course")
    assert course.owner_id == teacher.id  # builder access = can_manage_course(owner)

    for name in ("demo_student", "demo_s1", "demo_s2", "demo_s3"):
        u = User.objects.get(username=name)
        assert EmailAddress.objects.filter(user=u, verified=True).exists()


@pytest.mark.django_db
def test_seeded_ca_can_open_builder(client):
    # The whole PoC rests on the seeded CA being able to open the demo-course
    # builder. Pin it here (200, not 302/403) so a missing owner relationship
    # fails fast in CI instead of only as a capture selector timeout.
    from django.contrib.auth import get_user_model

    call_command("seed_demo_course")
    teacher = get_user_model().objects.get(username="demo_teacher")
    client.force_login(teacher)
    resp = client.get("/manage/courses/demo-course/build/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_seed_demo_course.py::test_seed_creates_verified_ca_owner_and_students tests/test_seed_demo_course.py::test_seeded_ca_can_open_builder -v`
Expected: FAIL (`User.DoesNotExist: demo_teacher`).

- [ ] **Step 3: Implement user seeding**

In `courses/management/commands/seed_demo_course.py`, add imports at the top:

```python
from accounts.emails import ensure_verified_primary_email
from accounts.services import set_user_role
from institution.roles import COURSE_ADMIN
from institution.roles import seed_roles

DEMO_PASSWORD = "demo-pass-123"  # single reused demo credential (not a test literal)
```

Add a helper method on `Command`:

```python
    def _user(self, username, display_name, *, email, is_staff=False, role=None):
        user, created = User.objects.get_or_create(
            username=username, defaults={"display_name": display_name}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
        user.theme = "light"
        user.language = "en"
        user.is_staff = is_staff or user.is_staff
        user.save()
        ensure_verified_primary_email(user, email)
        if role is not None:
            set_user_role(user, role)  # sets is_staff + role group idempotently
        return user
```

In `handle()`, the user-seeding must run **before** any element/quiz/group call that depends on `self.teacher`/`self.group_students`/`self.course`. Do BOTH of the following:

**(a)** Immediately after `course.subjects.add(subject)` (near the top of `handle()`, **before** the `_node` calls), insert:

```python
        self.course = course
        seed_roles()  # ensure the 4 role auth-groups + perms exist before set_user_role
        teacher = self._user(
            "demo_teacher", "Demo Teacher",
            email="demo_teacher@demo.example", role=COURSE_ADMIN,
        )
        course.owner = teacher  # builder access requires ownership (can_manage_course)
        course.save(update_fields=["owner"])

        student = self._user("demo_student", "Demo Student", email="demo_student@demo.example")
        s1 = self._user("demo_s1", "Ada Demo", email="demo_s1@demo.example")
        s2 = self._user("demo_s2", "Ben Demo", email="demo_s2@demo.example")
        s3 = self._user("demo_s3", "Cleo Demo", email="demo_s3@demo.example")
        for st in (student, s1, s2, s3):
            Enrollment.objects.get_or_create(student=st, course=course)
        self.teacher = teacher              # consumed by Task 4
        self.group_students = [s1, s2, s3]  # consumed by Task 4
```

**(b)** DELETE the old student block near the end of `handle()` (the `student, created = User.objects.get_or_create(username="demo_student", ...)` / `set_password` / `Enrollment.objects.get_or_create(student=student, course=course)` lines) — it is fully replaced by (a).

Keep the existing `self.stdout.write(...SUCCESS...)` line at the very end of `handle()`. After this task, `handle()`'s order is: subject/course → **users** (`self.course`/`self.teacher`/`self.group_students` set) → `_node` calls → element calls, so every later helper's dependencies already exist.

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/test_seed_demo_course.py -v`
Expected: PASS (existing idempotency test + the two new tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
uv run ruff format courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git add courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git commit -m "feat(seed): verified Course-Admin owner + students in demo seed"
```

---

## Task 3: Seed — diverse leaf elements

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py`
- Test: `tests/test_seed_demo_course.py`

**Interfaces:**
- Consumes: `_upsert(unit, model, **fields)` (existing), the `lesson` node from `handle()`.
- Produces: `CalloutElement`, `SpoilerElement`, `TableElement` attached to the `Core lesson` unit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seed_demo_course.py`:

```python
@pytest.mark.django_db
def test_seed_has_diverse_leaf_elements():
    from courses.models import CalloutElement, SpoilerElement, TableElement

    call_command("seed_demo_course")
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1

    call_command("seed_demo_course")  # idempotent: still one of each
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_seed_demo_course.py::test_seed_has_diverse_leaf_elements -v`
Expected: FAIL (counts are 0).

- [ ] **Step 3: Implement leaf-element seeding**

Add imports in `seed_demo_course.py`:

```python
from courses.models import CalloutElement
from courses.models import SpoilerElement
from courses.models import TableElement
```

Add helper methods on `Command`:

```python
    def _callout(self, unit):
        self._upsert(
            unit, CalloutElement,
            kind="tip", heading="Remember",
            body="<p>Order of operations matters.</p>",
        )

    def _spoiler(self, unit):
        self._upsert(
            unit, SpoilerElement,
            label="Show the answer", body="<p>42</p>",
        )

    def _table(self, unit):
        self._upsert(
            unit, TableElement,
            data=TableElement.normalize_data({
                "header_row": True, "border": "grid",
                "cells": [
                    [{"html": "Symbol"}, {"html": "Meaning"}],
                    [{"html": "π"}, {"html": "pi"}],
                ],
            }),
        )
```

In `handle()`, after the existing `self._image(extra, "bonus-image", "Decorative diagram")` line, add:

```python
        self._callout(lesson)
        self._spoiler(lesson)
        self._table(lesson)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/test_seed_demo_course.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
uv run ruff format courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git add courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git commit -m "feat(seed): diverse leaf elements (callout, spoiler, table)"
```

---

## Task 4: Seed — graded quiz + group with populated grades

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py`
- Test: `tests/test_seed_demo_course.py`

**Interfaces:**
- Consumes: `self.teacher`, `self.group_students` (Task 2), the `chapter` node and `course` from `handle()`.
- Produces: a quiz `ContentNode` (`unit_type="quiz"`) with a `ShortTextQuestionElement` + `ChoiceQuestionElement`; one SUBMITTED, scored `QuizSubmission` per group student on that quiz; a `Group` (`Demo Group`) on the course with the teacher and the 3 students. This makes the analytics matrix / gradebook cells populate.

**Grading path (faithful, matches `courses/views.py` submit):** for each question, `f = to_stored_fraction(question.mark(answer).fraction)`, `QuestionResponse(fraction=f, earned_marks=earned_marks(f, q.max_marks), ...)`, then `finalize_submission(quiz_unit, submission)` which freezes `QuizSubmission.score`/`max_score` and sets `status=SUBMITTED` — exactly what `build_results_matrix` / `build_quiz_gradebook` read.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seed_demo_course.py`:

```python
@pytest.mark.django_db
def test_seed_quiz_group_populate_analytics():
    from django.contrib.auth import get_user_model
    from courses.models import ContentNode, Course, QuizSubmission
    from grouping.models import Group, GroupMembership
    from courses.rollups import build_results_matrix, quiz_units_in_order

    call_command("seed_demo_course")
    User = get_user_model()
    course = Course.objects.get(slug="demo-course")

    quizzes = list(quiz_units_in_order(course))
    assert len(quizzes) == 1
    quiz = quizzes[0]
    assert quiz.unit_type == "quiz"

    group = Group.objects.get(name="Demo Group", course=course)
    students = [m.student for m in GroupMembership.objects.filter(group=group)]
    assert len(students) == 3
    assert group.teachers.filter(username="demo_teacher").exists()

    # Every group member has a SUBMITTED, scored submission on the course gradeable
    # (the non-empty-intersection requirement — a populated matrix, not empty cells).
    for st in students:
        sub = QuizSubmission.objects.get(student=st, unit=quiz)
        assert sub.status == QuizSubmission.Status.SUBMITTED
        assert sub.max_score and sub.max_score > 0

    matrix = build_results_matrix(course, students, expanded=set(), values="percent")
    # at least one populated cell exists across the group×quiz grid. Cells are dicts
    # {"percent": .., "label": ..} (courses/rollups.py _cell); a populated cell has a
    # non-None percent.
    flat = [c for row in matrix["rows"] for c in row["cells"]]
    assert any(c["percent"] is not None for c in flat)


@pytest.mark.django_db
def test_seed_quiz_group_idempotent():
    from courses.models import QuizSubmission

    call_command("seed_demo_course")
    subs = QuizSubmission.objects.count()
    call_command("seed_demo_course")
    assert QuizSubmission.objects.count() == subs
```

> Note: `build_results_matrix(course, students, expanded=frozenset(), values="percent")` returns rows whose `cells` are dicts with a `percent` key (`courses/rollups.py`, `_cell`); it branches only on `values == "raw"` (any other value is percent mode). If the exact keys differ at implementation time, read that function and adjust the cell access, keeping "≥1 populated cell"; do not weaken it to "a submission exists".

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_seed_demo_course.py::test_seed_quiz_group_populate_analytics tests/test_seed_demo_course.py::test_seed_quiz_group_idempotent -v`
Expected: FAIL (no quiz unit / no group).

- [ ] **Step 3: Implement quiz + group + grading**

Add imports in `seed_demo_course.py`:

```python
from decimal import Decimal

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import QuestionResponse
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.quiz import finalize_submission
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from grouping.models import Group
from grouping.models import GroupMembership
```

Add helper methods on `Command`:

```python
    def _quiz(self, chapter):
        quiz = self._node(self.course, chapter, "unit", "Demo quiz", "quiz")
        if not quiz.elements.exists():
            short = ShortTextQuestionElement.objects.create(
                stem="What is 2 + 2?", accepted="4",
                marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
            )
            self.q_short = Element.objects.create(unit=quiz, content_object=short)
            choice = ChoiceQuestionElement.objects.create(
                stem="Which are prime?", multiple=True,
                marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("1"),
            )
            Choice.objects.create(question=choice, text="2", is_correct=True)
            Choice.objects.create(question=choice, text="3", is_correct=True)
            Choice.objects.create(question=choice, text="4", is_correct=False)
            self.q_choice = Element.objects.create(unit=quiz, content_object=choice)
        else:
            self.q_short = quiz.elements.filter(
                content_type__model="shorttextquestionelement"
            ).first()
            self.q_choice = quiz.elements.filter(
                content_type__model="choicequestionelement"
            ).first()
        return quiz

    def _respond(self, submission, element, answer):
        question = element.content_object
        f = to_stored_fraction(question.mark(answer).fraction)
        QuestionResponse.objects.get_or_create(
            submission=submission, element=element,
            defaults={
                "fraction": f,
                "earned_marks": earned_marks(f, question.max_marks),
                "latest_answer": sorted(answer) if isinstance(answer, set) else answer,
                "attempt_count": 1,
            },
        )

    def _graded_submission(self, quiz, student, short_answer, choice_answer):
        submission, _ = QuizSubmission.objects.get_or_create(
            student=student, unit=quiz,
            defaults={"status": QuizSubmission.Status.IN_PROGRESS},
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return  # already graded on a prior run — idempotent
        self._respond(submission, self.q_short, short_answer)
        correct_ids = set(
            self.q_choice.content_object.choices.filter(is_correct=True).values_list(
                "pk", flat=True
            )
        )
        # choice_answer: "full" -> all correct, "partial" -> one correct only
        picks = correct_ids if choice_answer == "full" else set(list(correct_ids)[:1])
        self._respond(submission, self.q_choice, picks)
        finalize_submission(quiz, submission)  # freezes score/max_score, SUBMITTED

    def _group(self, quiz):
        group, _ = Group.objects.get_or_create(name="Demo Group", course=self.course)
        group.teachers.add(self.teacher)
        for st in self.group_students:
            GroupMembership.objects.get_or_create(group=group, student=st)
        # varied but fixed scores across the three students
        plans = [("4", "full"), ("4", "partial"), ("5", "partial")]
        for st, (short_ans, choice_ans) in zip(self.group_students, plans):
            self._graded_submission(quiz, st, short_ans, choice_ans)
        return group
```

In `handle()`, after the leaf-element calls from Task 3 (which run after Task 2's user-seeding block, so `self.teacher`/`self.group_students`/`self.course` are already set), add:

```python
        quiz = self._quiz(chapter)
        self._group(quiz)
```

`chapter` is the node created near the top of `handle()` and is in scope here. Do **not** re-add `self.course = course` — Task 2 already sets it.

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/test_seed_demo_course.py -v`
Expected: PASS. If `build_results_matrix`'s return shape differs, read `courses/rollups.py` and fix only the assertion's cell-access, keeping "≥1 populated cell".

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
uv run ruff format courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git add courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git commit -m "feat(seed): graded quiz + group with populated analytics grades"
```

---

## Task 5: Fix the broken demo image (materialize into MEDIA)

**Files:**
- Create: `courses/management/commands/seed_assets/demo.png` (committed source)
- Modify: `courses/management/commands/seed_demo_course.py` (`_image`)
- Test: `tests/test_seed_demo_course.py`

**Interfaces:**
- Consumes: `_upsert`, the existing `_image(unit, slug, alt)` helper and its `MediaAsset` lookup.
- Produces: a real on-disk MEDIA file for the demo `ImageElement`, materialized idempotently from a committed source PNG.

- [ ] **Step 1: Create the committed source PNG**

Run this once to write a small valid PNG (a 16×16 solid tile — enough that the image renders, not broken):

```bash
uv run python - <<'PY'
import base64, pathlib
# 16x16 opaque PNG (valid, tiny). Generated deterministically.
b64 = (
 "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAHElEQVR42mNk"
 "YPhfz0AEYBxVSF+Fo4rGFY0rAgASIwMBY5r5wQAAAABJRU5ErkJggg=="
)
p = pathlib.Path("courses/management/commands/seed_assets")
p.mkdir(parents=True, exist_ok=True)
(p / "demo.png").write_bytes(base64.b64decode(b64))
print("wrote", p / "demo.png")
PY
```

Verify it is a real PNG:

Run: `uv run python -c "from PIL import Image; print(Image.open('courses/management/commands/seed_assets/demo.png').size)"`
Expected: `(16, 16)`.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_seed_demo_course.py`:

```python
@pytest.mark.django_db
def test_seed_materializes_demo_image_idempotently(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from courses.models import MediaAsset

    call_command("seed_demo_course")
    asset = MediaAsset.objects.get(original_filename="demo.png")
    assert asset.file  # a file is set
    assert asset.file.storage.exists(asset.file.name)  # and exists on disk
    assert asset.file.size > 0
    first_name = asset.file.name

    call_command("seed_demo_course")  # rerun
    asset.refresh_from_db()
    assert asset.file.name == first_name  # stable name, no demo_<rand>.png
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run python -m pytest tests/test_seed_demo_course.py::test_seed_materializes_demo_image_idempotently -v`
Expected: FAIL (`asset.file.storage.exists(...)` is False — the current seed sets a path string with no bytes).

- [ ] **Step 4: Implement materialization in `_image`**

Add imports in `seed_demo_course.py`:

```python
from pathlib import Path

from django.core.files.base import ContentFile

_DEMO_PNG = Path(__file__).resolve().parent / "seed_assets" / "demo.png"
```

Replace the body of `_image` with:

```python
    def _image(self, unit, slug, alt):
        course = unit.course
        asset = MediaAsset.objects.filter(
            course=course, original_filename="demo.png"
        ).first()
        if asset is None:
            asset = MediaAsset.objects.create(
                course=course, kind="image", original_filename="demo.png"
            )
        # Materialize real bytes idempotently: FileField.save() would append a random
        # suffix if the target name already exists (get_available_name), so only write
        # when there is no backing file on disk yet — keeping a stable "demo.png" name.
        if not asset.file or not asset.file.storage.exists(asset.file.name):
            asset.file.save("demo.png", ContentFile(_DEMO_PNG.read_bytes()), save=True)
        self._upsert(unit, ImageElement, media=asset, alt=alt)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/test_seed_demo_course.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit (including the binary asset)**

```bash
uv run ruff check --fix courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
uv run ruff format courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git add courses/management/commands/seed_assets/demo.png courses/management/commands/seed_demo_course.py tests/test_seed_demo_course.py
git commit -m "fix(seed): materialize a real demo image into MEDIA (closes broken-image #1.5)"
```

---

## Task 6: Capture harness + collection-isolation checks

**Files:**
- Create: `tests/capture_help_screenshots.py` (no `test_` prefix — regeneration tool)
- Create: `tests/test_help_capture_isolation.py` (the CI-isolation checks)

**Interfaces:**
- Consumes: `seed_demo_course` (Tasks 2–5), the `live_server` + `page` pytest-playwright fixtures, the existing e2e login pattern.
- Produces: `core/static/core/img/help/builder-tree.png` when run explicitly.

- [ ] **Step 1: Write the capture module**

Create `tests/capture_help_screenshots.py`:

```python
"""Deterministic help-screenshot capture (regeneration tool, not a CI test).

Run explicitly to (re)generate committed help screenshots:

    uv run playwright install chromium   # first time only
    uv run python -m pytest tests/capture_help_screenshots.py

This file is deliberately NOT prefixed `test_`, so pytest does not auto-collect it
in the unit CI job (bare `pytest -n auto`) or the e2e job (`pytest -m e2e`). Passing
its path explicitly bypasses the `python_files` filter, so the `test_`-named function
below still runs. It is NOT marked `@pytest.mark.e2e` (that would make the explicit
run deselect it under the default `-m 'not e2e'`).
"""

import os

import pytest
from django.conf import settings
from django.core.management import call_command

pytestmark = pytest.mark.django_db(transaction=True)  # committed rows visible to server


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


DEMO_PASSWORD = "demo-pass-123"  # mirrors the seed's DEMO_PASSWORD


def _login(page, live_server, username, password=DEMO_PASSWORD):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()


def test_capture_help_screenshots(live_server, page):
    call_command("seed_demo_course")

    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme="light", reduced_motion="reduce")

    # Tripwire: fail if any image request on the captured page returns >= 400. The
    # builder tree renders no MEDIA image (the demo image is exercised only in lesson
    # views — slice 3), so today this guards static assets and future MEDIA-rendering
    # captures; the Task 5 image fix is validated by the seed test, not here.
    bad_images = []

    def _on_response(resp):
        if resp.request.resource_type == "image" and resp.status >= 400:
            bad_images.append((resp.url, resp.status))

    page.on("response", _on_response)

    _login(page, live_server, "demo_teacher")
    page.goto(f"{live_server.url}/manage/courses/demo-course/build/")
    page.locator(".builder__tree").wait_for(state="visible")
    page.wait_for_load_state("networkidle")

    assert not bad_images, f"broken image request(s) on builder page: {bad_images}"

    out_dir = settings.BASE_DIR / "core" / "static" / "core" / "img" / "help"
    out_dir.mkdir(parents=True, exist_ok=True)
    page.locator("section.builder").screenshot(path=str(out_dir / "builder-tree.png"))
```

- [ ] **Step 2: Write the collection-isolation checks**

Create `tests/test_help_capture_isolation.py`:

```python
"""The capture module must never run in CI (unit or e2e) but must be collectable on
explicit invocation. These checks shell out to `pytest --collect-only` in a subprocess
(an in-process test cannot observe another collection)."""

import subprocess
import sys

from django.conf import settings

CAP = "tests/capture_help_screenshots.py"
CAP_NODE = "test_capture_help_screenshots"


def _collect(args):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
        cwd=str(settings.BASE_DIR), capture_output=True, text=True, timeout=300,
    )
    return proc.stdout + proc.stderr


def test_capture_not_collected_by_bare_run():
    # One full walk of tests/ (mirrors the unit CI job's bare auto-collection). The
    # capture file is not test_-prefixed, so it is absent. This is the ONLY check that
    # walks the whole tree; keep the timeout generous.
    out = _collect(["tests"])
    assert CAP_NODE not in out


def test_capture_deselected_under_e2e_marker():
    # Even on an explicit path, -m e2e deselects the unmarked capture fn (cheap: one
    # file, no tree walk). The `e2e` marker is registered in pyproject.toml (no
    # strict-markers), so `-m e2e` does not error.
    out = _collect(["-m", "e2e", CAP])
    assert CAP_NODE not in out


def test_capture_collected_on_explicit_path():
    # Explicit path bypasses the python_files filter; the test_-named fn is collected.
    out = _collect([CAP])
    assert CAP_NODE in out
```

- [ ] **Step 3: Run the isolation checks**

Run: `uv run python -m pytest tests/test_help_capture_isolation.py -v`
Expected: PASS (capture module absent from bare + e2e collection, present on explicit path). If `test_capture_collected_on_explicit_path` fails, the filename mechanism does not collect it on this pytest/config — fall back to the marker mechanism per the spec (mark the function `@pytest.mark.capture`, register the marker in `pyproject.toml`, add `-m 'not capture'` to BOTH CI jobs, and change these assertions to "not selected" under those job commands).

- [ ] **Step 4: Smoke-run the capture (produces the PNG for Task 7)**

```bash
uv run playwright install chromium   # if not already installed
uv run python -m pytest tests/capture_help_screenshots.py -v
```
Expected: PASS, and `core/static/core/img/help/builder-tree.png` now exists. Run in the FOREGROUND (never backgrounded — a backgrounded `-m e2e`-style run can leave runaway Chromium). Do NOT commit the PNG in this task; it is committed in Task 7.

- [ ] **Step 5: Lint + commit (harness + isolation checks only, not the PNG yet)**

```bash
uv run ruff check --fix tests/capture_help_screenshots.py tests/test_help_capture_isolation.py
uv run ruff format tests/capture_help_screenshots.py tests/test_help_capture_isolation.py
git add tests/capture_help_screenshots.py tests/test_help_capture_isolation.py
git commit -m "feat(help): deterministic Playwright capture harness + CI isolation checks"
```

---

## Task 7: PoC illustration — embed screenshot, proof + coverage tests

**Files:**
- Add (binary): `core/static/core/img/help/builder-tree.png` (produced in Task 6 Step 4)
- Modify: `docs/help/course-admin/builder.md` (EN topic)
- Test: `tests/test_help.py`

**Interfaces:**
- Consumes: `resolve_static_srcs` / `render_markdown_doc(..., resolve_static=...)` (Task 1), the committed PNG, `staticfiles.finders`.

- [ ] **Step 1: Embed the screenshot in the EN builder topic**

In `docs/help/course-admin/builder.md`, add near the top of the body (after the first heading paragraph) a figure line:

```markdown
![The course builder showing the demo course tree](static:core/img/help/builder-tree.png)
```

Leave `docs/help/course-admin/builder.pl.md` unchanged (PL illustration is slice 3).

- [ ] **Step 2: Write the proof + coverage tests**

Add to `tests/test_help.py`:

```python
def test_builder_topic_embeds_existing_screenshot():
    from django.contrib.staticfiles import finders
    from core.help import render_markdown_doc

    html = render_markdown_doc("help/course-admin/builder.md")
    assert 'src="/static/core/img/help/builder-tree.png"' in html  # rewrite applied
    # bridge URL -> disk via the RAW sentinel rel path (not the rendered /static src)
    assert finders.find("core/img/help/builder-tree.png") is not None


def test_all_topics_static_refs_resolve():
    """Every `static:` image reference in every topic resolves to a real file.
    Scans the PRE-rewrite render (image nodes only), so a topic that merely
    documents the sentinel in prose/code produces no <img> and is not scanned."""
    import re
    from django.contrib.staticfiles import finders
    from core.help import TOPICS, render_markdown_doc

    pat = re.compile(r'<img[^>]+src="static:([^"]+)"')
    for topic in TOPICS:
        raw = render_markdown_doc(topic.path, resolve_static=False)
        for rel in pat.findall(raw):
            assert finders.find(rel) is not None, f"{topic.slug}: missing {rel}"
```

- [ ] **Step 3: Run to verify pass (image already committed-in-tree from Task 6 Step 4)**

Run: `uv run python -m pytest tests/test_help.py -v`
Expected: PASS. If `finders.find` returns `None`, the PNG was not produced — re-run Task 6 Step 4.

- [ ] **Step 4: Confirm the full non-e2e suite + ruff are green**

Run: `uv run python -m pytest -q`
Run: `uv run ruff check .`
Expected: all pass; no e2e collected (capture module excluded).

- [ ] **Step 5: Commit the PNG, the topic edit, and the tests**

```bash
git add core/static/core/img/help/builder-tree.png docs/help/course-admin/builder.md tests/test_help.py
git commit -m "feat(help): illustrate the builder topic with a committed screenshot (PoC)"
```

---

## Self-Review notes (spec coverage)

- Enriched idempotent seed — Tasks 2–5. Verified CA owner (correct `can_manage_course` mechanism) + students (2), diverse leaf elements (3), graded quiz unified with group grades so the analytics matrix populates (4), materialized demo image closing §1.5 (5).
- `static:` sentinel rewrite, manifest-safe — Task 1. Coverage scan on pre-rewrite image nodes — Task 7 `test_all_topics_static_refs_resolve`.
- Deterministic capture harness (viewport/theme/locale/motion/slug/element-clip/repo-root path) + response-listener broken-image guard — Task 6. MEDIA-serving intentionally out of scope: the builder page renders the structural tree only and requests no MEDIA image (spec case ii); the §1.5 fix is validated by Task 5's seed test. If a future capture targets a MEDIA-rendering view, add MEDIA serving then.
- Isolation via non-`test_` filename, verified both directions via subprocess `--collect-only` — Task 6, with the marker fallback spelled out in Step 3.
- PoC proof test bridging URL→disk via `finders.find` on the raw sentinel — Task 7. `finders.find` resolves against the app **source** static dir, so these tests go green as soon as the PNG exists **on disk** (Task 6 Step 4), not at commit time (Task 7 Step 5) — the expected red→green transition happens at Step 4. (If Task 7's tests are written before Step 4 produces the PNG, they are red — the desired falsifiable signal.)
- Existing seed shape/count assertions: `tests/test_seed_demo_course.py`'s original test uses `>= 5` and equality-on-rerun, both still hold; no exact-count assertion elsewhere references the demo seed (verify with `grep -rn "seed_demo_course" tests/` during execution and update any exact-count assertion found).
