# Phase 3b — Self-enroll catalog: design

**Date:** 2026-06-23
**Status:** Spec (awaiting review)
**Depends on:** Phase 3a (grouping substrate — cohorts, `recompute_enrollment`, enrollment authority in `grouping/services.py`); Phase 1a (`Course.visibility`, `Enrollment.source`, `can_access_course`).

## Goal

Let a student browse a catalog of **open** courses and **enroll themselves**, closing
the enrollment loop that today is teacher-driven only (group assignment). The slice
rides entirely on hooks left inert by earlier phases: `Course.visibility="open"`,
`Enrollment.source="self"`, and `recompute_enrollment`'s immunity to self/manual rows.

## Locked decisions (from brainstorming)

1. **Cohort-gated open courses.** An open course is browsable/self-enrollable only by
   students whose cohort is in that course's allowed set. **Empty set = all students**
   (open means open; selecting cohorts narrows it).
2. **Configured in course settings** by the course owner / anyone with
   `courses.change_course` (CourseAdmin). They *select* from existing cohorts; they do
   not create them.
3. **No unenroll.** Self-enroll is one-way. Only a teacher/admin can remove an
   enrollment. This eliminates the group-reachable downgrade edge cases entirely.
4. **Card + overview modal.** The catalog is a grid of cards; clicking opens a richer
   overview (description, length, subject, language) in a modal, then Enroll. The modal
   body is a server-rendered fragment that degrades to a full detail page when JS is off.
   No unit content is shown pre-enroll.
5. **Filters: subject + language + text search**, applied server-side via GET params
   (same pattern as the roster filter, PR #32).

## Non-goals

- Unenroll / "leave course" (decided out).
- Read-only outline/unit preview before enrolling (overview metadata only).
- A separate "published" flag — `visibility` + the ≥1-unit guard are sufficient.
- Teacher/admin self-enroll flows (staff have no cohort; catalog is student-facing).
- Any analytics/review surface (that is Phase 3c).

## Architecture

### 1. Schema — one migration in `courses`

Add to `Course`:

```python
self_enroll_cohorts = models.ManyToManyField(
    "grouping.Cohort", blank=True, related_name="self_enroll_courses"
)
```

- String reference → no import, no circular dependency (`grouping.models` already
  string-references `courses.Course`). Migration declares a dependency on the latest
  `grouping` migration.
- The M2M lives on `Course` so `CourseForm` (a `ModelForm`) handles it natively, but all
  *behavior* (eligibility, enrollment) lives in `grouping/services.py`, keeping grouping
  the single enrollment authority — the 3a precedent.
- No change to `Enrollment` (`source="self"` already exists) or `visibility`.

### 2. Services — `grouping/services.py`

Three pure-ish functions, co-located with `recompute_enrollment`:

- **`catalog_courses_for(student)` → QuerySet[Course]**
  Eligible open courses for this student:
  `visibility="open"` **AND** (`self_enroll_cohorts` is empty **OR** the student's cohort
  is in `self_enroll_cohorts`) **AND** the course has ≥1 unit
  (`nodes` with `kind="unit"`) — the empty-shell guard. Returns a queryset so the view can
  compose subject/language/search filters and ordering on top. Does **not** exclude
  already-enrolled courses (the view marks those "Enrolled"); the guard is about
  *eligibility to appear*, not enrollment state.

- **`can_self_enroll(student, course)` → bool**
  Authoritative gate, used by BOTH the detail view and the enroll POST (never trust the
  button). True iff the course is in `catalog_courses_for(student)` (open + cohort-eligible
  + has content) and the actor is a student (non-staff). Already-enrolled is allowed to
  pass (idempotent no-op downstream).

- **`self_enroll(student, course)` → Enrollment**
  Atomic `get_or_create(student, course, defaults={"source": "self"})`. Idempotent;
  **no-op if any enrollment already exists** (never downgrades a `group`/`manual` row to
  `self`). Per-call savepoint so a concurrent create can't poison anything. Raises
  `ValidationError` (or returns a sentinel — settle in plan) if `can_self_enroll` is false;
  the view re-checks first regardless.

### 3. Views / URLs — `courses`

- **`catalog` (GET, `login_required`)** — renders the filtered card grid from
  `catalog_courses_for(request.user)`. Annotates each course with its enrollment state so
  the template shows "Enroll" vs. "Enrolled → open outline". Applies subject/language/search
  GET filters server-side.
- **`catalog_detail` (GET, `login_required`)** — the modal body fragment (and full-page
  fallback). Shows overview, subject, language, and **unit count**; gated by
  `can_self_enroll(user, course) or is_enrolled(user, course)` — **not** `can_access_course`,
  because this is pre-enroll. No unit content. A foreign/ineligible course 404s (or 403 —
  settle in plan; prefer 404 to avoid leaking existence of cohort-gated courses).
- **`self_enroll` (POST, CSRF, `login_required`)** — re-checks `can_self_enroll`
  server-side, calls `self_enroll(...)`, redirects to the course outline with a success
  message. Ineligible → redirect back to catalog with an error message (or 403).

### 4. UI

- **Catalog page** — bespoke token-driven card grid (no Bootstrap/React) + a filter bar
  reusing roster filter patterns. Cards: title, subject, language, short overview snippet,
  action button.
- **Overview modal** — small vanilla-JS handler fetches `catalog_detail` into a modal;
  `<noscript>` / no-JS falls back to navigating to the detail page. Modal contains the
  Enroll POST form.
- **Course settings** — add `self_enroll_cohorts` to `CourseForm` as a checkbox list of
  **non-archived** cohorts (`CheckboxSelectMultiple`, matching the roster checkbox pattern
  from PR #29). Meaningful only when `visibility="open"`; help text: "Leave empty = open to
  all students." (Field stays editable regardless; it's simply inert while `visibility="assigned"`.)
- **Navigation** — a "Browse courses" entry: a dashboard card/link plus a main-nav link,
  shown to students. Staff have no cohort, so the catalog naturally limits itself; the link
  is scoped to non-staff to keep the staff UI clean.
- **i18n** — EN + PL for every new string (recurring project requirement; grouping strings
  shipped untranslated in 3a and had to be backfilled).

### 5. Access — unchanged

`can_access_course` already grants on an `Enrollment` row, so post-enroll access works with
no change. `catalog_detail` deliberately bypasses `can_access_course` (pre-enroll) and uses
the catalog eligibility gate instead.

## Edge cases (all benign given the substrate)

| Case | Behavior |
|---|---|
| Course flipped `open`→`assigned` after a student self-enrolled | Enrollment persists (no auto-removal, matches "no unenroll"); course just leaves the catalog. |
| Cohort dropped from `self_enroll_cohorts` after enroll | Enrollment persists (self source immune to re-sync). |
| Open course with no units | Excluded from catalog by the ≥1-unit guard. |
| Already enrolled via group/manual, course also open | Catalog marks "Enrolled"; `self_enroll` is a no-op (no downgrade). |
| Concurrent enroll (double-click / race) | Unique constraint + atomic `get_or_create` → one row. |
| Staff member browsing | No cohort → sees only open courses with an empty cohort set; cannot meaningfully self-enroll (gated to non-staff). |

## Testing

- **Services** — eligibility matrix: `open`/`assigned` × cohort-in/out × empty-set ×
  has-content/empty × already-enrolled. `self_enroll` idempotency and no-downgrade of an
  existing `group`/`manual` row.
- **Views** — catalog filtering (subject/language/search), enroll POST creates
  `Enrollment(source="self")`, ineligible POST rejected, `catalog_detail` visible pre-enroll
  only when eligible (404/403 otherwise), CSRF enforced.
- **Form** — `self_enroll_cohorts` lists only non-archived cohorts; saving persists the M2M.
- **e2e** — browse → open overview modal → Enroll → land on the course outline, driving the
  real click path (per the e2e-must-drive-real-UI lesson; no `page.evaluate` shortcuts).

## Decisions deferred to the implementation plan

- `catalog_detail` and ineligible-POST failure mode: 404 vs 403 (lean 404 to avoid leaking
  cohort-gated course existence).
- Whether `self_enroll` raises `ValidationError` or returns a sentinel on ineligibility
  (view re-checks first either way).
- Exact "unit count" presentation (units only, or units + chapters).
