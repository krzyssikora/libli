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

> **Not everything in this section is an omission.** Three items here are *wrong
> prose*, which makes them Class-1 defects owned by slice 1a regardless of sitting
> in this section — the slice boundary is **defect type, not findings-section
> number**. They are tagged **[1a]** below. Everything else in §2 is pure additive
> omission, owned by slice 1b.

- Claim: `docs/help/course-admin/content-editors.md:24-58` documents six content
  types (Text, Image, Video, Iframe, Math, HTML); `quiz-editors.md:19-75`
  documents nine question types.
- **[1a]** Truth: `templates/courses/manage/editor/_add_menu.html` renders **four**
  palette groups, and the doc's claim that it is "split into a **Content** group
  and a **Questions** group" (`content-editors.md:6-7`, +PL `:6-8`) is **false
  prose, not an omission**: Content (`:13`), Interactive (`:28`, gated
  `{% if not unit_is_quiz %}` at `:27`), Questions (`:42`), Structure (`:56`).
  1a corrects the group count and names the four groups; enumerating their
  contents is 1b.

Missing, by palette group:

| Group | Missing types |
|---|---|
| Content (5) | Table, Gallery, Callout, Tabs, Columns |
| Interactive (9, lesson-only) | Show more, Fill in & confirm, Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step, Checklist, Guess the number |
| Questions (2) | Matrix question, Multi-select grid |
| Structure (1) | Slide break |

Also undocumented (**1b**, pure omission): per-option MCQ feedback
(`courses/models.py:1477` `Choice.feedback`; editor at
`templates/courses/manage/editor/_edit_choicequestion.html:41-42`).

Nesting/gating (**1b**, pure omission): Questions/Structure/Tabs/Columns are
hidden when nested inside a container (`_add_menu.html:24,25,41`).

**[1a]** `content-editors.md:6-7` group count (above) — wrong prose.
**[1a]** `quiz-editors.md:6` "Every question shares a few common fields" — the
marking fields are quiz-only (`_marking_fields.html:2`); tracked as a §3.2 bullet.

**Ownership:** the 17 element types + MCQ feedback + nesting/gating = **slice 1b**
(authoring, a distinct body of work). The **[1a]** items above are corrections and
belong to slice 1a.

---

## §3 — Class 1: genuine drift (doc edits)

### 3.1 Cross-cutting sweeps

Fix these once, everywhere, rather than per-topic:

1. **`Manage` → `Studio`.** `templates/base.html:79` renders `{% trans "Studio" %}`;
   PL msgstr is literally "Studio" (`django.po:3482-3483`, untranslated by design).
   Affects **only** the *nav entry*, in `create-a-course.md:3`,
   `export-import.md:22`, `subjects.md:20-21` (+PL). PL docs saying
   "**Zarządzaj**" for the nav are actively wrong.

   > **NOT a token sweep — "Manage" survives in the product.** Do not rewrite:
   > `Manage courses` is still the course-list `head_title` and `<h1>`
   > (`templates/courses/manage/course_list.html:3,7`) and is still reachable via
   > the **All courses** subtle-link (`home.html:57`); **Manage** is still the
   > Groups sub-tab (`templates/_groups_tabs.html:7`, PL "Zarządzaj",
   > `django.po:3148-3150`). Confine the edit to the three cited files.
2. **PL docs invented field names instead of quoting the catalog.** The single
   biggest systematic failure (≈20 findings). The rule: *quote the rendered
   msgstr, never translate the English afresh.* Where the "Cite" column names a
   **template** line, resolve the `{% trans %}` msgid on that line and look up
   *its* msgstr — the catalog is always the final authority.

   > **These are sense-scoped, not token sweeps.** Do NOT blanket-replace. Each
   > row is wrong only where it renders the named product concept; several of
   > these tokens are *correct* Polish elsewhere. Carve-outs are called out
   > per row.

   | PL doc says | Product renders | Cite | Scope / carve-out |
   |---|---|---|---|
   | etykiety | tagi | `django.po:3096-3097` | **ONLY** where it means the *tags* feature — i.e. `notes-tags.pl.md` (incl. its H1). `etykieta` is the product's correct PL for a generic **label** (`django.po:1407` "etykieta", `:1678` "etykieta kolumny", `:3959` "Poprawna etykieta:", `:4799` "Strefy i etykiety", `:4812` "Dodatkowe etykiety"). **Leave untouched:** `quiz-editors.pl.md:63,66,71,74,75` (drag-to-image, match pairs), `sso.pl.md:12`, `subjects.pl.md:33`. |
   | rocznik / roczniki | kohorta / kohorty | `grouping/group_form.html:26,28` (msgid `Cohort`/`All cohorts`) | `groups-collections.pl.md:3,7,9,13,39`; `roster.pl.md:11,12,32,37` |
   | test (for quiz) | quiz | msgid `You haven't created any tags yet. Open a lesson or quiz and add one.` → msgstr "…Otwórz lekcję lub **quiz** i dodaj tag." (rendered at `my_tags.html:10`) | PL docs only, and only for the *unit type*. **Leave untouched:** EN prose ("Send test event"), and PL "test" used in its ordinary sense. |
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

- **The "My tags" page and its nav link do not exist** (finding **B00**). Claim
  `notes-tags.md:38` "The **My tags** page — reachable from the nav link of the
  same name". Truth: the nav link is **Tags & notes** → `notes:overview`
  (`templates/base.html:77`); the page's `<h1>` is **Tags & notes**
  (`tags/templates/tags/my_tags.html:7`) — "My tags" survives only as its
  `head_title` (`:3`). The real path is nav **Tags & notes** → the **Manage tags**
  tab (`templates/_tags_notes_tabs.html:5-6`; the other tab is **By course**).
  Post-hub drift ([[tags-and-notes-hub-status]], PR #76). PL `notes-tags.pl.md:39`
  says "**Moje etykiety** … z odnośnika nawigacji o tej samej nazwie" — wrong on
  the term *and* the link *and* the page name.
  *(This is the finding that triggered the whole audit. It was used as an
  orienting anchor for the subagents and told to them as "already known — do not
  re-report", which is exactly why it went unrecorded until spec-review round 1
  caught the omission. Recorded here so the worklist is complete.)*

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

### 3.3 Label/name corrections (MED/LOW) — enumerated

The pattern is uniform: a bolded string in the doc exists in no template. Each row
is one finding with an ID. **Every row applies to the `.pl.md` sibling too**
(PL/EN parity, §4) — the PL fix is the `msgstr` of the same msgid, never a fresh
translation.

| ID | Topic | Doc claim | Truth (cite) |
|---|---|---|---|
| L01 | builder | "**Add unit**" (`builder.md:21`) | two chips `+ Lesson` / `+ Quiz` beside a **New title** field (`_add_affordance.html:15-24`) |
| L02 | builder | deepen/shallow symmetry implied (`builder.md:16-17`) | going shallower is **blocked** while items exist at the removed level (`courses/forms.py:219-244`) |
| L03 | content-editors | "Delete an element from its **editor form**" (`content-editors.md:18`) | form has only Save/Cancel (`_host_form.html:23-26`); delete is 🗑 on the row (`_element_row_controls.html:11-18`) |
| L04 | content-editors | author-only "**title**" (`content-editors.md:20-21`) | **Label (optional)**, placeholder "Shown in the element list" (`_host_form.html:18-20`); PL "Etykieta (opcjonalnie)" (`django.po:5246`) |
| L05 | content-editors | PL "**Matematyka**" (`content-editors.pl.md:51,67`) | palette renders **Wzór** (`django.po:929-933`) |
| L06 | content-editors | PL "**Ramka (iframe)**" (`content-editors.pl.md:43`) | Iframe→**Iframe** (`django.po:2210-2213`); **Ramka** is the PL name of *Callout* (`django.po:1058-1062`) |
| L07 | content-editors | "outline on the left" (`content-editors.md:4-5`) | it is the **Editor** pane of a two-pane grid with an **Editor/Split/Preview** toggle (`_editor_scope.html:2-18`, `editor.html:68-75`) |
| L08 | quiz-editors | "**Stem**" (`quiz-editors.md:8`) | internal field name; rendered label is **Question**, **Prompt (optional)**, or **Sentence with blanks** by type (`_edit_choicequestion.html:5`, `_edit_matchpairquestion.html:3`, `_edit_fillblankquestion.html:3`) |
| L09 | quiz-editors | "**Explanation**" (`quiz-editors.md:9`) | **Explanation (optional)** (`_edit_choicequestion.html:52` +7 siblings) |
| L10 | quiz-editors | PL headings nominalized (`quiz-editors.pl.md:30,40,46,54,61,69,78`) | palette uses imperatives: Krótki tekst / Liczba / Uzupełnij luki / Przeciągnij słowa / Dopasuj pary / Przeciągnij na obraz / Rozszerzona odpowiedź (`django.po:2217,2222,2228,2233,2238,782,2248`) |
| L11 | media-manager | "**usage count**" (`media-manager.md:20`) | renders **in use ×N** (expands to a unit list) or **unused** (`_asset_cell.html:19,21-28,31`) |
| L12 | media-manager | "deletion is **refused**" (`media-manager.md:28-30`) | button ships `disabled` while in use — the attempt cannot be made (`_asset_cell.html:35-36`) |
| L13 | sso | "**Name**" (`sso.md:11`) | **Display name** (`accounts/forms.py:176-181`); PL "Nazwa wyświetlana" (`django.po:23-24`) |
| L14 | sso | "**Server URL**" (`sso.md:12`) | **Issuer / discovery URL** (`accounts/forms.py:182-191`); PL "Adres wydawcy / discovery" (`django.po:77-78`) |
| L15 | sso | "**Enabled**" (`sso.md:17,29`) | **Enable SSO** (`accounts/forms.py:175`, `_sso_fields.html:8`); PL "Włącz logowanie SSO" (`django.po:69-70`) |
| L16 | sso | PL leaves "Client ID"/"Client secret" English (`sso.pl.md:14`) | **Identyfikator klienta** / **Sekret klienta** (`django.po:91-96`) |
| L17 | subjects | "**Add subject**" (`subjects.md:6`) | **New subject** (`subject_list.html:8`); PL "Nowy przedmiot" (`django.po:5639-5640`) |
| L18 | subjects | "a name and a slug" (`subjects.md:6-7`) | **two** title fields `title_en`/`title_pl`; slug derives from the **English** title (`courses/forms.py:261-284`) |
| L19 | subjects | "**course count**" (`subjects.md:10-11`) | renders "used by {{ n }} courses" as a filter link (`subject_list.html:19`) |
| L20 | create-a-course | Slug under "## Required fields" (`create-a-course.md:7,10`) | `courses/forms.py:128` sets `required = False` |
| L21 | invitations | "use **Invite**" (`invitations.md:3-4`) | always-visible form; button is **Send invitation** (`invitations.html:13-19`); PL "Wyślij zaproszenie" (`django.po:3336-3337`) |
| L22 | notifications | "the scheduled `flush`/purge job" (`notifications.md:31-32`) | job is `purge_notifications`; `flush_webhooks` is the SIS outbox; bare `flush` is Django's **DB-wiping** builtin |
| L23 | notifications | "Use **Purge now**" (`notifications.md:29-30`) | *Purge now* is the `<h2>`; the button is **Purge old notifications now** (`_notifications_tab.html:22,25`) |
| L24 | notifications | PL "**okno retencji**" (`notifications.pl.md:27`) | **Okno przechowywania (dni)** (`django.po:2434-2435`) |
| L25 | users-roles | Role select "on a user's row" (`users-roles.md:28-29`) | row has only **Edit** (`people.html:53-55`); the select is on the edit page (`user_form.html:15`). The row's "Role" select is a **filter** (`people.html:18-25`) |
| L26 | users-roles | "**Deactivate** on the user's row" (`users-roles.md:36-37`) | activation buttons are on the edit page (`user_form.html:32-39`) |
| L27 | users-roles | PL "Administrator **P**latformy/**K**ursu" (`users-roles.pl.md:3,19-22`) | "Administrator platformy" / "Administrator kursu" — lowercase (`django.po:2477-2482`) |
| L28 | branding-settings | tabs list omits Notifications (`branding-settings.md:3-5`) | `_tabs.html:11-12` renders a sixth tab with its own topic (`core/help.py:215-220`) |
| L29 | export-import | bolded flow-step names (`export-import.md:16-17,26-29`) | real strings: **Export — missing media** / **Export anyway** (`export_preview.html:6,24`), **Upload and preview** (`import_course.html:29`), **Confirm import** (`import_preview.html:51`) |
| L30 | integrations | "A delivery is queued" (`integrations.md:22`) | **one delivery per group** the student is in; review-pending submissions emit only after review (`integrations/services.py:75-85`) |
| L31 | first-run-wizard | "Each step can be **skipped**" (`first-run-wizard.md:19`) | Team has no Skip — only Invite another/Back/**Next** (`setup/team.html:21-41`); Next does skip (`views_setup.py:168-170`) |
| L32 | analytics | "**cherry-pick** filter … students **or units**" (`analytics.md:36-37`) | tick student rows then **Apply selection** (`analytics_matrix.html:176-177`); checkboxes are `name="student"` only (`:141`); **no unit subset exists**; "cherry-pick" is in no template |
| L33 | drill-down | "press **Apply**" (`drill-down.md:29`) | **Apply selection** (`analytics_matrix.html:176`); PL **Zastosuj wybór** |
| L34 | drill-down | PL "**3 zaznaczonych**" (`drill-down.pl.md:36`) | renders "Zaznaczono: 3" (`%(n)s selected` msgstr, `analytics_matrix.html:179`). EN `drill-down.md:34` is correct |
| L35 | drill-down | "the **back** link" (`drill-down.md:46-47`) | **← Analytics** / **← Analityka** (`analytics_student.html:9`) |
| L36 | drill-down | colour-config link listed for teachers (`drill-down.md:41-42`) | gated `can_edit_bands` = `can_manage_course` (`views_analytics.py:98`, `analytics_matrix.html:8-11`) — invisible to teachers |
| L37 | gradebook-export | "**This matrix view**" (`gradebook-export.md:19`) | **This matrix view (percentages)** (`analytics_matrix.html:24`) |
| L38 | gradebook-export | PL "**Dziennik testów (punkty surowe)**" (`gradebook-export.pl.md:21`) | **Dziennik quizów (surowe wyniki)** (`analytics_matrix.html:26`) |
| L39 | groups-collections | "top-bar **Groups** list (or **My groups**)" (`groups-collections.md:23-24`) | one hub, two tabs — the top-bar "Groups" link **is** My groups (`base.html:81-83`, `_groups_tabs.html:4-7`) |
| L40 | groups-collections | "Create a group with **New**" (`groups-collections.md:24`) | **New group** (`group_list.html:6`); PL "Nowa grupa" |
| L41 | groups-collections | PL "**Domyślny** … *(domyślny)*" (`groups-collections.pl.md:12`) | seeded name is the literal "Default" (`grouping/migrations/0002_default_cohort_backfill.py:12`), rendered "Default (**domyślna**)" (`grouping/models.py:50-55`) |
| L42 | roster | "press **Edit** … or **New**" (`roster.md:4-6`) | no Edit button — the group **name** is the edit link (`group_list.html:13`); rows have only Archive/Delete (`:18,20`); `group_detail.html` has **no edit control at all**; "New" is **New group** (`group_list.html:6`) |
| L43 | roster | PL "**Szukaj po nazwisku**" (`roster.pl.md:14`) | **Szukaj wg nazwiska** (`group_form.html:14,33`) |
| L44 | roster | PL "**Przydziel uczniów**" (`roster.pl.md:35`) | **Przypisz uczniów** (`cohort_form.html:19,23`) |
| L45 | quiz-review | "**Awaiting review**" PL (`quiz-review.pl.md:12`) | **Oczekuje na ocenę** (`review_queue.html:10`) |
| L46 | quiz-review | PL "**Wymuś wysłanie**" (`quiz-review.pl.md:16,39`) | **Wymuś przesłanie** (`review_queue.html:33`). But `:44`'s "Wymuś wysłanie wszystkich (N)" **is** correct — the product itself is inconsistent; quote each label as-is |
| L47 | quiz-review | "each with a count" (`quiz-review.md:23`) | *Reviewed* has no count (`review_submission.html:39-40,44-45,49`) |
| L48 | quiz-review | "**Feedback** box" (`quiz-review.md:27`) | **Feedback (optional)** (`review_submission.html:103`) |
| L49 | notes-tags | PL "**test**" for quiz (`notes-tags.pl.md:26,43`) | product says **quiz** — `:43` paraphrases the very string whose msgstr reads "Otwórz lekcję lub quiz" (`my_tags.html:10`) |
| L50 | groups-collections | PL "sprawdzanie **testów**" (`groups-collections.pl.md:21`) | product's PL word is **quiz** (see L49) |

**§3.3 total: 50 findings.**

### 3.5 H1 ≠ registry title (found by spec-review, not the audit)

A topic renders **two** titles: the registry title as page chrome
(`templates/help/doc.html:3,14,20` — head title, sidebar, breadcrumb) and the
markdown body's own H1. They are separate strings and nothing binds them.
Mechanically diffing all 22 topics against `TOPICS` and the PL msgstrs found
**four files already mismatched**:

| ID | File | Registry title renders | H1 says |
|---|---|---|---|
| H01 | `platform-admin/branding-settings.md:1` | Branding & settings | Branding & **platform** settings |
| H02 | `platform-admin/sso.pl.md:1` | Logowanie SSO (OIDC) | SSO (OIDC) |
| H03 | `platform-admin/integrations.md:1` | Integrations | Integrations **(grade sync)** |
| H04 | `platform-admin/integrations.pl.md:1` | Integracje | Integracje **(synchronizacja ocen)** |

**These are NOT mechanical fixes and are NOT slice-1a scope.** Each needs a
product decision, because the H1 is often the *better* string and matching it to
the registry would delete information ("(grade sync)" tells the reader what the
topic is; "Integrations" does not). Worse, `branding-settings` cannot be satisfied
by mirroring in both languages at once: the EN registry title lacks the "platform"
that its own PL msgstr carries ("Branding i ustawienia **platformy**"), so EN and
PL disagree about what the title even is.

Resolving these means either editing four H1s or renaming three registry titles
(new msgids, new translations) — a scope 1a explicitly does not take (§2 of the
slice-1a spec allows exactly **one** registry rename). **Defer to a follow-up.**

`notes-tags` is *not* in this table: it satisfies the invariant today. The slice-1a
rename is what would break it, which is why that spec fixes both its H1s.

### 3.4 SUSPECTED (1 of 103)

- `analytics.md:4-5` "Open it from your course with the **Analytics** button."
  For a teacher the link exists only on the dashboard Teaching panel
  (`templates/core/home.html:33`) and grouping pages
  (`my_groups.html:16,29`, `group_detail.html:9`, `collection_detail.html:9`) —
  no course-facing template renders it. Wording is arguably defensible; verify
  before rewriting.

---

### 3.6 Found during slice-1a execution

> Additions made while executing the slice-1a plan (2026-07-17). Spec §5 / plan G5:
> **the audit is a floor, not a ceiling** — anything found while editing a topic is
> in scope, and must be recorded here so the pre-release re-audit has a true
> baseline. **This document is that baseline**: an unrecorded fix looks like a
> regression when the re-audit diffs against §3.
>
> Each topic task appends its own additions here as it goes, rather than batching
> them at the end — a finding made in Task 4 should not have to survive twenty
> tasks in someone's head. This list is **open**: if a task surfaces something the
> plan did not enumerate, append it. Treating the enumeration as closed would
> reproduce, one level up, the exact partial coverage this section exists to record.

- **Task 3 (`notes-tags`), fixed.** `notes-tags.md:10-11` "When a block has no
  notes yet it reads **Add note**" claimed visible text. It isn't: in
  `notes/templates/notes/_block_notes.html:9` `{% trans 'Add note' %}` is only
  the `<summary>`'s `aria-label` (screen-reader-only); the handle's visible
  content is icon-only (SVG, no text — `notes.css:51-83` has no
  `attr()`/`content` trick that would surface it) in **both** states, so the
  doc's empty-vs-filled contrast (text → icon) was wrong on both sides, not
  just the "Add note" half. Affected **both languages**:
  `notes-tags.md:10-11` and `notes-tags.pl.md:10-11` ("widnieje na nim **Dodaj
  notatkę**"). Fixed in both to describe the real control (an icon handle,
  with "Add note" / "Dodaj notatkę" accurately reframed as the screen-reader
  label, not visible text) plus the actual filled-state change (a count
  badge, not a differently-labelled icon).

- **Task 6 (`gradebook-export`), observed then fixed in a coordinated
  cross-topic pass.** The standard §3.4 spillover sentence ("each group or
  collection card carries its own **Analytics** link scoped to that group or
  collection") is unconditionally true for **groups**
  (`templates/grouping/my_groups.html:16` — no `{% if %}` guard) but the
  **collection** card's Analytics link is gated behind `{% if c.can_review %}`
  (`my_groups.html:29`; the comment at `:325-327` records that `can_review` is
  course-wide and does not consult collection ownership). The shared sentence
  overclaimed for collections whose viewer lacks `can_review`. **This claim
  was not in the original audit — it was introduced by slice 1a's own §3.4
  replacement standard**, and shipped verbatim in `analytics.md`/`.pl.md`
  (Task 4) and `drill-down.md`/`.pl.md` (Task 5) before Task 6 applied it a
  third time in `gradebook-export.md`/`.pl.md` (per this task's explicit
  instruction to reuse the exact prose for cross-topic parallelism), so a
  unilateral fix in only one of the three topics would itself have created a
  contradiction between topics. **Fixed in a single coordinated dispatch
  across all six files** (EN: `analytics.md`, `drill-down.md`,
  `gradebook-export.md`; PL: `analytics.pl.md`, `drill-down.pl.md`,
  `gradebook-export.pl.md`). Each language now reads (modulo each file's
  existing antecedent): EN — "each group card carries an **Analytics** link
  scoped to that group. Collection cards carry one too, when you can review
  that collection's course."; PL — "każda karta grupy ma odnośnik
  **Analityka** ograniczony do tej grupy. Karta kolekcji ma go również,
  jeśli możesz przeglądać kurs tej kolekcji." The pre-release re-audit
  should treat this as already-fixed baseline, not as pre-existing drift.

- **Task 8 (`groups-collections`), G5 additions — two, both fixed.**
  1. **Archive is a 403 too, not just create/edit.** §1.2/§3 row 2 name only
     `group_create`/`group_edit` as 403 for teachers. `group_archive`
     (`grouping/views.py:252-255`) is `@permission_required("grouping.change_group")`
     — the same permission as edit, and `GROUPING_TEACHER_PERMS`
     (`institution/roles.py:68-74`) grants teachers neither. The doc's archive
     sentence ("You can **archive** a group…") was an equally false imperative,
     just uncatalogued. Folded into the third-person reframe alongside
     create/edit — **not** merged with `group_delete` (`views.py:261-263`),
     which gates on the separate `grouping.delete_group` and the doc never
     mentioned deletion. Also confirmed the **Show archived**/**Show active**
     toggle is a plain `?archived=` link (`templates/grouping/group_list.html:7`,
     no decorator) — genuinely open to teachers — so it was kept OUTSIDE the
     403 frame, not swept in with archive.
  2. **The Cohorts paragraph's teacher-use claim is false under the very
     permission gate this task exists to document.** `groups-collections.md:13`
     / `.pl.md:13-14` said cohorts are "mostly use[d] as a filter when
     building a roster." The only cohort-filter UI in the app is the student
     picker inside `templates/grouping/group_form.html:26-29` — reachable
     exclusively via `group_create`/`group_edit`, both gated on
     `add_group`/`change_group` (`grouping/views.py:189,223`), neither of
     which `GROUPING_TEACHER_PERMS` grants. `GROUPING_TEACHER_PERMS`
     (`institution/roles.py:68-74`) holds **no cohort permission at all** —
     not even `view_cohort` (contrast `GROUPING_COURSE_ADMIN_PERMS:76-86`,
     which does). A repo-wide template grep for `cohort` (`templates/**/*.html`)
     confirms `group_form.html` is the only teacher-relevant surface; no other
     teacher-reachable page filters or displays cohort membership. So a
     teacher never sees a cohort filter through any reachable UI — the claim
     was symmetric-false in both languages. Fixed in both files' Cohorts
     paragraph to state plainly that teachers don't interact with cohorts
     directly; they exist quietly in the background.
  Not previously in the audit's §1/§3 tables under either topic. No further
  claims in this topic were found to be false on re-verification against
  `grouping/views.py`, `institution/roles.py`, and `templates/grouping/`.

- **Task 9 (`roster`), one dispute + one audit-missed EN fabrication, both
  resolved.**
  1. **L44 disputed, not applied as written.** §3 row (`| Przydziel uczniów |
     Przypisz uczniów | cohort_form.html:19,23 |`) is itself a fabrication —
     verified false three ways: `msgid "Assign students"` does not exist in
     `locale/pl/LC_MESSAGES/django.po` (grep: zero hits); no template renders
     that string in either language; `templates/grouping/cohort_form.html:19`
     renders a **long** label — `{% trans "Assign students to this cohort
     (moves them from their current cohort)" %}` → msgstr "Przypisz uczniów do
     tej kohorty (przeniesie ich z obecnej kohorty)" (`django.po` lookup
     confirmed) — plus a button at `:23`, `{% trans "Assign" %}` → **Przypisz**
     (`django.po` lookup confirmed). L44's *direction* (the doc invented a
     label) was right; its *target* (`**Przypisz uczniów**`) was itself
     invented. **Resolution:** described the control by what it actually
     renders — the long checkbox-list caption quoted verbatim plus the real
     **Assign**/**Przypisz** button — with no bolded pseudo-label in either
     language. `roster.pl.md`'s "Kohorty przydziela się gdzie indziej" section.
  2. **EN has the identical fabrication and the audit missed it.**
     `roster.md:34` (pre-edit) — "on the cohort's own edit page (its **Assign
     students** list)" — is the same invented short label as the PL side, just
     never caught because §3's row only listed the PL string. Not in the
     audit's §1/§3 tables under either language for EN. Fixed identically:
     `roster.md`'s "Cohorts are assigned elsewhere" section now quotes the
     real long caption instead of a bolded pseudo-label.
  Verification note: the brief's Step 5 gate `grep -rn 'Assign students'
  docs/help/teacher/roster.md` no longer returns zero, because the corrected
  prose legitimately quotes the real msgid, which begins with that phrase
  ("Assign students to this cohort (moves them from their current cohort)").
  The precise fabrication-only gate (`its **Assign students** list`, bolded
  short label) does return zero, as required — confirmed by grep. This is
  flagged here so the pre-release re-audit does not mistake the legitimate
  quote for a regression of the fabrication.
  No further claims in this topic were found to be false on re-verification
  against `grouping/views.py`, `grouping/services.py`, `grouping/forms.py`,
  `institution/roles.py`, and `templates/grouping/`.

- **Task 10 (`builder`), G5 addition — "one of four structure presets" is
  itself false, fixed.** `builder.md:9` (pre-edit) claimed every course uses
  "one of four structure presets, chosen in the builder legend" — already
  known wrong on the legend half (§3.2, not chosen there). Re-verifying the
  preset-count half against `courses/ordering.py:165-171`
  (`preset_for_flags()` — a reverse lookup that returns `None`, "else None
  (Custom)", when a course's `uses_parts`/`uses_chapters`/`uses_sections`
  flag-triple matches none of the four presets) and `courses/forms.py:184`
  (`if current is None:  # Custom course`, which then sets a distinct
  "Custom: %(chain)s (keeps current structure)." help-text branch,
  `forms.py:185-187`) confirms a course **can** be Custom — the four presets
  are not exhaustive. Fixed in both languages: `builder.md`'s "Structure
  presets" intro now reads "one of four structure presets, or a custom chain
  of levels"; `builder.pl.md` "jednego z czterech presetów struktury albo z
  własnego, niestandardowego układu poziomów". Also folded in while editing
  the same section (not previously in §3's L02 row as prose, only as a bare
  claim): the shallower-transition block is now described in-doc — "Going
  shallower is only possible once no content exists at the level being
  removed — move or delete it first" (EN) / "Spłycenie struktury jest
  możliwe dopiero, gdy usuwany poziom nie zawiera żadnych treści — najpierw
  je przenieś lub usuń" (PL) — sourced from `courses/forms.py:219-244`
  (`clean()` raises `ValidationError` naming in-use levels) and the form's
  own help-text at `courses/forms.py:192-195` (msgstr confirmed at
  `locale/pl/LC_MESSAGES/django.po:689-693`).
  No further claims in this topic were found false on re-verification
  against `templates/courses/manage/_add_affordance.html`,
  `templates/courses/manage/_structure_legend.html`,
  `templates/courses/manage/_tree_node.html` (drag-to-reorder grip confirmed
  real, `:9`), `templates/courses/manage/_course_panel.html`, and
  `templates/core/home.html`.

- **Task 12 (`quiz-editors`), two G5 additions beyond the plan's own list,
  both fixed.**
  1. **L08's four-item stem-label list was itself incomplete — a fifth
     template exists but renders no distinct label at all, so it does not
     add a fifth entry.** The plan's brief already caught that
     `_edit_dragfillblankquestion.html:3` renders a fourth stem-label variant
     (`{% trans "Sentence with gaps" %}` → **Zdanie z lukami**) beyond the
     audit's three. Re-verifying against every question-type template
     (`_edit_choicequestion.html:5`, `_edit_shortnumericquestion.html:3`,
     `_edit_shorttextquestion.html:3` → `{% trans "Question" %}`;
     `_edit_dragtoimagequestion.html:4`, `_edit_matchpairquestion.html:3`,
     `_edit_choicegridquestion.html:12`, `_edit_multigridquestion.html:11` →
     `{% trans "Prompt (optional)" %}`; `_edit_fillblankquestion.html:3` →
     `{% trans "Sentence with blanks" %}`) confirms exactly four distinct
     stem-label msgids exist across all question types — no fifth. The doc
     now states this: EN four bolded entries (`Question`, `Prompt
     (optional)`, `Sentence with blanks`, `Sentence with gaps`); PL three,
     because `Sentence with blanks` and `Sentence with gaps` share one
     msgstr (**Zdanie z lukami**) — confirmed at
     `locale/pl/LC_MESSAGES/django.po:4754-4755,4829-4830`.
  2. **PL `zakazanych` in the Extended response section does not derive from
     the actual msgstr root.** `_edit_extendedresponsequestion.html:14`
     `{% trans "Forbidden keywords (one per line)" %}` →
     `locale/pl/LC_MESSAGES/django.po:4825-4826` msgstr "Zabronione słowa
     kluczowe (po jednym w wierszu)". The pre-edit doc's parallel bolded
     adjective pair read "**wymaganych** i **zakazanych**" — the first
     ("required") correctly derives from msgstr "Wymagane"
     (`django.po:4821-4822`), but the second used "zakazanych" (from
     "zakazany", a correct but *different* Polish synonym for "forbidden")
     instead of "zabronionych" (from "zabroniony", the catalog's actual
     word). Not in the plan's own §2/L-citation list for this task. Fixed:
     `quiz-editors.pl.md`'s Extended response section now reads
     "**zabronionych**".
  All other per-type claims (marking-exact-match logic in
  `courses/models.py` `ChoiceQuestionElement.mark()`; Short text's
  "accepted answers"/"case sensitive" toggle; Short numeric's
  "tolerance"/"value"; Fill in the blanks' `{{answer}}`/`|` syntax; Match
  pairs' left/right/distractors; Drag to image's zone editor; Extended
  response's required/forbidden keyword lists otherwise) were re-verified
  against their templates and the `pl` catalog and found accurate in both
  languages — no further findings.

- **Task 13 (`media-manager`), G5 addition beyond the plan's own list,
  fixed.** The plan's own Step 5 already flagged that the doc's claim of a
  single shared **Choose media** button for "Image and Video content blocks,
  the Drag to image question" was partly false —
  `templates/courses/manage/editor/_edit_dragtoimagequestion.html:17`
  renders `{% trans "Choose image" %}`/`{% trans "Change image" %}`, not
  `{% trans "Choose media" %}` (confirmed against `_edit_image.html:8` and
  `_edit_video.html:12`, which do render `{% trans "Choose media" %}`).
  Fixed in both languages: the doc now names the Image/Video blocks'
  **Choose media** button separately from the Drag to image question's
  **Choose image**/**Change image** button (msgstr "Wybierz plik" /
  "Wybierz obraz" / "Zmień obraz",
  `locale/pl/LC_MESSAGES/django.po`). Re-verifying the rest of the topic
  against `templates/courses/manage/media/_asset_cell.html`,
  `_asset_grid.html`, `_picker.html`, and `_picker_grid.html` found no
  further false claims — the Library/Upload picker tabs, the per-kind
  extension/size-ceiling claim, and the Rename/Delete affordances (beyond
  L11/L12, already in §3) all match the templates and catalog in both
  languages.

- **Task 14 (`branding-settings`), G5 addition confirming the plan's own
  Step 5 diagnosis, not fixed (product bug, filed for Task 27).**
  Re-verified `institution/forms.py:65-86` (`BrandingForm.Meta.fields`) and
  `:152-164` (`AccessForm.Meta.fields`): `name`, `logo`, `default_theme`
  (Branding) and `signup_policy` (Access) are `ModelForm`-auto-derived
  labels with no `label=_(...)` override and **no catalog entry at all**
  (confirmed: `grep '^msgid "Default theme"' locale/pl/LC_MESSAGES/django.po`
  → zero hits) — they render in English under a Polish UI, exactly as the
  plan's Step 5 already stated. The pre-edit PL doc had silently
  mistranslated this bug away: `branding-settings.pl.md` bolded
  **Polityka rejestracji** as if it were the field label, but that phrase
  is not in the catalog under any msgid (`grep 'Polityka rejestracji'
  locale/pl/LC_MESSAGES/django.po` → zero hits) and does not match what
  actually renders (`Signup policy`, English, per the bug above) or the
  section `<h2>` (`{% trans "Sign-up policy" %}` →
  `templates/institution/manage/_access_fields.html:6` → msgstr "Zasady
  rejestracji", `django.po:5913-5914` — a *different*, hyphenated string).
  Fixed per the plan's explicit decision: the PL Access bullet now names
  the real, untranslated field text (**Signup policy**, parenthetically
  noted as not yet translated) instead of either invented alternative, and
  quotes the two real translated **choice values** — `django.po:2440-2446`
  confirms `SIGNUP_CHOICES` msgids `"Invite only"` → **Tylko z
  zaproszeniem** / `"Open self-signup"` → **Otwarta samodzielna
  rejestracja** are genuinely localized (the choice *values* go through
  `_()` in `institution/models.py:20`, unlike the field *label*, which does
  not — the bug is label-only). Left the `**domyślny motyw**` / `**default
  theme**` field-name bolding untouched in both languages (same
  auto-derived-label bug applies to it too, already covered by this same
  filed product gap; not a new claim, no competing catalog string tempts a
  wrong substitution the way `Polityka rejestracji`/`Zasady rejestracji`
  did, so no doc rewrite was warranted there beyond the choice-list fix the
  plan specified). No further claims in this topic were found false on
  re-verification against `institution/models.py`,
  `institution/forms.py`, and `templates/institution/manage/_tabs.html`.

- **Task 15 (`cohorts`), two additions, both fixed.**
  1. **L41's defect (seeded-name mistranslation) recurs here, in three
     places, not filed against this topic before.** `cohorts.pl.md`
     translated the Default cohort's *name* itself (`Domyślnej` dative,
     „Domyślna” quoted-nominative, `Domyślną` instrumental) as if
     "Domyślna" were the stored value. It isn't: the seed migration
     (`grouping/migrations/0002_default_cohort_backfill.py:12`) creates it
     with the literal English `name="Default"`, and `Cohort.display_name`
     (`grouping/models.py:49-55`) renders it `"{name} ({_('default')})"` —
     only the parenthetical marker is translated (`msgid "default"` →
     msgstr "domyślna", `django.po:2342-2343`), giving **"Default
     (domyślna)"**, never "Domyślna" alone. Fixed all three spots to say
     **Default** (undeclined, matching the `groups-collections.pl.md`
     precedent already fixed for L41 itself) with one explanatory
     parenthetical on first mention; **kept** the `## Kohorta domyślna`
     heading unchanged since it names the concept ("the default cohort"),
     not the stored object.
  2. **G5 addition: "Make default" silently un-archives.**
     `cohort_promote` (`grouping/views.py:78-81`) is wired for every
     non-default cohort regardless of `archived` state —
     `cohort_list.html:14-17` renders the **Make default** form outside
     any archived-guard. `promote_default` (`grouping/services.py:73-90`)
     un-archives the cohort it promotes: "a default cohort must never be
     archived (it would vanish from pickers yet still auto-receive new
     members)" (docstring, same file). Undocumented in both languages'
     "Creating and archiving cohorts" section and beyond the plan's two
     flagged fixes (deletion precondition, archive-empties). Fixed in
     both: EN `cohorts.md` "**Make default** makes a different cohort the
     new Default (promoting an archived cohort also un-archives it)"; PL
     `cohorts.pl.md` "**Ustaw jako domyślną** czyni inną kohortę nową
     kohortą Default (ustawienie zarchiwizowanej kohorty jako domyślnej
     automatycznie przywraca ją z archiwum)".

- **Task 20 (`invitations`), fixed.** G5 re-check of the "Expiry, resending
  and revoking" section's bullet labels against `templates/accounts/manage/
  invitations.html:39-40` and `django.po:3352-3357` found the PL doc paraphrasing
  instead of quoting: `invitations.pl.md` said **"Wysłać ponownie"** (infinitive
  "to resend") where the button's msgstr is **"Wyślij ponownie"** (imperative;
  msgid `"Resend"`), and **"Odwołać"** where the button's msgstr is **"Cofnij"**
  (msgid `"Revoke"`) — not a grammatical variant but a different word entirely.
  Fixed both bullets to quote the msgstr verbatim: **Wyślij ponownie** /
  **Cofnij**.

- **Task 22 (`notifications`), fixed.** G5 re-check of the "Retention and
  purge" section against `templates/institution/manage/_notifications_tab.html`
  found two undocumented controls beyond the plan's L22–L24 fixes:
  1. `_notifications_tab.html:23` renders **"Purge uses the saved retention
     value; save your changes first."** — the doc's original "Set the
     retention window … Use Purge now" sequence implied the typed value took
     effect immediately. It does not: the retention window and the purge
     button live in **separate forms** (`:2` and `:19`), so purging before
     saving purges against the *old* window. Folded the warning into both
     languages.
  2. `_notifications_tab.html:14` renders a separate **"Save retention
     settings"** submit button that neither doc named. Named it in both:
     EN **Save retention settings**; PL **Zapisz ustawienia przechowywania**
     (msgid `"Save retention settings"`, verified at
     `locale/pl/LC_MESSAGES/django.po:2990-2991`).
  Also fixed the three plan-flagged findings: L22 EN `flush`/purge job →
  `` `purge_notifications` `` (the real retention entry point,
  `notifications/retention.py:51`; bare `flush` is Django's DB-wiping
  builtin, `flush_pending` in `integrations/flush.py` is the unrelated SIS
  outbox flusher); L23 kept **both** surviving strings rather than a naive
  swap — *Purge now* is the `<h2>` (`:22`), **Purge old notifications now**
  is the button (`:25`) — worded as "Under this tab's *Purge now* heading,
  the **Purge old notifications now** button …" (PL: "W sekcji *Wyczyść
  teraz* … przycisk **Wyczyść stare powiadomienia teraz** …"); L24 PL
  `**okno retencji (w dniach)**` → **Okno przechowywania (dni)** (msgid
  `"Retention window (days)"`, `django.po:2437-2438`). Per G7,
  `notifications.pl.md` already omitted the bogus `flush` — that carve-out
  was preserved (PL still has zero occurrences of `flush` after the edit);
  adding `purge_notifications` to the EN doc is a correct-name parity
  addition, not a revert of the carve-out.

- **Task 23 (`sso`), nothing further found.** G5 re-check of the whole topic
  against `accounts/forms.py:170-198` (`SsoForm`), `templates/institution/
  manage/_sso_fields.html`, `templates/institution/manage/_sso_tab.html`, and
  `templates/institution/setup/sso.html` beyond the plan's L13/L14/L15/L16
  fixes found no additional drift: the "Redirect URI" section's claims match
  `institution/views_manage.py:75-76` (`sso_secret_saved`/`sso_redirect_uri`
  context, backed by `accounts/sso_config.py:redirect_uri`); the client-secret
  write-only description matches `_sso_fields.html:41-49`'s
  saved/not-saved branching; the wizard-skip claim matches the **Skip**
  button at `templates/institution/setup/sso.html:11`. No new finding to
  record.

- **Task 24 (`subjects`), fixed — last topic in the slice.** Beyond the
  plan's `Manage`→`Studio`, `**Add subject**`→`**New subject**`, L18
  (model), and L19 (filter link) fixes:
  - `subjects.md:10` / `subjects.pl.md:12-13` "Existing subjects can be
    renamed or removed from their row" / "Istniejące przedmioty można
    zmienić nazwę lub usunąć z poziomu ich wiersza" named no controls.
    `templates/courses/manage/subject_list.html:23-24` shows the row
    actually has two named buttons, `{% trans "Edit" %}` and
    `{% trans "Delete" %}` (msgstrs "Edytuj" / "Usuń",
    `locale/pl/LC_MESSAGES/django.po:3428-3429` and `:2787-2788`). Fixed
    both languages to name them. The PL sentence was additionally
    ungrammatical (`Istniejące przedmioty można zmienić nazwę` needs the
    dative `przedmiotom`, not nominative `przedmioty`, before `zmienić
    nazwę`) — rewritten as "Istniejącym przedmiotom można zmienić nazwę
    lub je usunąć za pomocą przycisków **Edytuj** i **Usuń** w ich
    wierszu."
  - `subjects.md:8-9` / `subjects.pl.md:9-11` claimed a subject has "a name
    and a slug" ("nazwą i slugiem"). `courses/forms.py:258-270`
    (`SubjectForm`) has **no name field**: it has `title_en` (label
    "Title (English)", required), `title_pl` (label "Title (Polish)",
    optional, help text "falls back to the English title when blank"),
    and `slug` (help text "generated from the English title if left
    blank" — `unique_subject_slug` at `:282-284` is called with
    `cleaned_data.get("title_en", "")` specifically, never `title_pl`).
    Rewritten in both languages to name both title fields and state that
    the slug derives from the **English** title specifically (PL as a
    `z polami: X, Y oraz Z` colon list per plan Step 5, keeping the
    msgstrs `Tytuł (angielski)` / `Tytuł (polski)` / `końcówka URL
    (slug)` nominative and unbent).
  - `subjects.md:11` / `subjects.pl.md:14` "course count" /
    "liczbę kursów" described a passive count. `subject_list.html:19` is
    actually an `<a>` linking to
    `{% url 'courses:manage_course_list' %}?subject={{ s.slug }}` — a
    filter link into the course list, not inert text. `{% blocktrans
    count %}used by {{ n }} course{% plural %}used by {{ n }}
    courses{% endblocktrans %}` (`django.po:5654-5658`, PL msgstr[2]
    "używany przez %(n)s kursów"). Rewritten in both languages to name it
    as a filter link, using the plural msgstr[2] form in PL per plan Step
    4/G2.
  - `subjects.md:3-4` "Manage them from **Admin → Subjects**" was
    re-checked against `templates/base.html:90-98` (Admin dropdown →
    Subjects menu item, `perms.courses.change_subject`-gated) and against
    `msgid "Admin"` → "Administracja" (`django.po:3489-3490`) for the PL
    "Administracja → Przedmioty" — both correct, no fix needed.
  - This is the **last of 22 topics** (24 topic tasks) in slice-1a's
    execution; no further re-audit gaps were found in `subjects`.

- **`quiz-editors` — the four PL-invented marking-field translations, recorded
  here for the Task 26 completeness check.** `quiz-editors.pl.md` carries **no
  §3.1.2 row** at all — the §3.1.2 table's topic-keyed coverage never reached
  it — yet its pre-edit text independently invented four field translations
  that diverge from the catalog, the exact §3.1.2 failure mode occurring
  outside that table's reach. Direct evidence §3.1.2 is itself a floor, not a
  ceiling. Verified against `courses/models.py:1279-1282`
  (`QuestionElement.MarkingMode(models.TextChoices)`: `AUTO = "A",
  _("Auto-marked")`; `NOT_MARKED = "N", _("Not marked")`; `REVIEW = "R",
  _("Requires review")`) and `templates/courses/manage/editor/
  _marking_fields.html:9,13` (`{% trans "Max attempts" %}` / `{% trans "Max
  marks" %}`), each looked up in `locale/pl/LC_MESSAGES/django.po`:

  | Doc said (pre-edit, WRONG) | Product renders | msgid | msgstr cite |
  |---|---|---|---|
  | `Oceniane automatycznie` (`quiz-editors.pl.md:12` pre-edit) | **Automatycznie oceniane** | `Auto-marked` | `django.po:831-832` |
  | `Wymaga sprawdzenia` (`:13`, and again wrapped across `:82-83` — two occurrences) | **Wymaga recenzji** | `Requires review` | `django.po:839-840` |
  | `Maksymalna liczba prób` (`:15`) | **Maks. prób** | `Max attempts` | `django.po:5264-5265` |
  | `Maksymalna liczba punktów` (`:15`) | **Maks. punktów** | `Max marks` | `django.po:5268-5269` |

  **Fixed by Task 12** (commit `513954b`) — `quiz-editors.pl.md` now reads
  "Automatycznie oceniane … Wymaga recenzji … Nieoceniane" (`:18-20`) and
  "**Maks. prób** i **Maks. punktów**" (`:21`), plus the Extended-response
  "Wymaga recenzji" occurrence (`:88-89`), all msgstr-exact. Not listed under
  Task 12's own G5 additions above because these four were Task 12's
  *assigned* scope (plan Task 12 Step 5), not something found *beyond* it —
  Task 26's floor requires them recorded regardless, precisely because a
  topic outside §3.1.2's reach shipping its own invented translations is the
  evidence that table's coverage was never complete.

- **"cherry-pick" spans 4 locations, not the 1 that findings §3.3's row L32
  cites — recorded here for the Task 26 completeness check.** L32 (§3.3
  above) names only `analytics.md:36-37`. Re-derived against `MERGE_BASE`
  (`9be9c72`): the identical fabricated "select a subset of students **or
  units**" claim — there is no unit subset; the only checkbox in
  `templates/courses/manage/analytics_matrix.html:141` is `name="student"` —
  recurred in three further places: `analytics.pl.md:36` ("Filtr **wybór
  ręczny** pozwala zaznaczyć podzbiór uczniów **lub jednostek**", the Polish
  translation of the same fabrication, not merely the same defect
  independently); `drill-down.md:26` (an **H2 heading**, `## Cherry-picking a
  subset of students`); and `gradebook-export.md:11` ("any cherry-picked
  student subset"). All four were fixed, each as its own task's assigned
  scope rather than a flagged G5 addition: Task 4 (`analytics`, commit
  `958c5b2`) replaced the intro paragraph with the real tick-row/**Apply
  selection** control in both languages; Task 5 (`drill-down`, commit
  `70b02a9`) renamed the H2 to `## Selecting a subset of students`
  (`drill-down.md:29` today); Task 6 (`gradebook-export`, commit `4c73f7c`)
  changed "cherry-picked" to "selected" (`gradebook-export.md:15` today).
  None of the three tasks' reports recorded a §3.6 entry for it — Task 4's
  report states "No new findings recorded... already scoped in this task";
  Task 5's report states "No new findings... Nothing appended to §3.6" —
  because each treated its own fix as in-scope, not *beyond* scope, exactly
  paralleling the `quiz-editors` item above. `grep -rniP 'cherry' docs/help/`
  today returns zero hits across all 22 topics × 2 languages, confirming the
  fix is complete; this entry records that L32's citation undercounted by 3,
  which is evidence the §3.3 table's per-row citations are a floor too.

_(No further gaps beyond the two above were found while re-reading this
section end-to-end for the Task 26 completeness check; the remaining ten of
the plan's twelve floor items are each already present above under their own
topic task's entry, and the twelfth — `Administrator Platformy/Kursu`
spanning 5 files — is recorded in the §3.1.2 walk immediately below, row 17,
per the plan's own instruction to take the count from that walk rather than
assert one here.)_

---

**Slice 1b, Task 1 (`interactive-elements`, new topic).** Registered a new
Course-Admin topic — slug `interactive-elements`, perm
`grouping.change_group`, title `_("Interactive elements")` — directly after
`quiz-editors` in `core/help.py`, and wrote it end-to-end in both languages:
`docs/help/course-admin/interactive-elements.md` and `.pl.md`, documenting
all nine Interactive-group element types (Show more, Fill in & confirm,
Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step,
Checklist, Guess the number) in palette order, each verified against its
`_edit_*.html` editor template and model in `courses/models.py` before
writing its paragraph — not from memory. The one new translatable string,
the topic title, was authored as msgstr `"Elementy interaktywne"` via
`makemessages -l pl --no-obsolete`.

- **`makemessages` artifact, fixed.** Extracting the new msgid fuzzy-matched
  it against the pre-existing (unrelated) msgid `"interactive content"` and
  seeded `msgstr "treść interaktywna"` marked `#, fuzzy` — not a pre-existing
  entry re-fuzzied (the Global Constraints' named hazard), but the *new*
  entry itself arriving pre-fuzzied with someone else's translation. Authoring
  the real msgstr (`"Elementy interaktywne"`) and dropping the `#, fuzzy` /
  `#| msgid` lines resolved it; `grep -c "^#, fuzzy"` and `grep -c "^#~"` on
  the compiled `.po` are both 0.
- **PL button-copy quoted from the catalog, not invented.** Two in-body PL
  quotes (Spoiler's default button text; Step-by-step's reveal button) were
  resolved against the live catalog rather than translated afresh: msgid
  `"Reveal"` → msgstr `"Pokaż"` (`_edit_spoiler.html:6` placeholder, used as
  Spoiler's default **Tekst przycisku**), and msgid `"Show next"` → msgstr
  `"Pokaż dalej"` (the stepper's reveal control) — an initial draft used the
  invented `"Rozwiń"` / `"Pokaż następny"` and was corrected before commit.
- **No product-code changes** — this task is additive documentation only
  (one registry entry, two new markdown files, one catalog msgstr).

---

**Slice 1b, Task 2 (`content-editors`, Content +5 / Structure +1 /
nesting).** Added five Content paragraphs (Table, Gallery, Callout, Tabs,
Columns, in palette order, after HTML), a new `## Structure` section (Slide
break), and a new `## Containers and nesting` section to
`content-editors.md` / `.pl.md`, plus the intro/See-also cross-links to the
new `interactive-elements` topic. Each type verified against its
`_edit_*.html` editor template before writing (Table, Gallery, Callout, Tabs,
Columns) or, for Slide break (no editor form — it is a field-less marker),
against `courses/models.py:638-645` (`SlideBreakElement`) and
`courses/slideshow.py::partition_into_slides` (how the taking view actually
consumes it). The nesting section quotes `courses/builder.py:34-55`
`NESTABLE_TYPE_KEYS` directly: containers (Tabs, Columns) hold the 9 Content
types (text, image, video, iframe, math, html, table, gallery, callout) and
all 9 Interactive types (spoiler, reveal_gate, fill_gate, switch_gate,
switch_grid, fill_table, stepper, mark_done, guess_number) — nothing else;
`_add_menu.html:27` (`{% if not unit_is_quiz %}`) confirms Interactive is
lesson-only, so a container's add-menu inside a quiz offers Content types
only.

- **20 bolded EN/PL labels quoted from `django.po`, sweep-verified twice.**
  Every bolded control label introduced this task (Header row, Header
  column, Borders, Grid, Rows, Header only, None, Add image, Description
  position, Below image, Above image, Kind, Heading, Number of columns, plus
  the five type names and Slide break) was checked two ways: (1) resolved
  against the live catalog before writing, and (2) after writing, both files
  were re-read from disk and every `**label**` span extracted with a regex
  and diffed against the catalog's `msgid`/`msgstr` sets — 20/20 matched on
  both passes, closing the gap the previous task's PL-invention miss opened.
- **A line-wrap bug the first sweep pass caught.** The EN Table paragraph
  originally wrapped `**Header only**` across a markdown soft line break
  (`**Header\nonly**`) — renders fine as HTML (paragraph reflow collapses the
  newline to a space) but fails a literal substring/exact-match check, which
  is exactly what the sweep does. Rewrapped so the bold span sits on one
  line; re-verified.
- **In-page anchor links don't resolve — removed before commit.** A first
  draft cross-referenced the new "Containers and nesting" section from the
  Tabs/Columns paragraphs with `[Containers and nesting](#containers-and-nesting)`.
  `core/help.py::render_markdown_doc` calls `markdown.markdown(text,
  extensions=["fenced_code", "tables"])` — no `toc` extension, so headings get
  no `id` attribute and the anchor is dead. Replaced with a plain quoted
  section-name reference ("see "Containers and nesting" below") in both
  languages; no other help doc in the repo uses in-page anchors either
  (confirmed by grep), so this isn't an established pattern being broken.
- **`Kind` choices confirmed single-context.** Callout's four kind labels
  (Example/Note/Tip/Warning, `courses/models.py:417-421`) are quoted
  unbolded in prose; checked each msgid has exactly one `msgid` line in
  `django.po` (no `msgctxt` split) before trusting the catalog msgstr —
  `"Note"` in particular resolves to a single entry referencing
  `courses/models.py:419` and `notes/forms.py:11` (same string, same
  translation, no ambiguity).
- **No product-code changes** — this task is additive documentation only
  (two existing markdown files edited, no new catalog msgid).

---

**Slice 1b, Task 3 (`quiz-editors`, Questions +2 / per-option MCQ feedback /
cross-link).** Added two Questions-group paragraphs in palette order — Matrix
question and Multi-select grid, inserted between Match pairs and Drag to
image (confirmed against `_add_menu.html:50-53`: Match pairs → Matrix
question → Multi-select grid → Drag to image) — each verified against its
editor template (`_edit_choicegridquestion.html`, `_edit_multigridquestion.html`)
before writing. Extended the existing `## Single / Multiple choice` section
with per-option MCQ feedback, quoting the editor's own hint verbatim
(`_edit_choicequestion.html:15`) and its PL msgstr, plus the lesson-vs-quiz
reveal contrast. Added the `[Interactive elements](interactive-elements)`
cross-link (PL: `[Elementy interaktywne](interactive-elements)`) to `##
Where questions live` / `## Gdzie znajdują się pytania`. Mirrored in both
`quiz-editors.md` and `.pl.md`.

- **Lesson-vs-quiz reveal contrast, source-verified (not from memory).**
  `ChoiceQuestionElement.mark()` (`courses/models.py:1409-1430`) computes
  `annotated` as the choices carrying non-empty `feedback` whose selection
  state is wrong (`c.feedback and ((c.pk in answer) != c.is_correct)`) —
  empty feedback on every choice means an empty `annotated` set regardless of
  correctness. `ChoiceQuestionElement.render()` (`:1477`) sets
  `"reveal_template": None if mode == "lesson" else self.REVEAL_TEMPLATE` —
  **unconditional** on mode, not on whether any choice has feedback — so the
  lesson path never falls through to the bottom `_reveal_choice.html` list
  (`_question_feedback.html:10` guards `{% if not mark_result.correct and
  reveal_template %}`, and `reveal_template` is always `None` in lesson
  mode). The choice template itself (`templates/courses/elements/choicequestion.html:18-25`)
  only renders a marker + `{{ c.feedback }}` per choice when `mode ==
  "lesson" and mark_result and c.pk in mark_result.annotated` — so a lesson
  wrong answer with no per-option feedback shows only the verdict
  (`_question_feedback.html:3-9`), confirming the plan's claim. For the quiz
  side: `_quiz_question_feedback.html:36` includes `reveal_template` whenever
  `locked` (last wrong attempt) regardless of feedback; more decisively,
  `courses/views.py:1290-1337` (`_build_result_row`, quiz results/review)
  unconditionally sets `row["reveal_template"] = question.REVEAL_TEMPLATE`
  for every auto-marked question, and `templates/courses/quiz_results.html:43-44`
  includes it whenever `row.outcome != "correct"` — independent of the
  lesson-mode suppression logic, which lives entirely inside
  `ChoiceQuestionElement.render()` and is never reached by the results-page
  code path. `tests/test_choice_inline_feedback.py::test_lesson_render_suppresses_bottom_reveal_list`
  confirms the lesson side end-to-end (inline feedback present, but
  `"question__reveal" not in html`). Both halves of the plan's claim hold; no
  contradiction found.
- **PL msgstr verified, not invented.** `_edit_choicequestion.html:15`'s hint
  ("Optional feedback shows when a student gets an option wrong — a wrong
  pick, or a correct answer they missed.") resolves in
  `locale/pl/LC_MESSAGES/django.po:4724-4730` to msgstr "Opcjonalna
  informacja zwrotna pojawia się, gdy uczeń pomyli się na opcji — wybierze
  złą albo pominie poprawną." — quoted verbatim in `quiz-editors.pl.md`.
  Element names re-confirmed against the ground-truth table: `Matrix
  question` → `Pytanie macierzowe` (`django.po:2250-2251`), `Multi-select
  grid` → `Siatka wielokrotnego wyboru` (`django.po:1007-1008`).
- **Self-review caught a grammatical-inflection drift.** A first PL draft
  bolded `**szablonu Prawda/Fałsz**` (genitive-inflected) for the button
  msgstr `"Szablon Prawda/Fałsz"` — the doc's established convention
  (confirmed against existing sections, e.g. `**rozróżniaj wielkość liter**`
  for msgstr `"Rozróżniaj wielkość liter"`) preserves the catalog string
  as-is (at most a first-letter case change for sentence position), not
  further grammatical inflection. Rewrote the sentence to keep the label in
  its catalog nominative form (`kliknij **Szablon Prawda/Fałsz**`) before
  commit.
- **No product-code changes** — this task is additive documentation only
  (two existing markdown files edited, no new catalog msgid).

### §3.1.2 row-by-row walk (Task 25, DoD #1a)

> DoD #1 keys on "every finding **naming that topic**", but roughly half of
> findings §3.1.2's rows (the "PL doc says / Product renders / Cite / Scope"
> table under §3.1 item 2, plus the button-rename list) name no topic file at
> all — a topic-keyed pass sails past them, and several rows span **multiple**
> topics. This walks **all 18 rows of that table**, in the table's own order,
> re-deriving every count by search against the current tree (G1 — no earlier
> count, including this plan's own orientation numbers, is trusted without
> re-verifying). Where useful, occurrences are also checked against the
> pre-slice tree at `MERGE_BASE` (`9be9c72`) to confirm a row's defect was real
> before crediting its fix. `export LC_ALL=C.UTF-8` was set for every `-P`
> search; `-z` matches were counted with `tr -cd '\0' | wc -c` (NUL count, not
> `wc -l` and not `tr '\0' '\n' | grep -c .`, both of which mis-count wrapped
> matches).

1. **`etykiety` → `tagi`.** `notes-tags.pl.md` (the only in-scope file):
   `grep -c 'tykiet'` → **0** — fixed (Task 3's follow-up commit
   `f0f692a`). **Carve-out is 4 files, not the plan's originally-stated 3** —
   `grep -rl 'tykiet' docs/help/` → `content-editors.pl.md`,
   `quiz-editors.pl.md`, `sso.pl.md`, `subjects.pl.md`. The first three predate
   the slice (generic-label sense, correctly left — `django.po:1407` etc.).
   The fourth, `content-editors.pl.md:26` "**Etykieta (opcjonalnie)**", is
   **new content this slice wrote** (Task 11, `78b8df3`; absent from
   `content-editors.pl.md` at `MERGE_BASE` — confirmed by diffing against
   `9be9c72`) — it quotes `msgid "Label (optional)"` →
   msgstr "Etykieta (opcjonalnie)" (`django.po:5251-5253`) verbatim, the
   product's correct generic-label sense, same carve-out class as the other
   three. **Record 4 carve-out files, not 3.**

2. **`rocznik`/`roczniki` → `kohorta`/`kohorty`.** Re-derived
   `grep -rl 'ocznik' docs/help/` → **1 file only**: `cohorts.pl.md`.
   Applied in full at `groups-collections.pl.md` (8+ occurrences at
   `MERGE_BASE`, incl. the `## Roczniki` H2 and `## Roczniki przydziela się
   gdzie indziej` H2, both gender-flipped to `## Kohorty` / `## Kohorty
   przydziela się gdzie indziej` — Tasks 8/6) and `roster.pl.md` (8
   occurrences at `MERGE_BASE`, full masc.→fem. case-by-case flip table in
   Task 9's report — `Rocznik`→`Kohorta`, `Wszystkie roczniki`→`Wszystkie
   kohorty`, `Filtr rocznika`→`Filtr kohorty`, etc.) — both now 0. **Edge
   case:** `cohorts.pl.md:4` — "…grupowanie uczniów…, niezależne od
   konkretnego kursu — zwykle **rocznik** lub nabór" — **keeps `rocznik` and
   this is correct.** It uses the word in its *ordinary* sense (a school
   year-group) to describe, in prose, what a Cohort typically *is* — not the
   drifted UI-label sense the row targets. Present verbatim at `MERGE_BASE`
   (confirmed) and correctly left untouched by Task 15 (which touched this
   file for the `Administrator Platformy/Kursu` row, not this one). Not a
   missed hit.

3. **`test` (unit-type sense) → `quiz`, PL only.** Re-derived every PL
   occurrence of `\btest[a-ząćęłńóśźż]*\b`: **4 hits, all in
   `integrations.pl.md` (lines 16, 18, 20, 24)**, and all four are the
   **carved-out `Send test event` sense** ("**Wyślij zdarzenie testowe**" /
   "test sprawdza…" / "wynik testu…" / "dostaw testowych") — the webhook
   test-delivery feature, not the quiz-the-unit-type sense the row targets.
   **No PL doc anywhere currently uses `test` to mean the quiz unit type** —
   zero hits *of the targeted sense* exist, so there was nothing left to
   apply; the row resolves to "carve-out confirmed clean," not "applied."

4. **`Branding` → `Wygląd`.** Re-derived `grep -rniP 'branding|Wygląd'
   --include='*.pl.md'`: **6 occurrences across 4 files**, not the row's
   implicit single count. Of these, **5 belong to this row's sense** (the tab
   name) and split 2 applied / 3 carved out, matching the plan's "2 of 5"
   orientation number once cross-checked against `MERGE_BASE`:
   - Applied: `branding-settings.pl.md:4` ("Ten temat opisuje **Wygląd**…")
     and `:7` ("## Wygląd") — both said `Branding` at `MERGE_BASE`.
   - Carve-out (3, held): `branding-settings.pl.md:1` (the page's own H1,
     "# Branding i ustawienia platformy"), `first-run-wizard.pl.md:11`, and
     `invitations.pl.md:11-12` — all three *quote that same H1 as a
     cross-link title*, and that H1 is `docs/superpowers/specs/…#385` finding
     **H01**, a §3.5 H1≠registry-title mismatch **explicitly out of slice-1a
     scope (G6)**. Renaming the cross-link text without renaming the H1 it
     points to would make the link text lie about its destination — correctly
     left alone pending the deferred H1 decision.
   - **6th occurrence, outside the row's 5-hit scope, also correctly left**:
     `users-roles.pl.md:23` — "…ponadto sprawuje pełne zarządzanie
     instytucją: użytkownicy, **branding**, ustawienia dostępu, SSO…" — a
     lowercase, uncapitalized item in a prose capability list (not a bolded
     quote of a UI element), present verbatim at `MERGE_BASE` and untouched
     by every subsequent task that edited this file. This is reported here
     for transparency (G1) rather than asserted as definitely correct: it
     reads as the ordinary-language sense (an institution's "branding" as a
     general concept) rather than a literal tab-label quote, consistent with
     how the other ordinary-sense carve-outs in this table are treated, but
     it was not one of the 5 hits any prior task explicitly ruled on.

5. **`Przesyłanie plików` → `Przesyłanie`.** Re-derived
   `grep -rnzP 'Przesyłanie\s+plików'` (wrap-aware) → **0 hits anywhere**.
   Applied: `branding-settings.pl.md:30` "## Przesyłanie" (was "## Przesyłanie
   plików" at `MERGE_BASE`). **Carve-out held**: `media-manager.pl.md:8`
   "## Przesyłanie pliku" — singular "a file" ("Uploading a file"), a
   substring false positive on `Przesyłanie plik*`, not a hit on the plural
   tab-name mislabel. Confirmed correct PL prose, left untouched.

6. **`Kohort z samodzielnym zapisem` → `Kto może się zapisać`.** Re-derived
   `grep -rzP 'samodzielnym\s+zapisem'` → **0 hits**; both files (`cohorts.pl.md`
   at `MERGE_BASE` had "**samodzielny zapis**" language, `create-a-course.pl.md`
   likewise) now correctly read the field label **Kto może się zapisać**
   (`cohorts.pl.md`, "Gdzie kohorty mają znaczenie" section; `create-a-course.pl.md`,
   "Przedmioty i widoczność" section). Applied in both.

7. **`sekret podpisujący` → `Klucz podpisujący`.** Re-derived
   `grep -rniP 'sekret\s+podpisuj'` → **0**. `integrations.pl.md` now reads
   "**Klucza podpisującego**" (Konfiguracja section). Applied.

8. **`adres URL punktu odbioru` → `Adres URL punktu końcowego`.** Re-derived
   `grep -rniP 'punktu\s+odbioru'` → **0** (the file still uses "punkt odbioru"
   / "odbiornik" in their *ordinary* sense — "receiving endpoint" / "receiver" —
   describing the receiving server generically in prose, e.g. "Skonfiguruj
   punkt odbioru w **Administracja → …**"; this is not the specific mislabeled
   field name and is correctly left as ordinary vocabulary). `integrations.pl.md`
   now reads "**Adresu URL punktu końcowego**" (Konfiguracja section). Applied.

9. **`Slug` → `końcówka URL (slug)`.** Re-derived: no bare capitalized `Slug`
   field-label quote remains anywhere. Applied in **exactly the 2 files** the
   orientation number named: `create-a-course.pl.md:9` ("**końcówka URL
   (slug)**") and `subjects.pl.md:11` ("**końcówka URL (slug)**", rewritten by
   Task 24 from the older "z nazwą i slugiem" phrasing). Lowercase generic
   `slug` still appears in ordinary prose (`cohorts.pl.md:14,20`,
   `create-a-course.pl.md:11`) — correct ordinary-sense usage, not the
   mislabeled field-name row, left alone.

10. **`Matematyka` → `Wzór`.** Re-derived `grep -rn '\bMatemat'` across
    `docs/help/` → **1 hit**, and it is the *correct* ordinary-sense one:
    `content-editors.pl.md:33` "wzory **matematyczne**" (adjective, "math
    formulas," describing what KaTeX renders inside the Text element — not
    an element-type label). The mislabel this row targets —
    `content-editors.pl.md:51` "**Matematyka** — samodzielny blok wzoru…" at
    `MERGE_BASE` — is now `content-editors.pl.md:56` "**Wzór** — samodzielny
    blok wzoru…". Applied (Task 11).

11. **`Ramka` (for Iframe) → `Iframe`** (`Ramka` itself is reserved for the
    undocumented Callout element, out of slice-1a scope per G6). Re-derived
    `grep -rniP '\bRamk[aeęi]\b'` → **1 hit**, and it is the ordinary sense:
    `content-editors.pl.md:79` "zbyt duże **ramki**" (a preview tip about
    oversized embedded frames, generic noun, not an element-type label). The
    mislabel this row targets — `content-editors.pl.md:43` "**Ramka
    (iframe)**…" at `MERGE_BASE` — is now `content-editors.pl.md:48`
    "**Iframe** — osadza dowolną zewnętrzną stronę…". Applied (Task 11). No
    `Callout` element is documented in `content-editors.pl.md` at all, so
    there is no live claimant of the freed-up `Ramka` label yet — consistent
    with the 17-undocumented-element-types carve-out (G6, slice 1b).

12. **`Zastosuj` → `Zastosuj wybór`.** Re-derived: **2 occurrences** of
    "Zastosuj wybór" exist today (`analytics.pl.md:47`, `drill-down.pl.md:34`),
    both correct and no bare mislabeled `Zastosuj` remains
    (`grep -rzP 'Zastosuj(?!\s+wyb)'` → 0). Cross-checked against
    `MERGE_BASE`: only `drill-down.pl.md:31` had the actual defect ("naciśnij
    **Zastosuj**:"); `analytics.pl.md` had **no** "Zastosuj" text at
    `MERGE_BASE` at all — its "Zastosuj wybór" occurrence is new prose this
    slice wrote (describing the same cherry-pick control), correct from the
    start. So the row is **1 genuine pre-existing hit, applied** (matches the
    plan's "1 hit, not the ×2 the row implies" exactly, now independently
    confirmed against `MERGE_BASE` rather than taken on trust).

13. **`Eksportuj` → `Eksport`.** Re-derived against
    `locale/pl/LC_MESSAGES/django.po`: this row's single cite actually covers
    **3 distinct msgids at 3 different destinations**, all correctly quoted
    verbatim today:
    - `msgid "Export"` → msgstr "Eksport" (`django.po:4224-4226`,
      `analytics_matrix.html:13` / `builder.html:18` / `course_list.html:63`)
      — used in `export-import.pl.md:9`, `analytics.pl.md:51,53`,
      `gradebook-export.pl.md:4,12`.
    - `msgid "Export subtree"` → msgstr "Eksportuj poddrzewo"
      (`django.po:4169-4171`, `_tree_node.html:12`) — used in
      `export-import.pl.md:10`.
    - `msgid "Export anyway"` → msgstr "Eksportuj mimo to"
      (`django.po:5361-5363`, `export_preview.html:24`) — used in
      `export-import.pl.md:18`.
    All three verified verbatim against the catalog. Applied per-topic
    (matches the plan's "3 hits, 3 different destinations" exactly).

14. **`Szukaj po nazwisku` → `Szukaj wg nazwiska`.** Re-derived: **1 hit**,
    `roster.pl.md:28` "**Szukaj wg nazwiska**" — correct, `Szukaj po nazwisku`
    no longer appears anywhere. Applied (Task 9).

15. **`Przydziel uczniów` → `Przypisz uczniów`.** Re-derived: **0 hits** of a
    bolded `**Przydziel uczniów**` or `**Przypisz uczniów**` short pseudo-label
    anywhere in `docs/help/`. **This row's own proposed replacement was itself
    disputed and rejected as a fabrication during Task 9** (`roster`): neither
    `msgid "Assign students"` nor a rendered `Przypisz uczniów` two-word label
    exists in the product — `templates/grouping/cohort_form.html:19` renders a
    **long** checkbox-list caption (`{% trans "Assign students to this cohort
    (moves them from their current cohort)" %}` → msgstr "Przypisz uczniów do
    tej kohorty (przeniesie ich z obecnej kohorty)"), and the actual submit
    button at `:23` says only `{% trans "Assign" %}` → **Przypisz** (bare, no
    "uczniów"). **Resolution actually applied** (both languages, both
    `roster.md`/`roster.pl.md`): describe the control by what it literally
    renders — the long caption quoted verbatim plus the real bare
    **Assign**/**Przypisz** button — with no bolded pseudo-label in either
    language. Full detail, including the EN-side fabrication the original
    audit's §3 table missed entirely (`roster.md:34` pre-edit had the
    identical invented "**Assign students**" list), is recorded under this
    document's existing **Task 9 (`roster`)** entry above; this row is listed
    here only to close the partition — it is **applied**, not merely
    disputed-and-left-open. `grep -rn 'Przypisz uczniów'` today returns exactly
    one hit (`roster.pl.md:51`), and it is the wrapped tail of the verbatim
    long-caption quote, not a fabricated short label.

16. **`okno retencji` → `Okno przechowywania (dni)`.** Re-derived: **1 hit**,
    `notifications.pl.md:27` "**Okno przechowywania (dni)**" — correct,
    `okno retencji` no longer appears anywhere. Applied (Task 22).

17. **`Administrator Platformy/Kursu` → `Administrator platformy/kursu`**
    (lowercase noun after the role name — the title-cased second word was the
    defect). Re-derived wrap-aware: `grep -rozP
    'Administrator[a-ząćęłńóśźż]*\s+(Platformy|Kursu)' docs/help/ | tr -cd
    '\0' | wc -c` → **0** across the whole `docs/help/` tree today. Cross-checked
    against `MERGE_BASE` by extracting all 22×2 files as they stood at
    `9be9c72` and re-running the identical wrap-aware count: **11**, split
    exactly `users-roles.pl.md` (4), `create-a-course.pl.md` (3),
    `cohorts.pl.md` (2), `first-run-wizard.pl.md` (1),
    `branding-settings.pl.md` (1) — independently reproducing the plan's
    per-file breakdown byte-for-byte. Applied per-topic (Tasks 14, 15, 16, 18,
    21); the lowercase correct form is now present in 3 of those 5 files
    (`users-roles.pl.md` ×5, `branding-settings.pl.md` ×1,
    `first-run-wizard.pl.md` ×1 — the other two, `create-a-course.pl.md` and
    `cohorts.pl.md`, no longer need the phrase at all post-rewrite).

18. **`Sprawdzanie testów` (×5 cross-links) → `Sprawdzanie quizów`.**
    Re-derived wrap-aware, case-insensitive: `grep -rlzPi
    'sprawdzani\w*\s+testów' docs/help/` → **0 files**. The correct phrase
    `Sprawdzanie quizów` appears in **6 files**, not 5: the topic's own page
    (`quiz-review.pl.md:1` H1 + `:6` in-page button quote) plus the **5**
    inbound cross-links the row names — `drill-down.pl.md:61`,
    `gradebook-export.pl.md:50`, `groups-collections.pl.md:59`,
    `notes-tags.pl.md:52`, `roster.pl.md:60`, each `[Sprawdzanie
    quizów](quiz-review)`. The row's "×5" counts only the cross-links, not the
    topic's self-reference — both are correct, and the two counts (5 vs 6)
    reconcile exactly once the self-reference is separated out. Applied.

**Partition check.** The 18 rows above are, in order, exactly the 18 rows of
findings §3.1 item 2's "PL doc says / Product renders / Cite / Scope" table —
read directly off that table (not reconstructed from two separate plan-side
lists), which is why there is no possibility of the double-counting that hit
an earlier draft of Task 25's plan entry (its "10 tabled + 8 not-tabled" split
counted 4 rows twice and dropped a 5th, `rocznik`, from both lists). Rows:
(1) etykiety, (2) rocznik/roczniki, (3) test→quiz, (4) Branding,
(5) Przesyłanie plików, (6) Kohort z samodzielnym zapisem,
(7) sekret podpisujący, (8) adres URL punktu odbioru, (9) Slug,
(10) Matematyka, (11) Ramka, (12) Zastosuj, (13) Eksportuj,
(14) Szukaj po nazwisku, (15) Przydziel uczniów, (16) okno retencji,
(17) Administrator Platformy/Kursu, (18) Sprawdzanie testów — **18 distinct
rows, no overlap, no gap.**

**Resolution tally:** 17 rows resolve to **applied** (rows 1, 2, 4–18; rows 4
and 5 are each *also* partly "carve-out held" — see their entries), and 1 row
(3, `test`→`quiz`) resolves to **carve-out confirmed clean, nothing to apply**
(zero occurrences of the targeted sense exist; every remaining occurrence of
the word is the explicitly-carved-out `Send test event` sense). Every row that
carries a "leave untouched" decision has that decision recorded explicitly
above (rows 1, 2, 3, 4, 5, 9, 10, 11) — no carve-out was left silent, and no
row was skipped.

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
