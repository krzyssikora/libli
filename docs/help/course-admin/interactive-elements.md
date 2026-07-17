# Interactive elements

The **Interactive** group holds nine **lesson-only** self-check and reveal
elements, added from a unit's editor via **Add element** — the group is
absent when editing a quiz. Most are self-checks: the student checks their
own work in place, and the family convention is a locked widget with its
commit button removed, so there is nothing to submit and nothing to grade —
these elements record **no marks**. Like the [content element
types](content-editors), they are nestable inside Tabs and Columns.

## Show more

A thin gate with a **Button text** field (default *Show more*, shown
placeholder-style if left blank). It hides the elements that follow it in
the outline until a student clicks its button — no server check, no marks,
just a click-to-reveal divider. Use it to stage a lesson so later material
doesn't spoil what comes before it.

## Fill in & confirm

A reveal gate whose trigger is a fill-in blank rather than a plain button.
Write the **Prompt with blanks** with the blank marked as `{{answer}}`, using
`|` to separate accepted alternatives (e.g. `{{colour|color}}`) — same
syntax as [Fill in the blanks](quiz-editors). A correct, server-checked
answer reveals the following siblings; records no marks.

## Choose & confirm

A reveal gate whose trigger is an inline cycling "Choose ▾" widget instead
of a typed answer. Write the **Prompt with a choice** with the choice
position marked as `{{choice}}` (exactly once), then list the cycler's
**Options** below and mark the correct one. A correct, server-checked
choice reveals the following siblings; records no marks.

## Switch grid

A self-check made of one or more lines that interleave static text with
clickable cyclers: write each line with `{{choice}}` where a cycler should
appear (a cycler block is inserted for every marker), then fill in each
cycler's options and mark the correct one. Add as many lines as needed with
**Add line**. The whole grid is checked together with per-cycler feedback as
the student clicks through; it does not gate or reveal anything and records
no marks.

## Fill-in table

A table editor — the same grid, header-row/column, and border controls as
[Table](content-editors) — with one addition: the **Answer cell** toolbar
button turns a cell into an input holding an accepted-answer string instead
of rich content. Static cells stay editable text/math like a plain table;
answer cells are checked server-side per cell as the student types. Records
no marks and reveals nothing.

## Spoiler

A collapsible block that hides its content behind a click, using a
native `<details>` toggle with no JavaScript. Use it to tuck away a hint, a worked
answer, or an aside a student can open when they choose. Set an optional
**Button text** (default *Reveal*) and write the hidden body with the same
rich-text toolbar (bold/italic/underline, headings, lists, links, quote,
code, alignment) as other rich-text fields.

## Step-by-step

An ordered list of short **Steps** — one line of text or inline math each
(e.g. `\(2^{10}\)`) — with an optional **Intro prompt** above them. The
first step is visible immediately; a walking "Show next" button reveals the
rest one at a time. Ungraded, with no persistence: reloading the page
starts the walk over from the first step.

## Checklist

An optional prompt plus an ordered list of short **Checklist items** the
student ticks off to record "I've done this" — for a study checklist or a
self-paced task list rather than a question with a right answer. Unlike the
other Interactive types, a student's ticks persist per student across
visits. Ungraded.

## Guess the number

A numeric self-check with directional feedback rather than a plain
right/wrong verdict. Write the rich-text **Prompt with the answer** with the
target marked as `{{42}}` (exactly once), an optional **Tolerance (±)**, and
a rich-text **Success message** shown once the guess lands within tolerance
— note it is visible in the page source, so nothing secret belongs there. A
wrong guess is told only "too big" or "too small" and can be retried without
limit; it records no marks and reveals nothing, since the point is to let a
student be wrong repeatedly while narrowing in.

## See also

- [Content editors](content-editors) — the content block types, and how
  Tabs/Columns nest these Interactive elements alongside them.
- [Quiz editors](quiz-editors) — question elements, the graded/assessed
  counterpart used for lesson practice and quiz scoring.
