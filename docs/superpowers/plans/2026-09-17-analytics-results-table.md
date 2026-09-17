# Analytics results table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Results view of the teacher's student page into a table with per-section sums that equal the analytics grid, name the view in the heading and the back link, make the lesson chip read „lekcje: 1/2", switch the review-waiting wording to „sprawdzenie", and apply one scoring rule (`quiz_score_view`) to every pill and to the student's own results page.

**Architecture:** One PR. `courses/rollups.py` gains `quiz_score_view(row)` (the grid's "this quiz shows a score" rule), which `_quiz_pill` and `build_course_results` use; `build_student_breakdown(..., mode="results")` stamps sums on the pruned tree through a new `_stamp_results` and returns a course `total`. `analytics_student` paints every Results node with the course's colour bands (`_paint_results`), the template renders a `<table class="results-table">` through a recursive `_results_table_rows.html` (Progress keeps its `<ul>`), all CSS goes in `core/static/core/css/app.css`, and the catalogs are regenerated with `--no-obsolete`.

**Tech Stack:** Django 5 templates + views, pytest + pytest-django, BeautifulSoup for rendered-HTML tests, Playwright (sync) for computed-style e2e tests, gettext catalogs (`locale/pl`, `locale/en`).

**Spec:** `docs/superpowers/specs/2026-09-17-analytics-results-table-design.md`

## Global Constraints

- **Read the spec alongside this plan**, by absolute path from the main checkout: `C:/Users/krzys/Documents/Python/own/libli/docs/superpowers/specs/2026-09-17-analytics-results-table-design.md`. This plan lives at `C:/Users/krzys/Documents/Python/own/libli/docs/superpowers/plans/2026-09-17-analytics-results-table.md`. Both exist ONLY on the local, unpushed `docs/analytics-results-table-spec` branch; the worktree below never contains them. Section numbers (§) and test ids (T1…T15) are the spec's.
- **Owner rows are protected.** Nothing in this plan, a review round, or a design pass may change what an O-row in the table below says. A catch that would is raised with the owner as a question, never applied.
- **Test names carry an `rt_` prefix** (`test_rt_t1_…`): `tests/test_analytics_student_page.py` and `tests/test_analytics_student_quiz.py` already hold T1–T41 of two earlier specs, so a bare `test_t5…` would collide in `-k`. Select by NAME, and in a `-k` expression write `test_rt_`, never bare `rt_` — the substring also matches unrelated existing tests (`test_t30_polish_export…`, `test_zero_question_quiz…`, `test_single_part_answer…`, `test_t24c_every_columned_part…`, `test_t33_multi_part_grid…`, `test_t33_multi_part_block…`).
- **Mode vocabulary:** `"progress"` | `"results"`; anything else normalises to `"progress"` via `_drill_params`, never a second rule.
- **One scoring rule.** `rollups.quiz_score_view(row)` is the ONLY place that decides whether a quiz shows a score. `_quiz_pill`, `build_course_results` (the `score_view` key), `_stamp_results` and every template read its result; no caller re-derives `status == "submitted" and max_score > 0`, and nothing reads `row["graded"]` to decide a score (the `awaiting_review` branch of `course_results.html` keeps its `row.graded`, unchanged, spec §4).
- **Results-only keys (spec §2.1).** Container nodes: `quiz_total`, `counted`, `score_sum`, `max_sum`, `percent`, `summary`. Quiz nodes: `shows_score`, `score`, `max_score`, `percent`. The view adds `color`, `text_color` to every node and to `breakdown["total"]`. Progress mode stamps none of these and has no `total` key (O5).
- **Every CSS rule goes in `core/static/core/css/app.css`** — the student page links no page stylesheet. **No stylesheet line citations anywhere** (`tests/test_css_citations_are_durable.py` fails on `<name>.css:<digits>` in `.py/.js/.html/.css`); name the selector instead.
- **Line-count-neutral edits to two cited templates.** `tests/test_title_math_markers.py` cites `_breakdown_node.html` lines :4-13, :6 and :16, and `tests/test_courses_progress.py` cites `_outline_node.html` :3 and :5. Every edit to those two files replaces a line with ONE line.
- **Django template comments:** `{# … #}` is single-line ONLY. Anything spanning lines uses `{% comment %}…{% endcomment %}`.
- **Included templates do not inherit `{% load %}`.** `_results_table_rows.html` loads `i18n courses_extras` itself; `analytics_student.html` adds `courses_extras` for the total row's `|marks`.
- **No `only` on `_results_table_rows.html`'s includes** — it reads `course`, `student`, `drill_qs` from the inherited context.
- **Interface text (spec §5), exact strings:**

  | msgid | pl msgstr | status |
  |---|---|---|
  | `Whole course` | `Cały kurs` | new (Task 5) |
  | `Quiz results` | `Wyniki quizów` | new (Task 5) |
  | `lessons: %(done)s/%(total)s` | `lekcje: %(done)s/%(total)s` | new (Task 6) |
  | `Awaiting review` | `Oczekuje na sprawdzenie` | msgstr changed (Task 6, O13) |
  | `awaiting review` | `oczekuje na sprawdzenie` | msgstr changed (Task 6, O13) |
  | `Submitted for review` | `Przesłano do sprawdzenia` | msgstr changed (Task 6, O13) |
  | `%(n)s question awaiting review (up to 1 more mark)` (plural) | `%(n)s pytanie oczekuje na sprawdzenie (do 1 dodatkowego punktu)` / `%(n)s pytania oczekują na sprawdzenie (do 1 dodatkowego punktu)` / `%(n)s pytań oczekuje na sprawdzenie (do 1 dodatkowego punktu)` | msgstr changed (Task 6, O14) |
  | `%(n)s question awaiting review (up to %(m)s more marks)` (plural) | `%(n)s pytanie oczekuje na sprawdzenie (do %(m)s dodatkowych punktów)` / `%(n)s pytania oczekują na sprawdzenie (do %(m)s dodatkowych punktów)` / `%(n)s pytań oczekuje na sprawdzenie (do %(m)s dodatkowych punktów)` | msgstr changed (Task 6, O14) |
  | `Student results` | — | dropped (Task 5) |
  | `required` | — | dropped (Task 6) |

  Reused, never re-created: `Title`, `Quizzes`, `Score`, `Results`, `Progress`, `Analytics`, `not started`, `in progress`, `submitted`, `Review`, `No quizzes in this course yet`, `scored %(s)s/%(m)s`, `%(s)s / %(m)s marks`. The graded msgids (`Your quiz was graded`, `Quiz graded`, `submitted — not graded`) keep „ocena".
- **Catalog procedure (every task that adds, removes or re-translates a msgid):**
  1. `uv run python manage.py makemessages -l pl -l en --no-obsolete` (`--no-obsolete` drops unused msgids instead of leaving `#~` entries, which `tests/test_i18n_po_health.py::test_no_obsolete_entries` forbids).
  2. For each row of the table above that this task touches (and that is now present in the `.po`): open `locale/pl/LC_MESSAGES/django.po`, **overwrite** the `msgstr` (every `msgstr[i]` of a plural entry) with the table's value unconditionally, and delete any `#, fuzzy` and `#| msgid` lines on that entry — `makemessages` fuzzy-prefills from similar msgids. Leave `locale/en` msgstrs empty (repo convention).
  3. `grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po` → both `0`. (Do not anchor with `$`: the `.po` files are CRLF.)
  4. `uv run python manage.py compilemessages -l pl -l en`
  5. `uv run pytest tests/test_i18n_po_health.py` → PASS.
  6. Commit both `.po` and both `.mo`.
- **Polish in a view test:** set the session key, never `Accept-Language`:
  ```python
  def _polish(client):
      from core.middleware import LANGUAGE_SESSION_KEY

      session = client.session
      session[LANGUAGE_SESSION_KEY] = "pl"
      session.save()
  ```
  In an e2e test set `user.language = "pl"` before the browser logs in (`core.signals` seeds the session from it). Dark mode in e2e is `user.theme = "dark"`, never a cookie.
- **Test mechanics:**
  - Start the test DB once per session: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`.
  - Tools are not on PATH: `uv run pytest …`, `uv run ruff …`, `uv run python manage.py …`.
  - **Never pass `-q`** (addopts already has it; a second one hides the summary).
  - e2e tests need `-m e2e` (addopts deselects them).
  - **Read the pytest summary line, not just the exit code** (exit 0 has been seen with failures).
  - Scope runs to the files a task touches; whole-suite runs are the branch gate only (Task 9), in chunks — a single full run is OOM-killed.
  - Never run tests in two trees at once (they share the test database), and never kill a competing pytest mid-run.
  - Before each commit: `uv run ruff format <every .py file the task touched>`, then `uv run ruff check --no-cache .` and `uv run ruff format --check .`. The plan's code blocks are **not** pre-formatted — the formatter's output wins. A line the formatter cannot break (a long string literal, a long f-string, a long JS string) must be split by hand (implicit string concatenation or a local variable) so E501 (88 columns) passes. Imports are one per line (`force-single-line`).
- **Falsification (every *Mutant* and *A/B*):** apply the mutant **by hand with Edit**, run the one test, observe **red for the stated reason**, revert **by hand with Edit**, then `git diff` to confirm only intended changes remain. **Never `git checkout -- <file>` to revert a mutant** — it destroys the uncommitted implementation. For a `.po` mutant, re-run `compilemessages` after both the edit and the revert.
- **No assertion may rest on database ids** (pks of different models are independent sequences). Compare titles, usernames and rendered text; build expected hrefs with `reverse`/`_expand_qs` from the objects themselves; compare model instances with `==`.
- **Local data is local.** Any design-pass data (Tasks 7 and 9) is created on the LOCAL mat-pp copy only; prod is the source of truth and is never touched. Delete a `Course` through the instance (`c.delete()`), never a queryset delete. A `media` junction is removed ONLY with `cmd /c rmdir`.

## Owner decisions (protected)

Verbatim from spec §0 (2026-09-17). „Proposal" rows are the spec author's, accepted by the owner as written.

| # | Decision | Owner's words |
|---|---|---|
| O1 | The Results view of the student page is a **table**: quiz · quiz count or status · score · % | "it is a lot easier to see results in a table" |
| O2 | A **summary for every section containing more than one quiz** | "summary for each component containing more than 1 quiz" |
| O3 | A summary is **Σ score ÷ Σ max** over that section's quizzes, counting **exactly the quizzes the grid counts** (not started, in progress and awaiting review are left out, never counted as 0) | "Why is it not the same as sum of scores for this section / sum of max?" — confirmed: it is the grid's own rule (`build_results_matrix`) |
| O4 | The **% cells use the grid's colour bands** (the course's `color_bands`) | "yes, colours too" |
| O5 | The **Progress view keeps its current layout** | "progress can stay as it is" |
| O6 | The chapter lesson chip reads **„lekcje: 1/2"** (no grammatical-number forms) | "to avoid gramatic forms: "lekcje: 1/2"" |
| O7 | The **heading names the view**: „Wyniki — Imię Nazwisko" / „Postęp — Imię Nazwisko". No „ucznia", which is wrong for a girl | "is better than "Wyniki ucznia", as in the latter case for a girl it should be "Wyniki uczennicy"" |
| O8 | Proposal: the per-question page's back link names the same view, „← Wyniki" / „← Postęp" | "All good" |
| O9 | The options table's pick marker stays the same for single- and multiple-answer questions | "This is not that important, I can accept the current form." |
| O10 | Options table: **only the icons are coloured**, not the whole row. **Already true in the merged CSS — no change** (§6) | "only the icons coloured would be better than the whole row"; after §6 was shown: "you are right, it is already fine" |
| O11 | **Sums sit on the section's own heading row**, with the course total („Cały kurs") at the top. There are no „Razem" rows underneath | "yes, this is clever" |
| O12 | The **student's course outline** chip reads „lekcje: 1/2" too (one wording for the one shared chip) | "1 yes" |
| O13 | Review-waiting wording uses **„sprawdzanie"**, not „ocena": `Awaiting review` → „Oczekuje na sprawdzenie", `awaiting review` → „oczekuje na sprawdzenie", `Submitted for review` → „Przesłano do sprawdzenia" | "\"Sprawdzanie\" sounds better than \"ocena\"" |
| O14 | The two plural „awaiting review" entries on the student's `quiz_results.html` also use „sprawdzenie" (six Polish forms: „oczekuje/oczekują na sprawdzenie") | "Q4 yes" |
| O15 | The student's own `course_results.html` uses `quiz_score_view`, so a marked REVIEW-only quiz shows its score there too (test mirroring T10b) | "Q5 yes" |
| O16 | Q3 → a heading's score and % are Σ score ÷ Σ max over the section's **marked** quizzes only (the grid's figure); not-started and awaiting-review quizzes are left out, never counted as zero | "1 a" (asked with the example: A marked 8/10, B awaiting review, C not started → (a) „8 / 10 · 80%" vs (b) „8 / 30 · 27%") |
| O17 | Q3 → heading rows **keep** the quiz count „1/3" (quizzes whose score is in the sum / quizzes in the section) | "2. Yes, keep, please" |

## Spec gaps found while planning

The spec body and the O-rows agree everywhere; no O-row needed a tie-break. The gaps below are places where the spec leaves a choice open or where a literal reading would make a named test vacuous; the plan resolves each as stated.

1. **A class-only right-align rule would make T13's `thead` A/B vacuous.** §2.4 gives `results-table__num` cells `text-align:right` without a selector. Written as `.results-table .results-table__num` (0,2,0) it also out-ranks `.results-table thead th` (0,1,2) on „Wynik" and „%", so removing `.results-table thead th.results-table__num` (0,2,2) changes nothing and T13's A/B stays green. Task 7 writes the right-align as `.results-table td.results-table__num` (0,2,1) — body cells only — so the `thead` rule is the one that right-aligns the headers.
2. **T8a's 5-point margin has no fallback.** §7 says the correct build must clear the 30% floor by ≥ 5 points "for this A/B to mean anything" but not what to do if it does not. "The margin" is the measured share minus 0.30. On the **seeded e2e fixture** (`test_rt_t8a_phone_table_fits_and_keeps_the_title_share`, Task 7 Step 4 and Step 6 item 5): if the share is below 35%, run the nowrap A/B anyway; if it goes red, continue and record the margin in the PR body; if it does not go red, **STOP and ask the owner** (the levers that widen the margin — merging or dropping a column — touch O1). On **mat-pp or throwaway pages** (Task 7 Step 5e, Task 9 Step 2d) a share below 35% gets the same nowrap re-measure, but a re-measure that stays at or above 0.30 is **recorded, not a stop**: record the margin in the PR body. If that page has no wrappable pill (no awaiting-review, in-progress, not-started or submitted pill in its status column), the re-measure is skipped and „no pill on page" is recorded instead.
3. **T13d measures the declared border, not the painted winner.** `getComputedStyle` on a cell in a `border-collapse` table reports the cell's own declared `border-bottom` (2px, `--border-strong`), not the result of the collapse. The test pins the rule the spec names; whether the 2px border visibly wins over the next row's 1px `border-top` is judged in Task 9's screenshots.
4. **The builder invariant has no test in §7.** §2.1 requires `rows_by_unit[node.pk]` so a quiz node without a `build_course_results` row raises instead of rendering unscored. Task 3 adds `test_rt_invariant_a_quiz_without_a_row_raises` (monkeypatched builder drops a row; *Mutant:* `if d["node"].pk not in rows_by_unit: continue` → the must-raise test goes red).
5. **T10b's "same figures as its table row" needs the table.** Task 1 pins the header (T10b) and the Progress pill (T10d); Task 5 adds `test_rt_t10b_header_matches_the_table_row` once the table exists.

## File map

- Modify `courses/rollups.py` — add `quiz_score_view`, `_stamp_results`; `_quiz_pill` on the helper; `build_course_results` adds `score_view`; `build_student_breakdown` stamps and returns `total` in Results mode; `_course_results_row`'s `graded` comment corrected (line-count neutral).
- Modify `courses/views_analytics.py` — add `_paint_results`; `analytics_student` paints in Results mode; `analytics_student_quiz` passes `mode`.
- Modify `templates/courses/course_results.html` (O15), `templates/courses/manage/analytics_student.html` (heading, `<title>`, table, empty view), `templates/courses/manage/analytics_student_quiz.html` (back link), `templates/courses/manage/_breakdown_node.html` and `templates/courses/_outline_node.html` (chip, line-count neutral).
- Create `templates/courses/manage/_results_table_rows.html`.
- Modify `core/static/core/css/app.css` — the `.results-table*` block.
- Modify `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`.
- Modify `docs/help/teacher/drill-down.md`, `drill-down.pl.md`, `quiz-review.pl.md`; `core/static/core/img/help/drill-down.{en,pl}.png`, `review-queue.pl.png`.
- Modify `tests/capture_help_screenshots.py`, `tests/capture_title_math_screenshots.py`.
- Modify tests: `tests/test_analytics_rollups.py` (helper unit tests), `tests/test_analytics_student_quiz.py` (T10, T10b, T10d, T27 re-pointed, T37 re-pointed, old t28b retired), `tests/test_courses_views.py` (T15), `tests/test_analytics_student_page.py` (T1–T9, T11; old t6/t7 re-pointed, old t28b retired), `tests/test_title_math_markers.py` (T10c), `tests/test_e2e_analytics_student_pages.py` (T5d, T8a–c, T13–T13d).
- Create `tests/test_review_wording_pl.py` (T14).

## Where to work

This plan and its spec live ONLY on the local `docs/analytics-results-table-spec` branch; switching the main checkout away would remove both from the working tree. Execute in a **separate worktree** and leave the main checkout where it is:

```bash
git -C C:/Users/krzys/Documents/Python/own/libli fetch origin
git -C C:/Users/krzys/Documents/Python/own/libli worktree add C:/Users/krzys/Documents/Python/own/libli-results-table -b feat/analytics-results-table origin/master
```

Then, from the worktree, give it the main checkout's `.env` (gitignored; `config/settings/test.py` pins DEBUG and the vendor flag, so it is safe for tests) and prove the tests will hit the disposable container, not the local server holding mat-pp:

```bash
cp C:/Users/krzys/Documents/Python/own/libli/.env .env
echo "$TEST_DATABASE_URL"
uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test'); django.setup(); from django.conf import settings; print(settings.DATABASES['default']['PORT'])"
```

Expected: the URL ends `127.0.0.1:55433/libli` (the shell profile exports it in every shell; editing `.env` cannot override an exported variable) and the port prints `55433`. **If either differs, stop**: without it the suite creates and drops `test_libli` on the local server.

Run every command of every task from `C:/Users/krzys/Documents/Python/own/libli-results-table`. Confirm `git log --oneline -1` shows `origin/master`'s tip before Task 1 (it was `9b9220ea` when this plan was written; a newer tip is fine).

---

### Task 1: One scoring rule — `quiz_score_view`, and `_quiz_pill` on it

**Files:**
- Modify: `courses/rollups.py` (`_course_results_row` comment, new `quiz_score_view`, `_quiz_pill`)
- Test: `tests/test_analytics_rollups.py` (helper unit test), `tests/test_analytics_student_quiz.py` (T10b, T10d; `test_t27_…` re-pointed)

**Interfaces:**
- Consumes: a `_course_results_row` dict (`status`, `score`, `max_score`, `submission_pk`, …); `rollups._pct(a, b)`.
- Produces: `quiz_score_view(row) -> {"shows_score": bool, "score": Decimal, "max_score": Decimal, "percent": int | None}`; `_quiz_pill(row)` unchanged signature, returns `{"kind": "scored", "score", "max_score", "percent", "submission_pk"}` **iff** `quiz_score_view(row)["shows_score"]`.

**Implements:** O3, O16 (the grid's counting rule, marked quizzes only), and the pill half of spec §4 that O15 builds on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_rollups.py`:

```python
# --- results-table spec §4: the ONE "this quiz shows a score" rule ---------------
def _score_row(status, score=None, max_score=None, graded=False):
    """A _course_results_row-shaped dict; only the keys quiz_score_view reads matter."""
    return {
        "unit": None,
        "status": status,
        "graded": graded,
        "score": None if score is None else Decimal(score),
        "max_score": None if max_score is None else Decimal(max_score),
        "pending": status == "awaiting_review",
        "submission_pk": None,
        "url_name": "courses:quiz_results",
    }


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_score_row("not_started"), (False, Decimal("0"), Decimal("0"), None)),
        (_score_row("in_progress"), (False, Decimal("0"), Decimal("0"), None)),
        (
            _score_row("awaiting_review", "3", "5", graded=True),
            (False, Decimal("3"), Decimal("5"), None),
        ),
        (_score_row("submitted", "0", "0"), (False, Decimal("0"), Decimal("0"), None)),
        (
            _score_row("submitted", "8", "10", graded=True),
            (True, Decimal("8"), Decimal("10"), 80),
        ),
        # A REVIEW-only quiz, fully reviewed: graded is False, the grid counts it.
        (
            _score_row("submitted", "4", "5", graded=False),
            (True, Decimal("4"), Decimal("5"), 80),
        ),
        # A NULL score is coerced to 0, exactly as the grid does.
        (_score_row("submitted", None, "5"), (True, Decimal("0"), Decimal("5"), 0)),
    ],
)
def test_rt_quiz_score_view_is_the_grids_rule(row, expected):
    from courses.rollups import quiz_score_view

    view = quiz_score_view(row)
    assert set(view) == {"shows_score", "score", "max_score", "percent"}
    got = (view["shows_score"], view["score"], view["max_score"], view["percent"])
    assert got == expected
    assert isinstance(view["score"], Decimal)
    assert isinstance(view["max_score"], Decimal)
```

In `tests/test_analytics_student_quiz.py`, replace this block inside `test_t27_header_pill_matches_the_breakdown_pill_except_scored`:

```python
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
    assert (
        _breakdown_pill(breakdown, "Q scored").get_text(" ", strip=True)
        == "scored 1/5 (20%)"
    )
    assert (
        status.select_one(".answers__score").get_text(" ", strip=True) == "1 / 5 marks"
    )
```

with:

```python
    # (1) parity for every kind that still renders a pill. `reviewed` (REVIEW-only,
    # fully reviewed, max_score 1) is SCORED since the results-table spec §4, which
    # deliberately overrides the student-pages spec §2.8: it is in part (2) now.
    for quiz, kind in (
        (ungraded, "pill--submitted"),
        (awaiting, "pill--awaiting"),
        (live, "pill--progress"),
    ):
        header = _status(client, course, pupil, quiz).select_one(".pill")
        row = _breakdown_pill(breakdown, quiz.title)
        assert kind in header["class"], quiz.title
        assert header["class"] == row["class"], quiz.title
        assert header.get_text(" ", strip=True) == row.get_text(" ", strip=True)
    # (2) scored: no header pill; the breakdown keeps its pill, same numbers
    for quiz, marks, pill_text in (
        (scored, "1 / 5 marks", "scored 1/5 (20%)"),
        (reviewed, "1 / 1 marks", "scored 1/1 (100%)"),
    ):
        status = _status(client, course, pupil, quiz)
        assert status.select_one(".pill") is None, quiz.title
        assert (
            _breakdown_pill(breakdown, quiz.title).get_text(" ", strip=True)
            == pill_text
        )
        assert status.select_one(".answers__score").get_text(" ", strip=True) == marks
```

Then add, directly after `test_t27_header_pill_matches_the_breakdown_pill_except_scored` (before `test_t28_heading_is_name_then_title`):

```python
def test_rt_t10b_reviewed_review_only_header_shows_its_score(client):
    """results-table spec T10b: a fully reviewed REVIEW-only quiz with max_score > 0
    is scored in the per-question header (no pill), in Polish."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    status = _status(client, course, pupil, reviewed)
    assert status.select_one(".pill") is None
    assert status.select_one(".answers__score").get_text(" ", strip=True) == (
        "1 / 1 pkt"
    )
    assert status.select_one(".answers__percent").get_text(strip=True) == "100%"


def test_rt_t10d_reviewed_review_only_progress_pill_is_scored(client):
    """results-table spec T10d: the same quiz in PROGRESS mode renders the scored
    pill, not „przesłano"."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    soup = _soup(client.get(f"{page}?mode=progress"))
    pill = _breakdown_pill(soup, reviewed.title)
    assert "pill--scored" in pill["class"]
    assert pill.get_text(" ", strip=True) == "wynik 1/1 (100%)"
```

- [ ] **Step 2: Run them — expect RED**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run pytest tests/test_analytics_rollups.py tests/test_analytics_student_quiz.py -k "test_rt_ or t27 or t26"
```

Expected: `test_rt_quiz_score_view_is_the_grids_rule` fails with `ImportError` (no `quiz_score_view`); `test_rt_t10b_…` fails on `status.select_one(".pill") is None` (today's `_quiz_pill` returns `submitted` because `graded` is False); `test_rt_t10d_…` fails on `"pill--scored" in pill["class"]`; `test_t27_…` fails on `status.select_one(".pill") is None` for `Q reviewed`. `test_t26_header_by_pill_kind` passes (it never asserts `reviewed`).

- [ ] **Step 3: Correct the misleading `graded` comment (line-count neutral)**

In `courses/rollups.py`, replace:

```python
    graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0 (max_marks >= 0.01)
```

with:

```python
    graded = has_auto.get(unit.pk, False)  # top-level AUTO question, NOT max_score > 0
```

- [ ] **Step 4: Add `quiz_score_view` and put `_quiz_pill` on it**

In `courses/rollups.py`, replace the whole `_quiz_pill` function:

```python
def _quiz_pill(row):
    """Map a build_course_results row to a single-sourced status pill (spec §6).
    Every kind that has a submission carries its pk: the breakdown links the
    quiz title to the per-question page with it."""
    status = row["status"]
    if status == "submitted":
        if row["graded"] and row["max_score"]:
            # reuse the single-source percent rule (_pct guarantees b > 0, met here)
            return {
                "kind": "scored",
                "score": row["score"],
                "max_score": row["max_score"],
                "percent": _pct(row["score"], row["max_score"]),
                "submission_pk": row["submission_pk"],
            }
        # submitted but ungraded (max_score == 0): no percent
        return {"kind": "submitted", "submission_pk": row["submission_pk"]}
```

with:

```python
def quiz_score_view(row):
    """The grid's "this quiz shows a score" rule for one _course_results_row row.

    build_results_matrix sums a submission iff submission_is_counted, and a cell
    shows a figure iff its max_score sum is > 0; for ONE quiz that is `status ==
    "submitted"` (already not pending) and `max_score > 0`. It deliberately ignores
    `graded` (a top-level AUTO question): a fully reviewed REVIEW-only quiz with
    max_score > 0 is in the grid's sums, so it shows a score everywhere too
    (results-table spec §4). _quiz_pill, build_course_results' `score_view` and
    the Results-mode stamps all read THIS; never re-derive it.

    score/max_score are always Decimal (a NULL is 0, as in the grid); percent is
    None unless shows_score.
    """
    score = row["score"] or Decimal("0")
    max_score = row["max_score"] or Decimal("0")
    shows_score = row["status"] == "submitted" and max_score > 0
    return {
        "shows_score": shows_score,
        "score": score,
        "max_score": max_score,
        "percent": _pct(score, max_score) if shows_score else None,
    }


def _quiz_pill(row):
    """Map a build_course_results row to a single-sourced status pill (spec §6).
    Every kind that has a submission carries its pk: the breakdown links the
    quiz title to the per-question page with it. `scored` iff quiz_score_view
    says the quiz shows a score (results-table spec §4)."""
    status = row["status"]
    if status == "submitted":
        view = quiz_score_view(row)
        if view["shows_score"]:
            return {
                "kind": "scored",
                "score": view["score"],
                "max_score": view["max_score"],
                "percent": view["percent"],
                "submission_pk": row["submission_pk"],
            }
        # submitted, but no gradeable marks (max_score == 0): no percent
        return {"kind": "submitted", "submission_pk": row["submission_pk"]}
```

(The `awaiting_review`, `in_progress` and `not_started` branches below it stay as they are.)

- [ ] **Step 5: Run — expect GREEN**

```bash
uv run pytest tests/test_analytics_rollups.py tests/test_analytics_student_quiz.py tests/test_analytics_student_page.py tests/test_courses_rollups.py
```

Expected: all pass. `test_build_student_breakdown_pills` still sees the exact scored dict (`Decimal("9")` equals the coerced value), `test_unreviewed_review_multigrid_pills_awaiting_then_submitted` still sees `submitted` (its stored `max_score` stays 0).

- [ ] **Step 6: Falsify**

1. *Mutant (spec T1b/T10b/T10d):* in `quiz_score_view`, change `shows_score = row["status"] == "submitted" and max_score > 0` to `shows_score = row["status"] == "submitted" and row["graded"] and max_score > 0`. Run `uv run pytest tests/test_analytics_rollups.py tests/test_analytics_student_quiz.py -k "test_rt_"` → red: the REVIEW-only parametrize case, `test_rt_t10b_…` (a pill is rendered) and `test_rt_t10d_…` (`pill--submitted`). Revert by hand.
2. *Mutant (spec T10b/T10d, "keep the old condition"):* in `_quiz_pill`, change `if view["shows_score"]:` to `if row["graded"] and row["max_score"]:`. Run `uv run pytest tests/test_analytics_student_quiz.py -k "test_rt_t10 or t27"` → red on `test_rt_t10b_…`, `test_rt_t10d_…` and `test_t27_…`. Revert by hand.
3. *Mutant (always-Decimal):* in `quiz_score_view`, change `score = row["score"] or Decimal("0")` to `score = row["score"]`. Run `uv run pytest tests/test_analytics_rollups.py -k test_rt_quiz_score_view_is_the_grids_rule` → red (the `not_started` case gets `None`). Revert by hand.

`git diff` shows only Steps 1, 3 and 4.

- [ ] **Step 7: Ruff and commit**

```bash
uv run ruff format courses/rollups.py tests/test_analytics_rollups.py tests/test_analytics_student_quiz.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/rollups.py tests/test_analytics_rollups.py tests/test_analytics_student_quiz.py
git commit -m "feat(analytics): one scoring rule, quiz_score_view, behind every quiz pill"
```

### Task 2: The student's own results page follows the rule (O15)

**Files:**
- Modify: `courses/rollups.py` (`build_course_results`), `templates/courses/course_results.html`
- Test: `tests/test_courses_views.py` (T15)

**Interfaces:**
- Consumes: `quiz_score_view(row)` (Task 1).
- Produces: every `build_course_results(...)["rows"][i]` gains `score_view` = `quiz_score_view(row)`.

**Implements:** O15.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_courses_views.py`:

```python
# ---------------------------------------------------------------------------
# results-table spec T15 (O15): the student's own course results page
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rt_t15_course_results_scores_a_reviewed_review_only_quiz(client):
    from django.utils import timezone

    from core.middleware import LANGUAGE_SESSION_KEY
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from courses.models import QuestionResponse

    course = CourseFactory()
    user = make_login(client, "t15stud")
    EnrollmentFactory(student=user, course=course)
    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()
    reviewed = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Esej"
    )
    essay = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    element = Element.objects.create(unit=reviewed, content_object=essay)
    sub = QuizSubmissionFactory(
        student=user,
        unit=reviewed,
        status="submitted",
        score=Decimal("4.00"),
        max_score=Decimal("5.00"),
    )
    QuestionResponse.objects.create(
        submission=sub,
        element=element,
        earned_marks=Decimal("4.00"),
        fraction=Decimal("0.8000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    no_marks = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Bez punktow"
    )
    QuizSubmissionFactory(
        student=user,
        unit=no_marks,
        status="submitted",
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )
    soup = BeautifulSoup(
        client.get(f"/courses/{course.slug}/results/").content.decode(),
        "html.parser",
    )
    rows = {
        row.select_one(".result-row__title").get_text(strip=True): row
        for row in soup.select("li.result-row")
    }
    essay_row = rows["Esej"]
    assert essay_row.select_one(".result-row__score").get_text(" ", strip=True) == (
        "4 / 5"
    )
    assert essay_row.select_one(".badge--muted") is None
    assert rows["Bez punktow"].select_one(".result-row__score") is None
    assert rows["Bez punktow"].select_one(".badge--muted").get_text(strip=True) == (
        "przesłano — bez oceny"
    )
```

- [ ] **Step 2: Run it — expect RED**

Run: `uv run pytest tests/test_courses_views.py -k test_rt_t15`

Expected: FAIL — `essay_row.select_one(".result-row__score")` is `None` (the template branches on `row.graded`, False for a REVIEW-only quiz), so `.get_text` raises `AttributeError`.

- [ ] **Step 3: Give every row its score view**

In `courses/rollups.py` (`build_course_results`), replace:

```python
        row = _course_results_row(unit, sub, has_auto, total_review, reviewed_counts)
        rows.append(row)
```

with:

```python
        row = _course_results_row(unit, sub, has_auto, total_review, reviewed_counts)
        row["score_view"] = quiz_score_view(row)  # results-table spec §4, O15
        rows.append(row)
```

- [ ] **Step 4: Branch the template on it**

In `templates/courses/course_results.html`, replace:

```django
        {% if row.graded %}<span class="result-row__score">{{ row.score|marks }} / {{ row.max_score|marks }}</span>
        {% else %}<span class="badge badge--muted">{% trans "submitted — not graded" %}</span>{% endif %}
```

with:

```django
        {% if row.score_view.shows_score %}<span class="result-row__score">{{ row.score_view.score|marks }} / {{ row.score_view.max_score|marks }}</span>
        {% else %}<span class="badge badge--muted">{% trans "submitted — not graded" %}</span>{% endif %}
```

The `awaiting_review` branch (`{% if row.graded %}` before the `Awaiting review` badge) stays exactly as it is (spec §4).

- [ ] **Step 5: Run — expect GREEN**

Run: `uv run pytest tests/test_courses_views.py tests/test_courses_rollups.py tests/test_i18n_results.py tests/test_consumption_pages.py tests/test_title_math_markers.py -k "course_results or test_rt_t15 or build_course_results or awaiting or graded"`

Expected: all selected tests pass (`test_course_results_enrolled_renders_rows_and_drilldown` still shows „8 / 10").

- [ ] **Step 6: Falsify**

*Mutant (spec T15):* in `course_results.html`, change `{% if row.score_view.shows_score %}` back to `{% if row.graded %}`. Run `uv run pytest tests/test_courses_views.py -k test_rt_t15_course_results_scores_a_reviewed_review_only_quiz` → red (`AttributeError` on the missing score). Revert by hand; `git diff` shows only Steps 3–4 and the test.

- [ ] **Step 7: Ruff and commit**

```bash
uv run ruff format courses/rollups.py tests/test_courses_views.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/rollups.py templates/courses/course_results.html tests/test_courses_views.py
git commit -m "feat(results): the student's course results use quiz_score_view (O15)"
```

### Task 3: The builder stamps Results-mode sums and a course total

**Files:**
- Modify: `courses/rollups.py` (`build_student_breakdown`, new `_stamp_results` after `_keep_quizzes`)
- Test: `tests/test_analytics_student_page.py` (T1, T1b, T1c, T2, T3, T4, T5, T7 data halves; builder invariant)

**Interfaces:**
- Consumes: `quiz_score_view(row)` (Task 1); `_keep_quizzes(nodes)`; `_pct`.
- Produces: `_stamp_results(nodes, rows_by_unit) -> {"quiz_total": int, "counted": int, "score_sum": Decimal, "max_sum": Decimal, "percent": int | None, "summary": bool}`, stamping quiz nodes with `quiz_score_view`'s four keys and container nodes with these six. `build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress")` returns `{"student", "tree"}` in Progress mode (unchanged) and `{"student", "tree", "total"}` in Results mode.

**Implements:** O2, O3, O11 (the total's data), O16, O17, O5 (Progress stamps nothing).

- [ ] **Step 1: Write the failing tests**

In `tests/test_analytics_student_page.py`, replace the import lines:

```python
from django.urls import reverse

from courses import rollups
from courses.models import QuizSubmission
from courses.rollups import build_student_breakdown
from courses.views_analytics import _expand_qs
```

with:

```python
from django.urls import reverse
from django.utils import timezone

from courses import rollups
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rollups import _fmt_mark
from courses.rollups import build_results_matrix
from courses.rollups import build_student_breakdown
from courses.views_analytics import _expand_qs
from courses.views_analytics import _with_data_for
```

and replace the module docstring `"""The student results page (spec §4; T6-T13, T15, T16, T28b)."""` with:

```python
"""The teacher's student page. Two specs' ids live here: test_t6…test_t28b are the
student-pages spec's (2026-09-16); test_rt_* are the results-table spec's
(2026-09-17). Select by NAME."""
```

Append to the end of the file:

```python
# --- results-table spec (2026-09-17): Results-mode sums ---------------------------
def _auto(quiz, max_marks):
    question = ShortTextQuestionElement.objects.create(
        stem="<p>Q</p>", accepted="a", max_marks=Decimal(max_marks)
    )
    return Element.objects.create(unit=quiz, content_object=question)


def _review(quiz, max_marks):
    question = ExtendedResponseQuestionElement.objects.create(
        stem="<p>E</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=quiz, content_object=question)


def _sub(student, quiz, score, max_score):
    return QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal(score),
        max_score=Decimal(max_score),
    )


def _quiz(course, parent, title, **kw):
    return _node(course, parent, "unit", title, unit_type="quiz", **kw)


def _student_path(course, student):
    return reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )


def _results_fixture(client):
    """One student, three root chapters (spec §7 T1-T6):

    Rozdział A (d0)          2/7   12/15   80%
      Sekcja A1 (d1)         2/5   12/15   80%
        A1 oceniony          8/10 (AUTO)
        A1 sprawdzony        4/5  (REVIEW-only, fully reviewed: T1b)
        A1 do sprawdzenia    awaiting review, stored 3/5 -- never counted
        A1 w toku            in progress
        A1 nierozpoczęty     not started
      Lekcja A               a lesson: pruned
      Sekcja A2 (d1)         0/2   no counted quiz (T1c)
        A2 nierozpoczęty, A2 do sprawdzenia
    Rozdział B (d0)          1/2   16.5/22  75%
      B połowa               16.5/22
      B bez punktów          submitted, max_score 0 (T5)
    Rozdział C (d0)          one quiz: a percent, no summary (T2)
      Sekcja C1 (d1)
        C1 jedyny            3/4
    Whole course             4/10  31.5/41  77%
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory(
        first_name="Anna", last_name="Nowak", display_name="Anna Nowak"
    )
    EnrollmentFactory(student=student, course=course)
    a = _node(course, None, "chapter", "Rozdział A")
    a1 = _node(course, a, "section", "Sekcja A1")
    marked = _quiz(course, a1, "A1 oceniony")
    _auto(marked, "10")
    _sub(student, marked, "8", "10")
    reviewed = _quiz(course, a1, "A1 sprawdzony")
    essay = _review(reviewed, "5")
    QuestionResponse.objects.create(
        submission=_sub(student, reviewed, "4", "5"),
        element=essay,
        latest_answer="esej",
        attempt_count=1,
        locked=True,
        earned_marks=Decimal("4"),
        fraction=Decimal("0.8"),
        reviewed_at=timezone.now(),
    )
    awaiting = _quiz(course, a1, "A1 do sprawdzenia")
    _review(awaiting, "5")
    _sub(student, awaiting, "3", "5")
    live = _quiz(course, a1, "A1 w toku")
    _auto(live, "5")
    QuizSubmission.objects.create(
        student=student, unit=live, status=QuizSubmission.Status.IN_PROGRESS
    )
    _auto(_quiz(course, a1, "A1 nierozpoczęty"), "5")
    _node(course, a, "unit", "Lekcja A", unit_type="lesson", obligatory=True)
    a2 = _node(course, a, "section", "Sekcja A2")
    _auto(_quiz(course, a2, "A2 nierozpoczęty"), "2")
    pending = _quiz(course, a2, "A2 do sprawdzenia")
    _review(pending, "2")
    _sub(student, pending, "0", "0")
    b = _node(course, None, "chapter", "Rozdział B")
    half = _quiz(course, b, "B połowa")
    _auto(half, "22")
    _sub(student, half, "16.5", "22")
    _sub(student, _quiz(course, b, "B bez punktów"), "0", "0")
    c = _node(course, None, "chapter", "Rozdział C")
    c1 = _node(course, c, "section", "Sekcja C1")
    single = _quiz(course, c1, "C1 jedyny")
    _auto(single, "4")
    _sub(student, single, "3", "4")
    return course, student, _student_path(course, student)


def _grid(course, student, expand=()):
    """The matrix exactly as analytics_matrix builds it in Results + raw mode."""
    return build_results_matrix(
        course,
        [student],
        {node.pk for node in expand},
        "raw",
        drafts="keep-with-data",
        with_data=_with_data_for(course),
    )


def _grid_cell(course, student, node, expand=()):
    matrix = _grid(course, student, expand)
    cells = matrix["rows"][0]["cells"]
    for column, cell in zip(matrix["columns"], cells, strict=True):
        if column["node"] == node:
            return cell
    raise AssertionError(f"no grid column for {node.title!r}")


def _label(d):
    return f"{_fmt_mark(d['score_sum'])}/{_fmt_mark(d['max_sum'])}"


def _results(client, path):
    resp, soup = _get(client, f"{path}?mode=results")
    return resp.context["breakdown"], soup


def _all_nodes(tree):
    for d in tree:
        yield d
        yield from _all_nodes(d["children"])


def test_rt_t1_results_summaries_equal_the_grid(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    chapter_a = _find(tree, "Rozdział A")
    a1, a2 = _find(tree, "Sekcja A1"), _find(tree, "Sekcja A2")
    # Both branches below run: a summary heading with a counted quiz, one without.
    assert a1["summary"] and a1["counted"] > 0
    assert a2["summary"] and a2["counted"] == 0
    cases = (
        (chapter_a, ()),  # top-level
        (_find(tree, "Rozdział B"), ()),  # top-level
        # Nested: expand the ANCESTOR, never the section itself -- an expanded
        # node becomes a spanning header with no cell.
        (a1, (chapter_a["node"],)),
        (a2, (chapter_a["node"],)),
    )
    for d, ancestors in cases:
        title = d["node"].title
        cell = _grid_cell(course, student, d["node"], ancestors)
        if d["counted"] == 0:
            assert cell["percent"] is None and cell["label"] == "—", title
            assert d["percent"] is None, title
        else:
            assert d["percent"] == cell["percent"], title
            assert _label(d) == cell["label"], title


def test_rt_t1b_a_reviewed_review_only_quiz_is_scored_and_summed(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    quiz = _find(tree, "A1 sprawdzony")
    got = (quiz["shows_score"], quiz["score"], quiz["max_score"], quiz["percent"])
    assert got == (True, Decimal("4"), Decimal("5"), 80)
    a1 = _find(tree, "Sekcja A1")
    assert _label(a1) == "12/15"
    ancestors = (_find(tree, "Rozdział A")["node"],)
    assert _grid_cell(course, student, a1["node"], ancestors)["label"] == "12/15"


def test_rt_t1c_a_summary_with_no_counted_quiz_has_no_percent(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    a2 = _find(breakdown["tree"], "Sekcja A2")
    assert (a2["quiz_total"], a2["counted"], a2["summary"]) == (2, 0, True)
    assert (a2["score_sum"], a2["max_sum"], a2["percent"]) == (0, 0, None)
    assert isinstance(a2["score_sum"], Decimal)
    assert isinstance(a2["max_sum"], Decimal)


def _uncounted_course(client):
    """Two quizzes, neither started: the course total has no counted quiz."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    _auto(_quiz(course, chapter, "Pierwszy"), "1")
    _auto(_quiz(course, chapter, "Drugi"), "1")
    return _student_path(course, student)


def test_rt_t1c_a_course_total_with_no_counted_quiz_has_no_percent(client):
    breakdown, _soup = _results(client, _uncounted_course(client))
    total = breakdown["total"]
    assert (total["quiz_total"], total["counted"], total["summary"]) == (2, 0, True)
    assert (total["score_sum"], total["max_sum"], total["percent"]) == (0, 0, None)
    assert isinstance(total["score_sum"], Decimal)


def test_rt_t2_a_one_quiz_section_has_a_percent_but_no_summary(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    for title in ("Sekcja C1", "Rozdział C"):
        d = _find(breakdown["tree"], title)
        assert (d["quiz_total"], d["percent"], d["summary"]) == (1, 75, False), title


def test_rt_t3_course_total_equals_the_grids_overall(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    total = breakdown["total"]
    overall = _grid(course, student)["rows"][0]["overall"]
    assert (total["quiz_total"], total["counted"], total["summary"]) == (10, 4, True)
    assert total["percent"] == overall["percent"]
    assert _label(total) == overall["label"]


def _one_quiz_course(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    quiz = _quiz(course, _node(course, None, "chapter", "Rozdział"), "Jedyny")
    _auto(quiz, "2")
    _sub(student, quiz, "1", "2")
    return _student_path(course, student)


def test_rt_t3_a_one_quiz_course_has_no_total_summary(client):
    breakdown, _soup = _results(client, _one_quiz_course(client))
    assert breakdown["total"]["quiz_total"] == 1
    assert breakdown["total"]["summary"] is False


def _drafts_fixture(client):
    """Spec T4. Data is COURSE-wide (_with_data_for): 'Szkic bez danych' has none
    from any student; 'Szkic cudzy' has data from ANOTHER student only."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student, other = UserFactory(), UserFactory()
    for pupil in (student, other):
        EnrollmentFactory(student=pupil, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    live = _quiz(course, chapter, "Opublikowany")
    _auto(live, "4")
    _sub(student, live, "2", "4")
    kept = _quiz(course, chapter, "Szkic z danymi", published=False)
    _auto(kept, "4")
    _sub(student, kept, "3", "4")
    _auto(_quiz(course, chapter, "Szkic bez danych", published=False), "4")
    theirs = _quiz(course, chapter, "Szkic cudzy", published=False)
    _auto(theirs, "4")
    _sub(other, theirs, "4", "4")
    return course, student, chapter, _student_path(course, student)


def test_rt_t4_drafts_are_the_grids_drafts(client):
    course, student, chapter, path = _drafts_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    heading = _find(tree, "Rozdział")
    # A draft WITH data counts on both pages: its 3/4 is inside 5/8.
    cell = _grid_cell(course, student, chapter)
    assert heading["percent"] == cell["percent"]
    assert _label(heading) == cell["label"] == "5/8"
    # A draft with no data from ANY student has no row and no share of quiz_total.
    assert _find(tree, "Szkic bez danych") is None
    assert heading["quiz_total"] == 3
    # A draft only ANOTHER student attempted is on this page, not started.
    assert _find(tree, "Szkic cudzy")["pill"] == {"kind": "not_started"}


def test_rt_t5_a_zero_max_quiz_is_in_quiz_total_not_in_counted(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    b = _find(breakdown["tree"], "Rozdział B")
    assert (b["quiz_total"], b["counted"]) == (2, 1)
    assert _find(breakdown["tree"], "B bez punktów")["shows_score"] is False


RESULTS_ONLY_KEYS = frozenset(
    {
        "quiz_total",
        "counted",
        "score_sum",
        "max_sum",
        "percent",
        "summary",
        "shows_score",
        "score",
        "max_score",
        "color",
        "text_color",
    }
)


def test_rt_t7_progress_mode_carries_no_results_keys(client):
    """Each node dict's OWN top-level keys, walked through `children` only -- never
    inside `pill`: a scored Progress pill legitimately carries `percent`."""
    _course, _student, path = _results_fixture(client)
    resp, _soup = _get(client, f"{path}?mode=progress")
    breakdown = resp.context["breakdown"]
    assert "total" not in breakdown
    nodes = list(_all_nodes(breakdown["tree"]))
    assert any((d.get("pill") or {}).get("kind") == "scored" for d in nodes)
    for d in nodes:
        leaked = sorted(RESULTS_ONLY_KEYS & set(d))
        assert not leaked, (d["node"].title, leaked)


def test_rt_invariant_a_quiz_without_a_row_raises(monkeypatch):
    """Spec §2.1: the pruned tree's quiz nodes ARE build_course_results's rows, so a
    missing row is a bug and must raise, never render an unscored quiz."""
    course = CourseFactory()
    _quiz(course, _node(course, None, "chapter", "Rozdział"), "Quiz")
    real = rollups.build_course_results

    def without_rows(*args, **kwargs):
        results = real(*args, **kwargs)
        results["rows"] = []
        return results

    monkeypatch.setattr(rollups, "build_course_results", without_rows)
    with pytest.raises(KeyError):
        build_student_breakdown(course, UserFactory(), drafts="keep", mode="results")
```

- [ ] **Step 2: Run them — expect RED (except T7)**

Run: `uv run pytest tests/test_analytics_student_page.py -k "test_rt_"`

Expected: every `test_rt_t1…t5` fails with `KeyError` (`summary`, `total`, `shows_score` … are not stamped); `test_rt_invariant_…` fails with `DID NOT RAISE`. `test_rt_t7_progress_mode_carries_no_results_keys` **passes already** — it guards what this task must not break; Step 6 falsifies it.

- [ ] **Step 3: Add `_stamp_results`**

In `courses/rollups.py`, replace the tail of `_keep_quizzes`:

```python
        d["children"] = _keep_quizzes(d["children"])
        if d["children"]:
            kept.append(d)
    return kept
```

with:

```python
        d["children"] = _keep_quizzes(d["children"])
        if d["children"]:
            kept.append(d)
    return kept


def _stamp_results(nodes, rows_by_unit):
    """Results-mode figures (results-table spec §2.1), stamped IN PLACE on a tree
    _keep_quizzes has pruned, so every unit left is a quiz.

    A quiz node gets quiz_score_view's four keys for ITS build_course_results
    row. A container gets quiz_total (quizzes below), counted (those with
    shows_score), score_sum/max_sum (Decimal, 0 when nothing counts), percent
    (_pct when max_sum > 0, else None -- the grid's own cell rule, so a heading
    equals its grid cell by construction) and summary (quiz_total > 1, O2).
    Returns the same six figures for `nodes` taken together: the course total
    when `nodes` is the whole tree.

    rows_by_unit[...] and never .get(): both sides apply is_quiz_unit with the
    same drafts/with_data, so a quiz without a row is a bug and must raise.
    """
    quiz_total = counted = 0
    score_sum = max_sum = Decimal("0")
    for d in nodes:
        if d["is_unit"]:
            d.update(quiz_score_view(rows_by_unit[d["node"].pk]))
            quiz_total += 1
            if d["shows_score"]:
                counted += 1
                score_sum += d["score"]
                max_sum += d["max_score"]
        else:
            figures = _stamp_results(d["children"], rows_by_unit)
            d.update(figures)
            quiz_total += figures["quiz_total"]
            counted += figures["counted"]
            score_sum += figures["score_sum"]
            max_sum += figures["max_sum"]
    return {
        "quiz_total": quiz_total,
        "counted": counted,
        "score_sum": score_sum,
        "max_sum": max_sum,
        "percent": _pct(score_sum, max_sum) if max_sum > 0 else None,
        "summary": quiz_total > 1,
    }
```

- [ ] **Step 4: Stamp in Results mode only**

In `courses/rollups.py` (`build_student_breakdown`), replace:

```python
    mode="results" returns the tree already pruned to quizzes (analytics student
    pages spec §4.1). The default keeps every existing caller's tree unchanged.
    """
```

with:

```python
    mode="results" returns the tree already pruned to quizzes (analytics student
    pages spec §4.1), stamped by _stamp_results, plus the course `total`
    (results-table spec §2.1). The default keeps every existing caller's tree
    unchanged and stamps NOTHING (O5).
    """
```

and replace:

```python
    attach(tree)
    if mode == "results":
        tree = _keep_quizzes(tree)
    return {"student": student, "tree": tree}
```

with:

```python
    attach(tree)
    if mode != "results":
        return {"student": student, "tree": tree}
    tree = _keep_quizzes(tree)
    rows_by_unit = {r["unit"].pk: r for r in results["rows"]}
    total = _stamp_results(tree, rows_by_unit)
    return {"student": student, "tree": tree, "total": total}
```

- [ ] **Step 5: Run — expect GREEN**

```bash
uv run pytest tests/test_analytics_student_page.py tests/test_analytics_rollups.py tests/test_publish_analytics.py tests/test_title_math_assets.py
```

Expected: all pass (the templates ignore the new keys until Task 5).

- [ ] **Step 6: Falsify**

Run each mutant with `uv run pytest tests/test_analytics_student_page.py -k "<full test names>"`, observe red for the stated reason, revert by hand. Pass the FULL function names, never the short ids (a short id such as `rt_t1b` or `rt_t7` also matches Task 5's tests in the same file):

| Item | `-k` |
|---|---|
| 1 | `test_rt_t1_results_summaries_equal_the_grid` |
| 2 | `"test_rt_t1b_a_reviewed_review_only_quiz_is_scored_and_summed or test_rt_t1_results_summaries_equal_the_grid"` |
| 3 | `"test_rt_t2_a_one_quiz_section_has_a_percent_but_no_summary or test_rt_t3_a_one_quiz_course_has_no_total_summary"` |
| 4 | `test_rt_t3_a_one_quiz_course_has_no_total_summary` |
| 5, 6 | `test_rt_t4_drafts_are_the_grids_drafts` |
| 7 | `test_rt_t5_a_zero_max_quiz_is_in_quiz_total_not_in_counted` |
| 8, 9 | `test_rt_t7_progress_mode_carries_no_results_keys` |
| 10 | `test_rt_invariant_a_quiz_without_a_row_raises` |

1. *Mutant (spec T1, "count awaiting-review scores"):* in `quiz_score_view`, change `row["status"] == "submitted"` to `row["status"] in ("submitted", "awaiting_review")`. → `rt_t1` red: Sekcja A1 becomes 15/20 · 75% against the grid's 12/15 · 80%. Revert.
2. *Mutant (spec T1b):* in `quiz_score_view`, add `row["graded"] and` to the `shows_score` condition. → `rt_t1b` red (`shows_score` False) and `rt_t1` red on Sekcja A1's label (8/10 against 12/15, same 80%). Revert.
3. *Mutant (spec T2):* in `_stamp_results`, `"summary": quiz_total > 1` → `"summary": quiz_total >= 1`. → `rt_t2` red (`summary` True) and `rt_t3_a_one_quiz…` red. Revert.
4. *Mutant (spec T3):* in `build_student_breakdown`, insert `total["summary"] = total["quiz_total"] >= 1` just before the Results `return`. → `rt_t3_a_one_quiz_course_has_no_total_summary` red. Revert.
5. *Mutant (spec T4, drafts hidden):* in `courses/views_analytics.py::analytics_student`, change `drafts="keep-with-data"` to `drafts="hide"` in the `build_student_breakdown` call. → `rt_t4` red (Rozdział is 2/4 · 50% against the grid's 5/8). Revert.
6. *Mutant (spec T4, drafts kept):* same call, `drafts="keep"`. → `rt_t4` red on `_find(tree, "Szkic bez danych") is None` (the draft without data appears in the tree), before its `quiz_total == 3` check. Revert.
7. *Mutant (spec T5):* in `_stamp_results`, change `if d["shows_score"]:` to `if rows_by_unit[d["node"].pk]["status"] == "submitted":` (container aggregation only; the quiz node's own `shows_score` is untouched). → `rt_t5` red: `counted` 2, heading 2/2 instead of 1/2. Revert.
8. *Mutant (spec T7, crashes before the check):* in `build_student_breakdown`, insert `_stamp_results(tree, {r["unit"].pk: r for r in results["rows"]})` directly after `attach(tree)`. → `rt_t7` errors: `KeyError` on the unpruned lesson node (`Lekcja A` is `is_unit` but not a quiz, so it has no row in `rows_by_unit`), before the test's key-leak check runs. Revert.
9. *Mutant (spec T7, crash-free):* first change `_stamp_results`'s unit test from `if d["is_unit"]:` to `if d["is_unit"] and is_quiz_unit(d["node"]):` (skipping lessons; `is_quiz_unit` lives in `courses/rollups.py`, so no import is needed), then insert `_stamp_results(tree, {r["unit"].pk: r for r in results["rows"]})` directly after `attach(tree)`. → `rt_t7` red: Progress nodes now carry `quiz_total` / `counted` etc. Revert both edits by hand.
10. *Mutant (invariant):* in `_stamp_results`, insert `if d["node"].pk not in rows_by_unit: continue` as the first line of the `if d["is_unit"]:` branch. → `rt_invariant` red (`DID NOT RAISE`). Revert.

`git diff` shows only Steps 1, 3 and 4.

- [ ] **Step 7: Ruff and commit**

```bash
uv run ruff format courses/rollups.py tests/test_analytics_student_page.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/rollups.py tests/test_analytics_student_page.py
git commit -m "feat(analytics): Results-mode section sums and a course total, the grid's figures"
```

### Task 4: The view paints the Results tree with the course's bands

**Files:**
- Modify: `courses/views_analytics.py` (new `_paint_results`; `analytics_student`)
- Test: `tests/test_analytics_student_page.py` (T6 data half; T7's colour mutants)

**Interfaces:**
- Consumes: `breakdown = {"student", "tree", "total"}` (Task 3); `course_color_bands(course)`, `band_style(percent, bands) -> {"bg", "fg"}`.
- Produces: `_paint_results(breakdown, bands) -> None`, setting `color` / `text_color` on every node dict of `breakdown["tree"]` (recursively) and on `breakdown["total"]`; `None` / `None` for a `None` percent.

**Implements:** O4, O5.

- [ ] **Step 1: Write the failing test**

In `tests/test_analytics_student_page.py`, add to the imports (keeping them sorted; ruff's isort fixes the order):

```python
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
```

Append to the end of the file:

```python
# Custom bands: with the defaults, a hard-coded palette would pass (spec T6).
CUSTOM_BANDS = [
    {"key": "none", "min": 0, "color": "#101010"},
    {"key": "weak", "min": 40, "color": "#202020"},
    {"key": "ok", "min": 60, "color": "#303030"},
    {"key": "good", "min": 75, "color": "#404040"},
    {"key": "excellent", "min": 90, "color": "#f0f0f0"},
]


def _custom_bands(course):
    course.color_bands = CUSTOM_BANDS
    course.save(update_fields=["color_bands"])
    return course_color_bands(course)


def test_rt_t6_results_nodes_carry_the_course_band_colours(client):
    course, _student, path = _results_fixture(client)
    bands = _custom_bands(course)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    for title in ("Rozdział A", "A1 oceniony"):  # a container AND a quiz, both 80%
        d = _find(tree, title)
        style = band_style(d["percent"], bands)
        assert (d["color"], d["text_color"]) == (style["bg"], style["fg"]), title
        assert d["color"] == "#404040", title  # precondition: a CUSTOM band
    total = breakdown["total"]
    assert total["color"] == band_style(total["percent"], bands)["bg"]
    # Every node is painted, whatever it renders; a None percent paints nothing.
    for title in ("Sekcja A2", "A1 w toku"):
        d = _find(tree, title)
        assert (d["color"], d["text_color"]) == (None, None), title
```

- [ ] **Step 2: Run it — expect RED**

Run: `uv run pytest tests/test_analytics_student_page.py -k "test_rt_t6 or test_rt_t7"`

Expected: `rt_t6` fails with `KeyError: 'color'`; `rt_t7` passes.

- [ ] **Step 3: Add `_paint_results`**

In `courses/views_analytics.py`, replace:

```python
    for avg in matrix["averages"]:
        paint(avg)
    paint(matrix["overall_average"])
```

with:

```python
    for avg in matrix["averages"]:
        paint(avg)
    paint(matrix["overall_average"])


def _paint_results(breakdown, bands):
    """Band colour + readable text colour on EVERY node dict of a Results-mode
    breakdown tree (quiz and container alike, rendered or not) and on its total
    (results-table spec §2.2). _decorate walks the matrix's flat structure, so
    it is not reused. A None percent gets color/text_color None (neutral).
    Results mode only: a Progress tree has no `percent` and no `total`."""

    def paint(d):
        style = band_style(d["percent"], bands)
        d["color"] = style["bg"]
        d["text_color"] = style["fg"]

    def walk(nodes):
        for d in nodes:
            paint(d)
            walk(d["children"])

    walk(breakdown["tree"])
    paint(breakdown["total"])
```

- [ ] **Step 4: Call it in Results mode only**

In `courses/views_analytics.py` (`analytics_student`), replace:

```python
    has_math = tree_titles_have_math(breakdown["tree"])
    return render(
        request,
        "courses/manage/analytics_student.html",
```

with:

```python
    has_math = tree_titles_have_math(breakdown["tree"])
    if mode == "results":
        # The matrix's own call, so a heading's colour is its grid cell's (O4).
        _paint_results(breakdown, course_color_bands(course))
    return render(
        request,
        "courses/manage/analytics_student.html",
```

- [ ] **Step 5: Run — expect GREEN**

Run: `uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_analytics_views.py tests/test_title_math_assets.py tests/test_courses_progress.py`

Expected: all pass.

- [ ] **Step 6: Falsify**

Run each mutant with `uv run pytest tests/test_analytics_student_page.py -k "<full test name>"`, observe red for the stated reason, revert by hand. The short ids below map to full names: `rt_t6` → `-k test_rt_t6_results_nodes_carry_the_course_band_colours`; `rt_t7` → `-k test_rt_t7_progress_mode_carries_no_results_keys` (never a bare `rt_t6` / `rt_t7`: Task 5 adds `test_rt_t6_percent_cells_carry_the_band_inline` and `test_rt_t7_progress_renders_the_tree_not_the_table` to the same file).

1. *Mutant (spec T6):* in `analytics_student`, replace `course_color_bands(course)` with `default_color_bands()` (already imported). → `rt_t6` red (`#52b06a` against `#404040`). Revert.
2. *Mutant (spec T6):* in `_paint_results.walk`, change `paint(d)` to `if not d["is_unit"]: paint(d)` (on its own line with the call indented under it). → `rt_t6` red with `KeyError: 'color'` on „A1 oceniony". Revert.
3. *Mutant (spec T7, guarded walk in both modes):* in `_paint_results.paint`, change `d["percent"]` to `d.get("percent")`; change `paint(breakdown["total"])` to `paint(breakdown.get("total", {}))`; and in `analytics_student` remove the `if mode == "results":` line (dedent the call). → `rt_t7` red on the `color` / `text_color` keys. Revert all three.
4. *Mutant (spec T7, unguarded walk in both modes):* only remove the `if mode == "results":` guard. → `rt_t7` errors with `KeyError: 'percent'` raised through the test client (the client re-raises view exceptions; there is no 500 response to see). Revert.

`git diff` shows only Steps 1, 3 and 4.

- [ ] **Step 7: Ruff and commit**

```bash
uv run ruff format courses/views_analytics.py tests/test_analytics_student_page.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/views_analytics.py tests/test_analytics_student_page.py
git commit -m "feat(analytics): paint the Results tree with the course's colour bands"
```

### Task 5: The Results table, the view-named heading and back link, the empty view

**Files:**
- Modify: `templates/courses/manage/analytics_student.html` (whole file), `templates/courses/manage/analytics_student_quiz.html` (back link), `courses/views_analytics.py` (`analytics_student_quiz` context)
- Create: `templates/courses/manage/_results_table_rows.html`
- Modify: `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`
- Test: `tests/test_analytics_student_page.py` (T1b, T1c, T2, T3, T4, T5, T5b, T5c, T5e, T6, T7, T7b, T8d, T9 rendered; `test_t6_…`, `test_t7_…` re-pointed; `test_t28b_one_page_name_in_both_modes` retired), `tests/test_analytics_student_quiz.py` (T10, T10b parity; `test_t37_quiz_titles_link_…` re-pointed; `test_t28b_per_question_back_link_…` retired), `tests/test_title_math_markers.py` (T10c)

**Interfaces:**
- Consumes: `breakdown["tree"]` / `breakdown["total"]` with the Task 3 keys and Task 4 colours; context `course`, `student`, `mode`, `drill_qs`, `has_math`, `other_view_url`, `back_url`.
- Produces: `_results_table_rows.html`, included as `{% include "courses/manage/_results_table_rows.html" with nodes=<list of node dicts> %}`; `analytics_student_quiz` context gains `"mode"`.
- Markup contract every later task relies on: `div.results-table-wrap > table.results-table`; `caption#results-table-caption.sr-only`; `thead th` with `results-table__title` / `results-table__status` / `results-table__num` ×2; body rows `tr` (quiz) or `tr.results-table__section` (container) or `tr.results-table__section.results-table__total` (course total, first); cells `th.results-table__title.results-table__d{depth}`, `td.results-table__status`, `td.results-table__num` (score), `td.results-table__num` (%); empty view `p.results-table-empty`.

**Implements:** O1, O2, O4, O5, O7, O8, O11, O17.

**Existing-test inventory (spec §7).** Every existing assertion on markup or text this PR changes, and what happens to it:

| Existing test | File | Action | Why / successor |
|---|---|---|---|
| `test_t6_results_mode_shows_quizzes_only` | `tests/test_analytics_student_page.py` | **Re-pointed** in place at the table (this task) | `.breakdown-unit` no longer renders in Results mode; same claim (quizzes only, lessons-only chapter gone, `pill--none` on the unstarted quiz) on table rows |
| `test_t7_results_mode_hides_the_chapter_chip_progress_shows_it` | same | **Re-pointed** in place (this task) | `_head(results, …)` finds no `.breakdown-node__head` in Results mode; asserts no `.rollup` anywhere in Results, chip still in Progress |
| `test_t28b_one_page_name_in_both_modes` | same | **Retired** (this task) | Asserts „Wyniki ucznia — Anna Nowak" in both modes, which O7 reverses; replaced by `test_rt_t9_heading_and_title_name_the_view` |
| `test_t8_…`, `test_t9_…`, `test_t10_…`, `test_t11_…`, `test_t12_…`, `test_t13_…`, `test_t15_…`, `test_t16_…`, `test_units_are_stamped_additional_as_a_boolean` | same | Unchanged | Progress mode or builder level (O5); `test_t16` reads `has_math` from the context |
| `test_t27_header_pill_matches_the_breakdown_pill_except_scored` | `tests/test_analytics_student_quiz.py` | **Re-pointed** (Task 1) | Its `reviewed` tuple is replaced by `test_rt_t10b_…` / `test_rt_t10d_…`; `reviewed` moved into its scored part |
| `test_t26_header_by_pill_kind` | same | Unchanged | Shares `_pill_quizzes` but never asserts `reviewed` |
| `test_t37_quiz_titles_link_iff_the_pupil_has_a_submission` | same | **Re-pointed** (this task): parametrized over `progress` (the `span.breakdown-unit__title` rows) and `results` (the table's quiz `<th>`) | Its Results-mode `div.breakdown-unit` selector no longer matches |
| `test_t37_back_link_round_trips_scope_mode_expand_subset_and_values` | same | Unchanged | Asserts the `href` only |
| `test_t28b_per_question_back_link_names_the_student_results_page` | same | **Retired** (this task) | Asserts „← Wyniki ucznia"; replaced by `test_rt_t10_back_link_names_the_view` |
| `test_t29_polish_marks_use_a_decimal_comma_in_badge_and_pill`, `test_t29_english_marks_keep_a_decimal_point`, `test_awaiting_header_has_one_review_link`, `test_t41_grid_quizzes_header_pills` | same | Unchanged | Progress mode (no `mode`) and AUTO quizzes already scored; header markup unchanged |
| `test_t14_quiz_title_link_is_underlined_without_hover`, `test_t33_breakdown_right_column` (incl. its `_neutralise(".breakdown-unit .pill,.badge--todo{margin-left:0}")` A/B), `test_t33_breakdown_lesson_titles_share_one_colour`, `test_t33_per_question_header_pill_is_not_pushed`, `test_t33c_todo_marker_is_not_painted_as_done` | `tests/test_e2e_analytics_student_pages.py` | Unchanged | `_open_breakdown` opens the page with no `mode`, i.e. Progress, where `.breakdown-unit` and its pills still render (O5). The per-question header strip is untouched |
| `test_group_teacher_drills_from_the_matrix_to_one_answer` | `tests/test_e2e_analytics.py` | Unchanged | The matrix opens in Progress, so the student page is Progress; `a.breakdown-unit__link` renders there (and the table keeps the class); `.breakdown .manage__title` still contains the name |
| `test_analytics_breakdown_titles_are_marked` | `tests/test_title_math_markers.py` | Unchanged | Loads Progress mode only; Results mode gets `test_rt_t10c_…` (this task) |
| `test_analytics_breakdown_returns_200_and_loads_katex`, `test_analytics_breakdown_loads_no_katex_without_maths` | `tests/test_title_math_assets.py` | Unchanged | Progress mode, `has_math` unchanged |
| Row 11 (`.breakdown__tree`) | `tests/capture_title_math_screenshots.py` | Kept; row 11b (Results) **added** in Task 8 | Row 11 shoots Progress only |
| `drill-down` entry (`.breakdown__tree`) | `tests/capture_help_screenshots.py` | **Re-pointed** in Task 8 (`mode=results`, waits for `.results-table`) | Results mode no longer renders the tree |
| `test_build_student_breakdown_pills`, `test_build_student_breakdown_submitted_ungraded_no_percent`, `test_grid_only_auto_quiz_pills_scored`, `test_unreviewed_review_multigrid_pills_awaiting_then_submitted`, `test_in_progress_pill_carries_submission_pk` | `tests/test_analytics_rollups.py` | Unchanged | Pill dicts keep their exact shape; the multigrid quiz's stored `max_score` stays 0, so it stays `submitted` |
| `graded` assertions in `test_build_course_results_combined_headline_and_statuses`, `test_awaiting_review_is_element_driven_even_for_unanswered_review_question` | `tests/test_courses_rollups.py` | Unchanged | `graded` keeps its meaning; only its comment changed (Task 1) |
| `test_review_marks_noun_agrees_with_exactly_one_in_polish` | `tests/test_questions_2diii_results.py` | Unchanged | Asserts the substrings „(do 1 punktu)" / „(do 1 dodatkowego punktu)", which survive O14 (Task 6) |
| Lesson chip (`.rollup` existence) in `test_t8_…` | `tests/test_analytics_student_page.py` | Unchanged | Asserts presence only; the wording is `test_rt_t11_…` (Task 6) |
| O13 strings | — | none exist | No test asserts „na ocenę" / „do oceny" today (grep of `tests/`); T14 is new (Task 6) |

- [ ] **Step 1: Write the failing tests — student page**

In `tests/test_analytics_student_page.py`, replace `test_t6_results_mode_shows_quizzes_only` and `test_t7_results_mode_hides_the_chapter_chip_progress_shows_it` (the whole two functions) with:

```python
def test_t6_results_mode_shows_quizzes_only(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    titles = [row["title"] for row in _table_rows(soup)]
    assert titles == ["Whole course", "Mixed chapter", "Chapter quiz", "Unstarted quiz"]
    assert soup.select("ul.breakdown__tree") == []
    unstarted = _table_row(soup, "Unstarted quiz")
    assert unstarted["status"].select_one(".pill.pill--none") is not None


def test_t7_results_mode_hides_the_chapter_chip_progress_shows_it(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, results = _get(client, f"{path}?mode=results")
    _resp, progress = _get(client, f"{path}?mode=progress")
    assert results.select(".rollup") == []
    assert _head(progress, "Mixed chapter").select_one(".rollup") is not None
```

Delete the whole `test_t28b_one_page_name_in_both_modes` function (retired; successor `test_rt_t9_heading_and_title_name_the_view` below).

Append to the end of the file:

```python
# --- results-table spec: the rendered table ----------------------------------------
def _table_rows(soup):
    rows = []
    for tr in soup.select("table.results-table tbody tr"):
        status, score, pct = tr.select("td")
        th = tr.select_one("th")
        rows.append(
            {
                "tr": tr,
                "th": th,
                "title": th.get_text(" ", strip=True),
                "status": status,
                "score": score,
                "pct": pct,
            }
        )
    return rows


def _table_row(soup, title):
    for row in _table_rows(soup):
        if row["title"] == title:
            return row
    raise AssertionError(f"no Results-table row titled {title!r}")


def _cells(row):
    return [row[key].get_text(" ", strip=True) for key in ("status", "score", "pct")]


def test_rt_t1b_a_reviewed_review_only_row_shows_its_score(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    row = _table_row(soup, "A1 sprawdzony")
    assert _cells(row) == ["", "4/5", "80%"]
    assert row["status"].select(".pill") == []


def test_rt_t1c_an_uncounted_summary_renders_a_count_and_no_figures(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    row = _table_row(soup, "Sekcja A2")
    assert _cells(row) == ["0/2", "", ""]
    assert row["pct"].get("style") is None


def test_rt_t1c_an_uncounted_course_total_renders_a_count_and_no_figures(client):
    _resp, soup = _get(client, f"{_uncounted_course(client)}?mode=results")
    total = _table_rows(soup)[0]
    assert total["title"] == "Whole course"
    assert _cells(total) == ["0/2", "", ""]
    assert total["pct"].get("style") is None


def test_rt_t2_one_quiz_headings_render_no_figures(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title in ("Sekcja C1", "Rozdział C"):  # each has a percent (75), no summary
        row = _table_row(soup, title)
        assert "results-table__section" in row["tr"]["class"], title
        assert _cells(row) == ["", "", ""], title
        assert row["pct"].get("style") is None, title


def test_rt_t3_the_total_row_comes_first(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    first = _table_rows(soup)[0]
    assert first["title"] == "Whole course"
    assert first["tr"]["class"] == ["results-table__section", "results-table__total"]
    assert _cells(first) == ["4/10", "31.5/41", "77%"]
    assert len(soup.select("tr.results-table__total")) == 1


def test_rt_t3_a_one_quiz_course_renders_no_total_row(client):
    _resp, soup = _get(client, f"{_one_quiz_course(client)}?mode=results")
    assert soup.select("tr.results-table__total") == []
    assert _table_rows(soup)[0]["title"] == "Rozdział"


def test_rt_t4_another_students_draft_renders_not_started(client):
    _course, _student, _chapter, path = _drafts_fixture(client)
    _polish(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    status = _table_row(soup, "Szkic cudzy")["status"]
    assert status.select_one(".pill--none").get_text(strip=True) == "nie rozpoczęto"


def test_rt_t5_a_zero_max_quiz_counts_in_the_denominator_only(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    assert _cells(_table_row(soup, "Rozdział B"))[0] == "1/2"
    assert _table_row(soup, "B bez punktów")["status"].select_one(".pill--submitted")


def test_rt_t5b_polish_cells_read_exactly(client):
    _course, _student, path = _results_fixture(client)
    _polish(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    total = _table_rows(soup)[0]
    assert total["title"] == "Cały kurs"
    assert _cells(total) == ["4/10", "31,5/41", "77%"]
    assert _cells(_table_row(soup, "Rozdział B")) == ["1/2", "16,5/22", "75%"]
    assert _cells(_table_row(soup, "B połowa")) == ["", "16,5/22", "75%"]


def _parts_course(client, with_parts):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    if with_parts:
        part = _node(course, None, "part", "Część 1")
        chapter = _node(course, part, "chapter", "Rozdział 1")
        section = _node(course, chapter, "section", "Sekcja 1")
        _quiz(course, section, "Q1")
        _quiz(course, section, "Q2")
        _quiz(course, chapter, "Q3")
        _quiz(course, _node(course, None, "part", "Część 2"), "Q4")
        expected = [
            ("Whole course", 0),
            ("Część 1", 0),
            ("Rozdział 1", 1),
            ("Sekcja 1", 2),
            ("Q1", 3),
            ("Q2", 3),
            ("Q3", 2),
            ("Część 2", 0),
            ("Q4", 1),
        ]
    else:
        chapter = _node(course, None, "chapter", "Rozdział bez części")
        section = _node(course, chapter, "section", "Sekcja")
        _quiz(course, section, "Q1")
        _quiz(course, section, "Q2")
        _quiz(course, chapter, "Q3")
        expected = [
            ("Whole course", 0),
            ("Rozdział bez części", 0),
            ("Sekcja", 1),
            ("Q1", 2),
            ("Q2", 2),
            ("Q3", 1),
        ]
    return _student_path(course, student), expected


@pytest.mark.parametrize("with_parts", [True, False])
def test_rt_t5c_rows_are_preorder_with_their_depth_class(client, with_parts):
    path, expected = _parts_course(client, with_parts)
    _resp, soup = _get(client, f"{path}?mode=results")
    got = [
        (
            row["title"],
            [c for c in row["th"]["class"] if c.startswith("results-table__d")],
        )
        for row in _table_rows(soup)
    ]
    assert got == [(title, [f"results-table__d{depth}"]) for title, depth in expected]


def test_rt_t5e_status_cells_show_the_pill_for_their_status(client):
    course, student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title, kind in (
        ("A1 nierozpoczęty", "pill--none"),
        ("A1 w toku", "pill--progress"),
        ("A1 do sprawdzenia", "pill--awaiting"),
    ):
        pills = _table_row(soup, title)["status"].select(".pill")
        assert len(pills) == 1 and kind in pills[0]["class"], title
    awaiting = QuizSubmission.objects.get(
        student=student, unit__course=course, unit__title="A1 do sprawdzenia"
    )
    review = _table_row(soup, "A1 do sprawdzenia")["status"].select_one(
        "a.breakdown-unit__review"
    )
    assert review["href"] == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": awaiting.pk},
    )
    assert _table_row(soup, "A1 oceniony")["status"].select(".pill") == []


def test_rt_t6_percent_cells_carry_the_band_inline(client):
    course, _student, path = _results_fixture(client)
    bands = _custom_bands(course)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title in ("Rozdział A", "A1 oceniony"):  # a heading AND a quiz row, both 80%
        style = band_style(80, bands)
        expected = f"background:{style['bg']};color:{style['fg']}"
        assert _table_row(soup, title)["pct"].get("style") == expected, title


def test_rt_t7_progress_renders_the_tree_not_the_table(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=progress")
    assert soup.select('[class*="results-table"]') == []
    assert soup.select_one("ul.breakdown__tree") is not None
    assert soup.select("ul.breakdown__tree .badge--done, ul.breakdown__tree .badge--todo")


def test_rt_t7b_a_course_without_quizzes_says_so(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    _node(course, chapter, "unit", "Lekcja", unit_type="lesson", obligatory=True)
    _polish(client)
    _resp, soup = _get(client, f"{_student_path(course, student)}?mode=results")
    assert soup.select("table.results-table") == []
    empty = soup.select_one("p.results-table-empty")
    assert empty.get_text(strip=True) == "Ten kurs nie ma jeszcze quizów"


@pytest.mark.parametrize(
    ("title", "has_math"),
    [(r"Quiz \(x^2\)", True), ("Quiz bez wzorów", False)],
    ids=["maths", "plain"],
)
def test_rt_t8d_scroll_wrapper_is_a_region_only_with_maths(client, title, has_math):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    _quiz(course, _node(course, None, "chapter", "Rozdział"), title)
    resp, soup = _get(client, f"{_student_path(course, student)}?mode=results")
    assert resp.context["has_math"] is has_math
    wrap = soup.select_one("div.results-table-wrap")
    caption = soup.select_one("table.results-table > caption")
    if has_math:
        assert wrap.get("role") == "region"
        assert wrap.get("tabindex") == "0"
        assert caption.get("id")
        assert wrap.get("aria-labelledby") == caption.get("id")
    else:
        for attr in ("role", "tabindex", "aria-labelledby"):
            assert wrap.get(attr) is None, attr


def test_rt_t9_heading_and_title_name_the_view(client):
    _course, _student, _mixed, path = _page_fixture(client)  # student: Anna Nowak
    _polish(client)
    for mode, word in (("results", "Wyniki"), ("progress", "Postęp")):
        _resp, soup = _get(client, f"{path}?mode={mode}")
        h1 = soup.select_one("h1").get_text(" ", strip=True)
        title = soup.select_one("title").get_text(strip=True)
        assert h1 == f"{word} — Anna Nowak", mode
        assert title.startswith(f"{word} · "), mode
        assert "Nowak" not in title, mode  # the <title> never names the student
        assert "ucznia" not in h1 and "ucznia" not in title, mode
        current = soup.select_one('.breakdown__view a[aria-current="page"]')
        assert current.get_text(strip=True) == word
```

- [ ] **Step 2: Write the failing tests — per-question page and title markers**

In `tests/test_analytics_student_quiz.py`, replace the whole `test_t28b_per_question_back_link_names_the_student_results_page` function (retired; successor below) with:

```python
@pytest.mark.parametrize(("mode", "word"), [("results", "Wyniki"), ("progress", "Postęp")])
def test_rt_t10_back_link_names_the_view(client, mode, word):
    """results-table spec T9/T10 (O7, O8): the back link names the view it returns
    to, never „Wyniki ucznia"."""
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Back word")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk, f"?mode={mode}")))
    back = soup.select_one("section.answers .manage__head a")
    assert back.get_text(" ", strip=True) == f"← {word}"
    assert "ucznia" not in back.get_text()
```

Replace the block from `# --- T37 breakdown links and the back link` through the end of `test_t37_quiz_titles_link_iff_the_pupil_has_a_submission` (i.e. `_breakdown_title_span` and that test) with:

```python
# --- T37 breakdown links and the back link -------------------------------------
def _breakdown_title_span(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        span = unit.select_one(":scope > span.breakdown-unit__title")
        if span is not None and span.get_text(strip=True) == title:
            return span
    raise AssertionError(f"no breakdown title {title!r}")


def _results_title_cell(soup, title):
    rows = "table.results-table tbody tr:not(.results-table__section) > th"
    for th in soup.select(rows):
        if th.get_text(strip=True) == title:
            return th
    raise AssertionError(f"no Results-table quiz title {title!r}")


@pytest.mark.parametrize("mode", ["progress", "results"])
def test_t37_quiz_titles_link_iff_the_pupil_has_a_submission(client, mode):
    course, pupil = _owner_view(client)
    scored = _empty_quiz(course, "L scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("1"))
    ungraded = _empty_quiz(course, "L ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "L awaiting")
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _submitted(pupil, awaiting, score=Decimal("0"), max_score=Decimal("0"))
    live = _empty_quiz(course, "L live")
    _add(live)
    _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)
    notyet = _empty_quiz(course, "L not started")
    _add(notyet)

    qs = f"?scope=all&mode={mode}&student={pupil.pk}&values=raw"
    breakdown_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    soup = _soup(client.get(breakdown_path + qs))
    drill = _expand_qs("all", mode, [], [pupil.pk], "raw")
    title_of = _breakdown_title_span if mode == "progress" else _results_title_cell
    for quiz in (scored, ungraded, awaiting, live):
        link = title_of(soup, quiz.title).select_one("a.breakdown-unit__link")
        assert link is not None, quiz.title
        assert link["href"] == _url(course, pupil.pk, quiz.pk, f"?{drill}")
    assert title_of(soup, notyet.title).select("a") == []


def test_rt_t10b_header_matches_the_table_row(client):
    """results-table spec T10b: the header of a fully reviewed REVIEW-only quiz shows
    the same figures as its Results-table row."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    table = _soup(client.get(f"{page}?mode=results"))
    row = _results_title_cell(table, reviewed.title).find_parent("tr")
    _status_cell, score, percent = (td.get_text(strip=True) for td in row.select("td"))
    status = _status(client, course, pupil, reviewed)
    assert (score, percent) == ("1/1", "100%")
    assert status.select_one(".answers__score").get_text(" ", strip=True) == "1 / 1 pkt"
    assert status.select_one(".answers__percent").get_text(strip=True) == percent
```

In `tests/test_title_math_markers.py`, add directly after `test_analytics_breakdown_titles_are_marked`:

```python
def test_rt_t10c_results_table_titles_are_marked(client):
    """results-table spec T10c. Results mode renders titles in <th> cells: the
    section <th>, a linked quiz <th> and an unlinked quiz <th> each carry
    data-math-title AND lang, asserted SEPARATELY (a count passes on a half-marked
    table); the „Cały kurs" <th> is interface text and carries neither. The linked
    quiz is SCORED, so a scored pill that lost submission_pk (and with it the
    link) leaves the linked selector empty."""
    pa = make_pa(client)
    course, _unit, nodes = make_title_course(maths_on="far")
    course.owner = pa
    course.save(update_fields=["owner"])
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    linked = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=nodes["part2"],
        order=1,
        title=MATHS_TITLE,
    )
    QuizSubmission.objects.create(
        student=student,
        unit=linked,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("1"),
        max_score=Decimal("1"),
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=nodes["part2"],
        order=2,
        title=MATHS_TITLE,
    )
    url = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    soup = BeautifulSoup(
        client.get(f"{url}?mode=results").content.decode(), "html.parser"
    )
    body = "table.results-table tbody"
    quiz_th = f"{body} tr:not(.results-table__section) > th"
    groups = (
        ("section", f"{body} tr.results-table__section:not(.results-table__total) > th"),
        ("linked quiz", f"{quiz_th}:has(a.breakdown-unit__link)"),
        ("unlinked quiz", f"{quiz_th}:not(:has(a))"),
    )
    for name, selector in groups:
        cells = soup.select(selector)
        assert len(cells) == 1, name
        assert cells[0].has_attr("data-math-title"), name
        assert cells[0].get("lang") == course.language, name
    total = soup.select(f"{body} tr.results-table__total > th")
    assert len(total) == 1
    assert not total[0].has_attr("data-math-title")
    assert total[0].get("lang") is None
```

- [ ] **Step 3: Run them — expect RED**

```bash
uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_title_math_markers.py -k "test_rt_ or t6_results or t7_results or t37"
```

Expected: every rendered-table test fails (`table.results-table` does not exist: `_table_rows` returns `[]`, so `[0]` raises `IndexError` and `_table_row` raises `AssertionError: no Results-table row`); `test_rt_t9_…` fails on „Wyniki ucznia — Anna Nowak"; `test_rt_t10_…` fails on „← Wyniki ucznia"; `test_t37_…[results]` fails (no table), `[progress]` passes; `test_rt_t7_progress_renders_the_tree_not_the_table` passes already (a guard, falsified in Step 9); `test_t7_results_mode_hides_the_chapter_chip_progress_shows_it` passes already too (Results mode already hides `.rollup`, Progress shows it).

- [ ] **Step 4: Create the rows template**

Create `templates/courses/manage/_results_table_rows.html`:

```django
{% load i18n courses_extras %}
{% comment %}One Results-table row per node of the pruned breakdown tree, in pre-order
(results-table spec §2.3): a heading row, then its children, recursively. Reads
course, student and drill_qs from the inherited context, so no include here uses
`only`. The number cells are written on ONE line each: a newline inside a cell adds
a whitespace box that the e2e alignment tests would measure. The indent class comes
from the node's depth (0 for any root), never from its kind.{% endcomment %}
{% for item in nodes %}
  {% if item.is_unit %}
    <tr>
      <th scope="row" class="results-table__title results-table__d{{ item.depth }}" lang="{{ course.language }}" data-math-title>{% if item.pill.submission_pk %}<a class="breakdown-unit__link" href="{% url 'courses:manage_analytics_student_quiz' slug=course.slug student_pk=student.pk node_pk=item.node.pk %}?{{ drill_qs }}">{{ item.node.title }}</a>{% else %}{{ item.node.title }}{% endif %}</th>
      <td class="results-table__status">{% if not item.shows_score %}{% with p=item.pill %}{% include "courses/manage/_quiz_pill.html" %}{% if p.kind == "awaiting" %}<a class="breakdown-unit__review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=p.submission_pk %}">{% trans "Review" %}</a>{% endif %}{% endwith %}{% endif %}</td>
      <td class="results-table__num">{% if item.shows_score %}{{ item.score|marks }}/{{ item.max_score|marks }}{% endif %}</td>
      <td class="results-table__num"{% if item.shows_score %} style="background:{{ item.color }};color:{{ item.text_color }}"{% endif %}>{% if item.shows_score %}{{ item.percent }}%{% endif %}</td>
    </tr>
  {% else %}
    <tr class="results-table__section">
      <th scope="row" class="results-table__title results-table__d{{ item.depth }}" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</th>
      <td class="results-table__status">{% if item.summary %}{{ item.counted }}/{{ item.quiz_total }}{% endif %}</td>
      <td class="results-table__num">{% if item.summary and item.percent is not None %}{{ item.score_sum|marks }}/{{ item.max_sum|marks }}{% endif %}</td>
      <td class="results-table__num"{% if item.summary and item.percent is not None %} style="background:{{ item.color }};color:{{ item.text_color }}"{% endif %}>{% if item.summary and item.percent is not None %}{{ item.percent }}%{% endif %}</td>
    </tr>
    {% include "courses/manage/_results_table_rows.html" with nodes=item.children %}
  {% endif %}
{% endfor %}
```

- [ ] **Step 5: Rewrite the student page template**

Replace the whole content of `templates/courses/manage/analytics_student.html` with:

```django
{% extends "base.html" %}
{% load i18n courses_extras %}
{% block head_title %}{% if mode == "results" %}{% trans "Results" %}{% else %}{% trans "Progress" %}{% endif %} · {{ course.title }} · libli{% endblock %}
{% block extra_css %}{% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}{% endblock %}
{% block content %}
<section class="manage breakdown">
  <header class="manage__head">
    {% comment %}The heading names the VIEW, then the student: „Wyniki ucznia" is wrong
    for a girl (results-table spec O7). The <title> names the view but never the
    student, who would otherwise land in browser history and bookmarks.{% endcomment %}
    <h1 class="manage__title">{% if mode == "results" %}{% trans "Results" %}{% else %}{% trans "Progress" %}{% endif %} — {{ student.list_display_name }}</h1>
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
  {% if mode == "results" %}
    {% if breakdown.tree %}
      {% comment %}A Tab stop and a landmark ONLY when the table can scroll, i.e. when a
      KaTeX formula can widen it (results-table spec §2.5). position:relative on the
      wrapper is kept defensively (see app.css).{% endcomment %}
      <div class="results-table-wrap"{% if has_math %} role="region" aria-labelledby="results-table-caption" tabindex="0"{% endif %}>
        <table class="results-table">
          <caption id="results-table-caption" class="sr-only">{% trans "Quiz results" %}</caption>
          <thead>
            <tr>
              <th scope="col" class="results-table__title">{% trans "Title" %}</th>
              <th scope="col" class="results-table__status">{% trans "Quizzes" %}</th>
              <th scope="col" class="results-table__num">{% trans "Score" %}</th>
              <th scope="col" class="results-table__num">%</th>
            </tr>
          </thead>
          <tbody>
            {% with t=breakdown.total %}{% if t.summary %}
            <tr class="results-table__section results-table__total">
              <th scope="row" class="results-table__title results-table__d0">{% trans "Whole course" %}</th>
              <td class="results-table__status">{{ t.counted }}/{{ t.quiz_total }}</td>
              <td class="results-table__num">{% if t.percent is not None %}{{ t.score_sum|marks }}/{{ t.max_sum|marks }}{% endif %}</td>
              <td class="results-table__num"{% if t.percent is not None %} style="background:{{ t.color }};color:{{ t.text_color }}"{% endif %}>{% if t.percent is not None %}{{ t.percent }}%{% endif %}</td>
            </tr>
            {% endif %}{% endwith %}
            {% include "courses/manage/_results_table_rows.html" with nodes=breakdown.tree %}
          </tbody>
        </table>
      </div>
    {% else %}
      <p class="results-table-empty">{% trans "No quizzes in this course yet" %}</p>
    {% endif %}
  {% else %}
    <ul class="breakdown__tree">
      {% for item in breakdown.tree %}
        {% include "courses/manage/_breakdown_node.html" with item=item course=course %}
      {% endfor %}
    </ul>
  {% endif %}
</section>
{% endblock %}
{% block extra_js %}{% if has_math %}{% include "courses/_katex_js.html" %}{% endif %}{% endblock %}
```

- [ ] **Step 6: Name the view in the per-question back link**

In `templates/courses/manage/analytics_student_quiz.html`, replace:

```django
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% trans "Student results" %}</a>
```

with:

```django
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% if mode == "results" %}{% trans "Results" %}{% else %}{% trans "Progress" %}{% endif %}</a>
```

In `courses/views_analytics.py` (`analytics_student_quiz`), replace:

```python
            "back_url": f"{student_path}?{back_qs}",
            "has_math": _answers_have_math(unit, rows),
```

with:

```python
            "back_url": f"{student_path}?{back_qs}",
            # The back link names the view it returns to (results-table spec §3.2).
            "mode": mode,
            "has_math": _answers_have_math(unit, rows),
```

- [ ] **Step 7: Catalog procedure**

Run the Global Constraints catalog procedure for this task's rows: add `Whole course` → „Cały kurs" and `Quiz results` → „Wyniki quizów"; `Student results` must be gone:

```bash
grep -c 'msgid "Student results"' locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
```

Expected: `0` for both (a non-zero count means a template still uses it — find it with `grep -rn "Student results" templates courses` and stop).

- [ ] **Step 8: Run — expect GREEN**

```bash
uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_title_math_markers.py tests/test_title_math_assets.py tests/test_i18n_po_health.py tests/test_courses_progress.py
```

Expected: all pass.

- [ ] **Step 9: Falsify**

For each: apply by hand, run the named test with `uv run pytest <file> -k "<full test name>"`, observe red for the reason given, revert by hand. Pass the FULL function names below, never the short ids (`rt_t1c`, `rt_t6`, `rt_t7` … also match Task 3's and Task 4's tests in the same file):

| Item | File | `-k` |
|---|---|---|
| 1 | `tests/test_analytics_student_page.py` | `test_rt_t1c_an_uncounted_summary_renders_a_count_and_no_figures` |
| 2 | same | `test_rt_t2_one_quiz_headings_render_no_figures` |
| 3 | same | `test_rt_t3_a_one_quiz_course_renders_no_total_row` |
| 4, 5, 6 | same | `test_rt_t5b_polish_cells_read_exactly` |
| 7 | same | `test_rt_t5c_rows_are_preorder_with_their_depth_class` |
| 8 | same | `test_rt_t5e_status_cells_show_the_pill_for_their_status` |
| 9 | same | `test_rt_t6_percent_cells_carry_the_band_inline` |
| 10 | same | `test_rt_t7_progress_renders_the_tree_not_the_table` |
| 11 | same | `test_rt_t7b_a_course_without_quizzes_says_so` |
| 12 | same | `"test_rt_t8d_scroll_wrapper_is_a_region_only_with_maths and plain"` |
| 13 | same | `"test_rt_t8d_scroll_wrapper_is_a_region_only_with_maths and not plain"` (`and maths` would match both cases: the function name contains „maths") |
| 14 | same | `test_rt_t9_heading_and_title_name_the_view` |
| 15 | `tests/test_analytics_student_quiz.py` | `"test_rt_t10_back_link_names_the_view and results"` |
| 16, 17 | `tests/test_title_math_markers.py` | `test_rt_t10c_results_table_titles_are_marked` |

1. *Mutant (T1c):* in `_results_table_rows.html`'s heading row, change the score cell's `{% if item.summary and item.percent is not None %}` to `{% if item.summary %}`. → `rt_t1c_an_uncounted_summary…` red („0/0"). Revert.
2. *Mutant (spec T2):* drop `item.summary and` from BOTH the heading score and % conditions (the three `{% if … %}` on those two cells). → `rt_t2_one_quiz_headings…` red (Sekcja C1 shows „3/4", „75%" and a style). Revert.
3. *Mutant (T3 render):* in `analytics_student.html`, change `{% if t.summary %}` to `{% if True %}`. → `rt_t3_a_one_quiz_course_renders_no_total_row` red. Revert.
4. *Mutant (spec T5b):* on the heading score cell, drop `|marks` from `item.score_sum|marks`. → `rt_t5b` red („16,50/22" on Rozdział B — Django localises the bare stored two-decimal Decimal in Polish). Revert.
5. *Mutant (spec T5b):* swap the heading row's score and % `<td>` contents (move `{{ item.score_sum|marks }}/{{ item.max_sum|marks }}` into the last cell and `{{ item.percent }}%` into the third). → `rt_t5b` red. Revert.
6. *Mutant (spec T5b):* drop the `%` after `{{ item.percent }}` on the quiz row. → `rt_t5b` red („75" on B połowa). Revert.
7. *Mutant (spec T5c):* in `courses/rollups.py::_stamp_results`, add `d["depth"] = ContentNode.RANK[d["node"].kind]` as the first line inside `for d in nodes:`. → `rt_t5c` red for both parameters (Q3 under a chapter becomes d3; in the course without parts the chapter becomes d1). Revert.
8. *Mutant (spec T5e):* in `_results_table_rows.html`, delete `{% with p=item.pill %}` and its `{% endwith %}`. → `rt_t5e` red (every status pill `pill--none`). Revert.
9. *Mutant (T6 render):* delete the quiz row's `{% if item.shows_score %} style="…"{% endif %}`. → `rt_t6_percent_cells…` red on „A1 oceniony". Revert.
10. *Mutant (T7 render):* in `analytics_student.html`, change `{% if mode == "results" %}` (the one around the table, not the switch) to `{% if True %}`. → `rt_t7_progress_renders_the_tree_not_the_table` red. Revert.
11. *Mutant (T7b):* change `{% if breakdown.tree %}` to `{% if True %}`. → `rt_t7b` red (no `p.results-table-empty`). Revert.
12. *Mutant (spec T8d):* change `{% if has_math %} role="region"…{% endif %}` to always emit the three attributes. → `rt_t8d[plain]` red. Revert.
13. *Mutant (spec T8d):* delete `id="results-table-caption"` from the `<caption>`. → `rt_t8d[maths]` red. Revert.
14. *Mutant (T9):* change the `<h1>`'s `{% trans "Results" %}` to `{% trans "Student results" %}` (no catalog run: English msgid fallback). → `rt_t9` red. Revert.
15. *Mutant (T10):* delete the `"mode": mode,` line from `analytics_student_quiz`'s context. → `rt_t10[results-Wyniki]` red („← Postęp"). Revert.
16. *Mutant (spec T10c):* delete `data-math-title` from the quiz row's `<th>` in `_results_table_rows.html`. → `rt_t10c` red on „linked quiz". Revert.
17. *Mutant (spec T10c):* in `courses/rollups.py::_quiz_pill`, delete the `"submission_pk": row["submission_pk"],` line of the **scored** dict. → `rt_t10c` red (the linked selector matches nothing). Revert.

`git diff` shows only Steps 1, 2 and 4–7.

- [ ] **Step 10: Ruff and commit**

```bash
uv run ruff format courses/views_analytics.py tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_title_math_markers.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add templates/courses/manage/analytics_student.html templates/courses/manage/_results_table_rows.html templates/courses/manage/analytics_student_quiz.html courses/views_analytics.py locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_title_math_markers.py
git commit -m "feat(analytics): the Results view is a table with section sums; headings name the view"
```

### Task 6: „lekcje: 1/2" on both pages, and „sprawdzenie" for review waiting

**Files:**
- Modify: `templates/courses/manage/_breakdown_node.html` (line 24, line-count neutral), `templates/courses/_outline_node.html` (the two chip lines, line-count neutral)
- Modify: `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`
- Modify: `docs/help/teacher/quiz-review.pl.md`
- Test: `tests/test_analytics_student_page.py` (T11), create `tests/test_review_wording_pl.py` (T14), `tests/test_e2e_outline_tree.py` (stale rationale comment, line-count neutral)

**Interfaces:**
- Consumes: node dicts' `required_done` / `required_total` (unchanged); the msgids of the Global Constraints table.
- Produces: chip markup `<span class="rollup">lessons: {{ done }}/{{ total }}</span>` (pl „lekcje: 1/2") in both templates; the O13/O14 Polish msgstrs.

**Implements:** O6, O12, O13, O14.

- [ ] **Step 1: Write the failing tests — the chip (T11)**

In `tests/test_analytics_student_page.py`, add to the imports:

```python
from django.template.loader import render_to_string
from django.utils import translation

from tests.helpers_title_math import login_student
from tests.helpers_title_math import make_title_course
from tests.test_i18n_po_health import CATALOGS
from tests.test_i18n_po_health import _entries
```

Append to the end of the file:

```python
# --- results-table spec T11 (O6, O12): one chip wording on both pages ------------
def test_rt_t11_teacher_chip_reads_lekcje(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _polish(client)
    _resp, soup = _get(client, f"{path}?mode=progress")
    mixed = _head(soup, "Mixed chapter").select_one(".rollup")
    lonely = _head(soup, "Lessons-only chapter").select_one(".rollup")
    assert mixed.get_text(" ", strip=True) == "lekcje: 1/1"
    assert lonely.get_text(" ", strip=True) == "lekcje: 0/1"


def test_rt_t11_student_outline_chip_reads_lekcje(client):
    course, _unit, nodes = make_title_course(maths_on="none")
    student = login_student(client, course)
    UnitProgressFactory(student=student, unit=nodes["unitA"], completed=True)
    _polish(client)
    outline = reverse("courses:course_outline", kwargs={"slug": course.slug})
    _resp, soup = _get(client, outline)
    chips = {
        summary.select_one(".outline-node__title").get_text(strip=True): (
            summary.select_one(".rollup").get_text(" ", strip=True)
        )
        for summary in soup.select("summary.outline-node__head")
        if summary.select_one(".rollup") is not None
    }
    assert chips["Czesc pierwsza"] == "lekcje: 1/2"
    assert chips["Czesc druga"] == "lekcje: 0/1"


def test_rt_t11_childless_outline_branch_chip_reads_lekcje():
    """_outline_node.html's childless container arm is unreachable through a view
    (build_outline prunes empty containers), so it is rendered bare."""

    class _Node:
        pk = 1
        kind = "chapter"
        title = "Rozdział"

    class _Course:
        language = "pl"
        slug = "c"

    item = {
        "node": _Node(),
        "is_unit": False,
        "children": [],
        "required_total": 2,
        "required_done": 1,
        "additional_done": 0,
        "depth": 0,
    }
    with translation.override("pl"):
        html = render_to_string(
            "courses/_outline_node.html",
            {"item": item, "course": _Course(), "note_counts": {}},
        )
    chip = BeautifulSoup(html, "html.parser").select_one(".outline-node__head .rollup")
    assert chip.get_text(" ", strip=True) == "lekcje: 1/2"


def test_rt_t11_catalogs_drop_the_unused_msgids():
    for locale, path in CATALOGS.items():
        msgids = {entry["msgid"] for entry in _entries(path)}
        assert "required" not in msgids, locale
        assert "Student results" not in msgids, locale
```

- [ ] **Step 2: Write the failing tests — review wording (T14)**

Create `tests/test_review_wording_pl.py`:

```python
"""Review-waiting wording in Polish (results-table spec O13, O14; T14): „sprawdzenie",
never „ocena", wherever a submission waits for a teacher. The graded msgids keep
„ocena": grading is what they mean."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

OLD = "na ocenę"


def _polish(client):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()


def _soup(resp):
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), "html.parser")


def _review_question(max_marks):
    return ExtendedResponseQuestionElement.objects.create(
        stem="<p>Esej?</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )


def _finished_review_quiz(client, marks):
    """A student finishes, through the real quiz views, a quiz of REVIEW questions
    (one per entry of `marks`). Returns the unit."""
    user = make_login(client, "t14stu")
    _polish(client)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    for max_marks in marks:
        add_element(unit, _review_question(max_marks))
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.get(f"{base}/")  # materialise the QuizSubmission
    client.post(f"{base}/finish/")
    return unit


@pytest.mark.parametrize(
    ("marks", "footer"),
    [
        (["1"], "1 pytanie oczekuje na sprawdzenie (do 1 dodatkowego punktu)"),
        (
            ["0.5", "0.5"],
            "2 pytania oczekują na sprawdzenie (do 1 dodatkowego punktu)",
        ),
        (["0.2"] * 5, "5 pytań oczekuje na sprawdzenie (do 1 dodatkowego punktu)"),
        (["2"], "1 pytanie oczekuje na sprawdzenie (do 2 dodatkowych punktów)"),
        (
            ["1", "1"],
            "2 pytania oczekują na sprawdzenie (do 2 dodatkowych punktów)",
        ),
        (["1"] * 5, "5 pytań oczekuje na sprawdzenie (do 5 dodatkowych punktów)"),
    ],
)
def test_rt_t14_quiz_results_badge_and_all_six_plural_forms(client, marks, footer):
    unit = _finished_review_quiz(client, marks)
    soup = _soup(client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/results/"))
    meta = soup.select_one(".result-summary__meta").get_text(" ", strip=True)
    assert meta == footer
    badge = soup.select_one(".badge--review").get_text(" ", strip=True)
    assert badge.startswith("Oczekuje na sprawdzenie (")
    assert OLD not in soup.select_one("article.quiz-results").get_text(" ")


def test_rt_t14_course_results_awaiting_badge(client):
    unit = _finished_review_quiz(client, ["1"])
    soup = _soup(client.get(f"/courses/{unit.course.slug}/results/"))
    badge = soup.select_one("li.result-row .badge--review")
    assert badge.get_text(strip=True) == "Oczekuje na sprawdzenie"
    assert OLD not in soup.select_one("article.course-results").get_text(" ")


def test_rt_t14_teacher_pages_say_sprawdzenie(client):
    pa = make_pa(client, "t14pa")
    _polish(client)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Esej"
    )
    add_element(quiz, _review_question("1"))
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    QuizSubmission.objects.create(
        student=pupil,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    queue = _soup(
        client.get(reverse("courses:manage_review_queue", kwargs={"slug": course.slug}))
    )
    heading = queue.select("section.manage > h2")[0].get_text(" ", strip=True)
    assert heading.startswith("Oczekuje na sprawdzenie")
    student_page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    progress = _soup(client.get(f"{student_page}?mode=progress"))
    assert progress.select_one(".pill--awaiting").get_text(strip=True) == (
        "oczekuje na sprawdzenie"
    )
    answers = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student_quiz",
                kwargs={
                    "slug": course.slug,
                    "student_pk": pupil.pk,
                    "node_pk": quiz.pk,
                },
            )
        )
    )
    header_pill = answers.select_one(".answers__status .pill--awaiting")
    assert header_pill.get_text(strip=True) == "oczekuje na sprawdzenie"
    badge = answers.select_one(".answers__verdict .badge").get_text(" ", strip=True)
    assert badge == "Oczekuje na sprawdzenie (do 1 punktu)"
    for soup in (queue, progress, answers):
        assert OLD not in soup.select_one("section.manage").get_text(" ")


def test_rt_t14_question_feedback_says_przeslano_do_sprawdzenia():
    with translation.override("pl"):
        html = render_to_string(
            "courses/elements/_quiz_question_feedback.html", {"neutral": "review"}
        )
    verdict = BeautifulSoup(html, "html.parser").select_one(".question__verdict")
    assert verdict.get_text(strip=True) == "Przesłano do sprawdzenia"


def test_rt_t14_graded_wording_keeps_ocena():
    with translation.override("pl"):
        assert gettext("Quiz graded") == "Quiz oceniony"
        assert gettext("Your quiz was graded") == "Twój quiz został oceniony"
        assert gettext("submitted — not graded") == "przesłano — bez oceny"
```

- [ ] **Step 3: Run them — expect RED**

```bash
uv run pytest tests/test_analytics_student_page.py tests/test_review_wording_pl.py -k "test_rt_t11 or test_rt_t14"
```

Expected: the three chip tests fail („1/1 wymagane" ≠ „lekcje: 1/1"); `rt_t11_catalogs…` fails on `required`; every `rt_t14` rendering test fails on „oczekuje na ocenę" / „Oczekuje na ocenę" / „Przesłano do oceny"; `rt_t14_graded_wording_keeps_ocena` passes (a guard).

- [ ] **Step 4: One chip string, both templates**

In `templates/courses/manage/_breakdown_node.html`, replace the single line:

```django
      {% if item.required_total and mode != "results" %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
```

with the single line (the `mode != "results"` guard is dead: Results mode no longer renders this template):

```django
      {% if item.required_total %}<span class="rollup">{% blocktrans with done=item.required_done total=item.required_total %}lessons: {{ done }}/{{ total }}{% endblocktrans %}</span>{% endif %}
```

In `templates/courses/_outline_node.html`, the same fragment occurs on two lines with different indentation, so replace it with **`replace_all: true`** — replace:

```django
<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>
```

with:

```django
<span class="rollup">{% blocktrans with done=item.required_done total=item.required_total %}lessons: {{ done }}/{{ total }}{% endblocktrans %}</span>
```

Then confirm both files kept their line counts: `git diff --numstat -- templates/courses/manage/_breakdown_node.html templates/courses/_outline_node.html` shows `1	1	templates/courses/manage/_breakdown_node.html` and `2	2	templates/courses/_outline_node.html` (tab-separated).

In `tests/test_e2e_outline_tree.py`, its comment near line 160 still names the old chip wording. Replace the single line:

```python
    # becomes "Chapter A 0/1 required Start fresh", which still matches
```

with the single line:

```python
    # becomes "Chapter A lessons: 0/1 Start fresh", which still matches
```

- [ ] **Step 5: Catalog procedure**

Run the Global Constraints catalog procedure for this task's rows: add `lessons: %(done)s/%(total)s` → „lekcje: %(done)s/%(total)s"; overwrite the msgstrs of `Awaiting review`, `awaiting review`, `Submitted for review` and all three `msgstr[i]` of the two `… question awaiting review (up to …)` plural entries exactly as the table gives them. Then:

```bash
grep -c 'msgid "required"' locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
grep -n "na ocen\|do oceny" locale/pl/LC_MESSAGES/django.po
```

Expected: `0` for both; the second grep prints nothing.

- [ ] **Step 6: The review-queue help matches the page**

In `docs/help/teacher/quiz-review.pl.md`, replace:

```markdown
zgłoszenia trafiają do **kolejki sprawdzania** i czekają na ocenę. Otwiera ją
```

with:

```markdown
zgłoszenia trafiają do **kolejki sprawdzania** i czekają na sprawdzenie. Otwiera ją
```

and replace:

```markdown
- **Oczekuje na ocenę** — zgłoszenia, które uczniowie zakończyli, a
```

with:

```markdown
- **Oczekuje na sprawdzenie** — zgłoszenia, które uczniowie zakończyli, a
```

Then `grep -rn "na ocenę\|do oceny" docs/help` → no output (spec §8 found only these two hits on 2026-09-17; if another appears, list it in the PR body and change it only if it names a review-waiting label).

- [ ] **Step 7: Run — expect GREEN**

```bash
uv run pytest tests/test_analytics_student_page.py tests/test_review_wording_pl.py tests/test_i18n_po_health.py tests/test_questions_2diii_results.py tests/test_questions_2diii_quiz.py tests/test_unit_nav_render.py tests/test_outline_collapsible.py tests/test_courses_progress.py tests/test_title_math_markers.py tests/test_help.py
```

Expected: all pass.

- [ ] **Step 8: Falsify**

1. *Mutant (T11, outline):* in `_outline_node.html`, in the **childless** arm only (the second `lessons:` chip in the file — the `<span class="rollup">` line inside the `<div class="outline-node__head">` arm), replace `{% blocktrans with done=item.required_done total=item.required_total %}lessons: {{ done }}/{{ total }}{% endblocktrans %}` with `{{ item.required_done }}/{{ item.required_total }}`. → `rt_t11_childless_outline_branch_chip_reads_lekcje` red („1/2"), while `rt_t11_student_outline_chip_reads_lekcje` stays green (a view only reaches the `<details>` arm) — which is why the bare render exists. Revert.
2. *Mutant (T14):* in `locale/pl/LC_MESSAGES/django.po`, set `msgstr[1]` of `%(n)s question awaiting review (up to 1 more mark)` back to „%(n)s pytania oczekują na ocenę (do 1 dodatkowego punktu)" and run `uv run python manage.py compilemessages -l pl`. Run `uv run pytest tests/test_review_wording_pl.py -k test_rt_t14_quiz_results_badge_and_all_six_plural_forms` → red on exactly one case (the `["0.5", "0.5"]` one). Revert the `.po` by hand, re-run `compilemessages -l pl`, re-run the test → green.

`git diff` shows only Steps 1, 2 and 4–6.

- [ ] **Step 9: Ruff and commit**

```bash
uv run ruff format tests/test_analytics_student_page.py tests/test_review_wording_pl.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add templates/courses/manage/_breakdown_node.html templates/courses/_outline_node.html locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo docs/help/teacher/quiz-review.pl.md tests/test_analytics_student_page.py tests/test_review_wording_pl.py tests/test_e2e_outline_tree.py
git commit -m "feat(i18n): lekcje: 1/2 on both chips; sprawdzenie for review waiting (O6, O12-O14)"
```

### Task 7: Table CSS, computed-style e2e, and the 30% floor measured before it is committed

**Files:**
- Modify: `core/static/core/css/app.css` (one `.results-table*` block after `.breakdown-unit .pill{margin-left:auto}`)
- Test: `tests/test_e2e_analytics_student_pages.py` (T5d, T8a, T8b, T8c, T13, T13b, T13c, T13d)
- Scratch (never committed): `<scratchpad>/rt_page.py` — `<scratchpad>` is the executing session's scratchpad directory

**Interfaces:**
- Consumes: Task 5's markup contract.
- Produces: the CSS classes' computed behaviour below; the e2e fixture `_seed_results_table(client, username, *, theme="light", deep_title=RT_LONG_TITLE) -> (course, student)` and `_open_results_table(page, live_server, client, username, *, width, theme="light", deep_title=RT_LONG_TITLE) -> (course, student)`; module constants `RT_TITLE_SHARE_FLOOR`, `RT_DEPTH_REM`.

**Implements:** O1, O4, O5, O11.

Computed `padding-inline-start` of a body title cell (spec §2.3), which the CSS below must produce:

| band | base | d0 | d1 | d2 | d3 |
|---|---|---|---|---|---|
| wider than 640px (unconditional rules) | .5rem | .5rem | 1.5rem | 2.5rem | 3.5rem |
| `max-width:640px` block | .5rem | .5rem | 1rem | 1.5rem | 2rem |
| `max-width:480px` block | .25rem | .25rem | .75rem | 1.25rem | 1.75rem |

- [ ] **Step 1: Write the failing e2e tests**

In `tests/test_e2e_analytics_student_pages.py`, change the imports at the top from:

```python
import os
from decimal import Decimal
```

to:

```python
import os
from decimal import Decimal
from itertools import pairwise
```

Append to the end of the file:

```python
# --- results-table spec (2026-09-17) §2.4 / §7: the Results table --------------------
RT_LONG_TITLE = "Bardzo długi tytuł quizu na trzecim poziomie zagnieżdżenia tego kursu"
RT_MATH_TITLE = (
    # A SINGLE brace group around the whole formula body: no top-level relation
    # or binary operator, so KaTeX emits exactly one `.base` run, which the
    # vendored `.katex .base{display:inline-block; white-space:nowrap}` makes
    # one atomic inline box (unbreakable) -- not the app.css punctuation rule.
    # Without the wrapping braces the top-level `=`/`+` would split it into
    # several `.base` runs, which wraps instead of widening the table (T8b).
    r"Wzór \({\sum_{k=1}^{n} k^{2} = \frac{n(n+1)(2n+1)}{6}"
    r" = \int_{0}^{n} x^{2}\,dx + \sqrt{a^{2}+b^{2}+c^{2}+d^{2}+e^{2}}}\)"
)
# Spec §7 T8a: a FLOOR, measured by plan Task 7 on this fixture and on mat-pp before
# it was committed. A design pass may raise it, never lower it.
RT_TITLE_SHARE_FLOOR = 0.30
# Spec §2.3's computed padding-inline-start of d0..d3 title cells, in rem, by width.
RT_DEPTH_REM = {
    1280: (0.5, 1.5, 2.5, 3.5),
    600: (0.5, 1.0, 1.5, 2.0),
    390: (0.25, 0.75, 1.25, 1.75),
}


def _seed_results_table(client, username, *, theme="light", deep_title=RT_LONG_TITLE):
    """The Results-table fixture, rendered in Polish for a PA who owns the course:

    Część pierwsza (d0)               3/5   812,5/960,5  85%
      Rozdział z sekcjami (d1)        3/5   812,5/960,5  85%
        Sekcja pełna (d2)             2/4   804/850      95%
          <deep_title> (d3)           800/800  100%
          Mały quiz (d3)              4/50     8%
          Quiz do sprawdzenia (d3)    awaiting review + its Review link
          Quiz w toku (d3)            in progress
        Sekcja z jednym quizem (d2)   one quiz: no figures
          Jedyny quiz (d3)            8,5/110,5  8%
    Część druga (d0)                  one quiz: no figures
      Quiz nierozpoczęty (d1)         not started
    Cały kurs (total, first)          3/6   812,5/960,5  85%
    """
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import UserFactory
    from tests.factories import make_pa

    pa = make_pa(client, username)
    pa.language = "pl"
    pa.theme = theme
    pa.save(update_fields=["language", "theme"])
    course = CourseFactory(owner=pa)
    student = UserFactory(
        first_name="Anna", last_name="Nowak", display_name="Anna Nowak"
    )
    EnrollmentFactory(student=student, course=course)

    def node(parent, kind, title, **kw):
        kw.setdefault("unit_type", None)
        return ContentNodeFactory(
            course=course, parent=parent, kind=kind, title=title, **kw
        )

    def quiz(parent, title):
        return node(parent, "unit", title, unit_type="quiz")

    def submitted(unit, score, max_score):
        QuizSubmission.objects.create(
            student=student,
            unit=unit,
            status=QuizSubmission.Status.SUBMITTED,
            score=Decimal(score),
            max_score=Decimal(max_score),
        )

    chapter = node(node(None, "part", "Część pierwsza"), "chapter", "Rozdział z sekcjami")
    full = node(chapter, "section", "Sekcja pełna")
    submitted(quiz(full, deep_title), "800", "800")
    submitted(quiz(full, "Mały quiz"), "4", "50")
    awaiting = quiz(full, "Quiz do sprawdzenia")
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
    submitted(awaiting, "0", "0")
    QuizSubmission.objects.create(
        student=student,
        unit=quiz(full, "Quiz w toku"),
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    single = node(chapter, "section", "Sekcja z jednym quizem")
    submitted(quiz(single, "Jedyny quiz"), "8.5", "110.5")
    quiz(node(None, "part", "Część druga"), "Quiz nierozpoczęty")
    return course, student


def _open_results_table(
    page, live_server, client, username, *, width, theme="light", deep_title=RT_LONG_TITLE
):
    course, student = _seed_results_table(
        client, username, theme=theme, deep_title=deep_title
    )
    _login(page, live_server, username)
    page.set_viewport_size({"width": width, "height": 900})
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    page.goto(f"{live_server.url}{path}?mode=results")
    page.wait_for_selector("table.results-table")
    return course, student


def _rt_row(page, title):
    return page.locator("table.results-table tbody tr").filter(
        has=page.locator("th", has_text=title)
    )


def _lines(locator):
    """How many line boxes the element's own text occupies."""
    return locator.evaluate(
        """el => { const r = document.createRange(); r.selectNodeContents(el);
             const tops = new Set();
             for (const b of r.getClientRects()) {
               if (b.width > 0) tops.add(Math.round(b.top));
             }
             return tops.size; }"""
    )


def _text_edges(locator):
    """Gaps between the element's text and its content box: {left, right} in px."""
    return locator.evaluate(
        """el => { const r = document.createRange(); r.selectNodeContents(el);
             const t = r.getBoundingClientRect(); const c = el.getBoundingClientRect();
             const s = getComputedStyle(el);
             const left = c.left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft);
             const right = c.right - parseFloat(s.borderRightWidth) - parseFloat(s.paddingRight);
             return {left: t.left - left, right: right - t.right}; }"""
    )


def _effective_background(locator):
    """The first non-transparent background at or above the element."""
    return locator.evaluate(
        """el => { for (let n = el; n; n = n.parentElement) {
               const c = getComputedStyle(n).backgroundColor;
               if (c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c;
             }
             return null; }"""
    )


def _page_fits(page):
    return page.evaluate(
        "() => document.documentElement.scrollWidth"
        " <= document.documentElement.clientWidth"
    )


def _px(value):
    return float(value.removesuffix("px"))


@pytest.mark.parametrize("width", [1280, 600, 390])
def test_rt_t5d_title_indent_grows_with_depth_at_every_width(
    page, live_server, client, width
):
    _open_results_table(page, live_server, client, f"e2e_rt_indent{width}", width=width)
    rem = page.evaluate(
        "() => parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )
    pads = []
    for depth in range(4):
        cell = page.locator(f"table.results-table tbody th.results-table__d{depth}")
        pads.append(_px(_style(cell.first, "paddingInlineStart")))
    assert all(deeper > shallower for shallower, deeper in pairwise(pads)), pads
    for got, want in zip(pads, RT_DEPTH_REM[width], strict=True):
        assert abs(got - want * rem) < 0.5, (width, pads)


def test_rt_t8a_phone_table_fits_and_keeps_the_title_share(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_phone", width=390)
    # No formula title: a KaTeX formula would set the title column's minimum width.
    assert page.locator("table.results-table .katex").count() == 0
    awaiting = _rt_row(page, "Quiz do sprawdzenia")
    assert awaiting.locator("a.breakdown-unit__review").count() == 1
    assert _page_fits(page)
    wrap = page.locator(".results-table-wrap")
    scroll_w, client_w = wrap.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert scroll_w <= client_w, (scroll_w, client_w)
    title_w = _box(page.locator("table.results-table thead th.results-table__title"))
    share = title_w["w"] / _box(page.locator("table.results-table"))["w"]
    print(f"[rt] title share at 390px: {share:.3f}")
    assert share >= RT_TITLE_SHARE_FLOOR, share
    total = page.locator("tr.results-table__total")
    single_line = (
        total.locator("td").nth(1),  # 812,5/960,5
        total.locator("td").nth(2),  # 85%
        _rt_row(page, RT_LONG_TITLE).locator("td").nth(2),  # 100%
        _rt_row(page, "Rozdział z sekcjami").locator("td").nth(0),  # 3/5
    )
    for cell in single_line:
        assert _lines(cell) == 1, cell.text_content()


def test_rt_t8b_a_long_formula_scrolls_the_table_not_the_page(
    page, live_server, client
):
    _open_results_table(
        page, live_server, client, "e2e_rt_formula", width=390, deep_title=RT_MATH_TITLE
    )
    page.wait_for_selector("table.results-table .katex")
    wrap = page.locator(".results-table-wrap")
    scroll_w, client_w = wrap.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert scroll_w > client_w  # precondition: the formula really widens the table
    assert _page_fits(page)


def test_rt_t8c_numbers_are_right_aligned(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_align", width=1280)
    cells = _rt_row(page, "Mały quiz").locator("td")
    # „4/50" sits under the total's „812,5/960,5", „8%" under „100%": narrower than
    # their columns, so only the alignment decides where the text sits.
    for cell in (cells.nth(1), cells.nth(2)):
        edges = _text_edges(cell)
        assert abs(edges["right"]) <= 1, edges
        assert edges["left"] > 1, edges


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_rt_t13_heading_rows_are_tinted_and_bold_and_headers_align(
    page, live_server, client, theme
):
    _open_results_table(
        page, live_server, client, f"e2e_rt_rows_{theme}", width=1280, theme=theme
    )
    base = _token_colour(page, "--surface-base")
    heading = _rt_row(page, "Sekcja pełna")
    lone_heading = _rt_row(page, "Sekcja z jednym quizem")  # no figures, still a heading
    total = page.locator("tr.results-table__total")
    for row in (heading, lone_heading, total):
        assert "results-table__section" in row.get_attribute("class")
        assert _style(row, "backgroundColor") == base
    quiz_title = _rt_row(page, "Mały quiz").locator("th")
    assert _effective_background(quiz_title) != base
    for cell in (
        heading.locator("th"),
        heading.locator("td").nth(0),
        heading.locator("td").nth(1),
        total.locator("th"),
    ):
        assert int(_style(cell, "fontWeight")) >= 600
    assert int(_style(quiz_title, "fontWeight")) < 600
    assert _style(quiz_title, "textAlign") in ("start", "left")
    headers = page.locator("table.results-table thead th.results-table__num").all()
    assert len(headers) == 2
    for header in headers:  # „Wynik" and „%": each narrower than its column's data
        edges = _text_edges(header)
        assert abs(edges["right"]) <= 1, (header.text_content(), edges)
        assert edges["left"] > 1, (header.text_content(), edges)


def test_rt_t13b_desktop_pills_stay_on_one_line(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_pills", width=1280)
    pills = page.locator("table.results-table .pill").all()
    assert len(pills) == 3  # awaiting, in progress, not started
    for pill in pills:
        assert _lines(pill) == 1, pill.text_content()


def test_rt_t13c_a_coloured_cell_shows_its_band_not_the_tint(page, live_server, client):
    from courses.color_bands import band_style
    from courses.color_bands import default_color_bands

    _open_results_table(page, live_server, client, "e2e_rt_band", width=1280)
    hex_colour = band_style(95, default_color_bands())["bg"]  # Sekcja pełna: 95%
    band = "rgb({}, {}, {})".format(
        *(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    )
    cell = _rt_row(page, "Sekcja pełna").locator("td").nth(2)
    assert _style(cell, "backgroundColor") == band
    assert band != _token_colour(page, "--surface-base")


def test_rt_t13d_the_total_row_has_a_heavier_rule_below(page, live_server, client):
    _open_results_table(page, live_server, client, "e2e_rt_total", width=1280)
    strong = _token_colour(page, "--border-strong")
    cells = page.locator(
        "tr.results-table__total > th, tr.results-table__total > td"
    ).all()
    assert len(cells) == 4
    for cell in cells:
        assert _style(cell, "borderBottomWidth") == "2px"
        assert _style(cell, "borderBottomColor") == strong
```

- [ ] **Step 2: Run them — expect RED**

Run: `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k "test_rt_"`

Expected (no table CSS yet): `rt_t5d` fails (the UA `<th>` padding is not the table values); `rt_t8a` fails (the title share or the wrapper fit — the unstyled pills never wrap); `rt_t8c` fails at `edges["left"] > 1` (UA `<td>` is start-aligned); `rt_t13` fails on `backgroundColor == base`; `rt_t13d` fails on `2px`; `rt_t13c` passes (the inline style exists since Task 5); `rt_t8b` may pass or fail — it is falsified in Step 6 either way; `rt_t13b` may pass (unstyled pills do not wrap).

- [ ] **Step 3: Add the CSS**

In `core/static/core/css/app.css`, replace:

```css
/* Scoped: .pill is global and also sits in the per-question .answers__status strip. */
.breakdown-unit .pill{margin-left:auto}
```

with:

```css
/* Scoped: .pill is global and also sits in the per-question .answers__status strip. */
.breakdown-unit .pill{margin-left:auto}

/* Student page, Results view: one table with section sums (results-table spec §2.4).
   The student page links no page stylesheet, so every rule is here. Padding and
   indentation come in three bands with EQUAL selectors, so source order decides:
   the unconditional rules, then the 640px block, then the 480px block. The depth
   rules are (0,3,0) and beat the (0,1,1) padding shorthand wherever they sit; each
   depth ADDS to the base inline padding. Padding and indentation are the only
   per-band changes at 640px; the 480px block also shrinks the type and lets
   pills wrap. */
.results-table th,.results-table td{padding:.375rem .5rem;border-top:1px solid var(--border-subtle)}
.results-table .results-table__title.results-table__d0{padding-inline-start:.5rem}
.results-table .results-table__title.results-table__d1{padding-inline-start:1.5rem}
.results-table .results-table__title.results-table__d2{padding-inline-start:2.5rem}
.results-table .results-table__title.results-table__d3{padding-inline-start:3.5rem}
@media (max-width:640px){
  .results-table th,.results-table td{padding:.375rem .5rem}
  .results-table .results-table__title.results-table__d0{padding-inline-start:.5rem}
  .results-table .results-table__title.results-table__d1{padding-inline-start:1rem}
  .results-table .results-table__title.results-table__d2{padding-inline-start:1.5rem}
  .results-table .results-table__title.results-table__d3{padding-inline-start:2rem}
}
@media (max-width:480px){
  .results-table{font-size:.875rem}
  .results-table th,.results-table td{padding:.25rem .25rem}
  .results-table .results-table__title.results-table__d0{padding-inline-start:.25rem}
  .results-table .results-table__title.results-table__d1{padding-inline-start:.75rem}
  .results-table .results-table__title.results-table__d2{padding-inline-start:1.25rem}
  .results-table .results-table__title.results-table__d3{padding-inline-start:1.75rem}
  /* Only here does a pill wrap: in a width:1% column it breaks at every space, which
     above this width would be three lines where one fits. The smaller radius keeps
     a wrapped pill from turning into an oval that touches its text. */
  .results-table .pill{font-size:.7rem;padding:.05rem .3rem;white-space:normal;
    border-radius:.5rem;text-align:center}
}
/* position:relative is kept defensively: KaTeX's absolutely positioned .katex-mathml
   escapes a static scroller whenever a formula starts beyond the viewport (e.g. in a
   right-hand column), which this table's title column normally does not do. */
.results-table-wrap{overflow-x:auto;position:relative}
.results-table{width:100%;border-collapse:collapse;background:var(--surface-raised)}
/* overflow-wrap:anywhere breaks text titles; it cannot split a single-run
   formula (the vendored `.katex .base{display:inline-block; white-space:
   nowrap}` makes it one atomic inline box), whose width sets the title
   column's min-content -- the table then scrolls in .results-table-wrap,
   never the page. A MULTI-run formula (a top-level relation or binary
   operator splits it into several `.base` runs) wraps internally instead,
   as KaTeX intends. */
.results-table .results-table__title{overflow-wrap:anywhere}
.results-table .results-table__status{width:1%;white-space:nowrap;text-align:start}
.results-table .results-table__num{width:1%;white-space:nowrap}
/* td, not a bare class: a (0,2,0) class rule would right-align the thead cells too
   and leave the thead rule below with nothing to do. */
.results-table td.results-table__num{text-align:right}
/* A <th> is bold and centred by default (reset.css has no th rule): override by
   SPECIFICITY, never by order. */
.results-table tbody th{text-align:start;font-weight:normal}
.results-table tbody .results-table__section th,
.results-table tbody .results-table__section td{font-weight:600}
.results-table thead th{font-weight:600;text-align:start}
.results-table thead th.results-table__num{text-align:right}
/* --surface-base differs from --surface-raised in BOTH themes; --surface-sunken is
   lighter than the page in light mode and would not read as a tint. */
.results-table__section{background:var(--surface-base)}
/* On the CELLS and 2px wide: in border-collapse the wider border wins over the next
   row's 1px border-top; a same-width row border would lose to the cell border. */
.results-table__total > th,.results-table__total > td{border-bottom:2px solid var(--border-strong)}
/* The base .pill--none colour (--text-tertiary) fails AA, and the phone pill is smaller. */
.results-table .pill--none{color:var(--text-secondary)}
/* Scoped to the table: the Progress view's inline Review link is unchanged (O5). */
.results-table .breakdown-unit__review{display:block}
.results-table-empty{color:var(--text-secondary)}
```

- [ ] **Step 4: Run — expect GREEN, and read the measured share**

```bash
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -rP
uv run pytest tests/test_css_citations_are_durable.py
```

Expected: every test passes, including the pre-existing Progress-mode tests in the file. In the `-rP` output, find `[rt] title share at 390px: 0.xxx` and record the value.

- **STOP (spec §2.4 / T8a floor):** if the share is below `0.300`, do not commit. Ask the owner, giving the measured share and a 390px screenshot of the fixture: the remaining levers (merging or dropping a column) touch O1.
- If the share is below `0.350`, run the nowrap A/B of Step 6 item 5 now. If it goes red, continue and record the margin (share − 0.30) for the PR body; if it does **not** go red, **STOP and ask the owner** (Spec gaps item 2; this is the e2e fixture, where a green A/B is a stop).
- **STOP (spec T8b precondition):** `test_rt_t8b_a_long_formula_scrolls_the_table_not_the_page` asserts `scroll_w > client_w` as a precondition before checking `_page_fits`. `RT_MATH_TITLE` is a single `.base` run (unbreakable), so this should hold; if it still fails on this correct build, stop and report it rather than weakening the assertion, widening the viewport, or lengthening the formula further.

- [ ] **Step 5: Measure the floor on mat-pp before committing it**

The spec's floor must hold on real data too. Serve the worktree against the LOCAL mat-pp copy (no media junction is needed: the Results page has no images).

5a. Confirm `.env` points at the local mat-pp database and DEBUG is on:

```bash
uv run python manage.py shell -c "from django.conf import settings; from django.db import connection; print(settings.DEBUG, connection.settings_dict['NAME'])"
```

Expected: `True` and the database name the main checkout uses. If Django warns about unapplied migrations, **do not run `migrate` from the worktree** (it would rewrite the shared local DB); the warning is harmless for these pages.

5b. Create the throwaway platform admin (idempotent; local DB only; Task 10 deletes it). A PA can open any course's analytics, so no real user's password or settings are touched:

```bash
uv run python manage.py shell -c "
from django.contrib.auth.models import Group
from accounts.models import User
from institution.roles import PLATFORM_ADMIN
from tests.factories import make_verified_user
admin = User.objects.filter(username='rtadmin').first() or make_verified_user(username='rtadmin', email='rtadmin@example.invalid', password='RT-local-only!')
admin.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
User.objects.filter(pk=admin.pk).update(language='pl', theme='light')
print(admin.username, admin.groups.filter(name=PLATFORM_ADMIN).exists())
"
```

Expected: `rtadmin True`. (The snippet contains no backticks and no `$`: inside the double-quoted `-c` string bash would expand them.)

5c. List the mat-pp students with the most submissions and their Results URLs:

```bash
uv run python manage.py shell -c "
from django.db.models import Count
from django.urls import reverse
from courses.models import Course, Enrollment, QuizSubmission
c = Course.objects.get(slug='mat-pp')
top = QuizSubmission.objects.filter(unit__course=c).filter(student__in=Enrollment.objects.filter(course=c).values('student_id')).values('student_id').annotate(n=Count('id')).order_by('-n')[:3]
for row in top:
    print(row['n'], reverse('courses:manage_analytics_student', kwargs={'slug': c.slug, 'student_pk': row['student_id']}) + '?mode=results')
"
```

If `Course.objects.get(slug='mat-pp')` fails, the local slug differs (imports re-slug from the title): list `Course.objects.values_list('slug', 'title')` and substitute it.

5d. Write `<scratchpad>/rt_page.py` with the Write tool (never commit it):

```python
"""Screenshot, and optionally measure, one page of the local server (results-table
plan, Tasks 7, 9). The screenshot always happens; MEASURE only runs when the
final `measure` argument is passed (Results URLs only — every other page never
renders `table.results-table`).

usage: uv run python rt_page.py BASE PATH WIDTH OUT_PNG_OR_DASH USERNAME PASSWORD [measure]
"""

import sys

from playwright.sync_api import sync_playwright

MEASURE = """() => {
  const table = document.querySelector('table.results-table');
  if (!table) return null;
  const title = table.querySelector('thead th.results-table__title');
  const lines = el => { const r = document.createRange(); r.selectNodeContents(el);
    return new Set(Array.from(r.getClientRects()).filter(b => b.width > 0)
      .map(b => Math.round(b.top))).size; };
  const pills = Array.from(table.querySelectorAll('.pill')).map(lines);
  const wrap = table.closest('.results-table-wrap');
  return {
    share: title.getBoundingClientRect().width / table.getBoundingClientRect().width,
    pageFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    wrapFits: wrap.scrollWidth <= wrap.clientWidth,
    katex: table.querySelectorAll('.katex').length,
    maxPillLines: pills.length ? Math.max(...pills) : 0,
  };
}"""

base, path, width, out, username, password = sys.argv[1:7]
measure = len(sys.argv) > 7 and sys.argv[7] == "measure"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": int(width), "height": 900})
    page.goto(f"{base}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state()
    resp = page.goto(f"{base}{path}")
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:  # noqa: S110 - bounded, third-party-only wait
        pass
    if out != "-":
        page.screenshot(path=out, full_page=True)
    status = resp.status if resp else "?"
    print(f"status={status} url={page.url}")
    failed = (resp is not None and resp.status >= 400) or "/accounts/login/" in page.url
    if failed or not measure:
        browser.close()
        sys.exit(1 if failed else 0)
    result = page.evaluate(MEASURE)
    if result is None:
        print(f"width={width} NO TABLE (status={status} url={page.url})")
        browser.close()
        sys.exit(1)
    print(f"width={width} {result}")
    browser.close()
```

The screenshot is taken before any exit, so a page that fails still leaves
its PNG behind. Every run prints `status=<code> url=<url>` and exits
non-zero — with or without `measure` — when the response status is >= 400 or
the page ends on `/accounts/login/…` (an expired session or a bad login):
that failure is caught here rather than misread as a passing screenshot.
Only when the page loaded correctly and `measure` was passed does the script
evaluate `MEASURE`; if it finds no `table.results-table`, it prints
`NO TABLE` with the status and URL and exits non-zero instead of printing
`None` — a failed render (no table) is never a pass for the 30% floor. On a
correctly loaded page without `measure`, the script exits 0 after the
screenshot. Fix the URL, login or enrolment and re-run whenever the exit
code is non-zero.

5e. Start the app from the worktree with the `run` skill (or `Start-Process` running `uv run python manage.py runserver 127.0.0.1:8765 --noreload` from the worktree), record its port with `echo <port> > .env.rt-port` (the `.env*` ignore rule keeps it out of git), then for each URL from 5c:

```bash
uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<url from 5c>" 390 - rtadmin 'RT-local-only!' measure
```

Expected per line: `pageFits: True`, `wrapFits: True` unless `katex > 0` (a formula may scroll the table), and `share ≥ 0.30`. A render with `katex > 0` is not a floor check (a formula sets the title column's width); judge the others. Every URL from 5c is a Results URL, so every invocation here passes `measure`; a `NO TABLE` line (possible only on a `measure` invocation) is never a pass for the 30% floor — fix the URL, login or enrolment and re-run.

- **STOP (spec §2.4 / T8a floor):** if any formula-free mat-pp render has `share < 0.30`, do not commit; ask the owner with the measured shares and the screenshots (`rt_page.py … 390 <scratchpad>/matpp-390.png …`).
- A share below 0.35 → for that mat-pp or throwaway page, temporarily apply the nowrap pill change (Step 6 item 5) to `app.css`, re-run `rt_page.py … 390 … measure` on that same URL and expect a share below 0.30, then revert by hand. If it does not drop below 0.30, this is **recorded, not a stop** (Spec gaps item 2): record the margin — the measured share minus 0.30 — in the PR body. If that page has no wrappable pill (no awaiting-review, in-progress, not-started or submitted pill in its status column; its screenshot shows it), skip the re-measure and record „no pill on page" instead.
- Otherwise keep `RT_TITLE_SHARE_FLOOR = 0.30` (confirmed); record the fixture's and mat-pp's shares for the PR body.

5f. Stop the server the way it was started, then confirm nothing listens: `netstat -ano | grep ":<port> " | grep LISTENING` prints nothing.

- [ ] **Step 6: Falsify (every spec A/B; hand edits in `app.css`)**

For each: apply by hand, run `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py -k "<full test name>"`, observe red for the stated reason, revert by hand. Pass the FULL function names below, never the short ids (`rt_t13` also matches `rt_t13b`/`c`/`d`):

| Item | `-k` |
|---|---|
| 1 | `"test_rt_t5d_title_indent_grows_with_depth_at_every_width and 1280"` |
| 2, 3 | `"test_rt_t5d_title_indent_grows_with_depth_at_every_width and 600"` |
| 4, 5, 6 | `test_rt_t8a_phone_table_fits_and_keeps_the_title_share` |
| 7 | `test_rt_t8b_a_long_formula_scrolls_the_table_not_the_page` |
| 8 | `test_rt_t8c_numbers_are_right_aligned` |
| 9 | `"test_rt_t13_heading_rows_are_tinted_and_bold_and_headers_align and light"` |
| 10–14 | `test_rt_t13_heading_rows_are_tinted_and_bold_and_headers_align` |
| 15 | `test_rt_t13b_desktop_pills_stay_on_one_line` |
| 16 | `test_rt_t13c_a_coloured_cell_shows_its_band_not_the_tint` |
| 17 | `test_rt_t13d_the_total_row_has_a_heavier_rule_below` |

1. *A/B (spec T5d, specificity):* change the unconditional `.results-table .results-table__title.results-table__d1{padding-inline-start:1.5rem}` selector to `.results-table__d1` (0,1,0). → `rt_t5d[1280]` red: the (0,1,1) padding shorthand wins, d1 equals d0. Revert.
2. *A/B (spec T5d, 640 band):* delete the four depth rules inside `@media (max-width:640px)`. → `rt_t5d[600]` red (desktop values). Revert.
3. *A/B (spec T5d, order):* move the whole `@media (max-width:640px){…}` block above the unconditional `.results-table th,.results-table td{…}` rule. → `rt_t5d[600]` red: equal selectors, the later unconditional rules win. Revert.
4. *Falsifier (spec T8a, wrapper fit):* change `.results-table .results-table__title{overflow-wrap:anywhere}` to `.results-table .results-table__title{overflow-wrap:anywhere;white-space:nowrap}`. → `rt_t8a` red on `scroll_w <= client_w` (the long depth-3 title outgrows the wrapper while the page check stays green). Revert.
5. *A/B (spec T8a, pill wrap):* inside `@media (max-width:480px)`, change the pill's `white-space:normal` to `white-space:nowrap`. → `rt_t8a` red on the title share (a one-line „oczekuje na sprawdzenie" pill takes the title column below 30%).
   - If it goes **red**: revert; the test's A/B stands.
   - If it stays **green** at a share ≥ 0.35: revert it, record the in-table pill `white-space:normal` as defensive only (no A/B claimed) in the PR body.
   - If it stays **green** and the correct build's share (Step 4) is below 0.35: revert it and **STOP and ask the owner** (Spec gaps item 2 — on this seeded e2e fixture a green A/B is a stop, unlike the mat-pp / throwaway re-measures of Step 5e and Task 9 Step 2d, which are recorded).
6. *A/B first (spec T8a, number-cell nowrap):* delete `white-space:nowrap` from `.results-table .results-table__num{width:1%;white-space:nowrap}` and run `rt_t8a` at 390px. Their content has no line-break opportunity (UAX #14 LB25), so this likely stays green.
   - If it goes **red** on the single-line assertion: revert; the test's A/B stands.
   - If it stays **green**: revert, and record in the PR body that the number-cell `nowrap` is **defensive only** (no A/B claimed); also replace the rule's line with the two lines `/* nowrap here is defensive: „812,5/960,5" and „100%" have no break opportunity. */` and `.results-table .results-table__num{width:1%;white-space:nowrap}` (the test keeps only its single-line assertion).
7. *A/B first (spec T8b):* change `.results-table-wrap{overflow-x:auto;position:relative}` to `.results-table-wrap{overflow-x:auto}`. This likely stays green here: `.katex-mathml`'s static position falls inside the viewport (the title column), so dropping `position:relative` does not widen the page in this fixture.
   - If it goes **red**: KaTeX's absolute `.katex-mathml` escapes and the page scrolls; revert, the test's A/B stands.
   - If it stays **green**: revert it, and record `position:relative` as defensive only (no A/B claimed) in the PR body.
8. *A/B (spec T8c):* change `.results-table td.results-table__num{text-align:right}` to `text-align:start`. → `rt_t8c` red on `edges["left"] > 1`. Revert.
9. *A/B (spec T13, headers):* delete `.results-table thead th.results-table__num{text-align:right}`. → `rt_t13[light]` red on the header alignment (proves Spec gaps item 1). Revert.
10. *A/B (spec T13, token):* change `.results-table__section{background:var(--surface-base)}` to `var(--surface-sunken)`. → `rt_t13` red on `backgroundColor == base`. Revert.
11. *A/B (spec T13, differs):* change `.results-table{width:100%;border-collapse:collapse;background:var(--surface-raised)}` to drop `background:var(--surface-raised)`. → `rt_t13` red on `_effective_background(quiz_title) != base` in both themes (the body is `--surface-base`). Revert.
12. *A/B (spec T13, weight):* delete the two-line `.results-table tbody .results-table__section th, … td{font-weight:600}` rule. → `rt_t13` red on the section `<th>`, its count/score `<td>` and the total `<th>`. Revert.
13. *A/B (spec T13, specificity not order):* change that rule's selector to `.results-table__section th,.results-table__section td` (0,1,1) and move it to just after `.results-table tbody th{text-align:start;font-weight:normal}`. → `rt_t13` red on the section `<th>` (the (0,1,2) reset wins although it comes first). Revert.
14. *A/B (spec T13, reset):* delete `.results-table tbody th{text-align:start;font-weight:normal}`. → `rt_t13` red on the quiz `<th>` weight and alignment. Revert.
15. *A/B (spec T13b):* add the line `.results-table .pill{white-space:normal}` directly after `.results-table-empty{…}` (unconditional). → `rt_t13b` red (pills break at every space in a `width:1%` column). Revert.
16. *A/B (spec T13c):* in `templates/courses/manage/_results_table_rows.html`, delete the heading row's `{% if item.summary and item.percent is not None %} style="…"{% endif %}` on the % cell. → `rt_t13c` red: the cell's own computed `backgroundColor` is transparent (`rgba(0, 0, 0, 0)`); the tint visible there belongs to the row. Revert.
17. *A/B (spec T13d):* delete `.results-table__total > th,.results-table__total > td{…}`. → `rt_t13d` red (`0px`). Revert.

`git diff` shows only Steps 1 and 3 (plus item 6's comment if it applied). `git status --short` must not list `rt_page.py`, `.env.rt-port` or any PNG.

- [ ] **Step 7: Ruff and commit**

```bash
uv run ruff format tests/test_e2e_analytics_student_pages.py
uv run ruff check --no-cache .
uv run ruff format --check .
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py
git add core/static/core/css/app.css tests/test_e2e_analytics_student_pages.py
git commit -m "style(analytics): the Results table, dense at 480px; computed-style e2e"
```

### Task 8: Help pages, capture scripts, help screenshots

**Files:**
- Modify: `docs/help/teacher/drill-down.md`, `docs/help/teacher/drill-down.pl.md`
- Modify: `tests/capture_help_screenshots.py` (`_u`'s `manage_analytics_student` branch, the `drill-down` entry), `tests/capture_title_math_screenshots.py` (row 11b)
- Modify: `core/static/core/img/help/drill-down.en.png`, `drill-down.pl.png`, `review-queue.pl.png`
- Modify: `courses/geogebra.py` (stale line-number citation only)

**Interfaces:**
- Consumes: the finished pages of Tasks 5–7.
- Produces: `_u("manage_analytics_student", username=…, mode="results")` → the student page URL with `?mode=results`.

**Implements:** O1, O6, O7, O8, O11, O13, O16, O17 (documented and shown).

- [ ] **Step 1: English help**

In `docs/help/teacher/drill-down.md`, replace:

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
```

with:

```markdown
## Results and progress

Click a student's name to open their page for the current course. It opens in
the same view as the matrix you came from, and the heading names that view and
the student. A **Progress / Results** switch under the heading changes the view
without going back:

- **Progress** lists every lesson and quiz. A finished lesson carries a ✓, an
  unfinished one an empty ○, and a lesson that is not required is tagged
  **Additional**. Chapter headings count the required lessons done, as
  **lessons: 1/2**.
- **Results** is a table of the quizzes and of the parts, chapters and sections
  that contain them. A quiz with a score shows its marks and percentage; any
  other quiz shows its status, and one awaiting review links to the review page.
  Every heading that holds more than one quiz shows on its own row a quiz
  fraction such as **1/3**, the summed marks and the percentage, and **Whole
  course** at the top does the same for the whole course. The fraction counts
  the quizzes whose score is included in the sum out of all the quizzes in that
  section, so a quiz still awaiting review is not included yet. The sums and the
  colours of the percentages are the analytics matrix's own, so a heading row
  matches that section's cell in the Results matrix.
```

and replace:

```markdown
page. The **← Student results** link takes you back with your analytics view
unchanged.
```

with:

```markdown
page. The **← Results** or **← Progress** link (it names the view you came
from) takes you back with your analytics view unchanged.
```

Leave the image alt text `![A student's results page](…)` as it is (spec §8).

- [ ] **Step 2: Polish help**

In `docs/help/teacher/drill-down.pl.md`, replace `![Wyniki ucznia](static:core/img/help/drill-down.pl.png)` with `![Wyniki quizów w kursie](static:core/img/help/drill-down.pl.png)`, then replace:

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
```

with:

```markdown
## Wyniki i postęp

Kliknij imię i nazwisko ucznia, aby otworzyć jego stronę w bieżącym kursie.
Otwiera się w tym samym widoku, z którego przyszedłeś w macierzy, a nagłówek
nazywa ten widok i ucznia. Przełącznik **Postęp / Wyniki** pod nagłówkiem
zmienia widok bez powrotu:

- **Postęp** pokazuje wszystkie lekcje i quizy. Ukończona lekcja ma ✓,
  nieukończona puste ○, a lekcja nieobowiązkowa jest oznaczona jako
  **Dodatkowa**. Nagłówki rozdziałów liczą ukończone lekcje obowiązkowe, np.
  **lekcje: 1/2**.
- **Wyniki** to tabela quizów oraz części, rozdziałów i sekcji, które je
  zawierają. Quiz z wynikiem pokazuje punkty i procent; każdy inny quiz pokazuje
  swój stan, a quiz czekający na sprawdzenie ma odnośnik do strony sprawdzania.
  Każdy nagłówek, pod którym jest więcej niż jeden quiz, pokazuje w swoim
  wierszu ułamek quizów, np. **1/3**, sumę punktów i procent, a **Cały kurs** na
  górze robi to samo dla całego kursu. Ułamek to liczba quizów, których wynik
  wliczono do sumy, spośród wszystkich quizów w sekcji, więc quiz czekający na
  sprawdzenie nie jest jeszcze wliczony. Sumy i kolory procentów pochodzą z
  macierzy analitycznej, więc wiersz nagłówka zgadza się z komórką tej sekcji w
  macierzy wyników.
```

and replace:

```markdown
na sprawdzenie prowadzi prosto do strony sprawdzania. Odnośnik **← Wyniki ucznia**
wraca z niezmienionym widokiem analityki.
```

with:

```markdown
na sprawdzenie prowadzi prosto do strony sprawdzania. Odnośnik **← Wyniki** lub
**← Postęp** (nazywa widok, z którego przyszedłeś) wraca z niezmienionym widokiem
analityki.
```

Check the words against the catalog before saving: „Postęp"/„Wyniki" (`Progress`/`Results`), „Dodatkowa" (`Additional`), „Cały kurs" (`Whole course`), „lekcje: 1/2" (`lessons: %(done)s/%(total)s`), „Analityka" (`Analytics`); keep „quiz/quizy", „odnośnik" (never „link") and „sprawdzenie/sprawdzania" (never „ocena").

- [ ] **Step 3: Renamed headings break no anchor; no „ucznia" left in the headings**

```bash
grep -rn "#student-results\|#wyniki-ucznia" templates docs/help courses core tests
grep -n "Wyniki ucznia\|Student results" docs/help/teacher/drill-down.md docs/help/teacher/drill-down.pl.md
```

Expected: both print nothing (spec §8 found no anchor hit on 2026-09-17; a hit is updated to `#results-and-progress` / `#wyniki-i-postep` — confirm the generated slug by opening the help page — and listed in the PR body).

- [ ] **Step 4: The help capture opens Results mode**

In `tests/capture_help_screenshots.py`, replace:

```python
    if name == "manage_analytics_student":
        pk = User.objects.get(username=kwargs["username"]).pk
        return reverse(
            "courses:manage_analytics_student",
            kwargs={"slug": "demo-course", "student_pk": pk},
        )
```

with:

```python
    if name == "manage_analytics_student":
        pk = User.objects.get(username=kwargs["username"]).pk
        url = reverse(
            "courses:manage_analytics_student",
            kwargs={"slug": "demo-course", "student_pk": pk},
        )
        if kwargs.get("mode") == "results":
            url += "?mode=results"
        return url
```

and replace:

```python
        ("manage_analytics_student", {"username": "demo_s1"}),
        ".breakdown__tree",
```

with:

```python
        ("manage_analytics_student", {"username": "demo_s1", "mode": "results"}),
        ".results-table",
```

- [ ] **Step 5: The title-maths capture shoots the Results table too**

In `tests/capture_title_math_screenshots.py`, replace:

```python
            page.wait_for_selector(".breakdown-unit__title .katex")
            shoot(f"title-math-11-{theme}", page.locator(".breakdown__tree"))
```

with:

```python
            page.wait_for_selector(".breakdown-unit__title .katex")
            shoot(f"title-math-11-{theme}", page.locator(".breakdown__tree"))

            # Row 11b: the same page in Results mode -- titles in table <th> cells.
            page.goto(
                _url(
                    "courses:manage_analytics_student",
                    slug=slug,
                    student_pk=student.pk,
                )
                + "?mode=results"
            )
            page.wait_for_selector(".results-table__title .katex")
            shoot(f"title-math-11b-{theme}", page.locator(".results-table-wrap"))
```

Run it: `uv run pytest tests/capture_title_math_screenshots.py -m e2e`. Expected: `1 passed` and `SCREENSHOTS (…)` listing `title-math-11b-light` and `title-math-11b-dark` under `.superpowers/shots/` (gitignored). Open both with the Read tool: the long maths title is typeset inside the table and the table, not the page, scrolls.

- [ ] **Step 6: Help screenshots (manual checklist)**

The capture seeds files under `MEDIA_ROOT`; make sure `media` is not a junction into the main checkout first:

```bash
if [ -L media ]; then MSYS_NO_PATHCONV=1 cmd /c rmdir media; fi
CAPTURE_ONLY=drill-down,review-queue uv run python -m pytest tests/capture_help_screenshots.py
git status --short core/static/core/img/help/
git diff --name-only -- core/static/core/img/help/ | grep -v -e "drill-down\." -e "review-queue\.pl\." | xargs -r git checkout --
git clean -n -- core/static/core/img/help/
git status --short core/static/core/img/help/
```

(`git checkout --` here restores unrelated, byte-churned PNGs the capture rewrote; it never touches the implementation.) Expected final status: at most `drill-down.en.png`, `drill-down.pl.png`, `review-queue.pl.png`; `git clean -n` lists nothing. Open each changed PNG with the Read tool: both drill-down shots show the Results table with „Whole course"/„Cały kurs"; the Polish review queue shows „Oczekuje na sprawdzenie".

- [ ] **Step 7: Fix a stale line citation in `courses/geogebra.py`**

The citation is already off by one on master (it cites line 460; the `# noqa:
S110` handler is at 461), and Step 4 adds three more lines above the handler,
so replace the number with a named reference:

In `courses/geogebra.py`, replace:

```python
        # Precedent for S110 on a handler line: tests/capture_help_screenshots.py:460.
```

with:

```python
        # S110 precedent: capture_help_screenshots.py::test_capture_help_screenshots.
```

- [ ] **Step 8: Run and commit**

```bash
uv run ruff format tests/capture_help_screenshots.py tests/capture_title_math_screenshots.py courses/geogebra.py
uv run ruff check --no-cache .
uv run ruff format --check .
uv run pytest tests/test_help.py tests/test_help_capture_isolation.py
git add docs/help/teacher/drill-down.md docs/help/teacher/drill-down.pl.md tests/capture_help_screenshots.py tests/capture_title_math_screenshots.py core/static/core/img/help/ courses/geogebra.py
git commit -m "docs(help): results and progress, the table's sums; Results-mode captures"
```

Expected: the help tests pass; `git status --short` is clean afterwards except the ignored `media/` directory.

### Task 9: Design pass on mat-pp data, screenshots, branch gate, PR

**Files:**
- Possibly modify: `core/static/core/css/app.css`, templates of Task 5, `tests/test_e2e_analytics_student_pages.py`, help PNGs (only if the design pass changes CSS or markup)
- Scratch (never committed): `<scratchpad>/rt_page.py` (Task 7 Step 5d; re-create it with the same content if this session's scratchpad lacks it), `<scratchpad>/rt_seed_ui.py` (Step 0), screenshots

**Interfaces:**
- Consumes: everything above.
- Produces: the PR.

**Implements:** O1 (the floor and three-line-pill gates), O4, O5 (Progress unchanged), O9, O10 (verified untouched), O11, O12, O13, O14, O15 (screenshots of every changed surface).

- [ ] **Step 0: Serve the worktree on mat-pp, with media, a throwaway PA and a throwaway course**

⚠️ `config/settings/base.py` reads `.env` from the worktree (copied in "Where to work") and `MEDIA_ROOT` is `BASE_DIR / "media"`, which holds mat-pp's images only in the main checkout. The help capture (Task 8) left a REAL `media/` directory here; `mklink` refuses an existing path, so remove it — only if it is a plain directory, never a junction:

```bash
# MSYS_NO_PATHCONV=1 is required: Git Bash rewrites the bare /J switch to J:/.
if [ ! -L media ]; then
  [ -d media ] && rm -rf media
  MSYS_NO_PATHCONV=1 cmd /c mklink /J media "C:\Users\krzys\Documents\Python\own\libli\media"
fi
[ -L media ] || { echo "junction not created"; exit 1; }
uv run python manage.py shell -c "from django.conf import settings; from django.db import connection; print(settings.DEBUG, connection.settings_dict['NAME'], settings.MEDIA_ROOT)"
```

Expected: `True`, the mat-pp database name the main checkout uses, and a `MEDIA_ROOT` whose directory lists mat-pp's files. `git status --short` does not list `.env`, `.env.rt-port` or `media`.

Re-run Task 7 Step 5b's snippet (idempotent) so `rtadmin` exists. Then build the throwaway course, on the LOCAL copy only (prod is never touched). The snippet is idempotent; every question stem starts `RT:` (Task 10's orphan check keys on it); it contains no backticks and no `$`:

```bash
uv run python manage.py shell -c "
from decimal import Decimal
from django.db import transaction
from django.urls import reverse
from accounts.models import User
from courses.models import ContentNode, Course, Element, Enrollment, QuestionElement, ShortTextQuestionElement
from tests.factories import make_verified_user
admin = User.objects.get(username='rtadmin')
course, _ = Course.objects.get_or_create(slug='rt-throwaway', defaults={'title': 'RT throwaway', 'language': 'pl', 'owner': admin})
def node(parent, kind, title, **extra):
    found, _ = ContentNode.objects.get_or_create(course=course, parent=parent, kind=kind, title=title, defaults={'published': True, **extra})
    return found
def fill(unit, build):
    # keyed on existing elements, so a failed run still fills the unit next time
    if unit.elements.exists():
        return
    with transaction.atomic():
        for order, question in enumerate(build()):
            Element.objects.create(unit=unit, content_object=question, order=order)
def marked():
    return [ShortTextQuestionElement.objects.create(stem='<p>RT: stolica Polski?</p>', accepted='Warszawa', max_marks=Decimal('1')), ShortTextQuestionElement.objects.create(stem='<p>RT: stolica Francji?</p>', accepted='Paryż', max_marks=Decimal('1'))]
def essay():
    return [ShortTextQuestionElement.objects.create(stem='<p>RT: opisz zbiór jednym zdaniem.</p>', accepted='x', marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal('2'))]
def two_essays():
    return [ShortTextQuestionElement.objects.create(stem='<p>RT: pytanie otwarte ' + str(n) + '.</p>', accepted='x', marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal('1')) for n in (1, 2)]
def unstarted():
    return [ShortTextQuestionElement.objects.create(stem='<p>RT: nigdy nie otwierany.</p>', accepted='x', max_marks=Decimal('1'))]
section = node(node(node(None, 'part', 'RT część'), 'chapter', 'RT rozdział'), 'section', 'RT sekcja')
quizzes = [(node(section, 'unit', 'RT oceniany', unit_type='quiz'), marked), (node(section, 'unit', 'RT esej', unit_type='quiz'), essay), (node(section, 'unit', 'RT bardzo długi tytuł quizu, który czeka na sprawdzenie', unit_type='quiz'), two_essays), (node(section, 'unit', 'RT nierozpoczęty', unit_type='quiz'), unstarted)]
for unit, build in quizzes:
    fill(unit, build)
lessons = [node(section.parent, 'unit', 'RT lekcja ' + str(n), unit_type='lesson', obligatory=True) for n in (1, 2)]
student = User.objects.filter(username='rtstudent').first() or make_verified_user(username='rtstudent', email='rtstudent@example.invalid', password='RT-local-only!')
User.objects.filter(pk=student.pk).update(language='pl', theme='light')
Enrollment.objects.get_or_create(student=student, course=course)
for unit, _build in quizzes:
    print(unit.title, reverse('courses:quiz_unit', kwargs={'slug': course.slug, 'node_pk': unit.pk}))
for lesson in lessons:
    print(lesson.title, reverse('courses:lesson_unit', kwargs={'slug': course.slug, 'node_pk': lesson.pk}))
print('teacher-results', reverse('courses:manage_analytics_student', kwargs={'slug': course.slug, 'student_pk': student.pk}) + '?mode=results')
print('outline', reverse('courses:course_outline', kwargs={'slug': course.slug}))
print('course-results', reverse('courses:course_results', kwargs={'slug': course.slug}))
"
```

Expected: four quiz lines, two lesson lines, and the three page URLs. Start the app from the worktree with the `run` skill (or `Start-Process` running `uv run python manage.py runserver 127.0.0.1:8765`) and record its port: `echo <port> > .env.rt-port`. Leave it running through Step 2.

The throwaway student's rows must come from REAL answers (never hand-written `QuestionResponse` rows: a fraction that disagrees with the stored answer renders incoherent pages). **After Step 2a's mat-pp captures** (finishing a REVIEW quiz notifies `rtadmin`, whose unread badge would otherwise sit in those headers), drive the real UI with a scratch Playwright script — never by hand, never against prod. It does exactly this:
- as `rtstudent`: **RT oceniany**: answer „Warszawa" and „Londyn", finish the quiz (1/2);
- **RT esej**: type one sentence, finish (awaits review);
- **RT bardzo długi tytuł…**: type a sentence in both questions, finish (awaits review, two questions);
- **RT lekcja 1**: open it and, if it is not already ✓, press **Oznacz jako ukończone** (`Mark as done`); **never open RT lekcja 2** (an empty lesson may auto-complete on opening);
- **never open RT nierozpoczęty**;
- then as `rtadmin`: open the review queue of `rt-throwaway`, review **RT esej** and award **1,5** of 2 marks. Leave the long-titled quiz awaiting review.

Write `<scratchpad>/rt_seed_ui.py` with the Write tool (never commit it). Same conventions as `rt_page.py`: base URL and credentials as arguments, bounded waits, non-zero exit on any failure. Its selectors are the ones the existing e2e tests use: the login form of `rt_page.py`; `form.question__form input[name='answer']` and `[data-finish-btn]` with the confirm dialog accepted, then `**/quiz/results/` (`tests/test_e2e_quiz_finish.py`); `form.unit-progress button[type='submit']` and `[data-unit-done].is-complete` (`tests/test_e2e_courses.py`, `tests/test_e2e_slideshow.py`); the queue's `li.card-list__row` → `a.btn` and the review form's `input[name='earned_marks']` (`templates/courses/manage/review_queue.html`, `review_submission.html`, `tests/test_e2e_review.py`). Each user gets its own browser context, so no logout (whose button label is translated) is needed:

```python
"""Seed the rt-throwaway student's answers and the one review through the real UI
(results-table plan, Task 9 Step 0). LOCAL server only. Idempotent: a quiz that is
already submitted (quiz_unit redirects to its results), a lesson already complete
and a review already saved are skipped. Exits non-zero on any failure. (ASCII
only here: print(__doc__) must not abort on a cp1250 console.)

usage: uv run python rt_seed_ui.py BASE STUDENT PASSWORD ADMIN ADMIN_PASSWORD \
       OCENIANY_PATH ESEJ_PATH LONG_PATH LEKCJA1_PATH
"""

import sys

from playwright.sync_api import sync_playwright

TIMEOUT = 10000  # ms, every wait is bounded


def login(browser, base, username, password):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(TIMEOUT)
    page.goto(f"{base}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_load_state()
    if "/accounts/login/" in page.url:
        raise RuntimeError(f"login failed for {username}")
    return page


def open_ok(page, url):
    resp = page.goto(url)
    if resp is None or resp.status >= 400 or "/accounts/login/" in page.url:
        raise RuntimeError(f"{url}: status={resp.status if resp else '?'} url={page.url}")


def finish_quiz(page, base, path, answers):
    open_ok(page, f"{base}{path}")
    if page.url.endswith("/quiz/results/"):
        print(f"skip (already submitted): {path}")
        return
    page.wait_for_selector("form.question__form")
    forms = page.locator("form.question__form")
    if forms.count() != len(answers):
        raise RuntimeError(f"{path}: {forms.count()} questions, expected {len(answers)}")
    for n, answer in enumerate(answers):
        forms.nth(n).locator("input[name='answer']").fill(answer)
    page.once("dialog", lambda d: d.accept())  # the Finish confirm
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/")
    print(f"finished: {path}")


def main(base, student, password, admin, admin_password, oceniany, esej, long_quiz, lekcja1):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = login(browser, base, student, password)
        finish_quiz(page, base, oceniany, ["Warszawa", "Londyn"])
        finish_quiz(page, base, esej, ["Zbiór to kolekcja elementów."])
        finish_quiz(page, base, long_quiz, ["Pierwsza odpowiedź.", "Druga odpowiedź."])
        open_ok(page, f"{base}{lekcja1}")
        page.wait_for_selector("[data-unit-done]")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:  # noqa: S110 - bounded, third-party-only wait
            pass
        if page.locator("[data-unit-done].is-complete").count() == 0:
            try:
                page.locator("form.unit-progress button[type='submit']").click()
            except Exception:  # a timeout here can mean progress.js already auto-completed
                if page.locator("[data-unit-done].is-complete").count() == 0:
                    raise
        page.wait_for_selector("[data-unit-done].is-complete")
        print(f"lesson done: {lekcja1}")
        page.context.close()

        page = login(browser, base, admin, admin_password)
        open_ok(page, f"{base}/manage/courses/rt-throwaway/review-queue/")
        # "RT esej" is not a substring of the long quiz's title, so this is one row.
        row = page.locator("li.card-list__row").filter(has_text="RT esej")
        if row.count() == 0:
            print("skip (RT esej is not awaiting review)")
        else:
            row.locator("a.btn").click()
            page.wait_for_url("**/review/*/")
            marks = page.locator("input[name='earned_marks']")
            if marks.count() != 1:
                raise RuntimeError(f"RT esej review: {marks.count()} marks inputs, expected 1")
            # type=number takes a dot decimal, and ReviewResponseForm's DecimalField is
            # not localized: "1.5" is the value it parses (pages show it as „1,5").
            marks.fill("1.5")
            with page.expect_navigation() as nav:
                page.locator("form:has(input[name='earned_marks']) button[type='submit']").click()
            if nav.value is None or nav.value.status >= 400:
                raise RuntimeError(f"review save: status={nav.value.status if nav.value else '?'}")
            print("reviewed: RT esej 1.5/2")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 10:
        print(__doc__)
        sys.exit(2)
    try:
        main(*sys.argv[1:10])
    except Exception as exc:  # noqa: BLE001 - scratch script: any failure is exit 1
        print(f"FAILED: {exc!r}")
        sys.exit(1)
```

Run it with the four paths from the snippet's output above (the `RT oceniany`, `RT esej`, long-titled quiz and `RT lekcja 1` lines; never pass `RT lekcja 2` or `RT nierozpoczęty`):

```bash
uv run python <scratchpad>/rt_seed_ui.py http://127.0.0.1:<port> rtstudent 'RT-local-only!' rtadmin 'RT-local-only!' "<RT oceniany path>" "<RT esej path>" "<long-titled quiz path>" "<RT lekcja 1 path>"
```

Expected: exit code 0 and `finished:` (or `skip`) lines for the three quizzes, `lesson done:`, and `reviewed: RT esej 1.5/2` (or its `skip`). A non-zero exit: fix the cause and re-run (the script is idempotent).

Then verify the stored state, read-only (no backticks, no `$`):

```bash
uv run python manage.py shell -c "
from decimal import Decimal
from accounts.models import User
from courses.models import ContentNode, QuestionResponse, QuizSubmission, UnitProgress
student = User.objects.get(username='rtstudent')
problems = []
def sub(title):
    unit = ContentNode.objects.get(course__slug='rt-throwaway', title=title)
    return QuizSubmission.objects.filter(student=student, unit=unit).first()
def check(label, ok):
    print(label, 'OK' if ok else 'MISMATCH')
    if not ok:
        problems.append(label)
s = sub('RT oceniany')
check('RT oceniany submitted 1.00/2.00', s is not None and s.status == 'submitted' and (s.score, s.max_score) == (Decimal('1.00'), Decimal('2.00')))
s = sub('RT esej')
check('RT esej submitted 1.50/2.00', s is not None and s.status == 'submitted' and (s.score, s.max_score) == (Decimal('1.50'), Decimal('2.00')))
check('RT esej REVIEW response reviewed', s is not None and QuestionResponse.objects.filter(submission=s, reviewed_at__isnull=False).count() == 1)
s = sub('RT bardzo długi tytuł quizu, który czeka na sprawdzenie')
check('long quiz submitted, 2 unreviewed REVIEW responses', s is not None and s.status == 'submitted' and QuestionResponse.objects.filter(submission=s, reviewed_at__isnull=True).count() == 2 and not QuestionResponse.objects.filter(submission=s, reviewed_at__isnull=False).exists())
check('RT nierozpoczety has no submission', sub('RT nierozpoczęty') is None)
done_lessons = sorted(UnitProgress.objects.filter(student=student, unit__course__slug='rt-throwaway', unit__unit_type='lesson', completed=True).values_list('unit__title', flat=True))
check('completed lessons are exactly RT lekcja 1: ' + repr(done_lessons), done_lessons == ['RT lekcja 1'])
done_quizzes = sorted(UnitProgress.objects.filter(student=student, unit__course__slug='rt-throwaway', unit__unit_type='quiz', completed=True).values_list('unit__title', flat=True))
expected_quizzes = sorted(['RT oceniany', 'RT esej', 'RT bardzo długi tytuł quizu, który czeka na sprawdzenie'])
check('completed quizzes are exactly the three finished quizzes: ' + repr(done_quizzes), done_quizzes == expected_quizzes)
if problems:
    raise SystemExit(1)
"
```

Expected: seven `OK` lines and exit code 0. (The printed labels are ASCII on purpose: a cp1250 console aborts on some Unicode prints.) **If any line says `MISMATCH` or the exit code is non-zero: STOP, fix the seed (on this local throwaway course only), re-run the script and this check.** Note: the plan left the essay answers' wording open; the script fixes „Zbiór to kolekcja elementów." and „Pierwsza/Druga odpowiedź." — any text works, since REVIEW answers are not auto-marked and no screenshot or figure depends on them.

The throwaway course now carries, at depth 3, a scored quiz, a REVIEW-only scored quiz (1,5/2), a quiz awaiting review with a long title and its „Sprawdź" link, and a not-started quiz; the student's outline shows „lekcje: 1/2" (O12); their `quiz_results.html` for the long-titled quiz shows „2 pytania oczekują na sprawdzenie (do 2 dodatkowych punktów)" (O14); their `course_results.html` shows „1,5 / 2" for RT esej (O15) and „Oczekuje na sprawdzenie" (O13).

- [ ] **Step 1: `frontend-design` pass**

Invoke the `frontend-design:frontend-design` skill on the Results table as built (spec §9: after the markup exists, before screenshots are judged). Scope: spacing, type scale, vertical alignment and colour of `.results-table*`, `.results-table-empty` and the chip only. It must not touch the Progress view's layout (O5), the options table (O9, O10), a column or a row kind (O1, O11), or any owner-decided wording. Any change to a rule an e2e test pins must keep that test green: re-run `uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py` after applying. After any template or `.py` edit, restart the server (stop it, confirm the port is free, start it again) before shooting or re-shooting; CSS changes are served fresh without a restart.

- [ ] **Step 2: Screenshots, measured, judged**

2a. **As `rtadmin`, on mat-pp, before any `rtstudent` quiz is finished** — for the top student URL of Task 7 Step 5c, and for one per-question page reached from a quiz title link in the table (open that Results page in a browser as `rtadmin` and copy the `href` of an `a.breakdown-unit__link` for a submitted quiz):

```bash
for theme in light dark; do
  uv run python manage.py shell -c "from accounts.models import User; User.objects.filter(username='rtadmin').update(theme='$theme')"
  for width in 1280 600 390; do
    uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<mat-pp results url>" $width <scratchpad>/rt-matpp-results-$theme-$width.png rtadmin 'RT-local-only!' measure
  done
  for width in 1280 390; do
    uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<same url with mode=progress>" $width <scratchpad>/rt-matpp-progress-$theme-$width.png rtadmin 'RT-local-only!'
  done
  uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<per-question url, with its ?…mode=results query>" 1280 <scratchpad>/rt-matpp-question-$theme-1280.png rtadmin 'RT-local-only!'
done
```

(Here `$theme` and `$width` are meant to expand: this is a plain bash loop, not a `-c` string.)

2b. Run Step 0's `rt_seed_ui.py` (the `rtstudent` answers, the lesson and the `rtadmin` review) and then Step 0's read-only verification; continue only on its exit code 0 with seven `OK` lines. Then, as `rtadmin`, for the throwaway teacher page (`teacher-results` URL) in both themes, repeat ONLY the inner `for width in 1280 600 390` Results-URL invocation (with `measure`) — not the Progress or per-question invocations of 2a — using `rt-throwaway-results-…` names.

2c. **As `rtstudent`** (theme via `User.objects.filter(username='rtstudent').update(theme=…)`), light and dark, 1280 and 390: the `outline` URL, the `course-results` URL, and the long-titled quiz's results page (`/courses/rt-throwaway/u/<pk>/quiz/results/`, pk from Step 0's output):

```bash
for theme in light dark; do
  uv run python manage.py shell -c "from accounts.models import User; User.objects.filter(username='rtstudent').update(theme='$theme')"
  for width in 1280 390; do
    uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<outline URL>" $width <scratchpad>/rt-student-outline-$theme-$width.png rtstudent 'RT-local-only!'
    uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<course-results URL>" $width <scratchpad>/rt-student-course-results-$theme-$width.png rtstudent 'RT-local-only!'
    uv run python <scratchpad>/rt_page.py http://127.0.0.1:<port> "<long-titled quiz's results URL>" $width <scratchpad>/rt-student-quiz-results-$theme-$width.png rtstudent 'RT-local-only!'
  done
done
```

2d. **Measure and gate** from the `rt_page.py` output lines. Only Step 2a's and 2b's Results-URL invocations pass `measure` and print a measurement line at all; the Progress, per-question, outline, course-results and quiz_results invocations of 2a/2c never pass `measure`, so they print nothing to gate on here — they contribute PNGs to Step 2e only.
- a `NO TABLE` line (possible only from a `measure` invocation) is never a pass for the 30% floor — fix the URL, login or enrolment and re-run before judging anything else.
- every 390px Results line: `pageFits: True`; `wrapFits: True` unless `katex > 0`; formula-free lines `share ≥ 0.30`.
  - **STOP (T8a floor):** a formula-free render below 0.30 → do not continue; ask the owner with the shares and screenshots (the levers touch O1).
  - A share below 0.35 → for that mat-pp or throwaway page, temporarily apply the nowrap pill change (Task 7 Step 6 item 5) to `app.css`, re-run `rt_page.py … 390 … measure` on that same URL and expect a share below 0.30, then revert by hand. If it does not drop below 0.30, this is **recorded, not a stop** (Spec gaps item 2): record the margin — the measured share minus 0.30 — in the PR body. If that page has no wrappable pill (no awaiting-review, in-progress, not-started or submitted pill in its status column; its screenshot shows it), skip the re-measure and record „no pill on page" instead.
- every 600px and 1280px Results line: `maxPillLines: 1` (pills on one line above 480px).
- the 390px throwaway line: `maxPillLines` is expected to be 2–3 („oczekuje / na / sprawdzenie").
  - **STOP (three-line pills, spec §2.4):** open `rt-throwaway-results-light-390.png` and `…-dark-390.png` and judge whether the three-line awaiting pill with „Sprawdź" under it reads acceptably. If it does not, ask the owner with both screenshots before changing anything: the alternatives touch O1.

2e. **Judge by eye**, with the Read tool, every PNG, dark on its own terms: the sums read clearly at full depth (the owner's stated worry); the heading tint is visible against quiz rows in both themes; the 2px rule under „Cały kurs" visibly wins over the next row's 1px border (Spec gaps item 3); coloured % cells keep readable text; the `pill--none` text is legible (contrast with `--text-secondary`); the Progress view looks as before apart from „lekcje: …" (O5); the per-question back link reads „← Wyniki"; the student's outline chip, `course_results.html` and `quiz_results.html` show O12–O15's wording and figures. Fix what is wrong (design-level only, Step 1's scope) and re-shoot. After any template or `.py` edit, restart the server (stop it, confirm the port is free, start it again) before shooting or re-shooting; CSS changes are served fresh without a restart.

**Restore the throwaway users' themes** is unnecessary (Task 10 deletes them). No real user's setting was changed.

**Stop the server now**, the way it was started, and confirm nothing listens: `netstat -ano | grep ":<port> " | grep LISTENING` prints nothing.

- [ ] **Step 3: O9 and O10 — the options table is untouched**

```bash
git diff origin/master -- core/static/core/css/app.css | grep -n "answers__option" || echo "no options-table CSS change"
git diff origin/master -- templates/courses/manage/analytics_student_quiz.html | grep "^[-+][^-+]"
```

Expected: `no options-table CSS change`; the template diff shows only the back-link line (`-` „Student results", `+` the mode branch).

- [ ] **Step 4: Commit the design-pass fixes**

If `git status --short` is clean, skip this step. Otherwise:

```bash
uv run ruff format <every .py file changed in Steps 1-2>
uv run ruff check --no-cache .
uv run ruff format --check .
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py
uv run pytest tests/test_analytics_student_page.py tests/test_analytics_student_quiz.py tests/test_review_wording_pl.py
```

If a msgid changed, run the Catalog procedure. If any CSS or template changed, the Task 8 help screenshots are stale: remove the junction first — `if [ -L media ]; then MSYS_NO_PATHCONV=1 cmd /c rmdir media; elif [ -d media ]; then rm -rf media; fi` — then re-run Task 8 Step 6's capture-and-restore commands exactly and include the kept PNGs. Then:

```bash
git status --short   # stage EVERY file listed -- nothing else should be dirty
git add core/static/core/css/app.css templates/courses/ courses/ docs/help/ locale/ tests/ core/static/core/img/help/
git commit -m "style(analytics): design pass on the Results table"
git status --short
```

Expected: `git status` is clean (the rebase in Step 6 refuses a dirty tree, and the gate must test what gets pushed).

- [ ] **Step 5: Branch gate**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
uv run pytest tests/test_[a-f]*.py
uv run pytest tests/test_[g-o]*.py
uv run pytest tests/test_[p-z]*.py tests/demo tests/lal_import
uv run pytest accounts courses core demo grouping institution integrations notes notifications support tags
uv run pytest -m e2e tests/test_e2e_analytics_student_pages.py tests/test_e2e_analytics.py tests/test_e2e_results.py tests/test_e2e_review.py tests/test_e2e_unit_nav.py tests/test_e2e_outline_tree.py tests/test_e2e_quiz.py tests/test_e2e_quiz_math.py tests/test_e2e_questions_2diii.py tests/test_e2e_demo_tab.py
```

Expected: fuzzy counts `0`; every summary line `N passed` with no `failed`/`error` (read the line, not the exit code). If an e2e fails, re-run it alone before believing it (parallel-load flakes are known); a real failure is fixed, not retried away.

- [ ] **Step 6: Rebase, push, open the PR**

```bash
git fetch origin
git rebase origin/master
```

On ANY conflict in `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`:
  1. Take master's side of all four catalog files: `git checkout --ours -- locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.mo`. ⚠️ During a rebase `--ours` is the branch being rebased ONTO (master).
  2. Re-run the full Catalog procedure, overwriting the msgstr of **every row of the Global Constraints table now present in the `.po`**.
  3. `git add locale/` and `git rebase --continue`.

Never hand-merge a `.po` or a `.mo`. If the rebase replayed anything, re-run the **whole** Step 5 gate before pushing.

```bash
git push -u origin feat/analytics-results-table
gh pr create --base master --title "Analytics: the student Results view is a table with section sums" --body-file <scratchpad>/pr-results-table.md
```

PR body (`<scratchpad>/pr-results-table.md`): what changed per O-row (O1–O17, O9/O10 verified untouched); the one scoring rule and its visible effect (a fully reviewed REVIEW-only quiz is now scored in the pill, the per-question header, the table and the student's `course_results.html`, deliberately overriding the student-pages spec §2.8); new, re-translated and dropped msgids (the Global Constraints table); the existing-test inventory outcome (re-pointed: `test_t6_…`, `test_t7_…`, `test_t27_…`, `test_t37_…quiz_titles…`; retired: both `test_t28b_…`, with successors `test_rt_t9_…` / `test_rt_t10_…`); the measured title shares (e2e fixture, mat-pp, throwaway) against the 30% floor and the margin; whether the number-cell `nowrap` is A/B-backed or defensive only (Task 7 Step 6 item 6); the three-line-pill judgement; the plan's Spec gaps items 1–5; the kept help PNGs; then the attribution lines:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01H8rDB1pzsmrm9bdn8PwGw2
```

Commit messages in this plan end with the session's attribution lines when the executing session's instructions require them.

### Task 10: Clean up after the PR merges

**Implements:** — (housekeeping; no owner row).

**Precondition:** no process runs from the worktree: `netstat -ano | grep ":$(cat C:/Users/krzys/Documents/Python/own/libli-results-table/.env.rt-port) " | grep LISTENING` prints nothing (skip the check if `.env.rt-port` does not exist).

- [ ] **Step 0: Delete the throwaway course and users (local copy only)**

From the worktree (its `.env` points at the local mat-pp DB), before Step 1 removes anything:

```bash
uv run python manage.py shell -c "from accounts.models import User; from courses.models import Course; from notifications.models import Notification; print(Notification.objects.filter(data__course_slug='rt-throwaway').delete()); c = Course.objects.filter(slug='rt-throwaway').first(); print(c.delete() if c else 'no course'); print(User.objects.filter(username__in=['rtstudent', 'rtadmin']).delete())"
```

⚠️ Delete the course through the INSTANCE (`c.delete()`), never `Course.objects.filter(...).delete()`: `Course.delete` removes the concrete question rows first, and a queryset delete skips it, orphaning them. Expected: the notification tuple counts the review notifications of `rt-throwaway` (≥ 2 if Task 9 ran); the course tuple includes `'courses.Course': 1` plus cascaded rows (it does not list the question models, which `Course.delete` removed before the cascade it prints); the user tuple includes `'accounts.User': 2` (or `1` if Task 9 never created `rtstudent`). `no course` or `(0, {})` for the users means the wrong database or an already-cleaned copy — check `.env` before going on. Then prove nothing was orphaned:

```bash
uv run python manage.py shell -c "from accounts.models import User; from courses.models import ShortTextQuestionElement; from notifications.models import Notification; print(ShortTextQuestionElement.objects.filter(stem__contains='RT:').count(), Notification.objects.filter(data__course_slug='rt-throwaway').count(), User.objects.filter(username__in=['rtstudent', 'rtadmin']).count())"
```

Expected: `0 0 0`.

- [ ] **Step 1: Remove the `media` link or directory — junction-aware**

From the worktree:

```bash
if [ -L media ]; then MSYS_NO_PATHCONV=1 cmd /c rmdir media; elif [ -d media ]; then rm -rf media; fi
ls -d media 2>/dev/null && echo "media still present - stop" || echo "media gone"
ls C:/Users/krzys/Documents/Python/own/libli/media | head -3
```

⚠️ A junction is removed ONLY with `cmd /c rmdir`: `rm -rf` follows it and deletes the main checkout's `media/` (mat-pp's images). Expected: „media gone", and the last command still lists files in the main checkout's media.

- [ ] **Step 2: Remove the worktree and the merged branch**

From the main checkout, with no shell's cwd inside the worktree:

```bash
gh pr view feat/analytics-results-table --json state -q .state
```

Expected: `MERGED`. **If not, stop** — `git branch -d` is not a safety check here (the branch tracks its pushed upstream). Then:

```bash
git -C C:/Users/krzys/Documents/Python/own/libli worktree remove C:/Users/krzys/Documents/Python/own/libli-results-table
git -C C:/Users/krzys/Documents/Python/own/libli branch -d feat/analytics-results-table
```

`worktree remove` refuses if the tree is dirty (the copied `.env` and `.env.rt-port` are ignored and do not block it) or if a process still holds its files.

---

## Coverage

| Spec item | Task |
|---|---|
| T1 | 3 (data vs grid); 5 (rendered via T5b cells) |
| T1b | 1 (helper unit test + mutant), 3 (data), 5 (rendered row) |
| T1c | 3 (data, section and total), 5 (rendered, section and total) |
| T2 | 3 (data + `>= 1` mutant), 5 (rendered + `summary`-conjunct mutant) |
| T3 | 3 (vs grid overall + one-quiz total), 5 (first row, no total row) |
| T4 | 3 (grid, `hide`/`keep` mutants), 5 (other student's draft renders „nie rozpoczęto") |
| T5 | 3 (data + container mutant), 5 (rendered „1/2") |
| T5b | 5 |
| T5c | 5 (both course shapes, RANK mutant) |
| T5d | 7 |
| T5e | 5 |
| T6 | 4 (colours in context, both mutants), 5 (inline style) |
| T7 | 3 (no keys, stamp mutant), 4 (colour-walk mutants), 5 (no table class, tree + markers) |
| T7b | 5 |
| T8a | 7 (+ floor on mat-pp, Step 5), 9 (re-measured, Step 2d) |
| T8b | 7 |
| T8c | 7 |
| T8d | 5 |
| T9 | 5 (heading, `<title>`), 5 (back link, with T10) |
| T10 | 5 |
| T10b | 1 (header + mutants), 5 (header equals table row) |
| T10c | 5 |
| T10d | 1 |
| T11 | 6 (teacher chip, outline both arms, catalogs) |
| T13 | 7 |
| T13b | 7 |
| T13c | 7 |
| T13d | 7 (+ painted width judged in 9) |
| T14 | 6 |
| T15 | 2 |
| §2.1 invariant (`rows_by_unit[...]` raises) | 3 |
| §2.2 colour walk | 4 |
| §2.3 markup, empty view, `<th>` row headers, total row | 5 |
| §2.4 CSS (every rule) | 7 |
| §2.5 accessibility (caption, row/col headers, region only with maths) | 5 |
| §3.1 heading and `<title>` | 5 |
| §3.2 back link + `mode` in context; `Student results` dropped | 5 |
| §3.3 chip, dead guard removed, `required` dropped | 6 |
| §4 `quiz_score_view`, `_quiz_pill`, `graded` comment, `course_results.html` | 1, 2 |
| §5 interface text, catalog with `--no-obsolete` | 5, 6 |
| §6 options table unchanged | 9 (Step 3) |
| §7 existing-test inventory | 5 (table), 1 (`test_t27`) |
| §7 screenshots (mat-pp, light/dark, 1280/390; plus 600) | 9 |
| §8 help pages, alt text, link text, fraction sentence | 8 |
| §8 capture scripts (`_u` mode, `.results-table` wait; title-maths row 11b) | 8 |
| §8 quiz-review.pl.md, `docs/help` grep, review-queue PNG | 6, 8 |
| §8 anchor grep | 8 |
| §9 one PR, worktree, falsified tests, design pass | Where to work, 9 |
| §10 risks: grid comparison, student-facing screenshots, owner rows | 3, 9, Global Constraints |

| Owner row | Tasks (Implements) |
|---|---|
| O1 | 5, 7, 8, 9 |
| O2 | 3, 5 |
| O3 | 1, 3 |
| O4 | 4, 5, 7, 9 |
| O5 | 3, 4, 5, 7, 9 |
| O6 | 6, 8 |
| O7 | 5, 8 |
| O8 | 5, 8 |
| O9 | 9 |
| O10 | 9 |
| O11 | 3, 5, 7, 8, 9 |
| O12 | 6, 9 |
| O13 | 6, 8, 9 |
| O14 | 6, 9 |
| O15 | 2, 9 |
| O16 | 1, 3, 8 |
| O17 | 3, 5, 8 |
