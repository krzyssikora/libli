# Student course outline redesign

**Date:** 2026-10-18
**Status:** approved design (owner), mockup https://claude.ai/artifact/S8orXaZ3H3QR3C78WyXJka
**Base:** `master` at `d5c2f52a` (PR #397, the phone layout fix, is merged and is the starting point)

## 1. Purpose

The student course outline (`/courses/<slug>/`, `courses:course_outline`) is clear but reads as a
bare table of contents: plain text on the page background, a "lekcje: 0/62" chip on every
heading, bold everywhere, three bordered buttons plus a "Zacznij od nowa" in the head, and a
"Zacznij od nowa" link beside every container that has saved work. The owner called it "very dry,
not-inviting" on desktop and "simply ugly" on a phone.

This redesign gives the page rhythm and a clear next step without removing anything the page does
today: top-level parts become numbered cards with progress bars, the course gets an overall
progress bar and one obvious call to action, and the reset actions move out of sight into "⋯"
menus.

## 2. Owner decisions — PROTECTED

These rows were approved by the owner on 2026-10-18 against the mockup. **Review rounds must not
change any row.** A catch that would change one is not applied; it is raised to the owner as a
question, stated as the visible consequence for a student.

| # | Decision | Owner's words / source |
|---|---|---|
| D1 | The course title sits on its own line. Under it, a course-wide progress bar with a label: "18 z 199 lekcji ukończonych"; for a student with nothing done yet: "199 lekcji w 6 działach". | mockup; "keep everything else" |
| D2 | One clear next step. A returning student sees the existing resume card, its wording kept ("Wróć tam, gdzie skończyłeś"). A new student (no progress) sees a primary button "Zacznij pierwszą lekcję" linking to the first unit. | mockup + "keep its wording" |
| D3 | "Moje wyniki" and "Moje notatki" share one row. The course-level "Zacznij od nowa" moves into a "⋯" menu. | "reset into ⋯ menu" |
| D3a | Each part card gets its own small "⋯" menu holding "Zacznij od nowa", shown only when that part has saved work (exactly when the link shows today). | "lgtm" |
| D4 | Each top-level part is a raised card: a number badge (1…n), the title, a progress bar with a count, and a chevron. Long titles wrap inside the card. | mockup |
| D5 | Inside an open part, chapter rows carry a status circle: done = filled circle with a tick; in progress = partial ring; not started = empty ring. The in-progress row is highlighted. Tapping a chapter **unfolds its lessons in place**. | "unfold in place" |
| D6 | "Podsumowanie" / quiz rows get a quiz icon and a "QUIZ" label. | mockup |
| D7 | Every tappable row is at least 44px tall on a phone. | mockup |
| D8 | Above the list: a small "Działy · N" label, and "Rozwiń wszystko" as a plain text button. | mockup |
| D9 | Amber (`--glance-fill`, the dashboard glance bars' colour) for progress; teal (`--primary` / `--primary-subtle`) for the number badges and the quiz label. | mockup |
| D10 | Nothing from the mockup is dropped. | "keep everything else" |

### 2.1 How this spec reads D1–D10 against the existing code (interpretations, not changes)

- **D2 "new student".** `build_resume` (courses/rollups.py) already returns one of four states:
  `resume` ("Pick up where you left off" / "Wróć tam, gdzie skończyłeś"), `next` ("Up next"),
  `gap` ("Still to do"), and `start` ("Start the course" / "Rozpocznij kurs") — STEP 6, "genuinely
  nothing". "New student" = `resume.state == "start"`. In that state the card is replaced by the D2
  primary button, linking to the same target `build_resume` already chose (the first open unit).
  The other three states keep today's card and wording unchanged. `resume` is `None` for
  non-enrolled viewers (authors, teachers, staff previewing) and when every unit is done — then
  neither card nor button renders, as today.
- **D1 counts.** "Lessons" means what the page already counts: `required_total` / `required_done`
  (obligatory lesson units; quizzes and optional lessons excluded). The course totals come from the
  existing `_course_required_totals(tree)` (courses/rollups.py), the one place that sum lives.
  "Działy" (D1, D8) = the number of top-level **containers** (§3.2).
  The D1 label switches to the "nothing done yet" form when `required_done == 0`, independent of
  the resume state. When the course has no top-level containers (`section_count == 0`), the
  "nothing done yet" form drops the "w N działach" fragment and reads just "199 lekcji".
- **Earlier owner decisions O6/O12** (`2026-09-17-analytics-results-table-design.md`): O12 made
  the student outline's chip read „lekcje: 1/2", the same wording as the teacher breakdown chip
  (O6). D4/D5 (approved 2026-10-18) replace that chip on the **student outline only** with a
  progress bar + count; the teacher page keeps „lekcje: X/Y" (O6 untouched). **Owner confirmation
  requested 2026-10-18** — the visible consequence is that the two pages stop sharing one chip
  wording. Until confirmed, this row is the plan's assumption.
- **D2 target kind.** `build_resume`'s `start` target is the first open unit, which can be a quiz
  or an optional lesson. The button keeps the D2 wording in every case (protected) and reuses the
  card's quiz/lesson URL branch.
- **D3a "part card".** Every top-level container is a card (§3.2), so "part" = top-level
  container. D3 says reset moves into "⋯" menus; the same rule is applied to every container row
  that offers a reset today (chapters and deeper), so no "Zacznij od nowa" text link remains
  anywhere on the page. Each gets a "⋯" only when that container `has_state`.
- **D5 "chapter rows".** = the direct children of a card that are containers. Direct children that
  are units (e.g. a part-level "Podsumowanie" quiz) render as unit rows (§3.5) in the same list.
  "The in-progress row" = the one row on the page that leads to the resume target, only when
  `resume.state` is `resume`, `next` or `gap`:
  - target under a depth-1 container → that depth-1 container row;
  - target is itself a depth-1 unit (a direct child of a card) → that unit row;
  - target is a root-level unit (no card) → that unit row.
  So in those three states exactly one row is highlighted; in `start` or when `resume` is `None`,
  none is. Partially-done rows elsewhere get the partial ring but no highlight.
- **D6.** Applies to every quiz unit row (`unit_type == "quiz"`), wherever it sits, not only to
  units titled "Podsumowanie".

## 3. Architecture / components

Files touched: `templates/courses/outline.html`, `templates/courses/_outline_node.html`,
`templates/courses/_resume_card.html` (start state only), `core/static/core/css/app.css`
(the "Course outline" block), `courses/static/courses/js/outline_tree.js` (only where §3.7 says),
`courses/views.py::course_outline` (context additions only), `locale/{pl,en}/LC_MESSAGES/django.po`
+ compiled `.mo`. No model, migration, URL or `build_outline`/`build_resume` behaviour change.

### 3.1 Course head (`outline.html`)

Replaces today's `.outline__head` row:

```
<header class="outline__head">
  <h1 class="outline__title">…course title…</h1>
  <div class="outline__progress">           ← D1
    <div class="outline__bar" aria-hidden="true">fill</div>
    <span class="outline__progress-label">…</span>
  </div>
  {resume card | D2 start button | nothing}  ← D2
  <div class="outline__actions">            ← D3
    <a class="btn btn--ghost btn--small outline__results">Moje wyniki</a>
    <a class="btn btn--ghost btn--small outline__notes">Moje notatki</a>
    {⋯ menu with course reset, only if has_saved_work}
  </div>
</header>
```

- Title on its own line at every width (D1).
- Desktop (≥ 641px): a two-column top row — left column = title, then the bar + label; right
  column = the actions, bottom-aligned with the bar (mockup desktop frame). The resume card or
  start button sits below that row: the card spans the full head width (as today); the start
  button is auto-width, left-aligned.
- Phone (≤ 640px): one column — title, bar + label, resume card / start button (both full width),
  actions in one row ("Moje wyniki" and "Moje notatki" share the width equally, "⋯" fixed square).
- When neither card nor button renders, the head is just the top row (desktop) / title, bar,
  actions (phone).
- When the progress block is absent (`required_total == 0`), the desktop actions align to the
  title's last line (bottom of the left column).
- **DOM order is fixed:** title, progress, resume card / start button, actions — the phone visual
  order (mockup). Desktop places the actions into the top row's right column with CSS grid areas,
  so on desktop the tab order (card before actions) differs from the reading order (actions appear
  above the card). Accepted: both are adjacent, few controls, and the primary next step comes
  first in tab order.
- The course bar is `aria-hidden="true"`; the visible label next to it is the accessible text
  (no `role="img"`, no duplicate announcement). Same for card bars (§3.2).
- The resume card moves from below the head into it (between the progress bar and the actions);
  its markup and states are unchanged apart from the `start` branch (§3.6).
- Course-level reset keeps its URL (`courses:progress_reset_course` with `?next=`) and its
  condition (`has_saved_work`); only its placement changes (D3).
- The "Rozwiń wszystko" toggle moves out of the head into the list header (§3.3).
- The tag filter bar (`_tags_filter_bar.html`) stays between the head and the list, unchanged.

### 3.2 Cards: top-level containers

Every top-level node of kind part/chapter/section (a container at depth 0) renders as a card. The
card is the existing `<li class="outline-node outline-node--{kind}">` with a new class
`outline-node--card`; its `<details class="outline-node__group">` keeps the native disclosure.

Card head (`<summary class="outline-node__head">`):

1. number badge `outline-card__num` — 1-based position among top-level **containers** in render
   order (top-level units are skipped by the count); teal on `--primary-subtle` (D9). It is a
   decorative position marker: `aria-hidden="true"`, so the card's accessible name starts with
   the title. Numbers are stamped server-side over all root containers and stay **stable under a
   tag filter** — when a filter hides card 2 the visible cards read 1, 3, …; the gap is accepted
   (the number is the card's place in the course, not in the filtered view);
2. title (existing `.outline-node__title`, wraps inside the card — D4);
3. progress bar `outline-card__bar` (amber fill on a light track, D9) + count. Count text: phone
   "18/62"; ≥ 641px "18 z 62 lekcji". Two spans: the long form is always in the accessibility
   tree — at ≤ 640px it is **visually hidden** with the existing `.visually-hidden` pattern, never
   `display: none` — and the short form is `aria-hidden` and shown only at ≤ 640px. A container with `required_total == 0` shows no bar and no
   count (as today, where the rollup chip is omitted);
4. the "+N dodatkowe" rollup chip when `additional_done` (unchanged text and condition);
5. chevron, at the end of the row (rotates 90° when open, as today).

**Card head grid.** Desktop (≥ 641px): one row — badge, title, bar, count, (+N chip), chevron,
then the "⋯" when present (mockup desktop frame). The title is the **only** flexible column
(`minmax(0, 1fr)`); the bar is a fixed 12.5rem track and the long count a fixed-width column
(≈ 6rem), so a long title wraps instead of squeezing the bar. Phone (≤ 640px): two rows — row 1: badge,
title, chevron (and the "⋯" beside it when present); row 2: bar + count (+N chip), starting under
the title's left edge. The badge, chevron and "⋯" align to the **first** title line, not to the
centre of a wrapped title (mockup phone frames).

The card's "⋯" menu (D3a) is a **sibling** of the `<details>`, never inside `<summary>` (same reason
as today's D9 reset link: a focusable control inside a button-role summary corrupts its accessible
name). It is grid-placed onto the head row exactly like today's `.outline-node__reset`, and the
card head reserves space for it only when present (generalising PR #397's `:has()` rule).

Top-level **units** (a course with units at the root) are not cards and get no number; they render
as unit rows (§3.5) in the list, in order, between cards.

Open/closed defaults are unchanged: every card (`data-depth="0"`) renders `open` server-side, as
today's top-level groups do, and `outline_tree.js` then restores the student's stored partition.
(The phone mockup shows only the first card open, i.e. a stored state; the server default is not
changed.) The stored partition wins even over the highlighted row: if the student folded the card
holding `current_row_pk`, it stays folded and the highlight is out of sight until they open it —
accepted (their explicit choice; the resume card / start button above still points there).

### 3.3 List header (D8)

Between the tag filter bar and the list, **outside** `<nav class="outline-tree">` (directly before
it), so the nav landmark holds only the tree and no `.outline-tree` descendant rule or the
`--booting` class touches the header:

```
<div class="outline-list__head">
  <span class="outline-list__count">Działy · N</span>   ← N = number of cards; omitted when N == 0
  <button data-outline-toggle-all class="outline__toggle-all">Rozwiń wszystko</button>
</div>
```

The toggle keeps every existing attribute and behaviour (`hidden` until JS reveals it,
`data-label-expand`/`data-label-collapse`, disabled under a tag filter). Only its styling changes:
a plain text button (accent colour, no border) instead of `btn btn--ghost btn--small`.

### 3.4 Rows inside a card: containers (D5)

A container child of a card (depth 1: a chapter, or a section directly under a part) renders as a
row, in this order: status circle, title, count "1/10" (muted, no chip border), "+N dodatkowe" chip
when `additional_done`, small chevron at the row end; the row is the existing `<details>` summary,
so tapping it unfolds its own children **in place** inside the card (D5). Its "⋯" (when
`has_state`, §2.1) is a sibling of the `<details>`, grid-placed after the chevron.

**Containers at depth ≥ 2** (sections inside a chapter, …) keep today's head layout — chevron at
the start, title (uppercase micro-type for sections, as today) — with two changes: today's
bordered "lessons: X/Y" chip becomes the same muted "X/Y" count as depth-1 rows, and their reset
moves into a "⋯" at the row end. No status circle at depth ≥ 2. The "+N dodatkowe" chip stays.
After this change no "lessons: X/Y" chip remains anywhere on the page.

**Row counts use the card's two-span pattern:** a visible `aria-hidden` "X/Y" plus a
visually-hidden long form "%(done)s z %(counter)s lekcji" (the card count msgid, §3.9), so a
summary's accessible name still says "lessons" (today it says "lekcje: 1/10"). Depth ≥ 2 rows get
the same pair and no status word.

**Childless container arm** (`div.outline-node__head`, the fallback branch of
`_outline_node.html`): same count pair as a depth-1 row, its reset moved into a "⋯" at the end of
the div head; no chevron (nothing to fold), no circle at depth ≥ 2.

Status circle (inline SVG, `aria-hidden`). Its visually-hidden status word is placed **after the
title and the count pair, before the "+N dodatkowe" chip** in DOM order (not next to the circle),
so the DOM order is: circle, title, count pair, status word, chip, chevron; a summary's accessible
name starts with the title — e.g. "Chapter A 0 z 1 lekcji Nierozpoczęte +2 dodatkowe". This keeps the existing T6
assertion (`test_e2e_outline_tree.py`, accessible name matches `^Chapter A`) valid unchanged.

| state | condition | drawing | sr text |
|---|---|---|---|
| done | `required_total > 0 and required_done == required_total` | filled amber circle, dark tick | "Ukończone" / "Completed" (msgctxt "outline status", §3.9) |
| in progress | `0 < required_done < required_total`, **or** `required_done == 0 and has_state` (saved work but nothing completed), **or** `required_done == 0 and pk == current_row_pk and resume.state == "resume"` (the student's in-flight place — `resume` can come from a bare lesson visit or an in-progress quiz, neither of which sets `has_state`) | track ring + amber arc whose length is `_progress_width(required_done, required_total)` percent (the bars' 1..99 clamp, so an unfinished row never looks closed), with a minimum visible arc (≈ 1/12 of the circle) when `required_done == 0`; the view stamps `item["progress_width"]` on every container for this | "W toku" / "In progress" |
| not started | `required_done == 0`, not `has_state`, and not the `resume`-state current row | empty ring | "Nierozpoczęte" / "Not started" |

Precedence: "no circle" (`required_total == 0`) first, then `done`, then the in-progress
conditions, then not started. So a highlighted row in state `resume` with
`0 < required_total` and `required_done < required_total` always reads "in progress"; a
highlighted `resume` row whose required lessons are all done (the in-flight unit is an open quiz or
optional lesson) reads "Ukończone" and is still `is-current`; an all-quiz highlighted row has no
circle and no status word. A highlighted row in `next`/`gap` that the student has not touched reads "not started",
which is accurate (it is the next thing to start). Tests pin both.

A container with `required_total == 0` gets **no circle** (and no status word) and no count — an
empty ring would wrongly read "not started" for a finished all-quiz chapter.

Highlight: the one row defined in §2.1 (D5) gets `is-current` (sunken background, semi-bold
title). The class goes on the row element itself, never on the `<li>` (which would paint the whole
unfolded subtree): on `summary.outline-node__head` for a container row, on `a.outline-unit` for a
unit row. Tests count `.is-current` on those two selectors. The template decides it **only** by comparing the row's pk with `current_row_pk` from the
view (§4) — never by reading `contains_current`, which `build_resume` stamps in every state,
`start` included.

Deeper levels (sections under a chapter, then units) keep today's nested-list presentation (left
hairline rule, uppercase section headings, unit rows), restyled only enough to sit inside the card
(no extra card chrome, D7 heights on phones). The card's **own** child list
(`.outline-node--card > .outline-node__group > ul`) drops the hairline rule and the `--space-4`
indent — the card edge is the boundary (mockup); the rule and indent start one level down
(a depth-1 chapter's `<ul>`, which T17 checks). An e2e/computed-style assertion pins both.

A depth-1 row is styled **by position, not kind**: a section directly under a part renders like a
chapter row — no uppercase, `--text-primary`, §3.8's depth-1 size/weight. The depth-1 rule must
override the kind-based `.outline-node--section … .outline-node__title` rule (higher specificity
or later source order, stated in a CSS comment).

### 3.5 Unit rows

Unchanged content: the `<a class="outline-unit">` link with title, unit kind chip, ✓ done badge;
then tag chips, the tag-edit affordance, and the notes badge as siblings. Additions:

- **Quiz rows (D6):** a quiz icon before the title and a "QUIZ" label (teal, D9). The label **is**
  the existing chip: `unit_marker` returns `MARKER_QUIZ` for every quiz unit and
  `_unit_kind_chip.html` renders `span.badge.unit-kind-chip.unit-kind-chip--quiz` "Quiz". It is
  restyled only under the outline row selector (`.outline-unit .unit-kind-chip--quiz`): teal,
  `text-transform: uppercase` in CSS, so the "Quiz" msgid is untouched. The same partial is used by
  `_lesson_article.html`, `_quiz_article.html` and `_resume_card.html`, which must keep their
  current look — a test asserts the resume card's quiz chip keeps its computed style (colour,
  text-transform). Never a second quiz label.
- **Lesson unit rows** (every `unit_type == "lesson"` row, inside a card at any depth and at the
  root): a status circle at the start — done = filled with tick; **in progress** = partial ring at
  the minimum arc when the unit `has_state` or is the `resume`-state `current_row_pk` (so a
  highlighted unit row in `resume` matches D5 like a container row does); otherwise an empty ring.
  It is purely decorative — `aria-hidden`, no status word — because the ✓ badge (kept, with its
  `aria-label`) already announces completion. Quiz rows get the quiz icon instead of a circle.
  A unit whose `unit_type` is unset is treated as a lesson row here (gets the circle), so every
  unit row has a same-width leading glyph and titles stay aligned.
- Rows are ≥ 44px tall at ≤ 640px (D7) via `min-height` on `.outline-unit` and on container heads;
  desktop keeps today's denser rows.

### 3.6 Resume card / start button (D2)

`_resume_card.html` gains a branch: when `resume.state == "start"`, render
`<a class="btn btn--primary outline__start" lang="{{ LANGUAGE_CODE }}" href="…">Zacznij pierwszą lekcję<svg … aria-hidden="true">→</svg></a>`
instead of the card. The `href` reuses the card's existing branch verbatim (`quiz_unit` when
`resume.node.unit_type == 'quiz'`, else `lesson_unit`). The msgid carries no arrow; the arrow reuses the card chevron's SVG path but with its own class
`outline__start-arrow` (inline, `aria-hidden`) — never `resume__arrow`, which is absolutely
positioned for the card. `lang` is the UI language, as on the card's eyebrow
(the button sits inside `<section lang="{{ course.language }}">`; without it an English course with
a Polish UI would read the label in an English voice).

**UI-language `lang` rule.** Every new UI string rendered inside the outline section — the D1
label, "Działy · N", the card/row counts, the status words, the start button, the "⋯" label —
carries `lang="{{ LANGUAGE_CODE }}"` on its element. Author content (titles) keeps the course
language it inherits. `django.template.context_processors.i18n` is not enabled, so
`LANGUAGE_CODE` is not in the context by default: `outline.html` (head + list header) **and**
`_outline_node.html` itself (so a bare `render_to_string` of the partial, as T11 does, also works)
must each call `{% get_current_language as LANGUAGE_CODE %}`, like `_resume_card.html` does.
A server test asserts a row count / status word carries `lang="pl"` (non-empty) on an `en` course
viewed with a Polish UI. New msgid "Start the first lesson" → "Zacznij pierwszą lekcję". The old
"Start the course" msgid becomes unused in this template; leave it in the catalogue only if another
template still uses it (grep), otherwise let `makemessages` mark it obsolete.

### 3.7 JavaScript (`outline_tree.js`)

No behaviour change is intended. The file must keep working with:

- the toggle button moved into `.outline-list__head` (it is found by `[data-outline-toggle-all]`,
  so no change expected);
- "⋯" menus: implemented as `<details class="outline-menu">` with a `<summary>` "⋯" button
  (`aria-label` "More actions" / "Więcej akcji", the existing entry) and a link inside. They are **not**
  `.outline-node__group`, so the partition/expand-all logic ignores them — the selector
  `.outline-node__group` must stay scoped so a menu never counts as a group. A click inside a
  menu's summary must not trigger the outline's persistence write (`closest("summary.outline-node__head")`
  already excludes it — verify).
- Closing an open "⋯" menu on outside click / Escape is a small additive handler (or none — a
  `<details>` menu that stays open until re-clicked is acceptable); spec leaves the choice to the
  plan, but no global keydown handler that interferes with the editor (this page has none).

**Menu layout.** The `<details class="outline-menu">` wrapper is `position: relative` and sits at
the row's end (after the chevron on card heads and depth-1 rows; at the end of depth ≥ 2 heads and
in the course head's action row). Its `<summary>` is the "⋯" button: ≥ 44×44px at ≤ 640px
(D7 applies to it), 32×32px on desktop. The open panel is **out of flow**: `position: absolute`,
`top: 100%`, `right: 0` (right-aligned to the button, so it grows leftwards and never past the
viewport's right edge), `z-index` above the card, `--surface-raised` + `--border-default` +
`--shadow-md`, `min-width` fitting "Zacznij od nowa". Menu items are ≥ 44px tall at ≤ 640px.
The menu's `<summary>` gets `list-style: none` and a hidden `::-webkit-details-marker` (as
`summary.outline-node__head` does), so no UA triangle appears beside "⋯" or widens the square;
checked in the 360 and 1280 screenshots.

Opening a menu must not change any row's height or cause horizontal scroll. Cards, rows and the
list must not set `overflow: hidden`/`clip` or create a stacking context (`transform`, `filter`,
`isolation`) that would clip or trap the panel — a closed last card's menu has to spill below it.

Space for the menu on a head row is reserved only where the menu exists:
`.outline-node:has(> .outline-menu) > .outline-node__group > summary.outline-node__head` reserves
the "⋯" button's width plus a gap (44px + `--space-2` at ≤ 640px, 32px + `--space-2` on desktop).
PR #397's `:has(> .outline-node__reset)` rule and its 7.5rem measured-width comment become
obsolete and are removed.

The course-level reset inside the menu drops its `btn btn--ghost btn--small` classes and keeps only
`outline__reset` plus a shared menu-item class (`outline-menu__item`); container resets keep
`outline-node__reset` plus `outline-menu__item`. Menu items look like menu entries (full-width row,
hover = `--surface-sunken`, danger colour on hover as today's reset link), not buttons.

Each container's menu `<summary>` carries `aria-describedby` pointing at its row's title
(the title span gets `id="node-title-{{ pk }}"`), so the many "Więcej akcji" buttons are told
apart by their row; the course menu's points at the h1. The item names stay "Zacznij od nowa" as
today.

The reset link inside the menu keeps its existing class (`outline-node__reset` for containers,
`outline__reset` for the course), `href`, `title` and `aria-label`, so its URL contract and
its selectors are unchanged; only its parent changes.

### 3.8 Styling

All tokens from `core/static/core/css/tokens.css`; no new colours. Card = `--surface-raised`,
`--border-subtle`, `--radius-lg`, padding `--space-4` (phone) / `--space-5` (desktop). Bars reuse
the glance track/fill tokens (`--border-subtle` track, `--glance-fill` fill). Badge =
`--primary-subtle` background, `--primary` text. Light and dark both come from the tokens; dark is
judged separately in screenshots.

The phone breakpoint is the one PR #397 introduced (`max-width: 640px`).

**Type scale (mockup).** The kind-based title sizes are replaced by position-based ones for the
two levels the mockup draws, and kept below them:

| Level | Size | Weight |
|---|---|---|
| card title (depth 0, any kind) | 1.125rem phone / 1.25rem desktop | 600 |
| depth-1 row title (container or unit) | .9375rem (15px) | 500; 600 when `is-current` |
| depth ≥ 2 container heads | unchanged kind-based scale (chapter 1.1rem, section .75rem uppercase 700) | unchanged |
| unit rows at depth ≥ 2 | unchanged | 400 (today's `.outline-unit` weight) |
| root-level unit rows (depth 0, a course with units at the root) | depth-1 row scale (.9375rem) | 500 — plain rows on the page background, no card chrome, between the cards |

So the "bold everywhere" of §1 is removed at depth 1, where most of the bold was.

**Hover inside cards.** Today `summary.outline-node__head:hover` paints `--surface-raised`, which
is the card surface, so hover would vanish. Heads and unit rows inside a card hover with
`color-mix(in srgb, var(--surface-sunken) 50%, var(--surface-raised))` — visibly different from
both the card and the full `--surface-sunken` of `is-current`. Checked in the screenshots.

**Forced colours.** Like the glance bars (app.css `@media (forced-colors: active)` block), the
course bar, card bars and status circles get forced-colours rules: track = `1px solid CanvasText`
border on a transparent background, fill / arc / done circle = `Highlight`
(`forced-color-adjust: none` on the fill), tick = `Canvas`.

### 3.9 Strings (msgids, plural drivers, Polish forms)

All new strings go through `{% trans %}` / `{% blocktrans %}` with English msgids; `pl` and `en`
catalogues updated, `.mo` regenerated.

| Where | English msgid | Plural driver | Polish |
|---|---|---|---|
| D1, some done | "%(done)s of %(counter)s lesson completed" / "…lessons completed" | `counter` = course total | one: "%(done)s z %(counter)s lekcji ukończonej"; few / many: "%(done)s z %(counter)s lekcji ukończonych" ("z" takes the genitive; the participle agrees with the total) |
| D1, nothing done — lessons fragment | "%(counter)s lesson" / "%(counter)s lessons" | lesson total | "%(counter)s lekcja" / "lekcje" / "lekcji" |
| D1, nothing done — sections fragment | "in %(counter)s topic" / "in %(counter)s topics" | `section_count` | locative: "w %(counter)s dziale" / "w %(counter)s działach" / "w %(counter)s działach" |
| D1, nothing done — composition | "%(lessons)s %(sections)s" (no plural; lets a translator reorder) | — | "%(lessons)s %(sections)s" |
| card count, long (≥ 641px, accessible) | "%(done)s of %(counter)s lesson" / "…lessons" | `counter` = card total | "%(done)s z %(counter)s lekcji" (identical forms) |
| card count, short (≤ 640px, `aria-hidden`) | not translated: "{{ done }}/{{ total }}" | — | — |
| D8 | "Topics · %(n)s" | none (a label) | "Działy · %(n)s" |
| D2 | "Start the first lesson" | — | "Zacznij pierwszą lekcję" |
| "⋯" `aria-label` | reuse existing "More actions" | — | existing "Więcej akcji" (unchanged; shared with the editor tree) |
| status words (§3.4) | "Completed", "In progress", "Not started", all with msgctxt "outline status" | — | "Ukończone", "W toku", "Nierozpoczęte" |

The status words carry a context because the bare msgid "Completed" already exists as
"Ukończono" (✓ badge in three templates) and must not change; the context gives the adjective form
without touching that entry. "In progress" exists bare as "W toku"; the context entry repeats it.

English uses "topic" for "dział" because "section" and "part" are already node kinds in the UI.
The plan must grep the catalogue for each msgid first and reuse an existing entry (with its
context) rather than adding a duplicate.

## 4. Data flow

`course_outline` (courses/views.py) already builds `outline` (with rollups and `has_state`),
`resume`, `has_saved_work`, `note_counts`, tag data. It adds, computed in Python (no new queries):

- `course_done` / `course_total`: from `_course_required_totals(outline)` — do not re-sum;
- `section_count` (the "N" of D1/D8): number of roots with `is_unit == False`;
- per container (every depth — cards use it for the bar, depth-1 rows for the arc),
  `item["progress_width"] = _progress_width(required_done, required_total)` (additive key) — the
  template never re-implements the clamp;
- `course_progress_width = _progress_width(course_done, course_total)` for the D1 bar (server test
  for its `None`, partial-clamped and 100 cases);
- per root container, its 1-based card number — stamped into the outline dicts as
  `item["card_number"]` (additive key, like `depth`; other consumers of `build_outline` ignore it
  because the stamping happens in the view on the view's own tree);
- `current_row_pk`: the pk of the one row defined in §2.1 (D5) — the depth-1 container whose
  subtree contains `resume.node`, else `resume.node` itself when it is a depth-1 or root-level
  unit — and `None` unless `resume.state in {"resume", "next", "gap"}`. A pure dict walk over the
  view's tree (the view may read `contains_current`, which `build_resume` stamped, but the
  template reads only `current_row_pk`);
- per container, its status (`done` / `progress` / `none`) and arc length, derived in the template
  from `required_done`/`required_total` or stamped in the view — plan's choice, no queries either way.

Bar widths come from the existing `_progress_width(done, total)` (courses/rollups.py): `None`
when nothing is done or `total == 0`, 100 only when `done == total`, otherwise clamped to 1..99 so
an unfinished course never looks full. Rendering: `total == 0` → no bar at all; `total > 0` and
width `None` → the empty track (the D1 "nothing done" head still shows a bar); otherwise the fill
at that width. Never test widths by truthiness (0 never occurs, but `None` and a number differ).

## 5. Error handling and edge cases

- **No visible units:** `resume` is `None`, `required_total == 0` → no card/button, no bar, no
  label, no cards.
- **Every visible unit completed** (quizzes and optional lessons too): `resume` is `None` → no
  card/button; full bar and the done-form label ("199 z 199 lekcji ukończonych").
- **All required lessons done, a quiz or optional lesson still open:** full bar and the done-form
  label, and the resume card still renders (`build_resume` targets the open unit).
- **`required_total == 0`** (a course of only quizzes/optional lessons): no course bar and no
  progress label at all (the head shows title, next step, actions). Card bars/counts are omitted
  the same way. No "0 lekcji" text is ever rendered.
- **Tag filter:** `outline_with_tags` sets `tag_hidden`; hidden nodes carry `[hidden]`. Cards are
  `<li>`s, so `.outline-node[hidden] { display: none; }` must keep winning over the card's display
  rule — keep the specificity/order contract documented in app.css (the grid rule stays declared
  above `[hidden]`). "Działy · N" is server-computed and does not change under a JS filter (accepted).
- **No-JS:** cards and chapters fold with native `<details>`; "⋯" menus are `<details>` too, so the
  reset links stay reachable without JS. The toggle-all button stays `hidden` without JS (as today).
- **Internal links (`#node-N`):** `:target` highlight must land on the card head / row head, and
  `openHashTarget()` must still open the card and every ancestor.
- **Maths in titles:** titles keep `data-math-title`; KaTeX loading (`has_math`) unchanged.
- **Long titles / unbreakable words:** `min-width: 0` + `overflow-wrap: anywhere` on titles in cards
  and rows; no horizontal page scroll at 360px.
- **Drafts for authors** (`drafts="keep"`): unchanged — authors see draft units as today.
- **Print:** the outline page has no print stylesheet today; cards must not regress printing
  (no dark backgrounds forced, `<details>` content printed as the browser does today). Verify with
  one print-media screenshot; no new print rules unless something breaks.
- **i18n:** Polish plural forms for every count message (`ngettext` / `blocktrans count`), exactly
  as listed in §3.9 (the "działy" fragment is locative). English likewise.

## 6. Testing

Owner rules: TDD — a failing test first for each behaviour, mutants for each assertion (pick the
mutant from the failure mode), e2e drives the real UI, screenshots light + dark at 360 / 412 / 1280
looked at, dark judged separately. Never pass `-q`; grep the summary line. Run every
`tests/test_*css*.py` after CSS edits.

**Server-rendered (pytest + BeautifulSoup):**
- course head: title, bar `aria-hidden`, D1 label in both forms (nothing done / some done), the
  `section_count == 0` form, pl plural forms (1 / 2 / 5 lessons; 1 / 2 / 5 działy in the locative);
- D2: `start` state renders the primary button with the target URL and no card — once with a
  lesson as the first open unit, once with a quiz (href = `quiz_unit`); `resume`/`next`/`gap`
  render the card with unchanged eyebrow text; non-enrolled viewer renders neither; the start
  button carries `lang` = the UI language (pl UI on an `en` course) and its accessible name has no
  arrow;
- status circle boundary: a highlighted row in `resume` with `required_done == 0` reads "W toku"
  in all three ways `resume` arises — saved practice work; a bare lesson visit (a `UnitProgress`
  row with empty `element_state`); an in-progress quiz submission — and a highlighted untouched
  row in `next` reads "Nierozpoczęte"; for the depth-1-unit and root-unit target shapes in
  `resume`, the highlighted unit row draws the partial ring (class pinned), not the empty one —
  both fixtures use a **lesson** as the in-flight target (bare visit or saved state), since quiz
  rows draw no circle; a done chapter whose in-flight unit is an open quiz reads "Ukończone" and
  is still `is-current`;
- row accessible counts: a depth-1 summary's text contains "1 z 2 lekcji";
- accessible names start with the title: card summary (badge `aria-hidden`) and depth-1 summary
  (status word after title + count);
- D3/D3a: no visible "Zacznij od nowa" text link outside a "⋯" menu; course menu present iff
  `has_saved_work`; a card/row menu present iff that node `has_state`; reset hrefs unchanged;
- D4: card numbering skips top-level units; bar width/count; no bar when total is 0; "+N dodatkowe"
  still rendered;
- D5: status class per state for done / progress / none, and no circle when `required_total == 0`;
  exactly one `is-current` row in each of the three target shapes of §2.1 (under a depth-1
  container; a depth-1 unit; a root-level unit), none when `resume` is `start`/`None`;
- depth ≥ 2 heads: muted "X/Y" count, no "lessons: X/Y" chip anywhere on the page;
- D6: a quiz unit row has the quiz icon and exactly one quiz label;
- D8: "Działy · N" count; toggle button attributes unchanged;
- regression: tag filter `hidden` on cards/rows; `#node-N` ids on every `<li>`; notes badge, tag
  chips, tag-edit link, kind chip, ✓ badge still present on unit rows.

**e2e (Playwright, real UI, Polish UI via the header switch):**
- phone 360/412: no horizontal scroll; every unit row, container head, "⋯" button and open-menu
  item ≥ 44px tall (D7); a long part title wraps inside the card beside its badge; tapping a
  chapter unfolds its lessons inside the card (D5); "⋯" opens without changing any row's height or
  causing horizontal scroll, and its reset link navigates to the confirm page; the open menu of
  the **last** card is fully visible (not clipped); at 360px the card's long count span is in the
  accessibility tree (computed `display` is not `none`);
- desktop 1280: on a card with a **short** title, badge, the title's first line, bar, count and
  chevron overlap vertically (one line); on a card with a long title, the title wraps while the
  badge and chevron stay on its first line;
- expand-all / collapse-all still toggles every card and chapter, label flips;
- tag filter hides a card whose units are all filtered out, and shows it again on clear;
- deep link `#node-<chapter>` opens its card and the chapter head carries the `:target` styling
  (box-shadow ring) — using a chapter that is **not** `current_row_pk`, so `is-current` cannot
  satisfy the assertion by accident.

**Existing assertions this design legitimately supersedes** (update each to the replacement and
list them in the PR; no other existing assertion may be changed):

| Test | Pins today | Replacement |
|---|---|---|
| `test_courses_views.py` ~:427 | `("start", "Start the course")` eyebrow | `start` renders the D2 button "Start the first lesson"; the other three states unchanged |
| `test_e2e_outline_tree.py` ~:169 | "lessons: 0/1" rollup text | the card/row count text (§3.9) |
| `test_e2e_outline_tree.py` ~:625–651 | a visible `a.outline-node__reset` clicked/focused directly; Tab from the collapsed summary focuses the reset link | click: open the row's "⋯" first, then click the same `a.outline-node__reset`. Keyboard: Tab from the collapsed summary focuses `details.outline-menu > summary`; Enter opens it; Tab then focuses `a.outline-node__reset` |
| `test_e2e_outline_tree.py::test_nested_type_scale_and_guide_rule_survive_the_details_nesting` (T17) | depth-1 chapter title computes to 17.6px; depth-2 section title 12px uppercase | depth-1 chapter title computes to 15px (§3.8 type scale); depth-2 section title still 12px uppercase; guide-rule assertion unchanged |
| `test_outline_collapsible.py` ~:84–85 | `outline-node__reset` as a direct sibling of the `<details>` | the link inside `details.outline-menu`, which is the sibling |
| `test_courses_views.py::test_card_links_to_quiz_unit_for_a_quiz_target` | `a.resume` href for a fresh student (`start`) | seed one completed earlier unit so the state is `next`, keep the card href assertion; add the same assertion on the D2 button in `start` |
| `test_courses_views.py::test_card_links_to_lesson_unit_for_a_lesson_target` | same, lesson target | same treatment |
| `test_courses_views.py::test_eyebrow_carries_the_active_ui_language` | card eyebrow `lang` in `start` | seed progress → `next`; same `lang` assertion on the eyebrow |
| `test_courses_views.py::test_resume_card_renders_its_path_separator_and_affordance` | card separator + chevron in `start` | seed progress → `next`; same assertions |
| `test_title_math_markers.py::test_resume_card_title_and_crumbs_are_marked` | `span.resume__title` / `span.resume__crumb` marked in `start` | seed progress → `next`; the math-marker and crumb coverage of the card must survive in a non-start state |
| `test_analytics_student_page.py::test_rt_t11_student_outline_chip_reads_lekcje` | `summary .rollup` == "lekcje: 1/2" on the student outline (O12) | the parts are top-level, i.e. cards: the card head's long count reads "1 z 2 lekcji" and its short count "1/2" ("Czesc pierwsza"), and "0 z 1 lekcji" / "0/1" ("Czesc druga"); no `.rollup` "lekcje:" chip on the student outline |
| `test_analytics_student_page.py::test_rt_t11_childless_outline_branch_chip_reads_lekcje` | childless arm `.outline-node__head .rollup` == "lekcje: 1/2" | the childless arm renders the same count pair as a depth-1 row (§3.4) |
| `test_e2e_outline_tree.py::test_head_buttons_share_one_vertical_level` | 4 `.outline__head > .btn` on one top | "Moje wyniki", "Moje notatki" and the "⋯" summary inside `.outline__actions` share one vertical level; keep its align-self mutant |
| `test_e2e_outline_phone_layout.py::test_outline_fits_a_phone` (PR #397) | no horizontal scroll; title starts on the chevron's line (chevron before title); `.rollup` on the title's line; course title alone on its line with `.outline__head > .btn` beneath; nothing reserved on a head without a reset link | at 360/412: no horizontal scroll; on a card head the title starts on the badge's line, right of the badge; the bar + count row sits directly below the title inside the card (§3.2 phone grid); the h1 is alone on its line — the bar, the resume card / start button and every `.outline__actions` child (incl. the "⋯" summary) start below the h1's bottom, with the actions locator count asserted `== 3` (or `== 2` without saved work) so the loop cannot pass empty; **reservation**: on a card head without a menu the chevron's right edge reaches the summary's right edge (±2px), on a card head with a menu the chevron ends ≥ 44px before the row end and the "⋯" summary overlaps neither the chevron nor the count (mutants: drop the `:has()` qualifier; delete the rule) |
| `test_e2e_outline_phone_layout.py::test_outline_head_stays_on_one_line_on_desktop` | 4 head buttons on the h1's line at 1280 | at 1280: the actions sit in the top row, right of the title column, bottom-aligned with the bar (D1 puts the title alone in its column) |

Line numbers are approximate; the plan locates each by content.

**Existing suites that must stay green:** `test_outline_collapsible.py`, `test_outline_anchors.py`,
`test_tags_outline.py`, `test_publish_outline.py`, `test_resume_target.py`, `test_courses_views.py`,
`test_e2e_outline_tree.py`, `test_e2e_outline_phone_layout.py` (PR #397's guard — update its
geometry assertions only where the card layout legitimately supersedes them, and say so in the PR),
`test_e2e_tags.py`, `test_e2e_link_dialog.py`, `test_analytics_student_page.py` (its teacher-page
T11 test `test_rt_t11_teacher_chip_reads_lekcje` and `test_rt_t11_catalogs_drop_the_unused_msgids`
stay unchanged), every `test_*css*.py`.
