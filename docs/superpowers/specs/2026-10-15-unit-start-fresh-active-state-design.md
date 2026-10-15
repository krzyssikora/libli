# Unit-page "Start fresh": present by content, active only on saved work

## Purpose

The unit page offers "Start fresh" on every unit that *contains* a state-bearing element
(`has_stateful_elements`, `courses/views.py:519`; decision D1 of
`docs/superpowers/specs/2026-07-25-start-fresh-only-on-stateful-units-design.md`). A student who has
touched nothing still sees a live control and, on clicking it, lands on "Nothing to clear here.". The
course outline already gates its reset on stored state (`has_state`, `courses/rollups.py:229`). The
owner wants the unit page to stop offering a no-op reset, without giving up D1's property that the
control does not pop in and out.

Resolution: the control's **presence** stays a function of the lesson's content (unchanged); its
**enabled-ness** becomes a function of this viewer's stored practice state, and flips to enabled live,
without a reload, the first time a save stores something.

## Owner decisions (VERBATIM — do not reverse in review)

| # | Decision |
|---|---|
| D1' | Presence unchanged: the control renders iff `has_stateful_elements` (text/video-only units still have no control). |
| D2 | Enabled-ness: ACTIVE iff this viewer's stored element_state for the unit is non-empty (the `state` dict already in build_lesson_context — zero new queries); otherwise rendered INACTIVE (greyed, not clickable), NOT hidden — so nothing pops in/out and the unit head row never shifts. |
| D3 | Inactive markup: no `href`, `aria-disabled="true"`, clearly-disabled styling (token CSS, light+dark), title "Nothing to clear yet" (i18n, Polish catalog too). Active markup = today's link unchanged. |
| D4 | Live activation, approach (a): every client-side practice-state writer, on a SUCCESSFUL save whose echoed/stored state is non-empty, dispatches one shared document event (e.g. "libli:state-saved"); one small listener flips the inactive control to active (restores href, drops aria-disabled). Writers found: fillgate.js, filltable.js, guessnumber.js, markdone.js, reveal.js, state.js, switchgate.js, switchgrid.js, question.js (lesson answers via the second element_state write route); stepper.js goes via state.js — verify the list exhaustively. *(Verified in §4: these collapse to four network write sites.)* Approach (b) "activate on first interaction" was REJECTED (activates before/without a save). |
| D5 | A drift guard (in the spirit of tests/test_element_state_write_routes.py) fails if a state writer does not dispatch the event. |
| D6 | No reverse transition live: if a save empties state (e.g. an emptied answer), the control stays active until reload — accepted residual. |
| D7 | Update the July spec's D1 record so it is visibly superseded (not silently contradicted); update the views.py capability comment and the orphaned-blob test in courses/tests/test_reset_controls.py as the semantics now dictate (orphaned blob on a non-capability unit: still no control — presence is unchanged). |
| Scope | Unit page only; outline untouched. |

## Architecture / components

### 1. Server render (`templates/courses/_lesson_article.html:31-36`)

Inside the existing `{% if has_stateful_elements %}` block, branch on the stored state the view already
passes as `element_state` (`courses/views.py:580`, the int-keyed, read-side-filtered dict built at
`views.py:549-559`):

- **non-empty** → today's `<a class="btn btn--ghost btn--small lesson-unit__reset" href="…">` exactly
  as now (D3: active markup unchanged).
- **empty** → the same element, same classes (so the head row's box is identical — D2), but:
  - no `href`;
  - `aria-disabled="true"` and `role="link"` (an `<a>` without `href` has no implicit role; the
    explicit role makes assistive tech announce a dimmed link rather than plain text);
  - `title="{% trans 'Nothing to clear yet' %}"`;
  - `data-reset-href="…"` carrying the URL the active control would have, so the listener can
    restore it without the client constructing URLs;
  - a hook attribute for the listener, e.g. `data-reset-control`.

No new query: `element_state` is computed already. The `has_stateful_elements` computation and its
query shape are untouched (D1').

### 2. Styling (`core/static/core/css/app.css`, next to `.lesson-unit__reset` at ~`:763`)

`.lesson-unit__reset[aria-disabled="true"]`: reduced opacity in line with `.btn:disabled`
(`app.css:63`), `cursor: default`, and a hover override neutralising `.btn--ghost:hover`'s fill (the
same trap `.outline__toggle-all:disabled:hover` documents at `app.css:777-783`). **Do not** use
`pointer-events: none` — it would suppress the `title` tooltip that explains the state; with no `href`
the element has nothing to activate anyway. Token colours only; verify light and dark.

### 3. Event contract

One document-level `CustomEvent`, name `libli:state-saved`, dispatched on `document`, no payload
needed. Dispatched only after a save **succeeds** (`response.ok`) and the server reports that something
is now stored (see per-writer rules below). Never dispatched optimistically before the response.

### 4. The writers (exhaustive — verified against the source, 2026-10-15)

There are **four** network write sites into `UnitProgress.element_state` from the lesson page, not
nine: six widgets save through one shared helper.

| Site | Used by | Route | Response today | Change |
|---|---|---|---|---|
| `window.libliState.saveFlag` (`courses/static/courses/js/state.js:20-31`) | fillgate, filltable, guessnumber, stepper, switchgate, switchgrid | `element_state_save` (JSON) | `{"element", "state"}` echo, **ignored** (`.catch` only) | add `.then`: if `r.ok`, parse JSON; if `state` is a non-empty object → dispatch |
| `save()` in `reveal.js:27-38` | reveal gate | `element_state_save` (JSON) | echo, ignored | same as above |
| `markdone.js:57-80` | mark-done checklist | `element_state_save` (JSON) | echo, already adopted | in the existing success `.then`, after the sequence guard: if adopted blob is non-empty → dispatch |
| `question.js:48-79` | lesson questions with `RESTORABLE_IN_LESSON` | `check_answer` (`views.py:1120`) | HTML fragment | server: set response header `X-Libli-State-Saved: 1` when `check_answer` stored a **non-empty** answer (`views.py:1140-1146`, the non-`answer_is_empty` branch); client: if `r.ok` and the header is present → dispatch |

Notes:

- `element_state_save`'s REJECT path echoes what is **stored** (`views.py:1095-1098`), so "echo is
  non-empty" means "something is stored" on both the accept and reject paths — exactly D2's condition.
- An EMPTY save (stepper back to 0, every checkbox unticked, emptied answer) echoes `{}` / sets no
  header → no dispatch. The control never flips back to inactive live (D6).
- Each writer dispatches the event **itself** with a one-line `document.dispatchEvent(...)`. A shared
  helper in `state.js` is not usable: `markdone.js` and `question.js` load without `state.js`
  (`templates/courses/lesson_unit.html:76,90,98`).
- `question.js` also loads on `quiz_results.html`, where there is no control and `check_answer` is not
  the endpoint; the dispatch is harmless there (no listener target).
- The no-JS mark-done form posts and redirects back to the unit page, where the server render (§1)
  already shows the correct state. No change.
- `keepalive: true` stays on `saveFlag`/`reveal.js`; reading the body of a keepalive response is
  allowed while the page is alive.

### 5. Listener

A small script loaded on the lesson page iff `has_stateful_elements` (new
`courses/static/courses/js/reset_control.js`, or folded into an existing always-present lesson
script if the plan finds a better home). On `libli:state-saved`: for each `[data-reset-control]`
still `aria-disabled="true"`, set `href` from `data-reset-href`, remove `aria-disabled`, `role`
and `title`. Idempotent; removes nothing else, so the result matches the server-rendered active
markup. Deferred loading is safe: every dispatch follows a user interaction.

### 6. Decision-record updates (D7)

- July spec: under its D1, add a dated **"Superseded in part (2026-10-15)"** note pointing to this
  spec: presence still keys on capability; enabled-ness now keys on stored state, activated live.
- `courses/views.py:509-519` comment: keep "capability, NOT stored state" as the rule for
  **presence**, and add that the template now also reads `element_state` for **enabled-ness**.
- `courses/tests/test_reset_controls.py::test_an_orphaned_blob_does_not_bring_the_reset_link_back`:
  its assertion (no control on a non-capability unit with an orphaned blob) still holds under D1';
  update its docstring so it no longer describes the union rule as the untaken path in a way that
  contradicts the new semantics.

## Data flow

1. GET unit page → `build_lesson_context` already computes `has_stateful_elements` and `element_state`
   → template renders no control / inactive control / active control.
2. Student acts on a widget → writer POSTs → server stores → response (`state` echo, or header) →
   writer sees non-empty stored state → `document.dispatchEvent(new CustomEvent("libli:state-saved"))`.
3. Listener activates the control in place. Click → existing `progress_reset` GET interstitial
   (unchanged) → POST → redirect back to `next` → server render shows inactive again.

## Error handling

- Network failure or non-2xx → no dispatch; the control stays as it was. A failed save stored nothing,
  so "inactive" is correct.
- JSON parse failure on the echo → swallow (existing `.catch` style) and do not dispatch.
- Listener absent (script missing) → the control simply stays inactive until reload; never broken.
- Editor preview: `saveFlag`/`reveal` already return before fetching when `data-state-url` is `""`, so
  nothing dispatches; the preview has no reset control anyway.
- Previewers (non-enrolled staff) save and read their own state (`views.py:536-543`, `:1100-1107`), so
  the same rule applies to them unchanged.

## Testing

Falsify, don't just run: each test must go RED against a named mutant.

1. **Server render** (`courses/tests/test_reset_controls.py`): capability unit + enrolled student with
   no stored state → control present, no `href`, `aria-disabled="true"`, title text; same unit with a
   non-empty stored blob → today's active link with `href`; non-capability unit → no control (existing
   test stays). Mutants: render active unconditionally; gate on `has_stateful_elements` only.
2. **`check_answer` header** (unit test): non-empty answer on a restorable question → header present;
   empty answer → absent; non-restorable question → absent.
3. **Drift guard (D5)** (`tests/`): a source test that (a) asserts the four write sites dispatch
   `libli:state-saved`, and (b) finds every JS file under `courses/static/courses/js/` that reads a
   state-save URL (`stateUrl` / `data-state-url` / `data-markdone-url`) or is `question.js`, and asserts
   that set equals the expected writer set — so a fifth writer cannot ship silently. State its blind
   spots honestly, as `test_element_state_write_routes.py` does.
4. **e2e** (`tests/`, `-m e2e`, driving real UI): open a unit with a reveal gate → control inactive;
   open the gate → control becomes active **without reload** (wait on the attribute change, not a
   sleep); click it → interstitial loads. Also one `saveFlag` widget path and one question path
   (submitting a non-empty answer activates). An empty-answer submit must leave it inactive.
5. **Layout**: `tests/test_e2e_unit_head_layout.py` stays green; add an inactive-vs-active bounding-box
   equality assertion for the control.
6. **i18n**: `makemessages` + Polish translation for "Nothing to clear yet"; recompile `.mo`.
7. **Screenshots**: inactive and active control, light and dark.
