# Mark-done checklist element

## Purpose

Port the legacy `.mark_done` widget from the Demo Course into libli as a first-class content
element: a **self-tracking checklist**. An author writes an optional prompt plus an ordered list of
short statement items; a student ticks items to record "I've done this." Unlike every existing
lesson self-check (reveal-gate, stepper, spoiler, switch-grid, fill-in-table, formative MCQ/matrix),
which is deliberately **ephemeral** — formative practice meant to reset each visit — the checklist
records a **deliberate student self-assertion** and therefore **persists per-student, server-side**.

This joins the *completion* family (which already persists, via `UnitProgress.completed` +
`seen_element_ids`), not the *self-check* family (which is rightly ephemeral). It is **ungraded** (no
marks, no correct/incorrect), **lesson-only**, and **nestable in tabs / two-column** — consistent
with Stepper and Spoiler. It does **not** affect unit completion: ticking every item does not
auto-complete the unit (completion stays seen-based + the manual "Mark as done").

### Non-goals

- No marks, no grading, no quiz availability.
- No coupling of *ticking* to unit completion — ticking items never auto-completes the unit. (The
  element itself is still seen-tracked like every content element via the `data-element-id`
  seen-beacon; that is ordinary content behaviour, not checklist-specific coupling.)
- No client-only localStorage persistence (persistence is server-side, per-student, cross-device).
- No per-item deadlines, ordering-by-student, or collaborative/shared checklists.
- No retrofitting persistence onto other (rightly-ephemeral) elements — the JSON-on-`UnitProgress`
  pattern is left reusable, but wired only for this element.

## Architecture / components

The element is modelled directly on `StepperElement` (an `ElementBase` subclass with a single inline
formset of ordered sub-items), diverging only where persistence requires it. Every "new element type"
touch-point is updated in lockstep (see the touch-points checklist in the roadmap memory).

### Data model (`courses/models.py`)

- **`MarkDoneElement(ElementBase)`** — mirrors `StepperElement`:
  - Class attrs `MIN_ITEMS = 1`, `MAX_ITEMS = 20`, `MAX_LEN = 500`.
  - `prompt = CharField(max_length=MAX_LEN, blank=True)` (optional lead-in), stripped in `save()`.
  - `elements = GenericRelation(Element)` (cascade join-row cleanup, as Stepper).
- **`MarkDoneItem`** — mirrors `StepperStep`:
  - `element = ForeignKey(MarkDoneElement, on_delete=CASCADE, related_name="items")`.
  - `content = CharField(max_length=MarkDoneElement.MAX_LEN)`, stripped in `save()`.
  - `order = OrderField(for_fields=["element"], blank=True)`; `Meta.ordering = ["order", "pk"]`.
- **`ELEMENT_MODELS`** (`courses/models.py:259`) gains `"markdoneelement"`. On the current `master`
  base the length goes **29 → 30**; the implementer MUST read the actual base length and assert
  `base_len → base_len + 1` rather than hardcoding, in case a sibling PR changes the base count.

### Persistence (`UnitProgress.checklist_state`)

- New field on the existing `UnitProgress` model:
  `checklist_state = JSONField(default=dict)`.
- Shape: `{ "<element_pk>": [<item_pk>, ...], ... }` — top-level keys are **element pks as
  strings** (JSON object keys are strings), values are lists of **checked `MarkDoneItem` pks**.
- **Keyed by pk**, so an author can add / remove / reorder items without corrupting stored ticks.
  Stale item pks (from a since-deleted item) are ignored on read and pruned on the next write.
- One `UnitProgress` row per `(student, unit)` already exists as the lesson-state record; the
  checklist state rides alongside `seen_element_ids` on that row. No new table.

### Migrations

- New migration(s) adding `MarkDoneElement`, `MarkDoneItem`, and `UnitProgress.checklist_state`.
  `checklist_state` has `default=dict` so it back-fills to `{}` for existing rows with no data
  migration. (Splitting the model additions and the `UnitProgress` field into separate migration
  files is acceptable and slightly more reviewable, but a single generated migration is fine.)
- **Migration number is provisional.** On the current `master` base the next number is **0048**
  (highest existing is `0047`), but the implementer MUST run `makemigrations` against the actual
  branch base and use whatever number it assigns — never hardcode 0048 — since adjacent numbers may
  be claimed if a sibling PR lands first.

### Form + editor (`courses/element_forms.py`, editor templates/JS)

- `MarkDoneElementForm` (prompt field) + `MarkDoneItemForm` (content field) + `BaseMarkDoneFormSet`
  (MIN/MAX validation) + `MarkDoneItemFormSet = inlineformset_factory(...)` +
  `build_markdone_formset(...)` — the Stepper form stack, renamed.
- `FORM_FOR_TYPE["markdone"] = MarkDoneElementForm` (`courses/element_forms.py`).
- **Form key** is `markdone`; **transfer key** is `mark_done` (snake_case, per convention). They
  differ, so `mark_done` goes in `NESTABLE_TYPE_KEYS` and `markdone → mark_done` goes in
  `_NESTABLE_FORM_KEY_ALIASES` (`courses/builder.py`).
- Editor partial `templates/courses/manage/editor/_edit_markdone.html` — prompt input + inline items
  formset + add-row `<template>` (clone of `_edit_stepper.html`; field names must match the form:
  `prompt`, `items-__prefix__-content`, `items-TOTAL_FORMS`). Auto-included by `_host_form.html`
  via `_edit_<type_key>.html`, so the partial is **required** or a palette click 500s
  `TemplateDoesNotExist`.
- Add-row enhancer `courses/static/courses/js/markdone_editor.js` (clone of `stepper_editor.js`;
  `window.libliInitMarkDoneEditor`, self-boots on `[data-markdone-editor]`).
- `save_element` (`courses/builder.py`) gains a `markdone` branch mirroring the `stepper` branch
  (validate form + formset, save element, iterate `formset.forms`, assign gap-free 0-based `order`,
  drop blank/DELETE rows).
- `_render_open_form` formset wiring (`courses/views_manage.py:847`) gains a `markdone` branch
  (`build_markdone_formset(instance=...)`).
- Allow-tuples `element_add` / `element_save` (`courses/views_manage.py`) gain `"markdone"`.
- `_EDITOR_TYPE_LABELS["markdone"] = gettext_lazy("Checklist")` (`courses/views_manage.py`).
- `_ELEMENT_LABELS["markdoneelement"] = _("Checklist")` + `element_summary` `MarkDoneElement` branch
  (prompt or first item text, truncated) (`courses/templatetags/courses_manage_extras.py`).
- Palette card in the **Interactive** group of `_add_menu.html`
  (`data-add-type="markdone"`, new `#el-markdone` sprite symbol). The Interactive group is inside
  `{% if not unit_is_quiz %}`, so the element is lesson-only. Because
  `tests/test_manage_editor_menu.py` renders a **quiz** unit, Interactive cards are not counted by
  its `== 23` assert, so that assert should be **unchanged** — but the implementer MUST confirm this
  at build time by re-reading the test's rendered `unit_type` and the `{% if not unit_is_quiz %}`
  guard before relying on it; if the card is ever placed outside that guard the count must be bumped.

### Student render (`templates/courses/elements/markdoneelement.html`)

Selected by `ElementBase.render` convention. Renders a real, no-JS-correct form. The endpoint URL is
computed **once** (single source — resolves the dual-source drift) from the threaded `slug`/`node_pk`
(see Context plumbing) and used for both the form `action` and the JS `data-` hook:

```
{% url 'courses:markdone_save' slug=slug node_pk=node_pk as save_url %}
<div class="markdone" data-markdone data-markdone-url="{{ save_url }}" data-element-id="{{ el.pk }}">
  <form method="post" action="{{ save_url }}#markdone-{{ el.pk }}" id="markdone-{{ el.pk }}">
    {% csrf_token %}
    <input type="hidden" name="element" value="{{ el.pk }}">   {# no-JS disambiguation #}
    {% if el.prompt %}<p class="markdone__prompt">{{ el.prompt }}</p>{% endif %}
    <ul class="markdone__list">
      {% for item in el.items.all %}
        <li class="markdone__item{% if item.pk in checked %} on{% endif %}">
          <label>
            <input type="checkbox" name="item" value="{{ item.pk }}"
                   {% if item.pk in checked %}checked{% endif %}>
            <span class="markdone__text">{{ item.content }}</span>
          </label>
        </li>
      {% endfor %}
    </ul>
    <button type="submit" class="btn btn--small markdone__save" data-markdone-save>{% trans "Save" %}</button>
  </form>
</div>
```

- **`element` hidden input** disambiguates the no-JS POST when a unit contains more than one
  checklist (the endpoint URL is per-node, not per-element) — the endpoint's form-POST branch
  **requires** it. There is no "derive the element from the URL" path.
- `checked` = the **set** of checked item pks for this element, looked up by `el.pk` from the
  precomputed `checklist` map (**see Context plumbing — that section is authoritative for how the set
  is built**; do not also do a separate `str(el.pk)` lookup here). It is always an int set, so
  `{% if item.pk in checked %}` is an int-vs-int membership test. The template is reached **only via
  `render_element`**, which always supplies `checked` (default: empty set), so the guard never sees
  an undefined variable.
- Checked items get the `on` class **server-side**, so the done styling is correct with JS off.
- The `#markdone-{{ el.pk }}` fragment on the no-JS `action` returns the student to the checklist
  they ticked after the redirect.
- `data-element-id` lets the seen-beacon mark the checklist element seen like any other content
  element (ordinary behaviour); it is independent of the tick-persistence path.

**Context plumbing (the load-bearing seam — must be BUILT, not "extended").** A codebase check
confirms there is **no** existing per-student context threading for generic content elements:
`render_element` (`courses/templatetags/courses_extras.py:62`) renders them via a bare
`mark_safe(obj.render())`, and `ElementBase.render(self)` (`courses/models.py`) takes no arguments and
renders `{"el": self}`. Only `QuestionElement.render` receives per-render context (`mode`/`slug`/
`node_pk`), via a separate branch. **Crucially, several leaf content classes OVERRIDE `render()` with
their own zero-arg signature and are dispatched through that same generic `render_element` line** —
`FillGateElement`, `SwitchGateElement`, `SwitchGridElement`, `TableElement`, `FillTableElement`,
`GalleryElement` (six, all `def render(self):`), plus `HtmlElement.render(self, unit, course,
theme=None)` on its own dispatch branch. So the checklist is the **first** generic content element to
need per-student render context, and the seam is built explicitly across these sites (the plan
verifies exact signatures / line-numbers):

1. **`build_lesson_context`** computes, once, an **int-keyed** map `checklist = {int(content_pk):
   {int(item_pk), ...}}` from the student's `UnitProgress.checklist_state` (JSON keys are strings,
   values int lists — cast keys to `int`) — empty dict for previewers / non-enrolled — and puts
   `checklist`, `slug`, `node_pk` into the lesson page context. The map is keyed by the **content
   object pk** (`MarkDoneElement.pk`) — the same pk the template posts as `element` and the endpoint
   keys `checklist_state` by (one pk space end to end).
2. **`render_element`** (`takes_context=True`) reads `checklist` / `slug` / `node_pk` **from the tag
   context** — this is the single receiving mechanism; NO new tag parameters are added — and passes
   them into the generic element render: change the bare `obj.render()` call to
   `obj.render(checklist=checklist, slug=slug, node_pk=node_pk)` (the question and `HtmlElement`
   branches are unchanged).
3. **`ElementBase.render`** gains keyword params with safe defaults —
   `render(self, *, checklist=None, slug=None, node_pk=None)` — and resolves its own checked set,
   putting `{"el": self, "checked": (checklist or {}).get(self.pk, set()), "slug": slug,
   "node_pk": node_pk}` into the leaf template context. The defaults keep every existing zero-arg
   `render()` call site (editor preview, `element_try`, the ~28 other element templates that ignore
   the new vars) working unchanged.
4. **Every leaf `render()` reachable by that generic line MUST accept the new kwargs.** The base now
   declares them, but the six **zero-arg overrides** — `FillGateElement`, `SwitchGateElement`,
   `SwitchGridElement`, `TableElement`, `FillTableElement`, `GalleryElement` — do NOT inherit the base
   signature, so each must gain a tolerant `**_kwargs` (absorb-and-ignore), or a lesson containing any
   of them raises `TypeError: render() got an unexpected keyword argument 'checklist'`. (`HtmlElement`
   is on its own dispatch branch and is untouched.) **Gate this with a test** that renders a lesson
   mixing one of these six with a checklist.
5. **Container renders** `TabsElement.render` / `TwoColumnElement.render` also override `render()` and
   build an **isolated** `render_to_string(...)` context, so context inheritance does NOT reach nested
   children. They must accept the same `checklist`/`slug`/`node_pk` kwargs (so the generic line can
   call them) and **inject those values into their `render_to_string` context dict** — without this a
   nested checklist renders empty.
6. **Container templates** `tabselement.html` / `twocolumnelement.html` need **no change**: because
   step 5 re-injects `checklist`/`slug`/`node_pk` into the container's `render_to_string` context and
   `render_element` reads them **from context** (`takes_context`), the existing bare
   `{% render_element child %}` calls resolve each nested child's `checked` set automatically. The
   explicit-kwargs form `{% render_element child checklist=… %}` is deliberately NOT used — step 2
   adds no tag parameters to `render_element`, so unknown tag kwargs would raise. Context-injection is
   the single receiving mechanism.

- The leaf `markdoneelement.html` resolves `save_url` from the threaded `slug`/`node_pk` (**NOT** from
  `self`, which has no join-row / `unit`), so `ElementBase.render` MUST place `slug`/`node_pk` in the
  leaf context — otherwise the `{% url %}` tag raises `NoReverseMatch` and `data-markdone-url` is
  empty.
- Preview / editor / non-enrolled render → `checklist` defaults to empty, so `checked` resolves to an
  empty set; the save endpoint separately no-ops at the enrollment gate.

### Save endpoint (`courses/views.py` + `courses/urls.py`)

- URL: `path("courses/<slug:slug>/u/<int:node_pk>/markdone/", views.markdone_save,
  name="markdone_save")` (mirrors `seen` / `complete`).
- `@require_POST @login_required def markdone_save(request, slug, node_pk)`:
  1. `node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)`; `course =
     node.course`; `can_access_course` else `PermissionDenied` (403).
  2. Parse the posted element pk + checked item pks. **Two content types** (mirror seen/quiz):
     JS sends `application/json` (`{"element": <pk>, "items": [<pk>, ...]}`); no-JS sends a form POST
     (`element` = the required hidden input, `item` = `getlist("item")`). **Coerce all pks to `int`**:
     the form path yields *strings* (`getlist` gives `["5","6"]`) and the JSON path yields ints, so
     both `element` and every `item` value must be normalized to `int` before use. Reject a malformed
     **`element`** (missing / non-int / bad JSON / wrong shape) with `HttpResponseBadRequest`; a
     non-int **`item`** value is NOT a 400 — coerce items in a `try/except` and simply **skip** any
     that don't parse (dropped like any non-matching id), so a garbage `item=abc` never 500s. The
     **`items` collection itself** is normalized to a list first: an absent `items` key OR a non-list
     value (`{"element":5}`, `{"items":7}`, `{"items":"abc"}`) is treated as an **empty selection**
     (`items = data.get("items"); if not isinstance(items, list): items = []`) — the per-item
     coercion loop runs only over a confirmed list, so no malformed body can 500. An empty selection
     drops the element key (step 6).
  3. **Validate ownership FIRST** (before any enrollment branch): the target element must be a
     `MarkDoneElement` belonging to `node` (resolve via the `node.elements` GFK → element;
     `HttpResponseBadRequest` (**400**) if not — the element pk is client-supplied payload, not a
     URL-addressed resource, so 400 not 404). Filter the coerced **int** item pks to those that actually
     belong to that element (`set(element.items.values_list("pk", flat=True))` is int-keyed, so the
     int-vs-int intersection matches) — drops forged/foreign/stale ids. `element` is now known-valid
     for every downstream branch (so the enrollment response can never echo an unvalidated pk).
  4. **Enrollment gate:** if not `is_enrolled(request.user, course)` → no write; return the canonical
     synthetic response — JSON `{"element": element.pk, "items": []}` (the previewer has no stored
     state) for JS, or a redirect for no-JS — exactly as `seen` returns a synthetic response for
     previewers.
  5. Acquire the locked row inside a `transaction.atomic()` block: `get_or_create(student=…, unit=…)`
     to ensure the `(student, unit)` row exists, then **re-fetch it locked** with
     `UnitProgress.objects.select_for_update().get(pk=progress.pk)` (a bare `select_for_update()` is a
     QuerySet, not a held row). Tolerate the rare concurrent-first-save `IntegrityError` on the
     `(student, unit)` unique constraint (retry the get, or wrap the create in try/except).
     **Locking is used here** (unlike `seen`) because the write is a **read-modify-write of the shared
     per-unit `checklist_state` dict**: element A's save must not clobber a concurrent element B save.
     (The `seen` view can skip locking because its merge is a commutative set-union; a dict-key
     overwrite is not.)
  6. Write the element's key: if `validated_item_pks` is non-empty,
     `progress.checklist_state[str(element.pk)] = sorted(validated_item_pks)`; if it is **empty (all
     unchecked), DROP the key** (`progress.checklist_state.pop(str(element.pk), None)`) rather than
     storing `[]`, so empty selections never accumulate. Opportunistically pruning keys for
     since-deleted elements is allowed but optional (bounded). `progress.save()`.
  7. Respond: JSON `{"element": element.pk, "items": sorted(validated_item_pks)}` — the payload is
     explicitly **single-element-scoped**, deliberately NOT named `checklist_state` (which would imply
     the full per-unit state) — for JS; redirect to the lesson unit for no-JS. The lesson url name is
     **`courses:lesson_unit`** (the same name `complete` redirects to — verified against
     `courses/views.py`), with a `#markdone-<element.pk>` fragment so the no-JS user lands back at the
     checklist.
- IDOR-safe: `student = request.user` always; never trust a posted student id.

### Student JS (`courses/static/courses/js/markdone.js`)

- Self-boots `libliInitMarkDone(document)` at parse end (like `stepper.js`); idempotent per root via
  a `dataset` flag; `window.libliInitMarkDone` exported for editor re-init.
- On init: **hide the no-JS `[data-markdone-save]` submit button** (JS auto-saves instead).
- On checkbox `change`: toggle the row's `on` class live; POST the element's full checked set to
  `data-markdone-url` via `fetch` + `keepalive` + `X-CSRFToken` (the `progress.js` beacon pattern).
  Debounce/coalesce is optional (a checklist is low-frequency); at minimum, send on each change.
- **Save-failure handling:** on a non-OK / failed `fetch` (network error, 400/403), **revert** the
  just-toggled checkbox + its `on` class to the last-known-persisted state so the UI never shows a
  tick that didn't save, and (best-effort) reveal the no-JS Save button as a manual fallback. This is
  a deliberate departure from the fire-and-forget seen-beacon, precisely because the checklist's
  whole value is durable persistence.
- No-JS fallback: the `<form>` submit posts `item` checkboxes to the same endpoint; the server
  re-renders the lesson with the stored `checked` set.
- **`has_markdone` flat query** (`courses/views.py`, mirrors `has_stepper`):
  `node.elements.filter(content_type__model="markdoneelement").exists()` — flat (not
  `parent__isnull=True`) so a tab-/column-nested checklist still loads its JS. Emitted into the
  lesson context + gates the `markdone.js` script include in the lesson template.
- `markdone.js` + `markdone_editor.js` are added to **`editor.html`** as `<script defer>` includes,
  and `editor.js` gains `libliInitMarkDone(preview)` + `libliInitMarkDoneEditor(editorPane)` re-init
  calls after fragment swaps (the twice-missed step — test-guarded).

### Math (`courses/views.py`, `math.js`)

- `_element_has_math` gains a `MarkDoneElement` branch: `has_math_delimiters(obj.prompt) or
  any(has_math_delimiters(i.content) for i in obj.items.all())`. `_tabs_has_math` /
  `_twocolumn_has_math` recurse via `_element_has_math`, covering nesting.
- `math.js renderInlineText` selector allowlist gains `.markdone` so `\(...\)` in items typeset.

### Transfer trio (`courses/transfer/*`)

- Transfer key **`mark_done`** (payload `{"prompt": ..., "items": [<content>, ...]}`).
- `_ser_mark_done(el, media_ids)` → `{"prompt": el.prompt, "items": [i.content for i in
  el.items.all()]}`; registered in `SERIALIZERS` (`export.py`).
- `_val_mark_done(data, elid, media_kinds)` — mirrors `_val_stepper` (`.get()` optional-key style:
  absent prompt → `""`; absent/blank `items` → clean `TransferError` not `KeyError`; item count in
  `[MIN_ITEMS, MAX_ITEMS]`). It enforces `MAX_LEN` up front like `_val_stepper`:
  `check_str(prompt, max_length=MAX_LEN)` for the prompt and `check_str(item, max_length=MAX_LEN,
  required=True)` for each item — so over-length strings are rejected by the validator, not only later
  by the builder's `full_clean`. Registered in `VALIDATORS` (`payloads.py`).
- `_build_mark_done(data, assets)` → `(MarkDoneElement(...), [MarkDoneItem(...), ...])`. Mirror
  `_build_stepper`: `_clean_save(MarkDoneElement(prompt=...))` so the element/prompt is `full_clean`ed
  too (not only the items), and return the items for the generic importer loop to `full_clean`+save.
  Registered in `BUILDERS` (`importer.py`).
- **`FORMAT_VERSION` is NOT bumped** — this is an additive element type, and `checklist_state` is
  per-student state, never exported as course content.

## Data flow

**Authoring.** Author opens the editor, clicks the Checklist palette card → `element_add` →
`_render_open_form` builds `MarkDoneElementForm` + an empty items formset →
`_edit_markdone.html` renders → author types a prompt + items (add-row JS clones the template) →
`element_save` → `save_element`'s `markdone` branch validates and persists the element + ordered
items.

**Consumption (JS on).** Lesson view builds context, resolves each student's `checklist_state` from
their `UnitProgress`, renders `markdoneelement.html` with the `checked` set (server-side `on`
styling) → `markdone.js` hides the Save button and wires checkbox `change` → tick a box → live `on`
toggle + `fetch` POST `{element, items}` → `markdone_save` validates ownership, filters item pks,
locks + writes `checklist_state[element_pk]`, returns JSON → next page load renders the persisted
ticks.

**Consumption (JS off).** Same server render (Save button visible) → student ticks boxes → submits
the form → `markdone_save` reads `item` getlist → writes → redirects back to the lesson → server
re-renders with the stored `checked` set.

**Previewer / author preview / non-enrolled.** Render shows an empty `checked` set; `markdone_save`
short-circuits at the enrollment gate with a synthetic no-write response — the checklist is visible
but read-only, matching the quiz previewer rule.

**Import/export.** `_ser_mark_done` writes `{prompt, items}`; `_val_mark_done` validates on import;
`_build_mark_done` reconstructs the element + items. Student `checklist_state` is **not** part of the
course export.

## Error handling

- **Malformed POST** (bad JSON, wrong shape, missing element) → `HttpResponseBadRequest`.
- **No access** to the course → `PermissionDenied` (403).
- **Not enrolled** → canonical no-write response (not an error; previewers are allowed to see it).
- **Forged / foreign / stale item pks** → silently filtered to the element's real item pks (never
  trusted); forged element pk (not a `MarkDoneElement` in this unit) → `HttpResponseBadRequest` (400).
- **Concurrent saves** to different checklists in the same unit → `select_for_update` serializes the
  read-modify-write, preventing lost updates to the shared `checklist_state` dict.
- **Stale stored item pks** (author deleted an item after a tick) → ignored on read (only current
  item pks are matched when computing `checked`); pruned opportunistically on the next write.
- **Form/formset invalid** in the editor → `ElementFormInvalid(form, formset)` re-renders with
  errors (the Stepper path).
- **Import validation failure** → `TransferError` with a localized message (never a raw `KeyError`).
- **JS disabled / blocked** → the `<form>` + Save button is the working fallback; server renders the
  correct checked state on every load. No hard-hidden content depends on JS.

## Testing

Follow the libli element test conventions (unit tests in `courses/tests/`, integration/e2e at repo
root `tests/`). DoD: `ruff check` + `ruff format --check` clean, `makemigrations --check` +
`manage check` clean, EN/PL catalogs fuzzy-free (`test_po_catalog_clean`), full `pytest -m "not
e2e"` green (run `-n auto`), targeted e2e green (run the single file foreground with `-m e2e`).

**Model / form:** element + item creation, `order` assignment (gap-free, reorder), `save()`
stripping, MIN/MAX item validation, blank/DELETE row dropping in `save_element`.

**Persistence / endpoint:**
- Enrolled student POST persists `checklist_state[element_pk]` = checked item pks; reload renders
  them checked with `on`.
- No-JS form POST persists the same (getlist path).
- Non-enrolled / previewer POST does **not** write (synthetic response); render shows empty checked.
- Forged/foreign/stale item pks filtered out; forged element pk → 400.
- IDOR: a student cannot write another student's progress (student is always `request.user`).
- `can_access_course` false → 403.
- **Merge-not-clobber behaviour** (the real invariant behind `select_for_update`): a test saves
  element A, then element B, in the **same** unit, and asserts BOTH `checklist_state` keys survive —
  proving the endpoint does `checklist_state[pk] = ...` (read-modify-write) and never
  `checklist_state = {pk: ...}` (whole-dict overwrite). A `select_for_update`-presence assertion
  alone is insufficient (tautological) and does not substitute for this behavioural test. A full
  concurrent-interleaved-transaction test is not required (the lock defends live concurrency; the
  sequential merge test proves the code shape).
- **All-unchecked drops the key**: saving element A with items checked then re-saving with none
  checked leaves no `str(A.pk)` key in `checklist_state` (not a `[]` entry).
- Keyed-by-pk edit-safety: add/remove/reorder items, previously-checked surviving items stay
  checked, deleted item's tick ignored.
- Ticking all items does **not** complete the unit (completion still requires the seen-set / manual
  mark-done).

**Rendering / wiring:**
- `markdoneelement.html` renders real checkboxes with server-side `checked`/`on`.
- `has_markdone` true (flat) for a top-level AND a tab-/column-nested checklist → lesson loads
  `markdone.js`.
- `_element_has_math` true when a prompt or item carries `\(...\)`; nested-in-tabs math covered.
- Editor `_edit_markdone.html` renders (GET/POST `element_add` for `markdone` → 200; guards against
  `TemplateDoesNotExist`).
- `editor.html` includes `markdone.js` + `markdone_editor.js` (script-presence test, per the
  twice-missed-step guard).

**Transfer:** round-trip export → validate → import reconstructs prompt + ordered items;
`_val_mark_done` rejects bad shapes with `TransferError`; the `ELEMENT_MODELS` length assert in
`tests/test_transfer_schema.py` is bumped per the provisional `base_len → base_len + 1` rule (**29 →
30** on the current `master` base — illustrative only; read the actual value, don't hardcode).

**e2e (single focused file, foreground):** real-browser tick → reload persists (enrolled);
optionally a nested-in-tabs checklist ticks and persists. Drive the real checkbox gesture (not
`page.evaluate`), per the e2e-must-drive-real-UI lesson.

**Frontend-design pass (post-functional):** run `frontend-design` on BOTH the student render
(checklist idle / done-with-strikethrough states, light + dark) AND the editor authoring UI (prompt
+ items formset), verifying with light + dark screenshots — authoring UIs get the design pass too,
not just consumption.
