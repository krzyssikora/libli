# Baseline: tests slice 2 (builder filter + expand-all) can affect

Recorded 2026-07-29 on branch `worktree-builder-large-course-perf`, before Task 1
of the 17-task plan touches any behaviour. Purpose: let a later red be
classified as regression vs. intended migration.

Command used for exit codes / pass-fail (unit suite, single invocation):

```
uv run pytest tests/test_builder_lazy_scopes.py tests/test_builder_open_ids.py \
  tests/test_manage_node_ops.py tests/test_manage_element_ops.py \
  tests/test_manage_move_picker.py tests/test_manage_affordance.py \
  tests/test_builder_styles.py tests/test_builder_js_invariants.py \
  tests/test_manage_builder.py tests/test_builder_duplicate_unit.py \
  tests/test_manage_node_duplicate.py tests/test_tree_badge.py \
  tests/test_manage_duplicate_button.py \
  tests/test_i18n_po_health.py -q
```

Combined result: **exit 0**, 166 tests collected (verified separately via
`--collect-only -q`, since the run's own pytest summary line did not survive
capture to file — a known quirk in this environment; the dot-progress output
showed all `.` with no `F`/`E`, and exit code 0 independently confirms zero
failures/errors across the run).

## Unit / integration suite

| File | Exit (combined run) | Test count | Why this slice can affect it |
|---|---|---|---|
| `tests/test_builder_lazy_scopes.py` | 0 | 32 | Exercises the lazy-scope/collapsed-row rendering surface that expand-all must expand. |
| `tests/test_builder_open_ids.py` | 0 | 15 | Exercises the open-id/toggle-state surface (`withOpen`, `syncUrl`) this slice rewrites. |
| `tests/test_manage_node_ops.py` | 0 | 31 | **Encodes behaviour this slice CHANGES**: reorder now refuses under an active filter (Task 8). A red here after Task 8 lands is expected migration, not regression. |
| `tests/test_manage_element_ops.py` | 0 | 14 | Exercises node/element-ops surface adjacent to the filter/reorder changes. |
| `tests/test_manage_move_picker.py` | 0 | 2 | **Encodes behaviour this slice CHANGES**: the move picker gains a `q` param (Task 6). |
| `tests/test_manage_affordance.py` | 0 | 6 | Exercises builder affordance surface touched by disabling bulk controls under a filter (Task 9). |
| `tests/test_builder_styles.py` | 0 | 9 | **Encodes behaviour this slice CHANGES**: new selectors for the filter control and disabled bulk controls (Task 9). |
| `tests/test_builder_js_invariants.py` | 0 | 2 | Regexes `builder.js` source directly; the slice rewrites `withOpen`, the toggle `.then` chain, every `.catch`, `syncUrl`, the `swapping` lifecycle, and the picker fetch. |
| `tests/test_manage_builder.py` | 0 | 18 | Nothing in this slice edits it directly, but **Task 3 Step 8** and **Task 16 Step 1** both assert it green — baselined here so those assertions have a before-state. |
| `tests/test_builder_duplicate_unit.py` | 0 | 9 | `node_duplicate` gains `_stash_builder_force` beside `_persist_chain` (Task 7 Step 4), and `_tree_node.html`'s duplicate form gains a hidden `q` (Task 6 Step 4). Drives `builder_svc.duplicate_unit` directly and never calls the view — **a red here is a REGRESSION, not migration**. |
| `tests/test_manage_node_duplicate.py` | 0 | 5 | Same `_stash_builder_force`/hidden-`q` changes as above; all rows take the fetch/fragment path — **a red here is a REGRESSION, not migration**. |
| `tests/test_tree_badge.py` | 0 | 7 | Renders `_tree_node.html` **directly** via `render_to_string` with a hand-built context (`:55-56`) that defines neither `q` nor `filtered`; Tasks 6 and 8 edit this exact template, and both new `{% if %}` branches take their falsy arm here. Intended outcome — recorded as a before-state, not an assumption. |
| `tests/test_manage_duplicate_button.py` | 0 | 4 | Counts `data-op="duplicate"` in the builder page; Task 6 Step 4 adds an input inside that same form. |
| `tests/test_i18n_po_health.py` | 0 | 12 | Whole-catalog guard; this slice adds new translatable strings (filter control, expand/collapse-all) that must land in both `.po` catalogs. |

**Unit/integration total: 166 tests, combined exit 0.**

## e2e suite

Command used:

```
uv run pytest tests/test_e2e_builder_toggle.py tests/test_e2e_builder_reorder.py \
  tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py \
  tests/test_e2e_builder.py tests/test_e2e_builder_tree_layout.py \
  tests/test_e2e_inline_rename.py -m e2e -q
```

Combined result: **exit 0** (not exit 5 — the `-m e2e` marker was honoured), 63
tests collected (verified via `--collect-only -q -m e2e`), 1 test skipped in
the baseline run (visible as a single `s` in the dot-progress output; a skip
is not a failure and does not affect the exit code).

| File | Exit (combined run) | Test count | Why this slice can affect it |
|---|---|---|---|
| `tests/test_e2e_builder_toggle.py` | 0 | 16 | Exercises the toggle `.then` chain and `withOpen` this slice rewrites. |
| `tests/test_e2e_builder_reorder.py` | 0 | 2 | Exercises reorder, which Task 8 makes refuse under an active filter. |
| `tests/test_e2e_builder_ws2.py` | 0 | 9 | Exercises builder.js surface (toggle chain, `syncUrl`) this slice rewrites. |
| `tests/test_e2e_builder_authoring.py` | 0 | 3 | Exercises builder authoring flows over the same tree/toggle surface. |
| `tests/test_e2e_builder.py` | 0 | 3 | Exercises the core builder page/tree surface the filter and expand-all controls are added into. |
| `tests/test_e2e_builder_tree_layout.py` | 0 | 6 | Exercises tree layout/rendering that the new filter UI is added into. |
| `tests/test_e2e_inline_rename.py` | 0 | 24 | Drives the rename form in `_tree_node.html` (Task 6 Step 4 adds a hidden `q` to it) and builder.js's rename/`swapping` lifecycle — which Task 11 Step 7, Task 12's toggle-chain reshape, Task 13's `pointerdown` arming, and Task 14's M15 submit-handler conversion all touch. The single suite most exposed by this slice's JS work. |

**e2e total: 63 tests, combined exit 0 (62 passed + 1 skipped).**

## Rule going forward

Anything outside the two lists above going red during Tasks 1–16 is a
regression, not migration noise. Within the lists, only the five files named
explicitly as encoding changed behaviour (`test_manage_node_ops.py`,
`test_manage_move_picker.py`, `test_builder_styles.py`,
`test_builder_duplicate_unit.py`, `test_manage_node_duplicate.py`) may go red
as *intended* migration — and only once the specific task that changes that
behaviour has landed. `test_manage_builder.py` must stay green throughout;
it encodes no changed behaviour.

## M10 — investigated and DROPPED (Task 14 Step 2)

Recorded so the finding is not re-opened on the same false premise.

The slice-1 ledger entry read "`_persist_chain` re-runs `_children_map` on the
no-JS redirect path", implying a caller already holds that map. **It does not.**
Verified on this branch at Task 14:

- `_persist_chain` is defined at `courses/views_manage.py:602` and called from
  exactly three places — `node_add` (`:731`), `node_move`'s reparent branch
  (`:886`) and `node_duplicate` (`:986`).
- `grep -n "_children_map(" courses/` returns the definition at `:140` and call
  sites `:369`, `:406`, `:478`, `:610`, `:1006`, `:1081`. `:610` is *inside*
  `_persist_chain` itself; none of the three callers computes one.

So threading a map in would mean *adding* `_children_map(course)` to each caller
to pass it down: the same query, moved — no saving. A real fix would give
`_persist_chain` a narrower dependency (the container-pk set) and find a caller
that already has it; nobody on the no-JS redirect path does. **Dropped, not
deferred.**

## M16 — window blur disarm ships unfalsified here, and why (Task 14 fix wave)

Task 14's M16 change (`builder.js:754`, the `window.addEventListener("blur", ...)`
handler that clears `swapping`/`pointerFocus`) has no falsifying test in this
environment. Removing the line stays green here. This is a limitation of the
environment, not an oversight in the test suite:

- The only row in the suite that produces a *real* window blur is
  `tests/test_e2e_inline_rename.py:352 test_window_blur_does_not_commit`. It
  opens a second page in the same browser context and calls
  `other.bring_to_front()` — a genuine browser-level blur of the first page,
  not a synthetic `dispatchEvent`.
- That row carries a `document.hasFocus()` skip guard (`:372-376`): if the
  first page still reports focus after the second page is brought to front,
  the test skips itself rather than asserting on a state it cannot produce.
  In this environment that guard trips, so the row skips and M16 is never
  exercised.

The concrete check that would flip this: if a CI e2e run reports **0 skipped**
for `test_e2e_builder_*` / `test_e2e_inline_rename`, that means
`test_window_blur_does_not_commit` executed (not skipped) there, and an M16
row should be added to the ledger reflecting that it *is* falsifiable in that
environment. Do not add the M16 row itself here — in this environment it would
record a skip, not a falsification.

## Note on tooling

The combined pytest invocations' own final summary line (e.g. "166 passed in
Ns") did not appear in the captured output file in this environment, even
though it was redirected to a file rather than piped — only the dot-progress
line and the warnings summary were captured. Exit code 0 combined with an
all-dots progress line (no `F`/`E` characters) is sufficient to confirm zero
failures/errors; exact counts were independently confirmed via
`--collect-only -q` on the same file sets, which matches the dot counts.
