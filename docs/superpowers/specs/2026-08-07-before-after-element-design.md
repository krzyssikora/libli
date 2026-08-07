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
| Which children? | Reuse the existing `NESTABLE_TYPE_KEYS` allowlist unchanged | Graded quiz questions (`choice`, `short_text`, `extended_response`, `short_numeric`, `match_pair`, `choice_grid`, `multi_grid`, `drag_to_image`, `drag_fill_blank`) are already absent from it. A per-container exception would be the first in the codebase. |
| Button label per direction? | One label, both directions | One `CharField`; the icon reads as "switch" either way. |
| Persist the toggled state? | No — ephemeral, resets to "before" | No state route, no `ElementState` row, no endpoint. Matches Tabs. |
| Editor layout | Two stacked panels, both always visible | The author is authoring a *pair*; hiding one half defeats the comparison. |
| Rule extent | Around the content only; button above, outside the rule | The spoiler's shape, which the user asked to match. |
| Armed in quiz units? | **Yes** — unlike a reveal gate | A before/after has no grading interaction and no state, so arming it is safe; leaving it unarmed would permanently expose the answer side and break criterion 2. |
| `button_label` content | Plain text, autoescaped | No math, no inline HTML, no sanitiser. `math.js`'s scope list (`courses/static/courses/js/math.js:31`) is deliberately **not** extended, so `\(…\)` in a label would ship raw — the field is documented as plain text for that reason. |
| `FORMAT_VERSION` | **Not** bumped | See §10. |

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
biggest simplification versus `TwoColumnElement`, and it is deliberate. Everywhere a slot
id is needed, reference `SLOT_IDS` / `BEFORE_SLOT_ID` / `AFTER_SLOT_ID` — **never a string
literal**, which would reintroduce exactly the drift these constants exist to prevent.

Methods:

* `join_row()` — `self.elements.order_by("pk").first()`, as Spoiler/Callout do.
* `resolved_children()` — **returns a 2-tuple `(before, after)` of lists, in `SLOT_IDS`
  order**; `([], [])` when the join row is transient/mid-create. The children of *both*
  slots are fetched by a **single `children` queryset** — `order_by("order", "pk")`,
  `select_related("content_type")`, `prefetch_related("content_object")` — and
  partitioned in Python by `tab_id`. Not one queryset per slot. (The total query count is
  necessarily >1: `join_row()` is its own query and `prefetch_related` issues one query
  per distinct child content type, so "one query" is *not* the invariant — see the
  Testing table for the form the test actually takes.)
* `render(*, element=None, state=None, slug=None, node_pk=None)` — renders
  `templates/courses/elements/beforeafterelement.html`.

**`eid` must be computed by `render()`.** The context is `el`, `eid`, `before_children`,
`after_children`, `element_state` (the key is `element_state`, **not** `state` —
`courses_extras.render_element` reads that name), `slug`, `node_pk`, where:

```python
eid = element.pk if element is not None else 0
```

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
| 2 | `builder._CONTAINER_REGISTRY` | `BeforeAfterElement: (lambda _data: {"slots": [{"id": sid} for sid in BeforeAfterElement.SLOT_IDS]}, "slots", "id", None)` |
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
* `test_container_key_spaces_do_not_drift` and
  `test_container_keys_agree_by_key_not_by_count` should pass unchanged once all five
  seams land — they are the guard against a partial landing and **must not be relaxed**.

### 3. Student render

`templates/courses/elements/beforeafterelement.html` (house tag spelling is `{% trans %}`,
as in `templates/courses/manage/editor/_edit_callout.html`):

```html
{% load i18n %}
<div class="el el--beforeafter" data-beforeafter data-ba-eid="{{ eid }}">
  <button type="button" class="ba__toggle" aria-pressed="false"
          aria-controls="ba-{{ eid }}-panels"
          {% if not el.button_label %}aria-label="{% trans 'Switch content' %}"{% endif %}>
    <svg class="ic" aria-hidden="true" focusable="false"><use href="#el-beforeafter"/></svg>
    {% if el.button_label %}<span class="ba__label">{{ el.button_label }}</span>{% endif %}
  </button>
  <div class="ba__panels" id="ba-{{ eid }}-panels">
    <section class="ba__panel" data-ba-side="before">
      <p class="ba__side-heading">{% trans "Before" %}</p>
      <div class="ba__child">…</div>
    </section>
    <section class="ba__panel" data-ba-side="after">
      <p class="ba__side-heading">{% trans "After" %}</p>
      <div class="ba__child">…</div>
    </section>
  </div>
</div>
```

* **Namespaced ids.** `eid` is the join row's pk, computed in `render()` per §1.
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

`.ba__side-heading` uses the existing **`.visually-hidden`** utility
(`core/static/core/css/app.css:1212`) — i.e. it is taken out of flow, so it neither
occupies space nor disturbs the panel's margin collapsing, and `display` is untouched so
the print reveal works.

#### The `display` invariant, stated precisely

**In the element's own rules in `courses.css` / `app.css`, `.ba__panel` and `.ba__child`
declare no `display`.** That is what keeps the `hidden` attribute working through the UA
default. The armed pre-hide rule (§5), the reveal-cascade pre-hide (§7) and the print
reverts (§5, §7) are the **stated exceptions** — they are state-scoped rules, not the
element's base styling — and the CSS test must be scoped to the element's own block
rather than scanning the whole file, or it goes red on a correct implementation.

**Decision:** `.ba__child[hidden] { display: none !important; }` **is** added to the
guard at `core/static/core/css/app.css:1010`, joining `.lesson-block[hidden]` and
`.tabs__child[hidden]`. `.ba__child` is a reveal-cascade wrapper exactly as
`.tabs__child` is — the cascade sets `gateWrap.hidden = true` — so it needs the same
protection against an author-supplied `display` beating `[hidden]`. `.ba__panel` is
**not** added: its hiding is driven by this element's own JS, not the cascade.

Spacing between children inside a panel is left to the children's own margins, as the
spoiler does. No `+` sibling rule (that is again the callout's padding-driven treatment).

### 5. No flash of the answer — pre-hide, not a plain toggle

**This is the requirement that shapes the client design.** Tabs renders every panel
visible and lets JS hide the inactive ones; copying that here paints the solution for a
frame on every page load, which defeats the element's main use.

#### 5.1 The mechanism

1. `courses/views.py` gains `has_before_after`, computed with the same **flat** query the
   gate flags use (`courses/views.py:395-403` — deliberately *not* scoped to
   `parent__isnull=True`, so a nested instance is still detected) and added to the lesson
   context beside `has_reveal_gate` (`courses/views.py:476-484`).
2. `templates/courses/lesson_unit.html`, when `has_before_after`, emits a prepaint inline
   `<script>` adding `ba-armed` to `<html>`, and a render-blocking `<style>`:
   `html.ba-armed .ba__panels > [data-ba-side="after"] { display: none; }`.
3. `courses/static/courses/js/beforeafter.js`, at init, sets the `hidden` attribute on
   each instance's "after" panel, **then** adds `ba-js` to `<html>`, **then** removes
   `ba-armed`.

Step 3's ordering is load-bearing: removing `ba-armed` before the attributes are set
opens exactly the flash window the mechanism exists to close. Both class mutations happen
once, after all instances on the page are initialised.

#### 5.2 The boot guard (a failed script load must not strand the content)

Every existing prepaint block in `templates/courses/lesson_unit.html` pairs its
`classList.add(...)` with a `DOMContentLoaded` guard that removes the class if the module
never booted — `window.__revealBooted` at `:11`, `window.__stepperBooted` at `:24`. This
element uses the same pattern: `beforeafter.js` sets `window.__beforeAfterBooted = true`,
and the prepaint script drops `ba-armed` on `DOMContentLoaded` when the flag is absent.

Without it, a 404 / throw / blocked script leaves `ba-armed` applied forever and the
"after" content is permanently unreachable with no way back — strictly worse than the
reveal gate this design claims to improve on.

#### 5.3 The no-JS fallback needs a persistent hook

`ba-armed` cannot distinguish "JS disabled" from "initialised normally" — it is absent in
both cases. That is why step 3 adds a **persistent `ba-js` class**: the side headings are
revealed by `html:not(.ba-js) .ba__side-heading`, which is true only when the script
never ran.

So with JS disabled (or blocked): `ba-armed` is never added ⇒ **both panels are visible,
stacked, each under a revealed side heading**. Degraded but complete and labelled — a
better fallback than the reveal gate's, and the reason the class is added by script
rather than server-rendered.

#### 5.4 Quiz units are armed too

`build_quiz_context` (`courses/views.py:1139`) also sets `has_before_after`, and
`templates/courses/quiz_unit.html` emits the same prepaint script, pre-hide style and
script include.

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

```css
@media print {
  .ba__panel[hidden] { display: block !important; }
  .ba__side-heading  { position: static !important; clip-path: none !important; /* …un-hide */ }
  html.ba-armed .ba__panels > [data-ba-side="after"] { display: block !important; }
}
```

This is a **different rule** from the reveal-cascade sibling revert §7 asks for; both are
needed.

### 6. Client — `courses/static/courses/js/beforeafter.js`

~70 lines, copying `tabs.js`'s proven core and inventing nothing:

* **Idempotence** — `container.dataset.baReady === "1"` guard; the editor preview pane is
  rebuilt on every fragment swap and re-runs init over the whole pane (`tabs.js:66-68`).
* **Export** — `window.libliInitBeforeAfter(root)`, so the editor can re-run it after a
  swap, mirroring `libliInitTabs` / `libliInitGallery`.
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
* `aria-pressed` updated on the button each toggle.

The element deliberately has **no** keyboard-navigation layer beyond the button being a
button: one control, activated by Enter/Space natively.

### 7. `scopeOf` becomes a fifth scope

`courses/tests/test_reveal_scope_agreement.py` pins a **4-tuple** of cascade scopes
(`[data-tab-panel]`, `.slide`, `.spoiler__children`, `.callout__children`) across
**three** files. Since `reveal_gate` is nestable, a gate may be authored inside a panel,
so `.ba__panel` must join all three *and* the test's `SCOPES` tuple:

1. `scopeOf` in `courses/static/courses/js/reveal.js:52-54`;
2. the pre-hide `<style>` block in `templates/courses/lesson_unit.html`;
3. the `@media print` revert in `core/static/core/css/app.css:1014-1022`;
4. the `SCOPES` tuple in `courses/tests/test_reveal_scope_agreement.py`, plus the
   docstrings and test names that say "four".

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
  fields.
* **`templates/courses/manage/editor/_element_row.html`** — a new
  `beforeafterelement` branch carrying the **two stacked slot panels**, their headings
  (**Before / Przed**, **After / Po**), the child rows and the per-slot add controls.
  This is where container children live for every existing container (the callout branch
  at `:198`, the spoiler branch at `:146`), because `children_map`, `open_form_pk`,
  `clip_element_pk` and `depth` are in scope there and nowhere else.

  The branch **must match a nested instance too** — do not gate it on
  `el.parent_id is None`. The spoiler branch's comment records that dropping exactly that
  clause was required for depth-3 nesting.

Registration points:

| File | Change |
| --- | --- |
| `courses/element_forms.py` | define `BeforeAfterElementForm` (one `button_label` field) **and** register it in the form-key → form-class dispatch dict at `:1964` (`"beforeafter": BeforeAfterElementForm`) — defining the class alone leaves the edit form unrendered |
| `courses/views_manage.py` | add `"beforeafter"` to the `element_add` allow-tuple (`~:1823`) **and** to the `element_save` allow-tuple (`~:1894`) — two separate edits; the tuples genuinely differ (`slidebreak` is in save but not add) |
| `courses/views_manage.py` | add `"beforeafter": gettext_lazy("Before / after")` to `_EDITOR_TYPE_LABELS` (`:1621-1652`), which supplies the open-form heading — **form-key** keyed |
| `courses/templatetags/courses_manage_extras.py` | add `"beforeafterelement": _("Before / after")` to the label map (`:54-64`) — **content-type-model** keyed, a different namespace from the row above |
| `courses/templatetags/courses_manage_extras.py` | add a branch to `element_summary` (`~:118`): `if name == "BeforeAfterElement": return el.button_label or _("Before / after")` |
| `templates/courses/manage/editor/_add_menu.html` | the add card, carrying the **same depth guard** as the callout/tabs/columns cards at `:37-39`: `{% if depth < max_nest_depth|add:-1 %}` — without it the card is offered at depth 3 and every child add 400s |
| `templates/courses/manage/_icon_sprite.html` | `el-beforeafter` symbol |
| `core/help.py` | add `"beforeafter"` to `ELEMENT_ICON_SLUGS` (`:40`) — the sprite id minus the `el-` prefix; `test_element_icon_slugs_match_sprite` goes red if the symbol lands without it |
| `courses/static/courses/css/editor.css` | slot-panel styling |

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
`_element_has_math`, following `_callout_has_math`'s documented transient-guard
placement.

`math.js`'s scope list is deliberately **unchanged**: children are rendered elements
(`.el--text` etc.) already covered by it, and `button_label` is plain text by decision.

### 10. Icon and i18n

The sprite has no cycle/refresh glyph today. Add `el-beforeafter`: two arrows following a
circle, drawn as a monochrome `currentColor` line SVG on the 16×16 grid the other `el-*`
symbols use — never emoji.

New translatable strings, all with Polish catalogue entries: element name **Before /
after → Przed / po**; slot headings **Before → Przed**, **After → Po**; the icon-only
button's `aria-label` **Switch content → Zmień treść**.

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

* `_ser_before_after` returns `{"button_label": concrete.button_label}`.
* `_val_before_after` does `_exact_keys(data, ["button_label"], …)` plus
  `check_str(data["button_label"], max_length=120)`, and returns `set()` (references no
  media). Mirrors `_val_callout` (`courses/transfer/payloads.py:206`).
* `_build_before_after` in `courses/transfer/importer.py` sets it.

#### The export tree-walker branch

`courses/transfer/export.py` has a separate `emit()` walker (`~:626`) with an `isinstance`
branch per container — `TabsElement` (`:627`), `TwoColumnElement` (`:631`),
`SpoilerElement` (`:635`), `CalloutElement` (`:638`) — that yields each child with its
slot id. **Without a `BeforeAfterElement` branch the serializer runs but no children are
ever emitted**, so success criterion 4 fails silently.

The branch yields each child with the child's **own `tab_id`** — unlike the Spoiler and
Callout branches, which pass a fixed `SLOT_ID`, because this container has two slots to
distinguish.

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
| Child row with an unrecognised `tab_id` (corrupt import, hand-edited DB) | Falls into **before**, never dropped. Authored content must never become invisible; a stray element in the wrong half is a visible, fixable problem, a vanished one is not. |
| Join row transient / mid-create | `resolved_children()` returns `([], [])`. |
| Dangling GFK (`content_object is None`) | `type(None)` is in neither the registry nor `CONTAINER_TRANSFER_KEYS`, so it degrades to a leaf — existing behaviour, no new code. |
| Both slots empty | Renders the button and an empty ruled panel. Not an error; the author is mid-authoring. |
| Nested instance | Ownership scoping in the JS; depth clauses 3/4 already forbid a container at depth 4. |
| **`beforeafter.js` fails to load / throws** | The `DOMContentLoaded` boot guard (§5.2) drops `ba-armed`, so both panels become visible rather than the "after" side being stranded. |
| JS disabled | `ba-armed` never applied, `ba-js` never added ⇒ both panels visible and labelled (§5.3). |
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
| Reveal scope | `.ba__panel` in all three files + `SCOPES` | remove from any one → RED (extract each block before scanning, per that test's own docstring) |
| Reveal scope | the entry sits in the `has_reveal_gate` `<style>` block | move it to the new block → `_prehide_block` no longer sees it → RED |
| Context | `has_before_after` set for a **nested** instance | scope the query to `parent__isnull=True` → RED |
| Context | `has_before_after` set for a **quiz** unit | omit it from `build_quiz_context` → RED |
| a11y | icon-only button carries a translated `aria-label` | drop the `{% if not el.button_label %}` branch → RED |
| a11y | `aria-pressed` flips on toggle | freeze it at `"false"` → RED |
| e2e (lesson) | press → sides swap; press again → swaps back | — |
| e2e (lesson) | **"after" is not visible when the script never runs** — `page.route` aborts/stalls the `beforeafter.js` request, then assert the panel is not visible | remove the pre-hide `<style>` → RED. A plain post-load assertion would be green under that mutant, because init sets `hidden` either way; the route-abort is what brackets the pre-paint window rather than measuring the settled state |
| e2e (lesson) | the armed rule is present in the render-blocking `<style>` for a unit with `has_before_after` | remove the block → RED (static complement to the route-abort test) |
| e2e (lesson) | boot guard: with the script aborted, `ba-armed` is gone after `DOMContentLoaded` and both panels show | delete the guard → the "after" side is stranded |
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
