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
