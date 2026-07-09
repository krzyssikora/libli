# Table Content Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `table` lesson content element with an author-friendly WYSIWYG editor (per-cell B/I/U + LaTeX, per-cell alignment, header row/column toggles, border presets) and a clean, math-rendering student view.

**Architecture:** Follow the codebase's per-type element pattern: a concrete `TableElement(ElementBase)` model storing a single JSON `data` blob, wired into ~10 lockstep registries (models/migration, form+`FORM_FOR_TYPE`, render template, editor partial+JS, manage-UI labels/add-menu/icon, `has_math`, transfer export/validate/import). Cell HTML is sanitised at `save()` (like `TextElement.body`) down to `<strong>/<b>/<em>/<i>/<u>/<br>` with a math-protection pass that survives the HTML tokenizer; math renders client-side via the existing KaTeX inline pass.

**Tech Stack:** Django 5.2, Python, `nh3` sanitiser, KaTeX (client), MathLive (`window.libliMathInput`), vanilla JS editor (`contenteditable` + `document.execCommand`), pytest + Playwright e2e.

## Global Constraints

- Tooling: run everything via `uv run` (e.g. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`). Bash `ruff`/`pytest`/`python` are NOT on PATH.
- DoD for every task: `uv run ruff check` AND `uv run ruff format --check` must pass (ruff E402: imports stay at top of file; not auto-fixable).
- Tests: use `tests.factories.TEST_PASSWORD` — never hardcode a password literal (GitGuardian CI blocks new password literals).
- Math delimiters are `\(...\)` (inline) and `\[...\]` (display) EVERYWHERE. `$...$` is never recognised — do not introduce it.
- All new user-facing strings use `gettext_lazy` (module-level labels MUST be lazy — eager `gettext` has frozen labels to English here before) and ship EN + PL catalog entries.
- Django multi-line comments use `{% comment %}…{% endcomment %}`; `{# #}` is single-line only (a multi-line `{# #}` renders as visible text).
- e2e must drive the REAL UI gesture (actual clicks/typing), never a `page.evaluate` shortcut that bypasses the gesture.
- Tests live in the top-level `tests/` dir as `test_*.py`; e2e as `test_e2e_*.py`. Factories in `tests/factories.py`.
- Migration for the new model is `courses/migrations/0033_...` (latest is `0032`).

---

### Task 1: Cell sanitiser with math protection (`courses/sanitize.py`)

Pure functions, no Django — the foundation everything else trusts. The subtle part is `_sanitize_preserving_math`: it must let LaTeX survive the `nh3` HTML tokenizer AND converge two different input shapes (editor path where a typed `<` arrives already as `&lt;` from `innerHTML`; import path where `<` can be literal) to one single-escaped, KaTeX-correct, HTML-inert stored value.

**Files:**
- Modify: `courses/sanitize.py` (add cell allowlist + helpers; leave `sanitize_html` untouched)
- Test: `tests/test_table_sanitize.py` (create)

**Interfaces:**
- Produces: `sanitize_cell(value: str) -> str` (used by `TableElement.save()` in Task 2); `CELL_TAGS: set[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_sanitize.py`:

```python
from courses.sanitize import sanitize_cell


def test_keeps_bold_italic_underline_tags():
    # execCommand emits <b>/<i>; strong/em/u also allowed. All survive.
    for tag in ("strong", "b", "em", "i", "u"):
        assert f"<{tag}>x</{tag}>" in sanitize_cell(f"<{tag}>x</{tag}>")
    assert "<br>" in sanitize_cell("a<br>b")


def test_strips_disallowed_markup():
    assert "<script>" not in sanitize_cell("<script>alert(1)</script>")
    assert "onclick" not in sanitize_cell('<b onclick="x">y</b>')
    assert "<div>" not in sanitize_cell("<div>x</div>")


def test_editor_path_lt_entity_converges_single_escaped():
    # Editor serialises via innerHTML, so a typed < arrives as the entity &lt;.
    assert sanitize_cell(r"\(a&lt;b\)") == r"\(a&lt;b\)"


def test_import_path_literal_lt_converges_single_escaped():
    # Import payload can carry a literal <. Canonicalises to the SAME stored value.
    assert sanitize_cell(r"\(a<b\)") == r"\(a&lt;b\)"


def test_idempotent_no_double_escape_on_reedit():
    once = sanitize_cell(r"\(a<b\)")
    assert sanitize_cell(once) == once  # re-edit adds no &amp; layer


def test_math_span_cannot_smuggle_live_markup():
    out = sanitize_cell(r"\(<img src=x onerror=alert(1)>\)")
    assert "onerror" in out            # preserved as inert text for KaTeX
    assert "<img" not in out           # but not as a live tag
    assert "&lt;img" in out


def test_unmatched_delimiter_left_as_literal_text():
    # A lone \( has no closing \) — not protected; sanitised as ordinary text.
    out = sanitize_cell(r"a \( b < c")   # literal < outside a balanced pair
    assert "<c" not in out               # ordinary < is dropped/escaped by nh3


def test_display_math_protected_too():
    assert sanitize_cell(r"\[a<b\]") == r"\[a&lt;b\]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_table_sanitize.py -q`
Expected: FAIL / ImportError (`sanitize_cell` not defined).

- [ ] **Step 3: Implement the helpers**

Append to `courses/sanitize.py`:

```python
import html
import re
import secrets

# Cells allow only inline emphasis + line break. Includes b/i (not just
# strong/em) because document.execCommand("bold"/"italic") emits <b>/<i>.
CELL_TAGS = {"strong", "b", "em", "i", "u", "br"}

# Balanced \(...\) (inline) or \[...\] (display), non-greedy, no nesting.
_MATH_SPAN = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)


def _canon_math(span):
    """Canonicalise a math span's text: unescape once, then escape once, so the
    editor path (< already &lt;) and import path (literal <) converge to one
    single-escaped value that is inert to the HTML parser yet decodes to the
    correct textContent for KaTeX. quote=False leaves ' and " untouched."""
    return html.escape(html.unescape(span), quote=False)


def sanitize_cell(value):
    """Sanitise one table cell's html to CELL_TAGS, protecting balanced LaTeX
    spans from the HTML tokenizer. Idempotent on already-clean input."""
    value = value or ""
    nonce = secrets.token_hex(8)
    spans = []

    def _stash(match):
        spans.append(match.group(0))
        # Pure-alphanumeric placeholder: survives nh3.clean unchanged; nonce
        # makes collision with author-typed text effectively impossible.
        return f"litmathspan{nonce}x{len(spans) - 1}xend"

    protected = _MATH_SPAN.sub(_stash, value)
    cleaned = nh3.clean(
        protected,
        tags=CELL_TAGS,
        attributes={},
        url_schemes=set(),
        link_rel=None,
    )
    placeholder = re.compile(f"litmathspan{nonce}x(\\d+)xend")
    return placeholder.sub(lambda m: _canon_math(spans[int(m.group(1))]), cleaned)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_table_sanitize.py -q`
Expected: PASS (all 8).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/sanitize.py tests/test_table_sanitize.py
uv run ruff format courses/sanitize.py tests/test_table_sanitize.py
git add courses/sanitize.py tests/test_table_sanitize.py
git commit -m "feat(table): cell sanitiser with math-protection canonicalisation"
```

---

### Task 2: `TableElement` model + `normalize_data` + migration

**Files:**
- Modify: `courses/models.py` (add `TableElement`, append `"tableelement"` to `ELEMENT_MODELS`)
- Create: `courses/migrations/0033_tableelement_alter_element_content_type.py`
- Test: `tests/test_table_model.py` (create)

**Interfaces:**
- Produces: `TableElement(data: JSONField)`; `TableElement.normalize_data(data) -> dict` (staticmethod); `TableElement.save()` sanitises cell html. Consumed by Tasks 3, 4, 6, 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_model.py`:

```python
import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _cell(html="", h="left", v="top"):
    return {"html": html, "halign": h, "valign": v}


def test_normalize_empty_gives_default_2x2():
    d = TableElement.normalize_data({})
    assert len(d["cells"]) == 2 and len(d["cells"][0]) == 2
    assert d["header_row"] is False and d["header_col"] is False
    assert d["border"] == "grid"


def test_normalize_degenerate_empty_rows_falls_back_to_2x2():
    d = TableElement.normalize_data({"cells": [[], []]})
    assert len(d["cells"]) == 2 and len(d["cells"][0]) == 2


def test_normalize_rectangularises_ragged_without_truncating():
    d = TableElement.normalize_data({"cells": [[_cell("a")], [_cell("b"), _cell("c")]]})
    assert [len(r) for r in d["cells"]] == [2, 2]
    assert d["cells"][0][0]["html"] == "a"          # kept
    assert d["cells"][0][1]["html"] == ""            # padded


def test_normalize_fills_missing_cell_keys():
    d = TableElement.normalize_data({"cells": [[{"html": "x"}]]})
    c = d["cells"][0][0]
    assert c["halign"] == "left" and c["valign"] == "top" and c["html"] == "x"


def test_save_sanitises_each_cell_html():
    el = TableElement(data={"header_row": False, "header_col": False, "border": "grid",
                            "cells": [[_cell("<script>x</script><b>y</b>")]]})
    el.save()
    stored = el.data["cells"][0][0]["html"]
    assert "<script>" not in stored and "<b>y</b>" in stored


def test_save_does_not_raise_on_malformed_cells():
    el = TableElement(data={"cells": "nope"})   # legacy/garbage shape
    el.save()                                    # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_table_model.py -q`
Expected: FAIL (`TableElement` not importable).

- [ ] **Step 3: Add the model**

In `courses/models.py`, append `"tableelement"` to the `ELEMENT_MODELS` list, and add near the other element classes (after `SlideBreakElement`):

```python
class TableElement(ElementBase):
    """Styled table: a JSON grid of {html, halign, valign} cells plus header
    toggles and a border preset. Cell html is sanitised at save()."""

    DEFAULT_BORDER = "grid"
    BORDERS = {"grid", "rows", "header", "none"}
    HALIGN = {"left", "center", "right"}
    VALIGN = {"top", "middle", "bottom"}
    MAX_ROWS = 50
    MAX_COLS = 20

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _cell(raw):
        raw = raw if isinstance(raw, dict) else {}
        h = raw.get("halign")
        v = raw.get("valign")
        return {
            "html": raw.get("html") or "",
            "halign": h if h in TableElement.HALIGN else "left",
            "valign": v if v in TableElement.VALIGN else "top",
        }

    @staticmethod
    def normalize_data(data):
        """Return a well-formed dict for arbitrary stored data: defaults for
        missing top-level keys; ragged rows rectangularised (padded, never
        truncated); non-list rows / non-dict cells coerced; and a
        degenerate-collapse guard to the default 2x2 when height or width is 0."""
        data = data if isinstance(data, dict) else {}
        rows = data.get("cells")
        rows = rows if isinstance(rows, list) else []
        rows = [r if isinstance(r, list) else [] for r in rows]
        width = max((len(r) for r in rows), default=0)
        if not rows or width == 0:
            rows = [[{}, {}], [{}, {}]]          # default 2x2
            width = 2
        cells = [
            [TableElement._cell(r[i] if i < len(r) else {}) for i in range(width)]
            for r in rows
        ]
        border = data.get("border")
        return {
            "header_row": bool(data.get("header_row")),
            "header_col": bool(data.get("header_col")),
            "border": border if border in TableElement.BORDERS else TableElement.DEFAULT_BORDER,
            "cells": cells,
        }

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    @staticmethod
    def _sanitized_data(data):
        """Sanitise every cell's html in place, reading defensively so a
        malformed legacy shape cannot raise. The real write paths (form, import)
        normalise first; this is defense-in-depth for all paths."""
        if not isinstance(data, dict):
            return data
        rows = data.get("cells")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, list):
                    continue
                for cell in row:
                    if isinstance(cell, dict):
                        cell["html"] = sanitize_cell(cell.get("html", ""))
        return data
```

Add the import at the top of `courses/models.py` alongside the existing `from courses.sanitize import sanitize_html`:

```python
from courses.sanitize import sanitize_cell
```

- [ ] **Step 4: Create the migration**

Create `courses/migrations/0033_tableelement_alter_element_content_type.py` (mirror `0032`; the `AlterField` `model__in` list is the full `ELEMENT_MODELS` WITH `"tableelement"` appended):

```python
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("courses", "0032_slidebreakelement_alter_element_content_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="TableElement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data", models.JSONField(default=dict)),
            ],
            options={"abstract": False},
        ),
        migrations.AlterField(
            model_name="element",
            name="content_type",
            field=models.ForeignKey(
                limit_choices_to={"app_label": "courses", "model__in": [
                    "textelement", "imageelement", "videoelement", "iframeelement",
                    "mathelement", "htmlelement", "choicequestionelement",
                    "shorttextquestionelement", "extendedresponsequestionelement",
                    "shortnumericquestionelement", "fillblankquestionelement",
                    "dragfillblankquestionelement", "matchpairquestionelement",
                    "dragtoimagequestionelement", "slidebreakelement", "tableelement",
                ]},
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
    ]
```

Then verify no drift: `uv run python manage.py makemigrations --check --dry-run courses` must report no changes (if it wants a migration, reconcile field defs).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_table_model.py -q`
Expected: PASS (6).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check courses/models.py courses/migrations/0033_tableelement_alter_element_content_type.py tests/test_table_model.py
uv run ruff format courses/models.py courses/migrations/0033_tableelement_alter_element_content_type.py tests/test_table_model.py
git add courses/models.py courses/migrations/0033_tableelement_alter_element_content_type.py tests/test_table_model.py
git commit -m "feat(table): TableElement model, normalize_data, save-sanitise, migration"
```

---

### Task 3: Render template + `render()`

Student-facing `<table>`. Header cells become `<th>`; the corner is a scope-less `<th>`; alignment via `ta-*`/`va-*` classes; border preset via a wrapper class; math stays as raw `\(...\)` text (typeset client-side in Task 8). Normalisation happens in Python before the template.

**Files:**
- Create: `templates/courses/elements/tableelement.html`
- Modify: `courses/models.py` (`TableElement.render()`)
- Test: `tests/test_table_render.py` (create)

**Interfaces:**
- Consumes: `TableElement.normalize_data` (Task 2).
- Produces: rendered html with `class="el el--table el--table--border-<border>"`, `<th>` placement, `ta-*`/`va-*` cell classes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_render.py`:

```python
import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _grid(rows, cols, **top):
    cells = [[{"html": f"r{r}c{c}", "halign": "left", "valign": "top"}
              for c in range(cols)] for r in range(rows)]
    return {"header_row": False, "header_col": False, "border": "grid",
            "cells": cells, **top}


def test_renders_table_with_overflow_wrapper():
    html = TableElement(data=_grid(2, 2)).render()
    assert "el--table" in html and "<table" in html
    assert "el--table--border-grid" in html


def test_header_row_makes_first_row_th_scope_col():
    html = TableElement(data=_grid(2, 2, header_row=True)).render()
    assert 'scope="col"' in html


def test_header_col_makes_first_col_th_scope_row():
    html = TableElement(data=_grid(2, 2, header_col=True)).render()
    assert 'scope="row"' in html


def test_corner_th_has_no_scope():
    html = TableElement(data=_grid(2, 2, header_row=True, header_col=True)).render()
    # The (0,0) corner is a <th> with NO scope attribute.
    assert "<th>r0c0</th>" in html.replace(" ", " ")


def test_alignment_classes_emitted():
    d = _grid(1, 1)
    d["cells"][0][0].update(halign="center", valign="middle")
    html = TableElement(data=d).render()
    assert "ta-center" in html and "va-middle" in html


def test_border_header_both_toggles_off_is_noop_not_error():
    html = TableElement(data=_grid(2, 2, border="header")).render()
    assert "el--table--border-header" in html   # renders, no exception


def test_math_left_as_raw_text_for_client_typeset():
    d = _grid(1, 1)
    d["cells"][0][0]["html"] = r"\(x\)"
    html = TableElement(data=d).render()
    assert r"\(x\)" in html
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_render.py -q`
Expected: FAIL (no `render` output / template missing).

- [ ] **Step 3: Implement `render()` + template**

In `courses/models.py`, add to `TableElement`:

```python
    def render(self):
        from django.template.loader import render_to_string

        data = self.normalize_data(self.data)
        return render_to_string("courses/elements/tableelement.html",
                                {"el": self, "data": data})
```

Create `templates/courses/elements/tableelement.html`:

```django
{% comment %}Student-facing table. Normalised `data` is passed from render();
cell html is already sanitised at save() and emitted with |safe. Math stays as
raw \(...\) text — typeset client-side by math.js over .el--table.{% endcomment %}
<div class="el el--table el--table--border-{{ data.border }}"
     {% if data.header_row %}data-header-row{% endif %}
     {% if data.header_col %}data-header-col{% endif %}>
  <div class="el--table__scroll">
    <table>
      {% for row in data.cells %}
      <tr>
        {% for cell in row %}
          {% if forloop.parentloop.first and data.header_row and forloop.first and data.header_col %}
            <th class="ta-{{ cell.halign }} va-{{ cell.valign }}">{{ cell.html|safe }}</th>
          {% elif forloop.parentloop.first and data.header_row %}
            <th scope="col" class="ta-{{ cell.halign }} va-{{ cell.valign }}">{{ cell.html|safe }}</th>
          {% elif forloop.first and data.header_col %}
            <th scope="row" class="ta-{{ cell.halign }} va-{{ cell.valign }}">{{ cell.html|safe }}</th>
          {% else %}
            <td class="ta-{{ cell.halign }} va-{{ cell.valign }}">{{ cell.html|safe }}</td>
          {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_render.py -q`
Expected: PASS (7). If `test_corner_th_has_no_scope` is whitespace-fragile, assert `"<th>r0c0"` substring instead.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/models.py tests/test_table_render.py
uv run ruff format courses/models.py tests/test_table_render.py
git add courses/models.py templates/courses/elements/tableelement.html tests/test_table_render.py
git commit -m "feat(table): student-facing render template with header/align/border"
```

---

### Task 4: `TableElementForm` + `FORM_FOR_TYPE` + validation

Validation is authoritative here (shape, cap rejection, enum coercion, JSON-parse errors); html sanitisation is guaranteed at `save()` (Task 2), NOT re-run in `clean`.

**Files:**
- Modify: `courses/element_forms.py` (add `TableElementForm`; add `"table"` to `FORM_FOR_TYPE`)
- Test: `tests/test_table_form.py` (create)

**Interfaces:**
- Consumes: `TableElement` (Task 2).
- Produces: `FORM_FOR_TYPE["table"] = TableElementForm`; binds a single field `data`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_form.py`:

```python
import json

import pytest

from courses.element_forms import FORM_FOR_TYPE

pytestmark = pytest.mark.django_db

TableForm = FORM_FOR_TYPE["table"]


def _payload(rows=1, cols=1):
    cells = [[{"html": "x", "halign": "left", "valign": "top"} for _ in range(cols)]
             for _ in range(rows)]
    return {"header_row": False, "header_col": False, "border": "grid", "cells": cells}


def _bound(data_obj):
    return TableForm(data={"data": json.dumps(data_obj)})


def test_valid_payload_is_valid():
    assert _bound(_payload()).is_valid()


def test_unparseable_json_is_form_error_not_crash():
    f = TableForm(data={"data": "{not json"})
    assert not f.is_valid()


def test_ragged_cells_rejected():
    p = _payload(2, 2)
    p["cells"][0] = p["cells"][0][:1]   # ragged
    assert not _bound(p).is_valid()


def test_over_cap_rejected():
    assert not _bound(_payload(rows=51, cols=1)).is_valid()
    assert not _bound(_payload(rows=1, cols=21)).is_valid()


def test_out_of_range_enums_coerced_to_defaults():
    p = _payload()
    p["border"] = "zigzag"
    p["cells"][0][0]["halign"] = "sideways"
    f = _bound(p)
    assert f.is_valid()
    assert f.cleaned_data["data"]["border"] == "grid"
    assert f.cleaned_data["data"]["cells"][0][0]["halign"] == "left"


def test_empty_data_object_normalises_to_default_2x2():
    f = _bound({})
    assert f.is_valid()
    assert len(f.cleaned_data["data"]["cells"]) == 2
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_form.py -q`
Expected: FAIL (`KeyError: 'table'`).

- [ ] **Step 3: Implement the form**

In `courses/element_forms.py`, add (near the other element forms; reuse the file's existing `forms`, `_`, and add `from courses.models import TableElement` to the model imports if not present):

```python
class TableElementForm(forms.ModelForm):
    class Meta:
        model = TableElement
        fields = ["data"]

    def clean_data(self):
        data = self.cleaned_data.get("data")
        if not isinstance(data, dict):
            raise forms.ValidationError(_("Invalid table data."))
        rows = data.get("cells")
        if not isinstance(rows, list) or not rows:
            raise forms.ValidationError(_("A table needs at least one cell."))
        widths = {len(r) if isinstance(r, list) else -1 for r in rows}
        if widths == {0} or -1 in widths:
            raise forms.ValidationError(_("A table needs at least one cell."))
        if len(widths) != 1:
            raise forms.ValidationError(_("All table rows must have the same number of cells."))
        n_rows, n_cols = len(rows), next(iter(widths))
        if n_rows > TableElement.MAX_ROWS or n_cols > TableElement.MAX_COLS:
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": TableElement.MAX_ROWS, "c": TableElement.MAX_COLS}
            )
        # Coerce enums / fill cell defaults (does not resize a valid grid).
        return TableElement.normalize_data(data)
```

`JSONField` (the model field) already parses the hidden field's JSON string and raises a clean `ValidationError` on unparseable input, so `clean_data` only sees a parsed value.

Add `"table": TableElementForm,` to the `FORM_FOR_TYPE` dict.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_form.py -q`
Expected: PASS (6).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/element_forms.py tests/test_table_form.py
uv run ruff format courses/element_forms.py tests/test_table_form.py
git add courses/element_forms.py tests/test_table_form.py
git commit -m "feat(table): TableElementForm validation + FORM_FOR_TYPE registration"
```

---

### Task 5: Manage-UI plumbing (labels, add-menu, icon, dispatch allow-lists)

Wire `table` into the authoring dispatch and list UI so it can be added, saved, labelled, and summarised.

**Files:**
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`; `element_add` + `element_save` allow-tuples)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`; `element_summary`)
- Modify: `templates/courses/manage/editor/_add_menu.html` (Content-group card)
- Modify: `templates/courses/manage/_icon_sprite.html` (add `<symbol id="el-table">`)
- Test: `tests/test_table_manage_plumbing.py` (create)

**Interfaces:**
- Consumes: `TableElement`. Produces: `element_summary(TableElement)` → e.g. `"3×4 table"`; add/save accept `type=table`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_manage_plumbing.py`:

```python
import pytest

from courses.models import TableElement
from courses.templatetags.courses_manage_extras import element_summary

pytestmark = pytest.mark.django_db


def test_element_summary_reports_dimensions():
    el = TableElement(data=TableElement.normalize_data({"cells": [[{}, {}, {}],
                                                                   [{}, {}, {}]]}))
    assert element_summary(el) == "2×3 table"


def test_add_menu_exposes_table_card(client, django_user_model):
    # Follow the existing builder-view test setup in tests/test_element_add_save.py
    # for auth + a unit; assert the add-menu template includes the table card.
    from django.template.loader import render_to_string
    html = render_to_string("courses/manage/editor/_add_menu.html")
    assert 'data-add-type="table"' in html
    assert "#el-table" in html
```

Also add, following the auth/setup pattern already in `tests/test_element_add_save.py`, two assertions that `element_add` and `element_save` accept `type=table` (POST returns non-400). Mirror that file's existing helper/fixtures exactly rather than inventing new ones.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_manage_plumbing.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`courses/views_manage.py`: add `"table": gettext_lazy("Table"),` to `_EDITOR_TYPE_LABELS`, and add `"table",` to BOTH the `element_add` allowed-tuple (line ~844) and the `element_save` allowed-tuple (line ~874).

`courses/templatetags/courses_manage_extras.py`: add `"tableelement": _("Table"),` to `_ELEMENT_LABELS`, and add a branch to `element_summary` before the `stem` fallback:

```python
    if name == "TableElement":
        d = TableElement.normalize_data(el.data)
        rows, cols = len(d["cells"]), len(d["cells"][0])
        return f"{rows}×{cols} table"
```

Add `from courses.models import TableElement` to that module's imports (it already imports `ContentNode` from `courses.models`).

`templates/courses/manage/editor/_add_menu.html`: add to the Content group (after the `html` card):

```django
      <button type="button" class="typecard" data-add-type="table"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-table"/></svg>{% trans "Table" %}</button>
```

`templates/courses/manage/_icon_sprite.html`: add a monochrome `currentColor` line-SVG symbol (match the existing `.ic` symbols' `viewBox`/stroke conventions — open the file and mirror a neighbouring `<symbol>`):

```svg
<symbol id="el-table" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="1"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="4" x2="9" y2="20"/></symbol>
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_manage_plumbing.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_table_manage_plumbing.py
uv run ruff format courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_table_manage_plumbing.py
git add courses/views_manage.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html tests/test_table_manage_plumbing.py
git commit -m "feat(table): manage-UI plumbing (labels, add-menu card, icon, dispatch)"
```

---

### Task 6: Editor partial `_edit_table.html` (server-rendered grid + controls)

Auto-included by `_host_form.html` via `type_key`. Renders the normalised grid and controls server-side; the hidden `data` field is the sole authoritative form input (controls are name-less JS UI). `table_editor.js` (Task 7) enhances it.

**Files:**
- Create: `templates/courses/manage/editor/_edit_table.html`
- Modify (maybe): `courses/views_manage.py` `_render_open_form` only if it needs to pass normalised `data` into context — prefer exposing it via the form/instance so the template reads `form.instance` + `TableElement.normalize_data`. Add a `normalized_data` property to `TableElement` for template access (zero-arg).
- Test: `tests/test_table_editor_partial.py` (create)

**Interfaces:**
- Consumes: `TableElement.normalize_data`; the bound form (`form.data`/`form.instance.data`).
- Produces: DOM contract for Task 7 — `[data-table-editor]` root, `input[type=hidden][name="data"]`, `[data-table-grid]`, cells `td[contenteditable][data-halign][data-valign]`, controls `[data-th-row]`/`[data-th-col]`/`[data-border]`.

- [ ] **Step 1: Add the zero-arg seam + write the failing test**

Add to `TableElement` (Task 2 file):

```python
    @property
    def normalized_data(self):
        return self.normalize_data(self.data)
```

Create `tests/test_table_editor_partial.py`:

```python
import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _render(instance):
    form = FORM_FOR_TYPE["table"](instance=instance)
    return render_to_string("courses/manage/editor/_edit_table.html",
                            {"form": form, "type_key": "table"})


def test_new_table_renders_default_2x2_grid():
    html = _render(TableElement())          # data == {} -> normalises to 2x2
    assert "data-table-editor" in html
    assert html.count("contenteditable") >= 4


def test_existing_table_reflects_stored_border_and_headers():
    el = TableElement(data=TableElement.normalize_data(
        {"border": "rows", "header_row": True, "cells": [[{"html": "hi"}]]}))
    html = _render(el)
    assert "hi" in html
    assert 'value="rows"' in html or "selected" in html   # border reflected
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_editor_partial.py -q`
Expected: FAIL (template missing).

- [ ] **Step 3: Implement the partial**

Create `templates/courses/manage/editor/_edit_table.html`:

```django
{% load i18n %}
{% comment %}Table editor. The hidden name="data" field (bound to the form) is the
SOLE authoritative input; the controls strip and grid are name-less JS UI that
table_editor.js mirrors into it. Grid + controls are server-rendered from the
normalised stored data so an existing table shows its saved state.{% endcomment %}
{% with d=form.instance.normalized_data %}
<div class="el-editor el-editor--table" data-table-editor>
  <input type="hidden" name="data" value="{{ form.data.data|default:'' }}">

  <div class="table-editor__controls">
    <label><input type="checkbox" data-th-row {% if d.header_row %}checked{% endif %}> {% trans "Header row" %}</label>
    <label><input type="checkbox" data-th-col {% if d.header_col %}checked{% endif %}> {% trans "Header column" %}</label>
    <label>{% trans "Borders" %}
      <select data-border>
        <option value="grid" {% if d.border == "grid" %}selected{% endif %}>{% trans "Grid" %}</option>
        <option value="rows" {% if d.border == "rows" %}selected{% endif %}>{% trans "Rows" %}</option>
        <option value="header" {% if d.border == "header" %}selected{% endif %}>{% trans "Header only" %}</option>
        <option value="none" {% if d.border == "none" %}selected{% endif %}>{% trans "None" %}</option>
      </select>
    </label>
  </div>

  <div class="table-editor__toolbar" data-table-toolbar hidden>
    <button type="button" data-cmd="bold" title="{% trans 'Bold' %}"><b>B</b></button>
    <button type="button" data-cmd="italic" title="{% trans 'Italic' %}"><i>I</i></button>
    <button type="button" data-cmd="underline" title="{% trans 'Underline' %}"><u>U</u></button>
    <button type="button" data-cmd="math" title="{% trans 'Insert math' %}">∑</button>
    <span class="table-editor__aligns">
      <button type="button" data-halign="left" title="{% trans 'Align left' %}">⇤</button>
      <button type="button" data-halign="center" title="{% trans 'Align center' %}">⇔</button>
      <button type="button" data-halign="right" title="{% trans 'Align right' %}">⇥</button>
      <button type="button" data-valign="top" title="{% trans 'Align top' %}">⤒</button>
      <button type="button" data-valign="middle" title="{% trans 'Align middle' %}">⇕</button>
      <button type="button" data-valign="bottom" title="{% trans 'Align bottom' %}">⤓</button>
    </span>
  </div>

  <div class="table-editor__grid" data-table-grid>
    <table>
      {% for row in d.cells %}
      <tr>
        {% for cell in row %}
        <td contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}">{{ cell.html|safe }}</td>
        {% endfor %}
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
{% endwith %}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_editor_partial.py -q`
Expected: PASS (2).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/models.py tests/test_table_editor_partial.py
uv run ruff format courses/models.py tests/test_table_editor_partial.py
git add courses/models.py templates/courses/manage/editor/_edit_table.html tests/test_table_editor_partial.py
git commit -m "feat(table): server-rendered editor partial + normalized_data seam"
```

---

### Task 7: Editor JS `table_editor.js` + e2e

Progressive enhancement: focus a cell → show the pinned toolbar; B/I/U via `execCommand` (with `styleWithCSS=false` and `mousedown` `preventDefault`); align buttons set `data-halign`/`data-valign`; insert-math captures/restores the cell `Range` around `window.libliMathInput.open`; Enter inserts `<br>`; row/col add/delete with 1×1 floor and 50×20 ceiling; every mutation re-serialises the grid into the hidden `data` field.

**Files:**
- Create: `courses/static/courses/js/table_editor.js`
- Modify: `templates/courses/manage/editor/editor.html` (or wherever editor JS is loaded) to include the script — mirror how `text_toolbar.js` is loaded, and call the init on the editor-open hook the way `editor.js` calls `window.libliInitRte` after fragment swaps.
- Test: `tests/test_e2e_table_editor.py` (create) — Playwright, driving the real UI.

**Interfaces:**
- Consumes: DOM contract from Task 6; `window.libliMathInput.open(cb)`.
- Produces: `window.libliInitTableEditor(root)` (called on load + after editor fragment swap, mirroring `libliInitRte`).

- [ ] **Step 1: Write the failing e2e test**

Create `tests/test_e2e_table_editor.py`, mirroring the fixtures/harness in `tests/test_e2e_builder_authoring.py` (same login via `TEST_PASSWORD`, same page objects). Drive the REAL gestures:

```python
# Mirror tests/test_e2e_builder_authoring.py for app/server/login fixtures.
# Scenario (real gestures, no page.evaluate shortcuts):
#   1. Log in as a course manager; open a lesson unit's builder.
#   2. Click the "Table" add card; the editor opens with a 2x2 grid.
#   3. Click a cell, type "a<b" then \(x<5\); click Bold; click align-center.
#   4. Add a row via the insert handle; Save.
#   5. Reopen the element: assert the stored value round-trips
#      (cell shows a<b, math preserved as \(x<5\), alignment center, 3 rows).
#   6. Open the unit as a student: assert the table renders and \(x<5\) typesets
#      (a .katex node appears inside .el--table).
```

Also assert the double-escape guard explicitly: after typing `\(a<b\)` and saving, the persisted `TableElement.data` cell html equals `\(a&lt;b\)` (single-escaped), fetched from the DB in the test — this is the editor-path serialization guard the spec calls out.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_e2e_table_editor.py -q`
Expected: FAIL (no editor behaviour yet).

- [ ] **Step 3: Implement `table_editor.js`**

Create `courses/static/courses/js/table_editor.js` (vanilla IIFE, mirroring `text_toolbar.js` structure). It must:

- `initTableEditor(root)`: for each `[data-table-editor]`, wire the grid, toolbar, controls, and do an initial `serialize()`. Expose `window.libliInitTableEditor`. Call it at load and export it so `editor.js` can call it after a fragment swap (same place it calls `window.libliInitRte`).
- Track the focused cell (`focusin` on `td[contenteditable]`); show/position `[data-table-toolbar]`; reflect the focused cell's `data-halign`/`data-valign` in the align buttons' active state.
- Toolbar buttons: `mousedown` → `e.preventDefault()` (keep caret/selection). `click` handlers:
  - `data-cmd="bold|italic|underline"`: `document.execCommand("styleWithCSS", false, false); document.execCommand(cmd, false, null);` then `serialize()`.
  - `data-cmd="math"`: capture `window.getSelection().getRangeAt(0)` for the focused cell BEFORE calling `window.libliMathInput.open(function(latex){ ... })`; in the callback, restore the range and insert a text node `"\\(" + latex + "\\)"`, then `serialize()`.
  - `data-halign`/`data-valign` buttons: set the attribute + `ta-*`/`va-*` class on the focused cell; `serialize()`.
- Grid `keydown`: Enter (no shift) → `e.preventDefault(); document.execCommand("insertHTML", false, "<br>");` so the only intra-cell separator is `<br>`.
- Controls: `[data-th-row]`/`[data-th-col]` change → `serialize()`; `[data-border]` change → `serialize()`.
- Row/column add & delete handles (hover affordances on row/column edges): insert/remove `<tr>`/column cells. New cells created with `data-halign="left" data-valign="top"` and empty content and `contenteditable`. Disable/hide delete at 1 row/1 col; disable/hide insert/append at 50 rows/20 cols.
- `serialize()`: build `{header_row, header_col, border, cells}` where each cell = `{html: td.innerHTML, halign: td.dataset.halign||"left", valign: td.dataset.valign||"top"}`; write `JSON.stringify(...)` into the hidden `input[name="data"]`. `td.innerHTML` returns the RAW pre-typeset source (cells are never typeset in place), so a typed `<` serialises as `&lt;` — the server sanitiser canonicalises it (Task 1).

Keep the file focused; no math typesetting of editable cells anywhere.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_e2e_table_editor.py -q`
Expected: PASS. (If the repo gates e2e behind a marker/env, follow the same gating `tests/test_e2e_builder_authoring.py` uses.)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_e2e_table_editor.py
uv run ruff format tests/test_e2e_table_editor.py
git add courses/static/courses/js/table_editor.js templates/courses/manage/editor/editor.html tests/test_e2e_table_editor.py
git commit -m "feat(table): WYSIWYG editor JS (toolbar, align, math, rows/cols) + e2e"
```

---

### Task 8: Math consumption wiring (`math.js` + `has_math`)

Make cell math typeset on the student view and ensure KaTeX loads. Table cells join the inline pass; `has_math` gains a `TableElement` branch at the lesson AND quiz consumption sites. The results page (`quiz_results`, ~line 682) renders ONLY question rows (`if not isinstance(q, QuestionElement): continue`) — it never renders a table, so it is intentionally excluded (no branch there).

**Files:**
- Modify: `courses/static/courses/js/math.js` (add `.el--table` to `renderInlineText`)
- Modify: `courses/views.py` (`has_math` at ~line 140 lesson; ~line 468 quiz)
- Test: `tests/test_table_has_math.py` (create); plus a JS-covered consumption assertion already in Task 7's e2e.

**Interfaces:**
- Consumes: `has_math_delimiters` (`courses/htmlsandbox.py`); `TableElement`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_has_math.py`. Mirror the context-building test setup used by existing `has_math` tests (search `tests/` for `has_math`); assert:

```python
# For a LESSON unit containing a TableElement whose cell html has "\(x\)":
#   build_lesson_context(...)["has_math"] is True
# For a lesson table with no delimiters: has_math is False
# For a QUIZ unit containing such a table: the quiz context's has_math is True
```

Use `TableElement.normalize_data({"cells": [[{"html": r"\(x\)"}]]})` for the math case.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_has_math.py -q`
Expected: FAIL (has_math False for the table cases).

- [ ] **Step 3: Implement**

`courses/static/courses/js/math.js` — in `renderInlineText`, broaden the selector so tables are covered:

```javascript
    (root || document).querySelectorAll(".el--text, .el--table").forEach(function (el) {
```

`courses/views.py` — add a helper near `_question_has_math`:

```python
def _table_has_math(el):
    from courses.models import TableElement

    if not isinstance(el, TableElement):
        return False
    data = el.normalize_data(el.data)
    return any(
        has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )
```

Then extend BOTH `has_math` expressions (lesson ~140 and quiz ~468) with an extra `or any(_table_has_math(el.content_object) for el in elements)` term.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_has_math.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views.py tests/test_table_has_math.py
uv run ruff format courses/views.py tests/test_table_has_math.py
git add courses/static/courses/js/math.js courses/views.py tests/test_table_has_math.py
git commit -m "feat(table): typeset cell math client-side + has_math gating (lesson+quiz)"
```

---

### Task 9: Transfer export / validate / import

Round-trip a table through course export/import. Import persists via `TableElement.save()` (so cell html is sanitised even though the builder bypasses the form); the validator rejects over-cap and malformed shapes.

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_table` + `SERIALIZERS["table"]`)
- Modify: `courses/transfer/payloads.py` (`_val_table` + `VALIDATORS["table"]`)
- Modify: `courses/transfer/importer.py` (`_build_table` + `BUILDERS["table"]`)
- Test: `tests/test_table_transfer.py` (create)

**Interfaces:**
- Transfer key is `"table"`. Consumes `TableElement`, `_clean_save` (importer), the payload check helpers (`payloads.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_transfer.py`:

```python
import pytest

from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS

pytestmark = pytest.mark.django_db


def test_table_registered_in_all_three_registries():
    assert "table" in SERIALIZERS and "table" in VALIDATORS and "table" in BUILDERS


def test_import_sanitises_cell_html():
    data = {"header_row": False, "header_col": False, "border": "grid",
            "cells": [[{"html": "<script>x</script><b>y</b>", "halign": "left", "valign": "top"}]]}
    el, _children = BUILDERS["table"](data, {})
    assert "<script>" not in el.data["cells"][0][0]["html"]
    assert "<b>y</b>" in el.data["cells"][0][0]["html"]


def test_validator_rejects_over_cap():
    big = {"border": "grid", "header_row": False, "header_col": False,
           "cells": [[{"html": "", "halign": "left", "valign": "top"}] for _ in range(51)]}
    # _val_table signature mirrors the others: (data, elid, media_kinds)
    with pytest.raises(Exception):
        VALIDATORS["table"](big, "el1", {})
```

Also add a full course export→import round-trip test mirroring `tests/test_e2e_transfer.py` / the transfer unit tests: build a course with a `TableElement` (headers, border, per-cell alignment, math cell), export, import into a fresh course, assert an equivalent `TableElement` (border, header flags, alignments, cell html incl. `\(x<5\)` preserved).

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_transfer.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`courses/transfer/export.py` — add serialiser + registry entry (import `TableElement`):

```python
def _ser_table(el, ids):
    return {"data": el.data}
```

Add `"table": (TableElement, _ser_table),` to `SERIALIZERS`.

`courses/transfer/payloads.py` — add a validator mirroring the others' helper style (`_exact_keys`/`check_str`/isinstance checks already used in this file); it must check `data` is a dict, `cells` is a non-empty rectangular list within the 50×20 cap, enums are within range OR coercible, and each cell has string `html`. Register `"table": _val_table` in `VALIDATORS`. Reject (raise the module's validation error) on over-cap and ragged/empty.

`courses/transfer/importer.py` — add builder + registry entry (import `TableElement`):

```python
def _build_table(data, assets):
    normalized = TableElement.normalize_data(data)
    return _clean_save(TableElement(data=normalized)), ()
```

`_clean_save` calls `full_clean` + `save`; `save()` sanitises the cell html (Task 2), so import is safe. Add `"table": _build_table,` to `BUILDERS`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_table_transfer.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_table_transfer.py
uv run ruff format courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_table_transfer.py
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_table_transfer.py
git commit -m "feat(table): course export/validate/import round-trip (sanitise-on-import)"
```

---

### Task 10: Basic CSS + i18n catalogs

Functional styling for the four border presets, header emphasis, alignment classes, and the mobile scroll wrapper — plus editor-chrome basics (toolbar, controls, hover handles). This is intentionally BASIC; the polished visual pass comes afterward via the `frontend-design` skill (a separate step, not in this plan). Then compile EN/PL message catalogs for the new strings.

**Files:**
- Modify/Create: the elements stylesheet (find where `el--image`/`el--text` are styled — likely `courses/static/courses/css/*.css`) and the manage/editor stylesheet; add `.el--table`, `.el--table__scroll`, `.el--table--border-*`, `.ta-*`, `.va-*`, header emphasis via `[data-header-row]`/`[data-header-col]`, and `.el-editor--table` / `.table-editor__*` chrome.
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ `.mo`)
- Test: `tests/test_table_css.py` (create; mirror `tests/test_consumption_css.py` if it asserts presence of element styles)

**Interfaces:** none exported.

- [ ] **Step 1: Write the failing test**

Create `tests/test_table_css.py` mirroring `tests/test_consumption_css.py`'s approach (it checks the compiled stylesheet contains selectors for each element). Assert the stylesheet contains `.el--table`, `.el--table--border-grid`, `.el--table--border-rows`, `.el--table--border-header`, `.el--table--border-none`, `.ta-center`, `.va-middle`.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_table_css.py -q`
Expected: FAIL.

- [ ] **Step 3: Add the CSS**

Add a table section to the elements stylesheet (use the design token variables the file already uses for borders/spacing — grep the file for `--border`/`--space` tokens; do not hardcode colors):

```css
.el--table__scroll { overflow-x: auto; }
.el--table table { border-collapse: collapse; width: 100%; }
.el--table th, .el--table td { padding: var(--space-2, .5rem); }
.el--table--border-grid th, .el--table--border-grid td { border: 1px solid var(--border-default); }
.el--table--border-rows tr + tr th, .el--table--border-rows tr + tr td { border-top: 1px solid var(--border-default); }
.el--table--border-none th, .el--table--border-none td { border: 0; }
.el--table[data-header-row] tr:first-child th { border-bottom: 2px solid var(--border-strong); font-weight: 600; }
.el--table[data-header-col] tr th:first-child { border-right: 2px solid var(--border-strong); font-weight: 600; }
.ta-left { text-align: left; } .ta-center { text-align: center; } .ta-right { text-align: right; }
.va-top { vertical-align: top; } .va-middle { vertical-align: middle; } .va-bottom { vertical-align: bottom; }
```

Add matching basic editor chrome CSS (`.table-editor__toolbar`, `.table-editor__controls`, cell focus outline, hover insert/delete handles). Keep it functional.

- [ ] **Step 4: Compile catalogs + run tests**

```bash
uv run python manage.py makemessages -l en -l pl
# fill in the Polish translations for: "Table", "Header row", "Header column",
# "Borders", "Grid", "Rows", "Header only", "None", "Bold", "Italic",
# "Underline", "Insert math", and the align tooltips.
uv run python manage.py compilemessages
uv run pytest tests/test_table_css.py -q
```

Expected: catalogs compile; CSS test PASS. (Watch the makemessages fuzzy-flag gotcha — remove stray `#, fuzzy` on newly-filled entries.)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_table_css.py
uv run ruff format tests/test_table_css.py
git add courses/static/courses/css tests/test_table_css.py locale/
git commit -m "feat(table): basic element + editor CSS and EN/PL catalogs"
```

---

### Task 11: Full-suite regression + collectstatic sanity

**Files:** none (verification task).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: PASS (all prior tests + the ~9 new test modules). Investigate any failure — likely candidates: a `has_math` test that now sees a table, an element-count test, or an i18n `no-obsolete` catalog test (run the i18n catalog tests explicitly since Task 10 touched catalogs).

- [ ] **Step 2: Lint the whole change**

Run: `uv run ruff check .` and `uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Static + migration sanity**

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py collectstatic --no-input
```

Expected: no missing migration; `table_editor.js` collected.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test(table): full-suite regression fixes"
```

---

## Self-Review

**Spec coverage:**
- Model + JSON `data` + `ELEMENT_MODELS` + migration → Task 2. ✓
- `normalize_data` (defaults, rectangularise, degenerate guard, cell defaults, zero-arg `normalized_data`) → Tasks 2 & 6. ✓
- Cell sanitiser (`CELL_TAGS` incl b/i; math canonicalise unescape-once-then-escape-once; nonce placeholder; unmatched delimiters; XSS-inert; idempotent) → Task 1. ✓
- Sanitisation at `save()`, validation in form → Tasks 2 & 4. ✓
- Render template (overflow wrapper, `<th>` placement, corner no-scope, `ta-*`/`va-*`, border presets, header both-off no-op, math raw) → Task 3. ✓
- Form (shape, cap reject, enum coerce, JSON-parse error) → Task 4. ✓
- Manage plumbing (`_EDITOR_TYPE_LABELS`, `element_add`/`element_save`, `_ELEMENT_LABELS`, `element_summary`, add-menu card, icon) → Task 5. ✓
- Editor partial (server-rendered controls+grid from normalised data; name-less controls; hidden `data` authoritative) → Task 6. ✓
- Editor JS (focus toolbar, own execCommand B/I/U, styleWithCSS=false, mousedown preventDefault, math Range capture/restore, inline `\(...\)` only, Enter→`<br>`, data-halign/valign, 1×1 floor / 50×20 ceiling, serialise raw innerHTML) + real-UI e2e incl. single-escape guard → Task 7. ✓
- Math consumption (`math.js` `.el--table`; `has_math` lesson+quiz; results page excluded because it renders only question rows) → Task 8. ✓
- Transfer (export/validate/import; sanitise-on-import via save; over-cap reject; round-trip incl `\(x<5\)`) → Task 9. ✓
- Basic CSS + EN/PL i18n; frontend-design polish deferred → Task 10. ✓
- Full-suite + i18n catalog + collectstatic → Task 11. ✓

**Placeholder scan:** No TBD/TODO; every code step shows concrete code; test steps show real assertions. Two tasks (5, 7, 9) instruct mirroring an existing test module for fixtures rather than repeating boilerplate — intentional (those harnesses are large and repo-specific).

**Type consistency:** `normalize_data(data)` staticmethod + `normalized_data` property; `sanitize_cell(value)`; `_table_has_math(el)`; transfer key `"table"`; DOM contract (`[data-table-editor]`, `input[name="data"]`, `[data-table-grid]`, `data-halign`/`data-valign`, `[data-th-row]`/`[data-th-col]`/`[data-border]`) consistent across Tasks 6–7. Border/align vocab (`grid|rows|header|none`, `left|center|right`, `top|middle|bottom`) consistent across model/render/form/editor.
