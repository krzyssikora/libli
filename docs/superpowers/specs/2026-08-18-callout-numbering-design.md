# Callout Numbering

## Purpose

In the legacy matematyka course, callouts that carried questions and examples were
numbered consecutively within a unit. `libli` has no such numbering: every callout
renders its kind label alone (`Przykład`, `Zadanie`, `Uwaga`), so a unit with four
examples shows the word `Przykład` four times with nothing to refer to them by.

The student should instead see one running sequence per unit, shared across kinds, with
unnumbered kinds skipped rather than consuming a slot:

```
Przykład 1
Zadanie 2
Uwaga            <- not numbered, does not consume a number
Ważne 3
Zadanie 4
```

### Measured starting state (local `libli` DB, 2026-08-18)

| Measurement | Value |
| --- | --- |
| `CalloutElement` rows | 369 |
| ... in course `mat-pp` | 365 (the remaining 4 are `demo-course`) |
| Units containing at least one callout | 167 |
| Callouts per unit | median 2, max 9 |
| By kind | task 177, warning 97, example 62, tip 21, note 12 |
| Rows with a custom `heading` | **0** |
| Callouts nested inside a container | 36 (10%) |
| ... by parent | tabs 24, spoiler 9, two-column 3 |

Two of those numbers drive the design.

**Zero custom headings.** Every callout in the repository renders its kind's default
label today, so the rule chosen for custom headings (§4) changes nothing about existing
content. It still has to be decided, because the field exists and authors can use it.

**Ten percent are nested, and 24 of those sit inside tabs.** The tabs are used as
parallel exercises, and their labels already carry numbers:

```
unit 349   tabs: ['Zadanie 1.', 'Zadanie 2.', 'Zadanie 3.']   each holding one task callout
unit 359   tabs: ['1', '2', '3', '4', '5']                    same shape
unit 193   tabs: ['kwadrat sumy', 'kwadrat różnicy', ...]      each holding one example callout
```

Nested callouts still participate in the sequence (decision D3), so unit 349 will ship
with tab `Zadanie 1.` containing `Zadanie 4` until the author unticks those callouts.
That is accepted deliberately: one rule with no exceptions, and roughly 24 unticks
across ~10 units. The visible-sequence consequences of numbering inside containers that
show one child at a time are recorded as R4 (§10).

## Decisions

These were settled during brainstorming. Do not re-litigate them.

- **D1 — one shared sequence per unit, across all kinds.** Not one counter per kind.
  `Przykład 1, Zadanie 2, Ważne 3` is a single run.
- **D2 — per-kind defaults.** Example, Task and Important default to numbered; Note and
  Tip default to unnumbered. A per-callout checkbox overrides either way.
- **D3 — every numbered callout counts, wherever it sits.** Depth and container type are
  irrelevant to the walk. Nesting affects nothing except reading order.
- **D4 — the number attaches to the kind label; a custom heading follows it.** This
  changes the "custom heading replaces the label" behaviour for numbered callouts only.
- **D5 — existing rows get the kind default and nothing cleverer.** No special-casing of
  callouts inside tabs in the backfill.
- **D6 — numbers appear wherever the unit renders as a whole.** In practice that is the
  student lesson page, the student quiz page, and the editor preview — the three surfaces
  §5 wires. "Print" is not a fourth surface: there is no unit print view in the repo, only
  `@media print` rules, so browser-printing a lesson renders through the lesson site and
  needs no separate wiring. The editor's collapsed row list is deliberately unchanged.
- **D7 — no trailing period.** `Przykład 3`, not `Przykład 3.`

## Non-goals

- Numbering any element type other than `CalloutElement`.
- Numbering that continues across units, or restarts per section/chapter.
- Cross-references ("see Example 3") or anchors/links to a numbered callout.
- Removing the manual numbers already embedded in tab labels and body text.
- Showing numbers in the editor's collapsed element list (D6).
- Auto-flipping the checkbox in the editor when the author changes the kind. See
  "Deferred" below.

## 1. Data model

`courses/models.py`:

```python
class CalloutElement(ElementBase):
    ...
    numbered = models.BooleanField(default=True)
```

No `blank=True`. Django's `models.BooleanField.formfield` hard-codes `required=False`
(verified, both with and without `blank`), because an unchecked checkbox transmits
nothing. Adding `blank=True` would be noise.

Beside the existing `KIND_DEFAULT_HEADING` (`courses/models.py:569`), and for the same
reason — it must be built after the class body so it can read the enum:

```python
KIND_DEFAULT_NUMBERED = {
    CalloutElement.Kind.EXAMPLE.value: True,
    CalloutElement.Kind.TASK.value: True,
    CalloutElement.Kind.WARNING.value: True,
    CalloutElement.Kind.NOTE.value: False,
    CalloutElement.Kind.TIP.value: False,
}
```

**Exactly one runtime caller reads it:** the importer's default for pre-v13 archives
(§7). The editor form does *not* read it — a new callout is always created as `example`,
whose default is `True` and therefore indistinguishable from the model field default, so
a form-initial hook would be unobservable and untestable. The form takes the model
default (§6).

The backfill migration (§2) encodes the same decision but as a frozen literal, not an
import — see there for why.

An invariant test asserts the constant's key set equals
`{k.value for k in CalloutElement.Kind}`, so a sixth kind cannot be added without a
decision here.

`display_heading` is refactored so the per-kind fallback exists exactly once, and a new
`kind_label` property exposes the label without the custom-heading fallback:

The name collides with an unrelated existing symbol: `kind_label` is already a registered
`simple_tag` for **node** kinds (course/chapter/section) at
`courses/templatetags/courses_manage_extras.py:266`, used by `_add_affordance.html:29` and
`_structure_legend.html:4`. There is no functional clash — a model property and a template
tag resolve differently — but a grep now returns two unrelated concepts, so carry a
one-line comment on the property saying so.

```python
@property
def kind_label(self):
    # String fallback key ("example"), NOT bare `Kind.EXAMPLE` -- `Kind` is a nested
    # class and would resolve against module globals (undefined -> NameError).
    return KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])

@property
def display_heading(self):
    return self.heading or self.kind_label
```

The existing two-line comment at `courses/models.py:514-515` explaining the string
fallback key moves onto `kind_label` with the body it documents. Do not leave a second
copy of that fallback expression in `display_heading` — two copies of that subtlety will
drift. `display_heading` keeps its current behaviour and its current caller
(`courses/templatetags/courses_manage_extras.py:158`, the editor row summary — unchanged
per D6).

## 2. Migration

One migration file, two operations, in this order:

1. `AddField` for `numbered` (`default=True`).
2. `RunPython` backfill, through the historical model
   (`apps.get_model("courses", "CalloutElement")`, never the live class — the live
   `save()` re-sanitises `body`, and a bulk `.update()` on the historical model avoids
   touching it at all):
   `Callout.objects.filter(kind__in=["note", "tip"]).update(numbered=False)`.

Expected effect on the local DB: 33 rows set to `False` (12 note + 21 tip), 336 left
`True`.

The backfill **must not import `KIND_DEFAULT_NUMBERED` from `courses.models`** — a
migration that reads a live module constant silently changes meaning when that constant
is later edited. The false-kind list is inlined as a literal (`["note", "tip"]`) with a
comment naming the constant it was copied from, matching how the repo's other data
migrations pin their values.

Reverse operation is `RunPython.noop`: the `AddField`'s own reversal drops the column, so
there is nothing for the data step to undo. (Not a raising `unapply` — those cannot be
tested, because `unapply()` raises before running anything.)

`makemigrations --check` must be clean, and the migration must be re-checked against the
graph head before merge: a restore pinned to a node that a later migration supersedes runs
backwards and fails intermittently under `-n auto`.

## 3. The numbering pass

New module `courses/numbering.py`, one public function:

```python
def callout_numbers(node) -> dict[int, int]:
    """{Element.pk: number} for every numbered callout in `node`, in document order."""
```

It walks the unit's element tree depth-first in **reading order**, assigning consecutive
integers starting at 1 to callouts whose `numbered` is `True`. Unnumbered callouts are
visited (their children still count) but do not consume a number.

### Contract

- `node` is a **unit** `ContentNode`. Every call site passes one.
- A node with no elements — a section or chapter node, or an empty unit — returns `{}`.
  This falls out of `node.elements` being empty and needs no type check.
- **Early-out on units with no callouts.** The call is unconditional at all four sites, so
  without this a callout-free unit containing three tabs containers pays the full descent
  on every student and editor render — and most units have no callout at all (167 of them
  do). The function therefore begins with one indexed existence check on
  `node.elements.filter(content_type=<CalloutElement ct>)` and returns `{}` when it is
  empty. Note `node.elements` is unit-wide, **not** `parent__isnull=True`, so a unit whose
  only callout is nested is correctly *not* short-circuited.
- **The descent needs no cycle or depth bound, and must not add one.** The walk starts at
  `parent__isnull=True` roots and descends via `parent`; `Element.parent` is
  single-valued, so every node inside a corrupt parent cycle has a non-null parent and is
  therefore never a root — the reachable subgraph is acyclic by construction and cannot
  recurse forever. This is the same argument the editor's own unbounded recursion already
  relies on, stated in `templates/courses/manage/editor/_element_row.html` ("the reachable
  subgraph is acyclic by construction… The child-row recursion is deliberately
  UNBOUNDED"). `builder.element_depth`'s `MAX_NEST_DEPTH` bound is not a counter-example:
  it walks *upward* through `parent`, the one direction where a cycle is reachable.
- The function **re-queries its own roots**; it does not accept a pre-materialised element
  list, even though all four call sites have just built one. The cost is one duplicate
  roots query per render, and the benefit is that the pinned query count (§8) is a
  property of the function rather than of each caller — otherwise two implementers make
  different choices and the number is not reproducible.
- **Pre-order.** A container takes its own number *before* its children are walked. This
  matters because `CalloutElement` is itself a container (`courses/builder.py:204`), so a
  numbered callout may contain a numbered callout, and the outer heading precedes the
  inner one in the render. Pinned by a fixture, not left to "document order implies it"
  (§8.1).
- A row whose `content_object` is `None` (a dangling GFK — a real, handled condition in
  this repo) is **skipped**: not counted, not descended into, and *not* an error. This
  matches `render_element`, which returns `""` for such a row
  (`courses/templatetags/courses_extras.py:50-52`), and `build_element_export`, which
  records them as `problems` (`courses/builder.py:961-972`). The raise-on-unknown rule
  below must not fire on `NoneType`, or a single damaged row 500s the student page.

### Why the walk must use the containers' own accessors

Document order is **not** `order_by("order", "pk")`. Inside a tabs container, the children
of all tabs are interleaved in `order` — unit 349's real rows read
`t000000, t000001, t000002, t000000, t000001, ...` — so the reading order is *tab index,
then order within that tab*. The same is true of two-column (column index) and
before/after (slot index).

Re-deriving that ordering in the walk would create a second implementation of reading
order that drifts from the render the first time a container's grouping changes. The walk
therefore descends through the accessors the templates themselves consume:

| Container | Accessor | Shape |
| --- | --- | --- |
| `SpoilerElement` | `resolved_children()` | `[Element]` |
| `CalloutElement` | `resolved_children()` | `[Element]` |
| `TabsElement` | `resolved_tabs()` | `[(tab_dict, [Element])]` |
| `TwoColumnElement` | `resolved_columns()` | `[(col_dict, [Element])]` |
| `BeforeAfterElement` | `resolved_slots()` | `[(slot_id, [Element])]` |

Dispatch is on membership in `builder.CONTAINER_MODELS` (itself derived from
`_CONTAINER_REGISTRY`), read as a **module attribute** — `from courses import builder`
then `builder.CONTAINER_MODELS` at call time, never
`from courses.builder import CONTAINER_MODELS`. A from-import freezes the value at import
time, so §8.10's raise test (which patches the attribute with a sixth class) would fail
against a *correct* implementation. This repo has been bitten by exactly this and
documents it at `courses/views_manage.py:1858-1861` for `MAX_NEST_DEPTH`.

The accessor per type is a module-level mapping keyed by model
class; a container class in `CONTAINER_MODELS` but absent from the mapping **raises**,
so a sixth container type cannot be added without a decision here rather than silently
having its children skipped. That raise path is unreachable with today's five types and
is therefore pinned by its own test (§8.10), not left to chance.

Inheriting the accessors also inherits their quirks, which is the point — each of the
three decides which callouts get numbered, and in every case the render and the numbering
cannot disagree because they consume the same function:

- `resolved_tabs` **skips** a child whose `tab_id` resolves to no tab
  (`courses/models.py:1865`), so such a callout is invisible and unnumbered alike.
- `resolved_slots` **appends** an unknown-`tab_id` child to the *before* bucket rather than
  dropping it (`courses/models.py:597-599`), so an orphaned child is rendered — and
  therefore numbered — in the before slot.
- `resolved_columns` uses the destructive read-side `normalize_data` with its 2..4 render
  clamp, so a fifth column's children are dropped from both.

Roots are:

```python
node.elements.filter(parent__isnull=True)
    .order_by("order", "pk")
    .select_related("content_type")
    .prefetch_related("content_object")
```

The `select_related`/`prefetch_related` are not optional: without them the walk issues one
query per top-level element merely to learn its type — a per-render N+1 on the student
path, which is precisely the cost R3 claims to bound.

### Query cost

Per non-empty container: `join_row()` + `children` + **one prefetch query per distinct
`content_type` among those children**. Every accessor ends in
`.prefetch_related("content_object")`, and prefetching a `GenericForeignKey` costs one
query per distinct content type in the result set — so the floor is three, not two, and a
tab holding a text, a math and a callout costs five.

Two costs are avoidable in principle and neither is avoided. `join_row()`
(`self.elements.order_by("pk").first()`) re-fetches the very join row the walk is already
descending from. And the GFK prefetch is wasted **only on leaf non-callout children** —
the walk genuinely needs the concrete instance for every container (to call its accessor)
and for every callout (to read `obj.numbered`), so "the walk only needs types" is false
and must not be used as a reason to drop `prefetch_related("content_object")` from the
roots query; doing so reintroduces exactly the per-element N+1 forbidden above. Avoiding
either cost means bypassing the accessors, which is the one thing this design refuses to
do (see above). Both are accepted explicitly as the price of ordering agreement.

The roots query is accounted the same way: one query plus one per distinct top-level
content type.

Because the total is a function of *type diversity*, not just container count, no
arithmetic in this spec should be treated as the expected number. The invariant is the
**shape** — roots + (`join_row` + `children` + per-type prefetch) per container — and the
value is to be measured on the §8 fixture and recorded there once observed. An implementer
who derives an `assertNumQueries` constant from prose arithmetic will get a red test they
cannot explain.

## 4. Render

`CalloutElement.render` reads the map out of the `page` dict it already receives and puts
a plain integer (or `None`) in its template context:

```python
numbers = (page or {}).get("callout_numbers") or {}
"number": numbers.get(element.pk) if element is not None else None,
```

**The `element is not None` guard is load-bearing, not defensive noise.**
`CalloutElement.render`'s signature is `render(self, *, element=None, ...)`, and a bare
`element=None` render is a real, tested call shape:
`courses/tests/test_callout_render.py` calls `CalloutElement(...).render()` with no
element at **eight** sites (lines 17, 24, 32, 33, 42, 56, 61, 80), and
`courses/tests/test_render_seam.py:72` exists specifically to pin that such a render must
not raise. Without the guard, `element.pk` raises
`AttributeError: 'NoneType' object has no attribute 'pk'` and those tests go red. A
join-row-less callout has no unit-wide position, so `None` is the correct number for it.

The lookup happens in Python because a Django template cannot index a dict by a variable
key without a filter.

`templates/courses/elements/calloutelement.html:5` becomes a **single line** — Django does
not strip template whitespace, so a multi-line `{% if %}` would insert newlines and
indentation into the rendered heading and break the byte-identity guarantee below:

```django
<span class="callout__heading">{% if number %}{{ el.kind_label }} <span class="callout__number">{{ number }}</span>{% if el.heading %}. {{ el.heading }}{% endif %}{% else %}{{ el.display_heading }}{% endif %}</span>
```

Resulting header text:

| | today | numbered | unnumbered |
| --- | --- | --- | --- |
| no custom heading | `Przykład` | `Przykład 3` | `Przykład` |
| custom heading `Suma ciągu` | `Suma ciągu` | `Przykład 3. Suma ciągu` | `Suma ciągu` |

The unnumbered branch is today's expression verbatim with no surrounding whitespace added,
so an unnumbered callout renders byte-identically to the current build — including the
"custom heading replaces the label" behaviour, which changes for numbered callouts only
(D4).

No trailing period after a bare number (D7). The period appears only as the separator
before a custom heading.

The number is wrapped in its own `<span class="callout__number">` so it can be styled
independently and so a test can pin it without matching the surrounding translated label.
No new CSS is required; a style hook existing without a rule is intentional.

## 5. Context wiring

`callout_numbers` reaches the template through four context sites plus one barrier.

**The four sites:**

| Site | Function | File |
| --- | --- | --- |
| Lesson unit | `build_lesson_context` | `courses/views.py` (~`:339`) |
| Quiz unit | `build_quiz_context` | `courses/views.py` (~`:1301`) |
| Editor, fragment swap | `_render_editor_fragments` | `courses/views_manage.py` (~`:1853`) |
| Editor, full page load | `_editor_page` | `courses/views_manage.py` (~`:1915`) |

Each adds `"callout_numbers": callout_numbers(...)` to the context it **builds**. Only the
two `views.py` builders return a context dict; `_render_editor_fragments` and
`_editor_page` call `render(request, template, {...})` with an inline dict and return an
`HttpResponse`, and their parameter is named `unit`, not `node` — so the editor sites read
`callout_numbers(unit)`. There is no single choke point that covers all four; see R1.

The two editor sites are **different paths, not a builder and a duplicate**:
`_editor_page` renders the whole editor on first load, `_render_editor_fragments` renders
the two swappable `[data-scope]` panes for every subsequent 200/409/422. Wiring only the
page builder makes the first load look perfect while every add/save/move/paste silently
drops the numbers; wiring only the fragment builder inverts it. Both directions need a
test (§8.4).

**The barrier.** `render_element` (`courses/templatetags/courses_extras.py:34`) is a
context barrier: only containers receive `page`, and `page` is rebuilt from named keys at
every level. `callout_numbers` becomes a seventh key, read context-only with an `or {}`
fallback — the same shape as `feedback_ancestor_pks`, not the parameter-or-context shape
the question-state keys use:

```python
callout_numbers_map = context.get("callout_numbers") or {}
...
extra["page"] = {
    ...,
    "callout_numbers": callout_numbers_map,
}
```

Because each container template merges `**(page or {})` into its own context and the
recursive `render_element` reads from that context, the map propagates to any depth
without further plumbing.

Two edits ride along with this one:

- `courses/templatetags/courses_extras.py:53-56` reads *"Six explicit statements, one per
  key of the `page` dict below, so every name stays greppable."* That count becomes seven.
  The comment is deliberately invariant and this repo has tests that regex raw source, so
  leaving it stale is a live hazard, not cosmetics.
- `courses/tests/test_nested_question_nojs_feedback.py:641-650` asserts
  `captured.keys() == {...}` against the full six-key set, with an in-test comment
  explaining why the full set rather than a membership check
  (*"`\"mode\" not in captured` is green when `page` never arrived at all"*). Add
  `"callout_numbers"` to that set. **Keep it a full-key-set equality** — relaxing it to a
  subset check to make it pass would destroy the property it exists to hold.

**Editor fragment renders.** The editor swaps whole `[data-scope]` panes, and the preview
pane is one of them, so the preview always re-renders from `preview_elements` with the map
present. A single-element fragment render carries no map and therefore no number; that is
correct, because a lone element has no unit-wide position to report.

## 6. Editor form

Three changes, none of which the form machinery does for us.

**`CalloutElementForm`** (`courses/element_forms.py:263`): `Meta.fields` becomes
`["kind", "numbered", "heading", "body"]`. Nothing else on the form class changes — no
`__init__` hook, no per-kind initial (§1).

**`templates/courses/manage/editor/_edit_callout.html`** is hand-written HTML: it emits
`<select name="kind">`, `<input name="heading">` and `<textarea name="body">` directly and
never renders `{{ form.<field> }}`. The checkbox must therefore be authored by hand, and
placed immediately after the Kind `<label>` and before Heading, because it qualifies the
kind:

```django
<label class="el-editor__check">
  <input type="checkbox" name="numbered" {% if form.numbered.value %}checked{% endif %}>
  {% trans "Number this callout" %}
</label>
```

The class is `el-editor__check` (`courses/static/courses/css/editor.css:153` —
`inline-flex`, centred, `gap: var(--space-2)`), copied from
`templates/courses/manage/editor/_edit_shorttextquestion.html:19-22`, which is the same
case: a model-backed boolean on a hand-written element-editor partial. Do not invent a
class name; there is exactly one precedent and this is it.

`form.numbered.value` resolves to the posted value on a bound form and to the instance
value on an unbound one, so a failed validation round-trip preserves what the author
ticked.

**Two existing tests post without the key**, and both silently start producing
`numbered=False` rows the moment §6 lands. Because an unchecked checkbox transmits
nothing, such a POST is indistinguishable from a deliberate untick. Update both to assert
the resulting `numbered` explicitly, so the behaviour is pinned rather than incidental:

- `courses/tests/test_callout_form.py::test_valid_full_save` — form level, posts
  `{"kind", "heading", "body"}`.
- `courses/tests/test_callout_authoring.py::test_save_round_trips_kind_heading_body`
  (lines 50-68) — **the real `manage_element_save` endpoint** with `element: "new"`. This
  is the stronger evidence for R2 and the closer analogue of what a browser does: it is
  the production create path, and after this change it creates unnumbered callouts while
  staying green. State the expected value for the create-from-endpoint case explicitly.

See R2.

## 7. Transfer

`_val_callout` (`courses/transfer/payloads.py:211`) currently calls
`_exact_keys(data, ["kind", "heading", "body"], ...)`, which rejects any unknown key —
so a new key is a hard break for every existing archive unless it is introduced with the
optional-key pattern already used for `size` (`:139`) and width/height (`:170`):

1. Seed the key **before** `_exact_keys`, so a pre-v13 archive imports with per-kind
   defaults — matching the backfill migration exactly, so an archive exported before this
   feature and a database migrated by it agree.

   The seeding must not read `kind` naively. `_exact_keys` runs first in the current body
   (`payloads.py:214`) precisely so that `check_str(data["kind"], ...)` at `:215` can
   assume the key exists and is a string. Seeding ahead of it inverts that: at this point
   `kind` may be **absent** (today a clean `TransferError` from `_exact_keys`; a bare
   `data["kind"]` would raise `KeyError` first) or a **non-string** — and a list or dict
   key makes `KIND_DEFAULT_NUMBERED.get(...)` raise `TypeError: unhashable type`, an
   unwrapped exception where this file's contract is a translated `TransferError`. The
   two cited precedents do not have this property: `setdefault("size", "full")` and
   `setdefault("width", None)` depend on no other key, so this step is **not** simply
   "the existing pattern". Required form:

   ```python
   _kind = data.get("kind")
   data.setdefault(
       "numbered",
       KIND_DEFAULT_NUMBERED.get(_kind, True) if isinstance(_kind, str) else True,
   )
   ```

   The lookup must be total and must not raise for any JSON value. A validation test
   covers an archive whose callout payload omits `kind` entirely, asserting it still fails
   with the `TransferError` from `_exact_keys` and not a `KeyError`.

   `KIND_DEFAULT_NUMBERED` is imported on the **existing function-local** line
   `from courses.models import CalloutElement` (`payloads.py:212`). That import is local
   on purpose, to avoid an import cycle; a module-level import of the new constant would
   reintroduce exactly the cycle it avoids.
2. Add `"numbered"` to the `_exact_keys` list.
3. Validate it with the file's existing helper: `check_bool(data["numbered"], "numbered")`
   (used at `payloads.py:368`, `:410`, `:483`, `:621`). Not a hand-rolled `isinstance`
   check, which would produce a differently-worded error.
4. **Build it.** `_build_callout` (`courses/transfer/importer.py:556`) constructs
   `CalloutElement(kind=..., heading=..., body=...)` and must gain `numbered=...`.
   Without this step the field is validated on the way in and written on the way out but
   **discarded at construction**, so every import silently resets it to the model default.
5. The exporter writes `numbered`: `_ser_callout` (`courses/transfer/export.py:122`),
   registered as `"callout": (CalloutElement, _ser_callout)` at `:482`.

**Duplicate and paste ride on this.** `duplicate_element` and `paste_element` are not
separate copy paths: both round-trip the subtree through
`build_element_export` → `graft_elements` (`courses/builder.py:965`/`:976` and
`:1075`/`:1084`). So step 4 is not only about archive import — without it, duplicating or
copy-pasting an unnumbered callout inside the editor silently re-numbers it. This is the
highest-traffic consequence of the transfer work and gets its own mutant (§8.6c).

`FORMAT_VERSION` goes 12 → 13 (`courses/transfer/schema.py:14`).

**The bump has seven pinned assertions to update.** These are mechanical, expected churn,
not regressions — an implementer who meets them as unexplained failures may "fix" them by
reverting the bump:

| File | Line | Assertion |
| --- | --- | --- |
| `courses/tests/test_beforeafter_transfer.py` | 169 | `FORMAT_VERSION == 12` |
| `courses/tests/test_image_size_transfer.py` | 44 | `FORMAT_VERSION == 12` |
| `tests/test_link_transfer.py` | 54 | `FORMAT_VERSION == 12` |
| `tests/test_table_transfer.py` | 299 | `FORMAT_VERSION == 12` |
| `tests/test_tabs_transfer.py` | 62 | `FORMAT_VERSION == 12` |
| `tests/test_transfer_schema.py` | 57 | `FORMAT_VERSION == 12` |
| `tests/test_transfer_export.py` | 222 | `manifest["format_version"] == 12` |

**An eighth assertion breaks on step 5 rather than on the bump.**
`courses/tests/test_callout_transfer.py:34` asserts
`data == {"kind": "warning", "heading": "Careful", "body": "<p>hi</p>"}` — a full dict
equality on `_ser_callout`'s output. Adding `numbered` to the serializer turns it red, and
the tempting "fix" is to drop `numbered` from the serializer — which is precisely mutant
6b, the defect §8.6b exists to catch. Update the expected dict to include `numbered`, and
**keep it a full dict equality**; relaxing it to a key-subset check would destroy the
only assertion that pins the exact export payload.

**Do not** touch `courses/tests/test_nested_question_transfer.py:260`, which passes
`format_version=12` as a *legacy archive fixture*. That 12 is the point of the test.

**Merge hazard.** A `FORMAT_VERSION` bump is the canonical silent-merge conflict: two
branches bumping to the same number produce identical lines and no git conflict. Whatever
else is in flight when this lands must be checked for a competing bump before merge.

## 8. Testing

Every test is falsified against a named mutant and must be observed RED. The mutants,
ordered by what they would actually catch:

1. **Interleaved tab ordering** — replace the accessor descent in `callout_numbers` with a
   flat `order_by("order", "pk")` over all children. This is the entire justification for
   the design in §3. Fixture is unit 349's real shape: 3 tabs, one task callout in each,
   plus a top-level callout before them, asserting `1, 2, 3, 4` and not a permutation.
   **Extend the fixture with a numbered callout nested inside a numbered callout**,
   asserting outer-then-inner: the tabs-only fixture scores identically under pre- and
   post-order, so on its own it leaves §3's pre-order rule unpinned. Second mutant:
   assign the container's number after walking its children.
2. **Unnumbered consuming a slot** — increment the counter before the `numbered` check.
   The fixture is the acceptance criterion from the Purpose: example, task, note, warning,
   task → `1, 2, –, 3, 4`.
3. **The `page`-dict barrier.** Note that `CalloutElement` is itself in
   `CONTAINER_MODELS`, so `render_element` builds `page` for **top-level** callouts too —
   deleting the key from `extra["page"]` therefore strips numbers at *every* depth and is
   indistinguishable from a missing context site (mutant 4). The mutant that actually
   isolates propagation is to drop `**(page or {})` from **one** container's `render` (use
   `TabsElement`): a callout nested in tabs loses its number while top-level callouts and
   spoiler-nested callouts keep theirs. Assert a nested callout's rendered number, and
   additionally capture the `page` kwarg at a nested `CalloutElement.render` — the
   technique `test_mode_is_not_forwarded_to_a_nested_child` already uses — so the
   assertion names the mechanism rather than the symptom.
4. **A missing context site** — for each of the four sites in §5, remove its
   `callout_numbers` key and assert that site's render loses numbers. Four tests, because
   there is no invariant that covers them jointly. The two editor sites must be driven
   separately: a first editor page load for `_editor_page`, and a post-operation fragment
   response for `_render_editor_fragments`.
5. **Backfill** — change the migration to set every row `True`. The test DB has no callout
   rows, so the dev-DB tallies (12 note, 21 tip) are not the assertion: the test creates
   rows at the pre-migration historical state and migrates forward, asserting per-kind
   outcomes on its own fixture. Copy the pattern from one of the repo's four existing
   migration tests — `courses/tests/test_publish_migration.py` is the closest fit.
6. **Transfer, three mutants** — (a) drop the `setdefault`: a pre-v13 archive raises
   `TransferError` on `_exact_keys`; (b) drop `numbered` from the exporter: a v13
   round-trip of `numbered=False` returns `True`; (c) drop `numbered=` from
   `_build_callout`: **duplicating** an unnumbered callout in the editor produces a
   numbered copy. (c) is the one a reader is most likely to skip and the one users would
   hit first.
7. **Unnumbered render is unchanged** — pinned assertion on a `numbered=False` callout
   *with* a custom heading, so the header rewrite cannot quietly alter today's output.
   Falsified by making the numbered branch unconditional. Because §4 mandates a
   single-line template expression, the assertion is a **hardcoded expected literal** —
   `<span class="callout__heading">Suma ciągu</span>` — transcribed from a real render
   *before* the template is edited. (A test cannot compare against "the current output":
   the pre-change build does not exist at test time, and there is no golden-file
   mechanism in this repo to build one.) If the implementation ends up multi-line, restate
   the test as an assertion on `.callout__heading`'s text content and withdraw §4's
   byte-identity claim.
8. **Numbered with a custom heading** — the one row in §4's table that D4 actually
   changes, and the only branch with zero real rows exercising it. Note that
   `Przykład 3. Suma ciągu` is **not** a contiguous substring of the markup — §4 renders
   it as `Przykład <span class="callout__number">3</span>. Suma ciągu` — so the assertion
   must be one of two explicit forms, and the spec picks the first: assert the exact HTML
   fragment including the span, which keeps it under the attribute-form rule below. A
   normalised `.callout__heading` text-content assertion is the acceptable alternative,
   but it is a text assertion and therefore exempt from that rule; say which one the test
   is. Falsified two ways — swap the label/heading order, and emit `display_heading`
   instead of `heading` in the numbered branch (which would render `Suma ciągu` twice or
   drop the label).
9. **`KIND_DEFAULT_NUMBERED` covers every kind** — falsified by deleting one entry.
10. **The accessor map covers every container** — assert
    `set(ACCESSORS) == builder.CONTAINER_MODELS`, falsified by deleting one entry; plus a
    direct test that a container class absent from the map raises rather than returning
    silently. Without this, §3's raise-invariant is unreachable and therefore unproven.
11. **The form and its widget** — assert `"numbered" in CalloutElementForm.Meta.fields`,
    and that `_edit_callout.html` renders `<input type="checkbox" name="numbered">`.
    Both are two-line tests guarding the defect R2 describes, which is otherwise reachable
    only through the slowest instrument in the suite.

Assertions on rendered markup are pinned to the attribute form
(`class="callout__number"`), never the bare class name. The rationale is forward-looking
rather than present-tense: `templates/courses/lesson_unit.html:42` emits callout class
names as literals inside an inline `<style>` block, so a bare-substring assertion on any
class named there passes from the page `<head>` regardless of what the element rendered.
`callout__number` is not in that block today and §4 adds no CSS — but the moment a rule
for it is added there, a bare-substring assertion goes vacuous with no test failing to
announce it.

**e2e.** One test covering the R2 round trip: open a numbered callout's editor form,
change only the heading, save, and assert the callout is still numbered. The checkbox must
not be touched during the run — that is the whole point of the test.

**The instrument must be the re-opened form's checkbox state**, not the number visible in
the preview. A visible-number assertion also goes red for a missing context site (mutant
4) and for a dropped barrier key (mutant 3), so its failure would not identify R2 — and
e2e tests in this repo assert on rendered UI by default, so leaving the instrument
unstated invites exactly that. Re-reading the DB row is an acceptable addition; the
checkbox state is what the round trip is actually about. This complements, and does not
replace, the unit tests in mutant 11.

**Query count.** `assertNumQueries` around a **direct call to `callout_numbers(node)`**
with a fixture shaped like a real unit (a top-level callout, a 3-tab container each
holding a callout, a spoiler holding a callout). Not around a whole lesson render: that
total already includes progress, unit nav, notes, tags, the edit-unit link and per-question
prefetches (`courses/views.py:346-375`, `:594-632`), so it is brittle against unrelated
changes and attributes none of its number to the numbering pass — it would fail for
reasons having nothing to do with this feature, and pass without proving anything about
the per-container cost. The self-contained contract in §3 exists so this test can sit
directly on the function.

Record the observed number in the test with a comment breaking it down by the §3 shape, so
a later change to the walk shows up as an explained delta. If a whole-page figure is also
wanted, express it as the *delta* between a unit with callouts and the same unit with
none, never as an absolute.

## 9. i18n and help documentation

One new author-facing string: the checkbox label in `_edit_callout.html` (§6). Polish
translation required, `.po` and `.mo` both committed. The widget itself is new markup, not
a re-label of something existing.

**The author help pages describe this form and go stale.**
`docs/help/course-admin/content-editors.md:115-121` enumerates the callout editor's
controls in prose — *"Choose a **Kind** …, an optional **Heading** …, and rich-text body
content"* — and `docs/help/course-admin/content-editors.pl.md` is its Polish twin. Extend
that sentence with the numbering checkbox and the per-kind default, **in both files in the
same commit**. Nothing in the test suite catches twin-file drift here.

Two known traps apply. `makemessages` fuzzy-prefills a wrong translation from a similar
msgid, and clearing that requires deleting both the `#, fuzzy` marker and the wrong
`msgstr`. And a long-lived branch produces a binary `.mo` conflict on rebase — rebase and
regenerate before opening the PR, never merge the binary.

No student-facing *string* is added: the number is a bare integer appended to an already
translated label. But note that §4's template hardcodes both the ordering (label, number,
`. `, heading) and the separator punctuation in markup, so neither varies by locale. That
is deliberate and fine for pl/en; a future locale wanting `3. Przykład` needs a template
change, not a translation.

## 10. Risks

**R1 — four context sites, silent failure.** Miss one and numbering does not error; the
numbers are simply absent. This is the design's weakest seam. Mitigation is one test per
site (§8.4). A stronger invariant was considered and rejected: the four sites build
different context shapes for different templates, and a test asserting "every context
containing elements also contains `callout_numbers`" would have to enumerate the same four
sites to know where to look.

**R2 — the unchecked-checkbox POST.** An unchecked checkbox sends nothing, so any save
path that posts the callout form without the field sets `numbered=False` silently. This is
the same failure shape as the existing `el_title` trap, where a POST missing that key
blanks the element title.

**Why this is new rather than routine.** The repo has exactly one other model-backed
boolean on an element form — `ShortTextQuestionElement.case_sensitive`
(`courses/models.py:2357`) — and it defaults to **False**. There, a POST missing the key
reproduces the field's own default, so the hazard has never had a visible consequence and
nothing guards it. `numbered` defaults to **True**, which inverts that: a missing key
silently *loses* author intent instead of restoring the default. That asymmetry is the
whole reason R2 needs its own tests, and an implementer who spots the `case_sensitive`
precedent would otherwise reasonably conclude this risk is theoretical.

The root causes are the field being absent from `Meta.fields` or
the checkbox being absent from the hand-written template; both are pinned by cheap unit
tests (§8.11), with the e2e as the round-trip check rather than the only guard.

**R3 — query cost.** The shape is given in §3 and deliberately not restated as arithmetic
here: roots plus, per container, `join_row` + `children` + one prefetch per distinct child
content type. It is paid on every render of every unit that has at least one callout
anywhere in it; units with none pay a single existence check thanks to the §3 early-out.
That includes the editor: two of the four sites are
`_editor_page` and `_render_editor_fragments`, so the walk runs on every add / save / move
/ delete / paste round-trip, inside the transaction that holds the unit lock. Small at the
measured scale (167 units, max 9 callouts, shallow nesting), but it is a per-render cost on
both the student and editor paths, so it is pinned (§8) rather than assumed. The pinned
count is taken on the student render; the editor paths call the same function with the same
node and are not separately pinned.

**R4 — a number the student never sees in context.** D3 numbers every callout wherever it
sits, so a callout inside a container that shows one child at a time takes a number that
may be invisible, leaving an apparent gap in the sequence. This affects all three nesting
sites, in descending order of exposure:

- **Tabs (24 callouts).** Only the active tab renders visibly. A student on tab 1 may see
  `Zadanie 4` and on tab 2 `Zadanie 5`, with nothing showing 1–3 at that moment — on top
  of the duplicate-numbering clash with the tab labels described in Purpose.
- **Spoiler (9 callouts).** A closed `<details>` hides its callout entirely, so the visible
  sequence reads `Przykład 1`, `Przykład 3` until the student opens it. Arguably fine —
  opening the spoiler resolves the gap — but it is a gap by default.
- **Before/after (0 callouts today).** The two slots are alternative views of the same
  content, so one of the two numbers is always hidden.
- **Slideshow units — and this one reaches the other 90%.** `build_lesson_context` returns
  `"slides": partition_into_slides(elements)` and `templates/courses/_lesson_article.html`
  switches the article to `lesson--slideshow` whenever `slides|length > 1`, so only one
  slide is on screen. A student can land on a slide showing `Przykład 4` with 1–3 on
  earlier slides. Unlike the three cases above this needs no nesting, so it applies to
  **top-level** callouts — 90% of the corpus. It needs no wiring change (same lesson
  context, same map), and it is the one case the checkbox remedy does not really address:
  unticking removes the number rather than fixing the gap. Accepted on the same grounds as
  the rest — the sequence is a property of the unit, and a slideshow is still one unit.

All three are **accepted**, not solved. D3's one-rule-no-exceptions is the decision, and
the checkbox is the remedy: an author who dislikes the gap unticks the nested callouts. No
code special-cases any container type. Recorded here so the behaviour is a known
consequence rather than a bug report after release.

## Deferred

**Auto-flipping the checkbox on kind change.** When an author adds a callout it is created
as `example`, so the checkbox starts ticked; switching the kind to Note leaves it ticked
and the author must untick it. A small JS handler could flip it to the kind default while
the checkbox is untouched. Left out because tracking "untouched" across an edit of a saved
row is fiddly for a one-click saving. Revisit if it proves annoying in use.
