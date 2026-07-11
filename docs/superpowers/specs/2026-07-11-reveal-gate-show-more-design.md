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

**Views (editor)** — `courses/views_manage.py`
- Add `"revealgate"` to BOTH the `element_add` and `element_save` allow-tuples (it has a form).
- `_EDITOR_TYPE_LABELS["revealgate"] = gettext_lazy("Show more")`.

**Views (student lesson consumption)** — `courses/views.py`
- The lesson consumption view here already computes `has_math` / `has_questions` / `has_html` for `lesson_unit.html`; add **`has_reveal_gate`** to that same context, computed as the flat `Element`-by-unit query in Data flow. Do NOT add it only to the editor context — the co-gating triad must emit on the real lesson page.

**Base / lesson templates** — `templates/base.html`, `templates/courses/lesson_unit.html`
- `base.html` needs **no change**: `{% block prepaint %}` already exists at `base.html:43` (`<head>`, before stylesheet links).
- `lesson_unit.html` **newly overrides** `{% block prepaint %}` to emit — gated on `has_reveal_gate` — the inline `reveal-armed` setter + watchdog and the render-blocking pre-hide `<style>`; it also gains the deferred `reveal.js` include under the same `has_reveal_gate` gate (the co-gating triad).

**Labels / summary** — `courses/templatetags/courses_manage_extras.py`
- `_ELEMENT_LABELS["revealgateelement"] = _("Show more")` — `_` in `courses_manage_extras.py` must resolve to `gettext_lazy` (it already does), so this module-level dict entry doesn't freeze to English (the known lazy-import requirement for module-level translatable dicts).
- `element_summary` case: return the element's `label`, or the default when blank.

**Icon** — `templates/courses/manage/_icon_sprite.html`
- New monochrome `currentColor` sprite symbol `#el-revealgate`.

**Palette** — `templates/courses/manage/editor/_add_menu.html`
- New group **"Interactive"** containing the gate card (`data-add-type="revealgate"`, icon `#el-revealgate`). The **entire Interactive group (heading + card)** is gated on the non-quiz flag, not just the card — otherwise a quiz editor would show a stray "Interactive" heading with nothing under it.
- The card renders **only in lesson units**. NOTE: there is currently **no** quiz flag at the add-menu render seam — the `is_quiz` set at `views_manage.py:835` lives in `_render_open_form` and is passed only to `_host_form.html`, not to the palette (`_add_menu.html`, reached via `_render_editor_fragments` → `_editor_page`/`_editor_scope.html`). This slice must **newly thread** a quiz flag through that fragment/page/scope path into `_add_menu.html` (and into the nested add-menu path used when editing a tabs element), then gate the card on it. Do not treat the flag as pre-existing there: a missing template variable renders falsy, so a naive `{% if not is_quiz %}` would fail-open and show the card in quizzes — the opposite of the intended safety. The threaded flag is keyed on the **unit's** type (quiz-ness), not the container, so it suppresses the group in any quiz-unit context — top-level or nested. Whether a tabs element can currently be added in a quiz unit is not relied upon: if it can, the palette-gating test includes the nested-in-quiz case; if tabs are lesson-only, the nested threading is defensive-only. Available in nested (tab) context within lessons.

**Student renderer** — `templates/courses/elements/revealgateelement.html`
```html
<button type="button" class="reveal-gate" data-reveal-gate hidden>
  {% if el.label %}{{ el.label }}{% else %}{% trans "Show more" %}{% endif %}
</button>
```
The button is server-rendered `hidden`; only the reveal JS un-hides it (progressive enhancement). A CSS rule `.reveal-gate[hidden] { display: none !important; }` is **required** so the server-`hidden` state actually hides — an author-origin `display` on the button would otherwise beat the UA `[hidden]` rule (the same gotcha `app.css` already handles for `.btn[hidden]`, `.modal[hidden]`, etc.). Do not set a plain `display` on `.reveal-gate` without this guard. The same guard extends to the consumed **wrapper**, which `consume` hides via `[hidden]`: include `.lesson-block[hidden], .tabs__child[hidden] { display: none !important; }` (these wrappers carry no author `display` today, but consume relies on `[hidden]` actually hiding them, so pin the invariant in CSS).

**Editor row** — `templates/courses/manage/editor/_element_row.html`
- Bespoke divider-styled row (like `element-row--slidebreak`) BUT with an edit affordance for the label, captioned e.g. *"Show more — hides the following blocks until the student clicks."* Since the preview deliberately does not collapse, this row is how the author understands the gate's effect. The edit affordance is the **standard** element-row edit control (it opens the `element_save`/`revealgate` form) — the row must NOT inherit slidebreak's edit-suppression (slidebreak is fieldless; the gate's `label` must stay editable after creation). No bespoke inline label editor.
- In a **quiz** unit (a gate present post-conversion), the row is flagged, e.g. *"Show more (inactive in quizzes)."* The row detects quiz-ness by comparing `unit.unit_type` to `ContentNode.UnitType.QUIZ` (`_element_row.html` already receives `unit`); if the enum is not reachable from the template, pass a boolean into the row's context.

**Reveal engine (JS)** — `courses/static/courses/js/reveal.js`
- Exposes `window.libliInitRevealGates(root)`, following the `tabs.js` idiom: IIFE, idempotent `dataset` guard, self-init on `document`, class-agnostic wrapper walk.
- Loaded on `templates/courses/lesson_unit.html` **only** — **no i18n blob is required**, because the button label is server-rendered (author `label`, or the `{% trans "Show more" %}` default). NOT wired into the editor preview (`editor.js` `applyFragments`) — authors should see all their content while editing, and it avoids the `.prev-el` wrapper case. NOT loaded on the quiz page — this is what makes gates inert in quizzes. The lesson page also carries the synchronous inline `reveal-armed` class-setter and the pre-hide stylesheet (see Data flow); the quiz page and the editor preview carry **neither**, so neither pre-hides (this is what keeps the nested-in-tab preview fully expanded).
- **Co-gating invariant (fail-safe).** The three pieces — the inline `reveal-armed` setter, the render-blocking pre-hide `<style>`, and `reveal.js` — form an **all-or-nothing triad emitted together under one condition**: a `has_reveal_gate` context flag on the lesson page (mirroring the existing `has_math` / `has_questions` / `has_html` gating in `lesson_unit.html`). **`has_reveal_gate` must be true whenever a gate exists *anywhere* in the unit, including nested inside a tab** — compute it as a **flat** query over all `Element` rows for the unit whose concrete type is `RevealGateElement` (child elements keep their own `unit` FK, so a flat query catches tab-nested gates without a recursive walk). A lesson whose *only* gate is inside a tab must still emit the triad, or that gate's button is never un-hidden. NEVER emit the setter or the pre-hide `<style>` without `reveal.js`: the pre-hide would then hide content under `<html class="reveal-armed">` with no engine to reveal it and no visible button (buttons stay server-`hidden`) — a fail-closed content swallow. The setter and pre-hide `<style>` live in base.html's purpose-built `{% block prepaint %}` (in `<head>`, before stylesheet links — the render-blocking pre-paint home); `lesson_unit.html` must **newly override** that block (today it overrides only `extra_css` / `extra_js`, and `extra_js` is deferred at end-of-body, which would reintroduce the flash). **`{% block prepaint %}` already exists in base.html (`base.html:43`, in `<head>` before the stylesheet `<link>`s), so `lesson_unit.html` overriding it is valid — no base.html change is needed.**
- **Runtime resilience (engine load-failure fail-safe).** Emission-time co-gating is not enough: if `reveal.js` fails to load or run at runtime (404, stale cache, missed `collectstatic` — a known failure mode in this codebase), the sync setter and render-blocking pre-hide still apply and content is swallowed with no engine to reveal it. So the inline prepaint setter also registers a **watchdog**: `reveal.js` sets `window.__revealBooted = true` at the top of its IIFE, and the inline script registers a `DOMContentLoaded` handler that removes `reveal-armed` if `!window.__revealBooted` (un-arming the pre-hide so all content shows). This is deterministic because a deferred `reveal.js` that loads runs *before* `DOMContentLoaded`; if it 404s it never boots and the watchdog reveals everything — matching the no-JS fallback (content visible, buttons stay server-`hidden`).

**Transfer** — `courses/transfer/{export,payloads,importer}.py`
- New key `reveal_gate` (snake_case) in all three lockstep registries: `SERIALIZERS` (serialize `{"label": ...}`, no media), `VALIDATORS` (empty media set), `BUILDERS` (create with `label`).
- **Export dispatch is automatic:** register `SERIALIZERS["reveal_gate"] = (RevealGateElement, _ser_reveal_gate)`; export resolves a `RevealGateElement` instance → `reveal_gate` via `_MODEL_TO_KEY`, which is derived from the `SERIALIZERS` `(model, fn)` tuples (`export.py:233`). So the single registration covers BOTH directions — no separate model→key map needed, exactly as `slide_break`/`gallery`/`table` work.
- **No `FORMAT_VERSION` bump** — additive new element type, matching how `gallery`/`table`/`slide_break` were added (only the tabs *nesting* fields bumped to v3; `parent`/`tab` already exist at v3 and cover a gate inside a tab).

**i18n** — `locale/{en,pl}/LC_MESSAGES/django.po`
- New strings: default label "Show more" / "Pokaż więcej"; group "Interactive" / "Interaktywne"; editor label + row caption + quiz-inactive note.

## Data flow

**Render (student, lesson).** Elements render as `.slide > section.lesson-block[data-element-id]` siblings (the gate is a real element that stays in the DOM — unlike `slidebreak`, which `partition_into_slides` consumes before render). `_lesson_article.html` wraps blocks in `.slide` for **every** lesson, including a single-slide one (`partition_into_slides` always yields at least one slide group), so the gating selectors and the `closest('[data-tab-panel], .slide')` scope apply in the common single-slide case, not only multi-slide. The gate's reveal scope is therefore naturally bounded by its enclosing `.slide`, or by `[data-tab-panel]` when nested in a tab (children there are `.tabs__child` direct siblings).

**Slideshow lessons.** A lesson with 2+ slides renders as a slideshow (`data-slideshow`; inactive `.slide`s are `display:none`; `slideshow.js` runs on the same lesson page as `reveal.js`). Gates compose cleanly with it: a gate's scope is its own `.slide`, so both the pre-hide and the reveal stay within one slide and never cross slide boundaries, and a gate in a not-yet-active slide is simply double-hidden until that slide is shown. Focus-move-on-reveal targets a block within the same `.slide`, so it does not fight slide navigation. This combination is exercised by the multi-slide test below.

**Reveal engine runtime.** Scope for a gate = `button.closest('[data-tab-panel], .slide')`. The gate's own scope-child ancestor is found by walking up until the parent is the scope container (works for both `.lesson-block` and `.tabs__child` — class-agnostic).

- **Pre-paint hide (no flash, no-JS-safe) — class-gated CSS, not JS-after-paint.** A synchronous inline `<script>` in the lesson page **`<head>`** adds the class `reveal-armed` to **`document.documentElement` (`<html>`)** — pinned to `<html>`, because a head script runs before `<article>` exists, so an article-root target would be `null` and silently disable gating. A **render-blocking** stylesheet (inline `<style>` in `<head>`, or a head-linked sheet — never a late/deferred sheet, or the flash returns) pre-hides every run. The `:has()` test must match a block's **own** rendered gate via the **direct child path** — a plain descendant `:has([data-reveal-gate])` would wrongly match a `.lesson-block` that *wraps a tabs element containing a nested gate*, hiding following slide content — and a revealed block is excluded with `:not(.reveal-shown)` so it keeps its natural display (no forced override):
  - `.reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block:not(.reveal-shown) { display: none; }`
  - tab analogue: `.reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child:not(.reveal-shown) { display: none; }`

  (Verified DOM: a slide-level gate button is `.slide > .lesson-block > .lesson-block__body > button[data-reveal-gate]`; a gate nested in a tab is `[data-tab-panel] > .tabs__child > button[data-reveal-gate]`.) Because the hide is gated on `reveal-armed`, **no-JS never hides** (the inline script never ran → all content visible) and the **editor preview never hides** (it emits no `reveal-armed` setter) — covering the nested-in-tab preview case too. `:has()` is required; a browser lacking it drops the rule and gates simply don't gate (graceful degradation, same net effect as no-JS). There is no JS-after-paint hide, hence no spoiler flash.

- **Init (`reveal.js`, deferred, idempotent via a `dataset` guard).** Remove the server-rendered `hidden` attribute from **every** `[data-reveal-gate]` button. Buttons inside still-hidden wrappers stay invisible with their wrapper; only the first gate's button shows (its wrapper is the run's anchor, never a hidden following-sibling). This is the single "who un-hides the buttons" mechanism — there is no per-gate button arming beyond wrapper visibility.

- **Click.** Compute the run = following-sibling wrappers up to **and including** the next gate's wrapper in scope. "Next gate" detection uses the same **own-element** direct-path test as the CSS (a wrapper is a gate iff its *own* element is a gate — `:scope > .lesson-block__body > [data-reveal-gate]` for a slide-level block, `:scope > [data-reveal-gate]` for a tab child), so a following tabs-block that merely *contains* a nested gate is NOT mistaken for the boundary. Reveal each run wrapper by adding the `reveal-shown` class — the pre-hide's `:not(.reveal-shown)` then stops matching it, so it keeps its natural display with no forced override — and dispatch a bubbling `libli:reveal` CustomEvent on each (so a gallery/tabs/math inside re-measures — established contract). Then **consume** the clicked gate's own wrapper by setting its `hidden` attribute (removing `reveal-shown` first if present), so the button disappears. **Focus management:** the consumed button held focus, so after reveal move focus to the newly-armed next gate button if one exists, else to the first revealed block (a container given `tabindex="-1"`) — so keyboard/AT users keep their place and the new content is discoverable. **Degenerate case:** if the run is empty AND there is no next gate (a trailing gate that reveals nothing), move focus to the enclosing scope container (`.slide` or `[data-tab-panel]`, given `tabindex="-1"`) rather than letting it fall to `<body>`. The next gate's already-un-hidden button is armed. Exactly one gate button is ever visible, because exactly one un-consumed gate wrapper is visible at a time.

**Transfer round-trip.** Export serializes `{label}`; import rebuilds the element with that label. A gate nested in a tab round-trips via the existing v3 `parent`/`tab` keys.

## Error handling

- **No-JS:** the inline `reveal-armed` class-setter never runs → the pre-hide CSS is inert → all content is visible; buttons stay server-`hidden` (reveal.js never un-hid them), so no dead buttons appear. Correct, accessible fallback.
- **Quiz units / lesson→quiz conversion:** the lesson page carries the `reveal-armed` setter, the pre-hide stylesheet, and `reveal.js`; the **quiz page carries none of them**. So a gate that ends up in a quiz (units are convertible via the settings/type-only edit, `views_manage.py:302`) never pre-hides and never un-hides its button — it gates nothing. **Zero data migration** — the gate is automatically inert. A converted gate leaves only a small empty `.lesson-block` (button server-`hidden`); fully suppressing that is an optional refinement, not required.
- **Print:** an `@media print` block neutralizes the pre-hide by matching the same direct-path selectors and forcing them visible (`.reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block, .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child { display: revert !important; }`) and hides the buttons (`[data-reveal-gate] { display: none !important; }`). Everything prints and no buttons show, no matter how far the student had revealed.
- **Auto-completion interaction (`progress.js`):** unit auto-completion marks an element "seen" only when it intersects the viewport (`static/courses/js/progress.js`); gated content, hidden pre-reveal, has no layout box and is not counted until revealed. **Intended behavior:** a student must reveal gated content for it to count toward auto-completion; the existing "Mark as done" affordance remains the fallback for a unit whose trailing gate is left unopened. This is a deliberate consequence of gating, not a regression.
- **Empty/degenerate cases:** a gate with no following siblings in scope (last element) simply reveals nothing and consumes itself on click — harmless. Two adjacent gates ⇒ clicking the first reveals up to and including the second (nothing between), arming it.
- **Nesting:** the gate holds no children, so "nesting a gate into itself" does not arise; it is only *nestable into tabs*. Tabs-in-tabs restrictions are unaffected.

## Testing

- **Model/form/builder:** create + save via `RevealGateElementForm`; label persists; blank label renders the default; `revealgate` accepted by `element_add`/`element_save`; nestability flag present.
- **Transfer:** export → import round-trip preserves `label`; a gate inside a tab round-trips (v3 nesting keys); no `FORMAT_VERSION` change (existing schema-version tests stay green).
- **Renderer:** button rendered with `hidden` + `data-reveal-gate`; label vs default text.
- **Palette gating:** the Interactive gate card is present in a lesson-unit editor and absent in a quiz-unit editor; the whole Interactive **group heading** is also absent in a quiz unit (no stray empty heading).
- **Triad emitted for a tab-only gate:** a lesson whose only gate is nested inside a tab still computes `has_reveal_gate == true` and emits the setter + pre-hide `<style>` + `reveal.js`, and that nested gate reveals correctly.
- **Single-slide collapse:** a gate in a single-slide (non-slideshow) lesson actually collapses its run — asserted at the renderer/e2e level, not only the multi-slide case.
- **Editor row:** the bespoke row renders its caption; the quiz-inactive flag shows when the gate is in a quiz unit.
- **Completion interaction:** gated (unrevealed) content is not marked "seen" by `progress.js`; revealing it lets it count — a regression-guard documenting the intended auto-completion behavior.
- **Engine-load-failure fail-safe:** with `reveal.js` blocked/404 (Playwright route intercept), the `DOMContentLoaded` watchdog removes `reveal-armed` and all content stays reachable — the failure an engine-loaded e2e cannot otherwise catch.
- **No-JS / print fallbacks:** a renderer/DOM assertion that, WITHOUT `reveal-armed` on `<html>`, no block is `display:none` (the no-JS invariant); the `@media print` reveal-all + button-hide rule is a review-checklist item where CSS media can't be unit-tested.
- **Gate nested in a tab:** a gate inside a tab gates only that tab's following `.tabs__child` siblings — and, critically, a tabs element that *contains* a nested gate does NOT hide following slide-level content (the direct-path `:has` regression guard for C1).
- **Focus (a11y):** after clicking a gate, focus lands on the newly-armed next gate button (or, for the last gate, on the first revealed block), not on `<body>`.
- **Slideshow lesson:** a gate in a multi-slide (slideshow) lesson reveals only within its active `.slide`; revealing does not switch slides or move focus across slides.
- **e2e (Playwright, drives the REAL click cascade per the `e2e-must-drive-real-ui` lesson):** two gates in a lesson → only the first button visible initially; clicking it reveals its run and arms the second button; clicking the second reveals the rest; verify the quiz page does NOT gate (all content visible, no button). Quiz-side fixtures build the gate in a **lesson** unit and then convert the unit to a quiz via the type-only edit (`views_manage.py:302`), since the palette forbids adding a gate directly in a quiz. Run focused e2e in the foreground (per the gallery-carousel build lesson); the controller owns the full-suite Definition-of-Done, including the i18n catalog tests since this slice adds translatable strings.

## Prior art to copy

- Thin element wiring end-to-end: `slidebreak` (`models.py`, `element_forms.py:179`, `_element_row.html:2`, `_add_menu.html:38`, transfer `_ser/_val/_build_slide_break`).
- Enhancer idiom + `libli:reveal`: `tabs.js`, `gallery.js`.
- DOM: `_lesson_article.html` (`.slide > section.lesson-block[data-element-id]`), `tabselement.html` (`[data-tab-panel] > .tabs__child`).
- Nesting substrate & container prior art: the tabs element slice.
