# Show more reveal-gate element

Slice 1 of the interactive-elements roadmap: a new **"Show more"** content element that progressively reveals the elements following it, ported from the legacy Demo Course JS (`_template.html`, the "just show next" section).

## Purpose

Authors need to hide part of a lesson behind a button so students work through content in stages ("do this, then reveal the next step"). Today libli has no progressive-disclosure element.

The **Show more gate** is a thin **divider/marker** element (conceptually like the existing `slidebreak`), not a container. When present in a lesson it renders a button and hides the sibling elements that follow it within its scope. Clicking reveals the next run of content — up to and including the next gate — and arms that next gate. Only one button is visible at a time; the used button disappears.

This slice ships the **reveal engine** that slices 2 (fill-in & confirm) and 3 (choose & confirm) will build on, plus the simplest, check-free gate.

### Confirmed product decisions

- **Shape:** gate/divider that reveals *following sibling* elements — NOT a container of children.
- **Reveal per click:** reveal following siblings **up to and including the next gate** in scope, then stop (staged cascade). Multiple gates ⇒ multiple stages.
- **Button label:** author-editable single optional field; defaults to "Show more" / "Pokaż więcej" when blank.
- **Persistence:** ephemeral — gates reset to collapsed on every page load. No storage.
- **Availability:** offered in **lesson units only** (palette omits the card in quiz units); also allowed **inside tabs** within lessons.
- **Quiz / conversion safety:** the gate degrades to an inert no-op in quiz units (see Error handling).

### Out of scope

The inline reveal stepper (`010_test.html` — math revealed left-to-right on one line) is a separate self-contained element, deferred. Slices 2–3 (graded gates) are separate future slices. No change to `slidebreak` or `tabs`.

## Architecture / components

The gate clones the `slidebreak` element's end-to-end wiring, but because it has one editable field it uses the **normal add-form flow** (not slidebreak's fieldless direct-save). Touch-points:

**Model** — `courses/models.py`
- `RevealGateElement(ElementBase)` with `label = CharField(max_length=120, blank=True)` and the standard `elements = GenericRelation(Element)`.
- Add `"revealgateelement"` to `ELEMENT_MODELS` (this feeds the GFK `limit_choices_to`).
- Migration `0036_revealgateelement_...` with `dependencies = [("courses", "0035_...")]` (0035 is the current latest). It creates the model AND alters `Element.content_type`'s frozen `limit_choices_to` `model__in` list — same shape as `0032` did for slidebreak.

**Form** — `courses/element_forms.py`
- `RevealGateElementForm(forms.ModelForm)`, `Meta.fields = ["label"]`.
- Register `FORM_FOR_TYPE["revealgate"]`.

**Builder** — `courses/builder.py`
- No special-case needed in `save_element`; the generic path handles it (no sub-rows).
- Add `"revealgate"` to `NESTABLE_TYPE_KEYS` so a gate may live inside a tab.

**Views** — `courses/views_manage.py`
- Add `"revealgate"` to BOTH the `element_add` and `element_save` allow-tuples (it has a form).
- `_EDITOR_TYPE_LABELS["revealgate"] = gettext_lazy("Show more")`.

**Labels / summary** — `courses/templatetags/courses_manage_extras.py`
- `_ELEMENT_LABELS["revealgateelement"] = _("Show more")`.
- `element_summary` case: return the element's `label`, or the default when blank.

**Icon** — `templates/courses/manage/_icon_sprite.html`
- New monochrome `currentColor` sprite symbol `#el-revealgate`.

**Palette** — `templates/courses/manage/editor/_add_menu.html`
- New group **"Interactive"** containing the gate card (`data-add-type="revealgate"`, icon `#el-revealgate`).
- The card renders **only in lesson units**. NOTE: there is currently **no** quiz flag at the add-menu render seam — the `is_quiz` set at `views_manage.py:835` lives in `_render_open_form` and is passed only to `_host_form.html`, not to the palette (`_add_menu.html`, reached via `_render_editor_fragments` → `_editor_page`/`_editor_scope.html`). This slice must **newly thread** a quiz flag through that fragment/page/scope path into `_add_menu.html` (and into the nested add-menu path used when editing a tabs element), then gate the card on it. Do not treat the flag as pre-existing there: a missing template variable renders falsy, so a naive `{% if not is_quiz %}` would fail-open and show the card in quizzes — the opposite of the intended safety. Available in nested (tab) context within lessons.

**Student renderer** — `templates/courses/elements/revealgateelement.html`
```html
<button type="button" class="reveal-gate" data-reveal-gate hidden>
  {% if el.label %}{{ el.label }}{% else %}{% trans "Show more" %}{% endif %}
</button>
```
The button is server-rendered `hidden`; only the reveal JS un-hides it (progressive enhancement).

**Editor row** — `templates/courses/manage/editor/_element_row.html`
- Bespoke divider-styled row (like `element-row--slidebreak`) BUT with an edit affordance for the label, captioned e.g. *"Show more — hides the following blocks until the student clicks."* Since the preview deliberately does not collapse, this row is how the author understands the gate's effect.
- In a **quiz** unit (a gate present post-conversion), the row is flagged, e.g. *"Show more (inactive in quizzes)."* The row detects quiz-ness by comparing `unit.unit_type` to `ContentNode.UnitType.QUIZ` (`_element_row.html` already receives `unit`); if the enum is not reachable from the template, pass a boolean into the row's context.

**Reveal engine (JS)** — `courses/static/courses/js/reveal.js`
- Exposes `window.libliInitRevealGates(root)`, following the `tabs.js` idiom: IIFE, idempotent `dataset` guard, self-init on `document`, class-agnostic wrapper walk.
- Loaded on `templates/courses/lesson_unit.html` **only** — **no i18n blob is required**, because the button label is server-rendered (author `label`, or the `{% trans "Show more" %}` default). NOT wired into the editor preview (`editor.js` `applyFragments`) — authors should see all their content while editing, and it avoids the `.prev-el` wrapper case. NOT loaded on the quiz page — this is what makes gates inert in quizzes. The lesson page also carries the synchronous inline `reveal-armed` class-setter and the pre-hide stylesheet (see Data flow); the quiz page and the editor preview carry **neither**, so neither pre-hides (this is what keeps the nested-in-tab preview fully expanded).

**Transfer** — `courses/transfer/{export,payloads,importer}.py`
- New key `reveal_gate` (snake_case) in all three lockstep registries: `SERIALIZERS` (serialize `{"label": ...}`, no media), `VALIDATORS` (empty media set), `BUILDERS` (create with `label`).
- **No `FORMAT_VERSION` bump** — additive new element type, matching how `gallery`/`table`/`slide_break` were added (only the tabs *nesting* fields bumped to v3; `parent`/`tab` already exist at v3 and cover a gate inside a tab).

**i18n** — `locale/{en,pl}/LC_MESSAGES/django.po`
- New strings: default label "Show more" / "Pokaż więcej"; group "Interactive" / "Interaktywne"; editor label + row caption + quiz-inactive note.

## Data flow

**Render (student, lesson).** Elements render as `.slide > section.lesson-block[data-element-id]` siblings (the gate is a real element that stays in the DOM — unlike `slidebreak`, which `partition_into_slides` consumes before render). The gate's reveal scope is therefore naturally bounded by its enclosing `.slide`, or by `[data-tab-panel]` when nested in a tab (children there are `.tabs__child` direct siblings).

**Reveal engine runtime.** Scope for a gate = `button.closest('[data-tab-panel], .slide')`. The gate's own scope-child ancestor is found by walking up until the parent is the scope container (works for both `.lesson-block` and `.tabs__child` — class-agnostic).

- **Pre-paint hide (no flash, no-JS-safe) — class-gated CSS, not JS-after-paint.** A synchronous inline `<script>` at the top of the lesson page adds a root class `reveal-armed` (to `<html>` or the article root) *before* first paint. A stylesheet rule gated on that class pre-hides every run:
  - `.reveal-armed .slide > .lesson-block:has([data-reveal-gate]) ~ .lesson-block { display: none; }`
  - tab analogue: `.reveal-armed [data-tab-panel] > .tabs__child:has([data-reveal-gate]) ~ .tabs__child { display: none; }`

  Because the hide is gated on `reveal-armed`, **no-JS never hides** (the inline script never ran → no class → all content visible) and the **editor preview never hides** (the preview page emits no such inline script) — this covers the nested-in-tab preview case too. `:has()` is required; a browser lacking it drops the rule and gates simply don't gate (graceful degradation, same net effect as no-JS). This makes the earlier "accept a minor flash" fallback unnecessary — there is no JS-after-paint hide, hence no spoiler flash.

- **Init (`reveal.js`, deferred, idempotent via a `dataset` guard).** Remove the server-rendered `hidden` attribute from **every** `[data-reveal-gate]` button. Buttons inside still-hidden wrappers stay invisible with their wrapper; only the first gate's button shows (its wrapper is the run's anchor, never a hidden following-sibling). This is the single "who un-hides the buttons" mechanism — there is no per-gate button arming beyond wrapper visibility.

- **Click.** Compute the run = following-sibling wrappers up to **and including** the next gate's wrapper in scope. Reveal each by adding a `reveal-shown` class whose rule overrides the pre-hide (`.reveal-armed .reveal-shown { display: revert !important; }`), and dispatch a bubbling `libli:reveal` CustomEvent on each (so a gallery/tabs/math inside re-measures — established contract). Then **consume** the clicked gate's own wrapper: remove its `reveal-shown` (if any) and set its `hidden` attribute, so the button disappears and it cannot win over the pre-hide. The next gate's wrapper is now revealed and its already-un-hidden button is armed. Exactly one gate button is ever visible, because exactly one un-consumed gate wrapper is visible at a time.

**Transfer round-trip.** Export serializes `{label}`; import rebuilds the element with that label. A gate nested in a tab round-trips via the existing v3 `parent`/`tab` keys.

## Error handling

- **No-JS:** the inline `reveal-armed` class-setter never runs → the pre-hide CSS is inert → all content is visible; buttons stay server-`hidden` (reveal.js never un-hid them), so no dead buttons appear. Correct, accessible fallback.
- **Quiz units / lesson→quiz conversion:** the lesson page carries the `reveal-armed` setter, the pre-hide stylesheet, and `reveal.js`; the **quiz page carries none of them**. So a gate that ends up in a quiz (units are convertible via the settings/type-only edit, `views_manage.py:302`) never pre-hides and never un-hides its button — it gates nothing. **Zero data migration** — the gate is automatically inert. A converted gate leaves only a small empty `.lesson-block` (button server-`hidden`); fully suppressing that is an optional refinement, not required.
- **Print:** an `@media print` block neutralizes the pre-hide (`.reveal-armed .slide > .lesson-block:has([data-reveal-gate]) ~ .lesson-block, .reveal-armed [data-tab-panel] > .tabs__child:has([data-reveal-gate]) ~ .tabs__child { display: revert !important; }`) and hides the buttons (`[data-reveal-gate] { display: none !important; }`). Everything prints and no buttons show, no matter how far the student had revealed.
- **Auto-completion interaction (`progress.js`):** unit auto-completion marks an element "seen" only when it intersects the viewport (`static/courses/js/progress.js`); gated content, hidden pre-reveal, has no layout box and is not counted until revealed. **Intended behavior:** a student must reveal gated content for it to count toward auto-completion; the existing "Mark as done" affordance remains the fallback for a unit whose trailing gate is left unopened. This is a deliberate consequence of gating, not a regression.
- **Empty/degenerate cases:** a gate with no following siblings in scope (last element) simply reveals nothing and consumes itself on click — harmless. Two adjacent gates ⇒ clicking the first reveals up to and including the second (nothing between), arming it.
- **Nesting:** the gate holds no children, so "nesting a gate into itself" does not arise; it is only *nestable into tabs*. Tabs-in-tabs restrictions are unaffected.

## Testing

- **Model/form/builder:** create + save via `RevealGateElementForm`; label persists; blank label renders the default; `revealgate` accepted by `element_add`/`element_save`; nestability flag present.
- **Transfer:** export → import round-trip preserves `label`; a gate inside a tab round-trips (v3 nesting keys); no `FORMAT_VERSION` change (existing schema-version tests stay green).
- **Renderer:** button rendered with `hidden` + `data-reveal-gate`; label vs default text.
- **Palette gating:** the Interactive gate card is present in a lesson-unit editor and absent in a quiz-unit editor.
- **Editor row:** the bespoke row renders its caption; the quiz-inactive flag shows when the gate is in a quiz unit.
- **Completion interaction:** gated (unrevealed) content is not marked "seen" by `progress.js`; revealing it lets it count — a regression-guard documenting the intended auto-completion behavior (I4).
- **e2e (Playwright, drives the REAL click cascade per the `e2e-must-drive-real-ui` lesson):** two gates in a lesson → only the first button visible initially; clicking it reveals its run and arms the second button; clicking the second reveals the rest; verify the quiz page does NOT gate (all content visible, no button). Run focused e2e in the foreground (per the gallery-carousel build lesson); the controller owns the full-suite Definition-of-Done, including the i18n catalog tests since this slice adds translatable strings.

## Prior art to copy

- Thin element wiring end-to-end: `slidebreak` (`models.py`, `element_forms.py:179`, `_element_row.html:2`, `_add_menu.html:38`, transfer `_ser/_val/_build_slide_break`).
- Enhancer idiom + `libli:reveal`: `tabs.js`, `gallery.js`.
- DOM: `_lesson_article.html` (`.slide > section.lesson-block[data-element-id]`), `tabselement.html` (`[data-tab-panel] > .tabs__child`).
- Nesting substrate & container prior art: the tabs element slice.
