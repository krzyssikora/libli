# PR notes — previewer unit completion

Paste this file into the PR body:

```bash
gh pr create --body-file docs/superpowers/plans/2026-07-26-previewer-unit-completion-pr-notes.md
```

An explicit "Mark as done" click now persists for a non-enrolled viewer who can
access the course (author, course owner, teacher of a live group). The write gate
in `courses/views.py::complete` drops its `is_enrolled` wrapper and keeps
`can_access_course` as its sole guard; `build_lesson_context` assigns
`progress = state_row` so the resulting row actually re-renders. Passive GETs are
unchanged: a previewer who merely opens a lesson still gets no `UnitProgress` row.

---

## The unguarded half of the diff — seven comment edits no test covers

Six of these are prose in `courses/views.py` and one is a `{% comment %}` block in
`templates/courses/_lesson_article.html`. **No automated gate covers any of them.**
The atomic-block re-fetch that comment #1 documents is byte-identical to the
collapsed `get_or_create` form in every sequential test, so review of this prose is
the only thing protecting it. Read them as part of the diff, not around it.

### 1. NEW — the atomic block in `complete()` (`courses/views.py`)

```python
    with transaction.atomic():
        # Re-read under the lock instead of keeping get_or_create's instance. The rule
        # here is ORDERING, not exclusion: on PostgreSQL a plain UPDATE already blocks
        # on an existing FOR UPDATE, so the lock is not about which writers opt into
        # it. What FOR UPDATE cannot do is protect a writer whose READ happened before
        # the lock -- that writer carries a stale row across the block and writes it
        # back afterwards, losing the update. That is why save_element_state locks
        # BEFORE it reads, and why seen -- which does not -- can still lose one.
        # Collapsing this back to `progress, _ = get_or_create(...)` is byte-identical
        # in every sequential test, so this comment is the only thing protecting the
        # re-fetch.
```

**Gate check — PASSES.** It asserts the ordering rule positively ("What FOR UPDATE
cannot do is protect a writer whose READ happened before the lock"), and it
explicitly *rejects* the lock-exclusion framing rather than endorsing it ("The rule
here is ORDERING, not exclusion: on PostgreSQL a plain UPDATE already blocks on an
existing FOR UPDATE, so the lock is not about which writers opt into it"). The false
claim — that a lock only excludes writers that also take it — is named and denied,
which is the correct way to mention it.

### 2. NEW — the access check in `complete()` (`courses/views.py`)

```python
    # can_access_course is DELIBERATELY the sole guard on this write: the row is the
    # viewer's OWN record, not course analytics, so any viewer who can open the lesson
    # may mark it done -- the same reversal PR #136 applied to element_state_save.
    # Do not "restore" an enrollment check here; both directions are pinned by
    # tests/test_courses_progress.py (see test_unrelated_logged_in_user_is_denied).
```

### 3. CORRECTION — `element_state_save()` (`courses/views.py`)

```python
    # Practice state is personal self-tracking (ungraded, absent from analytics), so
    # ANY viewer who can access the lesson persists their own -- not just enrolled
    # students. This deliberately diverges from seen/quiz, which ignore previewers so
    # authors don't pollute their own SCROLL-tracking and quiz analytics. It is those
    # two specifically, NOT progress writes in general: an explicit "Mark as done"
    # click now persists for previewers too (see complete()). The can_access_course
    # gate above is the only guard the write needs.
```

### 4. CORRECTION — `build_lesson_context()`'s docstring (`courses/views.py`)

```python
    """Shared element/has_*/progress context for a LESSON unit. Reached through
    full_lesson_render_context, which serves every render site (see its docstring --
    do not re-enumerate them here, or the list drifts in two places).
    Enrolled: UnitProgress.get_or_create + seen-count, as a normal view. Non-enrolled
    but authorised: a read-only .filter().first() lookup that feeds practice state and
    the completion pill without creating a row on a GET."""
```

### 5. CORRECTION — the `elif user.is_authenticated` branch in `build_lesson_context()` (`courses/views.py`)

```python
        # Non-enrolled but can view (author/teacher): read an EXISTING row for their
        # practice state AND the completion pill -- an explicit "Mark as done" click
        # persists for them too (see complete()), and without this assignment the
        # write would land but never re-render. Still .filter().first(), never
        # get_or_create: a passive GET must not mint a row for a previewer.
```

### 6. CORRECTION — the non-enrolled early return in `seen()` (`courses/views.py`)

```python
        # ASYMMETRY, deliberate: SCROLL-tracking is not recorded for a previewer, but
        # completion via the explicit button IS (see complete()). So "untracked" is
        # narrow -- their practice state and their completion both persist; only this
        # signal is dropped. The synthetic response therefore reports completed=False
        # even when a stored row says True: this endpoint's contract is "here is your
        # scroll-tracking", not "here is your progress row". Do not "fix" it to echo
        # the stored row -- that breaks
        # tests/test_courses_progress.py::test_previewer_seen_no_write_and_ignores_stored_completion  # noqa: E501
        # and quietly turns a write-free endpoint into a state reporter.
```

### 7. CORRECTION — the `{% comment %}` block in `templates/courses/_lesson_article.html`

```django
    {% comment %}Completion is auto-tracked FOR ENROLLED STUDENTS ONLY: progress.js
       auto-completes the unit once every element has been seen (Phase-1a). For a
       non-enrolled viewer who can access the course, seen-tracking is never recorded,
       so this pill is not a fallback — it is their ONLY route to completion, and an
       explicit click persists for them (see courses/views.py::complete). For enrolled
       students it remains the no-JS fallback + manual override and the live status
       indicator — progress.js flips it to "✓ Completed" the moment auto-complete
       fires. The form keeps class="unit-progress" (e2e + no-JS POST).{% endcomment %}
```

---

## Falsification roster

Every entry below was driven RED against a named mutation and then restored, with
the restoration verified by an empty `git diff` on the mutated file before the test
was re-run.

| Roster entry | Driven RED by |
|---|---|
| 1(a) | restoring the `if is_enrolled(...)` wrapper around the write in `complete()` |
| 1(b) | the same `is_enrolled` wrapper (its blob assertions are exempt — see below) |
| 2 | deleting `progress = state_row` from `build_lesson_context` |
| 3 (step 1) | making `seen()`'s non-enrolled early return echo the stored row |
| 3 (steps 2–3) | the same mutation, reddening at the step-(3) assertion, not step (1) |
| 5(a) | replacing the `can_access_course` gate with an enrollment check |
| 5(b) | the same gate mutation |
| 5(c) | the same gate mutation |
| 5(d) | the same gate mutation, plus a diff-local mutation that skips the write |
| 6(a) | deleting `progress = state_row` (production code) |
| 6(b) | flipping `{% if progress.completed %}` in the template |
| 7 | deleting `progress = state_row`, checked on the `check_answer` POST re-render |
| 9 (outline) | mutating the outline-badge source; RED on the outline subtree assertion |
| 9 (footer) | second, separate run; RED on the footer counter assertion (`0 > 0`) |
| 10 | run 1 RED on the roster argument fed to `build_progress_matrix`; run 2 RED on the drill-down view-level resolution |
| 11 | removing the `if not progress.completed:` guard in `complete()`; RED on the query-trail assertion only |

**Exempt in writing, with reasons:**

- **8** — no insertion point for the mutation. There is no line of *existing*
  production code whose removal would redden it; inventing a hook to falsify
  against would mean writing new production code, and an invented insertion point
  is a wish, not a falsification.
- **12** — pre-existing regression protection. The diff does not change these
  tests' behaviour, so there is no honest RED recipe.
- **1(c)** — entirely.
- **1(b)'s blob assertions** — these are cover, not guards; they are not expected
  to redden under the `is_enrolled` mutation or any other.

**Test 4 is pre-existing and unchanged.**

---

## Spec label → task → test function

The correspondence is deliberately **not** parallel — spec §7 is Task 5, §8 is
Task 11, §9 is Task 8, §10 is Task 9, §11 is Task 10. Do not reconstruct it from
scratch; use this table.

| Spec label | Task | Test function |
|---|---|---|
| §1(a) | 1 | `test_previewer_complete_persists_and_redirects` |
| §1(b) | 2 | `test_previewer_complete_over_checklist_row_preserves_practice_state` |
| §1(c) | 2 | `test_enrolled_complete_over_existing_row_preserves_state_and_seen_ids` |
| §2 | 3 | `test_previewer_sees_completed_pill_after_marking` |
| §3 | 7 | `test_previewer_seen_no_write_and_ignores_stored_completion` |
| §4 | 12 | `courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row` (pre-existing) |
| §5(a) | 6 | `test_non_staff_course_owner_can_complete` |
| §5(b) | 6 | `test_teacher_of_archived_group_is_denied` |
| §5(c) | 6 | `test_unrelated_logged_in_user_is_denied` |
| §5(d) | 6 | `test_non_staff_teacher_of_live_group_can_complete` |
| §6(a) | 4 | `test_previewer_pre_existing_completed_row_shows_pill_without_posting` |
| §6(b) | 4 | `test_previewer_incomplete_row_still_renders_the_button` |
| §7 | 5 | `test_previewer_completed_pill_survives_no_js_check_answer_rerender` |
| §8 | 11 | `test_previewer_completion_becomes_learner_progress_on_enrollment` |
| §9 | 8 | `test_previewer_mark_lights_outline_badge_and_footer_counter` |
| §10 | 9 | `test_off_roster_previewer_absent_from_matrix_and_drilldown` |
| §11 | 10 | `test_double_complete_post_is_idempotent_and_issues_no_second_update` |
| §12 | 12 | `test_seen_merges_and_autocompletes`, `test_zero_element_unit_completes_only_via_fallback` (pre-existing) |

---

## Verification battery

| Run | Result |
|---|---|
| `uv run pytest courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row -v` | 1 passed |
| `uv run pytest tests/test_courses_progress.py::test_seen_merges_and_autocompletes tests/test_courses_progress.py::test_zero_element_unit_completes_only_via_fallback -v` | 2 passed |
| `uv run pytest -n auto` | **3957 passed**, 0 failed |
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 746 files already formatted |
| `uv run python manage.py makemigrations --check` | No changes detected (no model change) |
| `uv run python manage.py check` | 0 issues |
| `uv run pytest -m e2e tests/test_e2e_slideshow.py tests/test_e2e_unit_head_layout.py tests/test_e2e_unit_nav.py` | **35 passed** |

`tests/test_html_element.py::test_lesson_html_render_query_count_invariant` — the
test most likely to be wrongly blamed, since this change touches
`build_lesson_context` — **passed** in the full run. `progress = state_row` is a
bare assignment of an already-fetched row and issues zero additional queries, so no
base-commit reproduction was needed.

The `-m e2e` marker is mandatory on the e2e run: without it the whole e2e set is
silently deselected and pytest exits 5, which reads like a pass. The 35-passed
count above is the evidence that selection actually happened.

No new e2e test is required — the change has no client-side component, and the full
round trip is observable at the view/template layer by tasks 1, 3 and 5.
