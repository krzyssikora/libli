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
    explicit role makes assistive tech that reaches it in browse mode announce a dimmed link rather
    than plain text);
  - **deliberately unfocusable** (no `tabindex`): an `<a>` without `href` is out of the tab order, the
    same as a native disabled button. The `title` is a mouse affordance only; the greyed styling
    carries the meaning. On activation the restored `href` puts it back in the tab order.
  - `title="{% trans 'Nothing to clear yet' %}"`; Polish msgstr **"Nie ma nic do
    wyczyszczenia"** (owner-confirmed 2026-10-15; no trailing period, it is a tooltip). Clear any
    `#, fuzzy` pre-fill `makemessages` proposes (it is likely to derive one from "Nothing to clear
    here." → "Nie ma tu nic do wyczyszczenia.").
  - `data-reset-href="…"` carrying the URL the active control would have, so the listener can
    restore it without the client constructing URLs;
  - a hook attribute for the listener, e.g. `data-reset-control`.

No new query: `element_state` is computed already. The `has_stateful_elements` computation and its
query shape are untouched (D1').

**Boundaries of the predicate (accepted).** `element_state` is read-side filtered (non-dict values
and non-int keys dropped), whereas `progress_reset` and the outline's `has_state` test the raw column
(`~Q(element_state={})`). So:
- a row holding **only** a drifted blob renders INACTIVE although a reset would clear it. Accepted,
  like D6; the outline's reset still offers it.
- an orphaned blob (its element deleted) on a **capability** unit renders ACTIVE. Correct, because the
  reset really clears it.

### 2. Styling (`core/static/core/css/app.css`, next to `.lesson-unit__reset` at ~`:763`)

`.lesson-unit__reset[aria-disabled="true"]`: reduced opacity in line with `.btn:disabled`
(`app.css:63`), `cursor: default`, and an override on **both** `:hover` and `:active`
(`background: transparent`, at specificity above `.btn:active`'s (0,2,0)). Without it,
`.btn--ghost:hover`'s fill and `.btn:active { background: var(--primary-active) }` (`app.css:44`,
never overridden by `.btn--ghost`) repaint the "inactive" control as live on hover and press. This is
the trap `.outline__toggle-all:disabled:hover` documents at `app.css:777-783`; native `:disabled`
blocked `:active` there, but `aria-disabled` on an `<a>` does not. **Do not** use
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
| `question.js:48-79` | lesson questions with `RESTORABLE_IN_LESSON` | `check_answer` (`views.py:1120`) | HTML fragment | server: compute ONE local flag `stored_answer` in the `RESTORABLE_IN_LESSON` block (`views.py:1140-1146`; true only on the non-`answer_is_empty` branch), and set response header `X-Libli-State-Saved: 1` on **every** fragment response when it is true. There are two: the `INLINE_LESSON_FEEDBACK` full-element render (~`:1150`) and the `_question_feedback.html` render (~`:1165`, used by non-inline restorable types such as extended response). The no-JS full-page branch does not set it (no client reads it there). Client: dispatch in the **first** `.then`, where `r` is in scope: only the dispatch is guarded, and `return r.text()` stays **unconditional**, exactly as today:
`if (r.ok && r.headers.get(H)) document.dispatchEvent(...); return r.text();`. It must not go at the bottom of the second `.then`, because the inline branch's early `return` (`question.js:~73`) would skip it |

Notes:

- `element_state_save`'s REJECT path echoes what is **stored** (`views.py:1095-1098`), so "echo is
  non-empty" means "something is stored" on both the accept and reject paths — exactly D2's condition.
- An EMPTY save (stepper below 2 shown steps per `courses/state.py:104`, every checkbox unticked, emptied answer) echoes `{}` / sets no
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

A new file `courses/static/courses/js/reset_control.js`, included from `lesson_unit.html`'s script
block under `{% if has_stateful_elements %}` (the same condition as the control itself). On `libli:state-saved`: for each `[data-reset-control]`
still `aria-disabled="true"`, set `href` from `data-reset-href`, remove `aria-disabled`, `role`
and `title`. Idempotent; removes nothing else. The result equals the server-rendered active control
in `class`, `href`, text, and the absence of `aria-disabled`/`role`/`title`. The `data-reset-control`
/ `data-reset-href` hooks deliberately **remain** (they make the listener idempotent), so tests must
compare those properties, not `outerHTML`. The server-rendered active control carries **no**
`data-reset-*` attributes (D3: unchanged); the hooks exist only on the inactive render and survive
activation. **Script order:** include `reset_control.js` in `lesson_unit.html`'s script block
**before** `question.js`, `state.js`, `reveal.js` and `markdone.js`. Deferred scripts run in
document order, so the listener is attached before any writer can dispatch.

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
- `saveFlag` has no sequence guard, so out-of-order echoes (e.g. a stepper going to 2 shown steps and
  quickly back below 2) can activate the control while nothing is stored. Accepted, same class as D6.
- bfcache restore, or a second tab left open after a reset elsewhere, still shows an ACTIVE control
  that leads to "Nothing to clear here.". Same class as D6; accepted, no `pageshow` handling.
- Previewers (non-enrolled staff) save and read their own state (`views.py:536-543`, `:1100-1107`), so
  the same rule applies to them unchanged.

## Testing

Falsify, don't just run: each test must go RED against a named mutant.

1. **Server render** (`courses/tests/test_reset_controls.py`): capability unit + enrolled student with
   no stored state → control present, no `href`, `aria-disabled="true"`, title text; same unit with a
   non-empty stored blob → today's active link with `href`; non-capability unit → no control (existing
   test stays). **Parse the `.lesson-unit__reset` element** (e.g. BeautifulSoup) and assert on its
   attributes: `href == <url>` versus `href` absent. A substring check on the reset URL passes in
   both states, because the URL also appears in `data-reset-href`. Mutants (one per failure mode):
   "render active unconditionally", which is today's template and must turn the empty-state test RED;
   "render inactive unconditionally", which must turn the non-empty-blob test RED; and "branch on
   `has_stateful_elements and element_state` with the inactive branch dropped", which must turn the
   presence-when-empty test RED.
   **Existing presence tests** (`test_lesson_page_links_to_the_reset_interstitial`, its
   `_nested_in_a_tab` / `_question_only_unit` variants, `test_views_calls_the_state_helper…`) assert
   `_reset_url(...) in body` with no stored state. They stay green but now pin **D1' presence only**.
   Update their names or docstrings to say so, so nobody reads them as active-ness coverage.
2. **`check_answer` header** (unit test): non-empty answer on a restorable question → header present,
   for **one inline type** (e.g. choice / fill-blank) **and one non-inline restorable type** (e.g.
   extended response), covering both fragment return points; empty answer → absent; non-restorable
   question → absent. Mutant: header on only one return branch.
3. **Drift guard (D5)** (`tests/`): a source test over comment-stripped JS.
   (a) **Placement, not presence:** in each of the four write sites the dispatch must sit inside the
   response-handling `.then` (after the `r.ok` / header check), never before `fetch` and never
   unconditional on an empty echo. Implement this as a structural check, e.g. the dispatch text
   appears after the `fetch(` and inside the success callback, next to the non-empty guard. A bare
   `"libli:state-saved" in src` check is insufficient. Mutants it must catch: dispatch moved above
   `fetch`; non-empty guard removed. Also assert that `question.js` reads **exactly** the header
   name the server sets: define it once as a Python constant (e.g. `STATE_SAVED_HEADER` in
   `courses/views.py`), have the guard import it, and check that the literal appears in
   `question.js`'s comment-stripped source. Mutant: a typo on either side. Do the same for the
**event name**: keep it as one Python constant in the guard, and assert that each of the four write
sites contains exactly `new CustomEvent("libli:state-saved"` and that `reset_control.js` contains
`addEventListener("libli:state-saved"` (comment-stripped). Mutant: event-name typo in one writer.
   (b) **Writer set:** detect JS files under `courses/static/courses/js/` by **code shapes** only
   (`dataset.stateUrl`, `getAttribute("data-state-url")`, `getAttribute("data-markdone-url")`,
   matched after stripping comments, so `stepper.js:61`'s comment does not count). Assert the
   detected set equals literally `{state.js, reveal.js, markdone.js}`, with `question.js` named
   explicitly as the `check_answer` writer. **Blind spots, stated:** a widget posting to
   `element_state_save` through a differently named attribute, a template-injected URL, or a new
   server route that writes state from a different endpoint is not caught. A tripwire, not a proof.
4. **e2e** (`tests/`, `-m e2e`, driving real UI): open a unit with a reveal gate → control inactive;
   open the gate → control becomes active **without reload** (wait on the attribute change, not a
   sleep); click it → the interstitial shows a **non-zero** count, i.e. NOT "Nothing to clear here."
   (this proves the activation tracked real stored state; "interstitial loads" alone passes on the
   broken build). In this reveal-gate test, also assert the full activation contract (§5): after
   activation `aria-disabled`, `role` and `title` are absent, `href` equals the server-rendered
   active URL, and the computed opacity equals an active control's. Mutants: the listener omits
   `removeAttribute('aria-disabled')`; the listener omits `removeAttribute('title')`. Also: one `saveFlag` path, namely a **fill gate answered correctly** (the check
   passes, then `saveFlag({open: true})` stores a non-empty blob; wrong answers store nothing); one
   question path using an **inline** type such as choice (a non-empty answer activates; an
   empty-answer submit on a fresh page leaves it inactive). Assert that only **after** a
   post-response signal: the second `.then`'s fragment/form-body swap, which runs after the
   first-`.then` dispatch line. Asserting right after the click reads the pre-response DOM. Mutant:
   "header set when `answer_is_empty`" must turn this RED. This path is the **only** guard against
   the mutant "question.js dispatch moved to the end of the second `.then`", which drift guard (a)
   cannot see; do not trim it; and the **mark-done** path: tick, wait
   for that save's response (not the attribute), see active, untick everything, **wait for the response
   of the final untick save** (the one whose echo is `{}`, e.g. `expect_response` on that
   `element_state_save` POST), and only then assert it **stays active** (D6) and reload; after the
   reload it is inactive. Do not assert "tick + untick → inactive" live: it
   races the first echo against the seq guard and flakes on a correct build.
5. **Layout**: `tests/test_e2e_unit_head_layout.py` stays green. Add a **same-page** inactive-vs-active
   bounding-box equality assertion: measure the inactive control, trigger a real save, wait for
   `href` to appear, then measure again (no second page load). Mutant: an inactive-only `padding` or
   `border-width` change. Also check the **pressed** state: with `mouse.down()` and no `up()` on the
   inactive control, the computed background is transparent. Mutant: drop the `:active` selector
   from the override.
6. **i18n**: `makemessages` + Polish msgstr "Nie ma nic do wyczyszczenia" for "Nothing to clear yet" (clear any fuzzy pre-fill); recompile `.mo`.
7. **Screenshots**: inactive and active control, light and dark.
