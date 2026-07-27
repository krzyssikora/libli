# Internal link cutover (part 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make internal content links survive `migrate_course_content`, the mat-pp production cutover, which moves one top-level part at a time and would otherwise silently flatten every cross-part link in a 21-part course.

**Architecture:** Per-part imports rewrite **nothing** (a third `on_missing` value, `defer`); export writes a bundle-level `node_index` covering the whole source course; import accumulates `export_id → new_pk` into a crash-safe state file; exactly one deferred pass rewrites everything once the complete map is known. `verify` reconciles the result.

**Tech Stack:** Django 5.2.15, Python 3.11, pytest + pytest-django, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-07-26-internal-link-cutover-design.md` (converged, 10 review rounds, 139 catches). Where this plan and the spec disagree, **the spec wins** — report the discrepancy rather than guessing.

## MEASURED DIVERGENCE FROM THE SPEC — read before Task 7 or 12

The spec's §mechanics says part 2's third fail-closed condition is "evaluated over the **body as a
whole** — the scanner bails on the body, not on one anchor". **Measured against part 2's own planned
implementation, that is half true, and the difference makes two of the spec's §Testing cases
unbuildable.** Part 2's `rewrite_links` does:

```python
elif on_missing == "unwrap":
    close = re.compile(r"</a\s*>", re.I).search(html, end)   # from THIS anchor's end
    if close is None:
        return html, 0          # fail closed: no matching </a>
```

The *effect* is whole-body (it returns byte-identical), but the *trigger* is per-anchor, and a
**later** anchor's `</a>` satisfies an earlier torn anchor's search. Measured:

```
rewrite_links('<p><a href="/courses/n/3/">torn<a href="/courses/n/6/">ok</a></p>', {},
              on_missing="unwrap")   ->  ('<p>tornok</p>', 2)      # NOT fail-closed
rewrite_links('<p><a href="/courses/n/999999/">torn</p>', {3: 103},
              on_missing="unwrap")   ->  (unchanged, 0)            # fail-closed
```

Three consequences the tasks below encode:

1. **A fail-closed fixture must be a single torn anchor with no `</a>` anywhere after it.** The
   spec's "one unterminated anchor plus one well-formed link" shape does not fail-close.
2. **Its target must be *unmappable*.** The bail lives on the `elif on_missing == "unwrap"` branch,
   so a mappable pk is simply rewritten and never reaches it — the probe (empty map) would say
   `True` while the real pass rewrites normally. That is the spec's accepted over-report, and a test
   asserting `verify` reports the element needs the two to agree.
3. **Part 2's other two fail-closed conditions are invisible to `_is_fail_closed`, and that is
   safe.** `find_link_targets` catches `_Unscannable` and returns `set()`, so the probe's
   `if not find_link_targets(value): continue` skips them — but `_scan_links` uses the same helper,
   so those bodies are never reported as dangling either. Undetectable *and* never falsely failing.
   No task tries to cover them.

This is a spec defect, not a plan liberty. Report it upstream; do not "fix" the plan back toward the
spec's wording.

---

## PREREQUISITE — read before Task 1

**Part 2 must be implemented and merged before any task in this plan can run.** Measured on this
branch:

```console
$ ls courses/richtext.py
ls: cannot access 'courses/richtext.py': No such file or directory
$ grep -c "on_missing\|report" courses/transfer/importer.py
0
```

Part 3 consumes, and does not create: `courses/richtext.py`'s `rewrite_instance`,
`rewrite_links`, `find_link_targets`, `iter_rich_text`; and `import_subtree`'s keyword-only
`on_missing` / `report` parameters. Those are Tasks 1 and 4 of
`docs/superpowers/plans/2026-07-26-internal-link-durability.md`.

**Gate before starting Task 1:**

```bash
uv run python -c "
from courses.richtext import rewrite_instance, rewrite_links, find_link_targets, iter_rich_text
import inspect
from courses.transfer.importer import import_subtree
sig = inspect.signature(import_subtree)
assert 'on_missing' in sig.parameters, sig
assert 'report' in sig.parameters, sig
print('part 2 present:', sig)
"
```

If that fails, **stop** and report that part 2 has not landed. Do not stub it.

---

## Global Constraints

- **Tooling:** `python`, `pytest` and `ruff` are **not** on PATH. Every command is prefixed
  `uv run`, from the worktree root. `uv run ruff format --check .` and `uv run ruff check .` must
  pass before each commit.
- **Test DB isolation:** this worktree's `.env` sets `DATABASE_URL` to `…/libli_wt_cutover`. A
  parallel session runs tests against the main checkout — **never run two pytest invocations at
  once**, and never edit the `.env`.
- **pytest verdicts do not survive a shell pipe.** Use the exit code, or `grep FAILED`.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD` where a password is needed.
  (The existing `_user()` helper in this test file predates that rule and is left alone.)
- **Scope:** this plan changes `courses/transfer/export.py`, `courses/transfer/importer.py`,
  `courses/management/commands/migrate_course_content.py` and
  `tests/test_migrate_course_content.py` **only**. `courses/richtext.py` is **unchanged**;
  `courses/builder.py` is **unchanged**; no sanitiser, no model, no template, no migration.
- **`build_export` keeps its 4-tuple return.** It is unpacked positionally at 28 sites across 10
  files (plus one indexed call at `tests/test_tabs_transfer.py:29`). Widening the arity breaks all
  of them. The new data leaves through an out-param.
- **`rewrite_links` still accepts only `keep` and `unwrap`.** Part 2's
  `test_an_unknown_on_missing_raises` asserts `rewrite_links(..., on_missing="defer")` raises
  `ValueError` and **must stay green**. `defer` is an `import_subtree` concept only.
- **Seven existing tests must stay green** and are referenced by name throughout:
  `test_start_at_grafts_only_the_remainder`, `test_start_at_recovers_after_force_and_a_mid_run_failure`,
  `test_start_at_beyond_all_parts_reports_nothing_to_do`, `test_export_refuses_import_only_flags`,
  `test_verify_refuses_when_import_was_never_run`, `test_verify_fails_when_a_part_is_missing`,
  `test_export_aborts_on_problems_and_allow_problems_overrides`.
- **Falsify every test.** A passing test proves nothing — delete the behaviour it guards and
  require RED before moving on. Each task names its falsification.

---

## File Structure

| file | responsibility | change |
|---|---|---|
| `courses/transfer/export.py` | archive construction | `build_export` gains keyword-only `report=None`, filled with `node_ids` |
| `courses/transfer/importer.py` | archive ingestion | `on_missing` gains `defer`; `report` gains `node_map` |
| `courses/management/commands/migrate_course_content.py` | the cutover | state file + helpers, export `node_index`, import gates + outer atomic, the deferred pass, `--resolve-rewrite`, `verify` reconciliation |
| `tests/test_migrate_course_content.py` | all cases in the spec's §Testing | extended |

Everything new lives in the command module rather than a new file: the spec pins
`LINK_STATE_NAME` as "a module constant beside `MANIFEST_NAME` and `BASELINE_NAME`", and every
helper is command-private. The module grows by roughly 300 lines; that is in keeping with its
existing shape (615 lines, three phase methods plus shared helpers).

---

### Task 1: Exporter `report["node_ids"]` out-param

**Files:**
- Modify: `courses/transfer/export.py:501` (the `build_export` signature) and its return path
- Test: `tests/test_transfer_export.py` (extend)

**Interfaces:**
- Produces: `build_export(course, node=None, source_host="", *, drop_missing_media=True, report=None)`.
  When `report` is a dict it receives `report["node_ids"] = {source_pk: "nN"}` — **int** keys, the
  local's shape verbatim. Populated whenever `report` is supplied, **including** when `problems` is
  non-empty. Return type is unchanged: the same 4-tuple.

- [ ] **Step 1: Write the failing tests**

**Use this file's real fixtures.** `tests/test_transfer_export.py` has `pytestmark =
pytest.mark.django_db` at `:43` (so no `db` fixture is needed) and defines two pytest **fixtures** —
`course` (`:46`) and `image_asset` (`:52`) — plus module helpers `_mk_tree`, `_attach`,
`_delete_asset_file` and `_make_broken_join`. There is no `_course_with_two_units` or
`_course_with_a_broken_media_ref`; the problems path at `:405`/`:429` is produced by
`_delete_asset_file(image_asset)`. Append:

```python
def test_build_export_fills_report_node_ids_when_asked(course):
    # _mk_tree is MANDATORY: the `course` fixture is a bare
    # Course.objects.create(...) with ZERO nodes, so without it every assertion
    # below is set()==set() / 0==0 and the falsification cannot go RED.
    _mk_tree(course)
    report = {}
    _m, doc, _ma, _p = build_export(course, report=report)
    ids = report["node_ids"]
    assert len(ids) >= 3                         # a real tree, not an empty one
    # int keys (source pks), values are the document's own export ids.
    assert all(isinstance(k, int) for k in ids)
    assert set(ids.values()) == {nd["id"] for nd in doc["nodes"]}
    assert len(ids) == len(doc["nodes"])


def test_build_export_without_report_is_unchanged(course):
    _mk_tree(course)
    # The 4-tuple contract every other call site relies on.
    result = build_export(course)
    assert len(result) == 4


def test_report_node_ids_survives_the_problems_path(course, image_asset):
    """--allow-problems must not cost the operator the node index.

    `problems` is produced only for an asset reached THROUGH an element in the
    exported tree, so the tree and the ImageElement both have to exist first --
    copy the exact setup from the test at tests/test_transfer_export.py:396-410
    rather than the two lines below if they drift.
    """
    unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset, alt="a"))
    _delete_asset_file(image_asset)              # the file's own problems recipe
    report = {}
    _m, _doc, _ma, problems = build_export(course, report=report)
    assert problems                              # precondition: this path was taken
    assert report["node_ids"]                    # and the index still arrived
```

If `image_asset` needs to be attached to the tree for `problems` to be non-empty, copy the exact
setup from the test at `:405` rather than inventing one.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_transfer_export.py -k "report_node_ids or without_report" -q
```
Expected: FAIL — `TypeError: build_export() got an unexpected keyword argument 'report'`.

- [ ] **Step 3: Implement**

In `courses/transfer/export.py`, change the signature at `:501` and fill the dict where
`node_ids` is completed. `node_ids` is a local built at `:504-508`; the fill must happen **before**
any `return`, including the tolerant-export/`problems` return, so put it immediately after the node
loop:

```python
def build_export(course, node=None, source_host="", *, drop_missing_media=True, report=None):
    with transaction.atomic():
        nodes = _ordered_nodes(course, root=node)
        node_ids = {}
        node_dicts = []
        for i, n in enumerate(nodes, start=1):
            nid = f"n{i}"
            node_ids[n.pk] = nid
            parent_internal = (
                None
                if (node is not None and n.pk == node.pk)
                else node_ids.get(n.parent_id)
            )
            node_dicts.append(_node_dict(n, nid, parent_internal))

        # Out-param, NOT a fifth return value: build_export's 4-tuple is unpacked
        # positionally at 28 sites across 10 files (courses/builder.py:333 among
        # them), so widening the arity would break every one. Filled here, before
        # any return, so the tolerant-export `problems` path keeps it too --
        # --allow-problems must not cost the caller the node index.
        if report is not None:
            report["node_ids"] = dict(node_ids)
```

Leave the rest of the function untouched.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_transfer_export.py -q
```
Expected: PASS, whole file.

- [ ] **Step 5: Falsify**

Temporarily change `report["node_ids"] = dict(node_ids)` to `report["node_ids"] = {}`. Re-run:
`test_build_export_fills_report_node_ids_when_asked` and `test_report_node_ids_survives_the_problems_path`
must both go RED. Restore.

- [ ] **Step 6: Confirm no caller broke**

```bash
uv run pytest tests/test_transfer_export.py tests/test_transfer_import.py tests/test_transfer_subtree.py tests/test_tabs_transfer.py tests/test_transfer_materialize_duplicate.py -q
```
Expected: PASS. These cover the positional-unpack sites.

- [ ] **Step 7: Commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py
uv run ruff check courses/transfer/export.py tests/test_transfer_export.py
git add courses/transfer/export.py tests/test_transfer_export.py
git commit -m "feat(transfer): hand node_ids back through an optional report out-param on build_export"
```

---

### Task 2: Importer `defer` + `report["node_map"]`

**Files:**
- Modify: `courses/transfer/importer.py` (`import_subtree` at `:984`, and the post-pass part 2 added)
- Test: `tests/test_link_transfer.py` (extend — part 2 created it)

**Interfaces:**
- Consumes: part 2's `import_subtree(..., *, on_missing="unwrap", report=None)` and its rewrite
  post-pass.
- Produces:
  - `on_missing="defer"` on `import_subtree` — **skips the rewrite post-pass entirely**; every href
    still holds a source pk afterwards.
  - `report["node_map"] = {export_id: new_pk}` — **int** values, populated **unconditionally**,
    outside and before the post-pass, for all three `on_missing` values.
  - `report["flattened_links"]` is **present and `0`** under `defer`, never absent.

- [ ] **Step 1: Write the failing tests**

**These must drive `import_subtree`, not `import_course`.** Part 2's `_round_trip` helper
(`…-internal-link-durability.md:1029-1051`) calls `import_course`, which this task does **not**
teach `defer` — routing a `defer` test through it would reach `rewrite_links` and raise
`ValueError: unknown on_missing`. So add a subtree sibling first. Model its archive-buffer plumbing
on `tests/test_transfer_subtree.py`'s own buffer helper — the one ending in `return buf` just above
`:115`. **Not** `:121`, which is `_assert_subtree_graphs_equal(source_course, source_root,
target_course, target_root)`, a graph comparator with nothing to do with archive construction.

Append to `tests/test_link_transfer.py`:

```python
def _round_trip_subtree(course, root, target_course, user, report, *, on_missing):
    """Export `root` as a subtree and graft it into `target_course`.

    import_subtree is the ONLY entry point that learns `defer`, so every test
    below goes through here rather than part 2's import_course-based _round_trip.
    """
    import io

    from courses.transfer.export import build_export, write_archive_from
    from courses.transfer.importer import (
        import_subtree,
        open_archive,
        validate_archive_document,
    )

    manifest, document, assets, _problems = build_export(course, node=root)
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="subtree") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="subtree",
                                  target_course=target_course)
        return import_subtree(
            zf, mani, doc, media, target_course, None, user,
            on_missing=on_missing, report=report,
        )


def test_defer_skips_the_rewrite_and_reports_node_map():
    """The cutover's contract: rewrite NOTHING, but hand back the map."""
    course, chapter, _unit = _course_with_link()
    target = Course.objects.create(title="T", slug="t-defer", uses_chapters=True)
    report = {}
    _round_trip_subtree(course, chapter, target, course.owner, report,
                        on_missing="defer")

    from courses.models import TextElement

    body = TextElement.objects.filter(elements__unit__course=target).first().body
    # Untouched: the href still holds the SOURCE pk.
    assert f"/courses/n/{chapter.pk}/" in body
    # And the map came back anyway.
    assert report["node_map"]
    assert all(isinstance(v, int) for v in report["node_map"].values())
    # Present-and-zero, not absent -- callers read it without a .get.
    assert report["flattened_links"] == 0


@pytest.mark.parametrize("policy", ["keep", "unwrap", "defer"])
def test_node_map_is_populated_for_every_on_missing_value(policy):
    course, chapter, _unit = _course_with_link()
    target = Course.objects.create(
        title="T", slug=f"t-{policy}", uses_chapters=True
    )
    report = {}
    _round_trip_subtree(course, chapter, target, course.owner, report,
                        on_missing=policy)
    assert report["node_map"], policy
    assert "flattened_links" in report, policy


def test_rewrite_links_still_rejects_defer():
    """`defer` is an importer concept. Part 2's helper must not learn it."""
    from courses.richtext import rewrite_links

    with pytest.raises(ValueError):
        rewrite_links('<a href="/courses/n/1/">x</a>', {}, on_missing="defer")
```

`_course_with_link()` is part 2's fixture; read it and adjust the `chapter` argument if its return
shape differs. If `validate_archive_document`'s subtree kwargs differ from the above, copy them
verbatim from `tests/test_transfer_subtree.py` rather than guessing.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_link_transfer.py -k "defer or node_map" -q
```
Expected: FAIL — `defer` is not an accepted `on_missing` value yet, and `node_map` is not in `report`.

- [ ] **Step 3: Implement**

In `courses/transfer/importer.py`, inside `import_subtree`'s `work()` (`:997-1003`), populate the
report before the post-pass, and gate the post-pass on the policy:

```python
def import_subtree(
    zf, manifest, document, media_entries, target_course, insertion_node, user,
    *, on_missing="unwrap", report=None,
):
    created_files = []

    def work():
        assets = _create_media(
            zf, document, media_entries, target_course, user, created_files
        )
        node_map = _create_nodes(document, target_course, root_parent=insertion_node)
        # Part 2 changes _create_elements to `return list(joins.values())` and
        # threads the result into _rewrite_links. Keep BOTH -- dropping `created`
        # silently makes the post-pass iterate nothing, so the Studio
        # subtree-upload path stops rewriting links with only
        # report["flattened_links"] == 0 to show for it.
        created = _create_elements(document, node_map, assets)

        # Bookkeeping is UNCONDITIONAL -- `defer` skips the rewrite, not this.
        # migrate_course_content needs export_id -> new_pk from every part, and
        # the natural reading of "skip the post-pass entirely" would drop exactly
        # it. The pk-valued projection keeps the state file JSON-serialisable.
        if report is not None:
            report["node_map"] = {eid: n.pk for eid, n in node_map.items()}
            report.setdefault("flattened_links", 0)

        if on_missing != "defer":
            _rewrite_links(
                document, node_map, created, on_missing=on_missing, report=report
            )
        return node_map[document["nodes"][0]["id"]]

    return _run_import(work, created_files)
```

`_rewrite_links(document, node_map, created_joins, *, on_missing, report)` is part 2's real
signature (`docs/superpowers/plans/2026-07-26-internal-link-durability.md:1150`), and
`import_subtree` calls it at `:1203-1204` exactly as above. Do **not** invent a name for it, and do
**not** drop the `created` argument.

**Do not add an `on_missing` guard anywhere.** Measured: part 2 validates in exactly one place,
`rewrite_links` (`…-internal-link-durability.md:451`, `if on_missing not in ("keep", "unwrap")`);
`import_subtree` has no validation at all. So there is nothing to extend — `defer` simply never
reaches `rewrite_links`, because the `if on_missing != "defer":` gate above short-circuits it.
Touching `rewrite_links`' tuple would turn part 2's `test_an_unknown_on_missing_raises` red, which
the Global Constraints forbid.

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_link_transfer.py tests/test_richtext.py -q
```
Expected: PASS, both files. `test_an_unknown_on_missing_raises` in `tests/test_richtext.py` must
still be green — that is the collision guard.

- [ ] **Step 5: Falsify**

Move the `report["node_map"] = …` assignment inside the `if on_missing != "defer":` block.
`test_defer_skips_the_rewrite_and_reports_node_map` must go RED with `KeyError: 'node_map'`.
Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/transfer/importer.py tests/test_link_transfer.py
uv run ruff check courses/transfer/importer.py tests/test_link_transfer.py
git add courses/transfer/importer.py tests/test_link_transfer.py
git commit -m "feat(transfer): add on_missing='defer' and report['node_map'] to import_subtree"
```

---

### Task 3: State-file constants and pure helpers

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py` (imports, constants, helpers)
- Test: `tests/test_migrate_course_content.py` (extend)

**Interfaces:**
- Produces, all module-level in the command module:
  - `LINK_STATE_NAME = "import-link-state.json"`, `LINK_STATE_VERSION = 1`
  - `_write_state(bundle, state) -> None` — atomic `.tmp` + `os.replace`
  - `_read_state(bundle, *, validate) -> dict | None`
  - `_fresh_state(target) -> dict`
  - `_invert_node_index(node_index, order) -> {export_id: int(source_pk)}`
  - `_live_pks(entries, target) -> set[int]`

- [ ] **Step 1: Write the failing tests**

**The six new imports go into the existing top-of-file import block** (`tests/test_migrate_course_content.py:13-21`),
alphabetised in place beside the existing `BASELINE_NAME` / `MANIFEST_NAME` / `Command` imports —
**not** appended at the bottom. `pyproject.toml:36` selects `["E", "F", "I", "UP", "B", "S"]`, so a
mid-file import is `E402 Module level import not at top of file` and every task's lint step would
fail. isort is `force-single-line = true`, so one `from … import X` per line:

```python
from courses.management.commands.migrate_course_content import LINK_STATE_NAME
from courses.management.commands.migrate_course_content import _fresh_state
from courses.management.commands.migrate_course_content import _invert_node_index
from courses.management.commands.migrate_course_content import _live_pks
from courses.management.commands.migrate_course_content import _read_state
from courses.management.commands.migrate_course_content import _write_state
```

Then append the helper and tests to the body of the file:

```python
def _read_state_raw(bundle):
    return json.loads((bundle / LINK_STATE_NAME).read_text(encoding="utf-8"))


def test_invert_node_index_parses_string_pks_to_ints():
    """The `src` guard is a fatal equality test and node_index keys are decimal
    STRINGS. Without int() the comparison is False on every part of every run."""
    ni = {"1234": [0, "n1"], "1235": [0, "n2"], "9001": [1, "n1"]}
    assert _invert_node_index(ni, 0) == {"n1": 1234, "n2": 1235}
    assert _invert_node_index(ni, 1) == {"n1": 9001}
    assert _invert_node_index(ni, 7) == {}


def test_invert_node_index_survives_a_json_round_trip():
    """JSON has no tuple type: [order, export_id] comes back as a 2-element list."""
    ni = json.loads(json.dumps({"1234": (0, "n1")}))
    assert _invert_node_index(ni, 0) == {"n1": 1234}


def test_write_state_is_atomic_and_leaves_no_tmp_file(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    _write_state(bundle, {"version": 1, "parts": []})
    assert _read_state_raw(bundle) == {"version": 1, "parts": []}
    assert not (bundle / (LINK_STATE_NAME + ".tmp")).exists()


def test_read_state_validating_rejects_torn_json_and_a_wrong_version(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    with pytest.raises(CommandError, match="not valid JSON"):
        _read_state(bundle, validate=True)
    (bundle / LINK_STATE_NAME).write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(CommandError, match="version"):
        _read_state(bundle, validate=True)


def test_read_state_non_validating_swallows_a_torn_file(tmp_path):
    """The `start_at is None` branch discards the file wholesale, so validating
    it there could only manufacture a dead end with no documented remedy."""
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    assert _read_state(bundle, validate=False) is None


def test_read_state_returns_none_when_absent(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    assert _read_state(bundle, validate=True) is None


def test_fresh_state_carries_all_five_top_level_keys():
    target = _mk_target()
    st = _fresh_state(target)
    assert set(st) == {"version", "status", "target_slug", "target_pk", "parts"}
    assert st["status"] == "collecting"
    assert st["target_pk"] == target.pk
    assert st["parts"] == []


def test_live_pks_filters_to_rows_in_the_given_course():
    """course=target is not decoration: a bare pk__in would call a node in some
    OTHER course 'resolved', which is the mis-point this design guards against."""
    target = _mk_target()
    other = Course.objects.create(title="Other", slug="other")
    a = ContentNode.objects.create(course=target, kind="part", title="A")
    b = ContentNode.objects.create(course=other, kind="part", title="B")
    entries = [{"order": 0, "node_map": {"n1": a.pk, "n2": b.pk, "n3": 10**9}}]
    assert _live_pks(entries, target) == {a.pk}
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "invert_node_index or write_state or read_state or fresh_state or live_pks" -q
```
Expected: FAIL — `ImportError: cannot import name 'LINK_STATE_NAME'`.

- [ ] **Step 3: Implement**

Add `import os` (with the stdlib imports, beside `import json` at `:13`) and
`from django.db import transaction` **before** the existing
`from django.db.models import Count` at `:20` — isort is `force-single-line` and orders
`django.core.management.base` -> `django.db` -> `django.db.models`, so appending it after `:20`
fails `ruff check` at the very next step. Neither is currently imported. Then add beside `BASELINE_NAME`:

```python
# Written by `import`, accumulated one entry per part, and read by the deferred
# link rewrite. It is the ONLY record of export_id -> new_pk: export ids exist
# nowhere else once an archive has been grafted, so losing this file loses the
# ability to rewrite anything. Lifecycle mirrors BASELINE_NAME -- never unlinked
# by `export --clean`, overwritten fresh when `start_at is None`.
LINK_STATE_NAME = "import-link-state.json"
LINK_STATE_VERSION = 1


def _write_state(bundle, state):
    """Serialise to <name>.tmp then os.replace onto the real name.

    NEVER truncate-in-place. Path.write_text opens mode="w", which truncates
    before writing a byte; this file is rewritten once per part (21 times for
    mat-pp) inside an open transaction, so a crash or ENOSPC in any of those
    windows would leave truncated JSON -- and a torn state file discards every
    committed part's export_id -> new_pk map, which is unrecoverable.
    """
    tmp = bundle / (LINK_STATE_NAME + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, bundle / LINK_STATE_NAME)


def _read_state(bundle, *, validate):
    """`validate=False` is for the one branch that discards the file wholesale
    (`start_at is None`, no --resolve-rewrite). Validating there could only turn
    a torn file into a permanent dead end: `export --clean` deliberately does not
    unlink this file, so the operator's only remedy would be a manual rm."""
    path = bundle / LINK_STATE_NAME
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        if not validate:
            return None
        raise CommandError(
            f"{LINK_STATE_NAME} in {bundle} is not valid JSON: {exc}"
        ) from exc
    if not validate:
        return state
    if state.get("version") != LINK_STATE_VERSION:
        raise CommandError(
            f"{LINK_STATE_NAME} in {bundle} has version "
            f"{state.get('version')!r}; this command writes and reads version "
            f"{LINK_STATE_VERSION}"
        )
    return state


def _fresh_state(target):
    return {
        "version": LINK_STATE_VERSION,
        "status": "collecting",
        "target_slug": target.slug,
        "target_pk": target.pk,
        "parts": [],
    }


def _invert_node_index(node_index, order):
    """{export_id: source_pk} for one part order.

    int(pk) is REQUIRED: node_index keys are decimal STRINGS and the `src` guard
    is a fatal equality test, so a missing int() makes it False on every part of
    every run and blocks the feature behind a spurious re-export error. This is
    THE shared helper -- called at the graft-time write and at the guard, never
    inlined at either.
    """
    return {
        eid: int(pk)
        for pk, (o, eid) in ((k, tuple(v)) for k, v in node_index.items())
        if int(o) == int(order)
    }


def _live_pks(entries, target):
    """Recorded pks of `entries`, filtered to rows that actually exist in
    `target`. Callers differ only in which entries they pass: the rewrite scope
    passes PENDING entries, the mapping's liveness filter and `verify` pass ALL
    of them."""
    recorded = {pk for e in entries for pk in e["node_map"].values()}
    return set(
        ContentNode.objects.filter(pk__in=recorded, course=target).values_list(
            "pk", flat=True
        )
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -k "invert_node_index or write_state or read_state or fresh_state or live_pks" -q
```
Expected: PASS.

- [ ] **Step 5: Falsify**

- Drop the `int(pk)` from `_invert_node_index` (leave `eid: pk`). Both
  `test_invert_node_index_*` tests must go RED.
- Drop `course=target` from `_live_pks`; `test_live_pks_filters_to_rows_in_the_given_course` must
  go RED.
- Replace `_write_state`'s body with a plain
  `(bundle / LINK_STATE_NAME).write_text(json.dumps(state), encoding="utf-8")`.
  `test_write_state_is_atomic_and_leaves_no_tmp_file` stays **GREEN** — which is the point: the
  presence/absence assertions cannot detect the truncate-in-place implementation the spec forbids.
  `test_write_state_really_goes_through_os_replace` (Task 12) is the one that goes RED. Note it and
  move on; do not weaken Task 12's test to compensate.

Restore all three.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): add the link-state file constants and its pure helpers"
```

---

### Task 4: Export writes the bundle-level `node_index`

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py:309-360` (`_export`'s loop and manifest write)
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: Task 1's `report["node_ids"]`.
- Produces: `bundle-manifest.json["node_index"] = {str(source_pk): [part_order, export_id]}`,
  covering **every** node in the source course.

- [ ] **Step 1: Write the failing tests**

```python
def test_export_writes_a_node_index_covering_every_node(tmp_path):
    course = _mk_source(parts=("Alpha", "Beta"))
    bundle = tmp_path / "bundle"
    call_command(
        "migrate_course_content", "export",
        "--source-slug", "src", "--bundle-dir", str(bundle),
    )
    index = _read_manifest(bundle)["node_index"]
    # Every node in the COURSE, not just link targets and not just one part.
    all_pks = set(ContentNode.objects.filter(course=course).values_list("pk", flat=True))
    assert {int(k) for k in index} == all_pks
    # Shape: {"<pk>": [order, "nN"]}, the pair in that order. JSON has no tuple
    # type, so it round-trips as a 2-element list.
    order, export_id = index[str(sorted(all_pks)[0])]
    assert isinstance(order, int)
    assert export_id.startswith("n")
    # Export ids restart at n1 in EVERY archive -- the part order is what
    # disambiguates them, and keying the two phases differently would make every
    # lookup miss silently.
    per_order = {}
    for o, eid in index.values():
        per_order.setdefault(o, set()).add(eid)
    assert all("n1" in ids for ids in per_order.values())


def test_export_node_index_survives_allow_problems(tmp_path):
    """--allow-problems must not cost the operator the node index."""
    _mk_source(parts=("Alpha",))
    bundle = tmp_path / "bundle"

    def fake(course, node=None, **kw):
        manifest, document, media, _p = _real_build_export(course, node=node, **kw)
        return manifest, document, media, ["synthetic problem"]

    import courses.management.commands.migrate_course_content as mod

    _real_build_export = mod.build_export
    mod.build_export = fake
    try:
        call_command(
            "migrate_course_content", "export",
            "--source-slug", "src", "--bundle-dir", str(bundle),
            "--allow-problems",
        )
    finally:
        mod.build_export = _real_build_export
    assert _read_manifest(bundle)["node_index"]
```

**Trap:** `test_export_aborts_on_problems_and_allow_problems_overrides`
(`tests/test_migrate_course_content.py:175`) monkeypatches `build_export` with
`def fake(course, node=None, **kw)`. Its `**kw` forwards the new `report` kwarg **by accident, not
by design**. Write the second test above so it pins that forwarding explicitly; if the existing
fake ever loses `**kw`, the index silently empties and the next `import` becomes a hard
`CommandError`. Prefer `monkeypatch` over the manual save/restore above if the file already uses
it — read the surrounding tests and match.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "node_index" -q
```
Expected: FAIL — `KeyError: 'node_index'`.

- [ ] **Step 3: Implement**

In `_export`, accumulate alongside the existing `side` map (which has exactly this lifecycle
already — see `:301-303`) and fold it into the manifest:

```python
        # pk -> [part order, ...]. Accumulated across ALL parts and folded
        # into the manifest once, only on full success -- see MANIFEST_NAME.
        side = {}
        # source pk -> [part order, export id], same lifecycle as `side`. Covers
        # EVERY node in the course, because every node descends from some
        # top-level part -- unlike document["link_nodes"], which holds only
        # targets referenced from inside one part, so a node linked to ONLY from
        # another part would appear in no archive's map at all.
        node_index = {}
        total_nodes = 0
        total_elements = 0
        node_kind_counts = {}
        written = set()
```

**Insert `node_index = {}` between the existing `side = {}` and `total_nodes = 0`** — do not
replace the block wholesale. The real `:301-307` initialises six names (`side`, `total_nodes`,
`total_elements`, `node_kind_counts`, `written`), all still needed by the loop and the manifest;
they are reproduced above so a wholesale replacement cannot silently drop three of them.

Inside the loop, pass the out-param and merge:

```python
        for part in parts:
            report = {}
            manifest, document, media_assets, problems = build_export(
                course, node=part, report=report
            )
            if problems and not o.get("allow_problems"):
                raise CommandError(...)                       # unchanged
            for pk, nid in report["node_ids"].items():
                node_index[str(pk)] = [part.order, nid]
```

And in the manifest dict:

```python
        bundle_manifest = {
            "source_slug": course.slug,
            "part_count": len(parts),
            "tallies": {...},                                  # unchanged
            "media_parts": side,
            "node_index": node_index,
        }
```

Extend the closing stdout line so the operator sees it:

```python
        self.stdout.write(
            f"wrote {MANIFEST_NAME} ({total_nodes} nodes, {total_elements} "
            f"elements, {len(side)} distinct media asset(s), "
            f"{len(node_index)} node(s) indexed for internal links)"
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS, whole file (nothing else reads `node_index` yet).

- [ ] **Step 5: Falsify**

Change `node_index[str(pk)] = [part.order, nid]` to key by `nid` instead of the pk.
`test_export_writes_a_node_index_covering_every_node` must go RED. Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): write a bundle-level node_index covering the whole source course"
```

---

### Task 5: Import — capture the manifest, refuse a pre-feature bundle, graft under an outer atomic

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py:387` and `:454-508`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: Task 2's `defer`/`node_map`, Task 3's `_write_state`/`_invert_node_index`, Task 4's `node_index`.
- Produces: a state file accumulating one entry per grafted part, each
  `{"order": int, "node_map": {...}, "src": {...}, "rewritten": False}`, with top-level `status`
  reset to `"collecting"` on every graft.

- [ ] **Step 1: Write the failing tests**

```python
def test_import_refuses_a_bundle_with_no_node_index(tmp_path):
    """A pre-feature bundle: fatal BEFORE anything is grafted. The tolerant
    fall-through would not mean 'no rewrites' -- with an empty map and
    on_missing='unwrap' it means every internal link in the course is destroyed
    inside a committed transaction, with the count arriving afterwards."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    manifest = _read_manifest(bundle)
    del manifest["node_index"]
    (bundle / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="predates internal-link support"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com",
        )
    assert ContentNode.objects.filter(course=target).count() == 0


def test_import_records_one_state_entry_per_grafted_part(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    state = _read_state_raw(bundle)
    assert state["version"] == 1
    assert state["target_pk"] == target.pk
    assert [e["order"] for e in state["parts"]] == [0, 1, 2]
    index = _read_manifest(bundle)["node_index"]
    for entry in state["parts"]:
        # node_map values are real pks in the target.
        assert all(
            ContentNode.objects.filter(pk=pk, course=target).exists()
            for pk in entry["node_map"].values()
        )
        # src is the manifest's inversion for that order -- int-valued.
        assert entry["src"] == _invert_node_index(index, entry["order"])
        # NOTE FOR TASK 8: once site 2 is wired, this full import also runs the
        # pass, which flips every flag. Change this line to `is True` then --
        # Task 8 Step 4 names it.
        assert entry["rewritten"] is False


def test_a_regraft_replaces_the_entry_rather_than_duplicating(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    first = _read_state_raw(bundle)
    ContentNode.objects.filter(course=Course.objects.get(slug="dst"),
                               parent__isnull=True).exclude(title="P0").delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    second = _read_state_raw(bundle)
    assert [e["order"] for e in second["parts"]] == [0, 1, 2]   # not 0,1,2,1,2
    assert second["parts"][1]["node_map"] != first["parts"][1]["node_map"]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "no_node_index or state_entry_per_grafted or regraft_replaces" -q
```
Expected: FAIL.

- [ ] **Step 3: Implement**

At `:387`, capture the manifest under a **distinct name** and hoist `node_index`:

```python
        bundle = Path(o["bundle_dir"])
        archives = self._bundle_archives(bundle)
        # NOT `manifest`: the graft loop binds that name at :457-462 via
        # `with open_archive(...) as (zf, manifest, ...)`, and a `with ... as`
        # target binds in the ENCLOSING FUNCTION SCOPE and survives the block.
        # After the loop `manifest` is the LAST ARCHIVE's manifest, so the
        # post-loop trigger would read the wrong dict and raise KeyError.
        bundle_manifest = self._read_bundle_manifest(bundle, archives)
        if "node_index" not in bundle_manifest:
            raise CommandError(
                f"{MANIFEST_NAME} in {bundle} has no 'node_index': this bundle "
                f"predates internal-link support. Re-export it -- importing it "
                f"as-is would flatten every internal link in the course."
            )
        node_index = bundle_manifest["node_index"]
        ordered = [(self._archive_order(p.name), p) for p in archives]
```

In the graft loop, replace the bare `import_subtree(...)` call at `:481-489` with an outer atomic
that also writes the state entry:

```python
                        # OUTER atomic, opened here and NOT around the archive
                        # open: _run_import's own atomic becomes a savepoint, so
                        # the real commit happens when THIS block exits -- after
                        # the state write below. That inverts the crash window
                        # from a MISSING entry (unrecoverable: export ids exist
                        # nowhere else) to a STALE one (detectable, and replaced
                        # by the re-graft).
                        try:
                            with transaction.atomic():
                                report = {}
                                import_subtree(
                                    zf,
                                    manifest,
                                    document,
                                    media_entries,
                                    target,
                                    None,
                                    user,
                                    on_missing="defer",
                                    report=report,
                                )
                                state["parts"] = [
                                    e
                                    for e in state["parts"]
                                    if int(e["order"]) != order
                                ]
                                state["parts"].append(
                                    {
                                        "order": order,
                                        "node_map": report["node_map"],
                                        "src": _invert_node_index(node_index, order),
                                        "rewritten": False,
                                    }
                                )
                                # A RE-graft after "applied" must re-arm the pass.
                                state["status"] = "collecting"
                                _write_state(bundle, state)
                        except OSError as exc:
                            # NOT `except Exception`: import_subtree runs inside
                            # this block and TransferError is a plain Exception
                            # subclass, so a broad catch would report an
                            # IntegrityError as a state-file failure and leave
                            # :490's handler reachable only for open_archive.
                            if committed is None:
                                hint = (
                                    "no parts committed; re-run import from "
                                    "the start"
                                )
                            else:
                                hint = (
                                    f"last part committed: {committed}; "
                                    f"resume with --start-at {committed + 1}"
                                )
                            raise CommandError(
                                f"could not write {LINK_STATE_NAME} while "
                                f"grafting part {order}: {exc}. Part {order}'s "
                                f"media files may be orphaned on disk.\n{hint}"
                            ) from exc
```

Note `hint` reuses **both** arms of `:494-500`. Using only the `else` arm would evaluate
`None + 1` on the first part and raise `TypeError` — a raw traceback, which is exactly what this
handler exists to prevent.

`state` must be in scope before the loop. Task 6 owns where it is loaded; for now, immediately
after the `node_index` hoist, add a placeholder that Task 6 replaces:

```python
        # PLACEHOLDER -- superseded by Task 6's ordered branch. Deliberately
        # over-strict: it validates on the `start_at is None` path, which spec
        # step 1 exempts, so a torn state file would make a from-scratch import
        # raise. That is acceptable only because no test exercises it until
        # Task 6, which replaces this line. Do not ship it.
        state = _read_state(bundle, validate=True) or _fresh_state(target)
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS, whole file — including all seven pinned tests.

- [ ] **Step 5: Falsify**

Move `_write_state(bundle, state)` to **after** the `with transaction.atomic():` block. The
inversion is then lost; `test_import_records_one_state_entry_per_grafted_part` still passes (it
does not crash), so instead falsify the *replace* rule: delete the list-comprehension line that
drops the existing order. `test_a_regraft_replaces_the_entry_rather_than_duplicating` must go RED
with five entries. Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): graft each part under an outer atomic and record its link state"
```

---

### Task 6: The ordered branch — load, validate, and the five resume gates

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py:390-451`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Produces: `_check_identity(state, target)`, `_check_src_drift(state, node_index)`, and the
  ordered branch that decides how `state` is obtained. The order is normative.

**The ordering, verbatim from the spec — implement exactly this sequence:**

1. Load the state file. Validate JSON and `version` **except** when `start_at is None` **and**
   `--resolve-rewrite` was not supplied.
2. If `--resolve-rewrite` was supplied: run the `target_pk` identity check **first**, then hand to
   the terminal action (Task 9) and return.
3. If `start_at is None`: discard the loaded file and write a fresh one — **behind the `:401`
   double-run guard and inside the `if not o.get("dry_run"):` at `:408-411`**.
4. Otherwise (a resume, including the degenerate `--start-at 0`): with no state file and
   `--start-at 0`, create a fresh one behind the dry-run gate and skip the rest; with
   `--start-at K > 0`, `CommandError`. Otherwise apply five gates **in this order**, all of them
   *after* the pre-existing `:429-439` invariant: identity → `in_progress` refusal → resume subset
   guard → `recorded - on_disk` refusal → `src` drift comparison.
5. Compute `todo`.
6. Trigger sites (Task 8).

- [ ] **Step 1: Write the failing tests**

```python
def _seed_state(bundle, target, orders, *, status="collecting", rewritten=False):
    """Hand-write a state file AND the world it describes.

    Three things must line up or the test measures the wrong gate:

    1. `BASELINE_NAME` must exist. Without it the resume path re-captures the
       baseline NOW (`:419-427`), so `baseline["top_nodes"] == existing` and
       `:433` raises for EVERY `--start-at K > 0` -- before any gate under test.
       Seeded here as an all-zero baseline, matching an empty target.
    2. The target must hold exactly `len(orders)` top-level nodes, or `:433`
       raises anyway.
    3. `node_map` values must be REAL live pks in `target`. Synthetic pks make
       `_build_mapping`'s `skipped_dead` non-empty, so any seeded test that
       reaches the pass dies on the fatal-skip CommandError instead.

    Every seeded test must also pass `match=` to `pytest.raises`, or it can pass
    on `:433`'s message and prove nothing.
    """
    index = _read_manifest(bundle)["node_index"]
    (bundle / BASELINE_NAME).write_text(
        json.dumps({
            "top_nodes": 0, "all_nodes": 0, "kind_counts": {},
            "elements": 0, "media": 0,
        }),
        encoding="utf-8",
    )
    state = _fresh_state(target)
    state["status"] = status
    for o in orders:
        src = _invert_node_index(index, o)
        # One real node per export id, so _live_pks finds every recorded pk.
        top = ContentNode.objects.create(course=target, kind="part", title=f"S{o}")
        node_map = {}
        for i, eid in enumerate(src):
            node_map[eid] = (
                top.pk
                if i == 0
                else ContentNode.objects.create(
                    course=target, kind="chapter", title=f"S{o}c{i}", parent=top
                ).pk
            )
        state["parts"].append({
            "order": o,
            "node_map": node_map,
            "src": src,
            "rewritten": rewritten,
        })
    _write_state(bundle, state)
    return state


def test_resume_refuses_a_state_file_missing_target_pk(tmp_path):
    """The gate that stops a wrong-target resume writing itself a matching
    identity. Adopting the resolved target instead would defeat it."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    st = _seed_state(bundle, target, [0])
    del st["target_pk"]
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="pre-feature import"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "1",
        )


def test_resume_refuses_a_state_file_for_a_different_target(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    other = Course.objects.create(title="Other", slug="other", uses_parts=True)
    _user()
    st = _seed_state(bundle, target, [0])
    st["target_pk"] = other.pk
    _write_state(bundle, st)
    # match= is mandatory: :433's own message contains "target", so a bare
    # pytest.raises(CommandError) would pass on the wrong gate.
    with pytest.raises(CommandError, match="Refusing to mix targets"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "1",
        )


def test_a_renamed_course_is_a_note_not_an_error(tmp_path, capsys):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import", "--target-slug", "dst",
        "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
        "--start-at", "0",
    )
    target.slug = "dst-renamed"
    target.save(update_fields=["slug"])
    call_command(
        "migrate_course_content", "import", "--target-slug", "dst-renamed",
        "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
        "--start-at", "3",
    )
    assert "renamed" in capsys.readouterr().out


def test_resume_refuses_when_a_committed_order_is_missing_from_the_state(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # Two orders' worth of nodes, but only order 0 recorded.
    _seed_state(bundle, target, [0])
    ContentNode.objects.create(course=target, kind="part", title="extra")
    with pytest.raises(CommandError, match="does not record them"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "2",
        )


def test_the_subset_guard_is_not_lexicographic(tmp_path):
    """JSON coerces int object keys to strings and max() over them is
    lexicographic: max(['0','9','10']) == '9'. With mat-pp's 21 parts a
    max()-based guard is wrong from part 10 onward. Hand-write the state and
    seed the nodes rather than running a real ten-part import."""
    bundle = _export_bundle(tmp_path, parts=tuple(f"P{i}" for i in range(11)))
    target = _mk_target()
    _user()
    # rewritten=True: this test asserts the GUARD accepts. After the loop grafts
    # part 10, recorded == on_disk == {0..10} and site 2 DOES fire -- seeding the
    # orders as already-rewritten keeps the pass's scope to order 10 alone,
    # rather than dragging ten seeded parts into it as a second subject.
    _seed_state(bundle, target, list(range(10)), rewritten=True)
    # Accepted: every archive order below 10 is recorded. A lexicographic-max
    # implementation computes max(["0".."9"]) == "9" and rejects this.
    call_command(
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com", "--start-at", "10",
    )
    assert ContentNode.objects.filter(course=target, title="P10").exists()


def test_resume_refuses_when_the_state_records_orders_no_longer_on_disk(tmp_path):
    """recorded > on_disk. Without this the trigger's set equality is merely
    False and `import` exits 0 having rewritten nothing."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2], rewritten=True)
    (sorted(bundle.glob("*.zip"))[-1]).unlink()
    manifest = _read_manifest(bundle)
    manifest["part_count"] = 2
    (bundle / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="no longer holds their archive"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "3",
        )


def test_a_missing_state_file_with_start_at_above_zero_refuses(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    # A baseline plus one committed part, but NO state file -- the pre-feature
    # import shape. Without the baseline, :433 would raise first.
    (bundle / BASELINE_NAME).write_text(
        json.dumps({"top_nodes": 0, "all_nodes": 0, "kind_counts": {},
                    "elements": 0, "media": 0}),
        encoding="utf-8",
    )
    ContentNode.objects.create(course=target, kind="part", title="P0")
    with pytest.raises(CommandError, match="cannot be reconstructed"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "1",
        )


def test_a_torn_state_file_is_tolerated_on_the_discard_branch(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    call_command(                                    # no --start-at: discards it
        "migrate_course_content", "import",
        "--target-slug", "dst", "--bundle-dir", str(bundle),
        "--as-user", "mig@example.com",
    )
    assert _read_state_raw(bundle)["version"] == 1


def test_a_torn_state_file_refuses_on_the_resume_branch(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0])          # baseline + one committed part
    (bundle / LINK_STATE_NAME).write_text('{"version": 1, "par', encoding="utf-8")
    with pytest.raises(CommandError, match="not valid JSON"):
        call_command(
            "migrate_course_content", "import",
            "--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com", "--start-at", "1",
        )


def test_src_drift_refuses_after_a_re_export_from_an_edited_source(tmp_path):
    """A sibling REORDER inside an ALREADY-RECORDED part. Export ids are
    per-archive positional, so editing an ungrafted part leaves every recorded
    part's src byte-identical and the guard correctly does not fire -- which
    would make this test vacuous. Reordering top-level parts changes archive
    names, not intra-part export ids, so that would be vacuous too."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import", "--target-slug", "dst",
        "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
        "--start-at", "0",
    )
    src = Course.objects.get(slug="src")
    p0 = ContentNode.objects.get(course=src, title="P0")
    ContentNode.objects.create(course=src, kind="chapter", title="extra", parent=p0)
    call_command(
        "migrate_course_content", "export", "--source-slug", "src",
        "--bundle-dir", str(bundle), "--clean",
    )
    with pytest.raises(CommandError, match="re-exported"):
        call_command(
            "migrate_course_content", "import", "--target-slug", "dst",
            "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
            "--start-at", "3",
        )


def test_dry_run_leaves_an_existing_state_file_byte_identical(tmp_path):
    """--force names step 3's write path. A bare `import --dry-run` over a
    bundle whose parts are committed hits :401 first (which fires regardless of
    dry_run, since :408's gate is downstream) and would pass on the wrong error."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command(
        "migrate_course_content", "import", "--target-slug", "dst",
        "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
    )
    before = (bundle / LINK_STATE_NAME).read_bytes()
    call_command(
        "migrate_course_content", "import", "--target-slug", "dst",
        "--bundle-dir", str(bundle), "--as-user", "mig@example.com",
        "--dry-run", "--force",
    )
    assert (bundle / LINK_STATE_NAME).read_bytes() == before
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "target_pk or renamed or subset_guard or no_longer_on_disk or torn_state or src_drift or byte_identical or reconstructed" -q
```
Expected: FAIL.

- [ ] **Step 3: Implement**

Add the two gate helpers next to `_capture_baseline`:

```python
    def _check_identity(self, state, target):
        """Which target database these pks belong to. Without it a resume
        against the wrong course is not refused -- the pass's course=target
        liveness filter simply finds nothing live, and (but for the fatal skip
        rule) that is a whole-scope flatten. target_pk is authoritative;
        target_slug only names the course in messages, so a rename is a note."""
        if "target_pk" not in state:
            raise CommandError(
                f"{LINK_STATE_NAME} in this bundle has no 'target_pk': it was "
                f"written by a pre-feature import. Re-run `import` from the "
                f"start against a clean target."
            )
        if state["target_pk"] != target.pk:
            raise CommandError(
                f"{LINK_STATE_NAME} records target pk {state['target_pk']} "
                f"({state.get('target_slug')!r}), but --target-slug resolved to "
                f"{target.slug!r} (pk {target.pk}). Refusing to mix targets."
            )
        if state.get("target_slug") != target.slug:
            self.stdout.write(
                f"note: this course was renamed from "
                f"{state.get('target_slug')!r} to {target.slug!r} since the "
                f"import began; continuing on the recorded pk"
            )

    def _check_src_drift(self, state, node_index):
        """Runs BEFORE anything is grafted, not inside the pass. Inside the
        pass it is a post-mortem: the remaining parts are all committed from
        the NEW archives first, and only then does it raise.

        Compares SOURCE PKS, not export-id sets. Export ids are positional and
        _create_nodes keys node_map by every document node, so both sides are
        always exactly {n1..nK} for a part of K nodes -- a set comparison
        returns True no matter what those ids now denote, and a sibling reorder
        re-labels both nodes while preserving the set.
        """
        for entry in state["parts"]:
            order = int(entry["order"])
            expected = _invert_node_index(node_index, order)
            recorded = {eid: int(pk) for eid, pk in entry.get("src", {}).items()}
            if recorded != expected:
                raise CommandError(
                    f"{LINK_STATE_NAME} disagrees with {MANIFEST_NAME} about "
                    f"part {order}: the bundle was re-exported from a changed "
                    f"source after that part was grafted, so the recorded "
                    f"export-id map no longer describes it. Re-run `import` "
                    f"from the start against a clean target."
                )
```

Then restructure `_import`'s branch. Replace the Task 5 placeholder with the real ordering:

```python
        start_at = o.get("start_at")
        resolve = o.get("resolve_rewrite")          # Task 9 adds the flag
        baseline_path = bundle / BASELINE_NAME

        # STEP 1. Validate unless this invocation discards the file wholesale.
        # --start-at is fatal alongside --resolve-rewrite, so `start_at is None`
        # is ALWAYS true on a resolve invocation -- a naive exemption would skip
        # validation on every one of them, and step 2 returns before step 3 ever
        # discards anything.
        state = _read_state(
            bundle, validate=not (start_at is None and resolve is None)
        )

        # STEP 2. --resolve-rewrite is terminal. Identity FIRST, so a wrong
        # --target-slug cannot flip the file and destroy the only record of
        # whether the real target's rewrite ran.
        if resolve is not None:
            if state is None:
                raise CommandError(
                    f"{LINK_STATE_NAME} is missing from {bundle}; there is no "
                    f"rewrite state to resolve"
                )
            self._check_identity(state, target)
            return self._resolve_rewrite(o, bundle, state, node_index, target)

        if start_at is None:
            baseline = self._capture_baseline(target)
            existing = baseline["top_nodes"]
            if existing and not o.get("force"):
                raise CommandError(...)                    # unchanged :401
            todo = ordered
            if not o.get("dry_run"):
                baseline_path.write_text(...)              # unchanged :409
                # STEP 3. Behind :401 AND behind the dry-run gate. Before :401,
                # a plain re-run after a crash would wipe `parts` to [] and THEN
                # raise "target already has N top-level node(s)" -- consuming an
                # unrecoverable map on an invocation that does nothing else.
                state = _fresh_state(target)
                _write_state(bundle, state)
            elif state is None:
                state = _fresh_state(target)               # in-memory only
        else:
            ... # baseline reuse, unchanged :419-427
            existing = ContentNode.objects.filter(
                course=target, parent__isnull=True
            ).count()
            expected_existing = baseline["top_nodes"] + start_at
            if existing != expected_existing:
                raise CommandError(...)                    # unchanged :433

            # STEP 4. All five gates, in this order, AFTER :429-439.
            # `or not state.get("parts")` is the spec's second half: a file
            # present but with parts: [] is the same pre-feature situation, and
            # must give the same message rather than the subset guard's.
            if state is None or not state.get("parts"):
                if start_at == 0:
                    state = _fresh_state(target)
                    if not o.get("dry_run"):
                        _write_state(bundle, state)
                else:
                    raise CommandError(
                        f"{LINK_STATE_NAME} is missing from {bundle}, but "
                        f"--start-at {start_at} says {start_at} part(s) are "
                        f"already committed. That import began before "
                        f"internal-link support, so its export_id -> new_pk map "
                        f"cannot be reconstructed -- export ids exist nowhere "
                        f"else. Re-run `import` from the start against a clean "
                        f"target."
                    )
            else:
                self._check_identity(state, target)                       # 1
                if state["status"] == "in_progress":                      # 2
                    raise CommandError(self._in_progress_message(bundle, state, target))
                recorded = {int(e["order"]) for e in state["parts"]}
                on_disk = {order for order, _p in ordered}
                missing = {x for x in on_disk if x < start_at} - recorded  # 3
                if missing:
                    raise CommandError(
                        f"--start-at {start_at} expects part(s) "
                        f"{sorted(missing)} to be committed, but "
                        f"{LINK_STATE_NAME} does not record them. Proceeding "
                        f"would flatten every link into them."
                    )
                extra = recorded - on_disk                                # 4
                if extra:
                    raise CommandError(
                        f"{LINK_STATE_NAME} records part(s) {sorted(extra)} as "
                        f"grafted, but {bundle} no longer holds their "
                        f"archive(s). The bundle was re-exported with parts "
                        f"removed; re-run `import` from the start."
                    )
                self._check_src_drift(state, node_index)                  # 5

            todo = [(order, path) for order, path in ordered if order >= start_at]
            ...  # baseline write and the `not todo` early return -- Task 8 edits this
```

`_in_progress_message` is a stub returning a plain string for now; **Task 11** gives it the probe
reading.

Note the subset guard is a **set** operation against archive orders on disk. Never
`max(recorded) + 1`: `recorded` can be empty and `max(())` raises a bare `ValueError`, not a
`CommandError` — and its string keys would sort lexicographically.

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS, whole file.

- [ ] **Step 5: Falsify**

- Replace the subset guard with `max(recorded) + 1 <= start_at`;
  `test_the_subset_guard_is_not_lexicographic` must go RED.
- Delete the `extra` check; `test_resume_refuses_when_the_state_records_orders_no_longer_on_disk`
  must go RED.
- Change `_check_identity`'s missing-key branch to adopt the resolved target
  (`state["target_pk"] = target.pk`); `test_resume_refuses_a_state_file_missing_target_pk` must go
  RED.
- Move the `state = _fresh_state(target)` write above the `:401` guard;
  `test_dry_run_leaves_an_existing_state_file_byte_identical` must go RED.

Restore all four.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): order the import gates and refuse an inconsistent link state"
```

---

### Task 7: The deferred pass — mapping, fatal skips, fail-closed probe, rewrite, counts

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: `_live_pks`, `_invert_node_index`, `_write_state`, part 2's `rewrite_instance`,
  `rewrite_links`, `find_link_targets`, `iter_rich_text`.
- Produces:
  - `_is_fail_closed(instance) -> bool`
  - `_build_mapping(state, node_index, target) -> (mapping, scope_pks, order_by_new_pk, scanned_orders)` — raises `CommandError` on any nonzero skip counter
  - `_merge_rewrite(prior, per_order, fail_closed, all_orders) -> dict`
  - `Command._run_link_pass(bundle, state, node_index, target) -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_is_fail_closed_separates_the_three_cases():
    """The naive `not changed` rule is catastrophically wrong: a body with NO
    links returns exactly the same signal as a fail-closed one, so it would
    record nearly every element and make verify's reconciliation vacuous."""
    from courses.models import TextElement

    plain = TextElement(body="<p>no links here</p>")
    good = TextElement(body='<p><a href="/courses/n/7/">x</a></p>')
    torn = TextElement(body='<p><a href="/courses/n/7/">x</p>')     # no </a>
    assert _is_fail_closed(plain) is False
    assert _is_fail_closed(good) is False
    assert _is_fail_closed(torn) is True


def test_build_mapping_covers_every_order_but_scopes_to_pending():
    """Two sets, never one. The rewrite's SCOPE is pending-only; the mapping's
    LIVENESS filter is every recorded order, because a pending part's links may
    point into an already-rewritten one."""
    target = _mk_target()
    nodes = [ContentNode.objects.create(course=target, kind="part", title=f"N{i}")
             for i in range(3)]
    state = _fresh_state(target)
    state["parts"] = [
        {"order": 0, "node_map": {"n1": nodes[0].pk, "n2": nodes[1].pk},
         "src": {}, "rewritten": True},
        {"order": 1, "node_map": {"n1": nodes[2].pk}, "src": {}, "rewritten": False},
    ]
    node_index = {"1234": [0, "n1"], "1235": [0, "n2"], "9001": [1, "n1"]}
    mapping, scope_pks, _attr, scanned = _build_mapping(state, node_index, target)
    assert mapping == {1234: nodes[0].pk, 1235: nodes[1].pk, 9001: nodes[2].pk}
    assert scope_pks == {nodes[2].pk}          # pending only
    assert scanned == {1}


def test_build_mapping_is_fatal_when_a_recorded_pk_is_not_live():
    """Not a warning. Under on_missing='unwrap' an entry that contributes no
    mapping is not inert -- every href to it is flattened irreversibly."""
    target = _mk_target()
    state = _fresh_state(target)
    state["parts"] = [
        {"order": 0, "node_map": {"n1": 10**9}, "src": {}, "rewritten": False}
    ]
    with pytest.raises(CommandError, match="skipped_dead"):
        _build_mapping(state, {"1": [0, "n1"]}, target)


def test_build_mapping_is_fatal_on_an_unrecorded_order_or_export_id():
    target = _mk_target()
    node = ContentNode.objects.create(course=target, kind="part", title="N")
    state = _fresh_state(target)
    state["parts"] = [
        {"order": 0, "node_map": {"n1": node.pk}, "src": {}, "rewritten": False}
    ]
    with pytest.raises(CommandError, match="skipped_parts"):
        _build_mapping(state, {"1": [5, "n1"]}, target)
    with pytest.raises(CommandError, match="skipped_ids"):
        _build_mapping(state, {"1": [0, "nZZ"]}, target)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "fail_closed or build_mapping" -q
```
Expected: FAIL — names not importable.

- [ ] **Step 3: Implement**

Add the part 2 imports at the top of the command module:

```python
from courses.richtext import find_link_targets
from courses.richtext import iter_rich_text
from courses.richtext import rewrite_instance
from courses.richtext import rewrite_links
```

Then the helpers:

```python
def _is_fail_closed(instance):
    """True iff part 2 declines to touch a body that demonstrably holds link
    targets.

    Part 2's return types carry no fail-closed flag and part 3 does not widen
    them, so this is a decidable probe rather than an observation. `not changed`
    is NOT a substitute: a body with no internal links returns exactly the same
    signal, so that rule would record most of the 20,054 elements and make
    verify's reconciliation permanently vacuous.

    Under an empty map with on_missing="unwrap" every target in a well-formed
    body is flattened; a body that holds targets and still comes back
    byte-identical with flattened == 0 is exactly part 2's fail-closed path.
    """
    for _field, value in iter_rich_text(instance):
        if not find_link_targets(value):
            continue
        probed, flattened = rewrite_links(value, {}, on_missing="unwrap")
        if probed == value and flattened == 0:
            return True
    return False


def _build_mapping(state, node_index, target):
    """(mapping, scope_pks, order_by_new_pk, scanned_orders).

    TWO pk sets, never one. Conflating them drops every node in an
    already-rewritten order from the mapping, so a link from a re-grafted part
    into an earlier one is unmapped and unwrap flattens it -- and the drop is a
    bare `continue`, so all three counters report 0 and the fatal gate below
    never fires.
    """
    pending_entries = [e for e in state["parts"] if not e["rewritten"]]
    scanned_orders = {int(e["order"]) for e in pending_entries}

    # LIVENESS for the MAPPING: every recorded order.
    live = _live_pks(state["parts"], target)
    all_recorded = {pk for e in state["parts"] for pk in e["node_map"].values()}
    skipped_dead = sorted(all_recorded - live)
    # SCOPE of the rewrite: pending orders only. _live_pks already filters, and
    # pending is a subset of all, so no further intersection is needed.
    scope_pks = _live_pks(pending_entries, target)

    by_order = {int(e["order"]): e["node_map"] for e in state["parts"]}
    order_by_new_pk = {pk: o for o, nm in by_order.items() for pk in nm.values()}

    skipped_parts, skipped_ids, mapping = [], [], {}
    for old_pk_str, pair in node_index.items():
        order, export_id = tuple(pair)
        part = by_order.get(int(order))
        if part is None:
            skipped_parts.append(int(order))
            continue
        new_pk = part.get(export_id)
        if new_pk is None:
            skipped_ids.append((int(order), export_id))
            continue
        if new_pk not in live:          # already counted in skipped_dead
            continue
        mapping[int(old_pk_str)] = new_pk

    if skipped_parts or skipped_ids or skipped_dead:
        # FATAL, before the transaction and before status flips to in_progress.
        # None of the three is reachable on a healthy migration, and each one
        # means hrefs would be unwrap-flattened irreversibly. Counted in full so
        # the message can name every offender rather than failing on the first.
        raise CommandError(
            f"refusing to run the deferred link rewrite: the bundle and "
            f"{LINK_STATE_NAME} disagree. "
            f"skipped_parts={sorted(set(skipped_parts))} "
            f"skipped_ids={sorted(set(skipped_ids))} "
            f"skipped_dead={skipped_dead}. Every one of these would flatten "
            f"links irreversibly; nothing has been changed."
        )
    return mapping, scope_pks, order_by_new_pk, scanned_orders


def _merge_rewrite(prior, per_order, fail_closed, all_orders):
    """A pass scans only the pending orders, so it REPLACES their rows and
    CARRIES the rest forward. Overwriting the whole object would discard the
    fail_closed_elements of orders it did not scan, and verify would then read
    a previously-recorded fail-closed element as an ordinary dangling one and
    raise with no remedy reachable."""
    # Capture emptiness BEFORE the pop: a {"resolved_by_operator": True} object
    # is NOT a first pass, and popping first would make it look like one.
    first_pass = not prior
    prior = dict(prior or {})
    prior.pop("resolved_by_operator", None)
    rows = {int(r["order"]): r for r in prior.get("parts", [])}
    for order, counts in per_order.items():
        rows[order] = {"order": order, **counts}
    for order in all_orders:
        rows.setdefault(
            order, {"order": order, "elements_touched": None, "flattened": None}
        )
    parts = [rows[o] for o in sorted(rows)]

    merged = {"parts": parts}
    if all(r["elements_touched"] is not None for r in parts):
        merged["elements_touched"] = sum(r["elements_touched"] for r in parts)
        merged["flattened"] = sum(r["flattened"] for r in parts)
    else:
        merged["elements_touched"] = None
        merged["flattened"] = None
    # Unioned ONLY when the prior object actually had the key; OMITTED entirely
    # when it did not. An incomplete list is worse than an absent one, because
    # verify recomputes live on absence but TRUSTS a present list -- so emitting
    # this pass's findings alone after a --resolve-rewrite applied (which writes
    # no such key) would drop a previously-recorded element and make verify raise
    # with status == "applied" and no remedy reachable.
    #
    # `first_pass` is the genuinely-first pass: nothing has been recorded yet, so
    # this pass's findings ARE complete and the key is safe to write.
    if "fail_closed_elements" in prior:
        union = set(prior["fail_closed_elements"]) | set(fail_closed)
    elif first_pass:
        union = set(fail_closed)
    else:
        return merged                       # key stays ABSENT -> verify recomputes
    # Drop entries whose Element rows no longer exist, or a delete-and-re-graft
    # cycle accumulates dead pks in this list forever (spec Counts).
    merged["fail_closed_elements"] = sorted(
        Element.objects.filter(pk__in=union).values_list("pk", flat=True)
    )
    return merged
```

And the pass itself, as a `Command` method:

```python
    def _run_link_pass(self, bundle, state, node_index, target):
        self._check_src_drift(state, node_index)      # redundant assertion here
        mapping, scope_pks, order_by_new_pk, scanned_orders = _build_mapping(
            state, node_index, target
        )
        per_order = {
            o: {"elements_touched": 0, "flattened": 0} for o in scanned_orders
        }
        fail_closed = []

        # Marker BEFORE the transaction: a crash between the DB commit and the
        # file write would otherwise leave fully rewritten content with no
        # marker, and the trigger would re-apply an old-source-pk map over hrefs
        # that now hold target pks -- the silent mis-point nothing can detect.
        state["status"] = "in_progress"
        _write_state(bundle, state)

        with transaction.atomic():
            qs = (
                Element.objects.filter(unit_id__in=scope_pks)
                .order_by("pk")
                .prefetch_related("content_object")
            )
            # chunk_size is MANDATORY after prefetch_related on Django 5.2:
            # iterator() raises ValueError without it. The value is a tuning
            # constant; passing one at all is not.
            for join in qs.iterator(chunk_size=500):
                obj = join.content_object
                if obj is None:                      # dangling GFK
                    continue
                if _is_fail_closed(obj):
                    # Record, AND STILL REWRITE: the probe is per-instance, and
                    # the instance's other fields may hold mappable hrefs. Part 2
                    # returns the fail-closed field byte-identical on its own.
                    fail_closed.append(join.pk)
                changed, flattened = rewrite_instance(
                    obj, mapping, on_missing="unwrap"
                )
                if changed:
                    obj.save(update_fields=changed)
                order = order_by_new_pk[join.unit_id]
                if changed:
                    per_order[order]["elements_touched"] += 1
                per_order[order]["flattened"] += flattened

        for entry in state["parts"]:
            entry["rewritten"] = True
        state["status"] = "applied"
        state["rewrite"] = _merge_rewrite(
            state.get("rewrite"),
            per_order,
            fail_closed,
            {int(e["order"]) for e in state["parts"]},
        )
        _write_state(bundle, state)

        for row in state["rewrite"]["parts"]:
            self.stdout.write(
                f"part {row['order']}: {row['elements_touched']} element(s) "
                f"rewritten, {row['flattened']} link(s) flattened"
            )
        # BOTH lookups must tolerate absence: _merge_rewrite omits
        # fail_closed_elements when the prior object lacked it, and nulls the
        # totals when any carried-forward row has unknown counts. Reached by the
        # resolve-applied-then-repair-resume path.
        rw = state["rewrite"]
        fc = rw.get("fail_closed_elements")
        self.stdout.write(
            f"deferred link rewrite applied: "
            f"{rw['elements_touched'] if rw['elements_touched'] is not None else 'unknown'} "
            f"element(s) touched, "
            f"{rw['flattened'] if rw['flattened'] is not None else 'unknown'} "
            f"link(s) flattened, "
            f"{len(fc) if fc is not None else 'unknown'} body(ies) left "
            f"untouched by the scanner"
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS.

- [ ] **Step 5: Falsify**

- Change `_is_fail_closed` to `return not find_link_targets(value)`;
  `test_is_fail_closed_separates_the_three_cases` must go RED on the `plain` case.
- Build the mapping's liveness set from `pending_entries` instead of `state["parts"]`;
  `test_build_mapping_covers_every_order_but_scopes_to_pending` must go RED with a one-entry
  mapping.
- Turn the three-counter `raise` into a `self.stdout.write`; both fatal tests must go RED.

Restore all three.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): build the deferred link map and run the single rewrite pass"
```

---

### Task 8: Trigger wiring — two sites, two predicates

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py:445-508`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: Task 7's `_run_link_pass`.
- Produces: the pass firing automatically on both the fresh and resume paths.

**The two predicates are different and conflating them breaks the feature in one direction or
destroys data in the other:**

```
pending_orders = {int(e["order"]) for e in state["parts"] if not e["rewritten"]}

site 1 — immediately before the `if not todo:` at :445, resume branch only:
    not todo and recorded == on_disk and state["status"] == "collecting" and pending_orders

site 2 — after the graft loop, both branches:
    recorded == on_disk and state["status"] == "collecting" and pending_orders
```

- [ ] **Step 1: Write the failing tests**

```python
def _link_between(course, from_title, to_title):
    """Give the unit under `from_title` a text element linking to `to_title`'s
    unit. Returns the target node's pk."""
    src_unit = ContentNode.objects.get(course=course, title=f"U{from_title[-1]}")
    dst_unit = ContentNode.objects.get(course=course, title=f"U{to_title[-1]}")
    Element.objects.create(
        unit=src_unit,
        title="L",
        content_object=TextElement.objects.create(
            body=f'<p><a href="/courses/n/{dst_unit.pk}/">go</a></p>'
        ),
    )
    return dst_unit.pk


def test_a_full_import_rewrites_cross_part_and_intra_part_links(tmp_path):
    """The headline case. The intra-part link is NOT padding: it is what catches
    a rewrite-per-part-then-finish design, under which the final old-pk-keyed
    pass would flatten every within-part link in the course. A cross-part-only
    fixture passes that broken design.

    This is also site 2's falsification: add `not todo` to site 2 and this goes
    RED, because the loop never empties `todo`."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")          # cross-part
    _link_between(course, "P0", "P0")          # intra-part
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")

    new_u0 = ContentNode.objects.get(course=target, title="U0")
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies      # cross-part -> NEW pk
    assert f"/courses/n/{new_u0.pk}/" in bodies      # intra-part -> NEW pk
    assert _read_state_raw(bundle)["status"] == "applied"


def test_the_pass_survives_an_interrupted_import_resumed_with_start_at(tmp_path):
    """What pins the state to a file rather than memory."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    # `--start-at 0` grafts BOTH parts, so simulate the interruption by removing
    # the second one. Resuming at 1 with 2 top-level nodes present would fail
    # :433 (expected baseline + 1, holds 2) before reaching anything under test.
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P1"
    ).delete()
    st = _read_state_raw(bundle)
    st["parts"] = [e for e in st["parts"] if int(e["order"]) != 1]
    st["status"] = "collecting"
    for e in st["parts"]:
        e["rewritten"] = False
    st.pop("rewrite", None)
    _write_state(bundle, st)
    # A second process. The map for part 0 must have survived on disk.
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


def test_the_skipped_pass_window_still_applies_on_a_start_at_resume(tmp_path):
    """A run that dies after the last part commits, resumed with
    --start-at part_count, must still rewrite. Site 1 is the only place that
    can fire here, because the loop body never runs."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    # Simulate the crash: parts committed, pass never ran.
    st = _read_state_raw(bundle)
    st["status"] = "collecting"
    for e in st["parts"]:
        e["rewritten"] = False
    st.pop("rewrite", None)
    _write_state(bundle, st)
    call_command("migrate_course_content", "import", *args, "--start-at", "2")
    assert _read_state_raw(bundle)["status"] == "applied"


def test_a_completed_migration_re_invoked_does_not_re_run_the_pass(tmp_path):
    """The once-only guard, and the existing 'nothing to do' line must survive."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    before = _read_state_raw(bundle)["rewrite"]
    out = io.StringIO()
    call_command("migrate_course_content", "import", *args,
                 "--start-at", "3", stdout=out)
    assert _read_state_raw(bundle)["rewrite"] == before
    assert "already complete" in out.getvalue()


def test_a_link_with_no_target_in_any_part_is_flattened_and_counted(tmp_path):
    course = _mk_source(parts=("P0",))
    unit = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=unit, title="L",
        content_object=TextElement.objects.create(
            body='<p><a href="/courses/n/999999/">gone</a></p>'
        ),
    )
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    out = io.StringIO()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com", stdout=out)
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert "/courses/n/999999/" not in bodies
    assert "gone" in bodies                      # unwrapped to plain text
    assert _read_state_raw(bundle)["rewrite"]["flattened"] >= 1
    assert "flattened" in out.getvalue()
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "cross_part_and_intra_part or interrupted_import or skipped_pass_window or does_not_re_run or no_target_in_any_part" -q
```
Expected: FAIL — the pass never fires.

- [ ] **Step 3: Implement**

Add a predicate helper and wire both sites:

```python
    def _should_run_pass(self, state, ordered, *, todo=None):
        """`todo` is passed ONLY at site 1. Site 2 must not carry it: `todo` is
        a list the graft loop iterates but never empties, so `not todo` is False
        after any run that grafted anything -- and the `start_at is None` branch
        has no other trigger site, which would make the whole feature inert on
        the primary invocation.

        At site 1 the conjunct is required for the opposite reason: without it
        the pass fires while parts are still ungrafted (the stale-entry window
        at the last part), aborting on skipped_dead and stalling the migration.
        """
        if todo is not None and todo:
            return False
        recorded = {int(e["order"]) for e in state["parts"]}
        on_disk = {order for order, _p in ordered}
        pending_orders = {
            int(e["order"]) for e in state["parts"] if not e["rewritten"]
        }
        return (
            recorded == on_disk
            and state["status"] == "collecting"
            and bool(pending_orders)
        )
```

Site 1, immediately before the existing `if not todo:` at `:445`:

```python
            fired_here = False
            if not o.get("dry_run") and self._should_run_pass(
                state, ordered, todo=todo
            ):
                self.stdout.write(
                    "no parts left to graft; applying the deferred link rewrite"
                )
                self._run_link_pass(bundle, state, node_index, target)
                fired_here = True
            if not todo:
                if not fired_here:
                    self.stdout.write(
                        f"nothing to do: --start-at {start_at} is at or beyond "
                        f"the bundle's {len(archives)} part(s); this migration "
                        f"is already complete"
                    )
                return
```

The existing message must be printed **only when the pass did not fire there** —
`test_start_at_beyond_all_parts_reports_nothing_to_do` asserts that string and must keep passing.

Site 2, after the graft loop, before the closing stdout at `:505`:

```python
        if not o.get("dry_run") and self._should_run_pass(state, ordered):
            self._run_link_pass(bundle, state, node_index, target)
        elif not o.get("dry_run") and state["status"] != "applied":
            # Backstop: never end `import` silently without the pass having run.
            self.stdout.write(
                f"note: the deferred link rewrite did not run "
                f"(status={state['status']!r}); run `verify` to see why"
            )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS, whole file.

- [ ] **Step 5: Falsify**

Pass `todo=todo` at **site 2** as well. `test_a_full_import_rewrites_cross_part_and_intra_part_links`
must go RED (`status` stays `collecting`, hrefs keep source pks). Restore.

Then delete `todo=todo` from **site 1** and re-run
`test_the_skipped_pass_window_still_applies_on_a_start_at_resume` — site 1 must not fire while
`todo` is non-empty. Restore.

**Deferred falsification.** Site 1's other guard —
`test_the_stale_entry_resume_grafts_first_and_rewrites_after` — is written in Task 12. Do not skip
it: Task 12 Step 3 re-runs it against this same `todo=todo` deletion, and it is the case that
catches the stalled-migration outcome.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): fire the deferred link rewrite from both trigger sites"
```

---

### Task 9: `--resolve-rewrite`

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py` (`add_arguments`, `_ACTION_FLAGS`, `_FLAG_UNSET`, `_import`)
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: Task 7's `_run_link_pass`, Task 6's `_check_identity`.
- Produces: `Command._resolve_rewrite(o, bundle, state, node_index, target)`, terminal.

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_rewrite_not_applied_runs_the_pass_in_one_invocation(tmp_path):
    """ONE invocation, not two: no --start-at value both clears :433 and empties
    todo under non-contiguous orders, so a flip-then-resume form has no working
    argument."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    # Simulate the crash window: marker set, pass never committed.
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)

    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com",
                 "--resolve-rewrite", "not-applied")
    assert _read_state_raw(bundle)["status"] == "applied"


def test_resolve_rewrite_applied_sets_every_per_entry_flag(tmp_path):
    """status == 'applied' <=> no entry has rewritten == false. Flipping only
    status leaves every entry false, and the documented repair resume then makes
    pending == every order, re-applying an old-source-pk map over hrefs that
    already hold target pks."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    # The completed pass already set every flag True, so leaving them would make
    # the assertion below hold whether or not the `applied` arm sets them --
    # i.e. the falsification could not go RED. The spec's scenario is precisely
    # "flipping only status leaves every entry FALSE".
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com",
                 "--resolve-rewrite", "applied")
    after = _read_state_raw(bundle)
    assert after["status"] == "applied"
    assert all(e["rewritten"] for e in after["parts"])
    assert after["rewrite"]["resolved_by_operator"] is True


def test_resolve_rewrite_applied_then_a_repair_resume_leaves_bodies_alone(tmp_path):
    """The consequence the per-entry flags exist to prevent: with only `status`
    flipped, a repair resume makes pending == every order and the pass re-applies
    an old-SOURCE-pk map over hrefs that already hold TARGET pks."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P0")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    call_command("migrate_course_content", "import", *args,
                 "--resolve-rewrite", "applied")
    p0_before = sorted(
        TextElement.objects.filter(
            elements__unit__parent__parent__title="P0",
            elements__unit__course=target,
        ).values_list("body", flat=True)
    )
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P1"
    ).delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    assert sorted(
        TextElement.objects.filter(
            elements__unit__parent__parent__title="P0",
            elements__unit__course=target,
        ).values_list("body", flat=True)
    ) == p0_before


def test_resolve_rewrite_refuses_a_wrong_target_before_mutating(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    Course.objects.create(title="Other", slug="other", uses_parts=True)
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    _write_state(bundle, st)
    before = (bundle / LINK_STATE_NAME).read_bytes()
    with pytest.raises(CommandError, match="Refusing to mix targets"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "other", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com",
                     "--resolve-rewrite", "applied")
    assert (bundle / LINK_STATE_NAME).read_bytes() == before


def test_resolve_rewrite_applied_refuses_a_collecting_file(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2])
    with pytest.raises(CommandError, match="only meaningful on an in_progress"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com",
                     "--resolve-rewrite", "applied")


def test_resolve_rewrite_requires_as_user(tmp_path):
    """Pins the documented invocation against the real required-argument gate
    rather than the spec's prose: --as-user is checked unconditionally at :371,
    before the pinned handling point."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    with pytest.raises(CommandError, match="requires --as-user"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--resolve-rewrite", "not-applied")


@pytest.mark.parametrize("extra", [("--start-at", "0"), ("--force",), ("--dry-run",)])
def test_resolve_rewrite_refuses_conflicting_flags(tmp_path, extra):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    _seed_state(bundle, target, [0, 1, 2], status="in_progress")
    with pytest.raises(CommandError, match="cannot be combined with"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com",
                     "--resolve-rewrite", "not-applied", *extra)


def test_resolve_rewrite_not_applied_accepts_a_complete_collecting_file(tmp_path):
    """The second disjunct of the acceptance rule, and the ONLY test of it.

    It exists because site 1 is provably unreachable under non-contiguous orders
    -- there is no --start-at value that both clears :433 and empties todo -- so
    without this arm such a bundle can never reach the pass. Falsify by deleting
    the `collecting` disjunct: this goes RED while every other test stays green.
    """
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    # Wind back to collecting-with-everything-recorded: the skipped-pass shape.
    st = _read_state_raw(bundle)
    st["status"] = "collecting"
    for e in st["parts"]:
        e["rewritten"] = False
    st.pop("rewrite", None)
    _write_state(bundle, st)

    call_command("migrate_course_content", "import", *args,
                 "--resolve-rewrite", "not-applied")
    assert _read_state_raw(bundle)["status"] == "applied"
    new_u1 = ContentNode.objects.get(course=target, title="U1")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u1.pk}/" in bodies


@pytest.mark.parametrize("arm", ["applied", "not-applied"])
@pytest.mark.parametrize(
    "raw, match",
    [('{"version": 1, "par', "not valid JSON"), ('{"version": 2}', "version")],
)
def test_resolve_rewrite_validates_the_state_file(tmp_path, arm, raw, match):
    """Step 1's validate expression is `not (start_at is None and resolve is
    None)`, not a plain `start_at is None`. --start-at is fatal alongside
    --resolve-rewrite, so start_at is ALWAYS None here -- a naive exemption would
    skip validation on every resolve invocation, and step 2 returns before step 3
    ever discards anything. Falsify by simplifying the expression: all four of
    these go RED."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    (bundle / LINK_STATE_NAME).write_text(raw, encoding="utf-8")
    with pytest.raises(CommandError, match=match):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com",
                     "--resolve-rewrite", arm)


def test_export_rejects_resolve_rewrite(tmp_path):
    """The flag matrix. Omitting it from _ACTION_FLAGS lets export silently
    accept and ignore it; adding it there but not to _FLAG_UNSET makes
    _reject_foreign_flags raise a raw KeyError on every export and verify."""
    _mk_source()
    with pytest.raises(CommandError, match="not valid for the 'export' action"):
        call_command("migrate_course_content", "export",
                     "--source-slug", "src",
                     "--bundle-dir", str(tmp_path / "b"),
                     "--resolve-rewrite", "applied")


def test_verify_does_not_keyerror_on_the_new_flag(tmp_path):
    """_FLAG_UNSET lookup happens for EVERY foreign flag on every action."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    call_command("migrate_course_content", "verify",
                 "--target-slug", "dst", "--bundle-dir", str(bundle))
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "resolve_rewrite or keyerror_on_the_new_flag" -q
```
Expected: FAIL — unrecognised argument.

- [ ] **Step 3: Implement**

Register the flag in `add_arguments`:

```python
        parser.add_argument(
            "--resolve-rewrite",
            choices=("applied", "not-applied"),
            help="import only: break the in_progress deadlock left by a crash "
            "during the deferred link rewrite. 'applied' records that the "
            "rewrite committed; 'not-applied' runs it now. The command prints "
            "a probe reading to inform the choice; it never guesses.",
        )
```

Both matrix entries — **both are needed**:

```python
_ACTION_FLAGS = {
    "export": {"allow_problems", "clean"},
    "import": {"as_user", "dry_run", "force", "start_at", "resolve_rewrite"},
    "verify": set(),
}

_FLAG_UNSET = {
    "allow_problems": False,
    "clean": False,
    "dry_run": False,
    "force": False,
    "as_user": None,
    "start_at": None,
    "resolve_rewrite": None,
}
```

And the terminal action:

```python
    def _resolve_rewrite(self, o, bundle, state, node_index, target):
        """Terminal: mutates only the state file, grafts nothing, returns.

        Handled before the baseline capture and the :401 double-run guard --
        an in_progress file only exists after a complete or nearly-complete
        import, so the natural invocation would otherwise hit :401 and the
        operator would never reach the state file. Following that error's advice
        and adding --force is worse: it re-grafts every part.
        """
        answer = o["resolve_rewrite"]
        for flag, label in (
            ("start_at", "--start-at"),
            ("force", "--force"),
            ("dry_run", "--dry-run"),
        ):
            if o.get(flag) is not _FLAG_UNSET[flag]:
                raise CommandError(
                    f"--resolve-rewrite cannot be combined with {label}: it is "
                    f"a terminal action that grafts nothing, so {label} would "
                    f"be silently ignored."
                )

        recorded = {int(e["order"]) for e in state["parts"]}
        on_disk = {
            self._archive_order(p.name) for p in self._bundle_archives(bundle)
        }
        status = state["status"]
        if answer == "applied":
            if status != "in_progress":
                raise CommandError(
                    f"--resolve-rewrite applied is only meaningful on an "
                    f"in_progress {LINK_STATE_NAME}; this one is {status!r}."
                )
            for entry in state["parts"]:
                entry["rewritten"] = True
            state["status"] = "applied"
            rewrite = dict(state.get("rewrite") or {})
            rewrite["resolved_by_operator"] = True
            state["rewrite"] = rewrite
            _write_state(bundle, state)
            self.stdout.write(
                "recorded the deferred link rewrite as applied on the "
                "operator's word; counts for the resolved parts are unknown"
            )
            return

        if not (status == "in_progress" or (status == "collecting" and recorded == on_disk)):
            raise CommandError(
                f"--resolve-rewrite not-applied needs an in_progress "
                f"{LINK_STATE_NAME}, or a collecting one whose recorded parts "
                f"match the archives on disk; this one is {status!r} with "
                f"recorded={sorted(recorded)} on_disk={sorted(on_disk)}."
            )
        # The `collecting` flip is NOT persisted first: the pass's own gates
        # raise before it writes in_progress, and a persisted `collecting` would
        # leave --resolve-rewrite refused ever after. Leaving the file as-is
        # until the pass succeeds keeps this action re-runnable.
        for entry in state["parts"]:
            entry["rewritten"] = False
        state["status"] = "collecting"
        self._run_link_pass(bundle, state, node_index, target)
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS.

- [ ] **Step 5: Falsify**

- Remove `"resolve_rewrite"` from `_FLAG_UNSET` (leaving it in `_ACTION_FLAGS`);
  `test_verify_does_not_keyerror_on_the_new_flag` must go RED with `KeyError`.
- Remove it from `_ACTION_FLAGS["import"]`; `test_export_rejects_resolve_rewrite` must go RED.
- Delete the per-entry flag loop from the `applied` arm;
  `test_resolve_rewrite_applied_sets_every_per_entry_flag` must go RED.
- Move `self._check_identity(...)` in `_import` to *after* the `_resolve_rewrite` dispatch;
  `test_resolve_rewrite_refuses_a_wrong_target_before_mutating` must go RED.

Restore all four.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): add --resolve-rewrite to break the in_progress deadlock"
```

---

### Task 10: `verify` — state gates, identity, and the link reconciliation

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py:512-615`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: `_live_pks`, `_is_fail_closed`, part 2's `iter_rich_text` / `find_link_targets`.
- Produces: `Command._scan_links(state, target) -> (dangling, dangling_elements, total_elements)`.

**Gate order is pinned** because two existing tests assert on message text:
existing `MANIFEST_NAME` gate (`:522`) → existing `BASELINE_NAME` gate (`:525-535`) → state file
presence / JSON / `version` → **`target_pk` identity** → marker checks → existing archive re-read
and the four tally checks → **link reconciliation last**. A content-level link failure must never
pre-empt a structural one; a missing part is the more actionable report.

- [ ] **Step 1: Write the failing tests**

```python
def test_verify_refuses_when_the_link_state_is_missing(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    (bundle / LINK_STATE_NAME).unlink()
    with pytest.raises(CommandError, match=LINK_STATE_NAME):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "dst", "--bundle-dir", str(bundle))


def test_verify_refuses_a_state_file_that_is_not_applied(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "collecting"
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="deferred link rewrite never ran"):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "dst", "--bundle-dir", str(bundle))


def test_verify_refuses_an_in_progress_state_file(tmp_path):
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    _write_state(bundle, st)
    with pytest.raises(CommandError, match="in_progress"):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "dst", "--bundle-dir", str(bundle))


def test_verify_refuses_the_wrong_target_rather_than_passing_trivially(tmp_path):
    """Without the identity check the scope is empty, so total_elements == 0
    and the reconciliation succeeds having checked nothing."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    Course.objects.create(title="Other", slug="other", uses_parts=True)
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    # match= is mandatory: verifying "other" also trips the pre-existing node
    # tally ("node count mismatch"), so a bare raises() passes with the identity
    # check deleted and the falsification below could never go RED.
    with pytest.raises(CommandError, match="Refusing to mix targets"):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "other", "--bundle-dir", str(bundle))


def test_verify_raises_on_a_dangling_internal_href(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    # MUTATE an existing body -- do NOT add an Element. The pinned gate order
    # puts the four tally checks before the reconciliation, so an extra join
    # raises "element count mismatch: expected 6, target 'dst' holds 7" and the
    # match= never fires. (Measured: sanitize_html leaves this markup
    # byte-identical, so .update() and .save() both work.)
    TextElement.objects.filter(elements__unit__course=target).update(
        body='<p><a href="/courses/n/999999/">x</a></p>'
    )
    with pytest.raises(CommandError, match="dangling"):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "dst", "--bundle-dir", str(bundle))


def test_verify_passes_on_a_clean_migration(tmp_path):
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    out = io.StringIO()
    call_command("migrate_course_content", "verify",
                 "--target-slug", "dst", "--bundle-dir", str(bundle), stdout=out)
    assert "OK" in out.getvalue()
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "verify_refuses_when_the_link_state or not_applied or in_progress_state_file or wrong_target_rather or dangling_internal or passes_on_a_clean" -q
```
Expected: FAIL.

- [ ] **Step 3: Implement**

Add the scan helper:

```python
    def _scan_links(self, state, target):
        """(dangling, dangling_elements, total_elements) over ALL recorded
        orders. Composed from part 2's read-only exports -- none of them returns
        an href, so a reported href is RECONSTRUCTED as /courses/n/<pk>/ from
        the dangling pk, not captured."""
        qs = (
            Element.objects.filter(unit_id__in=_live_pks(state["parts"], target))
            .order_by("pk")
            .prefetch_related("content_object")
        )
        referenced = {}
        total_elements = 0
        for join in qs.iterator(chunk_size=500):
            total_elements += 1
            obj = join.content_object
            if obj is None:
                continue
            for _field, value in iter_rich_text(obj):
                for pk in find_link_targets(value):
                    referenced.setdefault(pk, []).append((join.unit_id, join.pk))

        live_targets = set(                  # NOT `live`: a different set
            ContentNode.objects.filter(
                course=target, pk__in=referenced
            ).values_list("pk", flat=True)
        )
        dangling = {
            pk: sites for pk, sites in referenced.items() if pk not in live_targets
        }
        dangling_elements = {epk for sites in dangling.values() for _u, epk in sites}
        return dangling, dangling_elements, total_elements
```

In `_verify`, after the existing `BASELINE_NAME` block and **before** the archive re-read:

```python
        state = _read_state(bundle, validate=True)
        if state is None:
            raise CommandError(
                f"{LINK_STATE_NAME} is missing from {bundle}; run `import` "
                f"before `verify` so the link rewrite is on record"
            )
        self._check_identity(state, target)
        # A stale entry REPORTS here rather than raising -- unlike in the pass,
        # because `verify` never mutates.
        stale = {
            pk
            for e in state["parts"]
            for pk in e["node_map"].values()
        } - _live_pks(state["parts"], target)
        if stale:
            orders = sorted(
                int(e["order"])
                for e in state["parts"]
                if set(e["node_map"].values()) & stale
            )
            self.stdout.write(
                f"note: {LINK_STATE_NAME} records {len(stale)} node(s) in "
                f"part(s) {orders} that no longer exist in {target.slug!r}"
            )
        if state["status"] == "in_progress":
            raise CommandError(
                f"{LINK_STATE_NAME} in {bundle} is in_progress: a crash left "
                f"the deferred link rewrite in an unknown state. Resolve it "
                f"with `import --resolve-rewrite` before verifying."
            )
        if state["status"] != "applied":
            raise CommandError(
                f"{LINK_STATE_NAME} in {bundle} is {state['status']!r}: the "
                f"deferred link rewrite never ran, so internal links still "
                f"hold source pks. Re-run `import`."
            )
```

And at the very end, after the media tally, the reconciliation:

```python
        rewrite = state.get("rewrite") or {}
        if rewrite.get("resolved_by_operator"):
            self.stdout.write(
                "link rewrite: marked applied by the operator; counts "
                "unavailable"
            )
        for row in rewrite.get("parts", []):
            self.stdout.write(
                f"  part {row['order']}: {row['elements_touched']} rewritten, "
                f"{row['flattened']} flattened"
            )

        dangling, dangling_elements, total_elements = self._scan_links(state, target)
        if "fail_closed_elements" in rewrite:
            fail_closed = set(rewrite["fail_closed_elements"])
        else:
            # Absent, NOT empty. The resolved_by_operator shape has no such key
            # by construction, and treating it as empty would read every
            # fail-closed body as an ordinary dangling element -- with status
            # already applied and --resolve-rewrite refusing a non-in_progress
            # file, verify would then fail forever with no remedy.
            fail_closed = {
                join.pk
                for join in Element.objects.filter(
                    pk__in=dangling_elements
                ).prefetch_related("content_object")
                if join.content_object is not None
                and _is_fail_closed(join.content_object)
            }
        real = dangling_elements - fail_closed
        reported = dangling_elements & fail_closed

        if reported:
            self.stdout.write(
                f"note: {len(reported)} element(s) hold links the scanner "
                f"declines to touch (malformed anchor markup); they keep their "
                f"source pks and need a manual fix"
            )
        if real:
            examples = []
            for pk, sites in sorted(dangling.items()):
                for unit_id, epk in sites:
                    if epk in real:
                        examples.append((unit_id, epk, f"/courses/n/{pk}/"))
                if len(examples) >= 10:
                    break
            raise CommandError(
                f"{len(real)} migrated element(s) hold a dangling internal "
                f"link (of {total_elements} in scope). First {len(examples)}: "
                f"{examples}"
            )
        self.stdout.write(
            f"internal links OK: {total_elements} element(s) in scope, none "
            f"dangling"
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS, whole file. `test_verify_refuses_when_import_was_never_run` (asserting
`match="is missing from"`) and `test_verify_fails_when_a_part_is_missing` (asserting
`match="node count mismatch"`) must both still pass — that is what the gate order protects.

- [ ] **Step 5: Falsify**

- Delete the `self._check_identity(state, target)` line from `_verify`;
  `test_verify_refuses_the_wrong_target_rather_than_passing_trivially` must go RED. (It only can
  because of the `match="Refusing to mix targets"` above — without it the pre-existing node tally
  satisfies a bare `raises()`.)
- The other two falsifications need tests written in Task 12, so they are **deferred to Task 12
  Step 3**, which names them explicitly. Do not skip them: (a) replacing the
  `fail_closed_elements` absence branch with `fail_closed = set()` must turn
  `test_resolve_rewrite_applied_then_verify_recomputes_fail_closed` RED — the **present**-key case
  cannot falsify that branch, only the resolve-applied path reaches it; and (b) moving the link
  reconciliation above the node tally must turn
  `test_verify_reports_a_structural_failure_before_a_link_one` RED. Do **not** use
  `test_verify_fails_when_a_part_is_missing` for this: its `_export_bundle` fixture carries no
  internal links at all, so the hoisted scan finds nothing, the node tally still raises, and the
  falsification is silent.

Restore all three.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): reconcile internal links in verify"
```

---

### Task 11: The `in_progress` probe reading

**Files:**
- Modify: `courses/management/commands/migrate_course_content.py`
- Test: `tests/test_migrate_course_content.py`

**Interfaces:**
- Consumes: Task 10's `_scan_links`, `_is_fail_closed`.
- Produces: `Command._in_progress_message(bundle, state, target) -> str` (replaces Task 6's stub).

- [ ] **Step 1: Write the failing test**

```python
def test_the_in_progress_refusal_prints_a_probe_reading(tmp_path):
    """The reading is the sole discriminator for an irreversible operator
    decision, so both numbers must be present and both must be over the PENDING
    scope -- over all entries the ratio is meaningless on a repair resume."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    with pytest.raises(CommandError) as exc:
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com", "--start-at", "3")
    msg = str(exc.value)
    assert "--resolve-rewrite" in msg
    assert "dangling" in msg
    assert "in the pending scope" in msg
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_migrate_course_content.py -k "probe_reading" -q
```
Expected: FAIL — the stub message has no numbers.

- [ ] **Step 3: Implement**

```python
    def _in_progress_message(self, bundle, state, target):
        """The discriminator. After a committed pass no in-scope element holds
        a dangling internal href; before it, essentially every one does. The
        command reports and refuses -- an automatic guess that lands wrong
        produces exactly the silent mis-point this design exists to prevent.

        Both numbers are over the PENDING scope, because only pending orders
        would be rewritten. Over all entries, one re-grafted part of ~1,000
        elements inside a 20,054-element scope reads as ~5% -- neither near zero
        nor near total -- and 5% pushes the operator toward `applied`, stranding
        the re-grafted part's hrefs on source pks.
        """
        pending = [e for e in state["parts"] if not e["rewritten"]]
        probe = dict(state)
        probe["parts"] = pending
        _dangling, dangling_elements, total = self._scan_links(probe, target)
        fail_closed = {
            join.pk
            for join in Element.objects.filter(
                pk__in=dangling_elements
            ).prefetch_related("content_object")
            if join.content_object is not None
            and _is_fail_closed(join.content_object)
        }
        # Context only: how big the pending scope is relative to the whole
        # migration. Without it, "N of M in scope" on a repair resume hides that
        # M is one part of twenty-one -- the ~5%-vs-~100% misreading the spec
        # warns about.
        migration_total = Element.objects.filter(
            unit_id__in=_live_pks(state["parts"], target)
        ).count()
        return (
            f"{LINK_STATE_NAME} in {bundle} is in_progress: a crash left the "
            f"deferred link rewrite in an unknown state.\n"
            f"  probe: {len(dangling_elements - fail_closed)} element(s) hold a "
            f"dangling internal link, of {total} in the pending scope "
            f"({len(fail_closed)} more are malformed and were never "
            f"rewritable; the whole migration holds {migration_total}).\n"
            f"  near {total} means the rewrite did NOT run  -> re-run with "
            f"--resolve-rewrite not-applied\n"
            f"  near 0 means it DID commit                  -> re-run with "
            f"--resolve-rewrite applied\n"
            f"The command will not guess: a wrong answer silently re-points "
            f"correct links at unrelated nodes."
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS.

- [ ] **Step 5: Falsify**

Extend the test so the scoping is observable, then falsify it:

```python
def test_the_probe_denominator_is_the_pending_scope(tmp_path):
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:                      # only ONE order pending
        e["rewritten"] = int(e["order"]) != 1
    _write_state(bundle, st)
    with pytest.raises(CommandError) as exc:
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com", "--start-at", "3")
    msg = str(exc.value)
    pending_n = int(re.search(r"of (\d+) in the pending scope", msg).group(1))
    whole_n = int(re.search(r"migration holds (\d+)", msg).group(1))
    assert pending_n < whole_n
```

(`import re` belongs in the top-of-file import block, per Task 3's note.) Now change
`probe["parts"] = pending` to `probe["parts"] = state["parts"]` — `pending_n == whole_n` and the
test goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
uv run ruff check courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git add courses/management/commands/migrate_course_content.py tests/test_migrate_course_content.py
git commit -m "feat(migrate): print a probe reading with the in_progress refusal"
```

---

### Task 12: The remaining spec cases, and the full suite

**Files:**
- Modify: `tests/test_migrate_course_content.py`

**Interfaces:** consumes everything above; produces no new production code unless a case fails.

- [ ] **Step 1: Write the remaining cases**

```python
def test_the_repair_resume_rewrites_only_the_re_grafted_part(tmp_path):
    """A tail deletion is the only shape :433 accepts -- deleting a middle part
    gives a red test on the wrong error. Parts BEFORE K must be byte-identical:
    that half is what catches a fix that re-runs the whole pass and re-applies
    an old-pk map over already-rewritten hrefs."""
    course = _mk_source(parts=("P0", "P1", "P2"))
    _link_between(course, "P0", "P0")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    p0_bodies = sorted(
        TextElement.objects.filter(
            elements__unit__parent__parent__title="P0",
            elements__unit__course=target,
        ).values_list("body", flat=True)
    )
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title__in=("P1", "P2")
    ).delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    assert sorted(
        TextElement.objects.filter(
            elements__unit__parent__parent__title="P0",
            elements__unit__course=target,
        ).values_list("body", flat=True)
    ) == p0_bodies
    assert _read_state_raw(bundle)["status"] == "applied"


def test_a_cross_part_link_from_a_re_grafted_part_into_a_rewritten_one(tmp_path):
    """The scope/mapping separation. Falsify by building the mapping's liveness
    set from pending orders only: the link is silently unwrap-flattened while
    all three skip counters report 0."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P1", "P0")          # part 1 -> part 0
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P1"
    ).delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    new_u0 = ContentNode.objects.get(course=target, title="U0")
    bodies = " ".join(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    assert f"/courses/n/{new_u0.pk}/" in bodies


def test_force_leaves_pre_existing_linked_content_untouched(tmp_path):
    """Scoping matters most under --force: pre-existing bodies carry TARGET
    pks, and sweeping them with an old-pk-keyed map would flatten them or, on a
    numeric coincidence, mis-point them."""
    bundle = _export_bundle(tmp_path, parts=("P0",))
    target = _mk_target()
    _user()
    squatter = ContentNode.objects.create(course=target, kind="part", title="Sq")
    ch = ContentNode.objects.create(course=target, kind="chapter",
                                    title="C", parent=squatter)
    unit = ContentNode.objects.create(course=target, kind="unit", title="SqU",
                                      parent=ch, unit_type="lesson")
    body = f'<p><a href="/courses/n/{squatter.pk}/">mine</a></p>'
    Element.objects.create(
        unit=unit, title="pre",
        content_object=TextElement.objects.create(body=body),
    )
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com", "--force")
    assert TextElement.objects.get(elements__unit=unit).body == body


def test_a_fail_closed_body_is_recorded_and_reported_not_fatal(tmp_path):
    """MUST use FillGateElement, not TextElement.

    Measured: TextElement.save() runs sanitize_html (courses/models.py:393), and
        sanitize_html('<p><a href="/courses/n/7/">torn</p>')
        -> '<p><a href="/courses/n/7/">torn</a></p>'
    i.e. the sanitiser CLOSES the anchor, so a TextElement fixture can never be
    fail-closed and the test would assert an empty list. FillGateElement has no
    save() override and _build_fill_gate (importer.py:549-552) stores `stem`
    raw on the import side too -- the spec names it as the only reachable
    vehicle. The stem carries BOTH a torn anchor and a well-formed mappable one,
    which is also the I8 mixed-body case.
    """
    from courses.models import FillGateElement

    course = _mk_source(parts=("P0", "P1"))
    u0 = ContentNode.objects.get(course=course, title="U0")
    u1 = ContentNode.objects.get(course=course, title="U1")
    Element.objects.create(
        unit=u0, title="mixed",
        content_object=FillGateElement.objects.create(
            # SINGLE torn anchor, UNMAPPABLE target, no </a> anywhere after it.
            # A second well-formed anchor would supply the </a> this one's search
            # finds, and a mappable pk never reaches the unwrap branch at all --
            # see MEASURED DIVERGENCE above.
            stem='<p><a href="/courses/n/999999/">torn</p>',
            answers=[["x"]],   # list[list[str]], per the model docstring
        ),
    )
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")

    assert _read_state_raw(bundle)["rewrite"]["fail_closed_elements"]
    out = io.StringIO()
    call_command("migrate_course_content", "verify",     # reports, does not raise
                 "--target-slug", "dst", "--bundle-dir", str(bundle), stdout=out)
    assert "malformed" in out.getvalue()


def test_a_fail_closed_instance_still_gets_its_other_fields_rewritten():
    """The deliberate absence of `continue` after fail_closed_elements.append.

    UNIT-level, and it must be: the guard only bites on an instance with TWO
    registry fields, and part 2's registry gives exactly two such models --
    GuessNumberElement (stem + success_message) and the question models
    (stem + explanation). Built UNSAVED so no save() sanitiser closes the torn
    anchor, the same trick Task 7's _is_fail_closed unit test uses.

    Falsify by adding `continue` after the append in Task 7's rewrite loop: the
    mappable link in success_message then keeps its source pk, and verify stays
    silent because the element was subtracted from the dangling count.
    """
    from courses.models import GuessNumberElement

    obj = GuessNumberElement(
        stem='<p><a href="/courses/n/999999/">torn</p>',        # fail-closed
        success_message='<p><a href="/courses/n/55/">ok</a></p>',  # mappable
    )
    assert _is_fail_closed(obj) is True
    changed, _flattened = rewrite_instance(obj, {55: 900}, on_missing="unwrap")
    assert "success_message" in changed
    assert "/courses/n/900/" in obj.success_message
    assert obj.stem == '<p><a href="/courses/n/999999/">torn</p>'   # untouched


def test_resolve_rewrite_applied_then_verify_recomputes_fail_closed(tmp_path):
    """The `fail_closed_elements`-ABSENT branch, which no other test reaches.

    --resolve-rewrite applied writes no such key by construction, so verify must
    recompute it live. Treating the missing key as [] makes every fail-closed
    body read as ordinary dangling -- and with status already applied and
    --resolve-rewrite refusing a non-in_progress file, verify fails forever with
    no remedy."""
    from courses.models import FillGateElement

    course = _mk_source(parts=("P0", "P1"))
    u0 = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=u0, title="torn",
        content_object=FillGateElement.objects.create(
            # UNMAPPABLE target: a mappable pk never reaches the unwrap
            # branch where the fail-closed bail lives.
            stem='<p><a href="/courses/n/999999/">torn</p>',
            answers=[["x"]],
        ),
    )
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    # Force the resolved_by_operator shape: no counts, no fail_closed key.
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    st.pop("rewrite", None)
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    call_command("migrate_course_content", "import", *args,
                 "--resolve-rewrite", "applied")
    assert "fail_closed_elements" not in _read_state_raw(bundle)["rewrite"]

    out = io.StringIO()
    call_command("migrate_course_content", "verify",   # reports, does NOT raise
                 "--target-slug", "dst", "--bundle-dir", str(bundle), stdout=out)
    assert "malformed" in out.getvalue()


def test_a_repair_resume_keeps_a_fail_closed_element_from_another_part(tmp_path):
    """The merge rule. Falsify by replacing the `rewrite` object wholesale: the
    earlier part's element vanishes from the list, verify TRUSTS the shortened
    list, counts it as ordinary dangling, and raises with no remedy."""
    from courses.models import FillGateElement

    course = _mk_source(parts=("P0", "P1"))
    u0 = ContentNode.objects.get(course=course, title="U0")
    Element.objects.create(
        unit=u0, title="torn",
        content_object=FillGateElement.objects.create(
            # UNMAPPABLE target: a mappable pk never reaches the unwrap
            # branch where the fail-closed bail lives.
            stem='<p><a href="/courses/n/999999/">torn</p>',
            answers=[["x"]],
        ),
    )
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    recorded = set(_read_state_raw(bundle)["rewrite"]["fail_closed_elements"])
    assert recorded
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P1"
    ).delete()
    call_command("migrate_course_content", "import", *args, "--start-at", "1")
    after = set(_read_state_raw(bundle)["rewrite"]["fail_closed_elements"])
    assert recorded <= after          # part 0's finding carried forward


def test_verify_reports_a_structural_failure_before_a_link_one(tmp_path):
    """Gate ordering: a missing part is the more actionable report, so the node
    tally must pre-empt the link reconciliation. Needs a fixture that would trip
    BOTH -- _export_bundle alone has no internal links, so it cannot falsify
    the ordering."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    # Deleting P1 removes the link's target too, so both gates would fire.
    ContentNode.objects.filter(
        course=target, parent__isnull=True, title="P1"
    ).delete()
    with pytest.raises(CommandError, match="node count mismatch"):
        call_command("migrate_course_content", "verify",
                     "--target-slug", "dst", "--bundle-dir", str(bundle))


def test_skipped_dead_raises_before_the_transaction(tmp_path):
    """The unit test in Task 7 cannot observe either half of this: the status
    flip and the transaction both live in _run_link_pass. Moving the raise after
    `status = "in_progress"; write` would leave the unit test green."""
    course = _mk_source(parts=("P0", "P1"))
    _link_between(course, "P0", "P1")
    bundle = tmp_path / "bundle"
    call_command("migrate_course_content", "export",
                 "--source-slug", "src", "--bundle-dir", str(bundle))
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args, "--start-at", "0")
    st = _read_state_raw(bundle)
    st["status"] = "collecting"
    for e in st["parts"]:
        e["rewritten"] = False
    st.pop("rewrite", None)
    # Point one recorded pk at a row that does not exist.
    st["parts"][0]["node_map"][sorted(st["parts"][0]["node_map"])[0]] = 10**9
    _write_state(bundle, st)
    bodies_before = sorted(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    )
    with pytest.raises(CommandError, match="skipped_dead"):
        call_command("migrate_course_content", "import", *args, "--start-at", "2")
    assert _read_state_raw(bundle)["status"] == "collecting"    # never flipped
    assert sorted(
        TextElement.objects.filter(elements__unit__course=target).values_list(
            "body", flat=True
        )
    ) == bodies_before                                          # nothing touched


def test_resolve_rewrite_with_no_state_file_refuses(tmp_path):
    """I3 / spec: '--resolve-rewrite with no state file at all -> CommandError'."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    call_command("migrate_course_content", "import",
                 "--target-slug", "dst", "--bundle-dir", str(bundle),
                 "--as-user", "mig@example.com")
    (bundle / LINK_STATE_NAME).unlink()
    with pytest.raises(CommandError, match="no rewrite state to resolve"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com",
                     "--resolve-rewrite", "not-applied")


def test_a_failed_resolve_leaves_the_file_in_progress_and_re_runnable(tmp_path):
    """I4. The `collecting` flip is deliberately NOT persisted before the pass:
    the pass's own gates raise before it writes `in_progress`, so persisting
    first would leave --resolve-rewrite refused ever after -- and the --start-at
    fallback provably has no working value under non-contiguous orders.

    Falsify by persisting `collecting` first: the second invocation is refused
    and the migration is stuck."""
    bundle = _export_bundle(tmp_path)
    target = _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    for e in st["parts"]:
        e["rewritten"] = False
    _write_state(bundle, st)
    # Break the src guard so the pass raises before it can write in_progress.
    src = Course.objects.get(slug="src")
    p0 = ContentNode.objects.get(course=src, title="P0")
    ContentNode.objects.create(course=src, kind="chapter", title="extra", parent=p0)
    call_command("migrate_course_content", "export", "--source-slug", "src",
                 "--bundle-dir", str(bundle), "--clean")

    with pytest.raises(CommandError, match="re-exported"):
        call_command("migrate_course_content", "import", *args,
                     "--resolve-rewrite", "not-applied")
    assert _read_state_raw(bundle)["status"] == "in_progress"   # still re-runnable


def test_a_fresh_start_overwrites_an_in_progress_state_file(tmp_path):
    """I5 / spec: the `start_at is None` branch OVERWRITES rather than refuses,
    and must be asserted separately from the resume-path refusal."""
    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    args = ("--target-slug", "dst", "--bundle-dir", str(bundle),
            "--as-user", "mig@example.com")
    call_command("migrate_course_content", "import", *args)
    st = _read_state_raw(bundle)
    st["status"] = "in_progress"
    _write_state(bundle, st)
    # No --start-at: step 3's branch. --force because the target is non-empty.
    call_command("migrate_course_content", "import", *args, "--force")
    after = _read_state_raw(bundle)
    assert after["status"] == "applied"          # rebuilt, not refused
    assert len(after["parts"]) == 3


def test_a_state_write_oserror_on_a_later_part_names_the_resume_hint(tmp_path, monkeypatch):
    """I2 / spec: 'a second case on a later part asserts the --start-at
    <committed + 1> hint AND the orphaned-media log line.' Without it, the else
    arm of the hint and the orphan sentence could both be deleted silently."""
    import courses.management.commands.migrate_course_content as mod

    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()
    real = mod._write_state
    calls = {"n": 0}

    def boom(bundle_, state_):
        calls["n"] += 1
        if calls["n"] <= 2:            # fresh-state write + part 0's write
            return real(bundle_, state_)
        raise OSError("disk full")

    monkeypatch.setattr(mod, "_write_state", boom)
    with pytest.raises(CommandError) as exc:
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com", "--start-at", "0")
    msg = str(exc.value)
    assert "--start-at 1" in msg
    assert "orphaned" in msg


def test_write_state_really_goes_through_os_replace(tmp_path, monkeypatch):
    """I6. The presence/absence assertions alone are green for a plain
    truncate-in-place write, which is exactly what the spec forbids -- so assert
    the MECHANISM."""
    import courses.management.commands.migrate_course_content as mod

    bundle = tmp_path / "b"
    bundle.mkdir()
    seen = []
    real_replace = mod.os.replace

    def spy(src, dst):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", spy)
    _write_state(bundle, {"version": 1, "parts": []})
    assert seen == [
        (str(bundle / (LINK_STATE_NAME + ".tmp")), str(bundle / LINK_STATE_NAME))
    ]


def test_a_state_write_oserror_on_part_zero_names_the_right_recovery(tmp_path, monkeypatch):
    """committed is None on the first part, so an else-arm-only hint evaluates
    None + 1 and raises TypeError -- a raw traceback, exactly what the handler
    exists to prevent."""
    import courses.management.commands.migrate_course_content as mod

    bundle = _export_bundle(tmp_path)
    _mk_target()
    _user()

    # The step-4 branch writes a fresh state file BEFORE the graft loop, outside
    # the try/except OSError under test. Blowing up on call 1 would raise a bare
    # OSError out of handle() -- a different bug, and the test would pass on the
    # wrong exception type. Let that first write through.
    real = mod._write_state
    calls = {"n": 0}

    def boom(bundle_, state_):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(bundle_, state_)
        raise OSError("disk full")

    monkeypatch.setattr(mod, "_write_state", boom)
    with pytest.raises(CommandError, match="no parts committed"):
        call_command("migrate_course_content", "import",
                     "--target-slug", "dst", "--bundle-dir", str(bundle),
                     "--as-user", "mig@example.com", "--start-at", "0")
    assert calls["n"] >= 2       # the loop's write really was reached
```

- [ ] **Step 2: Run the new cases**

```bash
uv run pytest tests/test_migrate_course_content.py -q
```
Expected: PASS. Any failure here is a real defect in Tasks 1–11 — fix the production code, not the
test, and report which task it belongs to.

- [ ] **Step 3: Falsify — including the three deferred from Tasks 8 and 10**

Own-task guards:
- Pass `todo=todo` at site 2 → `test_a_full_import_rewrites_cross_part_and_intra_part_links` RED.
- Build the mapping's liveness from `pending_entries` →
  `test_a_cross_part_link_from_a_re_grafted_part_into_a_rewritten_one` RED.

Deferred from Task 8 (site 1's `not todo`):
- Delete `todo=todo` from site 1 → `test_the_stale_entry_resume_grafts_first_and_rewrites_after`
  must RED with the `skipped_dead` `CommandError` and part `N-1` ungrafted.

Deferred from Task 10 (`verify`):
- Replace the `fail_closed_elements` absence branch with `fail_closed = set()` →
  `test_resolve_rewrite_applied_then_verify_recomputes_fail_closed` RED.
- Move the link reconciliation above the node tally →
  `test_verify_reports_a_structural_failure_before_a_link_one` RED.

Restore all five and re-run.

- [ ] **Step 4: Run the whole affected surface**

```bash
uv run pytest tests/test_migrate_course_content.py tests/test_transfer_export.py tests/test_transfer_import.py tests/test_transfer_subtree.py tests/test_link_transfer.py tests/test_richtext.py tests/test_tabs_transfer.py tests/test_transfer_materialize_duplicate.py tests/test_transfer_views.py -q
```
Expected: PASS, exit 0.

- [ ] **Step 5: Run the full unit suite**

```bash
uv run pytest -m "not e2e" -q
```
Expected: exit 0. If anything unrelated fails, check it fails on `master` too before touching it —
a pre-existing flake belongs in its own PR, not this one.

- [ ] **Step 6: Lint**

```bash
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_migrate_course_content.py
git commit -m "test(migrate): cover the cutover, repair resume, and every error-handling condition"
```

---

## Self-Review

**Spec coverage** — every §Scope row and §Error handling condition maps to a task:

| spec section | task |
|---|---|
| `export.py` `report` out-param | 1 |
| `importer.py` `defer` + `node_map` | 2 |
| state-file schema, helpers, atomic write | 3 |
| bundle `node_index` | 4 |
| outer atomic, per-part append, `bundle_manifest`, `node_index` absence fatal, `OSError` handler | 5 |
| six-step ordering, five resume gates, identity, `src` drift | 6 |
| mapping join, fatal skips, `_is_fail_closed`, rewrite loop, counts, crash-safe marking | 7 |
| two trigger sites | 8 |
| `--resolve-rewrite`, flag matrix | 9 |
| `verify` gates + link reconciliation | 10 |
| `in_progress` probe | 11 |
| §Testing's remaining cases | 12 |

**Known gaps, deliberate:**
The spec's **four accepted gaps**, none of them implemented:
- **Cross-course links** inside migrated bodies are flattened.
- **Bodies part 2 fail-closes** keep their source pks; the pass records them and `verify` reports
  them non-fatally (Tasks 7, 10, 12).
- **A repair resume strands inbound cross-part links.** `verify` detects it and raises; the remedy
  is manual.
- **Absolute same-origin permalinks** pass through untouched and unreported.

Separately — **prevented, not accepted, and untestable from this harness:** the pk-collision
double-apply. Both courses live in one test database, so new pks always exceed source pks. It is
prevented by the once-only invariant (per-order `rewritten` flags), not detected.

**Type consistency check:** `report["node_ids"]` is int-keyed (Task 1) and consumed as
`str(pk)` when written into `node_index` (Task 4). `report["node_map"]` is
`{export_id: int}` (Task 2) and stored verbatim (Task 5). `_invert_node_index` returns
`{export_id: int}` on both sides of the `src` guard (Tasks 3, 5, 6). `_live_pks` takes an
**entry list**, never a set (Tasks 3, 7, 10, 11). `pending_orders` (a set of ints, Task 8) and
`pending_entries` (a list of dicts, Task 7) are deliberately different names for different types.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-27-internal-link-cutover.md`.**

**Blocked on part 2** — see the PREREQUISITE section. Run its gate command before Task 1.
