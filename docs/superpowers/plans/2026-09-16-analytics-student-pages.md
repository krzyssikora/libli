# Analytics student pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two teacher analytics drill-down pages say what they mean: students listed by surname, the student results page following the matrix's Progress/Results view, and the per-question page showing every choice option, labelled answers and outcome colour.

**Architecture:** Two PRs. **PR A** adds one ordering helper in `grouping/scoping.py` and swaps the matrix and gradebook export to it and to `User.list_display_name`. **PR B** threads the matrix `mode` into `build_student_breakdown` (which prunes to quizzes in Results mode), rewrites the breakdown rows, extends `courses/answer_summary.py` with an `Option` record fed by the `choice_marks` dict the view already computes, restructures the per-question template (options table, a three-column grid for multi-part questions, a two-line header), localises the `marks` filter, and adds outcome modifiers to the verdict badge on both verdict pages.

**Tech Stack:** Django 5 templates + views, pytest + pytest-django, BeautifulSoup for rendered-HTML tests, Playwright (sync) for computed-style e2e tests, gettext catalogs (`locale/pl`, `locale/en`).

**Spec:** `docs/superpowers/specs/2026-09-16-analytics-student-pages-design.md` — read it alongside this plan. Section numbers (§) and test ids (T1…T34) below are the spec's.

## Global Constraints

- **Order key (D5):** `(polish_sort_key(u.sort_name), u.username)`. Display label: `User.list_display_name`.
- **Mode vocabulary:** `"progress"` | `"results"`; anything else normalises to `"progress"` (via `_drill_params`, never a second rule).
- **Never read `Choice.is_correct`** in `answer_summary.py` or the templates. The key comes from `mark_result.reveal`.
- **`_choice` never calls `choice_marks`.** The only call site feeding this page is `courses/views.py::_results_row`; `courses/models.py`'s own `self.choice_marks(...)` call is the lesson/quiz render path and unrelated. This work adds no third call site.
- **Every §4 CSS rule goes in `core/static/core/css/app.css`** (the student results page does not link `courses.css`). The §5.4 badge modifiers go in `courses/static/courses/css/courses.css` beside `.badge--muted`.
- **No stylesheet line citations anywhere in live code** — `tests/test_css_citations_are_durable.py` fails on any `<name>.css:<digits>` in `.py/.js/.html/.css`. Name the selector instead (``app.css's `.badge--done` ``).
- **Django template comments:** `{# … #}` is single-line ONLY. Anything spanning lines uses `{% comment %}…{% endcomment %}`.
- **Included templates do not inherit `{% load %}`.** `_quiz_pill.html` and `_breakdown_node.html` must load `courses_extras` themselves when they use `|marks` / `marker_label`.
- **No `only` on `_breakdown_node.html`'s recursive include** — it reads `mode`, `student`, `drill_qs` from the inherited context.
- **Interface text (spec §6), exact strings:**

  | msgid | pl msgstr |
  |---|---|
  | `Student's answer:` | `Odpowiedź ucznia:` |
  | `Student's answer` | `Odpowiedź ucznia` |
  | `Student's choice` | `Wybór ucznia` |
  | `Answer key` | `Klucz` — ⚠️ never the bare `Key`, which is already „Legenda" |
  | `chosen, correct` | `wybrana, poprawna` |
  | `chosen, incorrect` | `wybrana, niepoprawna` |
  | `correct, not chosen` | `poprawna, niewybrana` |
  | `chosen` | `wybrana` — ⚠️ plan addition, see "Spec gaps" below |
  | `correct answer: %(key)s` | `poprawna odpowiedź: %(key)s` |
  | `%(s)s / %(m)s marks` | `%(s)s / %(m)s pkt` |
  | `Not completed` | `Nieukończone` |
  | `Student results` | `Wyniki ucznia` |

  Reused, never re-created: `Answer`, `Correct answer:`, `(removed option)`, `(none)`, `Not answered`, `Correct`/`Incorrect`/`Partial`, `Review`, `Additional` (via `marker_label` only), `Progress`/`Results`, `Metric`, `Completed`, `scored %(s)s/%(m)s`.
- **Catalog procedure (every task that adds or removes a msgid):**
  1. `uv run python manage.py makemessages -l pl -l en`
  2. For each msgid this task adds: open `locale/pl/LC_MESSAGES/django.po`, **overwrite** the `msgstr` from the table above unconditionally, and delete any `#, fuzzy` and `#| msgid` lines on that entry. `makemessages` fuzzy-prefills from similar msgids (e.g. `Answer key` from `Key` → „Legenda"). Leave `locale/en` msgstrs empty (repo convention).
  3. `grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po` → both `0`. (Do not anchor with `$`: the `.po` files are CRLF.)
  4. `uv run python manage.py compilemessages -l pl -l en`
  5. Commit both `.po` and both `.mo`.
- **Polish in a view test:** set the session key, never `Accept-Language`:
  ```python
  def _polish(client):
      from core.middleware import LANGUAGE_SESSION_KEY

      session = client.session
      session[LANGUAGE_SESSION_KEY] = "pl"
      session.save()
  ```
- **Test mechanics:**
  - Start the test DB once per session: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`.
  - Tools are not on PATH: `uv run pytest …`, `uv run ruff …`, `uv run python manage.py …`.
  - **Never pass `-q`** (addopts already has it; a second one hides the summary).
  - e2e tests need `-m e2e` (addopts deselects them).
  - Read the pytest summary line, not just the exit code.
  - Scope runs to the files a task touches; whole-suite runs are a branch gate (last task of each PR), in chunks.
  - Before each commit: `uv run ruff format <every .py file the task touched>`, then `uv run ruff check --no-cache .` and `uv run ruff format --check .`. The plan's code blocks are **not** pre-formatted — the formatter's output wins. A line the formatter cannot break (a long string literal, a long f-string, a long line inside a triple-quoted JS string) must be split by hand — implicit string concatenation or a local variable — so E501 (88 columns) passes.
- **Falsification (every test marked *Mutant*):** apply the mutant **by hand with Edit**, run the one test, observe **red for the stated reason**, revert **by hand with Edit**, then `git diff` to confirm only intended changes remain. **Never `git checkout -- <file>` to revert a mutant** — it destroys the uncommitted implementation.
- **No assertion may rest on database ids** (pks of different models are independent sequences). Compare usernames, titles and rendered text; build expected hrefs with `reverse`/`_expand_qs` from the objects themselves.

## Spec gaps found while planning (the plan resolves them as stated)

1. **T10's mutant cannot fail.** "Prune before `attach`" leaves every quiz in place (`is_quiz_unit` does not read the pill) and `attach` still reaches it on the pruned tree. Task B2 uses a mutant that can fail: a **non-recursive** prune (a container is kept only if it has a *direct* quiz child).
2. **A non-auto choice question would hide the student's pick from assistive tech.** §5.1 aria-hides nothing explicitly but emits a label only when `mark` is set; on a REVIEW/NOT_MARKED question every row has `mark is None`, so a screen reader hears no pick at all — a regression against today's „Odpowiedź: B" text. Task B6 aria-hides the ●/○/✓ glyphs and adds one `sr-only` „wybrana" on a picked row that has no verdict. T21b's "exactly one label per row" still holds. Flag this in PR B's body for the owner.
3. **T33b as written passes on a transparent badge.** A transparent computed background (`rgba(0, 0, 0, 0)`) "differs" from the panel tint while showing it through — the exact green-on-green §2.7 warns about. Task B9's e2e also asserts the badge background is **opaque**.
4. **`quiz_results.html` carries no drift note today** (only `analytics_student_quiz.html` does). Task B9 adds a single-line `{# … #}` to it, appended to an existing line so the file's line count is unchanged.
5. **`.pill--awaiting`'s token re-expression (§5.4) names no tokens.** Task B9 uses `--warning-subtle` fill, `--warning` border, `--text-primary` text (AA-safe in both themes; `--warning` text on `--warning-subtle` is ~2.9:1 in light).
6. **`--warning` text on `--surface-sunken` (§5.4 `.badge--partial`) FAILS AA in light mode: 3.19:1** (`#B8811F` on `#FAF8F3`, computed from `tokens.css`; dark `#E8B761` on `#15130F` passes easily). Asked in **Task 0** below; if the owner has not answered, Task B9 implements the spec as written, Task B11 re-measures it in the browser as confirmation, and the PR body quotes the ratio. The colour is never changed unilaterally.
7. **T19 cannot catch a re-deriving builder.** A `_choice` that calls `choice_marks` itself computes the very dict the page computed, so T19's equality stays green. Task B5 adds **T19b**: the builder is handed a doctored dict and must follow it.

## File map

**PR A**
- Modify `grouping/scoping.py` — add `ordered_students`.
- Modify `courses/views_analytics.py` (matrix view), `courses/views_export.py` — call the helper.
- Modify `templates/courses/manage/analytics_matrix.html` (row name + checkbox label), `courses/gradebook.py` (both `name` fields).
- Modify `accounts/models.py` (`sort_name` docstring, line-count neutral), `tests/demo/test_provision.py` (stale comment, line-count neutral).
- Modify `docs/help/teacher/analytics.md`, `analytics.pl.md`.
- Create `tests/test_analytics_student_order.py` (T1–T5).

**PR B**
- Modify `courses/templatetags/courses_extras.py` (`marks_filter`), `templates/courses/manage/_quiz_pill.html`.
- Modify `courses/rollups.py` (`build_student_breakdown`, new `_keep_quizzes`).
- Modify `courses/views_analytics.py` (`analytics_student`, `_quiz_answer_rows`).
- Modify `templates/courses/manage/analytics_student.html`, `_breakdown_node.html`, `analytics_student_quiz.html`, `templates/courses/quiz_results.html`.
- Modify `courses/answer_summary.py` (`Option`, `Part` fields, `_choice`, `summarise`).
- Modify `tests/answer_summary_fixtures.py` (`summarise_stored`).
- Modify `core/static/core/css/app.css`, `courses/static/courses/css/courses.css`.
- Modify `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`.
- Modify `docs/help/teacher/drill-down.md`, `drill-down.pl.md`.
- Create `tests/test_analytics_student_page.py` (T6–T13, T15, T16, T28b), `tests/test_e2e_analytics_student_pages.py` (T14, T33, T33b, T33c).
- Modify `tests/test_answer_summary.py` (T17–T18 builder half), `tests/test_analytics_student_quiz.py` (T18 page half, T19–T32; T36 replaced by T27), `tests/test_quiz_scoring.py` (marks filter), `tests/test_analytics_student_order.py` (delete T5).

---

# PR A — student order and names (§3)

**Where to work.** This plan and its spec live ONLY on the local, unpushed `docs/analytics-pupil-pages-spec` branch; switching the main checkout to a branch cut from `origin/master` would remove both from the working tree. So execute in a **separate worktree** and leave the main checkout on the docs branch:

```bash
git -C C:/Users/krzys/Documents/Python/own/libli fetch origin
git -C C:/Users/krzys/Documents/Python/own/libli worktree add C:/Users/krzys/Documents/Python/own/libli-analytics-pages -b feat/analytics-student-order origin/master
```

Then, from the worktree, give it the main checkout's `.env` (gitignored; `config/settings/test.py` pins DEBUG and the vendor flag, so it is safe for tests) and prove the tests will hit the disposable container, not the local server holding mat-pp:

```bash
cp C:/Users/krzys/Documents/Python/own/libli/.env .env
echo "$TEST_DATABASE_URL"
uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test'); django.setup(); from django.conf import settings; print(settings.DATABASES['default']['PORT'])"
```

Expected: the URL ends `127.0.0.1:55433/libli` (the shell profile exports it in every shell — a one-off `export` would not survive between tool calls, and editing `.env` cannot override it) and the port prints `55433`. **If either differs, stop**: without it the suite creates and drops `test_libli` on the local server.

Run every command of PR A and PR B from `C:/Users/krzys/Documents/Python/own/libli-analytics-pages`. Read the plan and spec by absolute path from the main checkout (`C:/Users/krzys/Documents/Python/own/libli/docs/superpowers/…`). Never run tests in two trees at once — they share the test database.

### Task 0: Owner question before execution

- [ ] **Step 1:** Ask the owner (plain text, not a dialog): "`.badge--partial` (§5.4) is `--warning` text on `--surface-sunken`, 3.19:1 in light mode — below AA. Keep it as specified, or use a different text colour for the partial badge (e.g. `--text-primary` with the `--warning` border)?"
- [ ] **Step 2:** Record the answer as one line under "Spec gaps" item 6 in this plan (in the main checkout, committed on the docs branch). Task B9 Step 4 follows it: "keep" or no answer → the CSS as written; a named alternative → change only `.badge--partial`'s `color` declaration, and keep T33b's assertions unchanged.

### Task A1: One ordering helper, used by the matrix and the export

**Files:**
- Modify: `grouping/scoping.py` (imports; new function after `students_in_scope`)
- Modify: `courses/views_analytics.py` (`analytics_matrix`, the `if subset_pks:` block)
- Modify: `courses/views_export.py` (`gradebook_export`, the `students = (...)` expression)
- Create: `tests/test_analytics_student_order.py`

**Interfaces:**
- Produces: `grouping.scoping.ordered_students(students) -> list[User]`.

- [ ] **Step 1: Write the failing tests (T1, T2, T4)**

Create `tests/test_analytics_student_order.py`:

```python
"""Student order and names in the analytics matrix and gradebook export
(spec §3; T1-T5)."""

import csv
import io

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

# (username, first, last, display_name). Usernames are in generation order,
# which disagrees with surname order on purpose (T4).
ROSTER = [
    ("a_swiatek", "Iga", "Świątek", "Iga Świątek"),
    ("b_nowakowska", "Beata", "Nowakowska", "Beata Nowakowska"),
    ("c_nowak", "Anna", "Nowak", "Anna Nowak"),
    ("d_zych", "Tomasz", "Zych", "TZ nick"),  # unrelated display name (T3)
    ("e_adamczyk_m", "Mateusz", "Adamczyk", "Mateusz Adamczyk"),
    ("f_adamczyk_k", "Kamil", "Adamczyk", "Kamil Adamczyk"),
    ("g_login", "", "", "Borys"),  # no structured names: sorts by display name
]
# Surname, then first name, Polish alphabetical. Świątek before Zych is the
# polish_sort_key case: by raw codepoint "Ś" sorts after "Z".
EXPECTED_USERNAMES = [
    "f_adamczyk_k",
    "e_adamczyk_m",
    "g_login",
    "c_nowak",
    "b_nowakowska",
    "a_swiatek",
    "d_zych",
]


def _class(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, obligatory=True
    )
    users = {}
    for username, first, last, display in ROSTER:
        user = UserFactory(
            username=username, first_name=first, last_name=last, display_name=display
        )
        EnrollmentFactory(student=user, course=course)
        users[username] = user
    return course, users


def _matrix_usernames(client, course):
    resp = client.get(reverse("courses:manage_analytics", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    return [row["student"].username for row in resp.context["matrix"]["rows"]]


def _export_rows(client, course, shape):
    body = client.get(
        reverse("courses:manage_analytics_export", kwargs={"slug": course.slug}),
        {"shape": shape, "format": "csv"},
    ).content.decode("utf-8-sig")
    usernames = {username for username, *_rest in ROSTER}
    # Column 1 is Username; the title, subtitle, header, Max and Average rows
    # never carry one of the roster's usernames.
    return [row for row in csv.reader(io.StringIO(body)) if row[1:2] and row[1] in usernames]


def test_t4_fixture_username_order_disagrees_with_surname_order():
    assert sorted(EXPECTED_USERNAMES) != EXPECTED_USERNAMES


def test_t1_matrix_lists_students_by_surname_then_first_name(client):
    course, _users = _class(client)
    assert _matrix_usernames(client, course) == EXPECTED_USERNAMES


def test_t1_matrix_subset_keeps_the_same_order(client):
    course, users = _class(client)
    subset = [users["d_zych"], users["a_swiatek"], users["f_adamczyk_k"]]
    resp = client.get(
        reverse("courses:manage_analytics", kwargs={"slug": course.slug}),
        {"student": [u.pk for u in subset]},
    )
    got = [row["student"].username for row in resp.context["matrix"]["rows"]]
    assert got == ["f_adamczyk_k", "a_swiatek", "d_zych"]


@pytest.mark.parametrize("shape", ["matrix", "quiz"])
def test_t2_export_rows_follow_the_same_order(client, shape):
    course, _users = _class(client)
    assert [row[1] for row in _export_rows(client, course, shape)] == EXPECTED_USERNAMES
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_order.py`
Expected: T4 PASS; both T1 tests and both T2 cases FAIL (lists in username order).

- [ ] **Step 3: Add the helper**

In `grouping/scoping.py`, add to the imports (keep one import per line, isort order — `core` sorts before `courses`):

```python
from core.collation import polish_sort_key
```

Append after `students_in_scope`:

```python
def ordered_students(students):
    """Register order: surname, then first name, Polish alphabetical; username
    breaks ties (spec §3.1). The same key grouping/views.py's rosters use.
    Returns a LIST -- every consumer already calls list() or iterates."""
    return sorted(students, key=lambda u: (polish_sort_key(u.sort_name), u.username))
```

- [ ] **Step 4: Use it in both views**

`courses/views_analytics.py`, replace

```python
    if subset_pks:
        students = pool.filter(pk__in=subset_pks).order_by("username")
    else:
        students = pool.order_by("username")
```

with

```python
    students = scoping.ordered_students(
        pool.filter(pk__in=subset_pks) if subset_pks else pool
    )
```

`courses/views_export.py`, replace

```python
    students = (
        pool.filter(pk__in=subset_pks).order_by("username")
        if subset_pks
        else pool.order_by("username")
    )
```

with

```python
    students = scoping.ordered_students(
        pool.filter(pk__in=subset_pks) if subset_pks else pool
    )
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_analytics_student_order.py tests/test_analytics_views.py tests/test_views_export.py`
Expected: all PASS.

- [ ] **Step 6: Falsify**

- *Mutant 1:* in `analytics_matrix`, bypass the helper — replace the `students = scoping.ordered_students(...)` statement with the original `if subset_pks: students = pool.filter(pk__in=subset_pks).order_by("username")` / `else: students = pool.order_by("username")` block → T1 red. (Adding `.order_by` INSIDE the helper call stays green: the helper re-sorts.) Revert by hand.
- *Mutant 2:* in `ordered_students`, change the key to `lambda u: (u.sort_name, u.username)` → T1 red with `a_swiatek` after `d_zych`. Revert.
- *Mutant 3:* in `gradebook_export`, bypass the helper — replace the `scoping.ordered_students(...)` expression with the original `pool.filter(pk__in=subset_pks).order_by("username") if subset_pks else pool.order_by("username")` → T2 red for both shapes. Revert.
- `git diff` shows only Steps 3–4 and the new test file.

(The space-below-letters property is `tests/test_collation.py::test_space_sorts_before_letters`'s to falsify, not T1's — spec §2.2.)

- [ ] **Step 7: Commit**

```bash
git add grouping/scoping.py courses/views_analytics.py courses/views_export.py tests/test_analytics_student_order.py
git commit -m "feat(analytics): list students by surname in the matrix and export"
```

### Task A2: One display label in the matrix and the export

**Files:**
- Modify: `templates/courses/manage/analytics_matrix.html` (the `analytics__rowhead` cell in `<tbody>`)
- Modify: `courses/gradebook.py` (`build_matrix_table` and `build_quiz_gradebook` row `name`)
- Modify: `tests/test_analytics_student_order.py`

- [ ] **Step 1: Write the failing tests (T3, T5)**

Append to `tests/test_analytics_student_order.py`:

```python
from decimal import Decimal  # noqa: E402  (move into the import block above)

from bs4 import BeautifulSoup  # noqa: E402  (move into the import block above)

from courses.models import QuizSubmission  # noqa: E402  (move into the import block)


def _rowheads(client, course):
    html = client.get(
        reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    ).content.decode()
    return BeautifulSoup(html, "html.parser").select("tbody td.analytics__rowhead")


def test_t3_matrix_names_students_first_name_first(client):
    course, _users = _class(client)
    cells = _rowheads(client, course)
    by_text = {cell.get_text(" ", strip=True): cell for cell in cells}
    assert "Mateusz Adamczyk" in by_text
    assert "Borys" in by_text  # no structured names: display name
    assert "Tomasz Zych (TZ nick)" in by_text  # the parenthetical, in full
    # Zych's display name differs from his label, so reverting the aria-label
    # alone renders "Select TZ nick" and goes red.
    checkbox = by_text["Tomasz Zych (TZ nick)"].select_one("input[type=checkbox]")
    assert checkbox["aria-label"] == "Select Tomasz Zych (TZ nick)"


@pytest.mark.parametrize("shape", ["matrix", "quiz"])
def test_t3_export_names_students_first_name_first(client, shape):
    course, _users = _class(client)
    names = [row[0] for row in _export_rows(client, course, shape)]
    assert names == [
        "Kamil Adamczyk",
        "Mateusz Adamczyk",
        "Borys",
        "Anna Nowak",
        "Beata Nowakowska",
        "Iga Świątek",
        "Tomasz Zych (TZ nick)",
    ]


def test_t5_drill_down_headings_keep_the_display_name_until_pr_b(client):
    """PR A's boundary (spec §8). PR B DELETES this test -- it rewrites both
    headings by design, and T28/T28b are the successors."""
    course, users = _class(client)
    student = users["d_zych"]
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    student_page = client.get(
        reverse(
            "courses:manage_analytics_student",
            kwargs={"slug": course.slug, "student_pk": student.pk},
        )
    ).content.decode()
    quiz_page = client.get(
        reverse(
            "courses:manage_analytics_student_quiz",
            kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
        )
    ).content.decode()
    for html in (student_page, quiz_page):
        h1 = BeautifulSoup(html, "html.parser").select_one("h1").get_text(" ", strip=True)
        assert "TZ nick" in h1 and "Tomasz" not in h1
```

Move the three new imports into the module's import block (isort order) and drop the `noqa` comments.

- [ ] **Step 2: Run to verify T3 fails and T5 passes**

Run: `uv run pytest tests/test_analytics_student_order.py`
Expected: both T3 tests FAIL (display names: "TZ nick", "Select TZ nick"…); T5 PASS.

- [ ] **Step 3: Switch the matrix template**

In `templates/courses/manage/analytics_matrix.html`, inside `<tbody>`'s `analytics__rowhead` cell, replace the checkbox label and both name branches so the two lines read:

```django
                         aria-label="{% blocktrans with name=row.student.list_display_name %}Select {{ name }}{% endblocktrans %}">
                  {% if row.breakdown_url %}<a href="{{ row.breakdown_url }}">{{ row.student.list_display_name }}</a>{% else %}{{ row.student.list_display_name }}{% endif %}</td>
```

The msgid `Select %(name)s` is unchanged.

- [ ] **Step 4: Switch the gradebook**

In `courses/gradebook.py`, both row dicts: replace `"name": r["student"].display_name or r["student"].username,` with `"name": r["student"].list_display_name,` and `"name": s.display_name or s.username,` with `"name": s.list_display_name,`.

- [ ] **Step 5: Run to verify**

Run: `uv run pytest tests/test_analytics_student_order.py tests/test_analytics_views.py tests/test_views_export.py tests/test_exporters.py tests/test_gradebook.py tests/test_grouping_analytics_links.py tests/test_dashboard_panels.py tests/demo/test_provision.py`
Expected: all PASS.

- [ ] **Step 6: Falsify**

- *Mutant 1:* revert the row name cell to `display_name|default:username` → the matrix T3 test red. Revert.
- *Mutant 2:* revert only the `aria-label` → red on the checkbox assertion. Revert.
- *Mutant 3:* revert `build_quiz_gradebook`'s `name` → T3 export red for `quiz` only; revert; same for `build_matrix_table` → red for `matrix` only. Revert.
- *Mutant 4:* in `analytics_student.html`, change the `h1` to `student.list_display_name` → T5 red. Revert.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/analytics_matrix.html courses/gradebook.py tests/test_analytics_student_order.py
git commit -m "feat(analytics): name students First Surname in the matrix and export"
```

### Task A3: Stale comments, help text, screenshots, branch gate, PR

**Files:**
- Modify: `accounts/models.py` (`User.sort_name` docstring)
- Modify: `tests/demo/test_provision.py` (the two-line comment above `pupil = kit.users…`)
- Modify: `docs/help/teacher/analytics.md`, `docs/help/teacher/analytics.pl.md`
- Possibly modify: `core/static/core/img/help/analytics-matrix.{en,pl}.png`

- [ ] **Step 1: Repair the `sort_name` docstring, line-count neutral**

In `accounts/models.py`, the docstring's last two lines currently end `…(ł/ń/ś/ż land` / `after z) — the app does no locale-aware collation anywhere yet."""`. Replace those two lines with exactly two lines:

```python
        Python's default string order mis-sorts Polish diacritics (ł/ń/ś/ż land
        after z) — pass it through core.collation.polish_sort_key."""
```

(Keep the preceding `mapping), else display_name-or-username. Callers case-fold it. NOTE:` line as is.)

- [ ] **Step 2: Repair the `test_provision.py` comment, line-count neutral**

Replace

```python
    # The analytics templates render display_name|default:username and nothing
    # else, so a pupil without one shows as "sp-12-p01".
```

with

```python
    # Analytics names students by list_display_name, which falls back to the
    # display name, so a student without one would show as "sp-12-p01".
```

Leave the `pupil` variable as is (the rename is optional per spec §2.10; not doing it keeps the diff minimal).

- [ ] **Step 3: Run the §2.10 inventory (expected empty)**

Run: `uv run pytest tests/test_analytics_views.py tests/test_analytics_rollups.py tests/test_analytics_scoping.py tests/test_analytics_student_quiz.py tests/test_views_export.py tests/test_exporters.py tests/test_gradebook.py tests/test_grouping_analytics_links.py tests/test_dashboard_panels.py tests/demo/test_provision.py` (`tests/test_e2e_analytics.py` — whose locators find students by name — runs under `-m e2e` in Step 6.)
Expected: PASS. If anything fails on a rendered student name, stop and report — spec §2.10 predicts none, because `UserFactory` sets no structured names.

- [ ] **Step 4: Help text**

In `docs/help/teacher/analytics.md`, under `## Reading the grid`, change the bullet `- **Rows** are students, one per line.` to:

```markdown
- **Rows** are students, one per line, in register order: by surname, then first
  name, alphabetically. A student whose account lacks either a first name or a
  surname is placed by their display name.
```

Open `docs/help/teacher/analytics.pl.md`, find the matching „Wiersze" bullet, and replace it with:

```markdown
- **Wiersze** to uczniowie, po jednym w wierszu, w kolejności dziennika: według
  nazwiska, a potem imienia, alfabetycznie. Uczeń, któremu na koncie brakuje imienia
  lub nazwiska, jest umieszczony według nazwy wyświetlanej.
```

(If the Polish bullet's bold word differs, keep its existing bold word and replace only the sentence.)

- [ ] **Step 5: Help screenshots (manual checklist, not a pytest)**

```bash
uv run python -m pytest tests/capture_help_screenshots.py
git status --short core/static/core/img/help/
```

Keep `analytics-matrix.en.png` and `analytics-matrix.pl.png` only, then restore everything else:

```bash
git diff --name-only -- core/static/core/img/help/ | grep -v "analytics-matrix\." | xargs -r git checkout --
git clean -n -- core/static/core/img/help/   # untracked PNGs the restore above cannot see
git clean -f -- core/static/core/img/help/   # only if the dry run listed files; none are ours
git status --short core/static/core/img/help/
```

Expected: `git status` lists **no file other than those two** (and quite possibly neither — the seed's students have no structured names, spec §2.11). Never use `git stash` here: with nothing to stash, `stash push` saves nothing and the following `stash pop` would apply an unrelated older stash.

- [ ] **Step 6: Branch gate**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
uv run pytest tests/test_css_citations_are_durable.py tests/test_analytics_student_order.py
```

Then the full non-e2e suite in chunks (a single run is OOM-killed):

```bash
uv run pytest tests/test_[a-f]*.py
uv run pytest tests/test_[g-o]*.py
uv run pytest tests/test_[p-z]*.py tests/demo tests/lal_import
uv run pytest accounts courses core demo grouping institution integrations notes notifications support tags
```

Expected: each summary line reads `N passed` with no `failed`/`error`. Read the summary, not the exit code. Then `uv run pytest -m e2e tests/test_e2e_analytics.py tests/test_e2e_demo_tab.py` (the second loads the matrix as a kit teacher).

- [ ] **Step 7: Commit and open PR A**

```bash
git add accounts/models.py tests/demo/test_provision.py docs/help/teacher/analytics.md docs/help/teacher/analytics.pl.md core/static/core/img/help/analytics-matrix.en.png core/static/core/img/help/analytics-matrix.pl.png
git commit -m "docs(analytics): student order in help; repair two stale comments"
git push -u origin feat/analytics-student-order
gh pr create --base master --title "Analytics: students by surname, named First Surname" --body-file <scratchpad>/pr-a.md
```

PR body: what changed (§3), T1–T5, that T5 is a boundary test PR B deletes, the screenshot outcome (changed or byte-identical), and the Claude Code attribution line.

---

# PR B — the two pages (§4, §5, §6)

Branch: `feat/analytics-student-pages`, created in the same worktree from the tip of PR A's branch — `git switch -c feat/analytics-student-pages feat/analytics-student-order` — once PR A is pushed. After PR A merges, `git rebase origin/master` before opening PR B (Task B11 Step 4).

### Task B1: Marks read the same everywhere (§5.5)

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (`marks_filter`)
- Modify: `templates/courses/manage/_quiz_pill.html` (line 1 and the `scored` branch)
- Modify: `tests/test_quiz_scoring.py`
- Modify: `tests/test_analytics_student_quiz.py`

- [ ] **Step 1: Rewrite the filter tests (per locale)**

In `tests/test_quiz_scoring.py`, replace `test_marks_filter_trims_trailing_zeros`, `test_marks_filter_whole_tens_not_scientific` and `test_marks_filter_none_is_dash` with:

```python
@pytest.mark.parametrize(
    ("language", "value", "expected"),
    [
        ("en", "2.00", "2"),
        ("en", "1.50", "1.5"),
        ("en", "0.67", "0.67"),
        ("en", "10.00", "10"),  # regression: normalize() gives "1E+1"
        ("en", "1234.50", "1234.5"),
        ("pl", "2.00", "2"),
        ("pl", "1.50", "1,5"),
        ("pl", "0.67", "0,67"),
        ("pl", "10.00", "10"),
        ("pl", "1234.50", "1234,5"),
    ],
)
def test_marks_filter_trims_and_localises(language, value, expected):
    with translation.override(language):
        assert marks_filter(Decimal(value)) == expected


@pytest.mark.parametrize("language", ["en", "pl"])
def test_marks_filter_none_is_dash(language):
    with translation.override(language):
        assert marks_filter(None) == "—"
```

Add `from django.utils import translation` to the imports; add `import pytest` if absent.

(No grouping case — spec §2.9: `force_grouping` cannot suppress grouping, so such a test could never go red.)

- [ ] **Step 2: Write the page tests (T29 badge + pill, T30)**

First update the module docstring of `tests/test_analytics_student_quiz.py`. Its first line reads `"""The per-question drill-down page (spec §3, §5; T30, T31, T31b, T33, T35-T39, T41).`; replace that one line with:

```python
"""The per-question drill-down page. Two specs' test ids live here: T30, T31, T31b,
T33, T35-T39, T41 are the per-question drill-down spec's (2026-09-14); T18-T32 added
from Task B1 on are the analytics student pages spec's (2026-09-16). Same number, two
tests (e.g. test_t31_each_path_segment_… vs test_t31_option_table_…): -k by NAME.
```

Keep the rest of the docstring. The file grows three lines at the top; no live-code file cites its line numbers.


Append to `tests/test_analytics_student_quiz.py` (`QuestionElement` is already imported; add the `_polish` helper from Global Constraints near `_owner_view`):

```python
# --- T29 / T30 marks read the same everywhere (spec §5.5) --------------------------
def test_t29_polish_marks_use_a_decimal_comma_in_badge_and_pill(client):
    course, pupil = _owner_view(client)
    _polish(client)
    half = _empty_quiz(course, "Half")
    el = _add(half)
    sub = _submitted(pupil, half, score=Decimal("0.5"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="x", fraction=Decimal("0.5"), attempt_count=1)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))

    badge = _badge(_items(_soup(client.get(_url(course, pupil.pk, half.pk))))[0])
    assert "(0,5/1)" in badge
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    assert _breakdown_pill(breakdown, "Thirds").get_text(" ", strip=True) == (
        "wynik 0,67/1 (67%)"
    )


def test_t29_english_marks_keep_a_decimal_point(client):
    course, pupil = _owner_view(client)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    assert _breakdown_pill(breakdown, "Thirds").get_text(" ", strip=True) == (
        "scored 0.67/1 (67%)"
    )


def test_t30_polish_export_keeps_a_decimal_point(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Exported")
    _add(quiz, marking_mode=QuestionElement.MarkingMode.AUTO)
    _submitted(pupil, quiz, score=Decimal("0.5"), max_score=Decimal("1"))
    body = client.get(
        reverse("courses:manage_analytics_export", kwargs={"slug": course.slug}),
        {"shape": "quiz", "format": "csv"},
    ).content.decode("utf-8-sig")
    assert "0.5" in body
    assert "0,5" not in body
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_scoring.py tests/test_analytics_student_quiz.py -k "marks_filter or t29 or t30"`
Expected: the `pl` filter cases with a fraction FAIL (`1.5`); `test_t29_polish_marks_use_a_decimal_comma_in_badge_and_pill` FAILS (`0.5/1`, pill `wynik 0,7/1`); `test_t29_english_marks_keep_a_decimal_point` FAILS (`scored 0.7/1`); `test_t30_polish_export_keeps_a_decimal_point` PASSES (a guard — the export never used the filter). The `-k t30` filter also selects the existing `test_t30_access_matrix`, which PASSES.

- [ ] **Step 4: Localise the filter**

In `courses/templatetags/courses_extras.py`, add `from django.utils.formats import number_format` to the imports, and make the filter:

```python
@register.filter(name="marks")
def marks_filter(value):
    """Format a marks Decimal for display: at most 2dp, trailing zeros + a trailing
    separator trimmed, decimal separator localised (spec §5.5).

    NOT Decimal.normalize() -- that yields scientific notation for whole tens
    (Decimal("10.00").normalize() == Decimal("1E+1")). Grouping is left to the
    USE_THOUSAND_SEPARATOR setting: number_format's force_grouping can only ADD
    grouping, never suppress it.
    """
    if value is None:
        return "—"
    s = f"{Decimal(value).quantize(Decimal('0.01')):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return number_format(Decimal(s), decimal_pos=None)
```

- [ ] **Step 5: The pill uses the filter**

`templates/courses/manage/_quiz_pill.html` line 1 becomes `{% load i18n courses_extras %}`. In the `scored` branch change only the two filters:

```django
  <span class="pill pill--scored">{% blocktrans with s=p.score|marks m=p.max_score|marks %}scored {{ s }}/{{ m }}{% endblocktrans %} ({{ p.percent }}%)</span>
```

- [ ] **Step 6: Run to verify**

Run: `uv run pytest tests/test_quiz_scoring.py tests/test_analytics_student_quiz.py tests/test_analytics_views.py tests/test_consumption_pages.py tests/test_views_export.py`
Expected: all PASS.

- [ ] **Step 7: Falsify**

- *Mutant 1:* `return s` instead of `number_format(...)` → pl filter cases and T29 Polish badge red. Revert.
- *Mutant 2:* restore `|floatformat` in the pill → T29 red on `0,7`/`0.7`. Revert.
- *Mutant 3:* restore `{% load i18n %}` alone in `_quiz_pill.html` → `TemplateSyntaxError` on both pages. Revert.
- *Mutant 4:* replace the blocktrans with `{{ p.score|marks }}/{{ p.max_score|marks }}` → T29 red on the missing „wynik"/"scored" word. Revert.
- *Mutant 5:* in `courses/gradebook.py`/`courses/exporters.py`, format the quiz cell with `marks_filter` → T30 red. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/manage/_quiz_pill.html tests/test_quiz_scoring.py tests/test_analytics_student_quiz.py
git commit -m "feat(analytics): marks use the locale's decimal separator, pill included"
```

### Task B2: The breakdown builder owns the Results prune (§4.1)

**Files:**
- Modify: `courses/rollups.py` (`build_student_breakdown`; new `_keep_quizzes` right after it)
- Create: `tests/test_analytics_student_page.py`

**Interfaces:**
- Produces: `build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress") -> {"student", "tree"}`; every unit dict gains `"additional": bool`.

- [ ] **Step 1: Write the failing builder tests (T10, T15, and the stamp)**

Create `tests/test_analytics_student_page.py`:

```python
"""The student results page (spec §4; T6-T13, T15, T16, T28b)."""

from decimal import Decimal

import pytest

from courses.models import QuizSubmission
from courses.rollups import build_student_breakdown
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _node(course, parent, kind, title, **kw):
    unit_type = kw.pop("unit_type", None)
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title, **kw
    )


def _titles(tree):
    out = []

    def walk(nodes):
        for d in nodes:
            out.append(d["node"].title)
            walk(d["children"])

    walk(tree)
    return out


def _find(tree, title):
    for d in tree:
        if d["node"].title == title:
            return d
        hit = _find(d["children"], title)
        if hit is not None:
            return hit
    return None


def test_t10_results_keeps_a_deep_quiz_with_every_ancestor():
    course = CourseFactory()
    part = _node(course, None, "part", "Part")
    chapter = _node(course, part, "chapter", "Chapter")
    section = _node(course, chapter, "section", "Section")
    quiz = _node(course, section, "unit", "Deep quiz", unit_type="quiz")
    _node(course, section, "unit", "Side lesson", unit_type="lesson", obligatory=True)
    student = UserFactory()
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )

    tree = build_student_breakdown(course, student, drafts="keep", mode="results")[
        "tree"
    ]
    assert _titles(tree) == ["Part", "Chapter", "Section", "Deep quiz"]
    assert _find(tree, "Deep quiz")["pill"]["kind"] in {"submitted", "scored"}


def test_t15_default_mode_is_progress_and_keeps_lessons():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Lesson", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _titles(tree) == ["Chapter", "Lesson", "Quiz"]


def test_units_are_stamped_additional_as_a_boolean():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Required", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Extra", unit_type="lesson", obligatory=False)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _find(tree, "Required")["additional"] is False
    assert _find(tree, "Extra")["additional"] is True
    assert _find(tree, "Quiz")["additional"] is False  # never the raw "quiz" marker
```

- [ ] **Step 2: Run to verify**

Run: `uv run pytest tests/test_analytics_student_page.py`
Expected: T10 FAILS (`TypeError: unexpected keyword argument 'mode'`); T15 PASSES (guard of today's default); the stamp test FAILS (`KeyError: 'additional'`).

- [ ] **Step 3: Implement**

In `courses/rollups.py`, replace `build_student_breakdown` with:

```python
def build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress"):
    """Compose build_outline + build_course_results into one teacher-facing tree
    (spec §3). NOT pure — calls two query-backed builders. Quiz units gain `pill`;
    every unit gains `additional` (a BOOLEAN from unit_marker, so no template can
    render the raw "quiz" marker as a chip).

    Forwards drafts/with_data into BOTH internal calls: build_outline defaults to
    "hide", so leaving it unthreaded would drop draft units from the tree while
    pill_by_unit (from build_course_results) still carries their results.

    mode="results" returns the tree already pruned to quizzes (analytics student
    pages spec §4.1). The default keeps every existing caller's tree unchanged.
    """
    tree = build_outline(course, student, drafts=drafts, with_data=with_data)
    results = build_course_results(course, student, drafts=drafts, with_data=with_data)
    pill_by_unit = {r["unit"].pk: _quiz_pill(r) for r in results["rows"]}

    def attach(nodes):
        for d in nodes:
            node = d["node"]
            if d["is_unit"]:
                if node.unit_type == ContentNode.UnitType.QUIZ:
                    d["pill"] = pill_by_unit.get(node.pk)
                d["additional"] = unit_marker(node) == MARKER_ADDITIONAL
            attach(d["children"])

    attach(tree)
    if mode == "results":
        tree = _keep_quizzes(tree)
    return {"student": student, "tree": tree}


def _keep_quizzes(nodes):
    """The Results view's prune (spec §4.1): a unit stays iff is_quiz_unit — ONE
    predicate, so a unit with no unit_type is dropped, never kept by a "not a
    lesson" reading — and a container stays iff a descendant stayed. Runs after
    attach, on a tree build_outline just built, so rewriting `children` in place
    is safe."""
    kept = []
    for d in nodes:
        if d["is_unit"]:
            if is_quiz_unit(d["node"]):
                kept.append(d)
            continue
        d["children"] = _keep_quizzes(d["children"])
        if d["children"]:
            kept.append(d)
    return kept
```

(`unit_marker`, `MARKER_ADDITIONAL` and `is_quiz_unit` are defined earlier in the same module.)

- [ ] **Step 4: Run to verify**

Run: `uv run pytest tests/test_analytics_student_page.py tests/test_analytics_rollups.py tests/test_publish_analytics.py`
Expected: all PASS.

- [ ] **Step 5: Falsify**

- *Mutant 1 (T10, replaces the spec's inapplicable mutant):* in `_keep_quizzes`, replace the container branch with `if any(c["is_unit"] and is_quiz_unit(c["node"]) for c in d["children"]): kept.append(d)` (no recursion) → T10 red (`Part`/`Chapter` dropped). Revert.
- *Mutant 2 (T15):* default `mode="results"` → T15 red **and** `tests/test_analytics_rollups.py::test_build_student_breakdown…` red on `by_unit[les.pk]` (KeyError). Revert.
- *Mutant 3:* `d["additional"] = unit_marker(node)` → the stamp test red (`"quiz"`/`""` is not `False`). Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_analytics_student_page.py
git commit -m "feat(analytics): the student breakdown prunes to quizzes in Results mode"
```

### Task B3: The page follows the mode, has one name and a view switch (§4.1, §4.3)

**Files:**
- Modify: `courses/views_analytics.py` (`analytics_student`)
- Modify: `templates/courses/manage/analytics_student.html`
- Modify: `templates/courses/manage/_breakdown_node.html` (the chapter `rollup` line)
- Modify: `templates/courses/manage/analytics_student_quiz.html` (back link word only)
- Modify: `tests/test_analytics_student_page.py`, `tests/test_analytics_student_order.py` (delete T5)
- Modify: `locale/*`

**Interfaces:**
- Consumes: `build_student_breakdown(..., mode=)` (B2).
- Produces: context keys `mode`, `other_view_url` on `analytics_student`.

- [ ] **Step 1: Write the failing page tests (T6–T9, T11, T16, T28b)**

Append to `tests/test_analytics_student_page.py`. Add to its import block (isort order) `from bs4 import BeautifulSoup`, `from django.urls import reverse`, `from courses.views_analytics import _expand_qs`, `from tests.factories import EnrollmentFactory`, `from tests.factories import UnitProgressFactory`, `from tests.factories import make_login` — B2 left them out so its commit passes F401 — and add the `_polish` helper from Global Constraints:

```python
def _page_fixture(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    mixed = _node(course, None, "chapter", "Mixed chapter")
    lesson = _node(
        course, mixed, "unit", r"Required lesson \(x\)", unit_type="lesson",
        obligatory=True,
    )
    _node(course, mixed, "unit", "Extra lesson", unit_type="lesson", obligatory=False)
    quiz = _node(course, mixed, "unit", "Chapter quiz", unit_type="quiz")
    _node(course, mixed, "unit", "Unstarted quiz", unit_type="quiz")
    _node(course, mixed, "unit", "Typeless unit", unit_type=None)
    lonely = _node(course, None, "chapter", "Lessons-only chapter")
    _node(course, lonely, "unit", "Lonely lesson", unit_type="lesson", obligatory=True)
    # display_name equal to "First Last", so list_display_name adds no parenthetical
    student = UserFactory(first_name="Anna", last_name="Nowak", display_name="Anna Nowak")
    EnrollmentFactory(student=student, course=course)
    UnitProgressFactory(student=student, unit=lesson, completed=True)
    QuizSubmission.objects.create(
        student=student, unit=quiz, status="submitted",
        score=Decimal("1"), max_score=Decimal("1"),
    )
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    return course, student, mixed, path


def _get(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    return resp, BeautifulSoup(resp.content.decode(), "html.parser")


def _unit_titles(soup):
    return [s.get_text(" ", strip=True) for s in soup.select(".breakdown-unit__title")]


def _head(soup, title):
    for head in soup.select(".breakdown-node__head"):
        if head.select_one(".breakdown-node__title").get_text(strip=True) == title:
            return head
    return None


def test_t6_results_mode_shows_quizzes_only(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    assert _unit_titles(soup) == ["Chapter quiz", "Unstarted quiz"]
    assert _head(soup, "Lessons-only chapter") is None
    unstarted = soup.select(".breakdown-unit")[1]
    assert unstarted.select_one(".pill.pill--none") is not None


def test_t7_results_mode_hides_the_chapter_chip_progress_shows_it(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, results = _get(client, f"{path}?mode=results")
    _resp, progress = _get(client, f"{path}?mode=progress")
    assert _head(results, "Mixed chapter").select_one(".rollup") is None
    assert _head(progress, "Mixed chapter").select_one(".rollup") is not None


def test_t8_progress_mode_keeps_lessons_and_chips(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=progress")
    titles = _unit_titles(soup)
    assert "Extra lesson" in titles and "Lonely lesson" in titles
    assert _head(soup, "Lessons-only chapter").select_one(".rollup") is not None


@pytest.mark.parametrize("query", ["", "?mode=nonsense"])
def test_t9_missing_or_unknown_mode_renders_progress(client, query):
    _course, _student, _mixed, path = _page_fixture(client)
    resp, soup = _get(client, f"{path}{query}")
    assert resp.context["mode"] == "progress"
    assert "Lonely lesson" in _unit_titles(soup)


def test_t11_switch_links_the_other_mode_and_keeps_every_param(client):
    course, student, mixed, path = _page_fixture(client)
    query = f"?scope=all&mode=results&expand={mixed.pk}&student={student.pk}&values=raw"
    _resp, soup = _get(client, f"{path}{query}")
    switch = soup.select_one(".breakdown__view")
    current = switch.select_one('a[aria-current="page"]')
    assert current.get_text(strip=True) == "Results"
    others = [a for a in switch.select("a") if a is not current]
    assert [a.get_text(strip=True) for a in others] == ["Progress"]
    expected = _expand_qs("all", "progress", [mixed.pk], [student.pk], "raw")
    assert others[0]["href"] == f"{path}?{expected}"


def test_t16_has_math_is_computed_from_the_pruned_tree(client):
    _course, _student, _mixed, path = _page_fixture(client)
    results, _soup = _get(client, f"{path}?mode=results")
    progress, _soup = _get(client, f"{path}?mode=progress")
    assert results.context["has_math"] is False  # the maths title is a lesson's
    assert progress.context["has_math"] is True


def test_t28b_one_page_name_in_both_modes(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _polish(client)
    for mode, word in (("results", "Wyniki"), ("progress", "Postęp")):
        _resp, soup = _get(client, f"{path}?mode={mode}")
        assert soup.select_one("h1").get_text(" ", strip=True) == "Wyniki ucznia — Anna Nowak"
        assert soup.select_one("title").get_text(strip=True).startswith("Wyniki ucznia ·")
        current = soup.select_one('.breakdown__view a[aria-current="page"]')
        assert current.get_text(strip=True) == word
```

And in `tests/test_analytics_student_quiz.py` append:

```python
def test_t28b_per_question_back_link_names_the_student_results_page(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Back word")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    back = soup.select_one("section.answers .manage__head a")
    assert back.get_text(" ", strip=True) == "← Wyniki ucznia"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py -k "t6 or t7 or t8 or t9 or t11 or t16 or t28b"`
Expected: T6, T7, T9 (`KeyError: 'mode'`), T11, T16, both T28b FAIL; T8 PASS.

- [ ] **Step 3: The view**

In `courses/views_analytics.py`, replace the body of `analytics_student` from `with_data = _with_data_for(course)` to the end with:

```python
    # Parsed BEFORE the builder: the mode decides the tree (spec §4.1).
    scope, mode, expand_pks, subset_pks, values = _drill_params(request)
    with_data = _with_data_for(course)
    breakdown = build_student_breakdown(
        course, student, drafts="keep-with-data", with_data=with_data, mode=mode
    )
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    student_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
    other_mode = "progress" if mode == "results" else "results"
    other_qs = _expand_qs(scope, other_mode, expand_pks, subset_pks, values)
    # build_student_breakdown returns a DICT WRAPPER, {"student": …, "tree": …};
    # passing `breakdown` itself would iterate the dict's keys and raise
    # TypeError -- a 500 on this page. The tree is already pruned for the mode,
    # so KaTeX loads only for titles the page renders.
    has_math = tree_titles_have_math(breakdown["tree"])
    return render(
        request,
        "courses/manage/analytics_student.html",
        {
            "course": course,
            "student": student,
            "breakdown": breakdown,
            "mode": mode,
            "other_view_url": f"{student_path}?{other_qs}",
            "back_url": f"{matrix_path}?{back_qs}",
            "drill_qs": back_qs,
            "has_math": has_math,
        },
    )
```

- [ ] **Step 4: The student page template**

Replace `templates/courses/manage/analytics_student.html` with:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Student results" %} · {{ course.title }} · libli{% endblock %}
{% block extra_css %}{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
{% block content %}
<section class="manage breakdown">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Student results" %} — {{ student.list_display_name }}</h1>
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% trans "Analytics" %}</a>
  </header>
  {% comment %}The view switch sits BELOW .manage__head, never inside it: the header's
  wrap behaviour is shared by fifteen templates (spec §5.3).{% endcomment %}
  <p class="breakdown__view">
    <span class="analytics__toggle" role="group" aria-label="{% trans 'Metric' %}">
      {% if mode == "results" %}
        <a class="btn btn--small" href="{{ other_view_url }}">{% trans "Progress" %}</a>
        <a class="btn btn--small is-active" aria-current="page" href="?{{ drill_qs }}">{% trans "Results" %}</a>
      {% else %}
        <a class="btn btn--small is-active" aria-current="page" href="?{{ drill_qs }}">{% trans "Progress" %}</a>
        <a class="btn btn--small" href="{{ other_view_url }}">{% trans "Results" %}</a>
      {% endif %}
    </span>
  </p>
  <ul class="breakdown__tree">
    {% for item in breakdown.tree %}
      {% include "courses/manage/_breakdown_node.html" with item=item course=course %}
    {% endfor %}
  </ul>
</section>
{% endblock %}
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

The order is always Progress, Results — the same as the matrix's own toggle.

Add to `core/static/core/css/app.css`, directly after the `.breakdown__tree,.breakdown-node ul{…}` rule:

```css
.breakdown__view{margin:0 0 var(--space-3)}
```

- [ ] **Step 5: The chapter chip follows the mode (D7)**

In `templates/courses/manage/_breakdown_node.html`, the rollup line becomes:

```django
      {% if item.required_total and mode != "results" %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
```

- [ ] **Step 6: The per-question back link**

In `templates/courses/manage/analytics_student_quiz.html`, the back link becomes `← {% trans "Student results" %}`.

- [ ] **Step 7: Delete T5**

Delete `test_t5_drill_down_headings_keep_the_display_name_until_pr_b` from `tests/test_analytics_student_order.py` (and the imports only it used — `QuizSubmission`, `Decimal`; `ruff check` flags any left behind), and change the module docstring's `(spec §3; T1-T5).` to `(spec §3; T1-T4).` on the same line. Its successors are T28b (here) and T28 (Task B8).

- [ ] **Step 8: Catalogs**

Run the Catalog procedure. New: `Student results` → `Wyniki ucznia`. Expected side effect: `Breakdown` becomes an obsolete `#~` block in both catalogs — that is intended (spec §6). No other new msgid.

- [ ] **Step 9: Run to verify**

Run: `uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_analytics_views.py tests/test_title_math_markers.py tests/test_title_math_assets.py tests/test_analytics_student_order.py`
Expected: all PASS.

- [ ] **Step 10: Falsify**

- *Mutant 1 (T6):* drop `mode=mode` from the builder call → T6 red. Revert.
- *Mutant 2 (T7):* remove `and mode != "results"` → T7 red. Revert.
- *Mutant 3 (T8):* in `build_student_breakdown`, prune unconditionally (`tree = _keep_quizzes(tree)`) → T8 red. Revert.
- *Mutant 4 (T9):* in `_drill_params`, `mode = "progress" if request.GET.get("mode") == "progress" else "results"` → T9 red on both cases. Revert.
- *Mutant 5 (T11):* pass `[]` instead of `subset_pks` to `other_qs` → T11 red. Revert.
- *Mutant 6 (T16):* have the view scan an unpruned tree — `has_math = tree_titles_have_math(build_student_breakdown(course, student, drafts="keep-with-data", with_data=with_data)["tree"])` → T16 red. Revert.
- *Mutant 7 (T28b):* put `{% if mode == "results" %}{% trans "Results" %}{% else %}{% trans "Progress" %}{% endif %}` in the `h1` instead of `Student results` → T28b red. Revert.
- *Mutant 8 (T28b):* restore `{% trans "Breakdown" %}` in `head_title` → red on the title assertion. Revert.

- [ ] **Step 11: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/analytics_student.html templates/courses/manage/_breakdown_node.html templates/courses/manage/analytics_student_quiz.html core/static/core/css/app.css tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_analytics_student_order.py locale/
git commit -m "feat(analytics): the student results page follows the matrix view"
```

### Task B4: What each row shows (§4.2)

**Files:**
- Modify: `templates/courses/manage/_breakdown_node.html` (line 1; lesson branch)
- Modify: `core/static/core/css/app.css` (`.badge--done`; the breakdown block)
- Modify: `tests/test_analytics_student_page.py`
- Create: `tests/test_e2e_analytics_student_pages.py`
- Modify: `locale/*`

- [ ] **Step 1: Write the failing view tests (T12, T13)**

Append to `tests/test_analytics_student_page.py` (add `from courses import rollups`):

```python
def _row(soup, title):
    for row in soup.select(".breakdown-unit"):
        if row.select_one(".breakdown-unit__title").get_text(" ", strip=True) == title:
            return row
    raise AssertionError(f"no row titled {title!r}")


def test_t12_additional_tag_sits_between_title_and_marker(client, monkeypatch):
    monkeypatch.setitem(
        rollups.UNIT_MARKER_LABELS, rollups.MARKER_ADDITIONAL, "SENTINEL-ADDITIONAL"
    )
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, path)
    extra = _row(soup, "Extra lesson")
    classes = [" ".join(child.get("class", [])) for child in extra.find_all(recursive=False)]
    assert classes == [
        "breakdown-unit__title",
        "badge breakdown-unit__tag",
        "badge badge--todo",
    ]
    assert extra.select_one(".breakdown-unit__tag").get_text(strip=True) == (
        "SENTINEL-ADDITIONAL"
    )
    assert _row(soup, "Lonely lesson").select_one(".breakdown-unit__tag") is None
    quiz = _row(soup, "Chapter quiz")
    assert quiz.select_one(".breakdown-unit__tag") is None
    assert quiz.select_one(".unit-kind-chip") is None


def test_t13_quiz_rows_carry_a_pill_lesson_rows_a_marker(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, path)
    quiz = _row(soup, "Chapter quiz")
    assert quiz.select_one(".pill") is not None
    assert quiz.select_one(".badge--done, .badge--todo") is None
    done = _row(soup, r"Required lesson \(x\)")
    assert done.select_one(".pill") is None
    assert done.select_one(".badge--done")["aria-label"] == "Completed"
    todo = _row(soup, "Lonely lesson")
    assert todo.select_one(".badge--done") is None
    assert todo.select_one(".badge--todo")["aria-label"] == "Not completed"
```

(`r"Required lesson \(x\)"` is the raw title text: KaTeX is client-side, so the served HTML still carries the delimiters.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_page.py -k "t12 or t13"`
Expected: both FAIL (no tag, no `.badge--todo`).

- [ ] **Step 3: The lesson branch**

`templates/courses/manage/_breakdown_node.html` line 1 becomes `{% load i18n courses_extras %}`. The lesson branch's `<div class="breakdown-unit">…</div>` becomes:

```django
      <div class="breakdown-unit">
        <span class="breakdown-unit__title{% if item.completed %} is-done{% endif %}" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
        {% if item.additional %}<span class="badge breakdown-unit__tag">{% marker_label "additional" %}</span>{% endif %}
        {% if item.completed %}<span class="badge badge--done" aria-label="{% trans 'Completed' %}">✓</span>{% else %}<span class="badge badge--todo" aria-label="{% trans 'Not completed' %}">○</span>{% endif %}
      </div>
```

`"additional"` is `rollups.MARKER_ADDITIONAL`'s value; the word still comes from `UNIT_MARKER_LABELS` through `marker_label`. Never `{% trans "Additional" %}` (spec §4.1).

- [ ] **Step 4: The CSS (app.css only)**

Replace

```css
.badge--done { margin-left: auto; background: var(--success-subtle); color: var(--success);
  border-color: color-mix(in srgb, var(--success) 45%, var(--border-default)); }
```

with

```css
/* Alignment ONLY is shared: .badge--done also carries the green fill, which must
   never reach "not completed". courses.css's `.unit-tree__check` resets the margin. */
.badge--done, .badge--todo { margin-left: auto; }
.badge--done { background: var(--success-subtle); color: var(--success);
  border-color: color-mix(in srgb, var(--success) 45%, var(--border-default)); }
.badge--todo { background: transparent; color: var(--text-secondary); }
```

In the breakdown block, replace

```css
.breakdown-unit__title.is-done{color:var(--text-secondary)}
.breakdown-unit__review{font-size:.8rem}
.breakdown-unit__link{color:inherit;text-decoration:none}
.breakdown-unit__link:hover,.breakdown-unit__link:focus-visible{text-decoration:underline}
```

with

```css
/* No colour on .is-done: a finished lesson must not look dimmer than an unfinished
   one. The class stays in the markup as the row's completion record. */
.breakdown-unit__review{font-size:.8rem}
/* The one clickable thing on the page reads as a link without hovering. */
.breakdown-unit__link{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.breakdown-unit__link:hover,.breakdown-unit__link:focus-visible{text-decoration-thickness:2px}
/* Scoped: .pill is global and also sits in the per-question .answers__status strip. */
.breakdown-unit .pill{margin-left:auto}
```

- [ ] **Step 5: Catalogs**

Catalog procedure. New: `Not completed` → `Nieukończone`.

- [ ] **Step 6: Run to verify**

Run: `uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_title_math_markers.py tests/test_title_math_css.py tests/test_border_contrast_css.py tests/test_css_citations_are_durable.py tests/test_css_comments_are_terminated_once.py`
Expected: all PASS.

- [ ] **Step 7: Falsify T12/T13**

- *Mutant 1:* `{% if item.is_unit %}` instead of `{% if item.additional %}` → T12 red on „Lonely lesson". Revert.
- *Mutant 2 (the raw marker, unguarded):* in the builder `d["additional"] = unit_marker(node)`; in the template use `<span class="badge breakdown-unit__tag">{% marker_label item.additional %}</span>` under `{% if item.additional %}`, and add that same line after the quiz branch's title span → T12 red (the quiz row gains a „Quiz" tag). Revert all three edits.
- *Mutant 3:* move the tag after the marker → T12 red on the class order. Revert.
- *Mutant 4:* replace `{% marker_label "additional" %}` with `{% trans "Additional" %}` → T12 red (renders "Additional", not the sentinel). Revert.
- *Mutant 5:* render the completion marker outside `{% if item.node.unit_type == "quiz" %}` so quiz rows get one too → T13 red. Revert.

- [ ] **Step 8: Write the e2e A/B tests (T14, T33 breakdown cases, T33c)**

Create `tests/test_e2e_analytics_student_pages.py`:

```python
"""Computed-style checks for the analytics student pages (spec §7.4: T14, T33,
T33b, T33c). Every layout rule is an A/B: the shipped state is measured, then the
rule's own declaration is neutralised in place and the measurement must change.

Marked e2e (excluded from the default run; use -m e2e)."""

import os
from decimal import Decimal

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state()


def _neutralise(page, css):
    page.add_style_tag(content=css)


def _box(locator):
    return locator.evaluate(
        """el => {
             const r = el.getBoundingClientRect();
             return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width};
           }"""
    )


def _style(locator, prop):
    return locator.evaluate("(el, p) => getComputedStyle(el)[p]", prop)


def _seed_breakdown(client, username):
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter"
    )

    def unit(title, unit_type, **kw):
        return ContentNodeFactory(
            course=course, kind="unit", unit_type=unit_type, parent=ch, title=title, **kw
        )

    done = unit("Done lesson", "lesson", obligatory=True)
    unit("Extra lesson", "lesson", obligatory=False)
    scored = unit("Scored quiz", "quiz")
    awaiting = unit("Awaiting quiz", "quiz")
    Element.objects.create(
        unit=scored,
        content_object=ShortTextQuestionElement.objects.create(
            stem="<p>Q</p>", accepted="a", max_marks=Decimal("1")
        ),
    )
    Element.objects.create(
        unit=awaiting,
        content_object=ExtendedResponseQuestionElement.objects.create(
            stem="<p>E</p>",
            required_keywords="",
            forbidden_keywords="",
            marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("1"),
        ),
    )
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    UnitProgressFactory(student=student, unit=done, completed=True)
    QuizSubmission.objects.create(
        student=student, unit=scored, status="submitted",
        score=Decimal("1"), max_score=Decimal("1"),
    )
    QuizSubmission.objects.create(
        student=student, unit=awaiting, status="submitted",
        score=Decimal("0"), max_score=Decimal("0"),
    )
    return course, student, awaiting


def _open_breakdown(page, live_server, client, username):
    course, student, awaiting = _seed_breakdown(client, username)
    _login(page, live_server, username)
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".breakdown-unit")
    return course, student, awaiting


def _row(page, title):
    return page.locator(".breakdown-unit").filter(
        has=page.locator(".breakdown-unit__title", has_text=title)
    )


def test_t14_quiz_title_link_is_underlined_without_hover(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_link")
    link = _row(page, "Scored quiz").locator("a.breakdown-unit__link")
    assert "underline" in _style(link, "textDecorationLine")
    accent = page.evaluate(
        """() => { const p = document.createElement('span');
                   p.style.color = 'var(--accent)'; document.body.appendChild(p);
                   const c = getComputedStyle(p).color; p.remove(); return c; }"""
    )
    assert _style(link, "color") == accent
    _neutralise(page, ".breakdown-unit__link{text-decoration:none;color:inherit}")
    assert "underline" not in _style(link, "textDecorationLine")


def test_t33_breakdown_right_column(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_column")
    scored = _row(page, "Scored quiz")
    pill = scored.locator(".pill")
    assert abs(_box(scored)["r"] - _box(pill)["r"]) <= 1

    awaiting = _row(page, "Awaiting quiz")
    a_pill, review = awaiting.locator(".pill"), awaiting.locator(".breakdown-unit__review")
    assert _box(a_pill)["r"] < _box(review)["l"]  # pill, then link
    assert _box(review)["l"] - _box(a_pill)["r"] < 24  # travelling together
    assert abs(_box(awaiting)["r"] - _box(review)["r"]) <= 1

    extra = _row(page, "Extra lesson")
    title, tag = extra.locator(".breakdown-unit__title"), extra.locator(".breakdown-unit__tag")
    todo = extra.locator(".badge--todo")
    assert _box(title)["r"] <= _box(tag)["l"] < _box(todo)["l"]
    assert _box(tag)["l"] - _box(title)["r"] < 24  # the tag follows the title
    assert abs(_box(extra)["r"] - _box(todo)["r"]) <= 1

    _neutralise(page, ".breakdown-unit .pill,.badge--todo{margin-left:0}")
    assert _box(scored)["r"] - _box(pill)["r"] > 50
    assert _box(extra)["r"] - _box(todo)["r"] > 50


def test_t33_breakdown_lesson_titles_share_one_colour(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_colour")
    done = _row(page, "Done lesson").locator(".breakdown-unit__title")
    extra = _row(page, "Extra lesson").locator(".breakdown-unit__title")
    assert "is-done" in (done.get_attribute("class") or "")
    assert _style(done, "color") == _style(extra, "color")
    _neutralise(page, ".breakdown-unit__title.is-done{color:var(--text-secondary)}")
    assert _style(done, "color") != _style(extra, "color")


def test_t33_per_question_header_pill_is_not_pushed(page, live_server, client):
    course, student, awaiting = _open_breakdown(page, live_server, client, "e2e_sp_hdr")
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": awaiting.pk},
    )
    page.goto(f"{live_server.url}{path}")
    status = page.locator(".answers__status")
    pill, review = status.locator(".pill"), status.locator(".answers__review")
    assert abs(_box(pill)["l"] - _box(status)["l"]) <= 1
    assert _box(review)["l"] - _box(pill)["r"] < 24


def test_t33c_todo_marker_is_not_painted_as_done(page, live_server, client):
    _open_breakdown(page, live_server, client, "e2e_sp_todo")
    done = _row(page, "Done lesson").locator(".badge--done")
    todo = _row(page, "Extra lesson").locator(".badge--todo")
    assert _style(todo, "backgroundColor") != _style(done, "backgroundColor")
    assert _style(todo, "borderTopColor") != _style(done, "borderTopColor")
```

- [ ] **Step 9: Run the e2e tests**

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py`
Expected: all PASS. If a geometry tolerance fails, print the boxes and fix the fixture or tolerance — never widen a tolerance past what separates the A and B legs.

- [ ] **Step 10: Falsify the CSS**

- *Mutant 1:* restore `.breakdown-unit__link{color:inherit;text-decoration:none}` → T14 red. Revert.
- *Mutant 2:* change the scoped rule to a bare `.pill{margin-left:auto}` → `test_t33_per_question_header_pill_is_not_pushed` red. Revert.
- *Mutant 3:* delete `.breakdown-unit .pill{margin-left:auto}` → `test_t33_breakdown_right_column` red. Revert.
- *Mutant 4:* restore `.breakdown-unit__title.is-done{color:var(--text-secondary)}` → the colour test red. Revert.
- *Mutant 5:* join `.badge--todo` to `.badge--done`'s fill rule (`.badge--done, .badge--todo { background: var(--success-subtle); … }`) and delete `.badge--todo`'s own rule → T33c red. Revert.

- [ ] **Step 11: Commit**

```bash
git add templates/courses/manage/_breakdown_node.html core/static/core/css/app.css tests/test_analytics_student_page.py tests/test_e2e_analytics_student_pages.py locale/
git commit -m "feat(analytics): breakdown rows — visible links, completion markers, optional tag"
```

### Task B5: The answer builder lists every option (§5.1, builder half)

**Files:**
- Modify: `courses/answer_summary.py` (`OPTIONS`, `Option`, `Part`, `_choice`, `summarise`)
- Modify: `tests/answer_summary_fixtures.py` (`summarise_stored`)
- Modify: `courses/views_analytics.py` (`_quiz_answer_rows`, the `summarise` call)
- Modify: `tests/test_answer_summary.py` (five `_choice` tests replaced)
- Modify: `tests/test_analytics_student_quiz.py` (T19)

**Interfaces:**
- Produces: `answer_summary.OPTIONS = "options"`; `Option(text: str, picked: bool, correct: bool | None, mark: str | None)`; `Part.options: tuple[Option, ...] | None = None`, `Part.options_auto: bool | None = None`, `Part.options_empty_key: bool = False`; `summarise(question, response, mark_result, *, option_marks=_MISSING)`.

- [ ] **Step 1: The shared fixture moves first**

Replace `summarise_stored` in `tests/answer_summary_fixtures.py` with:

```python
def summarise_stored(question, stored, *, unanswered=False):
    """summarise() fed exactly as views._results_row + _quiz_answer_rows feed it:
    for a choice question that includes the choice_marks dict the view computes
    (spec §5.1). Every question type's builder tests go through here."""
    from courses.answer_summary import summarise

    response = None if unanswered else SimpleNamespace(latest_answer=stored)
    if question.marking_mode != AUTO:
        mark_result = None
    elif response is None or stored is None:
        mark_result = question.mark(question.build_answer(QueryDict()))
    else:
        mark_result = question.mark(answer_from_json(question, stored))
    if not isinstance(question, ChoiceQuestionElement):
        return summarise(question, response, mark_result)
    marks = None
    if mark_result is not None:
        picked = (
            selected_ids(answer_from_json(question, stored))
            if response is not None and stored is not None
            else set()
        )
        marks = question.choice_marks(
            list(question.choices.all()), picked, mark_result, "quiz", True
        )
    return summarise(question, response, mark_result, option_marks=marks or {})
```

Add `from courses.quiz import selected_ids` to the module imports (after `answer_from_json`).

- [ ] **Step 2: Replace the five `_choice` tests (T17, T17b, T17c, T18 builder, T32 builder)**

In `tests/test_answer_summary.py`, replace everything from `# --- choice ---` up to (not including) `# --- shorttext / shortnumeric ---` with:

```python
# --- choice (spec §5.1: T17, T17b, T17c, T18, T32) ---------------------------------
def _options(parts):
    assert len(parts) == 1 and parts[0].kind == answer_summary.OPTIONS
    return [(o.text, o.picked, o.correct, o.mark) for o in parts[0].options]


def test_t17_choice_picked_correct_and_wrong_and_missed():
    q = build_all_types()["choice"]
    assert _options(summarise_stored(q, _pks(q, "2", "3"))) == [
        ("2", True, True, "correct"),
        ("3", True, True, "correct"),
        ("4", False, False, None),
    ]
    parts = summarise_stored(q, _pks(q, "2", "4"))
    assert _options(parts) == [
        ("2", True, True, "correct"),
        ("3", False, True, "missed"),
        ("4", True, False, "wrong"),
    ]
    assert parts[0].options_auto is True
    assert parts[0].options_empty_key is False
    assert parts[0].mark is None  # no part-level glyph for a choice question


def test_t17_choice_not_answered_with_no_response_row():
    q = build_all_types()["choice"]
    assert _options(summarise_stored(q, None, unanswered=True)) == [
        ("2", False, True, "missed"),
        ("3", False, True, "missed"),
        ("4", False, False, None),
    ]


def test_t17_choice_single_select_renders_the_same_shape():
    q = build_all_types()["choice"]
    q.multiple = False
    q.save()
    assert _options(summarise_stored(q, _pks(q, "4"))) == [
        ("2", False, True, "missed"),
        ("3", False, True, "missed"),
        ("4", True, False, "wrong"),
    ]


def test_t17b_each_deleted_pick_is_its_own_row_last_and_unmarked():
    q = build_all_types()["choice"]
    gone = list(Choice.objects.filter(question=q, text__in=["3", "4"]))
    stored = sorted([*_pks(q, "2"), *(c.pk for c in gone)])
    for choice in gone:
        choice.delete()
    assert _options(summarise_stored(q, stored)) == [
        ("2", True, True, "correct"),
        ("(removed option)", True, None, None),
        ("(removed option)", True, None, None),
    ]


def test_t17c_summarise_demands_option_marks_for_a_choice_question():
    q = build_all_types(mode=REVIEW)["choice"]
    with pytest.raises(TypeError):
        answer_summary.summarise(q, None, None)
    parts = answer_summary.summarise(q, None, None, option_marks={})
    assert parts[0].kind == answer_summary.OPTIONS


def test_t18_non_auto_choice_has_no_key_and_no_verdicts():
    q = build_all_types(mode=REVIEW)["choice"]
    parts = summarise_stored(q, _pks(q, "4"))
    assert _options(parts) == [
        ("2", False, None, None),
        ("3", False, None, None),
        ("4", True, None, None),
    ]
    assert parts[0].options_auto is False
    assert parts[0].options_empty_key is False


def test_t32_auto_choice_with_an_empty_key_marks_every_pick_wrong():
    q = build_all_types()["choice"]
    Choice.objects.filter(question=q).update(is_correct=False)
    parts = summarise_stored(q, _pks(q, "4"))
    assert _options(parts) == [
        ("2", False, False, None),
        ("3", False, False, None),
        ("4", True, False, "wrong"),
    ]
    assert parts[0].options_empty_key is True
```

Successor map (none deleted without one): `test_choice_correct_wrong_unanswered` → `test_t17_choice_picked_correct_and_wrong_and_missed` + `test_t17_choice_not_answered_with_no_response_row`; `test_choice_single_select` → `test_t17_choice_single_select_renders_the_same_shape`; `test_choice_review_mode_has_no_expected_or_ok` → `test_t18_…`; `test_choice_removed_option_appended_after_live_texts` → `test_t17b_…`; `test_choice_with_no_correct_option_expects_none_label` → `test_t32_…`.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_answer_summary.py`
Expected: every choice test that goes through `summarise_stored` FAILS (`summarise() got an unexpected keyword argument 'option_marks'`); `test_t17c_…` FAILS with `Failed: DID NOT RAISE <class 'TypeError'>` (its first call omits the argument, and today's `_choice` returns normally); `test_t19b_…` is written in Step 7; the other nine types' tests PASS.

- [ ] **Step 4: Implement the builder**

In `courses/answer_summary.py`:

After `KEYWORD = "keyword"` add `OPTIONS = "options"`.

Before `@dataclass(frozen=True) class Part`, add:

```python
@dataclass(frozen=True)
class Option:
    """One choice option as the teacher sees it (spec §5.1)."""

    text: str
    picked: bool
    correct: bool | None  # None when the question is not auto-marked
    mark: str | None  # "correct" | "wrong" | "missed" | None -- choice_marks' kind
```

Add three defaulted fields at the end of `Part` (after `ok`):

```python
    options: tuple[Option, ...] | None = None
    options_auto: bool | None = None
    options_empty_key: bool = False
```

Replace `_choice` with:

```python
def _choice(question, response, mark_result, option_marks):
    """EVERY option in author order, with the student's pick and the per-option
    verdicts the page already computed (spec §5.1). `option_marks` is
    views._results_row's choice_marks dict, normalised to {} by the caller: this
    function never calls choice_marks itself (one call site) and never reads
    Choice.is_correct (the key is mark_result.reveal, None when not auto)."""
    choices = list(question.choices.all())
    # Guarded: `response` is None for a question the student never touched.
    picked = set(response.latest_answer or []) if _answered(response) else set()
    auto = _is_auto(question)
    key = set(mark_result.reveal or ()) if auto else set()
    options = [
        Option(
            text=c.text,
            picked=c.pk in picked,
            correct=(c.pk in key) if auto else None,
            mark=option_marks.get(c.pk, {}).get("kind"),
        )
        for c in choices
    ]
    live = {c.pk for c in choices}
    # One row per missing pk: a deleted option's correctness is unknowable.
    options += [
        Option(text=_("(removed option)"), picked=True, correct=None, mark=None)
        for _missing in sorted(picked - live)
    ]
    return [
        Part(
            kind=OPTIONS,
            label_is_content=False,
            label=None,
            given=None,
            expected=None,
            ok=None,
            options=tuple(options),
            options_auto=auto,
            options_empty_key=auto and not key,
        )
    ]
```

Replace `summarise` with:

```python
_MISSING = object()


def summarise(question, response, mark_result, *, option_marks=_MISSING):
    """Display parts for one question's stored answer (spec §4.1).

    A choice question also needs `option_marks` -- the page's choice_marks dict,
    {} when there is none. The sentinel is not None on purpose: {} is a legitimate
    value for a non-auto question, and a None-keyed guard could not tell an
    omitted argument from it. The other nine adapters keep their signature."""
    adapter = _ADAPTERS[type(question)]
    if adapter is _choice:
        if option_marks is _MISSING:
            raise TypeError("summarise() needs option_marks for a choice question")
        return _choice(question, response, mark_result, option_marks)
    return adapter(question, response, mark_result)
```

- [ ] **Step 5: The view passes the marks**

In `courses/views_analytics.py::_quiz_answer_rows`, replace `row["parts"] = summarise(question, response, row["reveal_result"])` with:

```python
        # row["marks"] is None outside _results_row's AUTO branch; {} is the
        # builder's "no verdicts" (spec §5.1).
        row["parts"] = summarise(
            question, response, row["reveal_result"], option_marks=row["marks"] or {}
        )
```

- [ ] **Step 6: Run to verify**

Run: `uv run pytest tests/test_answer_summary.py tests/test_analytics_student_quiz.py tests/test_analytics_views.py`
Expected: all PASS (the page's choice rows render no answer text yet — Task B6 adds the table; no existing page test asserts on a choice answer).

- [ ] **Step 7: Write T19 (the builder follows the page's marks)**

Append to `tests/test_analytics_student_quiz.py` (add `from courses.models import Choice`, `from courses.models import ChoiceQuestionElement`):

```python
def _choice_quiz(course, title, *, marking_mode=None, correct=("B",), texts=("A", "B", "C")):
    quiz = _empty_quiz(course, title)
    fields = {"stem": "<p>Pick</p>", "max_marks": Decimal("1"), "multiple": True}
    if marking_mode is not None:
        fields["marking_mode"] = marking_mode
    question = ChoiceQuestionElement.objects.create(**fields)
    for order, text in enumerate(texts):
        Choice.objects.create(
            question=question, text=text, is_correct=text in correct, order=order
        )
    el = Element.objects.create(unit=quiz, content_object=question)
    return quiz, question, el


def _pick(question, *texts):
    return sorted(c.pk for c in question.choices.all() if c.text in texts)


def test_t19_option_kinds_equal_the_marks_the_page_computed(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Kinds", correct=("B", "C"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A", "B"), fraction=Decimal("0"), attempt_count=1)
    resp = client.get(_url(course, pupil.pk, quiz.pk))
    row = resp.context["rows"][0]
    by_text = {c.pk: c.text for c in question.choices.all()}
    expected = {by_text[pk]: mark["kind"] for pk, mark in row["marks"].items()}
    got = {o.text: o.mark for o in row["parts"][0].options}
    assert {t: k for t, k in got.items() if k is not None} == expected
    assert {t for t, k in got.items() if k is None} == set(by_text.values()) - set(expected)
    assert got == {"A": "wrong", "B": "correct", "C": "missed"}
```

And T19b — the builder follows the dict it is handed — in `tests/test_answer_summary.py` (add `from types import SimpleNamespace` and `from courses.quiz import answer_from_json`):

```python
def test_t19b_choice_marks_come_from_the_caller_never_the_builder():
    q = build_all_types()["choice"]
    stored = _pks(q, "2")
    mark_result = q.mark(answer_from_json(q, stored))
    doctored = {c.pk: {"kind": "wrong"} for c in q.choices.all()}
    parts = answer_summary.summarise(
        q, SimpleNamespace(latest_answer=stored), mark_result, option_marks=doctored
    )
    assert [o.mark for o in parts[0].options] == ["wrong", "wrong", "wrong"]
```

- [ ] **Step 8: Run and falsify T17–T19, T32**

Run: `uv run pytest tests/test_answer_summary.py tests/test_analytics_student_quiz.py -k "t17 or t18 or t19 or t32"` → PASS.

- *Mutant 1:* `picked=c.pk not in picked` → T17 red. Revert.
- *Mutant 2 (drop `missed`):* `mark=(lambda k: None if k == "missed" else k)(option_marks.get(c.pk, {}).get("kind"))` → T17 red. Revert.
- *Mutant 3:* remove the `if _answered(response) else set()` guard (`picked = set(response.latest_answer or [])`) → `AttributeError` on the no-response case. Revert.
- *Mutant 4:* emit one placeholder (`if picked - live: options.append(Option(...))`) → T17b red. Revert.
- *Mutant 5:* removed rows `mark="wrong"` → T17b red. Revert.
- *Mutant 6 (two edits):* change the default to `option_marks=None` AND the guard to a falsy check, `if not option_marks: raise TypeError(...)` → T17c's first half still passes (`None` raises), its second half goes red (`option_marks={}` now raises — every non-auto choice question would 500). ⚠️ Changing only the guard is a different mutant: the truthy `_MISSING` default then slips through to `_MISSING.get` and errors with `AttributeError` on the first half. Revert both edits.
- *Mutant 7:* `correct=c.is_correct` → T18 red. Revert.
- *Mutant 8 (T19b):* in `_choice`, re-derive the marks — as its first statement, `option_marks = question.choice_marks(list(question.choices.all()), set(response.latest_answer or []) if _answered(response) else set(), mark_result, "quiz", True)` → T19b red (the doctored dict is ignored). Revert. ⚠️ T19 stays GREEN under this mutant — a re-deriving builder computes the same dict the page did — which is exactly why T19b exists.

- [ ] **Step 9: Commit**

```bash
git add courses/answer_summary.py courses/views_analytics.py tests/answer_summary_fixtures.py tests/test_answer_summary.py tests/test_analytics_student_quiz.py
git commit -m "feat(analytics): the answer builder lists every choice option"
```

### Task B6: The options table (§5.1, markup half)

**Files:**
- Modify: `templates/courses/manage/analytics_student_quiz.html` (inside the `answers__part` div)
- Modify: `core/static/core/css/app.css` (after the `.answers__*` block)
- Modify: `tests/test_analytics_student_quiz.py`
- Modify: `tests/test_e2e_analytics_student_pages.py`
- Modify: `locale/*`

- [ ] **Step 1: Write the failing page tests (T18 page, T19 student page, T20, T21, T21b, T22, T31, T32)**

Append to `tests/test_analytics_student_quiz.py`:

```python
def _option_rows(item):
    table = item.select_one("table.answers__options")
    assert table is not None
    return table.select("tbody tr")


def _ths(item):
    return [th.get_text(" ", strip=True) for th in item.select("table.answers__options th")]


def test_t31_option_table_columns_and_cells(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz, question, el = _choice_quiz(course, "Table", correct=("B",))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A"), fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _ths(item) == ["Wybór ucznia", "Klucz", "Odpowiedź"]
    cells = [
        [td.get_text(" ", strip=True) for td in tr.select("td")] for tr in _option_rows(item)
    ]
    # column 1: ● iff picked (plus its sr-only label); column 2: ✓ iff correct
    assert cells == [
        ["● wybrana, niepoprawna", "", "A"],
        ["○ poprawna, niewybrana", "✓", "B"],
        ["○", "", "C"],
    ]


def test_t21b_one_verdict_label_per_option_row_in_column_one(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Labels", correct=("B",))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A"), fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    for tr in _option_rows(item):
        labels = tr.select(".sr-only")
        tds = tr.select("td")
        assert len(labels) <= 1
        assert all(label.find_parent("td") is tds[0] for label in labels)
    classes = [tr.get("class", []) for tr in _option_rows(item)]
    assert classes == [["answers__option", "is-wrong"], ["answers__option", "is-missed"], ["answers__option"]]


def test_t18_non_auto_choice_table_has_no_key_column(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Review", marking_mode=REVIEW)
    sub = _submitted(pupil, quiz)
    _respond(sub, el, latest_answer=_pick(question, "C"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _ths(item) == ["Student's choice", "Answer"]
    rows = _option_rows(item)
    assert all(len(tr.select("td")) == 2 for tr in rows)
    assert rows[2].select_one(".sr-only").get_text(strip=True) == "chosen"
    assert rows[0].select_one(".sr-only") is None


def test_t20_every_option_in_author_order(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Order", texts=("A", "B", "C"))
    Choice.objects.filter(question=question, text="A").update(order=2)
    Choice.objects.filter(question=question, text="C").update(order=0)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "B"), fraction=Decimal("1"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    texts = [tr.select("td")[-1].get_text(strip=True) for tr in _option_rows(item)]
    assert texts == ["C", "B", "A"]


def test_t32_empty_key_caption_distinguishes_it_from_non_auto(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "No key", correct=())
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A"), fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    caption = item.select_one("table.answers__options caption")
    assert caption.get_text(" ", strip=True) == "correct answer: (none)"
    assert "is-wrong" in _option_rows(item)[0]["class"]


def _loginable_pupil(course, username):
    """A student the test client can log in as. NOT UserFactory: it sets
    skip_postgeneration_save, so its password never reaches the database, the
    session auth hash fails on the next request, and a @login_required page
    answers 302."""
    pupil = make_verified_user(username=username, email=f"{username}@test.example.com")
    EnrollmentFactory(student=pupil, course=course)
    return pupil


def test_t19_student_results_page_shows_the_same_kinds(client):
    course, _factory_pupil = _owner_view(client)
    pupil = _loginable_pupil(course, "parity")
    quiz, question, el = _choice_quiz(course, "Parity", correct=("B", "C"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A", "B"), fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    teacher = {
        tr.select("td")[-1].get_text(strip=True): next(
            (c[3:] for c in tr["class"] if c.startswith("is-")), None
        )
        for tr in _option_rows(item)
    }
    client.force_login(pupil)
    resp = client.get(
        reverse("courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk})
    )
    assert resp.status_code == 200
    student = {}
    for li in _soup(resp).select("li.question__reveal-item"):
        mark = li.select_one(".question__reveal-mark")
        kind = None
        if mark is not None:
            kind = next(c.split("--")[1] for c in mark["class"] if "--" in c)
        student[li.select_one("span").get_text(strip=True)] = kind
    assert teacher == student == {"A": "wrong", "B": "correct", "C": "missed"}
```

`REVIEW` is already defined in this test module (used by T36); if not, add `REVIEW = QuestionElement.MarkingMode.REVIEW`. The teacher half runs FIRST, while the owner is still logged in; `force_login(pupil)` then switches the client for the student half. ⚠️ The student must come from `_loginable_pupil` (`make_verified_user`), never `_owner_view`'s `UserFactory` pupil — see its docstring.

Extend `test_t35_teacher_voice_only` (T21): before the `text = …` line add a choice question answered wrongly:

```python
    cquiz_q = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", max_marks=Decimal("1"), multiple=True
    )
    for order, text_ in enumerate(("A", "B")):
        Choice.objects.create(question=cquiz_q, text=text_, is_correct=text_ == "B", order=order)
    cel = Element.objects.create(unit=quiz, content_object=cquiz_q)
    _respond(sub, cel, latest_answer=_pick(cquiz_q, "A"), fraction=Decimal("0"), attempt_count=1)
```

and after the existing assertion add `assert "chosen, incorrect" in text and "correct, not chosen" in text` (the text is lower-cased — both labels are already lower case).

T22 — append:

```python
def test_t22_maths_in_an_option_loads_katex(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Maths", texts=("A", r"\(x^2\)"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=_pick(question, "A"), fraction=Decimal("0"), attempt_count=1)
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    assert any("katex" in src for src in _script_srcs(soup))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -k "t18 or t19 or t20 or t21 or t22 or t31 or t32 or t35"`
Expected FAIL (no table): `test_t31_option_table_columns_and_cells`, `test_t21b_…`, `test_t18_non_auto_choice_table_has_no_key_column`, `test_t20_…`, `test_t32_empty_key_caption_…`, `test_t19_student_results_page_shows_the_same_kinds`, `test_t35_teacher_voice_only`. Expected PASS: `test_t22_maths_in_an_option_loads_katex` (a guard — `_question_has_math` already scans options), `test_t19_option_kinds_equal_the_marks_the_page_computed` (B5), and the pre-existing tests the `-k` filter also selects (`test_t31_each_path_segment_404s_on_its_own`, `test_t31b_…`, the other two `test_t35_*`).

- [ ] **Step 3: The markup**

In `templates/courses/manage/analytics_student_quiz.html`, inside `<div class="answers__part answers__part--{{ part.kind }}">`, insert **before** `{% if part.label %}`:

```django
            {% if part.kind == "options" %}
              {% comment %}Every option (spec §5.1). Glyphs are aria-hidden; each row's ONE
              sr-only label sits in column 1. A picked row with no verdict (a question
              that is not auto-marked) still says it was chosen.{% endcomment %}
              <table class="answers__options">
                {% if part.options_empty_key %}{% trans "(none)" as none_label %}<caption class="answers__options-caption">{% blocktrans with key=none_label %}correct answer: {{ key }}{% endblocktrans %}</caption>{% endif %}
                <thead><tr>
                  <th scope="col" class="answers__options-mark">{% trans "Student's choice" %}</th>
                  {% if part.options_auto %}<th scope="col" class="answers__options-mark">{% trans "Answer key" %}</th>{% endif %}
                  <th scope="col">{% trans "Answer" %}</th>
                </tr></thead>
                <tbody>
                  {% for option in part.options %}
                    <tr class="answers__option{% if option.mark %} is-{{ option.mark }}{% endif %}">
                      <td class="answers__options-mark"><span aria-hidden="true">{% if option.picked %}●{% else %}○{% endif %}</span>{% if option.mark == "correct" %}<span class="sr-only">{% trans "chosen, correct" %}</span>{% elif option.mark == "wrong" %}<span class="sr-only">{% trans "chosen, incorrect" %}</span>{% elif option.mark == "missed" %}<span class="sr-only">{% trans "correct, not chosen" %}</span>{% elif option.picked %}<span class="sr-only">{% trans "chosen" %}</span>{% endif %}</td>
                      {% if part.options_auto %}<td class="answers__options-mark">{% if option.correct %}<span aria-hidden="true">✓</span>{% endif %}</td>{% endif %}
                      <td class="answers__options-text" lang="{{ course.language }}">{{ option.text }}</td>
                    </tr>
                  {% endfor %}
                </tbody>
              </table>
            {% endif %}
```

(The existing `{% if part.label %}`, `answer` branch, glyph and `expected` lines stay; for an options part they all render nothing — `label`, `given`, `expected` and `mark` are `None`.)

⚠️ `test_t31` expects the missed row's first cell text `○ poprawna, niewybrana` and the wrong row `● wybrana, niepoprawna`. A correct picked row in Polish would read `● wybrana, poprawna`.

- [ ] **Step 4: The CSS**

In `core/static/core/css/app.css`, directly after `.answers .dragimage__stage{…}`:

```css
/* Choice options (spec §5.1). width:100% — without it the table shrink-wraps
   inside the flex .answers__part. Marker columns are as wide as their header. */
.answers__options{width:100%;table-layout:auto;border-collapse:collapse;margin:.25rem 0}
.answers__options th{font-size:.75rem;font-weight:600;color:var(--text-secondary);
  text-align:left;padding:.15rem .5rem}
.answers__options td{padding:.2rem .5rem;border-top:1px solid var(--border-subtle);
  vertical-align:baseline}
.answers__options .answers__options-mark{width:1%;white-space:nowrap;text-align:center}
.answers__options-text{overflow-wrap:anywhere}
.answers__options-caption{caption-side:top;text-align:left;font-size:.8rem;
  color:var(--text-secondary);padding:0 .5rem .2rem}
.answers__option.is-correct .answers__options-mark{color:var(--success)}
.answers__option.is-wrong .answers__options-mark{color:var(--danger)}
.answers__option.is-missed .answers__options-mark{color:var(--warning)}
```

and inside the existing `@media (max-width:640px){ … }` block that follows the `.answers__*` rules, add:

```css
  /* The header words collapse; each row's sr-only label still carries the meaning.
     These are reset.css's nine .sr-only declarations, copied: CSS cannot add a class
     at a breakpoint, and hiding in THIS direction never has to out-rank .sr-only.
     The th.answers__options-mark half out-ranks the width:1% marker-column rule. */
  .answers__options th,.answers__options th.answers__options-mark{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
    overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
```

- [ ] **Step 5: Catalogs**

Catalog procedure. New: `Student's choice`, `Answer key`, `chosen, correct`, `chosen, incorrect`, `correct, not chosen`, `chosen`, `correct answer: %(key)s`. ⚠️ Check `Answer key`'s msgstr is `Klucz`, not a fuzzy „Legenda".

- [ ] **Step 6: Run to verify**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_answer_summary.py tests/test_css_citations_are_durable.py tests/test_css_comments_are_terminated_once.py`
Expected: all PASS, including `test_t38_query_count_does_not_grow_with_questions` (T23).

- [ ] **Step 7: Falsify**

- *Mutant 1 (T31):* column 1 from `option.correct` instead of `option.picked` → T31 red. Revert.
- *Mutant 2 (T31/T18):* drop `{% if part.options_auto %}` around the key `<td>`/`<th>` → T18 page red. Revert.
- *Mutant 3 (T31):* emit `<th scope="col"></th>` for the third header → T31 red. Revert.
- *Mutant 3b (T31):* `{% trans "Answer key" %}` → `{% trans "Key" %}` in the options table's second `<th>` → T31 red („Legenda"). No catalog step: `Key` already has a msgstr, so the mutant renders without `makemessages`/`compilemessages` — do not run either mid-mutant. Revert.
- *Mutant 4 (T21b):* repeat the verdict label in the key `<td>` → T21b red. Revert.
- *Mutant 5 (T20):* `{% for option in part.options %}{% if option.picked %}…{% endif %}` → T20 red. Revert.
- *Mutant 6 (T21):* render `{{ … }}` from `MARK_GLYPHS` labels — replace `{% trans "chosen, incorrect" %}` with `{% trans "your answer, incorrect" %}` → T35 red. Revert.
- *Mutant 7 (T22):* delete the `ChoiceQuestionElement` branch of `courses/views.py::_question_has_math` → T22 red. Revert.
- *Mutant 8 (T23):* in `_choice`, `choices = list(question.choices.all().order_by("order", "pk"))` → `test_t38_…` red. Revert.
- *Mutant 9 (T32):* delete the caption → T32 page red. Revert.
- *Mutant 10 (T19):* in `_choice`, `mark=None` for every live option → `test_t19_option_kinds_equal_the_marks_the_page_computed`, `test_t19b_choice_marks_come_from_the_caller_never_the_builder` and `test_t19_student_results_page_shows_the_same_kinds` red. Revert.
- *Mutant 11 (T18 page, moved here from B5):* in `_quiz_answer_rows`, drop `or {}` from `option_marks=row["marks"] or {}` → `test_t18_non_auto_choice_table_has_no_key_column` errors with `AttributeError: 'NoneType' object has no attribute 'get'`. Revert.

- [ ] **Step 8: e2e — the header words collapse on a phone (T33, §5.1)**

Append to `tests/test_e2e_analytics_student_pages.py`:

```python
def _seed_choice_page(client, username):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Choice quiz"
    )
    question = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", max_marks=Decimal("1"), multiple=True
    )
    picked = None
    for order, text in enumerate(("Alpha", "Beta", "Gamma")):
        choice = Choice.objects.create(
            question=question, text=text, is_correct=text == "Beta", order=order
        )
        if text == "Alpha":
            picked = choice
    el = Element.objects.create(unit=quiz, content_object=question)
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=quiz, status="submitted",
        score=Decimal("0"), max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=sub, element=el, latest_answer=[picked.pk],
        fraction=Decimal("0"), attempt_count=1,
    )
    return reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )


@pytest.mark.parametrize("width", [1280, 390])
def test_t33_option_headers_visible_on_desktop_hidden_on_a_phone(
    page, live_server, client, width
):
    path = _seed_choice_page(client, f"e2e_sp_th{width}")
    _login(page, live_server, f"e2e_sp_th{width}")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{live_server.url}{path}")
    th = page.locator("table.answers__options th").first
    if width == 1280:
        assert _box(th)["w"] > 20
    else:
        assert _box(th)["w"] <= 1
        _neutralise(
            page,
            # (0,2,1): must out-rank the collapse rule's th.answers__options-mark half
            ".answers__options th.answers__options-mark{position:static;width:auto;"
            "height:auto;clip:auto;margin:0}",
        )
        assert _box(th)["w"] > 20
```

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k option_headers` → PASS. (The first `<th>` carries `answers__options-mark`, so this measures the collapse against the `width:1%` rule — the case that needs the higher-specificity selector.)
*Mutant:* delete the `@media` `th` rule → the 390 case red. Revert. *Mutant:* move the declarations out of the media query → the 1280 case red. Revert.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/analytics_student_quiz.html core/static/core/css/app.css tests/test_analytics_student_quiz.py tests/test_e2e_analytics_student_pages.py locale/
git commit -m "feat(analytics): a choice question shows every option with pick and key"
```

### Task B7: Labels, and a grid for multi-part questions (§5.2)

**Files:**
- Modify: `courses/views_analytics.py` (`_quiz_answer_rows`; import `ANSWER`)
- Modify: `templates/courses/manage/analytics_student_quiz.html` (the `answers__parts` block)
- Modify: `core/static/core/css/app.css`
- Modify: `tests/test_analytics_student_quiz.py`, `tests/test_e2e_analytics_student_pages.py`
- Modify: `locale/*`

**Interfaces:**
- Produces: `row["columned"]: bool` on each `_quiz_answer_rows` row.

- [ ] **Step 1: Write the failing tests (T24, T24b, T24c, header row, single-part label)**

Append to `tests/test_analytics_student_quiz.py` (add `from courses.models import Blank`, `FillBlankQuestionElement`, `ChoiceGridQuestionElement`, `GridColumn`, `GridRow`; import `TOKEN0`, `TOKEN1` from `tests.answer_summary_fixtures`):

```python
def _fillblank_quiz(course, title, *, marking_mode=None):
    quiz = _empty_quiz(course, title)
    fields = {"stem": f"<p>2 + {TOKEN0} = {TOKEN1}</p>", "max_marks": Decimal("1")}
    if marking_mode is not None:
        fields["marking_mode"] = marking_mode
    question = FillBlankQuestionElement.objects.create(**fields)
    Blank.objects.create(question=question, accepted="2", order=0)
    Blank.objects.create(question=question, accepted="4", order=1)
    el = Element.objects.create(unit=quiz, content_object=question)
    return quiz, el


def _answered_page(client, course, pupil, quiz, el, answers, fraction):
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=answers, fraction=fraction, attempt_count=1)
    resp = client.get(_url(course, pupil.pk, quiz.pk))
    return resp, _items(_soup(resp))[0]


def test_blank_grid_statement_never_borrows_the_student_answer_label(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Blank row")
    grid = ChoiceGridQuestionElement.objects.create(stem="<p>G</p>", max_marks=Decimal("1"))
    yes = GridColumn.objects.create(question=grid, label="yes", order=0)
    no = GridColumn.objects.create(question=grid, label="no", order=1)
    GridRow.objects.create(question=grid, statement="", correct_column=yes, order=0)
    GridRow.objects.create(question=grid, statement="r2", correct_column=no, order=1)
    el = Element.objects.create(unit=quiz, content_object=grid)
    # all correct -> NOT columned, so the non-columned label branch renders
    resp, item = _answered_page(client, course, pupil, quiz, el, [yes.pk, no.pk], Decimal("1"))
    assert resp.context["rows"][0]["columned"] is False
    assert "Student's answer:" not in item.get_text(" ", strip=True)


def test_single_part_answer_is_labelled(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Single")
    el = _add(quiz)
    _resp, item = _answered_page(client, course, pupil, quiz, el, "Krakow", Decimal("0"))
    part = item.select_one(".answers__part")
    assert part.select_one(".answers__label").get_text(strip=True) == "Odpowiedź ucznia:"
    assert "Poprawna odpowiedź: Warsaw" in part.get_text(" ", strip=True)
    assert item.select_one(".answers__header-row") is None


def test_t24_extended_response_with_keywords_is_not_columned(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Essay")
    el = _add(quiz, ExtendedResponseQuestionElement, required_keywords="alpha\nbeta")
    resp, item = _answered_page(client, course, pupil, quiz, el, "alpha", Decimal("0.5"))
    assert resp.context["rows"][0]["columned"] is False
    parts = item.select(".answers__part")
    assert parts[0].select_one(".answers__label").get_text(strip=True) == "Student's answer:"
    assert item.select_one(".answers__header-row") is None


def test_t24b_the_expected_term(client):
    course, pupil = _owner_view(client)
    right, rel = _fillblank_quiz(course, "All right")
    partly, pel = _fillblank_quiz(course, "Partly")
    review, vel = _fillblank_quiz(course, "Review", marking_mode=REVIEW)
    all_right, _i = _answered_page(client, course, pupil, right, rel, ["2", "4"], Decimal("1"))
    partial, _i = _answered_page(client, course, pupil, partly, pel, ["2", "5"], Decimal("0.5"))
    sub = _submitted(pupil, review)
    _respond(sub, vel, latest_answer=["2", "5"], attempt_count=1)
    non_auto = client.get(_url(course, pupil.pk, review.pk))
    assert all_right.context["rows"][0]["columned"] is False
    assert partial.context["rows"][0]["columned"] is True
    assert non_auto.context["rows"][0]["columned"] is False


def test_t24c_every_columned_part_emits_three_children(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Grid")
    grid = ChoiceGridQuestionElement.objects.create(stem="<p>G</p>", max_marks=Decimal("1"))
    yes = GridColumn.objects.create(question=grid, label="yes", order=0)
    no = GridColumn.objects.create(question=grid, label="no", order=1)
    GridRow.objects.create(question=grid, statement="", correct_column=yes, order=0)
    GridRow.objects.create(question=grid, statement="r2", correct_column=no, order=1)
    el = Element.objects.create(unit=quiz, content_object=grid)
    # row 1 (blank statement) answered right, row 2 wrong -> partially correct
    resp, item = _answered_page(client, course, pupil, quiz, el, [yes.pk, yes.pk], Decimal("0.5"))
    assert resp.context["rows"][0]["columned"] is True
    parts = item.select(".answers__parts--columned > .answers__part")
    assert len(parts) == 2
    for part in parts:
        assert [c["class"][0] for c in part.find_all(recursive=False)] == [
            "answers__label",
            "answers__given-cell",
            "answers__expected",
        ]
    assert parts[0].select_one(".answers__label").get_text(strip=True) == ""
    assert parts[0].select_one(".answers__expected").get_text(strip=True) == ""
    header = item.select_one(".answers__parts--columned > .answers__header-row")
    assert [s.get_text(strip=True) for s in header.find_all(recursive=False)] == [
        "",
        "Odpowiedź ucznia",
        "Klucz",
    ]
```

Adjust the grid's stored-answer shape if `answer_from_json` for a choice grid expects strings: `tests/test_analytics_student_quiz.py::_stored_answer` stores `[q.columns.first().pk, ""]`, so a list of column pks is the stored shape.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -k "single_part_answer or t24 or blank_grid"`
Expected: all FAIL — `test_blank_grid_statement_never_borrows_the_student_answer_label` with `KeyError: 'columned'` (its label half is a guard for Step 4's condition, but `columned` does not exist until Step 3), the others with `KeyError: 'columned'`, no label, or no header row.

- [ ] **Step 3: The predicate**

In `courses/views_analytics.py`, add `from courses.answer_summary import ANSWER` to the imports, and in `_quiz_answer_rows` right after the `row["parts"] = summarise(...)` statement:

```python
        parts = row["parts"]
        # ONE predicate for the grid and its header row (spec §5.2): several parts,
        # all plain answers (not extended response's keyword parts, not an options
        # table), and at least one carrying a key -- so neither an all-correct
        # question nor a non-auto one (every part expected=None) gets an empty
        # third column.
        # all(...) is defensive: with today's adapters no part carrying `expected`
        # is ever a keyword or options part, so no test can falsify that clause
        # alone (T24's mutant removes both clauses).
        row["columned"] = (
            len(parts) > 1
            and all(p.kind == ANSWER for p in parts)
            and any(p.expected for p in parts)
        )
```

- [ ] **Step 4: The markup**

Replace the whole `<div class="answers__parts">…</div>` block with:

```django
      <div class="answers__parts{% if row.columned %} answers__parts--columned{% endif %}">
        {% if row.columned %}
          {% comment %}Three spans, one per grid column; the first is empty because the
          labels name their own rows. display:contents puts each span in a track.{% endcomment %}
          <div class="answers__header-row"><span></span><span>{% trans "Student's answer" %}</span><span>{% trans "Answer key" %}</span></div>
        {% endif %}
        {% for part in row.parts %}
          <div class="answers__part answers__part--{{ part.kind }}">
            {% if part.kind == "options" %}
              …the options table from Task B6, unchanged…
            {% endif %}
            {% comment %}A columned part emits EXACTLY three children -- label, given-cell,
            expected -- each unconditionally: under display:contents a missing child
            slides every later row one track left.{% endcomment %}
            {% if row.columned %}
              <span class="answers__label"{% if part.label_is_content %} lang="{{ course.language }}"{% endif %}>{{ part.label|default:"" }}</span>
            {% elif part.label %}
              <span class="answers__label"{% if part.label_is_content %} lang="{{ course.language }}"{% endif %}>{{ part.label }}</span>
            {% elif part.kind == "answer" and not part.label_is_content %}
              {% comment %}Only a part whose label is interface text can be "the student's
              answer": a grid/match row's label is CONTENT, and a blank statement there must
              stay blank rather than borrow this word.{% endcomment %}
              <span class="answers__label">{% trans "Student's answer:" %}</span>
            {% endif %}
            {% if part.kind != "options" %}
            <span class="answers__given-cell">
              {% if part.kind == "answer" %}
                {% if part.given is not None %}<span class="answers__given" lang="{{ course.language }}">{{ part.given }}</span>{% else %}<span class="answers__muted">{% trans "Not answered" %}</span>{% endif %}
              {% endif %}
              {% comment %}The glyph and its sr-only label are ONE unit, keyed on
              Part.mark, which already suppresses a tick on an empty part.{% endcomment %}
              {% if part.mark == "correct" %}<span class="answers__glyph answers__glyph--correct" aria-hidden="true">✓</span><span class="sr-only">{% trans "Correct" %}</span>
              {% elif part.mark == "incorrect" %}<span class="answers__glyph answers__glyph--incorrect" aria-hidden="true">✗</span><span class="sr-only">{% trans "Incorrect" %}</span>{% endif %}
            </span>
            {% endif %}
            {% if row.columned %}
              <span class="answers__expected">{% if part.expected %}<span class="answers__expected-label">{% trans "Correct answer:" %}</span> <strong lang="{{ course.language }}">{{ part.expected }}</strong>{% endif %}</span>
            {% elif part.expected %}
              <span class="answers__expected"><span class="answers__expected-label">{% trans "Correct answer:" %}</span> <strong lang="{{ course.language }}">{{ part.expected }}</strong></span>
            {% endif %}
          </div>
        {% empty %}
          <p class="answers__muted">{% trans "(this question no longer has any parts)" %}</p>
        {% endfor %}
      </div>
```

Paste Task B6's `<table class="answers__options">…</table>` block (with its `{% comment %}`) where the placeholder line is — the placeholder is not template syntax and must not remain.

- [ ] **Step 5: The CSS**

In `core/static/core/css/app.css`, after the options rules from Task B6:

```css
/* Multi-part questions (spec §5.2). .answers__given-cell groups the given value and
   its glyph; outside the grid it is transparent to the flex row. */
.answers__given-cell{display:contents}
.answers__header-row{font-size:.75rem;font-weight:600;color:var(--text-secondary)}
.answers__parts--columned{display:grid;grid-template-columns:auto 1fr 1fr;
  column-gap:.6rem;row-gap:.35rem;align-items:baseline}
.answers__parts--columned .answers__part{display:contents}
.answers__parts--columned .answers__header-row{display:contents}
.answers__parts--columned .answers__label,
.answers__parts--columned .answers__given-cell,
.answers__parts--columned .answers__expected{overflow-wrap:anywhere}
.answers__parts--columned .answers__given-cell{display:flex;flex-wrap:wrap;
  align-items:baseline;gap:.25rem .6rem}
@media (min-width:641px){
  .answers__parts--columned .answers__expected-label{display:none}
}
```

and inside the existing `@media (max-width:640px){…}` block for `.answers__*`:

```css
  .answers__parts--columned{display:block}
  .answers__parts--columned .answers__part{display:flex;flex-direction:column}
  .answers__parts--columned .answers__given-cell{display:contents}
  .answers__parts--columned .answers__header-row{display:none}
```

⚠️ The `@media (max-width:640px)` block must come **after** the base `.answers__parts--columned .answers__given-cell{display:flex…}` rule in source order (equal specificity). If the existing media block sits above the insertion point, add a new `@media (max-width:640px){…}` block after the grid rules instead.

- [ ] **Step 6: Catalogs**

Catalog procedure. New: `Student's answer:`, `Student's answer`.

- [ ] **Step 7: Run to verify**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_css_citations_are_durable.py tests/test_css_comments_are_terminated_once.py`
Expected: all PASS — including the existing `Correct answer: Warsaw` / `Correct answer: 3` / `"Correct answer:" not in` assertions and `test_answered_extendedresponse_keyword_parts_never_say_not_answered`.

- [ ] **Step 8: Falsify**

- *Mutant 1 (T24):* `row["columned"] = len(parts) > 1` → T24 red. Revert.
- *Mutant 2 (T24b):* drop `and any(p.expected for p in parts)` → T24b red on all-correct **and** non-auto. Revert.
- *Mutant 3 (T24c):* in the columned branch wrap the expected span in `{% if part.expected %}` → T24c red (two children). Revert.
- *Mutant 4 (T24c):* replace the columned label branch with `{% if part.label %}…{% endif %}` → T24c red on the blank-statement part. Revert.
- *Mutant 5:* use `{% trans "Key" %}` in the header row → T24c red („Legenda"). Revert.
- *Mutant 6:* drop `and not part.label_is_content` from the label fallback → `test_blank_grid_statement_never_borrows_the_student_answer_label` red. Revert.

- [ ] **Step 9: e2e — grid, fallback, prefix (T33, §5.2)**

Append to `tests/test_e2e_analytics_student_pages.py`:

```python
def _seed_fillblank_page(client, username):
    from courses.fillblank import SENTINEL
    from courses.models import Blank
    from courses.models import Element
    from courses.models import FillBlankQuestionElement
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Gaps quiz"
    )
    t0, t1 = f"{SENTINEL}0{SENTINEL}", f"{SENTINEL}1{SENTINEL}"
    question = FillBlankQuestionElement.objects.create(
        stem=f"<p>{t0} and {t1}</p>", max_marks=Decimal("1")
    )
    Blank.objects.create(question=question, accepted="2", order=0)
    Blank.objects.create(question=question, accepted="4", order=1)
    el = Element.objects.create(unit=quiz, content_object=question)
    student = UserFactory(first_name="Anna", last_name="Nowak")
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=quiz, status="submitted",
        score=Decimal("0.5"), max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=sub, element=el,
        latest_answer=["2", "a considerably longer wrong answer"],
        fraction=Decimal("0.5"), attempt_count=1,
    )
    return reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )


def test_t33_multi_part_grid_aligns_columns_on_desktop(page, live_server, client):
    path = _seed_fillblank_page(client, "e2e_sp_grid")
    _login(page, live_server, "e2e_sp_grid")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{path}")
    parts = page.locator(".answers__parts--columned > .answers__part")
    given = [_box(parts.nth(i).locator(".answers__given-cell")) for i in range(2)]
    expected_cells = [_box(parts.nth(i).locator(".answers__expected")) for i in range(2)]
    assert abs(given[0]["l"] - given[1]["l"]) <= 1
    assert abs(expected_cells[0]["l"] - expected_cells[1]["l"]) <= 1
    header = page.locator(".answers__header-row > span")
    assert abs(_box(header.nth(2))["l"] - expected_cells[1]["l"]) <= 1
    assert _style(parts.nth(1).locator(".answers__expected-label"), "display") == "none"
    # B leg: without the grid the rows are independent flex lines again.
    _neutralise(
        page,
        ".answers__parts--columned{display:block}"
        ".answers__parts--columned .answers__part{display:flex}",
    )
    moved = [_box(parts.nth(i).locator(".answers__expected")) for i in range(2)]
    assert abs(moved[0]["l"] - moved[1]["l"]) > 20


def test_t33_multi_part_block_fallback_on_a_phone(page, live_server, client):
    path = _seed_fillblank_page(client, "e2e_sp_grid390")
    _login(page, live_server, "e2e_sp_grid390")
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{live_server.url}{path}")
    part = page.locator(".answers__parts--columned > .answers__part").nth(1)
    assert _style(page.locator(".answers__header-row"), "display") == "none"
    assert _style(page.locator(".answers__parts--columned"), "display") == "block"
    assert _style(part, "flexDirection") == "column"
    label = part.locator(".answers__expected-label")
    assert _style(label, "display") != "none" and _box(label)["w"] > 0
```

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k multi_part` → PASS.

*Mutants:* move `.answers__expected-label{display:none}` out of its `min-width` query → the phone test red. Revert. Delete `.answers__parts--columned .answers__header-row{display:contents}` → the desktop header-alignment assertion red. Revert. Delete the 640px `display:block` line → the phone test red on the container's `display == "block"` assertion (the part's own `flexDirection` stays `column` — that assertion alone could not catch it). Revert.

- [ ] **Step 10: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/analytics_student_quiz.html core/static/core/css/app.css tests/test_analytics_student_quiz.py tests/test_e2e_analytics_student_pages.py locale/
git commit -m "feat(analytics): label the student's answer; align multi-part answers in a grid"
```

### Task B8: The per-question header (§5.3)

**Files:**
- Modify: `templates/courses/manage/analytics_student_quiz.html` (`manage__head` and `answers__status`)
- Modify: `core/static/core/css/app.css`
- Modify: `tests/test_analytics_student_quiz.py` (T26, T27 replaces T36, T28, T29 header)
- Modify: `tests/test_e2e_analytics_student_pages.py`
- Modify: `locale/*`

- [ ] **Step 1: Write the failing tests**

In `tests/test_analytics_student_quiz.py`, **delete** `test_t36_header_pill_matches_the_breakdown_pill`, rewrite the two section comments that name it **in place** (same line count, keep the dashes padding to the same width) — `# --- header pill + Review link (full parity is T36, Task 7) ---…` → `# --- header pill + Review link (full parity is T27) ---…` and `# --- T36 header parity ---…` → `# --- T27 header parity ---…` — and append:

```python
def _status(client, course, pupil, quiz):
    return _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(".answers__status")


def _pill_quizzes(course, pupil):
    scored = _empty_quiz(course, "Q scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("5"))
    ungraded = _empty_quiz(course, "Q ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "Q awaiting")
    _add(awaiting)
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    awaiting_sub = _submitted(pupil, awaiting, score=Decimal("1"), max_score=Decimal("1"))
    reviewed = _empty_quiz(course, "Q reviewed")
    rel = _add(reviewed, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    rsub = _submitted(pupil, reviewed, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        rsub, rel, latest_answer="essay", attempt_count=1, locked=True,
        earned_marks=Decimal("1"), fraction=Decimal("1"), reviewed_at=timezone.now(),
    )
    live = _empty_quiz(course, "Q live")
    _add(live)
    _add(live)
    live_sub = _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(live_sub, live.elements.order_by("order", "pk").first(), latest_answer="x", attempt_count=1)
    return scored, ungraded, awaiting, awaiting_sub, reviewed, live


def test_t26_header_by_pill_kind(client):
    course, pupil = _owner_view(client)
    scored, ungraded, awaiting, _sub, _reviewed, live = _pill_quizzes(course, pupil)
    s = _status(client, course, pupil, scored)
    assert s.select_one(".pill") is None
    assert s.select_one(".answers__score").get_text(" ", strip=True) == "1 / 5 marks"
    assert s.select_one(".answers__percent").get_text(strip=True) == "20%"
    for quiz, kind in ((ungraded, "pill--submitted"), (awaiting, "pill--awaiting"), (live, "pill--progress")):
        status = _status(client, course, pupil, quiz)
        assert kind in status.select_one(".pill")["class"]
        assert status.select_one(".answers__score") is None
    assert "1 of 2 questions answered" in _status(client, course, pupil, live).get_text(" ", strip=True)


def test_t27_header_pill_matches_the_breakdown_pill_except_scored(client):
    course, pupil = _owner_view(client)
    scored, ungraded, awaiting, awaiting_sub, reviewed, live = _pill_quizzes(course, pupil)
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    # (1) parity for every kind that still renders a pill; `reviewed` resolves to
    # `submitted` (spec §2.8)
    for quiz, kind in (
        (ungraded, "pill--submitted"),
        (awaiting, "pill--awaiting"),
        (reviewed, "pill--submitted"),
        (live, "pill--progress"),
    ):
        header = _status(client, course, pupil, quiz).select_one(".pill")
        row = _breakdown_pill(breakdown, quiz.title)
        assert kind in header["class"], quiz.title
        assert header["class"] == row["class"], quiz.title
        assert header.get_text(" ", strip=True) == row.get_text(" ", strip=True)
    # (2) scored: no header pill; the breakdown keeps its pill, same numbers
    status = _status(client, course, pupil, scored)
    assert status.select_one(".pill") is None
    assert _breakdown_pill(breakdown, "Q scored").get_text(" ", strip=True) == "scored 1/5 (20%)"
    assert status.select_one(".answers__score").get_text(" ", strip=True) == "1 / 5 marks"
    # (3) exactly one Review link; (4) no "scored" text on the awaiting strip
    awaiting_status = _status(client, course, pupil, awaiting)
    review_url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": awaiting_sub.pk},
    )
    assert len(awaiting_status.select(f'a[href="{review_url}"]')) == 1
    assert "scored" not in awaiting_status.get_text(" ", strip=True)


def test_t28_heading_is_name_then_title(client):
    course, pupil = _owner_view(client)
    pupil.first_name, pupil.last_name = "Anna", "Nowak"
    pupil.save()
    quiz = _empty_quiz(course, r"Sets \(A\)")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    head = _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(".manage__head")
    assert head.select_one(".answers__student").get_text(strip=True) == pupil.list_display_name
    h1 = head.select_one("h1")
    assert h1.get_text(" ", strip=True) == r"Sets \(A\)"
    assert "—" not in h1.get_text()
    assert h1.select_one("[data-math-title]") is not None
    assert head.select_one(".answers__student").get("data-math-title") is None


def test_t29_polish_header_score_uses_a_decimal_comma(client):
    course, pupil = _owner_view(client)
    _polish(client)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))
    status = _status(client, course, pupil, thirds)
    assert status.select_one(".answers__score").get_text(" ", strip=True) == "0,67 / 1 pkt"
```

(`pupil.list_display_name` with display name from Faker and first/last set renders the parenthetical form — the assertion compares against the property, so it holds either way.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -k "t26 or t27 or t28 or t29"`
Expected FAIL: `test_t26_header_by_pill_kind`, `test_t27_…` (scored half), `test_t28_heading_is_name_then_title`, `test_t29_polish_header_score_uses_a_decimal_comma`. Expected PASS: the two B1 `test_t29_*` tests, and any pre-existing `t28`-matching test.

- [ ] **Step 3: The markup**

In `templates/courses/manage/analytics_student_quiz.html`, replace the `<header class="manage__head">…</header>` and `<p class="answers__status">…</p>` blocks with:

```django
  <header class="manage__head">
    <div class="answers__heading">
      <p class="answers__student">{{ student.list_display_name }}</p>
      <h1 class="manage__title"><span lang="{{ course.language }}" data-math-title>{{ unit.title }}</span></h1>
    </div>
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% trans "Student results" %}</a>
  </header>
  <p class="answers__status">
    {% with p=pill %}
      {% comment %}A scored quiz shows its score INSTEAD of the shared pill; the pill
      partial's logic is untouched and still serves every other kind (spec §5.3).{% endcomment %}
      {% if p.kind == "scored" %}
        <span class="answers__score">{% blocktrans with s=p.score|marks m=p.max_score|marks %}{{ s }} / {{ m }} marks{% endblocktrans %}</span>
        <span class="answers__percent">{{ p.percent }}%</span>
      {% else %}
        {% include "courses/manage/_quiz_pill.html" %}
      {% endif %}
      {% if p.kind == "awaiting" %}
        <a class="answers__review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=submission.pk %}">{% trans "Review" %}</a>
      {% endif %}
      {% if p.kind == "in_progress" and question_count %}
        <span class="answers__count">{% blocktrans with k=answered_count count n=question_count %}{{ k }} of {{ n }} question answered{% plural %}{{ k }} of {{ n }} questions answered{% endblocktrans %}</span>
      {% endif %}
    {% endwith %}
  </p>
```

- [ ] **Step 4: The CSS**

In `core/static/core/css/app.css`, after the `.answers__status{…}` rule:

```css
.answers__heading{min-width:0}
.answers__student{margin:0 0 .15rem;font-size:.875rem;color:var(--text-secondary)}
.answers .manage__head .btn{flex-shrink:0}
/* Scoped by class AND width: .manage__head is shared and wraps on purpose, and below
   641px app.css cancels the button's auto-push precisely because the header wraps. */
@media (min-width:641px){.answers .manage__head{flex-wrap:nowrap}}
.answers__score{font-size:1.25rem;font-weight:700;font-variant-numeric:tabular-nums}
.answers__percent{font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.answers__score + .answers__percent::before{content:"·";margin-right:.6rem;
  color:var(--text-tertiary)}
```

- [ ] **Step 5: Catalogs**

Catalog procedure. New: `%(s)s / %(m)s marks` → `%(s)s / %(m)s pkt`.

- [ ] **Step 6: Run to verify**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_title_math_markers.py tests/test_title_math_assets.py`
Expected: all PASS.

- [ ] **Step 7: Falsify**

- *Mutant 1 (T26):* render `.answers__score` for every kind → T26 red on three kinds. Revert.
- *Mutant 2 (T27):* keep the include for `scored` too → T27 red on (2). Revert.
- *Mutant 3 (T27):* add the awaiting Review link to `_quiz_pill.html` → T27 red on (3). Revert.
- *Mutant 4 (T28):* restore `{{ unit.title }} — {{ student.display_name|default:student.username }}` → T28 red. Revert.
- *Mutant 5 (T28):* drop the `data-math-title` span → T28 red. Revert.
- *Mutant 6 (T29):* `{{ p.score }}` without `|marks` → T29 header red. Revert.

- [ ] **Step 8: e2e — the back button does not wrap (T33, §5.3)**

Append to `tests/test_e2e_analytics_student_pages.py`:

```python
@pytest.mark.parametrize("width", [1280, 390])
def test_t33_back_button_stays_beside_a_long_title(page, live_server, client, width):
    from courses.models import ContentNode

    username = f"e2e_sp_head{width}"
    course, student, awaiting = _seed_breakdown(client, username)
    ContentNode.objects.filter(pk=awaiting.pk).update(
        title="A deliberately long quiz title that would push the back button " * 2
    )
    _login(page, live_server, username)
    page.set_viewport_size({"width": width, "height": 900})
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": awaiting.pk},
    )
    page.goto(f"{live_server.url}{path}")
    head = page.locator(".answers .manage__head")
    heading, button = head.locator(".answers__heading"), head.locator(".btn")
    if width == 1280:
        assert _box(button)["t"] < _box(heading)["b"]  # same line
        assert abs(_box(head)["r"] - _box(button)["r"]) <= 1
        _neutralise(page, ".answers .manage__head{flex-wrap:wrap}")
        assert _box(button)["t"] >= _box(heading)["b"] - 1
    else:
        assert _box(button)["t"] >= _box(heading)["b"] - 1  # wraps below, as today
    # the shared header on another page still wraps
    page.set_viewport_size({"width": 1280, "height": 900})
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    page.goto(f"{live_server.url}{matrix_path}")
    assert _style(page.locator(".manage__head").first, "flexWrap") == "wrap"
```

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k back_button` → PASS.
*Mutants:* unscope the rule to `.manage__head{flex-wrap:nowrap}` at every width → the shared-header assertion red. Revert. Remove the `min-width` query (nowrap at every width) → the 390 case red. Revert.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/analytics_student_quiz.html core/static/core/css/app.css tests/test_analytics_student_quiz.py tests/test_e2e_analytics_student_pages.py locale/
git commit -m "feat(analytics): per-question header — student above title, score instead of pill"
```

### Task B9: Outcome colour on both verdict pages (§5.4)

**Files:**
- Modify: `templates/courses/manage/analytics_student_quiz.html` (the `answers__verdict` badges + its drift comment)
- Modify: `templates/courses/quiz_results.html` (the badges; drift note appended to an existing line)
- Modify: `courses/static/courses/css/courses.css` (after `.badge--muted`)
- Modify: `core/static/core/css/app.css` (`.answers__item` edge; `.pill--scored`, `.pill--awaiting`)
- Modify: `tests/test_analytics_student_quiz.py`, `tests/test_e2e_analytics_student_pages.py`

- [ ] **Step 1: Write the failing test (T25)**

Append to `tests/test_analytics_student_quiz.py`:

```python
def _outcome_quiz(course, pupil):
    quiz = _empty_quiz(course, "Outcomes")
    sub = _submitted(pupil, quiz, score=Decimal("1.5"), max_score=Decimal("4"))
    for fraction in ("1", "0.5", "0"):
        el = _add(quiz)
        _respond(sub, el, latest_answer="x", fraction=Decimal(fraction), attempt_count=1)
    _add(quiz)  # untouched -> not_answered
    return quiz


EXPECTED_BADGES = [
    ("is-correct", "badge--correct"),
    ("is-partial", "badge--partial"),
    ("is-incorrect", "badge--incorrect"),
    ("is-not_answered", "badge--muted"),
]


def test_t25_badge_modifier_per_outcome_on_both_verdict_pages(client):
    course, _factory_pupil = _owner_view(client)
    # _loginable_pupil is defined in Task B6; see its docstring
    pupil = _loginable_pupil(course, "outcomes")
    quiz = _outcome_quiz(course, pupil)
    items = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    got = [
        (next(c for c in item["class"] if c.startswith("is-")),
         item.select_one(".answers__verdict .badge")["class"][1])
        for item in items
    ]
    assert got == EXPECTED_BADGES
    client.force_login(pupil)
    resp = client.get(reverse("courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}))
    assert resp.status_code == 200
    student = [
        (next(c for c in li["class"] if c.startswith("is-")),
         li.select_one(".question__feedback-panel .badge")["class"][1])
        for li in _soup(resp).select("li.quiz-results__item")
    ]
    assert student == EXPECTED_BADGES
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_analytics_student_quiz.py -k t25` → FAIL (`IndexError`: a bare `.badge` has one class).

- [ ] **Step 3: The markup, on both templates**

In `analytics_student_quiz.html`, change the three verdict badges' opening tags to `<span class="badge badge--correct">`, `<span class="badge badge--partial">`, `<span class="badge badge--incorrect">`. Edit the existing comment's text in place (same line count): `(spec §5.1): extracting a partial would change the pupil's results page.` → `(spec §5.1), outcome modifiers included: extracting a partial would change the pupil's page.`

In `quiz_results.html`, make the same three class changes, and append a single-line comment to the end of the `<div class="question__feedback-panel …">` line (no new line):

```django
      <div class="question__feedback-panel question__feedback-panel--{{ row.outcome }}">{# Badges: a deliberate copy of manage/analytics_student_quiz.html's, modifiers included; change both. #}
```

- [ ] **Step 4: The CSS**

First read "Spec gaps" item 6 in the plan for the owner's Task 0 answer. "Keep" or no answer → the block below as written. A named alternative → use it for `.badge--partial`'s `color` declaration only (border stays `--warning`); T33b's assertions are unchanged either way.

`courses/static/courses/css/courses.css`, replace `.badge--muted { color: var(--text-tertiary); }` with:

```css
/* The muted chip reads at body size: --text-tertiary fails AA there. */
.badge--muted { color: var(--text-secondary); }
/* Outcome badges (analytics student pages spec §5.4). The fill stays the base
   .badge's --surface-sunken: it differs from the student page's tinted
   .question__feedback-panel--* AND from the teacher page's raised .answers__item,
   so the badge never sits green-on-green or raised-on-raised. */
.badge--correct { color: var(--success); border-color: var(--success); }
.badge--partial { color: var(--warning); border-color: var(--warning); }
.badge--incorrect { color: var(--danger); border-color: var(--danger); }
```

`core/static/core/css/app.css`, after `.answers__item{…}`:

```css
/* The teacher's card edge mirrors the student page's tinted verdict panel. */
.answers__item.is-correct{border-left:4px solid var(--success)}
.answers__item.is-partial{border-left:4px solid var(--warning)}
.answers__item.is-incorrect{border-left:4px solid var(--danger)}
```

and replace the two hard-coded pills:

```css
.pill--scored{background:var(--primary);color:var(--text-inverse)}
```

```css
.pill--awaiting{background:var(--warning-subtle);color:var(--text-primary);
  border:1px solid var(--warning)}
```

- [ ] **Step 5: Run to verify**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_consumption_pages.py tests/test_courses_views.py tests/test_quiz_results_choice_reveal.py tests/test_ux_roster_and_feedback.py tests/test_css_citations_are_durable.py tests/test_css_comments_are_terminated_once.py tests/test_border_contrast_css.py tests/test_text_colour_css.py`
Expected: all PASS.

- [ ] **Step 6: Falsify T25**

- *Mutant:* drop `badge--partial` from `quiz_results.html` only → T25 red on the student half. Revert. Same for the teacher template → red on the teacher half. Revert.

- [ ] **Step 7: e2e — the badge owns its surface (T33b) and the card edge**

Append to `tests/test_e2e_analytics_student_pages.py`:

```python
def _seed_outcomes(client, username):
    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_pa
    from tests.factories import make_verified_user

    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Outcomes"
    )
    student = make_verified_user(
        username=f"{username}_s", email=f"{username}_s@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=quiz, status="submitted",
        score=Decimal("1.5"), max_score=Decimal("3"),
    )
    for fraction in ("1", "0.5", "0"):
        el = Element.objects.create(
            unit=quiz,
            content_object=ShortTextQuestionElement.objects.create(
                stem="<p>Q</p>", accepted="a", max_marks=Decimal("1")
            ),
        )
        QuestionResponse.objects.create(
            submission=sub, element=el, latest_answer="x",
            fraction=Decimal(fraction), attempt_count=1,
        )
    return pa, student, course, quiz


OUTCOMES = ("correct", "partial", "incorrect")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_t33b_badge_has_its_own_opaque_surface_on_both_pages(page, live_server, client, theme):
    username = f"e2e_sp_badge_{theme}"
    pa, student, course, quiz = _seed_outcomes(client, username)
    for user in (pa, student):
        user.theme = theme
        user.save(update_fields=["theme"])

    _login(page, live_server, username)
    teacher_path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student.pk, "node_pk": quiz.pk},
    )
    page.goto(f"{live_server.url}{teacher_path}")
    for outcome in OUTCOMES:
        item = page.locator(f"li.answers__item.is-{outcome}")
        badge = item.locator(".answers__verdict .badge")
        bg = _style(badge, "backgroundColor")
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), outcome
        assert bg != _style(item, "backgroundColor"), outcome
        assert _style(item, "borderLeftWidth") == "4px", outcome

    page.context.clear_cookies()
    _login(page, live_server, f"{username}_s")
    results_path = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    page.goto(f"{live_server.url}{results_path}")
    for outcome in OUTCOMES:
        panel = page.locator(f".question__feedback-panel--{outcome}")
        badge = panel.locator(".badge")
        bg = _style(badge, "backgroundColor")
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), outcome
        assert bg != _style(panel, "backgroundColor"), outcome
```

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k t33b` → PASS.
*Mutants:* `.badge--correct { background: transparent; … }` → red on the opaque assertion. Revert. `.badge--correct { background: var(--surface-raised); … }` → red on the teacher page. Revert. `.badge--correct { background: var(--success-subtle); … }` → red on the student page. Revert. Delete the `.answers__item.is-partial` edge → red on `borderLeftWidth`. Revert.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/analytics_student_quiz.html templates/courses/quiz_results.html courses/static/courses/css/courses.css core/static/core/css/app.css tests/test_analytics_student_quiz.py tests/test_e2e_analytics_student_pages.py
git commit -m "feat(analytics): outcome colour on the verdict badge, both pages; pills in tokens"
```

### Task B10: Help pages and help screenshots

**Files:**
- Modify: `docs/help/teacher/drill-down.md`, `docs/help/teacher/drill-down.pl.md`
- Possibly modify: `core/static/core/img/help/drill-down.{en,pl}.png`, `review-submission.{en,pl}.png`

- [ ] **Step 1: English help**

In `docs/help/teacher/drill-down.md`, change the screenshot's alt text `![A per-student results breakdown](static:core/img/help/drill-down.en.png)` to `![A student's results page](static:core/img/help/drill-down.en.png)`, and replace the `## Per-student breakdown` and `## Per-question answers` sections with:

```markdown
## Student results

Click a student's name to open their results page for the current course. It
opens in the same view as the matrix you came from, and a **Progress / Results**
switch under the heading changes it without going back:

- **Progress** lists every lesson and quiz. A finished lesson carries a ✓, an
  unfinished one an empty ○, and a lesson that is not required is tagged
  **Additional**. Chapter headings show how many required lessons are done.
- **Results** lists only the quizzes — with their status or score — and the
  chapters that contain them.

The **← Analytics** link restores the exact scope, mode, expanded columns and
subset you came from, so you can dip into one student and pop straight back to
the same grid.

## Per-question answers

On a student's results page, the title of every quiz they have started is a
link. Click it to see that quiz question by question: the student's answer, the
answer key where theirs was wrong, the marks, and how many attempts they used.
A choice question lists **every** option, marking what the student chose and
which options are correct; a question with several parts lines the student's
answers and the key up in columns. A quiz still in progress shows the answers
given so far. A question waiting for your review links straight to the review
page. The **← Student results** link takes you back with your analytics view
unchanged.
```

- [ ] **Step 2: Polish help**

Read `docs/help/teacher/drill-down.pl.md` in full. Change the screenshot's alt text `![Szczegółowe wyniki ucznia](static:core/img/help/drill-down.pl.png)` to `![Wyniki ucznia](static:core/img/help/drill-down.pl.png)`, then replace its two matching sections (the per-student and per-question ones) with:

```markdown
## Wyniki ucznia

Kliknij imię i nazwisko ucznia, aby otworzyć stronę jego wyników w bieżącym
kursie. Otwiera się w tym samym widoku, z którego przyszedłeś w macierzy, a
przełącznik **Postęp / Wyniki** pod nagłówkiem zmienia go bez powrotu:

- **Postęp** pokazuje wszystkie lekcje i quizy. Ukończona lekcja ma ✓,
  nieukończona puste ○, a lekcja nieobowiązkowa jest oznaczona jako
  **Dodatkowa**. Nagłówki rozdziałów pokazują, ile obowiązkowych lekcji ukończono.
- **Wyniki** pokazuje tylko quizy — z ich stanem lub wynikiem — i rozdziały,
  które je zawierają.

Odnośnik **← Analityka** przywraca dokładnie ten zakres, widok, rozwinięte kolumny i
wybór uczniów, z którego przyszedłeś.

## Odpowiedzi na pytania

Na stronie wyników ucznia tytuł każdego rozpoczętego przez niego quizu jest
odnośnikiem. Kliknij go, aby zobaczyć quiz pytanie po pytaniu: odpowiedź ucznia,
klucz tam, gdzie odpowiedź była błędna, punkty i liczbę prób. Pytanie
wielokrotnego wyboru pokazuje **wszystkie** opcje — co uczeń wybrał i które
opcje są poprawne; pytanie z kilkoma częściami układa odpowiedzi ucznia i klucz
w kolumnach. Quiz w toku pokazuje dotychczasowe odpowiedzi. Pytanie czekające
na sprawdzenie prowadzi prosto do strony sprawdzania. Odnośnik **← Wyniki ucznia**
wraca z niezmienionym widokiem analityki.
```

Keep the page's existing link words exactly as the Polish UI renders them: check „Analityka" and „Postęp"/„Wyniki" against `locale/pl` (`Analytics`, `Progress`, `Results`) and „Dodatkowa" against `Additional`; match the file's and the catalog's vocabulary throughout — „quiz/quizy/quizu" (never „kwiz"; `Quiz` is „Quiz" in `locale/pl`), „odnośnik" (never „link") and „sprawdzenie/sprawdzania" for review (the UI's `Review` is „Sprawdź"; never „ocena/oceniania") — and if the file uses a different register (e.g. no „Ty"-form), match the file.

- [ ] **Step 3: Help screenshots (manual checklist)**

```bash
uv run python -m pytest tests/capture_help_screenshots.py
git status --short core/static/core/img/help/
git diff --name-only -- core/static/core/img/help/ | grep -v -e "drill-down\." -e "review-submission\." | xargs -r git checkout --
git clean -n -- core/static/core/img/help/   # untracked PNGs the restore above cannot see
git clean -f -- core/static/core/img/help/   # only if the dry run listed files; none are ours
git status --short core/static/core/img/help/
```

Expected final status: only files from those four (any of them may be unchanged). Open each changed PNG with the Read tool and confirm it shows the new page (student results heading; the review page's muted badge).

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/test_help.py tests/test_help_capture_isolation.py` → PASS.

```bash
git add docs/help/teacher/drill-down.md docs/help/teacher/drill-down.pl.md core/static/core/img/help/drill-down.en.png core/static/core/img/help/drill-down.pl.png core/static/core/img/help/review-submission.en.png core/static/core/img/help/review-submission.pl.png
git commit -m "docs(help): student results page, view switch, every option listed"
```

### Task B11: Design pass, screenshots (T34), branch gate, PR B

- [ ] **Step 0: Serve the worktree on mat-pp**

Steps 1 and 2 both need the two pages rendered on real data, so set this up first.

⚠️ **A worktree cannot serve the app as-is.** `config/settings/base.py` reads `.env` from `BASE_DIR` (the worktree — copied there at creation; without it `DEBUG` falls back to False, so the DEBUG-only media routes vanish, and `DATABASE_URL` falls back to its hard-coded default), and `MEDIA_ROOT` is `BASE_DIR / "media"`, which holds mat-pp's images only in the main checkout. From the worktree, first:

```bash
# .env was copied when the worktree was created (PR A, "Where to work").
# The help-screenshot captures (A3, B10) seeded a REAL media/ directory here
# (seed_demo_course saves demo.png under MEDIA_ROOT). mklink refuses an existing
# path, so remove it -- only if it is a plain directory, never a junction:
# MSYS_NO_PATHCONV=1 is required: Git Bash rewrites the bare /J switch to J:/.
if [ ! -L media ]; then
  [ -d media ] && rm -rf media
  MSYS_NO_PATHCONV=1 cmd /c mklink /J media "C:\Users\krzys\Documents\Python\own\libli\media"
fi
[ -L media ] || { echo "junction not created"; exit 1; }
uv run python manage.py shell -c "from django.conf import settings; from django.db import connection; print(settings.DEBUG, connection.settings_dict['NAME'], settings.MEDIA_ROOT)"
```

Expected: `True`, the mat-pp database name the main checkout uses, and a `MEDIA_ROOT` whose directory lists mat-pp's files. Both `.env` and `media` are gitignored — confirm `git status --short` does not list them.

**A student to log in as — with REAL answers, not fabricated rows.** `quiz_results.html` and `course_results.html` are a student's OWN pages; a teacher cannot open them for someone else, and no mat-pp student's password is known. Do NOT write `QuestionResponse` rows by hand: a fraction that disagrees with the stored answer (or a "partial" on a single-answer question) renders incoherent badges and tables, which the design pass would then judge. Instead, on the LOCAL copy only (prod is the source of truth and is never touched), build a tiny throwaway course the mat-pp owner can see, and let a throwaway student take its quiz through the real UI so the real marking produces the rows. From the worktree (its `.env` points at the local mat-pp DB). The snippet is idempotent — safe to re-run:

```bash
uv run python manage.py shell -c "
from decimal import Decimal
from django.db import transaction
from django.urls import reverse
from courses.fillblank import SENTINEL
from courses.models import Blank, Course, ContentNode, Element, Enrollment, FillBlankQuestionElement, QuestionElement, ShortTextQuestionElement
from accounts.models import User
from tests.factories import make_verified_user
matpp = Course.objects.get(slug='mat-pp')
course, _ = Course.objects.get_or_create(slug='t34-throwaway', defaults={'title': 'T34 throwaway', 'language': matpp.language, 'owner': matpp.owner})
def quiz(title):
    node, _ = ContentNode.objects.get_or_create(course=course, kind='unit', unit_type='quiz', title=title, defaults={'published': True})
    return node
def fill(node, build):
    # keyed on existing elements, not on get_or_create: a failed run must still fill the node
    if node.elements.exists():
        return
    with transaction.atomic():  # all-or-nothing: a failed run leaves no question rows to orphan
        for order, q in enumerate(build()):
            Element.objects.create(unit=node, content_object=q, order=order)
def marked_questions():
    t0, t1 = f'{SENTINEL}0{SENTINEL}', f'{SENTINEL}1{SENTINEL}'
    q1 = ShortTextQuestionElement.objects.create(stem='<p>T34: capital of Poland?</p>', accepted='Warszawa', max_marks=Decimal('1'))
    q2 = FillBlankQuestionElement.objects.create(stem=f'<p>T34: 1 + 1 = {t0}, 2 + 2 = {t1}</p>', max_marks=Decimal('1'))
    Blank.objects.create(question=q2, accepted='2', order=0)
    Blank.objects.create(question=q2, accepted='4', order=1)
    q3 = ShortTextQuestionElement.objects.create(stem='<p>T34: capital of France?</p>', accepted='Paryż', max_marks=Decimal('1'))
    return [q1, q2, q3]
def review_questions():
    return [ShortTextQuestionElement.objects.create(stem='<p>T34: describe a set in one sentence.</p>', accepted='x', marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal('1'))]
def unstarted_questions():
    return [ShortTextQuestionElement.objects.create(stem='<p>T34: never opened.</p>', accepted='x', max_marks=Decimal('1'))]
marked, review, unstarted = quiz('T34 marked'), quiz('T34 review'), quiz('T34 unstarted')
fill(marked, marked_questions)
fill(review, review_questions)
fill(unstarted, unstarted_questions)
student = User.objects.filter(username='t34student').first() or make_verified_user(username='t34student', email='t34student@example.invalid', password='T34-local-only!')
Enrollment.objects.get_or_create(student=student, course=course)
for node in (marked, review, unstarted):
    print(node.title, reverse('courses:quiz_unit', kwargs={'slug': course.slug, 'node_pk': node.pk}))
"
```

(Every stem starts `T34:` — Task B12's orphan check keys on that. The snippet contains no backticks and no `$`: inside the double-quoted `-c` string bash would expand them.)

Expected: three lines, `T34 marked /courses/t34-throwaway/u/<pk>/quiz/`, then `T34 review …` and `T34 unstarted …`. If `Course.objects.get(slug='mat-pp')` fails, the local slug differs (imports re-slug from the title): list `Course.objects.values_list('slug', 'title')` and substitute it. Then, with the server running (below), log in as `t34student` / `T34-local-only!` and, through the UI:
- open **T34 marked** and answer **„Warszawa"** (correct), blanks **„2" and „5"** (partial), **„Londyn"** (incorrect); finish the quiz;
- open **T34 review**, type any sentence, finish the quiz — it now awaits review;
- **never open T34 unstarted** — it is what renders a „not started" `.badge--muted` row on `course_results.html`.

Step 1 measures `.badge--partial` on this student's own `quiz_results.html`, switching only the THROWAWAY user's theme (`User.objects.filter(username='t34student').update(theme='light')`, measure, then `'dark'`, measure) — it needs no restore. Task B12 deletes the throwaway course and student.

Then start the app against the local mat-pp database (use the `run` skill) and leave it running through Step 2. ⚠️ Expect an "unapplied migration" warning: `origin/master` carries a data-only migration (`courses` 0065, blank-stem cleanup) that the local mat-pp DB and the main checkout's docs branch do not have. **Do not run `migrate` from the worktree** — it would rewrite the shared local DB and record a migration the main checkout cannot see. The warning is harmless for these pages. **Record its port** where Task B12 can find it in a later session without publishing it: `echo <port> > .env.t34-port` in the worktree (the `.env*` ignore rule keeps it out of git).

- [ ] **Step 1: `frontend-design` pass**

Invoke the `frontend-design:frontend-design` skill on the two pages as built (spec §8: after the markup exists, before screenshots are judged). Scope: spacing, type scale and colour of the new elements only (`.breakdown__view`, `.breakdown-unit__tag`, `.badge--todo`, `.answers__options`, `.answers__header-row`, `.answers__heading`, `.answers__score`). Any change it proposes to a rule an e2e test pins must keep that test green; re-run `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py` after applying.

On the Step 0 server, logged in as `t34student`, open **T34 marked**'s `quiz_results.html` and measure the partial row's `.badge--partial` text contrast (computed `color` against computed `background-color`) with `t34student`'s theme set to `light`, then to `dark` (the `theme` field as in Step 0, never a cookie; reload after each change). If either is below 4.5:1, **do not change the colour**. If Task 0 got an owner answer (recorded under "Spec gaps" item 6), report the measured ratios beside that decision; only if it got none, record the ratio for the PR body as a question for the owner.

- [ ] **Step 2: Screenshots on mat-pp data (T34)**

With the server from Step 0 running, capture light **and** dark, 1280 and 390 wide.

**As the mat-pp owner** (theme switched via the owner's `theme` field — see the restore note below):
- on **mat-pp**, from REAL submissions: the student results page in Results and in Progress mode; the per-question page for „Zbiory - quiz" with a wrong choice answer on question 1; the per-question page for an in-progress quiz;
- on **t34-throwaway** — the one exception to "real mat-pp submissions", because the local mat-pp copy holds NO submission awaiting review: `t34student`'s per-question page for **T34 review**, and that submission's `review_submission.html` (reached from its Review link).

**As `t34student`** (the only student with a known password; theme via `User.objects.filter(username='t34student').update(theme='light')`, then `'dark'`, reloading after each):
- `quiz_results.html` for **T34 marked** (correct/partial/incorrect rows on tinted panels);
- `course_results.html` for **t34-throwaway** — its **T34 unstarted** row is the „not started" `.badge--muted` surface this capture exists to judge.

Save them under the scratchpad directory, open each with the Read tool, and judge dark on its own terms (legibility of `--warning` text, the badge surface against the card, the pill tokens). Fix what is wrong before continuing.

**Dark teacher pages change a REAL user's setting.** Before the first dark teacher-page capture, note the mat-pp owner's current value (`Course.objects.get(slug='mat-pp').owner.theme`); after the last capture, set it back to exactly that value with `User.objects.filter(pk=<owner pk>).update(theme='<original>')`.

**Stop the Step 0 server now** (it would otherwise keep running through the gate and the rebase, autoreloading on every rewritten file, and hold files in the worktree that block Task B12). Stop it the way the `run` skill started it, then confirm nothing listens on its port: `netstat -ano | grep ":<port> " | grep LISTENING` prints nothing.

- [ ] **Step 2b: Commit the design-pass and screenshot fixes**

If `git status --short` is clean, skip this step. Otherwise:

```bash
uv run ruff format <every .py file changed in Steps 1-2>
uv run ruff check --no-cache .
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py
uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py
```

If a msgid changed, run the Catalog procedure too. If any CSS or template changed, the help screenshots committed in Task B10 are stale: first take `media` out of the way with the same junction-aware command Task B12 uses — `if [ -L media ]; then MSYS_NO_PATHCONV=1 cmd /c rmdir media; elif [ -d media ]; then rm -rf media; fi` — because the capture seeds files under `MEDIA_ROOT` and must not write into the main checkout's media, then re-run Task B10 Step 3's capture-and-restore commands exactly, and include the kept PNGs in this commit. The re-capture leaves a plain `media/` directory behind: if you go back to Steps 0-2 for more mat-pp screenshots, re-run Step 0's junction block (it removes the seeded directory), then restart the server (the throwaway-course snippet is idempotent, and the student's quiz is already taken — do not take it again). Then:

```bash
git status --short   # stage EVERY file listed (CSS, templates, courses/*.py, docs/help/, locale/, tests/, help PNGs) -- nothing else should be dirty
git add core/static/core/css/app.css courses/static/courses/css/courses.css templates/courses/ courses/ docs/help/ locale/ tests/ core/static/core/img/help/drill-down.en.png core/static/core/img/help/drill-down.pl.png core/static/core/img/help/review-submission.en.png core/static/core/img/help/review-submission.pl.png
git commit -m "style(analytics): design pass on the student pages"
git status --short
```

Expected: `git status` is clean — `git rebase` in Step 4 refuses to start on a dirty tree, and the Step 3 gate must test what gets pushed.

- [ ] **Step 3: Branch gate**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
uv run pytest tests/test_[a-f]*.py
uv run pytest tests/test_[g-o]*.py
uv run pytest tests/test_[p-z]*.py tests/demo tests/lal_import
uv run pytest accounts courses core demo grouping institution integrations notes notifications support tags
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py tests/test_e2e_analytics.py tests/test_e2e_results.py tests/test_e2e_review.py tests/test_e2e_unit_nav.py tests/test_e2e_outline_tree.py tests/test_e2e_quiz_math.py tests/test_e2e_quiz.py tests/test_e2e_choicegrid.py tests/test_e2e_questions_2diii.py tests/test_e2e_demo_tab.py
```

Expected: fuzzy counts `0`; every summary line `N passed` with no `failed`/`error`. If an e2e fails, re-run it alone before believing it (parallel-load flakes are known); a real failure is fixed, not retried away.

- [ ] **Step 4: Rebase and open PR B**

**Stop here until PR A is merged** — Steps 1–3 may finish while PR A is still in review. If PR A took review changes after `feat/analytics-student-pages` was cut, they arrive through this rebase; on a conflict in `tests/test_analytics_student_order.py`, keep B3's deletion of T5 and keep PR A's other changes. Once PR A is merged:

```bash
git fetch origin
git rebase origin/master
```

Catalog conflicts are expected: five PR B commits (B3, B4, B6, B7, B8) touch `locale/`, and each rewrites the `#:` source comments. On ANY conflict in `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`:
  1. Take master's side of all four catalog files: `git checkout --ours -- locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.mo`. ⚠️ During a rebase the sides are swapped: `--ours` is the branch being rebased ONTO (master), `--theirs` is the commit being replayed.
  2. Re-run the full Catalog procedure from Global Constraints: `makemessages`, then overwrite the msgstr of **every msgid from the Global Constraints table that is now present in the `.po`** (e.g. „Klucz"), fuzzy count 0, `compilemessages`.
  3. `git add locale/` and `git rebase --continue`.

  Expect to repeat this once per conflicting catalog commit. Never hand-merge a `.po` (it resurrects fuzzies and drops owner-decided msgstrs) or a binary `.mo`. After the rebase, re-run the **whole** Step 3 gate — ruff check and format check, the fuzzy count, all four non-e2e chunks and the full e2e line (at minimum `tests/test_e2e_analytics_student_pages.py`, which pins the computed styles master's CSS changes could shift) — before pushing.

```bash
git push -u origin feat/analytics-student-pages
gh pr create --base master --title "Analytics student pages: follow the view, list every option, outcome colour" --body-file <scratchpad>/pr-b.md
```

PR body: the three scopes; the new and obsolete msgids (§6, with „Klucz" as the owner's decision); the plan's "Spec gaps" items 2 (the added „wybrana" label), 3 and 5 as questions for the owner; item 6 with the measured contrast ratios — as a question only if Task 0 got no answer, otherwise as a report next to the owner's decision; that T5 was deleted with T28/T28b as successors and T36 replaced by T27; the help screenshots kept; the Claude Code attribution line.

### Task B12: Clean up after PR B merges

**Precondition:** no process runs from the worktree — the B11 Step 0 server is stopped: `netstat -ano | grep ":$(cat C:/Users/krzys/Documents/Python/own/libli-analytics-pages/.env.t34-port) " | grep LISTENING` prints nothing.

- [ ] **Step 0: Delete the throwaway T34 course and student (local copy only)**

From the worktree (its `.env` points at the local mat-pp DB), before Step 1 removes anything:

```bash
uv run python manage.py shell -c "from accounts.models import User; from courses.models import Course; c = Course.objects.filter(slug='t34-throwaway').first(); print(c.delete() if c else 'no course'); print(User.objects.filter(username='t34student').delete())"
```

⚠️ Delete the course through the INSTANCE (`c.delete()`), never `Course.objects.filter(...).delete()`: `Course.delete` is overridden to remove the concrete question rows first, and a queryset delete skips it, orphaning them. Expected: the first tuple includes `'courses.Course': 1` plus cascaded rows (`ContentNode`, `Enrollment`, `QuizSubmission`, …) — it does NOT list the question models, because `Course.delete` removes those BEFORE the cascade whose counts it prints; the second includes `'accounts.User': 1`. `no course` or `(0, {})` means the wrong database or an already-cleaned copy — check `.env` before going on. Then prove nothing was orphaned:

```bash
uv run python manage.py shell -c "from courses.models import Blank, FillBlankQuestionElement, ShortTextQuestionElement; print(ShortTextQuestionElement.objects.filter(stem__contains='T34:').count(), FillBlankQuestionElement.objects.filter(stem__contains='T34:').count(), Blank.objects.filter(question__stem__contains='T34:').count())"
```

Expected: `0 0 0`.

- [ ] **Step 1: Remove the `media` link or directory — junction-aware**

From the worktree:

```bash
if [ -L media ]; then MSYS_NO_PATHCONV=1 cmd /c rmdir media; elif [ -d media ]; then rm -rf media; fi
ls -d media 2>/dev/null && echo "media still present - stop" || echo "media gone"
ls C:/Users/krzys/Documents/Python/own/libli/media | head -3
```

⚠️ A junction is removed ONLY with `cmd /c rmdir`: `rm -rf` follows it and deletes the main checkout's `media/` (mat-pp's images). A plain directory (left by a help-screenshot capture) needs `rm -rf`. Expected: "media gone", and the last command still lists files in the main checkout's media.

- [ ] **Step 2: Remove the worktree and the merged branches**

From the main checkout, with no shell's cwd inside the worktree:

```bash
gh pr view feat/analytics-student-order --json state -q .state
gh pr view feat/analytics-student-pages --json state -q .state
```

Expected: `MERGED` twice. **If either is not `MERGED`, stop.** `git branch -d` is not a safety check here: both branches track their pushed upstream, so it deletes them whether or not the PR merged. Then:

```bash
git -C C:/Users/krzys/Documents/Python/own/libli worktree remove C:/Users/krzys/Documents/Python/own/libli-analytics-pages
git -C C:/Users/krzys/Documents/Python/own/libli branch -d feat/analytics-student-order feat/analytics-student-pages
```

`worktree remove` refuses if the tree is dirty (the copied `.env` is ignored and does not block it) or if a process still holds its files.
