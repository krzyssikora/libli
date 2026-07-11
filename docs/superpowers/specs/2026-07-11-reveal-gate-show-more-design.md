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
- Migration: create the model AND alter `Element.content_type`'s frozen `limit_choices_to` `model__in` list (mirror migration `0032`).

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
- The card renders **only in lesson units** — gate on the existing `is_quiz` context flag (available at `element_add`, `views_manage.py:835`). Available in nested (tab) context within lessons.

**Student renderer** — `templates/courses/elements/revealgateelement.html`
```html
<button type="button" class="reveal-gate" data-reveal-gate hidden>
  {% if el.label %}{{ el.label }}{% else %}{% trans "Show more" %}{% endif %}
</button>
```
The button is server-rendered `hidden`; only the reveal JS un-hides it (progressive enhancement).

**Editor row** — `templates/courses/manage/editor/_element_row.html`
- Bespoke divider-styled row (like `element-row--slidebreak`) BUT with an edit affordance for the label, captioned e.g. *"Show more — hides the following blocks until the student clicks."* Since the preview deliberately does not collapse, this row is how the author understands the gate's effect.
- In a **quiz** unit (a gate present post-conversion), the row is flagged, e.g. *"Show more (inactive in quizzes)."*

**Reveal engine (JS)** — `courses/static/courses/js/reveal.js`
- Exposes `window.libliInitRevealGates(root)`, following the `tabs.js` idiom: IIFE, idempotent `dataset` guard, self-init on `document`, class-agnostic wrapper walk.
- Loaded on `templates/courses/lesson_unit.html` **only** (with an i18n blob if needed). NOT wired into the editor preview (`editor.js` `applyFragments`) — authors should see all their content while editing, and it avoids the `.prev-el` wrapper case. NOT loaded on the quiz page — this is what makes gates inert in quizzes.

**Transfer** — `courses/transfer/{export,payloads,importer}.py`
- New key `reveal_gate` (snake_case) in all three lockstep registries: `SERIALIZERS` (serialize `{"label": ...}`, no media), `VALIDATORS` (empty media set), `BUILDERS` (create with `label`).
- **No `FORMAT_VERSION` bump** — additive new element type, matching how `gallery`/`table`/`slide_break` were added (only the tabs *nesting* fields bumped to v3; `parent`/`tab` already exist at v3 and cover a gate inside a tab).

**i18n** — `locale/{en,pl}/LC_MESSAGES/django.po`
- New strings: default label "Show more" / "Pokaż więcej"; group "Interactive" / "Interaktywne"; editor label + row caption + quiz-inactive note.

## Data flow

**Render (student, lesson).** Elements render as `.slide > section.lesson-block[data-element-id]` siblings (the gate is a real element that stays in the DOM — unlike `slidebreak`, which `partition_into_slides` consumes before render). The gate's reveal scope is therefore naturally bounded by its enclosing `.slide`, or by `[data-tab-panel]` when nested in a tab (children there are `.tabs__child` direct siblings).

**Reveal engine runtime.** Scope for a gate = `button.closest('[data-tab-panel], .slide')`. The gate's own scope-child ancestor is found by walking up until the parent is the scope container (works for both `.lesson-block` and `.tabs__child` — class-agnostic).
- **Init:** for the FIRST gate in each scope, hide every following sibling wrapper in that scope using the `hidden` **attribute** (like `tabs.js`, so print CSS can override). Later gates need no init — already hidden by the first.
- **Click:** reveal following siblings up to **and including** the next gate's wrapper, then stop (the next gate's run stays hidden from the first gate's init). On each newly revealed wrapper dispatch a bubbling `libli:reveal` CustomEvent (so a gallery/tabs/math inside re-measures — established contract). Then hide the clicked gate's own wrapper (button disappears). The next gate's button is now visible and armed.

**Flash-of-content mitigation.** Runs are hidden by JS after paint, so there is a brief flash of full content before collapse. Preferred fix: a pure-CSS pre-paint hide using `:has()`, e.g. `.slide .lesson-block:has([data-reveal-gate]) ~ .lesson-block { display: none; }` (and the `[data-tab-panel]` analogue), which the JS then overrides as it reveals. The implementation reconciles this CSS initial-hide with the `hidden`-attribute reveal (e.g. JS clears the CSS-hide by toggling a scope class once enhanced, and manages per-run visibility via the `hidden` attribute). Acceptable fallback if `:has()` proves awkward: accept a minor flash.

**Transfer round-trip.** Export serializes `{label}`; import rebuilds the element with that label. A gate nested in a tab round-trips via the existing v3 `parent`/`tab` keys.

## Error handling

- **No-JS:** button stays `hidden`, all content visible — correct, accessible fallback.
- **Quiz units / lesson→quiz conversion:** `reveal.js` is not loaded on the quiz page, so a gate that ends up in a quiz (units are convertible via the settings/type-only edit, `views_manage.py:302`) never un-hides its button and gates nothing. **Zero data migration** — the gate is automatically inert. A converted gate leaves only a small empty `.lesson-block`; fully suppressing that is an optional refinement, not required.
- **Print:** `@media print` overrides `[hidden]` on `.lesson-block`/`.tabs__child` so all content prints, and hides `[data-reveal-gate]` buttons — same idiom as tabs.
- **Empty/degenerate cases:** a gate with no following siblings in scope (last element) simply reveals nothing and removes itself on click — harmless. Two adjacent gates ⇒ clicking the first reveals up to and including the second (nothing between), arming it.
- **Nesting:** a gate is non-nestable-into-itself concern does not arise (it holds no children); it is only *nestable into tabs*. Tabs-in-tabs restrictions are unaffected.

## Testing

- **Model/form/builder:** create + save via `RevealGateElementForm`; label persists; blank label renders the default; `revealgate` accepted by `element_add`/`element_save`; nestability flag present.
- **Transfer:** export → import round-trip preserves `label`; a gate inside a tab round-trips (v3 nesting keys); no `FORMAT_VERSION` change (existing schema-version tests stay green).
- **Renderer:** button rendered with `hidden` + `data-reveal-gate`; label vs default text.
- **Palette gating:** the Interactive gate card is present in a lesson-unit editor and absent in a quiz-unit editor.
- **Editor row:** the bespoke row renders its caption; the quiz-inactive flag shows when the gate is in a quiz unit.
- **e2e (Playwright, drives the REAL click cascade per the `e2e-must-drive-real-ui` lesson):** two gates in a lesson → only the first button visible initially; clicking it reveals its run and arms the second button; clicking the second reveals the rest; verify the quiz page does NOT gate (all content visible, no button). Run focused e2e in the foreground (per the gallery-carousel build lesson); the controller owns the full-suite Definition-of-Done, including the i18n catalog tests since this slice adds translatable strings.

## Prior art to copy

- Thin element wiring end-to-end: `slidebreak` (`models.py`, `element_forms.py:179`, `_element_row.html:2`, `_add_menu.html:38`, transfer `_ser/_val/_build_slide_break`).
- Enhancer idiom + `libli:reveal`: `tabs.js`, `gallery.js`.
- DOM: `_lesson_article.html` (`.slide > section.lesson-block[data-element-id]`), `tabselement.html` (`[data-tab-panel] > .tabs__child`).
- Nesting substrate & container prior art: the tabs element slice.
