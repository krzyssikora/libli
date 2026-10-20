# Attempts defaults: course → quiz → question

**Status:** design approved in brainstorming 2026-10-20; spec awaiting owner review.

Today `max_attempts` lives only on each question (`QuestionElement.max_attempts`,
`courses/models.py:2306`, default 1, null = unlimited, consumed only in quiz
units). There is no course or quiz level and no bulk setter. This feature adds a
course default, overridable per quiz unit, overridable per question, plus an
optional "reset overrides" choice at course and quiz level.

## 1. Owner decisions (PROTECTED)

Every owner answer and every approved design-section bullet. A review catch that
would change a row below is NOT applied: it is brought back to the owner.

| # | Decision | Owner's words (verbatim) |
|---|---|---|
| D1 | Three levels: course default, overridable per quiz unit, overridable per question. Most specific set level wins. | "2 is a better option. What about a course default that could be overwritten per quiz or per question?" |
| D2 | Existing questions are migrated: exactly the old default (1) → *inherit*; every other value stays an override (see D9 for 0). | "I agree with (a)." |
| D3 | When saving the course default, the author can choose to clear all more specific settings (every quiz and question then inherits) or keep them. | "When the course default is changed, could the course admin have 2 options: either overwrite all more specific settings (so that each question inherits) or leave specific settings unchanged." |
| D4 | The same keep / reset choice exists at quiz level (clears question overrides in that quiz). | "I can go with your recommendation, although this is a lot less important." |
| D5 | Storage approach A: explicit `attempts_mode` (inherit / limited / unlimited) + `attempts_limit` per level; one resolver; `max_attempts` removed so stale readers fail loudly. | "Yes, A" |
| D6 | Section 1 (data + migration, §3 below) approved as presented. | "Yes. 0 as inherit makes sense for me. Must be made clear for course authors, too" |
| D7 | Section 2 (resolver + readers, §4) approved. | "Yes" |
| D8 | Section 3 (editor UI + reset choice, §5) approved. | "Looks good" |
| D9 | Old value 0 migrates to *inherit*, and this must be made clear to course authors: the editor never uses 0 to mean inherit; typing 0 is rejected with a message pointing at the "Same as …" option. | "0 as inherit makes sense for me. Must be made clear for course authors, too" |
| D10 | Section 4 (export/import, §6) approved. | "Looks right" |
| D11 | Section 5 (testing, §7) approved; write the spec. | "Yes" |

Approved section bullets that are individually protected (from D6–D11):

- P1. Nothing set anywhere resolves to **1** (today's default). Course default is *limited*, 1.
- P2. *Unlimited* is a choice at every level. Course has no *inherit*.
- P3. Lessons keep ignoring attempts; only `[A]` auto-marked questions use the value (`[N]`/`[R]` stay single-submission).
- P4. Every student's effective limit is identical the day after deploy (except former 0s, which become answerable).
- P5. Existing `QuestionResponse.attempt_count` is untouched; lowering a limit below a student's count behaves as today (locked; Show answer still works).
- P5a. *(Added in spec review — OPEN for owner confirmation.)* Raising a limit at any level does **not** unlock a `QuestionResponse` that is already `locked` (stored boolean, checked first by the `quiz_answer` gate): unchanged behaviour. The new limit applies to responses not yet locked. If the owner wants a raise to unlock students, that is a new decision.
- P6. The migration is reversible: reverse writes each question's **effective** value into `max_attempts`.
- P7. The *inherit* option label always shows the current resolved value and its source ("Same as quiz (currently: 3)", "Same as course (currently: unlimited)").
- P8. The reset choice defaults to **Keep**; it is shown only when overrides exist, shows the counts, applies even if the number did not change, runs in the same transaction as the save, and is confirmed with a message ("Settings saved. 2 quizzes and 41 questions now use the course setting.").
- P9. Counts and resets cover **quiz units only**; questions in lessons are untouched.
- P10. Sub-tree import: *inherit* resolves against the **target** course; no warning.
- P11. Format version 17 → 18; legacy files map with the same rule as the migration.

## 2. Vocabulary

- **Mode** — `inherit` | `limited` | `unlimited` (course: `limited` | `unlimited`).
- **Effective limit** — `int` (≥ 1) or `None` (= unlimited); what the quiz enforces.
- **Override** — a question or quiz unit whose mode is not `inherit`.

## 3. Data and migration

### 3.1 Fields

A shared `AttemptsMode` `TextChoices` (`inherit`, `limited`, `unlimited`).

| Model | `attempts_mode` | `attempts_limit` |
|---|---|---|
| `QuestionElement` (abstract; its 10 concrete tables today: Choice, ShortText, ExtendedResponse, ShortNumeric, FillBlank, DragFillBlank, MatchPair, ChoiceGrid, MultiGrid, DragToImage) | default `inherit` | `PositiveSmallIntegerField(null=True, blank=True)` |
| `ContentNode` | default `inherit`; meaningful only for `unit_type == quiz` (dormant elsewhere, like `obligatory`) | same |
| `Course` | choices `limited`/`unlimited` only, default `limited` | default `1` |

`QuestionElement.max_attempts` is **removed**.

Everything that touches "all question tables" (migration, reset, counts, constraint
tests) iterates a **derived** list — the concrete subclasses of `QuestionElement`
(in the migration: the historical models of those classes) — never a hand-written
one, so a new question type is covered automatically.

`attempts_limit` is capped at `MAX_ATTEMPTS_LIMIT = 999` (forms and import
validation), well inside `PositiveSmallIntegerField`'s 32767.

### 3.2 Database constraints

On every table: `attempts_limit IS NOT NULL AND attempts_limit >= 1` exactly when
`attempts_mode = 'limited'`, otherwise `attempts_limit IS NULL`. On `Course`,
additionally `attempts_mode != 'inherit'`.

The question constraints are declared on the abstract `QuestionElement.Meta`, so
their names must be class-interpolated (`%(app_label)s_%(class)s_attempts_…`) and
every concrete subclass that declares its own `Meta` must inherit
`QuestionElement.Meta`, or it silently drops them.

**Stale limit with a non-`limited` mode:** at every level the editing save path
(form `clean()`, `rename_node`) sets `attempts_limit = NULL` whenever the mode
is not `limited`, so a hidden-but-posted number never reaches the constraint
(no IntegrityError / 500). The importer does **not** null: it rejects such a
payload (§6).

### 3.3 Migration

**Three migrations**, each in its own transaction (a single schema+data+schema
migration risks PostgreSQL's "cannot ALTER TABLE … pending trigger events" on the
question tables): (1) add the new fields; (2) `RunPython` data step; (3) remove
`max_attempts` and add the §3.2 constraints. The migration-graph-head restore check
covers the last of the three. The data step applies, for every existing question,
quiz or lesson:

| Old `max_attempts` | New |
|---|---|
| 1 | `inherit` |
| 0 | `inherit` (D9) |
| null | `unlimited` |
| n ≥ 2 | `limited`, n |

All existing `ContentNode` rows → `inherit`; all `Course` rows → `limited`, 1.
Hence P4.

Reverse (P6): `max_attempts` = effective limit computed with the §4 rules
(including the §4 quiz-only rule for the unit step). Reverse is lossy for former
0s: they come back as the resolved value (1 by default), not 0.

**Scoping joins.** Question rows reach their unit only through the generic
`Element` join (`unit` FK, `content_type`, `object_id`). The reverse data step,
the reset and the override counts all scope each concrete table with
`pk__in=Element.objects.filter(unit__in=…, content_type=<that table's CT>)
.values('object_id')` (historical `ContentType` in the migration). A question row
with no `Element` row resolves to 1 in the reverse step.

## 4. Resolver and readers

`courses/quiz.py`:

```python
def effective_course_attempts(course):
    """int >= 1, or None for unlimited: the course level alone."""

def effective_unit_attempts(unit):
    """(value, source): value int >= 1 or None; source "quiz" | "course".
    The unit step applies only when unit.unit_type == quiz."""

def effective_max_attempts(question, unit):
    """int >= 1, or None for unlimited. question -> unit -> course.
    Delegates steps 2-3 to effective_unit_attempts (one copy of the rules)."""
```

1. question mode `limited` → its limit; `unlimited` → `None`;
2. else, **only if `unit.unit_type == quiz`**, the unit's mode, same way. A lesson
   unit's dormant override (left by a quiz→lesson switch, or imported) is skipped;
3. else the course's (always set).

The same helpers feed the inherit-option labels, so labels and enforcement cannot
disagree: the **question** select (§5.1) uses `effective_unit_attempts(unit)`; the
**quiz** select (§5.2) uses `effective_course_attempts(unit.course)` — never
`effective_unit_attempts`, which on an overriding quiz would return the quiz's own
value. `effective_unit_attempts` delegates its step 3 to
`effective_course_attempts`.

The caller passes the unit (its `course` loaded); no per-question query.

Readers switched to it (every current `max_attempts` reader); `locked_after`,
`quiz_feedback_context` and `ephemeral_quiz_feedback` all gain a `unit` argument:

- `locked_after` (`quiz.py:121`) — the single lock rule. Both answer paths (persisted `quiz_answer` and `ephemeral_quiz_feedback`) pass it.
- `quiz_feedback_context` (attempts-left, `quiz.py:86`) — callers `views.py:1544`, `views.py:1658`, `views_manage.py:2810`.
- `ephemeral_quiz_feedback` — callers: student previewer `views.py:1768`, author previewer `views_manage.py:2807`.
- exhausted gate in `quiz_answer` (`views.py:1811`).
- analytics attempt column (`views_analytics.py:412`).
- the editor marking template (§5.1).

The plan re-greps these call sites at execution time (line numbers rot).

Removing the field makes any missed reader an `AttributeError` in tests (D5).

## 5. Editor UI

### 5.1 Question (`templates/courses/manage/editor/_marking_fields.html`, quiz only)

*Max attempts* number input → **Attempts** select:
- **Same as quiz (currently: N | unlimited)** — source word is *quiz* when the unit overrides, else *course* ("Same as course (currently: 1)") (P7);
- **Limited to…** — reveals a number input. The input carries **no `min`/`max`
  attributes** (the form strips the `min="0"`/`max="32767"` Django adds for a
  `PositiveSmallIntegerField`): browser constraint validation would block values
  with its own generic text and the messages below would never be seen (D9);
- **Unlimited**.

Validation: `limited` with an empty limit, with limit 0, or above
`MAX_ATTEMPTS_LIMIT` is rejected. The 0 message (D9) names the option **actually
shown**, i.e. follows the source word of P7:
- source quiz: *"0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'."*
- source course: *"0 isn't a limit. To use the course's setting, choose 'Same as course'."*

The same text also shows as help text under the number input, so the guidance is
visible before submitting.

Other limit messages (all three levels): empty or negative under *Limited to…* →
*"Enter a number of attempts, or choose another option."*; above the cap → *"At
most 999 attempts."* (these replace Django's default min/max/required messages).

**Reveal mechanism (all three levels).** The number input is always rendered in
the HTML; a CSS-only rule (`:has()` on the select's checked `limited` option)
shows it when *Limited to…* is selected and hides it otherwise. No JS, so it
needs no re-initialisation after a fragment swap or a 422 re-render, and it is
visible on first render whenever the bound or stored mode is `limited`. A hidden
input's posted value is harmless (§3.2 nulling).

**Form wiring.** The question form takes the `unit` as a constructor argument and
builds the inherit-option label itself from `effective_unit_attempts(unit)`, so
every render path (full page, fragment swap, 422 re-render, add-element) shows it.
When the attempts fields are **absent** from the POST (a lesson question — the
select renders only in quizzes), both stored values are kept unchanged; the
nulling rule of §3.2 runs only when a mode was actually posted. A lesson question's
dormant `limited` override therefore survives an edit.

### 5.2 Quiz unit (`templates/courses/manage/editor/_unit_settings.html`, only when `unit_type == quiz`)

Same select; inherit option reads **Same as course (currently: …)**; same input
rules and the course-source 0 message from §5.1. Below it, shown only when ≥ 1
question in this quiz overrides (P8):

- ◉ **Keep questions' own settings (N questions)** (default)
- ○ **Make all questions in this quiz use the quiz setting**

**Save path.** Unit settings do not post to a form: they go to
`views_manage.node_rename` → `builder.rename_node(...)`, which also serves plain
tree renames and the unit-type toggle. `rename_node` gains `attempts_mode`,
`attempts_limit` and `reset_question_attempts`, all defaulting to `_UNSET`. The view
passes them **only when the attempts select was actually posted** (it renders only
for a quiz unit), so saving a lesson's settings or renaming a node never touches a
dormant override. Validation (incl. the D9 message) raises `ValidationError`, which
surfaces through the existing `_editor_page(..., error=msg, status=422)` route. The
reset runs inside `rename_node`'s existing locked transaction.

**Message path.** `rename_node`'s return value is unchanged for existing callers;
when a reset is requested it also records the reset count on the returned node
(e.g. `node.attempts_reset_count`), and `node_rename` adds a
`django.contrib.messages` success message, which the editor page renders after
the redirect. `course_edit` does the same with the counts from its reset.

### 5.3 Course (`CourseForm`)

**Attempts per question**: *Limited to…* / *Unlimited*, default *Limited to 1*.
Below it, shown only when overrides exist in the course's quiz units (P8, P9):

- ◉ **Keep specific settings (Q quizzes, N questions have their own)** (default)
- ○ **Make every quiz and question use the course setting**

A limit of 0 at course level gets: *"0 isn't a limit. Choose 'Unlimited' or a
number from 1."* (the course has no inherit option). The number input has no `min`
attribute, as in §5.1.

`course_edit` wraps `form.save()` and the reset in one `transaction.atomic()`
(today it has none and `ATOMIC_REQUESTS` is off). `course_create` shows neither the
reset choice nor runs a reset (a new course has no overrides).

### 5.4 Reset semantics

- Reset sets `attempts_mode='inherit'`, `attempts_limit=NULL` by bulk update, across every concrete question table (§3.1 derived list), restricted to elements in quiz units of this course (course reset also resets those quiz units) or of this unit (quiz reset).
- Runs inside the save's transaction (§5.2 / §5.3), regardless of whether the number changed.
- **Concurrency:** the reset bumps `ContentNode.updated` on every quiz unit it touched (units whose questions or own mode changed). The bump is **explicit** — `ContentNode.objects.filter(pk__in=touched).update(updated=timezone.now(), …)` — because `updated` is `auto_now` and `QuerySet.update()` never applies `auto_now`; a question-only reset touches no `ContentNode` row at all otherwise. An editor already open on such a unit then gets the existing stale-token "changed elsewhere" response on its next save, instead of silently re-posting the old override and undoing the reset. The plan must audit every reader of `ContentNode.updated` (author live-view links, LAL "no hand edit" checks, unit-progress staleness) before relying on the bump, and report any reader for which the bump is wrong.
- Success message reports the counts actually reset.
- Questions in lessons, other quizzes and other courses are untouched.
- **Counts** (and whether the reset choice is shown) include only `[A]` auto-marked questions, the only ones an attempts setting affects (P3). The reset itself clears every question row in scope, `[N]`/`[R]` included (harmless).
- Accepted consequence of P9: a lesson unit's dormant override survives a course reset and takes effect again if the unit is later switched to a quiz (the quiz panel then shows it). Not "fixed".

**Count wording (§5.2, §5.3, P8 message):** a zero part is omitted ("41 questions
have their own", not "0 quizzes, 41 questions …"); each count uses its own
`ngettext` / `blocktrans count` (Polish plurals).

**Translations.** Every new or changed string (labels incl. "Max attempts" →
"Attempts", option labels, D9 and other messages, counts) gets a Polish
translation: run `makemessages`, translate every new msgid, clear any fuzzy
pre-fill (it is often a wrong translation), recompile the `.mo`.

## 6. Export / import (FORMAT_VERSION 17 → 18)

- **Question payload:** `attempts_mode` + `attempts_limit` replace `max_attempts` (`export.py:76`, `payloads.py:97/103`, `importer.py:489`).
- **Node payload:** `attempts_mode` + `attempts_limit` beside `obligatory` (`export.py:603`, `importer.py:932`, and the node `_exact_keys` list in `transfer/schema.py`).
- **Course payload** (KIND_COURSE only): beside `color_bands` (`export.py:1006`, `importer.py:1109`, and the course key check in `transfer/schema.py`).
- Legacy defaults for absent keys are applied **by version, before** the exact-keys check (as `published` already is), so v≤17 archives are not rejected.
- **Copies and moves** (`duplicate_unit`, `duplicate_element`, copy-units across courses, element moves between units) keep the stored mode as-is and resolve at the destination — same rule as sub-tree import.
- **Legacy (≤ 17):** question `max_attempts` mapped per §3.3; nodes absent → `inherit`; course absent → `limited`, 1.
- **Validation:** unknown mode, `inherit` on course, missing / < 1 / > `MAX_ATTEMPTS_LIMIT` limit under `limited`, or limit present otherwise → `TransferError` with a translated message.
- **Sub-tree import:** modes kept as-is; *inherit* resolves against the target course (P10).
- **Merge guard:** before merging, confirm no other open branch also bumps to 18 (identical-line bumps merge silently).

## 7. Testing

TDD; each new test proven RED against a mutant chosen from its failure mode.

1. **Resolver** — full mode matrix over the three levels; nothing set → 1; a lesson unit with a `limited` override is skipped (step 2 quiz-only).
2. **Migration** (pattern of `tests/test_subject_migrations.py`) — forwards per §3.3; backwards writes effective values (former 0 → 1, lossy); property: every question's effective limit equal before and after **for every old value except 0**, and a separate assertion that an old 0 resolves to the course default (1).
3. **Readers** — `test_quiz_lock_rule_parity.py` gains inherit cases; exhausted gate: inheriting quiz limit 2 → 2 wrong attempts accepted, the 3rd refused (locked response); inheriting unlimited never locks; raising a limit leaves an already-locked response locked (P5a); attempts-left and analytics show resolved values.
4. **Forms / save paths** — 0 / empty / > `MAX_ATTEMPTS_LIMIT` under `limited` rejected at all three levels with the level's message (both D9 source variants); posting `unlimited` or `inherit` together with a limit saves with `attempts_limit = NULL` (no 500); inherit label shows correct value + source; a quiz unit with its own `limited` 3 under a course `limited` 1 shows "Same as course (currently: 1)"; course cannot be `inherit`; saving a **lesson's** settings or a plain tree rename leaves a dormant unit override untouched; editing a lesson question with a dormant `limited` override keeps it unchanged; the inherit label is correct on every render path; a lesson unit with an override switched to quiz shows and enforces it after a course reset.
5. **Reset** — keep vs reset; exact scope (quiz units only, this course/unit only); counts incl. zero-part omission; message; atomic with the save (a failure in the reset rolls back the course/unit save); touched units' `updated` bumped, including a question-only quiz reset (must fail on a build relying on `auto_now`), and a stale editor save then gets the stale-token response; counts ignore `[N]`/`[R]` overrides.
6. **Transfer** — v18 round trip at all three levels; v17 fixture mapping (accepted by the exact-keys check); invalid payloads rejected; sub-tree import inherits from target; copying units across courses keeps modes and resolves at the destination.
6a. **Migration on Postgres** — forwards and backwards on a DB with populated rows of every question type (catches the pending-trigger failure).
7. **Constraints** — the full truth table at the DB, on **every** concrete question table (derived list), `ContentNode` and `Course`: `limited` without a limit, `limited` with 0, `inherit`/`unlimited` with a limit all fail; `Course` with `inherit` fails.
8. **e2e (real UI)** — a question with its own override (`limited` 2); author sets course to 3 and chooses "Make every quiz and question use the course setting" → a student **who has not answered yet** gets 3 tries, 4th refused (proves the reset through the UI); author sets a quiz to Unlimited while a question keeps 2 → it still stops at 2; author types 0 in a question's limit and sees the D9 message (proves the browser does not swallow it); after a fragment swap, selecting "Limited to…" shows the number input.
9. **Screenshots** — question select, quiz panel with reset choice, course form; light + dark.

### 7.1 Existing-test sweep (risk)

`max_attempts` appears in ~60 existing test files (factories, `create(...)`
kwargs, and form POST dicts). Model kwargs fail loudly after the rename. **Form
POST dicts do not:** the form fields are `required=False`, so a stale
`"max_attempts": "3"` key is silently ignored and the question saves as
`inherit` (resolving to 1), which can turn a test green for the wrong reason or
red for a confusing one. The plan must sweep every POST-dict occurrence
explicitly (grep, not recall), not rely on failures to find them.

## 8. Out of scope

- Per-student or per-cohort attempt allowances.
- Changing how `[N]`/`[R]` questions submit.
- Any change to lesson (non-quiz) behaviour.
