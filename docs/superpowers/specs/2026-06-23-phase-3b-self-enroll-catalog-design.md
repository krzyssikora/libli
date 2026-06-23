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
   overview (overview text, unit count, subject, language) in a modal, then Enroll. The modal
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
  string-references `courses.Course`). The auto-generated M2M migration must declare a
  dependency on the highest-numbered `grouping` migration at build time (currently
  `grouping.0003_*`, the staff-cleanup migration from 3a) so `grouping.Cohort` exists.
- The M2M lives on `Course` so `CourseForm` (a `ModelForm`) handles it natively, but all
  *behavior* (eligibility, enrollment) lives in `grouping/services.py`, keeping grouping
  the single enrollment authority — the 3a precedent.
- No change to `Enrollment` (`source="self"` already exists) or `visibility`.

### 2. Services — `grouping/services.py`

Three DB-backed services, co-located with `recompute_enrollment`. (They read/write the DB;
only `self_enroll` needs atomicity care.)

**Cross-app field-name asymmetry (footgun):** `Enrollment.student`, but
`CohortMembership.user`. The cohort lookup is `CohortMembership.objects.filter(user=student)`,
NOT `student=`. `access.is_enrolled(user, course)` filters `Enrollment` by `student=user`.

- **`catalog_courses_for(student)` → QuerySet[Course]**
  Eligible open courses for this student. Eligibility joins through the student's cohort
  (`CohortMembership.cohort`, looked up via `user=student`). A student with **no
  `CohortMembership` row** has no cohort and therefore matches only empty-set courses
  (treated as "not in any allowed set").

  Query construction (pins distinct/dedupe semantics):

  ```python
  cohort_id = (
      CohortMembership.objects.filter(user=student)
      .values_list("cohort_id", flat=True).first()
  )  # None if no membership
  has_unit = ContentNode.objects.filter(course=OuterRef("pk"), kind="unit")
  qs = (
      Course.objects.filter(visibility="open")
      .filter(Q(self_enroll_cohorts__isnull=True) | Q(self_enroll_cohorts=cohort_id))
      .filter(Exists(has_unit))
      .distinct()
  )
  ```

  `Q(self_enroll_cohorts__isnull=True)` is the empty-set ("open to all") arm;
  `Q(self_enroll_cohorts=cohort_id)` is the cohort-match arm (with `cohort_id=None` this arm
  matches nothing, so a membership-less student sees only empty-set courses). `.distinct()`
  is **required** — the M2M OR-filter would otherwise emit one `Course` row per matching
  cohort. The ≥1-unit guard uses `Exists(...)` (not a `nodes__kind` join) to avoid
  multiplying rows per unit. Returns a queryset so the view composes subject/language/search
  filters + ordering on top. Does **not** exclude already-enrolled courses (the view marks
  those "Enrolled"); the guard is about *eligibility to appear*, not enrollment state.

- **`can_self_enroll(student, course)` → bool**
  Authoritative gate, used by BOTH the detail view and the enroll POST (never trust the
  button). Defined as: `not is_staff_user(student)` **AND**
  `catalog_courses_for(student).filter(pk=course.pk).exists()`. The non-staff check is an
  *additional* condition `catalog_courses_for` does not enforce — so `can_self_enroll` and
  `catalog_courses_for` **deliberately disagree for staff**: a staff member matches empty-set
  open courses in `catalog_courses_for` (no cohort → the `__isnull` arm hits) but
  `can_self_enroll` is False for them (see the "Staff member browsing" edge case).
  Already-enrolled courses pass the gate (the downstream `self_enroll` is an idempotent no-op).

- **`self_enroll(student, course)` → Enrollment**
  Atomic `get_or_create(student, course, defaults={"source": "self"})`. Idempotent;
  **no-op if any enrollment already exists** (never downgrades a `group`/`manual` row to
  `self`). Per-call savepoint so a concurrent create can't poison anything. The view
  re-checks `can_self_enroll` first; if a course flips `open`→`assigned` in the race window
  between that re-check and the `get_or_create`, the resulting `self` row is **accepted**
  (consistent with "no auto-removal / no unenroll") rather than rolled back — `self_enroll`
  does not re-validate eligibility inside the savepoint. On a direct ineligible call
  (defense in depth) it raises `ValidationError` vs. returns a sentinel — settle in plan.

### 3. Views / URLs — `courses`

- **`catalog` (GET, `login_required`)** — renders the filtered card grid from
  `catalog_courses_for(request.user)`. Enrollment state is computed with **one** query, not
  per-card: `enrolled_ids = set(Enrollment.objects.filter(student=request.user,
  course__in=qs).values_list("course_id", flat=True))`, passed to the template so each card
  shows "Enroll" vs. "Enrolled → open outline" (the latter links to the existing
  `course_outline` route by slug). No N+1.
  **Filters** (GET params, server-side, composed on the `catalog_courses_for` queryset;
  empty/absent params are no-ops):
  - `subject` — `Subject` **pk**; dropdown options = only subjects present in the student's
    eligible set (avoids empty-result filters).
  - `language` — language **code** (the 5-char `COURSE_LANGUAGES` value); options = only
    languages present in the eligible set.
  - `q` — case-insensitive search over **title and overview**
    (`Q(title__icontains=q) | Q(overview__icontains=q)`).
- **`catalog_detail` (GET, `login_required`)** — the modal body fragment (and full-page
  fallback). Shows overview, subject, language, and **unit count**; gated by
  `can_self_enroll(user, course) or is_enrolled(user, course)` — **not** `can_access_course`,
  because this is pre-enroll. No unit content. Because the gate admits already-enrolled
  users (including enrolled-but-no-longer-eligible courses — flipped to `assigned`, or whose
  cohort was dropped), the fragment renders **"open outline" instead of a live Enroll form
  whenever the user is already enrolled** — an enrolled user never sees an Enroll button. A
  foreign/ineligible course 404s (prefer 404 over 403 to avoid leaking the existence of
  cohort-gated courses; settle in plan).
- **`self_enroll` (POST, CSRF, `login_required`)** — re-checks `can_self_enroll`
  server-side, calls the `self_enroll(...)` service, redirects to the course outline with a
  success message. Ineligible → 404 (matching `catalog_detail`; settle 404-vs-403 in plan).

### 4. UI

- **Catalog page** — bespoke token-driven card grid (no Bootstrap/React) + a filter bar
  reusing roster filter patterns. Cards: title, subject, language, short overview snippet,
  action button.
- **Overview modal** — small vanilla-JS handler fetches `catalog_detail` into a modal;
  `<noscript>` / no-JS falls back to navigating to the detail page. Modal contains the
  Enroll POST form (or the "open outline" link when already enrolled, per §3).
- **Course settings** — add `self_enroll_cohorts` to `CourseForm` as a
  `CheckboxSelectMultiple` (matching the roster checkbox pattern from PR #29). The field
  queryset is **non-archived cohorts, UNIONed with any cohorts already selected on this
  course instance** — so a cohort archived *after* selection is still rendered and is not
  silently dropped on the next save (a `ModelMultipleChoiceField` whose queryset excludes a
  currently-selected value treats it as invalid and drops it on submit). The Default cohort
  is offered like any other (selecting it = "open to all", redundant with the empty set but
  harmless). Meaningful only when `visibility="open"`; help text: "Leave empty = open to all
  students." (Field stays editable regardless; it's simply inert while `visibility="assigned"`.)
- **Navigation** — a "Browse courses" entry: a dashboard card/link plus a main-nav link.
  The **views** (`catalog`/`catalog_detail`/`self_enroll`) are `login_required` only and
  degrade naturally for staff (empty/limited catalog, `can_self_enroll` False); the nav
  **link** is merely hidden from staff to keep their UI clean. A staff member reaching the
  catalog by URL is thus well-defined (see edge cases), just unlinked.
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
  has-content/empty × already-enrolled, **plus a student with no `CohortMembership` row**
  (sees only empty-set courses) and **a course with N units and/or N allowed cohorts appears
  exactly once** (the `.distinct()`/`Exists` dedupe). `self_enroll` idempotency and
  no-downgrade of an existing `group`/`manual` row.
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
