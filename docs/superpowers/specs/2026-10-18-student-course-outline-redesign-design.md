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
  (obligatory lesson units; quizzes and optional lessons excluded). The course totals are the sums
  over the outline roots. "Działy" (D1, D8) = the number of top-level **containers** (§3.2).
  The D1 label switches to the "nothing done yet" form when `required_done == 0`, independent of
  the resume state.
- **D3a "part card".** Every top-level container is a card (§3.2), so "part" = top-level
  container. D3 says reset moves into "⋯" menus; the same rule is applied to every container row
  that offers a reset today (chapters and deeper), so no "Zacznij od nowa" text link remains
  anywhere on the page. Each gets a "⋯" only when that container `has_state`.
- **D5 "chapter rows".** = the direct children of a card that are containers. Direct children that
  are units (e.g. a part-level "Podsumowanie" quiz) render as unit rows (§3.5) in the same list.
  "The in-progress row" = the chapter row containing the resume target when `resume.state` is
  `resume`, `next` or `gap` (at most one row on the page). It is the row the student will open
  next; partially-done rows elsewhere get the partial ring but no highlight.
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
    <div class="outline__bar" role="img" aria-label="…">fill</div>
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

- Title on its own line at every width (D1). Desktop: title + bar on the left, actions on the
  right of the same block (mockup desktop frame); phone: stacked, actions in one row (mockup).
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
   order (top-level units are skipped by the count); teal on `--primary-subtle` (D9);
2. title (existing `.outline-node__title`, wraps inside the card — D4);
3. progress bar `outline-card__bar` (amber fill on a light track, D9) + count. Count text: phone
   "18/62"; ≥ 641px "18 z 62 lekcji" (two spans toggled by CSS; the long form is the accessible
   one, the short form `aria-hidden`). A container with `required_total == 0` shows no bar and no
   count (as today, where the rollup chip is omitted);
4. the "+N dodatkowe" rollup chip when `additional_done` (unchanged text and condition);
5. chevron, at the end of the row (rotates 90° when open, as today).

The card's "⋯" menu (D3a) is a **sibling** of the `<details>`, never inside `<summary>` (same reason
as today's D9 reset link: a focusable control inside a button-role summary corrupts its accessible
name). It is grid-placed onto the head row exactly like today's `.outline-node__reset`, and the
card head reserves space for it only when present (generalising PR #397's `:has()` rule).

Top-level **units** (a course with units at the root) are not cards and get no number; they render
as unit rows (§3.5) in the list, in order, between cards.

Open/closed defaults are unchanged: every card (`data-depth="0"`) renders `open` server-side, as
today's top-level groups do, and `outline_tree.js` then restores the student's stored partition.
(The phone mockup shows only the first card open, i.e. a stored state; the server default is not
changed.)

### 3.3 List header (D8)

Between the tag filter bar and the list:

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

A container child of a card (chapter, or section directly under a part) renders as a row:
status circle, title, count "1/10", and (if it has children) the existing `<details>` disclosure
— tapping the row unfolds its own children **in place** inside the card (D5). It keeps its own
"⋯" when `has_state` (§2.1).

Status circle (inline SVG, `aria-hidden`; a visually-hidden status word follows it):

| state | condition | drawing | sr text |
|---|---|---|---|
| done | `required_total > 0 and required_done == required_total` | filled amber circle, dark tick | "Ukończone" / "Completed" (existing msgid) |
| in progress | `0 < required_done < required_total` | track ring + amber arc of `required_done/required_total` | "W toku" / "In progress" |
| not started | `required_done == 0` | empty ring | "Nierozpoczęte" / "Not started" |

A container with `required_total == 0` gets the empty ring and no count.

Highlight: the row whose subtree contains the resume target (§2.1) gets `is-current`
(sunken background, semi-bold title). Computed in the view (§4) — no template recursion over the
tree to find it.

Deeper levels (sections under a chapter, then units) keep today's nested-list presentation (left
hairline rule, uppercase section headings, unit rows), restyled only enough to sit inside the card
(no extra card chrome, D7 heights on phones).

### 3.5 Unit rows

Unchanged content: the `<a class="outline-unit">` link with title, unit kind chip, ✓ done badge;
then tag chips, the tag-edit affordance, and the notes badge as siblings. Additions:

- **Quiz rows (D6):** a quiz icon before the title and a "QUIZ" label (teal, D9). The existing
  unit kind chip (`_unit_kind_chip.html`) is the marker system for unit kinds; if it already emits
  a quiz chip the "QUIZ" label is that chip restyled, not a second label. (Plan must check what
  `unit_marker` returns for a quiz unit and pick one — never render two quiz labels.)
- **Lesson rows inside a card:** a status circle at the start (done = filled with tick; not done =
  empty ring), replacing nothing — the ✓ badge stays for done rows, since the outline's existing
  completion tests key on it.
- Rows are ≥ 44px tall at ≤ 640px (D7) via `min-height` on `.outline-unit` and on container heads;
  desktop keeps today's denser rows.

### 3.6 Resume card / start button (D2)

`_resume_card.html` gains a branch: when `resume.state == "start"`, render
`<a class="btn btn--primary outline__start" href="…same target URL…">Zacznij pierwszą lekcję →</a>`
instead of the card. New msgid "Start the first lesson" → "Zacznij pierwszą lekcję". The old
"Start the course" msgid becomes unused in this template; leave it in the catalogue only if another
template still uses it (grep), otherwise let `makemessages` mark it obsolete.

### 3.7 JavaScript (`outline_tree.js`)

No behaviour change is intended. The file must keep working with:

- the toggle button moved into `.outline-list__head` (it is found by `[data-outline-toggle-all]`,
  so no change expected);
- "⋯" menus: implemented as `<details class="outline-menu">` with a `<summary>` "⋯" button
  (`aria-label` "Więcej działań" / "More actions") and a link inside. They are **not**
  `.outline-node__group`, so the partition/expand-all logic ignores them — the selector
  `.outline-node__group` must stay scoped so a menu never counts as a group. A click inside a
  menu's summary must not trigger the outline's persistence write (`closest("summary.outline-node__head")`
  already excludes it — verify).
- Closing an open "⋯" menu on outside click / Escape is a small additive handler (or none — a
  `<details>` menu that stays open until re-clicked is acceptable); spec leaves the choice to the
  plan, but no global keydown handler that interferes with the editor (this page has none).

### 3.8 Styling

All tokens from `core/static/core/css/tokens.css`; no new colours. Card = `--surface-raised`,
`--border-subtle`, `--radius-lg`, padding `--space-4` (phone) / `--space-5` (desktop). Bars reuse
the glance track/fill tokens (`--border-subtle` track, `--glance-fill` fill). Badge =
`--primary-subtle` background, `--primary` text. Light and dark both come from the tokens; dark is
judged separately in screenshots.

The phone breakpoint is the one PR #397 introduced (`max-width: 640px`).

## 4. Data flow

`course_outline` (courses/views.py) already builds `outline` (with rollups and `has_state`),
`resume`, `has_saved_work`, `note_counts`, tag data. It adds, computed in Python (no new queries):

- `course_done` / `course_total`: sums of `required_done` / `required_total` over the roots;
- `section_count` (the "N" of D1/D8): number of roots with `is_unit == False`;
- per root container, its 1-based card number — stamped into the outline dicts as
  `item["card_number"]` (additive key, like `depth`; other consumers of `build_outline` ignore it
  because the stamping happens in the view on the view's own tree);
- the pk of the depth-1 container whose subtree contains `resume.node` when
  `resume.state in {"resume", "next", "gap"}` → `current_row_pk` (reuse
  `_stamp_current_chain`/`contains_current` if it is already stamped on this tree by
  `build_resume`; otherwise a pure dict walk);
- per container, its status (`done` / `progress` / `none`) and arc length, derived in the template
  from `required_done`/`required_total` or stamped in the view — plan's choice, no queries either way.

Bar widths: `round(100 * done / total)`; `None` when `total == 0` (no bar). Follow the glance
convention: never test widths by truthiness.

## 5. Error handling and edge cases

- **No visible units / everything done:** `resume` is `None`; no card/button. Progress label shows
  the done form ("199 z 199 lekcji ukończonych").
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
- **RTL / i18n:** Polish plural forms for every count message (`ngettext` / `blocktrans count`):
  "lekcja/lekcje/lekcji", "dział/działy/działów". English likewise.

## 6. Testing

Owner rules: TDD — a failing test first for each behaviour, mutants for each assertion (pick the
mutant from the failure mode), e2e drives the real UI, screenshots light + dark at 360 / 412 / 1280
looked at, dark judged separately. Never pass `-q`; grep the summary line. Run every
`tests/test_*css*.py` after CSS edits.

**Server-rendered (pytest + BeautifulSoup):**
- course head: title, bar `aria-label`, D1 label in both forms (nothing done / some done), plural
  forms in pl;
- D2: `start` state renders the primary button with the target URL and no card; `resume`/`next`/
  `gap` render the card with unchanged eyebrow text; non-enrolled viewer renders neither;
- D3/D3a: no visible "Zacznij od nowa" text link outside a "⋯" menu; course menu present iff
  `has_saved_work`; a card/row menu present iff that node `has_state`; reset hrefs unchanged;
- D4: card numbering skips top-level units; bar width/count; no bar when total is 0; "+N dodatkowe"
  still rendered;
- D5: status class per state for done / progress / none; exactly one `is-current` row, on the row
  containing the resume target, none when `resume` is `start`/`None`;
- D6: a quiz unit row has the quiz icon and exactly one quiz label;
- D8: "Działy · N" count; toggle button attributes unchanged;
- regression: tag filter `hidden` on cards/rows; `#node-N` ids on every `<li>`; notes badge, tag
  chips, tag-edit link, kind chip, ✓ badge still present on unit rows.

**e2e (Playwright, real UI, Polish UI via the header switch):**
- phone 360/412: no horizontal scroll; every unit row and container head ≥ 44px tall (D7); a long
  part title wraps inside the card beside its badge; tapping a chapter unfolds its lessons inside
  the card (D5); "⋯" opens and its reset link navigates to the confirm page;
- desktop 1280: card head on one line (badge, title, bar, count, chevron);
- expand-all / collapse-all still toggles every card and chapter, label flips;
- tag filter hides a card whose units are all filtered out, and shows it again on clear;
- deep link `#node-<chapter>` opens its card and highlights the row.

**Existing suites that must stay green:** `test_outline_collapsible.py`, `test_outline_anchors.py`,
`test_tags_outline.py`, `test_publish_outline.py`, `test_resume_target.py`, `test_courses_views.py`,
`test_e2e_outline_tree.py`, `test_e2e_outline_phone_layout.py` (PR #397's guard — update its
geometry assertions only where the card layout legitimately supersedes them, and say so in the PR),
`test_e2e_tags.py`, `test_e2e_link_dialog.py`, every `test_*css*.py`.
