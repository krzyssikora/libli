# libli — View Inventory

*Updated 2026-06-13 after the open-questions walkthrough. Expands `/views.md`.
This is the candidate list of all screens, to drive mockups (light + dark,
mobile + desktop) within each build phase.*

**Role key:** **S** = Student · **T** = Teacher · **CA** = Course Admin ·
**PA** = Platform Admin. (PA can do everything CA can; T and CA can also consume
courses like a student, untracked — e.g. teacher workshops put a teacher in a
student's shoes.)

**Conventions assumed throughout** (not separate views): language switch (EN/PL),
light/dark toggle, and per-institution branding (logo/palette) apply to every view.

---

## Resolved decisions (2026-06-13)

| Topic | Decision |
|---|---|
| **Signup** | **Configurable per institution** — Platform Admin chooses invite-only vs. open self-signup in platform settings. Both code paths built. New users default to Student. |
| **Landing page** | **Full public landing page** (branded; intro content; login/signup CTAs). |
| **Dashboard** | **One adaptive dashboard** with role-based sections that are **collapsible and reorderable**, per-user state remembered. Single-role users see only their own area, no role artifacts. |
| **Notes & tags** | **In-context only (A+).** Notes anchored to blocks in a unit (margin on desktop; 📝 icon → modal on mobile); discovered via outline note-count badges. Tags added/removed on units + filtered in outline. A small **"Manage tags" modal** (from the outline filter) handles rename / delete-unused. **No** dedicated notes-list page in v1 (addable later for revision navigation). |
| **Teacher analytics** | **One configurable matrix** (students × course-components × metric). Scope = group/collection + all/chosen students; depth = course→unit via column drill-down; **Progress ↔ Results** toggle; single-student = click a row. |
| **Color coding** | **Score/progress band thresholds + colors are configurable.** Primary: set at **course level** (Course settings). Nice-to-have (later): teacher per-group override, defaulting to course config. |
| **First-run** | **Guided setup wizard** (Institution → Branding → SSO → Signup policy → First cohort → Invite people; every step skippable) **+ a persistent "finish setup" checklist** on the PA dashboard. Everything re-editable in Settings. |
| **Enrollment** | **Group-assignment + optional self-enroll.** Default: students get courses by being added to a group. Additionally, a course can be marked **open**, letting students self-enroll via a catalog. |

---

## 1. Public / unauthenticated

| # | View | Notes |
|---|------|-------|
| 1.1 | Institution landing / home | **Full branded landing page** — intro content, login/signup CTAs, may surface open courses. |
| 1.2 | Login | Username/email + password **and** an SSO button when SSO is configured. |
| 1.3 | SSO redirect/callback + error | Mostly non-visual; needs an "SSO error / account-not-provisioned" page. |
| 1.4 | Signup / accept invite | Honors the institution's signup policy (invite-token **or** open). Default role = Student. |
| 1.5 | Password reset — request | Enter email. |
| 1.6 | Password reset — confirm | Set new password from emailed link. |
| 1.7 | Error pages | 403 / 404 / 500, branded. |

---

## 2. Common authenticated (all roles)

| # | View | Roles | Notes |
|---|------|-------|-------|
| 2.1 | Dashboard / home | S T CA PA | **Adaptive**: role-based sections, collapsible + reorderable, per-user state. PA also sees the **setup checklist** until complete. |
| 2.2 | User settings / profile | S T CA PA | Name, email, password change, language, theme, (future: notification prefs). |

---

## 3. Student — learning & enrollment

| # | View | Roles | Notes |
|---|------|-------|-------|
| 3.1 | My courses | S (+T/CA/PA preview) | Courses the user is in. |
| 3.2 | Course catalog (open courses) | S | Browse courses marked **open**; entry to self-enroll. |
| 3.3 | Course landing / self-enroll | S | Open-course detail + enroll action (self-enroll → membership/auto-group for that course). |
| 3.4 | Course detail / outline | S | Hierarchy tree (course>part>chapter>section>unit). Per-level **progress** indicator, **note-count badges**, **tag filter** (+ "Manage tags" modal). |
| 3.5 | Unit view — **lesson** | S | Renders elements (text/image/video/iframe/HTML/math) as blocks on one screen. **Anchored note** add/view (margin desktop / icon→modal mobile) and **tag** add/remove. Marks progress 0→1. |
| 3.6 | Unit view — **quiz** | S | Question elements; optional **slideshow** (one per screen). Submit → auto-mark / submitted-for-review / unmarked feedback. Shows attempts used vs. max. |
| 3.7 | Quiz summary — own performance | S | Per course + drill-down: results + attempts. Student-facing counterpart of the teacher matrix. |

*(Notes & tags have no dedicated pages — see decisions; managed in-context + the tag modal.)*

---

## 4. Teacher — monitoring & review

| # | View | Roles | Notes |
|---|------|-------|-------|
| 4.1 | My groups & collections | T (+CA/PA) | List of assigned groups/collections. |
| 4.2 | Group detail | T CA PA | Roster + at-a-glance progress/results. |
| 4.3 | Collection detail | T CA PA | Union of groups; same as 4.2 across multiple groups. |
| 4.4 | Create / edit collection | T (own groups) CA PA | Build from selectable groups. Archive/delete. |
| 4.5 | **Analytics matrix** | T CA PA | The single configurable view: scope (group/collection, all/chosen students) × depth (course→unit, column drill-down) × **Progress ↔ Results**; click a student row for their breakdown. Color bands per course config; (later) teacher per-group override. |
| 4.6 | Quiz review queue | T | Questions/quizzes marked **[R] requires review** for the teacher's groups; mark them, flag further review. |

---

## 5. Course Admin — authoring

| # | View | Roles | Notes |
|---|------|-------|-------|
| 5.1 | My courses (admin) | CA PA | Courses the user administers. |
| 5.2 | Create / edit course | CA PA | Metadata (title, subject, language(s), overview), **open/assigned visibility**. |
| 5.3 | Course settings | CA PA | Course-wide **CSS file** + **JS file** for HTML elements; default marking; **color-band thresholds/colors**; languages; visibility. |
| 5.4 | Course builder (tree editor) | CA PA | Add / reorder / skip-or-include **part / chapter / section**; add **units**; obligatory flag. |
| 5.5 | Unit editor | CA PA | Set unit type (**lesson** vs **quiz**), obligatory, slideshow (quiz); add / reorder / delete **elements**; per-unit JS (may fold in here). |
| 5.6–5.11 | Element editors | CA PA | One per type: **text** (styled), **image** (+figcaption), **video** (whitelist URL or upload), **iframe** (whitelisted, e.g. GeoGebra), **HTML** (tags preserved; MathJax/LaTeX; uses course CSS/JS + per-unit JS), **math block**. |
| 5.12 | Question editors (×9) | CA PA | single/multi MCQ, fill-blanks, drag-fill-blanks, short text, short numeric (answer + tolerance), extended response (required/forbidden keywords), match pairs, drag-to-image. Each sets **marking mode** [A]/[N]/[R], **max marks**, **max attempts**; prompts on quiz/question-type conflicts. (Likely one editor shell + type-specific bodies.) |
| 5.13 | Media storage / file manager | CA PA | Upload (whitelisted image/video types), browse, pick, delete; drag-and-drop. |
| 5.14 | Preview as student | CA PA (+T) | Walk the course like a student, untracked (reuses §3 views in preview mode). |
| 5.15 | Groups — list | CA PA | Groups for the admin's course(s). |
| 5.16 | Group — create / edit | CA PA | Create, connect 1↔1 to a course, assign teachers, add/remove students (from cohort(s)). Archive/delete. Membership changes preserve progress. |

---

## 6. Platform Admin — institution operations

| # | View | Roles | Notes |
|---|------|-------|-------|
| 6.0 | **First-run setup wizard** | PA | Guided stepper on first launch (Institution → Branding → SSO → Signup policy → First cohort → Invite people), skippable; backed by a dashboard setup checklist. |
| 6.1 | User management | PA | List/search users; invite; assign any role; deactivate. |
| 6.2 | Assign course-admin role | PA | Grant a user Course Admin for a specific course. |
| 6.3 | Course management | PA | Create / delete courses (CA can edit but not create/delete). |
| 6.4 | Cohort management | PA | Create / edit / archive / delete cohorts (each student in exactly one; default single cohort). |
| 6.5 | Branding settings | PA | Logo + colour palette. "Easy, non-technical." |
| 6.6 | SSO configuration | PA | Simple SSO setup (provider, metadata/keys). |
| 6.7 | Platform settings | PA | Institution-wide: enabled languages, **signup policy**, storage/whitelist config, etc. |

---

## 7. Cross-cutting partials / modals (to mock, not full pages)

| # | Element | Where |
|---|---------|-------|
| 7.1 | Note add/edit popover & mobile modal | Lesson units (§3.5) — margin desktop, 📝 icon → modal mobile. |
| 7.2 | Tag add/remove control | Units (§3.5). |
| 7.3 | "Manage tags" modal (rename / delete-unused) | Outline tag filter (§3.4). |
| 7.4 | Media picker (storage/device/drag-drop) | Image/video editors (§5.6). |
| 7.5 | Confirm dialogs | Archive / delete across groups, collections, cohorts, courses, content. |
| 7.6 | Quiz question feedback states | Per type: correct / incorrect / partial / submitted-for-review / attempts-exhausted. |

---

## 8. Deferred / future (note in the plan; not v1)

These are explicitly wanted later — design data models so they can be added
without rework, but they are **out of v1 scope**:

| Capability | Notes |
|---|---|
| **Notifications & announcements** | Not in v1, but **will** be added. At minimum: teacher/admin announcements to a group, and system event notifications (e.g. "quiz reviewed"). Reserve model hooks now. |
| **Exports (CSV / printable)** | Gradebook-style export of progress/results from the analytics matrix. Definitely needed; later phase. |
| **External result sharing / integration** | A webhook or similar to push results automatically to an external system (e.g. a school's electronic register / SIS). Later; design the results data so it's exportable/streamable. |
| **Notes index page** | A per-course list of notes (jump-links only) for revision navigation. Easy add if wanted. |
| **Teacher per-group color-band override** | Nice-to-have on the analytics matrix. |
