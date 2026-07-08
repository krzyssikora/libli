# Analytics matrix: raw/percent toggle + dash clarity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Percent/Raw toggle to the teacher analytics *Results* matrix, and disambiguate the overloaded `—` dash with a mode-aware caption plus a "not measured in this view" column badge.

**Architecture:** A new `values` GET param (`percent`|`raw`, default `percent`) is guarded like `mode`, threaded through every analytics URL builder, and passed to `build_results_matrix`, which relabels cells/overall/footer as `earned/max` while keeping `percent` for colouring. Column-measurability flags computed in `frontier_columns` drive a neutral badge on columns a mode can't measure; a mode-aware caption and a symmetric Progress empty-state complete the clarity work.

**Tech Stack:** Django (server-rendered templates, no JS for the toggle), Python `Decimal`, pytest + pytest-django, Playwright (e2e), gettext i18n (EN source + PL catalog).

## Global Constraints

- Run all Python tooling via `uv run` (ruff/pytest/manage.py are NOT on PATH). E.g. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`.
- New user-facing strings MUST be `{% trans %}`/`gettext`-wrapped and translated in BOTH EN (source) and PL (`locale/pl/LC_MESSAGES/django.po`).
- No hardcoded test passwords — use `tests.factories.TEST_PASSWORD`.
- Icons are monochrome `currentColor` line SVGs (shared `.icon` convention), never emoji.
- `_public_columns` (rollups.py:476) MUST keep returning exactly `{"node","title","expandable"}` — an existing test (`tests/test_analytics_rollups.py:462`) asserts that key set. Do NOT add flags there.
- `courses/gradebook.py:30-31` uses the same `builder` alias values-less; it MUST stay unchanged (relies on `build_results_matrix`'s `values="percent"` default).
- Django `{# #}` comments must be single-line; use `{% comment %}` for multi-line.
- One commit per task.

---

### Task 1: `_fmt_mark` helper + `_cell` label override

**Files:**
- Modify: `courses/rollups.py` (near `_cell`, ~lines 460-466)
- Test: `tests/test_analytics_rollups.py`

**Interfaces:**
- Produces: `_fmt_mark(value) -> str` (Decimal→compact fixed-point string, no exponent, no trailing zeros); `_cell(percent, label=None) -> dict` (optional label override, `percent` still stored for colouring).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analytics_rollups.py` (import `_cell` and `_fmt_mark` at top with the other `courses.rollups` imports):

```python
from courses.rollups import _cell
from courses.rollups import _fmt_mark


@pytest.mark.parametrize(
    "value,expected",
    [
        ("4", "4"), ("4.0", "4"), ("4.5", "4.5"), ("4.50", "4.5"),
        ("0", "0"), ("100", "100"), ("100.0", "100"),
        ("120", "120"), ("150", "150"), ("120.50", "120.5"),
    ],
)
def test_fmt_mark_compact_no_exponent(value, expected):
    assert _fmt_mark(Decimal(value)) == expected


def test_cell_label_override_keeps_percent():
    c = _cell(68, label="34/50")
    assert c == {"percent": 68, "label": "34/50"}
    # default path unchanged
    assert _cell(68) == {"percent": 68, "label": "68%"}
    assert _cell(None) == {"percent": None, "label": "—"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py::test_fmt_mark_compact_no_exponent tests/test_analytics_rollups.py::test_cell_label_override_keeps_percent -v`
Expected: FAIL (`ImportError` / `_fmt_mark` not defined; `_cell()` takes 1 positional arg).

- [ ] **Step 3: Implement**

In `courses/rollups.py`, add `_fmt_mark` just above `_cell`, and extend `_cell`:

```python
def _fmt_mark(value):
    """Decimal mark -> compact fixed-point string: no exponent notation (`:f`
    guarantees fixed-point, so Decimal('1E+2') renders '100'), no trailing zeros
    (normalize)."""
    return f"{Decimal(value).normalize():f}"


def _cell(percent, label=None):
    return {
        "percent": percent,
        "label": label
        if label is not None
        else (f"{percent}%" if percent is not None else "—"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -k "fmt_mark or cell_label_override" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): add _fmt_mark + _cell label override"
```

---

### Task 2: `build_results_matrix` raw mode (cells, overall, footer)

**Files:**
- Modify: `courses/rollups.py` `build_results_matrix` (lines 530-584)
- Test: `tests/test_analytics_rollups.py`

**Interfaces:**
- Consumes: `_fmt_mark`, `_cell(percent, label=...)` (Task 1).
- Produces: `build_results_matrix(course, students, expanded=frozenset(), values="percent")`. In `values="raw"`: each body cell `label` = `"<earned>/<mx>"` (percent still set); `row["overall"]` label = `"<tot_e>/<tot_m>"`; `averages[i]`/`overall_average` = class totals `Σearned/Σmx` (percent from those totals); empty cells (`mx==0`) stay `label="—"`, `percent=None`. Also returns `has_lessons` (see Task 3 for the flag source; add the key here now as `any(c["lesson_pks"] for c in columns)`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analytics_rollups.py` (reuse existing `_chapter`, `_quiz`, `_auto_q` helpers):

```python
def _counted_sub(student, unit, score, mx):
    QuizSubmission.objects.create(
        student=student, unit=unit, status="submitted",
        score=Decimal(score), max_score=Decimal(mx),
    )


@pytest.mark.django_db
def test_results_matrix_raw_cell_and_overall_labels():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "50")
    s1 = UserFactory()
    _counted_sub(s1, qz, "34", "50")
    m = build_results_matrix(course, [s1], values="raw")
    cell = m["rows"][0]["cells"][0]
    assert cell["label"] == "34/50"
    assert cell["percent"] == 68  # still present for colouring
    assert m["rows"][0]["overall"]["label"] == "34/50"
    # percent-mode parity for the same data
    p = build_results_matrix(course, [s1])
    assert m["rows"][0]["cells"][0]["percent"] == p["rows"][0]["cells"][0]["percent"]


@pytest.mark.django_db
def test_results_matrix_raw_student_specific_denominator():
    course = CourseFactory()
    ch = _chapter(course)
    q1, q2 = _quiz(course, ch), _quiz(course, ch)
    _auto_q(q1, "10"); _auto_q(q2, "10")
    s_full, s_partial = UserFactory(), UserFactory()
    _counted_sub(s_full, q1, "8", "10"); _counted_sub(s_full, q2, "6", "10")
    _counted_sub(s_partial, q1, "5", "10")  # only took q1
    m = build_results_matrix(course, [s_full, s_partial], values="raw")
    # single un-expanded column aggregates both quizzes
    assert m["rows"][0]["cells"][0]["label"] == "14/20"
    assert m["rows"][1]["cells"][0]["label"] == "5/10"   # denominator differs


@pytest.mark.django_db
def test_results_matrix_raw_empty_cell():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")
    s = UserFactory()  # no submission
    m = build_results_matrix(course, [s], values="raw")
    cell = m["rows"][0]["cells"][0]
    assert cell["label"] == "—" and cell["percent"] is None


@pytest.mark.django_db
def test_results_matrix_raw_footer_is_class_totals():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")
    s1, s2 = UserFactory(), UserFactory()
    _counted_sub(s1, qz, "8", "10"); _counted_sub(s2, qz, "6", "10")
    m = build_results_matrix(course, [s1, s2], values="raw")
    assert m["averages"][0]["label"] == "14/20"      # Σearned/Σmx, not avg%
    assert m["averages"][0]["percent"] == 70         # for colouring
    assert m["overall_average"]["label"] == "14/20"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k "results_matrix_raw" -v`
Expected: FAIL (`values` unexpected kwarg / labels are `%`).

- [ ] **Step 3: Implement**

Replace the body of `build_results_matrix` (rollups.py:530-584) with:

```python
def build_results_matrix(course, students, expanded=frozenset(), values="percent"):
    """Quiz score %, students × frontier columns. Excludes not-started /
    in-progress / awaiting-review from the ratio (neutral, not 0). No N+1.
    values="raw" relabels cells/overall/footer as earned/max (percent kept for
    colouring); footer becomes class totals Σearned/Σmx."""
    students = list(students)
    fc = frontier_columns(course, expanded)
    columns = fc["columns"]
    all_quiz_pks = set()
    for c in columns:
        all_quiz_pks |= c["quiz_pks"]
    subs = list(
        QuizSubmission.objects.filter(unit_id__in=all_quiz_pks, student__in=students)
    )
    _, total_review, reviewed_counts = _quiz_review_maps(all_quiz_pks, subs)
    counted = {}  # (student_id, unit_id) -> (score, max)
    for sub in subs:
        if submission_is_counted(sub, total_review, reviewed_counts):
            counted[(sub.student_id, sub.unit_id)] = (
                sub.score or Decimal("0"),
                sub.max_score or Decimal("0"),
            )
    raw = values == "raw"

    def _score_cell(earned, mx):
        pct = _pct(earned, mx)
        if raw:
            return _cell(pct, label=f"{_fmt_mark(earned)}/{_fmt_mark(mx)}")
        return _cell(pct)

    col_e = [Decimal("0")] * len(columns)  # raw-mode per-column accumulators
    col_m = [Decimal("0")] * len(columns)
    ov_e = ov_m = Decimal("0")
    rows = []
    for s in students:
        cells = []
        tot_e = tot_m = Decimal("0")
        for i, c in enumerate(columns):
            earned = Decimal("0")
            mx = Decimal("0")
            for uid in c["quiz_pks"]:
                pair = counted.get((s.id, uid))
                if pair is not None:
                    earned += pair[0]
                    mx += pair[1]
            if mx > 0:
                tot_e += earned
                tot_m += mx
                col_e[i] += earned
                col_m[i] += mx
                cells.append(_score_cell(earned, mx))
            else:
                cells.append(_cell(None))
        if tot_m > 0:
            ov_e += tot_e
            ov_m += tot_m
            overall = _score_cell(tot_e, tot_m)
        else:
            overall = _cell(None)
        rows.append({"student": s, "cells": cells, "overall": overall})

    if raw:
        averages = [
            _score_cell(col_e[i], col_m[i]) if col_m[i] > 0 else _cell(None)
            for i in range(len(columns))
        ]
        overall_average = _score_cell(ov_e, ov_m) if ov_m > 0 else _cell(None)
    else:
        averages = [
            _avg_cell([r["cells"][i]["percent"] for r in rows])
            for i in range(len(columns))
        ]
        overall_average = _avg_cell([r["overall"]["percent"] for r in rows])

    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "has_quizzes": bool(all_quiz_pks),
        "has_lessons": any(c["lesson_pks"] for c in columns),
        "expanded_nodes": fc["expanded_nodes"],
        "header_rows": fc["header_rows"],
        "total_rows": fc["total_rows"],
        "mode": "results",
    }
```

- [ ] **Step 4: Run to verify pass (and no regression on existing results tests)**

Run: `uv run pytest tests/test_analytics_rollups.py -v`
Expected: PASS (new raw tests + all existing results/percent tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): raw-mode cells/overall/footer in build_results_matrix"
```

---

### Task 3: Column + matrix measurability flags

**Files:**
- Modify: `courses/rollups.py` `frontier_columns` (leaf branch ~412-433) and `build_progress_matrix` return (~517-527)
- Test: `tests/test_analytics_rollups.py`

**Interfaces:**
- Produces: each leaf **column** dict and each **leaf header cell** dict gains `has_lessons`/`has_quizzes` booleans; `build_progress_matrix` return gains `has_lessons` (`any(c["lesson_pks"] for c in columns)`). Spanning (non-leaf) header cells do NOT get the flags.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_frontier_leaf_cells_carry_measurability_flags():
    course = CourseFactory()
    ch_quiz = _chapter(course); _quiz(course, ch_quiz)
    ch_lesson = _chapter(course); _lesson(course, ch_lesson)
    ch_extra = _chapter(course); _lesson(course, ch_extra, obligatory=False)
    fc = frontier_columns(course, frozenset())
    by_pk = {c["node"].pk: c for c in fc["columns"]}
    assert (by_pk[ch_quiz.pk]["has_quizzes"], by_pk[ch_quiz.pk]["has_lessons"]) == (True, False)
    assert (by_pk[ch_lesson.pk]["has_quizzes"], by_pk[ch_lesson.pk]["has_lessons"]) == (False, True)
    # non-obligatory-lesson-only column: both False
    assert (by_pk[ch_extra.pk]["has_quizzes"], by_pk[ch_extra.pk]["has_lessons"]) == (False, False)
    # leaf header cells mirror the flags
    leaf_cells = {c["node"].pk: c for row in fc["header_rows"] for c in row if c["is_leaf"]}
    assert leaf_cells[ch_quiz.pk]["has_quizzes"] is True
    assert leaf_cells[ch_lesson.pk]["has_lessons"] is True


@pytest.mark.django_db
def test_progress_matrix_exposes_has_lessons():
    course = CourseFactory()
    ch = _chapter(course); _lesson(course, ch)
    m = build_progress_matrix(course, [UserFactory()])
    assert m["has_lessons"] is True
    quizless = CourseFactory()
    chq = _chapter(quizless); _quiz(quizless, chq)
    assert build_progress_matrix(quizless, [UserFactory()])["has_lessons"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k "measurability_flags or exposes_has_lessons" -v`
Expected: FAIL (`KeyError: 'has_lessons'`).

- [ ] **Step 3: Implement**

In `frontier_columns`, the leaf `else` branch (rollups.py:412-433) — compute the flags once and attach to both dicts:

```python
            else:
                lesson_pks, quiz_pks = subtree_pks(node)
                has_lessons = bool(lesson_pks)
                has_quizzes = bool(quiz_pks)
                columns.append(
                    {
                        "node": node,
                        "title": node.title,
                        "lesson_pks": lesson_pks,
                        "quiz_pks": quiz_pks,
                        "has_lessons": has_lessons,
                        "has_quizzes": has_quizzes,
                        "expandable": bool(kids),
                        "depth": depth,
                    }
                )
                cells_by_depth.setdefault(depth, []).append(
                    {
                        "node": node,
                        "title": node.title,
                        "is_leaf": True,
                        "expandable": bool(kids),
                        "has_lessons": has_lessons,
                        "has_quizzes": has_quizzes,
                        "depth": depth,
                        "colspan": 1,
                    }
                )
                leaves += 1
```

In `build_progress_matrix` return dict, add the `has_lessons` key next to `has_quizzes`:

```python
        "has_quizzes": any(c["quiz_pks"] for c in columns),
        "has_lessons": any(c["lesson_pks"] for c in columns),
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_analytics_rollups.py -v`
Expected: PASS (incl. the `_public_columns` key-set test at line ~462, which is untouched).

- [ ] **Step 5: Commit**

```bash
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): column + matrix measurability flags"
```

---

### Task 4: Thread `values` through the views (matrix, decorate-links, redirect, student)

**Files:**
- Modify: `courses/views_analytics.py` (`_expand_qs` ~123, `_decorate_links` ~139, `analytics_matrix` ~42-100, `_matrix_redirect` ~103-109, `analytics_student` ~171-198)
- Test: `tests/test_analytics_views.py` (update line 446-449 test; add new tests)

**Interfaces:**
- Consumes: `build_results_matrix(..., values)` (Task 2).
- Produces: `_expand_qs(scope, mode, expand_pks, subset_pks, values)` (required 5th positional; emits `values=raw` only when raw). `_decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks, values)`. `analytics_matrix` adds `values`, `percent_url`, `raw_url` to context. `_matrix_redirect` reads `values` from POST. `analytics_student` re-threads `values` into `back_url`.

- [ ] **Step 1: Update the existing test + write new failing tests**

Replace `tests/test_analytics_views.py:446-449` with:

```python
def test_expand_qs_emits_sorted_student_and_omits_when_empty():
    qs = _expand_qs("all", "progress", [], {3, 1, 2}, "percent")
    assert "student=1&student=2&student=3" in qs
    assert "student" not in _expand_qs("all", "progress", [], set(), "percent")
    # values emitted only when raw
    assert "values=raw" in _expand_qs("all", "results", [], set(), "raw")
    assert "values" not in _expand_qs("all", "results", [], set(), "percent")
```

Add new tests (reuse `_course_with_lesson`, `make_login`; add a quiz helper import as needed):

```python
def _course_with_quiz(owner):
    from courses.models import QuizSubmission  # noqa: F401
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    qz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch)
    return course, ch, qz


@pytest.mark.django_db
def test_values_raw_round_trips_and_defaults(client):
    from decimal import Decimal
    from courses.models import Enrollment, QuizSubmission
    owner = make_login(client, "owner")
    course, ch, qz = _course_with_quiz(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    QuizSubmission.objects.create(
        student=student, unit=qz, status="submitted",
        score=Decimal("34"), max_score=Decimal("50"),
    )
    raw = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results&values=raw")
    assert raw.context["values"] == "raw"
    assert b"34/50" in raw.content
    pct = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert pct.context["values"] == "percent"
    assert b"68%" in pct.content
    # garbage collapses to percent
    junk = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results&values=banana")
    assert junk.context["values"] == "percent"


@pytest.mark.django_db
def test_values_preserved_across_links(client):
    owner = make_login(client, "owner")
    course, ch, qz = _course_with_quiz(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results&values=raw")
    for key in ("progress_url", "results_url", "clear_url", "colours_url",
                "percent_url", "raw_url"):
        pass
    # percent_url intentionally drops values; the rest carry it
    assert "values=raw" in resp.context["results_url"]
    assert "values=raw" in resp.context["colours_url"]
    assert "values=raw" in resp.context["raw_url"]
    assert "values" not in resp.context["percent_url"]


@pytest.mark.django_db
def test_progress_mode_ignores_values(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=progress&values=raw")
    assert resp.status_code == 200
    # progress builder ignores values; no Percent/Raw toggle rendered
    assert b"Number format" not in resp.content


@pytest.mark.django_db
def test_student_back_url_carries_values(client):
    from courses.models import Enrollment
    owner = make_login(client, "owner")
    course, ch, qz = _course_with_quiz(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/student/{student.pk}/?mode=results&values=raw"
    )
    assert "values=raw" in resp.context["back_url"]
```

> Note: confirm the per-student URL path by checking `courses/urls.py` (`manage_analytics_student`); adjust the literal path if it differs.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "expand_qs or values_raw or preserved_across or ignores_values or back_url_carries" -v`
Expected: FAIL (`_expand_qs` missing arg / `values` not in context).

- [ ] **Step 3: Implement**

`_expand_qs` (views_analytics.py:123):

```python
def _expand_qs(scope, mode, expand_pks, subset_pks, values):
    """Querystring preserving scope/mode/values + expand pks + student subset (all
    repeatable). subset emitted sorted; empty subset emits no `student`. `values`
    is required (fails loudly at call sites) and emitted ONLY when "raw"."""
    data = {
        "scope": scope,
        "mode": mode,
        "expand": list(expand_pks),
        "student": sorted(subset_pks),
    }
    if values == "raw":
        data["values"] = "raw"
    return urlencode(data, doseq=True)
```

`_matrix_redirect` (103-109) — read and thread `values`:

```python
def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    values = "raw" if request.POST.get("values") == "raw" else "percent"
    expand_pks = _clean_expand(request.POST.getlist("expand"))
    subset_pks = _clean_expand(request.POST.getlist("student"))
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{_expand_qs(scope, mode, expand_pks, subset_pks, values)}")
```

`_decorate_links` (139) — add `values` param and thread it into the three inner calls:

```python
def _decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks, values):
    base_pks = [en["pk"] for en in matrix["expanded_nodes"]]
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    for hrow in matrix["header_rows"]:
        for cell in hrow:
            if cell["is_leaf"]:
                if cell["expandable"]:
                    expand_pks = base_pks + [cell["node"].pk]
                    expand_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
                    cell["expand_url"] = f"{matrix_path}?{expand_qs}"
            else:
                rest = [p for p in base_pks if p != cell["node"].pk]
                cell["collapse_url"] = (
                    f"{matrix_path}?{_expand_qs(scope, mode, rest, subset_pks, values)}"
                )
    for row in matrix["rows"]:
        if row["student"].pk in reviewable_ids:
            student_path = reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": row["student"].pk},
            )
            row["breakdown_url"] = (
                f"{student_path}?{_expand_qs(scope, mode, base_pks, subset_pks, values)}"
            )
    return base_pks
```

`analytics_matrix` (42-100) — parse `values`, branch the builder, pass `values` to `_decorate_links`, build the URLs, extend context. Apply these edits:

```python
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    values = "raw" if request.GET.get("values") == "raw" else "percent"
```

Replace the builder call (65-66):

```python
    if mode == "results":
        matrix = build_results_matrix(course, students, expand_pks, values)
    else:
        matrix = build_progress_matrix(course, students, expand_pks)
```

Update the `_decorate_links` call (72) to pass `values`:

```python
    base_pks = _decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks, values)
```

Update the querystring builders (76-79) to thread `values`, and add percent/raw:

```python
    clear_url = f"{matrix_path}?{_expand_qs(scope, mode, base_pks, set(), values)}"
    progress_qs = _expand_qs(scope, "progress", base_pks, subset_pks, values)
    results_qs = _expand_qs(scope, "results", base_pks, subset_pks, values)
    colours_qs = _expand_qs(scope, mode, base_pks, subset_pks, values)
    percent_qs = _expand_qs(scope, mode, base_pks, subset_pks, "percent")
    raw_qs = _expand_qs(scope, mode, base_pks, subset_pks, "raw")
```

Extend the context dict (add these keys alongside the existing ones):

```python
            "values": values,
            "percent_url": f"{matrix_path}?{percent_qs}",
            "raw_url": f"{matrix_path}?{raw_qs}",
```

`analytics_student` (183-188) — parse and thread `values`:

```python
    scope = request.GET.get("scope", "all")
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    values = "raw" if request.GET.get("values") == "raw" else "percent"
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    subset_pks = _clean_expand(request.GET.getlist("student"))
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (new + all existing view tests). Then `uv run pytest tests/test_analytics_scoping.py tests/test_grouping_analytics_links.py -q` to catch cross-module `_expand_qs`/view regressions.

- [ ] **Step 5: Commit**

```bash
git add courses/views_analytics.py tests/test_analytics_views.py
git commit -m "feat(analytics): thread values through matrix views + links"
```

---

### Task 5: Colour-bands `values` round-trip

**Files:**
- Modify: `courses/views_analytics.py` `analytics_bands` context (~242-246)
- Modify: `templates/courses/manage/analytics_bands.html` (hidden inputs block ~12-15)
- Test: `tests/test_analytics_views.py`

**Interfaces:**
- Consumes: `_matrix_redirect` reading `values` from POST (Task 4).
- Produces: `analytics_bands` context key `values` (string, default `""`); a hidden `values` input in the bands form so Save/Reset POST it back.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_bands_form_carries_values_and_redirect_preserves(client):
    owner = make_pa(client, "pa")  # PA passes can_manage_course
    course, ch, qz = _course_with_quiz(owner)
    # GET the bands page in raw context -> hidden input present
    # (route name manage_analytics_bands is served at .../analytics/colors/)
    page = client.get(
        f"/manage/courses/{course.slug}/analytics/colors/?mode=results&values=raw"
    )
    assert page.context["values"] == "raw"
    assert b'name="values"' in page.content
    # POST reset -> redirect Location carries values=raw
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {"scope": "all", "mode": "results", "values": "raw", "reset": "1"},
    )
    assert resp.status_code == 302 and "values=raw" in resp["Location"]
```

> Confirm the bands URL path via `courses/urls.py` (`manage_analytics_bands`) and adjust if needed.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_analytics_views.py -k "bands_form_carries_values" -v`
Expected: FAIL (`values` not in context / not in content).

- [ ] **Step 3: Implement**

In `analytics_bands` context (views_analytics.py, the render dict ~242-246), add:

```python
            "values": src.get("values", ""),
```

In `templates/courses/manage/analytics_bands.html`, after line 13 (`<input type="hidden" name="mode" ...>`), add:

```html
    <input type="hidden" name="values" value="{{ values }}">
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_analytics_views.py -k "bands" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/analytics_bands.html tests/test_analytics_views.py
git commit -m "feat(analytics): colour-bands form round-trips values"
```

---

### Task 6: Template — Percent/Raw toggle, hidden form input, export label

**Files:**
- Modify: `templates/courses/manage/analytics_matrix.html` (form ~47-50, controls ~59-64, export ~23-24)
- Modify: `core/static/core/css/app.css` (no new toggle CSS needed — reuses `.analytics__toggle`; verify only)
- Test: `tests/test_analytics_views.py`

**Interfaces:**
- Consumes: `values`, `percent_url`, `raw_url` context (Task 4).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_toggle_and_export_label_render(client):
    owner = make_login(client, "owner")
    course, ch, qz = _course_with_quiz(owner)
    r = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results&values=raw")
    assert b"Number format" in r.content          # new toggle group aria-label
    assert b">Raw<" in r.content and b">Percent<" in r.content
    assert b"This matrix view (percentages)" in r.content
    # toggle hidden from progress mode
    p = client.get(f"/manage/courses/{course.slug}/analytics/?mode=progress")
    assert b"Number format" not in p.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_analytics_views.py -k "toggle_and_export_label" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `analytics_matrix.html`, after line 49 (`<input type="hidden" name="scope_rendered" ...>`), add the hidden values input:

```html
    <input type="hidden" name="values" value="{{ values }}">
```

After the existing metric-toggle `</span>` (line 64), add the Percent/Raw control:

```html
      {% if mode == "results" %}
      <span class="analytics__toggle" role="group" aria-label="{% trans 'Number format' %}">
        <a class="btn btn--small {% if values != 'raw' %}is-active{% endif %}"
           href="{{ percent_url }}">{% trans "Percent" %}</a>
        <a class="btn btn--small {% if values == 'raw' %}is-active{% endif %}"
           href="{{ raw_url }}">{% trans "Raw" %}</a>
      </span>
      {% endif %}
```

Rename the export radio label (line 24): `{% trans "This matrix view" %}` → `{% trans "This matrix view (percentages)" %}`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_analytics_views.py -k "toggle_and_export_label" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/analytics_matrix.html tests/test_analytics_views.py
git commit -m "feat(analytics): Percent/Raw toggle + export label"
```

---

### Task 7: Template — badges, caption, Progress empty-state, suppression + CSS

**Files:**
- Modify: `templates/courses/manage/analytics_matrix.html` (header leaf cell ~95-108, after legend ~75, empty-state ~149-151)
- Modify: `core/static/core/css/app.css` (add `.analytics__badge`, `.analytics__colhead--unmeasured`, `.analytics__caption`)
- Test: `tests/test_analytics_views.py`

**Interfaces:**
- Consumes: leaf header cell `has_lessons`/`has_quizzes` + matrix `has_lessons`/`has_quizzes` (Tasks 2-3).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_badges_and_caption(client):
    from courses.models import Enrollment
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    ch_l = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Lessons")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch_l, obligatory=True)
    ch_q = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Quizzes")
    ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch_q)
    # A student MUST be enrolled or matrix.rows is empty and the header cells
    # (where badges live) never render — the "No students in this scope." branch
    # wins instead.
    Enrollment.objects.create(student=UserFactory(), course=course)
    # Results: the lesson-only column is "not scored"; caption present
    r = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert b"Not scored in this view" in r.content
    assert b"not attempted yet" in r.content
    # Progress: the quiz-only column is "not part of progress tracking"
    p = client.get(f"/manage/courses/{course.slug}/analytics/?mode=progress")
    assert b"Not part of progress tracking" in p.content
    assert b"not tracked as progress" in p.content


@pytest.mark.django_db
def test_badge_suppressed_and_progress_empty_state(client):
    from courses.models import Enrollment
    owner = make_login(client, "owner")
    # Quiz-less course: Results has no measurable column -> badges suppressed;
    # Progress default shows the new empty-state and no badges.
    course, ch, les = _course_with_lesson(owner)  # obligatory lesson, no quiz
    Enrollment.objects.create(student=UserFactory(), course=course)  # else rows empty
    r = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert b"Not scored in this view" not in r.content        # suppressed
    assert b"No quizzes in this course yet." in r.content
    # Progress on a quiz-only course -> new empty-state, no badges
    q = CourseFactory(owner=owner)
    chq = ContentNodeFactory(course=q, kind="chapter", unit_type=None, parent=None)
    ContentNodeFactory(course=q, kind="unit", unit_type="quiz", parent=chq)
    Enrollment.objects.create(student=UserFactory(), course=q)  # else rows empty
    pg = client.get(f"/manage/courses/{q.slug}/analytics/?mode=progress")
    assert b"No progress-tracked lessons in this course yet." in pg.content
    assert b"Not part of progress tracking" not in pg.content  # suppressed
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "badges_and_caption or badge_suppressed" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `analytics_matrix.html`, add the muted class + badge to the leaf header cell. Change the opening `<th class="analytics__colhead...">` (95-98) to append the unmeasured class:

```html
                {% for cell in hrow %}
                  <th class="analytics__colhead{% if not cell.is_leaf %} analytics__group{% endif %}{% if cell.is_leaf and mode == 'progress' and matrix.has_lessons and not cell.has_lessons %} analytics__colhead--unmeasured{% endif %}{% if cell.is_leaf and mode == 'results' and matrix.has_quizzes and not cell.has_quizzes %} analytics__colhead--unmeasured{% endif %}"
                      colspan="{{ cell.colspan }}" rowspan="{{ cell.rowspan }}"
                      style="top:calc(var(--ahead-h) * {{ forloop.parentloop.counter0 }})">
```

Inside the `{% if cell.is_leaf %}` block, after the title `<a>`/`<span>` (right before the `{% else %}` for spanning cells at line 103), add the badge:

```html
                      {% if mode == "progress" and matrix.has_lessons and not cell.has_lessons %}<span
                         class="analytics__badge icon" role="img"
                         aria-label="{% trans 'Not part of progress tracking' %}"
                         title="{% trans 'Not part of progress tracking' %}"><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6"/><line x1="4" y1="12" x2="12" y2="4"/></svg></span>{% endif %}
                      {% if mode == "results" and matrix.has_quizzes and not cell.has_quizzes %}<span
                         class="analytics__badge icon" role="img"
                         aria-label="{% trans 'Not scored in this view' %}"
                         title="{% trans 'Not scored in this view' %}"><svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6"/><line x1="4" y1="12" x2="12" y2="4"/></svg></span>{% endif %}
```

Add the caption after the legend `</ul>` (line 75), OUTSIDE the rows/columns conditional:

```html
    <p class="muted analytics__caption">
      {% if mode == "results" %}
        {% if matrix.has_quizzes %}{% trans "— = not attempted yet, or awaiting review (badged columns aren't scored in this view)." %}{% else %}{% trans "— = not attempted yet, or awaiting review." %}{% endif %}
      {% else %}
        {% if matrix.has_lessons %}{% trans "— = not tracked as progress here (badged columns aren't part of progress; quiz scores appear under Results)." %}{% else %}{% trans "— = not tracked as progress here; quiz scores appear under Results." %}{% endif %}
      {% endif %}
    </p>
```

Extend the empty-state block (149-151) to add the symmetric Progress paragraph:

```html
      {% if mode == "results" and not matrix.has_quizzes %}
        <p class="muted">{% trans "No quizzes in this course yet." %}</p>
      {% elif mode == "progress" and not matrix.has_lessons %}
        <p class="muted">{% trans "No progress-tracked lessons in this course yet." %}</p>
      {% endif %}
```

In `core/static/core/css/app.css`, near the other `.analytics__*` rules (~610-668), add:

```css
.analytics__badge{display:inline-flex;vertical-align:middle;margin-inline-start:.25rem;color:var(--muted)}
.analytics__colhead--unmeasured{opacity:.72}
.analytics__caption{margin:.25rem 0 .5rem;font-size:.85em}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_analytics_views.py -k "badges_and_caption or badge_suppressed" -v`
Expected: PASS.

- [ ] **Step 5: Verify UI with screenshots (light + dark)**

Per the "verify UI with screenshots" convention, load the Results and Progress matrices for a mixed course in light and dark; confirm the badge is legible, the caption reads clearly, and the unmeasured column is subtly muted. Self-critique before proceeding.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/analytics_matrix.html core/static/core/css/app.css tests/test_analytics_views.py
git commit -m "feat(analytics): dash caption + not-measured column badges"
```

---

### Task 8: e2e click-path + i18n (PL) + full-suite DoD

**Files:**
- Modify: `tests/test_e2e_analytics.py` (add a toggle test)
- Modify: `locale/pl/LC_MESSAGES/django.po` (translate new strings)
- Test: the e2e test itself; then the i18n catalog tests

**Interfaces:**
- Consumes: the rendered toggle + raw cells (Tasks 2-7).

- [ ] **Step 1: Write the failing e2e test**

Append to `tests/test_e2e_analytics.py` (mirrors the existing `_login` fixture + factory style at the top of that file):

```python
@pytest.mark.django_db(transaction=True)
def test_teacher_toggles_raw_and_percent(page, live_server, client):
    from decimal import Decimal
    from courses.models import Enrollment, QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2eraw")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    qz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch, title="Q1")
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    QuizSubmission.objects.create(
        student=student, unit=qz, status="submitted",
        score=Decimal("34"), max_score=Decimal("50"),
    )

    _login(page, live_server, "e2eraw")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/?mode=results")
    expect(page.locator("table.analytics__matrix")).to_contain_text("68%")
    # Real click on the Raw toggle link
    page.get_by_role("link", name="Raw").click()
    expect(page).to_have_url(re.compile(r"values=raw"))
    expect(page.locator("table.analytics__matrix")).to_contain_text("34/50")
    # Back to Percent
    page.get_by_role("link", name="Percent").click()
    expect(page.locator("table.analytics__matrix")).to_contain_text("68%")
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_analytics.py::test_teacher_toggles_raw_and_percent -v`
Expected: PASS (driving the real toggle link). If the e2e marker requires a browser install, follow the repo's existing e2e run convention.

- [ ] **Step 3: Regenerate + translate the PL catalog**

Run: `uv run python manage.py makemessages -l pl` (mind the fuzzy-flag gotcha — review diffs). Then in `locale/pl/LC_MESSAGES/django.po`, fill `msgstr` for every new string:

- "Percent" → "Procenty"
- "Raw" → "Punkty"
- "Number format" → "Format liczb"
- "This matrix view (percentages)" → "Ten widok macierzy (procenty)"
- "Not part of progress tracking" → "Nieuwzględniane w postępach"
- "Not scored in this view" → "Nieoceniane w tym widoku"
- "No progress-tracked lessons in this course yet." → "Brak lekcji wliczanych do postępów w tym kursie."
- "— = not attempted yet, or awaiting review (badged columns aren't scored in this view)." → "— = jeszcze nie podjęto lub oczekuje na sprawdzenie (oznaczone kolumny nie są oceniane w tym widoku)."
- "— = not attempted yet, or awaiting review." → "— = jeszcze nie podjęto lub oczekuje na sprawdzenie."
- "— = not tracked as progress here (badged columns aren't part of progress; quiz scores appear under Results)." → "— = nieuwzględniane w postępach tutaj (oznaczone kolumny nie liczą się do postępów; wyniki quizów są w zakładce Wyniki)."
- "— = not tracked as progress here; quiz scores appear under Results." → "— = nieuwzględniane w postępach tutaj; wyniki quizów są w zakładce Wyniki."

Then compile: `uv run python manage.py compilemessages -l pl`.

- [ ] **Step 4: Run the i18n catalog tests + full suite (DoD)**

Run: `uv run pytest tests/ -k "i18n or catalog or messages" -q` (confirm no obsolete `#~` entries and no missing PL translations), then the full suite `uv run pytest -q`, then `uv run ruff check` and `uv run ruff format --check`.
Expected: all green; catalogs clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_analytics.py locale/pl/LC_MESSAGES/django.po
git commit -m "test+i18n(analytics): raw/percent e2e + PL translations"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- `values` param, guard, results-only — Tasks 4, 6. ✓
- Builder-call branches on mode — Task 4. ✓
- `_expand_qs` required 5th arg + all call sites (clear/progress/results/colours/percent/raw/decorate/redirect/student) — Task 4. ✓
- `_decorate_links` gains `values` — Task 4. ✓
- Main GET form hidden input + context — Tasks 4, 6. ✓
- Colour-bands view/template carry values; `_matrix_redirect` re-emits — Tasks 4, 5. ✓
- `analytics_student` re-threads `back_url` only — Task 4. ✓
- Raw cell/overall labels via `_fmt_mark`; percent kept; empty `—` — Tasks 1, 2. ✓
- Raw footer = class totals w/ new accumulators — Task 2. ✓
- `_fmt_mark` exponent-safe (≥100 tests) — Task 1. ✓
- Neutral "not measured" badge, `is_leaf` guard, symmetric suppression via matrix flags — Tasks 3, 7. ✓
- Mode-aware caption outside conditional + variant when unmeasurable — Task 7. ✓
- Symmetric Progress empty-state — Task 7. ✓
- Distinct aria-label — Task 6. ✓
- `gradebook.py` alias stays values-less — Global Constraints (no task touches it). ✓
- Export label rename — Task 6. ✓
- Existing `_expand_qs` 4-arg test updated — Task 4. ✓
- i18n EN+PL — Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows real code. e2e/i18n paths call out the one "confirm the URL literal / run convention" checks explicitly rather than hand-waving. ✓

**Type consistency:** `_expand_qs(scope, mode, expand_pks, subset_pks, values)` and `_decorate_links(..., subset_pks, values)` used consistently across Task 4; `values` is always the string `"percent"`/`"raw"`; matrix flags `has_lessons`/`has_quizzes` named identically in Tasks 2/3/7. ✓
