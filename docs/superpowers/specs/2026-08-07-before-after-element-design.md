# Before / after element

A fifth container element. The author fills two fixed slots — **before / przed** and
**after / po** — and the student sees the "before" content plus a button; pressing the
button swaps to "after", pressing it again swaps back. The visible side carries a
spoiler-style left rule so the extent of the element's content is unmistakable.

Author-facing name: **Before / after** (pl: **Przed / po**). Transfer key
`before_after`; element-form key `beforeafter`; model `BeforeAfterElement`.

Paths are given in full on first mention. Note in particular that the shared stylesheet
is **`core/static/core/css/app.css`** (there is no `courses/static/courses/css/app.css`),
the element stylesheet is `courses/static/courses/css/courses.css`, and the transfer
validators live in **`courses/transfer/payloads.py`**.

## Purpose

Authors need to present a *transformation* — a problem and its solution, a sentence
before and after correction, an equation before and after simplification, a diagram
before and after a construction step — as one object the student can flip between, in
place, without losing their position on the page.

The existing elements do not cover this:

* **Spoiler** is additive disclosure — the revealed content appears *below* the trigger
  and the original stays on screen. There is no swap, and no way back once revealed.
* **Tabs** swaps, but its slots are author-labelled and 2–8 in number; it reads as
  parallel alternatives, not as one thing changing into another, and it has no single
  call-to-action button.
* **Two-column** shows both at once, which is exactly what a before/after must not do.

Success criteria:

1. An author can add the element, fill both slots with ordinary child elements, and
   optionally set the button's label.
2. A student sees only the "before" side on load — **never a frame of the "after" side**
   — and toggles with one button, repeatedly, both ways. This holds in **lesson and quiz
   units alike** (see §5.4).
3. The element nests inside the other containers and accepts the same children they do.
4. It survives course export/import — **and `duplicate_element`** — with its children in
   the correct slots and its `button_label` intact.

### Decisions taken during design (do not relitigate)

| Question | Decision | Why |
| --- | --- | --- |
| Which children? | Reuse the existing `NESTABLE_TYPE_KEYS` allowlist unchanged | Nine of the ten graded question types (`choice`, `short_text`, `extended_response`, `short_numeric`, `match_pair`, `choice_grid`, `multi_grid`, `drag_to_image`, `drag_fill_blank`) are already absent from it. A per-container exception would be the first in the codebase. **`fill_blank` is the one exception** — `FillBlankQuestionElement` is a graded `QuestionElement` and *is* nestable, pinned by `courses/tests/test_spoiler_nesting.py:184`. See §5.4 for what that means in a quiz unit. |
| Button label per direction? | One label, both directions | One `CharField`; the icon reads as "switch" either way. |
| Persist the toggled state? | No — ephemeral, resets to "before" | No state route, no `ElementState` row, no endpoint. Matches Tabs. |
| Editor layout | Two stacked panels, both always visible | The author is authoring a *pair*; hiding one half defeats the comparison. |
| Rule extent | Around the content only; button above, outside the rule | The spoiler's shape, which the user asked to match. |
| Visible "which side am I on?" indicator | **None ships** | The content *is* the signal — that is what a swap means — and an always-visible BEFORE/AFTER eyebrow would compete with the author's own material and restate what the reader can already see. Screen-reader users get `aria-pressed`, because for them the content is not glanceable. The headings therefore stay `.visually-hidden` except in the states where nothing else distinguishes the panels (no-JS, failed boot, print). |
| Armed in quiz units? | **Yes** — unlike a reveal gate | A before/after has no grading interaction and no state, so arming it is safe; leaving it unarmed would permanently expose the answer side and break criterion 2. |
| `button_label` content | Plain text, autoescaped | No math, no inline HTML, no sanitiser. `math.js`'s scope list (`courses/static/courses/js/math.js:31`) is deliberately **not** extended, so `\(…\)` in a label would ship raw — the field is documented as plain text for that reason. |
| `FORMAT_VERSION` | **Not** bumped | See §11. |

## Architecture / components

### 1. Model — `courses/models.py`

A new concrete beside `CalloutElement`:

```python
class BeforeAfterElement(ElementBase):
    BEFORE_SLOT_ID = "before"
    AFTER_SLOT_ID = "after"
    SLOT_IDS = (BEFORE_SLOT_ID, AFTER_SLOT_ID)   # order is the contract

    button_label = models.CharField(max_length=120, blank=True)
    elements = GenericRelation(Element)   # cascade: deleting this removes its join row
```

No `data` field and no `body` field. Children live in `Element` rows whose `parent` is
this element's join row and whose `tab_id` is one of the two slot ids — the substrate
`TabsElement`, `SpoilerElement` and `CalloutElement` already use.

Because the slots are **class constants rather than persisted data**, there is nothing to
normalize: no `normalize_ids` / `normalize_data` pair, no id minting, no truncation, and
no way for the stored slot set to drift from what the code expects. This is the single
biggest simplification versus `TwoColumnElement`, and it is deliberate. In Python and in
templates, everywhere a slot id is needed, reference `SLOT_IDS` / `BEFORE_SLOT_ID` /
`AFTER_SLOT_ID` — **never a string literal**, which would reintroduce exactly the drift
these constants exist to prevent.

**CSS is the one unavoidable exception**: a stylesheet cannot reference a Python
constant, so `[data-ba-side="after"]` is hardcoded in three places (the lesson pre-hide
`<style>`, the quiz pre-hide `<style>`, and the print block). Because nothing otherwise
ties those literals to the constant, renaming `AFTER_SLOT_ID` would silently disarm the
pre-hide — and the failure mode is a flashed answer, not a test error. A guard test pins
the two together; see the Testing table.

Methods:

* `join_row()` — `self.elements.order_by("pk").first()`, as Spoiler/Callout do.
* `resolved_slots()` — **returns a list of `(slot_id, children)` pairs, in `SLOT_IDS`
  order**; `[("before", []), ("after", [])]` when the join row is transient/mid-create.
  The children of *both* slots are fetched by a **single `children` queryset** —
  `order_by("order", "pk")`, `select_related("content_type")`,
  `prefetch_related("content_object")` — and partitioned in Python by `tab_id`. Not one
  queryset per slot. (The total query count is necessarily >1: `join_row()` is its own
  query and `prefetch_related` issues one query per distinct child content type, so "one
  query" is *not* the invariant — see the Testing table for the form the test actually
  takes.)

  **Pairs, not a bare tuple**, because this is the shape the editor row template must
  consume: every container branch in `_element_row.html` needs the slot *id* alongside
  its children to pass as `tab=` to the `_add_menu.html` include and to
  `{% paste_buttons %}`. `TwoColumnElement.resolved_columns` establishes the convention
  (`{% for column, children in obj.resolved_columns %}`,
  `templates/courses/manage/editor/_element_row.html:131`). A bare `(before, after)`
  tuple would force either slot-id string literals in the template (which §1 forbids) or
  two accessor calls per row, re-running `join_row()` and the children queryset each time.

  **`resolved_slots()` is the single accessor** consumed by the student template, the
  editor row branch, and the export walker alike. Both templates distinguish the two
  sides with `forloop.first` rather than comparing against a literal, which is what makes
  `SLOT_IDS` order load-bearing rather than decorative.

  **The unknown-`tab_id` rule belongs to this contract, not only to the Error-handling
  table.** `TwoColumnElement.resolved_columns` — the model §1 tells you to copy — ends
  `return [(col, by_col.get(col["id"], [])) for col in columns]` (`courses/models.py:1757`),
  which silently **drops** a child whose `tab_id` matches no slot. This accessor must do
  the opposite: **any child whose `tab_id` is not in `SLOT_IDS` is appended to the
  `BEFORE_SLOT_ID` bucket**, after that slot's own children and preserving the
  `order`/`pk` ordering. An implementer copying `resolved_columns` verbatim gets the
  dropping behaviour and passes every test but one.
* `render(*, element=None, state=None, slug=None, node_pk=None)` — renders
  `templates/courses/elements/beforeafterelement.html`.

**`eid` must be computed by `render()`.** The context is `el`, `eid`, `slots` (the
`resolved_slots()` pairs), `element_state` (the key is `element_state`, **not** `state` —
`courses_extras.render_element` reads that name), `slug`, `node_pk`, where:

```python
eid = element.pk if element is not None else 0
```

The `0` fallback cannot collide on a served page: `courses_extras.render_element` always
supplies `element` (`:100-107`), so `element is None` occurs only in direct `render()`
calls — i.e. `test_render_seam`'s `CONCRETES` loop.

`node_pk` must **not** be used for this. `node_pk` is the *unit's* pk
(`courses/views.py:491` sets `"node_pk": node.pk`), identical for every element on the
page, so keying DOM ids off it would give every instance the same ids — the exact
duplicate-id bug the namespacing exists to prevent (`courses/static/courses/js/tabs.js:88-91`).

#### `ELEMENT_MODELS` must be extended

Append `"beforeafterelement"` to `ELEMENT_MODELS` (`courses/models.py:261`), which feeds
`Element.content_type`'s `limit_choices_to` (`courses/models.py:324`). This is a required
**source edit**, not something `makemigrations` invents: the
`alter_element_content_type` half of the migration is a *consequence* of it, and without
the edit the migration is `0055_beforeafterelement` alone.

**This edit turns three existing tests RED**, in files with no visible relationship to
this feature — an implementer who does not expect them is likely to mis-diagnose. All
three assert the old count and must move `31` → `32`:

* `tests/test_transfer_schema.py:11` — **and its function name**,
  `test_element_models_lists_all_31_concrete_element_models`, becomes `..._32_...`;
* `tests/test_guessnumber_model.py:11`;
* `tests/test_models_multigrid.py:11`.

Migration `0055_beforeafterelement_alter_element_content_type.py`, schema-only — no data
migration and no backfill, because no existing row can be this type. **Re-check the
migration head immediately before opening the PR**: `0054_imageelement_size` is head
today, but two branches both minting `0055` merge without a git conflict — the same
silent-merge hazard §10 flags for `FORMAT_VERSION`.

### 2. Containment — five seams, not three

`courses/builder.py:58-62` warns that a new container must reach three structures and
names the drift test that enforces it. In practice a *nestable* container needs five:

| # | Seam | Change |
| --- | --- | --- |
| 1 | `builder.CONTAINER_TRANSFER_KEYS` | add `"before_after"` |
| 2 | `builder._CONTAINER_REGISTRY` | `BeforeAfterElement: (lambda _data: {"slots": [{"id": sid} for sid in BeforeAfterElement.SLOT_IDS]}, "slots", "id", None)` — needs `from courses.models import BeforeAfterElement` at module level in `courses/builder.py` (beside the existing `TabsElement` / `SpoilerElement` / `CalloutElement` / `TwoColumnElement` imports at `:10-15`), since the registry is evaluated at import and keys on the class itself |
| 3 | `payloads._CONTAINER_SLOT_KEY` | `"before_after": frozenset(BeforeAfterElement.SLOT_IDS)` |
| 4 | `builder.NESTABLE_TYPE_KEYS` | add `"before_after"` — lets it live inside Tabs/Spoiler/Callout/Two-column |
| 5 | `builder._NESTABLE_FORM_KEY_ALIASES` | `"beforeafter": "before_after"` |

Seam 2's `max_slots` is `None`, meaning "never truncated" — the registry contract at
`courses/builder.py:131-134` says `None` makes `paste_allowed` **skip** the slot-position
check rather than apply a bound. A fixed-slot container is never truncated, so `None` is
correct and `2` would be wrong. The lambda derives its ids from `SLOT_IDS` for the
no-literals reason in §1 (the Spoiler and Callout entries likewise use their `SLOT_ID`
constants).

Seam 5 is not optional. `_NESTABLE_FORM_KEY_ALIASES` translates the element-form key to
the transfer key before `resolve_scope` checks membership;
`test_twocolumn_form_key_alias_exists` exists because without the alias the card is
offered in the nested add-menu and every click 400s.

#### The `_CONTAINER_SLOT_KEY` sentinel must change shape

Today (`courses/transfer/payloads.py:818-823`) the values are either a `str` (the key
under which the container's `data` holds its slot list) or `None`, and `None` means
"single-slot: the only valid id is `SINGLE_SLOT_ID`" — consumed at
`courses/transfer/payloads.py:857-862`:

```python
slot_key = _CONTAINER_SLOT_KEY[parent["type"]]
valid_slot_ids = (
    {SINGLE_SLOT_ID} if slot_key is None
    else {s["id"] for s in parent["data"][slot_key]}
)
```

A **fixed two-slot** container is a third shape that sentinel cannot express. Replace the
sentinel with an explicit set rather than adding a third branch:

```python
_CONTAINER_SLOT_KEY = {
    "tabs": "tabs",
    "two_column": "columns",
    "spoiler": frozenset({SINGLE_SLOT_ID}),
    "callout": frozenset({SINGLE_SLOT_ID}),
    "before_after": frozenset(BeforeAfterElement.SLOT_IDS),
}
...
valid_slot_ids = (
    {s["id"] for s in parent["data"][slot_key]}
    if isinstance(slot_key, str)
    else set(slot_key)
)
```

**Import placement is part of this change.** `_CONTAINER_SLOT_KEY` is module-level, but
`SINGLE_SLOT_ID` is currently imported *inside* `validate_nesting`
(`courses/transfer/payloads.py:838`) and container models are imported inside their
validators — so both names are undefined at module scope today and the dict above would
raise `NameError` at import. Move `from courses.models import SINGLE_SLOT_ID` and
`from courses.models import BeforeAfterElement` to module level (module-level
`courses.models` imports already exist at `:16-18`, so this introduces no import cycle),
and delete the now-redundant local import in `validate_nesting`.

**Two more comments go stale in the templates and tests this feature touches**, and by the
same standard must be rewritten:

* `templates/courses/manage/editor/_add_menu.html:12-16` — "The CONTAINER cards (Tabs,
  Columns, Spoiler, Callout) are guarded by `depth < max_nest_depth|add:-1`…", falsified by
  a fifth container card in the very file the change edits.
* `tests/test_editor_depth.py:162-166` — `test_no_add_menu_inside_a_depth_4_element`'s
  docstring says "`_element_row.html` includes `_add_menu.html` at four sites — tabs,
  two-column, spoiler and callout". This element adds **two more include sites**, one per
  slot.

**A third comment goes stale in `courses/builder.py` itself.** The lines seam 4's new key
joins read `# Containers, as of the depth-3 slice. Both are already in /
# transfer.export.SERIALIZERS, so NESTABLE_TYPE_KEYS <= SERIALIZERS holds.` — "Both"
becomes false with a third container key. Rewrite it, and re-check the
`CONTAINER_TRANSFER_KEYS` header at `courses/builder.py:58-62`, which says a new container
must reach "all three" structures against this spec's finding that a *nestable* container
needs five.

**Rewrite the two comments that document the old sentinel.** The 5-line block above the
dict (`:811-817`, "…`None` means SINGLE-SLOT … `None` already serves as the
not-a-container sentinel") and the inline comment inside `validate_nesting` (`:849-851`)
both become false. In this repo such comments are load-bearing and a stale one is a
defect.

The membership test at `:852` runs *before* this lookup and is unaffected. The only other
reader is the drift test, which uses `set(_CONTAINER_SLOT_KEY)` — keys only — so it is
unaffected too.

This is a targeted change to a structure the feature cannot otherwise use, not a general
refactor: no other sentinel, module or call site is touched.

#### Existing tests that must be updated

* `courses/tests/test_nesting_rule.py::test_container_registry_carries_a_slot_cap`
  asserts `len(reg) == 4`; it becomes `5`, plus
  `assert reg[BeforeAfterElement][3] is None`.
* The three `len(ELEMENT_MODELS) == 31` assertions listed in §1 (`31` → `32`, plus the
  function rename in `tests/test_transfer_schema.py`).
* `courses/tests/test_render_seam.py`'s `CONCRETES` list (`:27`) gains
  `(BeforeAfterElement, {})`. That list is the codebase's designated guard that every
  concrete's `render()` accepts the state kwargs — "the exact class of break plan-review
  and code-review both caught on the mark-done build". It carries **no count assertion**,
  so omitting the entry ships green and leaves the new render seam unguarded.
* `courses/tests/test_render_seam.py`'s **second** guard: `test_lesson_renders_200_with_each_concrete`
  (`:181-187`) is parametrized over `CONCRETES` **and** `placement`
  (`["top", "tabs", "twocolumn", "callout", "spoiler"]`). Add `"beforeafter"` to the
  placement list. `CONCRETES` alone makes this element a *child* in five hosts but never a
  *host* — leaving unexercised exactly the seam #214 made this file guard. The host-side
  fixture must fill a slot with `tab_id = BEFORE_SLOT_ID`; a wrong id would be masked by
  `resolved_slots()`' re-homing rule and the test would pass vacuously.
* `tests/test_manage_editor_menu.py:62` asserts `body.count('data-add-type="') == 23`
  (`23` → **24**), and the `# 11 content cards` comment at `:77` (→ 12). The fixture is a
  **quiz** unit, so the Interactive group is absent and the count covers
  Content + Questions + Structure only — which is precisely why a Content-group card moves
  it. Another file with no visible relationship to this feature.
* `tests/test_manage_editor_menu.py`'s `EL_ICON_MAP` (`:8`), the add-type-key → sprite-symbol
  map that `test_add_menu_icons_are_svg` iterates (`:43`). **Unlike the count assertion,
  this one does not go red** when a card is added without an entry — it silently stops
  covering the new card, so a card pointing at a symbol the sprite never defines (a blank
  icon in the menu) would ship green.
* `tests/test_editor_depth.py`'s `CONTAINER_CARDS` tuple (`:83`) gains `"beforeafter"`.
  This shared constant already drives five depth tests (top-level offer, depth-1, depth-2,
  depth-3 hide, fetch-fragment); without the entry an implementer writes a redundant new
  test while the existing matrix never exercises the new card.
* `test_container_key_spaces_do_not_drift` and
  `test_container_keys_agree_by_key_not_by_count` should pass unchanged once all five
  seams land — they are the guard against a partial landing and **must not be relaxed**.

### 3. Student render

`templates/courses/elements/beforeafterelement.html` (house tag spelling is `{% trans %}`,
as in `templates/courses/manage/editor/_edit_callout.html`):

```html
{% load i18n courses_extras %}
<div class="el el--beforeafter" data-beforeafter>
  <button type="button" class="ba__toggle" aria-pressed="false"
          aria-controls="ba-{{ eid }}-panels"
          {% if not el.button_label %}aria-label="{% trans 'Switch content' %}"{% endif %}>
    <svg class="ic" aria-hidden="true" focusable="false"><use href="#el-beforeafter"/></svg>
    {% if el.button_label %}<span class="ba__label">{{ el.button_label }}</span>{% endif %}
  </button>
  <div class="ba__panels" id="ba-{{ eid }}-panels">
    {% for slot_id, children in slots %}
    <section class="ba__panel" data-ba-side="{{ slot_id }}">
      <p class="ba__side-heading visually-hidden">
        {% if forloop.first %}{% trans "Before" %}{% else %}{% trans "After" %}{% endif %}
      </p>
      {% for child in children %}<div class="ba__child">{% render_element child %}</div>{% endfor %}
    </section>
    {% endfor %}
  </div>
</div>
```

* **`{% load %}` carries `courses_extras`** — that is where `render_element` lives; a
  snippet loading only `i18n` raises `Invalid block tag`. Both sibling containers
  (`calloutelement.html`, `spoilerelement.html`) load the same pair.
* **The panel renders unconditionally.** Unlike `calloutelement.html` /
  `spoilerelement.html`, which wrap their children in `{% if children %}`, an empty slot
  here still emits its `<section>` — that is what makes the "empty ruled panel" row in
  the Error-handling table true rather than aspirational.
* **`.visually-hidden`** is applied as a class in the markup (§4), not copied into
  `.ba__side-heading`'s own declarations.
* **Namespaced ids.** `eid` is the join row's pk, computed in `render()` per §1. There is
  deliberately **no `data-ba-eid` attribute**: nothing reads it — the JS scopes by
  `data-beforeafter` + `closest()`, and the namespacing is carried entirely by the
  `id="ba-{{ eid }}-panels"` / `aria-controls` pair. (`tabs.js` needs `data-tabs-eid`
  only because it *builds* its ids client-side; ours are server-rendered.)
* **Accessible name.** With a label, the visible text names the button. Without one it is
  icon-only and takes a translated `aria-label`; an icon-only button with no accessible
  name is a defect, not a nicety.
* **`aria-pressed`** flips with the state — this is a toggle button, and the state is
  otherwise invisible to a screen-reader user given one label serves both directions.
* **Side headings** are `<p>`, not `<hN>`: they exist for print and for the no-JS
  fallback, and real headings would pollute the lesson's document outline.

### 4. CSS — the left rule

The rule goes on `.ba__panel` itself. **No `.ba__children` wrapper.** The spoiler needed
one (`core/static/core/css/app.css:982-990`) because it had *many* sibling
`.spoiler__child` boxes and a per-child border came out segmented — measured, and
recorded in the #212 design notes: child boxes sit 16px apart because their inner margins
collapse through the child wrapper, and `display: flow-root` fixes the segmentation only
by inflating the element 154px → 202px. Here each side is already **one** box holding all
of that side's children, so a single border per side is continuous by construction and
the wrapper buys nothing.

```css
.ba__panel {
  padding-left: var(--space-4);
  border-left: 2px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
```

Ported verbatim from `core/static/core/css/app.css:986-990`
(`.spoiler__body, .spoiler > .spoiler__children`), including the constraint that makes it
work: **horizontal padding only, no vertical margin, not a `flow-root`**, so the
children's own margins keep collapsing out through the box and the rule starts and stops
on the *content* rather than on the margins.

Do **not** add `> :first-child { margin-top: 0 }` / `> :last-child { margin-bottom: 0 }`.
Those are the *callout's* treatment, needed only because `.callout` has padding that
blocks margin collapsing (`courses/static/courses/css/courses.css:1823-1834` says so
explicitly, warning that the spoiler's rationale does not transfer). Applying them here
would defeat the hug.

`.ba__panels` is a bare grouping div: no margin, no padding, no border, not a
`flow-root`, so margins collapse through it untouched.

#### The element wrapper and the toggle

Both need rules of their own — a `<button>` with no class-based styling renders as a bare
UA button beside an inline SVG, and the Screenshots test row assumes the control meets AA.
All of this lives in `courses/static/courses/css/courses.css`, alongside `.el--tabs`'
block:

* `.el--beforeafter { margin-block: var(--space-6); }`, matching `.el--tabs`.
* `.ba__toggle` borrows **`.spoiler__toggle`'s token set** verbatim
  (`core/static/core/css/app.css:933-945`): `display: inline-flex`, `width: fit-content`,
  `align-items: center`, `gap: var(--space-2)`, `padding: var(--space-2) var(--space-4)`,
  `font: inherit`, `font-weight: 600`, `line-height: 1`, `color: var(--primary)`,
  `background: var(--primary-subtle)`, `border: 1px solid color-mix(in srgb, var(--primary) 32%, transparent)`,
  `border-radius: var(--radius-full)`, **`cursor: pointer`** and
  **`transition: background .15s ease, color .15s ease, border-color .15s ease`** — plus
  the `:hover` and `:focus-visible` states. In short: every declaration in
  `app.css:933-950` except the two `<summary>`-specific ones (`list-style: none` and the
  `::-webkit-details-marker` rule), which do not apply to a `<button>`. `cursor` matters —
  a `<button>`'s UA cursor is `default`, so omitting it ships a control with no pointer
  affordance, which the Screenshots row would not obviously flag. Reusing the spoiler's
  visual language is deliberate: both are "press this to change what you see" controls, and
  an author who has used one should recognise the other.
* `.ba__toggle .ic` sized to the label's line-box so icon-only and icon+label buttons are
  the same height.
* `.ba__toggle { margin-bottom: var(--space-3); }` — the gap goes on **the toggle**, not
  on `.ba__panels`. Two reasons. First, `.ba__toggle + .ba__panels { margin-top: … }`
  would select `.ba__panels` (the adjacent-sibling combinator names the subject on its
  *right*), directly contradicting the no-margin invariant above. Second, the two are not
  equivalent even in effect: the toggle is an `inline-flex` box, so its `margin-bottom`
  does not collapse and yields a fixed gap, whereas a `margin-top` on `.ba__panels` would
  collapse with the first panel content's own `margin-top` and give `max()` of the two.

#### The side headings when they are actually visible

In all three states where the headings show (JS disabled, failed boot, print) they would
otherwise be a bare `<p>` indistinguishable from the panel's own prose, with nothing
marking where "before" ends and "after" begins — which would make §5.3's claim of a
"complete and labelled" fallback false in practice. Give them the house eyebrow treatment
used by `.callout__heading` (`courses.css:1811-1818`): `font-size: 0.75rem`,
`font-weight: 700`, `letter-spacing: 0.08em`, `text-transform: uppercase`,
`color: var(--text-secondary)`.

Scope that treatment **and** any panel separation (`.ba__panel + .ba__panel { margin-top: var(--space-5); }`)
under `html:not(.ba-js)` and `@media print` only. Applied unconditionally, the panel margin
would violate §4's no-vertical-margin constraint in the normal single-visible-panel case.

`.ba__side-heading` carries the existing **`.visually-hidden`** utility **as a second
class in the markup** (`core/static/core/css/app.css:1212`) — see the §3 snippet. It is
taken out of flow, so it neither occupies space nor disturbs the panel's margin
collapsing, and `display` is untouched so the print reveal works.

Its declarations are, exactly:

```css
.visually-hidden {
  position: absolute; width: 1px; height: 1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}
```

It declares six properties; the un-hide rules revert **five**. `white-space: nowrap` is
deliberately left in place — the headings are one word ("Before" / "Przed", "After" /
"Po"), so it changes nothing, and reverting it would be noise. The "five properties" count
used in §5.3, §5.5 and the two CSS test rows is therefore exact, not an oversight.

**Both un-hide rules below (print, §5.5; no-JS, §5.3) must invert precisely these.** In
particular the property is `clip`, **not `clip-path`** — a `clip-path: none` override is a
no-op here and would leave a 1×1 overflow-hidden box, i.e. an invisible heading that
*looks* handled. Reverting `position` alone is likewise insufficient. The full inverse is:

```css
position: static !important; width: auto !important; height: auto !important;
overflow: visible !important; clip: auto !important;
```

#### The `display` invariant, stated precisely

**In the element's own rules in `courses.css` / `app.css`, `.ba__panel` and `.ba__child`
declare no `display`.** That is what keeps the `hidden` attribute working through the UA
default. The armed pre-hide rule (§5), the reveal-cascade pre-hide (§7), the
`html:not(.ba-js)` / `.ba--dead` rules (§5.3) and the print reverts (§5, §7) are the
**stated exceptions** — they are state-scoped rules, not the element's base styling.

**The test needs a mechanical block boundary, and it is prescribed here** rather than left
to the implementer. In `courses.css`, the element's base block opens with the literal
comment `/* Before / after — base */` and ends at the **first occurrence of
`html:not(.ba-js)`**, which is the first state-scoped rule (§5.3 requires that ordering).
The extraction helper must **assert it matched**, as `_prehide_block` and `_print_block`
already do — a silent non-match would make the test vacuous. Without a prescribed
delimiter the likely implementation is a line-offset or a loose regex that swallows the
state rules and goes red on a correct build.

**Decision:** `.ba__child[hidden] { display: none !important; }` **is** added to the
guard at `core/static/core/css/app.css:1010`, joining `.lesson-block[hidden]` and
`.tabs__child[hidden]`. `.ba__child` is a reveal-cascade wrapper exactly as
`.tabs__child` is — the cascade sets `gateWrap.hidden = true` — so it needs the same
protection against an author-supplied `display` beating `[hidden]`. `.ba__panel` is
**not** added: its hiding is driven by this element's own JS, not the cascade.

**Cascade order is load-bearing between that rule and §5.5's print rule.** Both are
`.ba__child[hidden]` (specificity 0-2-0) and both are `!important`, so neither
specificity nor `@media print` decides the winner — **only document order does**, and the
print declaration must come later. It does, because `base.html` loads `app.css` before
`{% block extra_css %}` loads `courses.css`. If any part of §5.5's block is instead placed
in `app.css`, it must sit **after** `:1010`. The CSS test carries a mutant for exactly
this (move the print block earlier → the child stays hidden in print).

Spacing between children inside a panel is left to the children's own margins, as the
spoiler does. No `+` sibling rule (that is again the callout's padding-driven treatment).

### 5. No flash of the answer — pre-hide, not a plain toggle

**This is the requirement that shapes the client design.** Tabs renders every panel
visible and lets JS hide the inactive ones; copying that here paints the solution for a
frame on every page load, which defeats the element's main use.

#### 5.1 The mechanism

1. `courses/views.py` gains `has_before_after`: a **flat** query (deliberately *not*
   scoped to `parent__isnull=True`, so a nested instance is still detected), added to the
   lesson context beside `has_reveal_gate` (`courses/views.py:476-484`). Use the
   **app_label-pinned** form that `has_html` uses —
   `content_type__app_label="courses", content_type__model="beforeafterelement"` — not
   `has_reveal_gate`'s bare `content_type__model__in`; the neighbouring comment records
   that the pin exists to avoid cold-cache `ContentType` SELECTs, and this is a
   single-model lookup.
2. `templates/courses/lesson_unit.html`, when `has_before_after`, emits **in
   `{% block prepaint %}`** an inline `<script>` adding **both `ba-armed` and `ba-js`** to
   `<html>`; **in `{% block extra_css %}`** a `<style>`
   (`html.ba-armed .ba__panels > [data-ba-side="after"] { display: none; }`); and in
   `extra_js` the include
   `<script src="{% static 'courses/js/beforeafter.js' %}" defer></script>`, matching
   `tabs.js` at `lesson_unit.html:81`. **`defer` is load-bearing**, not incidental: it is
   what makes the script run before `DOMContentLoaded`, which the §5.2 boot guard and the
   two script-failure e2e tests in the Testing table both turn on.
3. `courses/static/courses/js/beforeafter.js`, at init, sets the `hidden` attribute on
   each instance's "after" panel, **then** removes `ba-armed` from `<html>`. It does
   **not** touch `ba-js`.

Step 3's ordering is load-bearing: removing `ba-armed` before the attributes are set
opens exactly the flash window the mechanism exists to close. The class removal happens
once, after all instances on the page are initialised.

**`ba-js` must be set by the prepaint script, not by the module.** `beforeafter.js` is a
*deferred external* script: it runs after parsing but carries no guarantee of running
before first paint, and on a slow or contended connection it certainly will not. Since
the no-JS rule (§5.3) is `html:not(.ba-js) .ba__side-heading { … }` — five `!important`
declarations that *un-hide* the headings — setting `ba-js` from the module would leave
that rule in force through first paint, producing a visible "Before"/"After" flash and a
layout shift on every load. That is the same class of defect this whole section exists to
eliminate. The prepaint inline script, by construction, runs only when JS is enabled and
runs before paint, so it is the correct home for both classes.

#### 5.2 The boot guard (a failed script load must not strand the content)

Every existing prepaint block in `templates/courses/lesson_unit.html` pairs its
`classList.add(...)` with a `DOMContentLoaded` guard that removes the class if the module
never booted — `window.__revealBooted` at `:11`, `window.__stepperBooted` at `:24`.

**The flag is set at parse time**, as the first statement of the IIFE, exactly as
`reveal.js:9` does ("The IIFE runs after parsing and before DOMContentLoaded, which is
what lets the watchdog see the engine is alive") and `stepper.js:6` echoes. So
`beforeafter.js` opens with `window.__beforeAfterBooted = true;`, and the prepaint script
disarms on `DOMContentLoaded` when the flag is absent.

**Parse-time placement means the watchdog cannot catch a mid-init throw** — the flag is
already `true`, so the guard does nothing and `ba-armed` would stay applied. That is why
`tabs.js` carries an explicit `bail()` (`:435-450`).

#### Recovery has two scopes, and neither is "remove two classes"

`tabs.js`'s `bail()` **reverses the per-instance DOM state it applied** —
`removeAttribute("inert")`, `removeAttribute("aria-hidden")`, `classList.remove("is-active")`,
`stage.style.minHeight = ""`, `classList.remove("tabs--js")`. Recovery here must do the
same, because `initOne` sets `hidden` on the "after" panel **first**, before wiring the
button: a recovery that only strips `<html>` classes leaves that attribute in place while
`html:not(.ba-js) .ba__toggle { display: none }` hides the one control that could clear it.
The content would be permanently unreachable — precisely the stranding this section exists
to prevent.

**Global recovery — `window.__baDisarm()`.** Defined **in the prepaint inline script**, not
in `beforeafter.js`. This placement is forced: the 404/blocked path is one of the cases
that must recover, and in that path the module never executes, so a module-defined function
would not exist for the watchdog to call. (The existing watchdogs at
`lesson_unit.html:10-14` and `:22-26` are bare inline `classList.remove` calls with no
shared helper, which is why this one must be introduced deliberately.) It:

1. removes `ba-armed` **and** `ba-js` from `<html>`;
2. walks every `[data-beforeafter]` on the page, removing `hidden` from both panels and
   clearing `data-ba-ready`.

Called from two sites: the inline `DOMContentLoaded` watchdog when
`window.__beforeAfterBooted` is absent, and `beforeafter.js`'s **document-level** `catch`
for a throw outside any single instance.

**Per-instance recovery.** The `try`/`catch` lives **inside `initOne`**, as `tabs.js`'s
does — not around the whole boot. A single global `try` would abort instances 4–5 when
instance 3 throws while leaving 1–2 fully armed, and then a global `disarm()` would hide
*every* toggle, stranding the two instances whose own init succeeded. Instead `initOne`'s
`catch` un-arms **only its own container**: remove `hidden` from its two panels, clear
`data-ba-ready`, and add `ba--dead` to the container. `.ba--dead` is the per-instance
analogue of `html:not(.ba-js)` and shares its declarations by grouped selector (§4), so
that one instance shows both panels, labelled, with its toggle hidden — and its siblings
keep working.

`initAll` wraps each `initOne` call so a throw can never escape into the caller. That
matters on the editor path: `editor.js` calls `libliInitBeforeAfter(preview)` in a sequence
of re-init calls (`:105`), and an escaping throw would abort every enhancer sequenced after
it — tabs, imagezoom, reveal gates — silently, on a page with no watchdog to recover.

Every recovery path logs via `console.error`.

Without any of this, a 404 / throw / blocked script leaves `ba-armed` applied forever and
the "after" content is permanently unreachable with no way back — strictly worse than the
reveal gate this design claims to improve on.

#### 5.3 The no-JS fallback needs a persistent hook

`ba-armed` cannot distinguish "JS disabled" from "initialised normally" — it is absent in
both cases. That is why the prepaint script also sets a **persistent `ba-js` class**: the
side headings are revealed by `html:not(.ba-js) .ba__side-heading`, which is true only
when the element's JS is not in play.

These rules live in **`courses/static/courses/css/courses.css`**, immediately *after* the
element's base block and *before* the `@media print` block of §5.5. That position matters
for §4's display-invariant test: the scan's block boundary ends where the base block does,
so these state-scoped rules — which legitimately declare `display` — sit outside it.

The rule body must be the **full five-property inverse** from §4, not a guess like
`display: block` (which reveals nothing, because the heading is hidden by
`position`/`width`/`height`/`overflow`/`clip`, not by `display`). Every selector is grouped
with its **`.ba--dead` per-instance twin** (§5.2), so a single failed instance degrades
exactly as a JS-less page does:

```css
html:not(.ba-js) .ba__side-heading,
.ba--dead .ba__side-heading {
  position: static !important; width: auto !important; height: auto !important;
  overflow: visible !important; clip: auto !important;
  /* eyebrow treatment — see §4 */
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-secondary);
}
html:not(.ba-js) .ba__panel + .ba__panel,
.ba--dead .ba__panel + .ba__panel { margin-top: var(--space-5); }
html:not(.ba-js) .ba__toggle,
.ba--dead .ba__toggle { display: none; }
```

The eyebrow and separation declarations are written **here**, not left to §4's prose — §4
states the treatment and its scoping, this block is where it lands.

There are **three degraded states**, and the recovery contract of §5.2 is what makes them
land in the same place:

| State | `ba-armed` | `ba-js` | `hidden` on "after" | Result |
| --- | --- | --- | --- | --- |
| JS disabled entirely | never added | never added | never set | Both panels visible, stacked, each under a revealed heading; toggle hidden |
| `beforeafter.js` 404s / blocked | added, removed by `__baDisarm()` | added, removed by `__baDisarm()` | never set (module never ran) | Identical to the above |
| Module boots, `initOne` throws | removed by the document-level path | removed likewise | **set, then removed by the per-instance `catch`** | Identical, for the failed instance only; siblings keep working |

All three end **complete and labelled** — a better fallback than the reveal gate's, and the
reason the classes are set by script rather than server-rendered. Two failure modes this
contract exists to exclude: recovery that removes only `ba-armed` leaves *unlabelled*
panels with a live dead button; recovery that removes only the classes and not `hidden`
leaves the "after" side unreachable with the toggle hidden.

The toggle is hidden in both, by `html:not(.ba-js) .ba__toggle { display: none; }`:
leaving a focusable button that advertises `aria-pressed="false"` while doing nothing is
worse than not offering it, since both panels are already shown.

#### 5.4 Quiz units are armed too

`build_quiz_context` (`courses/views.py:1139`) also sets `has_before_after`, and
`templates/courses/quiz_unit.html` emits the same prepaint script, pre-hide style and
script include.

**Only the script block is new.** `quiz_unit.html` defines `{% block extra_css %}` (`:4`),
`{% block content %}` (`:9`) and `{% block extra_js %}` (`:14`) — it has **no `prepaint`
block at all**, because the reveal gate and stepper (the only existing prepaint users) are
lesson-only. So `quiz_unit.html` gains a new `{% block prepaint %}` for the arming
`<script>`; the pre-hide `<style>` goes in the `extra_css` block it already has.

That split mirrors `lesson_unit.html`, where `prepaint` (`:4-31`) holds only the arming
scripts and the reveal pre-hide `<style>` sits in `extra_css` (`:37-45`) — which is why
`_prehide_block` in `test_reveal_scope_agreement.py` anchors inside the latter. Note the
pre-hide is render-blocking simply because **any `<style>` in `<head>` is**; it does not
depend on sitting above the stylesheet links.

The add-menu group choice in §8 is load-bearing here: an element card placed in the
**Interactive** group is wrapped in `{% if not unit_is_quiz %}` and can never be authored
in a quiz unit at all, which would make this whole sub-section dead code.

**The graded-child boundary.** Since `fill_blank` is nestable (see the decisions table), a
before/after in a quiz unit can legally hold a graded question in its hidden "after" slot
— by import, by `duplicate_element`, by converting a lesson unit to a quiz, or by a direct
POST (`_add_menu.html`'s own comment records that card hiding is "COURTESY only"). The
student can always reach it by pressing the button; if they never do, it submits
unanswered.

This is **not a new exposure**, which is why it does not change the arming decision: Tabs
and Callout are already in the Content group, already offered in quiz units, already
accept `fill_blank`, and Tabs already hides its inactive panels. A before/after is the
same shape. The reveal gate is inert in quizzes for a different reason — it interacts with
submission — which does not apply here.

This is a deliberate **departure from the reveal gate**, which is inert in quizzes. A
reveal gate hides graded content and interacts with submission; a before/after has no
state, no endpoint and no grading interaction, so arming it is safe. Leaving it unarmed
would permanently expose the answer side in every quiz unit and break success criterion 2.

#### 5.5 Print

`@media print` reveals both panels and both side headings. The declaration matters:
the existing reveal print block uses `display: revert !important`
(`core/static/core/css/app.css:1014-1022`), and `revert` rolls back to the **UA origin**,
which is exactly where `[hidden] { display: none }` lives — so `revert` **cannot** un-hide
an element carrying the `hidden` attribute. The panels therefore need an explicit:

This block lives in **`courses/static/courses/css/courses.css`**, alongside the element's
other base styling — deliberately *not* in `app.css`. If any part of it were added to
`app.css` it must go **after** the existing `@media print` block at `:1014-1022`, because
`_print_block` in `courses/tests/test_reveal_scope_agreement.py` extracts the **first**
`@media print` block in the file (`re.search(r"@media print\s*\{(.*?)\n\}", css, re.S)`)
— inserting a second one above it makes that test extract the wrong block and go RED
against a correct implementation.

```css
@media print {
  .ba__panel[hidden] { display: block !important; }
  html.ba-armed .ba__panels > [data-ba-side="after"] { display: block !important; }
  .ba__child[hidden] { display: block !important; }
  .ba__toggle { display: none !important; }
  .ba__side-heading {
    position: static !important; width: auto !important; height: auto !important;
    overflow: visible !important; clip: auto !important;
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-secondary);
  }
  .ba__panel + .ba__panel { margin-top: var(--space-5); }
}
```

The eyebrow and panel-separation declarations are **required here too**, not only in the
`html:not(.ba-js)` block. Print is the *only* path that reaches these headings on a
working JS page, so omitting them ships a printed page with two panels butted together
under two unstyled bare `<p>`s — which is exactly the state §4 says would make the
"complete and labelled" claim false.

The `.ba__side-heading` declarations are the full five-property inverse of
`.visually-hidden` from §4 — `clip`, not `clip-path`. The heading's *visual* treatment
(eyebrow styling, panel separation) is scoped to this block and `html:not(.ba-js)`, per §4.

`.ba__toggle` is hidden because both panels are revealed in print, leaving the control
meaningless ink. This follows the house precedent: the shared print block ends
`[data-reveal-gate] { display: none !important; }`, and `courses.css:2044` hides
`.unit-strip__edit`.

The `.ba__child[hidden]` line is here for the reason §7 explains: the reveal cascade hides
gate siblings with the `hidden` attribute, and the existing shared print block's
`display: revert !important` cannot un-hide those, by the very argument this sub-section
makes for `.ba__panel`.

These are **different rules** from the reveal-cascade sibling revert §7 asks for; all are
needed.

### 6. Client — `courses/static/courses/js/beforeafter.js`

~70 lines, copying `tabs.js`'s proven core and inventing nothing:

* **Two-level contract, explicitly split.** `initOne(container)` / `initAll(root)` do
  **per-instance work only**: set `hidden` on the "after" panel, wire the button, set
  `data-baReady`. `initOne` owns a `try`/`catch` around its own work and recovers only its
  own container (§5.2); `initAll` wraps each call so nothing escapes to the caller. The
  **document-level boot** — and only it — removes `ba-armed` from `<html>` on success, and
  calls `window.__baDisarm()` for a failure outside any instance.
  `window.libliInitBeforeAfter` is bound to **`initAll`** — the root-scoped *enhancer*, not
  the document-level *boot*. (The contrast is boot-vs-enhancer, not root-vs-instance:
  `editor.js` passes a `preview` **root**, so exporting `initOne` would break the editor
  re-init.)

  This matters at a live call site: `editor.js` re-inits with a `preview` root on a page
  that has **no prepaint script and no `ba-armed`**. If the exported function also mutated
  `<html>` or set the boot flag, it would either throw on absent classes or run
  "once-only" work on every fragment swap.

  **The editor page must still carry `ba-js`** — see §8. Without it the `html:not(.ba-js)`
  rules of §5.3 are permanently in force in the editor: the preview's toggle would be
  `display: none` and both side headings un-hidden, while `initAll` still sets `hidden` on
  the "after" panel. The preview would show one labelled panel and no control — and the
  "toggles after a fragment swap" e2e would be RED against an otherwise correct build.
* **Idempotence** — set and read the guard through the **`dataset` property**
  (`container.dataset.baReady = "1"`, tested as `container.dataset.baReady === "1"`), which
  produces the attribute `data-ba-ready`. Do **not** `setAttribute("data-baReady", …)`:
  attribute names lowercase to `data-baready`, which `dataset.baReady` would never read —
  silently defeating the guard, so the editor preview re-wires the button on every
  fragment swap. The editor pane is rebuilt on every swap and re-runs init over the whole
  pane (`tabs.js:66-68`).
* **Export** — `window.libliInitBeforeAfter(root)`, so the editor can re-run it after a
  swap, mirroring `libliInitTabs` / `libliInitGallery`. The export is inert without the
  **two editor seams** in §8: `libliInitTabs` works in the editor only because
  `templates/courses/manage/editor/editor.html:170` includes `tabs.js` *and*
  `courses/static/courses/js/editor.js:105` calls it after each fragment swap. Omit
  either and the live-preview pane shows both panels stacked under a dead button.
* **Boot flag** — `window.__beforeAfterBooted = true` (§5.2).
* **Ownership scoping** — every lookup rejects nodes owned by a nested instance
  (`el.closest("[data-beforeafter]") === container`). A before/after may legally contain
  another one, and an unscoped `querySelectorAll` would let the outer instance drive the
  inner's panels (`tabs.js:34-63`).
* **`hidden` attribute, never inline `display:none`** — an inline style cannot be
  overridden by the `@media print` rule (`tabs.js:166-168`).
* **`libli:reveal`** — dispatched on the newly shown panel, `bubbles: true`, so a gallery,
  carousel or table inside it re-measures instead of sitting at the zero height it
  measured while hidden (`tabs.js:172-174`).
* **Toggle ordering is load-bearing**, as §5.1 step 3's is: remove `hidden` from the
  incoming panel **first**, then set `hidden` on the outgoing one, then update
  `aria-pressed`, then dispatch `libli:reveal` on the now-visible panel. A listener that
  measures synchronously would read zero if the event fired first — and the "gallery
  measures non-zero" e2e would not catch it, because `tabs.js`'s own listener is
  rAF-deferred and would mask the ordering.
* `aria-pressed` updated on the button each toggle: **`"true"` means the "after" panel is
  visible**, `"false"` means "before". The polarity is pinned because `aria-pressed` is the
  only signal a screen-reader user gets about which side is showing (see the decisions
  table), and "flips" alone would be satisfied by an inverted mapping.

The element deliberately has **no** keyboard-navigation layer beyond the button being a
button: one control, activated by Enter/Space natively.

**No height reservation — the reflow is accepted.** The two slots will routinely differ in
height, so toggling reflows whatever follows the element. The tabs *carousel* reserves
height (`stage.style.minHeight`) because its slides are a fading stage; this is a plain
swap, and reserving the taller side's height here would fight the design: the left rule is
specified to hug its content exactly (§4), so a reserved box would leave a tall empty ruled
box hanging under a short "before" side. It would also have to measure a panel that is
`display: none` at first paint, which measures zero.

The Purpose section's "without losing their position on the page" is satisfied by the
**button being above the panels** — the control the student just pressed does not move
under them. Content below the element does move; that is inherent to swapping content and
is what the author is asking for.

### 7. `scopeOf` becomes a fifth scope

`courses/tests/test_reveal_scope_agreement.py` pins a **4-tuple** of cascade scopes
(`[data-tab-panel]`, `.slide`, `.spoiler__children`, `.callout__children`) across
**three** files. Since `reveal_gate` is nestable, a gate may be authored inside a panel,
so `.ba__panel` must join all three *and* the test's `SCOPES` tuple:

1. `scopeOf` in `courses/static/courses/js/reveal.js:52-54`;
2. the pre-hide `<style>` block in `templates/courses/lesson_unit.html`;
3. the `@media print` revert in `core/static/core/css/app.css:1014-1022`;
4. the `SCOPES` tuple in `courses/tests/test_reveal_scope_agreement.py`, plus the
   docstrings and test names that say "four";
5. the two comment blocks in `courses/static/courses/js/reveal.js` that **enumerate** the
   scopes and become false: `:40-42` ("a slide in a slideshow lesson, a tab panel inside a
   tabs element, a spoiler body, or a callout's children wrapper") and `isGateWrapper`'s
   block at `:55-63` ("Four scopes exist… those three scopes share the same direct-child
   form"). §2 sets the standard that a stale comment in this repo is a defect; it applies
   here as much as to the `_CONTAINER_SLOT_KEY` comments.

**§7's print entry is knowingly inert for a `[hidden]` child.** Adding `~ .ba__child` to
the shared `@media print` block satisfies the *scope-agreement* requirement that test
enforces, but that block's declaration is `display: revert !important`, and `revert` rolls
back to the UA origin where `[hidden] { display: none }` lives — so it cannot un-hide a
`.ba__child` the reveal cascade hid via `gateWrap.hidden = true`. This is pre-existing
behaviour shared with `.tabs__child`, not something this feature introduces; the working
un-hide is the explicit `.ba__child[hidden] { display: block !important }` in §5.5's
block. Both are required and they do different jobs.

That test has **no count assertions** — all three of its tests are containment loops over
`SCOPES`, plus one extra `assert _has_scope(scope_of, ".spoiler")` covering the deliberate
legacy fifth selector. So the work is "extend the tuple and the wording", not "update
exact-four assertions".

**Which `<style>` block.** `lesson_unit.html` will now contain two pre-hide blocks (the
`has_reveal_gate` one at `:37-38` and the new `has_before_after` one). The scope entry
must go in the **`has_reveal_gate` block**, because `_prehide_block` in that test extracts
only the block anchored on `has_reveal_gate %}\s*<style>` — putting it in the new block
turns the test red. Use the full selector shape the block's siblings use, including the
`:not(.reveal-shown)` suffix, without which a revealed sibling stays hidden:

```
.reveal-armed .ba__panel > .ba__child:has(> [data-reveal-gate]) ~ .ba__child:not(.reveal-shown)
```

`.ba__panel` is the correct scope because it is the element whose **direct** children are
the `.ba__child` rows the cascade walks sibling-by-sibling, which is what `ownWrapper`
(`courses/static/courses/js/reveal.js:59-63`) requires. Miss any of the four and a reveal
gate inside a panel silently escapes its scope — the failure #212 hit when it introduced
`.spoiler__children`.

### 8. Editor

The editor work splits across **two** templates; putting it all in one is the most likely
implementation error.

* **`templates/courses/manage/editor/_edit_beforeafter.html`** — the open **form only**:
  the `button_label` input. Modelled on `_edit_callout.html`, which is likewise only form
  fields. It must open with `<div class="el-editor el-editor--beforeafter">`, the wrapper
  every `_edit_*.html` partial uses: `_host_form.html` includes them via
  `{% include "courses/manage/editor/_edit_"|add:type_key|add:".html" %}`, and `.el-editor`
  is a load-bearing grid item in `editor.css` — it is the container the
  fieldset/`min-inline-size` scroll fix keys on, so a bare `<label>` would sit outside the
  grid. Inside: the `name="button_label"` input with `maxlength="120"` and its
  `{% for e in form.button_label.errors %}` row, mirroring `_edit_callout.html`'s heading
  field.
* **`templates/courses/manage/editor/_element_row.html`** — a new
  `beforeafterelement` branch carrying the **two stacked slot panels**, their headings
  (**Before / Przed**, **After / Po**), the child rows and the per-slot add controls.
  This is where container children live for every existing container (the callout branch
  at `:198`, the spoiler branch at `:146`), because `children_map`, `open_form_pk`,
  `clip_element_pk` and `depth` are in scope there and nowhere else.

  It loops `{% for slot_id, children in obj.resolved_slots %}` (the pairs accessor from
  §1) and closes **each** slot with both the add-menu include and the paste control, in
  the form every sibling container uses (`:141`, `:195`, `:244`):

  ```
  {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=slot_id depth=depth %}{% endif %}{% paste_buttons el.pk slot_id %}
  ```

  **Omitting `{% paste_buttons %}` would make this the only container you cannot paste
  into**, even though the registry entry §2 adds makes `paste_allowed` handle it
  correctly — a silent capability hole.

  The branch **must match a nested instance too** — do not gate it on
  `el.parent_id is None`. The spoiler branch's comment records that dropping exactly that
  clause was required for depth-3 nesting.

Registration points:

| File | Change |
| --- | --- |
| `courses/element_forms.py` | define `class BeforeAfterElementForm(forms.ModelForm)` with `Meta: model = BeforeAfterElement; fields = ["button_label"]` — mirroring `CalloutElementForm` (`:225-228`); `Meta.model` is what tells `element_add` which concrete row to create. **And** register it in `FORM_FOR_TYPE` (defined at `:1954`): `"beforeafter": BeforeAfterElementForm` — defining the class alone leaves the edit form unrendered |
| `courses/views_manage.py` | add `"beforeafter"` to the `element_add` allow-tuple (`~:1823`) **and** to the `element_save` allow-tuple (`~:1894`) — two separate edits; the tuples genuinely differ (`slidebreak` is in save but not add) |
| `courses/views_manage.py` | add `"beforeafter": gettext_lazy("Before / after")` to `_EDITOR_TYPE_LABELS` (`:1621-1652`), which supplies the open-form heading — **form-key** keyed |
| `courses/templatetags/courses_manage_extras.py` | add `"beforeafterelement": _("Before / after")` to `_ELEMENT_LABELS` (`:32-63`) — **content-type-model** keyed, a different namespace from the row above |
| `courses/templatetags/courses_manage_extras.py` | add a branch to `element_summary` (`~:118`): `if name == "BeforeAfterElement": return el.button_label or _("Before / after")` |
| `templates/courses/manage/editor/_add_menu.html` | the add card, in the **Content** group (`:27`) next to Callout/Tabs/Columns — **not** the Interactive group, which is wrapped in `{% if not unit_is_quiz %}` (`:41`) and would make the element unauthorable in quiz units, killing §5.4. Carries the **same depth guard** as those cards at `:37-39`: `{% if depth < max_nest_depth\|add:-1 %}` — without it the card is offered at depth 3 and every child add 400s |
| `templates/courses/manage/editor/editor.html` | include `<script src="{% static 'courses/js/beforeafter.js' %}" defer></script>` beside the `tabs.js` include at `:170` — the preview pane renders the *student* template, so without it the preview button is dead |
| `templates/courses/manage/editor/editor.html` | **a new `{% block prepaint %}` setting `ba-js` only** — never `ba-armed`. `editor.html` currently defines no such block and `base.html:43` renders an empty one, so overriding it is safe. Unconditional (the editor cannot know which element types a unit holds without a query, and one class costs nothing). Without it the §5.3 no-JS rules fire in the preview: hidden toggle, un-hidden headings — see §6 |
| `courses/static/courses/js/editor.js` | call `if (preview && window.libliInitBeforeAfter) window.libliInitBeforeAfter(preview);` beside the `libliInitTabs` call at `:105`, re-enhancing after each fragment swap |
| `templates/courses/manage/_icon_sprite.html` | `el-beforeafter` symbol |
| `core/help.py` | add `"beforeafter"` to `ELEMENT_ICON_SLUGS` (`:40`) — the sprite id minus the `el-` prefix; `test_element_icon_slugs_match_sprite` goes red if the symbol lands without it |
| `courses/static/courses/css/editor.css` | slot-panel styling for the classes named below |
| `docs/help/course-admin/content-editors.md` | a new `{el:beforeafter}` paragraph in the Content section, **plus** three enumerations this feature falsifies: `:146` "Tabs, Columns, Spoiler, and Callout are the four container types", `:155` the nested add-menu list, `:163` the quiz-specific list. Adding the sprite slug to `ELEMENT_ICON_SLUGS` without the doc entry leaves the icon token defined and unused |
| `docs/help/course-admin/content-editors.pl.md` | the Polish twin of the above |

**The branch reproduces the sibling row scaffolding first.** The container-specific part is
only the tail. Before it, the branch must emit exactly what the callout branch at `:199`
does:

* `<li class="el-row el-row--beforeafter{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}{% if clip_element_pk == el.pk|stringformat:'s' %} el-row--marked{% endif %}"` with `data-element`, `data-updated`, `data-unit`;
* `<div class="el-row__head">` containing the drag grip (`iconbtn ica--grip`) **and**
  `<div class="el-row__body">` > `<div class="el-row__top">`, which holds:
  * `<span class="el-tag">{% element_type_label el.content_type obj %}</span>` — **the only
    consumer of the `_ELEMENT_LABELS` entry this section requires**
    (`courses_manage_extras.py:76-83`). Omit the span and that entry has no consumer at
    all, and the row ships with no type tag while every other row has one;
  * `<span class="el-actions">` with `el-act-edit` (carrying `data-form-url`),
    `el-act-cancel`, and the `_element_row_controls.html` include;
* then, still inside `el-row__body`, the `el-row__label` button rendering
  **`{% if el.title %}{{ el.title }}{% else %}{{ obj|element_summary }}{% endif %}`**
  (`:217`). The `el.title` fallback is not optional: dropping it would make before/after
  the only element type whose author-set `Element.title` is ignored in the editor tree;
* **`<div class="el-edit-slot" data-edit-slot>{% if open_form_pk == el.pk|stringformat:'s' %}{{ open_form|safe }}{% endif %}</div>`** — this div is the *only* place
  `_render_open_form`'s rendered form lands. Omit it and `_edit_beforeafter.html` can be
  written, `FORM_FOR_TYPE` registered, and the author still never able to set
  `button_label` — failing success criterion 1 with every other test green.

**Editor row markup, named explicitly.** Every sibling branch is concrete
(`el-row__columns` / `columns-rows`, `el-row__spoiler`, each with an `{% empty %}`
`<li class="empty-state">`). The container-specific tail is:

```
<div class="el-row__ba">
  {% for slot_id, children in obj.resolved_slots %}
  <div class="ba-rows" data-ba-slot="{{ slot_id }}">
    <div class="ba-rows__label">{% if forloop.first %}{% trans "Before" %}{% else %}{% trans "After" %}{% endif %}
      <span class="ba-rows__count">{{ children|length }}</span></div>
    <ol class="element-list element-list--nested">
      {% for child in children %}…{% empty %}<li class="empty-state">{% trans "No content yet" %}</li>{% endfor %}
    </ol>
    {% if depth < max_nest_depth %}{% include … with nested=True parent=el.pk tab=slot_id depth=depth %}{% endif %}{% paste_buttons el.pk slot_id %}
  </div>
  {% endfor %}
</div>
```

Two details that are easy to lose:

* **`<ol class="element-list element-list--nested">` is required** as the child-row
  wrapper — every sibling branch uses it (`:84`, `:134`, `:184`, `:233`) and three
  `editor.css` rules key on it: `.element-list` (`:523`, the `list-style: none` +
  flex-column + gap), `.element-list--nested`'s left rule (`:1060`), and
  `.element-list--nested .ica--grip { display: none }` (`:584`). Loose `<li>`s in a `<div>`
  would show bullets, no gap, no hanging rule, and drag grips no other container shows.
* **`ba-rows__label`, not `ba-rows__summary`.** `columns-rows__summary` is the class on a
  literal `<summary>` element (`:132`), and this element has no `<details>` (see below), so
  a `__summary` name would describe markup that does not exist and may inherit
  `<summary>`-specific styling (marker, cursor) that cannot transfer. The count badge is
  kept — `ba-rows__count`, mirroring `columns-rows__count`.

"No content yet" / "Brak treści" is a new translatable string (§10).

**The slots are plain always-open `<div>`s, not `<details>`.** The columns and tabs
branches wrap each slot in a `<details>` whose open state is driven by
`{% if el.pk|slot_key:column.id|in_set:open_slots %} open data-force-open{% elif clip_active %} open data-force-open{% elif forloop.first %} open{% endif %}`,
because those containers can have up to 4–8 slots and collapsing is what keeps the tree
readable. With exactly two fixed slots there is nothing to collapse, and the machinery
(`open_slots`, `slot_key`, `in_set`, `clip_active`, `data-force-open`, and
`builder.ancestor_slots`' guarantee that a newly added child is never born inside a
collapsed `<details>`) is then unnecessary. Carry `data-ba-slot="{{ slot_id }}"` on each
slot div as the e2e hook.

These classes **must be disjoint from the student `.ba__panel` / `.ba__child` names**. If
the editor reused `.ba__panel` and `editor.css` gave it a `display`, §4's
`[hidden]`-through-the-UA-default invariant would break in the preview pane — and the §4
CSS test, scoped to the element's own block in `courses.css`/`app.css`, would not see it.

`COURSE_SCOPED_TYPE_KEYS` is **not** touched — the element has no media field, so its
form takes no `course=`.

### 9. Math detection

`_element_has_math` (`courses/views.py:176`) is a Python walk over *top-level* elements,
and every container has an explicit recursing branch — `_spoiler_has_math` (`:281`),
`_callout_has_math` (`:249`), `_twocolumn_has_math` (`:298`). Without one,
`BeforeAfterElement` falls through to the final `return (_table_has_math(obj) or …)` →
`False`, so KaTeX's CSS and JS never load and a unit whose only math sits inside a
before/after renders `\(…\)` literally. The Purpose section names "an equation before and
after simplification" as a headline use case, so this is not a corner.

Add `_before_after_has_math`, dispatching every child of **both** slots through
`_element_has_math`.

**Model it on `_twocolumn_has_math` (`courses/views.py:298-311`), not
`_callout_has_math`.** `_callout_has_math`'s guard sits *after* its heading/body checks,
and its own docstring (`:270-274`) says a top-of-function guard is "correct in
`_twocolumn_has_math`, which has no text of its own". `BeforeAfterElement` likewise has no
text of its own — `button_label` is plain text with no math by decision — so the
top-of-function **transient (`join_row() is None`) guard** is right, and the callout is
the model the codebase explicitly documents as *not* transferring to this shape. (The
`isinstance` guard is separate and unremarkable: all four helpers already open with one.)

**Wiring it is a separate step from writing it.** `_element_has_math` (`:176-222`) wires
its helpers two different ways: `_spoiler_has_math` / `_callout_has_math` get explicit
`isinstance` clauses at `:200-203`, while `_twocolumn_has_math` is folded into the
trailing `return _table_has_math(obj) or …` chain at `:216-221` (which works only because
each helper self-guards). Use an **explicit `isinstance(obj, BeforeAfterElement)` clause
beside the spoiler/callout ones** — the closer match, and unmissable. Written but unwired,
the helper is dead code and the bug survives.

`math.js`'s scope list is deliberately **unchanged**: children are rendered elements
(`.el--text` etc.) already covered by it, and `button_label` is plain text by decision.

### 10. Icon and i18n

The sprite has no cycle/refresh glyph today. Add `el-beforeafter`: two arrows following a
circle, drawn as a monochrome `currentColor` line SVG on the 16×16 grid the other `el-*`
symbols use — never emoji.

New translatable strings, all with Polish catalogue entries: element name **Before /
after → Przed / po**; slot headings **Before → Przed**, **After → Po**; the icon-only
button's `aria-label` **Switch content → Zmień treść**; the editor empty state
**No content yet → Brak treści** (§8); the editor slot labels, which reuse the
**Before / After** strings above; and the transfer error label **before/after data →
dane przed/po** (§11).

Module-level dicts must use `gettext_lazy`, and `makemessages` fuzzy-prefills must be
cleared, not accepted.

### 11. Transfer — no `FORMAT_VERSION` bump

`FORMAT_VERSION` stays **9**. The precedent is unambiguous: `callout` (`c10994bc`) and
`guess_number` (`f962a4a5`) both entered `SERIALIZERS` without a bump; the version is
raised only when an *existing* payload shape changes (iframe w/h → 2, nested elements →
3, choice feedback → 4, spanning tables → 5, link nodes → 6, image size → 7, table cell
images → 8, collision resolution → 9).

An older instance meeting an archive containing the new type fails loudly and correctly at
`courses/transfer/payloads.py:942` — *"Unknown element type … this archive may come from a
newer application version."* That is the designed behaviour, not a gap.

Not bumping also sidesteps the silent-merge hazard: two branches setting `FORMAT_VERSION`
to the *same* new number do not conflict in git, merge green, and ship two incompatible
formats under one version.

#### The payload shape, pinned

`validate_element_data` requires `el["data"]` to be a dict and every validator calls
`_exact_keys`. Leaving the shape unstated invites an implementer to emit `{}`, which would
drop `button_label` on every export, import **and `duplicate_element`** — invisibly, if
the only round-trip test checks children.

* `def _ser_before_after(concrete, media_ids): return {"button_label": concrete.button_label}`
  — **two positionals**, as every serializer in `courses/transfer/export.py` takes
  (`_ser_callout(concrete, media_ids)` at `:121`, with an inline reminder at `:133-135`
  that "real serializers take (concrete, media_ids)"). A one-arg definition `TypeError`s on
  the first export.
* `_val_before_after` does `_exact_keys(data, ["button_label"], _("before/after data"))`
  — the third positional is a required translated label, used in all three error messages
  this helper raises (`courses/transfer/schema.py:97`; `_val_callout` passes
  `_("callout data")`) — plus
  `check_str(data["button_label"], _("button label"), max_length=120)`, and returns
  `set()` (references no media). Mirrors `_val_callout`
  (`courses/transfer/payloads.py:206`). Note `check_str`'s **second positional is a
  translated field label** in all ~20 of its call sites (`:210`:
  `check_str(data["heading"], _("heading"), max_length=120)`); omitting it is a
  `TypeError`.
* `_build_before_after` in `courses/transfer/importer.py`, shaped exactly like
  `_build_callout` (`:544-550`) — a **2-tuple** of `(concrete, created_files)`, built with
  `_clean_save` rather than `.objects.create` so the validated `CharField` is checked:

  ```python
  def _build_before_after(data, assets):
      return _clean_save(BeforeAfterElement(button_label=data["button_label"])), ()
  ```

  Returning a bare instance would break every import *and* every `duplicate_element` —
  the same "defined but wrong" hazard as the dispatch dicts below.

**Defining the three functions does nothing on its own — each must be registered in its
dispatch dict**, exactly the hazard §8 calls out for `element_forms.py`:

Line numbers below are the **dict definitions**, matching how every other reference in this
spec cites a location:

| Registry | Defined at | Entry |
| --- | --- | --- |
| `courses/transfer/export.py` `SERIALIZERS` | `:461` | `"before_after": (BeforeAfterElement, _ser_before_after)` |
| `courses/transfer/payloads.py` `VALIDATORS` | `:896` | `"before_after": _val_before_after` |
| `courses/transfer/importer.py` `BUILDERS` | `:817` | `"before_after": _build_before_after` |

Without the `export.py` entry the element is not exportable at all, failing success
criterion 4.

#### The export tree-walker branch

`courses/transfer/export.py` has a separate `emit()` walker (`~:626`) with an `isinstance`
branch per container — `TabsElement` (`:627`), `TwoColumnElement` (`:631`),
`SpoilerElement` (`:635`), `CalloutElement` (`:638`) — that yields each child with its
slot id. **Without a `BeforeAfterElement` branch the serializer runs but no children are
ever emitted**, so success criterion 4 fails silently.

The branch consumes `resolved_slots()` (§1) — the same accessor the templates use — and
yields each child under **the pair's `slot_id`**, never the child's own `tab_id`. Every
sibling branch does the same (`tab["id"]`, `col["id"]`, `SLOT_ID`).

This matters because `walk_unit_joins`' docstring (`courses/transfer/export.py:595-598`)
states an invariant: *"Children are reached ONLY through `resolved_tabs()` /
`resolved_columns()` / `resolved_children()`, never `join.children.all()`: a child whose
`tab_id` matches no slot is deliberately OMITTED, because exporting it would produce a
payload the import validator rejects."* Yielding the child's own `tab_id` would break it —
`resolved_slots()` re-homes a stray child into `before` (§1) rather than dropping it, so
the walker would emit a corrupt `tab_id` that `validate_nesting` then rejects against
`_CONTAINER_SLOT_KEY["before_after"]`. Export would succeed and import would fail; and
since `duplicate_element` routes through `build_element_export` → `graft_elements`,
duplication would break the same way.

Yielding the slot id satisfies the invariant's *purpose* — never emit a slot id the
validator will reject — while improving on the sibling behaviour: the stray child is
re-homed rather than silently lost, and export now matches what the student actually sees.
**Update that docstring** to name `resolved_slots()` as a fourth accessor and to record
that this container re-homes rather than omits.

This also silently thins duplication: `builder.duplicate_element` routes through
`build_element_export` → `graft_elements`, so a missing branch makes "duplicate" return
200 with an empty copy.

## Data flow

**Authoring.** Add card → `views_manage.element_add` with type `beforeafter` →
`resolve_scope` translates the form key via `_NESTABLE_FORM_KEY_ALIASES` when nested →
`BeforeAfterElement` row + `Element` join row. Adding a child into a slot posts the parent
join-row pk and the slot id (`before` / `after`); `resolve_scope` validates it against the
registry's `{"slots": [...]}` and applies the depth clauses. The element is a container,
so it may sit at depth 1–3 and its children at 2–4.

**Rendering (student).** `build_lesson_context` (or `build_quiz_context`) sets
`has_before_after` → the unit template emits the prepaint script, the pre-hide style and
the `beforeafter.js` include → `render_element` calls `BeforeAfterElement.render`, which
computes `eid` → one `children` queryset fetches both slots' children, partitioned by
`tab_id` → both panels ship in the HTML, "after" hidden by the armed rule before first
paint → `beforeafter.js` sets `hidden`, adds `ba-js`, removes `ba-armed`.

**Toggling.** Click → swap the `hidden` attribute between the two panels, flip
`aria-pressed`, dispatch `libli:reveal` on the newly shown panel. No network, no state.

**Export/import.** The `emit()` walker yields each child with `parent` and its own `tab`
(`before` / `after`); the serializer carries `button_label`. Import validates the slot id
against `_CONTAINER_SLOT_KEY["before_after"]`, then rebuilds parent-first.

## Error handling

| Condition | Behaviour |
| --- | --- |
| Child row with an unrecognised `tab_id` (corrupt import, hand-edited DB) | Re-homed into **before**, never dropped (§1). Authored content must never become invisible; a stray element in the wrong half is a visible, fixable problem, a vanished one is not. On export it is emitted under the `before` slot id, so the archive stays valid (§11). |
| **`beforeafter.js` throws inside `initOne`** | The parse-time boot flag is already set, so the watchdog cannot help. `initOne`'s own `catch` un-arms **that container only** — clears `hidden`, clears `data-ba-ready`, adds `ba--dead` — and its siblings keep working (§5.2). |
| **A throw outside any instance** | The document-level `catch` calls `window.__baDisarm()`, un-arming the whole page. |
| Join row transient / mid-create | `resolved_slots()` returns `[("before", []), ("after", [])]` — the pairs are always present, only their child lists are empty. |
| Dangling GFK (`content_object is None`) | `type(None)` is in neither the registry nor `CONTAINER_TRANSFER_KEYS`, so it degrades to a leaf — existing behaviour, no new code. |
| Both slots empty | Renders the button and an empty ruled panel. Not an error; the author is mid-authoring. |
| Nested instance | Ownership scoping in the JS; depth clauses 3/4 already forbid a container at depth 4. |
| **`beforeafter.js` fails to load / throws** | The `DOMContentLoaded` boot guard (§5.2) drops `ba-armed`, so both panels become visible rather than the "after" side being stranded. |
| JS disabled | Neither class applied ⇒ both panels visible and labelled, toggle hidden (§5.3). |
| Graded `fill_blank` nested in a quiz unit's "after" slot | Reachable by pressing the button; submits unanswered if never revealed. Not a new exposure — Tabs and Callout already permit it in quizzes (§5.4). |
| Print | Both panels and both side headings revealed with explicit `display: block !important` (§5.5) — `revert` is insufficient against `[hidden]`. |
| Quiz unit | Armed exactly as a lesson (§5.4). |
| Archive with `before_after` on an older instance | Loud rejection at `courses/transfer/payloads.py:942`. |
| Archive naming a slot other than `before`/`after` | Rejected by `validate_nesting` — *"references a slot its parent does not have."* |
| Archive whose `data` lacks `button_label` or carries extra keys | Rejected by `_exact_keys` in `_val_before_after`. |

## Testing

Every test must be **falsified**, not merely run: delete or invert what it guards and
require RED. Each carries a named mutant. Falsify at the cheapest layer that can host the
mutant, and scope runs with `-k` — a whole-repo sweep is a branch gate, not a task step.

**Preconditions.** Start the test-DB container before any `pytest` run in this repo
(`docker compose -p libli-test -f docker-compose.test.yml up -d --wait`), or the suite
looks hung for ~4m21s. Tooling is behind `uv run`; `-m e2e` is mandatory for e2e files or
they silently deselect (exit 5).

**Stalling and aborting are not interchangeable**, and the §5.2 boot guard is exactly why.
An **abort** makes the deferred script fail immediately, so `DOMContentLoaded` fires, the
guard drops `ba-armed`, and the "after" panel becomes *visible* — a pre-hide test written
against an abort is RED on a correct build. Only a **stall** (a route handler that never
resolves) keeps the deferred script pending, blocks `DOMContentLoaded`, and leaves
`ba-armed` applied. The pre-hide test therefore stalls; the boot-guard test aborts.

| Area | Test | Mutant it must kill |
| --- | --- | --- |
| Model | children partition by slot | group by `parent` alone → "after" children appear in "before" |
| Model | unknown `tab_id` falls into "before" | drop-unknown → the row vanishes |
| Model | both slots fetched by ONE `children` queryset | `CaptureQueriesContext`: exactly one query filters on `parent_id` with no `tab_id` predicate. Mutant: call the queryset once per slot → two such queries |
| Model | `eid` is the element pk, not `node_pk` | use `node_pk` → two instances on one page collide on `id` |
| Containment | the five seams | `test_container_key_spaces_do_not_drift` / `…agree_by_key_not_by_count` go RED on any partial landing |
| Containment | registry cap is `None` | cap `2` → `paste_allowed` applies a bound it must skip |
| Containment | form-key alias | drop the alias → nested add 400s |
| Containment | a quiz question is refused as a child | add `choice` to the allowlist → accepted |
| Containment | add-card depth guard | remove the guard → the card is offered at depth 3 |
| Math | `has_math` true for math nested in a panel | make `_before_after_has_math` non-recursive → RED |
| Transfer | round-trip with children in both slots | omit the `emit()` walker branch → zero children exported |
| Transfer | round-trip preserves `button_label` | `_ser_before_after` returns `{}` → RED |
| Transfer | bad slot id rejected | accept-any → a corrupt archive imports silently |
| Transfer | `duplicate_element` copies children and label | same walker mutant → 200 with an empty copy |
| Transfer | `FORMAT_VERSION` still 9 | a bump → RED (guards the silent-merge hazard) |
| CSS | rule lands on `.ba__panel`; **within the element's own block** no `display` is declared on `.ba__panel`/`.ba__child` | add `display:block` to the base rule → RED. Scope the scan to that block — the armed/pre-hide/print rules legitimately declare `display`. Strip comments before scanning (`test_element_state_write_routes.py` precedent: a regex over raw source matches comments and docstrings too) |
| CSS | `.ba__child[hidden]` is in the `app.css:1010` guard | drop it → an author `display` beats `[hidden]` |
| CSS | print rule uses `display: block !important`, not `revert` | change to `revert` → panel stays hidden in print |
| CSS | the print un-hide of `.ba__side-heading` reverts **`clip`**, and also `position`/`width`/`height`/`overflow` | change `clip` to `clip-path` → RED (a no-op override leaving a 1×1 clipped box, i.e. an unlabelled printed page) |
| CSS | the `html:not(.ba-js)` no-JS rule reverts the same five properties | replace the body with `display: block` → RED |
| CSS | §5.5's print block sits in `courses.css`, or after `app.css:1014` | insert a second `@media print` above it in `app.css` → `test_reveal_scope_agreement::_print_block` extracts the wrong block → RED |
| Editor | **authoring the label end-to-end**: POST `element_add` with `type=beforeafter`, assert 200 and that the response carries the `button_label` input (the `test_callout_authoring.py:23` pattern, which is how `_edit_callout.html`'s existence is proven); then POST `element_save` with a label and assert it renders in the student template *and* in `element_summary` | three separate mutants, each of which leaves the rest of the table green: drop the `FORM_FOR_TYPE` entry; drop `"beforeafter"` from the `element_add` allow-tuple; drop it from the `element_save` allow-tuple. Also RED if the row branch omits `el-edit-slot` |
| Editor | pasting into each slot works | drop `{% paste_buttons %}` from a slot → RED |
| Editor | the preview's toggle is **visible** (not just wired) | omit `editor.html`'s `ba-js` prepaint block → `html:not(.ba-js) .ba__toggle { display: none }` hides it; the "toggles after a swap" row cannot distinguish this from "not wired" |
| Render seam | `BeforeAfterElement` is in `test_render_seam.py`'s `CONCRETES` | omit it → the list has no count assertion, so the seam ships unguarded |
| Render seam | `"beforeafter"` is in the `placement` matrix, i.e. every concrete renders *inside* a before/after | omit it → the element is only ever a child, never a host |
| Editor | the row emits `el-tag` with `{% element_type_label %}` | drop the span → the `_ELEMENT_LABELS` entry has no consumer and the row ships untagged, silently |
| Editor | `el.title` wins over `button_label` in the row label | drop the `{% if el.title %}` branch → an author-set title is ignored for this type only |
| Editor | `EL_ICON_MAP` covers the new card | add the card + sprite symbol but omit the map entry → suite stays green with nothing guarding the pairing |
| Editor | the add card is in the Content group (authorable in a quiz unit) | move it inside `{% if not unit_is_quiz %}` → RED |
| Editor | the preview pane's button toggles after a fragment swap | omit the `editor.js` re-init call → RED |
| Model | `ELEMENT_MODELS` has 32 entries | the three count assertions go RED until updated together |
| Model | a child with an unknown `tab_id` is re-homed into `before`, not dropped | copy `resolved_columns`' `by_col.get(id, [])` verbatim → the child vanishes |
| Containment | `"before_after" in NESTABLE_TYPE_KEYS` and `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` — the two-line guard every sibling transfer test carries (`test_callout_transfer.py:19-20`) | add seam 4 without the `export.py` `SERIALIZERS` entry → RED |
| Transfer | a child with an unknown `tab_id` exports under the `before` slot id and re-imports | yield the child's own `tab_id` → export succeeds, import fails validation |
| CSS | `AFTER_SLOT_ID == "after"` **and** `[data-ba-side="after"]` appears in all three sites — named explicitly: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`, `courses/static/courses/css/courses.css`. Two of the three are **templates, not stylesheets**; a guard that globs `*.css` covers one of three and ships green while the pre-hide it protects disarms. Each extraction must assert it matched | rename the constant → RED |
| CSS | the print block carries the eyebrow + `.ba__panel + .ba__panel` rules | drop them → a printed page shows two butted-together panels under unstyled bare `<p>`s. Print is the **only** path that reaches these on a working JS page |
| Editor | the open form's heading renders the `_EDITOR_TYPE_LABELS` string | omit the entry → the form opens with no heading |
| Editor | the rendered form's root carries `class="el-editor"` | omit the wrapper → the form leaves the editor grid and the fieldset scroll fix stops applying, silently |
| CSS | the print `.ba__child[hidden]` rule follows `app.css:1010` in document order | move it earlier → the child stays hidden in print (both rules are `!important` at equal specificity, so only order decides) |
| e2e (lesson) | script **boots then throws** mid-init: `disarm()` runs, both panels visible, toggle hidden | remove the `try`/`catch` → `ba-armed` stays applied and the "after" side is stranded (the abort test does **not** cover this — the parse-time flag is already set) |
| e2e (lesson) | no "Before"/"After" heading flash on a normal load | set `ba-js` from the module instead of the prepaint script → the headings paint visible, then vanish |
| e2e (editor) | the preview re-init does not touch `<html>` classes | bind `libliInitBeforeAfter` to the document-level boot → throws or re-runs once-only work on every swap |
| Reveal scope | `.ba__panel` in all three files + `SCOPES` | remove from any one → RED (extract each block before scanning, per that test's own docstring) |
| Reveal scope | the entry sits in the `has_reveal_gate` `<style>` block | move it to the new block → `_prehide_block` no longer sees it → RED |
| Context | `has_before_after` set for a **nested** instance | scope the query to `parent__isnull=True` → RED |
| Context | `has_before_after` set for a **quiz** unit | omit it from `build_quiz_context` → RED |
| a11y | icon-only button carries a translated `aria-label` | drop the `{% if not el.button_label %}` branch → RED |
| a11y | `aria-pressed` flips on toggle | freeze it at `"false"` → RED |
| e2e (lesson) | press → sides swap; press again → swaps back | — |
| e2e (lesson) | **"after" is not visible while the script is still pending** — `page.route` **stalls** the `beforeafter.js` request (a handler that never fulfils), then assert the panel is not visible | remove the pre-hide `<style>` → RED. A plain post-load assertion would be green under that mutant, because init sets `hidden` either way; stalling is what brackets the pre-paint window rather than measuring the settled state |
| e2e (lesson) | boot guard: with the script **aborted**, both panels show, **the headings are visible, and the toggle is hidden** | two mutants: delete the guard → the "after" side is stranded; **watchdog removes only `ba-armed`** → panels show but headings stay hidden and the dead toggle stays visible. Asserting only "both panels show" leaves the second one green |
| e2e (lesson) | `initOne` throws on instance 2 of 3: that instance shows both panels with `ba--dead`, **instances 1 and 3 still toggle** | move the `try`/`catch` to the document level → siblings are stranded too |
| e2e (lesson) | recovery clears `hidden`, not just the `<html>` classes | have `__baDisarm` remove only the classes → the "after" panel stays hidden with no control to reveal it |
| e2e (lesson) | the armed rule is present in the render-blocking `<style>` for a unit with `has_before_after` | remove the block → RED (static complement to the stall test) |
| e2e (lesson) | a gallery inside "after" measures non-zero after the first press | drop the `libli:reveal` dispatch → RED |
| e2e (editor) | both slots visible; a child added to each lands in the right slot | — |
| e2e (editor) | the slot panels render for a **nested** instance | gate the row branch on `el.parent_id is None` → RED |
| Screenshots | light **and** dark, judged separately | the rule reads identically to the spoiler's in both themes and the button's label/icon meet AA. (The 2px rule is decorative, not text, and its `color-mix` is ported verbatim from a shipped rule — so it is *not* held to AA text contrast.) |

## Out of scope

* Persistence of the toggled state (no `ElementState`, no endpoint, no migration).
* Per-direction button labels.
* A third slot, or a variable number of slots.
* Animation beyond what CSS gives free.
* Any change to which types are nestable in general.
* Any `FORMAT_VERSION` bump or archive-shape change.
* Math or inline HTML in `button_label` (plain text by decision; `math.js` scope unchanged).
