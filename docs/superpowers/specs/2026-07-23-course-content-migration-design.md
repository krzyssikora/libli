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
manage.py migrate_course_content export --source-slug <slug> --bundle-dir <dir> [--allow-problems]
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
  without opening 21 archives to read their manifests.
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

**Re-running export is safe and overwrites.** Because a problems-abort partway through leaves the
already-exported archives on disk, the export phase must define its own re-run behaviour rather than
inheriting the import side's. Archive names are deterministic (`{order:02d}-{slug}.zip`), so a re-run
simply overwrites by filename. No resume-by-index is needed here: export is read-only against the
source and cheap to repeat, so a clean full re-export is always correct — unlike import, where
re-running would duplicate committed content.

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
  command asserts the target course currently holds **exactly `K` top-level nodes** (parts `0 … K-1`,
  all already committed) and aborts with a clear message on mismatch. The operator supplies the
  intent; the command checks the fact.
- **Dry run.** A mode that reports what *would* be grafted — per-part node, element and media counts
  against their caps — while writing nothing. (The element count matters most: at a ~955 average
  against a 20,000 cap it has the widest headroom, but it is also the count a single outsized part
  would blow first.)
- **The source is never mutated.** The export phase only reads.

### Verification

The user asked for counts plus a broad sample rather than an exhaustive sweep. The command supports
the counting half directly: a mode that compares the target's totals against the bundle's — parts,
chapters, units, media, and per-element-type tallies — and reports any mismatch. For the migration
the node tallies should match exactly — 21 parts / 111 chapters / 793 units — while media should come
out at **at least** 1144, any excess being accounted for by the side table (see below). Stating the
media figure as an exact target would manufacture the very false alarm the side table exists to
prevent.

The sample half is a render check performed after the real cutover, deliberately spanning the element
families most likely to break in transit: a spoiler unit, the `250_pole` fill-table with its
`colspan` explanation rows, a video unit, a math unit, an interactive-in-spoiler unit, and the
binary-tree `HtmlElement` unit ("Klasyfikacja czworokątów").

**The media count may legitimately exceed the source's.** `build_export` instantiates a fresh
`MediaIdMap` per call, scoped to the single subtree being exported, so an asset referenced from more
than one top-level part is exported into each of those parts' archives and re-materialised once per
archive on import — arriving as two `MediaAsset` rows in the target. Whether any cross-part sharing
exists in this corpus is a database fact, not a source fact, and is unverified here.

So the verification mode must not treat "target media > source media" as automatically a bug. It
reports the delta, and must make that delta *diagnosable*.

**The archive's own media ids cannot do that job.** `MediaIdMap.register` assigns
`f"m{len(self._assets) + 1}"` and the map is per-`build_export`-call, so every part's document
restarts at `m1`. Correlating on the archive-local `id` field would flag `m1`/`m2`/`m3` in nearly
every part whether or not any asset is genuinely shared — near-universal false positives, and exactly
the opposite of what the preceding paragraph establishes.

The correlation must therefore be made where the source primary keys are still in hand: the export
phase already receives `media_assets` as `(mid, asset, is_placeholder)` triples, so it writes a
**bundle-level side table** — one small JSON file beside the archives — mapping each source
`MediaAsset.pk` to the list of part indices whose archive contains it. Those indices are the same
0-based `order` values used in the archive filenames (see "One index space"), so a side-table entry
`[3, 7]` reads directly against `03-…zip` and `07-…zip`.

**It is accumulated in memory and written once, only on a fully successful export.** Each
`build_export` call sees one part's assets, so the pk→parts mapping only exists as cross-part state
held by the export loop. Writing it incrementally would leave a stale, partial table behind after a
problems-abort partway through — and `verify` reading that table would silently under-report cross-part
sharing, turning a legitimate media delta back into an apparent fault. Exactly the hazard the archives
already handle via deterministic overwrite, which this artifact must not be exempt from: a re-run
overwrites the table wholesale, and an aborted run leaves none at all, so `verify` either finds a
table matching a complete bundle or refuses to run.

Verification reads that table:
entries with more than one part index are genuine cross-part sharing and explain a positive delta;
a delta that the table does not account for is an implementation fault. The side table lives outside
the archives and is never imported.

The 21 / 111 / 793 node tallies are exact; the 1144 media figure is a floor.

## Data flow

**Export phase**, per part: source course → `build_export(course, node=part)` produces
`(manifest, document, media_assets, problems)` → `problems` is checked (see "The real export-side
risk") → `write_archive_from(manifest, document, media_assets, fileobj)` writes a zip containing
`manifest.json`, `course.json`, and the media payload → one file per part in the bundle directory.

Across the whole loop, the export phase also accumulates the source-`MediaAsset.pk` → part-index
mapping in memory, and writes it once as the bundle side table **only after every part has exported
successfully** — so an aborted run leaves archives but no table, and never a stale one.

**Import phase**, per archive in part order: file → `open_archive(fileobj, expected_kind=…)` →
`validate_archive_document(...)` → `import_subtree(zf, manifest, document, media_entries,
target_course, None, user)` — every parameter is positional, and `None` is the top-level insertion
point — → new `ContentNode` rows under the target course, new `MediaAsset` rows with fresh primary
keys, and media files materialised from the archive.

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

**`verify` aborts when the bundle has no side table**, rather than proceeding as though no media were
shared. A missing table means the export that produced this bundle did not complete, so any media
delta it computed would be uninterpretable — and defaulting to "nothing is shared" would report
legitimate duplication as a fault, the exact inversion the table exists to prevent.

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
- **Re-running export overwrites existing archives** in the bundle directory rather than erroring or
  silently skipping.
- **Dry-run drives the real validator** (`open_archive` + `validate_archive_document` per archive) and
  writes nothing, so every cap is exercised rather than a hand-picked subset.
- **`--start-at K` aborts when the target does not hold exactly `K` top-level nodes**, so a mistyped
  index cannot silently skip or duplicate a part. Cover the off-by-one explicitly: with parts
  `0 … 10` committed, `--start-at 11` proceeds and `--start-at 10` and `--start-at 12` both abort.
- **A failure on the very first part reports "no parts committed"** and is recoverable by a plain
  re-run, not by `--start-at` — the degenerate `K = 0` boundary.
- **The bundle side table correlates shared media by source pk**, and verification uses it to explain
  a positive media delta — a test should cover an asset referenced from two parts arriving as two
  target rows *and* being accounted for, rather than reported as a fault.
- **An aborted export leaves no side table**, and `verify` refuses to run against a bundle whose table
  is missing rather than silently treating every asset as unshared.
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
