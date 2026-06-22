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
    course      ForeignKey(courses.Course, on_delete=CASCADE, related_name="groups")  # 1 group ↔ 1 course
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
    course      ForeignKey(courses.Course, on_delete=CASCADE, related_name="collections")  # single-course
    owner       ForeignKey(User, on_delete=CASCADE, related_name="owned_collections")
    groups      ManyToManyField(Group, related_name="collections")
    archived    BooleanField(default=False)
    created     DateTimeField(auto_now_add)
```

**Design decisions baked in:**
- **Cohort membership is a `CohortMembership` table, not a FK on `User`.** The
  `OneToOneField(user)` enforces "exactly one cohort" while avoiding an
  `accounts ↔ grouping` circular dependency, and reserves `assigned_at` /
  `assigned_by` hooks. Every new user gets a membership in the **Default** cohort
  via a `post_save(sender=User)` receiver guarded by `created=True`, using
  `get_or_create` so it is idempotent. Note this deliberately does **not** reuse
  the existing `accounts/signals.py` Student-role signal — that one is wired to
  allauth's `user_signed_up`, which fires only for self-signups; cohort
  membership must cover *every* creation path (admin, fixtures, SSO JIT), so a
  `post_save` receiver is used instead. The receiver is a no-op during the
  initial backfill migration (§7) because the Default cohort + memberships are
  created there directly against historical models, and `get_or_create` prevents
  any double-membership. Auto-default and backfill memberships set
  `assigned_by = None` (no acting user); only manager-driven assigns/reassigns
  record the acting user. The same convention applies to `GroupMembership.added_by`.
- **`Group.course` is a plain FK** — a group belongs to exactly one course; a
  course may have many groups (e.g. two Spanish classes). It is **immutable after
  creation** (mirroring `Collection.course`): the 5.16 edit form locks the course
  field, and a model `save()` guard rejects a change on an existing group. This
  avoids a "group course change" recompute that would have to drop every member's
  enrollment on the old course and create it on the new — out of scope; to move a
  roster, create a new group for the target course.
- **`Group.course` / `Collection.course` are `on_delete=CASCADE`.** Deleting a
  course (a rare PA action, view 6.3) deletes its groups, group memberships, and
  collections. No enrollment recompute is needed on course delete because
  `courses.Enrollment.course` is already `CASCADE` — the enrollments vanish with
  the course directly. (The service-driven recompute only handles the membership
  edits described in §3; bulk course-level cascades are left to the DB.)
- **`Collection.owner` is `on_delete=CASCADE`** — a personal saved view dies with
  its creator's account. Handling an owner who merely *loses* the Teacher role
  (collection becomes un-editable by them but isn't auto-deleted) is **deferred**
  beyond 3a; for now such a collection simply falls out of their
  `collections_manageable_by` scope until a PA/CA reassigns or deletes it.
- **"Students drawn from a cohort" is a UI filter**, not a model constraint. The
  group student-picker defaults to filtering by cohort but a manager may add any
  student; no FK ties a `GroupMembership` to a cohort.
- **Group teachers = the explicit `teachers` M2M only.** The course owner and
  Platform Admins get access *structurally* via scoping (§4), never copied into
  the M2M — so changing `Course.owner` never leaves stale rows. This is the
  reading of roles.md's "by default these include platform owners and course
  owners." So that the "by default these include the owner" expectation is met
  *visibly* and not just in access checks, the Group detail teacher roster (4.2)
  **displays the course owner** alongside the assigned teachers, labeled as
  "(owner)" and non-removable; Platform-Admin access is structural and not listed
  per-group. The **student roster and membership count are driven solely by
  `GroupMembership`**, and the **teacher list solely by the `teachers` M2M (+ the
  owner)** — so a user who is both a teacher and a student-member legitimately
  appears once in each list, with no double-counting; "membership count" always
  means student-members only.
- **`Collection.course`** makes the single-course rule first-class; the `groups`
  M2M is validated (form + model `clean`) so every group shares `collection.course`.

**Constraints / validation**
- `Cohort.is_default`: a partial `UniqueConstraint(condition=Q(is_default=True))`
  enforces *at most one* default at the DB level. *Exactly one* is then
  maintained by the service layer: the backfill migration creates the Default
  with `is_default=True`; the cohort service refuses to (a) clear the flag on the
  sole default, (b) delete or archive the default cohort. Each such attempt
  raises a `ValidationError` surfaced as a form error ("The default cohort cannot
  be removed; designate another default first."). There is no UI to create a
  second default — promoting another cohort to default **demotes the current
  default first, then promotes the new one**, within one transaction, so the
  partial unique index never sees two `is_default=True` rows at any statement
  boundary (Postgres checks the constraint immediately, not at commit, so the
  ordering — not deferral — is what keeps it legal). The cohort service is the
  **sole write path** to `is_default`; no view, form, or admin writes it directly,
  so the ordering guarantee is not merely documentary. A test asserts a direct
  two-`is_default=True`-rows attempt raises `IntegrityError`.
- `Cohort.slug`: auto-generated from `name` (slugify + numeric suffix on
  collision); the Default cohort gets a reserved, stable `default` slug that the
  service will not reassign. `slug` is globally `unique=True` (not partial on
  `archived`), so collision-suffixing counts **all** rows including archived ones
  — re-creating a same-named cohort while the old one is archived yields
  `name-2`. The bare `default` slug is permanently owned by the system Default
  cohort, so a PA-created cohort literally named "Default" is suffixed to
  `default-2`.
- `CohortMembership`: `OneToOne` on `user`.
- `GroupMembership`: `UniqueConstraint(group, student)`.
- `Collection`: every group in `groups` must satisfy
  `group.course == collection.course`. M2M membership **cannot** be validated in
  the model's `clean()` (the relation isn't available pre-save), so enforcement
  lives in two places: the create/edit **form** is the user-facing validation
  (rejects mismatched groups), and an `m2m_changed` receiver on
  `Collection.groups` is a defense-in-depth guard for non-form code paths
  (admin/shell/service). The receiver raises to **abort the surrounding
  transaction** (so callers must wrap `.add()`/`.set()` in `atomic`); it does
  **not** surface as a friendly form error — that's the form's job. An **empty
  collection is allowed** (it simply shows an empty roster). `Collection.course`
  is **immutable once any group is attached**: the form enforces this for users,
  **and a model `save()`/`clean()` guard rejects a `course` change when
  `self.pk and self.groups.exists()`** (parity with the M2M defense, so direct
  writes can't break the single-course invariant) — to retarget, remove all
  groups first.
- **URL identifiers:** `Cohort` is routed by `slug`; `Group` and `Collection`
  are routed by primary key (no slug field).

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
        get_or_create Enrollment(student, course, defaults={source: "group"})
        # concurrent racing create may return an existing row of ANY source
        # (created=False); we leave its source untouched — never downgrade.
    elif not reachable and enrollment and enrollment.source == "group":
        delete enrollment
    elif enrollment and enrollment.source in ("self", "manual"):
        leave untouched   # immune to group changes
    else:
        leave untouched   # reachable + existing group enrollment (steady state):
                          # intentional no-op. The branches are exhaustive.
```

**Ordering — recompute always runs *after* the mutation is persisted.** It reads
the *final* membership state, so `reachable` is authoritative: on a
`GroupMembership` delete the row is already gone (a student still in a second
group of the same course stays reachable → keeps access); on create the row is
already inserted; on archive/delete the group's state change is applied first.
This is what makes the §6 "remove-with-a-second-group → keeps it" and
"remove-last → drops it" outcomes well-defined.

**Idempotency & concurrency.** `Enrollment` has `UniqueConstraint(student,
course)`. Recompute is idempotent and must tolerate concurrent calls (bulk
import, add-to-two-groups): it runs inside an atomic transaction and uses
`get_or_create` for the create branch, so a racing duplicate create surfaces as a
caught `IntegrityError`/no-op rather than an error to the user.

**Batch operations.** Multi-student add/remove (view 5.16) and group
archive/delete fan out to **one `recompute_enrollment(student, course)` call per
affected `(student, course)`**, all wrapped in a single transaction. Cohort
operations (assign/reassign/delete-to-Default in 6.4) **do not** call recompute —
cohort membership does not drive course access (only group membership does); the
cohort↔enrollment relationship is intentionally a no-op.

**Called from these places** (all via **explicit service-layer calls**, never via
membership-model signals — so batch operations can dedupe to one call per
`(student, course)`; signals are reserved only for the cohort default-membership
`post_save`): `GroupMembership` create, `GroupMembership` delete, a group's
**archived-state change (archive *and* un-archive)**, and group delete. Un-archive
matters: it flips the group back to reachable, so it fans out one recompute per
current member to **re-create** the `source="group"` enrollments that archiving
dropped. Changing a group's `teachers` M2M **never** calls recompute — teachers
are not enrolled via groups; a user may be both a group teacher and a
student-member, with fully independent semantics.

**Invariants this guarantees:**
- **Progress is always preserved.** `UnitProgress`, `QuizSubmission`,
  `QuestionResponse`, `Attempt` all key on `(student, unit)` and are **never
  touched** by recompute. Dropping access and re-adding later restores the
  student's visible progress automatically.
- **Self/manual enrollments are immune** — a student who self-enrolled (3b) or
  was manually enrolled keeps access even when removed from every group.
- **Archived groups do not grant access** — recompute treats them as not
  reachable; un-archiving restores access.

**Overlapping sources (precedence).** An enrollment should exist iff the student
is *either* group-reachable *or* has a self/manual basis. The `source` field
records provenance, and **a self/manual source takes precedence over group** — so
adding a manual/self-enrolled student to a group never rewrites their `source` to
`"group"` (recompute's branch 3 leaves it untouched), and recompute's delete
branch only fires for `source == "group"`, so a group-reachable student is *never*
stranded by recompute. The one cross-cutting contract: **any path that removes a
self/manual basis (a 3b/manual-admin concern, out of 3a's recompute) must itself
call `recompute_enrollment` afterward**, so a student who is still group-reachable
is re-derived a `source="group"` enrollment rather than losing access. 3a does not
build those removal paths; it only states the contract they must honor.

**Lifecycle semantics** (archive = soft-hide & freeze; delete = hard remove):

| Action | Effect |
|---|---|
| **Cohort delete / archive** (non-empty) | Members are reassigned to the **Default** cohort first, then the cohort is removed/hidden — all in one transaction. Reassignment is an **in-place `UPDATE` of each `CohortMembership.cohort` FK** (never delete-and-recreate), so the `OneToOne(user)` row is preserved and never transiently duplicated. No enrollment recompute (cohort membership does not drive access). Mechanically the reassignment is `UPDATE CohortMembership SET cohort=Default WHERE cohort=<target>` — naturally a no-op for an empty cohort. The Default cohort itself cannot be deleted or archived, so this branch is unreachable for Default. |
| **Group archive** | Hidden from active lists; `GroupMembership` rows kept for history. Treated as "not reachable" → group-sourced access drops; progress persists; un-archiving restores access. Stays in any `Collection.groups` it belongs to but is **excluded from that collection's union roster/counts** (4.3) while archived, consistent with the "archived = frozen, not active" rule. Its own 4.2 detail still shows its roster/counts (with an archived badge), so it can be reviewed and un-archived. |
| **Group delete** | Memberships removed; `recompute_enrollment` runs per ex-member (group-sourced access drops); progress persists. The `Collection.groups` M2M rows referencing it are removed by the standard M2M cascade, so any collection's union roster shrinks accordingly. |
| **Collection archive / delete** | No effect on groups, members, or enrollments — a collection is only a saved union/view. |

---

## 4. Permissions & scoping (RBAC, re-sliceable)

Two layers, following the established "never hardcode role strings" rule. Model
permissions express coarse capability; pure scoping functions express the
object-level "which rows."

**Model permissions** (Django auto-generated, attached to role Groups in
`institution/roles.py`):
- `Cohort` add/change/delete/view → **Platform Admin**; `view` also → Course Admin
  (read access "all admins"). The CA `Cohort.view` grant is consumed in 3a by the
  **cohort filter on the 5.16 group student-picker** (a CA scoping group rosters
  needs to read cohort names); it is not a standalone CA cohort screen.
- `Group` add/change/delete/view → **Course Admin** + **Platform Admin**;
  **`Group.view` also → Teacher** (roles.md: read access is "all admins *and
  group teachers*"). Without the `view` grant a teacher would be blocked at the
  permission gate before object scoping runs.
- `Collection` add/change/delete/view → **Teacher** + **Course Admin** +
  **Platform Admin**.

Every list/detail view applies the Django model-permission gate (`view`/`change`)
**first**, then narrows rows via the scoping function below — so the `view` grant
is necessary-but-not-sufficient and scoping does the row-level filtering.

**Seeding mechanism.** `institution/roles.py` today only builds
`PLATFORM_ADMIN_PERMS` and calls `.permissions.set()` on the Platform Admin Group.
3a extends this with `TEACHER_PERMS` (`grouping.view_group`,
`grouping.add/change/delete/view_collection`) and `COURSE_ADMIN_PERMS`
(`grouping.add/change/delete/view_group`, `grouping.view_cohort`,
`grouping.*_collection`), and adds the new `grouping.*` perms to
`PLATFORM_ADMIN_PERMS`. Because `.set()` replaces, `seed_roles()` re-attaches the
full per-role list each run and is idempotent. The new `grouping.*` permissions
do not exist until the `grouping` app's migration runs, so **a `RunPython` step
in §7 calls `seed_roles()` after the `grouping` migration** to attach them to the
role Groups in already-migrated deployments; `seed_roles` continues to be safe to
re-run on every deploy.

**Object-level scoping** (`grouping/scoping.py` — pure functions):
```
groups_manageable_by(user)        # PA: all; CA: groups where group.course.owner == user
groups_visible_to(user)           # manageable ∪ groups where user in group.teachers
collections_manageable_by(user)   # PA: all; CA: collections on courses they own;
                                  #   Teacher: collections they own over groups they teach
can_add_collection_group(user, group)  # PA: always True; teacher must teach it; CA must own its course
```
Views call the Django `view`/`change` permission gate **then** the scoping
function; no raw `if role == "Teacher"`.

**Archived rows & un-archive.** The scoping functions **return archived rows too**
(otherwise a manager could never find a group to un-archive); the active/archived
split is applied by the **list views** on top of scoping (active by default, with
an "archived" filter). Un-archiving is a `change_group` mutation, gated
identically to archiving.

**Collection create bootstrap (4.4):** a teacher creating their *first* collection
has nothing for `collections_manageable_by` to match yet, so **create** is gated
by the model `add_collection` permission plus `can_add_collection_group(user,
group)` for every selected group (the teacher must teach each group / the CA must
own its course); `owner` is set to the creating user on save. **Edit/delete** of
an existing collection are gated by `collections_manageable_by`.

When the Course Admin role later splits
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
  delete/archive reassigns to Default (in-place `UPDATE`, OneToOne preserved);
  Default cannot be deleted/archived; **default promotion demotes-then-promotes
  and never leaves two `is_default=True` rows mid-transaction** (the partial
  unique index is not tripped); slug collision-suffixing counts archived rows.
- **Collection validation:** rejects a group whose course differs from
  `collection.course`.
- **Scoping functions** per role (PA / CA-owner / CA-non-owner / assigned teacher
  / unrelated teacher / student).
- **Batch / cohort integration tests** (the riskiest flows): multi-student add to
  a group fires exactly one recompute per `(student, course)` and creates the
  right enrollments in one transaction; cohort delete/archive reassigns all
  members to Default **without** touching enrollments; promoting a new default
  demotes the old one atomically.
- **e2e** drives the **real** add/remove/archive gestures end-to-end through the
  actual click path — including **multi-student membership changes** and **cohort
  delete-with-reassignment-to-Default** — no `page.evaluate` shortcuts (per the
  "e2e must drive real UI" rule).

---

## 7. Migrations

- New `grouping` app: initial migration for the **five explicit models** + their
  constraints, **plus the two auto-created M2M through-tables** (`Group.teachers`
  and `Collection.groups`) and the partial unique index on `Cohort.is_default`.
- A **pure data migration** (using historical models via `apps.get_model`, **not**
  the runtime `post_save` signal) that: creates the **Default** cohort
  idempotently (`is_default=True`, slug `default`); back-fills a
  `CohortMembership` into it for every existing user via `get_or_create`. Because
  it uses historical models, the runtime signal and the "exactly one default"
  service guard (§2) do not fire mid-migration. The runtime `post_save` receiver
  (§2) covers users created *after* the migration; `get_or_create` on both paths
  means neither double-creates nor skips a user.
- A `RunPython` step that calls `seed_roles()` (extended per §4 with the new
  `grouping.*` perm lists) **after** the `grouping` app's migration, so the new
  permissions — which don't exist until that migration — are attached to the
  Teacher / Course Admin / Platform Admin Groups in already-migrated
  deployments. Idempotent (`.set()` re-attaches each run).
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
