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

**Part 3 changes no interface part 2 defines.** Part 2 is converged and being implemented in a
parallel branch; every helper signature it pins (`rewrite_links`, `rewrite_instance`,
`document["link_nodes"]`, the `on_missing` values it owns) is consumed here exactly as written. Where
this spec needed a number part 2's return types do not carry, it derives that number here rather than
widening part 2 — see §Counts.

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
| `courses/management/commands/migrate_course_content.py` | bundle-level `node_index` at export; `defer` per part + a `LINK_STATE_NAME` state file; one final rewrite pass; `--resolve-rewrite`; stdout counts; `verify` reporting and its link reconciliation |
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
(`importer.py:1004` hands back only the grafted root, and `node_map` stays local to `work()`) — so
**`report` also receives `node_map`** as `{export_id: new_pk}` alongside `flattened_links`. Part 2's
own `node_map` is `{export_id: ContentNode}`; the importer emits the pk-valued projection of it into
`report`, so the state file stays JSON-serialisable.

Its schema, in full:

```json
{
  "version": 1,
  "status": "collecting",
  "parts": [
    {"order": 0, "node_map": {"n1": 4711, "n2": 4712}},
    {"order": 1, "node_map": {"n1": 4790}}
  ]
}
```

- `parts` is a **list of objects, not an object keyed by order**. This is not stylistic: JSON coerces
  integer object keys to strings, and `max()` over string keys is lexicographic. `json.loads(
  json.dumps({0: …, 9: …, 10: …}))` yields keys `"0" "9" "10"`, whose `max()` is `"9"` — with mat-pp's
  21 parts the resume guard below would be wrong from part 10 onward, rejecting a legitimate
  `--start-at 10` or accepting an incomplete map. A list of objects has no string keys to coerce.
  Defensively, every `order` read back is still passed through `int()` before any comparison.
- `node_map` keys are export ids (already strings); values are integer target pks.
- `status` is one of `collecting` (parts accumulating, rewrite not started), `in_progress` (the
  rewrite transaction has been entered), `applied` (the rewrite committed). A `rewrite` object is
  added when the pass completes — see §Counts.

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

The inverted failure is recoverable where the original is not:

- A stale entry cannot silently reach the final pass. The existing top-node invariant refuses the
  resume (`existing != baseline["top_nodes"] + start_at`, `migrate_course_content.py:433`) because
  part K's nodes are not in the target, and the failure path's own guidance — *resume with
  `--start-at <last committed + 1>`* (`:497-500`) — is the recovery. The operator re-grafts part K and
  its entry is overwritten.
- Belt and braces, the pass **drops any recorded new pk with no live `ContentNode` row** and counts the
  drop, so a stale entry can never contribute a mapping to a node that does not exist. Appending an
  entry for an order already present **replaces** it rather than duplicating.

Two things the implementation must confirm rather than assume, because the outer block changes when
work commits: that nothing in the importer relies on committing once per part, and that any
`transaction.on_commit` callback it registers (media finalisation in particular) still behaves when it
fires at the outer commit instead. If either fails, the fallback is to keep the write after the call
and document the "delete part K's nodes, resume at K" procedure in the `CommandError` — but the
wrapped form is the specified design.

Keying entries by part order is what lets the final pass attribute its counts per part, and what lets
a resume detect a short file. The resume guard, stated against the archive orders on disk rather than
against a count, because top-level `order` values are not guaranteed contiguous
(`migrate_course_content.py:326-336` records that `ContentNode.order` is not database-unique, and the
existing `--start-at` invariant already inherits this assumption):

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

`export --clean` gains a **third** unlink for the state file, and the non-empty-bundle refusal at
`migrate_course_content.py:278` gains the state file to its predicate — today it tests
`stale_zips or stale_manifest.exists()` only, so a directory holding just a leftover state file is
neither refused nor cleaned. This is a **divergence from `BASELINE_NAME`, not a mirror of it**:
measured, `rg -n "unlink" courses/management/commands/migrate_course_content.py` returns exactly two
hits (`:289` over `stale_zips`, `:291` for `stale_manifest`), and `BASELINE_NAME` is never unlinked
anywhere in the file. Whether `BASELINE_NAME` should join the new unlink is a separate question and is
deliberately **not** changed here.

### The final pass — trigger

**The final pass is triggered by bundle state, not by the loop.** The loop-completion reading has a
hole precisely where the state file exists to help: a process that dies after the last part commits
resumes with `--start-at part_count`, hits the "this migration is already complete" early return
(`migrate_course_content.py:445-451`), and never rewrites anything.

The trigger predicate is an explicit set comparison, safe against a gap left by the residual window
above:

```
recorded == on_disk  and  state["status"] != "applied"
```

where both sets are as defined in §Import phase. Not `len(recorded) == manifest["part_count"]` and not
`max(recorded) + 1 == len(archives)`; only set equality rejects a bundle whose parts 0..N-1 are
recorded but part K is not.

**Placement is part of the requirement.** The trigger is evaluated after `todo` is computed and
**before** the `if not todo: … return` early return, and again after the graft loop finishes. An
implementer following the loop-shaped reading of the rest of this section would place it after the
loop only and reproduce the exact hole this paragraph exists to close. The existing message
`"nothing to do: --start-at K is at or beyond the bundle's N part(s); this migration is already
complete"` is printed **only when the pass did not fire there** — `tests/test_migrate_course_content.py:572`
(`test_start_at_beyond_all_parts_reports_nothing_to_do`) asserts that string and must keep passing for
an already-`applied` migration. When the pass *does* fire on that path, the command instead prints
`"no parts left to graft; applying the deferred link rewrite"` followed by the counts.

Skipped entirely under `--dry-run`.

### The final pass — scope and mechanics

**Its scope is the `Element` rows whose `unit_id` appears among the state file's recorded new pks** —
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
recorded_pks = {pk for e in state["parts"] for pk in e["node_map"].values()}
# Drop anything a stale (rolled-back) entry recorded: those rows do not exist.
new_pks = set(
    ContentNode.objects.filter(pk__in=recorded_pks, course=target).values_list("pk", flat=True)
)
skipped_dead = len(recorded_pks) - len(new_pks)
by_order = {int(e["order"]): e["node_map"] for e in state["parts"]}

mapping = {}                                     # {old_source_pk: new_target_pk}
for old_pk_str, (order, export_id) in manifest["node_index"].items():
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

All three lookups **skip on miss and count the skip**; none raises. Part 2 sets the precedent for the
export-id one ("a `link_nodes` value that is not an export id present in `node_map` → that entry is
unresolvable, same as absent; should not occur, handled rather than asserted"). `skipped_parts`,
`skipped_ids` and `skipped_dead` are printed and recorded; each is a **warning line**, not an error,
because the pass remains correct — those entries simply contribute no targets. A nonzero
`skipped_dead` in particular means a stale entry survived, which the top-node invariant should already
have refused; the warning is the audit trail for that.

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
so anything still unresolved genuinely has no target anywhere in the migration.

### Crash-safe marking, and the way out of `in_progress`

The rewrite runs inside a single `transaction.atomic()`, but the marker lives in a JSON file, so
"atomic + write the marker after" leaves a window: a crash between the DB commit and the file write
yields fully rewritten content with no marker, and the state-driven trigger would then re-apply an
old-pk-keyed map to hrefs that now hold *target* pks — the silent mis-point case this design exists to
prevent, and the one the test harness cannot reach. So: set `status` to **`in_progress`** *before*
entering the transaction, flip it to **`applied`** after commit, and treat a state file found
`in_progress` as a **`CommandError`** in both `import` and `verify`, never a silent re-run.

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
  `in_progress` (otherwise `CommandError`). `applied` flips `status` to `applied` and records
  `rewrite` counts as unknown; `not-applied` flips it back to `collecting`, so the ordinary trigger
  re-fires on the next `import` invocation.
- The decision is the operator's, not the command's. An automatic probe that guesses wrong produces
  exactly the silent mis-point the whole design is built to avoid, so the command reports and refuses;
  the human decides.

### Counts

The pass **prints per-part and total counts** to stdout and records them in the state file under a
`rewrite` object added at the `applied` flip; the per-part grouping is what the part-order keying
provides. Each in-scope element is attributed to the part whose `node_map` contains its `unit_id`.

```json
"rewrite": {
  "parts": [{"order": 0, "elements_touched": 12, "flattened": 1}],
  "elements_touched": 12,
  "flattened": 1,
  "skipped_parts": 0,
  "skipped_ids": 0,
  "skipped_dead": 0
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

`verify` prints these from the state file; it cannot recompute them, since it reads only the manifest,
baseline and archives, none of which carry the counts.

### Verify — the link reconciliation

Counts cannot be recomputed at `verify` time, but the *outcome* can be checked directly, and the
design's headline risk is exactly a mis-pointed or unrewritten link. `verify` therefore scans the same
scope the pass used — `Element` rows whose `unit_id` is among the state file's recorded new pks — and
counts elements holding an internal href whose pk is not a `ContentNode` of the **target** course.

After a correct pass that count is **zero**: every mapped href points at a target node, and everything
unmapped was unwrapped to plain text. So the threshold is not a tuning knob —

- nonzero → `CommandError`, reporting the count and up to ten example `(unit_id, element pk, href)`
  triples. It catches a skipped pass (every href still holds a source pk) and a double-apply against
  nonexistent pks.
- zero → a printed confirmation line alongside the recorded counts.

It does **not** catch the pk-collision double-apply, where a re-applied map lands on a pk that happens
to exist in the target. Nothing can, from the target side alone; that case is prevented by the
once-only invariant below, not detected here.

`verify` also raises `CommandError` when the state file is `in_progress` (see above), when a committed
bundle's state file lacks the `applied` marker (the skipped-pass case), and when the state file is
**missing** entirely — telling the operator to run `import` first, mirroring what `verify` already does
for a missing `BASELINE_NAME` (`migrate_course_content.py:524-534`).

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

IMPORT (per part)
  with transaction.atomic():                              # OUTER: commits after the write below
      report = {}
      import_subtree(..., on_missing="defer", report=report)   # rewrites nothing
      state["parts"] = [e for e in state["parts"] if int(e["order"]) != order]
      state["parts"].append({"order": order, "node_map": report["node_map"]})  # {"n7": 4711}
      write LINK_STATE_NAME                               # status stays "collecting"

TRIGGER (before the `not todo` early return, and after the loop)
  recorded = {int(e["order"]) for e in state["parts"]}
  on_disk  = {order for order, _ in ordered}
  if recorded == on_disk and state["status"] != "applied":  run the pass

FINAL PASS (once)
  mapping = {int(old): by_order[int(order)][export_id] ...}   # skip-on-miss, both lookups
  state["status"] = "in_progress"; write            # BEFORE the transaction
  with transaction.atomic():
      for join in Element.objects.filter(unit_id__in=new_pks).prefetch_related("content_object"):
          if join.content_object is None: continue
          changed, flattened = rewrite_instance(join.content_object, mapping, on_missing="unwrap")
          if changed: join.content_object.save(update_fields=changed)
  state["status"] = "applied"; state["rewrite"] = {...}; write   # AFTER the commit

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
  within-part link in the course. A cross-part-only fixture passes that broken design.
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
- `--force` grafting into a target that already holds linked content: the pre-existing bodies are
  **untouched**, since the pass is scoped to the nodes the state file records as created by this
  migration.

**One case per §Error handling condition** — the section defines failures the cases above do not
reach:

- A bundle whose `bundle-manifest.json` has no `node_index` → `CommandError` at the top of `import`,
  before anything is grafted.
- A state file marked `in_progress` → `CommandError` from both `import` and `verify`, and the probe
  reading appears in the message; `--resolve-rewrite not-applied` then lets the pass run to
  completion, and `--resolve-rewrite applied` on a `collecting` file is itself a `CommandError`.
- `verify` with no state file at all → `CommandError` naming `import`.
- `--start-at K` where part `K-1` is absent from the state file → `CommandError`; and, to falsify the
  string-key hazard, a fixture with **≥ 11 parts** resumed at `--start-at 10`, which a
  lexicographic-`max` implementation rejects and the specified set predicate accepts.
- `--dry-run` over a bundle with an existing state file leaves that file byte-identical.

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
  be added explicitly rather than assumed.
- **A state file found `in_progress`** → `CommandError` in both `import` and `verify`, never a silent
  re-run; the message carries the probe reading and names `--resolve-rewrite`. See §Crash-safe marking.
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
- **`--resolve-rewrite` on a state file that is not `in_progress`** → `CommandError`; the flag exists
  only to break the `in_progress` deadlock.
- **A `node_index` entry whose part order is not recorded in the state file, or whose export id is
  absent from that part's `node_map`** → skipped and counted (`skipped_parts` / `skipped_ids`), never
  a `KeyError` mid-transaction. A nonzero `skipped_parts` prints a warning line.
- **`verify` finding a dangling internal href in the migrated scope** → `CommandError` with the count
  and up to ten examples.
