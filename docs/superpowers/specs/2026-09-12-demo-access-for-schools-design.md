# Demo access for schools — design

**Status:** approved in brainstorming 2026-09-11/12. Not yet planned, not yet built.
**Scope:** how an interested school representative is given a private, time-limited
look at a running libli (libli.pl), with pupil and teacher views populated well
enough to judge the product.

---

## 1. Problem

libli.pl is live, holds `mat-pp` (427 published units of a real Polish maths course),
and is the vendor instance: `/for-schools/` and the pricing table are served from it.
A school representative who reads that page has no way to see the product working.

What they must be able to do (settled with Krzysztof, 2026-09-11):

1. browse lessons as a pupil,
2. take a quiz and see it marked,
3. see teacher analytics — the progress/results matrix and the drill-down to one pupil.

Explicitly NOT in scope: editing content in the demo, self-serve signup, outgoing
email, and a demo review queue (see §3.4).

## 2. Decisions taken, with their reasons

| # | Decision | Why, and what was rejected |
|---|----------|----------------------------|
| D1 | **Gated access.** The rep asks; Krzysztof provisions and sends credentials himself. | Rejected: self-serve "Try it" (an anonymous account-creating endpoint on prod, needing throttling) and shared public logins (collisions on exactly the two things reps must do — take a quiz, read analytics). |
| D2 | **The demo runs on `mat-pp`.** | Real Polish content is the strongest proof for a Polish school, and the audit in §3.1 shows its quizzes are fully machine-answerable. Rejected: a purpose-built showcase course (content to author, less convincing). |
| D3 | **Per-rep kit, with its own fake pupils**, rather than a shared pupil pool. | Three reasons, in §2.1. |
| D4 | **Krzysztof sends the credentials.** | libli.pl has no outgoing email (`DJANGO_EMAIL_HOST` unset → console backend, `config/settings/production.py:30-39`). The invite flow would silently deliver nothing. This also keeps the handover personal, which suits a sales conversation. |
| D5 | **Kits expire.** An expiry date is set at creation (default 14 days); a nightly job deletes expired kits. | Rejected: manual removal (accounts with stranger-known passwords accumulate on prod) and deactivate-keeping-data (still needs a purge rule eventually). |
| D6 | **Management commands first, admin UI second**, both over one service layer. | Krzysztof is the only operator and already runs everything on the box over SSH; the UI is wanted too, so it is PR 3 of this spec rather than a later project. |
| D7 | **libli.pl will never host real pupils.** | Stated assumption, not contradicted: each school gets its own box ([[school-hosting-model-decisions]]). It is what makes fake pupils on prod acceptable. |

### 2.1 Why per-rep pupils, not a shared pool

1. **A rep's actions write to pupil data.** A Teacher can force-submit a pupil's
   in-progress quiz (`courses/views_review.py:194,207`), which finalises it, puts a
   score in the matrix and emails the reviewers. A realistic demo *contains*
   in-progress quizzes, and "Force submit" is exactly the button a curious visitor
   presses. In a shared pool that press changes every other rep's matrix permanently.
2. **`mat-pp` keeps changing.** Prod is the source of truth and Krzysztof edits there.
   Progress and submissions point at particular units: a pool seeded weeks earlier
   shows "—" for every pupil on a newly published part. A per-rep kit is generated
   against what is published on the day it is created.
3. **Expiry costs the same either way.** A pool still needs per-rep teacher/student/
   group tracking, so it still needs the `DemoKit` model and the purge job. Per-rep
   adds only "create and delete ~20 more users", which is seconds of work and a few
   thousand rows.

Accepted cost: one new model and one migration (an add-table migration, safe on the
live DB).

## 3. Findings that constrain the design

Each was measured or read during brainstorming; re-verify anything marked ⚠️.

### 3.1 `mat-pp` quiz audit (measured 2026-09-11 against the local `libli` DB, course
pk 19, 1,029 nodes, updated 2026-09-05)

- 98 quiz units: **49 published** (parts 0–9), 49 draft (parts 10–20).
- Published quizzes hold **479 elements**, of which **260 are questions**. Every one is
  **AUTO** marked and **top-level** (`Element.parent` null). Question types: choice 174,
  shortnumeric 79, fillblank 3, choicegrid 2, matchpair 2. 1–10 questions per quiz,
  median 5. `max_marks` 1.00 on 247, 2.00 on 7, 0.50 on 6.
- **All 371 published question elements were answered correctly and incorrectly by
  script and run through the real `mark()`; all 371 behaved as expected.** So the
  answer-shape work is known-feasible, not hoped-for:

  | type | answer shape | correct from | wrong from |
  |------|--------------|--------------|-----------|
  | choice (`courses/models.py:2359`) | set of `Choice` pks | `is_correct=True` | any other choice |
  | shortnumeric (`:2566`) | str parsed by `parse_numeric_value` | `value` | `value + tolerance + 1` |
  | fillblank (`:2596`) | list of str, one per blank | first line of each `Blank.accepted` | any other string (partial credit possible) |
  | matchpair (`:2708`) | list of right-hand tokens in pair order | `expected_tokens()` | the same tokens rotated |
  | choicegrid (`:2773`) | list of one `GridColumn` pk per row | `row.correct_column_id` | any other column (partial credit possible) |

- Published **lessons** also hold 111 AUTO self-check questions (42 of 378 lessons),
  but lesson self-check answers live in `UnitProgress.element_state`
  (`courses/state.py:18`), which **analytics never reads**. The generator therefore
  does not write them (§7, non-goal N3).
- Parts 0–2 (Zbiory liczbowe, Elementy logiki, Wyrażenia algebraiczne) hold
  **126 published lessons and 17 published quizzes**.
- ⚠️ These are LOCAL numbers. Prod is the source of truth and has moved since; the
  generator must derive everything from the live DB at provision time and must never
  hardcode a unit, part or count.

### 3.2 What the analytics screens read

- **Matrix** (`courses/views_analytics.py:76`):
  - progress mode reads only `UnitProgress(completed=True)` (`courses/rollups.py:774-777`);
    the denominator is the visible **obligatory lesson** units (`:157-164`). Optional
    lessons and quizzes never count; a column with no such lessons shows "—" (`:785-786`).
  - results mode reads cached `QuizSubmission.score` / `max_score` (`:830-840`), written by
    `finalize_submission` (`courses/quiz.py:241-246`), never re-derived from answers.
  - a submission counts only when SUBMITTED **and** every REVIEW question in the unit has a
    response with `reviewed_at` (`courses/rollups.py:402-409`); the review count comes from
    the unit's **elements**, not the responses (`:348-360`), so a *missing* response blocks
    the score exactly like an unreviewed one. This is the trap that sank the earlier seeder.
- **Drill-down** (`courses/views_analytics.py:233`): lesson ticks from `UnitProgress.completed`
  (`courses/rollups.py:246-265`), a status pill per quiz (`:514-532`).
- ⚠️ **Draft units appear as soon as they carry data.** These views pass
  `drafts="keep-with-data"` (`courses/views_analytics.py:28-54`, `courses/rollups.py:80-81`).
  Hence the published-only rule (§4.3, R2).
- There is **no teacher page for an AUTO answer**: `quiz_results` shows only the logged-in
  user's own submission (`courses/views.py:1728-1730`) and the review page shows REVIEW
  questions only (`courses/views_review.py:76-77`). ⚠️ `/for-schools/` currently claims
  analytics are "drillable down to one pupil and one question" — see open question Q3.
- `finalize_submission` sends no mail and fires no webhook, so seeding is silent.
  (Force-submit does both, but that is a rep's action inside their own kit:
  `courses/review.py:96-102`.)

### 3.3 Access control (this is what makes the kit isolate)

- Analytics/review/export all gate on `scoping.can_review_course`
  (`grouping/scoping.py:96-102`): holder of `courses.change_course`, the course owner, or
  **a teacher of any non-archived group in the course**. Not `is_staff`.
- A group teacher sees **only members of the groups they teach** (`grouping/scoping.py:76-93`,
  re-checked at `:141-168`). So kit A's Teacher cannot see kit B's pupils.
- Drafts are owner/Platform-Admin only — `can_see_drafts` is an alias of `can_manage_course`
  and deliberately excludes both `is_staff` and group teachers (`courses/access.py:90-101`).
  A rep therefore never sees parts 10–20.
- ⚠️ A Teacher **is** staff (`institution/roles.py:30-32`, `accounts/services.py:36`), which
  grants read access to **every** course (`courses/access.py:22-23`) and a login to
  `/admin/` with no model perms beyond grouping. Acceptable while `mat-pp` is the only
  course on libli.pl; it is a standing caveat before a private course is added there.
- The People page needs `accounts.view_user`, Platform Admin only
  (`accounts/views_manage.py:40`, `institution/roles.py:64-67`), so a rep cannot enumerate users.
- A Teacher **cannot submit a quiz**: finishing requires enrolment
  (`courses/views.py:1696-1697`); a non-enrolled staff viewer gets the previewer, which marks
  live and saves nothing (`courses/views.py:1455,1600-1627`). **Hence the rep also gets a
  Student login.** Staff cannot be group members or self-enrol
  (`grouping/services.py:23-33,162`), so the Student account must not be staff.
- A rep Teacher's only data-changing actions: force-submit, mark a REVIEW answer (emails the
  pupil, `courses/review.py:62-66`), and collection CRUD (`grouping/views.py:660,679,730`).
  They cannot edit groups, change enrolment, or invite.

### 3.4 No review queue content

`mat-pp` has **zero REVIEW-mode questions**, so the teacher review queue shows only
in-progress submissions (`courses/review.py:236-256`). The demo therefore shows
force-submit but not marking. Adding a REVIEW question to `mat-pp` purely for the demo is
**rejected**: it would change real content, and an unmarked REVIEW response drops its whole
submission from the matrix (§3.2). Q4 records the alternative if this matters to Krzysztof.

### 3.5 Deletion is safe

No FK to `AUTH_USER_MODEL` anywhere in the project uses `on_delete=PROTECT` (checked
2026-09-12 across `accounts`, `courses`, `grouping`, `institution`, `notes`, `tags`,
`support`, `notifications`, `integrations`, `core`; every PROTECT in the codebase points at
`MediaAsset` or `GridColumn`). Deleting a kit's users therefore cascades their enrolments,
progress, submissions, responses, notes, tags and collections away. ⚠️ Re-verify with a test,
not by reading (§8, T7) — a future model could add one.

### 3.6 ⚠️ `seed_demo_course` must never run on prod

`docs/deployment.md:440-448` (runbook §7) instructs the operator to run it on the live box.
It is a **screenshot fixture**, not a demo seeder:

- it creates `demo_admin` with role **Platform Admin** and the password `demo-pass-123`,
  hardcoded in the repo (`courses/management/commands/seed_demo_course.py:60,101-107`);
- it overwrites `Institution.name` to "Demo Academy" (`:481-484`);
- it enables a webhook endpoint pointing at `sis.demo.example` (`:463-476`);
- it saves an SSO config (`:453-461`).

Fixing this is PR 1 (§6).

## 4. Design

### 4.1 New app: `demo`

A new Django app `demo` holding the model, services, generator, commands, views and
templates. Rationale: it is a vendor-only concern with its own lifecycle; keeping it out of
`institution` and `courses` means it can be reasoned about (and, if ever needed, removed) as
a unit. Added to `INSTALLED_APPS` in `config/settings/base.py`.

### 4.2 Model

```
DemoKit
  label          CharField(200)                  # "SP 12 Kraków"
  slug           SlugField(unique)               # derived from label, used in usernames
  course         FK(courses.Course, PROTECT)     # mat-pp
  group          FK(grouping.Group, SET_NULL, null=True)
  teacher        FK(User, SET_NULL, null=True, related_name="+")
  student        FK(User, SET_NULL, null=True, related_name="+")
  users          M2M(User, related_name="demo_kits")   # EVERY user the kit created
  seed           PositiveIntegerField            # RNG seed; makes the data reproducible
  pupil_count    PositiveSmallIntegerField
  created_at     DateTimeField(auto_now_add)
  expires_at     DateTimeField
  created_by     FK(User, SET_NULL, null=True, related_name="+")
  revoked_at     DateTimeField(null=True)        # set by purge/revoke before the row is kept
```

`users` is the authority for purging, so nothing depends on a username convention at delete
time. `teacher`/`student` are conveniences for display and are members of `users` as well.

**Deletion policy:** `purge_kit` deletes the kit's users and its group, then **keeps the
`DemoKit` row** with `revoked_at` set and the FKs nulled, so `list` retains a record of who
was given a demo and when. The row carries no credentials.

### 4.3 Rules the generator obeys

- **R1 Derived score.** For every response written, the stored `fraction` comes from
  `question.mark(answer)` on the answer actually stored. A stored answer and its mark can
  never disagree.
- **R2 Published only.** Only units with `published=True` receive progress or submissions —
  otherwise a draft appears in the matrix (§3.2).
- **R3 Whole-unit skip.** If any question in a unit cannot be answered, the unit is skipped
  entirely and a warning is printed. Never skip a single question: a partial unit still
  counts, and a missing response reads exactly like an unreviewed REVIEW question.
- **R4 Completed progress accompanies every submission.** `finalize_submission` deliberately
  does not touch `UnitProgress`; both production close paths write it, and so must this
  (same reasoning as `seed_demo_course._complete_unit`).
- **R5 Determinism.** All randomness comes from `random.Random(kit.seed)`; the same kit
  regenerates identically.
- **R6 Silence.** No mail, no webhook. `finalize_submission` is called directly; no
  notification helper is invoked.
- **R7 No real users touched.** The generator writes only for users in `kit.users`.

### 4.4 What `provision_kit(label, *, course, days, pupils)` creates

1. **Teacher login** — role Teacher (`set_user_role`), `language="pl"`, generated password,
   verified primary email `<slug>-nauczyciel@demo.invalid` via `ensure_verified_primary_email`
   (needed: `ACCOUNT_EMAIL_VERIFICATION="mandatory"`, `config/settings/base.py:105`).
   Username `<slug>-nauczyciel`. Login accepts username or email
   (`ACCOUNT_LOGIN_METHODS = {"username", "email"}`, `base.py:99`).
2. **Student login** — role Student, not staff, `<slug>-uczen`, same email/password
   treatment. Enrolled through `grouping.services.add_students_to_group` (never a direct
   `Enrollment.objects.create` — the service is the only sanctioned path), and left with
   **no activity**, so the rep starts the course from the beginning.
3. **~20 fake pupils** — realistic Polish display names, usernames `<slug>-p01…`, emails
   `@example.invalid`, `set_unusable_password()` so none can log in, role Student, enrolled
   via the same service.
4. **Group** — `"Klasa demo — <label>"` in `course`, the Teacher added to `group.teachers`.
5. **Activity** for the fake pupils (§4.5).

All inside one transaction.

### 4.5 The activity generator

- **Bands.** Each pupil draws an ability band: strong 20% / average 60% / struggling 20%,
  giving a per-question probability of a correct answer of about 0.9 / 0.65 / 0.35 and a
  depth multiplier of about 1.15 / 1.0 / 0.7.
- **Class frontier.** A position in the published-unit order, defaulting to the last
  published unit of the **third top-level part** (derived from the live tree, never
  hardcoded; if the course has fewer parts, the midpoint of the published units).
  `--frontier-part N` overrides it.
- **Per pupil:** complete every **obligatory published lesson** in course order up to
  `frontier × depth multiplier ± jitter`; attempt every **published quiz** at or before that
  depth. With 17 quizzes inside parts 0–2 the matrix fills well and its ragged right-hand
  edge looks like a real class. (The earlier draft's pupils rarely reached a quiz at all,
  which is why its matrix stayed empty; the frontier sits well past the first quizzes.)
- **Per quiz:** for each top-level question decide right/wrong (and, where the type supports
  partial credit, partly right) from the band; build the answer via the type's builder
  (§3.1 table); score it with `question.mark(answer)`; write a `QuestionResponse`
  (`fraction`, `earned_marks`, `latest_answer` via `answer_to_json`, `attempt_count`); then
  `finalize_submission` under `select_for_update` and a completed `UnitProgress`.
- **Unfinished work.** One or two pupils are left with an **IN_PROGRESS** submission on the
  quiz just past their depth (some responses written, no finalize), so the review queue has
  entries and "Force submit" has a target.
- **Dates.** Activity is spread over the ~6 weeks before `created_at`, oldest first, so the
  class reads as having worked over a term. ⚠️ `UnitProgress.completed_at` is set by
  `save()` on the False→True transition and `QuizSubmission.submitted_at` is stamped in
  `save()`; back-dating therefore needs a follow-up `update()` (a queryset update bypasses
  `save()`) — see open question Q1.
- **Builders registry.** A module-level map `{question model → builder}`, where each builder
  returns `(correct_answer, wrong_answer, partial_answer_or_None)`. §8 T5 drives a test off
  this map so a new question type cannot be silently unsupported.

### 4.6 Operator surfaces

**Commands** (`demo` app, one `demo_access` command with subcommands):

| invocation | behaviour |
|---|---|
| `demo_access create --label "SP 12 Kraków" [--days 14] [--pupils 20] [--course mat-pp] [--frontier-part N]` | provisions; prints kit id, both usernames, both generated passwords and the expiry **once** |
| `demo_access list` | id, label, created, expires, status (`active` / `expired — pending purge` / `revoked`) |
| `demo_access extend <id> --days N` | moves `expires_at` |
| `demo_access revoke <id>` | purges now |
| `demo_access purge [--dry-run]` | purges every kit past `expires_at` |

Passwords are generated with `secrets.choice` over an unambiguous alphabet (no `O`/`0`,
`l`/`1`), ~12 characters, and are **never stored** — only Django's hash.

**Cron**, added to runbook §7 as one physical line:

```cron
45 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py demo_access purge
```

03:45 UTC: clear of the 02:15 backup and the 03:30 `purge_notifications`.

**Admin tab (PR 3).** A "Demo access" tab in institution settings:

- registered in `_tabs()` (`institution/views_manage.py:56`) the same way `pricing` is, so it
  exists **only when `settings.VENDOR_INSTANCE`** — a school's box never shows it. ⚠️ Note
  the module's aliasing trap: `settings` is rebound in that module, so the flag is read as
  `django_settings.VENDOR_INSTANCE` (`institution/views_manage.py:36-37`).
- Platform Admin only (the tab's existing gate).
- create form (label, days, pupils) → POST → result page showing both usernames and
  passwords **once**, with a "these are not stored" warning.
- list with **Extend +14 days** and **Revoke** (confirmed) buttons.
- ⚠️ every action view rejects non-POST with 405 — `if request.method != "POST"`, never
  `== "GET"` (the #307 defect: HEAD and OPTIONS are CSRF-exempt in Django).
- Strings translatable, `pl` filled, 0 fuzzy.

### 4.7 Expiry semantics

A kit past `expires_at` but not yet purged keeps working until the next purge run; `list`
and the tab label it `expired — pending purge`. No login-time check is added: the nightly
job is the single mechanism, and a second one would be a place for the two to disagree.

### 4.8 `/for-schools/` copy (PR 2)

A new section in `docs/public/for-schools.md` and `for-schools.pl.md`, placed after
"What we offer": we set up a private demo — a teacher login and a pupil login on the full
maths course, with an example class so the analytics have data; write to
`{libli:contact_email}`; access lasts two weeks. `contact_email` is an existing **inline**
token (`core/public_pages.py:162-165,211`), so no new token is needed and the degenerate
blank case already reads correctly.

⚠️ Adding a file section touches the parametrised content guards in
`tests/test_for_schools_content.py` and friends; `for-schools` carries no
`{libli:demo_notice}` and must stay out of `DEMO_NOTICE_SLUGS`.
**Polish wording is Krzysztof's to approve** (nine earlier Polish suggestions were
deliberately left unapplied for the same reason — [[public-pages-privacy-status]]).

## 5. Ops steps for Krzysztof (not code)

1. Fill `Institution.contact_email` on libli.pl if still blank (it ships blank).
2. Decide whether to switch on `Institution.demo_instance`. It adds the "demonstration site
   — do not enter real pupil data" notice to `/privacy/` and `/getting-started/`; it does
   **not** affect `/for-schools/`, which is exempt by design.
3. Install the purge cron line.

## 6. Delivery — three PRs

**PR 1 — safety.** `seed_demo_course` refuses to run when `DEBUG=False` (a `CommandError`
naming the reason), plus runbook §7 rewritten to say so. One test. No migration.

**PR 2 — core.** The `demo` app: model + migration, `provision_kit` / `purge_kit`, the
generator, the `demo_access` command, the cron line in the runbook, and the `/for-schools/`
section in both languages.

**PR 3 — admin tab.** Views, templates, form, i18n, e2e. No new business logic: every action
calls PR 2's services.

## 7. Non-goals

- **N1** Self-serve demo signup.
- **N2** Outgoing email / the invitation flow.
- **N3** Lesson self-check state (`UnitProgress.element_state`) — analytics never reads it.
- **N4** Editing content in the demo; the rep's Teacher owns no course and cannot author.
- **N5** A password-reset action for a kit — revoke and re-create is two commands.
- **N6** Rendering demo data on a school's own box: the whole feature is vendor-gated.

## 8. Testing

Against a small fixture course in the test DB (`mat-pp` is not available there), each test
falsified against a named mutant:

- **T1 Derived score.** Every written response satisfies
  `mark(latest_answer).fraction == fraction`. Mutant: a fixed 0.5 score.
- **T2 The matrix is populated.** Build it through the real `rollups` code and assert
  percentages, not "—". Mutant: drop the `UnitProgress` write (R4).
- **T3 Drafts untouched.** A fixture with draft units gains no progress and no submissions,
  and the matrix gains no column. Mutant: drop the published filter (R2).
- **T4 Whole-unit skip.** A unit with an unanswerable question receives **no** submission and
  warns. Mutant: `continue` past the question instead (R3).
- **T5 Type coverage, derived not pinned.** Enumerate `QuestionElement` subclasses; assert
  each is either in the builders registry or in an explicit `SKIP_UNIT_TYPES` set. A new
  question type fails until someone classifies it. **No `len(...) == N` pin**
  ([[guards-that-assert-the-adjacent-thing]] #9).
- **T6 Determinism.** Same seed → same responses and same progress.
- **T7 Purge leaves nothing.** After a rep has created a collection and force-submitted,
  `purge_kit` removes every kit user, the group and all their rows; the `DemoKit` row
  survives with nulled FKs. Mutant: make one FK PROTECT and watch it fail (§3.5).
- **T8 Isolation.** Kit A's Teacher sees A's pupils in analytics and none of B's; cannot
  reach a draft unit; fake pupils cannot authenticate (unusable password).
- **T9 Enrolment via the service.** Assert the source calls `add_students_to_group`, not
  `Enrollment.objects.create` (a direct write skips the service's invariants).
- **T10 Admin tab.** 404 when `VENDOR_INSTANCE` is off; Platform-Admin-only; non-POST → 405;
  passwords appear once in the response and never in the DB.
- **T11 `seed_demo_course` refuses** under `DEBUG=False`.
- **T12 Silence.** Provisioning sends no mail (`mail.outbox` empty) and enqueues no webhook
  delivery (R6).

**Beyond the suite:** provision a kit against the local `mat-pp` copy and read the matrix,
the drill-down and the pupil view in a browser, light and dark. A green suite cannot say
whether the class looks believable ([[verify-ui-with-screenshots]],
[[reviews-that-execute-beat-reviews-that-read]]).

## 9. Risks

1. **Prod writes.** Each kit writes a few thousand rows to the live DB. `provision_kit` runs
   in one transaction; purge is exercised on the local copy before the first real kit.
2. **Teacher reads every course.** §3.3. A standing caveat for the day a second, private
   course lands on libli.pl.
3. **The class ages.** Dates are relative to `created_at`, so a repeatedly extended kit
   eventually shows a class that stopped working months ago. Acceptable for 14-day kits;
   `extend` prints a reminder past 60 days.
4. **`mat-pp` edits during a demo.** Deleting a unit a kit has data for removes that data
   (hard delete, [[deleted-elements-recover-only-via-lal-json]]). Harmless — the column
   simply disappears.

## 10. Open questions

- **Q1** Do `UnitProgress.completed_at` and `QuizSubmission.submitted_at` accept a
  back-dated value through a post-save `update()`, and does any analytics surface actually
  display those dates? If not, drop the back-dating (§4.5) as untestable decoration.
- **Q2** Confirm the default pupil count (20) and kit lifetime (14 days) with Krzysztof.
- **Q3** `/for-schools/` claims analytics drill down "to one pupil and one question", but no
  teacher-facing per-question view exists for AUTO answers (§3.2). Either the copy is
  corrected or the claim is met — decide before the demo is shown to anyone.
- **Q4** Should the demo show teacher **marking** at all? It needs a REVIEW question, which
  `mat-pp` does not have (§3.4). Options: leave it out, or give the demo a tiny separate
  course carrying one REVIEW question.
