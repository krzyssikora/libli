# Phase 3c-iii-b — Analytics per-student cherry-pick subset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a teacher narrow the analytics matrix to an arbitrary subset of the students already in the current scope — row checkboxes + Apply + Clear + a JS Select-all — with the subset carried as a repeatable `student` URL param, no model field and no migration.

**Architecture:** The matrix view parses a repeatable `student` param, resets it on a scope change via a hidden `scope_rendered` sentinel, intersects the rest with the scope pool to get an *effective subset*, and passes the narrowed queryset to the existing builder (so the Average row recomputes for free). The single querystring helper `_expand_qs` gains a required `subset_pks` arg so every navigation link round-trips the subset. The matrix template becomes one GET form (controls header + table) with an always-rendered Apply, a `show_clear` flag, and an in-Student-cell checkbox.

**Tech Stack:** Django (server-rendered, progressive-enhancement, no JS framework), pytest, Playwright (e2e), `uv` task runner.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI checks `ruff format --check`, so run **both** `uv run ruff check --fix` and `uv run ruff format` at the end of every task.
- **isort:** project uses `force-single-line=true` — each import on its own line (ruff enforces).
- **i18n:** every new user-facing string gets EN + PL at build time (Task 5). `makemessages` re-marks copied msgstrs `#, fuzzy` (ignored at runtime) and can mis-guess — clear the flag and verify each new msgid; drop obsolete `#~` entries or `test_po_catalog_clean` fails. Compile `.mo`.
- **Manage convention:** all surfaces resolve the course by slug → 404 on mismatch; out-of-reach / non-staff → **404, never 403**. (Unchanged — gating is untouched this slice.)
- **Security invariant:** the subset can only ever *narrow* the already-authorized `students_in_scope` pool. The effective subset is `raw ∩ pool`; a forged/out-of-scope `student` pk is intersected away and never widens reach or leaks a row.
- **`None` ≠ `0`:** unchanged from 3c-ii — a cell `percent` is `int|None`; the builder is not modified here, only its `students` argument is filtered.
- **e2e:** real gestures only (no `page.evaluate` shortcuts). e2e runs need `-m e2e` (addopts defaults to `-m "not e2e"`).
- **Spec:** `docs/superpowers/specs/2026-06-28-phase-3c-iii-b-cherry-pick-subset-design.md` is the source of truth; section refs (§1–§5) below point into it.

---

### Task 1: View — parse the subset, scope sentinel, filter, context flags

The matrix view gains subset parsing, the `scope_rendered` reset, the `raw ∩ pool` filter (narrowed queryset → builder), and the new context keys (`subset_pks`, `subset_size`, `show_clear`, `clear_url`). Links do **not** yet carry the subset — that is Task 2. (Spec §1, §2, decisions #4/#9.)

**Files:**
- Modify: `courses/views_analytics.py` (the `analytics_matrix` function, lines 42–79)
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: existing `_clean_expand` (views_analytics.py:90), `scoping.students_in_scope`, the matrix builders.
- Produces: `analytics_matrix` GET context now also carries `subset_pks: set[int]`, `subset_size: int`, `show_clear: bool`, `clear_url: str`. Behaviour: with an in-scope `student` set the matrix `rows`/averages narrow to it; empty/forged/all-dropped → full scope; a submitted `scope` ≠ `scope_rendered` discards the subset.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
def _course_with_two_students(owner):
    """A course + one obligatory lesson; student A completed it (100%), B did
    not (0% in Progress). Returns (course, lesson, a, b)."""
    course, ch, les = _course_with_lesson(owner)
    a, b = UserFactory(), UserFactory()
    Enrollment.objects.create(student=a, course=course)
    Enrollment.objects.create(student=b, course=course)
    UnitProgressFactory(student=a, unit=les, completed=True)
    return course, les, a, b


@pytest.mark.django_db
def test_subset_narrows_rows_to_selected_students(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?student={a.pk}")
    pks = {row["student"].pk for row in resp.context["matrix"]["rows"]}
    assert pks == {a.pk}
    assert resp.context["subset_pks"] == {a.pk}
    assert resp.context["subset_size"] == 1
    assert resp.context["show_clear"] is True


@pytest.mark.django_db
def test_empty_and_forged_subset_show_full_scope(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    # no student param -> full scope, no Clear
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert len(resp.context["matrix"]["rows"]) == 2
    assert resp.context["show_clear"] is False
    # all-forged -> intersected away -> full scope
    resp2 = client.get(f"/manage/courses/{course.slug}/analytics/?student=999999")
    assert len(resp2.context["matrix"]["rows"]) == 2
    assert resp2.context["subset_pks"] == set()


@pytest.mark.django_db
def test_average_recomputes_over_subset(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    full = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert full.context["matrix"]["overall_average"]["percent"] == 50  # A=100,B=0
    narrowed = client.get(f"/manage/courses/{course.slug}/analytics/?student={a.pk}")
    assert narrowed.context["matrix"]["overall_average"]["percent"] == 100


@pytest.mark.django_db
def test_scope_sentinel_resets_subset_on_change(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    # student=a but scope changed (scope != scope_rendered) -> subset discarded
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/"
        f"?scope=all&scope_rendered=group:1&student={a.pk}"
    )
    assert len(resp.context["matrix"]["rows"]) == 2  # full scope, not narrowed
    assert resp.context["subset_pks"] == set()
    assert resp.context["show_clear"] is False  # and not scope_changed
    # same scope -> subset kept
    keep = client.get(
        f"/manage/courses/{course.slug}/analytics/"
        f"?scope=all&scope_rendered=all&student={a.pk}"
    )
    assert keep.context["subset_pks"] == {a.pk}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "subset or sentinel or average_recomputes" -v`
Expected: FAIL (`KeyError: 'subset_pks'` / rows not narrowed).

- [ ] **Step 3: Implement the subset logic in `analytics_matrix`**

In `courses/views_analytics.py`, replace the body of `analytics_matrix` (lines 42–79) up to the `return render(...)` so it reads:

```python
@login_required
def analytics_matrix(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    scope_rendered = request.GET.get("scope_rendered")
    scope_changed = scope_rendered is not None and scope_rendered != scope
    expand_pks = set(_clean_expand(request.GET.getlist("expand")))
    pool = scoping.students_in_scope(request.user, course, scope)
    pool_pks = set(pool.values_list("pk", flat=True))
    raw_subset = set() if scope_changed else set(_clean_expand(request.GET.getlist("student")))
    subset_pks = raw_subset & pool_pks
    if subset_pks:
        students = pool.filter(pk__in=subset_pks).order_by("username")
    else:
        students = pool.order_by("username")
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
    show_clear = bool(request.GET.getlist("student")) and not scope_changed
    clear_url = f"{matrix_path}?{_expand_qs(scope, mode, base_pks)}"
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
            "subset_pks": subset_pks,
            "subset_size": len(subset_pks),
            "show_clear": show_clear,
            "clear_url": clear_url,
            "progress_url": f"{matrix_path}?{_expand_qs(scope, 'progress', base_pks)}",
            "results_url": f"{matrix_path}?{_expand_qs(scope, 'results', base_pks)}",
            "colours_url": f"{bands_path}?{_expand_qs(scope, mode, base_pks)}",
        },
    )
```

Note: `_expand_qs` is still the 3-arg version here (Task 2 adds the subset arg). `clear_url` deliberately omits the subset, which the current `_expand_qs` already does.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_analytics_views.py -k "subset or sentinel or average_recomputes" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full analytics view suite (no regressions)**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (all existing tests still green — empty subset means identical behaviour).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix courses/views_analytics.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py tests/test_analytics_views.py
git commit -m "feat(3c-iii-b): analytics subset parse + scope sentinel + filter"
```

---

### Task 2: Thread the effective subset through every `_expand_qs` call site

Make `_expand_qs` carry a **required** `subset_pks` arg (emitted sorted), update `_decorate_links` (+ its caller) and the bands/breakdown call sites, so every navigation link round-trips the subset (spec §2, decision #8). This is the round-trip half of the contract, plus the breakdown back-link (C1) and the bands `_matrix_redirect` POST read.

**Files:**
- Modify: `courses/views_analytics.py` (`_expand_qs` :101; `_decorate_links` :108 + its caller in `analytics_matrix`; `_matrix_redirect` :82; `analytics_student` :136; and the three `*_url` lines + `clear_url` in `analytics_matrix`)
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: Task 1's `subset_pks` set in `analytics_matrix`.
- Produces: `_expand_qs(scope, mode, expand_pks, subset_pks) -> str` (required 4th arg; emits `student=` sorted ascending, omitted when empty). `_decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks) -> list[int]`. All matrix nav links (toggle/colours/expand/collapse/breakdown/clear) and the breakdown `back_url` carry the subset; `_matrix_redirect` round-trips POSTed `student`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
from courses.views_analytics import _expand_qs


def test_expand_qs_emits_sorted_student_and_omits_when_empty():
    qs = _expand_qs("all", "progress", [], {3, 1, 2})
    assert "student=1&student=2&student=3" in qs
    assert "student" not in _expand_qs("all", "progress", [], set())


@pytest.mark.django_db
def test_nav_links_carry_subset(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?student={a.pk}")
    assert f"student={a.pk}" in resp.context["progress_url"]
    assert f"student={a.pk}" in resp.context["results_url"]
    assert f"student={a.pk}" in resp.context["colours_url"]
    # clear_url drops the subset
    assert "student=" not in resp.context["clear_url"]
    # the breakdown link on student A's row carries the subset
    row_a = next(r for r in resp.context["matrix"]["rows"] if r["student"].pk == a.pk)
    assert f"student={a.pk}" in row_a["breakdown_url"]


@pytest.mark.django_db
def test_breakdown_back_url_preserves_subset(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/student/{a.pk}/?student={a.pk}&student={b.pk}"
    )
    back = resp.context["back_url"]
    assert f"student={a.pk}" in back and f"student={b.pk}" in back


@pytest.mark.django_db
def test_bands_save_redirect_preserves_subset(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {"reset": "1", "scope": "all", "mode": "progress", "student": [str(a.pk)]},
    )
    assert resp.status_code == 302
    assert f"student={a.pk}" in resp["Location"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "expand_qs or nav_links or back_url or bands_save_redirect_preserves_subset" -v`
Expected: FAIL (`_expand_qs() missing 1 required positional argument` / subset not in URLs).

- [ ] **Step 3: Extend `_expand_qs` (required subset arg, sorted)**

In `courses/views_analytics.py`, replace `_expand_qs` (lines 101–105):

```python
def _expand_qs(scope, mode, expand_pks, subset_pks):
    """Querystring preserving scope/mode + expand pks + the student subset (all
    repeatable). subset_pks is emitted sorted ascending so links are stable; an
    empty subset emits no `student` param. The arg is required (not optional) so
    every call site must thread the subset and fails loudly until it does."""
    return urlencode(
        {
            "scope": scope,
            "mode": mode,
            "expand": list(expand_pks),
            "student": sorted(subset_pks),
        },
        doseq=True,
    )
```

- [ ] **Step 4: Thread the subset through `_decorate_links`**

Replace `_decorate_links` (lines 108–133) — add the `subset_pks` param and pass it to every `_expand_qs`:

```python
def _decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks):
    """Attach pre-built hrefs (spec §4): on each header cell an expand_url (a
    not-yet-expanded leaf with children) or a collapse_url (an expanded spanning
    cell); a breakdown_url per drillable row. Every href carries the round-tripped
    expand set (the REACHED expanded_nodes pks, self-cleaning) and the student
    subset."""
    base_pks = [en["pk"] for en in matrix["expanded_nodes"]]
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    for hrow in matrix["header_rows"]:
        for cell in hrow:
            if cell["is_leaf"]:
                if cell["expandable"]:
                    cell["expand_url"] = (
                        f"{matrix_path}?"
                        f"{_expand_qs(scope, mode, base_pks + [cell['node'].pk], subset_pks)}"
                    )
            else:  # an expanded spanning cell -> collapse removes its pk
                rest = [p for p in base_pks if p != cell["node"].pk]
                cell["collapse_url"] = (
                    f"{matrix_path}?{_expand_qs(scope, mode, rest, subset_pks)}"
                )
    for row in matrix["rows"]:
        if row["student"].pk in reviewable_ids:
            student_path = reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": row["student"].pk},
            )
            row["breakdown_url"] = (
                f"{student_path}?{_expand_qs(scope, mode, base_pks, subset_pks)}"
            )
    return base_pks
```

- [ ] **Step 5: Update the call sites in `analytics_matrix`**

In `analytics_matrix`, pass `subset_pks` to `_decorate_links` and add it to the three `*_url` lines and `clear_url`:

```python
    base_pks = _decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks)
```
```python
    clear_url = f"{matrix_path}?{_expand_qs(scope, mode, base_pks, set())}"
```
```python
            "progress_url": f"{matrix_path}?{_expand_qs(scope, 'progress', base_pks, subset_pks)}",
            "results_url": f"{matrix_path}?{_expand_qs(scope, 'results', base_pks, subset_pks)}",
            "colours_url": f"{bands_path}?{_expand_qs(scope, mode, base_pks, subset_pks)}",
```

- [ ] **Step 6: Update `_matrix_redirect` (bands POST round-trip)**

Replace `_matrix_redirect` (lines 82–87):

```python
def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    expand_pks = _clean_expand(request.POST.getlist("expand"))
    subset_pks = _clean_expand(request.POST.getlist("student"))
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{_expand_qs(scope, mode, expand_pks, subset_pks)}")
```

- [ ] **Step 7: Update `analytics_student` back_url (C1 breakdown back-link)**

In `analytics_student` (lines 136–161), parse `student` (int-clean only — this view resolves no pool) and thread it into `back_url`. Change the `expand_pks` line and the `back_url`:

```python
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    subset_pks = _clean_expand(request.GET.getlist("student"))
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
```
```python
            "back_url": f"{matrix_path}?{_expand_qs(scope, mode, expand_pks, subset_pks)}",
```

- [ ] **Step 8: Run the new tests + full analytics suite**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (all — the 4 new round-trip tests plus every prior test).

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff check --fix courses/views_analytics.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py tests/test_analytics_views.py
git commit -m "feat(3c-iii-b): round-trip the student subset through every nav link"
```

---

### Task 3: Matrix template — single form, checkboxes, Apply/Clear/count/Select-all + CSS

Rewrite `analytics_matrix.html` into one GET form (controls header + table), add the row checkbox in the frozen Student cell, the `scope_rendered` sentinel, the always-rendered Apply (old `<noscript>` removed), the `show_clear` Clear link, the table-branch count, and a no-`name` Select-all with a tiny JS handler. Add one CSS rule. (Spec §3, §4.)

**Files:**
- Modify: `templates/courses/manage/analytics_matrix.html` (full rewrite)
- Modify: `core/static/core/css/app.css` (append one rule near the analytics block, ~line 531)
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: Task 1 context (`subset_pks`, `subset_size`, `show_clear`, `clear_url`, `scope`) + Task 2 links.
- Produces: a matrix page that is exactly one `<form method="get">`; each body row has a `name="student"` checkbox `checked` iff in `subset_pks`; a hidden `scope_rendered`; one always-visible Apply (not `<noscript>`); a `.analytics__selectall` header checkbox with no `name`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_views.py`:

```python
@pytest.mark.django_db
def test_matrix_is_single_form_with_sentinel_and_checkboxes(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    html = client.get(f"/manage/courses/{course.slug}/analytics/").content.decode()
    # exactly one <form> inside the analytics section (base.html may have others)
    section = html.split('class="manage analytics"')[1].split("</section>")[0]
    assert section.count("<form") == 1
    # the sentinel hidden input echoes the rendered scope
    assert '<input type="hidden" name="scope_rendered" value="all">' in html
    # a row checkbox per student
    assert f'name="student" value="{a.pk}"' in html
    # Apply is no longer wrapped in <noscript>
    assert "<noscript>" not in html
    # Select-all header control present
    assert "analytics__selectall" in html


@pytest.mark.django_db
def test_matrix_checkbox_checked_and_clear_visible_for_subset(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    html = client.get(
        f"/manage/courses/{course.slug}/analytics/?student={a.pk}"
    ).content.decode()
    # A's checkbox checked, Clear link shown
    seg = html.split(f'name="student" value="{a.pk}"')[1].split(">")[0]
    assert "checked" in seg
    assert "analytics__clear" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_analytics_views.py -k "single_form or checkbox_checked" -v`
Expected: FAIL (no `scope_rendered`, no checkbox, noscript still present).

- [ ] **Step 3: Rewrite the matrix template**

Replace the entire contents of `templates/courses/manage/analytics_matrix.html` with:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Analytics" %} · {{ course.title }} · libli{% endblock %}
{% block content %}
<section class="manage analytics">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Analytics" %} — {{ course.title }}</h1>
    {% if can_edit_bands %}
      <a class="btn btn--ghost btn--small" href="{{ colours_url }}">
        {% trans "Configure colours" %}</a>
    {% endif %}
  </header>

  {% comment %}One GET form wraps the controls AND the table so the row checkboxes
  submit with scope/mode/expand. The form is a plain block; flex lives only on the
  inner .analytics__controls div (else the legend/table become flex items).
  scope_rendered is the sentinel: the view discards the subset when the submitted
  scope differs from it (decision #9).{% endcomment %}
  <form method="get">
    <input type="hidden" name="mode" value="{{ mode }}">
    <input type="hidden" name="scope_rendered" value="{{ scope }}">
    {% for pk in expand_pks %}<input type="hidden" name="expand" value="{{ pk }}">{% endfor %}
    <div class="analytics__controls">
      <label>{% trans "Students" %}
        <select name="scope" onchange="this.form.submit()">
          {% for c in scope_choices %}
            <option value="{{ c.value }}" {% if c.value == scope %}selected{% endif %}>{{ c.label }}</option>
          {% endfor %}
        </select>
      </label>
      <span class="analytics__toggle" role="group" aria-label="{% trans 'Metric' %}">
        <a class="btn btn--small {% if mode == 'progress' %}is-active{% endif %}"
           href="{{ progress_url }}">{% trans "Progress" %}</a>
        <a class="btn btn--small {% if mode == 'results' %}is-active{% endif %}"
           href="{{ results_url }}">{% trans "Results" %}</a>
      </span>
      <button class="btn btn--small btn--primary" type="submit">{% trans "Apply" %}</button>
      {% if show_clear %}<a class="btn btn--small btn--ghost analytics__clear" href="{{ clear_url }}">{% trans "Show all" %}</a>{% endif %}
      {% if matrix.rows and matrix.columns and subset_size %}<span class="analytics__count">{% blocktrans with n=subset_size %}{{ n }} selected{% endblocktrans %}</span>{% endif %}
    </div>

    <ul class="analytics__legend">
      {% for b in legend %}
        <li><span class="analytics__swatch" style="background:{{ b.color }}"></span>
          {{ b.label }} ({{ b.lo }}–{{ b.hi }}%)</li>
      {% endfor %}
    </ul>

    {% if not matrix.rows %}
      <p class="muted">{% trans "No students in this scope." %}</p>
    {% elif not matrix.columns %}
      <p class="muted">{% trans "No content in this course yet." %}</p>
    {% else %}
      <div class="analytics__scroll">
        <table class="analytics__matrix">
          {% comment %}Nested header: each expanded node is one spanning cell over its
          descendant columns (colspan), children one row below; a shallow leaf rowspans
          down so its title (top-aligned via CSS) lines up with same-depth siblings.{% endcomment %}
          <thead>
            {% for hrow in matrix.header_rows %}
              <tr>
                {% if forloop.first %}
                  <th class="analytics__rowhead" rowspan="{{ matrix.total_rows }}" style="top:0">
                    <input type="checkbox" class="analytics__selectall" aria-label="{% trans 'Select all students' %}">
                    {% trans "Student" %}</th>
                {% endif %}
                {% for cell in hrow %}
                  <th class="analytics__colhead{% if not cell.is_leaf %} analytics__group{% endif %}"
                      colspan="{{ cell.colspan }}" rowspan="{{ cell.rowspan }}"
                      style="top:calc(var(--ahead-h) * {{ forloop.parentloop.counter0 }})">
                    {% if cell.is_leaf %}
                      {% if cell.expandable %}<a class="analytics__expand" href="{{ cell.expand_url }}"
                         lang="{{ course.language }}">{{ cell.title }} ▸</a>{% else %}<span
                         lang="{{ course.language }}">{{ cell.title }}</span>{% endif %}
                    {% else %}<span class="analytics__group-title"
                         lang="{{ course.language }}">{{ cell.title }}</span><a
                         class="analytics__collapse" href="{{ cell.collapse_url }}"
                         aria-label="{% trans 'Collapse' %}">✕</a>{% endif %}
                  </th>
                {% endfor %}
                {% if forloop.first %}
                  <th class="analytics__overall" rowspan="{{ matrix.total_rows }}" style="top:0">{% trans "Overall" %}</th>
                {% endif %}
              </tr>
            {% endfor %}
          </thead>
          <tbody>
            {% for row in matrix.rows %}
              <tr>
                <td class="analytics__rowhead">
                  <input type="checkbox" name="student" value="{{ row.student.pk }}"
                         {% if row.student.pk in subset_pks %}checked{% endif %}
                         aria-label="{% blocktrans with name=row.student.display_name|default:row.student.username %}Select {{ name }}{% endblocktrans %}">
                  {% if row.breakdown_url %}<a href="{{ row.breakdown_url }}">{{ row.student.display_name|default:row.student.username }}</a>{% else %}{{ row.student.display_name|default:row.student.username }}{% endif %}</td>
                {% for cell in row.cells %}
                  {% include "courses/manage/_analytics_cell.html" %}
                {% endfor %}
                {% with cell=row.overall %}
                  <td class="analytics__overall{% if cell.percent is None %} analytics__cell--empty{% endif %}"
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
                <td class="analytics__overall{% if cell.percent is None %} analytics__cell--empty{% endif %}"
                    {% if cell.color %}style="background:{{ cell.color }};color:{{ cell.text_color }}"{% endif %}>
                  {{ cell.label }}</td>
              {% endwith %}
            </tr>
          </tfoot>
        </table>
      </div>
      {% if mode == "results" and not matrix.has_quizzes %}
        <p class="muted">{% trans "No quizzes in this course yet." %}</p>
      {% endif %}
    {% endif %}
  </form>
</section>
{% endblock %}

{% block extra_js %}
<script>
  // Select-all: toggles every rendered row checkbox. Pure enhancement — the
  // control carries no `name`, so no-JS users just check rows individually.
  document.querySelectorAll(".analytics__selectall").forEach(function (sa) {
    sa.addEventListener("change", function () {
      document.querySelectorAll('input[name="student"]').forEach(function (cb) {
        cb.checked = sa.checked;
      });
    });
  });
</script>
{% endblock %}
```

- [ ] **Step 4: Add the CSS rule**

In `core/static/core/css/app.css`, immediately after the `.analytics__toggle .btn.is-active` line (~531), add:

```css
.analytics__rowhead input[type="checkbox"]{margin-right:.4rem;vertical-align:middle}
.analytics__count{font-size:.8rem;color:var(--text-secondary)}
```

- [ ] **Step 5: Run the template tests + full analytics suite**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (the 2 new template tests + all prior).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix tests/test_analytics_views.py
uv run ruff format tests/test_analytics_views.py
git add templates/courses/manage/analytics_matrix.html core/static/core/css/app.css tests/test_analytics_views.py
git commit -m "feat(3c-iii-b): single-form matrix with row checkboxes, Apply/Clear/Select-all"
```

---

### Task 4: Bands template — hidden `student` loop + view context

The bands view already round-trips scope/mode/expand; add the `student` subset to its context and a hidden-input loop so Save/Reset POST the subset (which `_matrix_redirect` already reads, Task 2). (Spec §2/§3.)

**Files:**
- Modify: `courses/views_analytics.py` (`analytics_bands`, the render context, lines ~186–209)
- Modify: `templates/courses/manage/analytics_bands.html` (add one hidden loop after line 14)
- Test: `tests/test_analytics_views.py` (append)

**Interfaces:**
- Consumes: `_clean_expand`; the existing `src = request.POST if POST else request.GET` pattern.
- Produces: `analytics_bands` context gains `subset: list[int]`; the bands form renders one hidden `student` input per pk.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analytics_views.py`:

```python
@pytest.mark.django_db
def test_bands_form_renders_hidden_student_inputs(client):
    owner = make_login(client, "owner")
    course, les, a, b = _course_with_two_students(owner)
    html = client.get(
        f"/manage/courses/{course.slug}/analytics/colors/?student={a.pk}"
    ).content.decode()
    assert f'<input type="hidden" name="student" value="{a.pk}">' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_analytics_views.py -k bands_form_renders_hidden -v`
Expected: FAIL (no hidden student input).

- [ ] **Step 3: Add `subset` to the bands context**

In `courses/views_analytics.py`, in `analytics_bands`, the render context dict already has a `src = request.POST if request.method == "POST" else request.GET` line. Add a `subset` key alongside `scope`/`mode`/`expand_pks`:

```python
            "scope": src.get("scope", "all"),
            "mode": "results" if src.get("mode") == "results" else "progress",
            "expand_pks": _clean_expand(src.getlist("expand")),
            "subset": _clean_expand(src.getlist("student")),
```

- [ ] **Step 4: Add the hidden loop to the bands template**

In `templates/courses/manage/analytics_bands.html`, after the existing hidden-`expand` loop (line 14), add:

```django
    {% for pk in subset %}<input type="hidden" name="student" value="{{ pk }}">{% endfor %}
```

- [ ] **Step 5: Run the test + full analytics suite**

Run: `uv run pytest tests/test_analytics_views.py -v`
Expected: PASS (incl. `test_bands_save_redirect_preserves_subset` from Task 2, now end-to-end).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix courses/views_analytics.py tests/test_analytics_views.py
uv run ruff format courses/views_analytics.py tests/test_analytics_views.py
git add courses/views_analytics.py templates/courses/manage/analytics_bands.html tests/test_analytics_views.py
git commit -m "feat(3c-iii-b): bands form round-trips the student subset"
```

---

### Task 5: i18n — EN + PL for the new strings

Extract and translate the new user-facing strings: "Apply", "Show all", "Select all students", "Select %(name)s", "%(n)s selected". (Global Constraints / spec §4.)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (translations) + compiled `.mo`
- Test: `tests/test_i18n_auth.py::test_po_catalog_clean` (existing meta-test — must stay green)

**Interfaces:** none (string catalog only).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Then open `locale/pl/LC_MESSAGES/django.po` and find the new untranslated msgids: `Apply`, `Show all`, `Select all students`, `Select %(name)s`, `%(n)s selected`.

- [ ] **Step 2: Translate (and clear any `#, fuzzy` flags makemessages added)**

Set these msgstrs (remove any `#, fuzzy` line above each):

```po
msgid "Apply"
msgstr "Zastosuj"

msgid "Show all"
msgstr "Pokaż wszystkich"

msgid "Select all students"
msgstr "Zaznacz wszystkich uczniów"

msgid "Select %(name)s"
msgstr "Zaznacz: %(name)s"

msgid "%(n)s selected"
msgstr "Zaznaczono: %(n)s"
```

Grep to confirm no stray fuzzy/obsolete entries: `uv run python -c "import re,sys; t=open('locale/pl/LC_MESSAGES/django.po',encoding='utf-8').read(); print('FUZZY' if '#, fuzzy' in t else 'ok'); print('OBSOLETE' if '#~' in t else 'ok')"`

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: `processing file django.po in …/locale/pl/LC_MESSAGES` with no errors.

- [ ] **Step 4: Run the i18n meta-test + a PL render sanity check**

Run: `uv run pytest tests/test_i18n_auth.py -v`
Expected: PASS (`test_po_catalog_clean` green — no `#, fuzzy`, no `#~`).

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(3c-iii-b): PL for subset controls (Apply/Show all/Select/N selected)"
```

---

### Task 6: e2e — the cherry-pick gesture (real Playwright)

Drive the real check → Apply → Clear path (and Select-all): a teacher narrows the matrix to a subset, then restores the full scope. (Spec §Testing; e2e-must-drive-real-UI.)

**Files:**
- Modify: `tests/test_e2e_analytics.py` (append a test)

**Interfaces:** none.

- [ ] **Step 1: Write the e2e test**

Append to `tests/test_e2e_analytics.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_teacher_cherry_picks_a_subset(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa("owner")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    students = [UserFactory() for _ in range(3)]
    for s in students:
        Enrollment.objects.create(student=s, course=course)
        UnitProgressFactory(student=s, unit=les, completed=True)

    _login(page, live_server, "owner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    # all three rows present
    expect(page.locator('input[name="student"]')).to_have_count(3)
    # Select-all, then uncheck the first student, then Apply
    page.locator(".analytics__selectall").check()
    page.locator('input[name="student"]').first.uncheck()
    page.get_by_role("button", name=re.compile("Apply", re.I)).click()
    # now two rows remain
    expect(page.locator('input[name="student"]')).to_have_count(2)
    # Clear ("Show all") restores all three
    page.get_by_role("link", name=re.compile("Show all", re.I)).click()
    expect(page.locator('input[name="student"]')).to_have_count(3)
```

- [ ] **Step 2: Run the e2e test (needs `-m e2e`)**

Run: `uv run pytest tests/test_e2e_analytics.py -k cherry_picks -m e2e -v`
Expected: PASS (real browser; 3 → 2 → 3 rows).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_analytics.py
git commit -m "test(3c-iii-b): e2e cherry-pick subset (Select-all, uncheck, Apply, Show all)"
```

---

### Task 7: Full-suite verification + screenshot polish

Confirm no regressions and verify the control bar looks right in light + dark (the styling lesson: screenshot before claiming done).

**Files:** none (verification only; any CSS tweak goes to `core/static/core/css/app.css`).

- [ ] **Step 1: Full non-e2e suite**

Run: `uv run pytest -q`
Expected: PASS (all green; addopts excludes e2e).

- [ ] **Step 2: Analytics e2e**

Run: `uv run pytest tests/test_e2e_analytics.py -m e2e -v`
Expected: PASS (both the 3c-ii journey and the new cherry-pick test).

- [ ] **Step 3: ruff + migration check**

```bash
uv run ruff check
uv run ruff format --check
uv run python manage.py makemigrations --check --dry-run
```
Expected: clean; **no migrations** (this slice adds no model field).

- [ ] **Step 4: Screenshot light + dark (throwaway harness, delete after)**

Use a disposable Playwright snippet to capture `/manage/courses/<slug>/analytics/?student=<pk>` in both themes; confirm the checkbox aligns with the name, Apply/Clear/Select-all read clearly, and the count chip is legible. Delete the harness after review. (No commit unless a CSS tweak is needed; if so, commit it with `style(3c-iii-b): …`.)

- [ ] **Step 5: Final commit (if any tweak)**

```bash
git add -A
git commit -m "style(3c-iii-b): control-bar polish (light+dark verified)"
```

---

## Notes for the executor

- **No migration.** If `makemigrations --check` reports a change, something is wrong — this slice touches no model.
- **Gating is untouched.** Don't add permission checks; the subset only narrows the already-authorized `students_in_scope` pool, and `reviewable_students` per-row breakdown gating is unchanged.
- **The builder is not modified.** Only its `students` argument is filtered — the Average row recomputes for free.
- **`scope_rendered` value = the raw `scope`** the `<select>` shows (`request.GET.get("scope","all")`), not the resolved scope; the sentinel and the select stay in lockstep.
