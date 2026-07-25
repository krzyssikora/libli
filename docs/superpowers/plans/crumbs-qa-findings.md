# Breadcrumb QA findings

## Accessible-name measurement

Measured on chromium 148.0.7778.96 at 360px, on `li.unit-crumbs__item--leaf`.

- `aria_snapshot()`: `- listitem "Section Sequences Series And Their Convergence Criteria In Depth"`
- CDP computed name: `Section Sequences Series And Their Convergence Criteria In Depth` — emitted,
  `ignored: false`, with the winning source reported as `attribute title` (the
  `aria-labelledby` and `aria-label` sources are both present and empty, neither
  superseded nor invalid)
- Reading: `title` contributes an accessible name duplicating the label text.

No change was made either way: the spec rules the remedy out of bounds because that
`title` is load-bearing for render test 12, for the 360px e2e coupling assertion, and
for the documented hover affordance.

## Follow-up: no breadcrumb on quiz_results.html

A student who has submitted a quiz is redirected to `quiz_results.html`, which renders
outside `_unit_shell.html` with no sidebar tree, no drawer and no `unit_nav` — so it is
the page with the *least* orientation and it deliberately gets no crumb in this change.
Covering it needs a `build_unit_nav` call on that view plus its own alignment work.

## Existing e2e suite

Existing e2e suite green, no changes. Swept all 70 `tests/test_e2e_*.py` modules via the
chunked `-m e2e -n 2` invocations from Task 8 Step 1 (7 sub-chunks, since two of the
brief's three chunks exceeded the 10-minute per-invocation ceiling and were split
further). One failure surfaced, in `tests/test_e2e_guessnumber.py::test_correct_guess_persists_across_reload`
(unrelated assertions — POST/reload state persistence and CSS classes, no geometry or
tab-order coupling); it reproduced green at `-n 0`, so it was classified as a
`-n 2` contention flake rather than a breadcrumb regression, and nothing was changed.
`tests/test_e2e_unit_crumbs.py` (9/9) and `tests/test_e2e_unit_nav.py` both passed clean
under this independent sweep, including the reviewer-requested re-confirmation of the
Task 7 design-pass crumb-label styling.
