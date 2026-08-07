# Before / after element

A fifth container element. The author fills two fixed slots — **before / przed** and
**after / po** — and the student sees the "before" content plus a button; pressing the
button swaps to "after", pressing it again swaps back. The visible side carries a
spoiler-style left rule so the extent of the element's content is unmistakable.

Author-facing name: **Before / after** (pl: **Przed / po**). Transfer key
`before_after`; element-form key `beforeafter`; model `BeforeAfterElement`.

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
   — and toggles with one button, repeatedly, both ways.
3. The element nests inside the other containers and accepts the same children they do.
4. It survives course export/import with its children in the correct slots.

### Decisions taken during design (do not relitigate)

| Question | Decision | Why |
| --- | --- | --- |
| Which children? | Reuse the existing `NESTABLE_TYPE_KEYS` allowlist unchanged | Graded quiz questions (`choice`, `short_text`, `extended_response`, `short_numeric`, `match_pair`, `choice_grid`, `multi_grid`, `drag_to_image`, `drag_fill_blank`) are already absent from it. A per-container exception would be the first in the codebase. |
| Button label per direction? | One label, both directions | One `CharField`; the icon reads as "switch" either way. |
| Persist the toggled state? | No — ephemeral, resets to "before" | No state route, no `ElementState` row, no endpoint. Matches Tabs. |
| Editor layout | Two stacked panels, both always visible | The author is authoring a *pair*; hiding one half defeats the comparison. |
| Rule extent | Around the content only; button above, outside the rule | The spoiler's shape, which the user asked to match. |
| `FORMAT_VERSION` | **Not** bumped | See "Transfer". |

## Architecture / components

### 1. Model — `courses/models.py`

A new concrete beside `CalloutElement`:

```python
class BeforeAfterElement(ElementBase):
    BEFORE_SLOT_ID = "before"
    AFTER_SLOT_ID = "after"
    SLOT_IDS = (BEFORE_SLOT_ID, AFTER_SLOT_ID)

    button_label = models.CharField(max_length=120, blank=True)
    elements = GenericRelation(Element)   # cascade: deleting this removes its join row
```

No `data` field and no `body` field. Children live in `Element` rows whose `parent` is
this element's join row and whose `tab_id` is one of the two slot ids — the substrate
`TabsElement`, `SpoilerElement` and `CalloutElement` already use.

Because the slots are **class constants rather than persisted data**, there is nothing to
normalize: no `normalize_ids` / `normalize_data` pair, no id minting, no truncation, and
no way for the stored slot set to drift from what the code expects. This is the single
biggest simplification versus `TwoColumnElement`, and it is deliberate.

Methods:

* `join_row()` — `self.elements.order_by("pk").first()`, as Spoiler/Callout do.
* `resolved_children()` — **one** query on the join row
  (`order_by("order", "pk")`, `select_related("content_type")`,
  `prefetch_related("content_object")`), partitioned in Python into `before` and `after`
  by `tab_id`. Not two queries, and not `resolved_children(slot)` called twice.
* `render(*, element=None, state=None, slug=None, node_pk=None)` — renders
  `courses/elements/beforeafterelement.html` with `el`, `before_children`,
  `after_children`, `element_state` (the context key is `element_state`, **not** `state`
  — `courses_extras.render_element` reads that name), `slug`, `node_pk`.

Migration `0055_beforeafterelement_alter_element_content_type.py`, schema-only, generated
by `makemigrations` — no data migration and no backfill, because no existing row can be
this type.

### 2. Containment — five seams, not three

`courses/builder.py:58-62` warns that a new container must reach three structures and
names the drift test that enforces it. In practice a *nestable* container needs five:

| # | Seam | Change |
| --- | --- | --- |
| 1 | `builder.CONTAINER_TRANSFER_KEYS` | add `"before_after"` |
| 2 | `builder._CONTAINER_REGISTRY` | `BeforeAfterElement: (lambda _data: {"slots": [{"id": "before"}, {"id": "after"}]}, "slots", "id", None)` |
| 3 | `payloads._CONTAINER_SLOT_KEY` | `"before_after": frozenset({"before", "after"})` |
| 4 | `builder.NESTABLE_TYPE_KEYS` | add `"before_after"` — lets it live inside Tabs/Spoiler/Callout/Two-column |
| 5 | `builder._NESTABLE_FORM_KEY_ALIASES` | `"beforeafter": "before_after"` |

Seam 2's `max_slots` is `None`, meaning "never truncated" — the registry contract at
`builder.py:131-134` says `None` makes `paste_allowed` **skip** the slot-position check
rather than apply a bound. A fixed-slot container is never truncated, so `None` is
correct and `2` would be wrong.

Seam 5 is not optional. `_NESTABLE_FORM_KEY_ALIASES` translates the element-form key to
the transfer key before `resolve_scope` checks membership; `test_twocolumn_form_key_alias_exists`
exists because without the alias the card is offered in the nested add-menu and every
click 400s.

#### The `_CONTAINER_SLOT_KEY` sentinel must change shape

Today (`payloads.py:818-823`) the values are either a `str` (the key under which the
container's `data` holds its slot list) or `None`, and `None` means "single-slot: the only
valid id is `SINGLE_SLOT_ID`" — consumed at `payloads.py:857-862`:

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

Still two branches. The membership test at `payloads.py:852` runs *before* this lookup and
is unaffected. The only other reader is the drift test, which uses `set(_CONTAINER_SLOT_KEY)`
— keys only — so it is unaffected too.

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

`templates/courses/elements/beforeafterelement.html`:

```html
<div class="el el--beforeafter" data-beforeafter data-ba-eid="{{ node_pk|default:'0' }}">
  <button type="button" class="ba__toggle" aria-pressed="false"
          aria-controls="ba-{{ eid }}-panels"
          {% if not el.button_label %}aria-label="{% translate 'Switch content' %}"{% endif %}>
    <svg class="ic" …></svg>
    {% if el.button_label %}<span class="ba__label">{{ el.button_label }}</span>{% endif %}
  </button>
  <div class="ba__panels" id="ba-{{ eid }}-panels">
    <section class="ba__panel" data-ba-side="before">
      <p class="ba__side-heading">{% translate "Before" %}</p>
      <div class="ba__child">…</div>
    </section>
    <section class="ba__panel" data-ba-side="after">
      <p class="ba__side-heading">{% translate "After" %}</p>
      <div class="ba__child">…</div>
    </section>
  </div>
</div>
```

* **Namespaced ids.** `eid` is the join row's pk. A page may hold several of these;
  unnamespaced ids would make one element's button control another's panels — the exact
  bug `tabs.js:88-91` documents.
* **Accessible name.** With a label, the visible text names the button. Without one it is
  icon-only and takes a translated `aria-label`; an icon-only button with no accessible
  name is a defect, not a nicety.
* **`aria-pressed`** flips with the state — this is a toggle button, and the state is
  otherwise invisible to a screen-reader user given one label serves both directions.
* **Side headings** are `<p>`, not `<hN>`: they exist for print and for the no-JS
  fallback, and real headings would pollute the lesson's document outline. They are
  visually hidden on screen (out of flow, so they do not disturb the rule's box — see
  below).

### 4. CSS — the left rule

The rule goes on `.ba__panel` itself. **No `.ba__children` wrapper.** The spoiler needed
one (`app.css:982-990`) because it had *many* sibling `.spoiler__child` boxes and a
per-child border came out segmented — measured, and recorded in the #212 design notes:
child boxes sit 16px apart because their inner margins collapse through the child
wrapper, and `display: flow-root` fixes the segmentation only by inflating the element
154px → 202px. Here each side is already **one** box holding all of that side's children,
so a single border per side is continuous by construction and the wrapper buys nothing.

```css
.ba__panel {
  padding-left: var(--space-4);
  border-left: 2px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
```

Ported verbatim from `app.css:986-990` (`.spoiler__body, .spoiler > .spoiler__children`),
including the constraint that makes it work: **horizontal padding only, no vertical
margin, not a `flow-root`**, so the children's own margins keep collapsing out through
the box and the rule starts and stops on the *content* rather than on the margins.

Do **not** add `> :first-child { margin-top: 0 }` / `> :last-child { margin-bottom: 0 }`.
Those are the *callout's* treatment, needed only because `.callout` has padding that
blocks margin collapsing (`courses.css:1823-1834` says so explicitly, warning that the
spoiler's rationale does not transfer). Applying them here would defeat the hug.

`.ba__panels` is a bare grouping div: no margin, no padding, no border, not a
`flow-root`, so margins collapse through it untouched.

**`.ba__panel` and `.ba__child` must carry no `display` declaration**, so the `hidden`
attribute keeps working through the UA default. `app.css:1010`'s guard
(`.lesson-block[hidden], .tabs__child[hidden] { display: none !important }`) lists only
two classes; if a `display` is ever added to either of ours, both must join that guard.
This is the trap `.callout__child` documents at `courses.css:1827-1830`, and the reveal
cascade — which sets `gateWrap.hidden = true` — is what would break.

Spacing between children inside a panel is left to the children's own margins, as the
spoiler does. No `+` sibling rule (that is again the callout's padding-driven treatment).

### 5. No flash of the answer — pre-hide, not a plain toggle

**This is the requirement that shapes the client design.** Tabs renders every panel
visible and lets JS hide the inactive ones; copying that here paints the solution for a
frame on every page load, which defeats the element's main use.

So this element arms the same render-blocking pre-hide the reveal gates use:

1. `courses/views.py` gains `has_before_after`, computed with the same **flat** query the
   gate flags use (`views.py:395-403` — deliberately *not* scoped to
   `parent__isnull=True`, so a nested instance is still detected) and added to the lesson
   context beside `has_reveal_gate` (`views.py:476-484`).
2. `templates/courses/lesson_unit.html`, when `has_before_after`, emits a prepaint inline
   `<script>` adding `ba-armed` to `<html>`, and a render-blocking `<style>`:
   `html.ba-armed .ba__panels > [data-ba-side="after"] { display: none; }`.
3. `beforeafter.js`, at init, sets the `hidden` attribute on each instance's "after"
   panel **and only then** removes `ba-armed` from `<html>`.

Step 3's ordering is load-bearing: removing the class before the attributes are set opens
exactly the flash window the mechanism exists to close. The class is removed once, after
all instances on the page are initialised.

Because the class is added by script rather than server-rendered, **JS disabled ⇒ the
class is never added ⇒ both panels are visible, stacked**, each under its now-revealed
side heading. That is a better fallback than the reveal gate's (where content stays
unreachable), and it costs nothing.

Quiz units do not build this context flag, so — exactly as with reveal gates
(`test_e2e_reveal_gate.py:397-403`) — the element is inert there and both sides show.

`@media print` reveals both panels and both side headings, overriding both the armed rule
and the `hidden` attribute.

### 6. Client — `courses/static/courses/js/beforeafter.js`

~70 lines, copying `tabs.js`'s proven core and inventing nothing:

* **Idempotence** — `container.dataset.baReady === "1"` guard; the editor preview pane is
  rebuilt on every fragment swap and re-runs init over the whole pane
  (`tabs.js:66-68`).
* **Export** — `window.libliInitBeforeAfter(root)`, so the editor can re-run it after a
  swap, mirroring `libliInitTabs` / `libliInitGallery`.
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
so `.ba__panel` must join all three *and* the test's `SCOPES`:

1. `reveal.js`'s `scopeOf` (`reveal.js:52-54`);
2. the pre-hide `<style>` block in `lesson_unit.html`;
3. the `@media print` revert in `app.css`;
4. `SCOPES` in `test_reveal_scope_agreement.py` (and its "exact-four" assertions become
   exact-five).

Miss one and a reveal gate inside a panel silently escapes its scope — the failure #212
hit when it introduced `.spoiler__children`. `.ba__panel` is the correct scope because it
is the element whose **direct** children are the `.ba__child` rows the cascade walks
sibling-by-sibling, which is what `ownWrapper` (`reveal.js:59-63`) requires.

### 8. Editor

`templates/courses/manage/editor/_edit_beforeafter.html`, modelled on `_edit_callout.html`:
one `button_label` text input, then two stacked slot panels, each with a heading
(**Before / Przed**, **After / Po**), its child rows, and its own add-element control.
Both always visible.

Registration points, from the callout precedent:

| File | Change |
| --- | --- |
| `courses/element_forms.py` | `BeforeAfterElementForm` (one `button_label` field) |
| `courses/views.py` | add `beforeafter` to the element add/save allow-tuples |
| `courses/views_manage.py` | editor wiring |
| `courses/templatetags/courses_manage_extras.py` | `"beforeafterelement": _("Before / after")` in the label map (`:54-64`) |
| `templates/courses/manage/editor/_add_menu.html` | the add card |
| `templates/courses/manage/editor/_element_row.html` | the row rendering |
| `templates/courses/manage/_icon_sprite.html` | `el-beforeafter` symbol |
| `courses/static/courses/css/editor.css` | slot-panel styling |

`COURSE_SCOPED_TYPE_KEYS` is **not** touched — the element has no media field, so its
form takes no `course=`.

### 9. Icon and i18n

The sprite has no cycle/refresh glyph today. Add `el-beforeafter`: two arrows following a
circle, drawn as a monochrome `currentColor` line SVG on the 16×16 grid the other `el-*`
symbols use — never emoji. The same path is inlined in the student button at `class="ic"`,
`aria-hidden="true"`, `focusable="false"`.

New translatable strings, all with Polish catalogue entries: element name **Before /
after → Przed / po**; slot headings **Before → Przed**, **After → Po**; the icon-only
button's `aria-label` **Switch content → Zmień treść**.

Module-level dicts must use `gettext_lazy`, and `makemessages` fuzzy-prefills must be
cleared, not accepted.

### 10. Transfer — no `FORMAT_VERSION` bump

`FORMAT_VERSION` stays **9**. The precedent is unambiguous: `callout` (`c10994bc`) and
`guess_number` (`f962a4a5`) both entered `SERIALIZERS` without a bump; the version is
raised only when an *existing* payload shape changes (iframe w/h → 2, nested elements →
3, choice feedback → 4, spanning tables → 5, link nodes → 6, image size → 7, table cell
images → 8, collision resolution → 9).

An older instance meeting an archive containing the new type fails loudly and correctly at
`payloads.py:942` — *"Unknown element type … this archive may come from a newer
application version."* That is the designed behaviour, not a gap.

Not bumping also sidesteps the silent-merge hazard: two branches setting `FORMAT_VERSION`
to the *same* new number do not conflict in git, merge green, and ship two incompatible
formats under one version.

Five files, the same diff shape as `c10994bc`: `_ser_before_after` in `export.py`,
`_val_before_after` + the `_CONTAINER_SLOT_KEY` entry in `payloads.py`, the builder in
`importer.py`, `"before_after"` in `builder.py`, and the round-trip test.

## Data flow

**Authoring.** Add card → `manage_element_add` with type `beforeafter` → `resolve_scope`
translates the form key via `_NESTABLE_FORM_KEY_ALIASES` when nested → `BeforeAfterElement`
row + `Element` join row. Adding a child into a slot posts the parent join-row pk and the
slot id (`before` / `after`); `resolve_scope` validates it against the registry's
`{"slots": [...]}` and applies the depth clauses. The element is a container, so it may
sit at depth 1–3 and its children at 2–4.

**Rendering (student).** `build_lesson_context` sets `has_before_after` → `lesson_unit.html`
emits the prepaint script, the pre-hide style and the `beforeafter.js` include →
`render_element` calls `BeforeAfterElement.render` → one query fetches the join row's
children, partitioned by `tab_id` → both panels ship in the HTML, "after" hidden by the
armed rule before first paint → `beforeafter.js` sets `hidden`, removes `ba-armed`.

**Toggling.** Click → swap the `hidden` attribute between the two panels, flip
`aria-pressed`, dispatch `libli:reveal` on the newly shown panel. No network, no state.

**Export/import.** Export walks the join rows; each child carries `parent` and `tab`
(`before` / `after`). Import validates the slot id against
`_CONTAINER_SLOT_KEY["before_after"]`, then rebuilds parent-first.

## Error handling

| Condition | Behaviour |
| --- | --- |
| Child row with an unrecognised `tab_id` (corrupt import, hand-edited DB) | Falls into **before**, never dropped. Authored content must never become invisible; a stray element in the wrong half is a visible, fixable problem, a vanished one is not. |
| Join row transient / mid-create | `resolved_children()` returns two empty lists, as Spoiler/Callout do. |
| Dangling GFK (`content_object is None`) | `type(None)` is in neither the registry nor `CONTAINER_TRANSFER_KEYS`, so it degrades to a leaf — existing behaviour, no new code. |
| Both slots empty | Renders the button and an empty ruled panel. Not an error; the author is mid-authoring. |
| Nested instance | Ownership scoping in the JS; depth clauses 3/4 already forbid a container at depth 4. |
| JS disabled | `ba-armed` never applied ⇒ both panels visible and labelled. Degraded but complete. |
| Print | Both panels and both side headings revealed, overriding the armed rule and `hidden`. |
| Quiz unit | Context flag absent ⇒ no pre-hide, no JS ⇒ both sides visible and inert. |
| Archive with `before_after` on an older instance | Loud rejection at `payloads.py:942`. |
| Archive naming a slot other than `before`/`after` | Rejected by `validate_nesting` — *"references a slot its parent does not have."* |

## Testing

Every test must be **falsified**, not merely run: delete or invert what it guards and
require RED. Each carries a named mutant. Falsify at the cheapest layer that can host the
mutant, and scope runs with `-k` — a whole-repo sweep is a branch gate, not a task step.

**Preconditions.** Start the test-DB container before any `pytest` run in this repo, or
the suite looks hung for ~4m21s. Tooling is behind `uv run`; `-m e2e` is mandatory for e2e
files or they silently deselect (exit 5).

| Area | Test | Mutant it must kill |
| --- | --- | --- |
| Model | children partition by slot | group by `parent` alone → "after" children appear in "before" |
| Model | unknown `tab_id` falls into "before" | drop-unknown → the row vanishes |
| Model | one query, not two | split into per-slot queries → query count rises |
| Containment | the five seams | `test_container_key_spaces_do_not_drift` / `…agree_by_key_not_by_count` go RED on any partial landing |
| Containment | registry cap is `None` | cap `2` → `paste_allowed` applies a bound it must skip |
| Containment | form-key alias | drop the alias → nested add 400s |
| Containment | a quiz question is refused as a child | add `choice` to the allowlist → accepted |
| Transfer | round-trip with children in both slots | swap the slot ids on export → children land in the wrong half |
| Transfer | bad slot id rejected | accept-any → a corrupt archive imports silently |
| Transfer | `FORMAT_VERSION` still 9 | a bump → RED (guards the silent-merge hazard) |
| CSS | rule lands on `.ba__panel`; no `display` declared on `.ba__panel`/`.ba__child` | add `display:block` → RED, because `hidden` would stop working. Strip comments before scanning — `test_element_state_write_routes.py` precedent: a regex over raw source matches comments and docstrings too |
| Reveal scope | `.ba__panel` in all three files + `SCOPES` | remove from any one → RED (extract each block before scanning, per that test's own docstring) |
| Context | `has_before_after` set for a **nested** instance | scope the query to `parent__isnull=True` → RED |
| e2e (lesson) | press → sides swap; press again → swaps back | — |
| e2e (lesson) | **"after" is not in the layout before the first press** | remove the pre-hide → RED. This is the only guard on the no-flash requirement |
| e2e (lesson) | a gallery inside "after" measures non-zero after the first press | drop the `libli:reveal` dispatch → RED |
| e2e (editor) | both slots visible; a child added to each lands in the right slot | — |
| Screenshots | light **and** dark, judged separately | the rule's `color-mix` against `--primary` must clear contrast in both |

## Out of scope

* Persistence of the toggled state (no `ElementState`, no endpoint, no migration).
* Per-direction button labels.
* A third slot, or a variable number of slots.
* Animation beyond what CSS gives free.
* Any change to which types are nestable in general.
* Any `FORMAT_VERSION` bump or archive-shape change.
