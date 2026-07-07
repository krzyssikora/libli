# Quiz editors

Question elements work the same way in a **quiz** unit (assessed, scored) and
in a **lesson** unit (practice, ungraded) — you add and edit them from the
unit's editor exactly like the [content element types](content-editors), via
**+ Add element → Questions**. Every question shares a few common fields:

- **Stem** — the question prompt (rich text, supports inline math).
- **Explanation** — optional feedback text shown after the student answers.
- **Marking mode** — Auto-marked (scored automatically), Requires review (a
  human marks it later — see the review queue), or Not marked (recorded but
  never scored).
- **Max attempts** and **Max marks** — how many tries a student gets in a quiz,
  and how many marks a correct answer is worth.

The type-specific fields below are what makes each question type behave
differently.

## Single / Multiple choice

A list of **choices**, each flagged correct or incorrect. Single choice
renders as radio buttons (exactly one answer); multiple choice renders as
checkboxes (any combination). Marking is exact-match: for multiple choice, the
student must select *all* correct choices and *no* incorrect ones to get
credit — partial selections score zero.

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

## See also

- [Content editors](content-editors) — the non-question block types.
- [Media manager](media-manager) — uploading the images used by Drag to image.
- [Building a course](builder) — creating lesson and quiz units.
