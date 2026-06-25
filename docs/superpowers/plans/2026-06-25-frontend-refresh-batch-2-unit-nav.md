# Frontend Refresh — Batch 2: Unit-Page Navigation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-column "unit shell" to the lesson and quiz unit pages — a collapsible course tree on the left, the existing unit content on the right, and a footer bar with Prev/Next + progress, plus a mobile drawer.

**Architecture:** A new pure service `build_unit_nav(course, user, current_node)` in `courses/rollups.py` derives the tree (reusing `build_outline`), Prev/Next neighbours, and part/course progress from a single shared pre-order walk (`_walk_preorder`). Both unit views call it and add `unit_nav` to context. A shared `courses/_unit_shell.html` partial (parameterised by a `content_partial` include) wraps the existing `<article>` and pulls in the tree, footer, and drawer partials. CSS lives in shared `courses/static/courses/css/courses.css` (so batch 3's review roster reuses the same `.unit-shell` classes). A pre-paint inline script on `<html>` restores the desktop collapse state without a flash; `unit_nav.js` handles the toggle, auto-scroll, and the mobile drawer (with its own focus trap).

**Tech Stack:** Django 5 (server-rendered templates, `{% trans %}` i18n), pytest + `pytest-django`, Playwright (pytest-playwright) for e2e, vanilla JS (no framework), token-driven CSS. Package/tooling via `uv`.

## Global Constraints

Every task implicitly includes all of these:

- **Tooling is `uv run …`.** Bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run pytest`, `uv run ruff check`, `uv run ruff format`, `uv run python manage.py …`.
- **Lint gate on every EDITED file (not just new ones):** before each commit run `uv run ruff check <files>` AND `uv run ruff format --check <files>`. CI runs `ruff format --check`; a task is not done until both are clean. (Batch-1 note from the user.)
- **TDD:** write the failing test first, watch it fail, implement minimally, watch it pass, commit. One logical change per commit.
- **i18n:** every new user-visible string is wrapped in `{% trans %}` (templates) and gets a Polish translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo` (`uv run python manage.py compilemessages`). After `makemessages`, clear any `#, fuzzy` flags on strings you translated and verify the auto-guessed `msgstr` is correct (the makemessages fuzzy gotcha — it mis-guesses, e.g. "Enrolled"→"Zapisz się").
- **Django comments:** `{# #}` must be single-line; use `{% comment %}…{% endcomment %}` for multi-line, or it renders as visible text.
- **Do not break the seen-tracking hook.** `progress.js` binds to `.lesson[data-seen-url]` and observes `[data-element-id]` sections. The unit shell wraps **around** the `<article class="lesson" data-seen-url=…>` element — never between it and its `<section>`s. Quiz units have **no** `data-seen-url`; do not add one.
- **e2e drives real gestures** (per the `e2e-must-drive-real-ui` rule): click the actual toggle/FAB/links; never bypass with `page.evaluate` shortcuts. New e2e tests mirror the harness in `tests/test_e2e_quiz.py` (the `_login`, `_make_student` helpers, `live_server`, ORM seeding, `pytestmark = pytest.mark.e2e`).
- **DoD per task:** full unit-test suite green, `ruff check` + `ruff format --check` clean. The whole-branch e2e + screenshot pass is the final task.

**Key model facts (verbatim, do not re-derive):**
- `ContentNode` has `kind` (`Kind.PART/CHAPTER/SECTION/UNIT`), `unit_type` (`UnitType.LESSON/QUIZ`, null on non-units), `parent` / `parent_id` (null on top-level roots), `order`, `obligatory`, `title`, `course`. No `is_unit`/`is_quiz` property — compare `node.kind == ContentNode.Kind.UNIT` and `node.unit_type == ContentNode.UnitType.QUIZ`. `Meta.ordering = ["order", "pk"]`.
- Top-level nodes have `parent_id is None`. A "top-level part" is a root node (`parent_id is None`) that is **not** a unit.
- Unit views are `@login_required`; `user` is always authenticated. Both unit views route through `courses:lesson_unit` for any unit link — `lesson_unit` redirects a quiz `node_pk` to `courses:quiz_unit`. Reuse that: **all** tree/Prev/Next links target `courses:lesson_unit`.

**Existing `build_outline(course, user)` contract (must stay identical after Task 1):** returns a **list** of root node dicts, each `{"node", "children" (list), "required_total", "required_done", "additional_done", "is_unit" (bool), "completed" (bool)}`. Rollups exclude quiz units from `required_*`/`additional_done`. Pinned by `tests/test_courses_rollups.py::test_rollup_required_additional_and_quiz_excluded` and `::test_rollup_container_less_course`.

---

### Task 1: Shared pre-order walk substrate (`_walk_preorder`, `units_in_order`; refactor `build_outline` + `quiz_units_in_order`)

Introduce one private generator that yields every node in `(parent_id, order)` pre-order, and route `build_outline`, `quiz_units_in_order`, and a new `units_in_order` through it so their order **cannot** diverge.

**Files:**
- Modify: `courses/rollups.py` (the `build_outline` and `quiz_units_in_order` functions; add `_walk_preorder`, `units_in_order`)
- Test: `tests/test_courses_rollups.py` (add tests; existing tests must still pass)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `_walk_preorder(course) -> Iterator[ContentNode]` — every node, depth-first pre-order, one query.
  - `units_in_order(course) -> list[ContentNode]` — `_walk_preorder` filtered to `kind == UNIT` (lessons **and** quizzes).
  - `quiz_units_in_order(course) -> list[ContentNode]` — unchanged public behaviour, now `units_in_order` filtered to `unit_type == QUIZ`.
  - `build_outline(course, user) -> list[dict]` — unchanged contract.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_courses_rollups.py`:

```python
@pytest.mark.django_db
def test_units_in_order_preorder_mixed_lesson_and_quiz():
    from courses.rollups import units_in_order

    course = CourseFactory()
    # ch1 (order 0): lesson L1 (order 0), quiz Q1 (order 9)
    # ch2 (order 1): lesson L2 (order 0)
    ch1 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=0)
    ch2 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=1)
    l1 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch1, order=0)
    q1 = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch1, order=9)
    l2 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch2, order=0)

    units = units_in_order(course)
    # Pre-order across part/chapter boundaries; quizzes included; non-units excluded.
    assert [u.pk for u in units] == [l1.pk, q1.pk, l2.pk]


@pytest.mark.django_db
def test_units_in_order_nested_and_root_level_units():
    from courses.rollups import units_in_order

    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    sec = ContentNodeFactory(course=course, kind="section", parent=part, unit_type=None, order=0)
    deep = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=sec, order=0)
    # A root-level unit with no enclosing part, after the part.
    root_unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, order=1)

    assert [u.pk for u in units_in_order(course)] == [deep.pk, root_unit.pk]


@pytest.mark.django_db
def test_units_in_order_empty_course():
    from courses.rollups import units_in_order

    assert units_in_order(CourseFactory()) == []
```

(The existing `test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes` already pins quiz order; keep it.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_courses_rollups.py::test_units_in_order_preorder_mixed_lesson_and_quiz tests/test_courses_rollups.py::test_units_in_order_nested_and_root_level_units tests/test_courses_rollups.py::test_units_in_order_empty_course -v`
Expected: FAIL — `ImportError: cannot import name 'units_in_order'`.

- [ ] **Step 3: Implement `_walk_preorder`, `units_in_order`, and refactor**

In `courses/rollups.py`, add the generator near the top of the module body (after imports) and rewrite the two existing functions. Replace the **entire** body of `quiz_units_in_order` and `build_outline` with the versions below; add `_walk_preorder` and `units_in_order`.

> The `course.nodes.all()` reverse accessor and the `node_pk` URL kwarg used later are **not** assumptions: the current `build_outline`/`quiz_units_in_order` already iterate `course.nodes.all()`, and `courses/urls.py` routes `courses:lesson_unit` as `courses/<slug:slug>/u/<int:node_pk>/`. The refactor reuses both verbatim; if either has changed since, use the actual accessor/kwarg.

```python
def _walk_preorder(course):
    """Yield every ContentNode of `course` in depth-first pre-order.

    The SINGLE shared traversal. One query (course.nodes.all(), Meta.ordering =
    ["order", "pk"]); parent_id-grouped recursion (sibling `order` is only locally
    monotonic, so a flat scan of nodes.all() is NOT pre-order). build_outline folds
    this stream into its nested tree; units_in_order / quiz_units_in_order filter it.
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    def walk(parent_id):
        for node in children.get(parent_id, []):
            yield node
            yield from walk(node.pk)

    yield from walk(None)


def units_in_order(course):
    """Flat list of all leaf units (lessons AND quizzes) in outline pre-order.

    Quizzes have required_total == 0 but are still navigable units — they are NOT
    dropped here. Crosses chapter/part boundaries.
    """
    return [n for n in _walk_preorder(course) if n.kind == ContentNode.Kind.UNIT]


def quiz_units_in_order(course):
    """Quiz units (kind=UNIT, unit_type=QUIZ) in depth-first pre-order — units_in_order
    filtered to quizzes, so it cannot diverge from the shared walk."""
    return [n for n in units_in_order(course) if n.unit_type == ContentNode.UnitType.QUIZ]


def build_outline(course, user):
    """Return a nested list of node dicts with required/additional rollups.

    Folds the shared _walk_preorder stream into a tree (pre-order guarantees a parent
    is yielded before its children, so the parent dict exists when a child arrives),
    then a post-order pass sums the rollups. Two queries (nodes + the user's completed
    unit ids). `required` counts only obligatory lesson units; `additional_done` counts
    completed non-obligatory lesson units; quiz units are excluded from both.
    """
    completed = set()
    if user.is_authenticated:
        completed = set(
            UnitProgress.objects.filter(
                student=user, unit__course=course, completed=True
            ).values_list("unit_id", flat=True)
        )

    by_pk = {}
    roots = []
    for node in _walk_preorder(course):
        is_unit = node.kind == ContentNode.Kind.UNIT
        d = {
            "node": node,
            "children": [],
            "required_total": 0,
            "required_done": 0,
            "additional_done": 0,
            "is_unit": is_unit,
            "completed": is_unit and node.pk in completed,
        }
        by_pk[node.pk] = d
        if node.parent_id is None:
            roots.append(d)
        else:
            by_pk[node.parent_id]["children"].append(d)

    def rollup(d):
        node = d["node"]
        if d["is_unit"]:
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            d["required_total"] = 1 if (is_lesson and node.obligatory) else 0
            d["required_done"] = 1 if (d["required_total"] and node.pk in completed) else 0
            d["additional_done"] = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
        else:
            for k in d["children"]:
                rollup(k)
            d["required_total"] = sum(k["required_total"] for k in d["children"])
            d["required_done"] = sum(k["required_done"] for k in d["children"])
            d["additional_done"] = sum(k["additional_done"] for k in d["children"])

    for r in roots:
        rollup(r)
    return roots
```

Keep all existing imports (`ContentNode`, `UnitProgress`, etc.) — they are already imported in `rollups.py`.

> **Contract-fidelity check before replacing the body.** Read the current `build_outline` first and confirm the replacement is byte-for-byte equivalent in output: (a) the dict has **exactly these 7 keys** — `node`, `children`, `required_total`, `required_done`, `additional_done`, `is_unit`, `completed` — and no others; (b) the original sets `"completed"` to `node.kind == ContentNode.Kind.UNIT and node.pk in completed` (so containers are `completed=False`, which the refactor preserves via `is_unit and node.pk in completed`); (c) the original excludes quiz units from `required_*`/`additional_done`. The refactor below reproduces all three. Also confirm (d) the **completed-unit-ids source**: the current `build_outline` derives them via `set(UnitProgress.objects.filter(student=user, unit__course=course, completed=True).values_list("unit_id", flat=True))` — the refactor reuses this exact query. If the current code instead routes through a shared helper, reuse that helper rather than the literal filter, so completion can't silently drift. If the current code emits any extra key or computes container `completed` differently, match it instead of the version below — the "stays identical" contract (pinned by the existing rollups tests) is the gate.

- [ ] **Step 4: Run the new tests + the full rollups file**

Run: `uv run pytest tests/test_courses_rollups.py -v`
Expected: PASS — the three new tests pass AND every pre-existing test (including `test_rollup_required_additional_and_quiz_excluded`, `test_rollup_container_less_course`, `test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes`, and the `build_course_results` suite) still passes.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/rollups.py tests/test_courses_rollups.py
uv run ruff format --check courses/rollups.py tests/test_courses_rollups.py
git add courses/rollups.py tests/test_courses_rollups.py
git commit -m "feat(rollups): shared _walk_preorder + units_in_order; refactor build_outline/quiz_units_in_order onto it"
```

---

### Task 2: `build_unit_nav(course, user, current_node)` service

The pure navigation service. Returns the tree, Prev/Next neighbours (by `pk`), and part/course progress.

**Files:**
- Modify: `courses/rollups.py` (add `build_unit_nav` + two small private helpers)
- Test: `tests/test_courses_rollups.py`

**Interfaces:**
- Consumes: `build_outline` (Task 1). It does **not** call `units_in_order` — Prev/Next come from `_flatten_unit_leaves(tree)` over the already-computed `build_outline` result (one query, no second walk). The leaf order is guaranteed identical to `units_in_order` because both originate from `_walk_preorder`; do not wire an extra `units_in_order` call.
- Produces: `build_unit_nav(course, user, current_node) -> dict` with keys:
  - `"tree"` — the `build_outline` list (each dict carries `node`, `children`, `is_unit`, `completed`, rollups).
  - `"current_pk"` — `current_node.pk` (for the tree's active highlight).
  - `"prev"` / `"next"` — neighbouring `ContentNode` or `None`.
  - `"part_progress"` — `{"done": int, "total": int, "title": str}` or `None` (hidden when current unit has no enclosing top-level part, or that part has `required_total == 0`).
  - `"course_progress"` — `{"done": int, "total": int}` (template hides the hairline when `total == 0`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_courses_rollups.py`. The helpers below use `CourseFactory`, `ContentNodeFactory`, `UserFactory`, and `UnitProgressFactory` — all four are **already imported** at the top of that file (lines 12–19), so no new imports are needed. (If a future refactor removes them, import them locally as Tasks 3/4 do, so the red phase fails on the intended `ImportError: build_unit_nav`, not a `NameError`.)

```python
def _three_unit_course():
    """part 'P' > [L1 obligatory done, L2 obligatory, Q1 quiz]; returns (course, user, nodes...)."""
    course = CourseFactory()
    user = UserFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    l1 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=0, obligatory=True)
    l2 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=1, obligatory=True)
    q1 = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=part, order=2)
    UnitProgressFactory(student=user, unit=l1, completed=True)
    return course, user, part, l1, l2, q1


@pytest.mark.django_db
def test_build_unit_nav_prev_next_neighbours():
    from courses.rollups import build_unit_nav

    course, user, part, l1, l2, q1 = _three_unit_course()
    nav = build_unit_nav(course, user, l2)
    assert nav["prev"].pk == l1.pk
    assert nav["next"].pk == q1.pk  # quiz IS a navigable neighbour
    assert nav["current_pk"] == l2.pk


@pytest.mark.django_db
def test_build_unit_nav_first_and_last_have_no_neighbour():
    from courses.rollups import build_unit_nav

    course, user, part, l1, l2, q1 = _three_unit_course()
    first = build_unit_nav(course, user, l1)
    assert first["prev"] is None and first["next"].pk == l2.pk
    last = build_unit_nav(course, user, q1)
    assert last["next"] is None and last["prev"].pk == l2.pk


@pytest.mark.django_db
def test_build_unit_nav_prev_next_resolve_by_pk_for_independent_instance():
    from courses.models import ContentNode
    from courses.rollups import build_unit_nav

    course, user, part, l1, l2, q1 = _three_unit_course()
    # Fetch current_node from a DIFFERENT queryset than the walk builds (distinct instance).
    independent = ContentNode.objects.get(pk=l2.pk)
    nav = build_unit_nav(course, user, independent)
    assert nav["prev"].pk == l1.pk and nav["next"].pk == q1.pk


@pytest.mark.django_db
def test_build_unit_nav_part_and_course_progress():
    from courses.rollups import build_unit_nav

    course, user, part, l1, l2, q1 = _three_unit_course()
    nav = build_unit_nav(course, user, l2)
    # Part P: two obligatory lessons, one done; quiz excluded from required_*.
    assert nav["part_progress"] == {"done": 1, "total": 2, "title": part.title}
    # Course total == the one part's total (partition invariant).
    assert nav["course_progress"] == {"done": 1, "total": 2}


@pytest.mark.django_db
def test_build_unit_nav_depth1_unit_hides_part_chip():
    from courses.rollups import build_unit_nav

    course = CourseFactory()
    user = UserFactory()
    # Root-level lesson with NO enclosing part.
    u = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, order=0, obligatory=True)
    nav = build_unit_nav(course, user, u)
    assert nav["part_progress"] is None  # the course hairline already represents it
    assert nav["course_progress"] == {"done": 0, "total": 1}


@pytest.mark.django_db
def test_build_unit_nav_zero_required_part_hides_chip():
    from courses.rollups import build_unit_nav

    course = CourseFactory()
    user = UserFactory()
    # A part whose only unit is a quiz (required_total == 0).
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    q = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=part, order=0)
    nav = build_unit_nav(course, user, q)
    assert nav["part_progress"] is None
    # Quiz-only course → course required total 0 → hairline hidden by template.
    assert nav["course_progress"] == {"done": 0, "total": 0}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_courses_rollups.py -k build_unit_nav -v`
Expected: FAIL — `ImportError: cannot import name 'build_unit_nav'`.

- [ ] **Step 3: Implement `build_unit_nav` + helpers**

Append to `courses/rollups.py`:

```python
def _flatten_unit_leaves(tree):
    """The is_unit leaf dicts of a build_outline tree, in outline order (same order
    as units_in_order — both originate from _walk_preorder)."""
    leaves = []

    def collect(items):
        for d in items:
            if d["is_unit"]:
                leaves.append(d)
            else:
                collect(d["children"])

    collect(tree)
    return leaves


def _top_level_part(tree, current_pk):
    """The root dict whose subtree contains current_pk (the top-level ancestor), or
    None. If current_pk is itself a root, returns that root dict (its is_unit tells the
    caller it is a depth-1 unit with no enclosing part)."""

    def contains(d):
        return d["node"].pk == current_pk or any(contains(c) for c in d["children"])

    for root in tree:
        if contains(root):
            return root
    return None


def build_unit_nav(course, user, current_node):
    """Pure navigation context for a unit page (mirrors build_lesson_context's role:
    the single source both unit views call, so they cannot drift).

    Returns {tree, current_pk, prev, next, part_progress, course_progress}. Prev/Next
    are the immediate neighbours of current_node among the is_unit leaves of the
    already-computed build_outline tree, located by pk (the walk builds its own node
    instances, distinct from the view's current_node). No queries beyond build_outline's.
    """
    tree = build_outline(course, user)
    leaves = _flatten_unit_leaves(tree)
    units = [d["node"] for d in leaves]

    idx = next((i for i, n in enumerate(units) if n.pk == current_node.pk), None)
    prev_node = units[idx - 1] if (idx is not None and idx > 0) else None
    next_node = units[idx + 1] if (idx is not None and idx < len(units) - 1) else None

    course_progress = {
        "done": sum(d["required_done"] for d in tree),
        "total": sum(d["required_total"] for d in tree),
    }

    part_progress = None
    top = _top_level_part(tree, current_node.pk)
    if top is not None and not top["is_unit"] and top["required_total"] > 0:
        part_progress = {
            "done": top["required_done"],
            "total": top["required_total"],
            "title": top["node"].title,
        }

    return {
        "tree": tree,
        "current_pk": current_node.pk,
        "prev": prev_node,
        "next": next_node,
        "part_progress": part_progress,
        "course_progress": course_progress,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_courses_rollups.py -k build_unit_nav -v`
Expected: PASS (all six).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/rollups.py tests/test_courses_rollups.py
uv run ruff format --check courses/rollups.py tests/test_courses_rollups.py
git add courses/rollups.py tests/test_courses_rollups.py
git commit -m "feat(rollups): build_unit_nav — tree + prev/next + part/course progress"
```

---

### Task 3: Wire `build_unit_nav` into both unit views (incl. the no-JS re-render paths)

Every view that renders `lesson_unit.html` or `quiz_unit.html` must add `unit_nav` to its context — otherwise, once Task 4 makes those templates unconditionally `{% include "courses/_unit_shell.html" %}`, a render site missing `unit_nav` paints an **empty** tree / no Prev-Next / no progress bar (a no-JS regression), and a site missing `course` in context raises `NoReverseMatch` on the tree/footer `{% url … node_pk=… %}` calls.

**First, pin the render-site set** (do not trust this list blindly — confirm it): run `grep -rn 'lesson_unit.html\|quiz_unit.html' --include='*.py'`. At plan time this returns **exactly four** sites, all in `courses/views.py` (lines 221, 317, 446, 480) — and no `TemplateResponse`/`render_to_string` of either template elsewhere (the quiz-review/force-submit views of 3c-i render `review_*`/`quiz_results.html`, not these). If the grep returns **more** than these four, every additional site must also get `unit_nav` (and have `course` in context). The four expected sites:
- `lesson_unit` (GET) — `courses/views.py:221`
- `quiz_unit` (GET) — `courses/views.py:446`
- `check_answer` (no-JS lesson feedback branch) — `courses/views.py:317`, re-renders `courses/lesson_unit.html`
- `_quiz_render_feedback` (no-JS quiz feedback branch) — `courses/views.py:480`, re-renders `courses/quiz_unit.html`

**Files:**
- Modify: `courses/views.py` (`lesson_unit`, `quiz_unit`, `check_answer`, `_quiz_render_feedback`)
- Test: `tests/test_courses_views.py`

**Interfaces:**
- Consumes: `build_unit_nav` (Task 2).
- Produces: `unit_nav` key in all four render sites' template context.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_courses_views.py` (use the factories/login helpers already imported there; if a helper to enrol + log in a student isn't present, mirror the existing view-test pattern in that file). Tests:

```python
@pytest.mark.django_db
def test_lesson_unit_context_has_unit_nav(client):
    from courses.models import ContentNode
    from tests.factories import ContentNodeFactory, CourseFactory, EnrollmentFactory, UserFactory, TEST_PASSWORD, make_verified_user

    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    l1 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=0, obligatory=True)
    l2 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=1, obligatory=True)
    user = make_verified_user(username="navstu", email="navstu@t.example.com", password=TEST_PASSWORD)
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    resp = client.get(f"/courses/{course.slug}/u/{l1.pk}/")
    assert resp.status_code == 200
    nav = resp.context["unit_nav"]
    assert nav["current_pk"] == l1.pk
    assert nav["next"].pk == l2.pk
    assert nav["prev"] is None
```

Add a parallel `test_quiz_unit_context_has_unit_nav` that seeds a quiz unit using `make_quiz_unit` from `tests/factories.py` (signature `make_quiz_unit(course=None, **kw)` — returns a `ContentNode` with `kind="unit", unit_type="quiz"`; pass `course=course, parent=part`), force-logs an enrolled student, GETs `/courses/<slug>/u/<pk>/quiz/`, asserts `resp.context["unit_nav"]["current_pk"] == quiz_unit.pk`.

Also add a **no-JS re-render** test pinning C1 — POST to `check_answer` without the fragment header and assert the shell renders with nav:

```python
@pytest.mark.django_db
def test_check_answer_nojs_rerender_includes_unit_nav(client):
    from courses.models import Element, ShortTextQuestionElement
    from tests.factories import ContentNodeFactory, CourseFactory, EnrollmentFactory, TEST_PASSWORD, make_verified_user

    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    l1 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=0, obligatory=True)
    l2 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=1, obligatory=True)
    q = ShortTextQuestionElement.objects.create(stem="2+2?", accepted="4", marking_mode="A", max_marks=1)
    el = Element.objects.create(unit=l1, content_object=q)
    user = make_verified_user(username="njs", email="njs@t.example.com", password=TEST_PASSWORD)
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    # No X-Requested-With header → full-page no-JS re-render. The check_answer route is
    # `courses/<slug>/u/<node_pk>/q/<element_pk>/check/` (name "courses:check_answer") — confirm
    # in courses/urls.py, or build it with reverse("courses:check_answer", ...) instead of hardcoding.
    resp = client.post(f"/courses/{course.slug}/u/{l1.pk}/q/{el.pk}/check/", {"answer": "5"})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "unit-shell" in html and "unit-tree" in html and "unit-foot__row" in html
    assert resp.context["unit_nav"]["current_pk"] == l1.pk
```

> Confirm the exact factory/helper import paths and the `ShortTextQuestionElement` field names against the top of `tests/test_courses_views.py` / `tests/test_courses_rollups.py::_quiz_with_questions` (which builds a `ShortTextQuestionElement` the same way) and reuse what's there rather than re-importing duplicates. The `marking_mode="A"` + `max_marks=1` values mirror that helper.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_courses_views.py -k unit_nav -v`
Expected: FAIL — `KeyError: 'unit_nav'` (the views don't add it yet).

- [ ] **Step 3: Implement — add `build_unit_nav` to both contexts**

In `courses/views.py`, ensure `build_unit_nav` is imported from `courses.rollups` (there is already a `from courses.rollups import …` line — add it there; if not, add `from courses.rollups import build_unit_nav`).

In `lesson_unit`, after `ctx = build_lesson_context(node, request.user)` and before/within the `ctx.update(...)`:

```python
    ctx["unit_nav"] = build_unit_nav(course, request.user, node)
```

In `quiz_unit`, after `ctx = build_quiz_context(node, request.user)` and before the render:

```python
    ctx["unit_nav"] = build_unit_nav(course, request.user, node)
```

(Place it before the `SUBMITTED → redirect` check is fine — but to avoid a wasted call on the redirect path, add it just before `return render(...)`.)

> **Confirm the template vars are present in all four contexts first.** The shell/tree/footer read `course` (for `{% url … slug=course.slug %}` — a missing `course` is a `NoReverseMatch`, not a silent blank) and the article partials read `unit` + `elements`. All three come from `build_lesson_context` / `build_quiz_context` (lesson ctx has `course`/`unit`/`elements`; quiz ctx has `course`/`unit`/`elements`/`render_states`), which every one of the four sites already calls — so adding `unit_nav` is sufficient. Verify this by reading each `build_*_context` return dict before relying on it; if `course` is somehow absent at a site, add `ctx["course"] = node.course` there too. Pass `node.course` (not a bare `course`) into `build_unit_nav` at the no-JS sites so it doesn't depend on a local name.

In `check_answer` (the no-JS branch, after `ctx = build_lesson_context(node, request.user)` at views.py:308), add — `node` and `request.user` are local; `node.course` gives the course:

```python
    ctx["unit_nav"] = build_unit_nav(node.course, request.user, node)
```

In `_quiz_render_feedback` (the no-JS branch, after `ctx = build_quiz_context(node, request.user)` at views.py:472), add:

```python
    ctx["unit_nav"] = build_unit_nav(node.course, request.user, node)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_courses_views.py -k unit_nav -v`
Expected: PASS (both).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views.py tests/test_courses_views.py
uv run ruff format --check courses/views.py tests/test_courses_views.py
git add courses/views.py tests/test_courses_views.py
git commit -m "feat(views): expose unit_nav context on lesson_unit and quiz_unit"
```

---

### Task 4: Unit shell + tree + footer partials and CSS (no-JS baseline)

The shared two-column structure, the recursive tree, and the footer bar — fully functional with JS off (links work; tree visible; footer Prev/Next + progress render). Collapse/auto-scroll/drawer are JS enhancements added in Tasks 5–6.

**Files:**
- Create: `templates/courses/_unit_shell.html`
- Create: `templates/courses/_unit_tree.html`
- Create: `templates/courses/_unit_tree_node.html`
- Create: `templates/courses/_unit_footer.html`
- Create: `templates/courses/_lesson_article.html`
- Create: `templates/courses/_quiz_article.html`
- Modify: `templates/courses/lesson_unit.html`
- Modify: `templates/courses/quiz_unit.html`
- Modify: `courses/static/courses/css/courses.css` (append the `.unit-shell` block)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ recompile `.mo`)
- Test: `tests/test_unit_nav_render.py` (new)

**Interfaces:**
- Consumes: `unit_nav` context (Task 3); `course`, `unit`, `elements`, and all existing lesson/quiz context.
- Produces: the `.unit-shell` / `.unit-tree` / `.unit-foot` class vocabulary that batch 3 reuses; the `_unit_shell.html` partial taking a `content_partial` variable.

- [ ] **Step 1: Write the failing render tests**

Create `tests/test_unit_nav_render.py`:

```python
import pytest

from tests.factories import (
    ContentNodeFactory,
    CourseFactory,
    EnrollmentFactory,
    TEST_PASSWORD,
    UnitProgressFactory,
    make_verified_user,
)


def _course_with_part():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None, order=0)
    l1 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=0, obligatory=True)
    l2 = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part, order=1, obligatory=True)
    return course, part, l1, l2


@pytest.mark.django_db
def test_unit_shell_wraps_lesson_article_and_keeps_seen_hook(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(username="r1", email="r1@t.example.com", password=TEST_PASSWORD)
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=l1, completed=True)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l2.pk}/").content.decode()
    # Shell wraps the page.
    assert "unit-shell" in html
    # The seen-tracking article is intact (progress.js depends on it).
    assert 'class="lesson"' in html and "data-seen-url=" in html
    # Tree landmark + current highlight + completed badge.
    assert 'aria-label' in html and "unit-tree" in html
    assert 'aria-current="page"' in html
    assert "badge--done" in html  # l1 completed → ✓ in the tree
    # Footer Prev shows the neighbour title — scope to the footer, since l1.title also
    # appears in the tree on every page (a bare `l1.title in html` would pass even with a
    # broken footer). Parse the footer region and assert the prev navtitle.
    import re
    foot = re.search(r'<footer class="unit-foot".*?</footer>', html, re.S).group(0)
    assert "unit-foot__nav" in foot and l1.title in foot  # prev neighbour in the footer
    # Course hairline present (course has required units).
    assert "unit-foot__course" in html


@pytest.mark.django_db
def test_unit_shell_first_unit_disables_prev(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(username="r2", email="r2@t.example.com", password=TEST_PASSWORD)
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l1.pk}/").content.decode()
    # Disabled prev is a non-focusable span, not an <a>.
    assert "unit-foot__nav--disabled" in html


@pytest.mark.django_db
def test_unit_shell_part_chip_hidden_for_root_unit(client):
    course = CourseFactory()
    u = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, order=0, obligatory=True)
    user = make_verified_user(username="r3", email="r3@t.example.com", password=TEST_PASSWORD)
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{u.pk}/").content.decode()
    assert "unit-foot__part" not in html  # no enclosing part → chip hidden
    assert "unit-foot__course" in html    # hairline still shown (course has 1 required)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_unit_nav_render.py -v`
Expected: FAIL — assertions about `unit-shell`/`unit-tree`/`unit-foot__*` not present (templates not yet changed).

- [ ] **Step 3: Create the partials**

`templates/courses/_unit_tree_node.html` (recursive):

```django
{% load i18n %}
<li class="unit-tree__node unit-tree__node--{{ item.node.kind }}">
  {% if item.is_unit %}
    {% comment %}Node titles are author content → lang=course.language. All units link to
       lesson_unit; that view redirects a quiz node to quiz_unit (existing pattern).{% endcomment %}
    <a class="unit-tree__unit{% if item.completed %} is-done{% endif %}{% if item.node.pk == current_pk %} is-active{% endif %}"
       lang="{{ course.language }}"
       href="{% url 'courses:lesson_unit' slug=course.slug node_pk=item.node.pk %}"
       {% if item.node.pk == current_pk %}aria-current="page"{% endif %}>
      {% if item.completed %}<span class="unit-tree__check badge badge--done" aria-label="{% trans 'Completed' %}">✓</span>{% endif %}
      <span class="unit-tree__label">{{ item.node.title }}</span>
    </a>
  {% else %}
    <div class="unit-tree__head" lang="{{ course.language }}">{{ item.node.title }}</div>
    {% if item.children %}
      <ul class="unit-tree__children">
        {% for child in item.children %}{% include "courses/_unit_tree_node.html" with item=child course=course current_pk=current_pk %}{% endfor %}
      </ul>
    {% endif %}
  {% endif %}
</li>
```

`templates/courses/_unit_tree.html`:

```django
{% load i18n %}
<nav class="unit-tree" aria-label="{% trans 'Course contents' %}" data-unit-tree>
  <div class="unit-tree__bar">
    <span class="unit-tree__heading">{% trans "Contents" %}</span>
    <button type="button" class="unit-tree__toggle" data-unit-tree-toggle
            aria-label="{% trans 'Collapse contents' %}" aria-expanded="true"
            data-label-collapse="{% trans 'Collapse contents' %}"
            data-label-expand="{% trans 'Expand contents' %}">‹</button>
  </div>
  <ul class="unit-tree__list" data-unit-tree-list>
    {% for item in unit_nav.tree %}{% include "courses/_unit_tree_node.html" with item=item course=course current_pk=unit_nav.current_pk %}{% endfor %}
  </ul>
</nav>
```

`templates/courses/_unit_footer.html`:

```django
{% load i18n %}
<footer class="unit-foot">
  {% if unit_nav.course_progress.total %}
    <div class="unit-foot__course" title="{% blocktrans with done=unit_nav.course_progress.done total=unit_nav.course_progress.total %}Course progress {{ done }} of {{ total }}{% endblocktrans %}">
      <i style="width: {% widthratio unit_nav.course_progress.done unit_nav.course_progress.total 100 %}%"></i>
    </div>
  {% endif %}
  <div class="unit-foot__row">
    {% if unit_nav.prev %}
      <a class="unit-foot__nav" href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit_nav.prev.pk %}">
        <span class="unit-foot__chev">‹</span>
        <span class="unit-foot__navtext">
          <span class="unit-foot__navmeta">{% trans "Previous" %}</span>
          <span class="unit-foot__navtitle" lang="{{ course.language }}">{{ unit_nav.prev.title }}</span>
        </span>
      </a>
    {% else %}
      <span class="unit-foot__nav unit-foot__nav--disabled" aria-disabled="true">
        <span class="unit-foot__chev">‹</span>
        <span class="unit-foot__navtext"><span class="unit-foot__navmeta">{% trans "Previous" %}</span></span>
      </span>
    {% endif %}

    {% if unit_nav.part_progress %}
      <div class="unit-foot__mid">
        {% comment %}title= surfaces the part NAME on hover so the computed part_progress.title
           has a consumer; the visible chip stays "PART d/t" per the accepted mockup.{% endcomment %}
        <span class="unit-foot__part" title="{{ unit_nav.part_progress.title }}">
          {% trans "Part" %} {{ unit_nav.part_progress.done }}/{{ unit_nav.part_progress.total }}
          <span class="unit-foot__bar"><i style="width: {% widthratio unit_nav.part_progress.done unit_nav.part_progress.total 100 %}%"></i></span>
        </span>
      </div>
    {% else %}
      <div class="unit-foot__mid"></div>
    {% endif %}

    {% if unit_nav.next %}
      <a class="unit-foot__nav unit-foot__nav--primary" href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit_nav.next.pk %}">
        <span class="unit-foot__navtext unit-foot__navtext--right">
          <span class="unit-foot__navmeta">{% trans "Next" %}</span>
          <span class="unit-foot__navtitle" lang="{{ course.language }}">{{ unit_nav.next.title }}</span>
        </span>
        <span class="unit-foot__chev">›</span>
      </a>
    {% else %}
      <span class="unit-foot__nav unit-foot__nav--primary unit-foot__nav--disabled" aria-disabled="true">
        <span class="unit-foot__navtext unit-foot__navtext--right"><span class="unit-foot__navmeta">{% trans "Next" %}</span></span>
        <span class="unit-foot__chev">›</span>
      </span>
    {% endif %}
  </div>
</footer>
```

`templates/courses/_unit_shell.html` (only `i18n` is needed — the shell has no `{% static %}`):

```django
{% load i18n %}
<div class="unit-shell" data-unit-shell>
  {% include "courses/_unit_tree.html" %}
  <div class="unit-shell__main">
    {% include content_partial %}
    {% include "courses/_unit_footer.html" %}
  </div>

  {% comment %}Mobile drawer trigger + drawer; behaviour wired by unit_nav.js (Task 6).
     With JS off the button is inert and the inline tree above is used.{% endcomment %}
  <button type="button" class="unit-tree-fab" data-unit-drawer-open
          aria-label="{% trans 'Open course contents' %}" aria-haspopup="dialog" aria-expanded="false" hidden>☰</button>
  <div class="unit-drawer" data-unit-drawer role="dialog" aria-modal="true"
       aria-label="{% trans 'Course contents' %}" hidden>
    <div class="unit-drawer__scrim" data-unit-drawer-close></div>
    <div class="unit-drawer__panel">
      <div class="unit-drawer__bar">
        <span class="unit-tree__heading">{% trans "Contents" %}</span>
        <button type="button" class="unit-drawer__close" data-unit-drawer-close
                aria-label="{% trans 'Close' %}">✕</button>
      </div>
      <ul class="unit-tree__list unit-drawer__list" data-unit-drawer-list>
        {% for item in unit_nav.tree %}{% include "courses/_unit_tree_node.html" with item=item course=course current_pk=unit_nav.current_pk %}{% endfor %}
      </ul>
    </div>
  </div>
</div>
```

> The active unit's `aria-current="page"` is emitted in **both** the inline tree and the drawer copy, but this is benign: the inline tree is `display:none` ≤640px and the drawer is `hidden`/`display:none` until opened, and `display:none`/`[hidden]` removes a subtree from the accessibility tree — so at most **one** `aria-current` is ever exposed to assistive tech. No de-duplication needed.

> The drawer markup is added here so Task 6 only adds JS + CSS, not template churn. Both the FAB and the drawer ship with the `hidden` attribute so they are inert and invisible with **JS off** (a no-JS mobile user keeps the working footer Prev/Next; the JS-only drawer is simply absent rather than a dead button). Task 6's `unit_nav.js` **removes `hidden` from the FAB on init** (progressive enhancement), and the FAB's mobile CSS (Task 4 Step 6) gates on `:not([hidden])` so the cascade can't override the `hidden` attribute. Do **not** rely on `display:flex` beating `[hidden]` — gate explicitly.

- [ ] **Step 4: Extract the article bodies into partials**

`templates/courses/_lesson_article.html` — move the `<article class="lesson" …>…</article>` block (lines 9–31 of the current `lesson_unit.html`) **verbatim** into this file. Prefix it with the **exact** `{% load %}` line the source template declares — at plan time `lesson_unit.html:2` is `{% load i18n static courses_extras %}`, and the article body uses `render_element` (from `courses_extras`) + `{% trans %}`/`{% url %}`/`{% widthratio %}` (builtins) + `static`, all covered. If the source's `{% load %}` line has changed, copy whatever it currently declares.

`templates/courses/_quiz_article.html` — move the `<article class="quiz" …>…</article>` block (lines 9–29 of the current `quiz_unit.html`) **verbatim** into this file. Same rule: copy the exact `{% load %}` line from `quiz_unit.html:2` (currently `{% load i18n static courses_extras %}`). The quiz body additionally uses the `dictkey` filter and `quiz_answer_url` filter — confirm both are provided by `courses_extras` (they are used in the current `quiz_unit.html`, so the same single `courses_extras` load covers them).

- [ ] **Step 5: Point the unit templates at the shell**

Confirm the block name first: both `lesson_unit.html` and `quiz_unit.html` currently wrap their article in `{% block content %}…{% endblock %}` (line 8). If a template uses a differently-named block, target that name. In `templates/courses/lesson_unit.html`, replace the `{% block content %}…{% endblock %}` body (the article) with:

```django
{% block content %}{% include "courses/_unit_shell.html" with content_partial="courses/_lesson_article.html" %}{% endblock %}
```

In `templates/courses/quiz_unit.html`, replace its `{% block content %}…{% endblock %}` body with:

```django
{% block content %}{% include "courses/_unit_shell.html" with content_partial="courses/_quiz_article.html" %}{% endblock %}
```

Leave both templates' `extra_css`/`extra_js` blocks unchanged (Tasks 5–6 add the unit_nav.js/CSS hooks). `courses.css` is already linked in `extra_css`.

- [ ] **Step 6: Append the CSS**

> **First reconcile the existing `.lesson` / `.quiz` rules.** Grep `core/static/core/css/app.css` and `courses/static/courses/css/courses.css` for `.lesson` and `.quiz` selectors — they likely already set `max-width`, centering (`margin: 0 auto`), and padding. The shell now becomes their containing block, so a pre-existing `max-width`/auto-centre on `.lesson`/`.quiz` would fight the new `.unit-shell__main` flex column (lost centering or doubled padding). If found: move the centering to `.unit-shell` (which already has `max-width: 72rem; margin: 0 auto`) and drop or neutralise the redundant `max-width`/`margin` on `.lesson`/`.quiz` inside the shell context (e.g. `.unit-shell__main > .lesson { max-width: none; margin: 0; }`). Do NOT defer this to the Task 7 screenshot pass.

Append to `courses/static/courses/css/courses.css` (uses existing tokens from `tokens.css`):

```css
/* ── Unit shell (batch 2: unit navigation; reused by batch 3 review roster) ── */
.unit-shell { display: flex; align-items: flex-start; gap: 0; max-width: 72rem; margin: 0 auto; }
.unit-shell__main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
.unit-shell__main > .lesson,
.unit-shell__main > .quiz { padding: 1.25rem 1.5rem; }

.unit-tree { flex: 0 0 14rem; align-self: stretch; background: var(--surface-sunken);
  border-right: 1px solid var(--border-default); position: sticky; top: 0;
  max-height: 100vh; overflow-y: auto; font-size: .82rem; }
.unit-tree__bar { display: flex; align-items: center; gap: .5rem; padding: .55rem .65rem;
  border-bottom: 1px solid var(--border-subtle); position: sticky; top: 0;
  background: var(--surface-sunken); }
.unit-tree__heading { font-size: .68rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--text-tertiary); flex: 1; }
.unit-tree__toggle { width: 1.4rem; height: 1.4rem; border: 1px solid var(--border-default);
  border-radius: .4rem; background: var(--surface-raised); color: var(--text-tertiary);
  cursor: pointer; line-height: 1; }
.unit-tree__toggle:hover { color: var(--text-secondary); }
.unit-tree__list, .unit-tree__children { list-style: none; margin: 0; padding: 0; }
.unit-tree__list { padding: .4rem .35rem .8rem; }
.unit-tree__children { padding-left: .55rem; }
.unit-tree__head { font-weight: 700; color: var(--text-primary); margin: .5rem .35rem .15rem; }
.unit-tree__node--section > .unit-tree__head,
.unit-tree__node--chapter > .unit-tree__head { font-size: .64rem; font-weight: 700;
  letter-spacing: .05em; text-transform: uppercase; color: var(--text-tertiary); }
.unit-tree__unit { display: flex; align-items: center; gap: .4rem; padding: .3rem .5rem;
  margin-left: .35rem; border-radius: .4rem; color: var(--text-secondary);
  border-left: 1px solid var(--border-subtle); text-decoration: none; }
.unit-tree__unit:hover { background: var(--surface-raised); color: var(--text-primary); }
.unit-tree__unit.is-done { color: var(--text-tertiary); }
.unit-tree__unit.is-active { background: var(--primary-subtle); color: var(--primary);
  font-weight: 600; border-left: 2px solid var(--primary); }
.unit-tree__check { font-size: .72rem; }
.unit-tree__label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Footer */
.unit-foot { border-top: 1px solid var(--border-default); background: var(--surface-raised); }
.unit-foot__course { height: 3px; background: var(--border-subtle); }
.unit-foot__course > i { display: block; height: 100%; background: var(--primary); }
.unit-foot__row { display: flex; align-items: center; gap: .9rem; padding: .7rem 1.1rem; }
.unit-foot__mid { flex: 1; display: flex; justify-content: center; }
.unit-foot__nav { display: inline-flex; align-items: center; gap: .4rem; font-size: .78rem;
  font-weight: 600; padding: .45rem .75rem; border-radius: .5rem;
  border: 1px solid var(--border-strong); color: var(--text-primary);
  background: var(--surface-raised); text-decoration: none; max-width: 42%; }
.unit-foot__nav:hover { border-color: var(--primary); }
.unit-foot__nav--primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.unit-foot__nav--primary:hover { filter: brightness(1.05); border-color: var(--primary); }
.unit-foot__nav--disabled { opacity: .45; pointer-events: none; }
.unit-foot__navtext { min-width: 0; }
.unit-foot__navtext--right { text-align: right; }
.unit-foot__navmeta { display: block; font-size: .62rem; font-weight: 500; color: var(--text-tertiary); }
.unit-foot__nav--primary .unit-foot__navmeta { color: #cfe3e0; }
.unit-foot__navtitle { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unit-foot__part { display: inline-flex; align-items: center; gap: .5rem; font-size: .66rem;
  color: var(--text-tertiary); font-variant-numeric: tabular-nums; letter-spacing: .04em;
  text-transform: uppercase; }
.unit-foot__bar { width: 4.6rem; height: 6px; border-radius: 9999px;
  background: var(--border-subtle); overflow: hidden; }
.unit-foot__bar > i { display: block; height: 100%; background: var(--accent); border-radius: 9999px; }

/* Mobile FAB + drawer — wired by unit_nav.js (Task 6). Hidden by default; shown ≤640px. */
.unit-tree-fab { display: none; }
.unit-drawer { display: none; }

@media (max-width: 640px) {
  .unit-shell { display: block; }
  .unit-tree { display: none; }  /* inline tree hidden on mobile; drawer holds the tree */
  .unit-shell__main > .lesson,
  .unit-shell__main > .quiz { padding: 1rem 1rem; }
  /* Gate on :not([hidden]) so the cascade never overrides the hidden attribute —
     the FAB stays invisible with JS off; unit_nav.js removes [hidden] on init. */
  .unit-tree-fab[data-unit-drawer-open]:not([hidden]) { display: flex; align-items: center;
    justify-content: center; position: fixed; right: 1rem; bottom: 1rem; z-index: 40;
    width: 3rem; height: 3rem; border-radius: 9999px; border: none; cursor: pointer;
    background: var(--primary); color: #fff; font-size: 1.2rem;
    box-shadow: var(--shadow-md); }
  .unit-drawer:not([hidden]) { display: block; position: fixed; inset: 0; z-index: 50; }
  .unit-drawer__scrim { position: absolute; inset: 0; background: rgba(30,28,24,.45); }
  .unit-drawer__panel { position: absolute; left: 0; right: 0; bottom: 0;
    max-height: 80vh; overflow-y: auto; background: var(--surface-raised);
    border-top-left-radius: .9rem; border-top-right-radius: .9rem;
    box-shadow: var(--shadow-md); }
  .unit-drawer__bar { display: flex; align-items: center; gap: .5rem; padding: .7rem .9rem;
    border-bottom: 1px solid var(--border-subtle); position: sticky; top: 0;
    background: var(--surface-raised); }
  .unit-drawer__close { margin-left: auto; border: none; background: transparent;
    font-size: 1rem; color: var(--text-tertiary); cursor: pointer; }
  .unit-drawer__list { padding: .5rem .5rem 1.2rem; }
}

@media (prefers-reduced-motion: reduce) {
  .unit-foot__nav, .unit-tree-fab { transition: none; }
}
```

> Verify these token names exist in `core/static/core/css/tokens.css` (`--primary`, `--primary-subtle`, `--accent`, `--surface-sunken`, `--surface-raised`, `--border-subtle`/`--default`/`--strong`, `--text-primary`/`--secondary`/`--tertiary`, `--shadow-md`). They are used by the accepted mockups and batch-1 CSS. If a name differs, use the actual token — do not invent.

- [ ] **Step 7: i18n — Polish translations**

Run `uv run python manage.py makemessages -l pl`, then in `locale/pl/LC_MESSAGES/django.po` set (clearing any `#, fuzzy` flag on these, and verifying no mis-guess):

```
msgid "Course contents"  →  msgstr "Spis treści kursu"
msgid "Contents"         →  msgstr "Spis treści"
msgid "Collapse contents"→  msgstr "Zwiń spis treści"
msgid "Expand contents"  →  msgstr "Rozwiń spis treści"
msgid "Open course contents" → msgstr "Otwórz spis treści kursu"
msgid "Close"            →  msgstr "Zamknij"
msgid "Previous"         →  msgstr "Poprzednia"
msgid "Next"             →  msgstr "Następna"
msgid "Part"             →  msgstr "Część"
```

`msgid "Completed"` already has a translation (used by the outline) — leave it. For the `blocktrans` tooltip, `makemessages` emits the variables as `%(name)s` (NOT `{{ }}`), so the generated entry is `msgid "Course progress %(done)s of %(total)s"` and the translation must use the **same** placeholders: `msgstr "Postęp kursu %(done)s z %(total)s"`. (`compilemessages` errors if the `msgstr` placeholders don't match the `msgid`, and a literal `{{ done }}` would render verbatim.) Then `uv run python manage.py compilemessages`.

> **Watch for shared msgids.** Short strings like `"Next"`, `"Previous"`, `"Close"`, `"Contents"` may already exist in `django.po` from other features (pagination, modals). `makemessages` merges all usages under one msgid — so if an entry already exists, do **not** blindly overwrite its `msgstr` (you could change unrelated UI or inherit a translation whose gender/sense is wrong here). For each msgid above: if it is **new**, add the translation; if it **pre-exists** and the existing translation reads correctly in this nav context, reuse it (no edit); if it pre-exists but conflicts in sense (e.g. "Next" as a wizard button vs. "next unit", or a masculine form where the unit is feminine), disambiguate this template's usage with `{% trans "Next" context "unit navigation" %}` (`pgettext`) and translate the new context-keyed entry rather than touching the shared one. The `"Previous"`/`"Next"` PL forms above (`Poprzednia`/`Następna`) are the feminine "unit" sense — verify they don't clobber a differently-gendered existing entry.

- [ ] **Step 8: Run the render tests + a broad smoke**

Run: `uv run pytest tests/test_unit_nav_render.py tests/test_consumption_pages.py -v`
Expected: PASS (new render tests green; the batch-1 consumption-page tests still render).

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff check tests/test_unit_nav_render.py
uv run ruff format --check tests/test_unit_nav_render.py
git add templates/courses/_unit_shell.html templates/courses/_unit_tree.html templates/courses/_unit_tree_node.html templates/courses/_unit_footer.html templates/courses/_lesson_article.html templates/courses/_quiz_article.html templates/courses/lesson_unit.html templates/courses/quiz_unit.html courses/static/courses/css/courses.css locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_unit_nav_render.py
git commit -m "feat(unit-nav): two-column unit shell — tree + footer progress partials + CSS (no-JS baseline)"
```

---

### Task 5: Desktop collapse rail (pre-paint restore + toggle) + auto-scroll to active unit

The desktop `‹` toggle collapses the tree to a rail; the choice persists in `localStorage` and restores before paint via a new inline script on `<html>`. The active unit auto-scrolls into view when the tree is expanded.

**Files:**
- Modify: `templates/base.html` (add the pre-paint collapse script in `<head>`, after the theme script)
- Create: `courses/static/courses/js/unit_nav.js`
- Modify: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html` (load `unit_nav.js` in `extra_js`)
- Modify: `courses/static/courses/css/courses.css` (collapsed-rail state scoped from `<html>`)
- Test: `tests/test_e2e_unit_nav.py` (new; e2e)

**Interfaces:**
- Consumes: the `data-unit-tree-toggle`, `data-unit-tree`, `.is-active` hooks from Task 4.
- Produces: `localStorage` key `libli_unit_tree_collapsed` ("1" = collapsed); `<html class="unit-tree-collapsed">` state.

- [ ] **Step 1: Write the failing e2e tests**

Create `tests/test_e2e_unit_nav.py`, mirroring the `tests/test_e2e_quiz.py` harness (the `_allow_async_unsafe` fixture, `_login`, `make_verified_user`, `pytestmark = pytest.mark.e2e`, ORM seeding). Seed a course with a part and ≥2 lesson units, enrol the student. Tests:

```python
def test_desktop_tree_collapse_persists(page, live_server, ...):
    # seed + login + goto lesson unit URL
    page.goto(unit_url)
    assert page.locator("[data-unit-tree]").is_visible()
    page.locator("[data-unit-tree-toggle]").click()
    # collapsed class lands on <html>
    assert "unit-tree-collapsed" in page.locator("html").get_attribute("class")
    # reload → still collapsed (restored before paint, no flash)
    page.reload()
    assert "unit-tree-collapsed" in (page.locator("html").get_attribute("class") or "")
    # toggle back → expanded + persisted
    page.locator("[data-unit-tree-toggle]").click()
    page.reload()
    assert "unit-tree-collapsed" not in (page.locator("html").get_attribute("class") or "")


def test_active_unit_scrolled_into_view(page, live_server, ...):
    # Seed MANY units so the active one is below the fold in the tree; open a late unit.
    page.goto(late_unit_url)
    # SCOPE to the inline tree: the drawer renders the SAME tree (a second .is-active node),
    # so a bare ".unit-tree__unit.is-active" matches TWO elements → count()!=1 and a
    # Playwright strict-mode violation on bounding_box(). [data-unit-tree] is the inline nav.
    active = page.locator("[data-unit-tree] .unit-tree__unit.is-active")
    assert active.count() == 1
    # The auto-scroll fired: the tree's scroll container is scrolled down (a NOT-scrolled
    # tree has scrollTop == 0 with the active item below the fold), AND the active link
    # sits within the tree container's visible viewport (top/bottom containment).
    # NOTE: the JS uses behavior:"smooth" unless reduced-motion; Playwright does NOT emulate
    # reduced-motion by default, so the scroll is ANIMATED — reading scrollTop synchronously
    # can observe 0 mid-animation (flaky). Build this test's context (or page) with
    # reduced_motion="reduce" so the JS takes the instant "auto" branch, AND poll rather
    # than read once:
    tree = page.locator("[data-unit-tree]")
    tree_handle = tree.element_handle()
    page.wait_for_function("el => el.scrollTop > 0", arg=tree_handle)
    tbox = tree.bounding_box()
    abox = active.bounding_box()
    assert tbox is not None and abox is not None
    assert abox["y"] >= tbox["y"] and abox["y"] + abox["height"] <= tbox["y"] + tbox["height"]
```

> Use real gestures (`.click()`, `.reload()`), never `page.evaluate` to set the class (reading `scrollTop`/bounding boxes for assertions is fine — that's observation, not driving the UI). Provide a seed helper in the test file (build via ORM like `_seed_quiz` in `test_e2e_quiz.py`). **Build the auto-scroll test's context with `reduced_motion="reduce"`** (`browser.new_context(reduced_motion="reduce")` → `ctx.new_page()`, and `ctx.close()` at the end) so the JS takes the instant `"auto"` scroll branch and the `wait_for_function` poll settles deterministically. For the auto-scroll test, seed **~30+** units in one part so the inline tree (`max-height: 100vh` ≈ 720px at the default viewport; rows are ~30px, so ~15 units ≈ 450px would NOT overflow and `scrollTop` would stay 0 → the `wait_for_function` would time out) reliably overflows and the active (last) unit is off-screen without the scroll. Sanity-check during the build that the seeded tree is actually taller than its container; if not, raise the count further or shrink the test viewport height.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -v`
Expected: FAIL — no toggle behaviour / class never set (JS not present).

- [ ] **Step 3: Add the pre-paint restore script to `base.html`**

In `templates/base.html`, immediately **after** the existing theme `<script>` (the IIFE ending at line ~28), add:

```html
<script>
  // Pre-paint: restore the desktop unit-tree collapse choice onto <html> so the rail
  // paints without a flash. Separate from the theme script above (which reads a cookie);
  // this reads localStorage. try/catch — storage can throw in private/sandboxed modes.
  (function () {
    "use strict";
    try {
      if (localStorage.getItem("libli_unit_tree_collapsed") === "1") {
        document.documentElement.classList.add("unit-tree-collapsed");
      }
    } catch (e) {}
  })();
</script>
```

(Runs on every page; inert unless a `.unit-shell` is present.)

- [ ] **Step 4: Create `unit_nav.js` (toggle + persistence + auto-scroll)**

`courses/static/courses/js/unit_nav.js`:

```javascript
(function () {
  "use strict";
  var KEY = "libli_unit_tree_collapsed";
  var html = document.documentElement;

  function store(val) {
    try { localStorage.setItem(KEY, val); } catch (e) {}
  }
  function isCollapsed() { return html.classList.contains("unit-tree-collapsed"); }

  // Desktop collapse toggle.
  var toggle = document.querySelector("[data-unit-tree-toggle]");
  if (toggle) {
    var EXPAND = toggle.getAttribute("data-label-expand");
    var COLLAPSE = toggle.getAttribute("data-label-collapse");
    function syncToggle(collapsed) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      // Announce the ACTION the button performs in its current state.
      if (EXPAND && COLLAPSE) toggle.setAttribute("aria-label", collapsed ? EXPAND : COLLAPSE);
    }
    toggle.addEventListener("click", function () {
      var collapsed = html.classList.toggle("unit-tree-collapsed");
      store(collapsed ? "1" : "0");
      syncToggle(collapsed);
    });
    syncToggle(isCollapsed());
  }

  // Auto-scroll the active unit into view — only when expanded (labels visible),
  // after the pre-paint collapse restore has already run on <html>.
  var active = document.querySelector(".unit-tree__unit.is-active");
  if (active && !isCollapsed()) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    active.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }
  // NOTE: spec §3.3 mandates scrollIntoView({block:"center"}). It walks every scrollable
  // ancestor, so in principle it could also nudge the window (jumping the article), not
  // just the sticky tree rail. If the Task-7 screenshot/e2e pass reveals a page jump,
  // switch to scrolling the container directly:
  //   var tree = document.querySelector("[data-unit-tree]");
  //   if (tree && active) tree.scrollTop = active.offsetTop - tree.clientHeight / 2;
  // (the sticky/overflow-y:auto tree is the intended scroll target).
})();
```

- [ ] **Step 5: Load `unit_nav.js` from both unit templates**

In `templates/courses/lesson_unit.html` and `templates/courses/quiz_unit.html`, inside `{% block extra_js %}`, add (after the existing scripts):

```django
  <script src="{% static 'courses/js/unit_nav.js' %}" defer></script>
```

- [ ] **Step 6: Add the collapsed-rail CSS**

Append to `courses/static/courses/css/courses.css`:

```css
/* Collapsed desktop rail — state lives on <html> (pre-paint script), so scope from it. */
@media (min-width: 641px) {
  html.unit-tree-collapsed .unit-tree { flex-basis: 2.4rem; }
  html.unit-tree-collapsed .unit-tree__heading,
  html.unit-tree-collapsed .unit-tree__list { display: none; }
  html.unit-tree-collapsed .unit-tree__toggle { transform: scaleX(-1); }  /* ‹ → › */
  html.unit-tree-collapsed .unit-tree__bar { justify-content: center; padding: .55rem .35rem; }
}
```

- [ ] **Step 7: Run the e2e tests**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -v`
Expected: PASS (collapse persists; active unit scrolled into view).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check tests/test_e2e_unit_nav.py
uv run ruff format --check tests/test_e2e_unit_nav.py
git add templates/base.html courses/static/courses/js/unit_nav.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html courses/static/courses/css/courses.css tests/test_e2e_unit_nav.py
git commit -m "feat(unit-nav): desktop collapse rail (pre-paint restore + toggle + persistence) + auto-scroll to active"
```

---

### Task 6: Mobile drawer + focus trap

On ≤640px the inline tree is hidden; a teal bottom-right FAB opens a bottom drawer holding the same tree. Drawer closes on scrim tap, ✕, and Esc; focus is trapped while open and returned to the FAB on close; reduced-motion aware.

**Files:**
- Modify: `courses/static/courses/js/unit_nav.js` (append the drawer module)
- Modify: `locale/pl/LC_MESSAGES/django.po` if any new strings (the drawer strings — "Open course contents", "Close", "Course contents" — were already added in Task 4; confirm, add only if missing)
- Test: `tests/test_e2e_unit_nav.py` (add mobile-viewport tests)

**Interfaces:**
- Consumes: `data-unit-drawer-open`, `data-unit-drawer`, `data-unit-drawer-close`, `data-unit-drawer-list` hooks (Task 4 markup); the `hidden` attribute toggling.
- Produces: drawer open/close behaviour; a self-contained focus trap.

- [ ] **Step 1: Write the failing mobile e2e tests**

Add to `tests/test_e2e_unit_nav.py`. These tests need the `browser` fixture (not the default `page`) so they can build a mobile-viewport context. Set it up once per test (mirroring the `browser.new_context(...)` pattern in `test_e2e_quiz.py`):

```python
def test_mobile_drawer_open_close_scrim_and_esc(browser, live_server, ...):
    ctx = browser.new_context(viewport={"width": 390, "height": 780})
    page = ctx.new_page()
    _login(page, live_server, username)   # seed + enrol first, as in the desktop tests
    page.goto(unit_url)
    fab = page.locator("[data-unit-drawer-open]")
    assert fab.is_visible()
    fab.click()
    drawer = page.locator("[data-unit-drawer]")
    assert drawer.is_visible()
    # focus moved into the drawer (close button or first link)
    # close on scrim tap
    page.locator(".unit-drawer__scrim").click(position={"x": 5, "y": 5})
    assert drawer.is_hidden()
    # reopen, close on Esc
    fab.click()
    page.keyboard.press("Escape")
    assert drawer.is_hidden()
    # focus returned to the FAB
    assert page.evaluate("document.activeElement?.getAttribute('data-unit-drawer-open') !== null") is True
    ctx.close()   # close the per-test context (or wrap the body in try/finally, or use a
                  # fixture with teardown) so contexts don't leak across the mobile tests


def test_mobile_drawer_focus_trap(...):
    fab.click()
    # Exercise the WRAP boundary the trap implements: Shift+Tab from the FIRST focusable
    # (the close button) must wrap to the LAST focusable, staying inside the drawer. A
    # single forward Tab would only move to the next interior element and never hit wrap.
    page.evaluate("document.querySelector('[data-unit-drawer] .unit-drawer__close')?.focus()")
    page.keyboard.press("Shift+Tab")
    inside = page.evaluate("!!document.querySelector('[data-unit-drawer]').contains(document.activeElement)")
    assert inside is True
    is_last = page.evaluate(
        "(() => { const p = document.querySelector('[data-unit-drawer] .unit-drawer__panel');"
        " const f = [...p.querySelectorAll('a[href],button:not([disabled])')].filter(e => e.offsetParent);"
        " return document.activeElement === f[f.length - 1]; })()"
    )
    assert is_last is True  # wrapped to the last focusable, not escaped to page chrome
```

> Drive real gestures (`.click()`, `keyboard.press`); the `evaluate` calls only set a known starting focus and read `document.activeElement` for the assertion (observation, not driving the UI under test). The earlier `test_mobile_drawer_open_close_scrim_and_esc` checks focus returns to the FAB on close.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -k drawer -v`
Expected: FAIL — FAB does nothing / drawer never opens.

- [ ] **Step 3: Append the drawer module to `unit_nav.js`**

Add, inside the same IIFE in `courses/static/courses/js/unit_nav.js` (before the closing `})();`):

```javascript
  // ── Mobile drawer with a self-contained focus trap (catalog_modal.js has none). ──
  var fab = document.querySelector("[data-unit-drawer-open]");
  var drawer = document.querySelector("[data-unit-drawer]");
  if (fab && drawer) {
    var panel = drawer.querySelector(".unit-drawer__panel");
    var lastFocus = null;

    // Progressive enhancement: the FAB ships with [hidden] (inert with JS off). Reveal
    // it now that JS can open the drawer; the mobile CSS shows it via :not([hidden]).
    fab.hidden = false;

    function focusable() {
      return Array.prototype.slice.call(
        panel.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])')
      ).filter(function (el) { return el.offsetParent !== null; });
    }
    function onKeydown(e) {
      if (e.key === "Escape") { closeDrawer(); return; }
      if (e.key !== "Tab") return;
      var items = focusable();
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    function openDrawer() {
      lastFocus = document.activeElement;
      drawer.hidden = false;
      fab.setAttribute("aria-expanded", "true");
      // scroll the active unit into view within the drawer
      var act = drawer.querySelector(".unit-tree__unit.is-active");
      if (act) act.scrollIntoView({ block: "center" });
      var items = focusable();
      (items[0] || panel).focus();
      document.addEventListener("keydown", onKeydown, true);
    }
    function closeDrawer() {
      drawer.hidden = true;
      fab.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", onKeydown, true);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    fab.addEventListener("click", openDrawer);
    drawer.addEventListener("click", function (e) {
      if (e.target.closest("[data-unit-drawer-close]")) closeDrawer();
    });

    // If the viewport crosses to desktop while open, close (the inline tree takes over).
    var mq = window.matchMedia("(min-width: 641px)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(function (e) {
      if (e.matches && !drawer.hidden) closeDrawer();
    });
  }
```

> `panel` needs to be focusable as a fallback — add `tabindex="-1"` to the `.unit-drawer__panel` div in `_unit_shell.html` (Task 4 markup) if focusing it is necessary. Add it now: edit `templates/courses/_unit_shell.html` so the panel is `<div class="unit-drawer__panel" tabindex="-1">`.

- [ ] **Step 4: Run the mobile e2e tests**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -k drawer -v`
Expected: PASS (open, scrim-close, Esc-close, focus return, trap).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_e2e_unit_nav.py
uv run ruff format --check tests/test_e2e_unit_nav.py
git add courses/static/courses/js/unit_nav.js templates/courses/_unit_shell.html tests/test_e2e_unit_nav.py
git commit -m "feat(unit-nav): mobile drawer with focus trap (Esc/scrim close, focus return)"
```

---

### Task 7: Integration — Prev/Next e2e traversal, full-suite DoD, light+dark screenshots

Pin Prev/Next traversal end-to-end (crossing the lesson↔quiz boundary), then run the whole Definition-of-Done gate and a throwaway light+dark screenshot self-review.

**Files:**
- Test: `tests/test_e2e_unit_nav.py` (add the traversal test)
- Throwaway: a temporary screenshot harness in the scratchpad (deleted after review)

**Interfaces:** none new — exercises Tasks 1–6 together.

- [ ] **Step 1: Write the Prev/Next traversal e2e test**

Add to `tests/test_e2e_unit_nav.py`. Seed a course: part with `[lesson A, quiz B, lesson C]`. Enrol + login. Test:

```python
def test_prev_next_traverses_lesson_and_quiz(...):
    page.goto(lesson_A_url)
    # Next → quiz B (link targets lesson_unit; server redirects quizzes to quiz_unit)
    page.locator(".unit-foot__nav--primary").click()
    page.wait_for_url("**/quiz/")               # landed on the quiz unit
    # Prev → back to lesson A
    page.locator(".unit-foot__nav:not(.unit-foot__nav--primary)").click()
    page.wait_for_url("**/u/%d/" % lesson_A.pk)
    # First unit has a disabled prev (a span, not a link)
    assert page.locator(".unit-foot__nav--disabled").count() >= 1
```

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -k traverse -v`
Expected: first FAIL if any wiring is off, then PASS once green. (If it passes immediately, that's fine — it's an integration pin.)

- [ ] **Step 2: Full unit-test suite (no e2e)**

Run: `uv run pytest -q`
Expected: all green (the batch-1 ~1048+ tests plus the new unit/render tests). Investigate and fix any regression — especially in `test_courses_rollups.py` (build_outline contract) and any template-render test touching the unit pages.

- [ ] **Step 3: Full e2e suite for unit nav + the touched pages**

Run: `uv run pytest -m e2e -k "unit_nav or quiz or results" -v`
Expected: green. (Confirms the shell didn't break the existing quiz/results e2e — `progress.js` seen hook, quiz finish, etc.)

- [ ] **Step 4: Lint the whole branch's touched files**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: clean. Fix any drift.

- [ ] **Step 5: Light + dark screenshot self-review**

Per the `verify-ui-with-screenshots` rule: write a throwaway Playwright script in the scratchpad (`C:\Users\krzys\AppData\Local\Temp\claude\…\scratchpad\shot.py`) that logs in a seeded student and screenshots: (a) a lesson unit desktop **light**, (b) same **dark** (`data-theme=dark` via the theme cookie/toggle), (c) the **collapsed** rail, (d) a mobile-viewport unit page with the **drawer open**. Review each for: tree alignment, active highlight contrast, footer Prev/Next legibility, the course hairline + part chip, dark-mode parity (no faint borders / unreadable text), drawer scrim + panel. Self-critique, fix any CSS issues found, re-shoot. **Delete the harness and screenshots after review.**

- [ ] **Step 6: Final commit (if screenshot review produced fixes)**

```bash
uv run ruff check courses/static/courses/css/courses.css
uv run ruff format --check <any edited .py>
git add -A
git commit -m "polish(unit-nav): light+dark screenshot review fixes"
```

(If the screenshot pass found nothing to fix, skip this commit.)

- [ ] **Step 7: Whole-branch verification before PR**

Run the DoD gate one last time:
```bash
uv run pytest -q && uv run pytest -m e2e -k unit_nav -v && uv run ruff check . && uv run ruff format --check .
```
Expected: all green. The branch is ready for the finishing-a-development-branch step (PR).

---

## Self-Review (against the spec, §3 + §8 + §9)

**Spec coverage:**
- §3.1 unit shell (two-column, footer) → Task 4 (`_unit_shell.html`, CSS). Article remains the direct seen-hook node (§9) → Task 4 structure + `test_unit_shell_wraps_lesson_article_and_keeps_seen_hook`.
- §3.2 `build_unit_nav` returning `{tree, prev, next, part_progress, course_progress}` → Task 2. Both views call it (§3.2 "cannot drift") → Task 3. Untracked previewer gets all-false tree → covered by `build_outline`'s empty `completed` set (unauth guard) — views are `@login_required` so always authenticated/enrolled-or-not.
- §3.3 tree (full structure, `.outline`-vocabulary adaptation, current `aria-current`, completed ✓, nav landmark, desktop toggle→rail, localStorage `libli_unit_tree_collapsed`, pre-paint on `<html>`, auto-scroll only when expanded after restore, mobile drawer) → Tasks 4 (tree + landmark + aria-current + ✓), 5 (toggle + pre-paint + auto-scroll), 6 (drawer).
- §3.4 `units_in_order` via one shared `_walk_preorder`; `quiz_units_in_order` rewritten as a filter; quizzes included; Prev/Next by `pk` for an independently-fetched node; first/last absent → Tasks 1 + 2 (`test_units_in_order_preorder_mixed_lesson_and_quiz`, `test_build_unit_nav_prev_next_resolve_by_pk_for_independent_instance`, `test_build_unit_nav_first_and_last_have_no_neighbour`). Neighbour titles + `lang` → Task 4 footer.
- §3.5 footer progress: course hairline (sum across parts, hidden when total 0), part chip (depth-1 ancestor ratio, hidden when no enclosing part or 0-required) → Task 2 (`test_build_unit_nav_part_and_course_progress`, `_depth1_unit_hides_part_chip`, `_zero_required_part_hides_chip`) + Task 4 template (`widthratio`, `{% if %}` guards) + `test_unit_shell_part_chip_hidden_for_root_unit`.
- §3.6 a11y: labelled nav, `aria-current`, drawer `role=dialog`/`aria-modal`, **new** focus trap, Esc + scrim close, focus return, real `<a>` Prev/Next with disabled ends non-focusable (rendered as `<span>`) → Tasks 4 + 6.
- §8 tests: ordering (nested/mixed/edge), `build_unit_nav` neighbours + progress + edges, pk-resolution, template-render of shell/tree/footer, e2e collapse+persist / drawer open+scrim+Esc / Prev-Next / auto-scroll → Tasks 1–7.
- §9 risks: seen hook intact (article direct, no seen on quiz) → Task 4; pre-paint on `<html>` via a separate localStorage script → Task 5.

**Placeholder scan:** no "TBD"/"add error handling"/"similar to Task N" — all code is inline. (Two deliberate "mirror the harness in test_e2e_quiz.py" references for e2e seeding/login are project convention, not placeholders — the gestures + assertions are spelled out.)

**Type consistency:** `build_unit_nav` returns `{tree, current_pk, prev, next, part_progress, course_progress}` — the same keys are read in `_unit_tree.html` (`unit_nav.tree`, `unit_nav.current_pk`), `_unit_footer.html` (`unit_nav.prev/next/part_progress/course_progress`), and asserted in Tasks 2–4 tests. `part_progress` is `{done,total,title}` (or None); `course_progress` is `{done,total}` — consistent across service, template `widthratio`, and tests. `localStorage` key `libli_unit_tree_collapsed` and class `unit-tree-collapsed` are identical in the base.html pre-paint script, `unit_nav.js`, and the CSS scope.

**Out of scope (not in this batch):** quiz-review roster (batch 3) and code-editor fields (batch 4) — the `.unit-shell` CSS is authored here for batch 3 to reuse.
