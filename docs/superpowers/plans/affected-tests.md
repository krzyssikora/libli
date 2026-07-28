# Affected tests: builder lazy-tree rendering (Task 0b)

Enumerated **before** Task 3 changes `_tree_node.html` to render only open scopes. Purpose:
give Tasks 6–10 a bounded green gate — "only these files may fail; anything else flagged
here as NOT AFFECTED going red is a real regression."

`SIZE_THRESHOLD = 150` nodes (constant will live in `courses/builder_open.py`, created by
Task 1). A course at or under this size opens **fully** on a bare page load (precedence step
4), so any fixture under 150 nodes keeps rendering the whole tree today AND after Task 3 —
it never exercises the lazy/collapsed path. That is flagged explicitly per file below as a
**trap**: green, but no longer meaningful coverage of the new behaviour.

Baseline (this run, both green — see `.superpowers/sdd/task-0b-report.md` for full output):
`uv run pytest tests/ -q` and `uv run pytest tests/ -q -m e2e`.

## Sweep

```
grep -rln "manage_builder\|/build/\|data-scope\|tree__row\|data-panel-url\|data-node-move-url" tests/ | sort
```

This returned **44 files** (broader than the brief's "expect at least" list of 14 — a
file-name prefix would have missed several, e.g. `test_element_editor_ops.py`,
`test_editor_page.py`, `test_media_manager.py`, `test_dashboard_panels.py`,
`test_code_field_seed.py`, `test_manage_element_ops.py` only shows up via `element_move`/
`element_delete` review, not the grep itself). Every file is classified below.

## Classification table

Legend for **Treatment**: `open=all` param · `expand_to()` (helper from `tests/helpers_builder.py`,
created in a later task) · re-measure · encodes-a-behaviour-change · NOT AFFECTED (grep false
positive or genuinely below-threshold trap).

| File | Seeded nodes | vs. 150 | Full-tree dependency | Treatment | Reason |
|---|---|---|---|---|---|
| `tests/test_manage_builder.py` | 0–2 per test | below | No — fragment/page assertions only | NOT AFFECTED (trap) | Small fixtures open fully either way; the one redirect assertion in this file (`test_editor_settings_save_persists_and_redirects`, line 144) targets `manage_editor`, not `manage_builder` — untouched by Task 6 |
| `tests/test_manage_node_ops.py` | 1–4 per test | below | Mostly no; **one exception** | `encodes-a-behaviour-change` for one test; NOT AFFECTED (trap) for the rest | `test_no_js_rename_still_redirects_to_the_builder` (line 717–727) asserts `resp.url == reverse("courses:manage_builder", ...)` with **no query string**. Task 6's `_redirect_to_builder` appends `?open=session` to `node_rename`'s no-JS redirect (`views_manage.py:344`). This WILL go red regardless of fixture size — update the assertion to expect the `?open=session` suffix |
| `tests/test_manage_affordance.py` | 2–3 per test | below | No | NOT AFFECTED (trap) | `data-add-scope` assertions pass only because the small fixture opens fully; would need `open=all` if ever scaled up |
| `tests/test_manage_node_duplicate.py` | 1–2 per test | below | No | NOT AFFECTED | `data-scope` assertions are on the mutation's own returned scope fragment (`_render_scope` for that specific parent), not a whole-tree render |
| `tests/test_manage_duplicate_button.py` | 1–2 per test | below | No | NOT AFFECTED (trap) | Straightforward small fixtures |
| `tests/test_manage_move_picker.py` | 2–3 per test | below | No | NOT AFFECTED | Asserts on the move-picker destination-list fragment, not the tree scope render |
| `tests/test_tree_badge.py` | N/A (6 of 8 tests render `_tree_node.html` directly with `node=<unit>`) | below | No | NOT AFFECTED — structurally immune | A unit is never a container (`{% if node.kind != "unit" %}` gates it out of the new open-scope branch entirely), so these never touch the new code path. The one container-node test uses a 1-node course via the real view |
| `tests/test_seed_demo_course.py` | ~6–8 (1 chapter, 1 section, a handful of units) | below | No | NOT AFFECTED | Only `test_seeded_ca_can_open_builder` touches `/build/`, and it asserts `status_code == 200` only — no tree-content assertion |
| `tests/test_element_editor_ops.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Grep matched `data-scope="editor"`/`data-scope="preview"` — the **editor/preview split-pane** markers, an unrelated reuse of the `data-scope` attribute name, not the tree's per-node scope |
| `tests/test_editor_page.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same `data-scope="editor"/"preview"` pattern |
| `tests/test_media_manager.py` | N/A | — | No | NOT AFFECTED | Matched a plain `href` link to `manage_builder` with no query string; Task 3/6 don't touch that outbound link |
| `tests/test_transfer_views.py` | 1–3 per test | below | No | NOT AFFECTED | Matched `reverse("courses:manage_builder", ...) in resp.url` — a **substring** check on an unrelated export-error redirect (`views_transfer.py`); would still pass even with a query string appended |
| `tests/test_code_field_seed.py` | N/A | — | No | NOT AFFECTED (false positive) | Matched `/build/unit/<pk>/edit/` — the editor URL happens to contain `/build/` as a path segment |
| `tests/test_dashboard_panels.py` | N/A | — | No | NOT AFFECTED | Plain dashboard `href` link to the builder, no query string |
| `tests/test_e2e_builder.py` | 0–2 top-level nodes | below | No | NOT AFFECTED (trap) | Every fixture is tiny/flat |
| `tests/test_e2e_builder_ws2.py` | ≤6 nodes per test | below | No | NOT AFFECTED (trap) | Single shallow scope per test |
| `tests/test_e2e_builder_authoring.py` | 1 chapter + 1 unit | below | No | NOT AFFECTED (trap) | Single-level nesting |
| `tests/test_e2e_builder_reorder.py` | 5 nodes (`_seed_tree`) | below | No | NOT AFFECTED (trap) | Reorder/move-picker assertions don't depend on collapse state at this size |
| `tests/test_e2e_builder_tree_layout.py` | 2–42 nodes, but **flat** (top-level units, no containers) even in the "tall tree" case | below, and irrelevant regardless | No | NOT AFFECTED | Task 3 only gates a **container's child** `<ol>`; top-level rows always render. These fixtures have zero containers, so even a 500-node version of this fixture would be unaffected |
| `tests/test_e2e_inline_rename.py` | 5 + `n_filler` (max case `n_filler=40` → 45 nodes) | below (max 45) | No | NOT AFFECTED (trap) | Even the "long tree / scroll preservation" case stays under threshold |
| `tests/test_e2e_transfer.py` | Source 2 nodes; destination 1→3 after import | below | No | NOT AFFECTED (trap) | Both courses tiny |
| `tests/test_e2e_alignment.py` | N/A (editor-only) | — | No | NOT AFFECTED (false positive) | `data-scope="editor"/"preview"` again, unrelated to the tree |
| `tests/test_e2e_editor.py` | 1 unit | below | No | NOT AFFECTED (false positive) | `/build/unit/<pk>/edit/` substring; never visits the tree page itself |
| `tests/test_e2e_editor_view_toggle.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_editor_ws3.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_editor_preview_state_regression.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_editor_unit_token.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_choice_editor_feedback.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_media_picker.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_gallery.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_filltable.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_imagezoom.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same pattern |
| `tests/test_e2e_math_input.py` | 1 unit | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_questions.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_questions_2dii.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_reveal_gate.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_spanning_roundtrip.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_stepper.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_switchgrid.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_table_editor.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_tabs.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_e2e_twocolumn.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/test_tabs_editor_dnd.py` | small | below | No | NOT AFFECTED (false positive) | Same |
| `tests/capture_help_screenshots.py` | demo-course (~6–8 nodes, see `test_seed_demo_course.py` row) | below | Not a pytest test — a doc-screenshot script. Its "builder tree" shot navigates `manage_builder` for demo-course and clips `.builder__tree` | re-measure | Below threshold today so the shot is unaffected; re-capture manually if demo-course content ever grows past 150 nodes or if Task 3/4's toggle chevron changes the clipped region's visual content |

### Not grep-discoverable, touched anyway

| File | What it checks | Expected impact |
|---|---|---|
| `tests/test_builder_styles.py` | Regexes `courses/static/courses/css/builder.css` from disk for specific selectors (`.builder`, `.tree__title`, `.builder__tree`, `.builder__panel`, `.element-list__item`, `input.tree__title`, `.tree__rename`) | None of the asserted selectors are the toggle/chevron rules Task 3/4 add. Expected to **stay green** through Task 3, but re-verify after Task 4 (adds toggle-column CSS) and Task 8 (busy-state CSS) in case a rule gets folded into an existing block those regexes match |
| `tests/test_builder_js_invariants.py` | Regexes `courses/static/courses/js/builder.js` raw source: exactly one `panel.innerHTML =` assignment (must be inside `setPanel()`), and `setPanel()` must reset `scrollTop`| Task 8 adds a toggle click-handler and an open-collector to `builder.js`. Neither should touch `panel.innerHTML` or `setPanel()`, so expected to **stay green** — but flag as a file to re-run immediately after Task 8, since a careless toggle handler that re-renders the panel would trip the "exactly one assignment" invariant |

## Decisions (recorded per the brief)

### 1. The two element-op redirects — `element_move` (`views_manage.py:636`) and `element_delete` (`:652`)

**Confirmed: the brief's default decision is correct.** Both currently do a bare
`redirect("courses:manage_builder", slug=course.slug)` on the no-JS path (skipped only when
`ctx=editor`, i.e. they fire from the builder's own unit panel, not the editor). After Task 3
this lands on a page-mode render with no `open`, collapsing the tree on every no-JS
reorder/delete — exactly the regression `open=session` exists to prevent for the other five
no-JS builder redirects (Task 6 already routes those, plus these two, through
`_redirect_to_builder(course)`; see plan lines 2099–2101). No chain persistence is needed
here: the unit itself still exists, and the session carrier (`builder_open`) already holds
whatever the author had open — the redirect only needs to add `?open=session` so that carrier
gets read back.

**New finding, not in the brief: this path has zero existing test coverage.** Every test that
posts to `manage_element_move`/`manage_element_delete` — in both `test_manage_element_ops.py`
and `test_element_editor_ops.py` — sends `HTTP_X_REQUESTED_WITH="fetch"` (the `FETCH` header),
so `_wants_fragment(request)` is always true and the redirect branch at `:636`/`:652` is never
exercised today. Confirmed by grepping both files for `manage_builder`/`resp.url`/
`resp["Location"]`/`status_code == 302` — no hits. Task 6 (or its test step) should add a
no-JS (no `FETCH` header) POST test for both endpoints asserting the redirect target is
`.../build/?open=session`, since nothing currently pins this behaviour in either direction.

### 2. The three `_render_tree` call sites outside the builder flow — `_element_conflict` (`views_manage.py:675`) and `element_save` (`:1076`, `:1087`)

**Decision: accept the collapsed recovery tree.** Read all three call sites directly:

```python
# _element_conflict, :666-675
unit = ContentNode.objects.filter(
    pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
).first()
if unit is None:
    return _render_tree(request, course, status=409)
```

and the two in `element_save` (`:1071-1076`, `:1082-1087`) are structurally identical: they
look up `unit` from `request.POST.get("unit")`, and only call `_render_tree` **in the branch
where `unit is None`** — i.e. exactly when the unit that was being edited has been deleted out
from under the request (a genuine conflict: another author or tab removed it while this one
still had an element form open).

This makes "pass `extra_open=_ancestor_chain(unit)`" **not just undesirable but
uncomputable at these three sites**: `_ancestor_chain` walks `node.parent` from the node
itself, and `unit` is `None` in the exact branch that reaches `_render_tree` — there is no
node object left to walk. The row/unit is gone; there is no ancestor chain to recover it into.
Accepting a collapsed top-level tree (with its 409 status making clear something went wrong)
is therefore not merely "defensible because rare" — it is the only implementable option
without adding a second query to recover the deleted node's last-known parent from history
that the app doesn't keep.

No existing test exercises this branch for any of the three sites either (confirmed: no test
constructs a "unit vanished mid-edit" scenario for `element_save`/`_element_conflict` with a
missing top-level `unit`; `test_element_op_vanished_row_409` in
`tests/test_manage_element_ops.py` exercises the *element* row vanishing, not the *unit* row,
so `unit` resolves fine there and the fallback branch is not hit). Whoever implements Task 3/6
should add one test per site (or one shared parametrized test) asserting: (a) the response is
409, (b) the tree renders collapsed (no `data-scope` for any child container), consistent
with a fully-collapsed `open_ids = frozenset()`.

## Baseline

See `.superpowers/sdd/task-0b-report.md` for the full command output. Summary: unit suite
green, e2e suite green, both run sequentially against the shared dev/test database per the
worktree's `.env`.

## Baseline (recorded before any behaviour change)

Measured on this worktree's **isolated** database `libli_blcp` (test DB
`test_libli_blcp`). The first attempt used the shared `libli`, and every e2e test
ERRORed on `CREATE DATABASE "test_libli"` — DuplicateDatabase, then ObjectInUse
with "2 inne sesje uzywaja bazy danych": another Claude session in a parallel
worktree held it. That is the contention `test-db-contention-across-worktrees`
warns about, reproduced.

| Suite | Command | Result |
| --- | --- | --- |
| unit (targeted) | `uv run pytest tests/test_manage_builder.py -q -p no:randomly` | exit 0 |
| e2e (builder-affected files) | `uv run pytest tests/test_e2e_builder.py tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_inline_rename.py -q -m e2e -p no:randomly` | **exit 0, green** |

**The full e2e suite was NOT baselined end to end.** It exceeds the 10-minute
ceiling on a single tool invocation; two attempts were killed mid-run (the second
showing passes, not errors, at 17%). The six builder-affected files above are the
ones this change can plausibly break, and they are green. Tasks 3–10 gate against
**those**, not against the whole e2e suite. Anything else going red during those
tasks is a regression, not migration noise.

Note: pytest's verdict line does not survive a Bash pipe in this repo — trust the
exit code and a `FAILED`/`ERROR` grep, not a "N passed" string.
