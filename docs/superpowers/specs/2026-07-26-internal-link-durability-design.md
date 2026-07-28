# Internal content links — durability

Part 2 of three.

- Part 1, `2026-07-26-internal-content-links-design.md` — the link dialog and the
  `/courses/n/<pk>/` permalink.
- **Part 2 (this)** — the registry and rewrite helpers, links surviving an *uploaded-archive*
  export→import, and a warning before a linked node is deleted.
- Part 3, `2026-07-26-internal-link-cutover-design.md` — links surviving `migrate_course_content`,
  the mat-pp production cutover. Depends on this spec.

Part 1 ships without either. This part makes the Studio export/import UI correct; **the production
cutover needs part 3 as well**, and running it on part 2 alone would silently flatten every
cross-part link.

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
| `courses/transfer/importer.py` | `_create_elements` returns what it created; `on_missing` + `report` threaded through the entry points; the rewrite post-pass |
| `courses/builder.py` | *unchanged* — `materialize_duplicate` defaults to `on_missing="keep"`, so `duplicate_unit` calls it exactly as it does today |
| `courses/views_transfer.py` | a second, separate `messages.warning` on both import paths when links were flattened |
| `courses/views_manage.py` | `counts["inbound_links"]` in `node_delete`'s GET branch |
| `templates/courses/manage/node_confirm_delete.html` | the warning sentence |
| `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py` | the two hard-coded `FORMAT_VERSION == 5` assertions (one is also a test *name*) |
| `tests/test_table_transfer.py` | line 265's comment "(4 <= FORMAT_VERSION=5)" goes stale — comment-only fix, the test itself still passes |
| `tests/test_richtext.py` | **new** — registry, scanner and rewrite cases |
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
two must agree — a prefix match here would make the delete count and the rewrite disagree with **the
dialog** about what an internal link even is. `/courses/n/12/?x=1` is therefore not an internal link
to the dialog, to the rewrite, or to the delete count.

Part 1's CSS marker is deliberately *not* cited as agreeing: it ships as the prefix selector
`.el a[href^="/courses/n/"]`, so `/courses/n/12/?x=1` does render with the internal-link glyph while
being an ordinary URL everywhere else. That is a benign over-match — a marker on a link that still
works — and belongs in part 1's acknowledged-misclassification list rather than being smoothed over
here.

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

**The open-tag scanner must be attribute-aware — `<a[^>]*>` is not safe.** An earlier draft of this
spec asserted that `nh3.clean` entity-escapes `>` inside attribute values, so a `title="a > b"` could
not truncate the match, and confined the risk to two unsanitised stems in a hand-crafted archive.
**That is false.** Measured against the real sanitiser:

```text
sanitize_html('<a title="a > b" href="/courses/n/1/">x</a>')
  -> '<a title="a > b" href="/courses/n/1/">x</a>'      # unchanged; > NOT escaped
re.findall(r'<a[^>]*>', …)  ->  ['<a title="a >']       # the href falls OUTSIDE the match
sanitize_html('<a href="/courses/n/1/?q=a>b">y</a>')
  -> '<a href="/courses/n/1/?q=a>b">y</a>'              # also unchanged
```

`title` is an allowed `<a>` attribute, so this is reachable from ordinary sanitised rich text — a
paste into the RTE, or part 1's explicitly supported no-JS hand-typed HTML — on *every* registry
field. It is not a hand-crafted-archive edge case, and the exposure is an order of magnitude wider
than that framing suggested.

The scanner therefore consumes attribute values properly: for each `<a`, alternate over
`"…"` / `'…'` / bare values until an unquoted `>`, so a `>` inside a quoted value can never terminate
the tag. Only then is the `href` value located and rewritten.

**Fail-closed, with the triggering conditions named** — "cannot match cleanly" has to be a decidable
condition, not a disposition. The whole *body* is returned byte-identical and contributes 0 to the
count when the scanner meets any of:

- an unterminated quoted attribute value;
- an `<a` with no unquoted `>` before end of input;
- on the unwrap path, an open tag with no matching `</a>`. This is reachable: `_build_fill_gate` and
  `_build_switch_gate` do not re-sanitise their stems on the import path, so a hand-crafted archive
  can carry unbalanced markup.

Note the naive scanner does **not** hit any of these on the `title="a > b"` case — it produces a
syntactically clean match of the wrong span and silently gets the answer wrong. That is exactly why
the scanner has to be attribute-aware rather than merely defensive, and why §Testing exercises both
attribute orders.

**Drift guard.** A new element type with a rich-text body that nobody adds here would silently
escape both features. The guard greps the **whole `courses/` package** — not a hand-maintained file
list — excluding `courses/tests/` and `sanitize.py`'s own definition. The repo-wide baseline today is
**14 call sites across 4 files**: `models.py` ×6, `element_forms.py` ×6, `transfer/importer.py` ×1
(`_build_guess_number`), and `templatetags/courses_extras.py` ×1 — the `|sanitize` filter, which is a
**render-time** re-sanitise, not a storage location, and is recorded as such rather than omitted.
(`fillblank.py:3` mentions `sanitize_html(` in a docstring and must not be counted; the grep excludes
comment and docstring lines.)

An earlier draft allowlisted three files. That was wrong twice over: it missed
`courses_extras.py` outright, and a fixed list cannot see a call site added in any other module —
`courses/switchgrid.py` already establishes that helper modules do sanitising work. A package-wide
grep is what makes the guard self-maintaining, which is the only reason it is worth having.

It records a **multiset of `(file, qualname, assignment target)` entries** — `qualname` being the
dotted `Class.method`, and the structure counting multiplicity rather than deduplicating.

Both refinements are load-bearing, and an earlier draft got the unit wrong twice. A `(file, def)`
pair would be byte-identical after a third sanitised field is added to `QuestionElement.save()`,
which already holds two calls. But `(file, def, target)` is *also* too coarse — measured, the 14
sites collapse to just **8 distinct triples**, because def names and targets repeat across classes:

```text
(models.py, save, self.body)              <- TextElement, SpoilerElement, CalloutElement   (3)
(element_forms.py, clean_stem, clean)     <- FillGate, GuessNumber, FillBlank, DragFillBlank (4)
(element_forms.py, clean, clean_stem)     <- SwitchGate, SwitchGrid                          (2)
```

So adding a new element type the cheapest way — copy `TextElement`: a `body` field plus
`def save: self.body = sanitize_html(self.body)` — yields a triple **already in the set**, and the
guard stays GREEN for exactly the case it was introduced to catch. Including the class disambiguates
those. Multiplicity is kept for the narrower case the qualname does not separate: two `sanitize_html`
calls sharing one qualname *and* one target inside a single method — as a second
`self.body = sanitize_html(self.body)` in the same `save()` would be.

The baseline is therefore stated as **14 entries over 14 distinct keys**, and the test asserts the
whole structure, not its length.

**The third component is defined for non-assignment sites**, so the baseline is reproducible rather
than implementation-dependent: it is the assignment target when the call's result is assigned
(`self.body`), and `None` otherwise. `courses_extras.py:117` is `return mark_safe(sanitize_html(v))`
— no target, so `None`. `importer.py:767` passes the call as a keyword argument inside
`GuessNumberElement.objects.create(...)`; a call nested in an expression records `None` too, never
the enclosing statement's target, since `obj` is a different notion from an attribute target.

The guard classifies a new site to choose its message, and the discriminator is **not** the file —
`element_forms.py` holds both kinds. It resolves the enclosing form class's `Meta.model` and tests
membership in `CONCRETE_QUESTION_MODELS`:

- in it **and** the sanitised field resolves to `stem` or `explanation` (e.g.
  `FillBlankQuestionElementForm.clean_stem`) → covered automatically by the comprehension; update the
  expected structure, leave `RICH_TEXT_FIELDS` alone. Both halves are required: the comprehension
  covers only those two field names, so a new sanitised `hint` on an existing question model would
  pass a model-only test and be told "covered automatically" while remaining invisible to the
  registry — the same wrong-advice failure the non-question branch is careful to avoid;
- not in it, or unresolvable (e.g. `FillGateElementForm.clean_stem`, `SwitchGateElementForm.clean`)
  → `RICH_TEXT_FIELDS` needs an entry **or a documented exclusion**. The softer wording is required,
  not politeness: `SwitchGridElementForm.clean` is exactly such a site today, and §1 spends a page
  arguing it must *not* get an entry. A message promising "add it to the registry" would give the
  next JSON-nested rich-text field precisely the wrong advice.

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
already holds `join.content_object`, so `iter_rich_text(instance)` applies directly — placed **after**
the existing `if join.content_object is None: … continue` guard (`export.py:545`, the tolerant-export
path for a concrete row that has gone). A broken join contributes no link targets, and
`iter_rich_text(None)` would raise there.

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
| `import_course` / `import_subtree` (uploaded archive, via the views) | `unwrap` | the pk means nothing here, and leaving it risks silently linking to an unrelated node that happens to occupy that pk |
| `materialize_duplicate` (same install, via `duplicate_unit`) | `keep` | those pks still resolve; flattening a working link would be a regression |
| `migrate_course_content` (the management command) | *see part 3* | one part per archive, so a cross-part target is in no archive — its own spec |

**The `mat-pp` cutover is part 3, not this spec.** `migrate_course_content` is a fourth caller of
`import_subtree`, and it moves one top-level part at a time — so a cross-part link has no resolvable
target in any single archive and the `unwrap` default above would flatten it. Handling that needs a
bundle-level map, a third `on_missing` value (`defer`), and a deferred single rewrite pass; all of it
lives in `2026-07-26-internal-link-cutover-design.md`, which depends on this spec. **Do not run the
production cutover on part 2 alone.**


**Threading the policy and the count without breaking callers.** The three entry points take two new
**keyword** arguments: `on_missing` and an optional `report` dict, which — when supplied — receives
`{"flattened_links": n}`.

The table above is the **default** on each entry point: `import_course` and `import_subtree` default
to `unwrap`, `materialize_duplicate` to `keep`. No caller passes it explicitly — `duplicate_unit`
simply calls `materialize_duplicate` as it does today. Defaults rather than required arguments,
because the policy is a property of the entry point, not of the call site, and a required argument
would put the decision where it could drift.

The `report` out-parameter exists specifically to avoid changing the return types. `import_course`
returns a `Course` and `import_subtree` a `ContentNode`, and **nine test modules** consume those
returns directly — eight under `tests/` (`test_gallery_transfer`, `test_reveal_gate_transfer`,
`test_slideshow_transfer`, `test_table_transfer`, `test_tabs_transfer`, `test_transfer_import`,
`test_transfer_subtree`, `test_transfer_views`) plus `courses/tests/test_spoiler_transfer.py`, which
lives in the other test location — several through shared local helpers whose own contracts would
change in turn. Add the management command as a tenth caller. Returning a tuple would redden all of
them for no gain; an ignorable keyword costs nothing.

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
node or any of its descendants. The query returns *concrete* rows (`TextElement`, …), and counting
those is the same number because each concrete element row carries exactly one `Element` join (the
GFK is effectively 1:1, which is why `SpoilerElement.join_row()` can take `.first()`). Elements, not anchors: two anchors in one body pointing at two doomed
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
- **A bundle exported before this change**, whose `bundle-manifest.json` has no `link_nodes` key →
  read with `manifest.get("link_nodes", {})`, so no part rewrites and the operator gets the flattened
  count rather than a raw `KeyError`. `_read_bundle_manifest` validates only `part_count`, so such a
  bundle passes the gate and must not traceback afterwards.
- **A body meeting one of the three fail-closed conditions** (unterminated quoted value; `<a` with no
  unquoted `>`; unwrap with no matching `</a>`) → returned byte-identical, nothing counted. Fail
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
- **Raw `>` inside an anchor attribute is rewritten *correctly*** — not merely "not mangled". Both
  attribute orders are exercised: `<a title="a > b" href="/courses/n/1/">` and
  `<a href="/courses/n/1/" title="a > b">`. The first is the one a naive `<a[^>]*>` gets silently
  wrong (it matches `<a title="a >`, leaving the href outside the match, so the link is neither
  rewritten nor counted), and it passes any test phrased as "returned byte-identical" — which is why
  the assertion must be on the rewritten href, not on the absence of damage. An `href` containing a
  raw `>` (`/courses/n/1/?q=a>b`) is covered too; it survives the sanitiser unescaped.
- **Fail-closed** applies to the three named conditions only — an unterminated quoted value, an `<a`
  with no unquoted `>`, and (unwrap path) an open tag with no matching `</a>`. Each returns the body
  byte-identical and contributes 0.
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

**The cutover path** is covered by part 3's own tests
(`2026-07-26-internal-link-cutover-design.md`), which exercise `migrate_course_content` end to end.


**Delete warning**

- Count is 0 with no links; counts **elements**, not anchors — two anchors in one body pointing at two
  doomed nodes count once; counts links to a *descendant* of the node, not just to the node itself;
  ignores links from another course; and **ignores links originating inside the doomed subtree**.
- The confirm page shows the sentence only when the count is non-zero.
- Query count pinned as a concrete whole-request total. The expected shape is stated so the number is
  derived rather than recorded from the first run: **one query per registry model (16)**, plus one
  per descendant depth level from `ContentNode._subtree_node_ids()` **plus one** for the terminating
  empty frontier (its breadth-first loop always runs a final query that returns nothing, so a leaf
  costs 1), plus the pre-existing per-node `_descendant_count` / `_element_count` walks, plus the
  view's own fixed queries — auth/session, the course resolve and permission check in
  `_require_manage`, and `get_node_or_404`. Without that last group the enumeration cannot be summed
  to the pinned number, which pushes the implementer straight back to recording the first run; part 1
  names the same fixed group for `link_picker`.
- The fixture must hold **at least two link-bearing elements of the same registry model OUTSIDE the
  doomed subtree** — among the rows the scan actually reads. Putting them *inside* would make the
  guard vacuous: the scan excludes the subtree, so those rows are never queried per-model at all and
  could not distinguish one-query-per-model from one-query-per-element. The subtree side needs only
  the link targets.

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
