# Phase 3a — Grouping Substrate (design)

*Brainstormed 2026-06-22. The first sub-split of Phase 3 (Grouping, enrollment &
teacher analytics). 3a delivers the **grouping substrate** — cohorts, groups,
collections, and the membership↔enrollment wiring — plus their management UIs.
Self-enroll (3b) and the teacher analytics matrix + quiz review queue (3c) are
later cycles that **consume** this substrate.*

Companion docs: [`docs/roadmap.md`](../../roadmap.md) (Phase 3 boundary),
[`docs/view-inventory.md`](../../view-inventory.md) (views 4.1–4.4, 5.15–5.16, 6.4),
[`roles.md`](../../../roles.md) (cohort/group/collection rules & RBAC).

---

## 1. Goal & scope

**Goal:** students can be organized into cohorts, groups, and collections;
group membership drives course access (enrollment) while preserving progress;
the people who manage these structures have the CRUD screens to do so.

**In scope (3a)**
- `Cohort` + `CohortMembership` (each student in exactly one; auto-default).
- `Group` + `GroupMembership` (a group ↔ one course; students from cohorts;
  assigned teachers; membership changes preserve progress).
- `Collection` (single-course union of groups).
- The `recompute_enrollment` service wiring group membership → `courses.Enrollment`.
- Model permissions + object-level scoping for the three concepts.
- Management/CRUD + roster views: 6.4, 5.15, 5.16, 4.1, 4.2 (roster only),
  4.3 (roster only), 4.4.

**Out of scope (deferred, by sub-split)**
- **3b:** open-course catalog, course landing, self-enroll flow (views 3.2/3.3).
  `Enrollment.source == "self"` is honored by the recompute service here but
  no self-enroll *path* is built in 3a.
- **3c:** at-a-glance progress/results on group/collection detail, the
  configurable analytics matrix (4.5), the quiz review queue (4.6). 3a detail
  pages are **roster + counts only**.
- **Out of v1 / later:** per-course color-band config consumption (3c), teacher
  per-group color-band override, exports.

**Settled by `roles.md` / roadmap (folded in, not re-litigated):** who CRUDs each
concept and who has read access; "each student in exactly one cohort, default
single cohort"; "1 group ↔ 1 course"; "a student can move between groups for the
same course, progress always preserved."

---

## 2. Data model

A **new `grouping` Django app** houses all three concepts. Rationale: keeps
`accounts` and `courses` from tangling, and gives cohorts/groups/collections one
home. FKs to `courses.Course` and `settings.AUTH_USER_MODEL` use string/lazy
references so migration dependencies stay one-directional
(`grouping` → `accounts`, `grouping` → `courses`).

```
grouping/models.py

class Cohort
    name        CharField
    slug        SlugField (unique)
    is_default  BooleanField(default=False)   # exactly one True; PA-protected
    archived    BooleanField(default=False)
    created     DateTimeField(auto_now_add)

class CohortMembership
    user        OneToOneField(User)           # OneToOne ⇒ "exactly one cohort"
    cohort      ForeignKey(Cohort)
    assigned_at DateTimeField(auto_now_add)
    assigned_by ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")

class Group
    name        CharField
    course      ForeignKey(courses.Course, related_name="groups")  # 1 group ↔ 1 course
    teachers    ManyToManyField(User, blank=True, related_name="taught_groups")
    archived    BooleanField(default=False)
    created     DateTimeField(auto_now_add)

class GroupMembership
    group       ForeignKey(Group, related_name="memberships")
    student     ForeignKey(User, related_name="group_memberships")
    added_at    DateTimeField(auto_now_add)
    added_by    ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")
    # unique(group, student) — the SOURCE OF TRUTH for group→enrollment

class Collection
    name        CharField
    course      ForeignKey(courses.Course, related_name="collections")  # single-course
    owner       ForeignKey(User, related_name="owned_collections")
    groups      ManyToManyField(Group, related_name="collections")
    archived    BooleanField(default=False)
    created     DateTimeField(auto_now_add)
```

**Design decisions baked in:**
- **Cohort membership is a `CohortMembership` table, not a FK on `User`.** The
  `OneToOneField(user)` enforces "exactly one cohort" while avoiding an
  `accounts ↔ grouping` circular dependency, and reserves `assigned_at` /
  `assigned_by` hooks. New users get a membership in the **Default** cohort via a
  `post_save` signal (mirrors the existing Student-role signal in
  `accounts/signals.py`).
- **`Group.course` is a plain FK** — a group belongs to exactly one course; a
  course may have many groups (e.g. two Spanish classes).
- **"Students drawn from a cohort" is a UI filter**, not a model constraint. The
  group student-picker defaults to filtering by cohort but a manager may add any
  student; no FK ties a `GroupMembership` to a cohort.
- **Group teachers = the explicit `teachers` M2M only.** The course owner and
  Platform Admins get access *structurally* via scoping (§4), never copied into
  the M2M — so changing `Course.owner` never leaves stale rows. This is the
  reading of roles.md's "by default these include platform owners and course
  owners."
- **`Collection.course`** makes the single-course rule first-class; the `groups`
  M2M is validated (form + model `clean`) so every group shares `collection.course`.

**Constraints / validation**
- `Cohort`: exactly one `is_default=True` (enforced in the service that creates
  it + a guard on save); the default cohort cannot be archived or deleted.
- `CohortMembership`: `OneToOne` on `user`.
- `GroupMembership`: `UniqueConstraint(group, student)`.
- `Collection`: every group in `groups` must have `group.course == collection.course`.

---

## 3. Enrollment wiring (the heart of 3a)

`grouping/services.py` exposes a single sync entry point. Group membership is the
source of truth; `courses.Enrollment` (unique per `(student, course)`, with
`source ∈ {manual, group, self}`) is recomputed from it.

```
recompute_enrollment(student, course):
    reachable = a GroupMembership exists for `student` in any
                NON-ARCHIVED Group whose course == `course`
    enrollment = Enrollment for (student, course)  # may be None

    if reachable and enrollment is None:
        create Enrollment(student, course, source="group")
    elif not reachable and enrollment and enrollment.source == "group":
        delete enrollment
    elif enrollment and enrollment.source in ("self", "manual"):
        leave untouched   # immune to group changes
```

**Called from exactly four places:** `GroupMembership` create, `GroupMembership`
delete, group archive, group delete.

**Invariants this guarantees:**
- **Progress is always preserved.** `UnitProgress`, `QuizSubmission`,
  `QuestionResponse`, `Attempt` all key on `(student, unit)` and are **never
  touched** by recompute. Dropping access and re-adding later restores the
  student's visible progress automatically.
- **Self/manual enrollments are immune** — a student who self-enrolled (3b) or
  was manually enrolled keeps access even when removed from every group.
- **Archived groups do not grant access** — recompute treats them as not
  reachable; un-archiving restores access.

**Lifecycle semantics** (archive = soft-hide & freeze; delete = hard remove):

| Action | Effect |
|---|---|
| **Cohort delete / archive** (non-empty) | Members are reassigned to the **Default** cohort first, then the cohort is removed/hidden. The Default cohort itself cannot be deleted or archived. |
| **Group archive** | Hidden from active lists; `GroupMembership` rows kept for history. Treated as "not reachable" → group-sourced access drops; progress persists; un-archiving restores access. |
| **Group delete** | Memberships removed; `recompute_enrollment` runs per ex-member (group-sourced access drops); progress persists. |
| **Collection archive / delete** | No effect on groups, members, or enrollments — a collection is only a saved union/view. |

---

## 4. Permissions & scoping (RBAC, re-sliceable)

Two layers, following the established "never hardcode role strings" rule. Model
permissions express coarse capability; pure scoping functions express the
object-level "which rows."

**Model permissions** (Django auto-generated, attached to role Groups in
`institution/roles.py`):
- `Cohort` add/change/delete/view → **Platform Admin**; `view` also → Course Admin
  (read access "all admins").
- `Group` add/change/delete/view → **Course Admin** + **Platform Admin**.
- `Collection` add/change/delete/view → **Teacher** + **Course Admin** +
  **Platform Admin**.

**Object-level scoping** (`grouping/scoping.py` — pure functions):
```
groups_manageable_by(user)        # PA: all; CA: groups where group.course.owner == user
groups_visible_to(user)           # manageable ∪ groups where user in group.teachers
collections_manageable_by(user)   # PA: all; CA: collections on courses they own;
                                  #   Teacher: collections they own over groups they teach
can_add_collection_group(user, group)  # teacher must teach it / CA must own its course
```
Views call the Django `view`/`change` permission gate **then** the scoping
function; no raw `if role == "Teacher"`. When the Course Admin role later splits
(Author/Manager) or a Senior Teacher role appears, only these functions change.

**Conscious deferral:** today a "Course Admin" is scoped via the **`Course.owner`**
FK (there is an `owner` FK and a `Course Admin` role Group, but no per-course
admin *assignment* table — that's view 6.2, a PA function, not yet built). 3a
scopes CA management to **courses they own**; multi-admin-per-course grants land
when 6.2 does. This is a deliberate deferral, not a gap.

---

## 5. Surfaces

Each view is EN/PL, light/dark, and responsive (mobile + desktop) per the
project-wide conventions. Screens are conventional CRUD that reuse the Phase-1b
builder/list component patterns.

| # | View | Roles | 3a content |
|---|------|-------|------------|
| 6.4 | Cohort management | PA | List / create / edit / archive / delete; assign & reassign students; Default-cohort fallback on delete/archive. |
| 5.15 | Groups — list | CA/PA | Groups for courses they own (`groups_manageable_by`). |
| 5.16 | Group — create / edit | CA/PA | Connect to a course; assign teachers; add/remove students (picker filtered by cohort); archive/delete. |
| 4.1 | My groups & collections | T/CA/PA | Lists scoped via `groups_visible_to` / `collections_manageable_by`. |
| 4.2 | Group detail | T/CA/PA | **Roster + membership counts only.** |
| 4.3 | Collection detail | T/CA/PA | **Union roster + counts only.** |
| 4.4 | Collection — create / edit | T(own)/CA/PA | Build from selectable single-course groups (validated); archive/delete. |

**Scope boundary that keeps 3a clean:** group/collection **detail pages show
roster + plain membership counts only** — no progress/results visualization. The
"at-a-glance progress/results" the view-inventory mentions for 4.2/4.3, the
configurable analytics matrix (4.5), and the quiz review queue (4.6) are **all
deferred to 3c**. 3a delivers the substrate and its CRUD; 3c consumes it.

**Mockups:** lightweight — reuse existing list/builder components rather than a
dedicated visual-design sub-spec, unless a dedicated mockup pass is requested
before build.

---

## 6. Testing

pytest + factory_boy against real PostgreSQL (project standard from Phase 0).

- **Factories:** `CohortFactory`, `GroupFactory`, `CollectionFactory`, and the
  membership models; a default-cohort fixture.
- **`recompute_enrollment` truth table** (unit): add (creates group enrollment),
  remove-last (drops it), remove-with-a-second-group-for-the-same-course (keeps
  it), group archive (drops), group un-archive (restores), self/manual immunity
  (untouched by group changes), progress-preserved (UnitProgress/QuizSubmission
  rows survive drop + re-add).
- **Cohort invariants:** OneToOne exactly-one; new-user auto-joins Default;
  delete/archive reassigns to Default; Default cannot be deleted/archived.
- **Collection validation:** rejects a group whose course differs from
  `collection.course`.
- **Scoping functions** per role (PA / CA-owner / CA-non-owner / assigned teacher
  / unrelated teacher / student).
- **e2e** drives the **real** add/remove/archive gestures end-to-end through the
  actual click path — no `page.evaluate` shortcuts (per the "e2e must drive real
  UI" rule).

---

## 7. Migrations

- New `grouping` app: initial migration for the five models + constraints.
- Data migration / signal to create the **Default** cohort and back-fill a
  `CohortMembership` into it for every existing user.
- No changes to `courses.Enrollment` schema (the `source` field and unique
  constraint already exist); 3a only adds *write paths* via the service.

---

## 8. Open items carried forward

- **Per-course color-band config** is referenced by the roadmap as "definable in
  course settings, consumed in Phase 3" but is not yet on `Course`. It is a **3c**
  concern (analytics rendering); 3a does not need it.
- **Per-course admin assignment (view 6.2)** — see §4 deferral; CA scoping uses
  `Course.owner` until 6.2 lands.
- **Self-enroll path (3b)** — the recompute service already respects
  `source="self"`; the catalog/landing/enroll flow is built in 3b.
