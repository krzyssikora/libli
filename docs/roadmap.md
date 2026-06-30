# libli — Phased Roadmap

*Drafted 2026-06-13. A dependency-ordered breakdown of libli into build phases.
Each phase later gets its own focused cycle: **mockups → spec → plan → build**
(and may be sub-split). This document defines phase boundaries and order, not
detailed designs.*

Companion docs: [`packt-review.md`](packt-review.md) (build-from-scratch decision),
[`view-inventory.md`](view-inventory.md) (all views + product decisions).

---

## Guiding principles

- **Vertical slices where possible.** Each phase should end with something
  demonstrable end-to-end, not a layer that's useless until the next phase.
- **Decisions that are painful to reverse go early** — custom user model, the
  content hierarchy schema, the RBAC substrate, i18n.
- **Django admin is our scaffolding.** Early phases can use Django admin / fixtures
  to create users, cohorts, courses, etc., so we don't have to build every admin
  UI before the learner-facing features work. Polished admin UIs come in Phase 5.
- **Reserve hooks for deferred features** (notifications, exports, SIS) so adding
  them later doesn't force a schema rewrite.

---

## Phase 0 — Foundations

**Goal:** an empty-but-correct platform you can log into, themed for an
institution, with the role system and i18n in place.

**Includes**
- Project scaffold: Python 3.13 + uv, Django 5.2 + DRF, PostgreSQL, ruff,
  pytest + factory_boy, Bootstrap 5, whitenoise. Settings split (base/local/test/prod).
- **Custom user model** from day one (roles, branding/institution link, SSO identity).
- **RBAC substrate:** Django Groups + model permissions, structured so roles are
  re-sliceable later (Course Author/Manager split, Senior Teacher, etc.). Seed the
  4 roles (Student, Teacher, Course Admin, Platform Admin).
- **Auth:** login, password reset, signup with **configurable policy** (invite-token
  *or* open), and an **SSO-ready** pluggable backend (config UI deferred to Phase 5).
- **i18n infrastructure:** EN/PL UI, `LocaleMiddleware`, language switch.
- **Branding/theming mechanism:** per-institution logo + palette applied via CSS
  variables in the base layout (admin UI deferred to Phase 5; mechanism is foundational
  so all later views inherit it).
- **Base UI shell:** responsive layout, nav, light/dark toggle, the adaptive
  dashboard shell (sections fill in as later phases land).
- **Deployment skeleton:** single-tenant deploy, `.env` contract, CI.

**Depends on:** nothing. **Deferred:** branding/SSO admin UIs, first-run wizard.

**Open questions for the spec:** content-translation strategy (see Cross-cutting);
exact deployment/install story for a non-technical school (see Cross-cutting).

---

## Phase 1 — Content model, authoring & lesson consumption

**Goal:** a Course Admin can build a course; a Student can read a lesson and have
progress recorded.

**Includes**
- **Content hierarchy:** course > part > chapter > section > unit > element, with
  part/chapter/section **skippable**, unit/element mandatory. `OrderField`-style
  ordering at each level (idiom borrowed from educa).
- **Unit** = lesson | quiz (quiz *behaviour* is Phase 2; here we model the type and
  render lessons), obligatory flag, one-screen rendering.
- **Lesson element types:** styled text, image (+figcaption), video (whitelisted
  domains or upload), iframe (whitelist, e.g. GeoGebra), HTML (course-wide CSS/JS +
  per-unit JS, MathJax/LaTeX), math block.
- **Media storage / file manager:** whitelist, upload/pick/browse/drag-drop.
- **Authoring views:** create/edit course, course settings (CSS/JS files; color-band
  field can be defined here even though it's consumed in Phase 3), course builder
  (tree editor), unit editor, element editors.
- **Student views:** my courses, course outline (tree + progress indicators), lesson
  unit consumption.
- **Progress tracking:** 0–1 per unit per student.

**Depends on:** Phase 0. **Likely sub-split:** (1a) schema + authoring, (1b) consumption + progress.

**Open questions for the spec:** element storage strategy (GFK vs JSON-payload vs
MTI — see Packt review §3); how per-unit JS is edited/stored.

---

## Phase 2 — Quiz engine & results

**Goal:** a Course Admin can author quizzes; a Student can take them and get marked;
results are recorded.

**Includes**
- **9 question types:** single/multi MCQ, fill-blanks, drag-fill-blanks, short text,
  short numeric (answer + tolerance), extended response (required/forbidden keywords),
  match pairs, drag-to-image.
- **Marking modes** [A] auto / [N] not-marked / [R] requires-review, with the
  quiz-vs-question-type constraints; **max marks** and **max attempts** per question;
  attempt recording.
- **Quiz unit rendering** (incl. optional slideshow), submission, auto-marking,
  feedback states.
- **Results metrics** (scores per question/unit/course); the **[R] flag** is produced
  here (the teacher review *queue* lands in Phase 3, once grouping scopes "their students").
- **Student quiz summary** (own performance).

**Depends on:** Phase 1 (units/elements). **This is the single largest subsystem —
expect sub-splits** (e.g. by question-type families, then marking/attempts).

---

## Phase 3 — Grouping, enrollment & teacher analytics

**Goal:** students are organized and assigned to courses; teachers can monitor and
review.

**Includes**
- **Cohorts** (PA-managed; each student in exactly one; default single cohort).
- **Groups** (CA-managed; 1 group ↔ 1 course; students from cohorts; teachers assigned;
  membership changes preserve progress).
- **Collections** (unions of groups; T/CA/PA).
- **Enrollment:** group-assignment **+ self-enroll to open courses** (catalog + enroll flow).
- **Teacher analytics matrix:** the single configurable view (scope × depth × Progress/Results),
  consuming the per-course **color-band config**.
- **Quiz review queue** (now scoped to a teacher's groups).

**Depends on:** Phase 1 (content/progress) + Phase 2 (results, [R] flag).

---

## Phase 4 — Notes & tags

**Goal:** students annotate and organize their own learning.

**Includes**
- **Per-user notes** anchored to content blocks (margin on desktop, 📝 icon → modal
  on mobile); outline note-count badges.
- **Per-user tags** on units, outline tag filter, "Manage tags" modal (rename / delete-unused).

**Depends on:** Phase 1 (content/units). Independent of Phases 2–3.
**Deferred:** the notes *index* page (revision navigation).

---

## Phase 5 — Platform admin polish

**Goal:** a non-technical Platform Admin can fully run the institution without Django admin.

**Includes**
- **First-run setup wizard** + persistent dashboard setup checklist.
- **Branding admin UI**, **SSO configuration UI**, **platform settings** (languages,
  signup policy, storage/whitelist).
- **User management**, **role assignment**, **cohort management UI** (if not already
  surfaced in Phase 3).

**Depends on:** the mechanisms from Phases 0/3. **Note:** can be pulled earlier if a
real pilot needs it before then — until it lands, Django admin + fixtures fill the gap.

---

## Deferred (post-v1; reserve hooks now)

| Capability | Why deferred / note |
|---|---|
| Notifications & announcements | Wanted, not v1. Reserve model hooks (announcement→group, event notifications). |
| Exports (CSV / printable gradebook) | Needed by real schools; later phase. Keep results data export-friendly. |
| External result sharing (webhook / SIS / e-register) | Later; design results so they're streamable/exportable. |
| Notes index page | Easy add for revision navigation. |
| Teacher per-group color-band override | Nice-to-have on the analytics matrix. |
| Subject localization (EN/PL) | **Resolved in Phase 5a.** `Subject` now has bespoke `title_en`/`title_pl` fields. `Subject.title` returns `title_pl` when active language is Polish and `title_pl` is set, falling back to `title_en`. PA manages subjects via `/manage/subjects/` CRUD (create/edit/delete with usage counts). Courses link subjects via `Course.subjects` M2M; the catalog filters by subject. Locale-aware ordering shipped as a 5a follow-up: `SubjectQuerySet.localized_order()` sorts by PL title under Polish (EN fallback) and is used by all subject list views; the static `ordering = ["title_en"]` is only the plain-queryset default. **Follow-ups:** (5b) taxonomy structure (hierarchical subjects / tags); merge-subjects workflow; platform-wide content translation (course text, not just subject titles). |

---

## Cross-cutting concerns (resolve in specs, not a single phase)

- **Content translation strategy** *(decide in Phase 1)* — UI is EN/PL, but is *course
  content* monolingual-per-course, or translatable per element? Big schema implication.
- **Non-technical deployment/install** *(revisit through Phase 0 & 5)* — "a school can
  start it easily" likely means a one-command/containerized install + the first-run wizard.
- **RBAC re-sliceability** — every permission check uses Django permissions/Groups, never
  hardcoded role strings, so roles can be split later.
- **Accessibility & responsive** — light/dark + mobile/desktop for every view (your stated requirement).
- **Testing** — pytest + factory_boy against real PostgreSQL from Phase 0 onward.

---

## Suggested order

**0 → 1 → 2 → 3**, with **4** insertable any time after 1, and **5** any time after
its mechanisms exist (latest sensible point, or earlier for a pilot). Deferred items
follow v1.
