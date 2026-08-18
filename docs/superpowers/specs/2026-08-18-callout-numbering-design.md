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

The existing five-line comment at `courses/models.py:514-516` explaining the string
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
- The function **re-queries its own roots**; it does not accept a pre-materialised element
  list, even though all four call sites have just built one. The cost is one duplicate
  roots query per render, and the benefit is that the pinned query count (§8) is a
  property of the function rather than of each caller — otherwise two implementers make
  different choices and the number is not reproducible.
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
`_CONTAINER_REGISTRY`). The accessor per type is a module-level mapping keyed by model
class; a container class in `CONTAINER_MODELS` but absent from the mapping **raises**,
so a sixth container type cannot be added without a decision here rather than silently
having its children skipped. That raise path is unreachable with today's five types and
is therefore pinned by its own test (§8.10), not left to chance.

Inheriting the accessors also inherits their quirks, which is the point: `resolved_columns`
uses the destructive read-side `normalize_data` with its 2..4 render clamp, so a fifth
column's children are dropped from *both* the render and the numbering, and cannot
disagree.

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

**Two queries per container encountered**, not one: every accessor first calls
`join_row()` (`self.elements.order_by("pk").first()`) and then queries `join.children`.
The walk already holds the join row it is descending from, so the `join_row()` call is
redundant — but avoiding it means bypassing the accessors, which is the one thing this
design refuses to do. The redundant query is accepted explicitly as the price of
ordering agreement.

Plus one roots query per call. The worst real unit is 9 callouts with a 5-tab container:
roughly a dozen extra queries per render. This is the deliberate trade — correctness of
ordering over query count, at a scale where the count does not matter — and it is pinned
with `assertNumQueries` rather than assumed (§8, R3).

## 4. Render

`CalloutElement.render` reads the map out of the `page` dict it already receives and puts
a plain integer (or `None`) in its template context:

```python
numbers = (page or {}).get("callout_numbers") or {}
"number": numbers.get(element.pk) if element is not None else None,
```

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

Each adds `"callout_numbers": callout_numbers(node)` to the context it returns. There is no
single choke point that covers all four; see R1.

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

- `courses/templatetags/courses_extras.py:49-51` reads *"Six explicit statements, one per
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
<label class="check">
  <input type="checkbox" name="numbered" {% if form.numbered.value %}checked{% endif %}>
  {% trans "Number this callout" %}
</label>
```

`form.numbered.value` resolves to the posted value on a bound form and to the instance
value on an unbound one, so a failed validation round-trip preserves what the author
ticked.

**Existing form test.** `courses/tests/test_callout_form.py::test_valid_full_save` posts
`{"kind", "heading", "body"}` with no `numbered` key. Because an unchecked checkbox
transmits nothing, that POST is indistinguishable from a deliberate untick and the saved
row comes back `numbered=False` — silently, without failing. Update that test to assert
the resulting `numbered` explicitly, so the behaviour is pinned rather than incidental.
See R2.

## 7. Transfer

`_val_callout` (`courses/transfer/payloads.py:211`) currently calls
`_exact_keys(data, ["kind", "heading", "body"], ...)`, which rejects any unknown key —
so a new key is a hard break for every existing archive unless it is introduced with the
optional-key pattern already used for `size` (`:139`) and width/height (`:170`):

1. `data.setdefault("numbered", KIND_DEFAULT_NUMBERED.get(kind, True))` **before**
   `_exact_keys`, so a pre-v13 archive imports with per-kind defaults — matching the
   backfill migration exactly, so an archive exported before this feature and a database
   migrated by it agree.
2. Add `"numbered"` to the `_exact_keys` list.
3. Validate it is a `bool` and `_err` otherwise, following the file's convention.
4. **Build it.** `_build_callout` (`courses/transfer/importer.py:556`) constructs
   `CalloutElement(kind=..., heading=..., body=...)` and must gain `numbered=...`.
   Without this step the field is validated on the way in and written on the way out but
   **discarded at construction**, so every import silently resets it to the model default.
5. The exporter writes `numbered`.

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
   single-line template expression, this can be a byte-level comparison against the
   current output; if the implementation ends up multi-line, the test must be restated as
   an assertion on `.callout__heading`'s text content and §4's byte-identity claim
   withdrawn.
8. **Numbered with a custom heading** — the one row in §4's table that D4 actually
   changes, and the only branch with zero real rows exercising it. Pin the exact
   `Przykład 3. Suma ciągu` shape: label, space, number, period, space, heading. Falsified
   two ways — swap the label/heading order, and emit `display_heading` instead of `heading`
   in the numbered branch (which would render `Suma ciągu` twice or drop the label).
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
not be touched during the run — that is the whole point of the test. This complements, and
does not replace, the unit tests in mutant 11.

**Query count.** `assertNumQueries` on a fixture shaped like a real unit (a top-level
callout, a 3-tab container each holding a callout, a spoiler holding a callout), so the
per-container cost is a pinned number rather than an assumption. Pin it on the student
lesson render; the editor paths run the same function and are covered by R3's note rather
than a second pinned count.

## 9. i18n

One new author-facing string: the checkbox label in `_edit_callout.html` (§6). Polish
translation required, `.po` and `.mo` both committed. The widget itself is new markup, not
a re-label of something existing.

Two known traps apply. `makemessages` fuzzy-prefills a wrong translation from a similar
msgid, and clearing that requires deleting both the `#, fuzzy` marker and the wrong
`msgstr`. And a long-lived branch produces a binary `.mo` conflict on rebase — rebase and
regenerate before opening the PR, never merge the binary.

No student-facing string is added: the number is a bare integer appended to an already
translated label.

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
blanks the element title. The root causes are the field being absent from `Meta.fields` or
the checkbox being absent from the hand-written template; both are pinned by cheap unit
tests (§8.11), with the e2e as the round-trip check rather than the only guard.

**R3 — query cost.** One roots query plus two queries per container, on every render of
every unit containing a callout. That includes the editor: two of the four sites are
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
