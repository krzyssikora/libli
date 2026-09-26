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

In a **quiz**, an auto-marked question colours each part green or red after every
Check, and a **Show answer** button appears after the first Check. Pressing it (after
a confirmation) ends the question at the marks the student has, and the student can
then switch between **Your answer** and **Correct answer** on the question itself.
The same switch appears when a question locks on its last attempt, and on the results
page after the quiz is finished. Multiple choice and extended response show the
answer their own way — see their sections below.

## {el:choice-single}{el:choice-multi} Single / Multiple choice

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
- In a **quiz**, every Check marks the options the student ticked with ✓
  (right) or ✗ (wrong); a correct option they did not tick is not pointed out
  while they can still try again. Once the question ends — a correct answer,
  the last attempt, or **Show answer** — the correct options they missed get
  ＋, and the results page shows the same marks. There is no Your answer /
  Correct answer switch for this type: the marks on the options are its
  answer view. Per-option feedback appears once the question has ended.

## {el:shorttext} Short text

A one-line free-text answer, marked by comparing the student's text against a
list of **accepted answers** (one per line — add every spelling/phrasing
variant you'll accept). Toggle **case sensitive** if capitalization must
match exactly; by default matching ignores case and surrounding whitespace.
In a **lesson**, a wrong answer turns the box red instead of showing the
correct answer; in a **quiz** the answer is available through **Show
answer**.

## {el:shortnumeric} Short numeric

A numeric answer, marked correct if it falls within a **tolerance** of the
target **value**. Both the value and the tolerance accept a decimal (`3.14`
or `3,14`), a fraction (`3/2`), or a mixed number (`1 1/2`) — any value equal
to the target is accepted, so `6/4` matches a target of `3/2`. **Leave the
tolerance blank for an exact match**; use this for calculated answers where
you want to accept small rounding differences instead.
In a **lesson**, a wrong answer turns the box red instead of showing the
correct answer; in a **quiz** the answer is available through **Show
answer**.

## {el:fillblank} Fill in the blanks

A stem with one or more inline gaps. Write the stem with each blank marked as
`{{answer}}`, using `|` to separate accepted alternatives, e.g.
`The capital of France is {{Paris|paris}}.` — the editor turns each marker
into its own gap with its own accepted-answer list, and each gap is marked
independently.

In a **lesson**, checking an answer turns each gap green (right) or red (wrong)
in place; the correct answers are not shown. If you want students to be able to
look them up, put them in a Spoiler under the question.

## {el:dragwords} Drag the words

Like Fill in the blanks, but the student drags word chips into the gaps
instead of typing. Mark each gap the same way with `{{token}}` in the stem;
add optional **distractors** (extra wrong chips shown alongside the correct
ones) to make guessing harder.

In a **lesson**, checking an answer turns each gap green (right) or red
(wrong) in place; the correct answers are not shown. If you want students to
be able to look them up, put them in a Spoiler under the question.

## {el:matchpairs} Match pairs

A two-column matching question: a list of **left** labels (the fixed targets)
each paired with its correct **right** token (the draggable/selectable
answer). Add optional **distractors** — extra right-hand tokens with no
matching left label — to prevent elimination-by-process-of-exclusion.

In a **lesson**, checking an answer turns each pair green (right) or red
(wrong) in place; the correct answers are not shown. If you want students to
be able to look them up, put them in a Spoiler under the question.

## {el:switchgrid} Matrix question

A grid of **statements** (rows) against a shared set of **columns** (the
answer options) — each statement is marked by picking exactly one correct
column. Add columns freely, or use the **True/False preset** to seed the two
columns instantly. Each row is scored independently (partial credit), unlike
the exact-match, all-or-nothing marking above.

In a **lesson**, checking an answer turns each row green (right) or red
(wrong) in place; the correct answers are not shown. If you want students to
be able to look them up, put them in a Spoiler under the question.

## {el:switchgrid} Multi-select grid

Like Matrix question — the same **statements**-against-**columns** grid —
but each statement can have *several* correct columns: tick every column
that applies per row. Marking is all-or-nothing per row: a statement counts
correct only when its full set of ticked columns matches.

In a **lesson**, checking an answer turns each row green (right) or red
(wrong) in place; the correct answers are not shown. If you want students to
be able to look them up, put them in a Spoiler under the question.

## {el:dragimage} Drag to image

The student drags labels onto marked zones over a picture. Pick an image from
the media library, then use the **zone editor**: click-drag directly on the
image to draw a rectangular zone, and type the zone's correct label. Click an
existing zone (or its row) to select, resize with the handles, or delete it.
Add optional **distractor** labels the same way as the other drag types.

In a **lesson**, checking an answer turns each zone green (right) or red
(wrong) in place; the correct answers are not shown. If you want students to
be able to look them up, put them in a Spoiler under the question.

## {el:extended} Extended response

A long free-text answer (essay-length). It can be marked automatically by
**required** and **forbidden keyword** lists (one per line), or set to
**Requires review** so a teacher reads and scores it manually afterwards, or
**Not marked** if you just want to collect responses without scoring them.

In a **quiz**, an auto-marked extended response has **Show answer** too. It
ends the question and shows the keyword list — which required keywords the
answer contains and which forbidden ones it uses — instead of a Your answer /
Correct answer switch. The same list appears when the question ends on its
last attempt without full marks, and on the results page. In a **lesson**
nothing changes.

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
