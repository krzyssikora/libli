# Choose & confirm gate (`SwitchGateElement`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Choose & confirm" interactive content element — an inline cycling "Choose ▾" widget whose server-checked correct choice reveals the following lesson siblings — completing the reveal-gate family (slice 3 after reveal-gate PR #99 and fillgate PR #104).

**Architecture:** Mirror the shipped `FillGateElement` substrate at every touch-point (model, form, server check endpoint, transfer trio, taking-view context flags, prepaint watchdog, reveal-cascade reuse), diverging only where the widget is genuinely new: a single-token stem with a separate variable-length **options list** (a plain non-Model form reading `getlist("option")` + an `answer` radio index), a client-side **cycler** (`<button data-switchgate-cycler>` toggling `hidden` option spans in a ring), and a **soft pk lookup** in the endpoint (200 on miss, not fillgate's 404).

**Tech Stack:** Django (server-rendered templates, generic-relation element models, JSONField), vanilla JS IIFE enhancers (no framework), KaTeX for math, pytest + pytest-django + Playwright for tests, ruff for lint/format. Tooling runs via **`uv run`** (bare `pytest`/`ruff` are not on PATH).

## Global Constraints

- **Three key namespaces (keep distinct):** type key `switchgateelement` · form key `switchgate` · transfer key `switch_gate`.
- **Stem sentinel:** reuse `courses.fillblank.SENTINEL` (U+FFFF `￿`); the single placeholder token is `￿0￿`. Author-facing marker is the literal `{{choice}}`.
- **Option sanitization:** reuse `courses.sanitize.sanitize_cell` (allowlist `strong,b,em,i,u,br` + balanced LaTeX `\(...\)`/`\[...\]` protection) — the same allowlist table cells use.
- **No marks / no per-student state:** this is a lesson reveal, not a quiz.
- **Fail-open invariant:** content must never be permanently trapped; the `lesson_unit.html` prepaint watchdog disarms the pre-hide if `window.__switchGateBooted` is falsy at `DOMContentLoaded`.
- **FORMAT_VERSION is NOT bumped.** The spec called for a 3→4 bump, but the codebase shows fillgate was added at version 3 with **no** bump (a new type key is backward-additive; an older importer rejects an unknown transfer key regardless of version). This plan follows the fillgate precedent and leaves `FORMAT_VERSION = 3`. Transfer tests assert a round-trip at the current version, not `== 4`. *(Deliberate, documented deviation from the reviewed spec.)*
- **i18n:** every user-facing string wrapped for EN/PL; no translatable strings are removed.
- **Testing runs:** `uv run pytest <path>`; lint `uv run ruff check` and `uv run ruff format --check`.
- **CSS lives in `core/static/core/css/app.css`** (single stylesheet, NOT under `courses/static/`); fillgate rules are at ~lines 906-974, reveal-gate at ~858-904.

---

### Task 1: Model + migration + registration

**Files:**
- Modify: `courses/models.py` (add `SwitchGateElement`, add `"switchgateelement"` to `ELEMENT_MODELS`)
- Create: `courses/migrations/0038_switchgateelement.py`
- Test: `courses/tests/test_switchgate_model.py`

**Interfaces:**
- Produces: `SwitchGateElement(ElementBase)` with fields `stem: TextField`, `options: JSONField(list[str])`, `answer: IntegerField`, `elements: GenericRelation`, and a `render()` returning the rendered student template. Options are sanitized in `save()` via `sanitize_cell`.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_model.py`:

```python
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import SwitchGateElement, Element, ELEMENT_MODELS

pytestmark = pytest.mark.django_db


def test_switchgate_registered_in_element_models():
    assert "switchgateelement" in ELEMENT_MODELS


def test_switchgate_defaults():
    el = SwitchGateElement.objects.create(stem="", options=[], answer=0)
    assert el.options == []
    assert el.answer == 0


def test_switchgate_save_sanitizes_options():
    el = SwitchGateElement.objects.create(
        stem="pick ﻿",  # arbitrary text
        options=["<b>ok</b>", "<script>x</script>bad", "\\(+\\)"],
        answer=0,
    )
    el.refresh_from_db()
    assert el.options[0] == "<b>ok</b>"          # allowed tag kept
    assert "<script>" not in el.options[1]        # script stripped
    assert "bad" in el.options[1]                 # text preserved
    assert el.options[2] == "\\(+\\)"            # LaTeX preserved


def test_switchgate_render_uses_template_and_eid():
    el = SwitchGateElement.objects.create(stem="￿0￿", options=["a", "b"], answer=1)
    ct = ContentType.objects.get_for_model(SwitchGateElement)
    # a bare render() with no join row must not raise and must produce markup
    html = el.render()
    assert "data-switchgate" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'SwitchGateElement'`.

- [ ] **Step 3: Add the model** — in `courses/models.py`, immediately after the `FillGateElement` class (~line 497). `sanitize_cell` is already imported at the top (line 24: `from courses.sanitize import sanitize_cell`):

```python
class SwitchGateElement(ElementBase):
    """A 'Choose & confirm' gate: a reveal gate whose trigger is an inline cycling
    'Choose ▾' widget. A correct (server-checked) choice reveals the following
    siblings. Records no marks. `stem` holds the ￿0￿ single-token stem (the cycler
    position); `options` is the sanitized list[str] of choice HTML fragments;
    `answer` is the 0-based index of the correct option. See the design doc."""

    stem = models.TextField(blank=True)
    options = models.JSONField(default=list)
    answer = models.IntegerField(default=0)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.options = [sanitize_cell(o or "") for o in (self.options or [])]
        super().save(*args, **kwargs)

    def render(self):
        from django.template.loader import render_to_string

        join = self.elements.order_by("pk").first()
        return render_to_string(
            "courses/elements/switchgateelement.html",
            {"el": self, "eid": join.pk if join else 0},
        )
```

- [ ] **Step 4: Register in `ELEMENT_MODELS`** — in `courses/models.py`, add to the list (~line 279, after `"fillgateelement"`):

```python
    "fillgateelement",
    "switchgateelement",
]
```

- [ ] **Step 5: Create the migration** — `courses/migrations/0038_switchgateelement.py`. Model the `AlterField` `limit_choices_to` on the FULL current model list (copy it verbatim from `0037_fillgateelement.py`'s AlterField and append `"switchgateelement"`):

```python
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("courses", "0037_fillgateelement"),
    ]

    operations = [
        migrations.CreateModel(
            name="SwitchGateElement",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stem", models.TextField(blank=True)),
                ("options", models.JSONField(default=list)),
                ("answer", models.IntegerField(default=0)),
            ],
            options={"abstract": False},
        ),
        # AlterField: copy the exact limit_choices_to model__in list from
        # 0037_fillgateelement.py and append "switchgateelement".
        migrations.AlterField(
            model_name="element",
            name="content_type",
            field=models.ForeignKey(
                limit_choices_to={"model__in": [
                    # <<< paste the full list from 0037 here, then add: >>>
                    "switchgateelement",
                ]},
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
    ]
```

Note to implementer: open `courses/migrations/0037_fillgateelement.py`, copy its `AlterField` `limit_choices_to["model__in"]` list literally, and append `"switchgateelement"`. Then run `uv run python manage.py makemigrations --check --dry-run courses` to confirm no *additional* migration is needed (the hand-written one matches the model state).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_model.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0038_switchgateelement.py courses/tests/test_switchgate_model.py
git commit -m "feat(switchgate): SwitchGateElement model, migration, registration"
```

---

### Task 2: Stem token helper (`courses/switchgate.py`)

**Files:**
- Create: `courses/switchgate.py`
- Test: `courses/tests/test_switchgate_stem.py`

**Interfaces:**
- Produces:
  - `SENTINEL_TOKEN: str` = `"￿0￿"`
  - `CHOICE_MARKER: str` = `"{{choice}}"`
  - `class SwitchGateError(ValueError)`
  - `parse_stem(clean: str) -> str` — replaces exactly one `{{choice}}` with `SENTINEL_TOKEN`; raises `SwitchGateError` on zero or ≥2 markers. Returns the token-stem.
  - `to_author_stem(token_stem: str) -> str` — inverse (`SENTINEL_TOKEN` → `{{choice}}`), for the edit form.
  - `render_stem(token_stem: str, widget_html: str) -> SafeString` — splits the token-stem on `SENTINEL_TOKEN` and joins `mark_safe(before) + widget_html + mark_safe(after)`.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_stem.py`:

```python
import pytest
from courses import switchgate


def test_parse_stem_replaces_single_marker():
    assert switchgate.parse_stem("pick {{choice}} now") == "pick ￿0￿ now"


def test_parse_stem_rejects_zero_markers():
    with pytest.raises(switchgate.SwitchGateError):
        switchgate.parse_stem("no marker here")


def test_parse_stem_rejects_two_markers():
    with pytest.raises(switchgate.SwitchGateError):
        switchgate.parse_stem("{{choice}} and {{choice}}")


def test_to_author_stem_roundtrips():
    token = switchgate.parse_stem("a {{choice}} b")
    assert switchgate.to_author_stem(token) == "a {{choice}} b"


def test_render_stem_splices_widget():
    out = switchgate.render_stem("a ￿0￿ b", "<WIDGET>")
    assert out == "a <WIDGET> b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_stem.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.switchgate'`.

- [ ] **Step 3: Write the helper** — `courses/switchgate.py`:

```python
"""Single-token stem helper for the Choose & confirm gate (SwitchGateElement).

The stem carries exactly one placeholder marking where the inline cycler renders.
Authors type the literal ``{{choice}}``; it is stored as the ￿0￿ sentinel token
(reusing courses.fillblank.SENTINEL), and split back out at render time. Unlike
fillblank, the token carries no answer data — the options live in a separate field.
"""

from django.utils.safestring import SafeString, mark_safe

from courses import fillblank

SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL
CHOICE_MARKER = "{{choice}}"


class SwitchGateError(ValueError):
    """Raised when the stem does not contain exactly one {{choice}} marker."""


def parse_stem(clean: str) -> str:
    """Return the token-stem: exactly one {{choice}} replaced by SENTINEL_TOKEN."""
    count = clean.count(CHOICE_MARKER)
    if count != 1:
        raise SwitchGateError(f"expected exactly one {CHOICE_MARKER}, found {count}")
    return clean.replace(CHOICE_MARKER, SENTINEL_TOKEN)


def to_author_stem(token_stem: str) -> str:
    """Inverse of parse_stem, for populating the edit form."""
    return (token_stem or "").replace(SENTINEL_TOKEN, CHOICE_MARKER)


def render_stem(token_stem: str, widget_html: str) -> SafeString:
    """Split the token-stem on the sentinel and splice the widget in its place.

    The stem segments are author HTML already sanitised at clean() time, so they
    are marked safe; widget_html is built by the render tag (already safe)."""
    before, _, after = (token_stem or "").partition(SENTINEL_TOKEN)
    return mark_safe(before) + mark_safe(widget_html) + mark_safe(after)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_stem.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/switchgate.py courses/tests/test_switchgate_stem.py
git commit -m "feat(switchgate): single-token stem helper"
```

---

### Task 3: Form (`SwitchGateElementForm`)

**Files:**
- Modify: `courses/element_forms.py` (add the form + `FORM_FOR_TYPE` entry + import)
- Test: `courses/tests/test_switchgate_form.py`

**Interfaces:**
- Consumes: `SwitchGateElement` (Task 1); `courses.switchgate` (Task 2); `sanitize_html`, `sanitize_cell`, `fillblank` (already available in `element_forms.py`).
- Produces: `SwitchGateElementForm(forms.Form)` — a plain form accepting `instance=` and exposing `save(commit=True) -> SwitchGateElement`. Reads options from `self.data.getlist("option")` and the correct index from `self.data.get("answer")`. Provides `option_rows()` → list of `{"value": str, "checked": bool}` padded to ≥6 rows for the editor partial. Registered as `FORM_FOR_TYPE["switchgate"]`.

Validation rules (from spec Error handling): sanitize each option first; drop **trailing** empty rows; reject if any remaining option is empty, if fewer than 2 options remain, if the stem lacks exactly one `{{choice}}`, if no/multiple correct selection, or if `answer` is out of range.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_form.py`:

```python
import pytest
from django.http import QueryDict
from courses.element_forms import SwitchGateElementForm, FORM_FOR_TYPE
from courses.models import SwitchGateElement

pytestmark = pytest.mark.django_db


def _post(stem, options, answer):
    qd = QueryDict(mutable=True)
    qd["stem"] = stem
    for o in options:
        qd.appendlist("option", o)
    if answer is not None:
        qd["answer"] = str(answer)
    return qd


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["switchgate"] is SwitchGateElementForm


def test_valid_form_saves_token_stem_options_answer():
    form = SwitchGateElementForm(data=_post("pick {{choice}} here", ["a", "b", "c"], 2))
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.stem == "pick ￿0￿ here"
    assert el.options == ["a", "b", "c"]
    assert el.answer == 2


def test_trailing_empty_options_ignored():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b", "", ""], 1))
    assert form.is_valid(), form.errors
    assert form.save().options == ["a", "b"]


def test_interior_empty_option_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "", "b"], 2))
    assert not form.is_valid()


def test_fewer_than_two_options_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a"], 0))
    assert not form.is_valid()


def test_stem_without_marker_rejected():
    form = SwitchGateElementForm(data=_post("no marker", ["a", "b"], 0))
    assert not form.is_valid()
    assert "stem" in form.errors


def test_answer_out_of_range_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b"], 5))
    assert not form.is_valid()


def test_missing_answer_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b"], None))
    assert not form.is_valid()


def test_option_sanitized_to_empty_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["<script>x</script>", "b", "c"], 1))
    # first option sanitises to "" (script stripped, no text) -> interior empty -> reject
    assert not form.is_valid()


def test_edit_prefills_author_stem_and_rows():
    el = SwitchGateElement.objects.create(stem="a ￿0￿ b", options=["p", "q"], answer=1)
    form = SwitchGateElementForm(instance=el)
    assert form.initial["stem"] == "a {{choice}} b"
    rows = form.option_rows()
    assert rows[0] == {"value": "p", "checked": False}
    assert rows[1] == {"value": "q", "checked": True}
    assert len(rows) >= 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'SwitchGateElementForm'`.

- [ ] **Step 3: Add the form** — in `courses/element_forms.py`. Add the import near the other model imports (line ~19, alongside `FillGateElement`): `from courses.models import SwitchGateElement` (extend the existing import line). Add `from courses import switchgate` near the `fillblank` import. Then add the form class after `FillGateElementForm` (~line 224):

```python
_MIN_OPTIONS = 2
_MIN_ROWS = 6


class SwitchGateElementForm(forms.Form):
    """Plain (non-Model) form for the Choose & confirm gate. Options are a
    variable-length list posted under the repeated field name ``option``; the
    correct one is the ``answer`` radio's 0-based row index."""

    stem = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance if instance is not None else SwitchGateElement()
        self._token_stem = ""
        self._options = []
        self._answer = 0
        super().__init__(*args, **kwargs)
        if instance is not None and instance.pk:
            self.initial["stem"] = switchgate.to_author_stem(instance.stem)

    def _posted_options(self):
        data = self.data
        return data.getlist("option") if hasattr(data, "getlist") else []

    def option_rows(self):
        """Rows for the editor partial: existing options (or blanks), padded to
        at least _MIN_ROWS, with the answer index marked checked."""
        opts = list(self.instance.options or [])
        answer = self.instance.answer if self.instance.pk else -1
        n = max(_MIN_ROWS, len(opts) + 1)
        rows = []
        for i in range(n):
            rows.append({"value": opts[i] if i < len(opts) else "", "checked": i == answer})
        return rows

    def clean(self):
        cleaned = super().clean()
        # --- stem: sanitise, strip stray sentinels, require exactly one {{choice}}
        raw_stem = cleaned.get("stem", "") or ""
        clean_stem = fillblank.strip_sentinel(sanitize_html(raw_stem))
        try:
            self._token_stem = switchgate.parse_stem(clean_stem)
        except switchgate.SwitchGateError:
            self.add_error("stem", _("Mark the choice position with {{choice}} exactly once."))
        # --- options: sanitise, drop trailing blanks, reject interior blanks / <2
        raw = [sanitize_cell(o or "") for o in self._posted_options()]
        while raw and raw[-1] == "":
            raw.pop()
        if any(o == "" for o in raw):
            self.add_error(None, _("Options cannot be empty."))
        elif len(raw) < _MIN_OPTIONS:
            self.add_error(None, _("Add at least two options."))
        self._options = raw
        # --- answer: integer, in range
        raw_answer = self.data.get("answer") if hasattr(self.data, "get") else None
        try:
            self._answer = int(raw_answer)
        except (TypeError, ValueError):
            self.add_error(None, _("Select the correct option."))
            self._answer = -1
        if self._options and not (0 <= self._answer < len(self._options)):
            self.add_error(None, _("Select the correct option."))
        return cleaned

    def save(self, commit=True):
        self.instance.stem = self._token_stem
        self.instance.options = self._options
        self.instance.answer = self._answer
        if commit:
            self.instance.save()
        return self.instance
```

Add to `FORM_FOR_TYPE` (~line 847, after the `"fillgate"` entry):

```python
    "fillgate": FillGateElementForm,
    "switchgate": SwitchGateElementForm,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_form.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/tests/test_switchgate_form.py
git commit -m "feat(switchgate): SwitchGateElementForm (options list + answer index)"
```

---

### Task 4: Server check endpoint (`switchgate_check`)

**Files:**
- Modify: `courses/views.py` (add `switchgate_check`, import `SwitchGateElement`)
- Modify: `courses/urls.py` (add the route)
- Test: `courses/tests/test_switchgate_check.py`

**Interfaces:**
- Consumes: `SwitchGateElement` (Task 1); existing `Element`, `can_access_course`, `@require_POST`, `@login_required`, `JsonResponse`, `PermissionDenied` (all already imported in `views.py`).
- Produces: `switchgate_check(request, element_pk)` → `JsonResponse({"correct": bool})`. **Soft pk lookup** (200 `{correct:false}` on miss/wrong-type); access check → `PermissionDenied` (non-200) for a resolved-but-denied element. URL name `courses:switchgate_check`.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_check.py`. Mirror `test_fillgate_check.py`'s fixtures (`enrolled_client`, `enrolled_unit`, `client_without_access`); inspect that file for the exact fixture wiring and reuse it:

```python
import pytest
from django.urls import reverse
from courses.models import SwitchGateElement, Element
from django.contrib.contenttypes.models import ContentType

pytestmark = pytest.mark.django_db


def _make_gate(enrolled_unit, answer=1, options=("a", "b", "c")):
    el = SwitchGateElement.objects.create(stem="￿0￿", options=list(options), answer=answer)
    join = Element.objects.create(
        unit=enrolled_unit,
        content_type=ContentType.objects.get_for_model(SwitchGateElement),
        object_id=el.pk,
    )
    return join


def _url(pk):
    return reverse("courses:switchgate_check", args=[pk])


def test_correct_choice(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": "1"})
    assert r.status_code == 200
    assert r.json() == {"correct": True}


def test_wrong_choice(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": "0"})
    assert r.json() == {"correct": False}


@pytest.mark.parametrize("choice", ["-1", "9", "", "abc"])
def test_placeholder_out_of_range_and_malformed_all_false(enrolled_client, enrolled_unit, choice):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": choice})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_unresolved_pk_soft_200(enrolled_client):
    r = enrolled_client.post(_url(999999), {"choice": "0"})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_wrong_type_pk_soft_200(enrolled_client, enrolled_unit):
    # a join whose content is NOT a switchgate -> soft miss, 200 {correct:false}
    other = SwitchGateElement.objects.create(stem="￿0￿", options=["a", "b"], answer=0)
    # deliberately point at a bare pk that is not a switch-gate Element join:
    r = enrolled_client.post(_url(10_000_000 + other.pk), {"choice": "0"})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_get_405(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit)
    assert enrolled_client.get(_url(join.pk)).status_code == 405


def test_access_denied_non_200(client_without_access, enrolled_unit):
    join = _make_gate(enrolled_unit)
    r = client_without_access.post(_url(join.pk), {"choice": "1"})
    assert r.status_code in (403, 302)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_check.py -v`
Expected: FAIL — `NoReverseMatch: 'switchgate_check'` / endpoint undefined.

- [ ] **Step 3: Add the endpoint** — in `courses/views.py`, next to `fillgate_check` (~line 483). Extend the `SwitchGateElement` import at the top (near the fillgate import, line ~43):

```python
@require_POST
@login_required
def switchgate_check(request, element_pk):
    # Soft lookup: a missing or wrong-type pk is a 200 {correct:false}, NOT a 404
    # (deliberate deviation from fillgate_check's get_object_or_404).
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGateElement):
        return JsonResponse({"correct": False})
    # Resolved element: apply the same access check fillgate_check uses.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    try:
        choice = int(request.POST.get("choice", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False})
    return JsonResponse({"correct": choice == concrete.answer})
```

- [ ] **Step 4: Add the URL** — in `courses/urls.py`, beside the `fillgate_check` route (~line 31):

```python
    path(
        "courses/element/<int:element_pk>/switchgate-check/",
        views.switchgate_check,
        name="switchgate_check",
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_check.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/urls.py courses/tests/test_switchgate_check.py
git commit -m "feat(switchgate): server check endpoint with soft pk lookup"
```

---

### Task 5: Student template + render tag + icon sprite

**Files:**
- Create: `templates/courses/elements/switchgateelement.html`
- Modify: `courses/templatetags/courses_extras.py` (add `render_switch_gate` tag)
- Modify: `templates/courses/manage/_icon_sprite.html` (add `#el-switchgate` symbol)
- Test: `courses/tests/test_switchgate_template.py`

**Interfaces:**
- Consumes: `SwitchGateElement`, `courses.switchgate.render_stem` (Task 2), `reverse` for the check URL.
- Produces: template tag `{% render_switch_gate el eid %}` → the full inline widget HTML (container `<div class="switchgate" data-reveal-gate data-switchgate data-element-pk data-check-url>`, the cycler `<button data-switchgate-cycler>` with a placeholder span + one `hidden` `.switchgate__option` span per option, a visually-hidden describedby hint, a `hidden` Confirm button, and a `hidden` `[data-switchgate-feedback]` "Try again" element).

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_template.py`:

```python
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import SwitchGateElement, Element

pytestmark = pytest.mark.django_db


def _render(enrolled_unit=None, options=("\\(+\\)", "b"), answer=0):
    el = SwitchGateElement.objects.create(stem="x ￿0￿ y", options=list(options), answer=answer)
    html = el.render()
    return html


def test_template_structure():
    html = _render()
    assert 'data-reveal-gate' in html
    assert 'data-switchgate' in html
    assert 'data-switchgate-cycler' in html
    assert 'switchgate__option' in html
    # both options present (all rendered, correct index withheld)
    assert html.count('switchgate__option') == 2
    # placeholder + confirm + feedback all present and confirm/feedback hidden
    assert 'switchgate__confirm' in html
    assert 'data-switchgate-feedback' in html
    # answer index must NOT appear as a data attribute anywhere
    assert 'data-answer' not in html
    # surrounding stem text spliced in
    assert 'x ' in html and ' y' in html
    # LaTeX option preserved verbatim (typeset client-side)
    assert '\\(+\\)' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_template.py -v`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/switchgateelement.html`.

- [ ] **Step 3: Add the render tag** — in `courses/templatetags/courses_extras.py`, mirroring `render_fill_blanks`. Add near it:

```python
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from courses import switchgate as _switchgate


@register.simple_tag
def render_switch_gate(el, eid):
    """Render the inline cycler widget spliced into the stem at its ￿0￿ token."""
    check_url = reverse("courses:switchgate_check", args=[eid])
    options_html = format_html_join(
        "",
        '<span class="switchgate__option" hidden>{}</span>',
        ((mark_safe(o),) for o in (el.options or [])),
    )
    hint_id = f"sg-hint-{eid}"
    widget = format_html(
        '<button type="button" class="switchgate__cycler" data-switchgate-cycler '
        'aria-describedby="{hint}">'
        '<span class="switchgate__placeholder">{placeholder}</span>{options}</button>'
        '<span id="{hint}" class="visually-hidden">{describe}</span>'
        '<button type="button" class="switchgate__confirm" hidden>{confirm}</button>'
        '<span class="switchgate__feedback" data-switchgate-feedback hidden>{tryagain}</span>',
        hint=hint_id,
        placeholder=_("Choose ▾"),
        options=options_html,
        describe=_("Choose an option"),
        confirm=_("Confirm"),
        tryagain=_("Try again"),
    )
    body = _switchgate.render_stem(el.stem, widget)
    return format_html(
        '<div class="switchgate" data-reveal-gate data-switchgate '
        'data-element-pk="{pk}" data-check-url="{url}">{body}</div>',
        pk=eid,
        url=check_url,
        body=body,
    )
```

Note: if `courses_extras.py` already imports some of these (`reverse`, `mark_safe`, `format_html`), do not duplicate the imports — merge.

- [ ] **Step 4: Add the student template** — `templates/courses/elements/switchgateelement.html`:

```django
{% load courses_extras %}
{% render_switch_gate el eid %}
```

- [ ] **Step 5: Add the icon symbol** — in `templates/courses/manage/_icon_sprite.html`, beside `#el-fillgate` (~line 31), add a monochrome `currentColor` line-SVG symbol (16×16 viewBox, matching sibling icons — e.g. a small list/chevron glyph):

```html
<symbol id="el-switchgate" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/></symbol>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_template.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/elements/switchgateelement.html courses/templatetags/courses_extras.py templates/courses/manage/_icon_sprite.html courses/tests/test_switchgate_template.py
git commit -m "feat(switchgate): student template + render tag + icon"
```

---

### Task 6: Editor partial + palette + labels + authoring wiring

**Files:**
- Create: `templates/courses/manage/editor/_edit_switchgate.html`
- Modify: `templates/courses/manage/editor/_add_menu.html` (palette card)
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`, `element_add` + `element_save` type tuples)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`)
- Test: `courses/tests/test_switchgate_authoring.py`

**Interfaces:**
- Consumes: `SwitchGateElementForm.option_rows()` (Task 3); the `_host_form.html` convention that includes `_edit_{{type_key}}.html` and passes `form`.
- Produces: a working GET+POST `manage_element_add` path for `switchgate` (returns 200). Editor labels for the type.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_authoring.py`. Mirror `test_fillgate_authoring.py` for the client/course fixtures:

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_element_add_get_renders_edit_partial(author_client, editable_unit):
    url = reverse("courses:manage_element_add")
    r = author_client.get(url, {"type": "switchgate", "unit": editable_unit.pk})
    assert r.status_code == 200
    assert b"data-add-type" in r.content or b'name="option"' in r.content


def test_element_add_post_creates(author_client, editable_unit):
    url = reverse("courses:manage_element_add")
    data = {
        "type": "switchgate", "unit": editable_unit.pk, "unit_token": "",
        "stem": "pick {{choice}}", "option": ["a", "b"], "answer": "0",
    }
    r = author_client.post(url, data)
    assert r.status_code in (200, 302)


def test_editor_type_label_present(author_client, editable_unit):
    from courses.views_manage import _EDITOR_TYPE_LABELS
    assert "switchgate" in _EDITOR_TYPE_LABELS
```

Note: confirm the exact fixture names (`author_client`, `editable_unit`) and the `manage_element_add` GET/POST parameter contract from `test_fillgate_authoring.py`; adapt if they differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_authoring.py -v`
Expected: FAIL — `TemplateDoesNotExist: courses/manage/editor/_edit_switchgate.html` (500) or label KeyError.

- [ ] **Step 3: Add the editor partial** — `templates/courses/manage/editor/_edit_switchgate.html`:

```django
{% load i18n %}
<div class="el-editor el-editor--switchgate">
  <label class="el-editor__label">{% trans "Prompt with a choice" %}</label>
  <p class="el-editor__hint">{% trans "Mark the choice position with {{choice}} (exactly once)." %}</p>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Options (mark the correct one)" %}</label>
  <div class="el-editor__options">
    {% for row in form.option_rows %}
      <div class="el-editor__option-row">
        <input type="radio" name="answer" value="{{ forloop.counter0 }}"{% if row.checked %} checked{% endif %}
               aria-label="{% trans 'Correct option' %}">
        <input type="text" name="option" class="rte-source" value="{{ row.value }}"
               placeholder="{% trans 'Option' %} {{ forloop.counter }}">
      </div>
    {% endfor %}
  </div>
  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

(Fixed row set — trailing blanks are ignored server-side, so no add/remove JS is needed. The legacy widget's busiest example had 4 real options; ≥6 rows covers it.)

- [ ] **Step 4: Add the palette card** — in `templates/courses/manage/editor/_add_menu.html`, inside the "Interactive" group (~after the `fillgate` button, line ~30):

```html
<button type="button" class="typemenu__item" data-add-type="switchgate">
  <svg class="icon" width="16" height="16"><use href="#el-switchgate"/></svg>{% trans "Choose & confirm" %}
</button>
```

- [ ] **Step 5: Add editor + element labels + type tuples** —
  In `courses/views_manage.py`: add to `_EDITOR_TYPE_LABELS` (~line 750): `"switchgate": gettext_lazy("Choose & confirm"),`. Add `"switchgate"` to the `element_add` whitelist tuple (~line 883-884) **and** the `element_save` whitelist tuple (~line 938-940).
  In `courses/templatetags/courses_manage_extras.py`: add to `_ELEMENT_LABELS` (~line 46): `"switchgateelement": _("Choose & confirm"),`. (No explicit `element_summary` branch — like fillgate, its `stem` falls through the generic `￿n￿`→`___` summariser.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_authoring.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_edit_switchgate.html templates/courses/manage/editor/_add_menu.html courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_switchgate_authoring.py
git commit -m "feat(switchgate): editor partial, palette card, labels, add/save wiring"
```

---

### Task 7: Client enhancer `switchgate.js` + editor re-init + editor.html script + reveal.js focus + CSS

**Files:**
- Create: `courses/static/courses/js/switchgate.js`
- Modify: `courses/static/courses/js/editor.js` (re-init line)
- Modify: `templates/courses/manage/editor/editor.html` (`<script>` include)
- Modify: `courses/static/courses/js/reveal.js` (`focusTargetIn` switchgate branch)
- Modify: `core/static/core/css/app.css` (`.switchgate*` rules)
- Test: `courses/tests/test_switchgate_wiring.py`, `courses/tests/test_switchgate_css.py`

**Interfaces:**
- Consumes: `window.libliRevealCascade` (reveal.js), `window.__switchGateBooted` watchdog contract (Task 9 wires the watchdog).
- Produces: `window.libliInitSwitchGates(root)` (idempotent); `window.__switchGateBooted = true`; a cycler that rings placeholder→options→placeholder toggling `hidden`; Confirm that POSTs `choice`, locks + cascades on correct, shows "Try again" on wrong; the "Try again" element re-hides on next cycle; unsaved-preview (`pk==="0"`) no-op; math typeset at init.

- [ ] **Step 1: Write the failing wiring/css tests** — `courses/tests/test_switchgate_wiring.py` (mirror `test_fillgate_wiring.py`):

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_editor_loads_switchgate_js(author_client, editable_unit):
    r = author_client.get(reverse("courses:manage_editor", args=[editable_unit.pk]))
    assert b"switchgate.js" in r.content
```

`courses/tests/test_switchgate_css.py` (mirror `test_fillgate_css.py`):

```python
from pathlib import Path
from django.conf import settings


def test_switchgate_css_present():
    css = Path(settings.BASE_DIR, "core", "static", "core", "css", "app.css").read_text(encoding="utf-8")
    assert ".switchgate__cycler" in css
    assert ".switchgate--done" in css
```

Confirm the `manage_editor` url name/args and the app.css path against the fillgate equivalents; adjust if needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_switchgate_wiring.py courses/tests/test_switchgate_css.py -v`
Expected: FAIL (script/CSS absent).

- [ ] **Step 3: Write `switchgate.js`** — `courses/static/courses/js/switchgate.js`:

```javascript
(function () {
  "use strict";

  // Fail-open boot flag: the lesson_unit.html prepaint watchdog disarms the
  // pre-hide if this is still falsy at DOMContentLoaded, so a dead switchgate.js
  // can never trap content hidden.
  window.__switchGateBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function ring(cycler) {
    // ordered ring entries: placeholder first, then each option span
    var ph = cycler.querySelector(".switchgate__placeholder");
    var opts = cycler.querySelectorAll(".switchgate__option");
    return [ph].concat(Array.prototype.slice.call(opts));
  }

  function currentIndex(cycler) {
    // -1 == placeholder visible; else the 0-based option index
    var entries = ring(cycler);
    for (var i = 1; i < entries.length; i++) {
      if (!entries[i].hasAttribute("hidden")) return i - 1;
    }
    return -1;
  }

  function showEntry(cycler, ringPos) {
    var entries = ring(cycler);
    for (var i = 0; i < entries.length; i++) {
      if (i === ringPos) entries[i].removeAttribute("hidden");
      else entries[i].setAttribute("hidden", "");
    }
  }

  function advance(container) {
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var entries = ring(cycler);
    // find current visible ring position (0 == placeholder)
    var pos = 0;
    for (var i = 0; i < entries.length; i++) {
      if (!entries[i].hasAttribute("hidden")) { pos = i; break; }
    }
    showEntry(cycler, (pos + 1) % entries.length);
    hideFeedback(container);  // a fresh attempt starts clean
  }

  function hideFeedback(container) {
    var fb = container.querySelector("[data-switchgate-feedback]");
    if (fb) fb.hidden = true;
  }

  function lock(container) {
    var cycler = container.querySelector("[data-switchgate-cycler]");
    if (cycler) cycler.disabled = true;
    var confirm = container.querySelector(".switchgate__confirm");
    if (confirm) confirm.remove();
    container.classList.add("switchgate--done");
  }

  function submit(container) {
    var pk = container.getAttribute("data-element-pk");
    var url = container.getAttribute("data-check-url");
    if (!pk || pk === "0" || !url) return;  // unsaved preview: no-op
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var body = new FormData();
    body.append("choice", String(currentIndex(cycler)));
    fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf() },
      body: body,
    })
      .then(function (r) { return r.ok ? r.json() : { correct: false }; })
      .then(function (data) {
        if (data.correct) {
          lock(container);
          if (window.libliRevealCascade) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
        } else {
          var fb = container.querySelector("[data-switchgate-feedback]");
          if (fb) fb.hidden = false;
        }
      })
      .catch(function () { /* leave gate closed, widget editable */ });
  }

  function typesetMath(container) {
    if (window.renderMathInElement) {
      try { window.renderMathInElement(container); } catch (e) { /* noop */ }
    }
  }

  function initOne(container) {
    if (container.dataset.switchgateReady === "1") return;
    container.dataset.switchgateReady = "1";
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var confirm = container.querySelector(".switchgate__confirm");
    if (confirm) confirm.hidden = false;  // arm Confirm now that JS is live
    if (cycler) {
      cycler.addEventListener("click", function () { advance(container); });
    }
    if (confirm) {
      confirm.addEventListener("click", function () { submit(container); });
    }
    typesetMath(container);
  }

  // Idempotent; re-run over the editor preview after each fragment swap.
  function initSwitchGates(root) {
    var scope = root || document;
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-switchgate]"), initOne
    );
  }

  window.libliInitSwitchGates = initSwitchGates;
  initSwitchGates(document);
})();
```

Note: confirm the math-typeset entrypoint fillgate/reveal use (the codebase may call `window.renderMathInElement` from KaTeX auto-render, or a project wrapper). Match whatever the student page exposes; if math auto-renders globally on load, `typesetMath` can be a no-op — but keep the call so freshly-cycled hidden spans render.

- [ ] **Step 4: Wire the editor re-init** — in `courses/static/courses/js/editor.js` (~line 78, after the fillgate line):

```javascript
    if (preview && window.libliInitFillGates) window.libliInitFillGates(preview);
    if (preview && window.libliInitSwitchGates) window.libliInitSwitchGates(preview);
```

- [ ] **Step 5: Add the editor `<script>`** — in `templates/courses/manage/editor/editor.html`, after the `fillgate.js` line (~145), so it loads after `reveal.js`:

```django
<script src="{% static 'courses/js/switchgate.js' %}" defer></script>
```

- [ ] **Step 6: Add the `focusTargetIn` switchgate branch** — in `courses/static/courses/js/reveal.js`, inside `focusTargetIn(wrapper)` (~lines 51-61), beside the `[data-fillgate]` special-case:

```javascript
    if (wrapper.matches("[data-switchgate]")) {
      return wrapper.querySelector("[data-switchgate-cycler]");
    }
```

- [ ] **Step 7: Add CSS** — in `core/static/core/css/app.css`, after the fillgate block (~line 974). Reuse fillgate's `--done` and confirm-pill idiom; the cycler + option are new:

```css
/* Choose & confirm gate (switchgate) */
.switchgate { margin: var(--space-4) 0; }
.switchgate__cycler {
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-2);
  padding: 0 var(--space-2);
  background: var(--surface-2);
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.switchgate__cycler:disabled { cursor: default; opacity: 0.85; }
.switchgate__placeholder { color: var(--text-muted); }
.switchgate__confirm { /* mirror .fillgate__confirm pill */ }
.switchgate__feedback { color: var(--danger); margin-left: var(--space-2); }
.switchgate--done { border-left: 3px solid var(--success); padding-left: var(--space-3); }
.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}
```

Note: copy the exact `.fillgate__confirm` rule for `.switchgate__confirm`, and confirm `.visually-hidden` isn't already defined (if it is, drop the duplicate). Use the real token names present in app.css (`--danger`/`--error`, `--surface-2`, etc.) — match fillgate's tokens.

- [ ] **Step 8: Run the wiring/css tests + verify JS loads**

Run: `uv run pytest courses/tests/test_switchgate_wiring.py courses/tests/test_switchgate_css.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add courses/static/courses/js/switchgate.js courses/static/courses/js/editor.js courses/static/courses/js/reveal.js templates/courses/manage/editor/editor.html core/static/core/css/app.css courses/tests/test_switchgate_wiring.py courses/tests/test_switchgate_css.py
git commit -m "feat(switchgate): client enhancer, editor re-init, reveal focus, CSS"
```

---

### Task 8: Taking-view context flags + `lesson_unit.html` wiring

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`: extend `has_reveal_gate`, add `has_switch_gate`, extend `has_math`)
- Modify: `templates/courses/lesson_unit.html` (watchdog `|| !window.__switchGateBooted`, `{% if has_switch_gate %}<script switchgate.js>`)
- Test: `courses/tests/test_switchgate_context.py`

**Interfaces:**
- Consumes: `SwitchGateElement` (import in views.py); `has_math_delimiters` (already imported).
- Produces: context flags `has_reveal_gate` (now includes switchgate), `has_switch_gate`, `has_math` (now scans switchgate stem+options); `lesson_unit.html` loads `switchgate.js` and registers the boot flag in the watchdog.

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_context.py` (mirror `test_fillgate_context.py`):

```python
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import SwitchGateElement, Element

pytestmark = pytest.mark.django_db


def _add_switchgate(unit, options=("a", "b"), stem="x ￿0￿ y"):
    el = SwitchGateElement.objects.create(stem=stem, options=list(options), answer=0)
    return Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGateElement),
        object_id=el.pk,
    )


def test_switchgate_arms_reveal_and_script(enrolled_client, enrolled_unit, lesson_url_for):
    _add_switchgate(enrolled_unit)
    r = enrolled_client.get(lesson_url_for(enrolled_unit))
    body = r.content.decode()
    assert "reveal-armed" in body or "data-reveal-gate" in body   # pre-hide armed
    assert "switchgate.js" in body                                # script loaded
    assert "__switchGateBooted" in body                           # watchdog registered


def test_switchgate_math_in_option_detected(enrolled_client, enrolled_unit, lesson_url_for):
    _add_switchgate(enrolled_unit, options=("\\(x\\)", "b"), stem="plain ￿0￿")
    r = enrolled_client.get(lesson_url_for(enrolled_unit))
    assert "katex" in r.content.decode().lower()


def test_switchgate_math_in_stem_detected(enrolled_client, enrolled_unit, lesson_url_for):
    _add_switchgate(enrolled_unit, options=("a", "b"), stem="\\(y\\) ￿0￿")
    r = enrolled_client.get(lesson_url_for(enrolled_unit))
    assert "katex" in r.content.decode().lower()
```

Note: reuse `test_fillgate_context.py`'s exact fixtures/helpers for building the enrolled lesson and its URL (named `lesson_url_for` here as a placeholder — match the real one).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_context.py -v`
Expected: FAIL — script/flags absent.

- [ ] **Step 3: Extend the context builder** — in `courses/views.py`, `build_lesson_context`. Import `SwitchGateElement` at top (extend the fillgate import line ~43).

  (a) Extend `has_reveal_gate` (~line 227) to include the new model:

```python
    has_reveal_gate = node.elements.filter(
        content_type__model__in=["revealgateelement", "fillgateelement", "switchgateelement"]
    ).exists()
```

  (b) Add `has_switch_gate` right after `has_fill_gate` (~line 230):

```python
    has_switch_gate = node.elements.filter(
        content_type__model="switchgateelement"
    ).exists()
```

  (c) Extend `has_math` (~lines 216-219) with a switchgate clause — math may live in the stem **OR** any option (OR, not AND):

```python
        or any(
            isinstance(el.content_object, SwitchGateElement)
            and (
                has_math_delimiters(el.content_object.stem)
                or any(has_math_delimiters(o) for o in (el.content_object.options or []))
            )
            for el in elements
        )
```

  (d) Add `has_switch_gate` to the returned context dict (beside `has_fill_gate`, ~lines 243-254).

- [ ] **Step 4: Wire `lesson_unit.html`** —
  In the prepaint watchdog (~lines 4-18), extend the disarm condition beside `__fillGateBooted`:

```django
      if (!window.__revealBooted{% if has_fill_gate %} || !window.__fillGateBooted{% endif %}{% if has_switch_gate %} || !window.__switchGateBooted{% endif %}) {
```

  In the `extra_js` block (~line 59, after the fillgate script), add:

```django
    {% if has_switch_gate %}<script src="{% static 'courses/js/switchgate.js' %}" defer></script>{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_context.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py templates/courses/lesson_unit.html courses/tests/test_switchgate_context.py
git commit -m "feat(switchgate): taking-view context flags + lesson_unit wiring"
```

---

### Task 9: Transfer (export / import / validate / nestable)

**Files:**
- Modify: `courses/transfer/export.py` (serializer + `SERIALIZERS`)
- Modify: `courses/transfer/payloads.py` (validator + `VALIDATORS`)
- Modify: `courses/transfer/importer.py` (builder + `BUILDERS`)
- Modify: `courses/builder.py` (`NESTABLE_TYPE_KEYS`, `_NESTABLE_FORM_KEY_ALIASES`)
- Test: `courses/tests/test_switchgate_transfer.py`

**Interfaces:**
- Consumes: `SwitchGateElement`.
- Produces: transfer key `switch_gate` round-trips `{stem, options, answer}`; the validator rejects `<2` options, out-of-range `answer`, or a stem without exactly one `￿0￿` sentinel; `switch_gate` is nestable inside tabs. **`FORMAT_VERSION` stays 3** (see Global Constraints).

- [ ] **Step 1: Write the failing test** — `courses/tests/test_switchgate_transfer.py` (mirror `test_fillgate_transfer.py`):

```python
import pytest
from courses.transfer.export import SERIALIZERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.importer import BUILDERS
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import SwitchGateElement

pytestmark = pytest.mark.django_db


def test_registered_and_nestable():
    assert "switch_gate" in SERIALIZERS
    assert "switch_gate" in VALIDATORS
    assert "switch_gate" in BUILDERS
    assert "switch_gate" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)   # the invariant


def test_round_trip():
    model_cls, ser = SERIALIZERS["switch_gate"]
    el = SwitchGateElement.objects.create(stem="￿0￿", options=["a", "b", "c"], answer=2)
    payload = ser(el)
    assert payload == {"stem": "￿0￿", "options": ["a", "b", "c"], "answer": 2}
    built, _media = BUILDERS["switch_gate"](payload, {})
    assert built.stem == "￿0￿"
    assert built.options == ["a", "b", "c"]
    assert built.answer == 2


def _validate(data):
    err = []
    VALIDATORS["switch_gate"](data, "el1", err)  # match the real _err signature
    return err


def test_validator_rejects_few_options():
    assert _validate({"stem": "￿0￿", "options": ["a"], "answer": 0})


def test_validator_rejects_bad_answer():
    assert _validate({"stem": "￿0￿", "options": ["a", "b"], "answer": 5})


def test_validator_rejects_missing_sentinel():
    assert _validate({"stem": "no token", "options": ["a", "b"], "answer": 0})


def test_validator_accepts_valid():
    assert not _validate({"stem": "￿0￿", "options": ["a", "b"], "answer": 0})
```

Note: read `courses/transfer/payloads.py`'s `_val_fill_gate` to match the EXACT validator signature and error-append convention (`_err(...)` vs. a list arg) before finalising these tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_switchgate_transfer.py -v`
Expected: FAIL — `KeyError: 'switch_gate'`.

- [ ] **Step 3: Add the serializer** — in `courses/transfer/export.py`, beside `_ser_fill_gate`:

```python
def _ser_switch_gate(concrete):
    return {"stem": concrete.stem, "options": concrete.options, "answer": concrete.answer}
```

Register in `SERIALIZERS` (after the `fill_gate` line):

```python
    "switch_gate": (SwitchGateElement, _ser_switch_gate),
```

(Import `SwitchGateElement` at the top of `export.py` alongside `FillGateElement`.)

- [ ] **Step 4: Add the validator** — in `courses/transfer/payloads.py`, mirroring `_val_fill_gate`'s exact signature and `_err` usage. Reuse the `￿0￿` sentinel via `from courses.switchgate import SENTINEL_TOKEN`:

```python
def _val_switch_gate(data, elid, media_kinds):
    stem = data.get("stem", "")
    options = data.get("options", [])
    answer = data.get("answer", None)
    if not isinstance(stem, str) or stem.count(SENTINEL_TOKEN) != 1:
        _err(elid, "switch_gate stem must contain exactly one choice token")
    if not isinstance(options, list) or len(options) < 2 or not all(isinstance(o, str) for o in options):
        _err(elid, "switch_gate needs a list of at least two string options")
    elif not isinstance(answer, int) or isinstance(answer, bool) or not (0 <= answer < len(options)):
        _err(elid, "switch_gate answer must be an index within options")
    return set()
```

Register in `VALIDATORS` (after `fill_gate`): `"switch_gate": _val_switch_gate,`. (Match the real `_err` / return-shape convention exactly — the snippet assumes `_err(elid, msg)` and a `set()` media return like `_val_fill_gate`.)

- [ ] **Step 5: Add the builder** — in `courses/transfer/importer.py`, beside `_build_fill_gate`:

```python
def _build_switch_gate(data, assets):
    obj = SwitchGateElement.objects.create(
        stem=data.get("stem", ""),
        options=data.get("options", []),
        answer=data.get("answer", 0),
    )
    return obj, ()
```

Register in `BUILDERS` (after `fill_gate`): `"switch_gate": _build_switch_gate,`. (Import `SwitchGateElement`.)

- [ ] **Step 6: Make it nestable** — in `courses/builder.py`: add `"switch_gate"` to `NESTABLE_TYPE_KEYS` (~line 44) and `"switchgate": "switch_gate"` to `_NESTABLE_FORM_KEY_ALIASES` (~line 49).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_switchgate_transfer.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/builder.py courses/tests/test_switchgate_transfer.py
git commit -m "feat(switchgate): transfer serialize/validate/build + nestable"
```

---

### Task 10: i18n catalogs (EN/PL)

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (and any app-level catalogs the project uses — mirror where fillgate's strings live)
- Test: run the existing i18n catalog tests + `makemessages` check

**Interfaces:**
- Consumes: all `_()`/`{% trans %}` strings added in Tasks 5, 6, 8 ("Choose ▾", "Choose an option", "Confirm", "Try again", "Choose & confirm", "Prompt with a choice", "Mark the choice position with {{choice}} (exactly once).", "Options (mark the correct one)", "Correct option", "Option", "Add at least two options.", "Options cannot be empty.", "Select the correct option.", "Mark the choice position with {{choice}} exactly once.").

- [ ] **Step 1: Regenerate message catalogs**

Run: `uv run python manage.py makemessages -l pl -l en` (match the project's actual locale set; see the [[uv-run-tooling]] note about the makemessages fuzzy-flag gotcha — do NOT leave `#, fuzzy` on freshly translated entries).
Expected: new `msgid`s for the switchgate strings appear in each `.po`.

- [ ] **Step 2: Add Polish translations** — fill each new `msgstr` in `locale/pl/LC_MESSAGES/django.po`, e.g.:

```
msgid "Choose & confirm"
msgstr "Wybierz i zatwierdź"

msgid "Confirm"
msgstr "Zatwierdź"

msgid "Try again"
msgstr "Spróbuj ponownie"

msgid "Choose ▾"
msgstr "Wybierz ▾"
```

(Translate every new msgid; keep `{{choice}}` and `▾` verbatim inside strings. Use the legacy Polish wording where it exists — e.g. "Spróbuj ponownie", "Zatwierdź".)

- [ ] **Step 3: Compile + run catalog tests**

Run: `uv run python manage.py compilemessages` then the project's i18n catalog test (find it — e.g. `uv run pytest -k "i18n or catalog or messages"`).
Expected: PASS; no obsolete `#~` entries, no stray `#, fuzzy` on new strings.

- [ ] **Step 4: Commit**

```bash
git add locale/
git commit -m "i18n(switchgate): EN/PL catalogs"
```

---

### Task 11: e2e behavior matrix (Playwright)

**Files:**
- Create: `tests/test_e2e_switchgate.py`

**Interfaces:**
- Consumes: the full feature. Mirror `tests/test_e2e_fillgate.py`'s harness (server fixture, page helpers, seeding of a gated unit, and a following-sibling to reveal).

- [ ] **Step 1: Write the e2e tests** — `tests/test_e2e_switchgate.py`. Drive the REAL gestures (click the cycler, click Confirm) — no `page.evaluate` shortcut (see [[e2e-must-drive-real-ui]]). Cover the matrix:

```python
# Seed a unit: [switchgate gate]  +  [following text block "SECRET"].
# Helper _seed_switchgate(author_stem, options, answer) mirrors _fillgate(...).

def test_cycle_wraps_through_placeholder(page, seeded):
    # click cycler N+1 times: placeholder -> opt0 -> ... -> optN-1 -> placeholder
    ...

def test_wrong_choice_shows_try_again_and_stays_gated(page, seeded):
    # cycle to a wrong option, Confirm -> "Try again" visible, SECRET still hidden,
    # widget still editable (cycler not disabled)
    ...

def test_wrong_then_correct_reveals_and_locks(page, seeded):
    # wrong Confirm -> try again; cycle (try-again hides) to correct -> Confirm ->
    # SECRET visible, cycler disabled, Confirm gone
    ...

def test_chains_to_next_gate_and_focuses_cycler(page, seeded_two_gates):
    # a preceding plain/reveal gate whose cascade stops at the switchgate ->
    # focus lands on [data-switchgate-cycler]
    ...

def test_option_math_typeset(page, seeded_math):
    # a \(+\) option renders KaTeX (a .katex node), not raw "\(+\)"
    ...

def test_switchgate_nested_in_tab_scopes_to_panel(page, seeded_tab):
    # switchgate inside a tab reveals only within that tab panel
    ...

def test_no_js_shows_content_and_inert_placeholder(context, seeded):
    # with JS disabled: SECRET visible (fail-open), cycler shows only "Choose ▾",
    # options + Confirm remain hidden
    ...
```

Fill in each body against the real `test_e2e_fillgate.py` helpers (`_confirm`, panel/gate seeding, the JS-disabled context pattern from fillgate/reveal e2e).

- [ ] **Step 2: Run the e2e file (foreground, focused)**

Run: `uv run pytest tests/test_e2e_switchgate.py -v` (foreground only — see [[gallery-carousel-status]] build lesson: never background `-m e2e`, which spawns runaway headless browsers).
Expected: PASS (all matrix cases).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_switchgate.py
git commit -m "test(switchgate): e2e behavior matrix"
```

---

### Task 12: Full-suite DoD + lint

**Files:** none (verification task).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest` (the controller owns the full-suite DoD; do not background it).
Expected: all green, including the transfer invariant test (`NESTABLE_TYPE_KEYS <= SERIALIZERS`), any `element_add`/`element_save` whitelist tests, and the i18n catalog tests.

- [ ] **Step 2: Lint + format check**

Run: `uv run ruff check` and `uv run ruff format --check`
Expected: both clean. (`ruff format --check` is a separate gate from `ruff check` — see [[sis-webhook-guide-status]].)

- [ ] **Step 3: `makemigrations --check`**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" — the hand-written migration 0038 fully matches model state.

- [ ] **Step 4: Final commit (if any lint/format fixes were applied)**

```bash
git add -A
git commit -m "chore(switchgate): lint/format + full-suite green"
```

---

## Self-Review Notes

**Spec coverage check** — every spec section maps to a task:
- Data model (stem/options/answer, sanitize, render) → Task 1; stem helper → Task 2.
- Server endpoint (soft pk lookup, access, malformed→false, decorators) → Task 4.
- Client enhancer (cycler ring, `-1` placeholder, Confirm→cascade/try-again, `__switchGateBooted`, preview no-op, math typeset, disabled-on-done, try-again-rehides-on-cycle, accessible name via visible text + describedby) → Tasks 5 (markup) + 7 (behavior).
- Student template (dual `data-reveal-gate`/`data-switchgate`, block child, hidden options/Confirm) → Task 5.
- Editor partial + options-list POST contract (`getlist("option")`, single `answer` radio) + palette + labels → Tasks 3 + 6.
- Transfer trio + integrity validators + NESTABLE + alias → Task 9. (**FORMAT_VERSION deliberately NOT bumped** — see Global Constraints.)
- Taking-view wiring (`has_reveal_gate`, `has_switch_gate` + script, `has_math` OR, `reveal.js` focus) → Tasks 8 + 7.
- Prepaint watchdog registration → Task 8. CSS deliverable → Task 7.
- i18n → Task 10. All tests (model/form, endpoint, transfer, authoring, editor-script wiring, taking-view wiring, e2e) → Tasks 1-11; DoD → Task 12.

**Known verification points for the implementer** (confirm against the repo, don't assume): exact fixture names in the fillgate test files; the `_err`/validator signature in `payloads.py`; the math-typeset entrypoint the student page exposes; the exact `element_add`/`element_save` whitelist tuples; the `.fillgate__confirm` CSS rule to copy; the locale set for `makemessages`; and that `sanitize_html` is already imported in `element_forms.py`.
