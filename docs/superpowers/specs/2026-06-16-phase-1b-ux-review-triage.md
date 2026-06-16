# Phase 1b — UX/visual review triage (2026-06-16)

Issues found during manual testing of the merged 1b-i builder + 1b-ii editor/media,
plus settings and login. Grouped by workstream and type so we tackle them in a sane
order. Types: **BUG** (functional/correctness), **UX** (needs a design decision/mockup),
**STYLE** (CSS-only, no decision), **I18N**, **FEATURE** (new capability), **Q** (question).

> Reframing: this is no longer just "visual polish of 1b-ii." It now spans **functional
> bug-fixes in the 1b-i builder**, a **builder UX overhaul**, **editor/settings/login
> redesign**, a **new embed feature**, and an **i18n sweep**.

## Workstream 1 — Bugs & data-safety (do FIRST; mostly no design decisions)

| # | Type | View | Issue | Notes |
|---|---|---|---|---|
| 1 | BUG/STYLE | editor + builder | **Dark-theme action buttons render white/invisible** → user deleted elements blind (data loss). | User: "first to be fixed." Likely missing dark-token contrast on icon/ghost buttons. |
| 9a | BUG | builder | **Reorder broken:** Arrow-Up does nothing; arrows sometimes make a node "disappear"; can't move a lesson back (Section A → Chapter 1); arrow-down on a section doesn't work. | Needs systematic-debugging; in 1b-i `element/node` move + ordering. |
| 9b | BUG | builder | **Spurious "This changed elsewhere — refreshed to the latest." 409** on a normal move-then-choose-target. | Optimistic `updated`-token desync after a prior op; investigate token refresh in move flow. |
| 7 | BUG/UX | builder | "Move" shows a **multiline** explanatory comment where a one-liner is intended. | Likely a layout/whitespace bug in the move picker. |
| 10 | BUG/UX | builder | New-node **input boxes partially hidden behind the dropdowns** (stacking/overflow). | z-index/overflow/layout. |

## Workstream 2 — Builder UX overhaul (needs mockups)

| # | Type | Issue | Notes |
|---|---|---|---|
| 5 | UX | Tree hierarchy isn't obvious — add **connector lines** (vertical/horizontal) to show the structure. | Indentation alone is too subtle. |
| 6 | UX | Up/down arrows + move/delete look **messy; align them** into a consistent control cluster. | Pairs with #1 (contrast). |
| 8 | UX | In "Move", you **can't see which node is being moved** — easy to mis-target. | Show the moving node's label prominently. |
| 11 | UX | Replace the node-add **inputs + kind dropdown** (which also shows *forbidden* kinds) with contextual **tiny "+" buttons** ("+ chapter", "+ unit"…) placed where each kind is legal. | Removes invalid choices by construction; cleaner. |
| 9c | UX/FEATURE | Add **drag-and-drop** reordering (beyond ↑/↓). | Bigger; do after the move/reorder **bugs** are fixed. |

## Workstream 3 — Editor & media polish (mockups; editor/media already mostly designed)

| # | Type | Issue | Notes |
|---|---|---|---|
| — | UX | Editor ｜ preview + media manager/picker restyle. | **Already mocked & accepted** (`content-editor_accepted-A.html`, `media-manager-and-picker_accepted.html`). |
| 12 | UX | Text toolbar: use **icon-only buttons with hover titles** (not text labels). | Update `_edit_text.html` toolbar + editor.css. |
| 14a | UX | **Unit title missing in the preview** — students must see it. | Add unit title to `_preview.html`/lesson render. |
| 14b | UX | "Back to builder" link **too close to the title**; prefer **icon buttons** for nav over text-labelled ones. | Spacing + nav affordance. |
| 13 | FEATURE | Iframe/embed: let authors **paste a full embed snippet** (e.g. GeoGebra `<iframe …>`), not just a URL — **parse out the `src`** and validate it against the existing embed-domain whitelist. | Security: still whitelist-gated; extract/validate, never trust raw pasted HTML. |

## Workstream 4 — Settings & auth (mockups)

| # | Type | View | Issue | Notes |
|---|---|---|---|---|
| 4 | UX | `/settings/institution/` + `/settings/` | Dropdowns aren't user-friendly — **adopt bonnot's settings pattern** (sibling repo available to inspect). | Likely segmented controls / radio cards / toggles instead of selects. |
| 3 | Q/UX | `/settings/institution/` | More settings expected later (e.g. institution **name**)? | **Answer: model already has** name/logo/branding/languages/theme + BrandColor; the form exposes a subset. Surface more when redesigning. |
| 15 | UX | `/accounts/login/` | Stock allauth login looks bad — spacing, sign-in button, "use third party" heading, the bullet list. | **Design already accepted** in Phase 0 (`identity-directions_V2-chosen.html`): implement to that mockup (override `account/login.html`). Mostly build-to-mockup. |

## Cross-cutting — i18n sweep

| # | Type | Issue |
|---|---|---|
| 2 | I18N | Form field **descriptions/help text are English only** (applies to all forms) — wrap `help_text`/labels in `gettext` + translate. |
| 9b | I18N | "This changed elsewhere — refreshed to the latest." not translated to PL (the JS literal in `editor.js`/builder is not extracted). |
| — | I18N | Systematic pass: `makemessages` for untranslated msgids + per-template `{% trans %}` audit (incl. allauth overrides). |

## Proposed sequencing

1. **WS1 bugs first** — especially #1 (data-loss contrast) and #9 (reorder/move correctness). These need no design decisions; #9 needs systematic-debugging + regression tests.
2. **WS2 builder UX** — mock the tree/connectors, control cluster, move UI, contextual "+" buttons; then implement (incl. drag-drop last).
3. **WS3 editor/media** — implement the already-accepted editor/media mockups + #12/#14a/#14b; add the #13 embed-paste feature.
4. **WS4 settings & login** — inspect bonnot, mock settings + login (or build login to the existing mockup), implement.
5. **i18n sweep** — fold per-workstream (translate strings as each screen is touched) + a final catch-all pass.

---

## Phase-1 debugging findings & RESUME-HERE (2026-06-16)

Status of WS1 so far:
- **#1 (dark buttons) — FIXED** (commit `3666483`). Root cause: editor reuses `.tree__act`/
  `.tree__inline` but doesn't load `builder.css`, and `reset.css` leaves `color:inherit`
  + UA-default background → light glyph on light button face = invisible in dark. Fixed by
  styling those classes in `editor.css` + regression guard `tests/test_editor_styles.py`.
- **#7 + #10 — FIXED (interim)** this session. Shared root cause: `app.css` sets
  `input[type=text], select { width:100% }`, but the inline `.tree__add` / `.move-picker`
  builder forms were never given counter-layout (neither class exists in `builder.css`),
  so controls stack full-width — the picker reads multi-line (#7) and the full-width kind
  `<select>` overlaps the title input (#10). Fixed with compact flex layout in `builder.css`.
  These forms get fully replaced by the WS2 redesign (contextual "+" buttons), so this is
  interim polish.

### #9 — root cause (investigation done; FIX NOT YET STARTED — resume here)

**The backend is correct and fully tested** (`tests/test_manage_node_ops.py` green: reorder,
reparent, position, 409/422, cascade). The bugs are in the **frontend swap** (`builder.js`)
and the panel lifecycle. Confirmed/strong candidates:

1. **Spurious "This changed elsewhere" 409 (move-back):** after any tree mutation,
   `builder.js` `applyFragment` swaps only the tree `[data-scope]` element — it **never
   refreshes the detail/Move panel** (`[data-panel]`). So a Move picker (or rename/settings
   form) left in the panel keeps a **stale token**; submitting it after another op →
   `_check_token` 409. This matches "move the lesson, choose the section → 'This changed
   elsewhere'". **Fix direction:** after a successful op, clear or re-fetch the panel (or
   have the picker re-read the moved node's fresh token from the swapped tree DOM).
2. **"Arrow up does nothing":** ↑/↓ are two submit buttons in one `<form>`; `builder.js`
   relies on `e.submitter` to append `direction`. If `e.submitter` is ever absent the
   server defaults to "down" (`move_in_list`: `j=i+1` when direction!="up"), so up looks
   dead. **Fix direction:** use `new FormData(form, e.submitter)` (2-arg) AND/OR carry
   `direction` on each button via separate forms / a data attribute; default-guard the view.
3. **"Node disappears":** NOT yet reproduced — needs a Playwright repro to confirm; likely
   a swap-target/stale-panel artifact related to (1). Do not fix until reproduced.

**RESUME PLAN for #9 (fresh session, full budget):**
1. Write a Playwright e2e replaying the user's sequence on a Chapter1 ▸ [Intro lesson,
   Section A ▸ Core lesson] tree: reorder ↑/↓ on a unit and a section; reparent intro
   lesson Ch1→SectionA; then move it back; observe which step breaks. (Reproduce FIRST.)
2. Fix the confirmed causes (panel refresh + direction robustness), failing-test-first.
3. Re-run the e2e + `test_manage_node_ops.py` + full suite.

### #9b — untranslated JS notice (documented for next session)

`builder.js` (`notice("This changed elsewhere — refreshed to the latest.")`) and
`editor.js` use **JS string literals**, which `makemessages` never extracts. (The server
template variant "…reloaded to the latest." IS translated.) **Fix direction:** pass the
translated string into the DOM via a `data-` attribute on the builder/editor root
(`{% trans %}`-rendered) and have the JS read it — no JS gettext catalog needed. Touches
`builder.js`, `editor.js`, their host templates, and the `.po`.

### Visual confirmations still owed by the user (dev server)

#1 (editor ↑/↓/Delete visible in dark), #7 (move picker one-line), #10 (add-node row tidy,
no overlap). Hard-refresh (Ctrl+F5) after a `collectstatic` (whitenoise manifest storage).
