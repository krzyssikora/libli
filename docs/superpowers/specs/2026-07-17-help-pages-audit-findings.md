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

_(populated during execution)_

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
