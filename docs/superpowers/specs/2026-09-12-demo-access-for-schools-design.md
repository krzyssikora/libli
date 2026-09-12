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
`provision_kit()` raises `ImproperlyConfigured`, and the `create`, `extend` and `revoke`
subcommands raise `CommandError`, when `settings.VENDOR_INSTANCE` is False. A school's box
therefore carries an empty table and a command that refuses to create anything — never a
path to fake pupils beside real ones. **`purge`, `purge_kit` and `list` are exempt on
purpose**; the reasoning is in R8, and it is the one asymmetry in this design that is
load-bearing rather than tidy. Test T13.

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
`<slug>-2-nauczyciel` … for the next, where the disambiguating integer is the lowest that
makes **every** username in the kit free. If any candidate username or email is taken by a
user the kit did not create, provisioning fails with a named error rather than reusing it.

**Length and degenerate labels** (`AbstractUser.username` is `max_length=150`,
`Group.name` is 200, `grouping/models.py:84`):

- `slug = slugify(label, allow_unicode=False)[:SLUG_MAX]` with `SLUG_MAX = 100`, which
  leaves room for the longest suffix the scheme can produce (`-NNN-nauczyciel`, `-NNN-pNN`,
  budgeted against the widest disambiguating integer below, not a two-digit one).
- The disambiguating integer is searched over **2..999**; past that, the named collision
  error, so the search always terminates.
- A label that slugifies to `""` — entirely non-ASCII input such as `"Łódź ###"` can —
  falls back to the literal `demo`; the disambiguating integer then separates schools.
- Pupil numbering is zero-padded to the width of `--pupils` (`p01…p20` at the default), so
  it stays consistent and cannot collide within a kit; `--pupils` is capped at 40 (§4.6).
- The group name truncates the label to 150 characters before the ` (#<pk>)` suffix.

**Closing policy.** `purge_kit` (whether from `revoke` or the nightly `purge`) is
`@transaction.atomic` **per kit** — a partial failure that deleted the users, left the group
and never set `closed_at` would be re-purged nightly for ever and keep reading as "pending"
in `list`. It deletes **the users first, then the group** via
`grouping.services.delete_group`, so that service's post-delete enrolment recompute
(`grouping/services.py:249-254`) finds no surviving members; then it **retains the `DemoKit`
row** with `closed_at` set,
`closed_reason` recording which path closed it, and the user/group FKs nulled. The row is a
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
- **R2 Published only.** Only units with `published=True` receive progress or submissions —
  otherwise a draft appears in the matrix (§3.2).
- **R3 Whole-unit skip.** If a unit contains any question the builders registry cannot
  answer (including one in neither the registry nor `SKIP_UNIT_TYPES`), any question that
  fails R1b, **or any REVIEW-mode question**, the unit is skipped entirely and a warning
  naming the unit and the reason is printed. Never skip a single question: a partial unit
  still counts, and a missing response reads exactly like an unreviewed REVIEW question.
  **The one exception is a NOT_MARKED question**, which `compute_scores` excludes from both
  `score` and `max_score` (`courses/quiz.py:204-228`): it is answered like an AUTO question
  when its type has a builder, and when it does not, it is skipped **without** skipping the
  unit — it can contribute to neither total, so a missing response cannot distort anything.
  That exception is stated here because it is the only place R3's "never skip one question"
  does not hold.
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
- **R8 Vendor only, on the creating half.** `provision_kit` (§4.4, §4.5) and the `create`,
  `extend` and `revoke` subcommands refuse when `settings.VENDOR_INSTANCE` is False (§4.1).
  ⚠️ **`purge_kit`, `purge` and `list` are deliberately NOT guarded.** Guarding the cleanup
  path is the one way the guard itself could leave stranger-known logins alive on prod: the
  flag is an env var (`LIBLI_VENDOR_INSTANCE`, `config/settings/base.py:288`), and a compose
  change that loses it would turn the nightly purge into a non-zero exit in a log nobody
  greps (Risk 5). On a school's box the table is empty, so purge is a no-op there anyway.
  T13 asserts this split at the **service** level as well as the parser.
- **R9 Top-level questions only.** The generator enumerates exactly
  `unit.elements.filter(parent__isnull=True)`, because that is the set `compute_scores` and
  the review-pending gate use (§3.2). A nested question is neither answered nor a cause of an
  R3 skip — answering one would write responses the score path ignores. This is a rule, not
  an observation about today's `mat-pp`: §3.1's audit found all 260 questions top-level, but
  the reason it is *safe* is the `parent__isnull=True` filter, which holds whatever the
  content does next.

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

**Argument bounds, enforced in `provision_kit` itself** — not only in the command, so the
PR 3 form inherits them — each raising a named error: `2 <= pupils <= 40` (0 pupils has no
band split and no analytics; 500 would write six figures of rows in one web request) and
`1 <= days <= 90` (0 or negative creates a kit the next purge deletes).

Order of work, inside one transaction:

0. **The `DemoKit` row** — label, slug, course, `expires_at`, `pupil_count`,
   `frontier_part`, `created_by` and the resolved `seed`. It is created **first** because
   the group name embeds its pk and every later step writes back to its FKs.
   ⚠️ **What the stored `seed` is for.** There is no `--seed` flag and no regenerate
   subcommand — regenerating a live kit in place is a non-goal (it would rewrite a class the
   rep may be looking at). R5's determinism exists so the **suite** can pin a class (T7) and
   so a puzzling kit can be reproduced locally from its stored seed for diagnosis. Say that
   rather than implying reproducibility is an operator feature.
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
1. **The group** — `"Klasa demo — <label> (#<kit pk>)"` in `course`, then written to
   `kit.group`. Created before the users: the enrolment service takes a group. The kit pk is
   in the name so two kits for the same school are distinguishable in the Teacher's pickers.
2. **Teacher login** — role Teacher (`set_user_role`), `language="pl"`,
   `display_name="Nauczyciel demo"`, generated password, verified primary email
   `<username>@demo.invalid` via `ensure_verified_primary_email` (needed:
   `ACCOUNT_EMAIL_VERIFICATION="mandatory"`, `config/settings/base.py:105`). Added to
   `group.teachers`. Login accepts username or email
   (`ACCOUNT_LOGIN_METHODS = {"username", "email"}`, `base.py:99`).
3. **Student login** — role Student, not staff, `display_name="Uczeń demo"`, same
   email/password treatment.
4. **`pupils` fake pupils** — `first_name` and `last_name` drawn from a checked-in list of
   Polish given names and surnames shipped in the `demo` app (a library or generator would
   make T7 dependent on an upgrade), `@demo.invalid` emails, `set_unusable_password()`,
   role Student.
   ⚠️ **Every kit user gets a human name**, because `User.__str__`/full-name logic prefers
   `display_name` then `first_name`/`last_name` (`accounts/models.py:26,42,55-70`) and the
   matrix sorts with `polish_sort_key`. Without them the rep's own row would read
   `sp-12-krakow-uczen` among "Anna Kowalska" — on the screen §4.4 calls the demo's best
   moment. **Pupils get `first_name` + `last_name` and no `display_name`** (the natural shape
   for a class list, and it lets the sort work on the surname); the two logins get a
   `display_name`, which takes precedence. Since `display_name` wins wherever it is set, both
   spellings render correctly on any surface; T20 pins that the rep's own row shows a human
   name rather than a username.
   Every kit user is created with `language="pl"` — the pupil login walks a Polish lesson in
   front of the rep, so the default locale must not decide it.
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

**Constants** (module-level named values in the `demo` app, not literals inline — T7 depends
on them being fixed):

| band | share | P(correct) | depth multiplier |
|------|-------|-----------|------------------|
| strong | 0.20 | 0.90 | 1.15 |
| average | 0.60 | 0.65 | 1.00 |
| struggling | 0.20 | 0.35 | 0.70 |

- **Band assignment is a fixed partition, not a weighted draw per pupil.** `strong =
  floor(0.20 × pupils)`, `struggling = floor(0.20 × pupils)`, and the remainder is
  `average`; the resulting list is then shuffled once with the kit RNG. A per-pupil weighted
  draw was rejected: a 20-pupil class could legitimately come out with no strugglers, which
  makes both the demo and the §8 acceptance criterion non-deterministic in a way T7 cannot
  express. The floor rule keeps the middle band absorbing the remainder at every size the
  bounds allow (2–40 pupils).
- **"Course order" means the outline pre-order**, i.e. the list
  `courses.rollups.units_in_order(course, drafts="hide")` returns — the generator reuses that
  helper rather than re-deriving the sequence. ⚠️ This is not pedantry: `ContentNode.order`
  is `OrderField(for_fields=["course", "parent"])` (`courses/models.py:210`), so sibling
  order is only **locally** monotonic and a flat `nodes.order_by("order")` interleaves unit 0
  of part 0 with unit 0 of part 5. `_walk_preorder`'s docstring
  (`courses/rollups.py:86-92`) says exactly this. Every ordered notion below — the frontier
  index, each pupil's slice, R5's per-unit RNG order, and the back-dating's "oldest first" —
  is defined on that pre-order list and is nonsense without it.
- **Class frontier.** `FRONTIER_FRACTION = 0.75`: the frontier is the index at 75% of that
  published-unit list.
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
  fraction. T21 covers it.
- **Per-pupil depth** = `clamp(round(frontier_index × multiplier × (1 + jitter)), 0,
  len(published_units) - 1)`, where `jitter = rng.uniform(-0.08, 0.08)`.
- **Per pupil:** the pupil's slice is `published_units[: depth + 1]` — inclusive of the unit
  at `depth`, stated as a slice because "up to" and "at or before" leave the bound
  ambiguous and the last matrix column depends on it. Within that slice the pupil attempts
  every **quiz**, and completes each **obligatory lesson** with probability
  `P_LESSON_DONE` = 1.00 / 0.95 / 0.80 by band.
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
  **The `QuestionResponse` field set is exactly:** `fraction` and `earned_marks` per R1,
  `latest_answer` via `answer_to_json`, `attempt_count = 1`, `last_attempt_at` set to the
  same timestamp the back-dating pass will use for that unit, and `locked` left False —
  `finalize_submission` sets it via `responses.update(locked=True)` for the finalized rows,
  and the IN_PROGRESS rows stay unlocked, which is what production leaves them as.
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
  question consumes **two** draws (correct?, then partial?), a non-partial one consumes
  **one**. That asymmetry is part of the fixed order below.
  **A unit whose top-level questions are all NOT_MARKED gets no submission at all** — its
  `score` and `max_score` would both be 0.00 and the cell could never show anything, while
  the 0/0 pair still joins the part column's sum (§3.2). Matches `quiz_gradeable_max`'s
  treatment of a unit with no gradeable question.
- **Unfinished work.** `IN_PROGRESS_PUPILS = 2`: the first two pupils in generation order
  get an IN_PROGRESS submission (responses written, no `finalize_submission`, no
  `UnitProgress`), so the review queue has entries and "Force submit" has a target.
  ⚠️ **The candidate set is the quizzes that pass R3 and R1b for this kit** — the same
  filtered set the finalized pass uses, not "published quizzes". Otherwise this rule is the
  one place that can select a unit the generator is forbidden to answer, and it would write
  an empty submission (no responses to force-submit) or raise, contradicting R1b's
  "a skip, never an exception". Within that set the target is **the first quiz strictly after
  the pupil's depth**; failing that, the last such quiz the pupil has not already submitted;
  failing that, skip the pupil and **warn** — a kit with fewer than `IN_PROGRESS_PUPILS`
  in-progress submissions has an empty review queue, one of the two screens the demo exists
  to show. A candidate found to fail validation mid-write is skipped and the chain continues.
- **RNG order (fixed, part of R5):** the band partition and its single shuffle → then, per
  pupil in order: jitter, then per unit in pre-order, and within a unit either the lesson's
  `P_LESSON_DONE` draw or, for a quiz, per question in element order (one draw, or two for a
  partial-capable type). An implementation that reorders these draws produces a different
  class from the same seed — that reordering is T7's mutant.
- **Dates.** After the writes, the timestamps are back-dated across `BACKDATE_DAYS = 42`
  before `created_at`, each unit's timestamp derived from its index in the ordered
  published-unit list so the class reads oldest-first.
  ⚠️ **One `.update()` per model is not enough, and the spec used to say it was.** A queryset
  `.update(completed_at=X)` writes the *same* scalar to every matched row, which cannot
  produce per-unit ordering. The mechanism is one `.update()` per model carrying a
  `Case(When(unit_id=…, then=Value(ts)), …)` mapping built from that list; a queryset update
  is still required (rather than `save()`) because these fields are stamped in `save()`.
  **Covered:** `UnitProgress.completed_at`; `QuizSubmission.submitted_at` **and `created`**
  for finalized rows — back-dating `submitted_at` alone would leave every submission
  claiming it was submitted 42 days before it was created (`created` is `auto_now_add`,
  `courses/models.py:3091`), a row no production path can make; the IN_PROGRESS submissions'
  `created`; and every response's `last_attempt_at`.
  **Knowingly left at `now()`:** `QuizSubmission.updated` (`auto_now`, invisible on every
  demo screen), `GroupMembership.added_at` and the group's own creation — the roster reads
  as set up today, which is true.
  ⚠️ Blocked on Q1: if no surface displays these dates, drop the back-dating rather than
  ship untestable decoration.

**Builders registry, and `SKIP_UNIT_TYPES`.** A module-level map `{question model →
builder}`, where each builder returns `(correct_answer, wrong_answer,
partial_answer_or_None)`; beside it, `SKIP_UNIT_TYPES`, the explicit set of question types
the generator deliberately cannot answer. **`SKIP_UNIT_TYPES` starts empty** — §3.1's audit
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
| `demo_access list` | id, label, created, expires, status (`active` / `expired — pending purge` / `closed (expired\|revoked)`) |
| `demo_access extend <id> --days N` | `expires_at = max(expires_at, now()) + N days` — the `max` matters for a kit that expired yesterday but has not been purged (§4.7), where extending from the stale date could leave it still expired. Refuses a closed kit; warns when the new `expires_at` is more than 60 days after `created_at` (the class's back-dated activity then looks abandoned) |
| `demo_access revoke <id>` | purges now, `closed_reason="revoked"`; refuses a closed kit |
| `demo_access purge [--dry-run]` | purges every kit matching `expires_at <= now() AND closed_at IS NULL`, `closed_reason="expired"`, **each kit in its own transaction**: a failure is logged and the loop continues to the next kit, with a non-zero exit at the end so the cron log shows it. One kit's failure must not leave the others' logins alive. `--dry-run` **prints the id and label of every kit it would purge** and writes nothing — a dry run that printed nothing could not serve as the "test it by hand first" step below |

`--course` takes a **slug** and is required; the command errors clearly when no course
matches. (A default would be a foot-gun the day a second course lands on libli.pl, and
import re-derives slugs from titles, so a slug is not a stable identifier —
[[import-course-reslugs-and-drops-subjects]].)

⚠️ The purge predicate's `closed_at IS NULL` conjunct is what makes purge **idempotent**:
without it every historical kit is re-processed nightly for ever. It is tested directly
(T15), not just via `purge_kit`.

Passwords are `PASSWORD_LENGTH = 14` characters drawn with `secrets.choice` from a pinned
module constant: the ASCII letters and digits minus the ambiguous `O o 0 I l 1`, i.e. 55
symbols, so ~81 bits. Stated exactly rather than as "~12 characters" because this credential
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
falsified against a named mutant.

⚠️ **Every test that provisions runs under `override_settings(VENDOR_INSTANCE=True)`.**
`config/settings/test.py:37` pins the flag **False** (its own comment says vendor tests opt
back in this way), so the suite's default is the *guarded* state: without the override,
T1–T12 and T15–T21 would all raise `ImproperlyConfigured` from R8's guard before asserting
anything. T13 is the one that runs at the default and reads as such.

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
- **T2c Live-row validation (R1b).** A fixture question doctored into the states R1b names
  (a choice with no `is_correct`; a shortnumeric whose `value` will not parse) causes its
  **unit** to be skipped with a warning, and provisioning still completes. Mutant: validate
  the builder against the type rather than the row, and the pupil silently fails a question.
- **T3 Real users untouched (R7).** A fixture course with a pre-existing enrolled student
  who is not in the kit gains **zero** new `UnitProgress`, `QuizSubmission` and
  `QuestionResponse` rows across a provision. Mutant: widen the generator's queryset from
  `kit.users` to all enrolled students.
- **T4 Drafts untouched.** A fixture with draft units gains no progress and no submissions,
  and the matrix gains no column. Mutant: drop the published filter (R2).
- **T5 Whole-unit skip, and its three counter-cases.** A unit with an unanswerable question,
  and separately a unit with a REVIEW question, each receive **no** submission and warn.
  Counter-cases: (a) a unit with a **NOT_MARKED** question of an unsupported type is still
  generated, that question alone skipped (R3's stated exception); (b) a unit whose top-level
  questions are **all** NOT_MARKED gets no submission (§4.5 — the cell could never show a
  score); (c) a unit with an unanswerable question **nested in a container** is generated
  normally, because R9 never looks at it. Plus: when the quiz just past a pupil's depth is
  R3-skipped, the IN_PROGRESS chain moves on to the next candidate rather than writing an
  empty submission. Mutant: `continue` past an unanswerable top-level AUTO question instead
  of skipping its unit.
- **T6 Type coverage, derived not pinned.** Enumerate `QuestionElement` subclasses; assert
  each is either in the builders registry or in `SKIP_UNIT_TYPES`, **and that every registry
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
  all their rows; the Default cohort's member count returns to its pre-kit value (§3.7); the
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
- **T13 Vendor guard, derived and split.** At the test settings' default
  (`VENDOR_INSTANCE=False`, no override): `provision_kit` raises `ImproperlyConfigured` with
  no rows written; **every** subcommand enumerated from the parser — never listed by hand,
  never pinned by count — is asserted to be in exactly one of two sets, the guarded
  (`create`, `extend`, `revoke`, raising `CommandError`) or the exempt (`purge`, `list`,
  running normally); and `purge_kit` itself is callable, since R8's exemption is a service-
  level claim and a parser-only test would miss a guard added one layer down. ⚠️ A guard on
  `create` alone would keep a hand-written version of this green while `purge` refused to run
  on prod ([[guards-that-assert-the-adjacent-thing]]).
- **T14 `/admin/` exposes nothing.** A kit Teacher's `/admin/` index lists zero models
  (§3.3). Mutant: register `Group` in `grouping/admin.py`.
- **T15 Purge selection.** A kit expiring tomorrow survives `demo_access purge`; one that
  expired yesterday does not; a second run is a no-op; `--dry-run` writes nothing **and
  prints the ids it would purge**. ⚠️ The idempotence case must contain an **already-closed**
  kit whose `expires_at` is in the past, or it passes because the second run found nothing
  rather than because the predicate filtered it. Mutant: drop the `closed_at IS NULL`
  conjunct. Second mutant: make one kit's purge raise and assert the others still close and
  the exit code is non-zero.
- **T15b Bounds and extend arithmetic.** `provision_kit` (not just the command) rejects
  `pupils` outside 2–40 and `days` outside 1–90 with the named error; `extend` on a kit that
  expired yesterday moves `expires_at` to `now() + N days`, not into the past. Mutant:
  validate in the command only — the service-level call must then go through, which is what
  PR 3's form would hit.
- **T16 Enrolment and deletion go through the services.** Provisioning calls
  `add_students_to_group` (not `Enrollment.objects.create`) and purge calls
  `delete_group` — asserted on **behaviour** (the `Enrollment` rows and `added_by` the
  service writes, and the post-delete recompute) rather than on a source grep, which a
  refactor defeats silently. Mutant: swap in a direct `Enrollment.objects.create` and a bare
  `group.delete()`.
- **T17 Username disambiguation.** A second kit for the same label provisions successfully
  with distinct usernames; a collision with a **non-kit** user — including one whose address
  exists only as an allauth `EmailAddress` row — fails with the named error before any user
  is created. Mutant: drop the non-kit collision check, or scan `User.email` only.
- **T18 Back-dating** (only if Q1 keeps it): `completed_at` and `submitted_at` land inside
  the `BACKDATE_DAYS` window before `created_at`; **two different units' timestamps are
  strictly ordered** by pre-order position; and every finalized row satisfies
  `created <= submitted_at`. Mutant: write one scalar to every row — the window assertion
  still passes, the ordering one must not.
- **T21 Frontier override.** `--frontier-part 0` produces the part-0 frontier, **not** the
  0.75 fraction (the falsy-zero trap, §4.5); a part index out of range, or one with no
  published unit, raises the named error.
- **T19 `seed_demo_course` refuses** under `DEBUG=False`. Mutant: guard on
  `settings.DEBUG is None` or on an env var the test does not set.
- **T20 The rep's Student can actually do the demo** — the only test of §1's requirement 2.
  The kit's Student is non-staff, holds a `GroupMembership` of the kit group with the
  recomputed `Enrollment`, and can open a published quiz, submit it and read a stored score.
  ⚠️ Every other test targets the generator or the gating; a kit whose Student came out
  staff (or unenrolled) passes all of them and then silently gets the read-only previewer
  instead of a real submission (`courses/views.py:1455,1696-1697`). Mutant: create the
  Student with role Teacher.

**Beyond the suite:** provision a kit against the local `mat-pp` copy and read the matrix,
the drill-down, the review queue and the pupil view in a browser, light and dark;
**record the wall-clock of that provision** (PR 3's tab depends on it, §4.6).
**Acceptance criteria for the frontier default**, both measured **with every part expanded
to unit columns** (an unexpanded part column lights up as soon as one quiz under it counts,
§3.2, so it cannot discriminate):
1. *results mode* — at least two-thirds of the **quiz unit** columns the generator actually
   attempted hold a score for at least half the class. R3-skipped units are excluded from the
   denominator and their warnings recorded alongside the measurement: a skip blanks a column
   for the whole class, so counting them would turn this into a verdict on builder coverage
   rather than on `FRONTIER_FRACTION`;
2. *progress mode* — the class shows **gaps behind the frontier**, not a clean staircase
   (the `P_LESSON_DONE` check, §4.5). This is the screen that opens first.

A green suite cannot say whether the class looks believable
([[verify-ui-with-screenshots]], [[reviews-that-execute-beat-reviews-that-read]]).

## 9. Risks

1. **Prod writes, and how long they take.** Each kit writes a few thousand rows to the live
   DB. `provision_kit` runs in one transaction (back-dating included, as bulk updates at its
   end); purge is exercised on the local copy before the first real kit. The measured
   duration from §8 is what decides whether PR 3's tab can call it synchronously (§4.6).
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

- **Q1** (blocks PR 2's date handling) Does any analytics or review surface actually display
  the back-dated timestamps? If none does, drop the back-dating (§4.5) and T18 as
  untestable decoration. (The mechanism half of this question is already settled: a queryset
  `update()` bypasses `save()` by construction, which is why §4.5 specifies it.)
- **Q2** (blocks PR 2) Confirm the default pupil count (20), kit lifetime (14 days) and
  `FRONTIER_FRACTION` (0.75) with Krzysztof.
- **Q3** (blocks PR 4) `/for-schools/` claims analytics drill down "to one pupil and one
  question", but no teacher-facing per-question view exists for AUTO answers (§3.2). Either
  the copy is corrected or the claim is met — decide before the demo is shown to anyone.
- **Q4** Should the demo show teacher **marking** at all? It needs a REVIEW question, which
  published `mat-pp` does not have (§3.4). Options: leave it out, or give the demo a tiny
  separate course carrying one REVIEW question.
