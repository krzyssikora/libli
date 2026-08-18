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
across ~10 units.

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
- **D6 — numbers appear wherever the unit renders as a whole** (student page, editor
  preview, print). The editor's collapsed row list is unchanged.
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

Beside the existing `KIND_DEFAULT_HEADING` (`models.py:569`), and for the same reason —
it must be built after the class body so it can read the enum:

```python
KIND_DEFAULT_NUMBERED = {
    CalloutElement.Kind.EXAMPLE.value: True,
    CalloutElement.Kind.TASK.value: True,
    CalloutElement.Kind.WARNING.value: True,
    CalloutElement.Kind.NOTE.value: False,
    CalloutElement.Kind.TIP.value: False,
}
```

Exactly two callers read it at runtime, and an invariant test asserts its key set equals
`{k.value for k in CalloutElement.Kind}` so a sixth kind cannot be added without a
decision here:

1. the importer's default for pre-v13 archives (§6),
2. `CalloutElementForm`'s initial value for a new callout (§5).

The backfill migration (§2) encodes the same decision but as a frozen literal, not an
import — see there for why.

The model default stays a constant `True`; a field default cannot vary by kind, and every
place that needs per-kind behaviour goes through the constant instead.

A `kind_label` property is added alongside `display_heading`, returning the kind's default
label without the custom-heading fallback:

```python
@property
def kind_label(self):
    return KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])
```

`display_heading` keeps its current behaviour and its current callers
(`courses_manage_extras.py:158`, the editor row summary — unchanged per D6).

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
is later edited. Inline the false-kind list as a literal (`["note", "tip"]`) with a
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
`_CONTAINER_REGISTRY`), so a sixth container type cannot be added without this walk
raising rather than silently skipping its children. The accessor per type is a module-level
mapping keyed by model class; an unmapped container type raises.

Inheriting the accessors also inherits their quirks, which is the point: `resolved_columns`
uses the destructive read-side `normalize_data` with its 2..4 render clamp, so a fifth
column's children are dropped from *both* the render and the numbering, and cannot
disagree.

Roots are `node.elements.filter(parent__isnull=True).order_by("order", "pk")`, matching
both context builders.

### Query cost

One query per container encountered (each accessor issues its own `join.children` query).
The worst real unit is 9 callouts with a 5-tab container — a handful of extra queries per
render. This is the deliberate trade: correctness of ordering over query count, at a scale
where the count does not matter. It is pinned with `assertNumQueries` on a
real-shaped fixture rather than assumed (§7, R3).

## 4. Render

`CalloutElement.render` reads the map out of the `page` dict it already receives and puts
a plain integer (or `None`) in its template context:

```python
numbers = (page or {}).get("callout_numbers") or {}
"number": numbers.get(element.pk) if element is not None else None,
```

The lookup happens in Python because a Django template cannot index a dict by a variable
key without a filter.

`templates/courses/elements/calloutelement.html:5` becomes:

```django
<span class="callout__heading">
  {% if number %}{{ el.kind_label }} <span class="callout__number">{{ number }}</span>{% if el.heading %}. {{ el.heading }}{% endif %}
  {% else %}{{ el.display_heading }}{% endif %}
</span>
```

Resulting header text:

| | today | numbered | unnumbered |
| --- | --- | --- | --- |
| no custom heading | `Przykład` | `Przykład 3` | `Przykład` |
| custom heading `Suma ciągu` | `Suma ciągu` | `Przykład 3. Suma ciągu` | `Suma ciągu` |

The unnumbered branch is today's expression verbatim, so an unnumbered callout renders
byte-identically to the current build — including the "custom heading replaces the label"
behaviour, which changes for numbered callouts only (D4).

No trailing period after a bare number (D7). The period appears only as the separator
before a custom heading.

The number is wrapped in its own `<span class="callout__number">` so it can be styled
independently and so a test can pin it without matching the surrounding translated label.
No new CSS is required; a style hook existing without a rule is intentional.

## 5. Context wiring

`callout_numbers` reaches the template through four context sites plus one barrier.

**The four sites:**

| Site | File |
| --- | --- |
| Lesson unit | `views.py::build_lesson_context` (~`:339`) |
| Quiz unit | `views.py::build_quiz_context` (~`:1301`) |
| Editor fragments | `views_manage.py` (~`:1853`) |
| Editor fragments (second builder) | `views_manage.py` (~`:1915`) |

Each adds `"callout_numbers": callout_numbers(node)` to the context it returns. There is no
single choke point that covers all four; see R1.

**The barrier.** `render_element` (`courses_extras.py:32`) is a context barrier: only
containers receive `page`, and `page` is rebuilt from named keys at every level.
`callout_numbers` becomes a seventh key, read context-only with an `or {}` fallback —
the same shape as `feedback_ancestor_pks`, not the parameter-or-context shape the
question-state keys use:

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

**Editor fragment renders.** The editor swaps whole `[data-scope]` panes, and the preview
pane is one of them, so the preview always re-renders from `preview_elements` with the map
present. A single-element fragment render carries no map and therefore no number; that is
correct, because a lone element has no unit-wide position to report.

## 6. Transfer

`_val_callout` (`payloads.py:211`) currently calls
`_exact_keys(data, ["kind", "heading", "body"], ...)`, which rejects any unknown key —
so a new key is a hard break for every existing archive unless it is introduced with the
optional-key pattern already used for `size` (`:139`) and width/height (`:170`):

1. `data.setdefault("numbered", KIND_DEFAULT_NUMBERED.get(kind, True))` **before**
   `_exact_keys`, so a pre-v13 archive imports with per-kind defaults — matching the
   backfill migration exactly, so an archive exported before this feature and a database
   migrated by it agree.
2. Add `"numbered"` to the `_exact_keys` list.
3. Validate it is a `bool` and `_err` otherwise, following the file's convention.

The exporter writes `numbered`. `FORMAT_VERSION` goes 12 → 13 (`transfer/schema.py:14`).

**Merge hazard.** A `FORMAT_VERSION` bump is the canonical silent-merge conflict: two
branches bumping to the same number produce identical lines and no git conflict. Whatever
else is in flight when this lands must be checked for a competing bump before merge.

## 7. Testing

Every test is falsified against a named mutant and must be observed RED. The mutants,
ordered by what they would actually catch:

1. **Interleaved tab ordering** — replace the accessor descent in `callout_numbers` with a
   flat `order_by("order", "pk")` over all children. This is the entire justification for
   the design in §3. Fixture is unit 349's real shape: 3 tabs, one task callout in each,
   plus a top-level callout before them, asserting `1, 2, 3, 4` and not a permutation.
2. **Unnumbered consuming a slot** — increment the counter before the `numbered` check.
   The fixture is the acceptance criterion from the Purpose: example, task, note, warning,
   task → `1, 2, –, 3, 4`.
3. **The `page`-dict barrier** — delete `callout_numbers` from the `extra["page"]` dict.
   Top-level callouts keep their numbers, nested ones lose them. Asserted on the student
   page *and* on the editor preview, because those are separate context sites and a test
   on one says nothing about the other.
4. **A missing context site** — for each of the four sites, remove its
   `callout_numbers` key and assert that site's render loses numbers. Four tests, because
   there is no invariant that covers them jointly.
5. **Backfill** — change the migration to set every row `True`; the 12 note and 21 tip rows
   come out numbered.
6. **Transfer, two mutants** — (a) drop the `setdefault`: a pre-v13 archive raises
   `TransferError` on `_exact_keys`; (b) drop `numbered` from the exporter: a v13
   round-trip of `numbered=False` returns `True`.
7. **Unnumbered render is unchanged** — pinned assertion on a `numbered=False` callout
   *with* a custom heading, so the header rewrite cannot quietly alter today's output.
   Falsified by making the numbered branch unconditional.
8. **`KIND_DEFAULT_NUMBERED` covers every kind** — falsified by deleting one entry.

Assertions on rendered markup are pinned to the attribute form
(`class="callout__number"`), never the bare class name: `lesson_unit.html` emits callout
class names as literals inside an inline `<style>` block, and a bare-substring assertion
passes from the page `<head>` regardless of what the element rendered.

**e2e.** One test covering R2: open a numbered callout's editor form, change only the
heading, save, and assert the callout is still numbered. The checkbox must not be touched
during the run — that is the whole point of the test.

**Query count.** `assertNumQueries` on a fixture shaped like a real unit (a top-level
callout, a 3-tab container each holding a callout, a spoiler holding a callout), so the
per-container cost is a pinned number rather than an assumption.

## 8. i18n

One new author-facing string: the checkbox label in `_edit_callout.html`. Polish
translation required, `.po` and `.mo` both committed.

Two known traps apply. `makemessages` fuzzy-prefills a wrong translation from a similar
msgid, and clearing that requires deleting both the `#, fuzzy` marker and the wrong
`msgstr`. And a long-lived branch produces a binary `.mo` conflict on rebase — rebase and
regenerate before opening the PR, never merge the binary.

No student-facing string is added: the number is a bare integer appended to an already
translated label.

## 9. Risks

**R1 — four context sites, silent failure.** Miss one and numbering does not error; the
numbers are simply absent. This is the design's weakest seam. Mitigation is one test per
site (§7.4). A stronger invariant was considered and rejected: the four sites build
different context shapes for different templates, and a test asserting "every context
containing elements also contains `callout_numbers`" would have to enumerate the same four
sites to know where to look.

**R2 — the unchecked-checkbox POST.** An unchecked checkbox sends nothing, so any save
path that posts the callout form without the field sets `numbered=False` silently. This is
the same failure shape as the existing `el_title` trap, where a POST missing that key
blanks the element title. Mitigated by the e2e in §7.

**R3 — query cost.** One query per container in the walk, on every render of every unit
containing a callout. Small at the measured scale (167 units, max 9 callouts, shallow
nesting), but it is a per-page-render cost on the student path, so it is pinned rather than
assumed.

**R4 — numbers inside a before/after container.** The two slots are alternative views of
the same content, so a numbered callout in the "after" slot takes a number the student may
never see in context, leaving an apparent gap. D3 says one rule with no exceptions, and no
such callout exists today (0 of 36 nested callouts sit in a before/after). Accepted; the
author can untick.

## Deferred

**Auto-flipping the checkbox on kind change.** When an author adds a callout it is created
as `example`, so the checkbox starts ticked; switching the kind to Note leaves it ticked
and the author must untick it. A small JS handler could flip it to the kind default while
the checkbox is untouched. Left out because tracking "untouched" across an edit of a saved
row is fiddly for a one-click saving. Revisit if it proves annoying in use.
