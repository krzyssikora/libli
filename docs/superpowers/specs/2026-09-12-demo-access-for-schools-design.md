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
| D7 | **libli.pl will never host real pupils.** | Stated assumption, not contradicted: each school gets its own box ([[school-hosting-model-decisions]]). It is what makes fake pupils on prod acceptable. ⚠️ It is also why §4.1's vendor guard exists: the same code must refuse to run on a school's box, where D7 does not hold. |

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
- Published **lessons** hold a further 111 AUTO self-check questions (42 of 378
  lessons), whose answers live in `UnitProgress.element_state` (`courses/state.py:18`)
  — which **analytics never reads**. The generator does not write them (non-goal N3).
- **All 371 published question elements — the 260 in quizzes plus those 111 in lessons
  — were answered correctly and incorrectly by script and run through the real
  `mark()`; all 371 behaved as expected.** Only the 260 are in the generator's path;
  the lesson figure is reported because it was measured, not because it is in scope.
  So the answer-shape work is known-feasible, not hoped-for:

  | type | answer shape | correct from | wrong from |
  |------|--------------|--------------|-----------|
  | choice (`courses/models.py:2359`) | set of `Choice` pks | `is_correct=True` | any other choice |
  | shortnumeric (`:2566`) | str parsed by `parse_numeric_value` | `value` | `value + tolerance + 1` |
  | fillblank (`:2596`) | list of str, one per blank | first line of each `Blank.accepted` | any other string (partial credit possible) |
  | matchpair (`:2708`) | list of right-hand tokens in pair order | `expected_tokens()` | the same tokens rotated |
  | choicegrid (`:2773`) | list of one `GridColumn` pk per row | `row.correct_column_id` | any other column (partial credit possible) |

- Parts 0–2 (Zbiory liczbowe, Elementy logiki, Wyrażenia algebraiczne) hold
  **126 published lessons and 17 published quizzes**; parts 0–9 are all published.
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
  analytics are "drillable down to one pupil and one question" — see open question Q3,
  which blocks PR 4.
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
  `/admin/`. Acceptable while `mat-pp` is the only course on libli.pl; it is a standing
  caveat before a private course is added there.
- ⚠️ **The `/admin/` login is harmless only because `grouping/admin.py` registers no
  models** (verified 2026-09-12: the file is a comment saying management happens through
  `/manage/`). The Teacher role holds `grouping.view_group` and full collection CRUD
  (`institution/roles.py:80-86`), and Django admin applies none of `grouping/scoping.py`'s
  filtering — so registering a grouping model in admin later would silently give every
  demo Teacher cross-kit visibility. Guard test in §8 (T14).
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

**Published** `mat-pp` has **zero REVIEW-mode questions** (§3.1; the 49 draft quizzes in
parts 10–20 were NOT audited for marking mode), so the teacher review queue shows only
in-progress submissions (`courses/review.py:236-256`). The demo therefore shows
force-submit but not marking. Adding a REVIEW question to `mat-pp` purely for the demo is
**rejected**: it would change real content, and an unmarked REVIEW response drops its whole
submission from the matrix (§3.2). R3 names REVIEW-containing units as skip candidates so
that publishing such a part mid-demo cannot silently blank a column. Q4 records the
alternative if showing marking matters to Krzysztof.

### 3.5 Deletion is safe

No FK to `AUTH_USER_MODEL` anywhere in the project uses `on_delete=PROTECT` (checked
2026-09-12 across `accounts`, `courses`, `grouping`, `institution`, `notes`, `tags`,
`support`, `notifications`, `integrations`, `core`; every PROTECT in the codebase points at
`MediaAsset` or `GridColumn`). Deleting a kit's users therefore cascades their enrolments,
progress, submissions, responses, notes, tags, collections and cohort memberships away.
⚠️ Re-verify with a test, not by reading (§8, T7) — a future model could add one.

### 3.6 ⚠️ `seed_demo_course` must never run on prod, and may already have run

`docs/deployment.md:440-448` (runbook §7) instructs the operator to run it on the live box.
It is a **screenshot fixture**, not a demo seeder:

- it creates `demo_admin` with role **Platform Admin** and the password `demo-pass-123`,
  hardcoded in the repo (`courses/management/commands/seed_demo_course.py:60,101-107`);
- it also creates `demo_teacher` (Course Admin) and four pupils on the same password;
- it overwrites `Institution.name` to "Demo Academy" (`:481-484`);
- it enables a webhook endpoint pointing at `sis.demo.example` (`:463-476`);
- it saves an SSO config (`:453-461`).

**A `DEBUG=False` guard is forward-looking only.** Whether it has already been run on
libli.pl is unknown as at 2026-09-12 and must be established first — see the blocking ops
step §5.0. PR 1 ships both the guard and that checklist.

### 3.7 ⚠️ Creating a student user auto-joins the Default cohort

`grouping/signals.py::ensure_cohort_membership` is a `post_save` receiver on `User`: every
newly created **non-staff** user is added to the current Default cohort via
`services.sync_default_cohort_membership`. `sync_cohort_on_role_change` (an `m2m_changed`
receiver on the user↔auth-group relation) re-runs the same sync whenever `set_user_role`
changes a role.

Consequences for a kit, all accepted rather than fought:

- the kit's **Student and ~20 pupils join the Default cohort**; the Teacher does not
  (staff are skipped);
- so libli.pl's cohort surfaces show demo pupils while a kit is live. Acceptable under D7,
  and it keeps the kit on the same path as every other student the system creates;
- `CohortMembership.student` is CASCADE (`grouping/models.py:139-143`), so purging the kit's
  users removes the memberships. T7 asserts the Default cohort's member count returns to its
  pre-kit value.

`provision_kit` therefore does **not** suppress or undo these signals. Creating a user and
then deleting its cohort row would leave the kit's pupils in a state no production path
produces — the same class of mistake as writing `Enrollment` directly (§4.4).

## 4. Design

### 4.1 New app: `demo`, vendor-gated at the service boundary

A new Django app `demo` holding the model, services, generator, commands, views and
templates. Rationale: it is a vendor-only concern with its own lifecycle; keeping it out of
`institution` and `courses` means it can be reasoned about (and, if ever needed, removed) as
a unit.

`demo` goes in `INSTALLED_APPS` in `config/settings/base.py`, **not** in a vendor-only
settings module: a conditionally installed app makes its migration conditional too, and a
box that later flips the flag would need a migration run out of band.

⚠️ **Because the app ships everywhere, the guard is in the code, not the install:**
`provision_kit()` raises `ImproperlyConfigured` and every `demo_access` subcommand raises
`CommandError` when `settings.VENDOR_INSTANCE` is False. A school's box therefore carries an
empty table and a command that refuses to run — never a path to fake pupils beside real
ones. Test T13.

### 4.2 Model

```
DemoKit
  label          CharField(200)                  # "SP 12 Kraków"
  slug           SlugField(200)                  # slugify(label, allow_unicode=False); NOT unique
  course         FK(courses.Course, PROTECT)     # mat-pp
  group          FK(grouping.Group, SET_NULL, null=True)
  teacher        FK(User, SET_NULL, null=True, related_name="+")
  student        FK(User, SET_NULL, null=True, related_name="+")
  users          M2M(User, related_name="demo_kits")   # EVERY user the kit created
  seed           PositiveIntegerField            # RNG seed; makes the data reproducible
  pupil_count    PositiveSmallIntegerField
  frontier_part  PositiveSmallIntegerField(null=True)  # the --frontier-part override, if given
  created_at     DateTimeField(auto_now_add)
  expires_at     DateTimeField
  created_by     FK(User, SET_NULL, null=True, related_name="+")
  closed_at      DateTimeField(null=True)        # when the users and group were deleted
  closed_reason  CharField(choices=("expired", "revoked"), blank=True)
```

**`slug` is deliberately NOT unique.** A closed kit's row is retained (below), so a unique
slug would permanently block a second demo for the same school — the most likely second
interaction in a sales conversation. Uniqueness lives on the usernames instead:
`<slug>-nauczyciel` / `<slug>-uczen` / `<slug>-p01…` for the first kit, and
`<slug>-2-nauczyciel` … for the next, where the disambiguating integer is the lowest that
makes **every** username in the kit free. If any candidate username or email is taken by a
user the kit did not create, provisioning fails with a named error rather than reusing it.

**Closing policy.** `purge_kit` (whether from `revoke` or the nightly `purge`) deletes the
kit's users and its group, then **retains the `DemoKit` row** with `closed_at` set,
`closed_reason` recording which path closed it, and the user/group FKs nulled. The row is a
record of who was given a demo and when; it holds no credentials. `extend` and `revoke`
refuse a kit that already has `closed_at` set.

### 4.3 Rules the generator obeys

- **R1 Derived score.** For every response written, the stored `fraction` comes from
  `question.mark(answer)` on the answer actually stored. A stored answer and its mark can
  never disagree. `earned_marks` comes from `courses.scoring.earned_marks(fraction,
  max_marks)` — the same helper the production path and `seed_demo_course` use — so the
  0.50 and 2.00 `max_marks` questions quantise exactly as `finalize_submission` expects.
- **R2 Published only.** Only units with `published=True` receive progress or submissions —
  otherwise a draft appears in the matrix (§3.2).
- **R3 Whole-unit skip.** If a unit contains any question the builders registry cannot
  answer, **or any REVIEW-mode question**, the unit is skipped entirely and a warning naming
  the unit and the reason is printed. Never skip a single question: a partial unit still
  counts, and a missing response reads exactly like an unreviewed REVIEW question.
- **R4 Completed progress accompanies every submission.** `finalize_submission` deliberately
  does not touch `UnitProgress`; both production close paths write it, and so must this
  (same reasoning as `seed_demo_course._complete_unit`).
- **R5 Determinism.** All randomness comes from one `random.Random(kit.seed)`, consumed in a
  fixed documented order (§4.5). The same kit regenerates identically.
- **R6 Silence.** Provisioning sends no mail, enqueues no webhook delivery, and creates no
  `Notification` row for any user outside `kit.users`. `finalize_submission` is called
  directly; no notification helper is invoked.
- **R7 No real users touched.** The generator writes progress, submissions and responses
  only for users in `kit.users`. Test T3.
- **R8 Vendor only.** Nothing in §4.4 or §4.5 runs when `settings.VENDOR_INSTANCE` is False
  (§4.1).

### 4.4 What `provision_kit()` creates

```python
provision_kit(
    label, *, course, days, pupils,
    frontier_part=None, seed=None, created_by=None,
) -> DemoKit
```

`seed`, when omitted, is drawn once from `secrets.randbelow(2**31)` and **persisted on the
row before any generation runs** (R5 is meaningless otherwise). `created_by` is null for
command invocations and `request.user` for the PR 3 tab. `frontier_part` is stored as given
(null means "use the derived default", §4.5).

Order of work, inside one transaction:

1. **The group** — `"Klasa demo — <label> (#<kit pk>)"` in `course`. Created first: the
   enrolment service takes a group. The kit pk is in the name so two kits for the same
   school are distinguishable in the Teacher's pickers.
2. **Teacher login** — role Teacher (`set_user_role`), `language="pl"`, generated password,
   verified primary email `<username>@demo.invalid` via `ensure_verified_primary_email`
   (needed: `ACCOUNT_EMAIL_VERIFICATION="mandatory"`, `config/settings/base.py:105`).
   Added to `group.teachers`. Login accepts username or email
   (`ACCOUNT_LOGIN_METHODS = {"username", "email"}`, `base.py:99`).
3. **Student login** — role Student, not staff, same email/password treatment.
4. **`pupils` fake pupils** — display names drawn from a checked-in list of Polish given
   names and surnames shipped in the `demo` app (a library or generator would make T6
   dependent on an upgrade), `@demo.invalid` emails, `set_unusable_password()`, role Student.
5. **Enrolment** — the Student and the pupils are added with
   `grouping.services.add_students_to_group(group, students, added_by=<kit Teacher>)`, never
   a direct `Enrollment.objects.create` (the service is the only sanctioned path, and
   `GroupMembership.added_by` is SET_NULL so deleting the Teacher later is safe).
6. **Activity** for the fake pupils only (§4.5).

**The rep's Student is a member of the demo group and starts with no activity.** That is
deliberate: their row sits in the matrix at 0%, and fills in front of them as they work
through a lesson and submit a quiz — the demo's best moment. §4.8's copy says so, so an
empty row reads as "you", not as a bug.

One `@demo.invalid` domain is used for every kit user (logins and pupils alike), so "is this
address a demo account?" is one pattern.

### 4.5 The activity generator

**Constants** (module-level named values in the `demo` app, not literals inline — T6 depends
on them being fixed):

| band | share | P(correct) | depth multiplier |
|------|-------|-----------|------------------|
| strong | 0.20 | 0.90 | 1.15 |
| average | 0.60 | 0.65 | 1.00 |
| struggling | 0.20 | 0.35 | 0.70 |

- **Class frontier.** `FRONTIER_FRACTION = 0.65`: the frontier is the published-unit index at
  65% of the course's published units in course order, derived from the live tree.
  ⚠️ It is deliberately NOT "the third part": parts 0–9 of `mat-pp` are published, so a
  third-part frontier would leave ~7 of ~10 matrix columns empty for every pupil — the same
  mostly-blank matrix that sank the earlier seeder, only further right. `--frontier-part N`
  overrides the fraction with the last published unit of part N.
- **Per-pupil depth** = `clamp(round(frontier_index × multiplier × (1 + jitter)), 0,
  len(published_units) - 1)`, where `jitter = rng.uniform(-0.08, 0.08)`.
- **Per pupil:** complete every **obligatory published lesson** in course order up to that
  depth; attempt every **published quiz** at or before it.
- **Per quiz:** for each top-level question decide right/wrong (and, for types that support
  partial credit, partly right) from the band; build the answer via the type's builder
  (§3.1 table); score it with `question.mark(answer)`; write a `QuestionResponse`
  (`fraction`, `earned_marks` per R1, `latest_answer` via `answer_to_json`,
  `attempt_count = 1`); then `finalize_submission` under `select_for_update` and a completed
  `UnitProgress`. **Every pupil makes exactly one attempt per quiz**, whatever the unit's
  `max_attempts` allows — a retry would need an `Attempt` history to be coherent and buys
  the demo nothing.
- **Unfinished work.** `IN_PROGRESS_PUPILS = 2`: the first two pupils in generation order
  get an IN_PROGRESS submission on the quiz just past their depth (responses written, no
  `finalize_submission`, no `UnitProgress`), so the review queue has entries and
  "Force submit" has a target.
- **RNG order (fixed, part of R5):** bands for all pupils in generation order → then, per
  pupil in order: jitter, then per unit in course order, then per question in element order.
  An implementation that reorders these draws produces a different class from the same seed
  and fails T6.
- **Dates.** After the writes, one bulk `.update()` per model at the end of the transaction
  back-dates `UnitProgress.completed_at` and `QuizSubmission.submitted_at` across the
  `BACKDATE_DAYS = 42` before `created_at`, oldest unit first. A queryset `update()` is
  required because both are stamped in `save()`. ⚠️ Blocked on Q1: if no analytics surface
  displays these dates, drop the back-dating rather than ship untestable decoration.

**Builders registry.** A module-level map `{question model → builder}`, where each builder
returns `(correct_answer, wrong_answer, partial_answer_or_None)`. §8 T5 drives the coverage
test off this map and T1b tests the builders' behaviour — a registry entry that returns a
*wrong* "correct" answer is otherwise invisible (§8).

### 4.6 Operator surfaces

**Commands** (`demo` app, one `demo_access` command with subcommands):

| invocation | behaviour |
|---|---|
| `demo_access create --label "SP 12 Kraków" --course <slug> [--days 14] [--pupils 20] [--frontier-part N]` | provisions; prints kit id, both usernames, both generated passwords and the expiry **once** |
| `demo_access list` | id, label, created, expires, status (`active` / `expired — pending purge` / `closed (expired\|revoked)`) |
| `demo_access extend <id> --days N` | moves `expires_at`; refuses a closed kit; warns when the new `expires_at` is more than 60 days after `created_at` (the class's back-dated activity then looks abandoned) |
| `demo_access revoke <id>` | purges now, `closed_reason="revoked"`; refuses a closed kit |
| `demo_access purge [--dry-run]` | purges every kit matching `expires_at <= now() AND closed_at IS NULL`, `closed_reason="expired"` |

`--course` takes a **slug** and is required; the command errors clearly when no course
matches. (A default would be a foot-gun the day a second course lands on libli.pl, and
import re-derives slugs from titles, so a slug is not a stable identifier —
[[import-course-reslugs-and-drops-subjects]].)

⚠️ The purge predicate's `closed_at IS NULL` conjunct is what makes purge **idempotent**:
without it every historical kit is re-processed nightly for ever. It is tested directly
(T15), not just via `purge_kit`.

Passwords are generated with `secrets.choice` over an unambiguous alphabet (no `O`/`0`,
`l`/`1`), ~12 characters, and are **never stored** — only Django's hash.

**Cron**, added to runbook §7 as one physical line in the **root** crontab (`sudo crontab
-e`), like the other two; test once by hand with `--dry-run` first:

```cron
45 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py demo_access purge >> /var/log/libli-demo-purge.log 2>&1
```

03:45: clear of the 02:15 backup and the 03:30 `purge_notifications`. The host clock is UTC
(stated in runbook §7 for the backup line), so this is 03:45 UTC.

⚠️ **A silently failing purge leaves live logins on prod.** `docker compose … exec -T` fails
whenever the app container is down — which includes the ~24 s of every deploy
([[wanted-continuous-deployment]]) and indefinitely after a failed one. The log above is the
first line of defence; the second is that `demo_access list` is part of the ops routine
(§5.3) and shows `expired — pending purge` rows. No login-time expiry check is added (§4.7),
so this residual exposure is accepted knowingly rather than by omission.

**Admin tab (PR 3).** A "Demo access" tab in institution settings:

- registered in `_tabs()` (`institution/views_manage.py:56`) the same way `pricing` is, so it
  is listed **only when `settings.VENDOR_INSTANCE`**. ⚠️ Note the module's aliasing trap:
  `settings` is rebound in that module, so the flag is read as
  `django_settings.VENDOR_INSTANCE` (`institution/views_manage.py:36-37`).
- ⚠️ **A hidden tab is not a 404.** `_active_tab` falls back to `"branding"` for an unknown
  tab (`institution/views_manage.py:59-61`), so `?tab=demo` with the flag off renders the
  branding panel with **HTTP 200**. The create/extend/revoke **action views are separate
  URLs and carry their own `VENDOR_INSTANCE` gate returning 404** — that gate, not the tab
  list, is what protects them. T10 asserts both halves.
- Platform Admin only (the tab's existing gate).
- create form (label, days, pupils) → POST → **redirect** to a result page that reads the
  credentials from a **one-shot session key, popped on read**. Redirecting (rather than
  rendering on the POST) is what stops a browser refresh creating a second kit; popping is
  what makes "shown once" a mechanism rather than a wish. The page carries a "these are not
  stored" warning.
- a list with **Extend +14 days** and **Revoke** (confirmed) buttons; both hidden and refused
  for closed kits.
- ⚠️ every action view rejects non-POST with 405 — `if request.method != "POST"`, never
  `== "GET"` (the #307 defect: HEAD and OPTIONS are CSRF-exempt in Django).
- Strings translatable, `pl` filled, 0 fuzzy.

### 4.7 Expiry semantics

A kit past `expires_at` but not yet purged keeps working until the next purge run; `list`
and the tab label it `expired — pending purge`. No login-time check is added: the nightly
job is the single mechanism, and a second one would be a place for the two to disagree. The
failure mode this leaves open, and the mitigations, are stated in §4.6 and Risk 5.

**A rep logged in when the purge runs** simply loses their session: their user row is gone,
so Django's session auth fails and the next request redirects to the login page as an
anonymous visitor. T7 asserts that (a request with the purged user's session cookie is
anonymous, not a 500). The purge runs at 03:45, so this is unlikely to be observed.

### 4.8 `/for-schools/` copy (PR 4)

A new section in `docs/public/for-schools.md` and `for-schools.pl.md`, placed after
"What we offer": we set up a private demo — a teacher login and a pupil login on the full
maths course, with an example class so the analytics have data; the pupil login starts with
a blank record, which fills as you work through it; write to `{libli:contact_email}`; access
lasts two weeks. `contact_email` is an existing **inline** token
(`core/public_pages.py:162-165,211`), so no new token is needed and the degenerate blank
case already reads correctly.

⚠️ Adding a section touches the parametrised public-page content guards. Find them all with
`grep -rn "DEMO_NOTICE_SLUGS\|SHIPPED" tests/` before editing; as at 2026-09-12 they are in
`tests/test_for_schools_content.py`, `tests/test_public_pages_content.py` and
`tests/test_getting_started_trim.py`. `for-schools` carries no `{libli:demo_notice}` and must
stay out of `DEMO_NOTICE_SLUGS`.

**PR 4 is blocked on Q3 and on Krzysztof's approval of the Polish wording** (nine earlier
Polish suggestions were deliberately left unapplied for the same reason —
[[public-pages-privacy-status]]).

## 5. Ops steps for Krzysztof (not code)

0. **BLOCKING, before PR 2 ships:** establish whether `seed_demo_course` has ever been run on
   libli.pl, since runbook §7 has told the operator to do exactly that since the first
   deployment. Check for a `demo_admin` / `demo_teacher` user, an `Institution.name` of
   "Demo Academy", a `WebhookEndpoint` pointing at `sis.demo.example`, and a saved SSO
   config. If any is present: delete the demo users, restore the institution name, disable
   the webhook endpoint, and clear the SSO config. PR 1 ships this as a checklist in the
   runbook beside the guard.
1. Fill `Institution.contact_email` on libli.pl if still blank (it ships blank).
2. Decide whether to switch on `Institution.demo_instance`. It adds the "demonstration site
   — do not enter real pupil data" notice to `/privacy/` and `/getting-started/`; it does
   **not** affect `/for-schools/`, which is exempt by design.
3. Install the purge cron line, and add `demo_access list` to the routine you already use to
   look at the box — it is what surfaces a purge that has silently stopped running.

## 6. Delivery — four PRs

**PR 1 — safety.** `seed_demo_course` refuses to run when `DEBUG=False` (a `CommandError`
naming the reason), plus runbook §7 rewritten: the instruction removed, and the §5.0
"has it already been run?" remediation checklist added. One test. No migration.

**PR 2 — core.** The `demo` app: model + migration, `provision_kit` / `purge_kit`, the
generator, the `demo_access` command, the vendor guard, and the cron line in the runbook.
Blocked on §5.0 and on Q1/Q2.

**PR 3 — admin tab.** Views, templates, form, i18n, e2e. No new business logic: every action
calls PR 2's services.

**PR 4 — public copy.** The `/for-schools/` section in both languages. Split from PR 2
deliberately: it is blocked on a human decision (Q3) and a human translation review, and the
core app should not wait on either.

## 7. Non-goals

- **N1** Self-serve demo signup.
- **N2** Outgoing email / the invitation flow.
- **N3** Lesson self-check state (`UnitProgress.element_state`) — analytics never reads it.
- **N4** Editing content in the demo; the rep's Teacher owns no course and cannot author.
- **N5** A password-reset action for a kit — revoke and re-create is two commands.
- **N6** Running on a school's own box: the services and commands refuse (§4.1).
- **N7** Multiple quiz attempts per pupil (§4.5).

## 8. Testing

Against a small fixture course in the test DB (`mat-pp` is not available there), each test
falsified against a named mutant:

- **T1 Derived score.** Every written response satisfies
  `mark(latest_answer).fraction == fraction`, and `earned_marks` equals
  `courses.scoring.earned_marks(fraction, max_marks)`. Mutant: a fixed 0.5 score.
- **T1b Builders are honest** — the highest-value test here. For **every** entry in the
  builders registry, against a fixture question of that type:
  `mark(correct).fraction == 1`, `mark(wrong).fraction < 1`, and where a partial is returned
  `0 < mark(partial).fraction < 1`. Without this, T1 is tautological (R1 defines `fraction`
  as `mark()`'s output), and a builder returning a wrong "correct" answer yields a
  self-consistent, fully green, meaningless class. Mutant: swap one type's correct and wrong
  builders.
- **T2 The matrix is populated.** Build it through the real `rollups` code and assert
  percentages, not "—". Mutant: drop the `UnitProgress` write (R4).
- **T3 Real users untouched (R7).** A fixture course with a pre-existing enrolled student
  who is not in the kit gains **zero** new `UnitProgress`, `QuizSubmission` and
  `QuestionResponse` rows across a provision. Mutant: widen the generator's queryset from
  `kit.users` to all enrolled students.
- **T4 Drafts untouched.** A fixture with draft units gains no progress and no submissions,
  and the matrix gains no column. Mutant: drop the published filter (R2).
- **T5 Whole-unit skip.** A unit with an unanswerable question, and separately a unit with a
  REVIEW question, each receive **no** submission and warn. Mutant: `continue` past the
  question instead (R3).
- **T6 Type coverage, derived not pinned.** Enumerate `QuestionElement` subclasses; assert
  each is either in the builders registry or in an explicit `SKIP_UNIT_TYPES` set. A new
  question type fails until someone classifies it. **No `len(...) == N` pin**
  ([[guards-that-assert-the-adjacent-thing]] #9).
- **T7 Determinism.** Same seed → same responses, same progress, same band assignment,
  including after a reordering of the generator's loops (the fixed RNG order, §4.5).
- **T8 Purge leaves nothing.** After a rep has created a collection and force-submitted,
  `purge_kit` removes every kit user, the group (via `grouping.services.delete_group`) and
  all their rows; the Default cohort's member count returns to its pre-kit value (§3.7); the
  `DemoKit` row survives with nulled FKs, `closed_at` and `closed_reason` set; and a request
  carrying the purged Teacher's session cookie is anonymous, not a 500 (§4.7). Mutant: make
  one FK to User PROTECT and watch it fail (§3.5).
- **T9 Isolation.** Kit A's Teacher sees A's pupils in analytics and none of B's, and cannot
  reach a draft unit.
- **T10 Vendor gating of the tab.** With the flag off: the tab link is absent and `?tab=demo`
  falls back to the branding panel with 200 (**not** 404 — `_active_tab`'s fallback), while
  each action view returns 404. With the flag on: Platform Admin only; non-POST → 405.
- **T11 Credentials are shown once.** The password appears in the first render of the result
  page, is absent from the session afterwards, and is absent from a second GET of that page
  and from the list page. Mutant: render on POST without popping the session key.
- **T12 Silence (R6).** Provisioning leaves `mail.outbox` empty, enqueues no
  `WebhookDelivery`, and creates no `Notification` row for any user outside `kit.users`.
- **T13 Vendor guard.** With `VENDOR_INSTANCE=False`, `provision_kit` raises
  `ImproperlyConfigured` and `demo_access create` raises `CommandError`, and no rows are
  written.
- **T14 `/admin/` exposes nothing.** A kit Teacher's `/admin/` index lists zero models
  (§3.3). Mutant: register `Group` in `grouping/admin.py`.
- **T15 Purge selection.** A kit expiring tomorrow survives `demo_access purge`; one that
  expired yesterday does not; a second run is a no-op (idempotence via `closed_at IS NULL`);
  `--dry-run` writes nothing.
- **T16 Enrolment and deletion go through the services.** Provisioning calls
  `add_students_to_group` (not `Enrollment.objects.create`) and purge calls
  `delete_group` — asserted on behaviour where possible, on the source otherwise.
- **T17 Username disambiguation.** A second kit for the same label provisions successfully
  with distinct usernames; a collision with a **non-kit** user fails with the named error.
- **T18 Back-dating** (only if Q1 keeps it): `completed_at` and `submitted_at` land inside
  the `BACKDATE_DAYS` window before `created_at`, and are ordered oldest-unit-first.
- **T19 `seed_demo_course` refuses** under `DEBUG=False`.

**Beyond the suite:** provision a kit against the local `mat-pp` copy and read the matrix,
the drill-down and the pupil view in a browser, light and dark. **Acceptance criterion for
the frontier default: at least two-thirds of the matrix's quiz columns hold a score for at
least half the class.** A green suite cannot say whether the class looks believable
([[verify-ui-with-screenshots]], [[reviews-that-execute-beat-reviews-that-read]]).

## 9. Risks

1. **Prod writes.** Each kit writes a few thousand rows to the live DB. `provision_kit` runs
   in one transaction (back-dating included, as bulk updates at its end); purge is exercised
   on the local copy before the first real kit.
2. **Teacher reads every course.** §3.3. A standing caveat for the day a second, private
   course lands on libli.pl.
3. **The class ages.** Dates are relative to `created_at`, so a repeatedly extended kit
   eventually shows a class that stopped working months ago. Hence `extend`'s warning past
   60 days from `created_at`.
4. **`mat-pp` edits during a demo.** Deleting a unit a kit has data for removes that data
   (hard delete, [[deleted-elements-recover-only-via-lal-json]]). Harmless — the column
   simply disappears.
5. **A silently failing purge.** §4.6. Mitigated by the cron log and by `demo_access list`
   in the ops routine; accepted rather than solved with a second expiry mechanism.
6. **`@demo.invalid` becomes a bounce source once SMTP lands.** D4 holds today only because
   mail goes to the console. When `DJANGO_EMAIL_HOST` is set, every rep force-submit and
   every review mark tries to deliver to a reserved non-resolving domain. Decide then
   whether to suppress mail for `kit.users` or to accept the bounces.

## 10. Open questions

- **Q1** (blocks PR 2's date handling) Do `UnitProgress.completed_at` and
  `QuizSubmission.submitted_at` accept a back-dated value through a post-save `update()`,
  and does any analytics surface actually display those dates? If not, drop the back-dating
  (§4.5) and T18 as untestable decoration.
- **Q2** (blocks PR 2) Confirm the default pupil count (20), kit lifetime (14 days) and
  `FRONTIER_FRACTION` (0.65) with Krzysztof.
- **Q3** (blocks PR 4) `/for-schools/` claims analytics drill down "to one pupil and one
  question", but no teacher-facing per-question view exists for AUTO answers (§3.2). Either
  the copy is corrected or the claim is met — decide before the demo is shown to anyone.
- **Q4** Should the demo show teacher **marking** at all? It needs a REVIEW question, which
  published `mat-pp` does not have (§3.4). Options: leave it out, or give the demo a tiny
  separate course carrying one REVIEW question.
