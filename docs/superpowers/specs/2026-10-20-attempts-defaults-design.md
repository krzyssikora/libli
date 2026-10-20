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
| `QuestionElement` (abstract; all 12 concrete tables) | default `inherit` | `PositiveSmallIntegerField(null=True, blank=True)` |
| `ContentNode` | default `inherit`; meaningful only for `unit_type == quiz` (dormant elsewhere, like `obligatory`) | same |
| `Course` | choices `limited`/`unlimited` only, default `limited` | default `1` |

`QuestionElement.max_attempts` is **removed**.

### 3.2 Database constraints

On every table: `attempts_limit IS NOT NULL AND attempts_limit >= 1` exactly when
`attempts_mode = 'limited'`, otherwise `attempts_limit IS NULL`. On `Course`,
additionally `attempts_mode != 'inherit'`.

### 3.3 Migration

One migration (schema add → data → schema remove), for every existing question,
quiz or lesson:

| Old `max_attempts` | New |
|---|---|
| 1 | `inherit` |
| 0 | `inherit` (D9) |
| null | `unlimited` |
| n ≥ 2 | `limited`, n |

All existing `ContentNode` rows → `inherit`; all `Course` rows → `limited`, 1.
Hence P4.

Reverse (P6): `max_attempts` = effective limit computed with the §4 rules.

## 4. Resolver and readers

`courses/quiz.py`:

```python
def effective_max_attempts(question, unit):
    """int >= 1, or None for unlimited. question -> unit -> course."""
```

1. question mode `limited` → its limit; `unlimited` → `None`;
2. else the unit's (quiz's) mode, same way;
3. else the course's (always set).

The caller passes the unit (its `course` loaded); no per-question query.

Readers switched to it (every current `max_attempts` reader):

- `locked_after` (`quiz.py:121`) — the single lock rule; gains the unit argument. Both answer paths (persisted `quiz_answer` and `ephemeral_quiz_feedback`) pass it.
- attempts-left context (`quiz.py:86`).
- exhausted gate in `quiz_answer` (`views.py:1811`).
- author previewer path (`views_manage.py:2807`, via `ephemeral_quiz_feedback`).
- analytics attempt column (`views_analytics.py:412`).
- the editor marking template (§5.1).

Removing the field makes any missed reader an `AttributeError` in tests (D5).

## 5. Editor UI

### 5.1 Question (`templates/courses/manage/editor/_marking_fields.html`, quiz only)

*Max attempts* number input → **Attempts** select:
- **Same as quiz (currently: N | unlimited)** — source word is *quiz* when the unit overrides, else *course* ("Same as course (currently: 1)") (P7);
- **Limited to…** — reveals a number input, `min=1`;
- **Unlimited**.

Validation: `limited` with an empty limit, or with limit 0, is rejected. The 0 message
(D9): *"0 isn't a limit. To use the quiz's setting, choose 'Same as quiz'."*

### 5.2 Quiz unit (`templates/courses/manage/editor/_unit_settings.html`, only when `unit_type == quiz`)

Same select; inherit option reads **Same as course (currently: …)**. Below it,
shown only when ≥ 1 question in this quiz overrides (P8):

- ◉ **Keep questions' own settings (N questions)** (default)
- ○ **Make all questions in this quiz use the quiz setting**

### 5.3 Course (`CourseForm`)

**Attempts per question**: *Limited to…* / *Unlimited*, default *Limited to 1*.
Below it, shown only when overrides exist in the course's quiz units (P8, P9):

- ◉ **Keep specific settings (Q quizzes, N questions have their own)** (default)
- ○ **Make every quiz and question use the course setting**

### 5.4 Reset semantics

- Reset sets `attempts_mode='inherit'`, `attempts_limit=NULL` by bulk update, across the 12 question tables, restricted to elements in quiz units of this course (course reset also resets those quiz units) or of this unit (quiz reset).
- Runs inside the form save's transaction, regardless of whether the number changed.
- Success message reports the counts actually reset.
- Questions in lessons, other quizzes and other courses are untouched.

## 6. Export / import (FORMAT_VERSION 17 → 18)

- **Question payload:** `attempts_mode` + `attempts_limit` replace `max_attempts` (`export.py:76`, `payloads.py:97/103`, `importer.py:489`).
- **Node payload:** `attempts_mode` + `attempts_limit` beside `obligatory` (`export.py:603`, `importer.py:932`).
- **Course payload** (KIND_COURSE only): beside `color_bands` (`export.py:1006`, `importer.py:1109`).
- **Legacy (≤ 17):** question `max_attempts` mapped per §3.3; nodes absent → `inherit`; course absent → `limited`, 1.
- **Validation:** unknown mode, `inherit` on course, missing/< 1 limit under `limited`, or limit present otherwise → `TransferError` with a translated message.
- **Sub-tree import:** modes kept as-is; *inherit* resolves against the target course (P10).
- **Merge guard:** before merging, confirm no other open branch also bumps to 18 (identical-line bumps merge silently).

## 7. Testing

TDD; each new test proven RED against a mutant chosen from its failure mode.

1. **Resolver** — full mode matrix over the three levels; nothing set → 1.
2. **Migration** (pattern of `tests/test_subject_migrations.py`) — forwards per §3.3; backwards writes effective values; property: every question's effective limit equal before and after.
3. **Readers** — `test_quiz_lock_rule_parity.py` gains inherit cases; exhausted gate: inheriting quiz limit 2 locks on the 3rd try, inheriting unlimited never locks; attempts-left and analytics show resolved values.
4. **Forms** — 0 / empty under `limited` rejected with the D9 message; inherit label shows correct value + source; course cannot be `inherit`.
5. **Reset** — keep vs reset; exact scope (quiz units only, this course/unit only); counts; message; same transaction.
6. **Transfer** — v18 round trip at all three levels; v17 fixture mapping; invalid payloads rejected; sub-tree import inherits from target.
7. **Constraints** — `limited` without a limit fails at the DB.
8. **e2e (real UI)** — author sets course to 3 + reset → a student gets 3 tries on a formerly-default question, 4th refused; author sets a quiz to Unlimited while a question keeps 2 → it still stops at 2.
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
