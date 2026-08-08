# Callout: a fifth kind — Task / Zadanie

## Purpose

`CalloutElement` currently offers four kinds — Example, Note, Tip and Important — each
rendering as a "textbook category marker": a tinted icon chip, an uppercase tracked eyebrow
heading, and a left spine, all driven from one `--callout-accent` per kind.

Course authors need a fifth category for **a problem set for the reader to work on**, distinct
from Example (a worked solution shown *to* the reader) and from the interactive question
elements (which are marked and stateful). The new kind is purely a visual/semantic category:
it changes nothing about how the callout behaves, nests, or persists.

The kind is author-facing in English as **Task** and in Polish as **Zadanie**.

### Non-goals

- No behaviour. The callout stays zero-JS with no server endpoint; the static render is the
  behaviour. Nothing about marking, state, or progress is introduced.
- No change to callout nesting, the container registry, the element palette, or the icon
  sprite. A *kind* is not an element type; `CalloutElement` remains a single palette card.
- No re-litigation of the existing `warning` value / "Important" label mismatch. That mismatch
  is deliberate and load-bearing (existing rows, `.callout--warning`, exported archives); this
  change neither depends on it nor repeats it.

## Decisions and rationale

**D1 — the stored value is `"task"`, matching its label.** The existing fourth kind stores
`"warning"` while displaying "Important", a mismatch that now needs a comment in the model to
stop a future contributor "fixing" it with a data migration. That mismatch exists only because
the relabel came after the data. Here there is no data and no constraint, so value and label
agree from the start rather than introducing a second such trap. `Kind.TASK = "task"`, CSS
class `.callout--task`, transfer payload `{"kind": "task"}`.

**D2 — `FORMAT_VERSION` is bumped 9 → 10.** `_val_callout` (`courses/transfer/payloads.py`)
**rejects** an unknown `kind` rather than coercing it, and does so deliberately: the adjacent
`_val_image` comment states the rule as "a cosmetic field with a lossless default must never
fail an import. (Contrast `_val_callout`, which rejects an unknown `kind` — a kind has no safe
fallback.)" So an archive exported from this build containing a Task callout **will** be
rejected by any older build. Without the bump the author sees "Element 'x' has an unknown
callout kind"; with it, the manifest gate fires first and the message is the honest "This
archive uses format version 10, but this instance supports up to version 9. It was exported
from a newer application version." Same rejection, comprehensible reason.

**D3 — accent and icon were chosen against rendered mockups**, both themes, alongside the
existing four at real size (3px spine, 18px chip). Magenta was selected over violet, teal and
rose: teal sits between the existing blue and green and reads as a shade of Tip; rose reads as
severity next to the amber Important.

## Architecture / components

### 1. Model — `courses/models.py`

Append one member to the nested `CalloutElement.Kind` TextChoices:

```python
TASK = "task", _("Task")
```

Constraints already satisfied, verified against the current field definition:

- `kind = models.CharField(max_length=12, ...)` — `"task"` is 4 characters, well inside the
  bound. No field-width change.
- `KIND_DEFAULT_HEADING` is built at module level as
  `{k.value: k.label for k in CalloutElement.Kind}` *after* the class body, so the new default
  heading ("Task" / "Zadanie") is picked up with no edit. `display_heading` needs no change.
- `save()`'s defensive coercion (`if self.kind not in self.Kind.values: self.kind = EXAMPLE`)
  needs no change — `"task"` is now a member, so it survives the check.

The class docstring enumerates the kinds ("Example/Note/Tip/Important") and must gain Task.

### 2. Migration

`0056_alter_calloutelement_kind` — an `AlterField` on `CalloutElement.kind`.

The SQL is a no-op: Django never emits a PG CHECK for `choices`, so `sqlmigrate` prints
`-- (no-op)`. The migration is nonetheless **required**, because `choices` is part of the
field's deconstruction: without it the migration state drifts and the next unrelated
`makemigrations` silently absorbs this `AlterField` into itself. This is the exact failure
mode that shipped in #203 and prompted the CI guard; `.github/workflows/ci.yml` now runs
`makemigrations --check --dry-run` in the `unit` job, so a missing migration fails CI.

Migration number `0056` assumes `0055` (from the before/after element, merged as #227) is the
current head. The implementation must confirm the actual head with `showmigrations` rather
than assuming, and let `makemigrations` assign the number.

### 3. Student render

`templates/courses/elements/_callout_icon.html` is an `{% if %}` / `{% elif %}` chain over
`el.kind`, terminating in an `{% else %}` that emits the Example book-open icon as the
fallback. Add a branch **before** that `{% else %}`:

```
{% elif el.kind == "task" %}
  <svg class="callout__icon" ...>…pencil…</svg>
```

The icon is the Lucide **pencil**, matching the house convention for this set: a monochrome
line SVG on a `0 0 24 24` viewBox, `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`,
round caps and joins, `aria-hidden="true"`, `focusable="false"`. Paths:

```
<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>
<path d="m15 5 4 4"/>
```

`calloutelement.html` itself needs no change: it emits
`class="callout callout--{{ el.kind }}"` and `{{ el.display_heading }}`, both already generic.

### 4. Styling — `courses/static/courses/css/courses.css`

Two declarations, added alongside the four existing pairs at the end of the callout section:

```css
.callout--task { --callout-accent: #a8318f; }
[data-theme="dark"] .callout--task { --callout-accent: #ee9fd8; }
```

Everything else derives from that single custom property, exactly as the other four kinds do:
the 3px left spine, the 6%-accent-over-`--surface-raised` container tint, the 14%-accent icon
chip, and the eyebrow colour.

**Contrast, computed against the tinted callout background** (`color-mix(accent 6%, surface)`,
i.e. `#FAF3F8` light and `#383030` dark):

| Theme | Accent | Background | Ratio |
|---|---|---|---|
| Light | `#a8318f` | `#FAF3F8` | ~5.5:1 |
| Dark | `#ee9fd8` | `#383030` | ~6.5:1 |

Both clear WCAG AA for normal text, so the 0.75rem/700 eyebrow is safe with margin and no
`--text-tertiary`-style near-miss is being introduced. These are the values a reviewer should
re-derive if either hex is ever changed.

### 5. Editor — no change

`templates/courses/manage/editor/_edit_callout.html` renders the kind picker by iterating
`form.fields.kind.choices`, with the selected-state comparison
`form.kind.value|stringformat:"s" == value|stringformat:"s"`. A new enum member appears in the
dropdown automatically and round-trips its selected state with no template edit.

`_element_row.html`'s callout branch is kind-agnostic (it shows the type label and either the
element title or `element_summary`), so the editor list needs nothing either.

### 6. Transfer — no code change beyond the version constant

- `_ser_callout` emits `{kind, heading, body}` straight off the model — generic.
- `_val_callout` checks `data["kind"] not in CalloutElement.Kind.values` — data-driven, so it
  accepts `"task"` the moment the enum gains it.
- `_build_callout` goes through `_clean_save` — generic.

Only `FORMAT_VERSION` changes, per D2. It is defined once at `courses/transfer/schema.py:14`
and imported symbolically everywhere in production code, but it is asserted as a **literal**
in **7 places across 6 test files**, enumerated here so the bump does not go looking for them
one CI failure at a time:

| File | Site |
|---|---|
| `tests/test_transfer_schema.py` | `assert FORMAT_VERSION == 9` |
| `tests/test_link_transfer.py` | `assert FORMAT_VERSION == 9` |
| `tests/test_table_transfer.py` | `assert FORMAT_VERSION == 9`, plus a prose comment reading `4 <= FORMAT_VERSION=9` |
| `tests/test_tabs_transfer.py` | `assert FORMAT_VERSION == 9` |
| `tests/test_transfer_export.py` | `assert manifest["format_version"] == 9` |
| `courses/tests/test_beforeafter_transfer.py` | `assert FORMAT_VERSION == 9` |
| `courses/tests/test_image_size_transfer.py` | `assert FORMAT_VERSION == 9` |

The last version bump merged silently because two branches made the *identical* line change
and git auto-resolved it with no conflict; the union of sites was larger than the branch had
found on its own. Enumerating them in the spec is the countermeasure.

### 7. i18n

`Task` is a new msgid in the Polish catalog, translated **`Zadanie`**.

This is precisely the shape that triggers the known `makemessages` fuzzy trap: `msgmerge`
pre-fills a new short msgid from a similar existing one and marks it `#, fuzzy` with a `#|
msgid` reference line. Clearing it is **two** deletions — the `#, fuzzy` flag line *and* the
`#| msgid` line — not one. The run must end at **0 fuzzy / 0 obsolete**, and `.mo` files must
be regenerated with `compilemessages`.

### 8. Help manual

Both language editions list the kinds inline and must gain the fifth:

- `docs/help/course-admin/content-editors.md` — "Choose a **Kind** (Example, Note, Tip, or
  Important — …" becomes the five.
- `docs/help/course-admin/content-editors.pl.md` — the corresponding sentence in the `{el:callout}`
  entry.

## Data flow

**Authoring.** The editor form offers the kind via `Kind.choices`; the POST stores
`kind="task"`; `save()` sanitises the body and leaves the kind alone. No new request path.

**Student render.** `calloutelement.html` interpolates the kind into `callout--task`, the icon
partial's new branch emits the pencil, and `display_heading` yields the translated "Task" /
"Zadanie" unless the author supplied a heading override. CSS resolves `--callout-accent` from
the class. There is no JS on this path.

**Export.** `_ser_callout` writes `{"kind": "task", …}`; the manifest carries
`format_version: 10`.

**Import into an equal-or-newer build.** The manifest gate passes; `_val_callout` accepts
`"task"` because it is in `Kind.values`; `_build_callout` saves it.

**Import into an older build.** The manifest gate rejects the archive up front with the
version message — the point of D2.

**Math.** No change is needed. `_element_has_math` dispatches on the *element type*
(`CalloutElement` → heading + body + recursive children), never on the kind, so a Task callout
arms KaTeX under exactly the same conditions as any other callout.

## Error handling

- **Unknown kind from a tampered import or a stale row** — unchanged: `save()` coerces
  anything outside `Kind.values` to `example`, and `display_heading` falls back through
  `KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])` using the **string**
  key (a bare `Kind.EXAMPLE` there would raise `NameError`, since `Kind` is a nested class
  resolved against module globals at method scope).
- **Unknown kind in an import payload** — unchanged: `_val_callout` raises a `TransferError`
  with a translated, user-facing message. Adding a member widens what is accepted; it does not
  weaken the rejection.
- **An archive from a newer build** — handled by the manifest version gate in
  `_validate_manifest`, which is why D2 bumps the constant.
- **A missing icon branch** — the `{% else %}` fallback means a typo in the branch condition
  degrades to the Example book-open icon rather than rendering nothing. Silent, hence the
  explicit icon test below.

## Testing

Every test below names the mutant that must turn it **red**. A test that passes both with and
without the change it guards is worthless, and roughly a third of the catches in the last
callout branch were exactly that.

| Test | Location | Mutant that must fail it |
|---|---|---|
| `.callout--task` present in the stylesheet | `tests/test_callout_css.py` (extend the existing class list) | delete the `.callout--task` rule |
| the dark-theme override is present | same file | delete the `[data-theme="dark"] .callout--task` rule |
| `display_heading` for `kind="task"` is "Task" | `courses/tests/test_callout_model.py` | remove the `TASK` enum member |
| render carries `callout--task` | `courses/tests/test_callout_render.py` | revert `calloutelement.html`'s class interpolation |
| render emits the pencil path `m15 5 4 4` for `task`, and that path is **absent** from an `example` render | same file | delete the `{% elif el.kind == "task" %}` branch — it then falls through to book-open, and both halves of the assertion move together |
| a `kind="task"` callout survives an export/import round trip | `courses/tests/test_callout_transfer.py` | revert the enum, so `_val_callout` rejects the payload |
| `FORMAT_VERSION == 10` at all 7 sites | the 6 files tabled above | leave the constant at 9 |

**Assertion form.** The stylesheet tests scan source text, so they must assert on a form that
cannot be satisfied from somewhere else in the file — the earlier callout branch had a test
pass from the page `<head>` because it asserted a bare class name. `.callout--task` is a novel
token here, but the dark assertion must include its `[data-theme="dark"]` prefix rather than
matching the bare class a second time.

**Layer.** All of this is falsifiable at the unit/template level. Nothing here is behavioural,
so **no e2e test is warranted** — the existing callout e2e coverage exercises the container
mechanics, which this change does not touch.

**Not re-tested:** the editor dropdown and the transfer validator are data-driven off the enum
and already covered by existing tests that iterate `Kind`; adding a member does not create a
new branch in either.

## Definition of done

1. `uv run python manage.py makemigrations --check --dry-run` clean (the migration exists).
2. `uv run python manage.py check` clean.
3. The affected test selection green — the callout tests, the transfer tests, and the CSS
   tests. The test-DB container must be running first, or the suite looks hung for ~4m21s.
4. Each new test verified red against its named mutant, not merely observed green.
5. `uv run ruff check .` and `uv run ruff format --check .` clean — the format check is a real
   CI gate; run `ruff format .` **last**, after every other edit.
6. Polish catalog at 0 fuzzy / 0 obsolete, `.mo` regenerated.
7. Light + dark screenshot confirmation of the new kind rendered beside the existing four.
