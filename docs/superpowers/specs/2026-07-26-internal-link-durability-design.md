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

**Files touched**

| file | change |
|---|---|
| `courses/richtext.py` | **new** — the registry, the scan/rewrite helpers |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 5→6; `link_nodes` admitted to `validate_document`'s key list and shape-checked |
| `courses/transfer/export.py` | emit `document["link_nodes"]` |
| `courses/transfer/importer.py` | `_create_elements` returns what it created; `on_missing` threaded through the three entry points; the rewrite post-pass |
| `courses/builder.py` | pass `on_missing="keep"` from `duplicate_unit` |
| `courses/views_transfer.py` | fold the flattened-link count into the confirm-step success message |
| `courses/views_manage.py` | `counts["inbound_links"]` in `node_delete`'s GET branch |
| `templates/courses/manage/node_confirm_delete.html` | the warning sentence |
| `locale/*/LC_MESSAGES/django.po` + `.mo` | two new strings, both catalogs, regenerated |

**Out of scope**

- A link audit / repair page. A reasonable follow-up; not needed to ship.
- Rewriting links in table or fill-table cells — `sanitize_cell` permits no `<a>`, so none exist.
- Repairing links already broken before this lands. There are none: part 1 has not shipped, so no
  stored internal links exist anywhere.
- **Fixing the switch-grid sanitiser inconsistency** documented in §1. It is a pre-existing defect,
  it predates this feature, and correcting it means changing what `_build_switch_grid` accepts —
  its own blast radius, its own change.

## Architecture / components

### 1. `courses/richtext.py` — the registry

Every link-bearing location is a plain `TextField` on a concrete element. There are 27 of them:

```python
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
```

`CONCRETE_QUESTION_MODELS` is introspected from `QuestionElement.__subclasses__()` filtered to
non-abstract models — currently exactly 10. Introspection is safe *there* and only there: every
concrete question type inherits the same two fields from the same abstract `save()`, so a new
question type is covered automatically. No such uniformity exists among the other element types,
which are listed by hand.

Each entry was derived by tracing an actual `sanitize_html` call site, not by reading field names:

- `TextElement.body`, `SpoilerElement.body`, `CalloutElement.body`, `GuessNumberElement.success_message`
  are sanitised in `save()`.
- `FillGateElement.stem`, `GuessNumberElement.stem` and `SwitchGateElement.stem` are sanitised
  **form-side** and deliberately *not* in `save()`, because the sentinel-token stems must go through
  `sanitize_html -> strip_sentinel -> parse` in that order. `GuessNumberElement.save()` says so in a
  comment, and `importer.py` re-sanitises that stem by hand for the same reason.
- The 10 concrete question models inherit `stem`/`explanation` sanitising from the abstract
  `QuestionElement.save()`.

**`SwitchGridElement.lines[*].stem` is deliberately excluded**, though `SwitchGridElementForm`
does run it through `sanitize_html`. Three measured facts, together, make a JSON accessor for it
machinery with nothing to do:

- there is **no authoring surface** — `_edit_switchgrid.html` renders `<textarea … data-stem>`, not
  `data-rte-source`, and `text_toolbar.js` mounts the RTE (and hence part 1's link button) only on
  `[data-rte-source]`. Part 1's dialog can never put a link there;
- a link **cannot survive import** — `importer.py::_build_switch_grid` passes every line stem through
  `switchgrid.sanitize_stem_segments`, which applies **`sanitize_cell`** to each non-token segment,
  and `CELL_TAGS` has no `<a>`. Any anchor is destroyed at build time, before a rewrite pass could
  run;
- so the only way to create one is hand-typing raw HTML into a plain textarea, and it would then be
  silently dropped by the next export→import round trip regardless of what this design does.

That form-side/import-side split (`sanitize_html` vs `sanitize_cell` on the same field) is a real
pre-existing inconsistency, and it is named in §Scope as out of scope rather than quietly inherited.
Excluding the field keeps the registry a flat list of model fields — which is what lets the accessor
protocol below stay trivial.

Also **not** in the registry, each checked rather than assumed:

| location | why it cannot hold an internal link |
|---|---|
| `StepperStep.content`, `MarkDoneItem.content` | plain text + KaTeX; `save()` only strips |
| `SwitchGridElement.prompt` | "plain-text instruction line" |
| `RevealGateElement.label`, `SpoilerElement.label`, `CalloutElement.heading` | plain labels |
| `TabsElement` tab labels | `sanitize_label` strips *every* tag |
| `Choice.text`, `Choice.feedback` | documented as "plain text + KaTeX delimiters; never sanitised" |
| every `sanitize_cell` location — table cells, fill-table cells, switch-gate and switch-grid cycler options, gallery descriptions | `CELL_TAGS` has no `<a>` |
| **`HtmlElement.html`** | raw author HTML/CSS/JS, explicitly **not** sanitised, rendered into a sandboxed `srcdoc` by `htmlsandbox.build_srcdoc`. It is opaque author markup this feature does not own — and note the drift guard below structurally cannot see it, since it never touches `sanitize_html` |

**The accessor protocol.** Because every entry is a plain field, an accessor is just
`(model, field_name)`; `getattr` / `setattr` read and write it, and `field_name` is exactly what
`update_fields` needs. Four functions:

```python
def find_link_targets(html) -> set[int]                    # node pks in /courses/n/<pk>/ hrefs
def rewrite_links(html, mapping, *, on_missing) -> tuple[str, int]   # -> (html, flattened_count)
def iter_rich_text(instance) -> Iterator[tuple[str, str]]  # (field_name, value)
def rewrite_instance(instance, mapping, *, on_missing) -> tuple[list[str], int]
                                                           # -> (changed field names, flattened)
```

`rewrite_instance` is what the import post-pass calls: it rewrites every registry field on one
instance and hands back the `update_fields` list, so no caller has to know the registry's shape.

**Only `<a>` `href` attributes are touched — never text content.** The mechanism is a targeted
regex over anchor tags, not a parse-and-reserialise:

- a bs4 round trip would re-escape entities (the repo's own recorded `str(Tag)` re-escaping trap),
  and stored bodies routinely carry `\(…\)` math whose escaping `sanitize.py::_canon_math` is
  deliberately precise about;
- a naive whole-document regex would rewrite a literal `/courses/n/12/` appearing in visible link
  *text*, which is a string an author may well type.

So: match `<a ...>` open tags, rewrite only the `href` value inside them, and for `on_missing="unwrap"`
drop the open tag and its matching `</a>` — safe without a parser because anchors never nest (the
sanitiser's output does not, and no browser produces nested `<a>`). Everything outside anchor tags is
returned byte-identical. §Testing pins that with a body containing both an inline math span and a
literal `/courses/n/…` in visible text.

**Drift guard.** A new element type with a rich-text body that nobody adds here would silently
escape both features. The guard greps for `sanitize_html(` call sites — but as a **set of
`(file, enclosing def/class)` pairs**, not a bare count, and it covers `courses/models.py`,
`courses/element_forms.py` *and* `courses/transfer/importer.py` (which has a third call site, at
`_build_guess_number`). A set-valued assertion is what lets the failure message distinguish the two
cases that a count conflates:

- a new site inside a *question* form's `clean_stem` → covered automatically by
  `CONCRETE_QUESTION_MODELS`; the expected set needs updating but `RICH_TEXT_FIELDS` does not;
- a new site on any other model → `RICH_TEXT_FIELDS` genuinely needs an entry.

With a bare count both read as "bump the constant", which trains exactly the wrong reflex.

Deriving the registry automatically was tried on paper and rejected on evidence — though not for the
reason it first appears. Twelve form fields declare `widgets = {... "data-rte-source" ...}` in
`element_forms.py`, and collecting those would miss `TextElement`, `SpoilerElement`,
`CalloutElement`, `GuessNumberElement` and `SwitchGridElement`. But the deeper problem is that
**those widget attributes are never rendered**: every editor template hand-writes its
`<textarea data-rte-source>`, including the ones the widget declarations supposedly cover
(`_edit_fillgate.html`, `_edit_switchgate.html`, `_edit_choicequestion.html`, and so on). A
widget-derived registry would be built on a signal the editor path does not use — worse than an
explicit list, because it would look authoritative.

### 2. Export — `courses/transfer/export.py`, `courses/transfer/schema.py`

The exporter already builds `node_ids = {pk: "nN"}` while walking the tree. The scan runs over the
**concrete element instances**, not the payload dicts:

```python
document["link_nodes"] = {"1234": "n7", ...}   # only targets inside the exported set
```

Scanning instances is not a stylistic preference — it is the only option consistent with the
registry. Element dicts are `{"type": type_key, "data": {…payload keys…}}`, and the registry speaks
`(model, field)`; applying one to the other would need both a `type_key → model` map and a
`field → payload key` map, i.e. exactly the second vocabulary §3 rejects. The pass-2 export loop
already holds `join.content_object`, so `iter_rich_text(instance)` applies directly.

Element bodies in the archive are left **byte-identical**.

**`link_nodes` must be admitted to the document validator, and this is the opposite of what an
earlier draft of this spec claimed.** `validate_document` calls
`_exact_keys(doc, ["course"|"context", "nodes", "elements", "media"], "course.json")`
(`schema.py:114-119`), and `_exact_keys` both requires every listed key and rejects every unlisted
one. So doing nothing would make every *new* archive fail import with "course.json contains an
unknown key 'link_nodes'", while naively adding it to the list would make every *v5* archive fail
with "course.json is missing the key 'link_nodes'". The fix is the optional-key pattern the repo
already uses for the FORMAT_VERSION-2 `width`/`height` addition (`payloads.py:153`):
`doc.setdefault("link_nodes", {})` **before** the `_exact_keys` call, then add it to the key list.

Its shape is then validated like every other document field, because the import must never 500 on a
hand-crafted archive: `link_nodes` is a dict; each key is a decimal string; each value is a string;
the whole dict is capped at a stated size. Anything else is rejected through `_err`, in the same
style as the surrounding validators. Keys that parse but are absent from `node_map` are *not* an
error — see §3.

`FORMAT_VERSION` goes 5 → 6, because what an archive can express has changed. The importer's gate
rejects only `version > FORMAT_VERSION`, so a v5 archive keeps importing into a v6 install.

**The reverse direction is a deploy-ordering constraint, and it is the one the `mat-pp` cutover
depends on:** a v6 archive is *rejected* by any install still running v5. Exporting from a dev or
staging box and importing into production therefore requires **production to be upgraded first**.
That is a prerequisite of the cutover, not a detail.

### 3. Import — `courses/transfer/importer.py`, `courses/builder.py`

The importer builds `node_map = {export_id: ContentNode}` in `_create_nodes` before any element is
created. Inverting `link_nodes` through it gives `{old_pk: new_pk}`; keys are decimal strings and
are parsed on the way in, with an unparseable key skipped rather than raised.

The rewrite runs as a **post-pass over the created instances**, using the same registry, rather than
over the payload dicts — payload keys are a second vocabulary that would have to be kept in step
with the model fields.

**Two interface changes this requires, neither free.** `_create_elements` currently returns `None`
and keeps its created objects in a local, so today the post-pass would have nothing to iterate: it
must return the created join rows. And the three entry points — `import_course`, `import_subtree`,
`materialize_duplicate` — each need an `on_missing` keyword to carry the policy below, with
`builder.duplicate_unit` passing it through. Only rows whose text actually contains `/courses/n/`
are re-saved, with `update_fields` from `rewrite_instance`.

**Unresolvable links.** A link whose target is not in the archive is handled by call site, because
the correct answer differs:

| entry point | `on_missing` | why |
|---|---|---|
| `import_course` / `import_subtree` (uploaded archive) | `unwrap` | the pk means nothing here, and leaving it risks silently linking to an unrelated node that happens to occupy that pk |
| `materialize_duplicate` (same install, via `duplicate_unit`) | `keep` | those pks still resolve; flattening a working link would be a regression |

**Reporting the flattened count.** It is folded into the confirm step's existing
`messages.success(...)`, **not** the import preview. The preview is computed by `build_preview` at
*upload* time, from the archive document alone, before anything is written — there is no preview
render after the import to put a post-hoc tally on. Reporting through the success message also keeps
the count derived from what actually happened rather than from a second, payload-dict-shaped
prediction. This means `import_course` and `import_subtree` change from returning a bare
`Course`/`ContentNode` to returning that plus the count; the call sites in `views_transfer.py` are
updated accordingly.

**Accepted, stated gap:** re-importing your own archive back into the install that produced it takes
the `unwrap` path, so out-of-scope links that would still have resolved get flattened. Flattening is
the safe direction — visible text that goes nowhere, rather than a link that confidently goes
somewhere wrong.

The archive does carry `manifest["source"]["instance"]`, and it is tempting to compare it against
the importing host to detect "same install" exactly. **Do not.** That field is filled from
`source_host`, the exporting request's host name — it identifies a *hostname*, not an installation.
Two unrelated developer instances are both `localhost:8000`, so the comparison would report "same
install" for a genuinely foreign archive and take the `keep` path, leaving stale pks that may resolve
to unrelated nodes in the destination. That is precisely the silent mis-link this design exists to
prevent. If an exact answer is ever needed, it wants a real install identity — a UUID on the
`Institution` singleton, stamped into the archive — which is a small follow-up, not part of this.

### 4. Delete warning — `courses/views_manage.py`, `node_confirm_delete.html`

`node_delete`'s GET branch already assembles `counts = {"descendants": ..., "elements": ...}`. A
third key joins it:

```python
counts["inbound_links"] = count_inbound_links(course, node)
```

**The query shape is specified, because the obvious one does not scale.** The target is a *set* of
pks (`_subtree_node_ids()`), and matching each one as its own `LIKE` would build a query with one OR
term per (pk × field) — deleting a top-level part of `mat-pp` would mean hundreds of terms across 17
models. Instead, per registry model: one course-scoped query filtering on the **constant** substring
`"/courses/n/"`, returning only the registry fields; then `find_link_targets` in Python on each row,
intersected with the subtree pk set. The database work is a fixed, small predicate; the per-pk
matching happens on the few rows that contain any internal link at all.

Course scoping is the reverse `GenericRelation` filter — `TextElement.objects.filter(elements__unit__course=course)`
— and needs no `content_type` pin: filtering backwards through a `GenericRelation` has no
`content_type` column to pin, because Django supplies it. Nested elements (tabs, two-column and
spoiler children) are covered without extra work, since a child `Element` keeps its own `unit` FK.

The scan is course-scoped, not install-wide. Every link the dialog can produce is same-course by
construction; a hand-typed cross-course link is out of the count, and the template says "in this
course" so the number is not read as a guarantee.

The confirm page gains one sentence, shown only when the count is non-zero. It is a warning, not a
block — the author may well intend the deletion.

## Data flow

```text
EXPORT
  walk nodes -> node_ids {pk: "nN"}
  scan concrete instances via iter_rich_text -> pks referenced
  document["link_nodes"] = {str(pk): "nN"} for pks inside the exported set
  schema: doc.setdefault("link_nodes", {}) before _exact_keys; shape-validated

IMPORT
  _create_nodes -> node_map {"nN": ContentNode}
  invert link_nodes through node_map -> {old_pk: new_pk}   (keys parsed; bad keys skipped)
  _create_elements -> created join rows (NEW: it returns them)
  post-pass: rewrite_instance(obj, mapping, on_missing=unwrap|keep)
      save(update_fields=changed) only when something changed
  return (course_or_node, flattened_count) -> confirm-step messages.success

DELETE (GET confirm)
  subtree pks -> per model: course-scoped filter on the constant "/courses/n/"
              -> find_link_targets in Python -> intersect subtree -> counts["inbound_links"]
```

## Error handling

- **`link_nodes` absent** (a v5 archive) → `setdefault` supplies `{}`; no rewrite happens and, on the
  uploaded-archive path, every internal link flattens. Correct: such an archive carries no way to
  resolve its links.
- **`link_nodes` malformed** (not a dict, non-decimal keys, non-string values, over the size cap) →
  rejected by `validate_document` through `_err`, like any other malformed field.
- **A target pk in `link_nodes` missing from `node_map`** → treated as unresolvable, same as absent.
  Should not occur; handled rather than asserted, since an import must never 500 on a bad archive.
- **Delete-count query failure** must not block a deletion; the count is advisory.

## Testing

Falsified before trusted — delete the behaviour, require RED — per house rule.

**Registry**

- `find_link_targets` on: no links; one link; several; an external link (ignored); a malformed
  `/courses/n/abc/` (ignored).
- `rewrite_links` with `on_missing="keep"` and `on_missing="unwrap"`; unwrap preserves inner text and
  surrounding markup, and returns the flattened count.
- **Byte-identity outside anchors:** a body containing an inline `\(…\)` math span *and* a literal
  `/courses/n/12/` in visible link text comes back unchanged apart from the intended `href` — the
  case that fails under both a bs4 round trip and a naive whole-document regex.
- The drift guard itself: add a throwaway `sanitize_html` call site and assert the test goes RED.
  Without this the guard is decoration. Assert separately that a new *question-form* site produces a
  different message from a new *model* site.
- Registry completeness spot-check: for each of text, spoiler, callout and guess-number, store an
  internal link through the real form path and assert `find_link_targets` sees it. (Switch-grid is
  deliberately absent — see §1.)
- **The switch-grid exclusion is pinned, not assumed:** a link hand-posted into a switch-grid line
  stem survives the *form*, and is then stripped by `_build_switch_grid` on import. Asserting both
  halves keeps the exclusion honest and makes it visible if the sanitiser inconsistency is ever
  fixed.

**Transfer**

- Round trip within one install: export a course containing an internal link, import as a new
  course, assert the stored href points at the **new** pk and that following it reaches the copied
  unit — not the original.
- Subtree export whose link points outside it → imported body has no anchor, text intact, and the
  reported flattened count is 1.
- `duplicate_unit` of a unit whose body links to a **sibling outside** the duplicated scope → link
  **unchanged** (the `keep` path). This is the case the naive rule gets wrong, so it is asserted
  directly.
- `duplicate_unit` of a unit whose body links to **itself** → rewritten to the copy's pk. This is the
  only in-scope rewrite that case can exercise: `builder.duplicate_unit` raises for anything that is
  not a unit, so the exported document always holds exactly one node.
- A v5 archive (no `link_nodes`) imports cleanly; a malformed `link_nodes` is rejected with a
  `TransferError`, not a 500.
- Existing transfer round-trip tests still pass with `FORMAT_VERSION` at 6.

**Delete warning**

- Count is 0 with no links; N with N links; counts links to a *descendant* of the node, not just to
  the node itself; ignores links from another course.
- The confirm page shows the sentence only when the count is non-zero.
- Query count pinned as a concrete whole-request total, with a comment naming which queries belong to
  the pre-existing per-node `_descendant_count` / `_element_count` walks and which to the new scan.
  The fixture must hold **at least two link-bearing elements of the same model** in the subtree —
  otherwise a regression to one query per element is invisible, and the assertion only measures tree
  size.

## i18n

Two new strings: the flattened-links clause in the import success message, and the delete-confirm
warning. Both are added to both catalogs via `makemessages -l pl -l en --no-obsolete`, with fuzzy
entries cleared properly (both the `#, fuzzy` line and the `#| msgid` comment). Both `.mo` files are
regenerated. `tests/test_i18n_po_health.py` requires a real Polish translation for each — an empty
msgstr turns `test_pl_has_no_untranslated_msgid` red.

Both strings take a count, so both use `{% blocktrans count %}` with plural forms: Polish has three,
and a bare `{{ n }}` string is untranslatable into it. The **existing** line in
`node_confirm_delete.html` — `This removes {{ d }} descendant node(s) and {{ e }} element(s).` — is
left exactly as it is. Correcting its `(s)` suffixes is a separate, unrelated i18n fix, and bundling
it would put an unrelated msgid change in this diff.
