# LAL widget mapping — Group A (render-correctness, parser-only)

**Date:** 2026-07-20
**Branch:** `worktree-matematyka-content-import`
**Scope:** parser-only fixes in `scripts/lal_import/lesson.py` + `tables.py`. No new
loader builders, no new element types. Fixes every concrete pilot rendering
complaint. Group B (native interactive-widget elements) is a separate later pass.

## Background

The pilot (part-001) rendered interactive/GeoGebra units badly. Root causes, all
confirmed against real corpus files:

- **GeoGebra missing + chrome leak** (`032_zbiory.html`): the applet lives inside
  `<div class="question_text">`, which the parser emits *wholesale* via
  `decode_contents()`. nh3 then strips the `<iframe>` and keeps the
  `.iframe_small`/`.info_iframe` fallback text. `_emit_figure` already drops chrome
  correctly — it just never runs because `question_text` swallows the figure.
- **Fragmented inline math + dropped commas** (`u/8`, `u/12`): descending a container
  emits each bare `\(..\)` text node and each inline `<span>`/`<div class=switch_value>`
  as its own TextElement; the connective commas/spaces between them are orphaned.
- **Leaked feedback** ("świetnie!", "Brawo!"): `.success`/`.failure` divs start
  `hidden` and are JS-revealed; the parser emits their text as visible content.
- **Interactive widgets fragmented** (`035_zbiory.html` switch): a `.switch_options`
  block descends into ~20 tiny broken text elements.

Note: **flags do not measure render quality** — part-001 has only 9 flags (8 href,
1 span) yet renders badly, because bad content maps to the *wrong* element (text
instead of iframe), which is never flagged.

## Widget interaction reference (from `script.js` + `styles.css`)

Every interactive unit is a `div[id^=question]` containing: a `.question`/`.example`
label (JS replaces its text with "Zadanie N"/"Przykład N"), a `.question_text`
prompt (prose + optional GeoGebra figure/table), one interactive widget, and hidden
`.success`/`.failure` feedback. Answer keys live in an inline `<script>` per file
(`localStorage.setItem("correct_choices", {20:[2,2,2,1,2]})`), so faithful graded
mapping is possible in Group B.

Interactive widget classes (→ Group B native target):
`switch_line`/`switch_value`/`switch_confirm` → SwitchGridElement;
`switch_show_next`/`switch_step` → Stepper+Switch;
`show_next`/`show_step` → StepperElement; `fill_show_next`/`fill_step`/`fill_answer`
→ Stepper+fill; `one_choice`/`confirm_choice` → ChoiceGridQuestionElement;
`multi_many_ans`/`confirm_multiple` → MultiGridQuestionElement;
`mult_choice`/`confirm_feedback_multiple` → ChoiceQuestionElement (per-option
feedback); `multi_ans`/`confirm_button_feedback` → ChoiceQuestion/Multi;
`truth`/`false`/`confirmTF` → SwitchGrid/ChoiceGrid; `table_input`/`table_answers`
→ FillInTableElement; `ks_tabs` → TabsElement; `more_less_input` → GuessNumberElement;
`show_slides`/`slide_show` → GalleryElement; `mark_done` → MarkDoneElement;
`data-binary-choose` → deferred.

## Group A rules

1. **Descend `question_text`** when it has block children (reuse `_has_block_child`);
   inline-only `question_text` still emits one TextElement (unchanged). Reaches
   `_emit_figure` → GeoGebra IframeElement, chrome dropped; renders prompt tables/prose.
2. **Drop chrome nodes** by class: `success`, `failure`, `ans_warning`,
   `inline_warning`, `iframe_small`, `iframe_telemetry`, `info_iframe`, `mailto_tag`.
   Dropped silently (no flag) — they are JS-only presentation.
3. **Coalesce inline runs** while descending: consecutive NavigableStrings + inline
   tags (`span`, `strong`, `em`, `b`, `i`, `u`, `code`, `a`, `br`, `sub`, `sup`) +
   bare `\(..\)` merge into ONE `<p>` TextElement (preserving connective text).
   Block children (`p`, `div`, `table`, `figure`, headings, `ul`/`ol`, `details`,
   media) flush the buffer first. Fixes fragmentation + comma loss.
4. **Reverse-order `show_solution`**: `_next_solution` scans forward then backward
   for the nearest unconsumed `.question_solution`.
5. **Stop flagging pure-fragment hrefs**: `href` starting with `#` is an in-page
   anchor (tab/toc), not a dropped link — not flagged.
6. **Tables**: rectangular styled tables already map to TableElement; only
   span/nested/ragged flag. Confirm with a real styled-table test; no change expected.
7. **Not-yet-native interactive widgets** → **one flagged placeholder block**:
   a `div[id^=question]` (or standalone container) holding any interactive marker
   class emits its prompt normally, then the interactive widget container as a single
   `{type:html, flagged:True, reason:"interactive_widget:<kind> (Group B)"}`. No
   fragmentation, no answer leak (keys are in `<script>`, not rendered; feedback
   dropped by rule 2). Loads with `--allow-html`. Group B replaces each with its
   native element.

## Verification

- Real-file unit tests on `032_zbiory.html` (exactly one iframe, zero "aplet" chrome
  text) and `035_zbiory.html` (prompt text + table + one placeholder, no leaked
  "świetnie", no 20-fragment blow-up).
- Backward-compat: existing `tests/lal_import/test_lesson.py` stays green (inline-only
  `question_text` and bare-node coalescing preserve current behavior).
- Re-seed part-001 with `--force`, reload into `libli_mat`, hand URLs to the user.

## Out of scope (Group B, later)

Native mapping of each interactive widget to its libli element (SwitchGrid, Stepper,
ChoiceGrid, MultiGrid, FillInTable, Tabs, Gallery, GuessNumber, MarkDone), including
answer-key extraction from the inline `<script>`. Any widget that genuinely cannot
map to a libli element is surfaced to the user for discussion.
