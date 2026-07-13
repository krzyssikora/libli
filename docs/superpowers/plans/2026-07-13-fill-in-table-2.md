# Fill-in Table Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ungraded self-check **Fill-in table** course element — a table whose cells can be fillable inputs, checked server-side with per-cell ✓/✗ feedback and a success/try-again summary, recording no marks.

**Architecture:** A hybrid of two existing elements. Structure + WYSIWYG authoring mirror `TableElement` (a `data` JSON grid, a `ModelForm` with one hidden `data` field mirrored from a contenteditable grid editor, `normalize_data`, `sanitize_cell` at `save()`). The self-check server flow mirrors `SwitchGridElement` (a soft-pk `filltable_check` endpoint returning per-cell correctness JSON, lock-on-success on the client, nothing persisted). Answer cells are marked in the editor via an "Answer cell" toolbar toggle and matched with `courses.marking.blank_matches`.

**Tech Stack:** Django (Python 3, server-rendered templates), vanilla JS (IIFE enhancers, no framework), Playwright (e2e), `uv` for all tooling, Postgres test DB.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run <tool>` (e.g. `uv run pytest`, `uv run ruff format`, `uv run python manage.py …`).
- **Test DB isolation (concurrent worktrees):** this worktree runs alongside others on Postgres `test_libli`. Before running the suite in this worktree, export a unique DB: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'` (→ `test_libli_filltable`). Run pytest with that env set.
- **No hardcoded passwords:** tests use `tests.factories.TEST_PASSWORD`, never a literal (GitGuardian).
- **JS i18n:** `makemessages` does NOT scan `.js`. Every JS-facing string is a server-rendered `{% trans %}` `data-*` attribute read by the JS.
- **New `{% trans %}` / `gettext_lazy` / `_( )` strings** must land in BOTH `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po` (PL translated).
- **Do NOT bump `FORMAT_VERSION`** (transfer/schema.py) — a new element type is additive. DO bump the `len(ELEMENT_MODELS)` assert in `tests/test_transfer_schema.py`.
- **Naming (fixed):** model `FillTableElement` / model_name `filltableelement`; form key & `type_key` `filltable`; transfer key `fill_table`; URL name `filltable_check`, path segment `filltable-check`; JS globals `window.libliInitFillTables` (student) and `window.libliInitFillTableEditor` (editor); student CSS class root `.el--filltable`, editor root `.el-editor--filltable`, widget wrapper `.filltable`.
- **Scope refinement vs spec (deliberate):** the element is **lesson-only**, exactly like its sibling `SwitchGridElement`. The palette card lives in the Interactive group, which is already gated `{% if not unit_is_quiz %}`, so a fill-table cannot be added on a quiz page. The spec's "quiz-unit gating" is therefore **dropped as YAGNI** — there is no reachable path that places a fill-table on a quiz page, so no quiz builder changes are made. All other spec requirements stand.
- **Index-base invariant:** `data-r`/`data-c` (template), `r{row}c{col}` keys (JS), `request.POST.get("r{r}c{c}")` (view), and response `{"r","c"}` are ALL 0-based indices into `normalize_data(data)["cells"]`.
- **Answer must never reach the client:** the student template emits answer cells as EMPTY inputs — no `value=`, no `data-answer`, no inline-JSON dump of `data`.

---

## File Structure

**New files:**
- `courses/filltable.py` — small shared helpers: `split_alternatives`, `is_blank_answer`, `answer_cells` (used by BOTH the form's validation and the check view, so authoring and checking agree).
- `courses/migrations/00XX_filltableelement.py` — auto-generated model migration.
- `templates/courses/elements/filltableelement.html` — student render.
- `templates/courses/manage/editor/_edit_filltable.html` — editor partial.
- `courses/static/courses/js/filltable.js` — student enhancer.
- `courses/static/courses/js/filltable_editor.js` — authoring grid editor.
- `tests/test_filltable_model.py`, `test_filltable_form.py`, `test_filltable_check.py`, `test_filltable_render.py`, `test_filltable_context.py`, `test_filltable_manage_plumbing.py`, `test_filltable_editor_partial.py`, `test_filltable_transfer.py`, `tests/test_e2e_filltable.py`.

**Modified files:**
- `courses/models.py` — `ELEMENT_MODELS` + `FillTableElement`.
- `courses/element_forms.py` — `FillTableElementForm` + `FORM_FOR_TYPE`.
- `courses/views.py` — `filltable_check` + `_fill_table_has_math` + `build_lesson_context` flags.
- `courses/urls.py` — the check route.
- `courses/views_manage.py` — `element_add`/`element_save` allow-tuples + `_EDITOR_TYPE_LABELS`.
- `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS` + `element_summary`.
- `courses/transfer/export.py`, `payloads.py`, `importer.py` — transfer trio.
- `templates/courses/manage/editor/_add_menu.html` — palette card.
- `templates/courses/manage/_icon_sprite.html` — `#el-filltable` icon.
- `templates/courses/manage/editor/editor.html` — two `<script>` includes.
- `templates/courses/lesson_unit.html` — `has_fill_table` script gate.
- `courses/static/courses/js/editor.js` — two re-init calls.
- `courses/static/courses/css/courses.css` — student + editor CSS.
- `tests/test_transfer_schema.py` — count assert 23 → 24.
- `locale/en|pl/LC_MESSAGES/django.po` — new strings.

---

## Task 1: Model — `FillTableElement`, `normalize_data`, migration

**Files:**
- Modify: `courses/models.py` (`ELEMENT_MODELS` ~259–283; add class near `TableElement` ~657)
- Create: `courses/migrations/00XX_filltableelement.py` (via makemigrations)
- Test: `tests/test_filltable_model.py`

**Interfaces:**
- Produces: `FillTableElement(data: JSONField)`; staticmethods `normalize_data(data) -> dict` (keys `header_row, header_col, border, case_sensitive, prompt, cells`; each cell `{"kind":"static","html","halign","valign"}` or `{"kind":"answer","answer","halign","valign"}`), `_cell(raw) -> dict`; `_sanitized_data(data)`; `save()`; `render()`; property `normalized_data`. Constants reuse `TableElement.BORDERS/HALIGN/VALIGN/MAX_ROWS/MAX_COLS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_model.py`:

```python
import pytest
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db


def _cells(nd):
    return nd["cells"]


def test_normalize_defaults_and_degenerate_collapse():
    nd = FillTableElement.normalize_data({})
    assert len(nd["cells"]) == 2 and len(nd["cells"][0]) == 2  # default 2x2
    assert nd["border"] == "grid"
    assert nd["header_row"] is False and nd["header_col"] is False
    assert nd["case_sensitive"] is False
    assert nd["prompt"] == ""
    # every cell has a valid kind
    assert all(c["kind"] in ("static", "answer") for row in nd["cells"] for c in row)


def test_normalize_ragged_rows_padded_not_truncated():
    nd = FillTableElement.normalize_data(
        {"cells": [[{"kind": "static", "html": "a"}], [{"kind": "static", "html": "b"},
                    {"kind": "answer", "answer": "x"}]]}
    )
    assert len(nd["cells"][0]) == 2 and len(nd["cells"][1]) == 2


def test_normalize_unknown_kind_becomes_static():
    nd = FillTableElement.normalize_data({"cells": [[{"kind": "weird", "html": "h"}]]})
    assert nd["cells"][0][0]["kind"] == "static"


def test_normalize_scalar_coercion_never_faults_on_tampered_types():
    nd = FillTableElement.normalize_data(
        {"prompt": 123, "case_sensitive": "yes", "header_row": 1, "border": "dashed",
         "cells": [[{"kind": "answer", "answer": 5}]]}
    )
    assert nd["prompt"] == ""            # non-string prompt -> ""
    assert nd["case_sensitive"] is True  # coerced via bool()
    assert nd["header_row"] is True
    assert nd["border"] == "grid"        # out-of-enum -> default
    assert nd["cells"][0][0]["answer"] == ""  # non-string answer -> ""


def test_save_sanitizes_static_html_and_trims_answer():
    el = FillTableElement(data={"cells": [
        [{"kind": "static", "html": "<script>x</script><b>ok</b>"},
         {"kind": "answer", "answer": "  0,5 | 0.5  "}]]})
    el.save()
    static, answer = el.data["cells"][0][0], el.data["cells"][0][1]
    assert "<script>" not in static["html"] and "<b>ok</b>" in static["html"]
    assert answer["answer"] == "0,5 | 0.5"  # trimmed, not HTML-sanitized


def test_save_preserves_math_in_static_cell():
    el = FillTableElement(data={"cells": [[{"kind": "static", "html": r"\(x<5\)"}]]})
    el.save()
    assert r"\(x<5\)" in el.data["cells"][0][0]["html"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_model.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'FillTableElement'`.

- [ ] **Step 3: Add the model**

In `courses/models.py`, add `"filltableelement",` to the end of the `ELEMENT_MODELS` list (after `"switchgridelement",`). Then add this class immediately after `TableElement` (reuse `TableElement`'s constants):

```python
class FillTableElement(ElementBase):
    """Ungraded self-check table: a JSON grid whose cells are either static
    (rich HTML/math, sanitised at save) or answer cells (a plain accepted-answer
    string). Checked server-side per cell; records no marks, reveals nothing."""

    ANSWER = "answer"
    STATIC = "static"
    # Reuse TableElement's structural caps (TableElement is defined just above).
    MAX_ROWS = TableElement.MAX_ROWS
    MAX_COLS = TableElement.MAX_COLS

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _cell(raw):
        raw = raw if isinstance(raw, dict) else {}
        h = raw.get("halign")
        v = raw.get("valign")
        halign = h if h in TableElement.HALIGN else "left"
        valign = v if v in TableElement.VALIGN else "top"
        if raw.get("kind") == FillTableElement.ANSWER:
            ans = raw.get("answer")
            return {
                "kind": FillTableElement.ANSWER,
                "answer": ans if isinstance(ans, str) else "",
                "halign": halign,
                "valign": valign,
            }
        return {
            "kind": FillTableElement.STATIC,
            "html": raw.get("html") or "",
            "halign": halign,
            "valign": valign,
        }

    @staticmethod
    def normalize_data(data):
        data = data if isinstance(data, dict) else {}
        rows = data.get("cells")
        rows = rows if isinstance(rows, list) else []
        rows = [r if isinstance(r, list) else [] for r in rows]
        width = max((len(r) for r in rows), default=0)
        if not rows or width == 0:
            rows = [[{}, {}], [{}, {}]]  # default 2x2
            width = 2
        cells = [
            [FillTableElement._cell(r[i] if i < len(r) else {}) for i in range(width)]
            for r in rows
        ]
        border = data.get("border")
        prompt = data.get("prompt")
        return {
            "header_row": bool(data.get("header_row")),
            "header_col": bool(data.get("header_col")),
            "case_sensitive": bool(data.get("case_sensitive")),
            "border": border if border in TableElement.BORDERS else TableElement.DEFAULT_BORDER,
            "prompt": prompt.strip() if isinstance(prompt, str) else "",
            "cells": cells,
        }

    @staticmethod
    def _sanitized_data(data):
        """Sanitise static-cell html and trim answer strings, in place, defensively."""
        if not isinstance(data, dict):
            return data
        p = data.get("prompt")
        data["prompt"] = p.strip() if isinstance(p, str) else ""
        rows = data.get("cells")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, list):
                    continue
                for cell in row:
                    if not isinstance(cell, dict):
                        continue
                    if cell.get("kind") == FillTableElement.ANSWER:
                        a = cell.get("answer")
                        cell["answer"] = a.strip() if isinstance(a, str) else ""
                    else:
                        cell["html"] = sanitize_cell(cell.get("html", ""))
        return data

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    def render(self):
        from django.template.loader import render_to_string

        data = self.normalize_data(self.data)
        join = self.elements.order_by("pk").first()
        return render_to_string(
            "courses/elements/filltableelement.html",
            {"el": self, "data": data, "eid": join.pk if join else 0},
        )

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/00XX_filltableelement.py` with one `CreateModel`. Confirm no unrelated changes: `uv run python manage.py makemigrations --check --dry-run` should report nothing further.

- [ ] **Step 5: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_model.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/ tests/test_filltable_model.py
git commit -m "feat(filltable): FillTableElement model + normalize_data + migration"
```

---

## Task 2: Shared helpers + `FillTableElementForm`

**Files:**
- Create: `courses/filltable.py`
- Modify: `courses/element_forms.py` (add form; `FORM_FOR_TYPE` ~1108–1132)
- Test: `tests/test_filltable_form.py`

**Interfaces:**
- Consumes: `FillTableElement.normalize_data` (Task 1).
- Produces: `courses.filltable.split_alternatives(answer: str) -> list[str]` (split on `|`, trim, drop empties); `is_blank_answer(answer: str) -> bool` (True iff `split_alternatives` empty); `answer_cells(cells) -> Iterator[tuple[int,int,str]]` (yield `(r, c, answer)` for every `kind=="answer"` cell). `FillTableElementForm(forms.ModelForm)` with `Meta.model=FillTableElement, fields=["data"]`, `clean_data` returning normalized data and raising distinct `ValidationError`s for *no answer cell* vs *blank answer cell*.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_form.py`:

```python
import pytest
from django import forms
from courses.filltable import split_alternatives, is_blank_answer, answer_cells
from courses.element_forms import FillTableElementForm

pytestmark = pytest.mark.django_db


def test_split_alternatives_trims_and_drops_empties():
    assert split_alternatives("0,5 | 0.5") == ["0,5", "0.5"]
    assert split_alternatives("  a  ") == ["a"]
    assert split_alternatives("") == []
    assert split_alternatives("|") == []          # pipe-only -> no alternatives
    assert split_alternatives("  |  ") == []


def test_is_blank_answer():
    assert is_blank_answer("") is True
    assert is_blank_answer("|") is True
    assert is_blank_answer("x") is False


def _data(cells, **kw):
    d = {"cells": cells}
    d.update(kw)
    return d


def _bind(data_dict):
    import json
    return FillTableElementForm(data={"data": json.dumps(data_dict)})


def test_form_accepts_grid_with_answer_cell():
    f = _bind(_data([[{"kind": "static", "html": "t"},
                      {"kind": "answer", "answer": "4"}]]))
    assert f.is_valid(), f.errors
    nd = f.cleaned_data["data"]
    assert nd["cells"][0][1]["kind"] == "answer"


def test_form_rejects_no_answer_cell_with_distinct_message():
    f = _bind(_data([[{"kind": "static", "html": "a"}, {"kind": "static", "html": "b"}]]))
    assert not f.is_valid()
    assert any("at least one answer cell" in str(e).lower() for e in f.errors["data"])


def test_form_rejects_blank_answer_cell_with_distinct_message():
    f = _bind(_data([[{"kind": "answer", "answer": "|"},
                      {"kind": "static", "html": "b"}]]))
    assert not f.is_valid()
    assert any("blank" in str(e).lower() for e in f.errors["data"])


def test_form_rejects_over_cap_grid():
    from courses.models import FillTableElement
    big = [[{"kind": "answer", "answer": "1"}] for _ in range(FillTableElement.MAX_ROWS + 1)]
    f = _bind(_data(big))
    assert not f.is_valid()
    assert any("limited to" in str(e).lower() for e in f.errors["data"])


def test_answer_cells_iterates_positions():
    nd = FillTableElementForm  # placeholder to keep import used
    cells = [[{"kind": "static"}, {"kind": "answer", "answer": "x"}],
             [{"kind": "answer", "answer": "y"}, {"kind": "static"}]]
    assert list(answer_cells(cells)) == [(0, 1, "x"), (1, 0, "y")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_form.py -x -q`
Expected: FAIL — `ModuleNotFoundError: courses.filltable`.

- [ ] **Step 3: Create `courses/filltable.py`**

```python
"""Shared helpers for the Fill-in table self-check element. Used by BOTH the
form's answer validation and the check view, so authoring and checking agree on
what counts as an alternative and what counts as blank."""


def split_alternatives(answer):
    """Split a stored answer string on '|' into trimmed, non-empty alternatives."""
    if not isinstance(answer, str):
        return []
    return [part.strip() for part in answer.split("|") if part.strip()]


def is_blank_answer(answer):
    """True iff the answer yields zero non-empty alternatives (blank or pipe-only)."""
    return not split_alternatives(answer)


def answer_cells(cells):
    """Yield (row_index, col_index, answer_string) for every answer cell, 0-based."""
    for r, row in enumerate(cells or []):
        if not isinstance(row, list):
            continue
        for c, cell in enumerate(row):
            if isinstance(cell, dict) and cell.get("kind") == "answer":
                yield r, c, cell.get("answer", "")
```

- [ ] **Step 4: Add the form**

In `courses/element_forms.py`, add (near `TableElementForm`), importing `FillTableElement` and `courses.filltable` helpers at the top of the module as the neighbours do:

```python
class FillTableElementForm(forms.ModelForm):
    class Meta:
        model = FillTableElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # JSONField(default=dict) is required=True and {} is an EMPTY_VALUE, so an
        # unedited add would fail "required" before clean_data. Make optional.
        self.fields["data"].required = False

    def clean_data(self):
        from courses.filltable import answer_cells, is_blank_answer

        data = self.cleaned_data.get("data")
        nd = FillTableElement.normalize_data(data if isinstance(data, dict) else {})
        cells = nd["cells"]
        n_rows, n_cols = len(cells), len(cells[0])
        if n_rows > FillTableElement.MAX_ROWS or n_cols > FillTableElement.MAX_COLS:
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": FillTableElement.MAX_ROWS, "c": FillTableElement.MAX_COLS}
            )
        answers = list(answer_cells(cells))
        if not answers:
            raise forms.ValidationError(
                _("Mark at least one answer cell (use the “Answer cell” button).")
            )
        if any(is_blank_answer(ans) for _r, _c, ans in answers):
            raise forms.ValidationError(
                _("An answer cell is blank — type its accepted answer, or make it a normal cell.")
            )
        return nd
```

Add `"filltable": FillTableElementForm,` to `FORM_FOR_TYPE` (after `"table":`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_form.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/filltable.py courses/element_forms.py tests/test_filltable_form.py
git commit -m "feat(filltable): shared answer helpers + FillTableElementForm with distinct validation"
```

---

## Task 3: Check endpoint `filltable_check` + URL route

**Files:**
- Modify: `courses/urls.py` (~39–43, alongside `switchgrid-check`)
- Modify: `courses/views.py` (add view near `switchgrid_check` ~597; imports at 26/32 already present)
- Test: `tests/test_filltable_check.py`

**Interfaces:**
- Consumes: `FillTableElement`, `courses.filltable.answer_cells`/`split_alternatives`, `courses.marking.blank_matches`, `courses.access.can_access_course`.
- Produces: `filltable_check(request, element_pk)` returning `JsonResponse` — `{"cells": [{"r","c","correct"}...], "all_correct": bool}`; empty-set/miss → `{"cells": [], "all_correct": false}`. URL name `courses:filltable_check`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_check.py`. Use existing factories (`tests/factories.py`: `make_verified_user`, `add_element`, `TEST_PASSWORD`); model the fixtures on `tests/` sibling `test_table_*`/`courses/tests/test_switchgrid_check.py`. Cover:

```python
import json
import pytest
from django.urls import reverse
from courses.models import Element, FillTableElement

pytestmark = pytest.mark.django_db


def _post(client, pk, fields):
    return client.post(reverse("courses:filltable_check", args=[pk]), fields)


# Build a lesson unit with a fill-table via ORM. Reuse the helper the sibling
# switchgrid check test uses to attach an element to a unit and get its Element pk.
# (See courses/tests/test_switchgrid_check.py for the exact fixture shape; mirror it.)

def test_all_correct_non_00_cell(filltable_on_unit, auth_client):
    element, _course = filltable_on_unit(
        [[{"kind": "static", "html": "t"}, {"kind": "answer", "answer": "4"}]]
    )
    r = _post(auth_client, element.pk, {"r0c1": "4"})
    body = r.json()
    assert body["all_correct"] is True
    assert {"r": 0, "c": 1, "correct": True} in body["cells"]


def test_partial_is_not_all_correct(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit(
        [[{"kind": "answer", "answer": "1"}, {"kind": "answer", "answer": "2"}]]
    )
    r = _post(auth_client, element.pk, {"r0c0": "1", "r0c1": "99"})
    body = r.json()
    assert body["all_correct"] is False
    got = {(d["r"], d["c"]): d["correct"] for d in body["cells"]}
    assert got == {(0, 0): True, (0, 1): False}


def test_soft_pk_miss_returns_200_empty_set(auth_client):
    r = _post(auth_client, 999999, {"r0c0": "x"})
    assert r.status_code == 200
    assert r.json() == {"cells": [], "all_correct": False}


def test_zero_answer_cells_returns_all_correct_false(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit([[{"kind": "static", "html": "a"}]])
    r = _post(auth_client, element.pk, {})
    assert r.json() == {"cells": [], "all_correct": False}


def test_missing_post_key_is_incorrect_not_500(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit([[{"kind": "answer", "answer": "4"}]])
    r = _post(auth_client, element.pk, {})  # no r0c0
    assert r.status_code == 200
    assert r.json()["all_correct"] is False


def test_forbidden_user_denied(filltable_on_unit, other_auth_client):
    element, _ = filltable_on_unit(
        [[{"kind": "answer", "answer": "4"}]], private=True
    )
    r = other_auth_client.post(
        reverse("courses:filltable_check", args=[element.pk]), {"r0c1": "4"}
    )
    assert r.status_code in (403, 404)  # PermissionDenied surfaces per project convention


def test_get_not_allowed(auth_client):
    r = auth_client.get(reverse("courses:filltable_check", args=[1]))
    assert r.status_code == 405
```

Define the `filltable_on_unit`, `auth_client`, `other_auth_client` fixtures at the top of the file mirroring `courses/tests/test_switchgrid_check.py`'s fixtures (create a course+lesson unit owned by a verified user, `add_element`/attach a `FillTableElement`, return its `Element` join row). Read that sibling file for the exact fixture code and adapt (swap `SwitchGridElement(lines=…)` for `FillTableElement(data={"cells": …})`). **Note:** `filltable_on_unit` must be a **factory fixture** — a fixture that returns a *callable* accepting `cells` (and `private=False`) and building the element on demand — because the tests invoke it with arguments (`filltable_on_unit([[…]])`). The sibling's element fixtures are valueless; converting to a factory (`def filltable_on_unit(...): def _make(cells, private=False): …; return _make`) is the non-trivial adaptation. `auth_client`/`other_auth_client` are plain value fixtures (a logged-in test client for the owner / a different user).

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_check.py -x -q`
Expected: FAIL — `NoReverseMatch: 'filltable_check'`.

- [ ] **Step 3: Add the route**

In `courses/urls.py`, alongside the `switchgrid-check` path:

```python
    path(
        "courses/element/<int:element_pk>/filltable-check/",
        views.filltable_check,
        name="filltable_check",
    ),
```

- [ ] **Step 4: Add the view**

In `courses/views.py`, near `switchgrid_check` (`can_access_course`, `blank_matches`, `require_POST`, `login_required`, `Element`, `JsonResponse`, `PermissionDenied` already imported):

```python
@require_POST
@login_required
def filltable_check(request, element_pk):
    """Server-side self-check for a Fill-in table. Per-cell correctness only —
    NOTHING is persisted, no marks. Soft pk lookup (a missing/wrong-type pk is a
    200 empty-set body, not 404) BEFORE any access dereference, mirroring
    switchgrid_check. Response shape deliberately differs: flat r/c dicts + a
    top-level `all_correct` (not switchgrid's nested `correct`)."""
    from courses.filltable import answer_cells, split_alternatives
    from courses.models import FillTableElement

    empty = {"cells": [], "all_correct": False}
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, FillTableElement):
        return JsonResponse(empty)
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    nd = concrete.normalize_data(concrete.data)
    case_sensitive = nd["case_sensitive"]
    cells = []
    all_correct = True
    for r, c, answer in answer_cells(nd["cells"]):
        got = request.POST.get(f"r{r}c{c}", "")
        ok = blank_matches(got, split_alternatives(answer), case_sensitive=case_sensitive)
        cells.append({"r": r, "c": c, "correct": ok})
        all_correct = all_correct and ok
    if not cells:
        return JsonResponse(empty)  # zero answer cells: never a vacuous True
    return JsonResponse({"cells": cells, "all_correct": all_correct})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_check.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/urls.py courses/views.py tests/test_filltable_check.py
git commit -m "feat(filltable): filltable_check endpoint + route (soft-pk, per-cell, no marks)"
```

---

## Task 4: Student template + render + widget CSS

**Files:**
- Create: `templates/courses/elements/filltableelement.html`
- Modify: `courses/static/courses/css/courses.css` (add `.el--filltable*` / `.filltable*` near the `.el--table` block ~698–707)
- Test: `tests/test_filltable_render.py`

**Interfaces:**
- Consumes: `FillTableElement.render()` passing `{el, data, eid}` (Task 1); URL `courses:filltable_check` (Task 3).
- Produces: rendered HTML with root `.filltable` carrying `data-element-pk`, `data-check-url`, `data-success-msg`, `data-retry-msg`; static cells `|safe`; answer cells EMPTY `<input>` with 0-based `data-r`/`data-c`; a `.filltable__confirm` Check button; a `.filltable__summary[hidden]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_render.py`:

```python
import pytest
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db


def _render(cells, **kw):
    el = FillTableElement(data={"cells": cells, **kw})
    el.save()
    # attach to a unit so a join row exists and eid is real (mirror sibling render test);
    # for a pure-render check eid=0 is acceptable — render() falls back to 0.
    return el.render()


def test_answer_cell_input_carries_zero_based_indices_and_no_answer():
    html = _render([[{"kind": "static", "html": "t"},
                     {"kind": "answer", "answer": "secret"}]])
    assert 'data-r="0"' in html and 'data-c="1"' in html
    assert "secret" not in html            # answer NEVER reaches the client
    assert 'value="secret"' not in html


def test_static_cell_math_left_raw_for_client_typeset():
    html = _render([[{"kind": "static", "html": r"\(x<5\)"},
                     {"kind": "answer", "answer": "1"}]])
    assert r"\(x<5\)" in html


def test_root_has_check_url_and_summary_msgs():
    html = _render([[{"kind": "answer", "answer": "1"}, {"kind": "static", "html": "b"}]])
    assert "filltable-check" in html       # data-check-url reversed
    assert "data-success-msg" in html and "data-retry-msg" in html


def test_prompt_rendered_escaped_when_present():
    html = _render([[{"kind": "answer", "answer": "1"}]], prompt="Fill <it> in")
    assert "Fill &lt;it&gt; in" in html    # escaped, not |safe
```

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_render.py -x -q`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/filltableelement.html`.

- [ ] **Step 3: Create the template**

`templates/courses/elements/filltableelement.html` — model the table markup on `templates/courses/elements/tableelement.html` (header/border classes, `ta-*`/`va-*`, the `th`/`td` header logic), but each cell branches on `kind`, answer cells emit an empty input, and the whole thing is wrapped in the `.filltable` widget root:

```django
{% load i18n %}
{% comment %}Student Fill-in table self-check. Static cells are pre-sanitised at
save() and emitted |safe (math typeset client-side over .el--filltable). Answer
cells emit an EMPTY input — the accepted answer is NEVER sent to the client.
data-r/data-c are 0-based indices into normalize_data(data)["cells"].{% endcomment %}
<div class="filltable" data-filltable
     data-element-pk="{{ eid }}"
     data-check-url="{% url 'courses:filltable_check' eid %}"
     data-success-msg="{% trans 'Great!' %}"
     data-retry-msg="{% trans 'Try again' %}">
  {% if data.prompt %}<p class="filltable__prompt">{{ data.prompt }}</p>{% endif %}
  <div class="el el--filltable el--filltable--border-{{ data.border }}"
       {% if data.header_row %}data-header-row{% endif %}
       {% if data.header_col %}data-header-col{% endif %}>
    <div class="el--filltable__scroll">
      <table>
        {% for row in data.cells %}
        <tr>
          {% for cell in row %}
            {% if forloop.parentloop.first and data.header_row or forloop.first and data.header_col %}
              <th class="ta-{{ cell.halign }} va-{{ cell.valign }}"
                  {% if forloop.parentloop.first and data.header_row %}scope="col"{% elif forloop.first and data.header_col %}scope="row"{% endif %}>{% include "courses/elements/_filltable_cell.html" %}</th>
            {% else %}
              <td class="ta-{{ cell.halign }} va-{{ cell.valign }}">{% include "courses/elements/_filltable_cell.html" %}</td>
            {% endif %}
          {% endfor %}
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>
  <button type="button" class="filltable__confirm btn btn--small">{% trans "Check" %}</button>
  <p class="filltable__summary" data-filltable-summary hidden></p>
</div>
```

And the shared cell partial `templates/courses/elements/_filltable_cell.html`:

```django
{% if cell.kind == "answer" %}<input type="text" class="filltable__input" data-r="{{ forloop.parentloop.counter0 }}" data-c="{{ forloop.counter0 }}" aria-label="{% trans 'Answer' %}">{% else %}{{ cell.html|safe }}{% endif %}
```

Note: `forloop.parentloop.counter0` (row) and `forloop.counter0` (col) are 0-based. The partial is included inside the innermost `{% for cell in row %}` so those counters are the cell's row/col.

- [ ] **Step 4: Add CSS**

In `courses/static/courses/css/courses.css`, near the `.el--table` block, add student widget styles: `.filltable`, `.filltable__prompt`, `.el--filltable table`/borders (copy the `.el--table--border-*` rules, renamed), `.filltable__input` (small bordered input), correctness classes `.filltable__input--correct` / `--incorrect` (green/red border + a ✓/✗ pseudo-marker), `.filltable__confirm`, `.filltable__summary` + `--success`/`--retry`, and the lock guard:

```css
.filltable__confirm[hidden] { display: none !important; }
.filltable__input--correct { border-color: var(--ok, #16794b); }
.filltable__input--incorrect { border-color: var(--bad, #b3261e); }
```

Match existing token usage in `courses.css` (light + dark). Frontend-design pass happens in Task 6's verification; keep this functional-but-clean.

- [ ] **Step 5: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_render.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/elements/filltableelement.html templates/courses/elements/_filltable_cell.html courses/static/courses/css/courses.css tests/test_filltable_render.py
git commit -m "feat(filltable): student template (empty answer inputs, 0-based indices) + widget CSS"
```

---

## Task 5: Student JS enhancer + lesson gating + `_fill_table_has_math`

**Files:**
- Create: `courses/static/courses/js/filltable.js`
- Modify: `courses/static/courses/js/editor.js` (~80, preview re-init block)
- Modify: `templates/courses/manage/editor/editor.html` (~155, `<script>` block)
- Modify: `templates/courses/lesson_unit.html` (~61, script gate)
- Modify: `courses/views.py` (`_fill_table_has_math` near `_table_has_math` ~111; `build_lesson_context` has_math OR-chain ~259 + existence flag ~281 + ctx dict ~308)
- Test: `tests/test_filltable_context.py`

**Interfaces:**
- Consumes: `filltable_check` JSON (Task 3); `.filltable` root data-attrs (Task 4).
- Produces: `window.libliInitFillTables(root)`; `build_lesson_context` ctx key `has_fill_table` (existence) and a `has_math` clause; `_fill_table_has_math(obj) -> bool`.

- [ ] **Step 1: Write the failing context test**

Create `tests/test_filltable_context.py` mirroring `courses/tests/test_switchgrid_context.py`: build a lesson unit, attach a `FillTableElement`, call `build_lesson_context`, assert:
- `ctx["has_fill_table"] is True` when a fill-table is present (False otherwise).
- `ctx["has_math"] is True` when a static cell contains `\( … \)`; `False` for a fill-table with no math (this proves the content-inspecting helper, not a bare existence flag, drives math).

```python
import pytest
from courses.models import FillTableElement
# reuse the sibling's helper to build a unit + context; see test_switchgrid_context.py

pytestmark = pytest.mark.django_db

def test_has_fill_table_flag(unit_with_element, ctx_for):
    unit = unit_with_element(FillTableElement(data={"cells": [[{"kind": "answer", "answer": "1"}]]}))
    assert ctx_for(unit)["has_fill_table"] is True

def test_has_math_only_when_static_cell_has_math(unit_with_element, ctx_for):
    plain = unit_with_element(FillTableElement(data={"cells": [[{"kind": "answer", "answer": "1"}]]}))
    assert ctx_for(plain)["has_math"] is False
    mathy = unit_with_element(FillTableElement(data={"cells": [[{"kind": "static", "html": r"\(x\)"}, {"kind": "answer", "answer": "1"}]]}))
    assert ctx_for(mathy)["has_math"] is True
```

Define `unit_with_element`/`ctx_for` as **factory fixtures** (each returns a callable): `unit_with_element(el)` attaches the passed concrete element to a fresh lesson unit and returns the unit; `ctx_for(unit)` calls `build_lesson_context` for that unit and returns the ctx dict. (The sibling's fixtures are valueless — the callable shape is the adaptation, since the tests invoke them with arguments.)

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_context.py -x -q`
Expected: FAIL — `KeyError: 'has_fill_table'`.

- [ ] **Step 3: Add `_fill_table_has_math` and wire `build_lesson_context`**

In `courses/views.py`, add near `_table_has_math` (do NOT delegate to `_table_has_math` — its `isinstance(el, TableElement)` guard returns False for a fill-table):

```python
def _fill_table_has_math(obj):
    from courses.models import FillTableElement

    if not isinstance(obj, FillTableElement):
        return False
    data = obj.normalize_data(obj.data)
    return any(
        cell.get("kind") != "answer" and has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )
```

In `build_lesson_context`, add a clause to the `has_math` OR-chain (mirror the switch-grid clause at ~259):

```python
    or any(
        isinstance(el.content_object, FillTableElement)
        and _fill_table_has_math(el.content_object)
        for el in elements
    )
```

Add the existence flag near `has_switch_grid` (~281):

```python
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
```

Add `"has_fill_table": has_fill_table,` to the returned ctx dict (~308). Ensure `FillTableElement` is imported in views.py alongside the other model imports used there.

- [ ] **Step 4: Create `filltable.js`**

Model on `courses/static/courses/js/switchgrid.js` (read it). An IIFE exposing `window.libliInitFillTables`. Per-root `initOne(root)`:
- idempotency guard `root.dataset.filltableReady`;
- wire the `.filltable__confirm` click → `submit(root)`;
- **always** call `window.renderMathInElement(root)` in try/catch (typeset static-cell math, incl. editor preview) — this is NOT behind the pk guard;

`submit(root)`:
- read `pk = root.dataset.elementPk`, `url = root.dataset.checkUrl`; `if (!pk || pk === "0" || !url) return;` (unsaved preview — Check no-ops, but math already typeset in init);
- build a `FormData`, appending one field per answer input: `body.append("r"+inp.dataset.r+"c"+inp.dataset.c, inp.value)` for each `root.querySelectorAll(".filltable__input")`;
- `fetch(url, {method:"POST", headers:{"X-CSRFToken": csrf()}, body, credentials:"same-origin"})`, `.then(r=>r.json())`;
- paint: for each `{r,c,correct}` in `data.cells`, toggle `--correct`/`--incorrect` on the matching `.filltable__input[data-r=r][data-c=c]`;
- summary: set `.filltable__summary` text to `data.success-msg`/`data.retry-msg` (from root dataset) based on `data.all_correct`, unhide it, toggle `--success`/`--retry`;
- lock ONLY when `data.all_correct === true && (data.cells||[]).length > 0`: disable all inputs, hide `.filltable__confirm` (set `hidden`);
- `.catch(()=>{})` fail-open.

Include a `csrf()` cookie reader copied from `switchgrid.js`. End with `window.libliInitFillTables = initFillTables; initFillTables(document);`.

- [ ] **Step 5: Wire the script + gate + editor re-init**

- `templates/courses/manage/editor/editor.html`: add `<script src="{% static 'courses/js/filltable.js' %}" defer></script>` alongside `switchgrid.js`.
- `templates/courses/lesson_unit.html`: add `{% if has_fill_table %}<script src="{% static 'courses/js/filltable.js' %}" defer></script>{% endif %}` alongside the `has_switch_grid` gate (~61).
- `courses/static/courses/js/editor.js`: add `if (preview && window.libliInitFillTables) window.libliInitFillTables(preview);` in the preview re-init block (~80).

- [ ] **Step 6: Run the context test + a script-presence assertion**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_context.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/filltable.js courses/static/courses/js/editor.js templates/courses/manage/editor/editor.html templates/courses/lesson_unit.html courses/views.py tests/test_filltable_context.py
git commit -m "feat(filltable): student JS enhancer + lesson script/math gating (_fill_table_has_math)"
```

---

## Task 6: Editor partial + `filltable_editor.js` (WYSIWYG grid + Answer-cell toggle)

**Files:**
- Create: `templates/courses/manage/editor/_edit_filltable.html`
- Create: `courses/static/courses/js/filltable_editor.js`
- Modify: `templates/courses/manage/editor/editor.html` (add editor `<script>`)
- Modify: `courses/static/courses/js/editor.js` (editorPane re-init ~87)
- Modify: `courses/static/courses/css/courses.css` (`.el-editor--filltable*`)
- Test: `tests/test_filltable_editor_partial.py`

**Interfaces:**
- Consumes: `FillTableElement.normalized_data` for server-render of the grid; the hidden `name="data"` contract consumed by `FillTableElementForm` (Task 2).
- Produces: `window.libliInitFillTableEditor(editorPane)`; hidden `data` mirrors `{header_row, header_col, border, case_sensitive, prompt, cells:[[{kind,...}]]}`.

- [ ] **Step 1: Write the failing partial test**

Create `tests/test_filltable_editor_partial.py` mirroring `tests/test_table_editor_partial.py`: render `_edit_filltable.html` with a bound/instance form (or GET `manage_element_add` for `filltable` in Task 7) and assert the partial contains: the hidden `name="data"` input, the case-sensitive checkbox (`data-case-sensitive`), the prompt field (`name`/`data-prompt`), the "Answer cell" toggle button (`data-answer-toggle`), and the translated editor `data-*` message attrs (`data-msg-answer-blank`, `data-msg-no-answer`, `data-msg-answer-placeholder`). Also assert every `#ed-*` sprite referenced is defined (mirror `test_table_editor_partial.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_editor_partial.py -x -q`
Expected: FAIL — `TemplateDoesNotExist`.

- [ ] **Step 3: Create `_edit_filltable.html`**

Base it on `templates/courses/manage/editor/_edit_table.html` (read it). Keep the whole table editor structure (hidden `data`, controls strip with header-row/col + border select, the B/I/U/math toolbar, the contenteditable grid server-rendered from `d = form.instance.normalized_data`, the `data-msg-*` grid-handle labels). ADD:
- root element attribute hook `data-filltable-editor` (in addition to `data-table-editor` if you reuse handlers, but prefer a distinct root so `filltable_editor.js` owns it);
- in the controls strip: a **case-sensitive** checkbox `<input type="checkbox" data-case-sensitive {% if d.case_sensitive %}checked{% endif %}>` and an optional **prompt** `<input type="text" data-prompt value="{{ d.prompt }}">`;
- in the toolbar: an **Answer cell** toggle `<button type="button" class="rte-btn" data-answer-toggle title="{% trans 'Answer cell' %}" aria-label="{% trans 'Answer cell' %}">…</button>` (use a distinct `#ed-answer` sprite added to the `editor__sprite` block in `editor.html`, or a text glyph);
- render each grid cell by kind: a static cell as today (`<td contenteditable>…html…</td>`), an **answer cell** as a shaded `<td data-answer><input type="text" class="filltable-editor__answer" value="{{ cell.answer }}" placeholder="…"></td>`;
- JS-i18n `data-*` attrs on the root: `data-msg-answer-placeholder`, `data-msg-answer-blank`, `data-msg-no-answer` (all `{% trans %}`), read by the editor JS.

- [ ] **Step 4: Create `filltable_editor.js`**

Base on `courses/static/courses/js/table_editor.js` (read it — it already does contenteditable→hidden-JSON mirroring, toolbar, active-cell (`focusedCell`) tracking, row/col add-del, `data-msg-*` label reading, idempotent `dataset.tableWired`). Adapt into `window.libliInitFillTableEditor`:
- **Active-cell tracking must include answer cells.** The sibling's `focusin`/`click`/`input` handlers match only `e.target.closest("td[contenteditable]")` — an answer cell is `<td data-answer><input>` with NO `contenteditable`, so verbatim mirroring would never set `focusedCell` on it and the answer→static toggle would have no target (silently breaking reversibility). Change the tracking selector to `closest("td[contenteditable], td[data-answer]")` (and for the `<input>` inside, resolve up to its `<td data-answer>`).
- **serialize():** iterate **all** grid cells (every `td` in the grid, NOT just `td[contenteditable]`), emitting per-cell `kind`. A `td[data-answer]` → `{kind:"answer", answer: input.value, halign, valign}`; any other `td` → `{kind:"static", html, halign, valign}`. Add `case_sensitive` (from `[data-case-sensitive]`) and `prompt` (from `[data-prompt]`) to the mirrored object.
- **Answer-cell toggle (`[data-answer-toggle]`):** operates on the tracked active cell (`focusedCell`, now including answer cells). Disabled/no-op when none active. static→answer: stash the cell's current `innerHTML` on a per-node `Map` (keyed by the live `<td>` node), replace cell content with an empty `<input class="filltable-editor__answer">`, set `data-answer` and remove `contenteditable`; answer→static: stash the input's value, restore stashed html (or empty), remove `data-answer`, restore `contenteditable="true"`. Re-serialize after toggle.
- **Discard stashes on structural edits:** in the row/col insert/delete/reorder handlers, clear the stash `Map` (a stash could otherwise restore into the wrong node after the grid reshapes).
- **Submit guard (capture phase):** on the form submit, count answer cells; if zero → `preventDefault`, show `data-msg-no-answer` inline; if any answer input is blank per the same rule as `courses.filltable.is_blank_answer` (split on `|`, trim, drop empties → empty) → `preventDefault`, show `data-msg-answer-blank`. Register with `{capture:true}` so it fires before editor.js's bubble-phase save (mirror `switchgrid_editor.js`'s `onSubmit`).
- Read JS-i18n strings from the root `data-msg-*` attrs. Idempotent via `dataset.filltableWired`. Expose `window.libliInitFillTableEditor`.

- [ ] **Step 5: Wire the editor script + re-init + CSS**

- `editor.html`: add `<script src="{% static 'courses/js/filltable_editor.js' %}" defer></script>` alongside `table_editor.js`.
- `editor.js`: add `if (editorPane && window.libliInitFillTableEditor) window.libliInitFillTableEditor(editorPane);` in the editorPane block (~87).
- `courses.css`: add `.el-editor--filltable` styles + `.filltable-editor__answer` (shaded input distinct from static cells) + `.el-editor__answer-error` inline message. **Run the frontend-design skill** on the editor interaction AND the student render; screenshot light + dark and self-critique (per the every-view-ships-styled / verify-UI rules).

- [ ] **Step 6: Run the partial test + verify visually**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_editor_partial.py -q`
Expected: PASS. Then Playwright-screenshot the add-fill-table editor and a rendered widget (light+dark) and confirm the design.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_edit_filltable.html courses/static/courses/js/filltable_editor.js templates/courses/manage/editor/editor.html courses/static/courses/js/editor.js courses/static/courses/css/courses.css tests/test_filltable_editor_partial.py
git commit -m "feat(filltable): WYSIWYG editor partial + filltable_editor.js (Answer-cell toggle, stash, submit guard)"
```

---

## Task 7: Manage plumbing — palette card, labels, allow-tuples

**Files:**
- Modify: `courses/views_manage.py` (`element_add` ~878–901; `element_save` ~936–960; `_EDITOR_TYPE_LABELS` ~745)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` ~34; `element_summary` ~105)
- Modify: `templates/courses/manage/editor/_add_menu.html` (Interactive group, `{% if not nested %}`)
- Modify: `templates/courses/manage/_icon_sprite.html` (`#el-filltable`)
- Test: `tests/test_filltable_manage_plumbing.py`

**Interfaces:**
- Consumes: `FillTableElementForm` (Task 2), `_edit_filltable.html` (Task 6).
- Produces: `manage_element_add?type=filltable` → 200; palette card present in non-nested add-menu, absent in nested; `editor.html` loads both JS files.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_manage_plumbing.py` mirroring `tests/test_table_manage_plumbing.py` / `courses/tests/test_switchgrid_wiring.py`:

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_element_add_renders_filltable_editor_200(author_client, unit):
    # GET manage_element_add for type=filltable → 200 (exercises element_add ->
    # _render_open_form -> _host_form -> _edit_filltable). Mirror the sibling test's
    # URL + fixtures.
    url = reverse("courses:manage_element_add", args=[...]) + "?type=filltable"
    r = author_client.get(url)
    assert r.status_code == 200
    assert b'data-filltable-editor' in r.content


def test_palette_card_present_non_nested_absent_nested(author_client, unit):
    # The add-menu for a normal (non-nested) lesson unit shows the filltable card;
    # the nested (tabs) add-menu does not. Mirror how the switchgrid wiring test
    # renders _add_menu with nested=True/False.
    ...


def test_editor_html_loads_both_filltable_scripts(author_client, unit):
    r = author_client.get(reverse("courses:manage_editor", args=[...]))
    assert b"courses/js/filltable.js" in r.content
    assert b"courses/js/filltable_editor.js" in r.content
```

Fill in the exact `manage_element_add` / `manage_editor` URL args and fixtures from the sibling manage-plumbing test.

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_manage_plumbing.py -x -q`
Expected: FAIL (type not allowed / card absent).

- [ ] **Step 3: Register in views_manage**

- Add `"filltable"` to the `element_add` allow-tuple (with `"table"`, `"switchgrid"`).
- Add `"filltable"` to the `element_save` allow-tuple.
- Add `"filltable": gettext_lazy("Fill-in table"),` to `_EDITOR_TYPE_LABELS`.

- [ ] **Step 4: Register labels + summary**

In `courses/templatetags/courses_manage_extras.py`:
- Add `"filltableelement": _("Fill-in table"),` to `_ELEMENT_LABELS`.
- Import `FillTableElement`; add a branch to `element_summary`:

```python
    if name == "FillTableElement":
        d = FillTableElement.normalize_data(el.data)
        n_ans = sum(1 for row in d["cells"] for c in row if c["kind"] == "answer")
        rows, cols = len(d["cells"]), len(d["cells"][0])
        return _("%(rows)d×%(cols)d fill-in table, %(n)d answer(s)") % {
            "rows": rows, "cols": cols, "n": n_ans}
```

- [ ] **Step 5: Palette card + icon**

In `_add_menu.html`, in the **Interactive** group (which is already inside `{% if not unit_is_quiz %}`), add — wrapped in `{% if not nested %}` (non-nestable) — next to the switch-grid card:

```django
{% if not nested %}<button type="button" class="typecard" data-add-type="filltable"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-filltable"/></svg>{% trans "Fill-in table" %}</button>{% endif %}
```

In `templates/courses/manage/_icon_sprite.html`, add a `<symbol id="el-filltable" …>` (16×16 fill, matching sibling `el-*` symbols — a table glyph with a pen/blank motif).

- [ ] **Step 6: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_manage_plumbing.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/views_manage.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html tests/test_filltable_manage_plumbing.py
git commit -m "feat(filltable): manage plumbing — palette card, labels, summary, allow-tuples"
```

---

## Task 8: Transfer trio (export / validate / import)

**Files:**
- Modify: `courses/transfer/export.py` (`SERIALIZERS` ~244–268)
- Modify: `courses/transfer/payloads.py` (`VALIDATORS` ~568–592)
- Modify: `courses/transfer/importer.py` (`BUILDERS` ~669–693)
- Modify: `tests/test_transfer_schema.py` (count assert 23 → 24 + model name)
- Test: `tests/test_filltable_transfer.py`

**Interfaces:**
- Consumes: `FillTableElement` (Task 1).
- Produces: transfer key `fill_table` registered in all three registries; round-trips `data`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filltable_transfer.py` mirroring `tests/test_table_transfer.py`:
- round-trip: serialize a `FillTableElement`, validate, import → identical normalized `data` (static + answer cells, prompt, case_sensitive).
- validator REJECTS: `data` not a dict; `cells` not a list; a row not a list; a cell not a dict.
- validator ACCEPTS (tolerated, normalized on build): ragged rows; unknown `kind`; zero answer cells; out-of-enum `border`.

```python
import pytest
from courses.models import FillTableElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.importer import BUILDERS
from courses.transfer.schema import TransferError

pytestmark = pytest.mark.django_db


def test_round_trip_preserves_cells_and_flags():
    src = FillTableElement(data={"case_sensitive": True, "prompt": "go",
        "cells": [[{"kind": "static", "html": "<b>t</b>"},
                   {"kind": "answer", "answer": "4"}]]})
    src.save()
    payload = SERIALIZERS["fill_table"][1](src, set())
    VALIDATORS["fill_table"](payload, "e1", set())          # validator: (data, elid, media_kinds)
    obj, _children = BUILDERS["fill_table"](payload, {})
    nd = obj.normalize_data(obj.data)
    assert nd["cells"][0][1] == {"kind": "answer", "answer": "4", "halign": "left", "valign": "top"}
    assert nd["case_sensitive"] is True and nd["prompt"] == "go"


@pytest.mark.parametrize("bad", [
    "notadict",
    {"cells": "notalist"},
    {"cells": ["notarow"]},
    {"cells": [["notacell"]]},
])
def test_validator_rejects_gross_corruption(bad):
    # Call the validator DIRECTLY (not via validate_element_data, whose dispatcher
    # signature is (el, media_kinds) and which pre-guards non-dict). The direct call
    # also exercises _val_fill_table's own non-dict guard on the "notadict" case.
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](bad, "e1", set())


@pytest.mark.parametrize("ok", [
    {"cells": [[{"kind": "answer", "answer": "1"}], [{"kind": "static", "html": "x"}, {"kind": "static", "html": "y"}]]},  # ragged
    {"cells": [[{"kind": "weird"}]]},  # unknown kind
    {"cells": [[{"kind": "static", "html": "a"}]]},  # zero answer cells
    {"border": "dashed", "cells": [[{"kind": "answer", "answer": "1"}]]},  # bad border
])
def test_validator_accepts_tolerable_drift(ok):
    VALIDATORS["fill_table"](ok, "e1", set())  # must not raise
```

The direct `VALIDATORS["fill_table"](data, elid, media_kinds)` call mirrors how the sibling `tests/test_table_transfer.py` invokes `VALIDATORS["table"](...)`; `TransferError` is imported from `courses.transfer.schema` (its real home).

- [ ] **Step 2: Run to verify they fail**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_transfer.py -x -q`
Expected: FAIL — `KeyError: 'fill_table'`.

- [ ] **Step 3: Serializer**

In `courses/transfer/export.py`, import `FillTableElement`, add a serializer and registry entry (mirror `_ser_table` — return the data dict directly):

```python
def _ser_fill_table(el, ids):
    return dict(el.data)
```
Registry: `"fill_table": (FillTableElement, _ser_fill_table),`.

- [ ] **Step 4: Validator**

In `courses/transfer/payloads.py`, add (3-arg, `_err`, `return set()`; reject ONLY gross structural corruption — NOT out-of-enum border). This validator is **intentionally more lenient** than the sibling `_val_table` (which uses strict `_exact_keys` + `check_bool`): per the spec's tolerant-import stance, missing keys and value-enum drift are left for `normalize_data` to repair, so `_val_fill_table` only checks container shapes:

```python
def _val_fill_table(data, elid, media_kinds):
    if not isinstance(data, dict):
        _err(_("Element '%(el)s': fill-in table data must be an object."), el=elid)
    rows = data.get("cells")
    if rows is not None and not isinstance(rows, list):
        _err(_("Element '%(el)s': fill-in table cells must be a list."), el=elid)
    for row in rows or []:
        if not isinstance(row, list):
            _err(_("Element '%(el)s': fill-in table row must be a list."), el=elid)
        for cell in row:
            if not isinstance(cell, dict):
                _err(_("Element '%(el)s': fill-in table cell must be an object."), el=elid)
    return set()
```
Registry: `"fill_table": _val_fill_table,`.

- [ ] **Step 5: Builder**

In `courses/transfer/importer.py`, add (mirror `_build_table` — normalize then `_clean_save`; `save()` re-sanitises static cells):

```python
def _build_fill_table(data, assets):
    return _clean_save(FillTableElement(data=FillTableElement.normalize_data(data))), ()
```
Registry: `"fill_table": _build_fill_table,`. Import `FillTableElement`.

- [ ] **Step 6: Bump the count assert**

In `tests/test_transfer_schema.py`, change `assert len(ELEMENT_MODELS) == 23` → `24` and add `"filltableelement"` to the expected-names list (lines ~12–25) if it enumerates names. Also **rename the test function** `test_element_models_lists_all_23_concrete_element_models` → `…all_24…` so the name doesn't go stale against the bumped assertion.

- [ ] **Step 7: Run tests to verify they pass**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_filltable_transfer.py tests/test_transfer_schema.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_filltable_transfer.py tests/test_transfer_schema.py
git commit -m "feat(filltable): transfer trio (serialize/validate/import) + count assert"
```

---

## Task 9: e2e — real student gesture end-to-end

**Files:**
- Create: `tests/test_e2e_filltable.py`

**Interfaces:**
- Consumes: the full stack (Tasks 1–8).

- [ ] **Step 1: Write the e2e test**

Model on `tests/test_e2e_switchgrid.py` (read its top for the login helper, `pytestmark = pytest.mark.e2e`, `make_verified_user`, `add_element`, `TEST_PASSWORD`). Seed a lesson unit via ORM containing a `FillTableElement` with an answer cell at a **non-(0,0)** position, e.g.:

```python
data = {"cells": [
    [{"kind": "static", "html": "czas"}, {"kind": "static", "html": "woda"}],
    [{"kind": "static", "html": "0"}, {"kind": "answer", "answer": "4"}],
]}
```

Drive the REAL gesture (no `page.evaluate` shortcut):
- log in, open the lesson page;
- locate the answer input at `.filltable__input[data-r="1"][data-c="1"]`, `.fill("4")`;
- click `.filltable__confirm`;
- `expect` that input to get class `filltable__input--correct`, the summary to show the success text, and the Confirm button to become hidden (lock);
- a second scenario: fill a wrong value, click Check, assert `--incorrect` + retry summary + NOT locked.

- [ ] **Step 2: Run the e2e (focused, foreground)**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest tests/test_e2e_filltable.py -q -m e2e`
Expected: PASS. (Run foreground/focused only — never background `-m e2e`, which spawns runaway browsers.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_filltable.py
git commit -m "test(filltable): e2e drives the real student gesture (non-(0,0) answer, lock-on-success)"
```

---

## Task 10: i18n catalogs + full-suite verification

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l en -l pl` (watch the fuzzy-flag gotcha — remove stray `#, fuzzy` markers on strings you translate). Confirm all new fill-table msgids appear (`Fill-in table`, `Answer cell`, `Great!`, `Try again`, `Mark at least one answer cell…`, `An answer cell is blank…`, the editor `data-msg-*` strings, transfer `_err` strings).

- [ ] **Step 2: Translate PL**

Fill in the Polish `msgstr` for every new msgid in `locale/pl/LC_MESSAGES/django.po` (mirror the tone of neighbouring switch-grid/table entries). Leave `en` msgstrs as the source English.

- [ ] **Step 3: Compile + run the i18n catalog test**

Run: `uv run python manage.py compilemessages -l pl` then `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest -k "catalog or i18n or po" -q` (run whatever catalog-consistency test the repo has; find it via `grep -rl "django.po" tests/`).
Expected: PASS.

- [ ] **Step 4: Full non-e2e suite (DoD)**

Run: `export DATABASE_URL='postgres://libli:libli@localhost:5432/libli_filltable'; uv run pytest -q` (deselects e2e by default). Then the full e2e suite once, foreground: `uv run pytest -q -m e2e`.
Expected: all green. Also `uv run makemigrations --check --dry-run` (no missing migration) and `uv run ruff format --check` + `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po
git commit -m "i18n(filltable): EN/PL catalog entries"
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- Model / `normalize_data` / scalar coercion / save-sanitise → Task 1.
- Form / distinct validation / `|` split / blank rule → Task 2.
- Endpoint / gate order / decorators / URL-path pk / JSON shapes / empty-set / index base / matching → Task 3.
- Student template / empty answer inputs / no answer leak / prompt escaped / data-* root → Task 4.
- Student JS / CSRF / preview guard / renderMathInElement / lock rule; two-mechanism math+script gating (`_fill_table_has_math` replicating not delegating) → Task 5.
- Editor partial + editor JS / Answer-cell toggle / stash keyed to DOM node discarded on structural edits / active-cell / editor i18n data-attrs / both JS in editor.html → Task 6.
- Palette card (non-nested Interactive) / labels / summary / manage_element_add 200 / nested-absence → Task 7.
- Transfer trio / validator scope (border not rejected) / count assert → Task 8.
- e2e non-(0,0) real gesture → Task 9.
- i18n EN/PL → Task 10.
- **Deliberate refinement:** lesson-only (Interactive group is quiz-hidden), so the spec's quiz-unit gating is dropped — documented in Global Constraints.

**Placeholder scan** — the only intentional "fill in from sibling" pointers are exact file references (read `X`, mirror its fixtures) for test fixtures and long JS files, with the novel logic spelled out; no vague "add error handling"/"TBD".

**Type consistency** — names are fixed in Global Constraints and used identically across tasks: `FillTableElement`, `filltable`/`fill_table`/`filltableelement`, `filltable_check`, `libliInitFillTables`/`libliInitFillTableEditor`, `.filltable`/`.el--filltable`/`.el-editor--filltable`, `has_fill_table`, `_fill_table_has_math`, `courses.filltable.{split_alternatives,is_blank_answer,answer_cells}`, response keys `cells`/`all_correct`/`r`/`c`/`correct`, POST keys `r{r}c{c}`, data-attrs `data-element-pk`/`data-check-url`/`data-success-msg`/`data-retry-msg`.
