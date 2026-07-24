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
carrying roughly 327 MB of media, each through session staging, a preview-confirm round trip, and a
request timeout. A command drives the same underlying functions without the browser in the middle.

**What the command does *not* avoid is media size validation.** `validate_archive_document` →
`validate_media_entries` enforces `effective_max_image_bytes()` / `effective_max_video_bytes()` —
per-entry caps configured on the *target* instance — identically for any caller. The command removes
the browser and the staging overhead, not the caps. That makes the caps a real pre-cutover risk:
before the real migration, the target's configured image/video ceilings must be checked against the
largest source assets, or the cutover will fail on a `TransferError` partway through exactly as the
UI would have.

### Why the tool is general

Hardcoding `matematyka` and `mat-pp` would make the command untestable (the test would need the real
databases) and unusable a second time. Parameterising source slug, target slug, and bundle directory
costs nothing and makes the migration one invocation of a tool that can be exercised against
synthetic fixtures.

## Architecture and components

One new management command under `courses/management/commands/`. The closest existing convention to
follow is `import_lal_content.py`; there is currently **no** management command for the transfer
engine at all, so this establishes the pattern.

### The invocation surface

Three operations, selected by a required positional `action`, so which flags are valid where is
unambiguous:

```
manage.py migrate_course_content export --source-slug <slug> --bundle-dir <dir> [--allow-problems] [--clean]
manage.py migrate_course_content import --target-slug <slug> --bundle-dir <dir> --as-user <email>
                                        [--dry-run] [--force] [--start-at K]
manage.py migrate_course_content verify --target-slug <slug> --bundle-dir <dir>
```

`--dry-run` is a **flag on `import`**, not a fourth action: it exercises the identical archive-reading
path and stops short of writing, which is what makes it a meaningful rehearsal. `verify` is a separate
action because it runs *after* a completed import and needs no archive-opening privileges beyond
reading the bundle's tallies.

Flags are scoped to their action and rejected elsewhere — `--allow-problems` is an export-phase
concept and is not accepted under `import`; `--force`, `--start-at` and `--as-user` are import-phase
concepts and are not accepted under `export`. `import_lal_content.py` is a single-purpose command, so
this multi-action shape is a deliberate departure and worth stating rather than leaving an implementer
to infer.

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

**Splitting by part is doubly load-bearing.** Beyond the create-vs-graft asymmetry, `validate_document`
enforces per-**document** structural caps on every import: `TRANSFER_MAX_NODES = 5000`,
`TRANSFER_MAX_ELEMENTS = 20000`, `TRANSFER_MAX_MEDIA_ENTRIES = 1000`. Each archive is one document,
so a single whole-course archive would carry all 20,054 elements and 1144 media assets and **fail
validation on both counts**. The 21-way split is what keeps each document inside those limits — it is
not merely a consequence of using `import_subtree`.

That makes per-part sizing a real pre-cutover check rather than an abstraction. (With a 21-way split
the averages are far under — roughly 44 nodes, 955 elements, 54 media per part — but averages are not
guarantees, and one media-heavy part crossing 1000 entries is the plausible failure.)

**Dry-run implements that check by running the real validation, not a reimplementation of it.** It
invokes `open_archive` and `validate_archive_document` on every archive in the bundle and stops
before `import_subtree`. Enumerating the three structural caps by hand would silently miss the others
the same call enforces — `TRANSFER_MAX_COMPRESSED_BYTES` (1 GiB per zip),
`TRANSFER_MAX_UNCOMPRESSED_BYTES` (1.5 GiB declared/actual total), `TRANSFER_MAX_COURSE_JSON_BYTES`
(10 MiB), and the per-entry image/video byte caps — so a byte-heavy part would pass a hand-rolled
checklist and fail during the real cutover anyway. Driving the actual validator covers every cap as a
by-product and cannot drift from it. Dry-run additionally *reports* the per-part node/element/media
counts alongside their caps, so a part approaching a limit is visible before it breaches one.

### Who the import runs as

`import_subtree`'s final positional parameter is a `user`, and it is not decorative: it flows through
`_create_media` → `create_asset(course, kind, uploaded_file, user, name=…)` → `MediaAsset.uploaded_by`,
so it is stamped on **every one of the ~1144 re-materialised assets**. A management command has no
`request.user`, so the command takes a **required `--as-user <email>`**, resolved via
`get_user_model()`, and fails clearly if no such user exists. Defaulting silently to the target
course's owner is rejected: media attribution across a 1144-asset migration should be a stated
choice, not an inference.

### Two phases, because a Django process binds one database

`DATABASE_URL` selects a single database per process, so no single invocation can read `libli_mat`
and write `libli`. The command therefore has two phases with an on-disk bundle between them — which
is what the archive format exists for:

- **`export`** — run against the source database. Iterate the source course's top-level parts in
  `order`, and for each call `build_export(course, node=part)` then `write_archive_from(...)`,
  writing one archive per part into the bundle directory. Strictly read-only with respect to the
  source.

  **`build_export` returns a 4-tuple**, not three values:
  `(manifest, document, media_assets, problems)` — its signature is
  `build_export(course, node=None, source_host="", *, drop_missing_media=True)`. Unpacking three
  would raise `ValueError`, and dropping the fourth would discard the export's own content-loss
  signal (see "The real export-side risk" below).

  Archives are named `{order:02d}-{slug}.zip` so part order is recoverable from the filename alone,
  without opening 21 archives to read their manifests. **`{order:02d}` is a MINIMUM width, not a fixed
  one** — at 100+ top-level nodes (realistic for a Flat-preset course, where every unit sits at top
  level) `"100-…zip"` and `"20-…zip"` both exist, and a lexicographic sort of the filenames orders them
  wrong. Every site that needs an archive's part order therefore parses the `<order>-` prefix as an
  integer with a regex and sorts (or filters, for `--start-at`) on that integer — never on the filename
  text — and rejects outright any `*.zip` in the bundle that doesn't match the pattern.
- **`import`** — run against the target database. Iterate the bundle's archives **in part order** and
  for each call `open_archive` → `validate_archive_document` → `import_subtree(...)` with the target
  course and a top-level insertion point.

The bundle directory is the interface between the phases, and it is also what makes the whole
operation inspectable: the export phase writes archives to disk, but nothing reaches the target
database until the import phase runs, so the bundle can be examined first.

### The real export-side risk: `problems`

`build_export`'s fourth return value is a list of per-part problems — missing media substituted with
placeholders, dropped videos, elements that failed to serialise. The existing UI treats it as a
blocking signal: `views_transfer._stream_archive` refuses to stream the archive and renders a
confirmation page whenever `problems` is non-empty and the request has not already confirmed.

The command must not be laxer than the UI it replaces. **A non-empty `problems` list for any part
aborts the export phase by default**, reporting the affected part and its problems, and requires
`--allow-problems` to proceed. Exporting 21 parts and silently accepting placeholdered media would
produce a migration that looks complete and has quietly lost content — the precise failure this whole
effort exists to avoid.

**Re-running export requires `--clean`; a bundle is never silently merged into.** A problems-abort
partway through leaves the already-exported archives on disk, and export is read-only and cheap to
repeat, so a full re-export is always the correct recovery — but overwriting-by-filename alone is not
enough to make that safe, because a *smaller* re-export (fewer top-level parts than the run before it)
would leave the larger prior run's extra archive(s) behind, mixed in with the new ones: a Frankenstein
bundle straddling two different exports, indistinguishable from a complete one once `import` reads it.
Concretely: export 21 parts (bundle manifest written) → edit the source → re-export, which aborts at
part 5 on a `problems` finding → the bundle now holds parts 0–4 new, parts 5–20 stale, and the OLD
manifest. So `export` refuses to write into a bundle directory that already holds a `*.zip` or a
manifest **unless `--clean` is passed**, in which case it removes them first. A bundle is exported
completely, from a clean directory, every time — never appended to, never partially merged.

### Guards

The import phase will eventually run against a real database holding real courses, so it defends
itself:

- **Double-run guard.** Refuse to import when the target course already has content nodes, unless
  `--force` is passed. Re-running by accident would graft a second copy of all 21 parts.

  **`--force` and `--allow-problems` are separate flags and must stay separate.** They gate different
  phases and unrelated risks — one is a content-loss guard on export, the other an idempotency guard
  on import. A single shared `--force`-style switch would let overriding a placeholdered-media warning
  during export silently disable the double-graft check on a later import, which nothing about the
  first decision justifies.
- **Per-part transaction, and what it does *not* buy.** `importer._run_import` wraps each
  `import_subtree` call in its own `transaction.atomic()`. So a part is never half-grafted — but 21
  sequential grafts are 21 **independent** transactions, and a failure while grafting the part with
  `order == 11` leaves parts `0 … 10` durably committed. Atomicity is per part, not per migration;
  the spec must not imply otherwise.
- **Resume by index, because of the above.** A partial failure is a likely outcome over 21 grafts
  against a real database, and the double-run override is the wrong recovery lever — re-running with
  it would iterate the bundle from the start and graft parts `0 … 10` a *second* time. The import phase
  therefore reports the `order` of the last part committed, and accepts `--start-at K` to resume from
  the next one. For any `K > 0` the target is non-empty by construction, so `--start-at` bypasses the
  double-run guard by design.

  **The `K = 0` case is degenerate and is handled by not using `--start-at` at all.** If the very
  first graft (`order == 0`) fails, nothing was committed and the target is still empty — there is no
  "last part committed" to report. The failure message therefore says *no parts were committed; re-run
  `import` from the start*, and a plain re-run works because the empty target satisfies the double-run
  guard on its own. `--start-at 0` is accepted but redundant, and its invariant (target holds exactly
  0 top-level nodes) is precisely the guard's own condition, so the two agree rather than conflict.

  Resume-by-index is chosen over detecting already-present parts by title because an index is a
  stronger invariant than a string match in general: nothing in the schema makes sibling titles
  unique, so a title-keyed resume would be silently wrong the first time two parts shared a name, and
  it would fail in exactly the half-finished state where it is needed. (This corpus is known to carry
  duplicate-pattern titles one level down — 82 of its 111 chapters are `__PLACEHOLDER` — which shows
  the pattern is real here; whether the 21 *parts* themselves collide is not established, and the
  choice does not depend on it.)

  **One index space: the 0-based `order`.** `ContentNode.order` is assigned by `OrderField.pre_save`,
  which starts the first sibling at **0** (`except ObjectDoesNotExist: value = 0`), so the 21 parts
  carry `order` 0–20 and their archives are named `00-…zip` … `20-…zip`. Every index in this
  design — the archive filename, the "last part committed" the import phase reports, the `--start-at`
  argument, and the side table's part indices — is that same `order` value. A 1-based resume number
  would be off by one against the filenames an operator is literally reading in the bundle directory,
  which is precisely the mistype the invariant below exists to catch.

  So `--start-at K` grafts the parts with `order >= K`.

  **`--start-at K` must verify the index it is given, not trust it.** Because it deliberately bypasses
  the double-run guard, an operator who mistypes `K` — or reads a stale report, or points at the wrong
  bundle — would silently skip a part (a permanent content gap in the middle of the course) or graft
  one twice, which is exactly the failure class that guard exists to prevent. So before grafting, the
  command asserts the target course currently holds **exactly `K` top-level nodes MORE than it held
  before this migration began**, and aborts with a clear message on mismatch. The operator supplies
  the intent; the command checks the fact.

  **The invariant is against a captured BASELINE, not against a raw `K`.** `existing == K` is only
  correct when the target was empty before the migration started; the moment `--force` grafts into a
  target that already held its own top-level nodes (e.g. 2 pre-existing ones), that stops holding: part
  0 commits (making 3 nodes total), part 1 fails, the failure hint says `--start-at 1`, but a
  baseline-naive invariant then demands *exactly* 1 top-level node and aborts on the very hint it just
  printed — the advertised recovery path is unusable. So the FIRST invocation for a given bundle+target
  (the one where `--start-at` is not given, or is given as the degenerate `0`) captures the target's
  pre-migration state — top-level node count, all-levels node count, per-kind node counts, element
  count, media count — and writes it once to a small on-disk marker beside the bundle
  (`import-baseline.json`). Every later `--start-at K > 0` resume reads that SAME baseline back and
  checks `existing == baseline.top_nodes + K`, so the invariant and the hint always agree with each
  other regardless of what the target held before `--force` ever ran. `verify` reads the same baseline,
  for the same reason (see Verification).
- **Dry run.** A mode that reports what *would* be grafted — per-part node, element and media counts
  against their caps — while writing nothing. (The element count matters most: at a ~955 average
  against a 20,000 cap it has the widest headroom, but it is also the count a single outsized part
  would blow first.)
- **The source is never mutated.** The export phase only reads.

### Verification

> **This section describes a deliberate strengthening beyond the version of the spec that shipped
> the first three tasks.** Review of the initial implementation found that `verify` reconciled the
> target against **the bundle directory as found on disk** — archives it re-opened at verify time —
> never against a trustworthy record of what the *source* actually produced. That meant a bundle
> mixed from two different export runs (see "Re-running export requires `--clean`" above) could be
> grafted and then `verify`-blessed as complete, because `verify` had no independent way to know the
> bundle was incomplete. The fix below — a single manifest written once, atomically, on export
> success, plus a target-side baseline captured once at the true start of an import — is not what the
> original spec asked for; the original was too weak, and this replaces it.

The user asked for counts plus a broad sample rather than an exhaustive sweep. The command supports
the counting half directly: a mode that compares the target's totals against the bundle's own
recorded tallies — total nodes, per-**kind** node tallies (part/chapter/section/unit), total
elements, and media — and reports any mismatch. For the migration the node and element tallies should
match exactly — 21 parts / 111 chapters / 793 units, ~20,054 elements — and media should also match
exactly once cross-part sharing (see below) is accounted for. Elements are ~20,054 of the ~21,000
objects a full migration moves; a verification that only ever counted bare `ContentNode` totals would
never notice a lost or malformed element.

**The bundle manifest (`bundle-manifest.json`).** `export` writes this once, only after every part has
exported successfully — so its mere presence on disk means "this bundle is a complete, single-vintage
export", never a partial or mixed one. It carries: the source course's slug; `part_count`; the
**source's own tallies** frozen at that moment (`total_nodes`, `node_kind_counts`, `total_elements`,
`media_count`); and the media cross-part-sharing table (below). `import` refuses to graft anything
unless this manifest is present **and** its declared `part_count` matches the number of `*.zip` files
actually in the bundle directory — the completeness check that moves BEFORE the destructive graft step
rather than living only in `verify`, after the fact. `verify` performs the same check, then reconciles
the target against the manifest's recorded tallies — never against whatever archives happen to be
sitting in the bundle directory right now, which could have been edited, thinned, or mixed with a
different export since the manifest was written. (`verify` additionally re-opens each archive as a
lightweight integrity cross-check — corrupt or hand-edited content still surfaces, wrapped as a
`CommandError` rather than a raw `TransferError` or traceback.)

**The target-side baseline (`import-baseline.json`).** Both the `--start-at` invariant (see Guards,
above) and `verify` need to know what the target held *before this migration touched it* — trivially
zero for the standard prepared-empty-target workflow, but not after `--force`. `import` captures this
once, at the true start of a migration (the first invocation for which no such file yet exists: a
plain import, or the degenerate `--start-at 0`), and every later resume or `verify` call reads the
SAME captured baseline back rather than re-deriving it from whatever the target currently holds
(which, mid-migration, already includes this migration's own partial progress). `verify` refuses to
run without it, for the same reason it refuses to run without the bundle manifest: a delta computed
against an unknown baseline is uninterpretable.

**Node and element tallies are exact, reconciled as `baseline + bundle → target`.** For each of total
nodes, each node kind, and total elements: `expected = baseline value + bundle manifest's tallied
value`; a mismatch against the target's actual count aborts `verify` naming the discrepancy.

The sample half is a render check performed after the real cutover, deliberately spanning the element
families most likely to break in transit: a spoiler unit, the `250_pole` fill-table with its
`colspan` explanation rows, a video unit, a math unit, an interactive-in-spoiler unit, and the
binary-tree `HtmlElement` unit ("Klasyfikacja czworokątów").

**The media count may legitimately exceed the source's distinct-asset count — but the TARGET total is
fully determined, so `verify` checks it exactly, not as a floor.** `build_export` instantiates a fresh
`MediaIdMap` per call, scoped to the single subtree being exported, so an asset referenced from more
than one top-level part is exported into each of those parts' archives and re-materialised once per
archive on import — arriving as two `MediaAsset` rows in the target. Whether any cross-part sharing
exists in this corpus is a database fact, not a source fact, and is unverified here. But
`_create_media` materialises exactly one `MediaAsset` row per `document["media"]` entry — the same
list the side table is built from — so the TOTAL number of rows the import will create is fully
determined by that table; it is not merely bounded below by it. A floor-only check (`floor <= actual
<= ceiling`) accepts an import that lost exactly one re-materialised asset out of several duplicates of
a shared one, landing the actual count between the floor and the ceiling — silently. So `verify`
computes the exact expected total (`baseline media count + sum of every part-list's length in the
table`) and requires the target's actual count to equal it precisely.

**The archive's own media ids cannot do the cross-part-sharing correlation.** `MediaIdMap.register`
assigns `f"m{len(self._assets) + 1}"` and the map is per-`build_export`-call, so every part's document
restarts at `m1`. Correlating on the archive-local `id` field would flag `m1`/`m2`/`m3` in nearly
every part whether or not any asset is genuinely shared — near-universal false positives.

The correlation is instead made where the source primary keys are still in hand: the export phase
already receives `media_assets` as `(mid, asset, is_placeholder)` triples, so it accumulates a
**media table inside the bundle manifest** mapping each source `MediaAsset.pk` to the list of part
indices whose archive contains it. Those indices are the same 0-based `order` values used in the
archive filenames (see "One index space"), so a table entry `[3, 7]` reads directly against `03-…zip`
and `07-…zip`. It is accumulated in memory across the whole export loop and folded into the manifest
once, only on full success — exactly like every other manifest field, and for the same reason: a
partial table would make `verify` under-report cross-part sharing and turn a legitimate media surplus
into an apparent fault.

Entries with more than one part index are genuine cross-part sharing and explain part of a target
media count above the source's distinct-asset count; the exact-equality check above is what actually
distinguishes that from a fault, not merely a floor.

## Data flow

**Export phase**, per part: source course → `build_export(course, node=part)` produces
`(manifest, document, media_assets, problems)` → `problems` is checked (see "The real export-side
risk") → `write_archive_from(manifest, document, media_assets, fileobj)` writes a zip containing
`manifest.json`, `course.json`, and the media payload → one file per part in the bundle directory.

Across the whole loop, the export phase also accumulates the source-`MediaAsset.pk` → part-index
mapping and the node/element tallies in memory, and writes them once as the bundle manifest **only
after every part has exported successfully** — so an aborted run leaves archives but no manifest, and
never a stale one. `export` also refuses to start writing into a bundle directory that already holds
archives or a manifest from an earlier run, unless `--clean` is passed (see "Re-running export
requires `--clean`", above).

**Import phase**: first, the manifest completeness gate (bundle manifest present, its `part_count`
matches the archives on disk) — BEFORE anything is written to the target. Then, per archive in part
order: file → `open_archive(fileobj, expected_kind=…)` → `validate_archive_document(...)` →
`import_subtree(zf, manifest, document, media_entries, target_course, None, user)` — every parameter
is positional, and `None` is the top-level insertion point — → new `ContentNode` rows under the target
course, new `MediaAsset` rows with fresh primary keys, and media files materialised from the archive.
Before the first graft of a fresh (non-resume) run, the target's pre-migration baseline is captured
and written to `import-baseline.json` beside the bundle (see Verification).

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
grafts nothing and reports success would be indistinguishable from a completed migration. Likewise, a
`--start-at K` that lands beyond every part in the bundle (the whole migration is already complete)
says so explicitly ("nothing to do") rather than falling through to print `last part committed: None`.

**A bundle whose manifest is missing, or whose declared `part_count` disagrees with the archives on
disk, is refused by BOTH `import` and `verify`** — never proceeding as though the bundle were complete.
This is the completeness gate that catches a mixed-vintage ("Frankenstein") bundle: a missing manifest
means the export that produced this bundle never completed; a `part_count` mismatch means the bundle
directory has since been edited (an archive removed, or archives from two different export runs
present together). `import` checks this BEFORE grafting anything; `verify` checks it before trusting
the manifest's recorded tallies.

**`verify` aborts when the target has no recorded pre-migration baseline**, for the identical reason it
aborts on a missing manifest: `import-baseline.json` is written once, by the invocation that began the
migration, and a media/node delta computed against an unknown baseline is uninterpretable —
defaulting to "the target started empty" would report legitimate pre-existing content (e.g. after
`--force`) as a fault, the exact inversion the baseline exists to prevent.

**A malformed manifest or baseline file, and a corrupt archive encountered during `verify`'s own
integrity cross-check, surface as `CommandError`** — `json.JSONDecodeError` and `TransferError` are
both wrapped, exactly as `import` already wraps `TransferError` around its own archive-opening.

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
- **A non-empty `problems` list aborts the export phase**, and `--allow-problems` lets it proceed.
- **`--as-user` resolves to a real user and stamps `MediaAsset.uploaded_by`** on imported assets; an
  unknown email fails clearly rather than importing with a null uploader.
- **Re-running export without `--clean` is refused**, rather than merging into the existing bundle;
  **with `--clean` it replaces the bundle wholesale**, including removing a stale archive a *smaller*
  re-export would otherwise leave behind (the Frankenstein-bundle scenario).
  `ContentNode.order` is not database-unique, and two top-level nodes sharing an order must abort the
  export rather than silently letting the second overwrite the first's archive.
- **Archive filenames are parsed as an integer, not sorted as text** — `_bundle_archives` must order
  `["2-x.zip", "10-x.zip", "100-x.zip"]` correctly and must name-and-reject any `*.zip` not matching
  `<order>-<slug>.zip`, both as direct unit tests of the parsing (no need for a 100-part course fixture
  to exercise the bug).
- **Dry-run drives the real validator** (`open_archive` + `validate_archive_document` per archive) and
  writes nothing (including the baseline file), so every cap is exercised rather than a hand-picked
  subset.
- **`import` and `verify` both refuse a bundle whose manifest is missing, or whose declared
  `part_count` disagrees with the archives currently on disk** — the completeness gate, exercised
  BEFORE any destructive write (assert the target gains zero nodes from a refused import).
- **`--start-at K` aborts when the target does not hold exactly `K` top-level nodes**, so a mistyped
  index cannot silently skip or duplicate a part. Cover the off-by-one explicitly: with parts
  `0 … 10` committed, `--start-at 11` proceeds and `--start-at 10` and `--start-at 12` both abort.
- **The `--start-at` invariant is baseline-aware, not raw-`K`**: `--force` onto a target holding
  pre-existing top-level nodes, a mid-run failure, and a resume via the EXACT `--start-at` hint the
  command printed must succeed — proving the invariant and the hint agree with each other rather than
  merely that each is independently plausible.
- **A `--start-at K` beyond every part in the bundle says "nothing to do"** rather than printing
  `last part committed: None`.
- **A failure on the very first part reports "no parts committed"** and is recoverable by a plain
  re-run, not by `--start-at` — the degenerate `K = 0` boundary.
- **The bundle manifest's media table correlates shared media by source pk**, and verification uses it
  to explain a positive media delta — a test should cover an asset referenced from two parts arriving
  as two target rows *and* being accounted for, rather than reported as a fault.
- **Verification's media check is exact, not a floor**: deleting one imported `MediaAsset` — in a
  scenario where an asset IS shared across parts, so floor < ceiling — must make `verify` abort. A
  floor-only check would pass this silently (the count still sits within the floor..ceiling range),
  which is precisely the weakness being tested against.
- **Verification checks total elements and per-kind node tallies**, not only a bare total-node count —
  a lost element, or a node whose kind was corrupted without changing the total node count, must each
  be independently detectable.
- **`verify` refuses to run without a recorded pre-migration baseline** (i.e. before any `import` has
  run against this bundle+target), for the same reason it refuses without a manifest.
- **A malformed manifest/baseline JSON file and a corrupt archive encountered by `verify` both surface
  as `CommandError`**, never a raw `json.JSONDecodeError` or `TransferError`.
- **A corrupt or oversized archive in the bundle names that specific archive** in the import phase's
  error, rather than escaping as a raw traceback — the promise made in Error handling, and the
  failure mode most likely to occur across 21 real archives.
- **Resume by index:** a run that fails while grafting the part with `order == K` leaves parts
  `0 … K-1` committed, and `--start-at K` grafts the remainder without duplicating them. Test the
  whole sequence, not just the flag.
- **The `HtmlElement` round-trip described above** — as a regression guard on the not-sanitized
  policy, not as a mitigation.

### The HtmlElement round-trip: a regression guard, not a live risk

An earlier draft of this spec claimed `importer._build_html` passes imported html through
`sanitize_html`, and treated the possible stripping of the binary tree's `data-binary-choose`
attributes as the project's foremost risk. **That was false and is corrected here.**
`_build_html` is `return _clean_save(HtmlElement(html=data["html"])), ()` — no sanitisation on that
path. The only `sanitize_html` call in the importer is for a question stem. The model states the
policy outright: `html = models.TextField(blank=True)  # raw author HTML/CSS/JS — NOT sanitized`
(`courses/models.py`), because the **sandboxed iframe, not sanitisation, is the security boundary**
for `HtmlElement`.

So the attributes are not at risk today. The round-trip test is still worth writing — it is nearly
free and it pins the policy, so that anyone who later adds sanitisation to `_build_html` discovers
they have broken the binary tree — but it is a **regression guard, not a mitigation**, and it must
not displace the real export-side risk described immediately below.

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
