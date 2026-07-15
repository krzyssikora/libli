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
- No coupling to unit completion or the seen-set.
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
- **`ELEMENT_MODELS`** (`courses/models.py:259`) gains `"markdoneelement"` → length **29 → 30**.

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

- New migration(s) starting at **0048** adding `MarkDoneElement`, `MarkDoneItem`, and
  `UnitProgress.checklist_state`. `checklist_state` has `default=dict` so it back-fills to `{}` for
  existing rows with no data migration. (Splitting the model additions and the `UnitProgress` field
  into separate migration files is acceptable and slightly more reviewable, but a single generated
  migration is fine.)

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
  its `== 23` assert — **that assert is unchanged**.

### Student render (`templates/courses/elements/markdoneelement.html`)

Selected by `ElementBase.render` convention. Renders a real, no-JS-correct form:

```
<div class="markdone" data-markdone
     data-markdone-url="{% url 'courses:markdone_save' slug=... node_pk=... %}"
     data-element-id="{{ el.pk }}">
  <form method="post" action="{{ save_url }}">   {# no-JS submit path #}
    {% csrf_token %}
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

- `checked` = the set of checked item pks for this element, resolved from
  `UnitProgress.checklist_state[str(el.pk)]` (see Data flow). Passed into the render context.
- Checked items get the `on` class **server-side**, so the done styling is correct with JS off.
- The **`data-element-id`** attribute must be preserved for the seen-beacon (it lives on the
  top-level `.lesson-block`, but the element root also carrying it is harmless and matches how other
  elements expose their pk); the checklist itself is orthogonal to the seen-set.
- **Context plumbing:** `render()` needs the `checked` set and the `save_url`. Because
  `ElementBase.render()` takes no request/context, the render path must thread these in. Follow the
  existing pattern used to give elements per-student context in lessons (the lesson view already
  builds a `progress` object and per-element context in `build_lesson_context` /
  `_lesson_article.html`); the plan resolves the exact seam. Minimum: the lesson render passes a
  `checklist_state` lookup + a `save_url` resolver so each `MarkDoneElement` renders its checked set.
  Preview/editor render (no student) → empty `checked`, save no-ops.

### Save endpoint (`courses/views.py` + `courses/urls.py`)

- URL: `path("courses/<slug:slug>/u/<int:node_pk>/markdone/", views.markdone_save,
  name="markdone_save")` (mirrors `seen` / `complete`).
- `@require_POST @login_required def markdone_save(request, slug, node_pk)`:
  1. `node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)`; `course =
     node.course`; `can_access_course` else `PermissionDenied` (403).
  2. Parse the posted element pk + checked item pks. **Two content types** (mirror seen/quiz):
     JS sends `application/json` (`{"element": <pk>, "items": [<pk>, ...]}`); no-JS sends a form POST
     (`element` hidden or derived, `item` = `getlist("item")`). Accept both; reject malformed with
     `HttpResponseBadRequest`.
  3. **Enrollment gate:** if not `is_enrolled(request.user, course)` → return the canonical
     "no write" response (JSON `{"checklist_state": {...current for element...}}` or a redirect for
     no-JS), exactly as `seen` returns a synthetic response for previewers.
  4. **Validate ownership:** the target element must be a `MarkDoneElement` belonging to `node`
     (query `node.elements` GFK → element; 404/400 if not). Filter the incoming item pks to those
     that actually belong to that element (`element.items` pks) — drops forged/foreign/stale ids.
  5. `progress = UnitProgress.objects.select_for_update(...)` inside a transaction (or
     `get_or_create` then `select_for_update` re-fetch) — **`select_for_update` is used here**
     (unlike `seen`) because the write is a **read-modify-write of the shared per-unit
     `checklist_state` dict**: element A's save must not clobber a concurrent element B save. (The
     `seen` view can skip locking because its merge is a commutative set-union; a dict-key overwrite
     is not.)
  6. `progress.checklist_state[str(element.pk)] = sorted(validated_item_pks)`; **prune** any
     top-level keys whose element no longer exists in the unit is optional (bounded; may be deferred).
     `progress.save()`.
  7. Respond: JSON `{"checklist_state": {str(element.pk): [...]}}` for JS; redirect to
     `courses:lesson_unit` for no-JS.
- IDOR-safe: `student = request.user` always; never trust a posted student id.

### Student JS (`courses/static/courses/js/markdone.js`)

- Self-boots `libliInitMarkDone(document)` at parse end (like `stepper.js`); idempotent per root via
  a `dataset` flag; `window.libliInitMarkDone` exported for editor re-init.
- On init: **hide the no-JS `[data-markdone-save]` submit button** (JS auto-saves instead).
- On checkbox `change`: toggle the row's `on` class live; POST the element's full checked set to
  `data-markdone-url` via `fetch` + `keepalive` + `X-CSRFToken` (the `progress.js` beacon pattern).
  Debounce/coalesce is optional (a checklist is low-frequency); at minimum, send on each change.
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

- `_element_has_math` gains a `MarkDoneElement` branch: `has_math_delimiters(prompt) or
  any(has_math_delimiters(i.content) for i in obj.items.all())`. `_tabs_has_math` /
  `_twocolumn_has_math` recurse via `_element_has_math`, covering nesting.
- `math.js renderInlineText` selector allowlist gains `.markdone` so `\(...\)` in items typeset.

### Transfer trio (`courses/transfer/*`)

- Transfer key **`mark_done`** (payload `{"prompt": ..., "items": [<content>, ...]}`).
- `_ser_mark_done(el, media_ids)` → `{"prompt": el.prompt, "items": [i.content for i in
  el.items.all()]}`; registered in `SERIALIZERS` (`export.py`).
- `_val_mark_done(data, elid, media_kinds)` — mirrors `_val_stepper` (`.get()` optional-key style:
  absent prompt → `""`; absent/blank `items` → clean `TransferError` not `KeyError`; item count in
  `[MIN_ITEMS, MAX_ITEMS]`; each item `check_str(required=True)`); registered in `VALIDATORS`
  (`payloads.py`).
- `_build_mark_done(data, assets)` → `(MarkDoneElement(...), [MarkDoneItem(...), ...])`, the generic
  importer loop `full_clean`+saves the items; registered in `BUILDERS` (`importer.py`).
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
  trusted); forged element pk (not a `MarkDoneElement` in this unit) → 400/404.
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
- Forged/foreign/stale item pks filtered out; forged element pk → 400/404.
- IDOR: a student cannot write another student's progress (student is always `request.user`).
- `can_access_course` false → 403.
- Concurrent-write intent covered by a `select_for_update` presence/behaviour test (two elements'
  saves don't clobber each other's key).
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
`_val_mark_done` rejects bad shapes with `TransferError`; `ELEMENT_MODELS` length assert **29 → 30**
(`tests/test_transfer_schema.py`).

**e2e (single focused file, foreground):** real-browser tick → reload persists (enrolled);
optionally a nested-in-tabs checklist ticks and persists. Drive the real checkbox gesture (not
`page.evaluate`), per the e2e-must-drive-real-UI lesson.

**Frontend-design pass (post-functional):** run `frontend-design` on BOTH the student render
(checklist idle / done-with-strikethrough states, light + dark) AND the editor authoring UI (prompt
+ items formset), verifying with light + dark screenshots — authoring UIs get the design pass too,
not just consumption.
