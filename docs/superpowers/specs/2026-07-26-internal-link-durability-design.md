# Internal content links — durability

Part 2 of two. Part 1 (`2026-07-26-internal-content-links-design.md`) builds the link dialog and the
`/courses/n/<pk>/` permalink. This part keeps those links pointing at the right thing when content
is copied between installs, and warns an author before they break one. Part 1 ships without it;
this is what makes the feature survive the `mat-pp` production cutover.

## Purpose

An internal link stores a node primary key. Two operations invalidate one:

1. **Export → import.** The archive numbers nodes `n0, n1, …` — synthetic ids, not source pks — and
   the importer creates entirely new rows. A body carrying `/courses/n/1234/` arrives in the
   destination install still saying `1234`, which now means either nothing or, worse, some
   unrelated unit. The failure is silent: the link still renders, still clicks, and goes somewhere
   wrong.
2. **Deleting a node.** Nothing tells the author that four lessons point at the chapter they are
   about to remove.

Both need to know the same thing — *where can an internal link be stored?* — so both are built on
one registry rather than two overlapping guesses.

## Scope

**In scope**

- `courses/richtext.py`: the registry of link-bearing storage locations plus the scan/rewrite
  helpers, and a drift guard for the registry.
- Export: record which link targets are inside the exported set.
- Import: rewrite links onto the new pks; flatten the ones that cannot be resolved; report the
  count.
- Delete confirmation: count inbound links before destroying the target.

**Out of scope**

- A link audit / repair page. Still a reasonable follow-up; still not needed to ship.
- Rewriting links in table or fill-table cells — `sanitize_cell` permits no `<a>`, so none exist.
- Repairing links that were already broken before this lands. There are none yet: part 1 has not
  shipped, so no stored internal links exist anywhere.

## Architecture / components

### 1. `courses/richtext.py` — the registry

Rich text does not live in one shape. Most of it is a `TextField` on a concrete element; one type
keeps it inside a `JSONField`. The registry therefore holds *accessors*, not field names:

```python
# (model, field) — plain TextField holding sanitize_html output
RICH_TEXT_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (CalloutElement, "body"),
    (FillGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),
    (SwitchGateElement, "stem"),
    # every concrete QuestionElement subclass — 10 models x 2 fields
    *[(m, f) for m in CONCRETE_QUESTION_MODELS for f in ("stem", "explanation")],
]

# (model, json_field, path) — rich text nested inside a JSON structure
RICH_TEXT_JSON = [
    (SwitchGridElement, "lines", ("[*]", "stem")),
]
```

27 plain fields and one JSON accessor. `CONCRETE_QUESTION_MODELS` is introspected from
`QuestionElement.__subclasses__()` filtered to non-abstract models — currently exactly 10 — rather
than spelled out. Introspection is safe *there* and only there: every concrete question type
inherits the same two fields from the same abstract `save()`, so a new question type is covered
automatically. No such uniformity exists among the other element types, which is why they are
listed by hand.

Each entry was derived by tracing an actual `sanitize_html` call site, not by reading field names:

- `TextElement.body`, `SpoilerElement.body`, `CalloutElement.body`, `GuessNumberElement.success_message`
  are sanitised in `save()`.
- `FillGateElement.stem`, `GuessNumberElement.stem`, `SwitchGateElement.stem` and each
  `lines[*].stem` of `SwitchGridElement` are sanitised **form-side** and deliberately *not* in
  `save()`, because the sentinel-token stems must go through
  `sanitize_html -> strip_sentinel -> parse` in that order. `GuessNumberElement.save()` says so in
  a comment, and `importer.py` re-sanitises that stem by hand for the same reason.
- The 10 concrete question models inherit `stem`/`explanation` sanitising from the abstract
  `QuestionElement.save()`.

Explicitly **not** in the registry, each checked rather than assumed: `StepperStep.content` and
`MarkDoneItem.content` (plain text + KaTeX, `save()` only strips); `SwitchGridElement.prompt`
("plain-text instruction line"); `RevealGateElement.label`, `SpoilerElement.label`,
`CalloutElement.heading` (plain labels); every `sanitize_cell` location — table cells, fill-table
cells, switch-gate and switch-grid cycler options, gallery descriptions — which cannot hold an
anchor at all.

Three functions:

```python
def find_link_targets(html) -> set[int]      # node pks referenced by /courses/n/<pk>/
def rewrite_links(html, mapping) -> str      # remap; unmapped -> per `on_missing`
def iter_rich_text(instance)                 # yield (accessor, value) for one element instance
```

`rewrite_links` takes `on_missing="keep"` or `on_missing="unwrap"`; unwrapping removes the `<a>`
and keeps its text.

**Drift guard.** A new element type with a rich-text body that nobody adds here would silently
escape both features. The guard follows the tripwire idiom the repo already uses (the
`ELEMENT_MODELS` count assertion in `test_transfer_schema.py`, the twin-drift guard of #169): the
test greps `courses/models.py` and `courses/element_forms.py` for `sanitize_html(` call sites and
asserts the count matches a declared constant, with a message naming `courses/richtext.py` as what
to update. Adding a rich-text field changes the count and turns the test RED.

Deriving the registry automatically was tried on paper and rejected on evidence: the obvious
mechanism — collect form fields whose widget carries `data-rte-source` — covers `FillGateElement`,
`SwitchGateElement` and the question models, but **misses** `TextElement`, `SpoilerElement`,
`CalloutElement`, `GuessNumberElement` and `SwitchGridElement`, whose editor templates hand-write
the `<textarea data-rte-source>` instead of rendering a widget. An automatic registry that silently
covers 22 of 28 locations is worse than an explicit list with a tripwire.

### 2. Export — `courses/transfer/export.py`

The exporter already builds `node_ids = {pk: "nN"}` while walking the tree. After the element dicts
are built, scan them through the registry and emit:

```python
document["link_nodes"] = {"1234": "n7", ...}   # only targets inside the exported set
```

Element bodies in the archive are left **byte-identical**. That matters: an archive opened by an
older importer, or inspected by hand, still contains exactly what it contains today.

`link_nodes` is a new top-level key in `course.json`. Checked, not assumed: `course.json` is parsed
by `parse_json_bytes` and its top-level keys are **not** run through `_exact_keys` (unlike
`manifest.json`, which is strictly keyed), so the addition needs no validator change and a v5
archive lacking the key parses exactly as before.

`FORMAT_VERSION` still goes 5 → 6, because what an archive can express has changed. This is safe in
the direction that matters: the importer's gate rejects only `version > FORMAT_VERSION` — an
archive *newer* than the code — so a v5 archive keeps importing into a v6 install. The rule from
the reveal-gate work ("don't bump the version for a new element type") does not apply here; that
was about element payloads the format already accommodated, whereas this adds a document-level key.

### 3. Import — `courses/transfer/importer.py`

The importer builds `node_map = {export_id: ContentNode}` in `_create_nodes` before any element is
created. Inverting `link_nodes` through it gives `{old_pk: new_pk}`.

The rewrite runs as a **post-pass over the created instances**, using the same registry, rather than
over the payload dicts. Payload keys are a second vocabulary that would have to be kept in step with
the model fields; the registry already describes the models, and a post-pass reuses it exactly. Only
rows whose text actually contains `/courses/n/` are re-saved, with `update_fields`.

**Unresolvable links.** A link whose target is not in the archive — a subtree export pointing out of
its own subtree — is handled by call site, because the correct answer differs:

| entry point | `on_missing` | why |
|---|---|---|
| `import_course` / `import_content` (uploaded archive) | `unwrap` | the pk means nothing here, and leaving it risks silently linking to an unrelated node that happens to occupy that pk |
| `duplicate_unit` / `materialize_duplicate` (same install) | `keep` | those pks still resolve; flattening a working link would be a regression |

The count of flattened links is returned by the import and surfaced in the existing import preview
alongside the other tallies.

**Accepted, stated gap:** re-importing your own archive back into the install that produced it takes
the `unwrap` path, so out-of-scope links that would still have resolved get flattened. Flattening is
the safe direction — visible text that goes nowhere, rather than a link that confidently goes
somewhere wrong.

The archive does carry `manifest["source"]["instance"]`, and it is tempting to compare it against
the importing host to detect "same install" exactly. **Do not.** That field is filled from
`source_host`, the exporting request's host name — it identifies a *hostname*, not an installation.
Two unrelated developer instances are both `localhost:8000`, so the comparison would report "same
install" for a genuinely foreign archive and take the `keep` path, leaving stale pks that may
resolve to unrelated nodes in the destination. That is precisely the silent mis-link this design
exists to prevent, so the call-site rule above stays the discriminator. If an exact answer is ever
needed, it wants a real install identity — a UUID on the `Institution` singleton, stamped into the
archive — which is a small follow-up, not part of this.

### 4. Delete warning — `courses/views_manage.py`, `node_confirm_delete.html`

`node_delete`'s GET branch already assembles `counts = {"descendants": ..., "elements": ...}` for
the confirm page. A third key joins it:

```python
counts["inbound_links"] = count_inbound_links(course, node)
```

`count_inbound_links` scans the registry for links to the node **or any descendant**, reusing
`ContentNode._subtree_node_ids()`. Plain fields are filtered in the database, one query per model,
scoped to the course through the element join row (`elements__unit__course=course`) — the same
course-scoping join the editor media resolvers use, kept `app_label`-pinned. `SwitchGridElement`'s
`lines` is a `JSONField` where a substring filter is not portable, so those rows (few per course,
already course-scoped) are fetched and scanned in Python.

The scan is course-scoped, not install-wide. Every link the dialog can produce is same-course by
construction; a hand-typed cross-course link is out of the count, and the template says "in this
course" so the number is not read as a guarantee.

The confirm page gains one sentence, shown only when the count is non-zero. It is a warning, not a
block — the author may well intend the deletion.

## Data flow

```text
EXPORT
  walk nodes -> node_ids {pk: "nN"}
  scan element dicts through the registry -> pks referenced
  document["link_nodes"] = {pk: "nN"} for pks inside the exported set

IMPORT
  _create_nodes -> node_map {"nN": ContentNode}
  invert link_nodes through node_map -> {old_pk: new_pk}
  create elements
  post-pass: for each created instance, for each registry accessor,
      rewrite_links(value, mapping, on_missing=unwrap|keep)
      save(update_fields=[...]) only when the text changed
  report flattened count -> import preview

DELETE (GET confirm)
  subtree pks -> registry scan, course-scoped -> counts["inbound_links"]
```

## Error handling

- **`link_nodes` absent** (older archive, or an export predating this change) → the mapping is
  empty; no rewrite happens and, on the uploaded-archive path, every internal link flattens. Correct:
  such an archive genuinely carries no way to resolve its links.
- **A target pk in `link_nodes` missing from `node_map`** → treated as unresolvable, same as absent.
  Should not occur; handled rather than asserted, since an import must never 500 on a malformed
  archive.
- **Malformed JSON in `SwitchGridElement.lines`** (a line that is not a dict, a missing `stem`) →
  the accessor skips it. `payloads.py` already rejects non-string values on the way in.
- **Delete-count query failure** must not block a deletion; the count is advisory.

## Testing

Falsified before trusted — delete the behaviour, require RED — per house rule.

**Registry**

- `find_link_targets` on: no links; one link; several; an external link (ignored); a malformed
  `/courses/n/abc/` (ignored).
- `rewrite_links` with `on_missing="keep"` and `on_missing="unwrap"`; unwrap preserves inner text
  and surrounding markup.
- The drift guard itself: add a throwaway `sanitize_html` call site and assert the test goes RED.
  Without this the guard is decoration.
- Registry completeness spot-check: for each of the five element types whose editor templates
  hand-write the textarea (text, spoiler, callout, guess-number, switch-grid), store an internal
  link through the real form path and assert `find_link_targets` sees it. These are exactly the
  types a widget-derived registry would have missed, so they are the ones worth asserting.

**Transfer**

- Round trip within one install: export a course containing an internal link, import as a new
  course, assert the stored href points at the **new** pk and that following it reaches the copied
  unit — not the original.
- Subtree export whose link points outside it → imported body has no anchor, text intact, and the
  reported flattened count is 1.
- `duplicate_unit` of a unit linking to a sibling outside the duplicated scope → link **unchanged**
  (the `keep` path). This is the case the naive rule gets wrong, so it is asserted directly.
- `duplicate_unit` of a subtree with an internal link inside it → rewritten to the copy.
- An archive without `link_nodes` imports cleanly.
- Existing transfer round-trip tests still pass with `FORMAT_VERSION` at 6.

**Delete warning**

- Count is 0 with no links; N with N links; counts links to a *descendant* of the node, not just to
  the node itself; ignores links from another course.
- The confirm page shows the sentence only when the count is non-zero.
- Query count asserted, so the per-model scan cannot quietly become per-element.

## i18n

The flattened-links line in the import preview and the delete-confirm warning are translatable and
added to both catalogs via `makemessages -l pl -l en --no-obsolete`, with fuzzy entries cleared
properly (both the `#, fuzzy` line and the `#| msgid` comment). Both strings take a count, so they
use `blocktrans ... plural` — Polish has three plural forms, and a bare `{{ n }}` string would be
untranslatable into it.
