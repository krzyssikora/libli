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
| `courses/richtext.py` | **new** — the registry, the scan/rewrite helpers, `count_inbound_links` |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 5→6; `link_nodes` admitted to `validate_document`'s key list and shape-checked |
| `courses/transfer/export.py` | emit `document["link_nodes"]` |
| `courses/transfer/importer.py` | `_create_elements` returns what it created; `on_missing` + `report` threaded through the three entry points; the rewrite post-pass |
| `courses/builder.py` | pass `on_missing="keep"` from `duplicate_unit` |
| `courses/views_transfer.py` | a second, separate `messages.warning` on both import paths when links were flattened |
| `courses/views_manage.py` | `counts["inbound_links"]` in `node_delete`'s GET branch |
| `templates/courses/manage/node_confirm_delete.html` | the warning sentence |
| `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py` | the two hard-coded `FORMAT_VERSION == 5` assertions |
| `locale/*/LC_MESSAGES/django.po` + `.mo` | two new strings, both catalogs, regenerated |

**Out of scope**

- A link audit / repair page. A reasonable follow-up; not needed to ship.
- Rewriting links in table or fill-table cells — `sanitize_cell` permits no `<a>`, so none exist.
- **Fixing the switch-grid sanitiser inconsistency** documented in §1. It is a pre-existing defect
  that predates this feature, and correcting it means changing what `_build_switch_grid` accepts —
  its own blast radius, its own change.
- **The course-delete confirm page** (`course_confirm_delete.html`) is deliberately unchanged.
  Deleting a course destroys every node a hand-typed cross-course link could point at, but the scan
  is course-scoped by design (§4), so it could never report those. Same reason cross-course links
  are out of the count.
- **Repairing links already broken before this lands.** This holds only as a *merge-ordering*
  condition: part 1 is explicitly shippable alone and accepts the stale-pk risk "until part 2
  lands". If part 1 merges and authors use it in production before part 2 follows, any
  duplicate-then-move or export performed in between can leave a stale link that nothing here
  repairs. Land part 2 promptly, or accept a repair follow-up.

## Architecture / components

### 1. `courses/richtext.py` — the registry

Every link-bearing location is a plain `TextField` on a concrete element. **16 models, 27 fields:**

```python
RICH_TEXT_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (CalloutElement, "body"),
    (FillGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),   # 6 fields on 5 models
    (SwitchGateElement, "stem"),               # 6th model
    # every concrete QuestionElement subclass — 10 models x 2 fields = 20
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
pre-existing inconsistency, named in §Scope as out of scope rather than quietly inherited. Excluding
the field keeps the registry a flat list of model fields — which is what lets the accessor protocol
below stay trivial.

Also **not** in the registry, each checked rather than assumed:

| location | why it cannot hold an internal link |
|---|---|
| `StepperStep.content`, `MarkDoneItem.content` | plain text + KaTeX; `save()` only strips |
| `SwitchGridElement.prompt` | "plain-text instruction line" |
| `RevealGateElement.label`, `SpoilerElement.label`, `CalloutElement.heading` | plain labels |
| `Element.title` | optional author label on the join row; `CharField`, never sanitised, rendered autoescaped |
| `TabsElement` tab labels | `sanitize_label` strips *every* tag |
| `Choice.text`, `Choice.feedback` | documented as "plain text + KaTeX delimiters; never sanitised" |
| every `sanitize_cell` location — table cells, fill-table cells, switch-gate and switch-grid cycler options, gallery descriptions | `CELL_TAGS` has no `<a>` |
| **`HtmlElement.html`** | raw author HTML/CSS/JS, explicitly **not** sanitised, rendered into a sandboxed `srcdoc` by `htmlsandbox.build_srcdoc`. Opaque author markup this feature does not own — and note the drift guard below structurally cannot see it, since it never touches `sanitize_html` |

**The accessor protocol.** Because every entry is a plain field, an accessor is just
`(model, field_name)`; `getattr` / `setattr` read and write it, and `field_name` is exactly what
`update_fields` needs. Five functions, all in `courses/richtext.py`:

```python
def find_link_targets(html) -> set[int]                    # node pks in /courses/n/<pk>/ hrefs
def rewrite_links(html, mapping, *, on_missing) -> tuple[str, int]   # -> (html, flattened_count)
def iter_rich_text(instance) -> Iterator[tuple[str, str]]  # (field_name, value)
def rewrite_instance(instance, mapping, *, on_missing) -> tuple[list[str], int]
                                                           # -> (changed field names, flattened)
def count_inbound_links(course, node) -> int               # see §4 for what it counts
```

`rewrite_instance` is what the import post-pass calls: it rewrites every registry field on one
instance and hands back the `update_fields` list, so no caller has to know the registry's shape.

**The href predicate is part 1's, exactly.** `find_link_targets` matches only `href` *values*, and
matches them against the same anchored pattern part 1 pins for prefill: `^/courses/n/(\d+)/$`. The
two must agree — a prefix match here would make the delete count and the rewrite disagree with the
dialog and the CSS marker about what an internal link even is. `/courses/n/12/?x=1` is therefore not
an internal link anywhere in this feature.

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
returned byte-identical.

That relies on one property worth stating: all stored rich text is `nh3.clean` output, which
entity-escapes `>` inside attribute values, so a `title="a > b"` cannot truncate an `<a[^>]*>` match.
The property is weakest for `FillGateElement.stem` and `SwitchGateElement.stem`, which
`_build_fill_gate` / `_build_switch_gate` do **not** re-sanitise on the import path — a hand-crafted
archive could therefore carry a raw `>` in an attribute. The regex must **fail closed** on a body it
cannot match cleanly: leave it byte-identical and count nothing, never emit mangled markup.

**Drift guard.** A new element type with a rich-text body that nobody adds here would silently
escape both features. The guard greps for `sanitize_html(` call sites across `courses/models.py`,
`courses/element_forms.py` and `courses/transfer/importer.py` (a third *file*, with one call site, at
`_build_guess_number`) — 13 sites today, 6 / 6 / 1.

It records a set of **`(file, enclosing def, assignment target)` triples**, not `(file, def)` pairs
and certainly not a bare count. The finer unit is load-bearing: `QuestionElement.save()` already
contains *two* `sanitize_html` calls, so a pair-valued set would be byte-identical after someone adds
a third sanitised field to an existing `save()` — the cheapest possible way to add a link-bearing
field, and precisely the one the guard must not miss.

The guard classifies a new site to choose its message, and the discriminator is **not** the file —
`element_forms.py` holds both kinds. It resolves the enclosing form class's `Meta.model` and tests
membership in `CONCRETE_QUESTION_MODELS`:

- in it (e.g. `FillBlankQuestionElementForm.clean_stem`) → covered automatically by the comprehension;
  update the expected set, leave `RICH_TEXT_FIELDS` alone;
- not in it, or unresolvable (e.g. `FillGateElementForm.clean_stem`, `SwitchGateElementForm.clean`)
  → `RICH_TEXT_FIELDS` genuinely needs an entry.

Note two of those share the def name `clean_stem`, which is why the class's model — not the def name
— is the discriminator.

Deriving the registry automatically was tried on paper and rejected on evidence, though not for the
reason it first appears. Twelve *forms* declare `widgets = {... "data-rte-source" ...}` in
`element_forms.py`, covering twenty-two fields, and collecting those would miss `TextElement`,
`SpoilerElement`, `CalloutElement`, `GuessNumberElement` and `SwitchGridElement`. But the deeper
problem is that **those widget attributes are never rendered**: every editor template hand-writes its
`<textarea data-rte-source>`, including the ones the widget declarations supposedly cover
(`_edit_fillgate.html`, `_edit_switchgate.html`, `_edit_choicequestion.html`, …). A widget-derived
registry would be built on a signal the editor path does not use — worse than an explicit list,
because it would look authoritative.

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
hand-crafted archive:

- `link_nodes` is a dict, else `_err`;
- `len(link_nodes) > settings.TRANSFER_MAX_NODES` → `_err`, in the style of the surrounding
  `TRANSFER_MAX_NODES` / `TRANSFER_MAX_ELEMENTS` / `TRANSFER_MAX_MEDIA_ENTRIES` limits. That bound is
  the natural one: `link_nodes` cannot legitimately hold more than one entry per exported node;
- each key is a decimal string of at most 12 characters — the length cap matters, because a
  100 000-digit key would make a bare `int()` raise `ValueError` past CPython's 4300-digit conversion
  limit, turning a hostile archive into a 500 the surrounding validators exist to prevent;
- each value is a string.

A value that is not an export id present in `node_map` is *not* a validation error — see §3.

`FORMAT_VERSION` goes 5 → 6, because what an archive can express has changed. The importer's gate
rejects only `version > FORMAT_VERSION`, so a v5 archive keeps importing into a v6 install. **Two
existing tests hard-code the number and must be updated**, not merely expected to pass:
`tests/test_transfer_schema.py:57` (an assertion inside `test_transfer_error_carries_message`) and
`tests/test_tabs_transfer.py::test_format_version_is_5`, whose *name* changes too.

**The reverse direction is a deploy-ordering constraint, and it is the one the `mat-pp` cutover
depends on:** a v6 archive is *rejected* by any install still running v5. Exporting from a dev or
staging box and importing into production therefore requires **production to be upgraded first**.
That is a prerequisite of the cutover, not a detail.

### 3. Import — `courses/transfer/importer.py`, `courses/builder.py`

The importer builds `node_map = {export_id: ContentNode}` in `_create_nodes` before any element is
created. `link_nodes` maps **old pk → export id**, so inverting it *through* `node_map` — looking up
each **value** (`"n7"`) in `node_map`, not the key — yields `{old_pk: new_pk}`. Keys are decimal
strings and are parsed on the way in, with an unparseable key skipped rather than raised.

The rewrite runs as a **post-pass over the created instances**, using the same registry, rather than
over the payload dicts — payload keys are a second vocabulary that would have to be kept in step
with the model fields. `_create_elements` currently returns `None` and keeps its created objects in a
local, so it must return the created join rows; the post-pass then takes the one hop to the concrete:

```python
for join in created_joins:
    changed, flattened = rewrite_instance(join.content_object, mapping, on_missing=policy)
    if changed:
        join.content_object.save(update_fields=changed)
```

**Unresolvable links.** A link whose target is not in the archive is handled by call site, because
the correct answer differs:

| entry point | `on_missing` | why |
|---|---|---|
| `import_course` / `import_subtree` (uploaded archive) | `unwrap` | the pk means nothing here, and leaving it risks silently linking to an unrelated node that happens to occupy that pk |
| `materialize_duplicate` (same install, via `duplicate_unit`) | `keep` | those pks still resolve; flattening a working link would be a regression |

**Threading the policy and the count without breaking callers.** The three entry points take two new
**keyword** arguments: `on_missing` (defaulting per the table) and an optional `report` dict, which —
when supplied — receives `{"flattened_links": n}`. `builder.duplicate_unit` passes `on_missing="keep"`.

The `report` out-parameter exists specifically to avoid changing the return types. `import_course`
returns a `Course` and `import_subtree` a `ContentNode`, and **eight test modules** consume those
returns directly (`test_gallery_transfer`, `test_reveal_gate_transfer`, `test_slideshow_transfer`,
`test_table_transfer`, `test_tabs_transfer`, `test_transfer_import`, `test_transfer_subtree`,
`test_transfer_views`), several through shared local helpers whose own contracts would change in
turn. Returning a tuple would redden all of them for no gain; an ignorable keyword costs nothing.

**Reporting the flattened count.** `views_transfer.py` emits a **second, separate**
`messages.warning` after the existing success message, on *both* import paths — there are two
(`_("Course “%(title)s” imported.")` on the whole-course path and `_("Content imported.")` on the
subtree path), and both can flatten links. A separate message rather than a folded-in clause is
deliberate: folding would *change* those two existing msgids, so `makemessages --no-obsolete` would
drop the old entries and demand fresh Polish translations for strings that did not really change.
One new msgid, two call sites, two untouched existing entries.

It is reported at confirm time, not on the import preview. `build_preview` runs at *upload* time,
from the archive document alone, before anything is written — there is no preview render after the
import to carry a post-hoc tally, and a pre-import prediction would have to be computed from
payload dicts, the vocabulary this design rejects.

**Accepted gaps**, stated so they are not later filed as defects:

- Re-importing your own archive back into the install that produced it takes the `unwrap` path, so
  out-of-scope links that would still have resolved get flattened. Flattening is the safe direction —
  visible text that goes nowhere, rather than a link that confidently goes somewhere wrong.
- An **absolute same-origin permalink** (`https://host/courses/n/12/`), which part 1's no-JS baseline
  permits by hand and which part 1 §5 already records as rendering with the *outbound* marker, does
  not match `^/courses/n/(\d+)/$`. It is therefore invisible to `find_link_targets`: neither
  rewritten on import nor counted before a delete. Part 1's dialog normalises these away, so only
  hand-typed HTML is affected.

The archive does carry `manifest["source"]["instance"]`, and it is tempting to compare it against
the importing host to detect "same install" exactly. **Do not.** That field is filled from
`source_host`, the exporting request's host name — it identifies a *hostname*, not an installation.
Two unrelated developer instances are both `localhost:8000`, so the comparison would report "same
install" for a genuinely foreign archive and take the `keep` path, leaving stale pks that may resolve
to unrelated nodes in the destination. That is precisely the silent mis-link this design exists to
prevent. If an exact answer is ever needed, it wants a real install identity — a UUID on the
`Institution` singleton, stamped into the archive — a small follow-up, not part of this.

### 4. Delete warning — `courses/views_manage.py`, `node_confirm_delete.html`

`node_delete`'s GET branch already assembles `counts = {"descendants": ..., "elements": ...}`. A
third key joins it:

```python
counts["inbound_links"] = count_inbound_links(course, node)
```

**What the number counts, exactly:** the number of distinct `Element` join rows **elsewhere in this
course** — outside the subtree being deleted — whose registry text contains at least one link to the
node or any of its descendants. Elements, not anchors: two anchors in one body pointing at two doomed
nodes count once, because the author's unit of repair is "this element needs editing". And outside
the subtree, because a link *inside* the doomed subtree dies together with its target; counting those
would report a large number for a self-contained part whose lessons cross-link each other, which is
the opposite of the warning's purpose.

**The query shape is specified, because the obvious one does not scale.** The target is a *set* of
pks (`_subtree_node_ids()`), and matching each one as its own `LIKE` would build a query with one OR
term per (pk × field) — deleting a top-level part of `mat-pp` would mean hundreds of terms across 16
models. Instead, per registry model: one course-scoped query filtering on the **constant** substring
`"/courses/n/"`, excluding rows whose element lives inside the subtree, returning only that model's
registry fields; then `find_link_targets` in Python on each row, intersected with the subtree pk set.
The database work is a fixed, small predicate; the per-pk matching happens on the few rows that
contain any internal link at all.

Course scoping is the reverse `GenericRelation` filter — `TextElement.objects.filter(elements__unit__course=course)`,
with `.exclude(elements__unit_id__in=subtree_ids)` for the outside-the-subtree rule — and needs no
`content_type` pin: filtering backwards through a `GenericRelation` has no `content_type` column to
pin, because Django supplies it. Nested elements (tabs, two-column and spoiler children) are covered
without extra work, since a child `Element` keeps its own `unit` FK.

The scan is course-scoped, not install-wide. Every link the dialog can produce is same-course by
construction; a hand-typed cross-course link is out of the count, and the template says "in this
course" so the number is not read as a guarantee.

The count is computed unguarded, exactly like the existing `_descendant_count` / `_element_count`
walks beside it. (An earlier draft called it "advisory" and promised a fallback; that described no
reachable behaviour, since a query failure in the GET branch raises before any deletion is offered.)

The confirm page gains one sentence, shown only when the count is non-zero. It is a warning, not a
block — the author may well intend the deletion.

**The two literals need tying to the route.** Part 1 identified `/courses/n/` as a drift hazard the
route *name* does not protect, and tied `courses.css`'s selector to `reverse(...)`. This part adds
two more copies — `richtext`'s pattern and this scan's SQL constant — and §Testing requires the same
tie for both.

## Data flow

```text
EXPORT
  walk nodes -> node_ids {pk: "nN"}
  scan concrete instances via iter_rich_text -> pks referenced
  document["link_nodes"] = {str(pk): "nN"} for pks inside the exported set
  schema: doc.setdefault("link_nodes", {}) before _exact_keys; shape + size validated

IMPORT
  _create_nodes -> node_map {"nN": ContentNode}
  for old_pk_str, export_id in link_nodes.items():        # look up the VALUE
      mapping[int(old_pk_str)] = node_map[export_id].pk   # skip unparseable/absent
  created_joins = _create_elements(...)                   # NEW: it returns them
  for join in created_joins:
      changed, n = rewrite_instance(join.content_object, mapping, on_missing=policy)
      if changed: join.content_object.save(update_fields=changed)
  report["flattened_links"] = total -> a second messages.warning on both import paths

DELETE (GET confirm)
  subtree_ids = node._subtree_node_ids()
  per registry model: course-scoped, exclude elements inside subtree_ids,
                      filter on the constant "/courses/n/"
                   -> find_link_targets in Python -> intersect subtree_ids
                   -> count distinct Element join rows -> counts["inbound_links"]
```

## Error handling

- **`link_nodes` absent** (a v5 archive) → `setdefault` supplies `{}`; no rewrite happens and, on the
  uploaded-archive path, every internal link flattens. Correct: such an archive carries no way to
  resolve its links.
- **`link_nodes` malformed** (not a dict, over the size cap, a key that is not a short decimal
  string, a non-string value) → rejected by `validate_document` through `_err`, like any other
  malformed field.
- **A `link_nodes` *value* that is not an export id present in `node_map`** → that entry is
  unresolvable, same as absent. Should not occur; handled rather than asserted, since an import must
  never 500 on a bad archive.
- **A body the anchor regex cannot match cleanly** → returned byte-identical, nothing counted. Fail
  closed; never emit mangled markup.

## Testing

Falsified before trusted — delete the behaviour, require RED — per house rule.

**Registry**

- `find_link_targets` on: no links; one link; several; an external link (ignored); a malformed
  `/courses/n/abc/` (ignored); `/courses/n/12/?x=1` (ignored — the anchored predicate, matching part
  1); and **a literal `/courses/n/12/` in visible link text** → the empty set. That last one is the
  string an author may plausibly type, and matching it would silently inflate every delete count.
- `rewrite_links` with `on_missing="keep"` and `on_missing="unwrap"`; unwrap preserves inner text and
  surrounding markup, and returns the flattened count.
- **Byte-identity outside anchors:** a body containing an inline `\(…\)` math span *and* a literal
  `/courses/n/12/` in visible text comes back unchanged apart from the intended `href` — the case
  that fails under both a bs4 round trip and a naive whole-document regex.
- **Fail-closed:** a body with a raw `>` inside an anchor attribute is returned byte-identical rather
  than mangled.
- **Route-literal tie:** `richtext`'s pattern and the delete scan's SQL constant both agree with
  `reverse("courses:node_permalink", kwargs={"node_pk": 1})`, mirroring part 1's CSS-selector guard.
- The drift guard itself: add a throwaway `sanitize_html` call site and assert RED. Assert
  separately that (a) a new *question-form* site produces the "expected set" message while a new
  *non-question* site produces the "needs a registry entry" message, and (b) adding a **second**
  sanitised field inside an existing `save()` moves the recorded set — the case a `(file, def)` pair
  would miss.
- Registry completeness spot-check, storing an internal link through the real form path and asserting
  `find_link_targets` sees it, for: text, spoiler, callout, guess-number (the four a widget-derived
  registry would have missed), **fill-gate and switch-gate** (form-sanitised stems), and **one
  question model's `explanation`** — the field most easily lost from `RICH_TEXT_FIELDS`, since it
  arrives via the comprehension rather than a hand-written line.
- **The switch-grid exclusion is pinned, not assumed:** a link hand-posted into a switch-grid line
  stem survives the *form*, and is then stripped by `_build_switch_grid` on import. Asserting both
  halves keeps the exclusion honest and makes it visible if the sanitiser inconsistency is ever
  fixed.

**Transfer**

- Round trip within one install: export a course containing an internal link, import as a new
  course, assert the stored href points at the **new** pk and that following it reaches the copied
  unit — not the original.
- Subtree export whose link points outside it → imported body has no anchor, text intact,
  `report["flattened_links"] == 1`, and the warning message is emitted.
- `duplicate_unit` of a unit whose body links to a **sibling outside** the duplicated scope → link
  **unchanged** (the `keep` path). This is the case the naive rule gets wrong, so it is asserted
  directly.
- `duplicate_unit` of a unit whose body links to **itself** → rewritten to the copy's pk. This is the
  only in-scope rewrite that case can exercise: `builder.duplicate_unit` raises for anything that is
  not a unit, so the exported document always holds exactly one node.
- A v5 archive (no `link_nodes`) imports cleanly; a malformed `link_nodes` — non-dict, over the size
  cap, an over-long key — is rejected with a `TransferError`, not a 500.
- The two `FORMAT_VERSION == 5` assertions are updated (`test_transfer_schema.py:57`, and
  `test_tabs_transfer.py::test_format_version_is_5` renamed), and the round-trip suite is otherwise
  untouched.

**Delete warning**

- Count is 0 with no links; counts **elements**, not anchors — two anchors in one body pointing at two
  doomed nodes count once; counts links to a *descendant* of the node, not just to the node itself;
  ignores links from another course; and **ignores links originating inside the doomed subtree**.
- The confirm page shows the sentence only when the count is non-zero.
- Query count pinned as a concrete whole-request total. The expected shape is stated so the number is
  derived rather than recorded from the first run: **one query per registry model (16)**, plus one
  per subtree depth level from `ContentNode._subtree_node_ids()`, plus the pre-existing per-node
  `_descendant_count` / `_element_count` walks. The fixture must hold **at least two link-bearing
  elements of the same model** in the subtree — otherwise a regression to one query per element is
  invisible and the assertion only measures tree size.

## i18n

Two new strings, and they use **different mechanisms**, because one lives in a template and one does
not:

- **Delete confirm** — `node_confirm_delete.html`, so `{% blocktrans count %}`:
  *"%(n)s other element in this course links here."* /
  *"%(n)s other elements in this course link here."*
- **Import warning** — `views_transfer.py`, which is Python, so `{% blocktrans %}` is unusable and
  the tool is `django.utils.translation.ngettext`, following the existing precedent in
  `courses/views_review.py:208`:
  *"%(n)s internal link had no target in this archive and was turned into plain text."* /
  *"%(n)s internal links had no target in this archive and were turned into plain text."*

Both go into both catalogs via `makemessages -l pl -l en --no-obsolete`, with fuzzy entries cleared
properly (both the `#, fuzzy` line and the `#| msgid` comment). Both `.mo` files are regenerated.
`tests/test_i18n_po_health.py` requires a real Polish translation for each — an empty msgstr turns
`test_pl_has_no_untranslated_msgid` red — and Polish has three plural forms, so every form must be
filled.

Because the import warning is a **separate** message rather than a clause folded into the existing
success strings, no existing msgid changes and none is orphaned. The existing line in
`node_confirm_delete.html` — `This removes {{ d }} descendant node(s) and {{ e }} element(s).` — is
left exactly as it is; correcting its `(s)` suffixes is an unrelated i18n fix, and bundling it would
put an unrelated msgid change in this diff.
