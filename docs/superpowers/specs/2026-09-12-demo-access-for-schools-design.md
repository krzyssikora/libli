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
3. see teacher analytics — the progress/results matrix and the drill-down to one pupil,
4. and, secondarily, find the review queue non-empty: it is what makes "Force submit" a
   live button rather than a dead one. Listed here because §4.4's post-generation warning,
   §4.5's IN_PROGRESS pass and T5 all treat it as a deliverable, and a reader sizing the work
   from this list alone would otherwise miss it.

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
  | shortnumeric (`:2566`) | str parsed by `parse_numeric_value` | `value` | a value **outside the accepted band's upper bound**, computed from the band rather than by arithmetic on `tolerance` — the plan confirms the field's semantics at `courses/models.py:2566+`; if `tolerance` were ever relative, `value + tolerance + 1` could still land inside the band, R1b would fire and a whole unit would vanish for an untraceable reason |
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
- ⚠️ **A matrix column is NOT a quiz.** Columns come from `frontier_columns`
  (`courses/rollups.py:558-640`): each leaf column is a top-level part until the viewer
  expands it, and it carries `lesson_pks` / `quiz_pks` **sets over its whole subtree**, so a
  results cell sums every counted submission in that part. A column shows a score as soon as
  *one* quiz under it counts. Anything reasoning about "quiz columns" (§4.5, §8) must say
  whether it means the default part columns or the fully expanded unit columns.
- **Drill-down** (`courses/views_analytics.py:233`): lesson ticks from `UnitProgress.completed`
  (`courses/rollups.py:246-265`), a status pill per quiz (`:514-532`).
- ⚠️ **Scoring sees only top-level questions.** `compute_scores` (`courses/quiz.py:209`),
  `_quiz_review_maps` (`courses/rollups.py:346-351`) and `quiz_gradeable_max` all filter
  `parent__isnull=True`. A question nested in a callout or spoiler contributes to neither
  `score` nor `max_score`, and does not arm the REVIEW-pending gate. This is a property of
  the code, not of today's content, and it is what R9 rests on.
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
  ⚠️ **That is verified for `finalize_submission` ONLY.** R6 claims silence for the whole of
  provisioning, which also calls `User.objects.create_user` (×`pupils + 2` — Django's manager,
  not a project helper; the side effects to check are the `post_save` receivers §3.7
  enumerates), `set_user_role` (×`pupils + 2`), `ensure_verified_primary_email` (×2) and
  `add_students_to_group` (×1, looping internally over `pupils + 1` students) — none of them read
  for mail, `Notification` or webhook side effects. §3.7 already found that user creation
  fires two receivers nobody expected, so assuming these four are quiet is the one bet this
  spec otherwise refuses to make. **The plan verifies each with a file:line before relying on
  R6**, and T12 is what holds the line at runtime.

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
⚠️ Re-verify with a test, not by reading (§8, T8) — a future model could add one.

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
- `CohortMembership.user` is a **`OneToOneField`** (one cohort per student) with CASCADE
  (`grouping/models.py:61-66`) — note the field is `user`, not `student`, which is
  `GroupMembership`'s name; a query written from the wrong one raises `FieldError`. Purging
  the kit's users therefore removes the memberships. T8 asserts the Default cohort's member
  count returns to its pre-kit value.

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
`provision_kit()` raises `ImproperlyConfigured`, and the `create` and `extend` subcommands
raise `CommandError`, when `settings.VENDOR_INSTANCE` is False. A school's box therefore
carries an empty table and a command that refuses to create anything — never a path to fake
pupils beside real ones. **`purge`, `purge_kit`, `revoke` and `list` are exempt on purpose**;
the reasoning is in R8, and it is the one asymmetry in this design that is load-bearing
rather than tidy. Test T13.

✅ Verified 2026-09-12: the app label `demo` is free — `INSTALLED_APPS`
(`config/settings/base.py`) holds `core`, `accounts`, `institution`, `courses`, `grouping`,
`notes`, `notifications`, `tags`, `integrations`, `support` and no `demo`. (A label clash is
a hard startup failure on every box the app ships to, which is all of them; the existing
`seed_demo_course`, `Institution.demo_instance` and `{libli:demo_notice}` are names, not
labels.) PR 3's action views live under `/manage/settings/demo/…`, beside the other
institution-settings actions, in the `institution` URL namespace — the `demo` app ships no
URLconf of its own.

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
  seed           PositiveIntegerField            # RNG seed; diagnostic, see below
  pupil_count    PositiveSmallIntegerField
  frontier_part  PositiveSmallIntegerField(null=True)  # the --frontier-part override, if given
  created_at     DateTimeField(auto_now_add)
  expires_at     DateTimeField
  created_by     FK(User, SET_NULL, null=True, related_name="+")
  closed_at      DateTimeField(null=True)        # when the users and group were deleted
  closed_reason  CharField(max_length=16, choices=ClosedReason, blank=True)
```

`ClosedReason` is a `TextChoices` enum (`EXPIRED = "expired", _("Expired")` /
`REVOKED = "revoked", _("Revoked")`), matching how the rest of the codebase declares
choices — a bare tuple of strings is not a valid `choices` argument and would ship
untranslated labels.

⚠️ **`course` is PROTECT and rows are never deleted, so `mat-pp` becomes undeletable once
it has had a kit.** That is the intended direction (a course with demo history should not
vanish silently), but it must be stated: an operator who genuinely wants to delete a course
first deletes its closed `DemoKit` rows by hand. No automatic pruning of closed rows is
specified; if the table ever needs it, that is a new decision.

**`slug` is deliberately NOT unique.** A closed kit's row is retained (below), so a unique
slug would permanently block a second demo for the same school — the most likely second
interaction in a sales conversation. Uniqueness lives on the usernames instead:
`<slug>-nauczyciel` / `<slug>-uczen` / `<slug>-pNN` for the first kit, and
`<slug>-2-nauczyciel` … for the next.

**One rule, stated once:** the disambiguating integer is the lowest that makes **every**
username and email in the kit free, **whoever holds the taken one** — another kit's user or
an unrelated account alike. A taken name bumps the search; it is never adopted, which is what
"never reuse an existing account" means in practice. The **named collision error fires only
when 2..999 are exhausted**. ⚠️ An earlier draft said a non-kit holder was an immediate hard
failure; that would let one unrelated account permanently block every future kit for a
school whose `-3-`, `-4-` … names are all free. (Kit-created-ness would have been
`User.demo_kits.exists()` — the `users` M2M's reverse — and it is worth noting that a purged
kit leaves no such users behind, so the distinction could only ever have seen live kits.)

**Length and degenerate labels** (`AbstractUser.username` is `max_length=150`,
`Group.name` is 200, `grouping/models.py:84`):

- `slug = slugify(label, allow_unicode=False)[:SLUG_MAX]` with `SLUG_MAX = 100`, which
  leaves room for the longest suffix the scheme can produce (`-NNN-nauczyciel`, `-NNN-pNN`,
  budgeted against the widest disambiguating integer below, not a two-digit one).
- The disambiguating integer is searched over **2..999**; past that, the named collision
  error, so the search always terminates.
- A label that slugifies to `""` — a pure-punctuation label such as `"###"`, or CJK input —
  falls back to the literal `demo`; the disambiguating integer then separates schools.
  (Polish diacritics do **not** degenerate: `slugify("Łódź", allow_unicode=False)` is `odz`,
  since NFKD maps `ó`→`o` and `ź`→`z` and only the undecomposable `Ł` is dropped. A fixture
  built on a Polish label would never exercise this fallback.)
- Pupil numbering is zero-padded to the width of `--pupils` (`p01…p20` at the default), so
  it stays consistent and cannot collide within a kit; `--pupils` is bounded 5–40 (§4.4).
- The group name truncates the label to 150 characters before the ` (#<pk>)` suffix.

**Closing policy.** `purge_kit` (whether from `revoke` or the nightly `purge`) is
`@transaction.atomic` **per kit** — a partial failure that deleted the users, left the group
and never set `closed_at` would be re-purged nightly for ever and keep reading as "pending"
in `list`. It deletes **the users first, then the group** via
`grouping.services.delete_group`, so that service's post-delete enrolment recompute
(`grouping/services.py:249-254`) finds no surviving members; then it **retains the `DemoKit`
row** with `closed_at` set, `closed_reason` recording which path closed it, and the
user/group FKs nulled.

⚠️ The call is `delete_group(group)` — verified 2026-09-12: it takes **no actor argument**
(it reads the memberships, deletes, and recomputes enrolment for the former members), which
is what makes the users-first order safe. Had it required an actor there would be none, since
every kit user is gone by then. (`created_by` is a Platform Admin, never a kit user, and
purge never touches it.)

⚠️ **`purge_kit` must tolerate a half-dismantled kit.** All three FKs are SET_NULL precisely
because their rows can vanish — a group deleted by hand, say. (Not cascaded away with its
course: `course` is PROTECT and kit rows are never deleted, so that path is unreachable for
exactly the kits purge runs against.) So
purge deletes whatever of `kit.users` still exists, calls `delete_group` **only when
`kit.group_id` is not null**, and sets `closed_at`/`closed_reason` in every case, including
the wholly empty one. Otherwise `delete_group(None)` raises inside the per-kit transaction,
`closed_at` is never set, the kit matches the purge predicate for ever and every nightly run
exits non-zero — Risk 5's silently failing purge, made permanent. T15 covers it. The row is a
record of who was given a demo and when; it holds no credentials. `extend` and `revoke`
refuse a kit that already has `closed_at` set.

### 4.3 Rules the generator obeys

- **R1 Derived score.** For every response written, the stored `fraction` is
  `courses.scoring.to_stored_fraction(question.mark(answer).fraction)` on the answer
  actually stored, and `earned_marks` is `courses.scoring.earned_marks(fraction,
  max_marks)` — the pair `seed_demo_course._respond` and the production path both use.
  ⚠️ `mark()` returns a **float** and the column is a quantised `Decimal`
  (`courses/scoring.py:17-29`), so the conversion is load-bearing, not cosmetic: without
  it the field gets a float and any partial-credit assertion (1/3 on a fillblank) compares
  `Decimal("0.3333")` against `0.3333…` and fails on correct code. A stored answer and its
  mark can never disagree.
- **R1b Per-question validation at generation time.** Before using a builder's output, the
  generator asserts `mark(correct).fraction == 1.0` and `mark(wrong).fraction < 1.0`
  **for that specific question row**, and on failure applies R3's whole-unit skip with a
  warning naming the unit and the question. Type-level support is not enough on live data:
  a choice question with no `is_correct` row yields an empty pick, a fillblank whose first
  `accepted` line is blank yields `""`, and a shortnumeric whose `value` fails
  `parse_numeric_value` marks 0.0 for **every** answer (`courses/models.py:2574-2576`
  guards exactly that hand-edited/pre-migration case). Any of those silently produces a
  strong-band pupil failing a question. A failure here is a skip, never an exception that
  aborts the kit.
  ⚠️ **Validation runs on the STORED form of the answer, not the builder's Python value.** The
  builders return Python objects (a `set` of pks, a list of strings); `latest_answer` holds
  what `answer_to_json` made of them, and `answer_from_json` turns a choice answer back into a
  set (`courses/quiz.py:174,192`). So the generator serialises first and validates the
  deserialised value — otherwise R1b could pass on a builder whose *stored* answer marks
  differently, and T1, which re-marks `latest_answer`, would fail on code R1b called correct.
  Builder output, stored answer and asserted mark are then the same object by construction.
  ⚠️ **The partial answer is validated per row too**, whenever one is used:
  `0 < mark(partial).fraction < 1`. R1b's own argument applies to it verbatim — a "partial"
  fill-blank whose remaining blanks happen to match, or a partial on a single-row grid, marks
  **1.0**, so a pupil the generator decided got the question wrong is recorded with full
  credit and the band probabilities quietly stop meaning anything. A partial that fails
  validation **falls back to the validated wrong answer for that question**; it does not skip
  the unit, because a working wrong answer is already in hand. From then on that question is
  **treated as non-partial-capable and consumes one draw**, not two — pinned because the
  alternative (draw twice, discard the second) shifts the stream for every later question, the
  same R5 hole the NOT_MARKED and sentinel cases close.
  ⚠️ **A builder that cannot construct a wrong answer at all** — a matchpair whose rotation
  is the identity (one pair, or all right-hand tokens equal), a choice with one option or
  with every option correct, a one-column grid row — returns the module-level sentinel
  **`NO_WRONG_ANSWER`** in the wrong-answer slot (a named singleton, deliberately not `None`,
  which already means "this type supports no partial" in the third slot), and the
  generator then **answers it with the correct answer, consuming no RNG draw, and does not
  skip its unit.**
  ⚠️ **Be honest about what that costs.** For a genuinely NOT_MARKED question the answer is
  invisible — `compute_scores` excludes it from `score` and `max_score` alike. For a
  **sentinel on an AUTO question it is not**: that question's `max_marks` still counts toward
  `max_score` and the correct answer earns full marks, so **every pupil in every band aces
  it**. That is accepted — a shared full-marks question is a mild artefact, where the
  alternatives are worse: omitting the response penalises everyone (`max_score` counts it,
  `score` does not, §3.2) and skipping the unit blanks a whole column for a code-shaped
  reason. What the two paths share is the *mechanism* (correct answer, zero draws), not the
  scoring consequence; an earlier draft claimed "neither reaches `score` or `max_score`",
  which is false for the AUTO half. Zero draws is what keeps the RNG stream identical either
  way, which is what T7 needs. Blanking a whole matrix column because a
  builder ran out of options would be a content-shaped symptom with a code-shaped cause, and
  §8's criterion excludes skipped units from its denominator, so nothing would surface it.
- **R2 Published only.** Only units with `published=True` receive progress or submissions —
  otherwise a draft appears in the matrix (§3.2).
- **R3 Whole-unit skip.** If a unit contains any **question** (R9's filtered set — never a
  prose or image element) the builders registry cannot answer, including one whose type is in
  neither the registry nor `UNANSWERABLE_QUESTION_TYPES`, any question that
  fails R1b, **or any REVIEW-mode question**, the unit is skipped entirely and a warning
  naming the unit and the reason is printed. Never skip a single question: a partial unit
  still counts, and a missing response reads exactly like an unreviewed REVIEW question.
  **The one exception is a NOT_MARKED question**, which `compute_scores` excludes from both
  `score` and `max_score` (`courses/quiz.py:204-228`): it is answered with the **correct**
  answer and consumes **no RNG draw** (§4.5), and when its type has no builder it is skipped
  **without** skipping the unit — it can contribute to neither total, so a missing response
  cannot distort anything.
  That exception is stated here because it is the only place R3's "never skip one question"
  does not hold.
- **R4 Completed progress accompanies every submission.** `finalize_submission` deliberately
  does not touch `UnitProgress`; both production close paths write it, and so must this
  (same reasoning as `seed_demo_course._complete_unit`).
- **R5 Determinism.** All **content** randomness — names, bands, jitter, right/wrong, partial
  — comes from one `random.Random(kit.seed)`, consumed in the fixed order documented in
  §4.5. The same kit regenerates identically against the same content. Two deliberate
  exceptions, both `secrets`-sourced and both outside the rule: the **seed draw** itself and
  the **passwords** (§4.6), which must not be reproducible.
- **R6 Silence.** Provisioning sends no mail, enqueues no webhook delivery, and creates no
  `Notification` row for any user outside `kit.users`. `finalize_submission` is called
  directly; no notification helper is invoked.
- **R7 No real users touched.** The generator writes progress, submissions and responses
  only for users in `kit.users`. Test T3.
- **R8 Vendor only, on the creating half.** `provision_kit` (§4.4, §4.5) and the `create` and
  `extend` subcommands refuse when `settings.VENDOR_INSTANCE` is False (§4.1).
  ⚠️ **`purge_kit`, `purge`, `revoke` and `list` are deliberately NOT guarded.** Guarding a
  cleanup path is the one way the guard itself could leave stranger-known logins alive on
  prod: the flag is an env var (`LIBLI_VENDOR_INSTANCE`, `config/settings/base.py:288`), and
  a compose change that loses it would turn the nightly purge into a non-zero exit in a log
  nobody greps (Risk 5). **`revoke` belongs in the exempt set for the same reason** — it is
  the only immediate removal (after a credential leak, or the PR 3 timeout case in §4.6 that
  leaves "a kit only `revoke` can clear"), and guarding it would mean up to 24 hours of
  exposure with no operator override, in precisely the scenario the rule exists for. Every
  exempt command destroys or reads; none creates, and on a school's box the table is empty so
  all are no-ops there. T13 asserts this split at the **service** level as well as the parser.
- **R9 Top-level QUESTIONS only.** The generator enumerates
  `unit.elements.filter(parent__isnull=True).order_by("order", "pk")` **and keeps only those
  whose `content_object` is a `QuestionElement` instance** — the join rows are `Element`s, and
  §3.1 measured 479 elements against 260 questions, so the other 219 are prose, images and
  callouts. ⚠️ Without the question filter, R3's "a type in neither the registry nor
  `UNANSWERABLE_QUESTION_TYPES`" matches a text element and **every quiz is skipped**, leaving
  an empty kit that §4.4's post-generation invariant then rolls back. R3's classification rule
  is scoped to **question** types; a non-question element is ignored silently, like §4.5's
  non-lesson non-quiz units. Resolving a join row to its concrete subclass uses the same
  `content_object` access `compute_scores` does (`courses/quiz.py:213-217`,
  `prefetch_related("content_object")`), not a bespoke union.
  ⚠️ The **explicit `order_by` is load-bearing**: `Element.order` is
  `OrderField(for_fields=["unit"])` (`courses/models.py:337`) and an unordered queryset lets
  Postgres return rows in any order, which silently breaks R5 and makes T7 flaky rather than
  red. The same explicit ordering applies wherever the generator walks blanks, pairs, grid
  rows or choices — a matchpair's "tokens rotated" and a fill-blank's per-blank list both
  depend on a pinned order.
  Only top level: `compute_scores` and the review-pending gate filter `parent__isnull=True`
  (§3.2), so a nested question is neither answered nor a cause of an R3 skip — answering one
  would write responses the score path ignores. This is a rule, not
  an observation about today's `mat-pp`: §3.1's audit found all 260 questions top-level, but
  the reason it is *safe* is the `parent__isnull=True` filter, which holds whatever the
  content does next.

### 4.4 What `provision_kit()` creates

```python
provision_kit(
    label, *, course, days, pupils,
    frontier_part=None, seed=None, created_by=None,
) -> ProvisionResult          # dataclass: kit, teacher_password, student_password
```

⚠️ **The return type is a `ProvisionResult`, not the `DemoKit` row** — the row cannot carry
the passwords, because they are never persisted (§4.6), so returning it would leave both
callers with no way to display what they are required to display and make T11
unimplementable. `ProvisionResult` is an in-memory dataclass, and "never logged" is given a **mechanism**
rather than left as a rule: both password fields carry `field(repr=False)` (a plain
`@dataclass` generates a `__repr__` listing every field), `provision_kit` is decorated
`@sensitive_variables()` and PR 3's action view `@sensitive_post_parameters()`. ⚠️ Django's
error reporter dumps local variables into tracebacks — and into `ADMINS` mail once SMTP lands
(Risk 6) — so without those, any unrelated exception below the view leaks both
stranger-bound prod passwords into a log or an email. T22 asserts the `repr`. "Shown once" is therefore a property of the
caller — the command prints it and forgets it; the tab puts it in the one-shot session key.

`seed`, when omitted, is drawn once from `secrets.randbelow(2**31)` and **persisted on the
row before any generation runs** (R5 is meaningless otherwise). `created_by` is null for
command invocations and `request.user` for the PR 3 tab. `frontier_part` is stored as given
(null means "use the derived default", §4.5).

**The named errors.** One hierarchy, referenced by all three consumers: `DemoKitError` as the
base, with `InvalidLabel`, `InvalidBounds(field)`, `InvalidFrontierPart`, `UsernameCollision`,
`EmptyCourse`, `EmptyKit`, **`KitAlreadyClosed`** (raised by `extend_kit` and `revoke_kit` on a
kit whose `closed_at` is set — a first-class behaviour on two subcommands, two services and
two PR 3 buttons, which an earlier draft left with no class for T15b to assert on) and
**`NamePoolExhausted`** (the bounded surname redraw, §4.5). The command maps each to a `CommandError` with a useful message;
**PR 3's form needs `InvalidBounds` to carry the offending field name**, or it cannot attach
the message to `pupils` rather than `days` and the "the form inherits the bounds by calling
the service" claim fails; the tests assert on these classes rather than on `ValueError`.

**Preconditions and bounds, enforced in `provision_kit` itself** — not only in the command,
so the PR 3 form inherits them — each raising the matching error above:

- `label` non-blank after stripping and at most 200 characters. ⚠️ It is the one free-text
  input, and `Model.objects.create()` does **not** enforce `max_length`: an over-long label
  reaches Postgres as a raw `DataError` mid-transaction, after the collision scan, instead of
  a named error — and PR 3's form would inherit no check at all;
- `5 <= pupils <= 40` and `1 <= days <= 90` (0 or negative days creates a kit the next purge
  deletes; 500 pupils would write six figures of rows in one web request). ⚠️ **The floor is
  5, not 2**, because the integer partition gives `strong = struggling = pupils * 20 // 100`,
  which is **0** for 2–4 pupils: the whole class would be one band, with uniform `P(correct)`,
  uniform depth and uniform `P_LESSON_DONE`, making §8's "gaps, not a staircase" criterion
  and T7's band assertion vacuous. 5 is the smallest size with at least one pupil in every
  band;
- the frontier: when `--frontier-part N` is given, part N must exist and contain at least one
  published unit — checked **here**, with the other preconditions, not inside the generator.
  Otherwise the error surfaces only after the kit row, the group, and every user and allauth
  row have been written; the transaction rolls back, but the disambiguating-integer search
  and a few hundred writes happened for nothing, and PR 3's form would not inherit the check;
- ⚠️ **the course's published-unit list must be non-empty**, checked before step 0. Otherwise
  `len(published_units) - 1` is `-1`, the depth formula's `clamp(x, 0, -1)` has an inverted
  range, and every pupil's slice is empty — a provisioned kit with live credentials and
  nothing in it. Pointing `--course` at a freshly imported or wholly draft course is the most
  likely operator slip, and "a course with that slug exists" does not catch it;
- **a post-generation invariant on what was actually written**, checked inside the
  transaction so a failure rolls the whole kit back: **every generated pupil holds at least
  one completed obligatory `UnitProgress`, and at least one finalized `QuizSubmission` with a
  non-null `score`** — raising `EmptyKit`.
  ⚠️ **It is made satisfiable by construction, not left to the dice — and that takes two
  guarantees, not one.**
  1. *The draw:* the first obligatory lesson in a pupil's slice is completed **regardless of
     its `P_LESSON_DONE` draw**, though the draw is still consumed so R5's stream is
     unchanged. (No such clause is needed for the quiz: every in-slice quiz is attempted
     unconditionally, §4.5 — there is no per-quiz draw.) Without this, a struggling pupil with
     three obligatory lessons in slice fails all three `P = 0.80` draws with p ≈ 0.008; across
     four struggling pupils that is a few percent of provisions going red for a
     content-shaped reason, on a `secrets`-drawn seed.
  2. *The slice geometry:* for these two guaranteed rows **only**, a pupil whose slice
     contains no obligatory lesson, or no surviving quiz, reaches forward to the first one in
     the course's pre-order. ⚠️ Otherwise the guarantee is conditional on what the slice
     happens to hold, which the dice also decide: a struggling pupil sits at
     `round(frontier_index × 0.70 × (1 ± 0.08))`, so under the endorsed `--frontier-part 0` a
     part opening with a run of lessons before its first quiz gives them no quiz at all, and
     a legal invocation rolls back with `EmptyKit`, intermittently.

  With both, `EmptyKit` stays a genuine last-resort assertion — it fires only when the course
  itself has no obligatory lesson or no surviving quiz anywhere, which is what T22 exercises. ⚠️ A kit-wide floor of "at least one submission anywhere" — the earlier
  wording — is satisfied by a kit where nineteen of twenty pupils have an entirely blank
  results row, which is reachable whenever a struggling pupil's slice contains no quiz, reads
  as a broken demo, and leaves the suite green. Per pupil is the assertion that matches what
  a rep sees. (The IN_PROGRESS submission is a **warning**,
  not a rollback condition — §4.5 — and is stated separately because "X or a warning" is
  unfalsifiable: any implementation satisfies it by warning.) ⚠️ "At least one quiz survived R3/R1b" — the earlier wording — is not the
  same thing: every pupil's slice ends at their depth, so a course whose surviving quizzes
  all sit past even the strong band's reach passes that check and still provisions live
  credentials with an empty results mode and an empty review queue, which is exactly what the
  check exists to prevent. Assert on rows written, not on the candidate set.

Order of work, inside one transaction:

0. **The `DemoKit` row** — label, slug, course, `expires_at`, `pupil_count`,
   `frontier_part`, `created_by` and the resolved `seed`. It is created **first** because
   the group name embeds its pk and every later step writes back to its FKs.
   ⚠️ **What the stored `seed` is for.** There is no `--seed` flag and no regenerate
   subcommand — regenerating a live kit in place is a non-goal (it would rewrite a class the
   rep may be looking at). R5's determinism exists so the **suite** can pin a class (T7) and
   so a puzzling kit can be reproduced locally from its stored seed **against a database
   restored to the same content state** — §3.1's warning that local drifts from prod applies
   here too, and the seed alone reproduces nothing if the units or question rows have moved.
   `expires_at = timezone.now() + timedelta(days=days)` — stated because §4.6 pins
   `extend`'s arithmetic and leaving creation's implicit invites "end of the Nth day"
   instead. Consequence: a 14-day kit created at 10:00 is deleted by the 03:45 run on day
   15, so a rep gets 14 days plus a fraction.
   ⚠️ **Before any user is created**, scan every candidate username and email for a
   collision, case-insensitively, across `User.username`, `User.email` **and allauth's
   `EmailAddress.email`** — addresses live in both tables, and `ensure_verified_primary_email`
   raises a bare `ValueError` on a verified row bound to another user
   (`accounts/emails.py:8-17`). Scanning all names up front means the demo app's own named
   exception fires before the group exists, rather than allauth's `ValueError` landing
   mid-transaction with a Teacher already written; if that `ValueError` ever does fire, it is
   a bug in the scan, not an expected path. The unique constraint remains the real arbiter:
   an `IntegrityError` during user creation (two concurrent `create` runs resolving the same
   disambiguating integer) is caught and re-raised as the same named collision error.
   ⚠️ **That catch must run no further queries and must let the whole transaction unwind — no
   retry.** Once an `IntegrityError` surfaces inside an `atomic` block the transaction is
   marked for rollback, and any ORM call before unwinding raises `TransactionManagementError`
   instead, turning the named error into a confusing second exception. A retry would need its
   own savepoint; it is not worth one for a race that needs two concurrent `create` runs by a
   single operator.
1. **The group** — `Group.objects.create(name="Klasa demo — <label> (#<kit pk>)",
   course=course)`, then written to `kit.group`. ✅ Verified 2026-09-12 that a bare
   `objects.create` is right here: `grouping/services.py` wraps membership and deletion but
   has **no** group-creation helper. `archived` stays at its `False` default
   (`grouping/models.py:99`) — ⚠️ load-bearing, because `can_review_course` counts only
   teachers of a **non-archived** group (§3.3), so an archived group would silently make the
   whole kit invisible to the rep; T16 asserts the predicate rather than the flag. Created
   before the users: the enrolment service takes a group. The kit pk is in the name so two
   kits for the same school are distinguishable in the Teacher's pickers.
2. **Teacher login** — created with **`is_staff=True` in the initial `create_user` call**,
   then role Teacher via `set_user_role`, `language="pl"`,
   `display_name=f"Nauczyciel demo — {label}"` (truncated to the field's max length; the bare
   "Nauczyciel demo" would give every live kit an identical row in the People page and the
   group pickers, the ambiguity the kit pk in the group name exists to avoid), generated
   password, verified primary email
   `<username>@demo.invalid` via `ensure_verified_primary_email` (needed:
   `ACCOUNT_EMAIL_VERIFICATION="mandatory"`, `config/settings/base.py:105`). Login accepts
   username or email (`ACCOUNT_LOGIN_METHODS = {"username", "email"}`, `base.py:99`).
   ⚠️ **`is_staff` at creation time is load-bearing, not tidiness.** `ensure_cohort_membership`
   is a `post_save` receiver (§3.7) that skips staff — but `set_user_role` grants staff
   *after* the row exists, so a Teacher created non-staff would join the Default cohort on
   insert and depend on the `m2m_changed` re-sync to leave again. Setting the flag in the
   same `create_user` call means the receiver never adds it. T8 asserts the live kit's
   Teacher holds no `CohortMembership`.
   **Attached to `group.teachers` by a direct M2M add** — verified 2026-09-12: `grouping/
   services.py` wraps student membership (`add_students_to_group`) and group deletion
   (`delete_group`) but has **no** teacher-side function, so the M2M *is* the sanctioned
   path here, unlike the enrolment case in step 5. This single write is what makes
   `can_review_course` true for the rep (§3.3), so T16 asserts that predicate rather than
   the row.
3. **Student login** — role Student, not staff, `display_name=f"Uczeń demo — {label}"`
   (same reasoning; T20 still reads it as a human name rather than a username), same
   email/password treatment.
4. **`pupils` fake pupils** — `first_name` and `last_name` drawn (distinctly, §4.5) from
   **two gendered, checked-in lists** shipped in the `demo` app: feminine given names paired
   with feminine surname forms, masculine with masculine, the gender drawn first.
   ⚠️ Polish surnames inflect (`Kowalski`/`Kowalska`; `Nowak` is invariant), so independent
   draws from one flat pair of lists produce "Anna Kowalski" and "Piotr Nowacka" — obviously
   fake to any Polish reader, on the screen §4.4 calls the demo's best moment and §8 asks a
   human to judge for believability. A library or generator is rejected for a different
   reason: it would make T7 depend on a package upgrade. `@demo.invalid` addresses written to
   `User.email` **with no allauth `EmailAddress` row** — they never authenticate, so there is
   nothing to verify — `set_unusable_password()`, role Student, `language="pl"`.
   The collision scan (step 0) still covers both tables for every candidate.
   ⚠️ **Every kit user needs a `display_name`, and an earlier draft of this spec got that
   backwards.** The three demo screens render **`student.display_name|default:student.username`
   and nothing else** — `analytics_matrix.html:144-145`, `analytics_student.html:9`,
   `review_queue.html:16,31`, `review_submission.html:58`. `User.__str__` is
   `display_name or username` (`accounts/models.py:42`); only `sort_name` (`:45-55`) and
   `list_display_name` (`:57-72`) consult `first_name`/`last_name`, and **no demo screen uses
   either**. So pupils given only `first_name`/`last_name` would render as
   `sp-12-krakow-p01 … p20` across the matrix, the drill-down and the review queue — the exact
   failure the names exist to prevent, with the gendered lists, the redraw and the pool
   assertion all buying nothing visible.
   **So each pupil gets `first_name`, `last_name`, AND `display_name = f"{first} {last}"`**
   (`max_length=150`, `accounts/models.py:26`). Setting all three keeps `list_display_name`
   clean too: it appends `" (display)"` only when the display string differs from
   `"First Last"` (`:70`), which this spelling never does. The two logins keep their
   label-carrying `display_name`.
   ⚠️ **The matrix does not sort by surname**: `courses/views_analytics.py:96-98` orders the
   pool by `username`, and `polish_sort_key` lives only in `grouping/views.py`. The class list
   therefore reads in generation order, with the rep's own `…-uczen` row last — harmless, but
   no rationale should rest on alphabetical-by-surname.
   T20 asserts a **generated pupil's** row shows a human name, not only the rep's Student row:
   the Student is the one row that carries a `display_name` on the broken build and would pass
   alone.
   Every kit user is created with `language="pl"` — the pupil login walks a Polish lesson in
   front of the rep, so the default locale must not decide it.
5. **Enrolment** — the Student and the pupils are added with
   `grouping.services.add_students_to_group(group, students, added_by=<kit Teacher>)`, never
   a direct `Enrollment.objects.create` (the service is the only sanctioned path, and
   `GroupMembership.added_by` is SET_NULL so deleting the Teacher later is safe).
5.5. **The kit-wide content pass**, computed **once**, before any pupil is touched: resolve
   the published-unit list (§4.5), validate every top-level question per R1b, and cache the
   R3-skipped set, the per-question answers and the answerable-quiz candidate set.
   ⚠️ R1b costs two or three `mark()` calls per question row; re-deriving it inside the
   per-pupil loop multiplies that by `pupils` — a 20× multiplier on exactly the cost PR 3's
   request timeout turns on (§4.6). It also settles that "passes R3 for this kit" is a
   kit-level fact, not a per-pupil one, which the IN_PROGRESS rule depends on.
6. **Activity** for the fake pupils only (§4.5), consulting that cache and never re-marking.

⚠️ **Every user is added to `kit.users` the moment it is created** — steps 2, 3 and 4 each
write the M2M immediately, never in a batch at the end. Two behaviours read that set and
both break if it is populated late or partially: R7/T3 filter the generator's write set by
`kit.users` (an empty set means the generator writes nothing), and **`purge_kit`'s deletion
set is exactly `kit.users`** — a Teacher missing from it is a live staff login left on prod
under a kit marked closed. T8 asserts the Teacher, the Student and every pupil are members.

**The rep's Student is a member of the demo group and starts with no activity.** That is
deliberate: their row sits in the matrix at 0%, and fills in front of them as they work
through a lesson and submit a quiz — the demo's best moment. §4.8's copy says so, so an
empty row reads as "you", not as a bug.

One `@demo.invalid` domain is used for every kit user (logins and pupils alike), so "is this
address a demo account?" is one pattern.

### 4.5 The activity generator

**Constants** (module-level named values in the `demo` app, not literals inline — T7 depends
on them being fixed):

| band | share | P(correct) | depth multiplier |
|------|-------|-----------|------------------|
| strong | 0.20 | 0.90 | 1.15 |
| average | 0.60 | 0.65 | 1.00 |
| struggling | 0.20 | 0.35 | 0.70 |

- **Band assignment is a fixed partition, not a weighted draw per pupil.** In integer
  arithmetic off the shares themselves — `STRONG_PCT = STRUGGLING_PCT = 20`,
  `strong = struggling = pupils * STRONG_PCT // 100`, the remainder `average`, and the table
  above renders those same constants rather than restating them (a literal `20` in the
  formula means editing the table changes nothing and T7 still passes); float
  `floor(0.20 * pupils)` is at the mercy of binary representation (`0.2 * 15` is
  `3.0000000000000004`) in a rule T7 needs to be exact; the resulting list is then shuffled once
  with the kit RNG **and zipped with the pupils in creation order** (the mapping is
  load-bearing: R5 needs two implementations to agree, and the IN_PROGRESS rule tie-breaks on
  creation index). A per-pupil weighted
  draw was rejected: a 20-pupil class could legitimately come out with no strugglers, which
  makes both the demo and the §8 acceptance criterion non-deterministic in a way T7 cannot
  express. The floor rule keeps the middle band absorbing the remainder at every size the
  bounds allow (5–40 pupils; the floor is 5 precisely so every band is non-empty, §4.4).
- **"Course order" means the outline pre-order**, i.e. the list
  `courses.rollups.units_in_order(course, drafts="hide")` returns — the generator reuses that
  helper rather than re-deriving the sequence. ✅ Verified 2026-09-12 that `drafts="hide"` is
  exactly R2's `published=True` for units: `unit_is_visible` (`courses/rollups.py:70-83`)
  returns `drafts == "keep" or node.published`, then `keep-with-data`'s data test, then
  False — so under `hide` the predicate reduces to `node.published`. The generator
  nevertheless filters on `published=True` itself as well: it costs nothing, and R2 is the
  rule that keeps drafts out of the matrix. ⚠️ This is not pedantry: `ContentNode.order`
  is `OrderField(for_fields=["course", "parent"])` (`courses/models.py:210`), so sibling
  order is only **locally** monotonic and a flat `nodes.order_by("order")` interleaves unit 0
  of part 0 with unit 0 of part 5. `_walk_preorder`'s docstring
  (`courses/rollups.py:86-92`) says exactly this. Every ordered notion below — the frontier
  index, each pupil's slice, R5's per-unit RNG order, and the back-dating's "oldest first" —
  is defined on that pre-order list and is nonsense without it.
- **Class frontier.** `FRONTIER_FRACTION = 0.75`, and
  `frontier_index = floor(FRONTIER_FRACTION * len(published_units))` — the rounding is stated
  because floor, round and ceil differ by one on most lengths, and on §8's small fixture
  course that is a materially different class.
  ⚠️ **Why 0.75, honestly stated.** The obvious derivation — "the median pupil must reach
  two-thirds of the quiz columns" — does **not** discriminate 0.75 from 0.65, because a
  default matrix column is a *part*, not a quiz (§3.2): a column lights up as soon as one
  quiz under it counts, so at part granularity both fractions clear two-thirds. 0.75 is
  chosen on the plainer ground that it leaves fewer right-hand columns blank **when the rep
  expands a part into unit columns**, which is where an empty matrix would actually show.
  The median pupil (the `average` band covers the 20th–80th percentile) then sits at
  0.75 ± jitter of the published units, so roughly three-quarters of the expanded quiz
  columns carry a score for at least half the class. §8's acceptance criterion is stated
  against that expanded view for the same reason.
  ⚠️ It is likewise deliberately NOT "the third part": parts 0–9 of `mat-pp` are published,
  so a third-part frontier would leave ~7 of ~10 matrix columns empty for every pupil — the
  same mostly-blank matrix that sank the earlier seeder, only further right.
  `--frontier-part N` overrides the fraction with the last published unit of part N, where
  **"part N" means the Nth top-level child of the course by `order`, 0-indexed** ("part" is
  `mat-pp`'s editorial word, not a model). A part that does not exist, or that contains no
  published unit, is a named error — not a silent fallback to the fraction.
  ⚠️ **`frontier_part = 0` is legal and falsy.** The override is tested with `is not None`
  everywhere — service, command and the PR 3 form — because `if kit.frontier_part:`,
  `frontier_part or default`, or a form's `cleaned_data.get(...) or None` each silently turn
  `--frontier-part 0` (Zbiory liczbowe, a perfectly reasonable choice) into the 0.75
  fraction. T21 covers it. (The PR 3 form does not expose the override, so the rule binds the
  service and the command — and the form too, if it ever grows the field.)
- **Per-pupil depth** = `clamp(round(frontier_index × multiplier × (1 + jitter)), 0,
  len(published_units) - 1)`, where `jitter = rng.uniform(-0.08, 0.08)`. Every Bernoulli draw
  in this section — `P(correct)`, `P_LESSON_DONE`, `P_OPTIONAL_DONE`, `P_PARTIAL_GIVEN_WRONG`
  — is `rng.random() < p`, pinned for the same reason `uniform` and `randint` are: different
  methods consume the Mersenne stream differently, and R5 is a claim about the stream. The
  name draws are pinned the same way: **gender is `rng.random() < 0.5`** (feminine below),
  and the given name, the surname and each surname redraw are `rng.randrange(len(LIST))`
  indexes — not `rng.choice`, which consumes differently.
  With `--frontier-part N`, `frontier_index` is **that part's last published unit's position
  in the pre-order list** — an index into `units_in_order(course, drafts="hide")`, not a unit
  object, since the depth formula multiplies it.
- **Per pupil:** the pupil's slice is `published_units[: depth + 1]` — inclusive of the unit
  at `depth`, stated as a slice because "up to" and "at or before" leave the bound
  ambiguous and the last matrix column depends on it. Within that slice the pupil attempts
  every **quiz**, completes each **obligatory lesson** with probability
  `P_LESSON_DONE` = 1.00 / 0.95 / 0.80 by band, and completes each **optional lesson** with
  `P_OPTIONAL_DONE` = 0.50 / 0.30 / 0.15. **A failed draw writes no `UnitProgress` row at
  all** (not a row with `completed=False`): both render the same tick-less cell, but the row
  count is what T3 asserts on, and a future "started but not finished" indicator would read
  the two differently. "Obligatory lesson" means exactly
  `courses.rollups.is_obligatory_lesson(node)` (`courses/rollups.py:157-164`) — the same
  predicate the matrix denominator uses, reused rather than reimplemented, so the generator
  cannot desynchronise from the screen it generates for; an optional lesson is a `LESSON`
  unit that predicate rejects.
  ⚠️ Optional lessons count toward no matrix total (§3.2) but they **do** carry a tick in the
  per-pupil drill-down, which is §1's requirement 3 — leaving them untouched would show every
  optional lesson unticked for every pupil, a systematic pattern no class has, on one of the
  three screens the demo exists for. A unit that is neither a lesson nor a quiz is ignored
  silently.
  ⚠️ **That per-band probability is what stops the progress matrix being a perfect
  staircase.** Progress mode is the matrix's default — the first screen a rep sees — and it
  reads only `UnitProgress.completed` (§3.2), so a generator that completes *every* lesson
  behind the frontier renders every cell as 100%, one partial cell, then "—", with the bands
  invisible. A real class has holes behind it. The band `P(correct)` affects results mode
  only, so without `P_LESSON_DONE` nothing varies on the screen that opens first.
- **Per quiz:** open the submission exactly as the production close paths do —
  `QuizSubmission.objects.select_for_update().get_or_create(student=…, unit=…,
  defaults={"status": IN_PROGRESS})`, the shape `seed_demo_course._graded_submission` uses,
  with the enclosing `@transaction.atomic` supplying the lock `finalize_submission`'s
  docstring requires (`courses/quiz.py:232-240`). Then for each **top-level** question (R9)
  decide right / partly right / wrong from the band; build the answer via the type's builder
  (§3.1 table); validate it per R1b; write a `QuestionResponse`; then `finalize_submission`
  and a completed `UnitProgress`.
  **The `UnitProgress` field set is `student`, `unit`, `completed=True`** and nothing else
  (N3: `element_state` is never written), written through `save()` / `get_or_create` — ⚠️
  **never `bulk_create`.** `UnitProgress.save()` is what stamps `completed_at`
  (`courses/models.py:3047-3051`, whose comment declares the invariant "completed ⇒
  completed_at set, for EVERY write path"), so the obvious throughput optimisation on a
  thousands-of-rows write would leave `completed=True, completed_at=NULL` rows no production
  path can make — and T18 forbids only queryset `.update()`, so nothing else would catch it.
  T2a asserts `completed_at is not None`. The `(student, unit)` unique constraint makes
  `get_or_create` the natural call.
  **The `QuestionResponse` field set is exactly:** `fraction` and `earned_marks` per R1,
  `latest_answer` via `courses.quiz.answer_to_json` (`courses/quiz.py:174`),
  `attempt_count = 1`, `last_attempt_at = timezone.now()` at write time (the field has no auto
  behaviour, `courses/models.py:3126`; Q1 is resolved, so nothing rewrites it later) — and
  `locked` left False. Those are the **mutable** fields; the row is additionally identified by its
  `submission` and `element` FKs (the pair `finalize_submission`'s
  `responses.update(locked=True)` and `compute_scores`' `responses[el.pk]` lookup both rely
  on), and `max_marks` is **not** denormalised onto it — R1's `earned_marks(fraction,
  max_marks)` reads `max_marks` from the question object.
  `locked` is left False at write time; `finalize_submission` sets it via
  `responses.update(locked=True)` for the finalized rows, and the IN_PROGRESS rows stay
  unlocked, which is what production leaves them as.
  ⚠️ `last_attempt_at` is a plain nullable field with **no auto behaviour**
  (`courses/models.py:3126`): unless the generator writes it, it is NULL for every response
  and the back-dating pass has nothing to move.
  **No `Attempt` rows are created**, though `attempt_count = 1` — safe because no analytics
  or review surface reads `response.attempts` (§3.2; the review page reads `latest_answer`,
  `earned_marks`, `review_feedback`, `reviewed_at`). The plan must re-confirm that before
  relying on it. **Every pupil makes exactly one attempt per quiz**, whatever the unit's
  `max_attempts` allows — a fuller retry history is what `Attempt` rows would be for, and it
  buys the demo nothing.
  **Wrong-vs-partial split:** `P_PARTIAL_GIVEN_WRONG = 0.4` — of the answers that are not
  correct, 40% are partly right where the type supports it, so fill-blank and grid questions
  show the partial-credit marking that distinguishes libli. RNG cost: a partial-capable
  question consumes **two** draws (correct?, then partial?) **always — including when the
  first draw came out correct, in which case the second is drawn and discarded**; a
  non-partial one consumes **one**. Pinned because `P_PARTIAL_GIVEN_WRONG` is conditional on
  being wrong, which invites "draw the second only when wrong" — deterministic too, so T7
  cannot tell the two apart, and they diverge for every later question. That asymmetry is part of the fixed order below.
  **A quiz unit with no GRADEABLE top-level question gets no submission at all** — whether it
  has none at all (a quiz of prose and images, which T5(d) already builds) or only NOT_MARKED
  ones. Its `score` and `max_score` would both be 0.00, the cell could never show anything,
  and the 0/0 pair would still join the part column's sum (§3.2). Stated over the gradeable
  max, not over "all NOT_MARKED": the narrower wording let a question-free quiz slip through
  R3 (nothing unanswerable to find) into a finalized 0/0 — the exact harm the rule exists to
  prevent. Matches `quiz_gradeable_max`'s treatment of the same case, and such units are
  excluded from §8 criterion 1's denominator.
- **Unfinished work.** `IN_PROGRESS_PUPILS = 2` pupils get an IN_PROGRESS submission, so the
  review queue has entries and "Force submit" has a target. (Which two is the selection rule
  below — stated once, there.) **Responses are written for a strictly proper prefix of the unit's top-level
  questions** — at least one, at most n−1, the count drawn from the kit RNG (and part of the
  fixed order above) — with no `finalize_submission` and no `UnitProgress`. The submission is
  opened with the **identical** `select_for_update().get_or_create(student=…, unit=…,
  defaults={"status": IN_PROGRESS})` call as the finalized path and simply left there:
  `status=IN_PROGRESS`, `score`/`max_score` null, responses unlocked. ⚠️ The prefix is
  specified because this is the submission a rep will force-submit and resume: a fully
  answered one force-submits to an ordinary band-shaped score and shows the Student a
  complete form, while a partial one force-submits with missing AUTO responses (which
  `compute_scores` counts toward `max_score` but not `score`, §3.2) and shows a half-filled
  form on resume. The half-filled version is the realistic one — it is why the quiz is
  unfinished.
  ⚠️ **The candidate set** is the quizzes that pass R3 and R1b for this kit (§4.4 step 5.5's
  cache), **excluding** units whose questions are all NOT_MARKED (§4.5 gives those no
  submission at all) and units with **fewer than two** top-level answerable questions — a
  strictly proper prefix needs `n >= 2`, and `mat-pp` does contain one-question quizzes
  (§3.1), on which `randint(1, n-1)` would raise.
  **Which pupils get one:** the `IN_PROGRESS_PUPILS` shallowest pupils by depth **that have a
  candidate quiz ahead of them**, not "the first two in creation order" — sorted by
  `(depth, creation index)`, since bands share multipliers and jitter often rounds to the
  same integer, so "shallowest" alone is not a total order and different tie-breaks would
  give different kits from one seed. The target is the
  first candidate quiz strictly after the pupil's depth. ⚠️ The old chain was unreachable
  past its first clause: if no candidate lies after the pupil's depth then every candidate is
  inside the slice, where the pupil has already submitted all of them, so "the last one not
  already submitted" was empty by construction — and the one case that *did* reach it was an
  all-NOT_MARKED unit, which the same section forbids a submission. Picking shallow pupils
  makes a target exist by construction; the strong band, whose depth can clamp to the last
  unit, is exactly who had none.
  If no pupil qualifies at all, **warn** — a kit with no in-progress submission has an empty
  review queue.
  **The prefix is drawn over the unit's ANSWERABLE top-level questions** — the same `n` the
  candidate rule counts, never all top-level questions — and must contain at least one
  **gradeable** response. ⚠️ Otherwise a five-question unit with three NOT_MARKED or
  sentinel-answered questions can yield a prefix made entirely of questions that reach neither
  `score` nor `max_score`: the rep force-submits and gets a submission with nothing in it,
  the very state §4.5 forbids for an all-NOT_MARKED unit. If the chosen candidate cannot yield
  such a prefix, move to the next candidate, consuming one further prefix-length draw.
  (There is no "fails validation mid-write" fallback: step 5.5 makes validation a kit-level
  fact computed once, so a candidate cannot fail later. An earlier draft said otherwise, and
  taking it literally would reintroduce the 20× re-validation step 5.5 exists to remove.)
- **RNG order (fixed, part of R5), in full:**
  1. **per pupil in creation order: gender, then given name, then surname** (three draws each,
     plus **exactly one** further draw per rejected duplicate, since a rejection redraws the
     surname only — see below). ⚠️ These happen in §4.4 step 4, *before* everything
     below, and an earlier draft left them out of this list entirely, which made R5 either
     incomplete or false;
  2. the band partition and its single shuffle;
  3. then, per pupil in order: jitter, then per unit in pre-order, and within a unit either
     the lesson's completion draw (`P_LESSON_DONE` for an obligatory lesson,
     `P_OPTIONAL_DONE` for an optional one) or, for a quiz, per question in element order
     (one draw, or two for a partial-capable type; **a NOT_MARKED question, a sentinel
     question, and a question whose partial failed R1b all consume one fewer** — none at all
     for the first two, one for the third, which is thereafter treated as non-partial-capable).
     There is **no** back-dating offset draw: back-dating is gone (above).
     ⚠️ **A unit the kit-wide pass put in the R3-skipped set consumes NO draws**, and so do an
     all-NOT_MARKED quiz and a unit that is neither lesson nor quiz. Stated because the
     alternative — walking a skipped unit's questions and discarding the results — is equally
     consistent with a list that simply omits the case, and the two diverge for every unit
     after the first skip. T7 cannot adjudicate it: it compares two runs of the *same* code;
  4. finally, the IN_PROGRESS pass: **for the pupils chosen by the selection rule below,
     walked in `(depth, creation index)` order** — never "the first two in creation order",
     which is the rule that paragraph rejects — the prefix-length draw, then per answered
     question in element order on the same one-or-two-draw rule. Selection and iteration are
     each pinned once, and they agree. ⚠️ It runs **after** every pupil's finalized pass, as a
     separate sweep — an earlier version of this list omitted the
     pass entirely, so R5 was incomplete in the same way the name draws once were, and an
     implementation could run it before, inside or after the per-pupil loop and still claim
     conformance.

  **Names are distinct per kit**: a drawn `(first_name, last_name)` pair already used in this
  kit is rejected and **the surname alone is redrawn** — gender and given name are kept, so a
  rejection costs exactly **one** draw. Pinned because "a redraw" is not a number: re-rolling
  the surname, the pair, or all three diverge for every pupil after the first collision, and
  R5 pins the Bernoulli method and the `uniform`/`randint` choices for exactly this reason.
  ⚠️ **The pool assertion is on the list lengths, not on their product**:
  `len(F_GIVEN) >= 40 and len(F_SURNAMES) >= 40`, and the same for the masculine pair, checked
  by a test against the shipped lists. A product-based assertion (`>= MAX_PUPILS`) is
  satisfied by 40 given names × **1** surname, on which drawing the 40th distinct pair
  succeeds with probability 1/40 per attempt — the bounded retry's named error would then fire
  during ordinary provisioning rather than on a bad merge. The bound matters because gender is
  drawn per pupil, so a 40-pupil kit can need 40 distinct pairs from a single gender's lists.
  The retry is `NAME_RETRY_LIMIT = 50` surname redraws per pupil, then `NamePoolExhausted`
  (§4.4's hierarchy); `provision_kit` **also checks the list lengths at runtime**, since the
  shipped-lists assertion is a test and a service must not depend on a test having run. An implementation that reorders any of these draws produces a different class from
  the same seed: that reordering is T7's mutant.
- **Dates: there is no back-dating. Q1 is RESOLVED — nothing displays these timestamps.**
  Verified 2026-09-12 against the whole template tree and the export: **no** template renders
  `completed_at`, `submitted_at`, `last_attempt_at`, `created`, a `date:` filter or
  `timesince` — the matrix, the drill-down, the review queue and the review page render names,
  percentages and status pills only — and `courses/gradebook.py` / `courses/views_export.py`
  carry no timestamp column. The review queue orders by `unit__title, student__username`
  (`courses/review.py:245`), not by date. The one consumer found anywhere is the resume anchor
  (`courses/rollups.py:1115-1160`), which reads them **for the logged-in user** — and no fake
  pupil ever logs in (N8) while the rep's own Student starts with no activity by design.

  So every row keeps the timestamp its own `save()` stamps, and the generator writes no
  `.update()` at all. ⚠️ **This deletes a whole subsystem the spec carried for five rounds** —
  a `Case(When(...))` mapping per model, a per-pupil offset, a depth normalisation, a
  division-by-zero case at `d == 0`, a future-stamping trap for the IN_PROGRESS rows, a
  `created <= submitted_at` invariant, a kit-scoped filter on each update, and test T18 — none
  of which any human could ever have seen. It is also thousands of bind parameters removed
  from the one transaction PR 3 may run inside a web request (at the defaults the
  `UnitProgress` mapping alone approached ~26,000, against Postgres's 65,535 per-statement
  ceiling). The class simply reads as having been created today, which is true.

  ⚠️ Consequences to carry: R5's fixed order loses its back-dating offset draw (below);
  Risk 3's "the class ages" disappears, since nothing claims a date; and if a future surface
  ever *does* show these dates, back-dating returns as its own decision, not as a silent
  reinstatement.

**Builders registry, and `UNANSWERABLE_QUESTION_TYPES`** (named for what it holds — question
types, not unit types, which an earlier `SKIP_UNIT_TYPES` spelling got backwards while T6
enumerated `QuestionElement` subclasses against it)**.** A module-level map `{question model →
builder}`, where each builder returns `(correct_answer, wrong_answer,
partial_answer_or_None)`; beside it, `UNANSWERABLE_QUESTION_TYPES`, the explicit set of question types
the generator deliberately cannot answer. **`UNANSWERABLE_QUESTION_TYPES` starts empty** — §3.1's audit
found no unanswerable type in published `mat-pp` — and `extendedresponse` is its first
candidate if one is ever authored. A type in **neither** collection triggers R3's whole-unit
skip with a warning at runtime (never an exception), and fails T6 at test time. §8 T6 drives
the coverage test off the two collections; T1b tests the builders' behaviour — a registry
entry that returns a *wrong* "correct" answer is otherwise invisible (§8).

### 4.6 Operator surfaces

**Commands** (`demo` app, one `demo_access` command with subcommands):

| invocation | behaviour |
|---|---|
| `demo_access create --label "SP 12 Kraków" --course <slug> [--days 14] [--pupils 20] [--frontier-part N]` | provisions; prints kit id, both usernames, both generated passwords and the expiry **once** |
| `demo_access list [--all]` | active and `expired — pending purge` kits only, newest first; `--all` adds closed ones. ⚠️ The default filter is the point: `list` is Risk 5's early warning, and after a year of demos the one pending-purge row that matters would be buried among dozens of closed ones. Columns: id, label, **course slug, pupils**, created, expires, status (`active` / `expired — pending purge` / `closed (expired\|revoked)`). The course and pupil count are there because `list` is the ops-routine surface (§5.4): without them an operator reconciling "which kit is this?" once a second course exists has to go to the DB |
| `demo_access extend <id> --days N` | `expires_at = max(expires_at, now()) + N days` — the `max` matters for a kit that expired yesterday but has not been purged (§4.7), where extending from the stale date could leave it still expired. Refuses a closed kit; warns when the new `expires_at` is more than 60 days after `created_at` (the class's back-dated activity then looks abandoned) |
| `demo_access revoke <id>` | purges now, `closed_reason="revoked"`; refuses a closed kit |
| `demo_access purge [--dry-run]` | purges every kit matching `expires_at <= now() AND closed_at IS NULL`, `closed_reason="expired"`, **each kit in its own transaction**: a failure is logged and the loop continues to the next kit, with a non-zero exit at the end so the cron log shows it. One kit's failure must not leave the others' logins alive. `--dry-run` **prints the id and label of every kit it would purge** and writes nothing — a dry run that printed nothing could not serve as the "test it by hand first" step below |

`--course` takes a **slug** and is required; the command errors clearly when no course
matches. (A default would be a foot-gun the day a second course lands on libli.pl, and
import re-derives slugs from titles, so a slug is not a stable identifier —
[[import-course-reslugs-and-drops-subjects]].)

**The service layer behind the table** (D6: the commands and the tab call the same
functions): `provision_kit(...) -> ProvisionResult` (§4.4), `purge_kit(kit, *, reason)`
returning None, `extend_kit(kit, *, days) -> ExtendResult` (fields: `kit`, `new_expires_at`,
`long_lived` — the 60-day flag — so the command can print and the tab can render the same
message) and `revoke_kit(kit)` returning None like `purge_kit`.
**The vendor guard sits in the services, one answer each:** `provision_kit` and `extend_kit`
**guarded** (matching their subcommands), `revoke_kit` and `purge_kit` **exempt** (R8) — T13
asserts all four, not just the two it used to name.
**`extend_kit` enforces the same `1 <= days <= 90` bound as creation and the same closed-kit
refusal** — unbounded here, `--days 0` is a no-op that still writes, a negative value moves
`expires_at` into the past so the next purge deletes the kit the operator just tried to keep,
and `--days 3650` manufactures Risk 3's abandoned class. **It also returns the 60-day
warning** (as a flag on `ExtendResult`) rather than printing it: the warning is Risk 3's only
mitigation, and leaving it in the command would let PR 3's "Extend +14 days" button walk a kit
past 60 days silently — the one field where D6's shared service layer would have been broken.
The command prints it; the tab renders it as a form message. The `active / expired — pending purge / closed (…)` status string is
a **`DemoKit` property**, computed once on the model, so the command and the tab cannot drift.

⚠️ The purge predicate's `closed_at IS NULL` conjunct is what makes purge **idempotent**:
without it every historical kit is re-processed nightly for ever. It is tested directly
(T15), not just via `purge_kit`.

Passwords are `PASSWORD_LENGTH = 14` characters drawn with `secrets.choice` from a pinned
module constant: the ASCII letters and digits minus the ambiguous `O o 0 I l 1`, i.e. **56**
symbols (62 − 6), so ~81 bits. Stated exactly rather than as "~12 characters" because this credential
goes to a stranger and lives on prod for a fortnight. Passwords are **never stored** — only
Django's hash.

**Cron**, added to runbook §7 as one physical line in the **root** crontab (`sudo crontab
-e`), like the other two; test once by hand with `--dry-run` first:

```cron
45 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app /app/.venv/bin/python manage.py demo_access purge >> /var/log/libli-demo-purge.log 2>&1
```

03:45: clear of the 02:15 backup and the 03:30 `purge_notifications`. The host clock is UTC
(stated in runbook §7 for the backup line), so this is 03:45 UTC.

⚠️ **A silently failing purge leaves live logins on prod.** Three ways it can stop: the app
container being down (`docker compose … exec -T` then fails — including the ~24 s of every
deploy, [[wanted-continuous-deployment]], and indefinitely after a failed one); one kit
raising (hence the per-kit transactions above); and, if `purge` were vendor-gated, a lost
`LIBLI_VENDOR_INSTANCE` — which is precisely why R8 exempts it. The log above is the first
line of defence; the second is that `demo_access list` is part of the ops routine (§5.3) and
shows `expired — pending purge` rows. No login-time expiry check is added (§4.7), so this
residual exposure is accepted knowingly rather than by omission.

The log is append-only and root-owned; the runbook step says to confirm `logrotate` covers
`/var/log/libli-*.log` (the backup log at `/var/log/libli-backup.log` has the same shape)
and to add the pattern if it does not.

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
- ⚠️ **The tab runs `provision_kit` synchronously inside a web request.** At the defaults
  (20 pupils × 75% of ~430 published units, a `mark()` per question plus `compute_scores`
  and a locked `save()` per quiz) that is thousands of writes. **PR 2 must record the
  measured wall-clock of a default provision against the local `mat-pp` copy** (§8, "beyond
  the suite"); PR 3 then either keeps it comfortably inside the proxy/gunicorn request
  timeout or caps the tab's `--pupils` and says large kits go through the command. A
  timeout mid-provision is the bad case: the transaction may still commit while the
  operator never sees the credentials, leaving a kit only `revoke` can clear.
- create form (**course**, label, days, pupils) → POST → **redirect** to a result page that
  reads the credentials from a **one-shot session key, popped on read**. ⚠️ `course` is on the
  form because `provision_kit` requires it and §4.6 forbids a default: a `ModelChoiceField`
  over all courses ordered by title, with no initial selection, so the operator picks
  deliberately. The form enforces the same bounds as the service (§4.4), which it inherits by
  calling it rather than by re-listing them.
  ⚠️ **Where the passwords sit between the POST and the render.** Django's default session
  backend is DB-backed (no `SESSION_ENGINE` override anywhere in `config/settings`, checked
  2026-09-12), so a session-carried password is a cleartext row in `django_session` until the
  result page pops it — which is a real, if brief, contradiction of "never stored". The
  design accepts it, narrowly: the value is popped on first read, and the plan may instead
  carry it in the cache if that is cheap. What it must NOT do is widen the window by keeping
  it for a second render. T22 asserts the session no longer holds the password after the pop. Redirecting (rather than
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
anonymous visitor. T8 asserts that (a request with the purged user's session cookie is
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
   deployment. Check for **every** artefact it creates
   (`courses/management/commands/seed_demo_course.py`), not just the dangerous account:
   - `demo_admin` (Platform Admin) and `demo_teacher` (Course Admin) plus the four demo
     pupils, all on the repo-published password;
   - the `demo-course` **Course** and `demo-subject` **Subject** (`:70-77`), the
     "Demo Group" group (`:383`), the demo Collection, notes and tags (`:393-412`);
   - `Institution.name` overwritten to "Demo Academy" (`:481-484`);
   - the `WebhookEndpoint` pointing at `sis.demo.example` (`:463-476`) and its delivery row;
   - the saved SSO config (`:453-461`) and the `invitee@demo.example` invitation.

   ⚠️ **The course matters as much as the admin account.** §3.3's caveat — a rep Teacher
   reads every course — is justified there by "`mat-pp` is the only course on libli.pl". If
   this command has run, that premise is already false and the first rep sees an English
   "Demo Course" beside it.

   That yields **two separate checks**, which an earlier draft of this spec conflated into
   `Course.objects.count() == 1`:
   - **Seeder remediation** (one-off, before the first kit): no `demo-course` Course, no
     `demo-subject` Subject, no `demo_*` users, and the other artefacts above cleared.
   - **Rep visibility** (re-evaluated whenever a course is added, for ever): every course on
     the box is one a rep may see. The day a private course legitimately lands — which
     Risk 2 anticipates — this check fails, and the decision then is either to stop issuing
     kits or to narrow a rep's read access. Do not write it as a count: it would be
     permanently false and silently ignored.

   Remediation: take a DB snapshot first (the nightly backup exists, but a pre-deletion
   snapshot is the cheap insurance), then delete the demo users and course, restore the
   institution name, disable the webhook endpoint, and clear the SSO config. PR 1 ships this
   as a checklist in the runbook beside the guard.
1. Confirm `LIBLI_VENDOR_INSTANCE=true` is in `.env.production` **and visible inside the app
   container** (`config/settings/base.py:288` defaults it to False). Without it, `create`
   refuses — `purge` deliberately still runs (R8).
2. Fill `Institution.contact_email` on libli.pl if still blank (it ships blank).
3. Decide whether to switch on `Institution.demo_instance`. It adds the "demonstration site
   — do not enter real pupil data" notice to `/privacy/` and `/getting-started/`; it does
   **not** affect `/for-schools/`, which is exempt by design.
4. Install the purge cron line (checking `logrotate` covers its log, §4.6), and add
   `demo_access list` to the routine you already use to look at the box — it is what
   surfaces a purge that has silently stopped running.

## 6. Delivery — four PRs

**PR 1 — safety.** `seed_demo_course` refuses to run when `DEBUG=False` (a `CommandError`
naming the reason), plus runbook §7 rewritten: the instruction removed, and the §5.0
"has it already been run?" remediation checklist added. One test. No migration.

**PR 2 — core.** The `demo` app: model + migration, `provision_kit` / `purge_kit`, the
generator, the `demo_access` command, the vendor guard, and the cron line in the runbook.
Blocked on §5.0 and on Q2 (Q1 is resolved, §10).

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
- **N8** Logging in *as* a fake pupil. They carry `set_unusable_password()` and no rep can
  authenticate as one; the rep's own Student is the pupil view. This is a decision, not an
  oversight — generating 20 more stranger-known logins per kit on prod buys a view the rep
  already has.

## 8. Testing

Against a small fixture course in the test DB (`mat-pp` is not available there), each test
falsified against a named mutant.

⚠️ **Every provisioning test passes an explicit `seed`.** The service draws one from `secrets`
when omitted (§4.4), so any test asserting on generated content would otherwise run against a
fresh random class each time — T24's inequality most visibly, but every content assertion is
exposed.

⚠️ **The fixture must break two coincidences, or two named mutants are green on a broken
build.** In a freshly built fixture `Element.order` ascending *is* `pk` ascending and
`ContentNode` pre-order *is* pk order, so T7's "iterate questions in pk order" mutant and
T18's pre-order trap both produce identical output. The fixture therefore includes **at least
one quiz whose elements are re-ordered after creation** and **one course whose later part's
units were created first**. Same family as the project's recurring pk-coincidence flake
([[independent-pk-sequences-make-substring-assertions-flaky]]).

⚠️ **Every test that provisions runs under `override_settings(VENDOR_INSTANCE=True)`.**
`config/settings/test.py:37` pins the flag **False** (its own comment says vendor tests opt
back in this way), so the suite's default is the *guarded* state: without the override,
Stated as a **rule, not a list**: **every test except T13** provisions and therefore needs the
override, and T13 is the only one that runs at the test settings' default. (Two earlier
drafts enumerated ranges, and both went stale the moment a test was appended — first T14, then
T23–T25.)

- **T1 Derived score.** Every written response satisfies
  `fraction == to_stored_fraction(mark(latest_answer).fraction)`, and `earned_marks` equals
  `courses.scoring.earned_marks(fraction, max_marks)`. ⚠️ The `to_stored_fraction` wrapper is
  what makes this assertion true for partial credit (R1); comparing the raw float would fail
  on correct code. Include a partial-credit question in the fixture, or the wrapper is
  untested. Mutant: a fixed 0.5 score.
- **T1b Builders are honest** — the highest-value test here. It needs a fixture question of
  **every** registry type, including the awkward ones: `choicegrid` (with `GridColumn` rows
  and `row.correct_column_id`) and `matchpair`. Reuse the existing factories where they
  exist and write a shared fixture helper in the `demo` tests where they do not; T6 asserts
  no registry type lacks a fixture, so this cannot quietly shrink to the two easy types.
  For every entry, against a fixture question of that type:
  `mark(correct).fraction == 1`, `mark(wrong).fraction < 1`, and where a partial is returned
  `0 < mark(partial).fraction < 1`. Without this, T1 is tautological (R1 defines `fraction`
  as `mark()`'s output), and a builder returning a wrong "correct" answer yields a
  self-consistent, fully green, meaningless class. Mutant: swap one type's correct and wrong
  builders.
- **T2a The matrix is populated — progress mode.** Build it through the real `rollups` code
  and assert percentages, not "—". Mutant: drop the `UnitProgress` write (R4).
- **T2b The matrix is populated — results mode.** The same, against the cached-score path
  (§3.2 pins two independent readers). Mutant: skip `finalize_submission`, leaving
  `QuizSubmission.score` null — which T2a alone cannot see.
- **T2c Live-row validation (R1b), three outcomes.** A fixture question doctored into the
  states R1b names (a choice with no `is_correct`; a shortnumeric whose `value` will not
  parse) causes its **unit** to be skipped with a warning, and provisioning still completes.
  A row whose *partial* answer marks 1.0 falls back to the wrong answer and the unit is
  **kept**. A row for which no wrong answer can be built (a one-pair matchpair, an
  all-correct choice) is answered correctly, the unit is **kept**, and — when that question is
  AUTO — **every pupil scores full marks on it**, the accepted artefact R1b names rather than
  something to assert away. Mutant: validate the
  builder against the type rather than the row, and the pupil silently fails a question;
  second mutant: skip the unit on the partial failure, which blanks a column for a reason no
  measurement would trace.
- **T3 Real users untouched (R7).** A fixture course with a pre-existing enrolled student
  who is not in the kit gains **zero** new `UnitProgress`, `QuizSubmission` and
  `QuestionResponse` rows across a provision, **and their existing rows' timestamps are
  unchanged** — which is T18's mutant: a reinstated timestamp update with no
  `student__in=kit.users` filter rewrites a real pupil's `completed_at` while adding no rows,
  so a count-only assertion passes. Mutant: widen the generator's queryset from
  `kit.users` to all enrolled students.
- **T4 Drafts untouched.** A fixture with draft units gains no progress and no submissions,
  and the matrix gains no column. Mutant: drop the published filter (R2).
- **T5 Whole-unit skip, and its three counter-cases.** A unit with an unanswerable question,
  and separately a unit with a REVIEW question, each receive **no** submission and warn.
  Counter-cases: (a) a unit with a **NOT_MARKED** question of an unsupported type is still
  generated, that question alone skipped (R3's stated exception); (b) a unit whose top-level
  questions are **all** NOT_MARKED gets no submission (§4.5 — the cell could never show a
  score); (c) a unit with an unanswerable question **nested in a container** is generated
  normally, because R9 never looks at it; (d) a quiz holding **prose, image and callout
  elements** beside its questions is generated normally — R9's question filter, without which
  every real quiz would be skipped and the kit would roll back empty. Plus: a **one-question**
  quiz and an **all-NOT_MARKED** quiz are never chosen as IN_PROGRESS targets (the
  empty-prefix and no-gradeable-response boundaries, §4.5), and when the quiz just past a
  pupil's depth is R3-skipped the chain moves to the next candidate rather than writing an
  empty submission. Mutants: `continue` past an unanswerable top-level AUTO question instead
  of skipping its unit; drop the `QuestionElement` filter from R9's enumeration.
- **T6 Type coverage, derived not pinned.** Enumerate `QuestionElement` subclasses; assert
  each is either in the builders registry or in `UNANSWERABLE_QUESTION_TYPES`, **and that every registry
  type has a fixture in T1b** — so a type cannot pass quietly by having no fixture. A new
  question type fails until someone classifies it. **No `len(...) == N` pin**
  ([[guards-that-assert-the-adjacent-thing]] #9). Mutant: add a question type to neither
  collection; the test must go red.
- **T7 Determinism.** Two runs with the same seed produce identical responses, progress and
  band assignment. Mutant: swap the jitter draw ahead of the band shuffle, or iterate a
  unit's questions in pk order rather than element order — the class must change. (The
  earlier wording, "invariant under a reordering of the loops", asserted the opposite of
  §4.5 and was impossible to satisfy.)
- **T8 Purge leaves nothing.** After a rep has created a collection and force-submitted,
  `purge_kit` removes every kit user, the group (via `grouping.services.delete_group`) and
  all their rows; the Default cohort's member count returns to its pre-kit value (§3.7) —
  **and, before the purge, the live kit's Teacher holds no `CohortMembership` at all** (the
  `is_staff`-at-creation rule, §4.4 step 2; the post-purge count alone passes either way);
  the
  `DemoKit` row survives with nulled FKs, `closed_at` and `closed_reason` set; and a request
  carrying the purged Teacher's session cookie is anonymous, not a 500 (§4.7). Mutant
  (cheap): purge the group but not the users, or the users without `delete_group` — each
  leaves a named survivor. The PROTECT mutant of §3.5 needs a model plus migration edit and
  is an optional one-off; do not make it the routine falsification
  ([[reverting-a-mutant-with-git-checkout-destroys-your-work]]).
- **T9 Isolation.** Kit A's Teacher sees A's pupils in analytics and none of B's, and cannot
  reach a draft unit. ⚠️ Kit B must be **fully provisioned with data**, or the test passes
  because B is empty rather than because scoping works. Mutant: add kit A's Teacher to kit
  B's `group.teachers`; B's pupils must then appear and the test go red.
- **T10 Vendor gating of the tab.** With the flag off: the tab link is absent and `?tab=demo`
  falls back to the branding panel with 200 (**not** 404 — `_active_tab`'s fallback), while
  each action view returns 404. With the flag on: Platform Admin only; non-POST → 405.
  Mutant: gate the action views on the tab list instead of their own flag check — the 404
  assertions must go red.
- **T11 Credentials are shown once.** The password appears in the first render of the result
  page, is absent from the session afterwards, and is absent from a second GET of that page
  and from the list page. Mutant: render on POST without popping the session key.
- **T12 Silence (R6).** Provisioning leaves `mail.outbox` empty, enqueues no
  `WebhookDelivery`, and creates no `Notification` row for any user outside `kit.users`.
  ⚠️ **The fixture must carry an ACTIVE `WebhookEndpoint`** subscribed to the events enrolment
  and submission emit, plus a positive control (a non-kit action that *does* enqueue a
  delivery). Without an endpoint no code path can enqueue anything, so that half of the test
  is green on a build that fires a webhook per enrolment — the minimal edit keeping it green
  is "do nothing" ([[guards-that-assert-the-adjacent-thing]]). Mutant: emit a notification
  for the institution's admins on kit creation.
- **T13 Vendor guard, derived and split.** At the test settings' default
  (`VENDOR_INSTANCE=False`, no override): `provision_kit` raises `ImproperlyConfigured` with
  no rows written; **every** subcommand enumerated from the parser — never listed by hand,
  never pinned by count — is asserted to be in exactly one of two sets, **guarded =
  {`create`, `extend`}** (raising `CommandError`) or **exempt = {`purge`, `revoke`, `list`}**
  (running normally); `revoke` on a live kit closes it even with the flag off; and
  `purge_kit` itself is callable, since R8's exemption is a service-level claim and a
  parser-only test would miss a guard added one layer down. ⚠️ A guard on
  `create` alone would keep a hand-written version of this green while `purge` refused to run
  on prod ([[guards-that-assert-the-adjacent-thing]]).
- **T14 `/admin/` exposes nothing.** A kit Teacher's `/admin/` index lists zero models
  (§3.3). Mutant: register `Group` in `grouping/admin.py`.
- **T15 Purge selection.** A kit expiring tomorrow survives `demo_access purge`; one that
  expired yesterday does not; a second run is a no-op; `--dry-run` writes nothing **and
  prints the ids it would purge**. ⚠️ The idempotence case must contain an **already-closed**
  kit whose `expires_at` is in the past, or it passes because the second run found nothing
  rather than because the predicate filtered it. A kit whose **group was deleted by hand**
  still closes cleanly (§4.2's half-dismantled case), as does one whose users are already
  gone. Mutants: drop the `closed_at IS NULL` conjunct; call `delete_group` unconditionally,
  so the null-group kit raises and never closes; make one kit's purge raise and assert the
  others still close and the exit code is non-zero.
- **T15b Bounds and extend arithmetic.** `provision_kit` (not just the command) rejects
  `pupils` outside 5–40 and `days` outside 1–90 with the named error, and so does
  `extend_kit`; `extend_kit` on a kit that expired yesterday moves `expires_at` to
  `now() + N days`, not into the past, and refuses a closed kit. Mutant: validate in the
  command only — the service-level call must then go through, which is what PR 3's form and
  its Extend button would hit.
- **T16 Enrolment and deletion go through the services.** Provisioning calls
  `add_students_to_group` (not `Enrollment.objects.create`) and purge calls
  `delete_group` — asserted on **behaviour** (the `Enrollment` rows and `added_by` the
  service writes, and the post-delete recompute) rather than on a source grep, which a
  refactor defeats silently. It also asserts **`can_review_course(teacher, course)` is True**
  after provisioning — the teacher M2M add is a bare write (§4.4 step 2) and is the single
  thing that makes the whole kit visible to the rep. Mutant: swap in a direct
  `Enrollment.objects.create` and a bare `group.delete()`; second mutant: skip the
  `group.teachers` add.
- **T17 Username disambiguation.** A second kit for the same label provisions successfully
  with distinct usernames; a candidate name held by an **unrelated** account — including one
  whose address exists only as an allauth `EmailAddress` row — **bumps the integer and
  provisioning still succeeds** (§4.2's single rule); the named error appears only when the
  2..999 search is exhausted. Mutant: scan `User.email` only, so the `EmailAddress`-only
  holder is missed and `ensure_verified_primary_email` raises mid-transaction instead.
- **T18 No timestamp rewriting.** The generator issues **no** queryset `.update()` against
  `UnitProgress`, `QuizSubmission` or `QuestionResponse` — Q1 is resolved and back-dating is
  gone (§4.5). Assert it where it bites: a pre-existing non-kit student's `completed_at` is
  byte-identical after a provision. Mutant: reinstate a bare `Case(When(...))` update with no
  `student__in=kit.users` filter; the row count is unchanged, so only this assertion goes red.
- **T19 `seed_demo_course` refuses** under `DEBUG=False`. Mutant: guard on
  `settings.DEBUG is None` or on an env var the test does not set.
- **T20 The rep's Student can actually do the demo** — the only test of §1's requirement 2.
  The kit's Student is non-staff, holds a `GroupMembership` of the kit group with the
  recomputed `Enrollment`, and can open a published quiz, submit it and read a stored score.
  ⚠️ Every other test targets the generator or the gating; a kit whose Student came out
  staff (or unenrolled) passes all of them and then silently gets the read-only previewer
  instead of a real submission (`courses/views.py:1455,1696-1697`). It also asserts that a
  **generated pupil's** matrix row shows a human name — not only the rep's own row, which
  carries a `display_name` even on the build where the pupils' names never render (§4.4).
  Mutants: create the Student with role Teacher; give pupils `first_name`/`last_name` without
  a `display_name`, on which the matrix falls back to `…-p01`.
- **T21 Frontier override.** `--frontier-part 0` produces the part-0 frontier, **not** the
  0.75 fraction (the falsy-zero trap, §4.5); a part index out of range, or one with no
  published unit, raises the named error before any row is written. Mutant: `if
  kit.frontier_part:` in place of `is not None`.
- **T22 Preconditions, the credential path and the `repr`.** The two password fields are
  absent from `repr(ProvisionResult(...))` (the `field(repr=False)` mechanism, §4.4). A course with **no published units** raises
  the named error before any row is written (the inverted-`clamp` case, §4.4); a course whose
  quizzes all sit past every pupil's depth fails the **post-generation** invariant (no
  finalized submission with a score) and rolls back, rather than provisioning live
  credentials with an empty results mode; `provision_kit` returns a `ProvisionResult` whose
  two passwords authenticate their users, **neither appears in any persisted `DemoKit`
  field**, and after PR 3's result page is read once the password is gone from the session.
  Mutants: return the `DemoKit` row alone (the command and tab then have nothing to show);
  check the surviving-quiz set instead of the written rows (the past-the-depth case then
  provisions happily).
- **T23 The drill-down is populated.** Build one pupil's drill-down through the real
  `rollups` code and assert an **obligatory**-lesson tick, an **optional**-lesson tick and a
  quiz status pill. ⚠️ Without this, deleting the whole `P_OPTIONAL_DONE` pass keeps every
  other test green — optional lessons count toward no matrix total by construction — and the
  only thing that would catch it is the manual browser pass. Mutant: drop the optional-lesson
  pass.
- **T24 The bands actually differ.** On one provisioned kit — **an explicit `seed`, and a
  fixture big enough that each band holds several pupils over a double-figure count of
  obligatory lessons and gradeable questions** — the strong band's mean completed
  obligatory-lesson count **and** mean `score / max_score` both strictly exceed the struggling
  band's. ⚠️ Both conditions are load-bearing: at `pupils = 5` on a tiny course each edge band
  is **one** pupil over a handful of questions at P=0.90 vs P=0.35, and a strict inequality
  between two single-pupil means is inside flake range — more so because a sentinel-answered
  question (R1b) is aced by every band and compresses the gap. ⚠️ T7 pins determinism, not differentiation: flattening all three bands
  to one set of probabilities is perfectly deterministic, populates both matrix modes, and
  passes T1, T2a, T2b and T7 — leaving the demo's whole visual premise defended only by a
  human eyeballing "gaps, not a staircase". Mutant: flatten the band constants.
- **T25 The review queue is non-empty.** Build it through the real
  `courses/review.py::pending_reviews_for` **as the kit Teacher** and assert the in-progress
  list is non-empty and contains only kit pupils. ⚠️ §1's fourth requirement has no other
  test: T5 asserts only which quizzes are *never* chosen. That function filters on
  `scoping.reviewable_students` and on `quiz_units_in_order`, so an IN_PROGRESS submission
  written for a pupil outside the group, or on a unit the drafts filter drops, leaves the
  queue silently empty while every other test passes. Mutants: write the IN_PROGRESS
  submissions with `status=SUBMITTED`; write them for a non-member pupil.

**Beyond the suite:** provision a kit against the local `mat-pp` copy and read the matrix,
the drill-down, the review queue and the pupil view in a browser, light and dark;
**record the wall-clock of that provision** (PR 3's tab depends on it, §4.6).
**Acceptance criteria for the frontier default**, both measured **with every part expanded
to unit columns** (an unexpanded part column lights up as soon as one quiz under it counts,
§3.2, so it cannot discriminate):
1. *results mode* — at least two-thirds of **the course's published quiz units, minus those
   R3-skipped and those whose questions are all NOT_MARKED**, hold a score for at least half
   **the class, meaning the generated pupils only** — the matrix has `pupils + 1` rows and the
   extra one, the rep's Student, is deliberately blank at measurement time, so measuring
   "half" over 21 rows instead of 20 would shift this, the sole quantitative gate on
   `FRONTIER_FRACTION`.
   ⚠️ **The denominator must not move with `FRONTIER_FRACTION` either, or the criterion cannot
   gate it.** Two earlier denominators did: "units the generator attempted" and "units carrying a
   finalized submission" are both prefixes ending at the *deepest* pupil's depth
   (≈ `F × 1.15 × 1.08 × len`), while the numerator ends at the *median* pupil's
   (≈ `F × len`). Their ratio is ≈ `1/1.24 ≈ 0.8` for **every** F up to ~0.8 — the same
   verdict at 0.75, 0.65 and 0.10. Measured against the course's whole published quiz set the
   ratio is instead ≈ F, so two-thirds genuinely fails at 0.6 and passes at 0.75. The two
   exclusions are the units that can never hold a score for anyone, and skip warnings are
   recorded beside the number so a low reading can be attributed to builder coverage rather
   than to the fraction. Read off the exported matrix, not from generator logs;
2. *progress mode* — the class shows **gaps behind the frontier**, not a clean staircase
   (the `P_LESSON_DONE` check, §4.5). This is the screen that opens first.

A green suite cannot say whether the class looks believable
([[verify-ui-with-screenshots]], [[reviews-that-execute-beat-reviews-that-read]]).

## 9. Risks

1. **Prod writes, and how long they take.** Each kit writes a few thousand rows to the live
   DB. `provision_kit` runs in one transaction — **inserts only**, now that Q1's resolution
   removed the back-dating updates; purge is exercised on the local copy before the first real
   kit. The measured
   duration from §8 is what decides whether PR 3's tab can call it synchronously (§4.6).
2. **Teacher reads every course.** §3.3. A standing caveat for the day a second, private
   course lands on libli.pl.
3. **~~The class ages.~~ Retired by Q1's resolution** — nothing carries or displays a date, so
   an extended kit's class cannot read as abandoned. `extend_kit`'s 60-day warning is kept
   anyway: a kit alive for two months is worth a second look regardless of how its data reads.
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

- ~~**Q1**~~ **RESOLVED 2026-09-12 — no surface displays those timestamps, so there is no
  back-dating.** Checked across the whole template tree, `courses/gradebook.py` and
  `courses/views_export.py`; the review queue sorts by title and username
  (`courses/review.py:245`); the only reader anywhere is the resume anchor
  (`courses/rollups.py:1115-1160`), and it reads for the **logged-in** user, which no fake
  pupil ever is (N8). §4.5, R5's draw order, T18 and Risk 3 are updated accordingly. This no
  longer blocks PR 2.
- **Q2** (blocks PR 2) Confirm the default pupil count (20), kit lifetime (14 days) and
  `FRONTIER_FRACTION` (0.75) with Krzysztof.
- **Q3** (blocks PR 4) `/for-schools/` claims analytics drill down "to one pupil and one
  question", but no teacher-facing per-question view exists for AUTO answers (§3.2). Either
  the copy is corrected or the claim is met — decide before the demo is shown to anyone.
- **Q3b** ⚠️ **If Q3 is answered by BUILDING the per-question drill-down rather than by
  correcting the copy**, the generator needs more than one wrong answer per question: step
  5.5's kit-wide cache gives all twenty pupils the byte-identical wrong answer, which is
  invisible today (§3.2: no teacher-facing per-question view exists for AUTO answers) and
  becomes "twenty pupils all chose option C" the day that view lands. That changes the cache
  shape and R5's draw order, so it is a spec change, not an implementation detail.
- **Q4** Should the demo show teacher **marking** at all? It needs a REVIEW question, which
  published `mat-pp` does not have (§3.4). Options: leave it out, or give the demo a tiny
  separate course carrying one REVIEW question.
