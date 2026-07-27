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

**Part 3 changes no *signature* part 2 pins, but it does extend two of part 2's contracts, and the
part-2 branch has to land them.** Part 2 is converged and being implemented in a parallel branch, so
the coordination is named precisely rather than waved at:

- **No arity or return type changes.** `rewrite_links(html, mapping, *, on_missing) -> tuple[str, int]`,
  `rewrite_instance(instance, mapping, *, on_missing) -> tuple[list[str], int]`,
  `find_link_targets(html) -> set[int]`, `iter_rich_text(instance) -> Iterator[tuple[str, str]]` and
  `count_inbound_links(course, node) -> int` are consumed exactly as part 2 writes them. Where this
  spec needed a number those return types do not carry, it derives the number here rather than
  widening part 2 — see §Counts.
- **`on_missing` gains a third value, `defer`,** on `import_subtree`. Part 2 pins two.
- **`import_subtree`'s `report` gains `node_map`,** and gains the guarantee that `node_map` is
  populated outside the rewrite post-pass and that `flattened_links` is present-and-`0` under `defer`.
  Part 2 documents `report` as carrying `flattened_links`, delivered by the post-pass.

Both extensions are additive and land on **this** branch, not part 2's; part 2's own tests and call
sites keep passing unchanged because the new value and the new key are only ever requested here.
§Error handling also records the one converged part 2 bullet this spec **supersedes**.

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
| `courses/management/commands/migrate_course_content.py` | bundle-level `node_index` at export; `defer` per part + a `LINK_STATE_NAME` state file written inside an outer atomic; one final rewrite pass; `--resolve-rewrite` (+ `_ACTION_FLAGS` / `_FLAG_UNSET`); `manifest` captured at `:387`; stdout counts; `verify` reporting and its link reconciliation |
| `tests/test_migrate_course_content.py` | the cases in §Testing |

**Out of scope:** everything part 2 owns — the registry, the anchor scanner, `document["link_nodes"]`
itself, the delete warning, and the Studio import warning. In particular `courses/richtext.py` is
**unchanged**, and neither `rewrite_links` nor `rewrite_instance` changes arity or return type. This
spec changes no sanitiser, no model and no template.

`courses/builder.py` is likewise unchanged: it unpacks `build_export`'s 4-tuple positionally and never
passes `report`.

## Architecture

**The management command is the cutover, and the naive default breaks it.** Besides the Studio view,
`courses/management/commands/migrate_course_content.py:481` is the second production caller of
`import_subtree` — the fourth caller once the importer's other entry points (`import_course`,
`materialize_duplicate`) are counted, which is the sense in which part 2 numbers it. That command *is*
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

`defer` skips the *rewrite*, not the *bookkeeping*: **`report["node_map"]` is populated
unconditionally**, before and outside the post-pass, for all three `on_missing` values. It is the one
thing part 3 needs from every part, and the natural reading of "skip the post-pass entirely" would
drop exactly it. Under `defer`, `report["flattened_links"]` is **present and `0`**, not absent, so
callers can read it without a `.get`.

### Export phase — the bundle-level `node_index`

Export additionally writes a **bundle-level** `node_index` into `bundle-manifest.json`, covering every
node in the source course rather than only the current part. It is deliberately **not** called
`link_nodes`: part 2's `document["link_nodes"]` is `{str(pk): "nN"}` and holds only *link targets
inside one exported set*, while this holds *every node in the course* and a pair value. Two shapes one
document apart under one name is how a lookup silently misses.

Its JSON shape, literally, with the pair order fixed as `[part order, export id]` (JSON has no tuple
type; it round-trips as a 2-element list):

```json
"node_index": {"1234": [0, "n7"], "1235": [0, "n8"], "9001": [3, "n1"]}
```

Keys are decimal strings of the **source** pk — JSON object keys are always strings, and every read
site parses them with `int()`. Values pair the **integer part order** — the value `part.order` supplies
at export and `_archive_order(p.name)` parses back at import — with the export id. The join key is that
integer, never the filename: `_ARCHIVE_NAME_RE`'s own comment
(`migrate_course_content.py:56-60`) records that archive names are not zero-padded to a fixed width, so
a lexicographic sort of them is wrong at ≥100 parts. Export ids restart at `n1` in every archive
(`export.py:506`, `enumerate(nodes, start=1)`), so if the two phases keyed this differently every
lookup would miss and the whole course's links would flatten, silently.

The index is accumulated across parts and folded into the manifest once, after all parts export —
exactly the lifecycle the existing per-part media `side` map already has
(`migrate_course_content.py:301-303`), and exactly when the whole mapping is known. Its union covers
every node in the course because every node descends from some top-level part.

This needs plumbing the exporter lacks: `node_ids` is a local at `export.py:504` and `_node_dict`
(`export.py:456-468`) never emits the source pk. It is handed back through an **optional `report`
keyword**, not a fifth return value — `build_export` returns a 4-tuple that is unpacked positionally
at **28 sites across 10 files**, plus one indexed call in `tests/test_tabs_transfer.py:29`, for 29 call
sites across 11 files. Those include `courses/builder.py:333`, which §Scope declares unchanged.
Widening the arity would break every one of them, and would contradict the reasoning that already made
`report` an out-param on the importer. Only `migrate_course_content._export` passes it.

The exporter's key is **`report["node_ids"] = {pk: "nN"}`** — int keys, the local's shape verbatim.
It is populated whenever `report` is supplied, **including on the `problems` path**: `build_export`
returns from inside `with transaction.atomic()` after tolerant-export skips, and `--allow-problems`
must not cost the operator the node index. Note that the exporter's `report` and the importer's
`report` are unrelated dicts that merely share a keyword name; neither reads the other's keys.

The per-part `document["link_nodes"]` cannot substitute — it holds only targets referenced from
inside that part, so a node linked to *only* from another part appears in no archive's map at all.

### Import phase — the state file

Import passes `on_missing="defer"` per part and accumulates the map in a bundle-level state file,
`LINK_STATE_NAME = "import-link-state.json"` (a module constant beside `MANIFEST_NAME` and
`BASELINE_NAME`). Building it needs `export_id → new_pk`, which `import_subtree` does not return today
(`importer.py:1003` hands back only the grafted root — `return node_map[document["nodes"][0]["id"]]` —
and `node_map` stays local to `work()`, which `:1005` passes to `_run_import`) — so
**`report` also receives `node_map`** as `{export_id: new_pk}` alongside `flattened_links`. Part 2's
own `node_map` is `{export_id: ContentNode}`; the importer emits the pk-valued projection of it into
`report`, so the state file stays JSON-serialisable.

Its schema, in full:

```json
{
  "version": 1,
  "status": "collecting",
  "target_slug": "mat-pp",
  "target_pk": 42,
  "parts": [
    {"order": 0, "node_map": {"n1": 4711, "n2": 4712}, "src": {"n1": 1234, "n2": 1235},
     "rewritten": false},
    {"order": 1, "node_map": {"n1": 4790}, "src": {"n1": 9001}, "rewritten": false}
  ]
}
```

- `parts` is a **list of objects, not an object keyed by order**. This is not stylistic: JSON coerces
  integer object keys to strings, and `max()` over string keys is lexicographic. `json.loads(
  json.dumps({0: …, 9: …, 10: …}))` yields keys `"0" "9" "10"`, whose `max()` is `"9"` — with mat-pp's
  21 parts the resume guard below would be wrong from part 10 onward, rejecting a legitimate
  `--start-at 10` or accepting an incomplete map. A list of objects has no string keys to coerce.
  Defensively, every `order` read back is still passed through `int()` before any comparison.
- `node_map` keys are export ids (already strings); values are integer target pks. `src` is the same
  part's `{export_id: source_pk}`, inverted from the manifest's `node_index` at graft time — see the
  re-export guard below, which it exists to serve.
- **`target_slug` and `target_pk` are recorded at first write and re-checked on the resume path**
  (step 4 of §trigger's ordered branch) — not under `--resolve-rewrite`, which precedes it, and not on
  `start_at is None`, which rewrites the file. **`target_pk` is authoritative**; `target_slug` is
  carried so the error message can name the course, and so a rename between import and the final pass
  produces no spurious failure. A pk mismatch is a `CommandError`; a slug mismatch with a matching pk
  is a printed note that the course was renamed. Without these the file is a bag
  of pks with no statement of which database they belong to, and a resume against the wrong target
  would not be refused — the pass's `course=target` liveness filter would simply find nothing live,
  producing an empty `mapping` and, but for the fatal rule in §mechanics, a whole-scope flatten. The
  bundle-scoped `BASELINE_NAME` gets away without this only because the `:433` count invariant
  catches a wrong target indirectly; the state file has no such backstop.
- `status` is one of `collecting` (at least one recorded order is un-rewritten), `in_progress` (the
  rewrite transaction has been entered), `applied` (every recorded order has been rewritten). A
  `rewrite` object is added when the pass completes — see §Counts.
- **`rewritten` is per part order, and this is not bookkeeping — it is what makes a repair resume
  correct.** A single top-level `applied` flag is wrong, because a part can be re-grafted *after* the
  pass has run: full import → pass applies → the operator deletes one bad part → `import --start-at K`
  re-grafts it. `:433` accepts that resume, so the part is committed again with its hrefs holding
  **source** pks, and a top-level-`applied` trigger would never fire again — leaving them silently
  pointing at whatever target rows occupy those pks, which is the exact failure this spec exists to
  prevent, with no command able to reach the pass afterwards. This is not hypothetical: the existing
  green `test_start_at_grafts_only_the_remainder`
  (`tests/test_migrate_course_content.py:432`) performs precisely that sequence.

  So **grafting an order always writes `rewritten: false` for it and resets top-level `status` to
  `collecting`**, whether it is a first graft or a re-graft, and the pass is scoped to the *pending*
  orders only (§mechanics). The once-only invariant is preserved per order rather than per migration:
  each order's elements are rewritten exactly once per graft, and orders already rewritten are
  excluded from the scope, so the old-pk-keyed map is never re-applied to hrefs that already hold
  target pks.

Entries are appended **immediately after each part commits**, not once after the loop. Writing once
would lose every committed part's `export_id → new_pk` on a mid-loop failure, and those are
unrecoverable afterwards — export ids exist only in the returned `node_map`.

**The residual window is real and must be closed, not narrowed.** Per-part writing does not by itself
close it. `import_subtree` commits inside `_run_import`'s `transaction.atomic()` (`importer.py:924`);
a state write placed after that call necessarily follows the commit, so a crash in the gap leaves part
K's rows committed with its `export_id → new_pk` gone forever. The existing top-node invariant then
sees `baseline["top_nodes"] + K + 1` nodes while the state file records at most order `K-1`, and both
that invariant and the new guard below refuse every resume — a genuinely unrecoverable state, since
export ids exist nowhere else.

So the command **wraps each part's `import_subtree` call in its own outer `transaction.atomic()` and
performs the state-file append inside that block, before it exits.** `_run_import`'s atomic then
becomes a savepoint, and the real commit happens when the outer block exits — *after* the file write.
That inverts the window: a crash between the two now leaves a **stale** entry (recorded, never
committed) instead of a **missing** one.

The inverted failure is recoverable where the original is not — but **not by the mechanism an earlier
draft claimed**, and the difference decides which guard is load-bearing:

- The top-node invariant does **not** refuse a stale entry's resume. Walk `:429-439`: after the crash
  at part K the target holds `baseline["top_nodes"] + K` top-level nodes, so the *correct* resume
  `--start-at K` computes `expected_existing == baseline + K == existing` and is **accepted**. The
  invariant refuses only the *wrong* resume (`--start-at K+1`). A stale entry therefore does reach the
  run.
- What makes it safe on the accepted path is the re-graft: appending an entry for an order already
  present **replaces** it rather than duplicating, so part K's stale `node_map` is overwritten with the
  real one before the trigger can fire. The failure path's own guidance — *resume with `--start-at
  <last committed + 1>`* (`:497-500`) — is the operator-facing recovery.
- The liveness filter is a **fatal defensive assertion**, not a silent repair. Walking the guards, a
  surviving stale entry has no non-adversarial reachable path: at the accepted `--start-at K` the
  re-graft replaces it, at the wrong resume the `:433` invariant refuses, and on `start_at is None`
  the whole file is overwritten. So the pass **refuses** — `CommandError`, per §mechanics — when a
  recorded pk has no live `ContentNode` row in the target course, rather than dropping it and
  continuing. Dropping it silently would flatten every href into that part, which is the outcome
  §trigger calls catastrophic. §The final pass — trigger supplies the other half of this defence, the
  `not todo` conjunct at site 1.

The `on_commit` concern an earlier draft asked the implementer to "confirm" is **measured and moot**:
`rg -n "on_commit"` over the app finds only `accounts/signals.py:36`, `notifications/services.py:37`
and `courses/signals.py:32` (a `post_delete` receiver on `MediaAsset`, which an import never fires).
There are no import-path callbacks whose timing the outer block could disturb.

The real, unobvious consequence of the outer block is **orphaned media files**, and it is accepted
rather than fixed. `created_files` is local to `import_subtree` (`importer.py:995`) and
`_cleanup_files` runs only from `_run_import`'s four `except` handlers (`importer.py:927`, `:930`,
`:937`, `:947`) — never on success. So when the outer atomic rolls back *after* a successful
`import_subtree` — the designed stale-entry window, and also what happens if the `LINK_STATE_NAME`
write itself raises `OSError` inside the block — part K's re-materialised media files stay on disk
with no rows pointing at them and no cleanup hook. Magnitude: **one orphaned file set per crashed
part**, at most once per migration in practice, and the operator's re-graft writes a second copy.
That is a bounded disk cost against an unbounded correctness one, so the outer block stays.

**That path needs a handler, or it is a raw traceback.** The outer atomic sits inside the existing
`try:` whose only handler is `except TransferError` (`:490`), and an `OSError` from the state-file
write is neither a `TransferError` nor something `_run_import` normalises (it only wraps exceptions
raised inside `work()`). As written it would propagate out of `handle()` as a traceback — no
`CommandError`, no `--start-at` hint, `committed` left at its previous value, and no place to emit the
orphan log this paragraph promises. So the command wraps the outer atomic in its own
`except OSError` (or `except Exception`) that logs the part order and the orphaned-media note, then
re-raises as a `CommandError` carrying the guidance `:494-500` would produce **for the current value
of `committed`** — i.e. *both* arms, including the `committed is None` → "no parts committed; re-run
import from the start" case. Not just the `else` arm: `committed` is initialised to `None` at `:453`
and first assigned at `:502`, so an `OSError` on the **first** part would evaluate `None + 1` and
raise `TypeError` — a raw traceback, exactly the outcome this handler exists to prevent.

**The write must be atomic on the filesystem, too.** Inverting the DB/file ordering is pointless if
the file write itself can be torn. The three existing writes this one mirrors are plain
`Path.write_text` (`migrate_course_content.py:358`, `:409`, `:442`), which opens `mode="w"` and
**truncates before writing a byte** — tolerable for `BASELINE_NAME`, which is written at most once,
but `LINK_STATE_NAME` is rewritten **once per part** (21 times for mat-pp) and inside an open
transaction. A crash, `ENOSPC` or a kill in any of those 21 truncate-then-write windows leaves
truncated JSON, which §Error handling turns into a hard `CommandError` — discarding every committed
part's `export_id → new_pk` and reintroducing at the filesystem layer exactly the unrecoverable loss
the outer atomic was added to prevent. So: serialise to `LINK_STATE_NAME + ".tmp"` in the bundle
directory and `os.replace` it onto the real name. The `except OSError` handler below already covers
the failure of either step.

**Placement, exactly.** The outer `transaction.atomic()` opens immediately before the `import_subtree`
call at `:481` and closes after the state write — i.e. *inside* the `with open_archive(...)` body and
*after* the `--dry-run` `continue` at `:479`, not around the archive open. It must not wrap the zip
open: holding a DB transaction across archive extraction for 21 parts would extend it for no benefit,
and the dry-run `continue` must remain outside it so a dry run enters no transaction at all.

Keying entries by part order is what lets the final pass attribute its counts per part, and what lets
a resume detect a short file. The resume guard is stated against the archive orders on disk rather
than against a count, because **top-level `order` values are treated as possibly non-contiguous — a
deliberate defensive assumption, not a demonstrated fact.** The nearest evidence is that
`ContentNode.order` is not database-unique (`migrate_course_content.py:326-336`), which is a different
property and does not by itself establish gaps; `OrderField` renumbers on insert but a sibling delete
is the obvious way a gap could appear. Since nothing guarantees contiguity either, the guard costs
nothing to state safely and every rule in this spec applies the assumption **consistently** — the
resume guard, the trigger predicate, and the `--resolve-rewrite` recovery's `max(on_disk) + 1` all
work off the archive orders actually on disk. (The pre-existing `--start-at` invariant and the
"nothing to do" message carry the contiguity assumption already; that is inherited, not introduced,
and is not changed here.)

- Let `recorded = {int(e["order"]) for e in state["parts"]}` and `on_disk = {order for order, _path
  in ordered}` (the parsed archive orders).
- `--start-at K` is accepted only if `{o for o in on_disk if o < K} ⊆ recorded`. Otherwise
  `CommandError`: the map is missing a part that is supposed to be committed, and proceeding would
  flatten every link into it. Never evaluate `max()` on `recorded`; on a fresh bundle it is empty and
  `max(())` raises a bare `ValueError`, not a `CommandError`.

Missing- and empty-file branches are defined, mirroring how the existing code handles a missing
`BASELINE_NAME` on resume (`migrate_course_content.py:419-427`):

- `start_at is None` → write a fresh state file (`status: "collecting"`, `parts: []`).
- `--start-at 0` with no state file → the degenerate first invocation; start a fresh one.
- `--start-at K > 0` with no state file, or with an empty `parts` list → `CommandError` naming the
  cause: this migration's import began before internal-link support, so its `export_id → new_pk` map
  cannot be reconstructed; re-run `import` from the start against a clean target.
- A state file that is not valid JSON, or whose `version` is not `1` → `CommandError`, in the style of
  the existing `BASELINE_NAME` JSON guard.

Lifecycle: written fresh when `start_at is None`, read and extended on resume, and — like
`_capture_baseline`'s own write (`migrate_course_content.py:408`, `:441`) — **neither written nor
reset under `--dry-run`**, so a dry run cannot wipe a real migration's accumulated map.

**`export --clean` does not touch the state file, and neither does the `:278` refusal predicate.**
This reverses an earlier draft of this spec, which had `--clean` gain a third unlink; that rule would
have destroyed the command's own headline recovery path. The most common mid-run failure is a bad
archive, and repairing it means re-exporting into the same bundle directory, which `:278` refuses
without `--clean`. `tests/test_migrate_course_content.py:513`
(`test_start_at_recovers_after_force_and_a_mid_run_failure`) is exactly that sequence and is green
today: fail at part 1, `export … --clean` into the same bundle, `import --start-at 1`. Unlinking the
state file there would discard part 0's `export_id → new_pk` entries — which this section calls
unrecoverable, because export ids exist nowhere else — and the resume guard below would then reject
the very resume the command just printed. So the state file's lifecycle **genuinely does mirror
`BASELINE_NAME`**: never unlinked by `export`, overwritten fresh when `start_at is None`
(`migrate_course_content.py:393-397` does the same for the baseline, "always re-captures … overwriting
any left over"). Measured for the record: `rg -n "unlink" courses/management/commands/migrate_course_content.py`
returns exactly two hits (`:289` over `stale_zips`, `:291` for `stale_manifest`), and `BASELINE_NAME`
is never unlinked anywhere in the file — the earlier draft's "mirrors `BASELINE_NAME`" wording was
false only because of the unlink clause it has now dropped.

**Retaining the state file across a re-export needs one guard.** A retained entry is keyed by export
id, and export ids are positional (`enumerate(nodes, start=1)` over `_ordered_nodes`). A re-export of
an *unchanged* source reproduces them identically, which is why the retained map stays valid in the
test above. A re-export after the operator *edited* the source does not: `n7` in the new manifest may
denote a different node than the `n7` a committed part recorded, and the join would mis-point
silently.

**Comparing export-id *sets* does not detect this, and an earlier draft of this spec specified exactly
that.** Export ids are positional (`for i, n in enumerate(nodes, start=1): nid = f"n{i}"`,
`export.py:506-507`) and `_create_nodes` keys `node_map` by every node id in the document, so both
sides are *always* exactly `{n1 … nK}` for a part of K nodes. Measured: for K=5 the state-side set and
the manifest-side set are both `{'n1'…'n5'}` and compare equal no matter what those ids now denote.
Any count-preserving edit — **reordering two siblings** (`_ordered_nodes` sorts by `("order", "pk")`,
so a swap re-labels both), or deleting one node and adding another — passes a set comparison and
produces precisely the mis-point the guard is billed as preventing.

So the guard compares **source pks, not export ids**. Each state entry records the join it actually
used, which the command can build at graft time because the manifest's `node_index` inverts to
`{export_id: source_pk}` for that order:

```json
{"order": 0, "node_map": {"n7": 4711, "n8": 4712}, "src": {"n7": 1234, "n8": 1235}}
```

**The comparison runs in step 4 of §trigger's ordered branch — before `todo` is computed and before
anything is grafted** — not inside the pass. Placing it inside the pass makes it a post-mortem: graft
part 0, re-export `--clean` from an edited source, `import --start-at 1`; the subset guard passes
(`{0} ⊆ {0}`), `:433` passes, parts 1..N-1 are all grafted and committed from the *new* archives, and
only then does the comparison raise — leaving the full course committed, every link unrewritten, and
entry 0 unrepairable (`--resolve-rewrite` needs `in_progress`). It costs one dict comparison per
recorded part, so running it early is free. It stays inside the pass as a redundant assertion.

For every recorded part order, **`entry["src"]` must equal the `{export_id: source_pk}` inversion of
the current manifest's `node_index` for that order**. A mismatch is a `CommandError` naming the cause — *the bundle was re-exported from a changed source after part K
was grafted; the recorded map no longer describes it*. This is still cheap (one dict comparison per
part) and, unlike the set form, it actually identifies the nodes.

**Both sides must be built by one shared helper**, because the guard is a raw equality test on a fatal
path and `node_index` keys are decimal *strings*. Writing `src` per the schema (int values) while
computing the guard-time inversion without `int()` yields `{'n7': '1234'} != {'n7': 1234}` — measured
`False` — on every part of every run, permanently blocking the feature behind a spurious re-export
error. One helper, `_invert_node_index(node_index, order) -> {export_id: int(source_pk)}`, is called
at the graft-time write and at the guard.

### The final pass — trigger

**The final pass is triggered by bundle state, not by the loop.** The loop-completion reading has a
hole precisely where the state file exists to help: a process that dies after the last part commits
resumes with `--start-at part_count`, hits the "this migration is already complete" early return
(`migrate_course_content.py:445-451`), and never rewrites anything.

The trigger predicate is an explicit set comparison, safe against a gap left by the residual window
above:

**The trigger has two sites with two different predicates**, and conflating them breaks the feature in
one direction or destroys data in the other:

```
pending = {int(e["order"]) for e in state["parts"] if not e["rewritten"]}

site 1, immediately before the `if not todo:` at :445 (resume branch only):
    not todo  and  recorded == on_disk  and  state["status"] == "collecting"  and  pending

site 2, after the graft loop finishes (both branches):
    recorded == on_disk  and  state["status"] == "collecting"  and  pending
```

where `recorded` and `on_disk` are as defined in §Import phase. `pending` is what lets a re-grafted
order reach the pass again; grafting resets both it and `status` (§Import phase).

**Site 2 must not carry `not todo`.** An earlier draft of this spec used the site-1 predicate at both
sites, which makes the whole feature inert on its primary invocation: `todo` is a list that
`for order, archive in todo:` (`:454`) iterates but never empties, so `not todo` is `False` after any
run that grafted anything. Measured — iterate a 3-element `todo`, then evaluate: `not todo` → `False`,
so the pass never fires. The `start_at is None` branch (the mat-pp cutover itself) has no other
trigger site, so a single complete `export` → `import` would leave `status == "collecting"`, every
href still holding a source pk, §Testing's first bullet RED, and `verify` raising "lacks the applied
marker". Completing the loop without raising **is** the "nothing left to graft" evidence at site 2;
`recorded == on_disk` already covers coverage.

**At site 1, `not todo` is not redundant, and omitting it is catastrophic.** An earlier draft of this
spec wrote the predicate without it and evaluated it before the early return, which fires the pass
while parts are still ungrafted. Walk the stale-entry window at the *last* part: the outer atomic is entered for
part `N-1`, `import_subtree` succeeds, the state entry for `N-1` is appended and written, then the
process dies before the outer commit. Now `recorded == {0..N-1} == on_disk` and
`status == "collecting"`, while the target holds only `baseline + (N-1)` top-level nodes. The operator
resumes at the correct `--start-at N-1`: the `:433` invariant accepts (§Import phase — it accepts the
correct resume), `todo == [(N-1, …)]` is non-empty so the early return does not fire — and the trigger
fires anyway, **before part `N-1` is grafted**.

What happens next depends on §mechanics' fatal-skip rule, and it is worth being precise because an
earlier draft of this spec was not. Part `N-1`'s recorded pks have no live rows, so `skipped_dead` is
nonzero and the pass raises `CommandError` **before entering the transaction and before flipping
`status`** — nothing is flattened and nothing is committed. Measured: with `recorded == on_disk ==
{0,1,2}`, `todo == [(2, …)]` and part 2's pks absent from `live`, site 1 without `not todo` fires and
then aborts with `skipped_parts=0 skipped_ids=0 skipped_dead=1`.

So the outcome is a **stalled migration with a misleading error**, not data loss: the operator is
told a recorded node is missing from the target, when the real situation is simply that they resumed
correctly and the command evaluated the trigger too early. Part `N-1` is never grafted, and every
subsequent resume hits the same abort. That is reason enough for the conjunct — but the honest reason,
not the catastrophic one the earlier draft claimed. The two guards are complementary and both are
required: `not todo` keeps the pass from running early, and the fatal-skip rule keeps an early run
from destroying anything if `not todo` is ever removed.

Site 2 is safe against that same scenario without the conjunct: the loop grafts part `N-1` and
**replaces** its stale entry (§Import phase's append rule) before site 2 is reached, so by then
`recorded` describes only committed parts. If the loop raises, site 2 is never reached at all.

**`status == "collecting"`, not `!= "applied"`.** `"in_progress" != "applied"` is `True`, so the
negative form fires the pass on a state file left `in_progress` by a crash *after* the rewrite
committed — re-applying an old-source-pk-keyed map over hrefs that now hold target pks, which §The
once-only invariant identifies as the silent mis-point nothing can detect afterwards. The positive
form is safe by construction instead of relying on a guard elsewhere in the function.

Not `len(recorded) == bundle_manifest["part_count"]` and not `max(recorded) + 1 == len(archives)`;
only set equality rejects a bundle whose parts `0..N-1` are recorded but part K is not.

**The superset case is a `CommandError`, not a quiet `False`.** `recorded == on_disk` failing covers
two situations, and only one of them is benign. `recorded ⊂ on_disk` means parts are still to come —
correct to do nothing. `recorded ⊃ on_disk` means the bundle lost archives the state file says were
grafted, and it is reachable: graft parts 0,1,2, delete part 2 from the source, re-export `--clean`
(two archives, `part_count == 2`, so `_read_bundle_manifest`'s gate passes), resume `--start-at 3`.
`:433` accepts, `todo` is empty, and `{0,1,2} == {0,1}` is `False` — so the pass never fires, the
`src` drift guard never runs (it lives inside the pass), and the command prints the existing "this
migration is already complete" line and exits **0**. Only a later `verify` notices, and its message
names the marker rather than the cause. So: **`recorded - on_disk` non-empty → `CommandError`** naming
the orders recorded but no longer on disk. And, as a backstop against any other way of reaching the
end of `import` without the pass having fired at either site, the command prints an explicit
diagnostic line rather than exiting silently.

**Ordering is part of the requirement**, because the guards depend on when the state file is read.
This is **one ordered branch, not a list of independent gates** — an earlier draft stated steps 1 and
2 separately, which made step 1's unconditional refusal swallow step 2 and re-closed the very deadlock
`--resolve-rewrite` exists to open:

1. **Load** the state file (or note its absence). Validate JSON and `version`. Do not act on `status`
   yet.
2. **If `--resolve-rewrite` was supplied**, hand control to the terminal action (§Crash-safe marking)
   and return. This precedes every status refusal — the flag is legal only when `status ==
   "in_progress"`, so a refusal that fires first would make it unreachable by construction.
3. **If `start_at is None`**, the loaded file is discarded and a fresh one written — but **not here.**
   The write is pinned to the same place as the existing baseline write: **inside
   `if not o.get("dry_run"):` at `:408-411`, i.e. behind the `:401` double-run guard.** Both
   conditions are load-bearing and an earlier draft of this spec had neither:

   - *Behind `:401`.* Placed before it, a plain re-run after a crash (`import` with no `--start-at`,
     no `--force`) would wipe `parts` to `[]` and *then* raise "target already has N top-level
     node(s)" — consuming the `export_id → new_pk` map on an invocation that does nothing else.
     §Import phase calls those entries unrecoverable, so an aborted invocation must never consume
     them. The analogy to `:393-397` is about *overwrite semantics*, not placement: the baseline's
     own write is at `:409`, already behind the guard.
   - *Behind the dry-run gate.* Otherwise `import --dry-run` over a bundle holding a real accumulated
     map would destroy it, on the one flag that promises to write nothing — contradicting both
     §Import phase's Lifecycle rule and §Testing's byte-identical assertion.

   The fresh file carries **all five top-level keys** of the schema — `version`, `status:
   "collecting"`, `target_slug`, `target_pk`, `parts: []` — since this is the first write on the
   primary invocation and the resume path's identity check reads the two `target_*` fields.

   **No status check applies on this path.** A leftover `in_progress` or `applied` file from an
   earlier migration through this bundle must not block a legitimate fresh re-import. Step 5 has
   already happened on this branch (`todo = ordered` at `:407`, ahead of the write); continue at
   step 6.
4. **Otherwise** (a resume) apply, in this order: the `in_progress` refusal of §Crash-safe marking;
   the `target_pk` identity check; the resume subset guard; the **`recorded - on_disk` non-empty**
   refusal; and the **`src` re-export drift comparison** over every recorded entry. The last two are
   fatal gates that must run *before* anything is grafted — see §Import phase for why placing the
   drift check inside the pass makes it a post-mortem. (Both are inert on the other two branches:
   step 3 rewrites `parts` to `[]`, and step 2 has already returned.)
5. Compute `todo` (`:440` on this branch; on the `start_at is None` branch it was already computed at
   `:407`, ahead of step 3's write).
6. The trigger is then evaluated at exactly two sites: **immediately before the `if not todo:` at
   `migrate_course_content.py:445`** — i.e. on the `--start-at` branch only — and **after the graft
   loop finishes**, on both branches. Naming the site matters: `todo` is assigned in two mutually
   exclusive branches (`:407` for `start_at is None`, `:440` for the resume path) and the early return
   exists only in the second, so "after `todo` is computed" would name two sites where only one has
   the anchor the sentence pairs it with. The `start_at is None` branch has no early return and
   evaluates the trigger only after the loop.

On `verify`, an `in_progress` file **always** raises; `--resolve-rewrite` does not exist there.

The existing message `"nothing to do: --start-at K is at or beyond the bundle's N part(s); this
migration is already complete"` is printed **only when the pass did not fire there** —
`tests/test_migrate_course_content.py:572` (`test_start_at_beyond_all_parts_reports_nothing_to_do`)
asserts that string and must keep passing for an already-`applied` migration. When the pass *does*
fire on that path, the command instead prints `"no parts left to graft; applying the deferred link
rewrite"` followed by the counts.

Skipped entirely under `--dry-run`.

### The final pass — scope and mechanics

**Its scope is the `Element` rows whose `unit_id` appears among the *pending* orders' new pks** —
that is, the orders whose `rewritten` flag is `false`. On a first full migration that is every
recorded order and the distinction is invisible; on a repair resume it is the one re-grafted order,
and scoping to it is what keeps the old-pk-keyed map away from parts that already hold target pks.
The `mapping` itself is always built from the **whole** `node_index`, since a pending part's links may
point anywhere in the course. Concretely: `new_pks` below is drawn from pending entries only, while
`by_order` and `mapping` cover all of them.

Equivalently stated for the common case, **its scope is the `Element` rows whose `unit_id` appears
among the state file's recorded new pks** —
not the whole target course, and not a baseline-derived guess. An earlier draft said "the top-level
nodes this migration created, identifiable from the baseline's `top_nodes` plus the committed part
orders"; that does not work, because `_capture_baseline` records `top_nodes` as an integer **count**
(`nodes.filter(parent__isnull=True).count()`, `migrate_course_content.py:256`) and the part orders are
*source*-side. Neither yields a target pk. The state file already holds the exact answer: every
`node_map` value is the new pk of a node that part created, at every depth. Nested elements come for
free, since a child `Element` keeps its own `unit` FK.

Scoping matters most under `--force`, which permits grafting into a course that already holds content:
those pre-existing bodies carry *target* pks, and sweeping them with an old-pk-keyed map would flatten
them or, on a numeric coincidence, mis-point them.

The map is the three-way join of the two files:

```python
# SCOPE: pending orders only. MAPPING: every order, since links may point anywhere.
pending = [e for e in state["parts"] if not e["rewritten"]]
recorded_pks = {pk for e in pending for pk in e["node_map"].values()}
# Drop anything a stale (rolled-back) entry recorded: those rows do not exist.
new_pks = set(
    ContentNode.objects.filter(pk__in=recorded_pks, course=target).values_list("pk", flat=True)
)
skipped_dead = len(recorded_pks) - len(new_pks)
by_order = {int(e["order"]): e["node_map"] for e in state["parts"]}
# Reverse map for per-part count attribution (§Counts). The "append replaces an
# existing order" rule makes a pk appearing under two orders unreachable.
order_by_new_pk = {pk: order for order, nm in by_order.items() for pk in nm.values()}

skipped_parts = skipped_ids = 0
mapping = {}                                     # {old_source_pk: new_target_pk}
for old_pk_str, (order, export_id) in node_index.items():   # NOT `manifest` -- see §Error handling
    part = by_order.get(int(order))
    if part is None:                             # part order not recorded at all
        skipped_parts += 1
        continue
    new_pk = part.get(export_id)
    if new_pk is None:                           # export id absent from that part's node_map
        skipped_ids += 1
        continue
    if new_pk not in new_pks:                    # recorded but no live row (stale entry)
        continue
    mapping[int(old_pk_str)] = new_pk
```

The `course=target` filter on the liveness query is not decoration: a bare `pk__in` would admit a pk
that belongs to some other course, which is exactly the mis-point this design guards against.

All three lookups **skip on miss and count the skip** rather than raising `KeyError` mid-loop — but
**a nonzero total is then a `CommandError`, raised before the transaction is entered and before
`status` is flipped to `in_progress`.** An earlier draft of this spec called them warning lines "because
the pass remains correct"; that reasoning is wrong, and the error is worth naming because it is
seductive. The pass calls `rewrite_instance(..., on_missing="unwrap")`, so a `node_index` entry that
contributes no mapping is **not inert** — every href pointing at that source pk is flattened to plain
text inside a committed transaction, irreversibly. §trigger describes exactly this outcome, for one
part's worth of dropped pks, as "the irreversible whole-course flatten this spec exists to prevent".
The same condition cannot be a catastrophe there and a warning here. The degenerate case makes it
plain: a state file whose recorded pks all belong to a different course yields `mapping == {}` and
destroys every internal link in the migrated scope while printing three tidy warning lines.

None of the three is reachable on a healthy migration, which is what makes fatal the right severity
rather than an inconvenience:

- `skipped_parts` — the trigger already required `recorded == on_disk`, and `node_index`'s orders are
  the source parts' orders, so every order it names is recorded.
- `skipped_ids` — both sides are the full `{n1 … nK}` set for the part (§Import phase's re-export
  guard explains why), so a miss means the manifest and the state file disagree about a part, which
  the `src` comparison should already have caught.
- `skipped_dead` — a recorded pk with no live row in the target course means a stale entry survived
  un-re-grafted, or the target is wrong.

So the counters are **diagnostics on a fatal path**: they are computed in full so the `CommandError`
can name the offending orders and ids rather than failing on the first one, and they are printed with
the error. Part 2's "handled rather than asserted" precedent for the export-id miss applies to *how*
it is detected, not to whether the run continues; part 2's post-pass is scoped to a single archive,
while this one is scoped to a whole course.

The rewrite itself, in full, because leaving any of it to inference is what this spec exists to
prevent:

```python
qs = (
    Element.objects.filter(unit_id__in=new_pks)
    .order_by("pk")
    .prefetch_related("content_object")
)
for join in qs.iterator(chunk_size=500):
    if join.content_object is None:              # dangling GFK: concrete row gone
        continue
    changed, flattened = rewrite_instance(join.content_object, mapping, on_missing="unwrap")
    if changed:
        join.content_object.save(update_fields=changed)
```

- `prefetch_related("content_object")` is not optional at this scale — without it the generic FK is
  one query per row, and the production target is 21 parts / 793 units / 20,054 elements.
  `export.py:525` uses the same prefetch on the same relation for the same reason.
- The `content_object is None` guard is mandatory: part 2 makes it mandatory on the analogous export
  scan (`export.py:545`), where `iter_rich_text(None)` would raise.
- `.iterator(chunk_size=...)` bounds memory; the chunk size is a tuning constant, not a contract.
- Writes are per-instance `save(update_fields=changed)` — the joins are heterogeneous GFK models, so
  there is no `bulk_update` over them. Expect up to one UPDATE per element that actually changed, not
  per element scanned.

**One transaction, deliberately.** The whole pass runs inside a single `transaction.atomic()`, and
this is a hard requirement, not a default: the crash-safe marking below has exactly one marker to
flip, and per-part batching would need per-part markers and reintroduce a partially-rewritten state
the trigger cannot reason about. A single large transaction is acceptable here because the per-part
grafts already commit thousands of rows each, and the cutover is a one-shot operation on a quiescent
target.

It calls `rewrite_instance(..., on_missing="unwrap")`. The bundle map covers the whole source course,
so anything still unresolved has no target anywhere in *this migration*.

**Accepted gaps**, mirroring part 2's own list, because "no target anywhere in the migration" is not
the same as "no target anywhere":

- **Cross-course links inside migrated bodies are flattened.** `node_index` covers the source course
  only, so a hand-typed link to a node in a *different* course on the source install is unresolvable
  here and `unwrap` destroys it. This is correct for the cutover — the other course is not moving —
  but it is a real content change, so it lands in the `flattened` count rather than passing silently.
- **Bodies part 2 fail-closes keep their source pks.** An unterminated quoted attribute value, an `<a`
  with no unquoted `>`, or (on the unwrap path) an open tag with no matching `</a>` makes part 2
  return the whole body byte-identical — so *every* internal href in that body survives unrewritten,
  not just the malformed one. Reachable here because `_build_fill_gate` / `_build_switch_gate`
  (`importer.py:549-561`) store `stem` unsanitised. The pass records these element pks and §Verify
  reports them separately rather than failing on them.
- **Absolute same-origin permalinks pass through untouched and unreported.** `find_link_targets` sees
  relative hrefs only (part 2 §Accepted gaps), so `https://host/courses/n/12/` is neither rewritten by
  the pass nor flagged by §Verify's reconciliation. It will still point at the *source* install's node
  after the cutover. Nothing in part 3 changes this; it is recorded so the zero-tolerance threshold in
  §Verify is not misread as "no broken links exist".

### Crash-safe marking, and the way out of `in_progress`

The rewrite runs inside a single `transaction.atomic()`, but the marker lives in a JSON file, so
"atomic + write the marker after" leaves a window: a crash between the DB commit and the file write
yields fully rewritten content with no marker, and the state-driven trigger would then re-apply an
old-pk-keyed map to hrefs that now hold *target* pks — the silent mis-point case this design exists to
prevent, and the one the test harness cannot reach. So: set `status` to **`in_progress`** *before*
entering the transaction, flip it to **`applied`** after commit, and treat a state file found
`in_progress` as a **`CommandError`** — always on `verify`, and on `import`'s resume path — never a
silent re-run. (The two exemptions, `--resolve-rewrite` and the `start_at is None` overwrite, are
pinned in §trigger's ordered branch.)

**That refusal must not be a dead end.** The marker is written before the transaction, so the
reachable states include "marker written, transaction never entered or rolled back" — nothing
rewritten — and on a 20k-element course the rewrite is the longest single step in the cutover, which
makes a Ctrl-C or an OOM there the most likely single failure in the whole operation. "The migration
is now permanently stuck" is not an acceptable defined behaviour for a production cutover.

The discriminator is the link probe of §Verify, and it is decisive: after a committed pass, **no**
element in the migrated scope holds an internal href whose pk is not a `ContentNode` of the target
course, because `unwrap` flattened everything unmapped. Before the pass, essentially every internal
href still holds a source pk and fails that test. So:

- The `CommandError` raised on `in_progress` **runs the probe read-only and prints its reading** — the
  count of in-scope elements holding a dangling internal href, and the total in-scope element count —
  then states the two remedies rather than guessing between them.
- `import` gains **`--resolve-rewrite {applied,not-applied}`**, accepted only when the state file is
  `in_progress` (otherwise `CommandError`).
- The decision is the operator's, not the command's. An automatic probe that guesses wrong produces
  exactly the silent mis-point the whole design is built to avoid, so the command reports and refuses;
  the human decides.

**`--resolve-rewrite` is a terminal action, handled before the baseline and double-run guards.** This
is what makes it reachable at all, and it is not a detail: an `in_progress` file only exists after a
complete or nearly-complete import, so the natural invocation
`import --bundle-dir X --target-slug t --as-user u --resolve-rewrite not-applied` takes the
`start_at is None` branch, where `existing` is already `baseline + N` and
`migrate_course_content.py:401` raises *"target 'dst' already has N top-level node(s); pass --force
…"* — the operator never reaches the state file. Following that error's own advice and adding
`--force` is worse: `todo = ordered` and the command re-grafts all N parts. So the flag is handled
**at the top of `_import`, after the bundle/manifest/archive gates and after the state file is
loaded, but before the baseline capture and the double-run guard**; it mutates only the state file,
prints what it changed, and returns. It requires no `--start-at` and no `--force`, and grafts nothing
— but it **does** require `--target-slug` and `--as-user`, because the pinned handling point sits
after the required-argument gates at `:369-383`, where `--as-user` is checked unconditionally.
Measured: `call_command('migrate_course_content', 'import', '--bundle-dir', 'x', '--target-slug', 't')`
→ `CommandError: import requires --as-user`. `--target-slug` is genuinely needed (it resolves the
`target` that the pass and its liveness filter are scoped to). `--as-user` is not — nothing is
stamped, since no media is re-materialised — but it is demanded anyway rather than hoisting the
handling above `:371`, because a per-action exemption carved into a shared required-argument block is
the kind of special case that rots. §Testing's invocation shows all three flags.

- `applied` flips `status` to `applied` and writes `"rewrite": {"resolved_by_operator": true}` — that
  literal shape, with **no count keys at all**, because the counts genuinely are not known. `verify`
  prints `"link rewrite: marked applied by the operator; counts unavailable"` when it sees that key
  and the per-part table when it does not. The §Testing once-only assertion compares the `rewrite`
  object for equality, so it works for both shapes.
- `not-applied` flips `status` back to `collecting` **and runs the final pass in the same
  invocation**, then returns. It grafts nothing.

  **The `collecting` flip is not persisted before the pass runs.** The file stays `in_progress` on
  disk until the pass itself writes it. Persisting `collecting` first would be symmetric with the
  `applied` arm but destroys the escape hatch: the pass's first two gates (the `src` drift check and
  the fatal `skipped_*` check) both raise *before* `status = "in_progress"; write`, so a file already
  flipped to `collecting` would leave `--resolve-rewrite` refused ever after — and the `--start-at`
  fallback provably has no working value under non-contiguous orders. Leaving it `in_progress` until
  success makes the action **re-runnable**, which is what a recovery command has to be.

  **This is one invocation, not two, because no two-invocation form exists.** An earlier draft told
  the operator to flip the marker and then re-run with a `--start-at`; there is no value of
  `--start-at` that works. `:432-433` requires `start_at == the number of committed parts`, while
  `todo` is filtered as `order >= start_at` against *archive orders* (`:440`). With all parts
  committed under non-contiguous orders `{0, 5, 9}`: `--start-at 3` clears `:433` but leaves
  `todo == [(5,…), (9,…)]` and **re-grafts parts 5 and 9**; `--start-at 10` empties `todo` but is
  refused by `:433` (*expected 10, holds 3*). Brute-forced over `range(0, 50)`: **no** value both
  clears the invariant and empties `todo`. Under contiguous orders the two constraints happen to
  coincide, which is exactly why the dead end would have survived to production.

  Running the pass inside the resolve action sidesteps the whole problem. The action already knows the
  bundle is complete (it validated the state file to get here), it grafts nothing, so neither `:401`
  nor `:433` is relevant, and re-running the rewrite *is* the operator's stated intent when they
  answer "not applied". The trigger's site predicates are untouched: this is a third, explicit entry
  point to the pass, not a fourth implicit one.

**`--resolve-rewrite` combined with `--start-at`, `--force` or `--dry-run` is a `CommandError`.**
"Requires no `--start-at`" does not say what happens when one is supplied, and because the action is
terminal those flags would otherwise be silently ignored — against the module's stated principle at
`:63-75` that a flag used outside its action is rejected rather than ignored. `_ACTION_FLAGS` cannot
enforce it (all four belong to `import`), so it is an explicit check. `--dry-run` is the worst of the
three: it reads as "show me what you would change" while the action mutates the state file.

`--resolve-rewrite` joins **`_ACTION_FLAGS["import"]` and `_FLAG_UNSET`** (unset value `None`). The
module's design comment at `migrate_course_content.py:63-75` makes this mandatory — *"Anything used
outside its action is rejected rather than silently ignored"* — and both halves are needed: omitting
it from `_ACTION_FLAGS` lets `export --resolve-rewrite applied` be silently accepted and ignored,
while adding it there but not to `_FLAG_UNSET` makes `_reject_foreign_flags` do
`_FLAG_UNSET["resolve_rewrite"]` on every `export` and `verify` invocation, raising a raw `KeyError`
traceback instead of a `CommandError`.

### Counts

The pass **prints per-part and total counts** to stdout and records them in the state file under a
`rewrite` object added at the `applied` flip; the per-part grouping is what the part-order keying
provides. Each in-scope element is attributed via `order_by_new_pk[join.unit_id]` — the reverse map
built beside `by_order` in §mechanics, so attribution is a dict lookup rather than a linear search
over up to 21 `node_map` dicts for each of 20,054 elements.

```json
"rewrite": {
  "parts": [{"order": 0, "elements_touched": 12, "flattened": 1},
            {"order": 1, "elements_touched": 0, "flattened": 0}],
  "elements_touched": 12,
  "flattened": 1,
  "fail_closed_elements": []
}
```

**There is no "rewritten href" count, and this is a deliberate consequence of §Scope.** Part 2 pins
`rewrite_links(html, mapping, *, on_missing) -> tuple[str, int]` and
`rewrite_instance(instance, mapping, *, on_missing) -> tuple[list[str], int]`; the int in both is the
*flattened* count, and neither returns a count of successfully rewritten hrefs. `len(changed)` is not
a substitute — `changed` is a list of **field names**, and a field lands in it when an unwrap-only
edit occurred (0 rewrites, 1 flatten). Obtaining a true rewritten count would mean widening part 2's
return types, which this spec explicitly does not do. `elements_touched` — the number of in-scope
elements for which `changed` was non-empty — is the operator-facing signal instead, and `flattened` is
exact.

`parts` carries **one row per recorded order, including all-zero rows, in ascending order**. The
once-only case asserts whole-object equality on `rewrite`, and `verify` prints the rows as a table, so
omitting empty parts would both change the fixture and silently drop parts from the report.
`fail_closed_elements` is the list of element pks §Verify subtracts from its dangling count.

The three skip counters are **not** persisted here. §mechanics makes any nonzero value fatal before
the `rewrite` object is ever written, so a persisted `skipped_*: 0` could only ever be zero — recording
it would invite a reader to think a nonzero value is representable. They live in the `CommandError`
message instead.

`verify` prints these from the state file; it cannot recompute them, since it reads only the manifest,
baseline and archives, none of which carry the counts.

### Verify — the link reconciliation

Counts cannot be recomputed at `verify` time, but the *outcome* can be checked directly, and the
design's headline risk is exactly a mis-pointed or unrewritten link. `verify` therefore scans the same
scope the pass used — `Element` rows whose `unit_id` is among the state file's recorded new pks — and
counts elements holding an internal href whose pk is not a `ContentNode` of the **target** course.

**`new_pks` is rebuilt, not inherited.** It is defined in §mechanics as the output of the liveness
query run during `import`; `verify` is a different process and must recompute it from the state file
through the *same* `ContentNode.objects.filter(pk__in=recorded_pks, course=target)` query. The prose
"the state file's recorded new pks" and the code `new_pks` name two different sets whenever a stale
entry exists — the recorded set and its live subset — so **one named helper builds `recorded_pks` →
`new_pks` and is shared by `_import`, `_verify` and the `in_progress` probe.** The probe's "total
in-scope element count", which the operator uses as the denominator when choosing `applied` vs
`not-applied`, is counted over that same live set. (In `verify` a stale entry does not raise, unlike
in the pass — `verify` reports rather than mutates.)

**It is built from part 2's exports; no new helper is required, and no captured href is available.**
Part 2's public surface is `find_link_targets(html) -> set[int]`, `rewrite_links`,
`iter_rich_text(instance) -> Iterator[tuple[str, str]]`, `rewrite_instance` and `count_inbound_links`.
None returns an href — `find_link_targets` returns bare target pks — so the scan composes the two
read-only ones, and the "href" in a reported example is **reconstructed** as `/courses/n/<pk>/` from
the dangling pk, not a captured attribute value. Same query shape as the pass, for the same reason
(20,054 elements, one GFK dereference each):

```python
qs = (
    Element.objects.filter(unit_id__in=new_pks)
    .order_by("pk")
    .prefetch_related("content_object")
)
referenced = {}                                  # {target_pk: [(unit_id, element_pk), ...]}
for join in qs.iterator(chunk_size=500):
    if join.content_object is None:
        continue
    for _field, value in iter_rich_text(join.content_object):
        for pk in find_link_targets(value):
            referenced.setdefault(pk, []).append((join.unit_id, join.pk))

live = set(
    ContentNode.objects.filter(course=target, pk__in=referenced).values_list("pk", flat=True)
)
dangling = {pk: sites for pk, sites in referenced.items() if pk not in live}

# The two numbers that are actually reported. `dangling` is keyed by TARGET pk, so
# len(dangling) counts dangling targets, not elements -- one element with three bad
# hrefs contributes three keys, one bad pk cited from twenty elements contributes one.
dangling_elements = {epk for sites in dangling.values() for _uid, epk in sites}
total_elements = qs.count()
```

One resolution query for the whole scan, not one per element. `course=target` is required for the
same reason it is required in the pass: a bare `pk__in` would call a node in some *other* course
"resolved".

**Which number is which.** §Verify's threshold is on `len(dangling_elements)` — the count of migrated
elements holding at least one dangling href. The `in_progress` probe reports that same number **and**
`total_elements` as its denominator; the operator divides them to decide `applied` (near zero) versus
`not-applied` (near total). Since that ratio drives an irreversible decision, neither number may be
left to inference.

After a correct pass that count is **almost always zero** — every mapped href points at a target node
and everything unmapped was unwrapped to plain text — but **not unconditionally zero**, and an earlier
draft of this spec claimed it was. Part 2's converged fail-closed rule
(`2026-07-26-internal-link-durability-design.md:200-206`, restated at `:524-525` and `:550-552`)
returns the whole *body* byte-identical, contributing 0 to the count, when the scanner meets any of
three conditions — including, on the unwrap path, an open `<a` tag with no matching `</a>`. That path
never unwraps, so `find_link_targets` still reports the pk. Such a body therefore keeps its **source**
pk *and* leaves every other, mappable internal href in the same body unrewritten. Part 2 names this
reachable through exactly the import path this cutover uses, and it checks out: `_build_fill_gate` and
`_build_switch_gate` (`courses/transfer/importer.py:549-561`) create `stem` raw, with no
`sanitize_html` — part 2's own drift-guard census records `importer.py` as having a single sanitise
call site, `_build_guess_number`.

So the threshold is graded rather than absolute:

- Elements whose bodies the pass observed to be fail-closed are **recorded by element pk** in the
  `rewrite` object, and `verify` subtracts them. This is the only way to distinguish "part 2 declined
  to touch this body" from "the pass never ran".
- Any *other* dangling element → `CommandError`, reporting the count and up to ten example
  `(unit_id, element pk, href)` triples. It catches a skipped pass (every href still holds a source
  pk) and a double-apply against nonexistent pks.
- Fail-closed elements → a **reported, non-fatal count** with the same example triples. Fatal would be
  wrong: `status` is already `applied`, `--resolve-rewrite` needs `in_progress`, so `verify` would
  fail forever with no remedy. The operator repairs the body by hand and re-runs.
- Zero of both → a printed confirmation line alongside the recorded counts.

The same correction applies to the `in_progress` probe: fail-closed elements inflate its numerator and
would push the operator toward `not-applied` and the double-apply the design calls undetectable, so
the probe reports them as a separate third number rather than folding them into the dangling count.

It does **not** catch the pk-collision double-apply, where a re-applied map lands on a pk that happens
to exist in the target. Nothing can, from the target side alone; that case is prevented by the
once-only invariant below, not detected here.

`verify` also raises `CommandError` when the state file is `in_progress` (see above), when a committed
bundle's state file lacks the `applied` marker (the skipped-pass case), and when the state file is
**missing** entirely — telling the operator to run `import` first, mirroring what `verify` already does
for a missing `BASELINE_NAME` (`migrate_course_content.py:524-534`).

**Where these sit among `_verify`'s existing gates is pinned**, because two existing tests assert on
message text and are order-sensitive: `test_verify_refuses_when_import_was_never_run` (`:847`,
`match="is missing from"`) and `test_verify_fails_when_a_part_is_missing` (`:806`,
`match="node count mismatch"`). The order is: the existing `MANIFEST_NAME` gate (`:522`), the existing
`BASELINE_NAME` gate (`:525-535`), **then** the state file's presence / JSON / `version` / marker
checks, then the existing archive re-read and the four tally checks, and **the link reconciliation
last**. A content-level link failure should never pre-empt a structural one — a missing part is the
more actionable report.

### The once-only invariant

**The map is applied exactly once, to hrefs that still hold source pks** — which `defer` guarantees.
This invariant has to be argued rather than tested, and the reason is worth recording: source and
target live in *different databases*, so a new target pk can equal an old source pk. Any design that
re-applies the map over already-rewritten content can therefore silently re-point a correct link at an
unrelated node. `tests/test_migrate_course_content.py` creates both courses in one test database,
where new pks always exceed source pks, so the collision is not reachable from the harness.

What *is* testable, and must be tested, is the guard itself: a completed migration re-invoked must
find `status == "applied"` and not run the pass again. See §Testing.

This is the one place the design pays for the two-phase architecture, and it is not optional: without
it the spec's headline claim about the cutover is false.

## Data flow

```
EXPORT (per part, accumulated)
  report = {}
  manifest, document, media, problems = build_export(course, node=part, report=report)
  node_index.update({str(pk): [part.order, nid] for pk, nid in report["node_ids"].items()})
  ...after ALL parts:
  bundle-manifest.json["node_index"] = node_index        # {"1234": [0, "n7"], ...}

IMPORT (per part; inside `with open_archive(...)`, after the --dry-run `continue`)
  with transaction.atomic():                              # OUTER: commits after the write below
      report = {}
      import_subtree(..., on_missing="defer", report=report)   # rewrites nothing
      src = _invert_node_index(node_index, order)  # {"n7": 1234} -- THE shared helper
      # Never inline this comprehension: node_index keys are decimal STRINGS, and the
      # `src` guard is a fatal equality test. One spelling at both sites, or the
      # feature is permanently blocked by a spurious re-export error.
      state["parts"] = [e for e in state["parts"] if int(e["order"]) != order]
      state["parts"].append({"order": order, "node_map": report["node_map"],
                             "src": src, "rewritten": False})
      state["status"] = "collecting"   # a RE-graft after "applied" must re-arm the pass
      write LINK_STATE_NAME            # via <name>.tmp + os.replace, never truncate-in-place
  # wrapped in its own `except OSError` -> log + CommandError with the resume hint

TRIGGER -- TWO SITES, TWO PREDICATES (see §trigger; conflating them is fatal either way)
  recorded = {int(e["order"]) for e in state["parts"]}
  on_disk  = {order for order, _ in ordered}
  site 1, immediately before the `not todo` early return at :445 (resume branch only):
      if not todo and recorded == on_disk and state["status"] == "collecting":  run the pass
      # `not todo` here is NOT redundant: without it the pass fires before the
      # last part is grafted and flattens the whole course.
  site 2, after the graft loop (both branches):
      if recorded == on_disk and state["status"] == "collecting":  run the pass
      # NO `not todo` here: the loop never empties `todo`, so carrying the
      # conjunct over makes the pass unreachable on the primary invocation.

FINAL PASS (once)
  check every entry's "src" against node_index      -> CommandError on re-export drift
  mapping = {int(old): by_order[int(order)][export_id] ...}
  if skipped_parts or skipped_ids or skipped_dead:  -> CommandError, BEFORE the transaction
  state["status"] = "in_progress"; write            # BEFORE the transaction
  with transaction.atomic():
      for join in qs.iterator(chunk_size=500):      # qs per §mechanics -- prefetch_related,
          if join.content_object is None: continue  #   order_by("pk"); abbreviated here
          changed, flattened = rewrite_instance(join.content_object, mapping, on_missing="unwrap")
          if changed: join.content_object.save(update_fields=changed)
  mark every pending order "rewritten": true
  state["status"] = "applied" if no order is still pending else "collecting"
  state["rewrite"] = {...}; write                   # AFTER the commit

RESOLVE (terminal, top of _import, before the baseline/double-run guards; grafts nothing)
  --resolve-rewrite applied      -> status="applied", rewrite={"resolved_by_operator": true}; return
  --resolve-rewrite not-applied  -> status="collecting"; RUN THE PASS in this same invocation; return
  # ONE invocation, not two: no --start-at value both clears :433 and empties todo (see §Crash-safe)

VERIFY
  refuse on missing / in_progress / not-"applied" state file
  print state["rewrite"]
  scan the same scope for dangling internal hrefs -> nonzero is a CommandError
```

## Testing

Falsified before trusted — delete the behaviour, require RED.

**The cutover path** — the case the naive `unwrap` default silently breaks, so it gets end-to-end
coverage rather than a note:

- A two-part fixture course where a lesson in part A links to a unit in part B **and** another lesson
  in part A links within part A. Run `export` → `import` over both parts and assert **both** resolve
  to their **new** pks. The intra-part link is not padding: it is the assertion that catches the
  rewrite-per-part-then-finish design, under which the final old-pk-keyed pass would flatten every
  within-part link in the course. A cross-part-only fixture passes that broken design. This bullet is
  also the falsification for site 2's predicate: add `not todo` to it and this test goes RED, because
  the loop never empties `todo` and the pass would never fire on the plain `export` → `import` path.
- The same, with the import **interrupted after part A and resumed with `--start-at`**: the
  accumulated old→new state must survive across process invocations, so the final pass still
  resolves the cross-part link. This is what pins the state to a file rather than memory.
- A link whose target is in no part at all → flattened, counted, and the count printed to stdout.
- **The skipped-pass window:** a run interrupted *after* the last part commits but before the rewrite
  pass, then resumed with `--start-at part_count`, still applies the pass — and `verify` raises
  `CommandError` on a committed bundle whose state file lacks the applied marker.
- **The once-only guard:** a completed migration re-invoked with `--start-at part_count` finds
  `status == "applied"`, does **not** re-run the pass (assert the recorded `rewrite` counts are
  unchanged and no body was re-edited), and still prints the existing "nothing to do … already
  complete" line that `test_start_at_beyond_all_parts_reports_nothing_to_do`
  (`tests/test_migrate_course_content.py:572`) asserts.
- **The repair resume — a part re-grafted after the pass already applied.** Run a full `export` →
  `import` (pass applies, `status == "applied"`), delete one part's top-level node from the target,
  then `import --start-at K`. The re-grafted part's links must resolve to their new pks, and the
  already-rewritten parts' bodies must be **byte-identical to before** — the second half is what
  catches a fix that simply re-runs the whole pass and re-applies an old-pk map over rewritten hrefs.
  Falsify by making `rewritten` a single top-level flag: the re-grafted part's hrefs then keep source
  pks and the test goes RED. Note this sequence is exactly `test_start_at_grafts_only_the_remainder`
  (`tests/test_migrate_course_content.py:432`), which is green today and must stay green.
- `--force` grafting into a target that already holds linked content: the pre-existing bodies are
  **untouched**, since the pass is scoped to the nodes the state file records as created by this
  migration.
- **A fail-closed body** — an element whose `stem` holds an unmatched `<a>` and a second, well-formed
  internal link — survives the pass byte-identical, is recorded in `rewrite["fail_closed_elements"]`,
  and makes `verify` report it **without** raising. Falsify by dropping the subtraction: `verify`
  then raises with no remedy available.

**The export side**, which nothing above touches:

- After a plain `export`, `bundle-manifest.json["node_index"]` exists, has the `{str(pk): [order,
  "nN"]}` shape, and covers **every** node in the source course — not just link targets, and not just
  the last part's.
- After an `--allow-problems` export, it is still non-empty. `report["node_ids"]` must survive the
  tolerant path. Note that `test_export_aborts_on_problems_and_allow_problems_overrides` monkeypatches
  `build_export` with `def fake(course, node=None, **kw)` (`tests/test_migrate_course_content.py:175`)
  whose `**kw` forwards the new `report` kwarg by accident, not by design — this case is what pins it.

**One case per §Error handling condition.** The list below is complete against §Error handling as
written; if a condition is added there, a case is added here:

- A bundle whose `bundle-manifest.json` has no `node_index` → `CommandError` at the top of `import`,
  before anything is grafted.
- A state file marked `in_progress` → `CommandError` from `verify`, and from `import` **on the resume
  path** (name the branch: pass `--start-at`; a plain `start_at is None` re-run overwrites the file
  instead, per step 3, and must be asserted separately). The probe reading appears in the message.
  Recovery is **one `call_command` invocation**: `--resolve-rewrite not-applied` **with
  `--target-slug` and `--as-user`** (both required by `:369-383`) but no `--start-at` and no
  `--force` — it must not trip the `:401` double-run guard, and after it returns the pass has run and
  the links resolve. Assert there is no second invocation, since the two-step form is unreachable
  (§Crash-safe). Assert too that omitting `--as-user` raises, so the documented invocation is pinned
  against the real required-argument gate rather than the spec's prose. Separately, `--resolve-rewrite applied` on a `collecting` file is itself a
  `CommandError`, and `export --resolve-rewrite applied` is rejected by the flag matrix — extend the
  existing `test_export_refuses_import_only_flags` (`tests/test_migrate_course_content.py:284`), which
  exercises `_reject_foreign_flags` at `migrate_course_content.py:180-190`, rather than writing a new
  one.
- **The stale-entry ordering (site 1's `not todo` conjunct):** a state file whose last part is
  recorded but whose nodes are absent from the target, resumed with `--start-at N-1`, must **graft
  first and rewrite after** — the part is grafted, its entry replaced, and both links resolve.
  Falsify it by deleting `not todo` from site 1: the run must then raise the `skipped_dead`
  `CommandError` and leave part `N-1` ungrafted. Assert the `CommandError` and the absent part — do
  **not** assert flattened links, which the fatal-skip rule makes unreachable.
- **The re-export consistency guard:** repair-and-resume with an *unchanged* source succeeds (this is
  `test_start_at_recovers_after_force_and_a_mid_run_failure`, `tests/test_migrate_course_content.py:513`,
  which is green today and **must stay green** — it does `export … --clean` into the same bundle
  between the failure and the resume, so it directly exercises the decision not to unlink the state
  file). Re-exporting after adding a node to the source, then resuming, raises `CommandError`.
- `verify` with no state file at all → `CommandError` naming `import`; and `--resolve-rewrite` with no
  state file at all → `CommandError`.
- A state file that is not valid JSON, and one whose `version` is `2` → `CommandError` in both cases.
- A **missing** state file with `--start-at K > 0` → `CommandError` naming the pre-feature-import
  cause. This is a different branch from the next case, which has a state file that is merely short.
- `--start-at K` where part `K-1` is absent from the state file → `CommandError`; and, to falsify the
  string-key hazard, a fixture resumed at `--start-at 10` with orders 0–9 recorded, which a
  lexicographic-`max` implementation rejects and the specified set predicate accepts. Cost note: to
  clear the `:433` invariant this needs the target to actually hold `baseline + 10` top-level nodes
  and the state file to record orders 0–9, so it either runs a real ten-part import (the most
  expensive case in this list) or hand-writes the state file and seeds the nodes directly — the
  latter is acceptable here, since the guard under test reads the file rather than the graft.
- `--target-slug` pointing at a different course than the state file's `target_pk` → `CommandError`;
  and the same course after a rename (pk matches, slug does not) → **no** error, just the note.
- A bundle re-exported with one grafted part deleted, so `recorded ⊃ on_disk` → `CommandError` naming
  the orders no longer on disk. Falsify it by removing the superset check: the run then exits 0 with
  "this migration is already complete" and no rewrite, which is the silent failure the check exists
  for.
- A state file whose recorded pks are live but whose `src` map disagrees with the manifest → the
  re-export drift `CommandError`; and a **sibling reorder** in the source between export and resume
  must trip it, since that is the count-preserving edit an export-id set comparison cannot see.
  **The mutation must be inside a part whose order is already recorded in the state file** — export
  ids are per-archive positional (`enumerate(nodes, start=1)` over `_ordered_nodes(course, root=part)`,
  `export.py:506`), so editing an *ungrafted* part leaves every recorded part's `src` byte-identical
  and the guard correctly does not fire, making the test vacuous. For the same reason the reorder must
  be of siblings *within* a recorded part, not of the top-level parts themselves — reordering those
  changes archive names, not intra-part export ids.
- A state file with one recorded pk deleted from the target → the `skipped_dead` `CommandError`,
  raised with `status` still `collecting` and no element modified. Assert both, or the "before the
  transaction" ordering is untested.
- `--resolve-rewrite` with `--start-at`, with `--force`, and with `--dry-run` → `CommandError` in each
  case; `--dry-run` additionally must leave the state file byte-identical.
- `--dry-run` leaves an existing state file byte-identical, in **both** write paths, and the flag each
  case needs must be named — a bare `import --dry-run` over a bundle whose parts are already committed
  hits `:401` first (which fires regardless of `dry_run`, since `:408`'s gate is downstream) and would
  pass vacuously on the wrong error. So: `--dry-run --force` falsifies step 3's gate, and
  `--dry-run --start-at K` falsifies step 4's path.
- The state file is written via a temp file plus `os.replace`, not truncate-in-place: falsify by
  pointing the write at the real name and killing it mid-write, which must not be able to leave
  truncated JSON that the next invocation rejects.
- `--resolve-rewrite not-applied` whose pass then fails the `src` guard leaves the file **still
  `in_progress`**, so the same command can be run again after the operator repairs the bundle.
  Falsify by persisting `collecting` before the pass: the second invocation is then refused and the
  migration is stuck.

**Verify's link reconciliation:** a target whose migrated scope is hand-mutated to hold an internal
href pointing at a pk that is not a `ContentNode` of the target course → `verify` raises
`CommandError` and names the offending element.

## Error handling

- **A bundle exported before this change**, whose `bundle-manifest.json` has no `node_index` key →
  **`CommandError` at the top of `import`**, before any part is grafted: *this bundle predates
  internal-link support; re-export it*. The earlier `manifest.get("node_index", {})` fall-through was
  worse than it read — an empty map plus `on_missing="unwrap"` does not mean "no part rewrites", it
  means **every internal link in the migrated course is destroyed**, inside a committed transaction,
  with the operator learning the number afterwards. The condition is trivially detectable up front, so
  it is detected up front. `_read_bundle_manifest` content-validates only `part_count`
  (`migrate_course_content.py:235-241`), so such a bundle passes the existing gate and this check must
  be added explicitly rather than assumed. Mechanically, `_import` currently **discards** that
  function's return value (`self._read_bundle_manifest(bundle, archives)` at `:387`, unlike `_verify`
  at `:522` which assigns it); `:387` must capture it, since both this check and the final pass's
  `node_index` join need the value.

  **It must be captured under a distinct name — `bundle_manifest`, not `manifest`.** The graft loop
  binds `manifest` at `:457-462` (`with open_archive(fh, expected_kind=KIND_SUBTREE) as (zf, manifest,
  document, media_entries):`), and a `with … as` target binds in the *enclosing function scope* and
  survives the block. After the loop `manifest` is the **last archive's** manifest, so trigger site 2 —
  which runs after the loop — would read the wrong dict. Measured, simulating exactly that: after the
  loop `manifest` is `{'format_version': 6, 'kind': 'subtree'}` and the join raises
  `KeyError: 'node_index'`. So `:387` becomes `bundle_manifest = self._read_bundle_manifest(...)`
  (matching `_verify`'s own name at `:522`), and `node_index = bundle_manifest["node_index"]` is
  hoisted before the loop. Every reference in §mechanics and §Data flow is to `node_index`, never to
  `manifest`.

- **This supersedes a converged bullet in part 2.** Part 2's §Error handling
  (`2026-07-26-internal-link-durability-design.md:520-523`) says: *"A bundle exported before this
  change, whose `bundle-manifest.json` has no `link_nodes` key → read with
  `manifest.get("link_nodes", {})`, so no part rewrites and the operator gets the flattened count
  rather than a raw `KeyError`."* Part 3 changes that bullet twice over — it renames the bundle-level
  key from `link_nodes` to `node_index` (§Export phase, to stop it colliding with part 2's
  *document*-level `link_nodes`), and it inverts the policy from tolerant to fatal for the reason
  above. The bundle manifest is part 3's artifact, not part 2's, so the rule belongs here; whoever
  implements part 2 from part 2's own text must **not** ship the tolerant fall-through under the old
  key. Part 2's *document*-level `link_nodes` absence rule (a v5 archive → `setdefault` supplies `{}`)
  is untouched and still correct.
- **A state file found `in_progress`** → never a silent re-run, but the refusal is **path-scoped**, not
  unconditional: on `import` it refuses **on the resume path only** (step 4 of §trigger's ordered
  branch), it is preceded by `--resolve-rewrite` (step 2), and on `start_at is None` the file is
  overwritten behind the `:401` guard (step 3) rather than refused. On `verify` it **always** refuses.
  The `import` message carries the probe reading and names `--resolve-rewrite`. See §Crash-safe
  marking. §Testing's case must name which branch it exercises, or it can be written to pass under
  either reading.
- **A missing state file at `verify` time** → `CommandError` telling the operator to run `import`
  first, mirroring what `verify` already does for a missing `BASELINE_NAME`.
- **A missing state file at `import` time with `--start-at K > 0`** → `CommandError`: this migration
  began before internal-link support and its `export_id → new_pk` map cannot be reconstructed; re-run
  `import` from the start against a clean target. With `--start-at 0` or no `--start-at`, a fresh file
  is written instead.
- **A state file that is not valid JSON, or whose `version` is not `1`** → `CommandError`, in the
  style of the existing `BASELINE_NAME` JSON guard (`migrate_course_content.py:420-425`).
- **`--start-at K` where some archive order below `K` is absent from the state file** → `CommandError`:
  the map is incomplete, and proceeding would flatten every link into the missing part. Evaluated as a
  subset test against the archive orders on disk, never as `max(recorded) + 1` — `recorded` can be
  empty, and its string keys would sort lexicographically.
- **`--resolve-rewrite` on a state file that is not `in_progress`, or with no state file at all** →
  `CommandError`; the flag exists only to break the `in_progress` deadlock. It is handled before the
  baseline capture and double-run guard, so it never trips `:401`, and it is rejected on `export` and
  `verify` by `_ACTION_FLAGS` / `_FLAG_UNSET`.
- **A `node_index` entry whose part order is not recorded in the state file, whose export id is absent
  from that part's `node_map`, or whose recorded new pk has no live `ContentNode` row in the target
  course** → counted (`skipped_parts` / `skipped_ids` / `skipped_dead`) rather than raising `KeyError`
  mid-loop, then a **`CommandError` naming every offending order and id — raised before the
  transaction is entered and before `status` is flipped to `in_progress`.** None is reachable on a
  healthy migration, and each one means hrefs would be `unwrap`-flattened irreversibly. See
  §mechanics.
- **A state file whose `target_pk` does not match the resolved target course** → `CommandError`. The
  recorded pks belong to one target course; nothing else in the file says which. A `target_slug`
  mismatch with a matching `target_pk` is a renamed course — a printed note, not an error.
- **A recorded part whose `src` map does not match the manifest's `node_index` inversion for that
  order** → `CommandError`: the bundle was re-exported from a changed source after that part was
  grafted. Comparing export-id *sets* here would not detect it — both sides are always `{n1 … nK}`.
- **`--resolve-rewrite` combined with `--start-at`, `--force` or `--dry-run`** → `CommandError`, since
  the action is terminal and would otherwise ignore them silently.
- **An `OSError` from the state-file write** → logged with the part order and the orphaned-media note,
  then re-raised as a `CommandError` carrying the `:497-500` resume hint. Without an explicit handler
  it escapes `:490`'s `except TransferError` as a raw traceback.
- **`verify` finding a dangling internal href in the migrated scope** → `CommandError` with the count
  and up to ten examples.
