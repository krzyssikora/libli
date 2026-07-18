# Quiz editors

Question elements work the same way in a **quiz** unit (assessed, scored) and
in a **lesson** unit (practice, ungraded) — you add and edit them from the
unit's editor exactly like the [content element types](content-editors), via
**Add element** (the **Questions** group). Every question type has two
common fields:

- **Stem** — the question prompt (rich text, supports inline math). The
  rendered field label varies by type: **Question**, **Prompt (optional)**,
  **Sentence with blanks**, or **Sentence with gaps**.
- **Explanation (optional)** — feedback text shown after the student answers.

In a **quiz**, three further fields appear — a lesson's editor does not
render them at all:

- **Marking mode** — Auto-marked (scored automatically), Requires review (a
  human marks it later — see the review queue), or Not marked (recorded but
  never scored).
- **Max attempts** and **Max marks** — how many tries a student gets, and how
  many marks a correct answer is worth.

The type-specific fields below are what makes each question type behave
differently.

![The quiz editor with questions](static:core/img/help/quiz-editor.en.png)

## Single / Multiple choice

A list of **choices**, each flagged correct or incorrect. Single choice
renders as radio buttons (exactly one answer); multiple choice renders as
checkboxes (any combination). Marking is exact-match: for multiple choice, the
student must select *all* correct choices and *no* incorrect ones to get
credit — partial selections score zero.

Each choice can also carry optional per-option **feedback**. As the editor's
own hint puts it: "Optional feedback shows when a student gets an option
wrong — a wrong pick, or a correct answer they missed." Leave a choice's
feedback blank to opt it out.

This changes what a wrong answer shows, and it differs by unit type:

- In a **lesson**, without per-option feedback, a wrong answer shows only the
  verdict (Correct/Incorrect) — the correct choice is never revealed. With
  per-option feedback, the choices the student got wrong (a bad pick, or a
  correct one they missed) are marked inline and show their feedback text —
  but only those annotated choices; there's no separate list of the correct
  answers.
- In a **quiz**, the correct answers are always revealed once the student is
  locked out of further attempts (on the last wrong attempt, or afterwards at
  results/review) — independently of whether any choice has feedback text.

## Short text

A one-line free-text answer, marked by comparing the student's text against a
list of **accepted answers** (one per line — add every spelling/phrasing
variant you'll accept). Toggle **case sensitive** if capitalization must
match exactly; by default matching ignores case and surrounding whitespace.

## Short numeric

A numeric answer, marked correct if it falls within a **tolerance** of the
target **value** (tolerance 0 means an exact match). Use this for calculated
answers where you want to accept small rounding differences.

## Fill in the blanks

A stem with one or more inline gaps. Write the stem with each blank marked as
`{{answer}}`, using `|` to separate accepted alternatives, e.g.
`The capital of France is {{Paris|paris}}.` — the editor turns each marker
into its own gap with its own accepted-answer list, and each gap is marked
independently.

## Drag the words

Like Fill in the blanks, but the student drags word chips into the gaps
instead of typing. Mark each gap the same way with `{{token}}` in the stem;
add optional **distractors** (extra wrong chips shown alongside the correct
ones) to make guessing harder.

## Match pairs

A two-column matching question: a list of **left** labels (the fixed targets)
each paired with its correct **right** token (the draggable/selectable
answer). Add optional **distractors** — extra right-hand tokens with no
matching left label — to prevent elimination-by-process-of-exclusion.

## Matrix question

A grid of **statements** (rows) against a shared set of **columns** (the
answer options) — each statement is marked by picking exactly one correct
column. Add columns freely, or use the **True/False preset** to seed the two
columns instantly. Each row is scored independently (partial credit), unlike
the exact-match, all-or-nothing marking above.

## Multi-select grid

Like Matrix question — the same **statements**-against-**columns** grid —
but each statement can have *several* correct columns: tick every column
that applies per row. Marking is all-or-nothing per row: a statement counts
correct only when its full set of ticked columns matches.

## Drag to image

The student drags labels onto marked zones over a picture. Pick an image from
the media library, then use the **zone editor**: click-drag directly on the
image to draw a rectangular zone, and type the zone's correct label. Click an
existing zone (or its row) to select, resize with the handles, or delete it.
Add optional **distractor** labels the same way as the other drag types.

## Extended response

A long free-text answer (essay-length). It can be marked automatically by
**required** and **forbidden keyword** lists (one per line), or set to
**Requires review** so a teacher reads and scores it manually afterwards, or
**Not marked** if you just want to collect responses without scoring them.

## Where questions live

The same question types work in both contexts:

- In a **lesson**, students can check their answer immediately and see
  feedback — useful for practice.
- In a **quiz**, answers are collected and marked (or queued for review) as
  part of a graded attempt; see the analytics manual for how results surface
  afterwards.

Lessons also offer a set of lesson-only, ungraded self-check widgets — see
[Interactive elements](interactive-elements) for the "Show more"/"Fill in &
confirm"/"Choose & confirm" family and their cousins, the practice-oriented
counterpart to questions-as-practice.

## See also

- [Content editors](content-editors) — the non-question block types.
- [Media manager](media-manager) — uploading the images used by Drag to image.
- [Building a course](builder) — creating lesson and quiz units.
