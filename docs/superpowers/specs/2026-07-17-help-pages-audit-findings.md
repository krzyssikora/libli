# Help pages — audit findings (2026-07-17)

Evidence base for the help-pages refresh. Every claim below was checked against
the shipped code by a subagent and cites `file:line` on both sides (the doc's
claim, and the ground truth contradicting it). Findings marked **SUSPECTED** were
not fully confirmed; everything else is **VERIFIED**.

**Method.** Four parallel read-only audits (Teacher / Course Admin / Platform
Admin ×2) diffed all 22 registered `TOPICS` (44 files: `<slug>.md` +
`<slug>.pl.md`) against `templates/`, `*/views*.py`, `*/forms.py`,
`institution/roles.py`, and `locale/pl/LC_MESSAGES/django.po`. The controller
independently spot-verified every HIGH finding cited in §1 and §2 plus the
element registry, the colour bands, and the untranslated-string count.

**Result: 103 findings across 22 topics. No topic is clean.**

| Scope | HIGH | MED | LOW | Total |
|---|---|---|---|---|
| Teacher (7 topics) | 7 | 13 | 18 | 38 |
| Platform Admin (11 topics) | 8 | 25 | 12 | 45 |
| Course Admin (4 topics) | 6 | 8 | 6 | 20 |
| **Total** | **21** | **46** | **36** | **103** |

The findings fall into three classes needing **different treatment**. Only Class 1
is a documentation problem.

---

## §1 — Class 3: product gaps

**§1.1–1.5 are not fixable by editing docs.** These docs are *right*; the product
never got there. The help docs have been serving as a de-facto spec that was never
fully implemented. Each needs a product decision and its own branch — **out of
scope for the docs PR** (decision: 2026-07-17).

**§1.6 is the exception** — it is doc-fixable (delete the claim) and is grouped
here only because, like the rest, it describes UI that never shipped rather than
UI that drifted.

### 1.1 `grouping:collection_create` has no caller — HIGH

The doc says teachers create collections from **My groups → Collections**.
- Claim: `docs/help/teacher/groups-collections.md:33-34`; PL `:34-35`.
- Truth: `grouping/views.py:338` defines the view, `grouping/urls.py:38` routes
  it, and teachers hold `add_collection` (`institution/roles.py:68-74`) — but a
  repo-wide grep for `collection_create` over `**/*.{html,py}` returns exactly
  three hits: the view, the URL, and `tests/test_grouping_collection_views.py:19`.
  **Zero templates link to it.**
- The doc is not stale. It describes a button that was never built (or was
  dropped in the tabbed-Groups reshuffle).
- Decision needed: build the "New collection" button, or delete the claim.

### 1.2 Teacher manual documents flows teachers are 403'd from — HIGH

- Claim: `docs/help/teacher/roster.md` (the whole topic, e.g. `:24-25` "Press
  **Save** to apply") and `groups-collections.md:24-26` instruct the reader to
  create/edit groups. Both are registered TEACHER (`core/help.py:123-136`).
- Truth: `grouping/views.py:189-190` gates `group_create` on
  `grouping.add_group`; `:223-224` gates `group_edit` on `grouping.change_group`.
  `GROUPING_TEACHER_PERMS` (`institution/roles.py:68-74`) grants **neither** —
  it is `[view_group, add_collection, change_collection, delete_collection,
  view_collection]`. Teachers *can* reach the list (`view_group`), so they click
  through and hit a 403.
- Decision needed: re-file under Course Admin, add a read-only preamble, or grant
  the perms. Granting is an **access widening** — see
  `[[access-widening-reachability-tests]]`: drive every newly-reachable surface
  as the new role, latent 500s are likely.

### 1.3 Quiz review is unreachable for teachers — HIGH

- Claim: `docs/help/teacher/quiz-review.md:6-7` "Open it from your course with the
  **Quiz review** button"; PL `:5-6`.
- Truth: the only "Quiz review" link is
  `templates/courses/manage/_course_panel.html:7`, and that partial is included by
  exactly one template — `templates/courses/manage/builder.html:25`, the
  Studio builder, gated `can_manage_course` (`courses/access.py:37-43` = owner or
  `courses.change_course`; teachers have neither). The queue view itself is only
  `@login_required` + `scoping.can_review_course`
  (`courses/views_review.py:108-113`), so a teacher **is allowed in** — they just
  have no link. Reachable only by typing the URL.
- **This is the same bug, in the same partial, that PR #72 already fixed for the
  Analytics link** (see `[[teacher-analytics-link-status]]`). The fix pattern is
  established.

### 1.4 `Multi-select grid` is untranslated — MED

- Truth: `locale/pl/LC_MESSAGES/django.po:1000-1001` — `msgid "Multi-select grid"`
  → `msgstr ""`. It is the **only untranslated msgid in the entire catalog**
  (verified: 1 of ~1000). The palette card renders in English for PL users.
- One-line fix; no decision needed.

### 1.5 `seed_demo_course` creates a broken image — LOW

- Truth: `courses/management/commands/seed_demo_course.py:106` sets
  `file="courses/images/demo.png"` but never creates that file. The demo course's
  image element renders broken.
- Relevant to the screenshot slice (slice 2), which will drive this seed.

### 1.6 "Add user" is documented twice for UI that never existed — HIGH

- Claim: `docs/help/platform-admin/invitations.md:36-37` and
  `users-roles.md:7-8` (PL `:38-39` / `:8-9`).
- Truth: `accounts/urls.py:8-51` has **no user-create route**;
  `templates/accounts/manage/people.html:53-55` offers only **Edit**. A grep for
  "Add user" across `templates/` and `accounts/` returns **nothing**.
- This is doc-fixable (delete the claim) — invitation/SSO is the only path — but
  it is listed here because it documents UI that never shipped, not UI that drifted.

---

## §2 — Class 2: never documented (17 of 31 element types)

`courses/models.py:259-291` registers **31** element types. The docs describe
**14**. The drift is purely *additive omission* — nothing documented was deleted
or renamed.

- Claim: `docs/help/course-admin/content-editors.md:24-58` documents six content
  types (Text, Image, Video, Iframe, Math, HTML); `quiz-editors.md:19-75`
  documents nine question types.
- Truth: `templates/courses/manage/editor/_add_menu.html` renders **four** palette
  groups, not the two the doc claims (`content-editors.md:6-7`):
  Content (`:13`), Interactive (`:28`, gated `{% if not unit_is_quiz %}` at `:27`),
  Questions (`:42`), Structure (`:56`).

Missing, by palette group:

| Group | Missing types |
|---|---|
| Content (5) | Table, Gallery, Callout, Tabs, Columns |
| Interactive (9, lesson-only) | Show more, Fill in & confirm, Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step, Checklist, Guess the number |
| Questions (2) | Matrix question, Multi-select grid |
| Structure (1) | Slide break |

Also undocumented: per-option MCQ feedback (`courses/models.py:1477`
`Choice.feedback`; editor at
`templates/courses/manage/editor/_edit_choicequestion.html:41-42`).

Nesting/gating the docs omit: Questions/Structure/Tabs/Columns are hidden when
nested inside a container (`_add_menu.html:24,25,41`).

**This is authoring, not correction** — a distinct body of work from §3.

---

## §3 — Class 1: genuine drift (doc edits)

### 3.1 Cross-cutting sweeps

Fix these once, everywhere, rather than per-topic:

1. **`Manage` → `Studio`.** `templates/base.html:79` renders `{% trans "Studio" %}`;
   PL msgstr is literally "Studio" (`django.po:3482-3483`, untranslated by design).
   Affects `create-a-course.md:3`, `export-import.md:22`, `subjects.md:20-21`
   (+PL). PL docs saying "**Zarządzaj**" are actively wrong — that word now
   survives only as the Groups sub-tab (`templates/_groups_tabs.html:7`).
2. **PL docs invented field names instead of quoting the catalog.** The single
   biggest systematic failure (≈20 findings). The rule: *quote the rendered
   msgstr, never translate the English afresh.*
   | PL doc says | Product renders | Cite |
   |---|---|---|
   | etykiety | tagi | `django.po:3096-3097` |
   | rocznik / roczniki | kohorta / kohorty | `grouping/group_form.html:26,28` |
   | test (for quiz) | quiz | `my_tags.html:10` msgstr |
   | Branding | Wygląd | `django.po:6047-6048` |
   | Przesyłanie plików | Przesyłanie | `django.po:6051-6052` |
   | Kohort z samodzielnym zapisem | Kto może się zapisać | `django.po:580-581` |
   | sekret podpisujący | Klucz podpisujący | `django.po:2563-2564` |
   | adres URL punktu odbioru | Adres URL punktu końcowego | `django.po:2575-2576` |
   | Slug | końcówka URL (slug) | `django.po:563-564` |
   | Matematyka | Wzór | `django.po:929-933` |
   | Ramka (for Iframe) | Iframe — "Ramka" is **Callout** | `django.po:2210-2213` / `:1058-1062` |
   | Zastosuj / Zastosuj | Zastosuj wybór | `analytics_matrix.html:176` |
   | Eksportuj | Eksport | `django.po:4219-4220` |
   | Szukaj po nazwisku | Szukaj wg nazwiska | `group_form.html:14,33` |
   | Przydziel uczniów | Przypisz uczniów | `cohort_form.html:19,23` |
   | okno retencji | Okno przechowywania (dni) | `django.po:2434-2435` |
   | Administrator Platformy/Kursu | Administrator platformy/kursu | `django.po:2477-2482` |
   | Sprawdzanie testów (×5 cross-links) | Sprawdzanie quizów | `core/help.py:121` msgstr |
3. **Buttons renamed since authoring.** `Add cohort`→**New cohort**;
   `Promote`→**Make default**; `Export course`→**Export**; node `Export`→**Export
   subtree** (icon-only); `Import`→**Import content**; `New`→**New group**;
   `Add subject`→**New subject**; `Apply`→**Apply selection**; `Invite`→**Send
   invitation**; `Add unit`→the `+ Lesson` / `+ Quiz` chips.
4. **Help topic title.** `core/help.py:148` `_("Notes & tags")` → PL "Notatki i
   etykiety" (`django.po:219`) is the only title carrying the etykiety problem.
   Renaming it to **"Tags & notes"** matches the product's own nav
   (`templates/base.html:77`), **reuses the existing msgid** (`django.po:2796-2797`
   → "Tagi i notatki"), and deletes the bad entry — one change fixes terminology,
   word order, and product mismatch. Keep the slug `notes-tags` so URLs and the
   five inbound cross-links keep working.

### 3.2 Behavioural claims that are outright wrong

These would burn a reader following them:

- **Cohort deletion.** Claim `cohorts.md:21-22` "can only be deleted once it has
  no members." Truth: `grouping/services.py:121-124` — `delete_cohort` guards only
  the default cohort, then `_reassign_members_to_default(cohort)` and deletes.
  `cohort_confirm_delete.html:6` "{{ counter }} students will be moved to the
  Default cohort." **No such precondition exists.**
- **Cohort archiving silently empties it.** `grouping/services.py:113-117` —
  `archive_cohort` reassigns all members to Default before setting `archived`.
  Undocumented (`cohorts.md:19-21`).
- **Export does not placeholder all missing media.** Claim `export-import.md:17-18`
  "affected media is replaced with a clearly labelled placeholder". Truth:
  `templates/courses/manage/export_preview.html:14` placeholders **images only**;
  `:16` "Video ... will be left out of the export"; `:18` broken blocks likewise.
- **Grade sync needs four things, not two.** Claim `integrations.md:9-10` "Enter
  the **endpoint URL** and a **signing secret** ... Once both are set". Truth:
  `integrations/services.py:69-73` requires the endpoint row, `endpoint.enabled`
  (the **Enable result sync** toggle — `integrations/forms.py:20-21`,
  `_integrations_tab.html:8`), **and** `course.external_id`. Worse:
  `institution/views_manage.py:79` gates **Send test event** on url+secret only —
  so the test passes while live sync is off and no grades flow.
- **Analytics colour bands.** Claim `analytics.md:19-21` a 3-colour
  green/yellow/grey model keyed on "completed" and a "pass threshold". Truth:
  `courses/color_bands.py:14-26` — **five** percentage bands
  `none/weak/ok/good/excellent` at mins `[0, 40, 60, 75, 90]`, labels
  None/Weak/OK/Good/Excellent (PL Brak/Słabo/OK/Dobrze/Świetnie). Grey is the
  0–39% `none` band, **not** "not attempted"; not-attempted renders an em dash
  (`analytics_matrix.html:85`). Nothing keys off "completed" or a pass threshold.
  The documented model is fabricated.
- **Course Admin permissions (a PA assigning roles from this doc picks wrong).**
  Claim `users-roles.md:18-19` CA "builds and edits courses, and manages groups and
  **cohorts**". Truth: `institution/roles.py:76-86` grants CA `view_cohort` only;
  add/change/delete_cohort are PA-only (`:88-101`). And `*COURSE_PERMS`
  (incl. `add_course`) sits inside `PLATFORM_ADMIN_PERMS` only
  (`institution/roles.py:53-66`) — **a CA cannot create a course**. A CA *can*
  edit a course they own, via `courses/access.py:37-43`
  (`can_manage_course` = owner OR `courses.change_course`). The PL is worse:
  `users-roles.pl.md:18` says "tworzy i edytuje kursy" — *creates* — flatly false.
- **Dashboard entry point.** Claim `builder.md:4-5` and `media-manager.md:4-5`
  "Open it from **Manage courses** on your dashboard: find your course and press
  **Build**." Truth: `templates/core/home.html:45` the panel is **Studio**, and
  `:49` links each owned course **straight to the builder** — there is no Build
  button to press. The "Manage courses" list (with Build at
  `course_list.html:61`) is reached via the **All courses** subtle-link
  (`home.html:57`).
- **Structure presets are not chosen in the builder legend.** Claim
  `builder.md:9`. Truth: `templates/courses/manage/_structure_legend.html:2-5` is a
  static read-only `<p>`; the picker is the `structure` field on CourseForm
  (`courses/forms.py:52-55`), on the metadata form reached via **Edit course
  metadata** (`_course_panel.html:5`). Also undocumented: going *shallower* is
  blocked while items exist at the level being removed (`courses/forms.py:219-244`).
- **Student picker is not course-scoped.** Claim `roster.md:9-10` "everyone
  eligible for the group's course". Truth: `grouping/views.py:155-165` →
  `services.student_users()` (`grouping/services.py:23-33`) returns **every
  non-staff user on the platform**; the course is never consulted.
- **Notifications purge job is misnamed.** Claim `notifications.md:31-32` "the
  scheduled `flush`/purge job". Truth: the job is
  `notifications/management/commands/purge_notifications.py`. `flush_webhooks` is
  the unrelated SIS outbox flusher, and bare `flush` is Django's
  **database-wiping** builtin.
- **Team wizard step is not reachable from Institution settings.** Claim
  `first-run-wizard.md:27-29` "every step it covered" is reachable there. Truth:
  `templates/institution/manage/_tabs.html:3-14` has no Team tab; invitations live
  at Admin → People → Invitations (`templates/accounts/manage/_tabs.html:6`).
- **Sign-up policy is two-choice, not tri-state.** Claim
  `branding-settings.md:20-21` "open, restricted, or disabled". Truth:
  `institution/models.py:20` — `[("invite", "Invite only"), ("open", "Open self-signup")]`.
- **Default theme omits Auto, which is the default.** Claim
  `branding-settings.md:12` "(light/dark)". Truth: `institution/models.py:21,40` —
  three choices, `default="auto"`.
- **Marking fields are quiz-only.** Claim `quiz-editors.md:6` "Every question
  shares a few common fields" (Marking mode / Max attempts / Max marks). Truth:
  `templates/courses/manage/editor/_marking_fields.html:2` wraps all three in
  `{% if is_quiz %}` — not rendered in a lesson.
- **Per-row Force-submit does not confirm.** Claim `quiz-review.md:43-44` "Both ask
  you to confirm first." Truth: `review_queue.html:31-34` has no `data-confirm`;
  only the bulk action does (`review_submission.html:63`).
- **You cannot delete an element from its editor form.** Claim
  `content-editors.md:18`. Truth: `_host_form.html:23-26` offers only Save/Cancel;
  delete is a 🗑 on the element row (`_element_row_controls.html:11-18`).
- **Media deletion is prevented, not refused.** Claim `media-manager.md:28-30`
  "deletion is refused". Truth: `_asset_cell.html:35-36` ships the button
  `disabled` while in use — the attempt cannot be made.

### 3.3 Label/name corrections (MED/LOW)

Per-topic detail lives in the agent reports; the pattern is uniform — a bolded
string in the doc does not exist in any template. Representative:
`Stem`→**Question** / **Prompt (optional)** / **Sentence with blanks** (varies by
type); per-element `title`→**Label (optional)**; `Name`→**Display name**;
`Server URL`→**Issuer / discovery URL**; `Enabled`→**Enable SSO**;
`Explanation`→**Explanation (optional)**; `Feedback`→**Feedback (optional)**;
`This matrix view`→**This matrix view (percentages)**; `back` link→**← Analytics**;
`cherry-pick`→ tick rows then **Apply selection** (and there is no *unit* subset);
`usage count`→**in use ×N** / **unused**; `course count`→"used by N courses";
`Purge now` is a heading, the button is **Purge old notifications now**; the
top-bar **Groups** link *is* My groups (they are tabs in one hub,
`templates/_groups_tabs.html:4-7`), not two lists; `roster.md:4-6` **Edit** does
not exist — the group *name* is the edit link (`group_list.html:13`), and
`group_detail.html` has no edit control at all.

Also: `Slug` is listed under "Required fields" but `courses/forms.py:128` sets
`required = False`; a subject has **two** title fields (`title_en`/`title_pl`) with
the slug derived from the **English** one (`courses/forms.py:261-284`); the
colour-configuration link mentioned at `drill-down.md:41-42` is invisible to
teachers (`courses/views_analytics.py:98` gates it on `can_manage_course`).

### 3.4 SUSPECTED (1 of 103)

- `analytics.md:4-5` "Open it from your course with the **Analytics** button."
  For a teacher the link exists only on the dashboard Teaching panel
  (`templates/core/home.html:33`) and grouping pages
  (`my_groups.html:16,29`, `group_detail.html:9`, `collection_detail.html:9`) —
  no course-facing template renders it. Wording is arguably defensible; verify
  before rewriting.

---

## §4 — Notes for downstream slices

- **PL/EN structural parity holds.** Every `.pl.md` is a section-for-section
  mirror of its base, so **every EN finding reproduces in the PL sibling**. Two
  asymmetries: `users-roles.pl.md:18` is *worse* than EN (claims CAs create
  courses); `notifications.pl.md:33` is *better* (omits the bogus `flush`), and
  `cohorts.pl.md:22` already says "Ustaw jako domyślną" where EN says "Promote".
- **`django.po` is a merge-conflict hotspot.** Slice 1 touches it; the live
  `feat/student-practice-state` worktree may add strings. Sequence accordingly.
- **The root cause is structural, and we are deliberately not fixing it.** Docs
  hard-code UI labels and nav paths with no test binding them to the templates
  they describe. Nothing failed when `Manage` became `Studio`.
  **Decision (2026-07-17): no anti-rot mechanism.** A banned-terms test and a
  UI-label/catalog assertion were both considered and rejected: the app is close
  to feature-complete, so the churn that produced these 103 findings is nearly
  over, and a **re-audit is planned before release**. Re-running this audit costs
  ~20 minutes (four parallel agents; see Method above) — cheaper than machinery
  guarding against a recurrence that is not expected.
- **This document is the re-audit's baseline.** When the pre-release audit runs,
  diff against §3 here: anything that reappears means the fix did not stick.
