# Phase 1b — UX/visual review triage (2026-06-16)

Issues found during manual testing of the merged 1b-i builder + 1b-ii editor/media,
plus settings and login. Grouped by workstream and type so we tackle them in a sane
order. Types: **BUG** (functional/correctness), **UX** (needs a design decision/mockup),
**STYLE** (CSS-only, no decision), **I18N**, **FEATURE** (new capability), **Q** (question).

> Item numbers (#1, #9a…) are **global**, assigned in original discovery order; tables
> are grouped by workstream, so ids look non-monotonic within any one table. "Done" is
> gated per type: **BUG** by the named regression test; **UX** by the accepted mockup it
> points to; **I18N** by the locale gate in the i18n section.

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

> **Not implementation-ready from this doc.** Every WS2 item (#5, #6, #8, #11, #9c) is gated
> on a design pass that must first produce accepted mockups under `docs/mockups/` — at minimum:
> a tree-with-connectors mockup, a control-cluster mockup, a "move" mockup showing the moving
> node's label, and a contextual-"+"-buttons mockup. Implementation of any WS2 item starts only
> after its mockup is accepted (same bar as the WS3 "already accepted" mockups). **#9c** (drag-and-drop)
> is the exception: scheduled **last** (after the move/reorder bugs) and given its own interaction
> mockup when scheduled, so it is **not** gated on this initial mockup batch.

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
| — | UX | Editor ｜ preview + media manager/picker restyle. | **Already mocked & accepted**: `docs/mockups/content-editor_accepted-A.html`, `docs/mockups/media-manager-and-picker_accepted.html`. Fidelity: match layout + token usage; minor spacing latitude allowed. |
| 12 | UX | Text toolbar: use **icon-only buttons with hover titles** (not text labels). | Update `_edit_text.html` toolbar + editor.css. |
| 14a | UX | **Unit title missing in the preview** — students must see it. | Add unit title to `_preview.html`/lesson render. |
| 14b | UX | "Back to builder" link **too close to the title**; prefer **icon buttons** for nav over text-labelled ones. | Spacing + nav affordance. |
| 13 | FEATURE | Iframe/embed: let authors **paste a full embed snippet** (e.g. GeoGebra `<iframe …>`), not just a URL — **parse out the `src`** and validate it against the existing embed-domain whitelist. | **Algorithm:** (1) parse with an HTML parser (e.g. `html.parser`/`lxml`), **never regex over raw HTML**; (2) collect `<iframe>` elements — reject if **zero** ("no iframe found"), reject if **>1** ("paste a single embed"); (3) take that iframe's `src`, then feed it to the **existing** `courses/validators.py:validate_embed_url`, which checks the host against `settings.ALLOWED_EMBED_DOMAINS` (`config/settings/base.py:154`). (4) Store only the validated `src` URL — **never** the raw pasted HTML; **on render**, rebuild the iframe from a fixed template (do **not** trust pasted `width`/`height`). **v1 ignores pasted dimensions entirely** and renders responsively (e.g. a 16:9 wrapper at `width:100%`), so there is nothing to clamp — revisit per-embed sizing only if a concrete need arises later. **Per-reject error messaging, first-match-wins precedence** (so each fixture maps to one deterministic message): malformed-parse → multi-iframe → no-iframe → missing-`src` → non-whitelisted-domain. **Dispatch** (on the **trimmed** input): empty/blank is rejected upstream by the form's `required` validation; if it starts with `<`, treat it as a snippet (steps 1–3); else feed it straight to `validate_embed_url`. The "else" branch has **no undefined boundary** — any non-snippet that isn't a valid whitelisted https URL (e.g. scheme-less `geogebra.org`) surfaces `validate_embed_url`'s ValidationError. `validate_embed_url` already rejects non-`https` schemes (`javascript:`/`data:`/`http:` srcs fail on either path). |

**#13 parser test fixtures** (build the extract/validate logic against these):

```html
<!-- valid: whitelisted host → extract src, accept -->
<iframe scrolling="no" title="demo" src="https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600" width="800" height="600" style="border:0px;"> </iframe>

<!-- reject: non-whitelisted host -->
<iframe src="https://evil.example.com/x"></iframe>

<!-- reject: no iframe at all (plain no-iframe reject; raw HTML is never stored, so there is no injection surface) -->
<img src=x onerror="alert(1)">

<!-- reject: iframe present but non-https scheme → validate_embed_url rejects (real XSS-vector guard) -->
<iframe src="javascript:alert(1)"></iframe>

<!-- reject: more than one iframe -->
<iframe src="https://www.geogebra.org/material/iframe/id/a"></iframe><iframe src="https://www.geogebra.org/material/iframe/id/b"></iframe>
```

## Workstream 4 — Settings & auth (mockups)

| # | Type | View | Issue | Notes |
|---|---|---|---|---|
| 4 | UX | `/settings/institution/` + `/settings/` | Dropdowns aren't user-friendly — **adopt bonnot's settings pattern** (sibling repo at `../bonnot`). | Inspect `../bonnot/mockups/views/settings.html` + bonnot's settings templates/CSS and mirror them. Likely segmented controls / radio cards / toggles instead of selects — confirm against the bonnot source before mocking. Output: an accepted `docs/mockups/settings_*.html` mockup before WS4 implementation (same bar as WS2/WS3). If `../bonnot` isn't checked out (other machine/CI), check it out — or copy the referenced bonnot files into `docs/mockups/_refs/` — before starting; the sibling-repo path is a hard dependency. |
| 3 | Q/UX | `/settings/institution/` | More settings expected later (e.g. institution **name**)? | **Answer: model already has** name/logo/branding/languages/theme + BrandColor; the form exposes a subset. Surface more when redesigning. |
| 15 | UX | `/accounts/login/` | Stock allauth login looks bad — spacing, sign-in button, "use third party" heading, the bullet list. | **Design already accepted** in Phase 0 (`docs/mockups/identity-directions_V2-chosen.html`): implement to that mockup (override `account/login.html`). Fidelity: match layout + token usage. Mostly build-to-mockup. |

## Cross-cutting — i18n sweep

| # | Type | Issue |
|---|---|---|
| 2 | I18N | Form field **descriptions/help text are English only** (applies to all forms) — wrap `help_text`/labels in `gettext` + translate. **Inventory:** `makemessages` can't find *un*wrapped literals, so the **starting** list is `grep -rEn --include=*.py "help_text=|label=|verbose_name=" .` (run from the repo root; recurses every app incl. `courses/`). **Not exhaustive** — also scan **positional** field labels (`CharField("Name", …)`), `choices=` tuples, `ValidationError("…")`/error messages, and `Meta.verbose_name`/`verbose_name_plural`. Wrap every hit, then `makemessages` picks them up. |
| 9b-i18n | I18N | "This changed elsewhere — refreshed to the latest." not translated to PL (the JS literal in `editor.js`/builder is not extracted). Distinct id from the WS1 **bug** #9b (the 409 itself); same notice string, different work. **Unify the msgid:** normalize the JS notice to the **same** wording as the already-translated server variant ("…reloaded to the latest.") so PL gets **one** msgid, not two near-duplicates. |
| — | I18N | Systematic pass: `makemessages` for untranslated msgids + per-template `{% trans %}` audit (incl. allauth overrides). **Target locale: PL.** **Done-gate:** after `makemessages`, the PL catalog (`locale/pl/LC_MESSAGES/django.po`) has **no empty `msgstr ""`** and **no `#, fuzzy`** entries — gate the **whole** `django.po` (the sweep is comprehensive, so the entire catalog must be clean, not a per-screen subset). |

## Proposed sequencing

1. **WS1 bugs first** — especially #1 (data-loss contrast) and #9 (reorder/move correctness). These need no design decisions; #9 needs systematic-debugging + regression tests.
2. **WS2 builder UX** — mock the tree/connectors, control cluster, move UI, contextual "+" buttons; then implement (incl. drag-drop last).
3. **WS3 editor/media** — implement the already-accepted editor/media mockups + #12/#14a/#14b; add the #13 embed-paste feature.
4. **WS4 settings & login** — inspect bonnot, mock settings + login (or build login to the existing mockup), implement.
5. **i18n sweep** — fold per-workstream (translate strings as each screen is touched) + a final catch-all pass.

---

## Phase-1 debugging findings & RESUME-HERE (2026-06-16)

Status vocabulary: **FIXED** below means *code-complete + automated-test-guarded* — it does
**not** mean user-verified. The items in "Visual confirmations still owed by the user" are
FIXED-in-code but await a human dark/light eyeball pass; only after that are they *verified*.
(Separately, #9 is **not** FIXED — see "FIX NOT YET STARTED" below; it is a different item.)

Status of WS1 so far:
- **#1 (dark buttons) — FIXED** (commit `3666483`). Root cause: editor reuses `.tree__act`/
  `.tree__inline` but doesn't load `builder.css`, and `reset.css` leaves `color:inherit`
  + UA-default background → light glyph on light button face = invisible in dark. Fixed by
  styling those classes in `editor.css` + regression guard `tests/test_editor_styles.py`.
- **#7 + #10 — FIXED (interim)** this session. Shared root cause: `app.css` sets
  `input[type=text], select { width:100% }`, but the inline `.tree__add` / `.move-picker`
  builder forms were never given counter-layout (neither class exists in `builder.css`),
  so controls stack full-width — the picker reads multi-line (#7) and the full-width kind
  `<select>` overlaps the title input (#10). Fixed with compact flex layout in `builder.css`
  (commit `5ee1046`). **CSS-only, intentionally test-light** — no regression guard was added (unlike
  #1's `test_editor_styles.py`), because WS2 #11 will delete these rules; per the done-vocabulary
  this is "interim," not a fully test-guarded FIXED.
  These forms get fully replaced by the WS2 redesign (contextual "+" buttons), so this is
  interim polish. **Cleanup:** when WS2 #11 lands, delete the interim `.tree__add` / `.move-picker`
  flex rules added to `builder.css` as part of that PR (don't leave dead CSS).

### #9 — root cause (investigation done; FIX NOT YET STARTED — resume here)

**#9** is an umbrella over the reorder/move cluster: **#9a** (the user-visible symptoms),
**#9b** (the spurious 409), **#9c** (drag-and-drop FEATURE). **#9b-i18n** is a separate i18n
item, not part of #9. "FIX NOT YET STARTED" applies to the #9a/#9b bugs; #9c is future work.

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
   a swap-target/stale-panel artifact related to (1). Do not fix until reproduced. **If the
   repro in step 1 below does NOT surface the disappearance:** do not close #9a — keep this
   symptom open, add targeted logging/instrumentation around `applyFragment`'s swap (log the
   swap target + node ids before/after), and ship that instrumentation so the next real-world
   occurrence is diagnosable. **Remove** it once the disappearance is reproduced and fixed (or
   gate it behind a debug flag) — don't leave permanent diagnostic logging, mirroring the
   #7/#10 dead-CSS cleanup.
4. **"Arrow-down on a section doesn't work":** NOT yet root-caused — submitter-absence (candidate 2)
   makes *up* fail while *down* default-works, so this is a **distinct** symptom (suspect a
   section-vs-unit ordering-scope issue). Reproduce in the step-1 e2e before fixing.

**#9a done-gate (per symptom):** close #9a only when **each** of its four symptoms is either fixed
(failing-test-first regression) or proven absent by the step-1 repro: (a) arrow-up no-op,
(b) node disappears, (c) can't move a lesson back, (d) arrow-down on a section.

**RESUME PLAN for #9 (fresh session, full budget):**
1. Write a Playwright e2e replaying the user's sequence on a Chapter1 ▸ [Intro lesson,
   Section A ▸ Core lesson] tree: reorder ↑/↓ on a unit and a section; reparent intro
   lesson Ch1→SectionA; then move it back; observe which step breaks. (Reproduce FIRST.)
   Seed the tree with `tests.factories.ContentNodeFactory`/`CourseFactory` (as
   `test_manage_node_ops.py` and the existing `test_stale_token_409_swap` e2e do) so the node
   **kinds** exactly match the bug's structure — a kind mismatch could mask the candidate-4
   ordering-scope symptom.
2. Fix the confirmed causes (panel refresh + direction robustness), failing-test-first.
3. Re-run the e2e + `test_manage_node_ops.py` + full suite.

### #9b-i18n — untranslated JS notice (documented for next session)

`builder.js` (`notice("This changed elsewhere — refreshed to the latest.")`) and
`editor.js` use **JS string literals**, which `makemessages` never extracts. (The server
template variant "…reloaded to the latest." IS translated.) **Fix direction:** pass the
translated string into the DOM via a `data-` attribute on the builder/editor root
(`{% trans %}`-rendered) and have the JS read it — no JS gettext catalog needed. Touches
`builder.js`, `editor.js`, their host templates, and the `.po`.

### Visual confirmations still owed by the user (dev server)

#1 (editor ↑/↓/Delete visible in dark), #7 (move picker one-line), #10 (add-node row tidy,
no overlap). Hard-refresh (Ctrl+F5) after a `collectstatic` (whitenoise manifest storage).
