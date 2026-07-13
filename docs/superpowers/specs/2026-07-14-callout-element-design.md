# Callout element

A new **Callout** unit content element for libli: a framed, always-visible aside box
(Example / Note / Tip / Warning) holding rich text + math. Zero JavaScript, no server
endpoint. Its closest existing sibling is the **Spoiler** element — Callout is
essentially "Spoiler minus the collapse toggle, plus a `kind` and an optional heading."

## Purpose

Authors need a lightweight way to visually set apart a worked example, an incidental
note, a study tip, or a caution — the `.ks_example`-family boxes from the legacy Demo
Course. The element renders a colored, iconed frame around author-written rich content.
It is presentational only: it records no marks, reveals nothing, has no interactive
state, and needs no client script.

Design decisions locked during brainstorming:

- **Four kinds** — Example, Note, Tip, Warning — chosen from a dropdown. Each gets its
  own accent color + monochrome line icon.
- **Optional heading override.** Each kind supplies a localized default heading; the
  author may type a custom one. Empty → the kind's default.
- **Content group, not Interactive.** Callout is pure content, available in both lesson
  and quiz units (unlike the lesson-only Interactive widgets).
- **Nestable inside Tabs.**
- **Zero JS, no server endpoint** — like Spoiler; the static render *is* the behavior.

Non-goals (YAGNI): collapse/expand, per-kind custom colors, author-added icons,
dismissable state, nested callouts-within-callouts beyond the standard Tabs nesting.

## Architecture / components

### Data model — `CalloutElement(ElementBase)`
`courses/models.py`, mirroring `SpoilerElement`. Three fields:

- `kind` — `CharField(max_length=12, choices=Kind.choices, default=Kind.EXAMPLE)`,
  where `Kind` is a nested `TextChoices` **carrying a translatable label per member**
  (the codebase convention — cf. `ContentNode.Kind`, `MediaAsset.Kind`):
  `EXAMPLE = "example", _("Example")`, `NOTE = "note", _("Note")`,
  `TIP = "tip", _("Tip")`, `WARNING = "warning", _("Warning")`, using `gettext_lazy`.
  Without the second tuple element the author-facing `<select>` would render English
  labels even in a Polish UI.
- `heading` — `CharField(max_length=120, blank=True)` — optional author override.
- `body` — `TextField(blank=True)`.
- `elements = GenericRelation(Element)` (cascade join-row cleanup, like every element).

`save()`:
1. Coerces an unknown/blank `kind` to `Kind.EXAMPLE` (defensive against a tampered
   import writing an out-of-range value; the DB has no enum constraint).
2. `self.body = sanitize_html(self.body)` (identical to Text/Spoiler).

`display_heading` property returns `self.heading` if set, else
`KIND_DEFAULT_HEADING[self.kind]`. `KIND_DEFAULT_HEADING` is a **module-level dict keyed
by kind value string → `gettext_lazy` label**. Because the default heading and the
dropdown label coincide (both "Example"/"Note"/…), build the dict FROM the choice labels
so the strings are defined once: `KIND_DEFAULT_HEADING = {k.value: k.label for k in CalloutElement.Kind}`
(a `TextChoices` `.label` is the lazy string, so this stays translation-safe). If defined
as an explicit literal instead, it MUST use `gettext_lazy`, never eager `gettext` — an
eager call at import time freezes the label to the active language (the fill-blank
i18n-lazy lesson).

Because `save()` guarantees `kind` is always a valid member, the dict lookup is total;
still, `display_heading` guards with a **string** fallback key so a not-yet-saved instance
carrying a stray value never raises:
`KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])`. Do **not** write
a bare `Kind.EXAMPLE` inside the method body — `Kind` is a nested class, so an unqualified
reference resolves against module globals (undefined → `NameError`); use the value string
`"example"` (or `self.Kind.EXAMPLE`).

Register `"calloutelement"` in `ELEMENT_MODELS` (drives the GFK `limit_choices_to` and
the count assertion in `tests/test_transfer_schema.py`).

### Form — `CalloutElementForm(ModelForm)`
`courses/element_forms.py`, `fields = ["kind", "heading", "body"]`:
- `kind` — the choices come from the model field; see the editor partial below for how
  the `<select>` is actually rendered (with correct selected-state on edit).
- `heading` a plain text input. Its "leave blank to use the default for this kind"
  placeholder is written directly on the hand-written `<input>` in `_edit_callout.html`
  (mirroring how `_edit_spoiler.html` places its placeholder), NOT as a ModelForm widget
  attr — the editor renders the partial's markup, so a form-widget placeholder would be
  dead config.
- `body` — a `TextField`. Note the RTE wiring (`data-rte-source` / `rte-source` /
  `rte-toolbar`) is **not** a ModelForm widget: `SpoilerElementForm` declares no `widgets`
  at all, and the RTE attributes live on the hand-written `<textarea>` in the editor
  partial (`_edit_callout.html`), which the editor renders instead of the bound form
  field. So the `body` field's widget is effectively unused for rendering; the partial
  owns the RTE markup.

No custom `clean` is required — the model `save()` owns kind-coercion and body
sanitization, and blank heading/body are valid.

### Student template — `templates/courses/elements/calloutelement.html`
```
{% load i18n courses_extras %}
<aside class="callout callout--{{ el.kind }}">
  <div class="callout__header">
    {% include "courses/elements/_callout_icon.html" %}
    <span class="callout__heading">{{ el.display_heading }}</span>
  </div>
  <div class="el el--text callout__body">{{ el.body|sanitize }}</div>
</aside>
```
`_callout_icon.html` is a small partial that emits the correct inline SVG per
`el.kind` via `{% if el.kind == "example" %}…{% elif … %}` branches. Icons are
monochrome, `currentColor`, Lucide-style line SVGs carrying the shared `.icon`/
`.callout__icon` class (per the monochrome-SVG convention):
- Example → **book-open**, Note → info-circle, Tip → lightbulb,
  Warning → triangle-exclamation.

Always visible; the body renders math at page load (no hidden container to defeat
KaTeX auto-render).

### Styling — `courses/static/courses/css/courses.css`
A `.callout` base (border, radius, padding, left-rule, tinted background, header
flex row with icon + heading) plus four `.callout--<kind>` modifier classes. Each
modifier sets a single `--accent` custom property; the base derives the tint and edge
from it via `color-mix()`, so a kind is one line. Accents are **token-driven and must
resolve legibly in BOTH light and dark** — light and dark get their own `--accent`
values under the theme selector, mirroring how the fill-table CSS handles per-theme
border/tint. (Callout CSS lives in `courses.css` alongside `.el--text`, not
`editor.css`.)

### has_math gating — `courses/views.py`
`lesson_unit.html` loads KaTeX only `{% if has_math %}`. A callout can contain math in
its `body`, so its content must be scanned in BOTH context builders:
- **Lesson path:** add a clause to the `has_math` OR-chain in `build_lesson_context`,
  and add the matching branch to `_element_has_math` (the per-element helper).
- **Quiz path:** `build_quiz_context` computes its OWN `has_math` OR-chain (it inlines
  `MathElement`/`TextElement`/`_table_has_math`/`_gallery_has_math`/`_tabs_has_math`
  rather than calling `_element_has_math` for top-level elements). Because Callout is
  **quiz-available**, add an explicit top-level Callout clause there too — otherwise a
  math-only callout in a question-less quiz unit (where `bool(questions)` is false)
  never loads KaTeX. Nested-in-tabs callouts are already covered via
  `_tabs_has_math` → `_element_has_math`; only the top-level quiz case needs the new clause.

A `CalloutElement` whose `body` contains `\(…\)`/`\[…\]` must flip `has_math` true on both
paths. This is load-bearing: the editor preview loads `math.js` unconditionally, so a
missing clause only surfaces in a real lesson/quiz whose *only* math lives in a callout.

### Editor edit-form partial — `templates/courses/manage/editor/_edit_callout.html`
`_host_form.html` dynamically `{% include %}`s `_edit_<form_key>.html` for every type
with a standard edit control; a missing partial 500s (`TemplateDoesNotExist`) the moment
the palette card is clicked. The partial renders the three fields (kind `<select>`,
heading input, RTE body textarea) using the shared `.el-editor` / `.rte-toolbar`
components. `_edit_spoiler.html` is the mirror for the **heading input and RTE body
textarea** (hand-written `<input>` / `<textarea name="body" data-rte-source>`), but it
contains **no `<select>`**, so the kind dropdown has no direct Spoiler precedent —
specify it explicitly:

- Emit a hand-written `<select name="kind">` looping the field's choices, e.g.
  `{% for value, label in form.fields.kind.choices %}<option value="{{ value }}"
  {% if form.kind.value|stringformat:"s" == value|stringformat:"s" %}selected{% endif %}>
  {{ label }}</option>{% endfor %}`. **The selected-state is load-bearing on the edit
  path**: without it every edited callout's dropdown resets to the first option
  ("Example") regardless of its saved `kind`. `label` here is the translated choice
  label (from the `TextChoices`), satisfying the i18n requirement. (Rendering
  `{{ form.kind }}` directly is an acceptable alternative and also honors the translated
  labels + selected state — pick one; the hand-written form matches the partial's
  house style.)

Field names in it must match the form's field names. **No new editor JS and no
`editor.html` `<script>` tag** — Callout,
like Spoiler, needs no client enhancer (the RTE toolbar is already wired globally).

### Palette card — `templates/courses/manage/editor/_add_menu.html`
A card in the **Content** group (with Text/Image), type `callout`, label "Callout".
It is **not** wrapped in `{% if not nested %}` (Callout is nestable, so it must also
appear when `_add_menu.html` is included with `nested=True` inside a tab). The Content
group is not `unit_is_quiz`-gated, so the card is reachable in quiz units too.

**For the palette card specifically, mirror the unwrapped Content cards (Text / Image /
Table / Gallery), NOT Spoiler.** Spoiler is a poor model here: it lives in the
`{% if not unit_is_quiz %}`-gated **Interactive** group, its card *is* wrapped in
`{% if not nested %}`, and it is absent from `NESTABLE_TYPE_KEYS`. An implementer who
literally copied Spoiler's card would produce a quiz-hidden, nested-hidden card —
contradicting every placement requirement above. The nestable, unwrapped Content cards
are the correct model. (Spoiler remains the correct mirror for the *model / form /
transfer / save-sanitize* mechanics — just not for palette placement or nestability.)

Each palette card renders `<svg class="ic"><use href="#el-<type>"/></svg>`, so the card
needs a **new `<symbol id="el-callout">`** added to
`templates/courses/manage/_icon_sprite.html` (alongside `#el-text`, `#el-spoiler`, …).
Without it the card icon renders blank. This palette/outline sprite icon is **distinct**
from the four per-kind student-render icons in `_callout_icon.html` — a single glyph
representing the element type in the authoring UI (a framed-box or book-open glyph is a
reasonable choice).

### Nesting — `courses/builder.py`
Add `"callout"` to `NESTABLE_TYPE_KEYS`. The transfer key equals the form key
(`callout`), so **no** `_NESTABLE_FORM_KEY_ALIASES` entry is needed. The invariant
`NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` is preserved because `"callout"` is added to
`SERIALIZERS` too.

### Transfer trio
Mirror the **Text/Spoiler** body-bearing types, NOT the bodyless `_ser_reveal_gate`.
Match the exact registry/callable shapes used in the codebase:
- `SERIALIZERS["callout"] = (CalloutElement, _ser_callout)` — the registry maps each key
  to a `(Model, fn)` tuple, and every serializer takes `(concrete, media_ids)`. So
  `_ser_callout(concrete, media_ids)` returns
  `{"kind": concrete.kind, "heading": concrete.heading, "body": concrete.body}`.
- `VALIDATORS["callout"]` → `_val_callout(data, elid, media_kinds)`:
  strict `_exact_keys(data, ["kind", "heading", "body"], _("callout data"))` (a **list**
  literal, matching `_val_spoiler` and every other call in `payloads.py`), then
  `check_str(data["kind"], _("kind"))`,
  `check_str(data["heading"], _("heading"), max_length=120)` (mirror the model's 120 cap,
  as `_val_spoiler` does for `label`), and `check_str(data["body"], _("body"))`. Finally
  `kind` must be one of the `Kind` values (else `TransferError`). Use a translated `what`
  label throughout, mirroring `_val_spoiler`.
- `BUILDERS["callout"]` → `_build_callout(...)` constructs via `_clean_save` (the
  sanitize-on-save path), like `_build_text`/`_build_spoiler`.
No `FORMAT_VERSION` bump — adding a new element type is additive and does not change the
on-disk shape of existing types (the choose-and-confirm lesson).

### Remaining registration touch-points (kept in lockstep)
- `FORM_FOR_TYPE["callout"] = CalloutElementForm` (`element_forms.py`).
- `save_element` (`builder.py`) — the standard else-branch handles a plain ModelForm
  type; confirm `callout` routes through it (no special-casing needed).
- `element_add` / `element_save` type tuples (`views_manage.py`).
- `_EDITOR_TYPE_LABELS["callout"]` (`views_manage.py`) → "Callout".
- `_ELEMENT_LABELS` + `element_summary` (`courses_manage_extras.py`) → outline tile
  label "Callout" and a summary (e.g. the display heading or a body snippet).
- New `<symbol id="el-callout">` in `templates/courses/manage/_icon_sprite.html` — the
  palette/outline card glyph (distinct from the four per-kind student icons); a missing
  symbol renders the card icon blank.
- Migration adding `CalloutElement`. Note it will be a **two-operation** migration:
  appending `"calloutelement"` to `ELEMENT_MODELS` changes
  `Element.content_type`'s `limit_choices_to`, which Django records as a state-only
  `AlterField` on `Element` (no SQL) — exactly like the sibling
  `0039_spoilerelement_alter_element_content_type` /
  `0041_filltableelement_alter_element_content_type`. Expect
  `0042_calloutelement_alter_element_content_type` with both ops;
  `makemigrations --check` stays clean.
- i18n EN/PL for every new user-facing string (palette label, kind headings, editor
  labels, placeholder). Polish: Callout→"Ramka", Example→"Przykład", Note→"Notatka",
  Tip→"Wskazówka", Warning→"Uwaga".

## Data flow

**Authoring.** Author clicks the Content-group "Callout" card → `element_add` builds
`CalloutElementForm` → `_host_form.html` includes `_edit_callout.html`. Author picks a
kind, optionally types a heading, writes rich body → `element_save` → `save_element`
routes to the ModelForm path → `CalloutElement.save()` coerces kind + sanitizes body.
The editor preview re-renders the saved element via `render()`.

**Consumption (lesson).** `build_lesson_context` walks the unit's elements; the callout
clause flips `has_math` if its body has math. Each element renders through
`ElementBase.render()` → `calloutelement.html` → per-kind frame + `display_heading` +
sanitized body. KaTeX auto-render (loaded because `has_math`) renders the math in place.
In a quiz unit the callout renders through the same element path (content elements are
type-agnostic there).

**Nesting.** Inside a Tabs element, `_element_row.html` includes `_add_menu.html` with
`nested=True`; the unguarded Callout card resolves through `resolve_scope()`, which sees
form key `callout` ∈ `NESTABLE_TYPE_KEYS`, so the add succeeds (200). The child keeps its
`unit` FK and gains `parent`/`tab_id`.

**Transfer.** Export serializes `{kind, heading, body}`; import validates the exact keys
+ kind membership, then `_build_callout` re-saves through sanitization. Round-trip is
lossless.

## Error handling

- **Tampered/unknown `kind`** (import or direct DB write): `save()` coerces to
  `example`; `display_heading` additionally `.get()`-guards so an unsaved stray value
  never raises a `KeyError`. `_val_callout` rejects an out-of-range `kind` at import with
  a `TransferError` before it ever reaches the model.
- **XSS in body:** `sanitize_html` on save + `|sanitize` on render, identical to
  Text/Spoiler — no new sanitization surface.
- **Missing edit partial:** covered by an authoring test that GET/POSTs
  `manage_element_add` for `callout` and asserts 200 (a missing `_edit_callout.html`
  would 500 there).
- **Blank heading and/or blank body:** both valid; heading falls back to the kind
  default, body renders empty. No validation error.
- **In-tab add of a non-nestable type** is unchanged; Callout is explicitly nestable, and
  a test asserts the in-tab add returns 200.
- **Math-only-in-callout unit rendering blank math:** prevented by the `has_math` clause;
  guarded by an isolated-unit test (a unit whose sole math is inside a callout).

## Testing

Mirrors the Spoiler suite plus the kind/heading specifics:

- **Model** (`test_callout_model.py`): registered in `ELEMENT_MODELS`; `save()`
  sanitizes body; unknown/blank `kind` coerced to `example`; `display_heading` returns
  the override when set and each kind's localized default when blank.
- **Form**: valid save with kind+heading+body; blank heading/body accepted.
- **Render** (`test_callout_render.py` or view test): output carries
  `callout--<kind>` class, the correct per-kind icon, the resolved heading
  (override vs default), and the sanitized body; a `<script>` in body is stripped.
- **Transfer** (`test_callout_transfer.py`): `callout` present in
  `SERIALIZERS`/`VALIDATORS`/`BUILDERS`; round-trip preserves `{kind, heading, body}`;
  `_val_callout` rejects a bad `kind` and rejects extra/missing keys;
  `"callout" in NESTABLE_TYPE_KEYS`; `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)`.
- **CSS presence** (mirroring `tests/test_spoiler_css.py`): a cheap unit test asserting
  the `.callout` base rule and the four `.callout--<kind>` modifiers appear in
  `courses.css`, so a deleted/renamed styling hook fails a fast test rather than only the
  heavier screenshot pass (the Render test checks emitted HTML classes, not CSS presence).
- **has_math** (isolated unit): a unit whose only math lives in a callout body flips
  `has_math` true and loads KaTeX; a callout with no math does not. Cover **both** the
  lesson path and the top-level quiz path (question-less math-only-callout quiz).
- **Authoring** (`test_callout_authoring.py`): GET/POST `manage_element_add` for
  `callout` → 200 (edit partial exists); in-tab add (POST with a tab parent) → 200.
- **Element count**: the top-level `tests/test_transfer_schema.py` has
  `def test_element_models_lists_all_24_concrete_element_models(): assert len(ELEMENT_MODELS) == 24`.
  Adding Callout makes it 25 — bump BOTH the assertion value **and** the function name
  (`…all_25…`), or the name goes stale.
- **i18n**: catalog stays zero-fuzzy (`test_po_catalog_clean`); de-fuzz any entry
  `makemessages` fuzz-matches; EN `msgstr` stays empty; commit the `.mo`.
- **Screenshot pass** (baked into the styling task's DoD, NOT deferred): render all four
  kinds via the static Playwright harness (real `tokens.css` + `courses.css` + vendored
  KaTeX) in **light and dark**, confirm accent/tint/border/heading/icon are legible in
  both and math renders — per the fill-table dark-mode lesson (never defer the light+dark
  screenshot pass out of the styling task).

Full non-e2e suite green, `ruff check` + `ruff format --check` clean,
`makemigrations --check` and `manage.py check` clean.
