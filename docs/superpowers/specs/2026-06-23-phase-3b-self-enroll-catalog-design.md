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
  string-references `courses.Course`). The only ordering constraint is that `grouping.Cohort`
  exists — it is created in `grouping.0001_initial`, and `makemigrations` auto-generates a
  dependency on exactly that migration (an M2M depends on the migration that *creates* the
  referenced model, NOT on the latest grouping migration). No later grouping migration
  (e.g. `0003`) needs to be referenced; do not hand-add one.
- The M2M lives on `Course` so `CourseForm` (a `ModelForm`) handles it natively, but all
  *behavior* (eligibility, enrollment) lives in `grouping/services.py`, keeping grouping
  the single enrollment authority — the 3a precedent.
- No change to `Enrollment` (`source="self"` already exists) or `visibility`.

### 2. Services — `grouping/services.py`

Three DB-backed services, co-located with `recompute_enrollment`. (They read/write the DB;
only `enroll_self` needs atomicity care.) **Naming:** the write service is `enroll_self` —
distinct from the `courses` view named `self_enroll` (§3) so importing it into
`courses/views.py` does not shadow the view.

**Cross-app field-name asymmetry (footgun):** `Enrollment.student`, but
`CohortMembership.user`. The cohort lookup is `CohortMembership.objects.filter(user=student)`,
NOT `student=`. `access.is_enrolled(user, course)` filters `Enrollment` by `student=user`.

**Imports:** the query references `courses.models.{Course, ContentNode, Subject}` and
`django.db.models.{Q, Exists, OuterRef}`. Top-level cross-app imports are safe here —
`grouping/services.py` already does `from courses.models import Enrollment` (grouping→courses
is the established 3a direction; only `grouping.models` string-references `courses` to avoid
the reverse). No in-function import needed.

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
  multiplying rows per unit, and counts all `kind="unit"` nodes regardless of `unit_type`
  (lesson and quiz both qualify). A course restricted to cohorts that exclude the student's is
  correctly dropped: its joined rows are non-null and `!= cohort_id`, so neither `Q` arm
  matches (the test matrix pins this "restricted course, student not in set → excluded" case).
  Returns a queryset; the view then applies an explicit **`.order_by("title")`** (`Course` has
  no `Meta.ordering`; matches the enrolled-courses list at `courses/views.py:158`) so card
  order is deterministic, and composes the subject/language/search filters on top. Does **not**
  exclude already-enrolled courses (the view marks those "Enrolled"); the guard is about
  *eligibility to appear*, not enrollment state.

- **`can_self_enroll(student, course)` → bool**
  Authoritative gate, used by BOTH the detail view and the enroll POST (never trust the
  button). Defined as: `not is_staff_user(student)` **AND**
  `catalog_courses_for(student).filter(pk=course.pk).exists()`. The non-staff check is an
  *additional* condition `catalog_courses_for` does not enforce — so `can_self_enroll` and
  `catalog_courses_for` **deliberately disagree for staff**: a staff member matches empty-set
  open courses in `catalog_courses_for` (no cohort → the `__isnull` arm hits) but
  `can_self_enroll` is False for them (see the "Staff member browsing" edge case).
  Already-enrolled courses pass the gate (the downstream `enroll_self` is an idempotent no-op).

- **`enroll_self(student, course)` → Enrollment**
  Atomic `get_or_create(student, course, defaults={"source": "self"})`. Idempotent;
  **no-op if any enrollment already exists** (never downgrades a `group`/`manual` row to
  `self`). Per-call savepoint so a concurrent create can't poison anything. The view
  re-checks `can_self_enroll` first; if a course flips `open`→`assigned` in the race window
  between that re-check and the `get_or_create`, the resulting `self` row is **accepted**
  (consistent with "no auto-removal / no unenroll") rather than rolled back — `enroll_self`
  **does not re-validate eligibility** inside the savepoint, so the accepted-race path can
  never raise. The 404 for an ineligible request lives **entirely in the view**. The
  service's only failure surface is a programming-error guard; whether that guard raises
  `ValidationError` or returns a sentinel is settle-in-plan and cannot leak a 500 onto the
  accepted-race path.

### 3. Views / URLs — `courses`

- **`catalog` (GET, `login_required`)** — pipeline, in this order: build
  `eligible_qs = catalog_courses_for(request.user)` → derive the filter-option lists from it
  (**unfiltered**) → apply the `subject`/`language`/`q` filters → `.order_by("title")`; the
  result is `qs`, the queryset the cards iterate. Enrollment state is computed with **one**
  query off that same `qs` (not `eligible_qs`): `enrolled_ids = set(Enrollment.objects.filter(
  student=request.user, course__in=qs.values("pk")).values_list("course_id", flat=True))` (the
  `.values("pk")` keeps the `__in` subquery pk-only), passed to the template so each card shows
  "Enroll" vs. "Enrolled → open outline" (the latter links to the existing `course_outline`
  route by slug). `enrolled_ids` therefore covers exactly the rendered cards. No N+1.
  **Filters** (GET params, server-side; empty/absent params are no-ops):
  - `subject` — `Subject` **pk**; dropdown options =
    `Subject.objects.filter(courses__in=eligible_qs.values("pk")).distinct()` (the
    `.values("pk")` keeps the `__in` subquery pk-only, avoiding multi-column/join surprises),
    drawn from the **unfiltered** eligible set so selecting one filter never erases the others'
    options. `Course.subject` is nullable: null-subject courses are naturally absent from this
    dropdown, and a card omits the subject line when `subject is None`.
  - `language` — language **code** (the short `COURSE_LANGUAGES` code, e.g. `en`/`pl`; the
    `Course.language` column is `max_length=5`, which is the column width, not the code length).
    Options = `eligible_qs.values_list("language", flat=True).distinct()`, from the unfiltered
    set; the GET value stays the raw code. Labels resolve **per surface**: dropdown options are
    raw code strings → labels from `dict(COURSE_LANGUAGES).get(code)`; per-card language uses
    `course.get_language_display()` (the card iterates `Course` instances).
  - `q` — case-insensitive search over **title and overview**
    (`Q(title__icontains=q) | Q(overview__icontains=q)`).
- **`catalog_detail` (GET, `login_required`)** — the modal body fragment (and full-page
  fallback). Fragment vs. full page is chosen by the `X-Requested-With: XMLHttpRequest`
  header the modal fetch sends: present → render the bare fragment template; absent (direct
  navigation / no-JS) → render the **same** fragment wrapped in the base layout (so the
  degrade path is a real page, never a chrome-less fragment). Mechanism: one fragment partial,
  `{% include %}`-d by a thin page template for the no-JS path, so modal and fallback share a
  single source. Shows overview, subject,
  language, and **unit count** (`course.nodes.filter(kind="unit").count()` — units only,
  matching the eligibility guard's notion of "unit"); gated by
  `can_self_enroll(user, course) or is_enrolled(user, course)` — **not** `can_access_course`,
  because this is pre-enroll. No unit content. Because the gate admits already-enrolled
  users (including enrolled-but-no-longer-eligible courses — flipped to `assigned`, or whose
  cohort was dropped), the fragment **body branches on `is_enrolled(user, course)`, NOT on
  the gate result**: enrolled → always render the "open outline" link; not-enrolled → render
  the live Enroll form. The precedence is explicit so the "enrolled but `can_self_enroll`
  False" path can never fall through to an Enroll button. Both `catalog_detail` and
  `self_enroll` resolve the course by **slug** (matching `course_outline`):
  `get_object_or_404(Course, slug=...)` then apply the gate — so a non-existent course and an
  ineligible one both converge on 404 (prefer 404 over 403 to avoid leaking the existence of
  cohort-gated courses; settle in plan).
- **`self_enroll` (POST, CSRF, `login_required`)** — re-checks `can_self_enroll`
  server-side, calls the `enroll_self(...)` service, redirects to the course outline with a
  success message — a `{% trans %}`-wrapped string requiring an explicit PL translation (e.g.
  EN "You're now enrolled in {course}."). Ineligible → 404 (matching `catalog_detail`; settle
  404-vs-403 in plan).

### 4. UI

- **Catalog page** — bespoke token-driven card grid (no Bootstrap/React) + a filter bar
  reusing roster filter patterns. Cards: title, subject, language, short overview snippet,
  action button.
- **Overview modal** — small vanilla-JS handler fetches `catalog_detail` into a modal;
  `<noscript>` / no-JS falls back to navigating to the detail page. Modal contains the
  Enroll POST form (or the "open outline" link when already enrolled, per §3).
- **Course settings** — add `self_enroll_cohorts` to `CourseForm` as a
  `CheckboxSelectMultiple` (matching the roster checkbox pattern from PR #29). The field
  queryset is **non-archived cohorts, plus any cohorts already selected on this course
  instance**, expressed as a single filterable `Q`-OR
  (`Cohort.objects.filter(Q(archived=False) | Q(pk__in=selected_pks))`, **not** `.union()` —
  union querysets can't be further filtered/ordered, which `CheckboxSelectMultiple` needs).
  Append the field to `Meta.fields` (after `visibility`) and assign this queryset in the form's
  existing `__init__`. This keeps a cohort that was archived *after* it was selected still
  rendered (and not silently dropped on the next save — a `ModelMultipleChoiceField` whose
  queryset excludes a currently-selected value treats it as invalid and drops it on submit);
  the selected-cohorts arm is a narrow edge, not the common path. The Default cohort is offered
  like any other; selecting it is *approximately* open-to-all given the 3a Default backfill (it
  admits exactly Default members, whereas the empty set admits every student — not an exact
  equivalence, so don't reason from it as an invariant). Meaningful only when `visibility="open"`; help text: "Leave empty = open to all
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
  only when eligible (404/403 otherwise), CSRF enforced, and **a staff user GETting `catalog`
  sees only the empty-set open courses while a staff `self_enroll` POST is rejected (404)** —
  pinning the documented staff divergence. Also pin the highest-risk branch: an **enrolled
  student whose course became ineligible** (flipped to `assigned` / cohort dropped) GETting
  `catalog_detail` → 200 with the "open outline" link and **no** Enroll form.
- **Form** — `self_enroll_cohorts` lists only non-archived cohorts; saving persists the M2M.
- **e2e** — browse → open overview modal → Enroll → land on the course outline, driving the
  real click path (per the e2e-must-drive-real-UI lesson; no `page.evaluate` shortcuts).

## Decisions deferred to the implementation plan

- `catalog_detail` and ineligible-POST failure mode: 404 vs 403 (lean 404 to avoid leaking
  cohort-gated course existence).
- Whether the `self_enroll` programming-error guard raises `ValidationError` or returns a
  sentinel (view re-checks first either way; cannot affect the accepted-race path).
