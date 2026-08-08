# Unit publish state + one-click builder flag toggles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Course Admins a `published` flag on units so new content stays private until it is ready, plus one-click publish and obligatory toggles on every row of the builder tree.

**Architecture:** `ContentNode.published` is a second boolean independent of `obligatory`, meaningful only on units. Student visibility is filtered at one place per layer — `unit_is_visible` at outline dict-creation time, a `viewer=` guard in `access.get_node_or_404`, and explicit queryset filters on the tags/notes hubs, which never reach the traversal layer. One endpoint (`manage_node_flag`) writes both flags for a unit or a whole subtree, with confirmation enforced server-side.

**Tech Stack:** Django 5, PostgreSQL, pytest + pytest-django, Playwright (e2e), vanilla JS (`builder.js`), `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-08-08-unit-publish-state-design.md` — read it before starting. Test ids below (MIG1, ACC3, WR13…) refer to §9 of that spec.

## Global Constraints

- **Tooling is `uv`-only.** `pytest`, `ruff` and `python` are NOT on PATH. Every command is `uv run <tool>`.
- **Start the test-DB container before any pytest run.** Without it the suite looks hung for ~4m21s before failing.
- **Never run the whole suite mid-task.** Run only the files a task touches. A whole-repo sweep is a branch gate (Task 16), never a task step.
- **`uv run ruff format .` runs LAST**, after every other edit in a task. CI gates on `ruff format --check`.
- **e2e runs need `-m e2e`** or they silently deselect and exit 5.
- **New field name:** `published`. New CSS class: `tree__row--draft`. New context key: `flag_counts`. **New masked-icon classes** (not sprite ids — see Task 13 Step 2): `icm--live`, `icm--draft`, `icm--live-mixed`, `icm--req`, `icm--opt`, `icm--req-mixed`. Do not rename these — later tasks depend on them verbatim.
- **`drafts` modes are exactly** `"hide"`, `"keep"`, `"keep-with-data"`. `with_data` defaults to `None` (a sentinel), never `frozenset()`.
- **Every user-visible string is wrapped in `{% trans %}` / `gettext_lazy`.** Task 16 extracts them.
- **A test that cannot be made red by breaking what it covers does not count.** Each step below names its mutant; verify RED before implementing.

---

## Task 1: Model field, migration, and the test-fixture default

**Files:**
- Modify: `courses/models.py:201` (beside `obligatory`)
- Create: `courses/migrations/0057_contentnode_published.py`
- **Modify: `tests/factories.py`** — see Step 9, which is the reason this task is not just "add a field"
- Create: `courses/tests/test_publish_migration.py`, `courses/tests/test_publish_makemigrations.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ContentNode.published: BooleanField(default=False)`, and `ContentNodeFactory.published = True` so every existing fixture keeps representing **live** content.

> **Read Step 9 before starting.** `published=False` as the model default silently converts the whole existing test suite's content into drafts — 626 `ContentNodeFactory` uses and 134 raw `ContentNode.objects.create` calls. Without Step 9 this plan detonates at Task 3, not here.

- [ ] **Step 1: Confirm the migration leaf is still `0056`**

```bash
ls courses/migrations/ | tail -3
```

Expected: `0056_alter_calloutelement_kind.py` is the highest number. If a higher one exists, name your migration accordingly and update every reference to `0057` in this plan.

- [ ] **Step 2: Write the failing migration tests**

Create `courses/tests/test_publish_migration.py`:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from courses.models import ContentNode

BEFORE = ("courses", "0056_alter_calloutelement_kind")
AFTER = ("courses", "0057_contentnode_published")


@pytest.mark.django_db(transaction=True)
def test_existing_nodes_land_published():
    """MIG1. Rows that existed before 0057 must arrive published=True.

    Mutant: collapse the two operations into AddField(default=False) ->
    every pre-existing row is a draft -> this fails.

    transaction=True is MANDATORY: this test unapplies a migration and
    re-applies it, which cannot happen inside pytest-django's per-test
    atomic block. The `finally` restore is equally mandatory — under
    `-n auto` with a reused database (this repo's CI), a half-restored
    migration state poisons every subsequent test on that worker, and the
    failures land nowhere near this file.

    If you see unrelated tests failing with "no such column" or
    "relation does not exist" after running this, the restore did not run.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([BEFORE])
        executor.loader.build_graph()

        old_apps = executor.loader.project_state([BEFORE]).apps
        Course = old_apps.get_model("courses", "Course")
        Node = old_apps.get_model("courses", "ContentNode")
        course = Course.objects.create(title="Legacy", slug="legacy")
        Node.objects.create(course=course, kind="part", title="Part", order=0)

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])

        assert ContentNode.objects.filter(published=False).count() == 0
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db
def test_new_node_defaults_to_draft():
    """MIG3. models.py's declared default, not the AlterField."""
    node = ContentNode(kind="part", title="X")
    assert node.published is False
```

Add `courses/tests/test_publish_makemigrations.py`:

```python
import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_pending_migrations():
    """MIG2. A local, pre-push copy of the CI gate at ci.yml:53.

    Mutant: drop the AlterField from 0057 -> migration state says
    default=True while models.py says False -> --check detects a pending
    migration and raises SystemExit(1) -> this fails.

    Do NOT replace this with "a new node defaults to draft" (MIG3): that
    assertion is GREEN on the dropped-AlterField mutant, because the
    default comes from models.py either way.

    django_db is required, NOT optional: makemigrations --check calls
    MigrationLoader.check_consistent_history(connection), which queries
    django_migrations. Without the marker, pytest-django's blocker raises
    RuntimeError("Database access not allowed") — the test then fails on a
    CORRECT implementation as well as on the mutant, so it distinguishes
    nothing.
    """
    call_command("makemigrations", "courses", "--check", "--dry-run", verbosity=0)
```

Expected RED shape on the mutant: `SystemExit: 1`. Expected RED shape on a missing `django_db` marker: `RuntimeError: Database access not allowed`. They are different failures — do not accept the second as proof the test works.

- [ ] **Step 3: Run them to verify they fail**

```bash
uv run pytest courses/tests/test_publish_migration.py courses/tests/test_publish_makemigrations.py -v
```

Expected: FAIL — `ContentNode has no field named 'published'` / `NodeNotFoundError: 0057_contentnode_published`.

- [ ] **Step 4: Add the field**

In `courses/models.py`, directly below the `obligatory` line:

```python
    obligatory = models.BooleanField(default=True)  # meaningful only for units
    published = models.BooleanField(default=False)  # meaningful only for units
```

- [ ] **Step 5: Write the migration by hand**

Create `courses/migrations/0057_contentnode_published.py`:

```python
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    """Two operations, deliberately.

    AddField(default=True) BACKFILLS every existing row as published --
    that is the whole point of the pair. Django then DROPS the database
    default, so new rows take their value from models.py.

    AlterField(default=False) writes nothing to the database. It reconciles
    migration state with models.py so `makemigrations --check` (a CI gate
    since #204) stays clean.

    Collapsing these into one AddField(default=False) blacks out every
    course in every existing database. See the spec, section 1.
    """

    dependencies = [("courses", "0056_alter_calloutelement_kind")]

    operations = [
        migrations.AddField(
            model_name="contentnode",
            name="published",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="contentnode",
            name="published",
            field=models.BooleanField(default=False),
        ),
    ]
```

Note MIG2 duplicates CI's `makemigrations --check --dry-run` gate (`.github/workflows/ci.yml:53`) deliberately — it is the local, pre-push copy, so a dropped `AlterField` fails in seconds instead of on the PR.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest courses/tests/test_publish_migration.py courses/tests/test_publish_makemigrations.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Falsify MIG1** — temporarily replace the two operations with a single `AddField(default=False)`, re-run, confirm `test_existing_nodes_land_published` goes RED, then restore. A migration test that has never been seen red is worthless.

- [ ] **Step 8: Run the migration file in isolation, then confirm the suite still starts**

```bash
uv run pytest courses/tests/test_publish_migration.py -p no:randomly
uv run pytest tests/test_courses_views.py -q --verbosity=0
```

The second command is the canary for a botched `finally` restore. If it fails with schema errors, the restore did not run — fix that before continuing, or every later task's test run will lie to you.

**No serial-test mechanism is needed, and none exists to reach for.** `pyproject.toml`'s only pytest config is `addopts = "-q -m 'not e2e'"` — no serial marker, no `xdist_group` usage, no exclusion list. Do not go looking for one.

pytest-django gives **each xdist worker its own database**, so a migration unapplied on worker 3 cannot affect workers 1, 2 or 4. The `finally` restore is the whole protection, and it protects the only thing at risk: the *rest of this worker's* tests. Step 8's canary is what confirms it ran.

If a future change makes workers share a database, this file needs `@pytest.mark.xdist_group` plus `--dist loadgroup` in `addopts` — but that is not today's configuration and adding it now would be cargo cult.

- [ ] **Step 9: Republish the test fixtures — the step this whole task exists for**

`published=False` is the right default for *authoring* and the wrong default for *fixtures*. Without this step, every fixture-built unit is a draft, and the moment Task 3 adds `viewer=` or Task 5 makes `build_outline` hide drafts, hundreds of existing tests fail for a reason that has nothing to do with what they assert.

In `tests/factories.py`, add to `ContentNodeFactory`:

```python
class ContentNodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContentNode

    course = factory.SubFactory(CourseFactory)
    parent = None
    kind = "unit"
    title = factory.Sequence(lambda n: f"Node {n}")
    unit_type = "lesson"
    # Fixtures represent LIVE content. The model default is False (a new unit
    # is authored privately), but a test that has not opted into drafts is
    # asserting about content students can see. Pass published=False
    # explicitly to build a draft.
    published = True
```

Then audit the helpers built on it — `make_course_with_unit`, `make_quiz_unit`, `seed_slideshow_unit` all route through `ContentNodeFactory` and inherit the fix for free. Confirm that by reading them; do not assume.

- [ ] **Step 10: Sweep the raw `ContentNode.objects.create` sites**

134 call sites in `tests/` and `courses/tests/` bypass the factory entirely:

```bash
grep -rn "ContentNode.objects.create" tests/ courses/tests/ | wc -l
```

Most create containers (`kind="part"/"chapter"/"section"`), where `published` is never read and no change is needed. Only **unit** creations matter. Find them:

```bash
grep -rn -A3 "ContentNode.objects.create" tests/ courses/tests/ | grep -i "unit"
```

The `-A3` matters: `ruff format` wraps any call over 88 columns, so `ContentNode.objects.create(
    course=course, kind="unit", ...)` puts `kind="unit"` on a *different line* from the call and a same-line filter never sees it. Treat this as a first pass — Task 1 Step 11 and Task 3 Step 7 are what actually catch the misses.

Add `published=True` to each that creates a `kind="unit"` node **and** is later fetched through a student-facing surface. Where a test creates a unit and only ever inspects the row directly, leave it — an unnecessary edit is churn, and Task 3's and Task 5's suite runs will surface anything missed.

- [ ] **Step 11: Verify the fixtures are live**

```bash
uv run pytest tests/test_courses_rollups.py tests/test_courses_views.py -q --verbosity=0
```

Expected: green, and — critically — still green **after** Tasks 3 and 5. If a test here goes red at Task 3, the cause is almost always a missed raw `create` from Step 10, not the feature.

- [ ] **Step 12: Format and commit**

```bash
uv run ruff format .
git add courses/models.py courses/migrations/0057_contentnode_published.py tests/factories.py courses/tests/test_publish_migration.py courses/tests/test_publish_makemigrations.py
git commit -m "feat(courses): add ContentNode.published; fixtures build live content"
```

---

## Task 2: Access predicates and the chokepoint guard

**Files:**
- Modify: `courses/access.py`
- Modify: `courses/views.py:697-724` (`node_permalink`)
- Create: `tests/test_publish_access.py`

**Interfaces:**
- Consumes: `ContentNode.published` (Task 1).
- Produces:
  - `access.can_see_drafts(user, course) -> bool`
  - `access.manageable_courses(user) -> QuerySet[Course]`
  - `access.get_node_or_404(node_pk, slug, *, viewer=None, require_unit=False, require_lesson=False, require_quiz=False)` — `viewer` 404s a draft **unit** for a non-author.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_publish_access.py`:

These snippets use the **real** `tests/factories.py` API. There is no `make_user` and no `make_unit`; the exports are `UserFactory`, `CourseFactory`, `ContentNodeFactory`, `EnrollmentFactory`, `GroupFactory`, `GroupMembershipFactory`, plus the `make_course` / `make_course_with_unit` / `make_quiz_unit` convenience wrappers.

```python
import pytest
from django.contrib.auth.models import Permission
from django.http import Http404

from courses.access import can_see_drafts
from courses.access import get_node_or_404
from courses.access import manageable_courses
from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_draft_unit_404s_for_student_and_resolves_for_owner():
    """ACC1."""
    owner = UserFactory()
    student = UserFactory()
    course = CourseFactory(owner=owner)
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)

    with pytest.raises(Http404):
        get_node_or_404(unit.pk, course.slug, viewer=student, require_unit=True)
    assert get_node_or_404(unit.pk, course.slug, viewer=owner, require_unit=True) == unit


@pytest.mark.django_db
def test_is_staff_and_group_teacher_cannot_see_drafts():
    """ACC2. The gate is can_manage_course, NOT can_access_course.

    Mutant: implement can_see_drafts as can_access_course -> both resolve.
    """
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", published=False)
    staff = UserFactory(is_staff=True)
    teacher = UserFactory()
    GroupFactory(course=course).teachers.add(teacher)

    assert can_see_drafts(staff, course) is False
    assert can_see_drafts(teacher, course) is False
    for user in (staff, teacher):
        with pytest.raises(Http404):
            get_node_or_404(unit.pk, course.slug, viewer=user, require_unit=True)


@pytest.mark.django_db
def test_container_created_after_migration_stays_reachable():
    """ACC5 half A. A container carries published=False from the model
    default, and its own flag must NEVER decide visibility.

    Mutant: drop the `kind == UNIT` conjunct from the chokepoint -> a
    student 404s on every chapter created after the migration.

    Note this uses ContentNode.objects.create, NOT the factory: the factory
    sets published=True (Task 1 Step 9), which would mask the very default
    this test is about.
    """
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", title="Ch", parent=None
    )
    assert chapter.published is False  # the model default, as designed

    resolved = get_node_or_404(
        chapter.pk, course.slug, viewer=student, require_unit=False
    )
    assert resolved == chapter


@pytest.mark.django_db
def test_manageable_courses_has_two_branches():
    """WR15c. A courses.change_course holder gets EVERY course; an owner
    gets only theirs.

    Mutant: implement as filter(owner=user) alone -> the PA branch is
    missing and a Platform Admin loses drafts everywhere.
    """
    owner = UserFactory()
    mine = CourseFactory(owner=owner)
    theirs = CourseFactory()
    pa = UserFactory()
    pa.user_permissions.add(
        Permission.objects.get(
            codename="change_course", content_type__app_label="courses"
        )
    )
    pa = type(pa).objects.get(pk=pa.pk)  # drop the cached permission set

    assert set(manageable_courses(owner)) == {mine}
    assert set(manageable_courses(pa)) == {mine, theirs}
```

`GroupFactory(course=…).teachers.add(user)` is the shape the teacher fixture needs — `teachers` is an M2M with no factory post-generation hook. Re-fetching `pa` after granting the permission is not optional: `User.has_perm` caches, and without the re-fetch the PA branch reads as an owner.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_access.py -v
```

Expected: FAIL — `ImportError: cannot import name 'can_see_drafts'`.

- [ ] **Step 3: Add the predicates**

In `courses/access.py`, after `can_manage_course`:

```python
def manageable_courses(user):
    """Courses `user` may AUTHOR, as a queryset — the counterpart of
    can_manage_course, which exists only as a per-object predicate.

    NOT accessible_courses: that is the read gate, and using it here would
    show drafts to every enrolled student.

    Two branches, mirroring can_manage_course's two disjuncts. The first is
    easy to miss: courses.change_course is a MODEL-level permission with no
    per-course row to filter on, so a Platform Admin's result is unfiltered.
    """
    if not user.is_authenticated:
        return Course.objects.none()
    if user.has_perm("courses.change_course"):
        return Course.objects.all()
    return Course.objects.filter(owner=user)


def can_see_drafts(user, course):
    """Draft units are visible only to authors — the course owner or a
    holder of courses.change_course.

    Deliberately NOT is_staff (which grants read access to every course) and
    NOT an assigned group teacher (who cannot fix what they can see).

    A thin alias over can_manage_course rather than a direct call at each
    site: the two answers are the same today but the questions are not, and
    a future "teachers may preview drafts" setting must have one home.
    """
    return can_manage_course(user, course)
```

- [ ] **Step 4: Add the `viewer` guard to the chokepoint**

Replace `get_node_or_404`'s signature and add the check as the **last** step:

```python
def get_node_or_404(
    node_pk,
    slug,
    *,
    viewer=None,
    require_unit=False,
    require_lesson=False,
    require_quiz=False,
):
    """Resolve a node and enforce object scoping. 404 (never 403) on any mismatch.

    Order: exists -> slug match -> kind/unit_type -> published. Access (403)
    is checked by the caller AFTER this returns, so a foreign node always
    404s before any 403.

    `viewer=None` means "skip the publish check" — management views pass
    nothing. That makes the DEFAULT the insecure one, which is why
    tests/test_publish_viewer_scan.py exists.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if node.course.slug != slug:
        raise Http404("node does not belong to this course")
    if require_unit and node.kind != ContentNode.Kind.UNIT:
        raise Http404("not a unit")
    if require_lesson and node.unit_type != ContentNode.UnitType.LESSON:
        raise Http404("not a lesson unit")
    if require_quiz and node.unit_type != ContentNode.UnitType.QUIZ:
        raise Http404("not a quiz unit")
    # `kind == UNIT` is MANDATORY, not tidiness: every container row created
    # after migration 0057 carries published=False from the model default,
    # and a container's own flag must never decide visibility.
    if (
        viewer is not None
        and node.kind == ContentNode.Kind.UNIT
        and not node.published
        and not can_see_drafts(viewer, node.course)
    ):
        raise Http404("node is not published")
    return node
```

- [ ] **Step 5: Guard `node_permalink` inline**

`node_permalink` takes no slug and so never calls `get_node_or_404`. It needs its **own** copy of the guard — neither covers the other. In `courses/views.py`, after the existing `can_access_course` check:

```python
    if not can_access_course(request.user, node.course):
        raise Http404("node is not accessible")
    if (
        node.kind == ContentNode.Kind.UNIT
        and not node.published
        and not can_see_drafts(request.user, node.course)
    ):
        raise Http404("node is not published")
```

Import `can_see_drafts` at the top of `courses/views.py`.

- [ ] **Step 5b: Add ACC4 — a draft UNIT permalink 404s for a student**

Distinct from ACC5, which covers the *container* half of the same view. ACC4 pins that the inline guard fires when it should; ACC5 pins that it does not fire when it shouldn't. One without the other is half a guard.

```python
@pytest.mark.django_db
def test_permalink_to_draft_unit_404s_for_student(client):
    """ACC4. Mutant: omit the inline published check in node_permalink ->
    the student is redirected into a draft unit."""
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)
    client.force_login(student)

    url = reverse("courses:node_permalink", kwargs={"node_pk": unit.pk})
    assert client.get(url).status_code == 404
```

- [ ] **Step 6: Add the permalink half of ACC5** to `tests/test_publish_access.py`:

```python
@pytest.mark.django_db
def test_permalink_to_container_still_redirects(client):
    """ACC5 half B. A SEPARATE guard from the chokepoint's — node_permalink
    never calls get_node_or_404.

    Mutant: drop the kind == UNIT conjunct from the INLINE check -> a
    student 404s on every chapter permalink.
    """
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="Ch")
    client.force_login(student)

    url = reverse("courses:node_permalink", kwargs={"node_pk": chapter.pk})
    assert client.get(url).status_code == 302
```

Add `from django.urls import reverse` to the imports. Confirm the URL's kwarg name against `courses/urls.py` before writing it.

- [ ] **Step 7: Run and verify pass**

```bash
uv run pytest tests/test_publish_access.py -v
```

Expected: all pass.

- [ ] **Step 8: Falsify BOTH permalink guards, independently**

ACC4 and ACC5 test opposite directions of the same inline check, and both were authored after Step 5 landed it — so neither has been observed red on its own mutant yet. Run two falsifications:

1. Remove `node.kind == ContentNode.Kind.UNIT` from both checks → the two **ACC5** halves go RED (a container now 404s), ACC4 stays green.
2. Remove the whole inline `published` check from `node_permalink` → **ACC4** goes RED (a draft unit is redirected into), ACC5 stays green.

Restore after each. If either mutant reddens the wrong test, the two guards are entangled and one of them is not doing what its test claims.

- [ ] **Step 9: Format and commit**

```bash
uv run ruff format .
git add courses/access.py courses/views.py tests/test_publish_access.py
git commit -m "feat(access): can_see_drafts, manageable_courses, and the unit-only draft chokepoint"
```

---

## Task 3: Thread `viewer=` through every student-facing node view

**Files:**
- Modify: `courses/views.py` (10 sites), `notes/views.py:161`, `tags/views.py:38,75`
- Create: `tests/test_publish_viewer_sites.py`, `tests/test_publish_viewer_scan.py`

**Interfaces:**
- Consumes: `get_node_or_404(..., viewer=)` (Task 2).
- Produces: nothing new; closes the read/write surface.

- [ ] **Step 1: Write the parameterised endpoint test (ACC3)**

Create `tests/test_publish_viewer_sites.py`. Parameterise over every unit-addressed POST and assert 404 for an enrolled student on a draft unit, with **no** row written:

```python
import pytest
from django.urls import reverse

from courses.models import UnitProgress
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory

# (url name, payload, model the endpoint writes, lookup for that model)
# The model differs per endpoint, and that matters: a UnitProgress count is
# VACUOUSLY unchanged for note_add, tag_add, tag_remove and quiz_finish, which
# write Note / UnitTag / QuizSubmission. Those four are exactly the rows a
# courses/-scoped implementation misses, so a shared UnitProgress assertion
# would be green on every mutant for the endpoints the test exists to cover.
POST_ENDPOINTS = [
    ("courses:seen", {}, UnitProgress, lambda s, u: {"student": s, "unit": u}),
    ("courses:complete", {}, UnitProgress, lambda s, u: {"student": s, "unit": u}),
    (
        "courses:element_state_save",
        {"element": 0, "state": "{}"},
        UnitProgress,
        lambda s, u: {"student": s, "unit": u},
    ),
    ("notes:note_add", {"body": "x"}, Note, lambda s, u: {"author": s, "unit": u}),
    # tag_add reads request.POST.getlist("tag_pk") and .get("name") -- there is
    # NO "tag" parameter. Posting {"tag": "x"} falls through both branches and
    # writes nothing, so before == after == 0 and the write assertion is
    # vacuous on the mutant. Use "name".
    ("tags:tag_add", {"name": "x"}, UnitTag, lambda s, u: {"unit": u}),
    # tag_remove calls untag_unit(user, unit, request.POST.get("tag_pk")). With
    # no pre-seeded UnitTag its count is 0 == 0 either way -- so the fixture
    # MUST seed one on the draft unit and post its real pk, or a mutant
    # deletion is undetectable.
    ("tags:tag_remove", {"tag_pk": "<seeded>"}, UnitTag, lambda s, u: {"unit": u}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("name,payload,model,lookup", POST_ENDPOINTS)
def test_draft_unit_rejects_every_student_post(client, name, payload, model, lookup):
    """ACC3. The three cross-app endpoints (notes, tags) are the ones a
    courses/-scoped implementation misses.

    Mutant: gate only the GET views -> the POSTs still write.
    """
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)
    client.force_login(student)

    url = reverse(name, kwargs={"slug": course.slug, "node_pk": unit.pk})
    before = model.objects.filter(**lookup(student, unit)).count()

    assert client.post(url, payload).status_code == 404
    # 404 alone is not enough: assert the write did not land either.
    assert model.objects.filter(**lookup(student, unit)).count() == before
```

**Do not leave the body as `...`.** A body of `...` after a docstring is a *passing* test — the same trap Task 5 Step 1 names — and Step 3 would report 9 PASSED, leaving the most security-relevant test in the plan with no RED gate.

Import `Note` from `notes.models` and `UnitTag` from `tags.models` alongside the factories.

Three shapes the parameterisation above does not cover; give each its own test rather than bending the fixture:
- `check_answer` and `quiz_answer` take an extra `element_pk` kwarg.
- `quiz_finish` and `quiz_answer` need a quiz unit (`ContentNodeFactory(unit_type="quiz", published=False)`), not a lesson, and write `QuizSubmission`.
- `tag_remove`'s row needs the fixture to seed a `Tag` owned by the student **and** a `UnitTag` joining it to the draft unit, then post that tag's real pk — the `"<seeded>"` placeholder above is a reminder, not a literal. Without it `before` is 0 and the write assertion cannot fail.

Read each view's `urls.py` entry for the exact kwarg names before writing the `reverse()` calls; `node_pk` is the common one but not universal.

- [ ] **Step 2: Write the source-scan test (ACC6)**

Create `tests/test_publish_viewer_scan.py`:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Author-facing modules where `keep` is the correct rule (see spec section 2's
# export row, pinned by KEEP1). Excluding only views_manage.py would be green
# TODAY but would push the next implementer to pass viewer= in the exporter and
# silently drop drafts from archives.
AUTHOR_FACING = {
    "courses/views_manage.py",
    "courses/views_analytics.py",
    "courses/views_review.py",
    "courses/views_export.py",
    "courses/views_transfer.py",
    "courses/views_media.py",
}

CALL = re.compile(r"get_node_or_404\s*\(")


def test_every_student_facing_call_passes_viewer():
    """ACC6. viewer=None means "skip the check", so forgetting it fails
    SILENTLY. This is the only test covering call sites that do not exist
    yet, which is the entire point.
    """
    offenders = []
    for path in list(ROOT.glob("*/views.py")) + list(ROOT.glob("*/views_*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in AUTHOR_FACING:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not CALL.search(line):
                continue
            # Match the CALL, not the bare name: the `from courses.access
            # import get_node_or_404` line must not count as a violation.
            call_start = line.index("get_node_or_404")
            tail = line[call_start:]
            depth, chunk = 0, []
            for ch in tail:
                chunk.append(ch)
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0 and ch == ")":
                    break
            if "viewer=" not in "".join(chunk):
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, (
        "These get_node_or_404 calls must pass viewer=request.user. If the "
        "file is an AUTHOR-facing surface (builder, export, analytics, "
        "review, media), add it to AUTHOR_FACING above instead:\n  "
        + "\n  ".join(offenders)
    )
```

Two known limits of this scanner, both acceptable today and worth knowing when it next fires:

- **Single-line calls only.** If a real call spans lines, read the whole file text and scan with a multi-line regex instead — but keep the comment-exclusion.
- **The paren walk counts parens inside string literals and trailing comments**, so `get_node_or_404(pk, slug)  # (see note)` terminates the chunk early. All 13 current call sites are simple enough that it works, but the test exists to police *future* ones. If it ever produces a confusing result, drop the paren walk and just search the rest of the line for `viewer=` — the single-line assumption already makes the walk near-pointless.

- [ ] **Step 3: Run both to verify failure**

```bash
uv run pytest tests/test_publish_viewer_sites.py tests/test_publish_viewer_scan.py -v
```

Expected: FAIL — the POSTs return 200/302, and the scan lists ~13 offenders.

- [ ] **Step 4: Add `viewer=request.user` at all thirteen sites**

`courses/views.py`: `lesson_unit`, `quiz_unit`, `quiz_results`, `progress_reset` (node-scoped branch only), `seen`, `complete`, `element_state_save`, `check_answer`, `quiz_answer`, `quiz_finish`.
`notes/views.py:161`, `tags/views.py:38`, `tags/views.py:75`.

Each is a one-argument change, e.g.:

```python
    node = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=True)
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_publish_viewer_sites.py tests/test_publish_viewer_scan.py -v
```

- [ ] **Step 6: Falsify the scan** — remove `viewer=` from `notes/views.py:161`, confirm the scan names that exact file and line, restore.

- [ ] **Step 7: Run the neighbouring suites** (these views are heavily covered already):

```bash
uv run pytest tests/test_courses_views.py tests/test_notes_views.py tests/test_tags_views.py tests/test_tags_consumption.py tests/test_tags_outline.py -q --verbosity=0
```

Expected: green — **because Task 1 Step 9 set `ContentNodeFactory.published = True`**. This is the first task where that step pays off, and the first place its absence would show.

If tests here fail with 404s on `lesson_unit` / `quiz_unit`, the cause is a unit built by a raw `ContentNode.objects.create` that Task 1 Step 10 missed, not this task's change. Find it with the grep from that step and add `published=True`; do not weaken the gate.

`tests/test_tags_outline.py` and `tests/test_tags_consumption.py` are the two most likely to surface a missed fixture, since both drive student-facing surfaces over factory-built units.

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format .
git add courses/views.py notes/views.py tags/views.py tests/test_publish_viewer_sites.py tests/test_publish_viewer_scan.py
git commit -m "feat(access): gate every student-facing node view on publish state"
```

---

## Task 4: Parameterise the traversal helpers

**Files:**
- Modify: `courses/rollups.py`
- Create: `tests/test_publish_traversal.py`

**Interfaces:**
- Consumes: `ContentNode.published` (Task 1).
- Produces — every later task calls these:
  - `rollups.unit_is_visible(node, *, drafts, with_data) -> bool`
  - `rollups.units_in_order(course, *, drafts="keep", with_data=None)`
  - `rollups.units_under(node, *, drafts="keep", with_data=None)`
  - `rollups.quiz_units_in_order(course, *, drafts="keep", with_data=None)`
  - `rollups.build_outline(course, user, *, drafts="hide", with_data=None)` — **keywords and validation only in this task**; the filtering itself is Task 5
  - `rollups.build_unit_nav(course, user, current_node, *, drafts="hide", with_data=None)` — same, and it **forwards** both keywords into its internal `build_outline` call
  - `rollups.build_course_results(course, student, *, drafts="keep", with_data=None)`
  - `rollups.build_student_breakdown(course, student, *, drafts="keep", with_data=None)`

`frontier_columns` is **not** in this task — it is Task 8's deliverable.

**Both results helpers get a `"keep"` default here, deliberately.** They have 16 positional call sites (`rollups.py:378`, `views.py:596`, `views_analytics.py:193`, plus 13 assertions across `tests/test_courses_rollups.py` and `tests/test_analytics_rollups.py`), and this task's Files list does not touch any of them. A required keyword would end Task 4 with a `TypeError` in production code and in the two suites Step 7 tells you to run. Task 8 tightens them to required once Tasks 6 and 8 have threaded every caller.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_publish_traversal.py`:

Every test below asserts **validation or the predicate**, never `build_outline`'s filtering — that behaviour does not exist until Task 5, and asserting it here would leave Task 5's RED gate unsatisfiable.

```python
import pytest

from courses.rollups import build_outline
from courses.rollups import unit_is_visible
from courses.rollups import units_in_order
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_unknown_drafts_mode_raises():
    """A typo like "keep_with_data" falling through to "keep" is a LEAK that
    no behavioural test would catch.
    """
    course = CourseFactory()
    with pytest.raises(ValueError):
        units_in_order(course, drafts="keep_with_data")


@pytest.mark.django_db
def test_keep_with_data_requires_with_data_even_on_an_empty_course():
    """ANA7 half one. The fixture has ZERO units, deliberately.

    Mutant: put the guard inside unit_is_visible -> it runs per node, so a
    zero-unit course never reaches it and the check is absent exactly where a
    brand-new course is concerned. Only a zero-unit fixture proves the guard
    runs BEFORE any traversal.
    """
    course = CourseFactory()  # no units at all
    assert course.nodes.count() == 0
    with pytest.raises(ValueError):
        build_outline(course, UserFactory(), drafts="keep-with-data")


@pytest.mark.django_db
def test_empty_with_data_is_legitimate():
    """ANA7 half two. The fixture has >=1 unit, deliberately — on a zero-unit
    course "does not raise" is vacuously true of every implementation.

    An empty with_data is the ordinary state of a course no student has
    touched. It must NOT raise.
    """
    course = CourseFactory()
    ContentNodeFactory(course=course, kind="unit", published=True)
    build_outline(course, UserFactory(), drafts="keep-with-data", with_data=frozenset())


@pytest.mark.django_db
def test_low_level_helpers_default_to_keep():
    """The asymmetry IS the safety property: units_in_order's existing
    callers include the builder, the link picker and the exporter, where
    dropping drafts silently is DATA LOSS on transfer (KEEP1).
    """
    course = CourseFactory()
    draft = ContentNodeFactory(course=course, kind="unit", published=False)
    assert draft in units_in_order(course)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "drafts,published,in_data,expected",
    [
        ("hide", True, False, True),
        ("hide", False, False, False),
        ("keep", False, False, True),
        ("keep-with-data", False, False, False),
        ("keep-with-data", False, True, True),
        ("keep-with-data", True, False, True),
    ],
)
def test_unit_is_visible_truth_table(drafts, published, in_data, expected):
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", published=published)
    with_data = frozenset({unit.pk}) if in_data else frozenset()
    assert unit_is_visible(unit, drafts=drafts, with_data=with_data) is expected
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_traversal.py -v
```

Expected: FAIL — `cannot import name 'unit_is_visible'`.

- [ ] **Step 3: Add the mode constants, the validator, and the predicate**

Near the top of `courses/rollups.py`:

```python
# The three draft-filtering modes. `with_data` is the set of unit pks that hold
# data (>=1 QuizSubmission or >=1 UnitProgress); it is REQUIRED when
# drafts == "keep-with-data" and ignored otherwise.
DRAFTS_MODES = ("hide", "keep", "keep-with-data")


def _check_drafts(drafts, with_data):
    """Validate at the TOP of every public helper, before any traversal.

    NOT a bare `assert`: those are stripped under python -O and raise
    AssertionError, which no caller catches.

    NOT a check inside unit_is_visible: that runs per node, so a course with
    ZERO units would never reach it and the guard would be absent exactly
    where a brand-new course is concerned.

    None is the sentinel, NOT emptiness: an empty with_data is the ordinary
    state of a course no student has touched and must never raise.
    """
    if drafts not in DRAFTS_MODES:
        raise ValueError(f"unknown drafts mode {drafts!r}")
    if drafts == "keep-with-data" and with_data is None:
        raise ValueError("drafts='keep-with-data' requires with_data")


def unit_is_visible(node, *, drafts, with_data):
    """Whether this unit gets a dict in the outline tree at all. The ONE gate.

    In all three modes "appears in the tree" and "counts toward the totals"
    are the SAME condition, so there is no second, counter-level gate to
    write. Do not add a publish check to the rollup expressions: with the
    dict already gone those checks can never fire, and any test written
    against them passes vacuously on every mutant.
    """
    if drafts == "keep" or node.published:
        return True
    if drafts == "keep-with-data":
        return node.pk in (with_data or frozenset())
    return False
```

- [ ] **Step 4: Add the keyword to `units_in_order`, `units_under` and `quiz_units_in_order`**

Exactly these three. Each gains `*, drafts=<default>, with_data=None`, calls `_check_drafts(drafts, with_data)` first, and filters units through `unit_is_visible`. Containers are never filtered here — pruning is Task 5. Example:

```python
def units_in_order(course, *, drafts="keep", with_data=None):
    """Flat list of all leaf units (lessons AND quizzes) in outline pre-order.

    Defaults to "keep" — its existing callers include the builder, the link
    picker and the exporter, where dropping drafts is data loss on transfer.
    Student-facing callers must opt in to "hide" explicitly.
    """
    _check_drafts(drafts, with_data)
    return [
        n
        for n in _walk_preorder(course)
        if n.kind == ContentNode.Kind.UNIT
        and unit_is_visible(n, drafts=drafts, with_data=with_data)
    ]
```

`quiz_units_in_order` takes the same shape (default `"keep"`) and must **pass the keywords through** to `units_in_order` — it is the entry point the gradebook and review queue actually call.

**`units_under` does NOT take the same shape.** It returns a **set**, builds its own `parent_id` map and stack walk, and short-circuits before either:

```python
    if node.kind == ContentNode.Kind.UNIT:
        return {node} if unit_is_visible(node, drafts=drafts, with_data=with_data) else set()
```

Apply the predicate in **both** branches. A "same shape" reading patches the stack walk and skips the early return, leaving `units_under(draft_unit, drafts="hide")` returning the draft — which `progress_reset`'s node-scoped count then reports.

- [ ] **Step 4b: Give `build_outline` and `build_unit_nav` the keywords WITHOUT the filtering**

Both gain `*, drafts="hide", with_data=None` and call `_check_drafts` — and **nothing else changes in this task**. The dict-creation filter and the pruning passes are Task 5's deliverable; adding them here would make Task 5 Step 2's "run to verify failure" impossible to satisfy, because OUT1/OUT4/OUT5 would already be green before their implementation step.

They default to `"hide"` rather than `"keep"` — every one of their callers is student- or teacher-facing, so the restrictive default is the safe one there.

**`build_unit_nav` forwards both keywords into its internal `build_outline(course, user, …)` call and computes nothing itself.** It derives prev/next from `_flatten_unit_leaves(build_outline(...))`, so it has no unit list of its own to filter — and Task 5's OUT1 (prev/next skips a draft) depends entirely on this pass-through.

Write the forwarding now; the behaviour it enables arrives in Task 5.

- [ ] **Step 5: Thread the keyword into `build_course_results` and `build_student_breakdown`**

Both call the traversal **internally**, so a caller cannot filter their output after the fact: `build_course_results` computes `score_sum` / `max_sum` / `done_count` from its own `quiz_units_in_order` call, and post-filtering the returned rows would leave the headline totals still summing a drafted quiz.

Both take `*, drafts="keep", with_data=None` and pass them down. **A default, not a required keyword** — see this task's Interfaces block for why. Task 8 Step 6 removes the default once every caller is threaded, and that is where "every caller must decide" actually becomes true.

**`build_student_breakdown` forwards into BOTH of its internal calls, not one.** It composes two builders:

```python
    tree = build_outline(course, student, drafts=drafts, with_data=with_data)
    results = build_course_results(course, student, drafts=drafts, with_data=with_data)
```

Threading only `build_course_results` — the obvious reading, since that is the one this step is about — leaves `build_outline` on its `"hide"` default, so a teacher's breakdown renders a tree with every draft **removed** while `pill_by_unit` still carries their results. OUT7 then becomes unsatisfiable: it asserts the breakdown *keeps* a draft unit that holds data, and there is no dict in the tree to keep.

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_publish_traversal.py -v
```

- [ ] **Step 7: Run the existing rollup suites**

```bash
uv run pytest tests/test_courses_rollups.py tests/test_analytics_rollups.py courses/tests/test_rollups_units_under.py -q --verbosity=0
```

Expected: green — the `"keep"` defaults preserve every existing caller. Any failure here means a default is wrong; fix the default, not the test.

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format .
git add courses/rollups.py tests/test_publish_traversal.py
git commit -m "feat(rollups): drafts=/with_data= on the traversal helpers, validated at the top"
```

---

## Task 5: Outline filtering and the two pruning passes

**Files:**
- Modify: `courses/rollups.py` (`build_outline`)
- Create: `tests/test_publish_outline.py`

**Interfaces:**
- Consumes: `unit_is_visible` (Task 4).
- Produces: `build_outline` returns a tree with draft units absent and empty containers pruned per mode.

- [ ] **Step 1: Write the failing tests (OUT1, OUT2, OUT3, OUT4, OUT5, OUT5b)**

**OUT2 — `test_required_total_excludes_drafts`**
Fixture: 10 obligatory lesson units under one Part; draft 7 of them.
Assert: the student's root `required_total` is 3.
*Mutant:* filter drafts in the outline but not in the rollup → 10.

**OUT3 — `test_a_completed_unit_later_drafted_leaves_both_counters`**
Fixture: one obligatory lesson unit, published, with a `UnitProgressFactory(completed=True)` row.
Assert: `required_total == 1` and `required_done == 1`. Draft the unit, rebuild, assert **both** are 0 — and that the `UnitProgress` row is unchanged in the database.
*Mutant:* exclude from `required_total` only → `required_done` exceeds it, which is arithmetically impossible and is what the assertion catches.


Create `tests/test_publish_outline.py` with **six** tests — OUT1, OUT2, OUT3, OUT4, OUT5, OUT5b. **Do not write body-less functions with only a docstring** — those *parse and pass*, so Step 2's "run to verify failure" would report PASS and the RED gate would silently report the wrong colour. Write each body from the fixture spec below.

**OUT1 — `test_prev_next_skips_over_a_draft`**
Fixture: one Part; three lesson units in order A, B, C; draft B.
Assert: from A, `build_unit_nav(course, student, A, drafts="hide")`'s next is **C**, not B — it steps *over* the draft, not merely omits it from the outline.
*Mutant:* omit `build_unit_nav`'s forwarding of `drafts=` into `build_outline` (Task 4 Step 4b) → next is B.

**OUT4 — `test_additional_done_excludes_drafts_and_the_dict_is_gone`**
Fixture: one lesson unit with `obligatory=False, published=True`; a `UnitProgressFactory` row marking it complete for the student.
Assert: `additional_done` at the root is 1. Then set `published=False`, rebuild, and assert `additional_done` is 0 **and** that no dict anywhere in the tree has `d["node"].pk == unit.pk`.
Assert the dict's **absence** — not `completed is not True` on it. With the node filtered at dict creation there is no dict to read, so a `d.get("completed") is not True` sweep over the survivors passes vacuously on every mutant.
*Mutant:* gate `is_obligatory_lesson` instead of filtering at dict creation → `additional_done` still counts it, because that expression never calls the predicate.

**OUT5 — `test_a_root_level_part_with_only_drafts_is_pruned`**
Fixture: a **root-level Part** (`parent=None`) holding two draft lesson units, plus a second published Part alongside it so the tree is not empty.
Assert: `build_outline(course, student, drafts="hide")` returns one root, the published Part. Publish one unit in the first Part; assert both roots return.
*Mutant A:* filter at dict creation with no pruning pass → the empty Part still renders.
*Mutant B:* prune via the parent's `children` list only, without the `roots` filter → a nested-chapter fixture is **green** and only this root-level one goes red. Drafting a whole new Part is the headline use case, so Mutant B is the one that matters.

**OUT5b — `test_pruning_is_mode_dependent`**
Fixture: a root-level Part holding one draft lesson unit with **no** `UnitProgress` and **no** `QuizSubmission`.
Assert: `drafts="keep"` keeps the Part (the unit is retained, so the Part has children); `drafts="keep-with-data", with_data=frozenset()` **also keeps the Part**, even though the unit is filtered out — a teacher's breakdown preserves the course's shape.
*Mutant:* apply pruning uniformly across all three modes → the `keep-with-data` half loses the Part.

Import `CourseFactory`, `ContentNodeFactory`, `UserFactory`, `UnitProgressFactory` and `EnrollmentFactory` from `tests.factories`. Remember `ContentNodeFactory` now defaults `published=True` (Task 1 Step 9), so a draft must be requested explicitly.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_outline.py -v
```

Expected: **five assertion failures and one PASS.** OUT1, OUT2, OUT3, OUT4 and OUT5 go red (the draft is still present, `required_total` is 10, `additional_done` is still 1, the empty Part still renders). **OUT5b passes** — with no filtering and no pruning yet, both of its halves hold trivially.

That is not a missing body. OUT5b's RED gate is the Step 5 falsification (delete the `if prune:` guard around the `roots` filter), not this step. Only treat a PASS as a missing body for the other five — a `def` containing just a docstring is a green test, and that is the trap this step exists to catch.

- [ ] **Step 3: Filter at dict creation**

In `build_outline`, skip a unit that fails `unit_is_visible` before its dict is created:

```python
    for node in _walk_preorder(course):
        is_unit = node.kind == ContentNode.Kind.UNIT
        if is_unit and not unit_is_visible(node, drafts=drafts, with_data=with_data):
            continue
        ...
```

- [ ] **Step 4: Add the two pruning passes**

Container pruning **has** to be a second pass: `build_outline` walks pre-order and creates each container's dict *before* it reaches any child, so by the time a unit is filtered its chapter already exists. Fold it into the existing post-order `rollup`, and filter `roots` separately — a root container has no parent dict, so "removed from its parent's children" never reaches it:

```python
    prune = drafts != "keep-with-data"

    def rollup(d):
        node = d["node"]
        if d["is_unit"]:
            ...  # unchanged
        else:
            for k in d["children"]:
                rollup(k)
            if prune:
                d["children"] = [
                    k for k in d["children"] if k["is_unit"] or k["children"]
                ]
            d["required_total"] = sum(k["required_total"] for k in d["children"])
            ...

    for r in roots:
        rollup(r)
    if prune:
        roots = [r for r in roots if r["is_unit"] or r["children"]]
    return roots
```

The `prune` guard applies to **both** passes. Copying the `roots` line unconditionally prunes in all three modes including `keep-with-data`, where a root-level Part holding only never-published units would vanish from `build_student_breakdown`.

- [ ] **Step 5: Run to verify pass, then falsify**

```bash
uv run pytest tests/test_publish_outline.py -v
```

Then delete the `if prune:` guard around the `roots` filter and confirm `test_pruning_is_mode_dependent` goes RED — this is OUT5b's only RED gate, since it passes trivially at Step 2. Then delete the `roots` filter entirely and confirm `test_a_root_level_part_with_only_drafts_is_pruned` goes RED while a nested fixture would not. Restore.

- [ ] **Step 5b: Re-run the existing outline suites**

This task changes `build_outline` for **every** caller — draft filtering, plus pruning of *genuinely empty* containers under both `hide` and `keep`, a behaviour change the spec adopts knowingly. Task 4 Step 7 ran these before the filtering existed, so this is the first honest check:

```bash
uv run pytest tests/test_courses_rollups.py tests/test_analytics_rollups.py courses/tests/test_rollups_units_under.py tests/test_unit_nav_render.py -q --verbosity=0
```

A failure here is one of two things, and neither is a defect in this task's logic: an existing assertion about an empty chapter that pruning now removes, or a unit built by one of the raw `create` calls Task 1 Step 10 deliberately left alone. Diagnose before "fixing" — running this only at Task 6 or Task 8 gets the cause misattributed to whatever changed there.

- [ ] **Step 6: Format and commit**

```bash
uv run ruff format .
git add courses/rollups.py tests/test_publish_outline.py
git commit -m "feat(rollups): filter drafts at dict creation, prune empty containers per mode"
```

---

## Task 6: Student-facing call sites

**Files:**
- Modify: `courses/views.py` (`course_outline`, `course_results`, `progress_reset`, `full_lesson_render_context`, `quiz_unit`, `_quiz_render_feedback`), `notes/services.py`, **`notes/views.py`**, `grouping/services.py`
- Create: `tests/test_publish_call_sites.py`

**Interfaces:**
- Consumes: Task 4's keywords, Task 2's `can_see_drafts`.
- Produces: `notes.services.course_notes(author, course, *, drafts, with_data=None)`.

- [ ] **Step 1: Write the failing tests (OUT6, OUT6b, OUT8, OUT9, OUT10)**

Create `tests/test_publish_call_sites.py`. Fixture specs, in the Task 5 style:

**OUT10 — `test_author_keeps_drafts_on_student_surfaces`**
Fixture: one course, one Part, three lesson units A, B, C with B drafted. An owner and an enrolled student.
Assert, for the **author**: `GET course_outline` renders B, and `build_unit_nav`'s next from A is B. For the **student**: B absent from the outline, and next from A is C.
*Mutant:* hard-code `drafts="hide"` at the call sites instead of evaluating the viewer-conditional expression → the author loses B on both surfaces.
**This is the mutant the rest of the roster cannot catch** — OUT1–OUT4 assert the student side, ACC1 asserts only direct-URL access (which still works on the mutant), OUT5b calls `build_outline` directly rather than through a view.

**OUT6 — `test_reset_count_excludes_drafts_on_both_branches`**
Fixture: two lesson units, both with `UnitProgressFactory(element_state={"1": {"x": 1}})`; draft one.
Assert: the **course-wide** reset confirmation page reports 1, and the **node-scoped** one for the parent Part also reports 1.

`progress_reset` is registered under **two** URL names for the same view — reverse `courses:progress_reset_course` (`courses/<slug>/reset/`) for the course-wide branch and `courses:progress_reset` (`courses/<slug>/reset/<node_pk>/`) for the subtree one. Reversing `courses:progress_reset` without `node_pk` raises `NoReverseMatch`.
*Mutant:* filter `units_under` but leave `units_in_order` unfiltered → the course-wide branch, the commonly used one, still reports 2.

**OUT6b — `test_reset_post_still_clears_a_drafted_units_state`**
Same fixture; POST the course-wide reset. Assert the **drafted** unit's `element_state == {}`.
*Mutant:* filter `targets` rather than only the count → the drafted unit keeps its state, which resurfaces on republish. **Without this assertion the safe and unsafe implementations are indistinguishable**, since OUT6 alone is green on both.

**OUT8 — `test_student_results_drops_a_drafted_quiz_they_submitted_to`**
Fixture: one quiz unit, published; a `QuizSubmissionFactory(status=SUBMITTED)` for the student. Then draft the quiz.
Assert: the student's `course_results` page has no row for it.
*Mutant:* put the `keep-with-data` filter inside `build_course_results` instead of in each caller → the student's own submission keeps the row alive for them. This is the one call site where "holds data" and "the viewer is a student" are true at once.

**OUT9 — `test_all_draft_course_is_absent_from_the_catalogue`**
Fixture: a course with `visibility="open"` whose only unit is drafted, and a student not enrolled.
Assert: it does not appear in `catalog`. Publish the unit; assert it does.
*Mutant:* leave the `Exists(... kind="unit")` subquery without `published=True`.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_call_sites.py -v
```

Expected: five assertion failures. A PASS here means a missing body, not a passing implementation.

- [ ] **Step 3: Add the viewer-conditional expression at each site**

One expression, written once and reused:

```python
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
```

Apply at `course_outline`, `course_results`, `progress_reset`, and the notes hub view.

- [ ] **Step 4: Thread it into `build_unit_nav`'s THREE call sites**

`full_lesson_render_context` (serves the lesson GET, the `check_answer` re-render **and** the notes no-JS re-render), `quiz_unit`, and `_quiz_render_feedback` (the no-JS quiz-answer re-render) — all three in `courses/views.py`; find them by name, the line numbers drift. Patching only the two named views leaves two re-render paths shipping an unfiltered nav.

The three sites do **not** share a shape — read each signature rather than assuming:

| Site | Signature | Viewer comes from |
|---|---|---|
| `full_lesson_render_context(node, user, …)` | takes `user`, no `request` | the `user` argument |
| `quiz_unit(request, slug, node_pk)` | a view | `request.user` |
| `_quiz_render_feedback(request, node, element, question, response, …)` | takes `request`, **no `user` at all** | `request.user` — its body already does this |

Only the first reads the viewer off a `user` parameter, and there it is correct — for the opposite reason to `build_student_breakdown`, where `user` is the student being *read about*. That distinction is the whole reason the filter is a parameter; do not generalise from either case to the other.

- [ ] **Step 5: Split `progress_reset`'s count from its write**

`targets` is not display-only — the same list drives `rows.update(element_state={})`. Filtering it would silently narrow the **reset itself**, leaving stale state on drafted units to resurface on republish:

The view currently assigns `course` **inside** each branch (`get_object_or_404(Course, slug=slug)` in one, `node.course` in the other), so `drafts` cannot be computed before the `if`. Restructure it: resolve `course`/`node` first, then compute `drafts`, then build both lists.

```python
    # 1. Resolve course/node FIRST — drafts needs `course`.
    node = None
    if node_pk is None:
        course = get_object_or_404(Course, slug=slug)
    else:
        node = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=False)
        course = node.course

    if not can_access_course(request.user, course):
        raise PermissionDenied

    # 2. Now `course` exists.
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"

    # 3. targets is UNFILTERED — it drives the WRITE. Reset is the student's
    #    protection against automatic persistence; leaving hidden state behind
    #    is precisely the failure it exists to prevent. visible_targets is a
    #    SECOND call, and drives only the count.
    if node is None:
        targets = units_in_order(course)
        visible_targets = units_in_order(course, drafts=drafts)
    else:
        targets = units_under(node)
        visible_targets = units_under(node, drafts=drafts)

    rows = UnitProgress.objects.filter(student=request.user, unit__in=targets)
    ...
    # Filter the COUNT, never the WRITE.
    affected_count = (
        rows.exclude(element_state={}).filter(unit__in=visible_targets).count()
    )
```

Preserve the existing `can_access_course` check and the `raise PermissionDenied` — the reordering must not drop them. Read the current view body before editing; the snippet above shows the shape, not every line.

Two calls to the same helper, deliberately. `units_in_order`/`units_under` default to `"keep"`, so `targets` gets the unfiltered set for free.

- [ ] **Step 6: Parameterise `notes.services.course_notes` AND its one caller**

Add `*, drafts, with_data=None` to the service and pass them to its internal `units_in_order` call.

**Then edit `notes/views.py` — the sole caller, and easy to miss because it lives in another app.** `notes/views.py:60` calls `services.course_notes(request.user, course)` positionally; a required keyword breaks the notes hub with `TypeError` on every request, and WR15d (Task 7) asserts that hub filters for a student and keeps drafts for the author, which only that view can decide:

```python
def course_notes(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
    return render(
        request,
        "notes/course_notes.html",
        {
            "course": course,
            "units": services.course_notes(request.user, course, drafts=drafts),
        },
    )
```

- [ ] **Step 7: Gate the catalogue**

In `grouping/services.py`, the subquery is assigned first and applied a few lines later:

```python
has_unit = ContentNode.objects.filter(
    course=OuterRef("pk"), kind="unit", published=True   # <-- add published
)
...
.filter(Exists(has_unit))
```

Edit the `has_unit` assignment, not the `Exists(...)` call. Without it, a CA building a new course privately publishes a course listing for content that does not exist yet.

- [ ] **Step 8: Run, falsify OUT10, run the neighbouring suites**

```bash
uv run pytest tests/test_publish_call_sites.py courses/tests/test_progress_reset.py tests/test_courses_progress.py -q --verbosity=0
```

Falsify by hard-coding `drafts="hide"` at all **seven** sites — six in `courses/views.py`, one in `notes/views.py` — and confirming **only** OUT10 goes red.

- [ ] **Step 9: Format and commit**

```bash
uv run ruff format .
git add courses/views.py notes/services.py notes/views.py grouping/services.py tests/test_publish_call_sites.py
git commit -m "feat(courses): viewer-conditional draft filtering on every student-facing surface"
```

---

## Task 7: Tags and notes hub queryset filters

**Files:**
- Modify: `courses/access.py` (the new `exclude_foreign_drafts`), `tags/services.py` (`units_by_tag`, `list_tags`, `tags_by_course`), `notes/services.py` (`note_counts_by_course`)
- Create: `tests/test_publish_hubs.py`

**Interfaces:**
- Consumes: `manageable_courses` (Task 2).
- Produces: `access.exclude_foreign_drafts(qs, author, *, unit_field="unit")` — shared by both apps.

- [ ] **Step 1: Write the failing tests (WR15, WR15b, WR15d)**

- **WR15** — a student's tags hub drops a drafted unit; an author's keeps it. *Mutant: rely on the traversal keyword — `units_by_tag` builds from `UnitTag` rows and filters nothing, so a student keeps seeing a live link to a drafted unit.*
- **WR15b** — a user who manages course A but not course B sees A's drafts and not B's **in one result set**. *Mutant: a single `can_see_drafts` boolean — it cannot even be evaluated, since these queries take only `author`.*
- **WR15d** — the **per-course notes hub** (`course_notes`) drops a note on a drafted lesson for a student, keeps it for the author. *Mutant: leave its `units_in_order` call unparameterised → it inherits the `"keep"` default and leaks the drafted unit's title and live link.* This is the one surface in the table that filters through the **traversal keyword**, so WR15's mutant is the opposite direction and green here.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_hubs.py -v
```

Expected: FAIL — `ImportError: cannot import name 'exclude_foreign_drafts'`, i.e. a **collection error**, not per-test assertions.

That import error masks **WR15d**, whose implementation already landed in Task 6 Step 6 (`course_notes(*, drafts…)` plus the `notes/views.py` caller). Once the import resolves it passes without a single change in this task, so its stated mutant is never observed red. Give it one in Step 5: revert Task 6 Step 6's `drafts=` argument and confirm WR15d — and only WR15d — goes red.

- [ ] **Step 3: Apply the per-course Q filter**

These queries take only `author` and select over `accessible_courses(author)` — there is no single `course` to hand to `can_see_drafts`, and a boolean could not express the right answer anyway, since a user who manages A but not B must keep A's drafts and lose B's in the same result set:

Three of the four consumers live in `tags/services.py` and the fourth in `notes/services.py`, so the helper cannot be a private name in either. **Define it in `courses/access.py` as a public function** and import it from both — `notes` reaching into `tags` for a `_`-prefixed name would be a new cross-app coupling for no reason:

```python
# courses/access.py -- `Q` is already imported at module top; do not add it again
def exclude_foreign_drafts(qs, author, *, unit_field="unit"):
    """Drop drafted units the viewer may not author.

    A per-course condition inside the query, NOT a boolean: these hubs are
    cross-course (they take only `author` and select over accessible_courses),
    so there is no single course to hand to can_see_drafts — and a boolean
    could not express the answer anyway, since a user who manages course A
    but not B must keep A's drafts and lose B's in the SAME result set.

    The kind conjunct matters: excluding published=False alone would also drop
    rows attached to containers, whose published column is meaningless.
    """
    return qs.exclude(
        Q(**{f"{unit_field}__kind": "unit", f"{unit_field}__published": False})
        & ~Q(**{f"{unit_field}__course__in": manageable_courses(author)})
    )
```

**Three of the four take the helper; `list_tags` cannot.** It returns a **`Tag`** queryset whose per-tag number is an annotation:

```python
Tag.objects.filter(author=author).annotate(
    unit_count=Count("unit_tags", filter=Q(unit_tags__unit__course__in=accessible))
)
```

`Tag` has no `unit` path, so `exclude_foreign_drafts(qs, author)` raises `FieldError` — and even with `unit_field="unit_tags__unit"`, an `.exclude()` on a `Tag` queryset drops the **whole tag** as soon as one of its units is a foreign draft, instead of adjusting its count. The correction has to go **inside the `Count` filter**, which the helper's shape cannot express.

So export a bare-`Q` companion alongside it:

```python
def foreign_draft_q(author, unit_field="unit"):
    """The condition exclude_foreign_drafts negates, as a bare Q, for callers
    that must fold it into an annotation rather than an .exclude()."""
    return Q(**{f"{unit_field}__kind": "unit", f"{unit_field}__published": False}) & ~Q(
        **{f"{unit_field}__course__in": manageable_courses(author)}
    )
```

and in `list_tags`:

```python
    unit_count=Count(
        "unit_tags",
        filter=Q(unit_tags__unit__course__in=accessible)
        & ~foreign_draft_q(author, "unit_tags__unit"),
    )
```

| Consumer | Mechanism | `unit_field` |
|---|---|---|
| `tags.services.units_by_tag` | `exclude_foreign_drafts` | `"unit"` (default) |
| `tags.services.tags_by_course` | `exclude_foreign_drafts` | `"unit"` |
| `notes.services.note_counts_by_course` | `exclude_foreign_drafts` | `"unit"` |
| `tags.services.list_tags` | **`foreign_draft_q` inside `Count(filter=…)`** | `"unit_tags__unit"` |

Add `courses/access.py` to this task's Files and `git add`.

- [ ] **Step 4: Leave `_accessible_unit_count` alone**

Tag deletion deliberately counts drafts: it backs the "this will remove the tag from N units" confirmation, and the author deleting the tag owns it. Telling them N-minus-drafts and then removing more is the dishonesty `progress_reset` is careful to avoid. Add a comment saying so, so a later reader does not "fix" it.

- [ ] **Step 5: Run, falsify, commit**

```bash
uv run pytest tests/test_publish_hubs.py tests/test_tags_services.py tests/test_tags_notes_hub.py tests/test_notes_services.py -q --verbosity=0
uv run ruff format .
git add courses/access.py tags/services.py notes/services.py tests/test_publish_hubs.py
git commit -m "feat(tags,notes): exclude foreign drafts from the queryset-driven hubs"
```

---

## Task 8: Analytics

**Files:**
- Modify: `courses/rollups.py` (`frontier_columns`), `courses/views_analytics.py`, `courses/gradebook.py`, `courses/review.py`, **`courses/views_export.py`**, **`courses/views_review.py`**
- Modify (caller fixes): `tests/test_courses_rollups.py`, `tests/test_analytics_rollups.py`
- Create: `tests/test_publish_analytics.py`

**Interfaces:**
- Consumes: Task 4's keywords.
- Produces:
  - `rollups.frontier_columns(course, expanded_pks, *, drafts="keep", with_data=None)` — the analytics filter point. **`"keep"`, not `"keep-with-data"`**: `build_matrix_columns` and seven bare calls in `tests/test_analytics_rollups.py` pass no keywords, and a restrictive default makes `_check_drafts` raise on every one. The strictness lives on the callers below instead.
  - `rollups.build_results_matrix(course, students, expanded=frozenset(), values="percent", *, drafts, with_data=None)` — `drafts` **required**
  - `rollups.build_progress_matrix(course, students, expanded=frozenset(), *, drafts, with_data=None)` — `drafts` **required**
  - `gradebook.build_matrix_table(course, students, mode, expanded, *, drafts, with_data=None)`
  - `gradebook.build_quiz_gradebook(course, students, numbers_only, *, drafts, with_data=None)`
  - `review.pending_reviews_for(user, course, *, drafts, with_data=None)`
  - `build_course_results` / `build_student_breakdown` with `drafts` tightened to a **required** keyword
  - a `with_data` frozenset built once per request by each analytics view

- [ ] **Step 1: Write the failing tests (ANA1–ANA6, OUT7)**

- **ANA1** — a draft quiz **with** submissions keeps its gradebook column; one with **none** has no column. Its "with none" fixture must have **no submission row at all**, not merely no submitted one.
- **ANA2** — a draft **lesson** with `UnitProgress` keeps its column. *Mutant: implement "holds data" as the `QuizSubmission` check alone.*
- **ANA3** — drive `build_results_matrix` / `build_progress_matrix` through `views_analytics`, **including one drill-down expansion**. *Mutant: filter `build_matrix_columns` (a three-line alias with zero production callers) → both real matrices and every expansion stay unfiltered, and the test looks green.*
- **ANA4** — `lesson_pks` denominators match the columns.
- **ANA5** — the gradebook and review queue drop never-published quizzes, proving `quiz_units_in_order` carries the keyword.
- **ANA6** — **four containers plus an alignment assertion.** (a) an all-draft chapter has no column; (b) a chapter of only **non-obligatory published lessons** still **has** one; (c) an **expanded** all-draft chapter is dropped and absent from `expanded_nodes`; (d) a chapter with **no units at all** keeps its column, in **all three modes**. Then `len(header_rows[-1]) == len(columns)`, and (a)'s title absent from `header_rows`.

  *Mutant A:* key the drop on `lesson_pks`/`quiz_pks` emptiness → red on (b). *Mutant B:* post-filter `result["columns"]` instead of guarding inside `walk` → red on the alignment assertion only, green on (a)–(d). *Mutant C:* guard only the leaf arm → red on (c). *Mutant D:* drop the `total and` conjunct from Step 4's rule → red on (d), **and three existing `frontier_columns` tests go red too** (see Step 4).
- **OUT7** — `build_student_breakdown` keeps a draft unit that holds data even though its `user` argument is the *student*, and the test asserts **both** denominators (teacher's and student's) so the deliberate divergence is a pinned fixture.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_analytics.py -v
```

Expected: FAIL — `frontier_columns() got an unexpected keyword argument 'drafts'`.

- [ ] **Step 3: Build `with_data` once per request, in the view**

```python
    has_submissions = set(
        QuizSubmission.objects.filter(unit__course=course).values_list(
            "unit_id", flat=True
        )
    )
    has_progress = set(
        UnitProgress.objects.filter(unit__course=course).values_list(
            "unit_id", flat=True
        )
    )
    with_data = frozenset(has_submissions | has_progress)
```

Two batched lookups over two models — never one query per unit. Do **not** fold this into `_quiz_review_maps`: that helper is fed `quiz_units_in_order(course)` and knows nothing about lesson units or `UnitProgress`, so extending it would batch the quiz half and leave the lesson half issuing a query per unit.

`has_submissions` deliberately takes **any** status: a student who opened a quiz and stopped has left an interrupted attempt, which is data a teacher may need to see — especially on a quiz since pulled back, whose attempt is stranded until republication.

- [ ] **Step 4: Drop columns INSIDE `walk`, moving three outputs together**

`frontier_columns` emits **three coupled outputs from one traversal**: `columns` (aligned **positionally** with body cells), `cells_by_depth` → `header_rows` (the `<thead>`), and the `leaves` counter → an expanded ancestor's `colspan`.

Post-filtering `result["columns"]` is therefore wrong, and it is the reading a "drop the column" rule invites: it leaves a stale `<th>` and an over-counted `colspan`, shifting every column header off its data by one for the rest of the row — a silently misread matrix, not a visibly broken one.

Guard **both arms** of `walk`. The `if node.pk in expanded_pks and kids` arm keys on the unfiltered children map, so a drilled-into all-draft chapter is still recursed through, `walk` returns `0`, and the header emits `<th colspan="0">` — invalid HTML5 that browsers clamp to 1, producing a phantom spanning cell:

```python
    def unit_counts(root):
        """(total_units, visible_units) over root's subtree."""
        stack, total, visible = [root], 0, 0
        while stack:
            n = stack.pop()
            if n.kind == ContentNode.Kind.UNIT:
                total += 1
                visible += unit_is_visible(n, drafts=drafts, with_data=with_data)
            stack.extend(children.get(n.pk, []))
        return total, visible

    def walk(parent_id, depth):
        leaves = 0
        for node in children.get(parent_id, []):
            total, visible = unit_counts(node)
            # Drop ONLY when the subtree HAS units and none is visible.
            if total and not visible:
                continue  # suppresses columns.append, cells_by_depth AND leaves
            ...
```

**The `total and` conjunct is load-bearing — do not simplify it to "has a visible unit".** A container with **zero units** would then be dropped in every mode, including the `"keep"` default, and today `frontier_columns` emits a leaf column for any frontier node regardless of contents. Three existing tests pin that:

| Test | Fixture it asserts |
|---|---|
| `test_frontier_empty_matches_build_matrix_columns` | `_ch2` is a childless chapter; asserts it is column 1 with `expandable is False` |
| `test_frontier_expand_chapter_replaces_with_children` | expects `["Sec", "Loose"]`, where `Sec` is a childless section |
| `test_frontier_header_rows_colspan_rowspan_nesting` | expects `["P1","S1","S2","C2","C3"]`, where `P1`, `C2` and `C3` hold no units |

All three would go red on the simplified rule — and Step 6's diagnostic ("those tests assert about live content, so `drafts="keep"` is the correct value to add") would send the implementer chasing keyword threading for what is actually a container-pruning regression. With the conjunct, the rule is a **no-op under `keep`** and today's columns are preserved exactly.

Key the drop on **visible units**, never on `lesson_pks`/`quiz_pks` being empty: `subtree_pks` adds to `lesson_pks` only for `is_obligatory_lesson(n)` and to `quiz_pks` only for `is_quiz_unit(n)`, so a **non-obligatory lesson contributes to neither**. A chapter of only optional lessons has two empty pk sets *today*, with everything published — an emptiness rule would delete that column as an unrelated regression.

Filter `lesson_pks` / `quiz_pks` by the same rule, or the matrix divides by units it does not display.

- [ ] **Step 5: Leave `build_matrix_columns` alone**

It has **zero production callers** — it is test-only. Adding the keyword defensively invites a test written against the alias, which is exactly the green-but-uncovered outcome ANA3 exists to prevent. Add a comment saying so.

- [ ] **Step 6: Pass `drafts="keep-with-data", with_data=...` from every teacher-facing caller, then REMOVE the defaults**

**Five call chains, not two.** `views_analytics` is only one of three entry points, and the other two reach the traversal through helpers this plan has not named until now:

| Chain | Sites to thread |
|---|---|
| Analytics matrices | `views_analytics.py:67`, `:69` → `build_results_matrix` / `build_progress_matrix` → `frontier_columns` |
| Student breakdown | `views_analytics.py:193` → `build_student_breakdown` → **both** `build_outline` and `build_course_results` (`rollups.py:377-378`) |
| Student's own results | `views.py:596` — already threaded by Task 6 |
| **Gradebook export** | `views_export.py:56` → `gradebook.build_quiz_gradebook` → `quiz_units_in_order`; and `views_export.py:59` → `gradebook.build_matrix_table` (`gradebook.py:30`) → the two matrix builders |
| **Review queue** | `views_review.py:113` → `review.pending_reviews_for` (`review.py:238`) → `quiz_units_in_order` |

The last two are the ones a `views_analytics`-only reading misses entirely:

- **`gradebook.build_matrix_table` is a third caller of the matrix builders.** It does `builder = build_results_matrix if mode == "results" else build_progress_matrix; matrix = builder(course, students, expanded)`. Making `drafts` required (Step 6b) raises `TypeError` on **every matrix export** until this is threaded, and `tests/test_gradebook.py` is in Step 7's run list — so it surfaces as a failure with no diagnosis unless you read this table.
- **`build_quiz_gradebook` and `pending_reviews_for` both call `quiz_units_in_order(course)` bare**, so after Task 4 they inherit the `"keep"` default and filter nothing. **ANA5 asserts exactly these two surfaces**, and cannot go green until both — and their two view callers, which must build the `with_data` frozenset — are threaded.

Both view modules build `with_data` the same way Step 3 shows; Step 3 forbids building it inside the rollup helpers, so the view is the only place it can come from.

Then tighten both results helpers from `drafts="keep"` to a **required** keyword:

```python
def build_course_results(course, student, *, drafts, with_data=None): ...
def build_student_breakdown(course, student, *, drafts, with_data=None): ...
```

This is where "every caller must decide" becomes true — it could not be done in Task 4, whose Files list touched none of these call sites. Removing the default now converts any site still calling positionally into a loud `TypeError` at import/call time rather than a silent `"keep"`.

Run the two rollup suites and fix **every positional call they report as a `TypeError`** — there are 14 today (10 in `tests/test_courses_rollups.py`, 4 in `tests/test_analytics_rollups.py`), but treat the failure list as the checklist rather than the number, which drifts:

```bash
uv run pytest tests/test_courses_rollups.py tests/test_analytics_rollups.py -q --verbosity=0
```

Those tests are asserting about *live* content, so `drafts="keep"` is the correct value to add to each.

- [ ] **Step 6b: Give `frontier_columns` AND both matrix builders their keywords**

```python
def frontier_columns(course, expanded_pks, *, drafts="keep", with_data=None): ...
def build_results_matrix(course, students, expanded=frozenset(), values="percent",
                         *, drafts, with_data=None): ...
def build_progress_matrix(course, students, expanded=frozenset(),
                          *, drafts, with_data=None): ...
```

**All three, not just `frontier_columns`.** `views_analytics.py` calls the two **matrix builders**, never `frontier_columns` directly — the real chain is `views_analytics` → `build_results_matrix` / `build_progress_matrix` (`rollups.py:540`, `:591`) → `frontier_columns`. Without the middle link parameterised, the `with_data` frozenset built in Step 3 has **no route** to the filter, and ANA3 (which must be driven through `views_analytics`) has no implementation at all.

Each matrix builder calls `_check_drafts` and forwards both keywords into its `frontier_columns(course, expanded, …)` call.

**`frontier_columns` defaults to `"keep"`, not `"keep-with-data"`.** The restrictive default would be right if every caller were viewer-facing, but two are not: `build_matrix_columns` calls it bare (Step 5 says to leave that alone), and `tests/test_analytics_rollups.py` calls it bare at lines 304, 327, 346, 368, 395, 407 and 684. A `"keep-with-data"` default makes `_check_drafts` raise `ValueError` on every one of them — nine call sites broken by a default chosen for tidiness. The matrix builders take `drafts` as a **required** keyword instead, which puts the strictness exactly where the viewer-facing callers are.

- [ ] **Step 7: Run, falsify ANA6's Mutant B, commit**

```bash
uv run pytest tests/test_publish_analytics.py tests/test_analytics_views.py tests/test_gradebook.py -q --verbosity=0
```

Falsify by moving the drop to a post-filter on `result["columns"]` and confirming **only** the alignment assertion goes red — (a), (b) and (c) all stay green, which is the whole point of adding it.

```bash
uv run ruff format .
git add courses/rollups.py courses/views_analytics.py courses/gradebook.py courses/review.py courses/views_export.py courses/views_review.py tests/test_publish_analytics.py tests/test_courses_rollups.py tests/test_analytics_rollups.py tests/test_gradebook.py
git commit -m "feat(analytics): keep draft units that hold data, drop empty containers inside walk"
```

---

## Task 9: Transfer and duplication

**Files:**
- Modify: `courses/transfer/schema.py`, `courses/transfer/export.py`, `courses/transfer/importer.py`
- Modify: 7 test files pinning `FORMAT_VERSION`
- Create: `tests/test_publish_transfer.py`

**Interfaces:**
- Consumes: `ContentNode.published`.
- Produces: `FORMAT_VERSION == 10`; node payloads carry `"published"`.

- [ ] **Step 1: Re-verify `FORMAT_VERSION` against `origin/master`**

```bash
git fetch origin && git show origin/master:courses/transfer/schema.py | grep FORMAT_VERSION
```

Two branches bumping this to the *same* number produce **no git conflict** — the change is line-identical, so it merges silently and green while the union of assertion sites is larger than either branch saw. Confirm it is still `9` before proceeding.

- [ ] **Step 2: Write the failing tests (TR1–TR4, KEEP1)**

- **TR1** — `published` round-trips through export → import, both values.
- **TR2** — a **v9** archive imports with every unit published. *Mutant: `setdefault("published", False)` → everything imports hidden.*
- **TR3** — imported containers land `published=False`, matching natively-created ones.
- **TR4** — **duplicating a PUBLISHED unit yields a DRAFT copy.** *Mutant: let `materialize_duplicate` honour the payload like archive import does → the duplicate is live to students the instant it is created.* **Highest-value test outside the migration**: duplicate-and-edit is the most common way a CA adds content to a running course, and the defect is invisible in review because §8 reads as a data-fidelity change.
- **KEEP1** — a course containing draft units exports **all** of them, and the link picker lists them. *Mutant: push the draft filter into `units_in_order`/`_walk_preorder` → drafts vanish from the builder and are silently dropped from the export — data loss on transfer.*

- [ ] **Step 2b: Run to verify failure**

```bash
uv run pytest tests/test_publish_transfer.py -v
```

Expected: FAIL — `published` is absent from the exported node payload, and the duplicate is live.

- [ ] **Step 3: Add `published` to the four transfer sites**

Mirroring `obligatory` exactly — the fourth is the one a three-item list drops:

| File | What |
|---|---|
| `courses/transfer/export.py` | `"published": node.published` beside `"obligatory"` |
| `courses/transfer/schema.py` | `"published"` in the node `_exact_keys` list |
| `courses/transfer/schema.py` | **`check_bool(nd["published"], "published")`** — the type check |
| `courses/transfer/importer.py` | `published=nd["published"]` in the node construction |

- [ ] **Step 4: Add the optional-key setdefault**

Per node, **immediately before** the `_exact_keys(nd, [...])` call — the same position `doc.setdefault("link_nodes", {})` occupies relative to its own. After that call is too late: a v9 node would already have been rejected as missing the key.

```python
        # Optional-key pattern (see the FORMAT_VERSION-2 width/height note).
        # Default True, NOT False: a v9 archive came from an install with no
        # concept of drafts, so every unit in it was live.
        nd.setdefault("published", True)
```

Then normalise containers so the two creation paths agree. **Position matters twice:**

```python
        # AFTER the `nd["kind"] not in ContentNode.RANK` validity check —
        # otherwise this reads an unvalidated kind.
        # AFTER check_bool(nd["published"], "published") — otherwise a v10
        # archive carrying "published": "yes" on a container is silently
        # accepted, because the normalisation overwrites the bad value before
        # anything type-checks it.
        if nd["kind"] != "unit":
            nd["published"] = False
```

`check_bool(nd["obligatory"], …)` sits ~25 lines after `_exact_keys` in `courses/transfer/schema.py`; put the `published` check beside it and the normalisation immediately after. TR3 passes under either ordering, so **no test distinguishes them** — this is a case where the comment is the guard. Add a validation test if you want it pinned: a container payload with `"published": "yes"` must be rejected, not normalised.

- [ ] **Step 5: Bump `FORMAT_VERSION` to 10** and update the seven pinned assertions:

`tests/test_link_transfer.py:54`, `tests/test_table_transfer.py:296`, `tests/test_tabs_transfer.py:62`, `tests/test_transfer_schema.py:57`, `tests/test_transfer_export.py:220`, `courses/tests/test_beforeafter_transfer.py:165`, `courses/tests/test_image_size_transfer.py:41`.

Also update `tests/test_table_transfer.py:560`, which names the value in a **comment** — comments in this repo are matched by source-scanning tests, so a stale one is not merely untidy.

**`courses/tests/test_beforeafter_transfer.py` needs more than a number edit.** The assertion at :165 lives in a function named `test_format_version_is_unchanged` (:158), named that because the before/after element deliberately did *not* bump the format. Editing its body to `== 10` leaves a test whose name asserts the opposite of what it checks. Rename it (e.g. `test_format_version_is_pinned`) or add a comment recording why the number moved; do not leave the contradiction.

- [ ] **Step 6: Force `published=False` in `materialize_duplicate`**

`duplicate_unit` runs `export.build_export(...)` → `materialize_duplicate(...)`, reusing the transfer path wholesale — so once `published` joins the payload, duplicating a live unit produces a **live** duplicate.

`materialize_duplicate` has no field-setting site of its own; it delegates to `_create_nodes`, the shared node builder. So the override is an explicit post-pass inside `work()`:

```python
    def work():
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        # Duplication is authoring NEW content, not restoring an archive.
        # Chosen over a force_draft= keyword on _create_nodes because the
        # archive-import path must keep honouring the payload (TR1), and a
        # shared builder growing a flag for one of its two callers is how
        # that path acquires a bug later.
        ContentNode.objects.filter(pk__in=node_map.values()).update(published=False)
        created = _create_elements(document, node_map, media_map)
```

- [ ] **Step 7: Run, falsify TR4, commit**

```bash
uv run pytest tests/test_publish_transfer.py tests/test_transfer_import.py tests/test_transfer_export.py tests/test_transfer_schema.py tests/test_builder_duplicate_unit.py -q --verbosity=0
```

Falsify by removing the post-pass `update()` and confirming TR4 goes red while TR1 stays green.

```bash
uv run ruff format .
git add courses/transfer/schema.py courses/transfer/export.py courses/transfer/importer.py courses/builder.py tests/test_publish_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py courses/tests/test_beforeafter_transfer.py courses/tests/test_image_size_transfer.py
git commit -m "feat(transfer): FORMAT_VERSION 10 carries published; duplicates land as drafts"
```

---

## Task 10: Quiz submission predicates

**Files:**
- Create: `courses/quiz_warnings.py`
- Create: `tests/test_publish_quiz_warnings.py`

**Interfaces:**
- Consumes: `QuizSubmission`, `grouping.GroupMembership`.
- Produces:
  - `quiz_warnings.submission_counts(unit_or_pks) -> (submitted: int, in_progress: int)`
  - `quiz_warnings.is_quiet(unit_or_pks, course) -> bool` — True only when every submitting student is *provably* in a finished class.

**Both take a unit OR an iterable of pks**, the same contract, so the subtree strip (Task 12) can aggregate over a chapter. `is_quiet` with a single unit and `is_quiet` with one-element iterable must agree.

**Who consumes `is_quiet`** — it selects copy in exactly two places, and if neither is wired the whole quiet-note feature ships dead:
- Task 12's confirm strip (unit-scope quiz hide, and the aggregated subtree hide)
- Task 15's editor-page submission banner

- [ ] **Step 1: Write the failing tests (QZ1–QZ4)**

- **QZ1** — a submission from a student in a **non-archived** group → loud.
- **QZ2** — all submissions from archived groups only → quiet.
- **QZ3** — a submitting student with **NO** group membership → **loud**. *Mutant: implement the predicate as the single `exists()` on non-archived groups → the self-enrolled student's submissions read as "all archived" and the note goes quiet.* **This is the inversion the spec exists to prevent, and it is invisible without this specific fixture.**
- **QZ4** — a quiz with zero submissions shows neither banner.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_publish_quiz_warnings.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'courses.quiz_warnings'`.

- [ ] **Step 3: Implement the quiet predicate as the NEGATION**

The obvious implementation — one `exists()` joining `QuizSubmission → student → GroupMembership → Group(archived=False)`, quiet when `False` — **inverts the no-group rule**. A self-enrolled student has no `GroupMembership` at all (`Cohort`/`CohortMembership` are separate models from `Group`/`GroupMembership`), so that `exists()` returns `False` for them and routes exactly the population the rule protects into the quiet branch.

```python
def _unit_pks(unit_or_pks):
    """Accept a single ContentNode or an iterable of pks. Both public helpers
    take this contract so the subtree strip can aggregate over a chapter.
    """
    if hasattr(unit_or_pks, "pk"):
        return [unit_or_pks.pk]
    return list(unit_or_pks)


def is_quiet(unit_or_pks, course):
    """The quiet note fires only when EVERY submitting student is provably in
    a finished class. Two lookups, not one.

    Cohort.archived does NOT participate: a cohort gates self-enrolment
    eligibility, not class membership, and says nothing about whether a given
    student's work is historical. Only Group.archived means "this class is
    finished".
    """
    submitters = set(
        QuizSubmission.objects.filter(
            unit_id__in=_unit_pks(unit_or_pks),
            status=QuizSubmission.Status.SUBMITTED,
        ).values_list("student_id", flat=True)
    )
    if not submitters:
        return False  # no submissions -> neither banner shows at all
    in_any_group = set(
        GroupMembership.objects.filter(
            group__course=course, student_id__in=submitters
        ).values_list("student_id", flat=True)
    )
    in_active_group = GroupMembership.objects.filter(
        group__course=course, group__archived=False, student_id__in=submitters
    ).exists()
    ungrouped = submitters - in_any_group  # self-enrolled -> treated as ACTIVE
    return not in_active_group and not ungrouped
```

- [ ] **Step 4: Implement `submission_counts`**

The **"have submitted" count** filters `status=SUBMITTED`; the in-progress line counts the rest. A row exists as soon as a student *opens* the quiz, so counting every row would report "12 submissions" for a quiz twelve students merely glanced at — which trains the CA to ignore the banner, the failure mode a warning cannot recover from.

Accept either a single unit or an iterable of pks, so the subtree strip (Task 12) can aggregate.

- [ ] **Step 5: Run, falsify QZ3, commit**

Falsify by replacing `is_quiet` with the single-`exists()` form and confirming QZ3 goes red while QZ1 and QZ2 stay green.

```bash
uv run ruff format .
git add courses/quiz_warnings.py tests/test_publish_quiz_warnings.py
git commit -m "feat(courses): quiz submission counts and the archived-group quiet predicate"
```

---

## Task 11: The write endpoint

**Files:**
- Modify: `courses/builder.py`, `courses/views_manage.py`, `courses/urls.py`
- Create: `templates/courses/manage/_flag_strip.html`, `templates/courses/manage/node_confirm_flag.html` (minimal — Task 12 fills them out)
- Create: `tests/test_publish_flag_endpoint.py`

**Interfaces:**
- Consumes: Task 10's predicates.
- Produces:
  - `builder.set_node_flag(course, node_pk, *, flag, value, scope, token) -> ContentNode`
  - `views_manage._flag_error(request, course, node, msg, *, ctx)` — the three-arm 422/409 renderer
  - `views_manage._flag_strip(request, course, node, *, flag, scope, ctx=None)` — **a minimal version lands here**, because Step 4 calls it; Task 12 replaces its body with the full copy and counts. `ctx` is in the signature from the start and **must be passed at both call sites**: defaulted-and-never-supplied, the strip's `{% if ctx %}` hidden input never fires and a confirmation from `ctx=editor` returns on the builder arm.
  - URL name `courses:manage_node_flag`, path `manage/courses/<slug:slug>/build/node/flag/`

> **`_flag_strip` is a forward dependency, and this task must not defer it.** Step 4 returns it on the unconfirmed path, and WR13 and WR18 both drive that path. Write a minimal version here — the strip's `<form>` with its hidden fields, `data-flag-strip="<pk>"` on the root, and a bare count — and leave the four copy variants, the quiet/loud split and the quiz aggregation to Task 12.
>
> **It needs BOTH templates, and this task creates them**, so add them to the Files list and the `git add`:
> - `templates/courses/manage/_flag_strip.html` — the fragment
> - `templates/courses/manage/node_confirm_flag.html` — the full-page interstitial
>
> The interstitial is not optional here: **WR13 drives a hand-rolled POST with no `X-Requested-With` header**, so `_wants_fragment` is false and the *interstitial* is what renders. A minimal `_flag_strip` that only ever returns the fragment would leave WR13 asserting against a template that does not exist. Task 12 then *modifies* both files rather than creating them.

- [ ] **Step 1: Write the failing tests (WR1–WR5, WR7–WR9, WR11–WR14, WR16, WR18)**

The high-value ones, each with its mutant:

- **WR2** — bulk publish writes every descendant **and bumps `updated` on each**. Assert the `updated` values actually **changed**. *Mutant: drop `updated=timezone.now()` from the `.update()`.* **Highest-value test in the file**: the bug is invisible until the *next* edit to an affected row conflicts.
- **WR13** — a POST that needs confirmation and lacks `confirmed=1` **does not write**, and returns the strip rather than a 4xx. Drive it with a **hand-rolled POST**, not through the UI. *Mutant: let the template's element choice be the only guard → a direct POST unpublishes a quiz with no confirmation, and every UI-driven test stays green.*
- **WR9** — the **no-JS POST shape** works (parameters as hidden inputs in `request.POST`, not a `formaction` query string). *Mutant: read from `request.GET` only → the interstitial silently 422s.* Every other write-path test drives the JS path and stays green.
- **WR11** — `value` and `scope` are allow-listed like `flag`: 422 for `value="true"`, `value=""`, missing `scope`, `scope="everything"`, with **no write**.
- **WR14** — `flag=obligatory scope=subtree` writes **lesson units only** and bumps `updated`. *Mutant A: restrict to `kind="unit"` alone → the quiz's inert flag is stamped. Mutant B: fork on `flag` and omit `updated` from the obligatory arm.*
- **WR5** — a container toggle **does not touch nodes outside its subtree**. Seed two sibling chapters, each with units; toggle one; assert the other's units are byte-identical, `updated` included. *Mutant:* build `unit_pks` from `course.nodes.filter(kind="unit")` instead of from `_subtree_node_ids()` → the whole course flips on one click.
- **WR7** — every successful fragment response has **`data-scope="top"` on its root**, for a unit toggle **and** for a **collapsed** container's subtree toggle. Assert the *attribute*, not just a 200. *Mutant:* return the acted node's `<li>`, or the container's own `_scope.html` → the root carries no matching `data-scope`, `applyFragment` no-ops, and the UI shows nothing while the status code stays 200. **A status-code assertion is green on this**, which is the entire reason WR7 asserts markup.
- **WR8** — the returned fragment carries the **post-write `data-updated`** for every affected open row. Read `data-updated` out of the returned fragment and re-post it as `token` on a second edit to a descendant; assert it succeeds rather than 409ing. *Mutant:* omit `updated=now` from the bulk `.update()` → the fragment carries stale tokens and the follow-up 409s.
- **WR16** — `scope=node` on a container and `scope=subtree` on a unit both **422**, no write.
- **WR1b** — an anonymous request gets a **login redirect, not a 403**. *Mutant: omit `@login_required` → `_require_manage` raises `PermissionDenied` and the endpoint 403s where every neighbouring view redirects.* WR1 alone is green on that mutant.
- **WR18** — a confirmed write under an active filter comes back **still filtered**. **Fixture: the confirming QUIZ anchor**, not a container strip — container anchors are inert under a filter (TREE5), so "set `q`, open a container strip" is unreachable through the UI.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Add the service function**

In `courses/builder.py`, beside `rename_node`, reusing its `_locked_node` + `_check_token` preamble verbatim:

```python
FLAG_COLUMNS = ("published", "obligatory")


@transaction.atomic
def set_node_flag(course, node_pk, *, flag, value, scope, token):
    """Write `flag` on one unit or on every unit in a subtree.

    `flag` has already passed the view's allow-list, which is what makes
    **{flag: value} safe — it selects a COLUMN NAME, so the allow-list is a
    security boundary, not input hygiene.
    """
    node = _locked_node(course, node_pk)
    _check_token(node.updated, token)

    # Unit-scope only by construction: for scope="subtree" the node is a
    # container, whose unit_type is None. Placed BEFORE the branch so the
    # invariant reads as a precondition rather than as a late guard on
    # work already done.
    if flag == "obligatory" and node.unit_type == ContentNode.UnitType.QUIZ:
        raise ValidationError("obligatory does not apply to quiz units.")

    if scope == "node":
        if node.kind != ContentNode.Kind.UNIT:
            raise ValidationError("scope=node requires a unit.")
        unit_pks = [node.pk]
    else:
        if node.kind == ContentNode.Kind.UNIT:
            raise ValidationError("scope=subtree requires a container.")
        # TWO steps: _subtree_node_ids returns bare pks with no kind
        # information, and INCLUDES the container's own pk.
        ids = node._subtree_node_ids()
        qs = ContentNode.objects.filter(pk__in=ids, kind=ContentNode.Kind.UNIT)
        if flag == "obligatory":
            # obligatory is read only for lessons; stamping it on a quiz
            # writes a value no progress path consults.
            qs = qs.filter(unit_type=ContentNode.UnitType.LESSON)
        unit_pks = list(qs.values_list("pk", flat=True))

    # QuerySet.update() does NOT fire auto_now, so updating the flag alone
    # would leave every touched row's `updated` — and therefore its
    # concurrency token and the builder's data-updated attribute — pointing
    # at a state that no longer exists.
    now = timezone.now()
    ContentNode.objects.filter(pk__in=unit_pks).update(**{flag: value}, updated=now)
    # The container's own updated is bumped too, even though its flag column
    # is untouched: its data-updated and _scope.html's scope_updated would
    # otherwise describe a subtree that has changed underneath them.
    if scope == "subtree":
        ContentNode.objects.filter(pk=node.pk).update(updated=now)
    node.refresh_from_db()
    return node
```

- [ ] **Step 4: Add the view with server-side confirmation**

In `courses/views_manage.py`:

```python
@login_required  # _require_manage does NOT check authentication: for an
def node_flag(request, slug):  # anonymous request it raises PermissionDenied
    course = _require_manage(request, slug)  # -> 403 where every neighbour redirects

    # Three request shapes, one rule. A `formaction` query string is part of
    # the URL and lands in request.GET even on a POST; the no-JS interstitial
    # sends hidden inputs in request.POST; the strip GET uses request.GET.
    def param(name):
        return request.POST.get(name) or request.GET.get(name)

    # ctx is read HERE, before any error path can reference it. An
    # unrecognised value is a 422 -- but ctx is also what SELECTS the error
    # arm, so when ctx is itself the bad parameter it is treated as absent
    # and the 422 renders through the builder arm.
    ctx = param("ctx")
    bad_ctx = ctx is not None and ctx not in ("editor", "unit")
    if bad_ctx:
        ctx = None
    if bad_ctx:
        return _flag_error(request, course, None, _("Bad ctx."), ctx=None)

    # `node` is validated BEFORE resolution: param("node") returns None when
    # absent, and get_object_or_404(qs, pk=None) raises inside the ORM -- a
    # 500 on a trivially malformed request, at the one endpoint that can
    # unpublish a whole course.
    raw_node = param("node")
    if raw_node is None or not str(raw_node).isdigit():
        # This ONE 422 bypasses _flag_error: that helper dereferences `node`
        # on two of its three arms, and `node` is what failed.
        return _builder_with_notice(request, course, _("Bad node."), status=422)

    # NO viewer= -- this is an authoring surface and an author must be able to
    # reach a draft; the Task 3 source scan excludes views_manage.py for
    # exactly this reason.
    node = get_node_or_404(raw_node, slug)

    # `mode` and `title` also arrive, because the toggles live inside the
    # rowhead form. Both are IGNORED here — same precedent as the Duplicate
    # button, whose formaction posts the identical payload to node_duplicate.
    # A flag toggle must never be mistaken for a rename.
```

Validate `flag` ∈ `FLAG_COLUMNS`, `value` ∈ `{"0","1"}` (required on POST, optional on GET), `scope` ∈ `{"node","subtree"}`, `ctx` ∈ `{"editor","unit"}` or absent, all 422 otherwise. Nothing defaults — a missing `scope` is an error, not an implicit `"node"`, because the two differ in blast radius by orders of magnitude.

**`node` is validated too** — it is not in the allow-list table because it is not an enum, but `param("node")` returns `None` when absent, and `get_object_or_404(qs, pk=None)` raises inside the ORM. A 500 on a trivially malformed request, at the one endpoint that can unpublish a whole course:

| Parameter | Missing / non-integer | Resolves but foreign |
|---|---|---|
| `node` | **422** via `_builder_with_notice`, before any resolution — see the snippet above | 404 via `get_node_or_404`'s slug check |

Add `confirmed` to the allow-list too: accepted `"1"`, **missing allowed** (it means "not yet confirmed"), anything else 422. The plan's `param("confirmed") != "1"` test alone would turn `confirmed=true` or `confirmed=yes` into a silent re-prompt rather than an error. Extend WR11's cases to cover it alongside `value` and `scope`.

**Convert `value` to a bool once, immediately after the allow-list**, and pass the bool onward:

```python
    raw_value = param("value")
    # TWO conditions, not one. `value` may be ABSENT on a GET (a container
    # strip derives its direction from counts), but an out-of-domain value is
    # a 422 on EITHER method -- gating the whole check on POST silently
    # accepts ?value=true on the strip GET, and WR11 drives POSTs only.
    if raw_value is not None and raw_value not in ("0", "1"):
        return _flag_error(request, course, node, _("Bad value."), ctx=ctx)
    if request.method == "POST" and raw_value is None:
        return _flag_error(request, course, node, _("Missing value."), ctx=ctx)
    value = raw_value == "1"        # a real bool from here on
```

It happens to work if the string reaches `.update(**{flag: value})` — `BooleanField.to_python` coerces `"0"` and `"1"` — but leaving it a string invites a later "cleanup" to `bool(raw_value)`, under which `"0"` is **truthy** and every hide action becomes a publish. No listed test covers that: WR11 asserts rejection, not coercion. Convert once, here, and let `needs_confirmation` compare `value is False` rather than `== "0"`.

`node` is resolved twice by design: unlocked here to answer `needs_confirmation`, then re-resolved under `select_for_update` inside `set_node_flag`. The second is the one the write depends on.

`value` is **optional on GET** and required on POST: a mixed container's strip offers both directions and derives the single action from counts, so the container anchor sends no `value`. Requiring it on GET would 422 every container anchor.

Then compute `needs_confirmation` **server-side** — the template's choice of element is an optimisation, never the guard:

```python
    needs_confirmation = scope == "subtree" or (
        flag == "published"
        and value is False  # the bool from the conversion above, not "0"
        and node.published  # nothing to confirm about hiding what is hidden
        and node.unit_type == ContentNode.UnitType.QUIZ
        and QuizSubmission.objects.filter(unit=node).exists()  # ANY status
    )
    # A GET NEVER writes. The spec's contract is "GET -> the confirm strip",
    # full stop — without this branch a GET where needs_confirmation is false
    # (?node=<lesson>&flag=published&value=1&scope=node) falls straight
    # through to set_node_flag, i.e. a GET that mutates. "The UI never emits
    # that GET" is not an answer in a view whose whole premise is that the
    # server, not the markup, is the guard.
    if request.method == "GET":
        return _flag_strip(request, course, node, flag=flag, scope=scope, ctx=ctx)

    if needs_confirmation and param("confirmed") != "1":
        return _flag_strip(request, course, node, flag=flag, scope=scope, ctx=ctx)

    try:
        node = builder_svc.set_node_flag(
            course, node.pk, flag=flag, value=value, scope=scope, token=param("token")
        )
    except builder_svc.ConflictError:
        return _flag_conflict(request, course, node, ctx=ctx)      # 409 arm
    except ValidationError as e:
        return _flag_error(request, course, node, "; ".join(e.messages), ctx=ctx)
```

**The two exception arms are not optional.** `builder._check_token` raises `ConflictError` and `set_node_flag` raises `ValidationError` for the scope/kind and quiz/obligatory rejections — WR3 (stale token → 409), WR16 (scope/kind → 422) and TREE9's server half (quiz + obligatory → 422) all depend on this wrapping. Mirror `node_rename` (`views_manage.py:799`) and `node_duplicate` (`:973`); import `ConflictError` alongside `set_node_flag`.

- [ ] **Step 4b: Write the two error renderers**

Both dispatch on `ctx`, which neither existing helper does — `_op_error(request, message)` and `_builder_with_notice(request, course, message, status)` each know only the builder arm:

```python
def _flag_error(request, course, node, msg, *, ctx):
    """422. Three arms, per Step 5's response table. An unrecognised ctx has
    already been normalised to None (the builder arm) by validation."""
    if ctx == "editor":
        return _editor_page(request, node, error=msg, status=422)
    if ctx == "unit":
        return redirect(_unit_url(node))
    if _wants_fragment(request):
        return render(request, "courses/manage/_op_error.html",
                      {"message": msg}, status=422)
    return _builder_with_notice(request, course, msg, status=422)


def _flag_conflict(request, course, node, *, ctx):
    """409. Same three arms; the builder arm re-renders the scope so the tree
    picks up whatever changed elsewhere."""
    if ctx == "editor":
        url = reverse("courses:manage_editor",
                      kwargs={"slug": course.slug, "pk": node.pk})
        return redirect(f"{url}?changed=1")
    if ctx == "unit":
        return redirect(_unit_url(node))
    if _wants_fragment(request):
        return _conflict_scope(request, course, node.pk)
    return _builder_with_notice(
        request, course, _("This changed elsewhere — reloaded to the latest."),
        status=409,
    )
```

**`_unit_url` does not exist yet — this task creates it in `views_manage.py`.** The only one in the repo is `tags/views._unit_url`, a module-private helper in another app; importing a `_`-prefixed name across apps is not the answer. Add it beside `_flag_error`, making the same branch `node_permalink` already makes:

```python
def _unit_url(node):
    name = (
        "courses:quiz_unit"
        if node.unit_type == ContentNode.UnitType.QUIZ
        else "courses:lesson_unit"
    )
    return reverse(name, kwargs={"slug": node.course.slug, "node_pk": node.pk})
```

**Both error renderers fall back to the builder arm for a non-unit `node`, whatever `ctx` says.** `_editor_page(request, unit, …)` calls `_editor_rows(unit)` and `_unit_ancestors(unit)` — it is a unit-only surface — and `_unit_url` has no meaning for a container. But `node_flag` accepts any node, and two of its own 422 paths fire on containers (`scope=node` on a container, and a bad `value` posted with `ctx=editor&node=<container>`). So each `ctx` test carries a conjunct:

```python
    is_unit = node is not None and node.kind == ContentNode.Kind.UNIT
    if ctx == "editor" and is_unit: ...
    if ctx == "unit" and is_unit: ...
    # otherwise fall through to the builder arm
```

This is the same "never trust the caller" rule the endpoint validates `node` for; WR16 exercises the builder arm only, so extend it with a `ctx=editor` container case.

A single-node `.exists()` here, **not** the course-wide set Task 13 builds for the tree render. And **any status**, not `SUBMITTED`-only: an in-progress attempt is interrupted by unpublishing, which is worth confirming even though it damages no data.

- [ ] **Step 5: Wire the response contract**

`ctx` **wins over `_wants_fragment` on every arm** — the banner forms (Task 15) are ordinary no-JS-shaped posts, so without this rule `_wants_fragment` is false for them and an editor-page author is bounced to the builder:

| Case | `ctx` absent | `ctx=editor` | `ctx=unit` |
|---|---|---|---|
| Success, fragment | `top` scope via `applyFragment` | — | — |
| Success, non-fragment | `_redirect_to_builder(course, _raw_q(request))` | redirect to `manage_editor` | redirect to the unit URL |
| 409 | `_conflict_scope` / `_builder_with_notice` | editor `?changed=1` | unit URL |
| 422 | `_op_error.html` / `_builder_with_notice` | `_editor_page(..., status=422)` | unit URL |
| Needs confirmation, unconfirmed | strip (fragment) / interstitial | interstitial | interstitial |
| GET (always) | strip (fragment) / interstitial | interstitial | interstitial |

**The strip re-emits `ctx` as a hidden input**, so the confirmed round trip lands on the same arm it started from. Without that, a confirmation reached from `ctx=editor` comes back with `ctx` absent and redirects the author to the builder — WR10's mutant, reached from the other side.

An unrecognised `ctx` is a 422 rendered through the **builder** arm — `ctx` selects the arm, so when it is itself invalid there is no column to use.

Every successful fragment response re-renders the **`top` scope**. A bare `<li>` has no `data-scope` so `applyFragment` **silently no-ops**; the container's own `_scope.html` misses the row that was clicked; and a collapsed container has no `<ol data-scope>` in the DOM at all.

- [ ] **Step 6: Thread `q` through the success redirect** — `_redirect_to_builder(course, _raw_q(request))`, never the bare two-arg call, which defaults `q=""` and silently clears the CA's filter.

- [ ] **Step 7: Add the URL**

In `courses/urls.py`, beside `manage_node_rename`, with the same `<slug>`-only shape (`node` travels as a parameter, not a path segment) so `_scope.html` can hoist the reverse the same way:

```python
    path(
        "manage/courses/<slug:slug>/build/node/flag/",
        views_manage.node_flag,
        name="manage_node_flag",
    ),
```

- [ ] **Step 8: Run, falsify WR2 and WR13, commit**

```bash
uv run pytest tests/test_publish_flag_endpoint.py tests/test_manage_node_ops.py -q --verbosity=0
```

Falsify WR2 by dropping `updated=now`; falsify WR13 by removing the `needs_confirmation` check. Both must go red.

```bash
uv run ruff format .
git add courses/builder.py courses/views_manage.py courses/urls.py templates/courses/manage/_flag_strip.html templates/courses/manage/node_confirm_flag.html tests/test_publish_flag_endpoint.py
git commit -m "feat(builder): manage_node_flag endpoint with server-side confirmation"
```

---

## Task 12: The confirm strip and no-JS interstitial

**Files:**
- Modify: `templates/courses/manage/_flag_strip.html`, `templates/courses/manage/node_confirm_flag.html` (both **created** in Task 11; this task fills in the copy variants)
- Modify: `courses/views_manage.py` (`_flag_strip`)
- Create: `tests/test_publish_strip.py`

**Interfaces:**
- Consumes: Task 10's `submission_counts` / `is_quiet`, Task 11's minimal `_flag_strip`.
- Produces: `_flag_strip` upgraded from Task 11's stub to the full renderer, returning a fragment whose root is `<div data-flag-strip="<pk>">`.

The signature and the context dict are the interface between Steps 2/3 and Step 4, so they are pinned here rather than left to inference:

```python
def _flag_strip(request, course, node, *, flag, scope, ctx=None):
    """Render the confirm strip. Fragment for a `fetch`, full-page
    interstitial otherwise (_wants_fragment decides).

    `ctx` must round-trip -- see the response table in Task 11 Step 5."""
    return render(request, template, {
        "course": course,        # the form's action and the interstitial's
                                 # Cancel href both reverse on course.slug --
                                 # omit it and you get NoReverseMatch, not a
                                 # blank
        "node": node,
        "flag": flag,            # "published" | "obligatory"
        "scope": scope,          # "node" | "subtree"
        "total": total,          # units in subtree, or LESSONS when flag=obligatory
        "on": on,                # how many of `total` currently have the flag set
        "submitted": submitted,  # 0 when flag != published or on == 0
        "in_progress": in_progress,
        "quiet": quiet,          # selects the archived-groups copy
        "q": _raw_q(request),    # the filter, threaded through every arm
        "ctx": ctx,              # re-emitted as a hidden input
    })
```

TREE11 asserts the **rendered numbers**, so a key missing from this dict renders as a silent blank rather than raising — which is exactly why the dict is written down.

- [ ] **Step 1: Write the failing tests (QZ5, QZ10, TREE11)**

- **QZ5** — unpublishing a quiz **with** submissions opens the strip; one **without** applies immediately. One test, both halves.
- **QZ10** — hiding a **CHAPTER** containing a quiz with submissions shows the submission warning, counts aggregated over the subtree. *Mutant: render the plain container copy → the CA takes students' results out of reach with no warning, on the higher-blast-radius path.* QZ5 and QZ8 are unit-scope and green without this.
- **TREE11** — a container anchor's href carries **no `value`**, following it returns the mixed strip, and **the strip's rendered numbers are correct** (seed 5 units, 2 live → the strip says "5" and "2 are live"). *Mutant A: require `value` on GET → every container anchor 422s. Mutant B: count over the restricted set or over all nodes rather than units.*

- [ ] **Step 1b: Run to verify failure**

```bash
uv run pytest tests/test_publish_strip.py -v
```

Expected: **two failures and one PASS.** QZ10 and TREE11 go red — Task 11's minimal strip carries a bare count and none of the copy variants.

**QZ5 is green on arrival.** As specified it asserts only *which response comes back* (strip vs immediate write), and Task 11 already implements both halves via `needs_confirmation` plus the minimal strip. Either accept that and give it a falsification in Step 6 (remove the quiz clause from `needs_confirmation`), or extend QZ5 to assert the quiz-variant **copy** so it reddens against this task's own deliverable. Prefer the second — a test that only ever passes is not pulling its weight.

- [ ] **Step 2: Derive the counts from the subtree query**

Not from Task 13's `_tree_context` fold — the write view never calls it:

```python
    ids = node._subtree_node_ids()
    units = ContentNode.objects.filter(pk__in=ids, kind=ContentNode.Kind.UNIT)
    if flag == "obligatory":
        units = units.filter(unit_type=ContentNode.UnitType.LESSON)
    total = units.count()
    on = units.filter(**{flag: True}).count()
```

One aggregate over the set the write will touch, so the count and the action cannot disagree.

- [ ] **Step 3: Add the quiz warning, gated on `on > 0`, and select loud vs quiet copy**

**Not gated on `value == "0"`** — the subtree strip is rendered from the container GET, which carries no `value` at all, so a literal `value == "0"` gate is never true on that path and the warning would never render:

```python
    unit_pks = list(units.values_list("pk", flat=True))   # from Step 2

    # Initialise BEFORE the branch. For an obligatory strip, or a published
    # strip on an all-draft container (on == 0), the branch does not run --
    # and the context dict passes all three unconditionally, so leaving them
    # unbound raises NameError at render() rather than showing a blank.
    submitted = in_progress = 0
    quiet = False

    if flag == "published" and on > 0:  # i.e. this strip offers a hide action
        submitted, in_progress = submission_counts(unit_pks)
        quiet = is_quiet(unit_pks, course)
```

`unit_pks` is **every unit in the subtree**, not only the published ones. The strip is warning about what the *hide* action will take down, and on a mixed chapter the already-drafted units are not part of that — but their submissions still belong to the same quizzes the CA is about to bury, and under-reporting is the failure mode this warning exists to prevent. QZ10 asserts the aggregate over all subtree units.

`quiet` selects the copy: loud when any submitting student is in a live class or has no group at all, quiet ("12 submissions, all from archived groups") when every one of them is provably in a finished class. **Without this line `is_quiet` has no consumer and the entire archived-group feature ships dead**, with QZ1–QZ4 passing in isolation.

- [ ] **Step 4: Write the strip template**

Root element `<div class="flag-strip" data-flag-strip="{{ node.pk }}">`. It is a **sibling after** `<form class="tree__rowhead">`, inside the same `<li>` — **not** a descendant, because it carries its own `<form method="post">` and **HTML forbids nested forms**; nesting would produce markup browsers silently re-parent, breaking submission in a way that looks like a server bug.

Standalone form, every field rendered explicitly — there are no rowhead inputs to inherit:

```html
<form method="post"
      action="{% url 'courses:manage_node_flag' slug=course.slug %}"
      data-op="flag-confirm">
{% csrf_token %}
<input type="hidden" name="node"      value="{{ node.pk }}">
<input type="hidden" name="token"     value="{{ node.updated.isoformat }}">
<input type="hidden" name="flag"      value="{{ flag }}">
<input type="hidden" name="scope"     value="{{ scope }}">
<input type="hidden" name="confirmed" value="1">
{% if q %}<input type="hidden" name="q" value="{{ q }}">{% endif %}
{% if ctx %}<input type="hidden" name="ctx" value="{{ ctx }}">{% endif %}
{# value rides on the BUTTONS — the mixed case has two, differing only in it #}
<button type="submit" name="value" value="1" data-op="flag-confirm">…</button>
<button type="submit" name="value" value="0" data-op="flag-confirm">…</button>
```

One template with a `flag`-keyed string table, covering all four variants: published/mixed, published/single-action, obligatory/mixed (counting **lessons**, not units), and the quiz hide variant. In the **mixed** case the quiz warning lines attach **beneath the hide button**, scoped to it — printing them above both buttons would misdescribe the publish button sitting next to it.

The quiz hide variant has **two forms**, selected by `quiet`:

| `quiet` | Copy |
|---|---|
| `False` (loud) | "12 students have submitted. 3 students are part-way through." + the results/re-grade/interruption lines |
| `True` | "12 submissions, all from archived groups." + the same lines, at lower visual weight |

Never fully suppressed: archived is not deleted. Deleting a question still destroys that cohort's historical responses, and their gradebook is still reachable — the quiet form softens the tone, not the facts.

Add a test for the split, or `is_quiet` is exercised only by QZ1–QZ4 in isolation and its wiring is unpinned: seed one quiz whose only submitter is in an archived group, assert the quiet string; add a second submitter in a live group, assert the loud one.

- [ ] **Step 5: Write the no-JS interstitial** reusing the `node_confirm_delete.html` shape, with the same fields plus `q`.

- [ ] **Step 6: Run, commit**

```bash
uv run pytest tests/test_publish_strip.py -q --verbosity=0
uv run ruff format .
git add templates/courses/manage/_flag_strip.html templates/courses/manage/node_confirm_flag.html courses/views_manage.py tests/test_publish_strip.py
git commit -m "feat(builder): in-place confirm strip with aggregated quiz warnings"
```

---

## Task 13: Tree UI — sprite, markup, fold, CSS, legend

**Files:**
- Modify: `templates/courses/manage/_icon_sprite.html`, `_tree_node.html`, `builder.html`, `courses/views_manage.py` (`_tree_context` **and the new `_fold_flag_counts`**), **`courses/static/courses/css/builder.css`**
- Create: `templates/courses/manage/_flag_legend.html`
- Create: `tests/test_publish_tree.py`

**Interfaces:**
- Consumes: Task 4's helpers.
- Produces: context keys `flag_counts` (`dict[pk] -> (live_units, total_units, obligatory_lessons, total_lessons)`) and `quizzes_with_submissions` (a set of unit pks).

- [ ] **Step 1: Write the failing tests (TREE1–TREE10)**

TREE11 belongs to **Task 12**, which spells it out in full — do not write it twice.

The ones whose mutants are subtle:

- **TREE1** — the visually-hidden Rename submit precedes **both** toggle buttons in the rowhead's source order. *Mutant: place the toggles before it → Enter would publish instead of renaming.*

  **Assert source order, not behaviour.** "Enter renames" is a browser behaviour the Django test client cannot exercise; written naively as "POST the rowhead form and assert a rename", the test is green on the mutant — an assertion that cannot fail. Parse the rendered rowhead, collect its submit controls in document order, and assert the hidden Rename button's index is lower than either `[data-op="flag"]` button's. Implicit submission picks the *first* submit in tree order, so that index comparison **is** the behaviour.
- **TREE4** — container counts fold the **FULL** subtree under an active filter. Seed 6 units of which 2 are live, filter so only the 2 live ones match, and assert the container renders the **mixed** glyph. **Assert the glyph, not a rendered number** — under a filter the anchor is inert and its `title` is replaced by the filter tooltip, so a count may not appear anywhere in the markup. *Mutant: fold over the template's `children_map` (`fc.restricted`) → the restricted view sees 2 units, both live → renders all-live.*
- **TREE3/TREE5** — inert containers: assert the **non-clickable property** (no `href`, `aria-disabled="true"`), **never** the string `disabled`. `disabled` is not valid on `<a>` — it is ignored, the link stays clickable, and an assertion on it passes over markup that blocks nothing.
- **TREE6** — a container of one quiz + one obligatory lesson renders "all obligatory", not "mixed". *Mutant: share one `total_unit_count` between both tri-states → the quiz's inert flag drags it to mixed.*
- **TREE7** — **three** quiz rows, three renderings: published+submissions → confirming anchor; no submissions → button; **drafted+submissions → button**. *Mutant B: key the rendering on "has submissions" without `and node.published` → the drafted quiz opens a strip asking the user to confirm hiding something already hidden.* **The third case is the one a two-case test misses**, and it is the state every quiz lands in immediately after the carve-out fires.
- **TREE9** — two halves. **Markup**: the quiz row's obligatory control is `type="button"` with **no `formaction`**. *Mutant: apply the anchor recipe (drop `href`, add `aria-disabled`) → it is still `type="submit"` with a `formaction`, so a click submits natively and writes.* **Do not assert "no `href`" — a button has no `href` under any implementation, so that assertion is green on the very mutant this half exists for.* **Server**: `POST` with `flag=obligatory&scope=node&node=<quiz>` returns 422.
- **TREE10** — a **quiz-only** container renders the obligatory control inert and the publish control live. *Mutant: key inertness on unit count → a quiz-only chapter has units but zero lessons, so it renders a tri-state over an empty denominator.*
- **TREE8** — `builder.html` renders **six** legend rows, one per state, and each names one of the six `icm--*` classes from Step 2 (or the six `bi-*` symbols, if you took the sprite option there — assert whichever mechanism the legend actually uses).

- [ ] **Step 1b: Run to verify failure**

```bash
uv run pytest tests/test_publish_tree.py -v
```

Expected: ten assertion failures — no toggles are rendered yet, so every glyph, inertness and Enter assertion fails.

- [ ] **Step 2: Add six MASKED icon classes to `builder.css` — NOT sprite symbols**

**The builder tree does not use the `#bi-*` sprite, deliberately.** `builder.css` says so in a comment with measured numbers: `<use>` instances were 33% of mat-pp's expanded DOM (6,678 of them), and replacing them with CSS masks cut the swap's insert+layout from 334 ms to 230 ms. *"The sprite stays for `el-*` (element cards) and the editors, which render a bounded number of icons and where this trade does not pay."* Two `<use>`-backed glyphs per row would add ~5,700 shadow trees on mat-pp and re-introduce exactly that regression.

So the six icons are `--icm` custom properties beside `.icm--grip`, `.icm--trash` and the rest:

```css
.icm--live       { --icm: url("data:image/svg+xml,…"); }   /* filled dot   */
.icm--draft      { --icm: url("data:image/svg+xml,…"); }   /* hollow dot   */
.icm--live-mixed { --icm: url("data:image/svg+xml,…"); }   /* half dot     */
.icm--req        { --icm: url("data:image/svg+xml,…"); }   /* filled star  */
.icm--opt        { --icm: url("data:image/svg+xml,…"); }   /* outline star */
.icm--req-mixed  { --icm: url("data:image/svg+xml,…"); }   /* half star    */
```

**Fills inside the data URI are written `black`, never `currentColor`.** The same comment explains why: inside a `data:` URI the SVG is its own document, so `currentColor` there resolves against *that* document's initial colour, and the mask reads **alpha** — all that matters is that the glyph be opaque. `.icm::before` then paints it with `background-color: currentColor`, which is what makes hover, `:disabled` and `.ica--danger` keep working untouched.

Each control carries the base class `icm` plus its state class, exactly as the existing row controls do (`class="ica icm icm--grip"`).

Fill **and** silhouette both carry the state, so the pair survives greyscale and colour-blindness; colour is reinforcement, never the sole channel.

**`_flag_legend.html` is the one exception.** It renders six icons once per page — a bounded count, which is precisely the case the comment says the sprite is still for. It may use either mechanism; if you use the sprite there, add the six `bi-*` symbols for it alone and keep the two id sets distinct so TREE8 and the tree tests cannot collide. Simplest is to reuse the `icm--*` classes and add no sprite symbols at all.

TREE2, TREE4, TREE6 and TREE10 assert the **`icm--*` class**, not a `#bi-*` href.

- [ ] **Step 3: Compute the fold in `_tree_context`**

It is the one shared place that already receives the **full** `cmap` and is called by both `builder` and `_render_scope`. One bottom-up fold over the already-loaded node list:

```python
    # Fold the UNRESTRICTED cmap. The template's children_map is
    # fc.restricted under an active filter; folding THAT makes a container
    # claim "3 units" when its subtree holds 40 — and the strip's count is
    # the sole stated mitigation for the accepted over-publish cost, so a
    # wrong count does not merely mislead, it removes the only guard.
    "flag_counts": _fold_flag_counts(cmap),
    # ONE additional course-wide query, not zero. Per-row this would be an
    # N+1 across every quiz in a 2,866-node tree. ANY status — mirrors
    # needs_confirmation, so an interrupted attempt still earns a confirm.
    "quizzes_with_submissions": set(
        QuizSubmission.objects.filter(unit__course=course).values_list(
            "unit_id", flat=True
        )
    ),
```

**Separate denominators**: publish counts all units; obligatory counts **lesson units only**. A shared denominator makes a chapter of five obligatory lessons and one quiz read "mixed obligatory" purely because of an inert flag.

Write the helper in `courses/views_manage.py`, beside `_children_map`:

```python
def _fold_flag_counts(cmap):
    """pk -> (live_units, total_units, obligatory_lessons, total_lessons) over
    each CONTAINER's whole subtree.

    Fold the UNRESTRICTED cmap. Under an active filter the template's
    children_map is fc.restricted, and folding THAT makes a container claim
    "3 units" when its subtree holds 40 (TREE4).

    Containers only: a unit row reads its own node.published / node.obligatory
    directly in the template and needs no entry here. Roots live under the
    cmap key None, which is not a node and gets no entry either.
    """
    counts = {}

    def visit(pk):
        live = total = ob = lessons = 0
        for child in cmap.get(pk, []):
            if child.kind == ContentNode.Kind.UNIT:
                total += 1
                live += 1 if child.published else 0
                if child.unit_type == ContentNode.UnitType.LESSON:
                    lessons += 1
                    ob += 1 if child.obligatory else 0
            else:
                c_live, c_total, c_ob, c_lessons = visit(child.pk)
                live, total, ob, lessons = (
                    live + c_live,
                    total + c_total,
                    ob + c_ob,
                    lessons + c_lessons,
                )
        counts[pk] = (live, total, ob, lessons)
        return counts[pk]

    for root in cmap.get(None, []):
        if root.kind != ContentNode.Kind.UNIT:
            visit(root.pk)
    return counts
```

Note it recurses over containers only and seeds from `cmap[None]`. A unit row never appears as a key — the template reads a unit's own two booleans and needs no rollup.

- [ ] **Step 4: Add the two controls to `_tree_node.html`**

Direct children of `<form class="tree__rowhead">`, **siblings of `.tree__cluster`** — the rowhead is the flex container, so `.tree__cluster` is the flex *item* and `order` on anything nested inside it is **inert**, producing a silent layout failure with nothing to debug.

**The parameters ride in `formaction` / `href`, not in `data-` attributes.** `data-flag` is read by JS only; it is never submitted. The rowhead form supplies `csrf`, `node`, `token`, `mode`, `q` and `title` — so `flag`, `value` and `scope` have no channel unless the control carries them in its URL. This is what makes Task 11's `param()` helper read `request.GET` on a POST.

Write the URL once per row variant. `value` is the **opposite** of the row's current state — the control's job is to flip it:

**`flag_url` is reversed once per SCOPE, in `_scope.html`, and passed down** — not reversed here. `_scope.html` already hoists `rename_url`, `move_url`, `delete_url` and `duplicate_url` with an explicit comment: *"reverse it once per scope and pass it down instead of paying a reversal on every row (an 840-node course reversed it 840 times, ~64µs each)."* `_tree_node.html` is the per-row partial, so `{% url … as flag_url %}` here would pay 2,866 reversals on mat-pp — the exact cost Task 11 Step 7 chose the `<slug>`-only path shape to avoid.

Add to `_scope.html` beside the other four, and add `flag_url=flag_url` to its `{% include "courses/manage/_tree_node.html" with … %}` call. Add `templates/courses/manage/_scope.html` to this task's Files list.

```django
{# _scope.html, once per scope: #}
{% url 'courses:manage_node_flag' slug=course.slug as flag_url %}

{# _tree_node.html consumes the passed-in flag_url. #}
{# Lesson unit — publish toggle #}
<button type="submit" data-op="flag" data-flag="published"
        formaction="{{ flag_url }}?flag=published&amp;value={% if node.published %}0{% else %}1{% endif %}&amp;scope=node"
        aria-label="{% if node.published %}{% trans 'Hide from students' %}{% else %}{% trans 'Publish' %}{% endif %}"
        title="...">…</button>

{# Lesson unit — obligatory toggle: same shape, flag=obligatory, value flips node.obligatory #}

{# Container, and a published quiz with submissions — an ANCHOR, GET, no value #}
<a data-flag-confirm="{{ node.pk }}" data-flag="published"
   href="{{ flag_url }}?node={{ node.pk }}&amp;flag=published&amp;scope={% if node.kind == 'unit' %}node{% else %}subtree{% endif %}{% if q %}&amp;q={{ q|urlencode }}{% endif %}">…</a>
```

Three things the anchor does and the button does not: it carries `node` explicitly (there is no form to supply it), it carries **no `value`** (a mixed container's strip offers both directions and derives a single action from counts — requiring `value` on GET would 422 every container anchor), and it carries `q`.

The button needs no `node` or `q` — the rowhead form already posts both.

Element type by row:

| Row | Publish control | Obligatory control |
|---|---|---|
| Lesson unit | `<button type="submit" data-op="flag" data-flag="published" formaction="…?flag=published&value=<flip>&scope=node">` | same with `flag=obligatory` |
| Quiz unit, published, with ≥1 submission | `<a data-flag-confirm="{{ node.pk }}" data-flag="published" href="…?node=…&flag=published&scope=node">` | inert button |
| Quiz unit, otherwise | submit button, as the lesson row | inert button |
| Container | `<a data-flag-confirm>`, `scope=subtree` | `<a>`, `flag=obligatory`, inert when `total_lessons == 0` |

Note the quiz confirming anchor uses `scope=node`, not `subtree` — it is a single unit; it merely needs confirmation. The inert controls carry no `formaction` and no `href` at all, which is exactly what makes them inert (TREE9).

**Container anchors are ALSO inert while the builder filter is active** — a third inert case, separate from the two count-based ones in Step 4b, and the one TREE5 asserts. Bulk-publishing under a filter invites the CA to believe the action is scoped to the visible rows; the spec makes it unclickable for that reason.

The flag is already in the tree context: `_tree_context` emits `filtered` (fed from `fc.q_active`), so no new plumbing is needed:

```django
{% if filtered %}
  <a class="ica icm--live is-inert" aria-disabled="true" tabindex="-1"
     title="{% trans 'Clear the filter to publish or hide a whole section.' %}"></a>
{% else %}
  <a data-flag-confirm="{{ node.pk }}" data-flag="published" href="…">…</a>
{% endif %}
```

**Unit toggles stay live under a filter** — they affect exactly the one row shown. Without this step TREE5 is a test with nothing to test, and WR18's fixture rationale in Task 11 (which relies on container anchors being unreachable under a filter, so it uses the quiz anchor instead) rests on behaviour that was never built.

- [ ] **Step 4b: Select the glyph — the step TREE2, TREE4, TREE6 and TREE10 all assert**

Those four tests read *glyphs*, and nothing so far says how a glyph is chosen. Two mechanics an implementer will otherwise have to invent:

**Django cannot index a dict by a variable key.** `flag_counts[node.pk]` is not valid template syntax. The repo already has the filter for this — `get_item` in `courses/templatetags/courses_manage_extras.py`, which `_tree_node.html` already loads for `children_map|get_item:node.pk`.

**Units read their own booleans; containers read the fold.** A unit has no `flag_counts` entry (Step 3's helper keys containers only), so the two branches differ:

```django
{% load courses_manage_extras %}

{% if node.kind == "unit" %}
  {# binary: the node's own two flags #}
  {% if node.published %}icm--live{% else %}icm--draft{% endif %}
  {% if node.obligatory %}icm--req{% else %}icm--opt{% endif %}
{% else %}
  {% with fc=flag_counts|get_item:node.pk %}
    {% if fc %}
      {# publish tri-state: slots 0 (live_units) and 1 (total_units) #}
      {% if fc.1 == 0 %}{# inert: no glyph -- aria-disabled + the title IS the control #}
      {% elif fc.0 == fc.1 %}icm--live
      {% elif fc.0 == 0 %}icm--draft
      {% else %}icm--live-mixed{% endif %}

      {# obligatory tri-state: slots 2 (obligatory_lessons) and 3 (total_lessons) #}
      {% if fc.3 == 0 %}{# inert: no glyph, as above #}
      {% elif fc.2 == fc.3 %}icm--req
      {% elif fc.2 == 0 %}icm--opt
      {% else %}icm--req-mixed{% endif %}
    {% endif %}
  {% endwith %}
{% endif %}
```

**The `{% if fc %}` guard is not defensive padding.** `get_item` is `mapping.get(key, [])`, so a missing container key yields `[]` — and then `fc.0` / `fc.1` both resolve to Django's invalid-variable string `""`. `"" == 0` is False but `"" == ""` is True, so the `elif fc.0 == fc.1` arm fires and the row silently renders **all-live**. That is the worst possible default for this feature, and it fails without raising. The guard turns a silent wrong glyph into a missing one, which a test can see.

The two `== 0` guards are the **count-based** inert cases from Step 4's row table — the filter-active case is a third, also in Step 4 — and they use **different** slots — `fc.1` (units) for publish, `fc.3` (lessons) for obligatory. That asymmetry is the whole of TREE10: a quiz-only chapter has `fc.1 > 0` and `fc.3 == 0`, so its publish control is live while its obligatory control is inert.

Tuple slots are addressed positionally in Django (`fc.0`, `fc.1`, …). If that reads badly at the call site, return a small namedtuple from `_fold_flag_counts` instead and use `fc.live_units` — but then say so in Step 3, because the two are not interchangeable in the template.

**Inert means two different things**, because the two rows use two different elements:

- **Anchors**: no `href`, `aria-disabled="true"`, `tabindex="-1"`, handler bails.
- **The quiz row's obligatory button**: `type="button"`, **no `formaction`**, `aria-disabled="true"`, `tabindex="-1"` — and **not** `disabled`. Browsers do not dispatch pointer events to disabled controls, so a `title` on a `disabled` button **never shows its tooltip**, and that tooltip is the only thing telling the CA why the control is dead.

Both controls carry `title` **and** `aria-label` stating the *action* ("Publish", "Make optional"), not the state — `title` does not exist on touch.

- [ ] **Step 5: Place them with explicit `order` on EVERY rowhead child**

Enter in the title picks the form's first submit button in **tree** order, which is why the visually-hidden Rename button must stay ahead of the cluster. The toggles must therefore appear **after** it in the DOM while sitting left of the title visually. One negative `order` will not do it — the chevron, badge and title are all at the default `0`, so a single negative value puts the toggles leftmost:

| Rowhead child | DOM position | `order` |
|---|---|---|
| Expand toggle / leaf spacer | 1 | `1` |
| Kind badge | 2 | `2` |
| Title input | 3 | `4` |
| Visually-hidden Rename submit | 4 | `4` |
| Publish toggle | 5 | `3` |
| Obligatory toggle | 6 | `3` |
| `.tree__cluster` | 7 | `5` |

The two repeated values are **deliberate**: within an equal `order`, flex falls back to DOM order — publish left of obligatory, and the hidden Rename's position cosmetically irrelevant because it is 1×1 and clipped. Do not "fix" them into distinct values.

Accepted cost: a screen reader reaches the toggles after the title. Tolerable because each `aria-label` states a self-contained action rather than relying on proximity to the title.

- [ ] **Step 5b: Emit `tree__row--draft` on the `<li>`**

Nothing else in this task adds it, and E2E1 ("toggles it and applies the strike-through") has no implementation without it. In `_tree_node.html`, on the row element itself:

```django
<li class="tree__row{% if node.kind == 'unit' and not node.published %} tree__row--draft{% endif %}"
    id="node-{{ node.pk }}" data-node="{{ node.pk }}" ...>
```

The `node.kind == 'unit'` conjunct is load-bearing: a container has no publish state of its own, and striking one through would assert something the model does not hold.

- [ ] **Step 6: CSS — in `builder.css`, NOT `editor.css`**

**Every rule this task adds goes in `courses/static/courses/css/builder.css`.** `builder.html` loads only `builder.css`, and `.tree__row`, `.tree__rowhead`, `.tree__cluster` and `input.tree__title` are all defined there. `editor.css` says so itself: *"The builder's `.tree__scope`/`.tree__row`/`.tree__rowhead` are deliberately NOT reused: they live in builder.css, which this page does not load."*

Put **the six `.icm--*` rules from Step 2**, the strike-through, the seven `order` values from Step 5, and the opacity exemption below into `builder.css`. All four groups; omitting the `--icm` rules leaves every toggle rendering an empty 15×15 box, since `.icm::before` masks against an undefined custom property. Written into `editor.css` they would be inert — the builder never pulls that file in, so E2E1 and the whole Step 5 layout would fail silently, with correct-looking CSS sitting in the repo.

The class lands on the `<li>` while the strike-through belongs on the title, so it is a **descendant** selector — not a rule on the class itself:

```css
.tree__row--draft .tree__title { text-decoration: line-through; }
```

`.tree__title` is an `<input type="text">`, on which `text-decoration` renders correctly.

The toggles render at **full opacity at rest** and are exempt from `.tree__cluster`'s `opacity: .5` hover-reveal: they are state indicators first, and a 50%-dimmed publish dot defeats the one thing the feature is for.

- [ ] **Step 7: Create `_flag_legend.html`** — a `<dl>` of six symbol+label rows, included in `builder.html`. **Not** an addition to `_structure_legend.html`, which is a single `<p>` rendering a kind chain and has no per-symbol structure to add to.

- [ ] **Step 8: Run, falsify TREE1 and TREE9's markup half, commit**

```bash
uv run pytest tests/test_publish_tree.py tests/test_manage_builder.py -q --verbosity=0
uv run ruff format .
git add templates/courses/manage/ courses/views_manage.py courses/static/courses/css/builder.css tests/test_publish_tree.py
git commit -m "feat(builder): publish and obligatory toggles on every tree row"
```

---

## Task 14: builder.js

**Files:**
- Modify: `courses/static/courses/js/builder.js`
- Create: `tests/test_e2e_publish_toggle.py`

**Interfaces:**
- Consumes: Task 13's `data-op="flag"` / `data-flag-confirm` markup, Task 11's responses.

- [ ] **Step 1: Write the failing e2e tests (E2E1–E2E6)**

- **E2E1** — clicking a unit's publish icon toggles it and applies the strike-through, no page reload.
- **E2E2** — a container's icon opens the strip; confirming updates every descendant row; scroll position and expansion state survive.
- **E2E3** — a draft unit is **absent from the student's rendered outline** in a real browser session, and **present in the author's**, carrying the draft banner when opened. Assert the author's *outline* explicitly: "the author sees it" is ambiguous and is satisfied by opening the unit directly, which works even on a build where the outline has dropped it. Task 15's OUT5c leans on this test existing — it justifies its own scope with "E2E3 covers only the student render" — so skipping it leaves the student-facing draft banner with no coverage at all.
- **E2E4** — focus lands on **whichever publish control the re-rendered row now carries**. **Three cases**: unit toggle, confirmed container write, confirmed **quiz unpublish**. *Mutant: focus `[data-flag-confirm]` after every strip write → the drafted quiz now renders a **button**, the selector misses, focus falls to `<body>`* → red **on the third case only**. A two-case test using a container is green on it.
- **E2E5** — a **collapsed** container's toggle visibly updates its own glyph and its ancestors'. This is the case every narrower fragment choice silently no-ops on; a test that expands the container first passes on all of them.
- **E2E6** — a POST that comes back as a strip **opens the strip**, and the originating button is **usable again afterwards**. Full cycle: click → strip opens → dismiss → **click again succeeds**. *Mutant A: route the response straight to `applyFragment` → dead click. Mutant B: clear the `disabled` inside `applyFragment` → the strip branch returns first, the button stays disabled forever.* **A test that stops at "strip opens" is green on Mutant B.**

Sync on conditions, never sleeps. Use `checkVisibility()` wherever a collapsed `<details>` is involved.

- [ ] **Step 1b: Run to verify failure**

```bash
uv run pytest -m e2e tests/test_e2e_publish_toggle.py -v
```

Expected: six failures — the markup exists (Task 13) but no JS handles it, so clicks do nothing.

- [ ] **Step 2: Add the dispatch and handlers**

| Addition | Behaviour |
|---|---|
| `data-op="flag"` + `data-flag` on unit buttons | routed through the existing form-submit dispatch, like `rename` and `duplicate` |
| `data-flag-confirm` + `data-flag` on anchors | `fetch` the GET, insert the strip as a sibling after the rowhead, move focus into it |
| `data-op="flag-confirm"` on the strip form | ordinary POST through the existing dispatch |
| Strip dismiss (`×`, `Esc`) | remove the strip, return focus to the control that opened it — the **anchor** on the GET path, the **toggle button** on the POST-returns-a-strip path, where no anchor exists |
| Double-submit guard | `disabled` for **buttons**; `aria-disabled="true"` + handler bail for **anchors** |
| Open-strip exclusivity | opening a strip closes any other |
| Fetch headers | every fetch sends `X-Requested-With: "fetch"` |

The double-submit guard **cannot** be delegated to `busyStart()`: it only sets `data-busy` on the root and the sole rule keyed to it is a visual dim with **no `pointer-events` suppression**, so a second click during a dimmed tree fires a second submit. `releaseForm(form, op)` returns immediately unless `op === "rename"`, so it provides no lock either.

Omitting the fetch header makes `_wants_fragment` false and injects a whole page into an `<li>`.

- [ ] **Step 3: Branch on the strip response BEFORE `applyFragment`**

A POST can come back as a strip (a stale page, or a click that raced the quiz's first submission). That response's root is **not** `<… data-scope="top">`, so `applyFragment` misses the lookup and **silently no-ops** — the author clicks, nothing happens, nothing writes, nothing explains why:

`incoming`, `control` and `reenable` are not existing symbols — the existing dispatch has a raw `text` response, `e.submitter`, and `releaseForm(form, op)` (which returns early unless `op === "rename"`). Derive them:

```js
var control = e.submitter;                 // the clicked button/anchor
control.disabled = true;                   // buttons; anchors get aria-disabled
try {
  var incoming = parseFragment(text).firstElementChild;
  if (incoming && incoming.matches("[data-flag-strip]")) {
    // The server is asking, not answering: this response is a strip, whose
    // root has no data-scope, so applyFragment would silently no-op.
    insertStripAfterRowhead(incoming); focusInto(incoming); return;
  }
  applyFragment(text);
} finally {
  control.disabled = false;                // MUST run on every arm
  control.removeAttribute("aria-disabled");
}
```

The `finally` is not decoration: on this path the tree is **not** re-rendered, the original button survives in the DOM, and the branch `return`s before `applyFragment`. Clearing the guard "where the response is applied" leaves that button **permanently disabled** until a page reload.

- [ ] **Step 4: Restore focus after the swap**

Re-rendering `top` destroys the control that was activated:

| Path | Focus target |
|---|---|
| Unit toggle | `[data-node="<pk>"] [data-op="flag"][data-flag="<flag>"]` |
| Confirmed **container** write | `[data-node="<pk>"] [data-flag-confirm="<pk>"][data-flag="<flag>"]` |
| Confirmed **quiz** unpublish | `[data-node="<pk>"] [data-op="flag"][data-flag="<flag>"]` — a **button** |

The quiz case takes the unit selector because the write set `published=False`, so that row now renders a plain button — a drafted quiz needs no confirmation to be *published*.

- [ ] **Step 5: Run the e2e (mandatory `-m e2e`), commit**

```bash
uv run pytest -m e2e tests/test_e2e_publish_toggle.py -v
```

Falsify E2E6 by moving `reenable` inside `applyFragment` and confirming the "click again" half goes red while "strip opens" stays green.

```bash
uv run ruff format .
git add courses/static/courses/js/builder.js tests/test_e2e_publish_toggle.py
git commit -m "feat(builder): client wiring for flag toggles and the confirm strip"
```

---

## Task 15: Unit settings and the draft banners

**Files:**
- Modify: `templates/courses/manage/editor/_unit_settings.html`, `templates/courses/manage/editor/editor.html`, `templates/courses/lesson_unit.html`, the quiz unit template, `courses/builder.py` (`rename_node`), `courses/views_manage.py` (`node_rename`), **`courses/views.py`** (the render context the student-facing banner reads)
- Create: `tests/test_publish_banners.py`

**Interfaces:**
- Consumes: Task 10's counts, Task 11's endpoint.

- [ ] **Step 1: Write the failing tests (WR6, WR10/WR17, OUT5c, QZ6, QZ7, QZ8, QZ9)**

- **WR6** — the settings form round-trips `published`, including **unchecking** it (absent-means-false).
- **WR17** — the banner form actually renders `flag`, `value`, `scope` and `ctx` as hidden inputs. Assert the rendered markup; without them every click 422s.
- **WR10** — the redirect honours `ctx` on **both** arms, which are two different banners on two different pages:
  - `ctx=editor` (editor-page banner) → redirect to `manage_editor`, **not** the builder. *Mutant: let `_wants_fragment` decide instead of `ctx`* — the banner posts are ordinary no-JS-shaped forms, so `_wants_fragment` is false and the author lands on the builder.
  - `ctx=unit` (the **student-facing render** banner, posted by the author) → redirect back to the unit URL, and a stale token redirects there too.

  Do not fold these into one test. The `ctx=unit` arm is the only thing exercising the render-context wiring in Step 3 item 2, and without it that whole column of Task 11's response table is untested.
- **OUT5c** — the **editor page** renders the draft banner for a draft unit and not for a published one. Nothing else covers it: E2E3 covers only the student render, WR17 only the redirect.
- **QZ6** — in-progress rows are counted **on their own line, never as "submitted"**. Open a quiz without finishing; assert the banner **renders**, says "1 student is part-way through", and does **not** claim anyone submitted. *Mutant A: count every row into the submitted figure. Mutant B: trigger the banner on `SUBMITTED` only → a published in-progress-only quiz shows no banner at all, and unchecking Published below it strands those attempts in silence.*
- **QZ7** — a student who submitted **404s on `quiz_results`** while the quiz is drafted, and the row is gone from their `course_results`.
- **QZ8** — a quiz with **only** in-progress attempts still gets a confirm strip on unpublish. *Mutant: filter `needs_confirmation` to `SUBMITTED` → it unpublishes on one click with no warning.* QZ1–QZ6 all use submitted rows and are green on that mutant.
- **QZ9** — an interrupted attempt **resumes on republication**: same `QuizSubmission`, answers intact, no second row.

- [ ] **Step 1b: Run to verify failure**

```bash
uv run pytest tests/test_publish_banners.py -v
```

Expected: **six failures and three PASSes.** Nine tests, not seven — WR10 and WR17 are separate (Step 1 says "Do not fold these into one test").

Three are **green on arrival**, implemented by earlier tasks and living here only because this is where the quiz surfaces are assembled. Do not hunt for missing bodies:

| Test | Already implemented by | Its RED gate |
|---|---|---|
| QZ7 (student 404s on `quiz_results` for a drafted quiz) | Tasks 3 and 6 | revert Task 3's `viewer=` on `quiz_results` |
| QZ8 (in-progress-only quiz still gets a strip) | Task 11's ANY-status `needs_confirmation` | revert that widening to `status=SUBMITTED` |
| QZ9 (interrupted attempt resumes on republication) | pre-existing `quiz_unit` behaviour, gated by Task 3 | revert Task 3's `viewer=` on `quiz_answer`/`quiz_finish` |

Run each of those three falsifications in Step 4 so all three still get a RED gate somewhere, even though it is not here.

- [ ] **Step 2: Add the checkbox and thread `published` through `rename_node`**

`builder.rename_node` gains `published=_UNSET`, guarded by the same `if node.kind == ContentNode.Kind.UNIT:` block that already guards `unit_type`, `obligatory` and `html_seed_js`. `node_rename` passes `published=("published" in request.POST) if is_settings else builder_svc._UNSET`.

This path is **deliberately exempt** from the confirmation invariant — §6's editor banner has already delivered the counts and hazards on this very surface, directly above the form, so a confirmation here would restate what the author is looking at. Add a comment saying so, or a reader will file it as a bug.

- [ ] **Step 3: Add the three banners**

1. **Editor page, draft unit** — "Draft — not visible to students" + a Publish button.
2. **Student-facing render, viewed by an author** — same. **Text-only, no sprite glyph**: `_icon_sprite.html` is included only by `builder.html`, `editor/editor.html` and `help/doc.html`, so a glyph here would paint blank, and pulling the sprite into the lesson template to serve one banner ships the whole symbol set to every student page.

   **This banner needs render context that `courses/views.py` must supply.** `lesson_unit.html` and the quiz template can only ask "is the viewer an author?" if something puts the answer in the context. Add `"is_author": drafts == "keep"` to all **three** render paths — `full_lesson_render_context`, `quiz_unit` and `_quiz_render_feedback` — reusing the `drafts` expression Task 6 already computes there rather than calling `can_see_drafts` a second time. Then the template is `{% if is_author and not node.published %}`.

   Miss this and the banner renders for nobody, silently, on a page that otherwise looks correct.
3. **Editor page, quiz with any submission row** — the counts on **two lines**, plus the three hazards. **Both lines**: a published quiz whose only rows are `IN_PROGRESS` would otherwise carry no banner at all (it is live, so the draft banner does not apply), and unchecking Published directly below would strand every in-flight attempt in silence.

   **This is `is_quiet`'s second consumer**, and without it half of Task 10 ships dead — the spec's "archived groups soften the warning" section is about *this banner*, not only the strip. Compute all three and pin the context keys, the way Task 12 pins the strip's dict (a missing key renders as a silent blank, not an error):

   ```python
   # in the editor page's context builder, for unit_type == "quiz" only
   submitted, in_progress = quiz_warnings.submission_counts(unit)
   ctx["submitted"] = submitted
   ctx["in_progress"] = in_progress
   ctx["quiet"] = quiz_warnings.is_quiet(unit, unit.course)
   ```

   Two copy variants, mirroring Task 12 Step 3's table:

   | `quiet` | Copy |
   |---|---|
   | `False` | "12 students have submitted. 3 students are part-way through." + the three hazards |
   | `True` | "12 submissions, all from archived groups." + the same hazards, at lower visual weight |

   Add an assertion for the split to this task's test list — QZ1–QZ4 test the predicate in isolation and Task 12's split test covers the strip only, so nothing else pins this banner's loud/quiet choice.

Each banner is a real `<form method="post">` carrying **every** field:

```html
{% csrf_token %}
<input type="hidden" name="node"  value="{{ node.pk }}">
<input type="hidden" name="token" value="{{ node.updated.isoformat }}">
<input type="hidden" name="flag"  value="published">
<input type="hidden" name="value" value="1">
<input type="hidden" name="scope" value="node">
<input type="hidden" name="ctx"   value="editor">   {# or "unit" #}
```

- [ ] **Step 4: Run, falsify QZ6's Mutant B, commit**

```bash
uv run pytest tests/test_publish_banners.py tests/test_manage_builder.py -q --verbosity=0
uv run ruff format .
git add templates/ courses/builder.py courses/views_manage.py courses/views.py tests/test_publish_banners.py
git commit -m "feat(editor): Published setting and the draft / submission banners"
```

---

## Task 16: i18n, content links, and the branch gate

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`)
- Create: `tests/test_publish_links.py`

- [ ] **Step 1: Write LNK1**

A link to a draft unit renders **identically** for author and student, and the student gets 404 on following it. Pins the decision so a later "helpful" suppression is deliberate rather than silent.

- [ ] **Step 2: Merge `origin/master` and re-verify the two constants**

```bash
git fetch origin && git merge origin/master
grep -n "FORMAT_VERSION = " courses/transfer/schema.py
ls courses/migrations/ | tail -3
```

Master has moved as often as six times inside one session. If another branch landed a migration, renumber `0057`; if one bumped `FORMAT_VERSION`, note that two branches setting it to the **same** value merge **silently and green** — check the *value*, not just for conflicts.

- [ ] **Step 3: Extract and compile translations**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
uv run python manage.py compilemessages
```

Verify **0 fuzzy / 0 obsolete**. `makemessages` pre-fills fuzzy matches with *wrong* translations for near-miss strings, and this feature adds several close to existing ones ("Publish"/"Published", "Hide"/"Hidden"). Clearing a fuzzy entry is **two** deletions — the `#, fuzzy` comment and the wrong `msgstr`.

- [ ] **Step 4: Full-suite branch gate**

Start the test-DB container first. This is the one place a whole-repo run belongs:

```bash
uv run pytest -q --verbosity=0
uv run pytest -m e2e -q --verbosity=0
uv run ruff format --check .
uv run ruff check .
```

The e2e suite takes ~53 minutes and the harness reaps backgrounded pytest — run it with `Start-Process` and poll the PID rather than backgrounding it directly.

- [ ] **Step 5: Commit and open the PR**

```bash
uv run ruff format .
git status --short          # READ THIS before staging — see below
git add locale/ docs/superpowers/
git add <any file the Step 2 merge touched>
git commit -m "feat(courses): unit publish state with builder tree toggles"
gh pr create --title "Unit publish state + one-click builder flag toggles" --body "..."
```

**No `git add -A` here.** Every other task in this plan stages an explicit list, and a blanket add at the end sweeps up whatever the falsification steps, the e2e run and `compilemessages` left behind — reverted mutants, screenshots, `.pyc`, stray fixtures. Read `git status --short` and stage what you recognise. The `.mo` binaries are intended and must be included.

PR body: link the spec, list migration `0057` and `FORMAT_VERSION` 10 as deploy-affecting, and note that `0053`–`0057` all remain pending on deployed DBs.

---

## Self-Review

**Spec coverage:** §1 → Task 1. §2 → Tasks 4–8. §3 → Tasks 2–3. §4 → Tasks 11–12. §5 → Task 13. §6 → Tasks 10, 12, 15. §7 → Task 16. §8 → Task 9. §10 → Task 16. §11 (out of scope) → no tasks, correctly.

**§9 test-id assignment**, checked by sweeping every task's Step 1 list against the spec rather than asserted:

| Prefix | Task |
|---|---|
| MIG1–MIG3 | 1 |
| ACC1–ACC6 | 2 (ACC1, ACC2, ACC4, ACC5), 3 (ACC3, ACC6) |
| OUT1–OUT5c | 5 (OUT1–OUT5b), 15 (OUT5c) |
| OUT6–OUT10 | 6 (OUT6, OUT6b, OUT8, OUT9, OUT10), 8 (OUT7) |
| ANA1–ANA6 | 8 |
| ANA7 | 4 (both halves, with the opposite fixtures) |
| WR1–WR18 | 11 (WR1–WR5, WR7–WR9, WR11–WR14, WR16, WR18), 7 (WR15, WR15b, WR15d), 2 (WR15c), 15 (WR6, WR10, WR17) |
| TREE1–TREE10 | 13 |
| TREE11 | 12 |
| QZ1–QZ4 | 10 |
| QZ5–QZ10 | 12 (QZ5, QZ10), 15 (QZ6–QZ9) |
| LNK1 | 16 |
| KEEP1, TR1–TR4 | 9 |
| E2E1–E2E6 | 14 |

An earlier draft of this section claimed "every id assigned" while ACC4, OUT2, OUT3, WR5, WR7 and WR8 had no home. The table above is the reason the claim is now checkable — do not replace it with a sentence.

**Deliberate gaps carried from the spec:** the element-level `*_check` endpoints stay ungated (§3), content links render and 404 (§7), and quiz edits warn rather than re-grade (§6). All three are stated decisions, not omissions.

**Type consistency:** `unit_is_visible`, `set_node_flag`, `submission_counts`, `is_quiet`, `manageable_courses`, `can_see_drafts`, `flag_counts`, `quizzes_with_submissions`, `tree__row--draft`, `data-flag-strip`, `data-flag-confirm`, `data-op="flag"` / `"flag-confirm"` — each defined once and referenced by the same name everywhere after.

**Ordering:** every task's Consumes block names only tasks before it.
