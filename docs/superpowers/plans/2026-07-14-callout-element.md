# Callout Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Callout" content element — a framed, always-visible aside (Example / Note / Tip / Warning) holding rich text + math — to the libli course authoring/consumption system.

**Architecture:** A new `CalloutElement(ElementBase)` concrete model mirroring `SpoilerElement` (a `label`/`body` + sanitizing `save()` element) but with a `kind` `TextChoices`, an optional `heading`, and a sanitized `body`. Zero JavaScript, no server endpoint: the static render *is* the behavior. It plugs into the existing GFK element system (`Element` join-row + per-type registries), the Content palette group, the Tabs nesting substrate, the transfer archive trio, and the `has_math` KaTeX-gating chains.

**Tech Stack:** Django 5.2 (server-rendered templates), Postgres, pytest, ruff, `nh3`-based `sanitize_html`, vendored KaTeX, Playwright (screenshot verification).

## Global Constraints

- **i18n-lazy:** every new user-facing string uses `{% trans %}`/`{% blocktrans %}` in templates and `gettext_lazy` (imported as `_`) in Python. Module-level translatable dicts/labels MUST use `gettext_lazy`, never eager `gettext` (an eager call freezes the label to the import-time language).
- **Zero-fuzzy .po invariant:** `tests/test_i18n_*.py::test_po_catalog_clean` requires the entire `.po` to have zero `#, fuzzy`. De-fuzz any entry `makemessages` fuzz-matches. The EN catalog uses empty `msgstr ""` passthrough (leave EN empty). `.mo` files are committed.
- **No `FORMAT_VERSION` bump:** adding a new element type is additive; `courses/transfer/schema.py:FORMAT_VERSION` stays `3`.
- **Palette placement:** Callout goes in the **Content** group of `templates/courses/manage/editor/_add_menu.html` (NOT the Interactive group). Its card is **not** wrapped in `{% if not nested %}` and the Content group is not `{% if not unit_is_quiz %}`-gated — so the card is reachable in quiz units and inside Tabs. Mirror the unwrapped Content cards (Text/Table/Gallery), NOT Spoiler.
- **Transfer/form/model key names:** form key `callout`, transfer key `callout` (they coincide → no `_NESTABLE_FORM_KEY_ALIASES` entry), model `calloutelement`, palette/label "Callout" (PL "Ramka").
- **Green DoD each task:** `uv run ruff check --fix <files> && uv run ruff format <files>`, and where models/migrations change also `uv run python manage.py makemigrations --check --dry-run` and `uv run python manage.py check`. Run pytest **serially** (`uv run pytest -q`, no `-n`) to confirm green — `-n auto` gives spurious xdist DB-setup failures on this machine.
- **Windows/uv:** `ruff`/`pytest`/`python` are not on PATH; always invoke via `uv run`.

---

### Task 1: `CalloutElement` model + migration + registry

**Files:**
- Modify: `courses/models.py` (add `CalloutElement` after `SpoilerElement` ~line 358; add `"calloutelement"` to `ELEMENT_MODELS` list ~line 259-284)
- Create: `courses/migrations/0042_calloutelement_alter_element_content_type.py` (generated)
- Test: `courses/tests/test_callout_model.py`
- Modify: `tests/test_transfer_schema.py` (bump the element-count test)

**Interfaces:**
- Produces: `CalloutElement(kind, heading, body)` with nested `CalloutElement.Kind` TextChoices (`EXAMPLE/NOTE/TIP/WARNING`), a `display_heading` property, module-level `courses.models.KIND_DEFAULT_HEADING` dict (`{value: lazy_label}`), and `"calloutelement"` in `ELEMENT_MODELS`.

`courses/models.py` already imports `gettext_lazy as _`, `sanitize_html`, `GenericRelation`, and defines `ElementBase`/`Element` — no new imports needed.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_model.py`:

```python
import pytest

from courses.models import ELEMENT_MODELS
from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_registered_in_element_models():
    assert "calloutelement" in ELEMENT_MODELS


def test_body_is_sanitized_on_save():
    el = CalloutElement.objects.create(
        kind="note", body="<script>alert(1)</script><p>ok</p>"
    )
    el.refresh_from_db()
    assert "<script>" not in el.body
    assert "ok" in el.body


def test_unknown_kind_coerced_to_example():
    el = CalloutElement.objects.create(kind="bogus", body="")
    el.refresh_from_db()
    assert el.kind == "example"


def test_blank_kind_coerced_to_example():
    el = CalloutElement.objects.create(kind="", body="")
    el.refresh_from_db()
    assert el.kind == "example"


def test_display_heading_uses_override_when_set():
    el = CalloutElement(kind="tip", heading="Pro tip")
    assert el.display_heading == "Pro tip"


def test_display_heading_falls_back_to_kind_default():
    # gettext_lazy under the EN catalog renders the English label.
    assert str(CalloutElement(kind="example").display_heading) == "Example"
    assert str(CalloutElement(kind="note").display_heading) == "Note"
    assert str(CalloutElement(kind="tip").display_heading) == "Tip"
    assert str(CalloutElement(kind="warning").display_heading) == "Warning"


def test_display_heading_survives_stray_unsaved_kind():
    # Not-yet-saved instance carrying a stray value must not raise.
    assert str(CalloutElement(kind="bogus").display_heading) == "Example"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_model.py -q`
Expected: FAIL (`ImportError: cannot import name 'CalloutElement'`).

- [ ] **Step 3: Add the model**

In `courses/models.py`, immediately after the `SpoilerElement` class (the one ending with the `sanitize_html(self.body)` `save`), add:

```python
class CalloutElement(ElementBase):
    """A framed, always-visible callout/aside (Example/Note/Tip/Warning) holding
    rich text + math. Zero JS, no server endpoint. Mirrors SpoilerElement minus the
    toggle, plus a `kind` and an optional heading. See the callout-element design doc."""

    class Kind(models.TextChoices):
        EXAMPLE = "example", _("Example")
        NOTE = "note", _("Note")
        TIP = "tip", _("Tip")
        WARNING = "warning", _("Warning")

    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EXAMPLE)
    heading = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        if self.kind not in self.Kind.values:
            self.kind = self.Kind.EXAMPLE
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)

    @property
    def display_heading(self):
        # String fallback key ("example"), NOT bare `Kind.EXAMPLE` — `Kind` is a nested
        # class and would resolve against module globals (undefined -> NameError).
        return self.heading or KIND_DEFAULT_HEADING.get(
            self.kind, KIND_DEFAULT_HEADING["example"]
        )


# Defined AFTER the class so it can read the choice labels; keyed by value string.
# `.label` is the lazy translation string, so this stays translation-safe.
KIND_DEFAULT_HEADING = {k.value: k.label for k in CalloutElement.Kind}
```

Then add `"calloutelement",` to the `ELEMENT_MODELS` list (after `"filltableelement",`).

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `0042_calloutelement_alter_element_content_type.py` with **two** operations — `CreateModel(CalloutElement)` and a state-only `AlterField` on `Element.content_type` (from the `ELEMENT_MODELS` change). This mirrors `0039`/`0041`.

- [ ] **Step 5: Bump the element-count test**

In `tests/test_transfer_schema.py`, the test currently reads:

```python
def test_element_models_lists_all_24_concrete_element_models():
    assert len(ELEMENT_MODELS) == 24
```

Rename the function and bump the value to `25` (both — the name embeds the count):

```python
def test_element_models_lists_all_25_concrete_element_models():
    assert len(ELEMENT_MODELS) == 25
```

- [ ] **Step 6: Run tests to verify pass**

Run: `uv run pytest courses/tests/test_callout_model.py tests/test_transfer_schema.py -q`
Expected: PASS. Then `uv run python manage.py makemigrations --check --dry-run` (no changes) and `uv run python manage.py check` (clean).

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix courses/models.py courses/tests/test_callout_model.py tests/test_transfer_schema.py
uv run ruff format courses/models.py courses/tests/test_callout_model.py tests/test_transfer_schema.py
git add courses/models.py courses/migrations/0042_calloutelement_alter_element_content_type.py courses/tests/test_callout_model.py tests/test_transfer_schema.py
git commit -m "feat(callout): CalloutElement model + migration + element registry"
```

---

### Task 2: `CalloutElementForm` + `FORM_FOR_TYPE`

**Files:**
- Modify: `courses/element_forms.py` (import `CalloutElement` near line 38; add `CalloutElementForm` near `SpoilerElementForm` ~line 202; add `"callout": CalloutElementForm` to `FORM_FOR_TYPE` ~line 1157)
- Test: `courses/tests/test_callout_form.py`

**Interfaces:**
- Consumes: `CalloutElement` (Task 1).
- Produces: `CalloutElementForm(ModelForm, fields=["kind", "heading", "body"])`; `FORM_FOR_TYPE["callout"]`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_callout_form.py`:

```python
import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import CalloutElementForm

pytestmark = pytest.mark.django_db


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["callout"] is CalloutElementForm


def test_valid_full_save():
    form = CalloutElementForm(
        data={"kind": "warning", "heading": "Careful", "body": "<p>x</p>"}
    )
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.kind == "warning"
    assert el.heading == "Careful"


def test_blank_heading_and_body_are_valid():
    form = CalloutElementForm(data={"kind": "tip", "heading": "", "body": ""})
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.heading == ""
    assert el.display_heading  # falls back to the kind default
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_form.py -q`
Expected: FAIL (`ImportError: cannot import name 'CalloutElementForm'`).

- [ ] **Step 3: Add the form**

In `courses/element_forms.py`, add the import alongside the other model imports (near line 38):

```python
from courses.models import CalloutElement
```

Add the form class near `SpoilerElementForm`:

```python
class CalloutElementForm(forms.ModelForm):
    class Meta:
        model = CalloutElement
        fields = ["kind", "heading", "body"]
```

Add to the `FORM_FOR_TYPE` dict (near the `"spoiler": SpoilerElementForm,` entry):

```python
    "callout": CalloutElementForm,
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest courses/tests/test_callout_form.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix courses/element_forms.py courses/tests/test_callout_form.py
uv run ruff format courses/element_forms.py courses/tests/test_callout_form.py
git add courses/element_forms.py courses/tests/test_callout_form.py
git commit -m "feat(callout): CalloutElementForm + FORM_FOR_TYPE registration"
```

---

### Task 3: Transfer trio (serializer / validator / builder) + nesting

**Files:**
- Modify: `courses/transfer/export.py` (add `_ser_callout` near `_ser_spoiler` ~line 104; add `"callout": (CalloutElement, _ser_callout)` to `SERIALIZERS` ~line 260; ensure `CalloutElement` is imported)
- Modify: `courses/transfer/payloads.py` (add `_val_callout` near `_val_spoiler` ~line 191; add `"callout": _val_callout` to `VALIDATORS` ~line 599)
- Modify: `courses/transfer/importer.py` (add `_build_callout` near `_build_spoiler` ~line 523; add `"callout": _build_callout` to `BUILDERS` ~line 689; ensure `CalloutElement` is imported)
- Modify: `courses/builder.py` (add `"callout"` to `NESTABLE_TYPE_KEYS` ~line 33-47)
- Test: `courses/tests/test_callout_transfer.py`

**Interfaces:**
- Consumes: `CalloutElement`, `CalloutElement.Kind` (Task 1); `_exact_keys`, `check_str`, `TransferError` from `courses.transfer.schema`; `_clean_save` from `courses.transfer.importer`.
- Produces: `SERIALIZERS["callout"]`, `VALIDATORS["callout"]`, `BUILDERS["callout"]`, `"callout" in NESTABLE_TYPE_KEYS`.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_transfer.py`:

```python
import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import CalloutElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_callout_registered_in_all_three_registries():
    assert "callout" in SERIALIZERS
    assert "callout" in VALIDATORS
    assert "callout" in BUILDERS


def test_callout_is_nestable_and_invariant_holds():
    # transfer key == form key, so no alias needed
    assert "callout" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip_preserves_fields():
    el = CalloutElement.objects.create(
        kind="warning", heading="Careful", body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data == {"kind": "warning", "heading": "Careful", "body": "<p>hi</p>"}
    # validator accepts it
    VALIDATORS["callout"](data, "e1", set())
    # builder reconstructs
    rebuilt, _refs = BUILDERS["callout"](data, {})
    assert rebuilt.kind == "warning"
    assert rebuilt.heading == "Careful"
    assert "hi" in rebuilt.body


def test_validator_rejects_bad_kind():
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "bogus", "heading": "", "body": ""}, "e1", set()
        )


def test_validator_rejects_missing_and_extra_keys():
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": "note", "body": ""}, "e1", set())  # no heading
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "", "body": "", "x": 1}, "e1", set()
        )


def test_validator_rejects_overlong_heading():
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "z" * 121, "body": ""}, "e1", set()
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_transfer.py -q`
Expected: FAIL (`"callout" not in SERIALIZERS`, etc.).

- [ ] **Step 3: Add the serializer**

In `courses/transfer/export.py`, ensure `CalloutElement` is imported with the other model imports, then add near `_ser_spoiler`:

```python
def _ser_callout(concrete, media_ids):
    return {
        "kind": concrete.kind,
        "heading": concrete.heading,
        "body": concrete.body,
    }
```

Add to `SERIALIZERS` (after the `"spoiler"` entry):

```python
    "callout": (CalloutElement, _ser_callout),
```

- [ ] **Step 4: Add the validator**

In `courses/transfer/payloads.py`, add near `_val_spoiler`. Import `CalloutElement.Kind` values via the model (top-of-function local import keeps module import graph unchanged, matching how `_val_switch_gate` imports `SENTINEL_TOKEN`):

```python
def _val_callout(data, elid, media_kinds):
    from courses.models import CalloutElement

    _exact_keys(data, ["kind", "heading", "body"], _("callout data"))
    check_str(data["kind"], _("kind"))
    check_str(data["heading"], _("heading"), max_length=120)
    check_str(data["body"], _("body"))
    if data["kind"] not in CalloutElement.Kind.values:
        _err(_("Element '%(el)s' has an unknown callout kind."), el=elid)
    return set()
```

Add to `VALIDATORS` (after the `"spoiler"` entry):

```python
    "callout": _val_callout,
```

- [ ] **Step 5: Add the builder**

In `courses/transfer/importer.py`, ensure `CalloutElement` is imported, then add near `_build_spoiler`:

```python
def _build_callout(data, assets):
    el = CalloutElement(
        kind=data.get("kind", "example"),
        heading=data.get("heading", ""),
        body=data["body"],
    )
    return _clean_save(el), ()
```

Add to `BUILDERS` (after the `"spoiler"` entry):

```python
    "callout": _build_callout,
```

- [ ] **Step 6: Add to `NESTABLE_TYPE_KEYS`**

In `courses/builder.py`, add `"callout"` inside the `NESTABLE_TYPE_KEYS` frozenset (place it after the existing Content keys like `"table"`/`"gallery"`). No `_NESTABLE_FORM_KEY_ALIASES` entry — the form key and transfer key are both `callout`.

- [ ] **Step 7: Run to verify pass**

Run: `uv run pytest courses/tests/test_callout_transfer.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/builder.py courses/tests/test_callout_transfer.py
uv run ruff format courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/builder.py courses/tests/test_callout_transfer.py
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/builder.py courses/tests/test_callout_transfer.py
git commit -m "feat(callout): transfer serializer/validator/builder + Tabs nestability"
```

---

### Task 4: Student render template + per-kind icon partial

**Files:**
- Create: `templates/courses/elements/calloutelement.html`
- Create: `templates/courses/elements/_callout_icon.html`
- Test: `courses/tests/test_callout_render.py`

**Interfaces:**
- Consumes: `CalloutElement` with `display_heading` (Task 1). `ElementBase.render()` renders `courses/elements/<model_name>.html` with `{"el": self}`.
- Produces: HTML `<aside class="callout callout--<kind>">` with a `.callout__icon` SVG, `.callout__heading`, and a sanitized `.callout__body`.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_render.py`:

```python
import pytest

from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_render_carries_kind_modifier_class_and_heading_default():
    html = CalloutElement(kind="warning", body="<p>hi</p>").render()
    assert "callout--warning" in html
    assert "Warning" in html  # default heading
    assert "hi" in html


def test_render_uses_heading_override():
    html = CalloutElement(kind="tip", heading="Pro tip", body="").render()
    assert "Pro tip" in html
    assert "callout--tip" in html


def test_render_selects_correct_icon_per_kind():
    # The four kinds emit four distinct icon markers; assert the book-open path
    # (Example) is present only for example, and the triangle (warning) for warning.
    example = CalloutElement(kind="example", body="").render()
    warning = CalloutElement(kind="warning", body="").render()
    assert "callout__icon" in example
    # book-open has a distinctive M12 7v14 spine; warning has the triangle path.
    assert "M12 7v14" in example
    assert "M12 7v14" not in warning


def test_render_sanitizes_body_on_output():
    el = CalloutElement.objects.create(kind="note", body="<script>x</script><p>ok</p>")
    html = el.render()
    assert "<script>" not in html
    assert "ok" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_render.py -q`
Expected: FAIL (`TemplateDoesNotExist: courses/elements/calloutelement.html`).

- [ ] **Step 3: Create the icon partial**

Create `templates/courses/elements/_callout_icon.html` (monochrome `currentColor` line SVGs, `class="callout__icon"`):

```html
{% if el.kind == "note" %}
  <svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
{% elif el.kind == "tip" %}
  <svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M15 14c.2-1 .7-1.7 1.5-2.5A4.5 4.5 0 1 0 7.5 11.5c.8.8 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>
{% elif el.kind == "warning" %}
  <svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
{% else %}
  <svg class="callout__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3z"/><path d="M21 18a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1h-5a4 4 0 0 0-4 4"/></svg>
{% endif %}
```

- [ ] **Step 4: Create the student template**

Create `templates/courses/elements/calloutelement.html`:

```html
{% load i18n courses_extras %}
<aside class="callout callout--{{ el.kind }}">
  <div class="callout__header">
    {% include "courses/elements/_callout_icon.html" %}
    <span class="callout__heading">{{ el.display_heading }}</span>
  </div>
  <div class="el el--text callout__body">{{ el.body|sanitize }}</div>
</aside>
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest courses/tests/test_callout_render.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/elements/calloutelement.html templates/courses/elements/_callout_icon.html courses/tests/test_callout_render.py
git commit -m "feat(callout): student render template + per-kind icon partial"
```

---

### Task 5: `has_math` KaTeX gating (lesson + nested + quiz)

**Files:**
- Modify: `courses/views.py` — `_element_has_math` (~line 150-171), `build_lesson_context` OR-chain (~line 269-283), `build_quiz_context` OR-chain (~line 755-766)
- Test: `courses/tests/test_callout_has_math.py`

**Interfaces:**
- Consumes: `CalloutElement` (Task 1); existing `has_math_delimiters` helper.
- Produces: a math-bearing callout flips `has_math` true on the lesson path, the nested-in-tabs path (via `_element_has_math`), and the top-level quiz path.

**Context:** `build_lesson_context` and `build_quiz_context` each inline their own `has_math` OR-chain (they do NOT call `_element_has_math` for top-level elements); `_element_has_math` is used by the `_tabs_has_math` recursion for nested elements. All three need a Callout clause. Mirror the existing `SpoilerElement` clauses (callout body carries math exactly like spoiler body).

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_has_math.py`. Use the project's existing fixtures for building a unit with elements — mirror `courses/tests/test_spoiler_*` or the has_math tests already in the suite for the exact fixture names. The behavioral contract to pin:

```python
import pytest

from courses.views import _element_has_math
from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_element_has_math_true_for_math_body():
    el = CalloutElement(kind="note", body=r"see \(x^2\) here")
    assert _element_has_math(el) is True


def test_element_has_math_false_for_plain_body():
    el = CalloutElement(kind="note", body="plain prose")
    assert _element_has_math(el) is False
```

Add two integration tests that build (a) a **lesson** unit whose ONLY element is a math-bearing callout and assert the rendered lesson page loads KaTeX (`has_math`), and (b) a **quiz** unit with NO questions whose only element is a math-bearing callout and assert the same. Follow the existing has_math integration tests' pattern for constructing the unit + `Element` join row and asserting on `build_lesson_context`/`build_quiz_context` output (or the rendered page containing the KaTeX/`math.js` script). If the suite has a helper like `make_unit_with_element`, reuse it; otherwise construct via `Element.objects.create(unit=..., content_object=...)` as the sibling tests do.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_has_math.py -q`
Expected: FAIL (`_element_has_math` returns False for the math-body callout — no clause yet).

- [ ] **Step 3: Add the `_element_has_math` clause**

In `courses/views.py`, inside `_element_has_math`, add after the `SpoilerElement` branch:

```python
    if isinstance(obj, CalloutElement):
        return has_math_delimiters(obj.body)
```

Ensure `CalloutElement` is importable in that scope (the function does local imports of `MathElement`/`TextElement`; add `from courses.models import CalloutElement` alongside them, or rely on the module-level import if `CalloutElement` is already imported at top of `views.py` like `SpoilerElement` is).

- [ ] **Step 4: Add the `build_lesson_context` clause**

In the `has_math = (...)` OR-chain in `build_lesson_context`, add a clause mirroring the SpoilerElement one:

```python
        or any(
            isinstance(el.content_object, CalloutElement)
            and has_math_delimiters(el.content_object.body)
            for el in elements
        )
```

- [ ] **Step 5: Add the `build_quiz_context` clause**

In the `has_math = (...)` OR-chain in `build_quiz_context`, add the same clause:

```python
        or any(
            isinstance(el.content_object, CalloutElement)
            and has_math_delimiters(el.content_object.body)
            for el in elements
        )
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest courses/tests/test_callout_has_math.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix courses/views.py courses/tests/test_callout_has_math.py
uv run ruff format courses/views.py courses/tests/test_callout_has_math.py
git add courses/views.py courses/tests/test_callout_has_math.py
git commit -m "feat(callout): has_math gating on lesson, nested, and quiz paths"
```

---

### Task 6: CSS styling (light + dark) + CSS-presence test + screenshot verification

**Files:**
- Modify: `courses/static/courses/css/courses.css` (add `.callout` block near `.el--table`/`.spoiler` rules)
- Test: `tests/test_callout_css.py`

**Interfaces:**
- Consumes: the `.callout` / `.callout--<kind>` / `.callout__header` / `.callout__icon` / `.callout__heading` / `.callout__body` classes emitted by Task 4's template.

- [ ] **Step 1: Write the failing CSS-presence test**

Create `tests/test_callout_css.py` (mirrors `tests/test_table_css.py`):

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_courses_css_defines_callout_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".callout",
        ".callout__header",
        ".callout__icon",
        ".callout__heading",
        ".callout__body",
        ".callout--example",
        ".callout--note",
        ".callout--tip",
        ".callout--warning",
    ]:
        assert cls in css, f"missing callout class: {cls}"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_callout_css.py -q`
Expected: FAIL (classes absent from `courses.css`).

- [ ] **Step 3: Add the CSS**

Append to `courses/static/courses/css/courses.css` (near the `.spoiler`/`.el--table` rules). Each kind sets a single `--callout-accent`; the base derives tint + edge via `color-mix()`. Provide per-theme accents so contrast holds in both. Starting accents (tune during Step 4's screenshot pass; prefer an existing semantic token from `tokens.css` where one fits):

```css
.callout {
  --callout-accent: var(--primary);
  border: 1px solid color-mix(in srgb, var(--callout-accent) 42%, transparent);
  border-left: 3px solid var(--callout-accent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--callout-accent) 10%, transparent);
  padding: 0.6rem 0.85rem 0.7rem;
  margin: 1rem 0;
}
.callout__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}
.callout__icon { width: 1.2rem; height: 1.2rem; flex: none; color: var(--callout-accent); }
.callout__heading { font-weight: 700; color: var(--callout-accent); }
.callout__body > :first-child { margin-top: 0; }
.callout__body > :last-child { margin-bottom: 0; }

.callout--example { --callout-accent: #2563c9; }
.callout--note    { --callout-accent: #5b6b7a; }
.callout--tip     { --callout-accent: #1f8a52; }
.callout--warning { --callout-accent: #c07a12; }

[data-theme="dark"] .callout--example { --callout-accent: #6ba3f5; }
[data-theme="dark"] .callout--note    { --callout-accent: #9fb2c2; }
[data-theme="dark"] .callout--tip     { --callout-accent: #52c98a; }
[data-theme="dark"] .callout--warning { --callout-accent: #e0a94a; }
```

(If `courses.css` uses a different dark-theme selector convention — e.g. `:root[data-theme="dark"]` — match whatever the existing spoiler/table rules use.)

- [ ] **Step 4: Screenshot verification (light + dark) — REQUIRED, do not defer**

Using the static Playwright harness technique (link the real `core/static/core/css/tokens.css` + `courses/static/courses/css/courses.css` + vendored KaTeX from a scratch HTML, toggle `data-theme`, run `renderMathInElement`), render all four kinds with a heading, a body containing inline `\(...\)` + display `\[...\]` math, and an override heading. Screenshot **light and dark**. Confirm: accent/tint/border/heading/icon are legible in both themes, math renders, and the four kinds are visually distinguishable. Adjust the accents in Step 3 until legible. Save the screenshots to the scratch dir (not committed) and record in the commit body that the light+dark pass was done.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_callout_css.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_callout_css.py
git commit -m "feat(callout): light+dark CSS (screenshotted both) + CSS-presence test"
```

---

### Task 7: Editor edit-form partial + palette card + sprite + labels + summary + authoring tests

**Files:**
- Create: `templates/courses/manage/editor/_edit_callout.html`
- Modify: `templates/courses/manage/editor/_add_menu.html` (Content group; add card after the `gallery` card, before the `{% if not nested %}` tabs card)
- Modify: `templates/courses/manage/_icon_sprite.html` (add `<symbol id="el-callout">`)
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS` ~line 750; the two element-type tuples ~line 893 and ~line 953)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` ~line 48; `element_summary` ~line 105)
- Test: `courses/tests/test_callout_authoring.py`

**Interfaces:**
- Consumes: `CalloutElementForm` (Task 2), the `_host_form.html` `{% include "courses/manage/editor/_edit_<type_key>.html" %}` mechanism, `element_add`/`element_save` views, `resolve_scope` (Task 3's nestability).
- Produces: a working add/edit/authoring path for `callout`, reachable top-level and in-tab.

**Context:** `_host_form.html` dynamically includes `_edit_<type_key>.html`; a missing partial 500s the moment the palette card is clicked. `_edit_spoiler.html` is the mirror for the heading input + RTE body textarea, but has **no `<select>`** — the kind dropdown is specified explicitly below with load-bearing selected-state.

- [ ] **Step 1: Write the failing authoring tests**

Create `courses/tests/test_callout_authoring.py`. Mirror the existing spoiler/filltable authoring tests for the exact fixtures (a course + unit + a logged-in author with edit rights, and the `manage_element_add` / `manage_element_save` URL names). Pin these contracts:

```python
import pytest

pytestmark = pytest.mark.django_db


def test_add_form_renders_200(author_client, lesson_unit):
    # GET the add form for a callout — proves _edit_callout.html exists (else 500).
    resp = author_client.post(
        reverse("courses:manage_element_add"),
        {"type": "callout", "unit": lesson_unit.pk},
    )
    assert resp.status_code == 200
    assert 'name="kind"' in resp.content.decode()


def test_in_tab_add_returns_200(author_client, lesson_unit, tabs_element_in_unit):
    # Adding a callout INSIDE a tab must resolve (callout in NESTABLE_TYPE_KEYS).
    resp = author_client.post(
        reverse("courses:manage_element_add"),
        {
            "type": "callout",
            "unit": lesson_unit.pk,
            "parent": tabs_element_in_unit.join_pk,
            "tab_id": tabs_element_in_unit.first_tab_id,
        },
    )
    assert resp.status_code == 200


def test_edit_form_preselects_stored_kind(author_client, callout_element_in_unit):
    # Editing a saved warning callout must mark <option value="warning" selected>.
    resp = author_client.get(
        reverse("courses:manage_element_edit", args=[callout_element_in_unit.join_pk])
    )
    html = resp.content.decode()
    assert 'value="warning"' in html
    assert "selected" in html
```

Adapt the fixture names / POST keys to the ones the existing `manage_element_add` tests use (check `tests/test_*spoiler*`/`test_filltable_*` or `courses/tests/` for the real signatures — `manage_element_add` is POST-dispatched on `request.POST["type"]`/`["unit"]`, per the fill-table lesson). The three behavioral asserts (add 200 + `name="kind"`, in-tab 200, edit preselects stored kind) are the contract; keep them.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_callout_authoring.py -q`
Expected: FAIL — 500 `TemplateDoesNotExist: .../_edit_callout.html` (and/or `callout` not in the allowed type tuples).

- [ ] **Step 3: Create the edit-form partial**

Create `templates/courses/manage/editor/_edit_callout.html`. The kind `<select>` MUST mark the stored value selected on edit (else every edited callout resets to "Example"):

```html
{% load i18n %}
<div class="el-editor el-editor--callout">
  <label>{% trans "Kind" %}
    <select name="kind">
      {% for value, label in form.fields.kind.choices %}
        <option value="{{ value }}"{% if form.kind.value|stringformat:"s" == value|stringformat:"s" %} selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>{% trans "Heading" %}
    <input type="text" name="heading" maxlength="120"
           value="{{ form.heading.value|default:'' }}"
           placeholder="{% trans 'Leave blank to use the default for this kind' %}">
  </label>
  {% for e in form.heading.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  <div class="rte-toolbar" data-rte-toolbar>
    <button type="button" class="rte-btn" data-cmd="bold" title="{% trans 'Bold' %}" aria-label="{% trans 'Bold' %}"><svg class="ic"><use href="#ed-bold"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="italic" title="{% trans 'Italic' %}" aria-label="{% trans 'Italic' %}"><svg class="ic"><use href="#ed-italic"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="underline" title="{% trans 'Underline' %}" aria-label="{% trans 'Underline' %}"><svg class="ic"><use href="#ed-underline"/></svg></button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h2" title="{% trans 'Heading 2' %}">H2</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h3" title="{% trans 'Heading 3' %}">H3</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h4" title="{% trans 'Heading 4' %}">H4</button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn" data-cmd="ul" title="{% trans 'Bullet list' %}" aria-label="{% trans 'Bullet list' %}"><svg class="ic"><use href="#ed-ul"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="ol" title="{% trans 'Numbered list' %}" aria-label="{% trans 'Numbered list' %}"><svg class="ic"><use href="#ed-ol"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="link" title="{% trans 'Link' %}" aria-label="{% trans 'Link' %}"><svg class="ic"><use href="#ed-link"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="blockquote" title="{% trans 'Quote' %}" aria-label="{% trans 'Quote' %}"><svg class="ic"><use href="#ed-quote"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="code" title="{% trans 'Code' %}" aria-label="{% trans 'Code' %}"><svg class="ic"><use href="#ed-code"/></svg></button>
  </div>
  <textarea name="body" class="rte-source" data-rte-source rows="6">{{ form.body.value|default:"" }}</textarea>
  {% for e in form.body.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Add the palette card**

In `templates/courses/manage/editor/_add_menu.html`, in the **Content** group `<div class="typemenu__group">`, add after the `gallery` card and before the `{% if not nested %}...tabs...{% endif %}` card (unwrapped — Callout is nestable):

```html
      <button type="button" class="typecard" data-add-type="callout"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-callout"/></svg>{% trans "Callout" %}</button>
```

- [ ] **Step 5: Add the sprite symbol**

In `templates/courses/manage/_icon_sprite.html`, add a `<symbol id="el-callout">` (a framed-box / callout glyph, 16×16, `currentColor`). Example:

```html
  <symbol id="el-callout" viewBox="0 0 16 16"><rect x="1.5" y="2.5" width="13" height="11" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.3"/><path fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" d="M1.5 5.5h13"/><circle cx="4" cy="4" r="0.7" fill="currentColor"/></symbol>
```

- [ ] **Step 6: Register editor label + type tuples**

In `courses/views_manage.py`:
- Add to `_EDITOR_TYPE_LABELS` (near `"spoiler": gettext_lazy("Spoiler"),`):

```python
    "callout": gettext_lazy("Callout"),
```

- Add `"callout"` to BOTH element-type allow-tuples (the `element_add` list ~line 893 and the `element_save` list ~line 953), placing it next to `"spoiler"`/`"gallery"` in each.

- [ ] **Step 7: Register outline label + summary**

In `courses/templatetags/courses_manage_extras.py`:
- Add to `_ELEMENT_LABELS` (near `"spoilerelement": _("Spoiler"),`):

```python
    "calloutelement": _("Callout"),
```

- Add to `element_summary` (near the `SpoilerElement` branch):

```python
    if name == "CalloutElement":
        return el.display_heading
```

(ensure `CalloutElement` is importable where `element_summary` resolves `name`/`el`; it dispatches on `type(el).__name__`, so no new import if it uses `name` string comparison — match the sibling branches' style.)

- [ ] **Step 8: Run to verify pass**

Run: `uv run pytest courses/tests/test_callout_authoring.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_callout_authoring.py
uv run ruff format courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_callout_authoring.py
git add templates/courses/manage/editor/_edit_callout.html templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_callout_authoring.py
git commit -m "feat(callout): editor partial + palette card + sprite + labels + summary"
```

---

### Task 8: i18n (Polish translations) + full-suite green

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Modify: `locale/en/LC_MESSAGES/django.po` (+ `.mo`) — new msgids appear with empty `msgstr` (EN passthrough)

**Interfaces:**
- Consumes: every `{% trans %}` / `gettext_lazy` string added in Tasks 1–7 ("Callout", "Example", "Note", "Tip", "Warning", "Kind", "Heading", "Leave blank to use the default for this kind", "callout data", "kind", "heading", "body", the unknown-kind error).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en` (or the project's usual invocation — check `Makefile`/`docs/development/` for the exact locales/flags).

- [ ] **Step 2: Translate to Polish**

In `locale/pl/LC_MESSAGES/django.po`, fill Polish `msgstr` for the new msgids:
- "Callout" → "Ramka"
- "Example" → "Przykład"
- "Note" → "Notatka"
- "Tip" → "Wskazówka"
- "Warning" → "Uwaga"
- "Kind" → "Rodzaj"
- "Heading" → "Nagłówek"
- "Leave blank to use the default for this kind" → "Pozostaw puste, aby użyć domyślnego nagłówka dla tego rodzaju"
- "callout data" → "dane ramki"
- "kind" → "rodzaj"
- "heading" → "nagłówek"
- "body" → (reuse existing translation if the msgid already exists; otherwise "treść")
- "Element '%(el)s' has an unknown callout kind." → "Element „%(el)s” ma nieznany rodzaj ramki."

**De-fuzz:** remove any `#, fuzzy` flag `makemessages` attached to a new or nearby entry (the repo forbids all fuzzy entries). Leave the EN catalog's new `msgstr` empty.

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`

- [ ] **Step 4: Run the i18n + full suite**

Run:
```
uv run pytest tests/test_i18n_notes.py -q   # or whichever module holds test_po_catalog_clean
uv run pytest -q
```
Expected: `test_po_catalog_clean` passes (zero fuzzy) and the full non-e2e suite is green (now 25 element models).

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo
git commit -m "i18n(callout): Polish translations for the Callout element"
```

---

## Definition of Done (whole feature)

- `uv run pytest -q` (serial) green — all new `courses/tests/test_callout_*.py` + `tests/test_callout_css.py` + bumped count test pass.
- `uv run ruff check` and `uv run ruff format --check` clean.
- `uv run python manage.py makemigrations --check --dry-run` and `uv run python manage.py check` clean.
- `test_po_catalog_clean` green (zero fuzzy; EN empty; `.mo` committed).
- Light + dark screenshot pass done in Task 6 (not deferred).
- Manual smoke (optional but recommended): add a Callout of each kind in a real lesson AND inside a Tab, edit one and confirm the kind dropdown preserves its value, view as a student in light + dark.

## Self-Review Notes

- **Spec coverage:** model+Kind+display_heading+coercion (T1), form (T2), transfer trio + nestability + no-alias + no FORMAT_VERSION bump (T3), student render + per-kind icon (T4), has_math on all three paths (T5), light/dark CSS + CSS-presence test + screenshot (T6), editor partial + palette Content-group card + sprite + editor/outline labels + summary + authoring/in-tab/edit-preselect tests (T7), i18n EN/PL + zero-fuzzy + .mo + count test (T1/T8). All spec sections mapped.
- **Type consistency:** `CalloutElement.Kind` values `example/note/tip/warning`; form key/transfer key/`data-add-type` all `callout`; model name `calloutelement`; `KIND_DEFAULT_HEADING` keyed by value string; `display_heading` used identically in render (T4) and summary (T7).
- **Known adaptation points flagged for the implementer** (not placeholders — real fixture-name lookups): T5's integration-test fixtures and T7's authoring-test fixtures/URL-arg names must match the existing spoiler/filltable test helpers; the plan pins the behavioral asserts and points at the sibling tests to copy the harness from.
