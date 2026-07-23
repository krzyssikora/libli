# Course content migration between databases

A management command that moves a course's content from one database into an existing course in
another, using the transfer engine's archive format as the handoff. Built to migrate the finished
`matematyka` course out of the isolated `libli_mat` database and into the prepared `mat-pp` course in
the real `libli` database — but built as a general tool, not a one-off script.

**This work delivers the tool only.** Running it against the real database is a separate, deliberate
act the user has explicitly reserved for themselves. See Out of scope.

## Purpose

The LAL import effort produced a finished course inside a deliberately isolated database
(`libli_mat`): 925 content nodes (21 parts / 111 chapters / 793 units), roughly 20,054 elements, and
1144 media assets. It has to reach the real course the students use.

The destination already exists and is deliberately prepared: `mat-pp` in the real `libli` database
carries the correct slug, an owner, `allowed_kinds == ['part', 'chapter', 'unit']`, and — critically
— the `html_css` / `html_js` baseline (the LAL `styles.css` / `script.js`) that the sandboxed iframe
of an `HtmlElement` needs in order to render and function. It currently holds **zero** content nodes.

That prepared-but-empty destination is what fixes the approach. The transfer engine already knows how
to move content between databases correctly — it remaps media, validates against the schema, and
sanitises on import — and it is the sanctioned path (the alternative, copying rows between two
Postgres databases by hand, would have to solve primary-key collisions, media files, and referential
integrity from scratch, badly).

### Why a management command rather than the existing UI

The transfer engine today is reachable only through `courses/views_transfer.py`: a browser downloads
an export and uploads an archive through a staged preview-and-confirm flow. That is right for a
teacher sharing one unit. It is the wrong instrument for this: 21 separate export→upload cycles
carrying roughly 327 MB of media, through a form whose importer enforces per-entry size caps. A
command drives the same underlying functions without the browser in the middle.

### Why the tool is general

Hardcoding `matematyka` and `mat-pp` would make the command untestable (the test would need the real
databases) and unusable a second time. Parameterising source slug, target slug, and bundle directory
costs nothing and makes the migration one invocation of a tool that can be exercised against
synthetic fixtures.

## Architecture and components

One new management command under `courses/management/commands/`. The closest existing convention to
follow is `import_lal_content.py`; there is currently **no** management command for the transfer
engine at all, so this establishes the pattern.

### The mechanism: subtree grafting, not course import

The transfer engine offers two import entry points and they are **not** interchangeable:

- `import_course(zf, manifest, document, media_entries, user)` — **creates a new course**, carrying
  the exported course's own `html_css` / `html_js` and matching its subjects.
- `import_subtree(zf, manifest, document, media_entries, target_course, insertion_node, user)` —
  **grafts an exported subtree into a course that already exists**, under a chosen insertion point.

Because the destination already exists with the right slug and css/js, `import_course` is wrong: it
would create a *second* course beside the prepared one. The migration therefore uses the subtree
path, and since a subtree export is rooted at a single node, the course is moved **one top-level part
at a time** — 21 grafts, each landing at the destination's top level.

`insertion_choices(target_course, root_kind)` offers `"Top level"` precisely when the subtree's root
kind is a legal top-level child of the target, which holds here because `mat-pp` allows `part`.

### Two phases, because a Django process binds one database

`DATABASE_URL` selects a single database per process, so no single invocation can read `libli_mat`
and write `libli`. The command therefore has two phases with an on-disk bundle between them — which
is what the archive format exists for:

- **`export`** — run against the source database. Iterate the source course's top-level parts in
  `order`, and for each call `build_export(course, node=part)` then `write_archive_from(...)`,
  writing one archive per part into the bundle directory, named so that part order is recoverable.
  Strictly read-only with respect to the source.
- **`import`** — run against the target database. Iterate the bundle's archives **in part order** and
  for each call `open_archive` → `validate_archive_document` → `import_subtree(...)` with the target
  course and a top-level insertion point.

The bundle directory is the interface between the phases, and it is also what makes the whole
operation inspectable: after the export phase the archives can be examined before anything is
written anywhere.

### Guards

The import phase will eventually run against a real database holding real courses, so it defends
itself:

- **Double-run guard.** Refuse to import when the target course already has content nodes, unless an
  explicit override flag is passed. Re-running by accident would graft a second copy of all 21 parts.
- **Per-part transaction.** Each part's graft is atomic, so a failure part-way cannot leave a
  half-grafted part behind.
- **Dry run.** A mode that reports what *would* be grafted — per-part node and media counts — while
  writing nothing.
- **The source is never mutated.** The export phase only reads.

### Verification

The user asked for counts plus a broad sample rather than an exhaustive sweep. The command supports
the counting half directly: a mode that compares the target's totals against the bundle's — parts,
chapters, units, media, and per-element-type tallies — and reports any mismatch. For the migration
this should come out at 21 / 111 / 793 / 1144.

The sample half is a render check performed after the real cutover, deliberately spanning the element
families most likely to break in transit: a spoiler unit, the `250_pole` fill-table with its
`colspan` explanation rows, a video unit, a math unit, an interactive-in-spoiler unit, and the
binary-tree `HtmlElement` unit ("Klasyfikacja czworokątów").

## Data flow

**Export phase**, per part: source course → `build_export(course, node=part)` produces
`(manifest, document, media_assets)` → `write_archive_from(...)` writes a zip containing
`manifest.json`, `course.json`, and the media payload → one file per part in the bundle directory.

**Import phase**, per archive in part order: file → `open_archive(fileobj, expected_kind=…)` →
`validate_archive_document(...)` → `import_subtree(zf, manifest, document, media_entries,
target_course, insertion_node=<top level>, user)` → new `ContentNode` rows under the target course,
new `MediaAsset` rows with fresh primary keys, and media files materialised from the archive.

Node titles travel verbatim. That matters here: 29 of the source's chapters have been renamed by hand
and 82 still carry `__PLACEHOLDER chapter N__`. All 111 arrive exactly as they are, and the remaining
renaming happens in the destination afterward.

## Error handling

**A part that fails to import must not leave debris.** Each graft is wrapped so a failure rolls that
part back; the command then stops and reports which part failed rather than continuing and producing
a partial course whose gaps are hard to spot.

**The double-run guard fails loudly, not silently.** Importing into a non-empty target aborts with a
message naming the target and its current node count, and states the override flag. Silently
appending a second copy would be far worse than refusing.

**Archive validation errors surface as themselves.** `open_archive` and `validate_archive_document`
raise `TransferError` for malformed or oversized archives; the command reports the failing archive
by name rather than letting a raw traceback escape.

**A missing or empty bundle directory is an error**, not a no-op success — an import phase that
grafts nothing and reports success would be indistinguishable from a completed migration.

## Testing

Every task is test-first: write the failing test, confirm it fails for the stated reason, implement,
confirm green.

**The two-database split is a runtime concern only.** The command's logic is fully exercisable in a
single test database by creating a synthetic source course and a synthetic target course, running the
export phase into a `tmp_path` bundle, then the import phase into the target, and asserting on the
result. Tests must never touch `libli_mat` or the real `libli`.

Required coverage:

- A multi-part graft that **preserves part order** in the target.
- The **double-run guard** refusing a target that already has nodes, and the override flag bypassing
  it.
- **Dry run** writing nothing — asserted by node count before and after, not by reading the log.
- **Media re-materialised** with fresh primary keys in the target, distinct from the source's.
- **Titles carried verbatim**, including a `__PLACEHOLDER`-style title, so the rename-later workflow
  is protected.
- **The `HtmlElement` round-trip described below.**

### The risk that must be pinned before anything else

`importer._build_html` passes imported html through `sanitize_html`. The binary decision tree's
interactivity depends on `data-binary-choose` attributes that `course.html_js` binds to. If
sanitisation strips them, the element survives the migration as visibly-intact but dead markup —
exactly the kind of silent loss that is hard to notice among 793 units.

A test must therefore round-trip an `HtmlElement` carrying `data-binary-choose` through export and
import and assert the attribute survives. **If it does not survive, stop and surface it.** That is a
genuine content-loss finding which changes the design; it must not be worked around quietly.

### Known gaps, documented rather than solved

- **Course-level subjects do not transfer through a subtree graft.** Only `import_course` matches
  subjects; `import_subtree` moves content, not course metadata. The destination may need subjects
  set separately. This is accepted, not fixed here.
- **Both databases share one `MEDIA_ROOT`.** The import creates fresh `MediaAsset` rows with files
  materialised from the archive, so it should not reuse another course's file — but this must be
  confirmed rather than assumed, because this repository has a known trap in which two `MediaAsset`
  rows sharing a `file.name` also share a lifetime: deleting either one removes the file for both.

The full non-e2e suite must pass, and both `uv run ruff check .` and `uv run ruff format --check .`
must be clean; CI gates them separately.

## Out of scope

- **Running the migration against the real `libli` database.** This delivers a tested tool. The
  cutover is a separate, deliberate step, gated behind the user's explicit go-ahead. No task here may
  write to the real `libli` or to `libli_mat`.
- Changing the transfer engine's existing UI views, or the semantics of `import_course` /
  `import_subtree` — unless the `sanitize_html` risk above proves it necessary, in which case the
  finding is surfaced rather than silently designed around.
- Renaming chapters or touching the 82 `__PLACEHOLDER` titles — the user does that in the destination
  afterward.
- Setting subjects on the target course (see Known gaps).
- Retiring the `libli_mat` database or the matematyka worktree.
- Any database migration. No model changes are expected; if one proves necessary, surface it rather
  than adding it.
