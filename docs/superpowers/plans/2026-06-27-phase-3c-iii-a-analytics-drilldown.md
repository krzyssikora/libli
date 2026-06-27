# Phase 3c-iii-a — Analytics drill-down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 3c-ii analytics matrix drill down — recursive inline column expand (chip bar + flat headers) plus a per-student breakdown page — all read-only, no migration.

**Architecture:** A pure `frontier_columns(course, expanded_pks)` generalizes the existing `build_matrix_columns` to return the visible frontier columns **and** the active-expanded node list; the two matrix builders take an `expanded` arg and thread both through their result dict. A `build_student_breakdown` composition helper joins `build_outline` + `build_course_results` for one student. The view attaches pre-built hrefs (expand/collapse/breakdown) and a per-row reviewable gate; state rides in repeatable `?expand=` GET params, self-cleaned to the reached set.

**Tech Stack:** Django (server-rendered, progressive-enhancement, no JS framework), pytest, Playwright (e2e), `uv` task runner.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI checks `ruff format --check`, so run **both** `uv run ruff check --fix` and `uv run ruff format` at the end of every task.
- **isort:** project uses `force-single-line=true` — each import on its own line (ruff enforces).
- **i18n:** every new user-facing string gets EN + PL at build time (Task 9). `makemessages` re-marks copied msgstrs `#, fuzzy` (ignored at runtime) and can mis-guess — clear the flag and verify each new msgid. Compile `.mo`.
- **Single-source (anti-drift):** reuse `is_obligatory_lesson` / `is_quiz_unit` / `submission_is_counted` / `_quiz_review_maps`; never re-derive "counts toward Progress/Results" or "counted/pending".
- **`None` ≠ `0`:** a cell `percent` is `int|None`; `None` (no denominator) renders "—", `0` (attempted, scored 0) is the lowest band. No builder/template may collapse `None` to `0`.
- **Manage convention:** all new surfaces resolve the course by slug → 404 on mismatch; out-of-reach / non-staff → **404, never 403**.
- **Spec:** `docs/superpowers/specs/2026-06-27-phase-3c-iii-a-analytics-drilldown-design.md` is the source of truth; section refs (§1–§7) below point into it.

---

### Task 1: `frontier_columns` pure function (+ keep `build_matrix_columns` as alias)

Generalize the depth-1 column walk to a recursive frontier. Pure (no `user`, no DB beyond `course.nodes`). Returns the frontier `columns` and the active-`expanded_nodes` list (spec §1).

**Files:**
- Modify: `courses/rollups.py` (add `frontier_columns`; rewrite `build_matrix_columns` as a thin alias; keep `is_obligatory_lesson`/`is_quiz_unit` as-is)
- Test: `tests/test_analytics_rollups.py` (append; reuse the existing `_chapter`/`_lesson`/`_quiz` helpers at the top of that file)

**Interfaces:**
- Produces: `frontier_columns(course, expanded_pks) -> {"columns": list[dict], "expanded_nodes": list[dict]}`.
  - a **column** dict = `{"node": ContentNode, "title": str, "lesson_pks": set[int], "quiz_pks": set[int], "expandable": bool, "depth": int}`. `title` is the breadcrumb path (`" ▸ ".join(...)`); for a root/depth-0 column it equals `node.title`. `expandable` = has children and not expanded.
  - an **expanded_node** dict = `{"node": ContentNode, "pk": int, "title": str}` (breadcrumb title including self), one per node actually recursed through, in outline order.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_rollups.py`:

```python
from courses.rollups import frontier_columns


def _section(course, parent, **kw):
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="section", parent=parent, **kw)


@pytest.mark.django_db
def test_frontier_empty_matches_build_matrix_columns():
    course = CourseFactory()
    ch1, ch2 = _chapter(course, title="A"), _chapter(course, title="B")
    l1 = _lesson(course, ch1)
    fc = frontier_columns(course, set())
    base = build_matrix_columns(course)
    assert [c["node"].pk for c in fc["columns"]] == [c["node"].pk for c in base]
    assert fc["columns"][0]["lesson_pks"] == {l1.pk}
    assert fc["columns"][0]["title"] == "A"  # root title, no breadcrumb prefix
    assert fc["expanded_nodes"] == []
    assert fc["columns"][0]["expandable"] is True  # has the lesson child
    assert fc["columns"][1]["expandable"] is False  # ch2 has no children


@pytest.mark.django_db
def test_frontier_expand_chapter_replaces_with_children():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    other = _lesson(course, ch, title="Loose")
    fc = frontier_columns(course, {ch.pk})
    # ch is gone as a column; its children (sec, other) take its place, in order
    titles = [c["title"] for c in fc["columns"]]
    assert titles == ["Ch ▸ Sec", "Ch ▸ Loose"]
    assert [e["pk"] for e in fc["expanded_nodes"]] == [ch.pk]
    assert fc["expanded_nodes"][0]["title"] == "Ch"


@pytest.mark.django_db
def test_frontier_recursive_expand():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    leaf = _lesson(course, sec, title="U")
    fc = frontier_columns(course, {ch.pk, sec.pk})
    assert [c["title"] for c in fc["columns"]] == ["Ch ▸ Sec ▸ U"]
    assert [e["pk"] for e in fc["expanded_nodes"]] == [ch.pk, sec.pk]


@pytest.mark.django_db
def test_frontier_stale_descendant_pk_is_inert():
    """Sec's pk lingers but Ch is collapsed -> Sec is never reached; no stale chip."""
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    _lesson(course, sec)
    fc = frontier_columns(course, {sec.pk})  # parent ch NOT expanded
    assert [c["node"].pk for c in fc["columns"]] == [ch.pk]  # ch is the column
    assert fc["expanded_nodes"] == []  # sec not reached -> no chip


@pytest.mark.django_db
def test_frontier_ignores_unknown_and_leaf_pks():
    course = CourseFactory()
    ch = _chapter(course)
    leaf = _lesson(course, ch)
    fc = frontier_columns(course, {leaf.pk, 999999})  # leaf has no children; 999999 unknown
    assert [c["node"].pk for c in fc["columns"]] == [ch.pk]
    assert fc["expanded_nodes"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k frontier -v`
Expected: FAIL with `ImportError: cannot import name 'frontier_columns'`.

- [ ] **Step 3: Implement `frontier_columns` and re-point `build_matrix_columns`**

In `courses/rollups.py`, **replace** the existing `build_matrix_columns` (currently rollups.py:285-312) with the following two functions (order: `frontier_columns` first, then the alias):

```python
def frontier_columns(course, expanded_pks):
    """Recursive drill-down columns + the active-expanded node list (spec §1).

    One `course.nodes` query + a parent_id-grouped recursion (NOT the flat
    `_walk_preorder` generator — the frontier needs conditional recursion that
    stops at a non-expanded node, a has-children test, and ancestor titles).
    A node whose pk is in `expanded_pks` AND has children is recursed THROUGH
    (it becomes an `expanded_nodes` entry, never a column); every other node is
    a column. Pure: no `user`, no DB beyond the one nodes query.
    """
    nodes = list(course.nodes.all())
    children = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)

    def subtree_pks(root):
        lesson_pks, quiz_pks = set(), set()
        stack = [root]
        while stack:
            n = stack.pop()
            if is_obligatory_lesson(n):
                lesson_pks.add(n.pk)
            elif is_quiz_unit(n):
                quiz_pks.add(n.pk)
            stack.extend(children.get(n.pk, []))
        return lesson_pks, quiz_pks

    columns = []
    expanded_nodes = []

    def walk(parent_id, ancestor_titles):
        for node in children.get(parent_id, []):
            kids = children.get(node.pk, [])
            title = " ▸ ".join(ancestor_titles + [node.title])
            if node.pk in expanded_pks and kids:
                expanded_nodes.append({"node": node, "pk": node.pk, "title": title})
                walk(node.pk, ancestor_titles + [node.title])
            else:
                lesson_pks, quiz_pks = subtree_pks(node)
                columns.append(
                    {
                        "node": node,
                        "title": title,
                        "lesson_pks": lesson_pks,
                        "quiz_pks": quiz_pks,
                        "expandable": bool(kids),
                        "depth": len(ancestor_titles),
                    }
                )

    walk(None, [])
    return {"columns": columns, "expanded_nodes": expanded_nodes}


def build_matrix_columns(course):
    """Depth-1 roots as analytics columns (the un-expanded frontier). Thin alias
    over frontier_columns so the single walk stays single-source (spec §2)."""
    return frontier_columns(course, frozenset())["columns"]
```

Note: `" ▸ "` is the literal `" ▸ "` separator; write the actual `▸` character in the source.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -k "frontier or build_matrix_columns" -v`
Expected: PASS (new frontier tests + the existing `test_build_matrix_columns_partition`).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix courses/rollups.py tests/test_analytics_rollups.py
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): frontier_columns recursive drill-down columns (3c-iii-a)"
```

---

### Task 2: Builders accept `expanded`, return `expanded_nodes`, extend `_public_columns`

Both matrix builders take an `expanded` set (default empty == today), source columns from `frontier_columns`, surface `expanded_nodes` in the result dict, and expose `expandable` to the template via `_public_columns`. The partition invariant and no-N+1 must hold under expansion (spec §2).

**Files:**
- Modify: `courses/rollups.py` (`_public_columns`, `build_progress_matrix`, `build_results_matrix`)
- Test: `tests/test_analytics_rollups.py` (append)

**Interfaces:**
- Consumes: `frontier_columns` (Task 1).
- Produces:
  - `build_progress_matrix(course, students, expanded=frozenset()) -> dict` and `build_results_matrix(course, students, expanded=frozenset()) -> dict`, each now also containing `"expanded_nodes": list` and each `columns[i]` carrying `"expandable": bool` (plus existing `node`, `title`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_rollups.py`:

```python
@pytest.mark.django_db
def test_progress_partition_invariant_under_expansion():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    l1 = _lesson(course, sec)
    l2 = _lesson(course, ch)  # sibling of sec
    s = UserFactory()
    UnitProgressFactory(student=s, unit=l1, completed=True)  # 1 of 2 obligatory
    flat = build_progress_matrix(course, [s])
    expanded = build_progress_matrix(course, [s], {ch.pk})
    # expanding regroups, never changes the student's overall
    assert flat["rows"][0]["overall"]["percent"] == expanded["rows"][0]["overall"]["percent"]
    # the chapter is gone as a column; its children are columns now
    assert expanded["expanded_nodes"][0]["pk"] == ch.pk
    assert expanded["columns"][0]["expandable"] is True  # sec still expandable
    # sum of frontier (done,total) equals the un-expanded chapter's
    assert sum(1 for c in expanded["columns"] if c["title"]) == len(expanded["columns"])


@pytest.mark.django_db
def test_results_partition_invariant_under_expansion():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    qz = _quiz(course, sec)
    _auto_q(qz, "10")
    s = UserFactory()
    QuizSubmission.objects.create(
        student=s, unit=qz, status="submitted", score=Decimal("7"), max_score=Decimal("10")
    )
    flat = build_results_matrix(course, [s])
    expanded = build_results_matrix(course, [s], {ch.pk})
    assert flat["rows"][0]["overall"]["percent"] == 70
    assert expanded["rows"][0]["overall"]["percent"] == 70  # unchanged by expansion


@pytest.mark.django_db
def test_builders_expose_expanded_nodes_and_expandable():
    course = CourseFactory()
    ch = _chapter(course)
    _section(course, ch)
    m = build_progress_matrix(course, [])
    assert m["expanded_nodes"] == []
    assert m["columns"][0]["expandable"] is True
    assert set(m["columns"][0].keys()) == {"node", "title", "expandable"}


@pytest.mark.django_db
def test_progress_query_count_constant_under_expansion():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    sec = _section(course, ch)
    _lesson(course, sec)
    s = [UserFactory() for _ in range(3)]
    build_progress_matrix(course, s)  # warm
    with CaptureQueriesContext(connection) as c1:
        build_progress_matrix(course, s)
    with CaptureQueriesContext(connection) as c2:
        build_progress_matrix(course, s, {ch.pk, sec.pk})
    assert len(c1) == len(c2)  # only in-memory grouping changes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k "partition or expanded_nodes or constant_under_expansion" -v`
Expected: FAIL (`build_progress_matrix() takes 2 positional arguments but 3 were given`, and missing `expanded_nodes`).

- [ ] **Step 3: Implement the builder changes**

In `courses/rollups.py`:

Replace `_public_columns` (rollups.py:331-332):

```python
def _public_columns(columns):
    return [
        {"node": c["node"], "title": c["title"], "expandable": c["expandable"]}
        for c in columns
    ]
```

In `build_progress_matrix`, change the signature and the column source, and add `expanded_nodes` to the return:

```python
def build_progress_matrix(course, students, expanded=frozenset()):
    """Required-lesson completion %, students × frontier columns. No N+1. See spec §2-3."""
    students = list(students)
    fc = frontier_columns(course, expanded)
    columns = fc["columns"]
    # ... (body unchanged: uses `columns` exactly as before) ...
```

and the return dict gains one key:

```python
    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "has_quizzes": any(c["quiz_pks"] for c in columns),
        "expanded_nodes": fc["expanded_nodes"],
        "mode": "progress",
    }
```

Apply the identical three changes to `build_results_matrix` (signature `(course, students, expanded=frozenset())`, `fc = frontier_columns(course, expanded)` + `columns = fc["columns"]` replacing `columns = build_matrix_columns(course)`, and `"expanded_nodes": fc["expanded_nodes"]` + `"mode": "results"` in the return). The aggregation bodies are untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -v`
Expected: PASS (new tests + all pre-existing rollup tests — the empty-default keeps 3c-ii behavior).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix courses/rollups.py tests/test_analytics_rollups.py
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): builders take expanded set, surface expanded_nodes (3c-iii-a)"
```

---

### Task 3: Thread `submission_pk` onto `build_course_results` rows

The breakdown's review cross-link needs the submission pk. Add `submission_pk` to **every** `build_course_results` row that has a submission (`None` on `not_started`) — a consistent row schema, additive only (spec §3, decision option a).

**Files:**
- Modify: `courses/rollups.py` (`build_course_results`)
- Test: `tests/test_courses_rollups.py` if it exists, else `tests/test_analytics_rollups.py` (append) — see Step 1.

**Interfaces:**
- Produces: each `build_course_results(course, student)["rows"][i]` dict gains `"submission_pk": int | None`.

- [ ] **Step 1: Locate the existing `build_course_results` tests, write the failing test**

Run: `uv run pytest --collect-only -q tests/ 2>NUL | rg build_course_results` (or `grep`); add the test to the file that already exercises `build_course_results`. If none, append to `tests/test_analytics_rollups.py`:

```python
@pytest.mark.django_db
def test_build_course_results_rows_carry_submission_pk():
    from courses.rollups import build_course_results

    course = CourseFactory()
    ch = _chapter(course)
    qz1 = _quiz(course, ch)
    qz2 = _quiz(course, ch)
    _review_q(qz1, "10")
    s = UserFactory()
    sub = QuizSubmission.objects.create(
        student=s, unit=qz1, status="submitted", score=Decimal("0"), max_score=Decimal("0")
    )
    res = build_course_results(course, s)
    by_unit = {r["unit"].pk: r for r in res["rows"]}
    assert by_unit[qz1.pk]["submission_pk"] == sub.pk
    assert by_unit[qz2.pk]["submission_pk"] is None  # not_started -> no submission
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analytics_rollups.py -k submission_pk -v`
Expected: FAIL with `KeyError: 'submission_pk'`.

- [ ] **Step 3: Add `submission_pk` to each row**

In `courses/rollups.py` `build_course_results`, add `"submission_pk"` to **all three** appended row dicts:
- the `not_started` branch (rollups.py:226-235): `"submission_pk": None`.
- the `in_progress` branch (rollups.py:239-248): `"submission_pk": sub.pk`.
- the SUBMITTED branch (rollups.py:254-263): `"submission_pk": sub.pk`.

(Pure addition — no other behavior changes; existing assertions on the other keys stay valid.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -k submission_pk -v && uv run pytest tests/ -k course_results -v`
Expected: PASS (new test + all existing `build_course_results` tests still green).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix courses/rollups.py tests/test_analytics_rollups.py
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): build_course_results rows carry submission_pk (3c-iii-a)"
```

---

### Task 4: `build_student_breakdown` composition helper

Join `build_outline` (tree + lesson completion) with `build_course_results` (per-quiz status/score/pending/submission_pk) into one tree, attaching a single-sourced status **pill** dict to each quiz unit (spec §3, §6 pill mapping incl. the `max_score == 0` no-percent case).

**Files:**
- Modify: `courses/rollups.py` (add `_quiz_pill`, `build_student_breakdown`)
- Test: `tests/test_analytics_rollups.py` (append)

**Interfaces:**
- Consumes: `build_outline`, `build_course_results` (with `submission_pk` from Task 3).
- Produces: `build_student_breakdown(course, student) -> {"student": User, "tree": list}` where `tree` is the `build_outline` nested list and every **quiz** unit dict gains `"pill"`:
  - scored: `{"kind": "scored", "score": Decimal, "max_score": Decimal, "percent": int}`
  - `{"kind": "submitted"}` (submitted but ungraded, `max_score == 0`)
  - `{"kind": "awaiting", "submission_pk": int}`
  - `{"kind": "in_progress"}` / `{"kind": "not_started"}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_rollups.py`:

```python
@pytest.mark.django_db
def test_build_student_breakdown_pills():
    from courses.rollups import build_student_breakdown

    course = CourseFactory()
    ch = _chapter(course)
    les = _lesson(course, ch)
    scored = _quiz(course, ch)
    pending = _quiz(course, ch)
    notyet = _quiz(course, ch)
    _auto_q(scored, "10")
    _review_q(pending, "10")
    s = UserFactory()
    UnitProgressFactory(student=s, unit=les, completed=True)
    QuizSubmission.objects.create(
        student=s, unit=scored, status="submitted", score=Decimal("9"), max_score=Decimal("10")
    )
    sub_pending = QuizSubmission.objects.create(
        student=s, unit=pending, status="submitted", score=Decimal("0"), max_score=Decimal("10")
    )
    # pending has an unreviewed [R] -> awaiting_review (no QuestionResponse reviewed)
    bd = build_student_breakdown(course, s)
    by_unit = {}

    def collect(nodes):
        for d in nodes:
            by_unit[d["node"].pk] = d
            collect(d["children"])

    collect(bd["tree"])
    assert by_unit[les.pk]["completed"] is True
    assert by_unit[scored.pk]["pill"] == {
        "kind": "scored", "score": Decimal("9"), "max_score": Decimal("10"), "percent": 90,
    }
    assert by_unit[pending.pk]["pill"]["kind"] == "awaiting"
    assert by_unit[pending.pk]["pill"]["submission_pk"] == sub_pending.pk
    assert by_unit[notyet.pk]["pill"] == {"kind": "not_started"}


@pytest.mark.django_db
def test_build_student_breakdown_submitted_ungraded_no_percent():
    from courses.rollups import build_student_breakdown

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)  # no AUTO question -> graded False, max_score 0
    s = UserFactory()
    QuizSubmission.objects.create(
        student=s, unit=qz, status="submitted", score=Decimal("0"), max_score=Decimal("0")
    )
    bd = build_student_breakdown(course, s)
    pill = bd["tree"][0]["children"][0]["pill"]
    assert pill == {"kind": "submitted"}  # no score/max/percent -> no divide-by-zero
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k student_breakdown -v`
Expected: FAIL with `ImportError: cannot import name 'build_student_breakdown'`.

- [ ] **Step 3: Implement the helper**

Add to `courses/rollups.py` (after `build_course_results`):

```python
def _quiz_pill(row):
    """Map a build_course_results row to a single-sourced status pill (spec §6)."""
    status = row["status"]
    if status == "submitted":
        if row["graded"] and row["max_score"]:
            pct = int(round(Decimal(100) * row["score"] / row["max_score"]))
            return {
                "kind": "scored",
                "score": row["score"],
                "max_score": row["max_score"],
                "percent": pct,
            }
        return {"kind": "submitted"}  # submitted but ungraded (max_score == 0): no percent
    if status == "awaiting_review":
        return {"kind": "awaiting", "submission_pk": row["submission_pk"]}
    if status == "in_progress":
        return {"kind": "in_progress"}
    return {"kind": "not_started"}


def build_student_breakdown(course, student):
    """Compose build_outline + build_course_results into one teacher-facing tree
    (spec §3). NOT pure — calls two query-backed builders. Quiz units gain `pill`."""
    tree = build_outline(course, student)
    results = build_course_results(course, student)
    pill_by_unit = {r["unit"].pk: _quiz_pill(r) for r in results["rows"]}

    def attach(nodes):
        for d in nodes:
            node = d["node"]
            if d["is_unit"] and node.unit_type == ContentNode.UnitType.QUIZ:
                d["pill"] = pill_by_unit.get(node.pk)
            attach(d["children"])

    attach(tree)
    return {"student": student, "tree": tree}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -k student_breakdown -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix courses/rollups.py tests/test_analytics_rollups.py
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): build_student_breakdown composition helper (3c-iii-a)"
```

---

### Task 5: Make the matrix interactive — view link-decoration + template

Parse `?expand=`, thread it through the builder, build pre-built hrefs (expand/collapse/breakdown) and per-row reviewable gating, and render the chip bar + expandable headers + student links + hidden `expand` inputs. The round-tripped expand set is the **reached** `expanded_nodes` pks (self-cleaning); the scope GET form must carry hidden `expand` inputs and the mode/colours links must carry `expand` (spec §4 I1, §6).

**Files:**
- Modify: `courses/views_analytics.py` (`analytics_matrix`; add `_clean_expand`, `_expand_qs`, `_decorate_links`)
- Modify: `templates/courses/manage/analytics_matrix.html`
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: builders with `expanded` (Task 2); `scoping.reviewable_students`.
- Produces: helpers `_clean_expand(values) -> list[int]`, `_expand_qs(scope, mode, expand_pks) -> str`, used by Task 7 too.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
from courses.models import ContentNode


def _course_with_section_lesson(owner):
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    sec = ContentNodeFactory(course=course, kind="section", unit_type=None, parent=ch, title="Sec")
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sec, obligatory=True, title="U"
    )
    return course, ch, sec, les


@pytest.mark.django_db
def test_matrix_expand_renders_chip_and_subcolumns(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?expand={ch.pk}")
    assert resp.status_code == 200
    m = resp.context["matrix"]
    assert [e["pk"] for e in m["expanded_nodes"]] == [ch.pk]
    assert m["columns"][0]["node"].pk == sec.pk  # ch replaced by its child
    html = resp.content.decode()
    assert "Ch ▸ Sec" in html  # breadcrumb column title rendered


@pytest.mark.django_db
def test_matrix_scope_form_carries_expand_hidden_inputs(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?expand={ch.pk}")
    html = resp.content.decode()
    assert f'<input type="hidden" name="expand" value="{ch.pk}">' in html


@pytest.mark.django_db
def test_matrix_garbage_expand_is_ignored(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?expand=abc&expand=999999")
    assert resp.status_code == 200
    assert resp.context["matrix"]["expanded_nodes"] == []


@pytest.mark.django_db
def test_matrix_student_link_gated_on_reviewable(client):
    """Collection scope can show a student the viewer can't drill into -> plain text."""
    from tests.factories import CollectionFactory
    from tests.factories import GroupFactory
    from tests.factories import GroupMembershipFactory

    teacher = make_login(client, "teach")
    course = CourseFactory(owner=UserFactory())
    ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    taught = GroupFactory(course=course)
    taught.teachers.add(teacher)
    untaught = GroupFactory(course=course)
    coll = CollectionFactory(course=course)
    coll.groups.add(taught, untaught)
    mine = GroupMembershipFactory(group=taught)
    theirs = GroupMembershipFactory(group=untaught)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/?scope=collection:{coll.pk}"
    )
    rows = {r["student"].pk: r for r in resp.context["matrix"]["rows"]}
    assert rows[mine.student_id]["breakdown_url"]  # drillable
    assert rows[theirs.student_id].get("breakdown_url") is None  # plain text
```

(If `CollectionFactory` / `GroupFactory.teachers` differ, mirror `tests/test_analytics_scoping.py`'s collection setup — it already exercises `collections_visible_to`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "expand or reviewable" -v`
Expected: FAIL (`expanded_nodes` absent from context / no hidden expand input / `breakdown_url` KeyError).

- [ ] **Step 3: Implement the view helpers and extend `analytics_matrix`**

In `courses/views_analytics.py`, add imports if missing (`from django.contrib.auth import get_user_model` is needed in Task 7; `urlencode` and `reverse` are already imported). Add helpers:

```python
def _clean_expand(values):
    """Parse repeatable expand params into a list of ints, dropping junk."""
    pks = []
    for raw in values:
        try:
            pks.append(int(raw))
        except (TypeError, ValueError):
            pass
    return pks


def _expand_qs(scope, mode, expand_pks):
    """Querystring preserving scope/mode + the given expand pks (repeatable)."""
    return urlencode(
        {"scope": scope, "mode": mode, "expand": list(expand_pks)}, doseq=True
    )


def _decorate_links(matrix, course, scope, mode, reviewable_ids):
    """Attach pre-built hrefs (spec §4): expand_url per expandable column,
    collapse_url per expanded node, breakdown_url per drillable row. The
    round-tripped expand set is the REACHED expanded_nodes pks (self-cleaning)."""
    base_pks = [en["pk"] for en in matrix["expanded_nodes"]]
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    for col in matrix["columns"]:
        if col["expandable"]:
            col["expand_url"] = (
                f"{matrix_path}?{_expand_qs(scope, mode, base_pks + [col['node'].pk])}"
            )
    for en in matrix["expanded_nodes"]:
        rest = [p for p in base_pks if p != en["pk"]]
        en["collapse_url"] = f"{matrix_path}?{_expand_qs(scope, mode, rest)}"
    for row in matrix["rows"]:
        if row["student"].pk in reviewable_ids:
            student_path = reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": row["student"].pk},
            )
            row["breakdown_url"] = f"{student_path}?{_expand_qs(scope, mode, base_pks)}"
    return base_pks
```

Replace the body of `analytics_matrix` (keep the gate) with:

```python
@login_required
def analytics_matrix(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    expand_pks = set(_clean_expand(request.GET.getlist("expand")))
    students = scoping.students_in_scope(request.user, course, scope).order_by(
        "username"
    )
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students, expand_pks)
    bands = course_color_bands(course)
    _decorate(matrix, bands)
    reviewable_ids = set(
        scoping.reviewable_students(request.user, course).values_list("pk", flat=True)
    )
    base_pks = _decorate_links(matrix, course, scope, mode, reviewable_ids)
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    bands_path = reverse("courses:manage_analytics_bands", kwargs={"slug": course.slug})
    return render(
        request,
        "courses/manage/analytics_matrix.html",
        {
            "course": course,
            "matrix": matrix,
            "mode": mode,
            "scope": scope,
            "scope_choices": scoping.analytics_scope_choices(request.user, course),
            "legend": legend_rows(bands),
            "can_edit_bands": can_manage_course(request.user, course),
            "expand_pks": base_pks,
            "progress_url": f"{matrix_path}?{_expand_qs(scope, 'progress', base_pks)}",
            "results_url": f"{matrix_path}?{_expand_qs(scope, 'results', base_pks)}",
            "colours_url": f"{bands_path}?{_expand_qs(scope, mode, base_pks)}",
        },
    )
```

- [ ] **Step 4: Update the matrix template**

In `templates/courses/manage/analytics_matrix.html`:

Replace the "Configure colours" link `href` (line 9-11) to use the pre-built URL:

```html
      <a class="btn btn--ghost btn--small" href="{{ colours_url }}">
        {% trans "Configure colours" %}</a>
```

In the `<form>` (after the hidden `mode` input, line 17), add the expand hidden inputs:

```html
    {% for pk in expand_pks %}<input type="hidden" name="expand" value="{{ pk }}">{% endfor %}
```

Replace the two toggle links (lines 26-29) to use the pre-built URLs:

```html
      <a class="btn btn--small {% if mode == 'progress' %}is-active{% endif %}"
         href="{{ progress_url }}">{% trans "Progress" %}</a>
      <a class="btn btn--small {% if mode == 'results' %}is-active{% endif %}"
         href="{{ results_url }}">{% trans "Results" %}</a>
```

After the legend `</ul>` (line 39), add the chip bar:

```html
  {% if matrix.expanded_nodes %}
    <div class="analytics__chips">
      <span class="analytics__chips-label">{% trans "Expanded:" %}</span>
      {% for en in matrix.expanded_nodes %}
        <span class="analytics__chip" lang="{{ course.language }}">{{ en.title }}
          <a class="analytics__chip-x" href="{{ en.collapse_url }}"
             aria-label="{% trans 'Collapse' %}">✕</a></span>
      {% endfor %}
    </div>
  {% endif %}
```

Replace the column-header loop (line 51) to render expand links:

```html
            {% for col in matrix.columns %}
              <th>{% if col.expandable %}<a class="analytics__expand" href="{{ col.expand_url }}"
                     lang="{{ course.language }}">{{ col.title }} ▸</a>{% else %}<span
                     lang="{{ course.language }}">{{ col.title }}</span>{% endif %}</th>
            {% endfor %}
```

Replace the student-name cell (line 58) to gate the link:

```html
              <td class="analytics__rowhead">
                {% if row.breakdown_url %}<a href="{{ row.breakdown_url }}">{{ row.student.display_name|default:row.student.username }}</a>{% else %}{{ row.student.display_name|default:row.student.username }}{% endif %}</td>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (new tests + all pre-existing matrix-view tests, incl. `test_matrix_controls_round_trip_both_params` — the hidden `mode` input and scope round-trip survive).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --fix courses/views_analytics.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py templates/courses/manage/analytics_matrix.html tests/test_analytics_views.py
git commit -m "feat(analytics): interactive matrix — expand chips, headers, gated student links (3c-iii-a)"
```

---

### Task 6: Per-student breakdown — route, view, templates, review cross-link

Add `analytics_student` gated on `can_review_course` AND `student ∈ reviewable_students` (404 otherwise); render the composed tree with per-quiz status pills, the `awaiting_review` → review cross-link, and a breadcrumb back carrying matrix state. The breakdown ignores the student-facing `url_name` (no quiz hyperlinks except the cross-link) (spec §3, §4, §6).

**Files:**
- Modify: `courses/urls.py` (add the route)
- Modify: `courses/views_analytics.py` (`analytics_student`)
- Create: `templates/courses/manage/analytics_student.html`
- Create: `templates/courses/manage/_breakdown_node.html`
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: `build_student_breakdown` (Task 4); `_clean_expand`/`_expand_qs` (Task 5); `scoping.can_review_course`/`reviewable_students`.
- Produces: URL name `courses:manage_analytics_student` (kwargs `slug`, `student_pk`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
@pytest.mark.django_db
def test_breakdown_renders_for_owner_with_pills(client):
    from courses.models import QuizSubmission

    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    qz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch, title="Qz")
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    from decimal import Decimal

    from courses.models import QuestionElement
    from courses.models import ShortTextQuestionElement
    from courses.models import Element

    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal("10")
    )
    Element.objects.create(unit=qz, content_object=q)
    QuizSubmission.objects.create(
        student=student, unit=qz, status="submitted", score=Decimal("9"), max_score=Decimal("10")
    )
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{student.pk}/")
    assert resp.status_code == 200
    assert b"Ada L." in resp.content
    assert b"90%" in resp.content  # scored pill


@pytest.mark.django_db
def test_breakdown_404_for_student_out_of_reach(client):
    teacher = make_login(client, "teach")
    course = CourseFactory(owner=UserFactory())
    from tests.factories import GroupFactory

    g = GroupFactory(course=course)
    g.teachers.add(teacher)  # teacher reviews g's students only
    outsider = UserFactory()
    Enrollment.objects.create(student=outsider, course=course)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{outsider.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_breakdown_404_for_non_staff(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    s = UserFactory()
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{s.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_breakdown_awaiting_review_shows_cross_link(client):
    from decimal import Decimal

    from courses.models import Element
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement

    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    qz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch, title="Qz")
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("10")
    )
    Element.objects.create(unit=qz, content_object=q)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=qz, status="submitted", score=Decimal("0"), max_score=Decimal("0")
    )
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{student.pk}/")
    assert f"/review/{sub.pk}/".encode() in resp.content  # cross-link to manage_review_submission
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k breakdown -v`
Expected: FAIL with `NoReverseMatch` / 404 on a route that doesn't exist yet.

- [ ] **Step 3: Add the URL route**

In `courses/urls.py`, inside the analytics block (after the `manage_analytics` path, courses/urls.py:200), add:

```python
    path(
        "manage/courses/<slug:slug>/analytics/student/<int:student_pk>/",
        views_analytics.analytics_student,
        name="manage_analytics_student",
    ),
```

- [ ] **Step 4: Add the `analytics_student` view**

In `courses/views_analytics.py`, add (and ensure `from courses.rollups import build_student_breakdown` is imported at top):

```python
@login_required
def analytics_student(request, slug, student_pk):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    student = (
        scoping.reviewable_students(request.user, course).filter(pk=student_pk).first()
    )
    if student is None:
        raise Http404  # non-existent OR out-of-reach -> 404, never 403 (manage convention)
    breakdown = build_student_breakdown(course, student)
    scope = request.GET.get("scope", "all")
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return render(
        request,
        "courses/manage/analytics_student.html",
        {
            "course": course,
            "student": student,
            "breakdown": breakdown,
            "back_url": f"{matrix_path}?{_expand_qs(scope, mode, expand_pks)}",
        },
    )
```

- [ ] **Step 5: Create the breakdown templates**

Create `templates/courses/manage/analytics_student.html`:

```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Breakdown" %} · {{ course.title }} · libli{% endblock %}
{% block content %}
<section class="manage breakdown">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Breakdown" %} —
      {{ student.display_name|default:student.username }}</h1>
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% trans "Analytics" %}</a>
  </header>
  <ul class="breakdown__tree">
    {% for item in breakdown.tree %}
      {% include "courses/manage/_breakdown_node.html" with item=item course=course %}
    {% endfor %}
  </ul>
</section>
{% endblock %}
```

Create `templates/courses/manage/_breakdown_node.html` (recursive, teacher-facing; mirrors `_outline_node.html` but renders quiz pills and never links a unit except the review cross-link):

```html
{% load i18n %}
<li class="breakdown-node breakdown-node--{{ item.node.kind }}">
  {% if item.is_unit %}
    {% if item.node.unit_type == "quiz" %}
      <div class="breakdown-unit">
        <span class="breakdown-unit__title" lang="{{ course.language }}">{{ item.node.title }}</span>
        {% with p=item.pill %}
          {% if p.kind == "scored" %}
            <span class="pill pill--scored">{% blocktrans with s=p.score|floatformat m=p.max_score|floatformat %}scored {{ s }}/{{ m }}{% endblocktrans %} ({{ p.percent }}%)</span>
          {% elif p.kind == "submitted" %}
            <span class="pill pill--submitted">{% trans "submitted" %}</span>
          {% elif p.kind == "awaiting" %}
            <span class="pill pill--awaiting">{% trans "awaiting review" %}</span>
            <a class="breakdown-unit__review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=p.submission_pk %}">{% trans "Review" %}</a>
          {% elif p.kind == "in_progress" %}
            <span class="pill pill--progress">{% trans "in progress" %}</span>
          {% else %}
            <span class="pill pill--none">{% trans "not started" %}</span>
          {% endif %}
        {% endwith %}
      </div>
    {% else %}
      <div class="breakdown-unit">
        <span class="breakdown-unit__title{% if item.completed %} is-done{% endif %}" lang="{{ course.language }}">{{ item.node.title }}</span>
        {% if item.completed %}<span class="badge badge--done" aria-label="{% trans 'Completed' %}">✓</span>{% endif %}
      </div>
    {% endif %}
  {% else %}
    <div class="breakdown-node__head">
      <span class="breakdown-node__title" lang="{{ course.language }}">{{ item.node.title }}</span>
      {% if item.required_total %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
    </div>
    {% if item.children %}
      <ul>{% for child in item.children %}{% include "courses/manage/_breakdown_node.html" with item=child course=course %}{% endfor %}</ul>
    {% endif %}
  {% endif %}
</li>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -k breakdown -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --fix courses/views_analytics.py courses/urls.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py courses/urls.py tests/test_analytics_views.py
git add courses/views_analytics.py courses/urls.py templates/courses/manage/analytics_student.html templates/courses/manage/_breakdown_node.html tests/test_analytics_views.py
git commit -m "feat(analytics): per-student breakdown page + review cross-link (3c-iii-a)"
```

---

### Task 7: Colour-bands page round-trips `expand`

`analytics_bands` (C1): read `expand` from GET, emit one hidden `expand` input per pk on the save/reset form, and have `_matrix_redirect` carry the posted `expand` pks back to the matrix — so saving/resetting colours never silently drops expansion (spec §4 C1).

**Files:**
- Modify: `courses/views_analytics.py` (`analytics_bands`, `_matrix_redirect`)
- Modify: `templates/courses/manage/analytics_bands.html`
- Test: `tests/test_analytics_views.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
@pytest.mark.django_db
def test_bands_get_carries_expand_hidden_inputs(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/colors/?scope=all&mode=progress&expand={ch.pk}"
    )
    assert f'<input type="hidden" name="expand" value="{ch.pk}">' in resp.content.decode()


@pytest.mark.django_db
def test_bands_save_redirect_preserves_expand(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {
            "scope": "all",
            "mode": "progress",
            "expand": [str(ch.pk)],
            "reset": "1",  # reset path is simplest; exercises the same redirect
        },
    )
    assert resp.status_code == 302
    assert f"expand={ch.pk}" in resp.url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k bands -v`
Expected: FAIL (no hidden expand input; redirect URL lacks `expand`).

- [ ] **Step 3: Update `_matrix_redirect` and `analytics_bands`**

In `courses/views_analytics.py`, replace `_matrix_redirect` (views_analytics.py:70-74):

```python
def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    expand_pks = _clean_expand(request.POST.getlist("expand"))
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{_expand_qs(scope, mode, expand_pks)}")
```

In `analytics_bands`, add `expand_pks` to the GET render context (the dict passed to `render`, after `"mode": ...`):

```python
            "scope": request.GET.get("scope", "all"),
            "mode": "results" if request.GET.get("mode") == "results" else "progress",
            "expand_pks": _clean_expand(request.GET.getlist("expand")),
```

- [ ] **Step 4: Update the bands template**

In `templates/courses/manage/analytics_bands.html`, after the hidden `mode` input (line 13), add:

```html
    {% for pk in expand_pks %}<input type="hidden" name="expand" value="{{ pk }}">{% endfor %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -k bands -v`
Expected: PASS (new tests + existing bands tests — `reset`/`save`/CSRF still green).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --fix courses/views_analytics.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py templates/courses/manage/analytics_bands.html tests/test_analytics_views.py
git commit -m "feat(analytics): colour-bands page round-trips expand state (3c-iii-a)"
```

---

### Task 8: Styling — chips, expandable headers, breakdown, status pills

Bespoke, token-driven, dark-mode-aware CSS (spec §6). No behavior change → verify visually with throwaway Playwright screenshots (light + dark), then delete the harness (the verify-UI-with-screenshots convention).

**Files:**
- Modify: `core/static/core/css/app.css` (append after the existing `.analytics__*` block, ~app.css:508)

- [ ] **Step 1: Add the CSS**

Append to `core/static/core/css/app.css`:

```css
/* --- Analytics drill-down (Phase 3c-iii-a) --- */
.analytics__chips{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;
  margin:0 0 .75rem;font-size:.8rem}
.analytics__chips-label{color:var(--text-secondary);text-transform:uppercase;
  letter-spacing:.05em;font-size:.72rem}
.analytics__chip{display:inline-flex;align-items:center;gap:.4rem;padding:.15rem .5rem;
  border:1px solid var(--border-strong);border-radius:999px;background:var(--surface-sunken)}
.analytics__chip-x{text-decoration:none;color:var(--text-secondary);font-weight:700;line-height:1}
.analytics__chip-x:hover{color:var(--text-primary)}
.analytics__expand{text-decoration:none;color:inherit;border-bottom:1px dotted currentColor}
.analytics__expand:hover{color:var(--primary)}

/* Per-student breakdown tree (reuses the outline visual language) */
.breakdown__tree,.breakdown-node ul{list-style:none;margin:0;padding:0}
.breakdown-node ul{margin-left:1rem;padding-left:.75rem;border-left:1px solid var(--border-default)}
.breakdown-node__head{display:flex;align-items:baseline;gap:.6rem;
  margin:.5rem 0 .25rem;font-weight:600}
.breakdown-unit{display:flex;align-items:center;gap:.6rem;padding:.25rem 0}
.breakdown-unit__title.is-done{color:var(--text-secondary)}
.breakdown-unit__review{font-size:.8rem}

/* Status pills */
.pill{display:inline-block;padding:.1rem .55rem;border-radius:999px;font-size:.75rem;
  font-weight:600;white-space:nowrap}
.pill--scored{background:var(--primary);color:#fff}
.pill--submitted{background:var(--surface-sunken);color:var(--text-secondary);
  border:1px solid var(--border-strong)}
.pill--awaiting{background:#f5b942;color:#3a2a00}
.pill--progress{background:var(--surface-sunken);color:var(--text-secondary);
  border:1px solid var(--border-strong)}
.pill--none{background:transparent;color:var(--text-tertiary);
  border:1px dashed var(--border-default)}
```

- [ ] **Step 2: Verify light + dark with a throwaway screenshot harness**

Write a temporary `tests/test_screenshot_drilldown.py` (mirroring `tests/test_e2e_analytics.py`'s login + fixture pattern) that opens an expanded matrix and a breakdown page, calls `page.screenshot(...)` in both color schemes (`page.emulate_media(color_scheme="dark")`), and saves PNGs to the scratchpad. Run it, **look at the images** (`SendUserFile` or open them), self-critique contrast/legibility (especially `.pill--awaiting` text on the amber, chips on dark), adjust the CSS if needed, then **delete** the harness.

Run: `uv run pytest tests/test_screenshot_drilldown.py -v` (then delete the file).

- [ ] **Step 3: Commit**

```bash
uv run ruff format core/static/core/css/app.css
git add core/static/core/css/app.css
git commit -m "style(analytics): drill-down chips, expandable headers, breakdown pills (3c-iii-a)"
```

---

### Task 9: i18n — Polish translations + compile

Every new UI string gets a PL translation; compile `.mo` (Global Constraints).

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

**New msgids introduced (verify all are present):** `Expanded:`, `Collapse`, `Breakdown`, `scored %(s)s/%(m)s`, `submitted`, `awaiting review`, `Review`, `in progress`, `not started` (`Analytics`, `Configure colours`, `Save`, `Completed`, `required` already exist from prior phases — reuse, don't duplicate).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Then open `locale/pl/LC_MESSAGES/django.po` and find the new msgids.

- [ ] **Step 2: Translate**

Fill each new msgstr (clear any `#, fuzzy` flag makemessages added) — suggested PL:
- `Expanded:` → `Rozwinięte:`
- `Collapse` → `Zwiń`
- `Breakdown` → `Szczegóły ucznia`
- `scored %(s)s/%(m)s` → `wynik %(s)s/%(m)s`
- `submitted` → `przesłano`
- `awaiting review` → `oczekuje na ocenę`
- `Review` → `Oceń`
- `in progress` → `w trakcie`
- `not started` → `nie rozpoczęto`

Grep the new msgids to confirm none are left empty or fuzzy:

Run: `uv run pytest -q` is not the check here — instead verify with: open the `.po`, search each msgid, confirm a non-empty non-fuzzy msgstr.

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages -l pl`
(If it reports "up to date" on a timestamp quirk, invoke `msgfmt locale/pl/LC_MESSAGES/django.po -o locale/pl/LC_MESSAGES/django.mo` directly.)

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(analytics): Polish strings for drill-down + breakdown (3c-iii-a)"
```

---

### Task 10: e2e — the real drill-down journey

One Playwright test driving real gestures: open matrix → expand a chapter → expand its section (recursive) → collapse via the chip ✕ → click a student → land on the breakdown → breadcrumb back to the same matrix state (spec §"Testing" e2e; the e2e-must-drive-real-UI lesson — no `page.evaluate` shortcuts).

**Files:**
- Modify: `tests/test_e2e_analytics.py` (append one test, reuse the `_login` helper + `pytestmark`)

- [ ] **Step 1: Write the e2e test**

Append to `tests/test_e2e_analytics.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_teacher_drills_into_columns_and_a_student(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2edrill")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    sec = ContentNodeFactory(course=course, kind="section", unit_type=None, parent=ch, title="Sec1")
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sec, obligatory=True, title="U1"
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2edrill")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")

    # Expand Ch1 (real click on the expandable column header link)
    page.get_by_role("link", name=re.compile(r"Ch1")).click()
    expect(page.locator(".analytics__chip")).to_contain_text("Ch1")
    # Now Sec1 is a column; expand it (recursive)
    page.get_by_role("link", name=re.compile(r"Sec1")).click()
    expect(page.locator("table.analytics__matrix")).to_contain_text("U1")

    # Collapse Ch1 via its chip ✕ (real click) -> back to the top level
    page.locator(".analytics__chip", has_text="Ch1").get_by_role("link").click()
    expect(page.locator(".analytics__chip")).to_have_count(0)

    # Drill into the student
    page.get_by_role("link", name="Ada L.").click()
    expect(page.locator(".manage__title")).to_contain_text("Ada L.")
    expect(page.locator(".badge--done")).to_be_visible()  # U1 completed ✓

    # Breadcrumb back to the matrix
    page.get_by_role("link", name=re.compile(r"Analytics")).click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_analytics.py -v`
Expected: PASS (both the existing 3c-ii e2e and the new drill-down journey).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_analytics.py
git commit -m "test(analytics): e2e — recursive drill-down + student breakdown (3c-iii-a)"
```

---

## Final verification (after all tasks)

- [ ] Full suite: `uv run pytest -q` → all pass (incl. e2e).
- [ ] Lint: `uv run ruff check` and `uv run ruff format --check` → clean.
- [ ] Migrations: `uv run python manage.py makemigrations --check --dry-run` → "No changes" (this slice adds no model fields).
- [ ] Spec coverage spot-check: frontier/partition (T1-2), submission_pk (T3), breakdown+pills (T4,T6), interactive matrix + per-row gating + state round-trip incl. bands (T5,T7), styling (T8), i18n (T9), e2e (T10).
