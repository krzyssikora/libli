# Internal content links — the mat-pp cutover

Part 3 of three, and the one with a deadline attached.

- Part 1, `2026-07-26-internal-content-links-design.md` — the link dialog and the
  `/courses/n/<pk>/` permalink.
- Part 2, `2026-07-26-internal-link-durability-design.md` — `courses/richtext.py`, the registry and
  rewrite helpers, and links surviving an *uploaded-archive* import.
- **Part 3 (this) — links surviving `migrate_course_content`, the production cutover.**

**Part 3 depends on part 2** and cannot be built first: it consumes `rewrite_instance`, the registry,
`document["link_nodes"]`, and the `on_missing` / `report` plumbing that part 2 introduces. Part 2 is
independently useful without part 3 — it makes the Studio import/export UI correct — but part 2 alone
does **not** make the cutover safe, which is why this is its own deliverable rather than a paragraph
in someone else's.

It was split out after review: parts 1 and 2 converged, while this material produced 22 catches
(7 CRITICAL) across two rounds, every one of them here. It earns its own spec and its own review.

## Purpose

`courses/management/commands/migrate_course_content.py` is the mat-pp production cutover. It moves
content between databases in three phases (`export` / `import` / `verify`) with a bundle directory
between them, and it moves **one top-level part at a time**.

That last property is what breaks internal links. Each part's archive knows only its own nodes, so a
link from part A to part B has no resolvable target in either archive. Under part 2's uploaded-archive
default (`unwrap`), **every cross-part link in a 21-part course would be silently turned into plain
text** — and silently is exact: the command has no `messages` framework, so a discarded count never
reaches the operator.

## Scope

| file | change |
|---|---|
| `courses/transfer/export.py` | hand `node_ids` back through an optional `report` keyword on `build_export` — **not** a fifth return value |
| `courses/transfer/importer.py` | the third `on_missing` value, `defer`; `report` also carries `node_map` as `{export_id: new_pk}` |
| `courses/management/commands/migrate_course_content.py` | bundle-level `link_nodes` at export; `defer` per part + a `LINK_STATE_NAME` state file; one final rewrite pass; stdout counts; `verify` reporting |
| `tests/test_migrate_course_content.py` | the five cases in §Testing |

**Out of scope:** everything part 2 owns — the registry, the anchor scanner, `document["link_nodes"]`
itself, the delete warning, and the Studio import warning. This spec changes no sanitiser, no model
and no template.

## Architecture

**The management command is the cutover, and the naive default breaks it.** There is a fourth caller
of `import_subtree`: `courses/management/commands/migrate_course_content.py:481`. That command *is*
the `mat-pp` production cutover this spec's preamble names as its reason to exist, and its module
docstring is explicit: *"Content moves ONE TOP-LEVEL PART AT A TIME. That is not incidental"* — whole
-course archives would breach `TRANSFER_MAX_ELEMENTS`.

Because each archive is built with `build_export(course, node=part)`, its `node_ids` — and therefore
its `link_nodes`, restricted to "targets inside the exported set" — can never contain a node from
another part. Under a plain `unwrap` default, **every cross-part link in a 21-part course would be
silently turned into plain text**, and silently is exact: the command has no `messages` framework, so
a discarded `report` count would never reach the operator. The feature would fail precisely the
migration it was written for, for the most likely link shape in a large course.

The command already has the structure to do this correctly — three phases (`export` / `import` /
`verify`) with a bundle directory, a `bundle-manifest.json` written once after a complete export, and
`--start-at K` resume.

**The governing rule: no href is rewritten until the whole map exists.** Rewriting per part and then
"finishing up" at the end cannot work, and the reason is worth stating because it is the trap this
design fell into once already. If each part's import rewrote its own intra-part links to *new* pks,
the final pass — whose map is keyed by **old source** pks — would find those hrefs unresolvable and,
under `unwrap`, flatten every within-part link in the entire course. That is a far worse outcome than
the cross-part loss it was meant to fix. So the per-part imports rewrite **nothing**, and exactly one
pass rewrites everything, once, when the complete map is known.

That needs a third `on_missing` value, used only here:

| value | behaviour |
|---|---|
| `unwrap` | rewrite what maps; flatten the rest (uploaded archives) |
| `keep` | rewrite what maps; leave the rest (same-install duplicate) |
| **`defer`** | **skip the rewrite post-pass entirely** — every href still holds a source pk afterwards |

- **Export phase** additionally writes a **bundle-level** `link_nodes` into `bundle-manifest.json`,
  covering every node in the source course rather than only the current part:
  old pk → `(part order, export id)`. The join key is the **integer part order** — the value
  `part.order` supplies at export and `_archive_order(p.name)` parses back at import — never the
  filename. Export ids restart at `n1` in every archive, so if the two phases keyed this differently
  every lookup would miss and the whole course's links would flatten, silently. The manifest is
  written once, after all parts export, which is exactly when the whole mapping is known.

  This needs plumbing the exporter lacks: `node_ids` is a local in `build_export` and `_node_dict`
  never emits the source pk. It is handed back through an **optional `report` keyword**, not a fifth
  return value — `build_export` returns a 4-tuple that is unpacked positionally at **29 sites across
  10 files**, including `courses/builder.py`, which §Scope declares unchanged. Widening the arity
  would break every one of them, and would contradict the reasoning that already made `report` an
  out-param on the importer. Only `migrate_course_content._export` passes it.

  The per-part `document["link_nodes"]` cannot substitute — it holds only targets referenced from
  inside that part, so a node linked to *only* from another part appears in no archive's map at all.

- **Import phase** passes `on_missing="defer"` per part and accumulates the map in a bundle-level
  state file, `LINK_STATE_NAME` (a module constant beside `MANIFEST_NAME` and `BASELINE_NAME`).
  Building it needs `export_id → new_pk`, which `import_subtree` does not return today — it hands
  back only the grafted root — so **`report` also receives `node_map`** as `{export_id: new_pk}`
  alongside `flattened_links`.

  Entries are **keyed by part order** and the file is written **immediately after each part commits**,
  not once after the loop. Both halves matter. Writing once would lose every committed part's
  `export_id → new_pk` on a mid-loop failure, and those are unrecoverable afterwards — export ids
  exist only in the returned `node_map`. Keying by part order is what lets the final pass attribute
  its counts per part, and lets a resume detect a short file: if `--start-at K` exceeds
  `max(recorded part order) + 1`, the map is incomplete and the command raises `CommandError` rather
  than proceeding to flatten every link into the missing part. (The existing `--start-at` invariant
  only counts top-level nodes, so it cannot catch this.)

  Lifecycle mirrors `BASELINE_NAME`: written fresh when `start_at is None`, read and extended on
  resume, removed by `export --clean` (which today deletes only `*.zip` and the manifest), and —
  like `_capture_baseline`'s own write — **neither written nor reset under `--dry-run`**, so a dry
  run cannot wipe a real migration's accumulated map.

- **The final pass is triggered by bundle state, not by the loop.** It runs whenever every archive is
  committed *and* the state file does not record the pass as applied. The loop-completion reading has
  a hole precisely where the state file exists to help: a process that dies after the last part
  commits resumes with `--start-at part_count`, hits the "this migration is already complete" early
  return, and never rewrites anything. Skipped entirely under `--dry-run`.

- **Its scope is the `Element` rows whose `unit_id` appears among the state file's recorded new pks**
  — not the whole target course, and not a baseline-derived guess. An earlier draft said "the
  top-level nodes this migration created, identifiable from the baseline's `top_nodes` plus the
  committed part orders"; that does not work, because `_capture_baseline` records `top_nodes` as an
  integer **count** (`nodes.filter(parent__isnull=True).count()`) and the part orders are *source*-side.
  Neither yields a target pk. The state file already holds the exact answer: `report["node_map"]`
  values are the new pks of every node each part created. Nested elements come for free, since a child
  `Element` keeps its own `unit` FK (§4 relies on the same property).

  Scoping matters most under `--force`, which permits grafting into a course that already holds
  content: those pre-existing bodies carry *target* pks, and sweeping them with an old-pk-keyed map
  would flatten them or, on a numeric coincidence, mis-point them.

- It calls `rewrite_instance(..., on_missing="unwrap")`. The bundle map covers the whole source
  course, so anything still unresolved genuinely has no target anywhere in the migration.

- **Crash-safe marking, in two steps around one transaction.** The rewrite runs inside a single
  `transaction.atomic()`, but the marker lives in a JSON file, so "atomic + write the marker after"
  leaves a window: a crash between the DB commit and the file write yields fully rewritten content
  with no marker, and the state-driven trigger would then re-apply an old-pk-keyed map to hrefs that
  now hold *target* pks — the silent mis-point case this design exists to prevent, and the one the
  test harness cannot reach. So: write an **`in_progress`** marker *before* the transaction, flip it
  to **`applied`** after commit, and treat a state file found `in_progress` as a **`CommandError`** in
  both `import` and `verify`, never a silent re-run.

- It **prints per-part rewritten and flattened counts** to stdout and records them in the state file;
  the per-part grouping is what the part-order keying above provides. `verify` prints them from there
  — it cannot recompute them, since it reads only the manifest, baseline and archives, none of which
  carry the counts. In `verify`, a committed bundle whose state file lacks the `applied` marker is a
  `CommandError` (the skipped-pass case), and a **missing** state file is likewise a `CommandError`
  telling the operator to run `import` first — mirroring what `verify` already does for a missing
  `BASELINE_NAME`.

**The map is applied exactly once, to hrefs that still hold source pks** — which `defer` guarantees.
This invariant has to be argued rather than tested, and the reason is worth recording: source and
target live in *different databases*, so a new target pk can equal an old source pk. Any design that
re-applies the map over already-rewritten content can therefore silently re-point a correct link at
an unrelated node. `tests/test_migrate_course_content.py` creates both courses in one test database,
where new pks always exceed source pks, so the collision is not reachable from the harness.

This is the one place the design pays for the two-phase architecture, and it is not optional: without
it the spec's headline claim about the cutover is false.

## Testing

Falsified before trusted — delete the behaviour, require RED.

**The cutover path** — the case the naive `unwrap` default silently breaks, so it gets end-to-end
coverage rather than a note:

- A two-part fixture course where a lesson in part A links to a unit in part B **and** another lesson
  in part A links within part A. Run `export` → `import` over both parts and assert **both** resolve
  to their **new** pks. The intra-part link is not padding: it is the assertion that catches the
  rewrite-per-part-then-finish design, under which the final old-pk-keyed pass would flatten every
  within-part link in the course. A cross-part-only fixture passes that broken design.
- The same, with the import **interrupted after part A and resumed with `--start-at`**: the
  accumulated old→new state must survive across process invocations, so the final pass still
  resolves the cross-part link. This is what pins the state to a file rather than memory.
- A link whose target is in no part at all → flattened, counted, and the count printed to stdout.
- **The skipped-pass window:** a run interrupted *after* the last part commits but before the rewrite
  pass, then resumed with `--start-at part_count`, still applies the pass — and `verify` raises
  `CommandError` on a committed bundle whose state file lacks the applied marker.
- `--force` grafting into a target that already holds linked content: the pre-existing bodies are
  **untouched**, since the pass is scoped to the grafted top-level nodes.

## Error handling

- **A bundle exported before this change**, whose `bundle-manifest.json` has no `link_nodes` key →
  read with `manifest.get("link_nodes", {})`, so no part rewrites and the operator gets the flattened
  count rather than a raw `KeyError`. `_read_bundle_manifest` validates only `part_count`, so such a
  bundle passes the gate and must not traceback afterwards.
- **A state file found `in_progress`** → `CommandError` in both `import` and `verify`, never a silent
  re-run. See the crash-safe marking rule above.
- **A missing state file at `verify` time** → `CommandError` telling the operator to run `import`
  first, mirroring what `verify` already does for a missing `BASELINE_NAME`.
- **`--start-at K` exceeding `max(recorded part order) + 1`** → `CommandError`: the map is incomplete,
  and proceeding would flatten every link into the missing part.
