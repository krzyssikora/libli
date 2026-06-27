# Phase 3c-ii — Analytics Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-course teacher analytics matrix — scoped students (rows) × top-level course components (columns), each cell a percentage colored by a per-course band table, with a Progress↔Results toggle and an all/group/collection scope picker, plus a per-course color-band config UI.

**Architecture:** Pure cross-student aggregation builders in `courses/rollups.py` (no N+1) produce a plain matrix dict; scope resolution lives in `grouping/scoping.py` beside the existing 3c-i helpers; color bands are a single JSON field on `Course` read through one validating accessor in a new `courses/color_bands.py`; two views in a new `courses/views_analytics.py` render the read-only matrix and the owner/PA-only bands form. Server-rendered, GET-param state, no client framework.

**Tech Stack:** Django (server-rendered templates), pytest + pytest-django + factory_boy, Playwright (e2e), bespoke token-driven CSS (no Bootstrap/React).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI runs `uv run ruff format --check` — run `uv run ruff format <files>` (not just `ruff check`) every task.
- **i18n:** EN + PL for **every** new user-facing string at build time. Add `{% trans %}`/`gettext` msgids, then add PL `msgstr`s to `locale/pl/LC_MESSAGES/django.po` and compile `.mo` (`uv run python manage.py compilemessages`). Module-level translatable dicts MUST use `gettext_lazy`.
- **Access:** scope/ownership mismatch → **404 never 403** (manage convention, mirrors `get_node_or_404`).
- **No N+1:** matrix builders' query count MUST be constant in the number of students — assert with `CaptureQueriesContext` after warming the ContentType cache (the `test_build_course_results_query_count_is_size_independent` precedent).
- **Percent type:** every percent in a matrix dict is `int|None`, rounded once as `int(round(Decimal(100)*a/b))` (ROUND_HALF_EVEN). `None` ≠ `0` is load-bearing (no-denominator vs scored-0).
- **UI:** bespoke token-driven, dark-mode-aware, no Bootstrap/React. Mirror the manage ledger / roster / review-queue patterns (`.manage`, `.card-list`, `.btn`, `.badge`).
- **Spec:** `docs/superpowers/specs/2026-06-27-phase-3c-ii-analytics-matrix-design.md` is the contract.

---

## File Structure

- **Create** `courses/color_bands.py` — band defaults, validating accessor, `band_for`, `text_on`, `band_style`, `legend_rows`. Pure (one accessor reads `Course.color_bands`).
- **Create** `courses/migrations/0026_course_color_bands.py` — adds `Course.color_bands` JSONField.
- **Modify** `courses/models.py` — add `Course.color_bands` field.
- **Modify** `courses/rollups.py` — add `is_obligatory_lesson`, `is_quiz_unit`, `build_matrix_columns`, `_quiz_review_maps`, `submission_is_counted`, `_pct`/`_cell`/`_avg_cell`, `build_progress_matrix`, `build_results_matrix`; refactor `quiz_units_in_order`/`build_outline`/`build_course_results` to share the new predicates/helper (behavior unchanged).
- **Modify** `grouping/scoping.py` — add `collections_visible_to`, `analytics_scope_choices`, `students_in_scope`.
- **Modify** `courses/forms.py` — add `ColorBandsForm`.
- **Create** `courses/views_analytics.py` — `analytics_matrix`, `analytics_bands` (+ a band-decoration helper).
- **Modify** `courses/urls.py` — wire the two routes.
- **Create** `templates/courses/manage/analytics_matrix.html`, `templates/courses/manage/analytics_bands.html`.
- **Modify** `templates/courses/manage/_course_panel.html` — add the "Analytics" link.
- **Create** tests: `tests/test_color_bands.py`, `tests/test_analytics_scoping.py`, `tests/test_analytics_rollups.py`, `tests/test_analytics_bands_form.py`, `tests/test_analytics_views.py`, `tests/test_e2e_analytics.py`.
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`).

---

### Task 1: `Course.color_bands` field + migration

**Files:**
- Modify: `courses/models.py:123` (add field in the `Course` class, after `uses_sections`)
- Create: `courses/migrations/0026_course_color_bands.py`
- Test: `tests/test_color_bands.py`

**Interfaces:**
- Produces: `Course.color_bands` — `JSONField(blank=True, default=list)`; a fresh course reads `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_color_bands.py
import pytest

from tests.factories import CourseFactory


@pytest.mark.django_db
def test_new_course_color_bands_defaults_to_empty_list():
    course = CourseFactory()
    course.refresh_from_db()
    assert course.color_bands == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_color_bands.py::test_new_course_color_bands_defaults_to_empty_list -v`
Expected: FAIL — `AttributeError`/`FieldError` (no `color_bands`).

- [ ] **Step 3: Add the field**

In `courses/models.py`, immediately after the `uses_sections` field (line ~123):

```python
    # Phase 3c-ii: per-course analytics color bands (5-band threshold table).
    # Empty list = use courses.color_bands.default_color_bands(); validated &
    # read through courses.color_bands.course_color_bands(). Stored mins are
    # JSON ints (a plain JSONField can't serialize Decimal).
    color_bands = models.JSONField(blank=True, default=list)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses --name course_color_bands`
Expected: creates `courses/migrations/0026_course_color_bands.py` adding `color_bands`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_color_bands.py -v && uv run python manage.py migrate`
Expected: PASS; migrate applies cleanly.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format courses/models.py courses/migrations/0026_course_color_bands.py tests/test_color_bands.py
uv run ruff check courses/ tests/test_color_bands.py
git add courses/models.py courses/migrations/0026_course_color_bands.py tests/test_color_bands.py
git commit -m "feat(analytics): add Course.color_bands JSON field"
```

---

### Task 2: `courses/color_bands.py` — band helpers + validating accessor

**Files:**
- Create: `courses/color_bands.py`
- Test: `tests/test_color_bands.py` (extend)

**Interfaces:**
- Consumes: `Course.color_bands` (Task 1).
- Produces:
  - `BAND_KEYS = ["none", "weak", "ok", "good", "excellent"]`
  - `default_color_bands() -> list[dict]` — 5 dicts `{"key": str, "label": <lazy>, "min": int, "color": "#rrggbb"}`, ascending `min`, first `min == 0`.
  - `course_color_bands(course) -> list[dict]` — validated, sorted-ascending; falls back to defaults on any malformed stored value; labels re-resolved from key.
  - `band_for(percent, bands) -> dict|None` — max-`min` matching band; lowest band on no-match; `None` only when `percent is None`.
  - `text_on(color) -> str` — `"#000000"`/`"#ffffff"` by luminance.
  - `band_style(percent, bands) -> dict` — `{"bg": str|None, "fg": str|None}`.
  - `legend_rows(bands) -> list[dict]` — `{"label", "color", "lo": int, "hi": int}` per band.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_color_bands.py  (append)
from decimal import Decimal

from courses.color_bands import band_for
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import default_color_bands
from courses.color_bands import legend_rows
from courses.color_bands import text_on


def test_default_bands_shape_ascending_from_zero():
    bands = default_color_bands()
    assert [b["key"] for b in bands] == ["none", "weak", "ok", "good", "excellent"]
    mins = [b["min"] for b in bands]
    assert mins[0] == 0
    assert mins == sorted(mins) and len(set(mins)) == 5
    assert all(isinstance(b["min"], int) for b in bands)


def test_band_for_selects_max_min_match_and_handles_edges():
    bands = default_color_bands()
    assert band_for(None, bands) is None
    # 100 -> top band; 0 -> lowest band
    assert band_for(100, bands)["key"] == "excellent"
    assert band_for(0, bands)["key"] == "none"
    # order-independent: shuffled list still bands 100 as excellent
    shuffled = list(reversed(bands))
    assert band_for(100, shuffled)["key"] == "excellent"
    # no-match fallback -> lowest band (min coerced from str too)
    weird = [{"key": "x", "label": "x", "min": "50", "color": "#111111"}]
    assert band_for(10, weird)["key"] == "x"


def test_text_on_luminance():
    assert text_on("#000000") == "#ffffff"
    assert text_on("#ffffff") == "#000000"


def test_band_style_none_is_blank():
    bands = default_color_bands()
    assert band_style(None, bands) == {"bg": None, "fg": None}
    s = band_style(100, bands)
    assert s["bg"] == band_for(100, bands)["color"] and s["fg"] in ("#000000", "#ffffff")


@pytest.mark.django_db
def test_course_color_bands_fallback_and_override():
    course = CourseFactory()
    # unconfigured -> defaults
    assert [b["key"] for b in course_color_bands(course)] == [
        "none", "weak", "ok", "good", "excellent"
    ]
    # structurally invalid (only 3 entries) -> defaults
    course.color_bands = [{"key": "none", "min": 0, "color": "#000000"}]
    assert len(course_color_bands(course)) == 5
    # valid override (hand-reordered) -> sorted ascending, labels re-resolved from key
    course.color_bands = [
        {"key": "excellent", "min": 90, "color": "#1e8e4a"},
        {"key": "none", "min": 0, "color": "#eeeeee"},
        {"key": "weak", "min": 40, "color": "#e98b5a"},
        {"key": "ok", "min": 60, "color": "#f1c453"},
        {"key": "good", "min": 75, "color": "#52b06a"},
    ]
    out = course_color_bands(course)
    assert [b["min"] for b in out] == [0, 40, 60, 75, 90]
    assert [b["key"] for b in out] == ["none", "weak", "ok", "good", "excellent"]
    # inverted key order (min=0 paired with 'excellent') -> rejected -> defaults
    course.color_bands = [
        {"key": "excellent", "min": 0, "color": "#1e8e4a"},
        {"key": "good", "min": 40, "color": "#52b06a"},
        {"key": "ok", "min": 60, "color": "#f1c453"},
        {"key": "weak", "min": 75, "color": "#e98b5a"},
        {"key": "none", "min": 90, "color": "#eeeeee"},
    ]
    assert [b["color"] for b in course_color_bands(course)] == [
        b["color"] for b in default_color_bands()
    ]


def test_legend_rows_ranges():
    rows = legend_rows(default_color_bands())
    assert rows[0]["lo"] == 0
    assert rows[-1]["hi"] == 100
    # contiguous: each row's hi is next row's lo - 1
    for a, b in zip(rows, rows[1:]):
        assert a["hi"] == b["lo"] - 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_color_bands.py -v`
Expected: FAIL — `ModuleNotFoundError: courses.color_bands`.

- [ ] **Step 3: Write the implementation**

```python
# courses/color_bands.py
"""Per-course analytics color bands (Phase 3c-ii).

A band table is a 5-entry list of {key, label, min, color}. The matrix and
legend read it ONLY through course_color_bands(), which validates the stored
value and falls back to defaults — only the validated ColorBandsForm normally
writes the field, but raw/admin JSON edits are possible.
"""

import re

from django.utils.translation import gettext_lazy as _

# Fixed semantic order: a band's key tracks its position in ascending `min`.
BAND_KEYS = ["none", "weak", "ok", "good", "excellent"]

_LABELS = {
    "none": _("None"),
    "weak": _("Weak"),
    "ok": _("OK"),
    "good": _("Good"),
    "excellent": _("Excellent"),
}

# Defaults derived from the accepted mockup (neutral low -> green high).
_DEFAULT_MINS = [0, 40, 60, 75, 90]
_DEFAULT_COLORS = ["#e5e5e7", "#e98b5a", "#f1c453", "#52b06a", "#1e8e4a"]


def default_color_bands():
    return [
        {"key": k, "label": _LABELS[k], "min": m, "color": c}
        for k, m, c in zip(BAND_KEYS, _DEFAULT_MINS, _DEFAULT_COLORS)
    ]


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_valid_stored(raw):
    """True iff `raw` is a usable 5-band table: exactly the 5 fixed keys, each
    with an int-coercible min and a #rrggbb color, mins strictly ascending from
    0, AND key order tracking ascending min (so an inverted edit is rejected)."""
    if not isinstance(raw, list) or len(raw) != 5:
        return False
    try:
        rows = sorted(raw, key=lambda b: int(b["min"]))
    except (KeyError, TypeError, ValueError):
        return False
    mins, keys = [], []
    for b in rows:
        if not isinstance(b, dict) or "color" not in b or "key" not in b:
            return False
        if not isinstance(b["color"], str) or not _HEX.match(b["color"]):
            return False
        mins.append(int(b["min"]))
        keys.append(b["key"])
    if mins[0] != 0 or mins != sorted(set(mins)) or len(set(mins)) != 5:
        return False
    return keys == BAND_KEYS  # key order must track ascending min


def course_color_bands(course):
    raw = course.color_bands
    if not raw or not _is_valid_stored(raw):
        return default_color_bands()
    rows = sorted(raw, key=lambda b: int(b["min"]))
    # Re-resolve label from the fixed key (stored label, if any, is ignored).
    return [
        {"key": b["key"], "label": _LABELS[b["key"]], "min": int(b["min"]), "color": b["color"]}
        for b in rows
    ]


def band_for(percent, bands):
    if percent is None:
        return None
    matching = [b for b in bands if int(b["min"]) <= percent]
    if matching:
        return max(matching, key=lambda b: int(b["min"]))
    # No band <= percent (impossible for course_color_bands output): lowest band.
    return min(bands, key=lambda b: int(b["min"]))


def text_on(color):
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


def band_style(percent, bands):
    band = band_for(percent, bands)
    if band is None:
        return {"bg": None, "fg": None}
    return {"bg": band["color"], "fg": text_on(band["color"])}


def legend_rows(bands):
    rows = []
    for i, b in enumerate(bands):
        hi = 100 if i == len(bands) - 1 else int(bands[i + 1]["min"]) - 1
        rows.append({"label": b["label"], "color": b["color"], "lo": int(b["min"]), "hi": hi})
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_color_bands.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/color_bands.py tests/test_color_bands.py
uv run ruff check courses/color_bands.py tests/test_color_bands.py
git add courses/color_bands.py tests/test_color_bands.py
git commit -m "feat(analytics): color-bands module (defaults, validating accessor, band_for)"
```

---

### Task 3: Scope resolution in `grouping/scoping.py`

**Files:**
- Modify: `grouping/scoping.py` (append after `can_review_course`)
- Test: `tests/test_analytics_scoping.py`

**Interfaces:**
- Consumes: `reviewable_students`, `groups_visible_to`, `collections_manageable_by`, `_is_platform_admin` (existing).
- Produces:
  - `collections_visible_to(user, course) -> QuerySet[Collection]`
  - `analytics_scope_choices(user, course) -> list[dict]` — `[{"value": str, "label": str}, ...]`, first is `{"value": "all", "label": _("All my students")}`.
  - `students_in_scope(user, course, scope) -> QuerySet[User]` — resolves `all` / `group:<pk>` / `collection:<pk>`, falling back to `all` on any unreachable/malformed value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_scoping.py
import pytest

from grouping import scoping
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_pa


@pytest.mark.django_db
def test_students_in_scope_all_is_reviewable_set_for_owner():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    g = GroupFactory(course=course)
    m = GroupMembershipFactory(group=g)
    # owner sees all enrolled; but with no Enrollment rows the "all" set is empty.
    # Use the group arm to prove resolution; "all" for owner == reviewable_students.
    assert scoping.students_in_scope(owner, course, "all").count() == 0


@pytest.mark.django_db
def test_students_in_scope_group_arm(client):
    pa = make_pa(client)
    course = CourseFactory()
    g = GroupFactory(course=course)
    m = GroupMembershipFactory(group=g)
    ids = set(scoping.students_in_scope(pa, course, f"group:{g.pk}").values_list("pk", flat=True))
    assert ids == {m.student_id}


@pytest.mark.django_db
def test_students_in_scope_collection_arm_and_distinct(client):
    pa = make_pa(client)
    course = CourseFactory()
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    student = UserFactory()
    GroupMembershipFactory(group=g1, student=student)
    GroupMembershipFactory(group=g2, student=student)  # same student in both
    col = CollectionFactory(course=course)
    col.groups.add(g1, g2)
    ids = list(scoping.students_in_scope(pa, course, f"collection:{col.pk}").values_list("pk", flat=True))
    assert ids == [student.pk]  # distinct -> appears once


@pytest.mark.django_db
def test_students_in_scope_bad_values_fall_back_to_all(client):
    pa = make_pa(client)
    course = CourseFactory()
    for bad in ("group:999", "collection:0", "group:abc", "garbage", "group:", ""):
        # falls back to "all" (== reviewable_students == empty here), never raises
        assert scoping.students_in_scope(pa, course, bad).count() == 0


@pytest.mark.django_db
def test_scope_choices_include_all_groups_collections(client):
    pa = make_pa(client)
    course = CourseFactory()
    g = GroupFactory(course=course, name="Group A")
    col = CollectionFactory(course=course, name="Collection X")
    choices = scoping.analytics_scope_choices(pa, course)
    values = [c["value"] for c in choices]
    assert values[0] == "all"
    assert f"group:{g.pk}" in values
    assert f"collection:{col.pk}" in values


@pytest.mark.django_db
def test_collections_visible_to_excludes_archived_collection(client):
    pa = make_pa(client)
    course = CourseFactory()
    live = CollectionFactory(course=course)
    archived = CollectionFactory(course=course, archived=True)
    pks = set(scoping.collections_visible_to(pa, course).values_list("pk", flat=True))
    assert live.pk in pks and archived.pk not in pks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_scoping.py -v`
Expected: FAIL — `AttributeError: module 'grouping.scoping' has no attribute 'students_in_scope'`.

- [ ] **Step 3: Write the implementation**

Append to `grouping/scoping.py`:

```python
def collections_visible_to(user, course):
    """Collections on `course` the user may report on: manageable ∪ those whose
    groups include a NON-archived group the user teaches. Excludes archived
    collections (parity with the group filter). See spec §2."""
    manageable = collections_manageable_by(user).filter(course=course, archived=False)
    taught = Collection.objects.filter(
        course=course,
        archived=False,
        groups__teachers=user,
        groups__archived=False,
    )
    return (manageable | taught).distinct()


def analytics_scope_choices(user, course):
    """Picker options: "All my students" + each visible non-archived group +
    each visible collection on the course."""
    from django.utils.translation import gettext as _

    choices = [{"value": "all", "label": _("All my students")}]
    for g in groups_visible_to(user).filter(course=course, archived=False).order_by("name"):
        choices.append({"value": f"group:{g.pk}", "label": g.name})
    for c in collections_visible_to(user, course).order_by("name"):
        choices.append({"value": f"collection:{c.pk}", "label": c.name})
    return choices


def students_in_scope(user, course, scope):
    """Resolve a scope value to a student queryset, always re-deriving from the
    user's reach. Unreachable/malformed scope -> default ("all"). See spec §2."""
    User = get_user_model()
    if scope and scope != "all" and ":" in scope:
        prefix, _, raw_pk = scope.partition(":")
        try:
            pk = int(raw_pk)
        except (TypeError, ValueError):
            pk = None
        if pk is not None and prefix == "group":
            if groups_visible_to(user).filter(
                pk=pk, course=course, archived=False
            ).exists():
                student_ids = GroupMembership.objects.filter(group_id=pk).values(
                    "student_id"
                )
                return User.objects.filter(pk__in=student_ids).distinct()
        elif pk is not None and prefix == "collection":
            if collections_visible_to(user, course).filter(pk=pk).exists():
                student_ids = GroupMembership.objects.filter(
                    group__collections=pk, group__archived=False
                ).values("student_id")
                return User.objects.filter(pk__in=student_ids).distinct()
    # default / fallback
    return reviewable_students(user, course)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_scoping.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format grouping/scoping.py tests/test_analytics_scoping.py
uv run ruff check grouping/scoping.py tests/test_analytics_scoping.py
git add grouping/scoping.py tests/test_analytics_scoping.py
git commit -m "feat(analytics): scope resolution (collections_visible_to, students_in_scope, choices)"
```

---

### Task 4: Shared predicates + `build_progress_matrix`

**Files:**
- Modify: `courses/rollups.py` (add predicates, column helper, builder; refactor `quiz_units_in_order` + `build_outline` to use the predicates)
- Test: `tests/test_analytics_rollups.py`

**Interfaces:**
- Consumes: `_walk_preorder`, `UnitProgress`, `ContentNode` (existing).
- Produces:
  - `is_obligatory_lesson(node) -> bool` — `kind==UNIT and unit_type==LESSON and obligatory`.
  - `is_quiz_unit(node) -> bool` — `kind==UNIT and unit_type==QUIZ`.
  - `build_matrix_columns(course) -> list[dict]` — per depth-1 root: `{"node", "title", "lesson_pks": set, "quiz_pks": set}`, in outline order.
  - `_pct(a, b) -> int` (b>0), `_cell(p) -> dict`, `_avg_cell(percents) -> dict`.
  - `build_progress_matrix(course, students) -> dict` (the shape in spec §3).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_rollups.py
from decimal import Decimal

import pytest

from courses.rollups import build_matrix_columns
from courses.rollups import build_progress_matrix
from courses.rollups import is_obligatory_lesson
from courses.rollups import is_quiz_unit
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


def _chapter(course, **kw):
    # unit_type=None: chapters carry no unit_type (the test_courses_rollups
    # convention; ContentNodeFactory defaults unit_type="lesson").
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="chapter", parent=None, **kw)


def _lesson(course, parent, obligatory=True, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent,
        obligatory=obligatory, **kw,
    )


def _quiz(course, parent, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=parent, **kw
    )


@pytest.mark.django_db
def test_predicates():
    course = CourseFactory()
    ch = _chapter(course)
    les = _lesson(course, ch)
    qz = _quiz(course, ch)
    assert is_obligatory_lesson(les) and not is_quiz_unit(les)
    assert is_quiz_unit(qz) and not is_obligatory_lesson(qz)
    assert not is_obligatory_lesson(_lesson(course, ch, obligatory=False))


@pytest.mark.django_db
def test_build_matrix_columns_partition():
    course = CourseFactory()
    ch1, ch2 = _chapter(course), _chapter(course)
    l1 = _lesson(course, ch1)
    q1 = _quiz(course, ch1)
    l2 = _lesson(course, ch2)
    cols = build_matrix_columns(course)
    assert [c["node"].pk for c in cols] == [ch1.pk, ch2.pk]
    assert cols[0]["lesson_pks"] == {l1.pk} and cols[0]["quiz_pks"] == {q1.pk}
    assert cols[1]["lesson_pks"] == {l2.pk} and cols[1]["quiz_pks"] == set()


@pytest.mark.django_db
def test_progress_matrix_cells_overall_and_average():
    course = CourseFactory()
    ch = _chapter(course)
    l1, l2 = _lesson(course, ch), _lesson(course, ch)
    s1, s2 = UserFactory(), UserFactory()
    UnitProgressFactory(student=s1, unit=l1, completed=True)  # s1: 1/2 -> 50%
    # s2: 0/2 -> 0%  (defined, NOT None)
    m = build_progress_matrix(course, [s1, s2])
    assert m["mode"] == "progress"
    assert m["rows"][0]["cells"][0]["percent"] == 50
    assert m["rows"][0]["cells"][0]["label"] == "50%"
    assert m["rows"][1]["cells"][0]["percent"] == 0  # attempted-denominator, not None
    assert m["rows"][0]["overall"]["percent"] == 50
    # average of [50, 0] = 25
    assert m["averages"][0]["percent"] == 25
    assert m["overall_average"]["percent"] == 25


@pytest.mark.django_db
def test_progress_column_with_no_obligatory_lessons_is_none():
    course = CourseFactory()
    ch = _chapter(course)
    _quiz(course, ch)  # all-quiz chapter -> no obligatory lessons
    s1 = UserFactory()
    m = build_progress_matrix(course, [s1])
    assert m["rows"][0]["cells"][0]["percent"] is None
    assert m["rows"][0]["cells"][0]["label"] == "—"
    assert m["averages"][0]["percent"] is None  # mean of zero defined cells


@pytest.mark.django_db
def test_progress_overall_parity_with_build_outline():
    from courses.rollups import build_outline

    course = CourseFactory()
    ch = _chapter(course)
    l1, l2, l3 = _lesson(course, ch), _lesson(course, ch), _lesson(course, ch)
    s1 = UserFactory()
    UnitProgressFactory(student=s1, unit=l1, completed=True)
    UnitProgressFactory(student=s1, unit=l2, completed=True)  # 2/3
    m = build_progress_matrix(course, [s1])
    tree = build_outline(course, s1)
    done = sum(d["required_done"] for d in tree)
    total = sum(d["required_total"] for d in tree)
    assert m["rows"][0]["overall"]["percent"] == int(round(Decimal(100) * done / total))


@pytest.mark.django_db
def test_progress_matrix_query_count_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    _lesson(course, ch)

    def add_students(n):
        return [UserFactory() for _ in range(n)]

    s = add_students(3)
    build_progress_matrix(course, s)  # warm caches
    with CaptureQueriesContext(connection) as c1:
        build_progress_matrix(course, s)
    s2 = s + add_students(20)
    with CaptureQueriesContext(connection) as c2:
        build_progress_matrix(course, s2)
    assert len(c1) == len(c2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -v`
Expected: FAIL — `ImportError` (`is_obligatory_lesson` not defined).

- [ ] **Step 3: Write the predicates + column helper + progress builder**

In `courses/rollups.py`, add the predicates near the top (after `_walk_preorder`) and refactor `quiz_units_in_order`:

```python
def is_obligatory_lesson(node):
    """A unit that counts toward Progress: an obligatory lesson unit. The SINGLE
    source for "counts toward required_total" — build_outline's rollup reuses it."""
    return (
        node.kind == ContentNode.Kind.UNIT
        and node.unit_type == ContentNode.UnitType.LESSON
        and node.obligatory
    )


def is_quiz_unit(node):
    """A quiz unit. The SINGLE source quiz_units_in_order and the matrix share."""
    return (
        node.kind == ContentNode.Kind.UNIT
        and node.unit_type == ContentNode.UnitType.QUIZ
    )
```

Refactor `quiz_units_in_order` (it currently re-checks `unit_type`):

```python
def quiz_units_in_order(course):
    """Quiz units in depth-first pre-order — units_in_order filtered to quizzes."""
    return [n for n in units_in_order(course) if is_quiz_unit(n)]
```

Refactor `build_outline`'s `rollup` inner function to use the shared predicate (replace the `is_lesson = ...` / `required_total` lines):

```python
        if d["is_unit"]:
            obligatory = is_obligatory_lesson(node)
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            d["required_total"] = 1 if obligatory else 0
            d["required_done"] = 1 if (obligatory and node.pk in completed) else 0
            d["additional_done"] = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
```

Add the column helper + cell helpers + the progress builder (anywhere after `build_course_results`):

```python
def build_matrix_columns(course):
    """Depth-1 roots (parent_id is None) as analytics columns, each with the set
    of obligatory-lesson and quiz unit pks in its subtree. Outline order. One
    query (course.nodes). Columns key on parent_id, not kind/preset flags."""
    nodes = list(course.nodes.all())
    children = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    columns = []
    for root in children.get(None, []):
        lesson_pks, quiz_pks = set(), set()
        stack = [root]
        while stack:
            n = stack.pop()
            if is_obligatory_lesson(n):
                lesson_pks.add(n.pk)
            elif is_quiz_unit(n):
                quiz_pks.add(n.pk)
            stack.extend(children.get(n.pk, []))
        columns.append(
            {"node": root, "title": root.title, "lesson_pks": lesson_pks, "quiz_pks": quiz_pks}
        )
    return columns


def _pct(a, b):
    """Whole-number percent, rounded once (ROUND_HALF_EVEN). Caller guarantees b>0."""
    return int(round(Decimal(100) * Decimal(a) / Decimal(b)))


def _cell(percent):
    return {"percent": percent, "label": f"{percent}%" if percent is not None else "—"}


def _avg_cell(percents):
    defined = [p for p in percents if p is not None]
    if not defined:
        return _cell(None)
    return _cell(int(round(Decimal(sum(defined)) / Decimal(len(defined)))))


def _public_columns(columns):
    return [{"node": c["node"], "title": c["title"]} for c in columns]


def build_progress_matrix(course, students):
    """Required-lesson completion %, students × depth-1 columns. No N+1. See spec §3."""
    students = list(students)
    columns = build_matrix_columns(course)
    all_lesson_pks = set()
    for c in columns:
        all_lesson_pks |= c["lesson_pks"]
    completed = {}
    if all_lesson_pks and students:
        for sid, uid in UnitProgress.objects.filter(
            unit_id__in=all_lesson_pks, completed=True, student__in=students
        ).values_list("student_id", "unit_id"):
            completed.setdefault(sid, set()).add(uid)
    rows = []
    for s in students:
        done_set = completed.get(s.id, set())
        cells = []
        tot_done = tot_total = 0
        for c in columns:
            total = len(c["lesson_pks"])
            if total == 0:
                cells.append(_cell(None))
                continue
            done = len(done_set & c["lesson_pks"])
            tot_done += done
            tot_total += total
            cells.append(_cell(_pct(done, total)))
        overall = _cell(_pct(tot_done, tot_total) if tot_total else None)
        rows.append({"student": s, "cells": cells, "overall": overall})
    averages = [
        _avg_cell([r["cells"][i]["percent"] for r in rows]) for i in range(len(columns))
    ]
    overall_average = _avg_cell([r["overall"]["percent"] for r in rows])
    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "mode": "progress",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py -v && uv run pytest tests/test_courses_rollups.py -v`
Expected: PASS — including the **unchanged** existing rollups tests (regression check on the `build_outline`/`quiz_units_in_order` refactor).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
uv run ruff check courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): shared predicates + build_progress_matrix (no N+1)"
```

---

### Task 5: `build_results_matrix` + shared counted/pending helper

**Files:**
- Modify: `courses/rollups.py` (add `_quiz_review_maps`, `submission_is_counted`, `build_results_matrix`; refactor `build_course_results` to call the extracted maps helper)
- Test: `tests/test_analytics_rollups.py` (extend)

**Interfaces:**
- Consumes: `build_matrix_columns`, `_pct`/`_cell`/`_avg_cell`/`_public_columns` (Task 4); `QuizSubmission`, `QuestionResponse`, `Element`, `_QUESTION_MODELS` (existing).
- Produces:
  - `_quiz_review_maps(unit_pks, submissions) -> (has_auto: dict, has_review: dict, total_review: dict, reviewed_counts: dict)` — the batched maps `build_course_results` and the matrix share.
  - `submission_is_counted(sub, total_review, reviewed_counts) -> bool` — SUBMITTED ∧ not pending.
  - `build_results_matrix(course, students) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_rollups.py  (append)
from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement


def _auto_q(unit, marks="1"):
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="auto", max_marks=Decimal(marks)
    )
    return Element.objects.create(unit=unit, content_object=q)


@pytest.mark.django_db
def test_results_matrix_counts_submitted_not_started_and_in_progress():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")
    s1, s2, s3 = UserFactory(), UserFactory(), UserFactory()
    QuizSubmission.objects.create(
        student=s1, unit=qz, status="submitted",
        score=Decimal("8.00"), max_score=Decimal("10.00"),
    )
    QuizSubmission.objects.create(
        student=s2, unit=qz, status="in_progress",
        score=Decimal("0.00"), max_score=Decimal("0.00"),
    )
    # s3: no submission (not started)
    m = build_results_matrix(course, [s1, s2, s3])
    assert m["mode"] == "results"
    assert m["rows"][0]["cells"][0]["percent"] == 80  # s1 counted
    assert m["rows"][1]["cells"][0]["percent"] is None  # s2 in_progress -> neutral
    assert m["rows"][2]["cells"][0]["percent"] is None  # s3 not started -> neutral
    # average over defined cells only ([80]) = 80
    assert m["averages"][0]["percent"] == 80


@pytest.mark.django_db
def test_results_overall_parity_with_build_course_results():
    from courses.rollups import build_course_results

    course = CourseFactory()
    ch = _chapter(course)
    q1, q2 = _quiz(course, ch), _quiz(course, ch)
    _auto_q(q1, "10")
    _auto_q(q2, "10")
    s1 = UserFactory()
    QuizSubmission.objects.create(
        student=s1, unit=q1, status="submitted",
        score=Decimal("5.00"), max_score=Decimal("10.00"),
    )
    QuizSubmission.objects.create(
        student=s1, unit=q2, status="submitted",
        score=Decimal("9.00"), max_score=Decimal("10.00"),
    )
    m = build_results_matrix(course, [s1])
    assert m["rows"][0]["overall"]["percent"] == build_course_results(course, s1)["percent"]


@pytest.mark.django_db
def test_results_matrix_query_count_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")

    def students(n):
        out = []
        for _ in range(n):
            u = UserFactory()
            QuizSubmission.objects.create(
                student=u, unit=qz, status="submitted",
                score=Decimal("8.00"), max_score=Decimal("10.00"),
            )
            out.append(u)
        return out

    s = students(3)
    build_results_matrix(course, s)  # warm ContentType cache
    with CaptureQueriesContext(connection) as c1:
        build_results_matrix(course, s)
    s2 = s + students(20)
    with CaptureQueriesContext(connection) as c2:
        build_results_matrix(course, s2)
    assert len(c1) == len(c2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k results -v`
Expected: FAIL — `ImportError`/`AttributeError` (`build_results_matrix`).

- [ ] **Step 3: Extract the maps helper and write the results builder**

In `courses/rollups.py`, add (the body mirrors the existing `build_course_results` query block — extract it):

```python
def _quiz_review_maps(unit_pks, submissions):
    """Batched maps over a set of quiz units + submissions (shared by
    build_course_results and build_results_matrix). Returns:
      has_auto[unit_id]        -> bool (unit has ≥1 AUTO question)
      total_review[unit_id]    -> int  (# of [R] elements)
      reviewed_counts[sub_id]  -> int  (# reviewed [R] responses)
    """
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    has_auto, total_review = {}, {}
    elements = Element.objects.filter(
        unit_id__in=unit_pks, content_type_id__in=question_ct_ids
    ).prefetch_related("content_object")
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            has_auto[el.unit_id] = True
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            total_review[el.unit_id] = total_review.get(el.unit_id, 0) + 1
    reviewed_counts = dict(
        QuestionResponse.objects.filter(
            submission__in=submissions,
            reviewed_at__isnull=False,
            element__content_type_id__in=question_ct_ids,
        )
        .values_list("submission_id")
        .annotate(n=Count("id"))
    )
    return has_auto, total_review, reviewed_counts


def submission_is_counted(sub, total_review, reviewed_counts):
    """SUBMITTED ∧ not pending (every [R] reviewed). The single rule the matrix
    and build_course_results share for "this submission's score counts"."""
    if sub.status != QuizSubmission.Status.SUBMITTED:
        return False
    total_r = total_review.get(sub.unit_id, 0)
    reviewed_r = reviewed_counts.get(sub.pk, 0)
    return not (total_r > 0 and reviewed_r < total_r)


def build_results_matrix(course, students):
    """Quiz score %, students × depth-1 columns. Excludes not-started /
    in-progress / awaiting-review from the ratio (neutral, not 0). No N+1."""
    students = list(students)
    columns = build_matrix_columns(course)
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
    rows = []
    for s in students:
        cells = []
        tot_e = tot_m = Decimal("0")
        for c in columns:
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
                cells.append(_cell(_pct(earned, mx)))
            else:
                cells.append(_cell(None))
        overall = _cell(_pct(tot_e, tot_m) if tot_m > 0 else None)
        rows.append({"student": s, "cells": cells, "overall": overall})
    averages = [
        _avg_cell([r["cells"][i]["percent"] for r in rows]) for i in range(len(columns))
    ]
    overall_average = _avg_cell([r["overall"]["percent"] for r in rows])
    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "mode": "results",
    }
```

- [ ] **Step 4: Refactor `build_course_results` to call `_quiz_review_maps` (no behavior change)**

In `build_course_results`, replace the inline `question_ct_ids`/`has_auto`/`has_review`/`total_review` element loop AND the `reviewed_counts` aggregation block with:

```python
    has_auto, total_review, reviewed_counts = _quiz_review_maps(
        unit_pks, submissions.values()
    )
```

(Leave the rest of `build_course_results` — the row loop reading `has_auto`/`total_review`/`reviewed_counts` — unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_rollups.py tests/test_courses_rollups.py -v`
Expected: PASS — new results tests AND the existing `build_course_results` tests (regression check on the extraction).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py
uv run ruff check courses/rollups.py tests/test_analytics_rollups.py
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "feat(analytics): build_results_matrix + shared counted/pending maps helper"
```

---

### Task 6: `ColorBandsForm`

**Files:**
- Modify: `courses/forms.py` (add `ColorBandsForm`)
- Test: `tests/test_analytics_bands_form.py`

**Interfaces:**
- Consumes: `courses.color_bands.BAND_KEYS`, `default_color_bands` (Task 2).
- Produces:
  - `ColorBandsForm(forms.Form)` — fields `color_0..color_4` (5 hex colors) + `min_1..min_4` (4 thresholds; band 0 pinned at 0). `clean()` enforces `1 <= min_1 < min_2 < min_3 < min_4 <= 100`.
  - `ColorBandsForm.initial_from(bands) -> dict` (classmethod) — seed dict from a band list.
  - `form.to_bands() -> list[dict]` — 5-band list `{key, min, color}` (label omitted; re-resolved on read).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_bands_form.py
from courses.color_bands import default_color_bands
from courses.forms import ColorBandsForm


def _valid_post():
    return {
        "color_0": "#e5e5e7", "color_1": "#e98b5a", "color_2": "#f1c453",
        "color_3": "#52b06a", "color_4": "#1e8e4a",
        "min_1": "40", "min_2": "60", "min_3": "75", "min_4": "90",
    }


def test_valid_form_builds_5_bands():
    form = ColorBandsForm(_valid_post())
    assert form.is_valid(), form.errors
    bands = form.to_bands()
    assert [b["key"] for b in bands] == ["none", "weak", "ok", "good", "excellent"]
    assert [b["min"] for b in bands] == [0, 40, 60, 75, 90]
    assert bands[0]["color"] == "#e5e5e7"


def test_non_ascending_thresholds_rejected():
    post = _valid_post()
    post["min_3"] = "55"  # not > min_2 (60)
    form = ColorBandsForm(post)
    assert not form.is_valid()


def test_bad_hex_rejected():
    post = _valid_post()
    post["color_2"] = "red"
    form = ColorBandsForm(post)
    assert not form.is_valid()


def test_initial_from_round_trips_defaults():
    initial = ColorBandsForm.initial_from(default_color_bands())
    form = ColorBandsForm(initial)
    assert form.is_valid(), form.errors
    assert form.to_bands()[0]["min"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_bands_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'ColorBandsForm'`.

- [ ] **Step 3: Write the form**

Add to `courses/forms.py` (ensure `from courses.color_bands import BAND_KEYS` and a hex regex validator):

```python
class ColorBandsForm(forms.Form):
    """Edit a course's 5 analytics color bands: 5 colors + 4 thresholds (the
    first band's min is pinned at 0 and is not a field). See spec §4."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hex_validator = RegexValidator(
            r"^#[0-9a-fA-F]{6}$", _("Enter a colour as #rrggbb.")
        )
        for i in range(5):
            self.fields[f"color_{i}"] = forms.CharField(
                max_length=7, validators=[hex_validator]
            )
        for i in range(1, 5):
            self.fields[f"min_{i}"] = forms.IntegerField(min_value=1, max_value=100)

    def clean(self):
        cleaned = super().clean()
        mins = [cleaned.get(f"min_{i}") for i in range(1, 5)]
        if all(m is not None for m in mins):
            ordered = [0] + mins
            if any(b <= a for a, b in zip(ordered, ordered[1:])):
                raise forms.ValidationError(
                    _("Thresholds must increase: 0 < weak < ok < good < excellent ≤ 100.")
                )
        return cleaned

    def to_bands(self):
        mins = [0] + [self.cleaned_data[f"min_{i}"] for i in range(1, 5)]
        return [
            {"key": BAND_KEYS[i], "min": mins[i], "color": self.cleaned_data[f"color_{i}"]}
            for i in range(5)
        ]

    @classmethod
    def initial_from(cls, bands):
        data = {}
        for i, b in enumerate(bands):
            data[f"color_{i}"] = b["color"]
            if i >= 1:
                data[f"min_{i}"] = b["min"]
        return data
```

(If `RegexValidator` is not already imported in `forms.py`, add `from django.core.validators import RegexValidator`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_bands_form.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/forms.py tests/test_analytics_bands_form.py
uv run ruff check courses/forms.py tests/test_analytics_bands_form.py
git add courses/forms.py tests/test_analytics_bands_form.py
git commit -m "feat(analytics): ColorBandsForm (5 colors + 4 thresholds, pinned 0)"
```

---

### Task 7: Matrix view + URL + template + panel link

**Files:**
- Create: `courses/views_analytics.py`
- Modify: `courses/urls.py` (add 2 routes — register both now; the bands view lands in Task 8)
- Create: `templates/courses/manage/analytics_matrix.html`
- Modify: `templates/courses/manage/_course_panel.html` (add Analytics link)
- Test: `tests/test_analytics_views.py`

**Interfaces:**
- Consumes: `scoping.can_review_course`/`analytics_scope_choices`/`students_in_scope` (Task 3); `build_progress_matrix`/`build_results_matrix` (Tasks 4–5); `color_bands.course_color_bands`/`band_style`/`legend_rows` (Task 2); `access.can_manage_course`.
- Produces: `analytics_matrix(request, slug)`; `_decorate(matrix, bands)` helper.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_views.py
import pytest

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa


def _course_with_lesson(owner):
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    return course, ch, les


@pytest.mark.django_db
def test_matrix_renders_for_owner_with_progress_default(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert resp.status_code == 200
    assert resp.context["mode"] == "progress"
    assert resp.context["matrix"]["rows"][0]["cells"][0]["percent"] == 100
    assert b"100%" in resp.content


@pytest.mark.django_db
def test_matrix_mode_results_and_lenient_mode_param(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert resp.context["mode"] == "results"
    # garbage mode -> progress
    resp2 = client.get(f"/manage/courses/{course.slug}/analytics/?mode=banana")
    assert resp2.context["mode"] == "progress"


@pytest.mark.django_db
def test_matrix_controls_round_trip_both_params(client):
    """Scope form carries mode; mode toggle links carry scope (spec §6)."""
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    html = resp.content.decode()
    # the scope GET form preserves mode so changing scope keeps Results
    assert '<input type="hidden" name="mode" value="results">' in html
    # the toggle links preserve the current scope
    assert "scope=all&mode=progress" in html or "scope=all&amp;mode=progress" in html


@pytest.mark.django_db
def test_matrix_404_for_non_staff_outsider(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_matrix_group_scope_filters_rows(client):
    pa = make_pa(client)
    course = CourseFactory()
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    g = GroupFactory(course=course)
    m = GroupMembershipFactory(group=g)
    other = UserFactory()
    Enrollment.objects.create(student=other, course=course)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/?scope=group:{g.pk}"
    )
    students = [r["student"].pk for r in resp.context["matrix"]["rows"]]
    assert students == [m.student_id]


@pytest.mark.django_db
def test_matrix_cells_decorated_with_band_colors(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    cell = resp.context["matrix"]["rows"][0]["cells"][0]
    assert cell["color"] is not None and cell["text_color"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: FAIL — 404/`NoReverseMatch` (route + view absent).

- [ ] **Step 3: Write the view module**

```python
# courses/views_analytics.py
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses.access import can_manage_course
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import legend_rows
from courses.models import Course
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from grouping import scoping


def _decorate(matrix, bands):
    """Attach band color + readable text color to every cell, overall, and
    average. None percents get color/text_color = None (template renders neutral)."""

    def paint(cell):
        style = band_style(cell["percent"], bands)
        cell["color"] = style["bg"]
        cell["text_color"] = style["fg"]

    for row in matrix["rows"]:
        for cell in row["cells"]:
            paint(cell)
        paint(row["overall"])
    for avg in matrix["averages"]:
        paint(avg)
    paint(matrix["overall_average"])


@login_required
def analytics_matrix(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    students = scoping.students_in_scope(request.user, course, scope).order_by("username")
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students)
    bands = course_color_bands(course)
    _decorate(matrix, bands)
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
        },
    )
```

- [ ] **Step 4: Wire the routes**

In `courses/urls.py`, add `from courses import views_analytics` and, after the review-queue block:

```python
    # --- analytics matrix routes (Phase 3c-ii) ---
    path(
        "manage/courses/<slug:slug>/analytics/",
        views_analytics.analytics_matrix,
        name="manage_analytics",
    ),
    path(
        "manage/courses/<slug:slug>/analytics/colors/",
        views_analytics.analytics_bands,
        name="manage_analytics_bands",
    ),
```

(The `analytics_bands` view is added in Task 8; to keep this task runnable, add a temporary stub at the bottom of `views_analytics.py` now — Task 8 replaces it:)

```python
@login_required
def analytics_bands(request, slug):  # replaced in Task 8
    raise Http404
```

- [ ] **Step 5: Write the matrix template**

```django
{# templates/courses/manage/analytics_matrix.html #}
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Analytics" %} · {{ course.title }} · libli{% endblock %}
{% block content %}
<section class="manage analytics">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Analytics" %} — {{ course.title }}</h1>
    {% if can_edit_bands %}
      <a class="btn btn--ghost btn--small"
         href="{% url 'courses:manage_analytics_bands' slug=course.slug %}?scope={{ scope|urlencode }}&mode={{ mode }}">
        {% trans "Configure colours" %}</a>
    {% endif %}
  </header>

  <form method="get" class="analytics__controls">
    {# Carry the current mode so changing scope keeps Progress/Results (spec §6). #}
    <input type="hidden" name="mode" value="{{ mode }}">
    <label>{% trans "Students" %}
      <select name="scope" onchange="this.form.submit()">
        {% for c in scope_choices %}
          <option value="{{ c.value }}" {% if c.value == scope %}selected{% endif %}>{{ c.label }}</option>
        {% endfor %}
      </select>
    </label>
    <span class="analytics__toggle" role="group" aria-label="{% trans 'Metric' %}">
      <a class="btn btn--small {% if mode == 'progress' %}is-active{% endif %}"
         href="?scope={{ scope|urlencode }}&mode=progress">{% trans "Progress" %}</a>
      <a class="btn btn--small {% if mode == 'results' %}is-active{% endif %}"
         href="?scope={{ scope|urlencode }}&mode=results">{% trans "Results" %}</a>
    </span>
    <noscript><button class="btn btn--small" type="submit">{% trans "Apply" %}</button></noscript>
  </form>

  <ul class="analytics__legend">
    {% for b in legend %}
      <li><span class="analytics__swatch" style="background:{{ b.color }}"></span>
        {{ b.label }} ({{ b.lo }}–{{ b.hi }}%)</li>
    {% endfor %}
  </ul>

  {% if matrix.rows %}
    <div class="analytics__scroll">
      <table class="analytics__matrix">
        <thead>
          <tr>
            <th class="analytics__rowhead">{% trans "Student" %}</th>
            {% for col in matrix.columns %}<th>{{ col.title }}</th>{% endfor %}
            <th class="analytics__overall">{% trans "Overall" %}</th>
          </tr>
        </thead>
        <tbody>
          {% for row in matrix.rows %}
            <tr>
              <td class="analytics__rowhead">{{ row.student.display_name|default:row.student.username }}</td>
              {% for cell in row.cells %}
                {% include "courses/manage/_analytics_cell.html" %}
              {% endfor %}
              {% with cell=row.overall %}
                <td class="analytics__overall"
                    {% if cell.color %}style="background:{{ cell.color }};color:{{ cell.text_color }}"{% endif %}>
                  {{ cell.label }}</td>
              {% endwith %}
            </tr>
          {% endfor %}
        </tbody>
        <tfoot>
          <tr class="analytics__avg">
            <td class="analytics__rowhead">{% trans "Average" %}</td>
            {% for cell in matrix.averages %}
              {% include "courses/manage/_analytics_cell.html" %}
            {% endfor %}
            {% with cell=matrix.overall_average %}
              <td class="analytics__overall"
                  {% if cell.color %}style="background:{{ cell.color }};color:{{ cell.text_color }}"{% endif %}>
                {{ cell.label }}</td>
            {% endwith %}
          </tr>
        </tfoot>
      </table>
    </div>
  {% else %}
    <p class="muted">{% trans "No students in this scope." %}</p>
  {% endif %}
  {% if mode == "results" and not matrix.columns %}
    <p class="muted">{% trans "No quizzes in this course yet." %}</p>
  {% endif %}
</section>
{% endblock %}
```

```django
{# templates/courses/manage/_analytics_cell.html #}
{% load i18n %}
<td class="analytics__cell{% if cell.percent is None %} analytics__cell--empty{% endif %}"
    {% if cell.color %}style="background:{{ cell.color }};color:{{ cell.text_color }}"{% endif %}>
  {{ cell.label }}</td>
```

(Add the new files to the File Structure: `_analytics_cell.html`.)

- [ ] **Step 6: Add the panel link**

In `templates/courses/manage/_course_panel.html`, after the "Quiz review" link (line 7):

```django
  <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_analytics' slug=course.slug %}">{% trans "Analytics" %}</a>
```

- [ ] **Step 7: Add minimal CSS**

Append to the app stylesheet (`static/css/app.css` or the project's token-driven sheet — match where the manage/`.card-list` rules live):

```css
.analytics__controls{display:flex;gap:1rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem}
.analytics__legend{display:flex;gap:1rem;flex-wrap:wrap;list-style:none;padding:0;margin:0 0 1rem;font-size:.8rem;color:var(--text-secondary)}
.analytics__swatch{display:inline-block;width:.9em;height:.9em;border-radius:3px;vertical-align:middle;margin-right:.3em}
.analytics__scroll{overflow-x:auto}
.analytics__matrix{border-collapse:collapse;width:100%;font-size:.85rem}
.analytics__matrix th,.analytics__matrix td{border:1px solid var(--border-default);padding:.4rem .6rem;text-align:center}
.analytics__rowhead{text-align:left;font-weight:600;white-space:nowrap}
.analytics__cell--empty{color:var(--text-secondary)}
.analytics__overall,.analytics__avg{font-weight:700}
.analytics__toggle .btn.is-active{background:var(--primary);color:#fff}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (all 5).

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff format courses/views_analytics.py courses/urls.py tests/test_analytics_views.py
uv run ruff check courses/views_analytics.py courses/urls.py tests/test_analytics_views.py
git add courses/views_analytics.py courses/urls.py templates/courses/manage/analytics_matrix.html templates/courses/manage/_analytics_cell.html templates/courses/manage/_course_panel.html tests/test_analytics_views.py static/
git commit -m "feat(analytics): matrix view + template + scope/mode controls + panel link"
```

---

### Task 8: Bands config view + template

**Files:**
- Modify: `courses/views_analytics.py` (replace the `analytics_bands` stub)
- Create: `templates/courses/manage/analytics_bands.html`
- Test: `tests/test_analytics_views.py` (extend)

**Interfaces:**
- Consumes: `ColorBandsForm` (Task 6); `course_color_bands` (Task 2); `can_manage_course`.
- Produces: `analytics_bands(request, slug)` GET/POST.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analytics_views.py  (append)
from courses.color_bands import course_color_bands


@pytest.mark.django_db
def test_bands_page_owner_pa_only(client):
    teacher = make_login(client, "t")
    course = CourseFactory(owner=UserFactory())
    # a group teacher can view the matrix but NOT the bands page
    g = GroupFactory(course=course)
    g.teachers.add(teacher)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/colors/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_bands_save_persists_and_redirects_with_state(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {
            "color_0": "#e5e5e7", "color_1": "#e98b5a", "color_2": "#f1c453",
            "color_3": "#52b06a", "color_4": "#1e8e4a",
            "min_1": "30", "min_2": "55", "min_3": "70", "min_4": "85",
            "scope": "all", "mode": "results",
        },
    )
    assert resp.status_code == 302
    assert "mode=results" in resp.url
    course.refresh_from_db()
    assert [b["min"] for b in course_color_bands(course)] == [0, 30, 55, 70, 85]


@pytest.mark.django_db
def test_bands_reset_clears_to_defaults(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner, color_bands=[{"key": "none", "min": 0, "color": "#000000"}])
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {"reset": "1", "scope": "all", "mode": "progress"},
    )
    assert resp.status_code == 302
    course.refresh_from_db()
    assert course.color_bands == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k bands -v`
Expected: FAIL — the stub raises 404 for everything (the save/reset tests fail).

- [ ] **Step 3: Replace the stub**

In `courses/views_analytics.py`, replace the `analytics_bands` stub. **Hoist these
new imports into the module's existing top import block** (do NOT leave them mid-file
above the view — `ruff` flags E402 and the per-task `ruff check` fails):

```python
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from courses.forms import ColorBandsForm
from courses.color_bands import default_color_bands


def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{urlencode({'scope': scope, 'mode': mode})}")


@login_required
def analytics_bands(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise Http404
    if request.method == "POST":
        if "reset" in request.POST:
            course.color_bands = []
            course.save(update_fields=["color_bands"])
            messages.success(request, _("Colours reset to defaults."))
            return _matrix_redirect(course, request)
        form = ColorBandsForm(request.POST)
        if form.is_valid():
            course.color_bands = form.to_bands()
            course.save(update_fields=["color_bands"])
            messages.success(request, _("Colours saved."))
            return _matrix_redirect(course, request)
    else:
        form = ColorBandsForm(
            initial=ColorBandsForm.initial_from(course_color_bands(course))
        )
    return render(
        request,
        "courses/manage/analytics_bands.html",
        {
            "course": course,
            "form": form,
            "default_bands": default_color_bands(),
            "scope": request.GET.get("scope", "all"),
            "mode": "results" if request.GET.get("mode") == "results" else "progress",
        },
    )
```

(Remove the temporary stub from Task 7.)

- [ ] **Step 4: Write the bands template**

```django
{# templates/courses/manage/analytics_bands.html #}
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Configure colours" %} · {{ course.title }} · libli{% endblock %}
{% block content %}
<section class="manage analytics-bands">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Colour bands" %} — {{ course.title }}</h1>
  </header>
  <form method="post" class="analytics-bands__form">
    {% csrf_token %}
    <input type="hidden" name="scope" value="{{ scope }}">
    <input type="hidden" name="mode" value="{{ mode }}">
    {{ form.non_field_errors }}

    {# Band 0 (none): min pinned at 0, only the colour is editable. #}
    <div class="analytics-bands__row">
      <span class="analytics-bands__label">{{ default_bands.0.label }}</span>
      <span class="analytics-bands__min">{% trans "from 0%" %}</span>
      {{ form.color_0 }} {{ form.color_0.errors }}
    </div>

    {# Bands 1–4: an editable threshold + colour each. Rendered from `band_rows`
       (bound fields, built in the view) so posted values re-bind and field
       errors show on a validation failure. #}
    {% for row in band_rows %}
      <div class="analytics-bands__row">
        <span class="analytics-bands__label">{{ row.label }}</span>
        <label class="analytics-bands__min">{% trans "from" %} {{ row.min_field }}%
          {{ row.min_field.errors }}</label>
        {{ row.color_field }} {{ row.color_field.errors }}
      </div>
    {% endfor %}

    <div class="analytics-bands__actions">
      <button class="btn btn--primary" type="submit">{% trans "Save" %}</button>
      <button class="btn btn--ghost" type="submit" name="reset" value="1">{% trans "Reset to defaults" %}</button>
    </div>
  </form>
</section>
{% endblock %}
```

The template uses `form.color_0` (band 0's colour widget) and a small `band_rows`
context list (label + the two bound fields for bands 1–4). Build it in the view —
add to `analytics_bands`'s render context (so both the GET render and the
invalid-POST re-render carry it):

```python
        "band_rows": [
            {
                "label": default_color_bands()[i]["label"],
                "min_field": form[f"min_{i}"],
                "color_field": form[f"color_{i}"],
            }
            for i in range(1, 5)
        ],
```

`form["min_1"]`/`form["color_1"]` are `BoundField`s — rendering them emits the
input with its posted value bound and `.errors` populated, so no manual `value=`
wiring is needed. Set the colour widgets to `<input type="color">` by giving the
`color_*` fields `widget=forms.TextInput(attrs={"type": "color"})` in
`ColorBandsForm.__init__` (Task 6) — optional polish; a plain text input also
validates against the hex regex.

- [ ] **Step 5: Add CSS**

```css
.analytics-bands__row{display:flex;gap:1rem;align-items:center;margin-bottom:.6rem}
.analytics-bands__label{min-width:6rem;font-weight:600}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (all, incl. bands save/reset/gate).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
uv run ruff check courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py templates/courses/manage/analytics_bands.html tests/test_analytics_views.py static/
git commit -m "feat(analytics): per-course colour-band config page (owner/PA)"
```

---

### Task 9: Polish translations (PL) + compile

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

**Interfaces:** none (translations only).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: new `msgid`s appear in `locale/pl/LC_MESSAGES/django.po` (Analytics, Progress, Results, All my students, Student, Overall, Average, Configure colours, Colour bands, None/Weak/OK/Good/Excellent, "No students in this scope.", "No quizzes in this course yet.", Save, Reset to defaults, Colours saved., Colours reset to defaults., "from", "from 0%", Metric, Apply, "Thresholds must increase…", "Enter a colour as #rrggbb.").

- [ ] **Step 2: Fill in PL `msgstr`s**

Edit `locale/pl/LC_MESSAGES/django.po` — set each new `msgstr` and **clear any `#, fuzzy` flag** makemessages added (fuzzy entries are ignored at runtime). Suggested PL:

```
Analytics → "Analityka"; Progress → "Postęp"; Results → "Wyniki";
All my students → "Wszyscy moi uczniowie"; Student → "Uczeń"; Overall → "Łącznie";
Average → "Średnia"; Configure colours → "Konfiguruj kolory"; Colour bands → "Zakresy kolorów";
None → "Brak"; Weak → "Słabo"; OK → "OK"; Good → "Dobrze"; Excellent → "Świetnie";
No students in this scope. → "Brak uczniów w tym zakresie."; No quizzes in this course yet. → "Brak quizów w tym kursie.";
Save → "Zapisz"; Reset to defaults → "Przywróć domyślne"; Colours saved. → "Zapisano kolory.";
Colours reset to defaults. → "Przywrócono domyślne kolory."; from → "od"; from 0% → "od 0%";
Metric → "Metryka"; Apply → "Zastosuj";
Thresholds must increase: 0 < weak < ok < good < excellent ≤ 100. → "Progi muszą rosnąć: 0 < słabo < ok < dobrze < świetnie ≤ 100.";
Enter a colour as #rrggbb. → "Podaj kolor w formacie #rrggbb."
```

(Grep the new msgids and verify none stayed fuzzy or mis-guessed — the recurring makemessages gotcha.)

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`
Expected: `locale/pl/LC_MESSAGES/django.mo` rebuilt, no errors.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (sanity — no template breakage from new tags).

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(analytics): Polish translations for the analytics matrix"
```

---

### Task 10: End-to-end test (real UI)

**Files:**
- Create: `tests/test_e2e_analytics.py`

**Interfaces:** none (drives the real UI; mirrors `tests/test_e2e_review.py`).

- [ ] **Step 1: Write the e2e test**

This mirrors `tests/test_e2e_review.py` EXACTLY: module-level `pytestmark =
pytest.mark.e2e`, fixtures `page, live_server, client`, the `_allow_async_unsafe`
session fixture, and a local `_login(page, live_server, username)` helper that
fills the real allauth login form. The owner is created with `make_pa(client, …)`
(PA holds `courses.change_course`, satisfies `can_review_course` AND
`can_manage_course`) — created via the helper so it has a verified email +
`TEST_PASSWORD` and can log in through the form.

```python
# tests/test_e2e_analytics.py
"""Playwright e2e for Phase 3c-ii: the teacher analytics-matrix journey.

The owner opens the matrix (Progress), sees a student's 100% cell, toggles to
Results, then edits a colour-band threshold and saves — all via real gestures.
"""

import os
import re

import pytest

from tests.factories import make_pa

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    from tests.factories import TEST_PASSWORD

    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def test_teacher_views_matrix_toggles_mode_and_edits_a_band(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2eanalytics")  # PA: passes can_review + can_manage
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2eanalytics")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    expect = __import__("playwright.sync_api", fromlist=["expect"]).expect
    expect(page.locator("table.analytics__matrix")).to_contain_text("100%")
    expect(page.get_by_text("Ada L.")).to_be_visible()

    # Toggle to Results (real click on the toggle link)
    page.get_by_role("link", name="Results").click()
    expect(page).to_have_url(re.compile(r"mode=results"))

    # Edit a colour-band threshold and save (real form submit)
    page.get_by_role("link", name="Configure colours").click()
    page.fill("input[name='min_1']", "10")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()
```

> **Implementer note:** keep this in lock-step with `tests/test_e2e_review.py` — if that file's `_login`/fixtures differ when you implement, copy the current version. Replace the inline `expect` import with a normal top-level `from playwright.sync_api import expect` (shown inline only to keep the snippet self-contained). Do NOT use `page.evaluate` shortcuts — drive the real clicks (the e2e-must-drive-real-UI lesson). Adjust selectors to the markup shipped in Tasks 7–8.

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_analytics.py -v` (or the project's e2e invocation, e.g. `-m e2e`).
Expected: PASS — the matrix renders, the mode toggle navigates, and a band edit saves.

- [ ] **Step 3: Commit**

```bash
uv run ruff format tests/test_e2e_analytics.py
uv run ruff check tests/test_e2e_analytics.py
git add tests/test_e2e_analytics.py
git commit -m "test(analytics): e2e — view matrix, toggle mode, edit a colour band"
```

---

## Final verification

- [ ] **Full suite + lint + migrations:**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run python manage.py compilemessages
```

Expected: all green; no pending migrations; `.mo` compiled.

- [ ] **Manual smoke (screenshot light + dark):** open `/manage/courses/<slug>/analytics/` as an owner — verify colored cells, the Progress/Results toggle round-trips scope, the legend matches the bands, "—" for empty cells, and the bands page saves & returns. Use a throwaway Playwright screenshot harness (delete after review) per the verify-UI-with-screenshots habit.

- [ ] **Finish the branch** via the `superpowers:finishing-a-development-branch` skill (PR to master).
