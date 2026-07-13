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
  where `Kind` is a nested `TextChoices`:
  `EXAMPLE="example"`, `NOTE="note"`, `TIP="tip"`, `WARNING="warning"`.
- `heading` — `CharField(max_length=120, blank=True)` — optional author override.
- `body` — `TextField(blank=True)`.
- `elements = GenericRelation(Element)` (cascade join-row cleanup, like every element).

`save()`:
1. Coerces an unknown/blank `kind` to `Kind.EXAMPLE` (defensive against a tampered
   import writing an out-of-range value; the DB has no enum constraint).
2. `self.body = sanitize_html(self.body)` (identical to Text/Spoiler).

`display_heading` property returns `self.heading` if set, else
`KIND_DEFAULT_HEADING[self.kind]`. `KIND_DEFAULT_HEADING` is a **module-level dict keyed
by kind value → `gettext_lazy` string** (Example/Note/Tip/Warning). Module-level
translatable dicts MUST use `gettext_lazy`, never `gettext` — an eager `gettext` at
import time freezes the label to the active language (the fill-blank i18n-lazy lesson).
Because `save()` guarantees `kind` is always a valid member, the dict lookup is total;
still, `display_heading` uses `KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING[Kind.EXAMPLE])`
so a not-yet-saved instance carrying a stray value never raises.

Register `"calloutelement"` in `ELEMENT_MODELS` (drives the GFK `limit_choices_to` and
the count assertion in `tests/test_transfer_schema.py`).

### Form — `CalloutElementForm(ModelForm)`
`courses/element_forms.py`, `fields = ["kind", "heading", "body"]`:
- `kind` renders as the model's choice `<select>`.
- `heading` a plain text input; its widget `placeholder` hints "leave blank to use the
  default for this kind."
- `body` the shared RTE textarea (`data-rte-source` attr), exactly like `SpoilerElementForm`.

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
its `body`, so its content must be scanned:
- Add a clause to the `has_math` OR-chain in `build_lesson_context`.
- Add the matching branch to `_element_has_math` (the per-element helper).
A `CalloutElement` whose `body` contains `\(…\)`/`\[…\]` must flip `has_math` true. This
is load-bearing: the editor preview loads `math.js` unconditionally, so a missing clause
only surfaces in a real lesson whose *only* math lives in a callout.

### Editor edit-form partial — `templates/courses/manage/editor/_edit_callout.html`
`_host_form.html` dynamically `{% include %}`s `_edit_<form_key>.html` for every type
with a standard edit control; a missing partial 500s (`TemplateDoesNotExist`) the moment
the palette card is clicked. The partial renders the three fields (kind `<select>`,
heading input, RTE body textarea) using the shared `.el-editor` / `.rte-toolbar`
components — same structure as `_edit_spoiler.html`. Field names in it must match the
form's field names. **No new editor JS and no `editor.html` `<script>` tag** — Callout,
like Spoiler, needs no client enhancer (the RTE toolbar is already wired globally).

### Palette card — `templates/courses/manage/_add_menu.html`
A card in the **Content** group (with Text/Image), type `callout`, label "Callout".
It is **not** wrapped in `{% if not nested %}` (Callout is nestable, so it must also
appear when `_add_menu.html` is included with `nested=True` inside a tab). The Content
group is not `unit_is_quiz`-gated, so the card is reachable in quiz units too.

### Nesting — `courses/builder.py`
Add `"callout"` to `NESTABLE_TYPE_KEYS`. The transfer key equals the form key
(`callout`), so **no** `_NESTABLE_FORM_KEY_ALIASES` entry is needed. The invariant
`NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` is preserved because `"callout"` is added to
`SERIALIZERS` too.

### Transfer trio
Mirror the **Text** element (a body-bearing type), NOT the bodyless `_ser_reveal_gate`:
- `SERIALIZERS["callout"]` → `_ser_callout(el)` returns
  `{"kind": el.kind, "heading": el.heading, "body": el.body}`.
- `VALIDATORS["callout"]` → `_val_callout(data, elid, media_kinds)`:
  strict `_exact_keys(data, {"kind","heading","body"}, "callout")`, `check_str` on all
  three fields, and `kind` must be one of the `Kind` values (else `TransferError`).
- `BUILDERS["callout"]` → `_build_callout(...)` constructs via `_clean_save` (the
  sanitize-on-save path), like `_build_text`.
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
- Migration adding `CalloutElement` (one model, no alterations to existing tables).
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
- **has_math** (isolated unit): a unit whose only math lives in a callout body flips
  `has_math` true and loads KaTeX; a callout with no math does not.
- **Authoring** (`test_callout_authoring.py`): GET/POST `manage_element_add` for
  `callout` → 200 (edit partial exists); in-tab add (POST with a tab parent) → 200.
- **Element count**: bump the `ELEMENT_MODELS` count assertion in the top-level
  `tests/test_transfer_schema.py`.
- **i18n**: catalog stays zero-fuzzy (`test_po_catalog_clean`); de-fuzz any entry
  `makemessages` fuzz-matches; EN `msgstr` stays empty; commit the `.mo`.
- **Screenshot pass** (baked into the styling task's DoD, NOT deferred): render all four
  kinds via the static Playwright harness (real `tokens.css` + `courses.css` + vendored
  KaTeX) in **light and dark**, confirm accent/tint/border/heading/icon are legible in
  both and math renders — per the fill-table dark-mode lesson (never defer the light+dark
  screenshot pass out of the styling task).

Full non-e2e suite green, `ruff check` + `ruff format --check` clean,
`makemigrations --check` and `manage.py check` clean.
