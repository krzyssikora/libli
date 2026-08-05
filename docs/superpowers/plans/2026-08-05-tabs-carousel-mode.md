# Tabs Carousel Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `TabsElement` a `display: carousel` mode so an author can step a reader through slides holding arbitrary elements (tables above all) with gallery-style ‹ › arrows and dots, instead of a tab strip.

**Architecture:** Two new scalar keys on the existing `TabsElement.data` JSON (`display`, `label_pos`), no migration and no new model. The children, the container registries, nesting, clipboard and export routing are all untouched because tabs is already a registered container. The student enhancer branches inside the existing `tabs.js`; the carousel half is a **port of `gallery.js::show`** with a closed list of six departures.

**Tech Stack:** Django 5 + Python 3.12 (`uv run` for all tooling), vanilla ES5-style browser JS (no build step, no framework), token-driven CSS in `courses/static/courses/css/`, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-05-tabs-carousel-mode-design.md` — 1360 lines, passed 16 review rounds. It is authoritative. Where this plan and the spec disagree, the spec wins; do not re-open its decisions.

## Global Constraints

- **Tooling is `uv run`** — `ruff`, `pytest` and `python` are NOT on PATH. Always `uv run pytest …`, `uv run ruff …`.
- **Scope every test run narrowly.** Use `-k` or an explicit file path. A whole-repo sweep is a branch-level gate, never a per-task step. Never run two pytest invocations at once, and never background a pytest run (it orphans the test DB and the next run dies with `DuplicateDatabase`).
- **e2e needs `-m e2e`** or the tests silently deselect and pytest exits 5. Run e2e in the **foreground**, one file at a time.
- **Falsify, don't just run.** Every test in this plan names a mutant. Apply the mutant, confirm RED, revert, confirm GREEN. A passing test proves nothing on its own.
- **`MIN_TABS = 2`, `MAX_TABS = 10`, `LABEL_MAX = 80`** are unchanged.
- **No migration.** `TabsElement.data` is a `JSONField`; defaults are supplied on read.
- **Enum values, verbatim:** `display` ∈ `("tabs", "carousel")`, default `"tabs"`. `label_pos` ∈ `("above", "below", "hidden")`, default `"above"`.
- **Class names, verbatim, and no seventh:** `tabs__stage` (server-rendered), and JS-built `tabs__cbar`, `tabs__cprev`, `tabs__cnext`, `tabs__dots`, `tabs__dot`, `tabs__status`.
- **Gate class is `.tabs--carousel`**, added as the last step of a successful carousel init — never `.tabs--js`.
- **Every carousel CSS rule uses an explicit child chain** (`> .tabs__stage > .tabs__section`), never a descendant selector.
- **Polish translations** for every new user-facing string, and `django.mo` regenerated before the PR.
- **Never hardcode a test password**; use the existing factories/fixtures.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `courses/models.py` | `TabsElement` enums, `_coerce_enum`, 3 normalizer sites, `display_settings()`, `render()` context | 1, 4 |
| `courses/element_forms.py` | `TabsElementForm.clean_data` threading, `editor_display` / `editor_label_pos` | 2 |
| `courses/templatetags/courses_manage_extras.py` | `tabs_bounds` exposes the choice tuples; `element_summary` names the mode | 3, 10 |
| `templates/courses/manage/editor/_edit_tabs.html` | The two `<select>`s, wrapped in visible `<label>`s | 3 |
| `courses/static/courses/js/tabs_editor.js` | Serialize both keys; re-serialize on change; toggle the label-pos row | 3 |
| `courses/static/courses/css/editor.css` | `tabs-editor__*` rules + the paired `[hidden]` rule | 3 |
| `templates/courses/elements/tabselement.html` | `.tabs__stage` wrapper, `data-display`, `data-label-pos`, rewritten header comment | 4 |
| `templates/courses/lesson_unit.html`, `quiz_unit.html`, `manage/editor/editor.html` | `TABS_I18N` carousel keys (all three, together) | 5 |
| `locale/pl/LC_MESSAGES/django.po` + `.mo` | Polish for every new string | 5 |
| `courses/static/courses/css/courses.css` | Carousel styles, 4 scoped rules, print resets, reduced motion | 6 |
| `courses/static/courses/js/tabs.js` | The carousel branch: init, nav, `show()` port, `try/catch` | 7 |
| `courses/static/courses/js/tabs.js` | Keyboard guards, `rescueFocus`, height reservation | 8 |
| `courses/transfer/{export,payloads,importer,schema}.py` | Serialize/validate/build the two keys; `FORMAT_VERSION` 7 → 8 | 9 |
| `courses/builder.py` | `_CONTAINER_REGISTRY` contract comment only (no code) | 10 |
| `tests/test_tabs_*.py`, `tests/test_e2e_tabs.py`, `courses/tests/…` | Tests, incl. the widened `_print_block` / `_screen_label_rule` helpers | all |

---

### Task 1: Model — enums, coercion, the three key-drop sites, `display_settings()`

**Files:**
- Modify: `courses/models.py` (`TabsElement`, ~line 1369-1505)
- Modify: `courses/builder.py` (`_CONTAINER_REGISTRY` comment only)
- Test: `tests/test_tabs_element.py` (existing file — append)

**Interfaces:**
- Consumes: nothing.
- Produces: `TabsElement.DISPLAY_CHOICES`, `.DISPLAYS`, `.DEFAULT_DISPLAY`, `.LABEL_POS_CHOICES`, `.LABEL_POSITIONS`, `.DEFAULT_LABEL_POS` (all class attributes); `TabsElement._coerce_enum(value, allowed, default) -> str` (staticmethod); `TabsElement.display_settings() -> {"display": str, "label_pos": str}`. `normalize_labels_and_ids(data)` and `normalize_data(data)` now return `{"tabs": [...], "display": str, "label_pos": str}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tabs_element.py`:

```python
import pytest
from courses.models import TabsElement


def test_normalizers_default_the_new_keys_on_an_empty_blob():
    norm = TabsElement.normalize_labels_and_ids({})
    assert norm["display"] == "tabs"
    assert norm["label_pos"] == "above"


@pytest.mark.parametrize("hostile", [None, 42, True, "CAROUSEL", [], {}, ["carousel"]])
def test_normalizers_coerce_hostile_values_without_raising(hostile):
    # [] and {} are the falsification for the tuple-not-frozenset decision:
    # `[] in frozenset(...)` raises TypeError: unhashable type.
    norm = TabsElement.normalize_labels_and_ids({"display": hostile, "label_pos": hostile})
    assert norm["display"] == "tabs"
    assert norm["label_pos"] == "above"


@pytest.mark.parametrize("display", ["tabs", "carousel"])
@pytest.mark.parametrize("pos", ["above", "below", "hidden"])
def test_every_enum_member_round_trips(display, pos):
    norm = TabsElement.normalize_labels_and_ids({"display": display, "label_pos": pos})
    assert (norm["display"], norm["label_pos"]) == (display, pos)


def test_normalize_data_carries_the_keys_through_padding_and_truncation():
    padded = TabsElement.normalize_data({"tabs": [], "display": "carousel", "label_pos": "below"})
    assert len(padded["tabs"]) == TabsElement.MIN_TABS
    assert padded["display"] == "carousel"
    assert padded["label_pos"] == "below"

    over = [{"id": f"t{i:06x}", "label": f"T{i}"} for i in range(TabsElement.MAX_TABS + 3)]
    truncated = TabsElement.normalize_data({"tabs": over, "display": "carousel", "label_pos": "hidden"})
    assert len(truncated["tabs"]) == TabsElement.MAX_TABS
    assert truncated["display"] == "carousel"
    assert truncated["label_pos"] == "hidden"


@pytest.mark.django_db
def test_save_round_trip_preserves_both_keys():
    """THE critical one. save() calls normalize_labels_and_ids and assigns its return
    to self.data, so a key missing from that literal is silently dropped on write."""
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel", "label_pos": "below"}
    )
    obj.refresh_from_db()
    assert obj.data["display"] == "carousel"
    assert obj.data["label_pos"] == "below"


def test_default_data_is_self_describing():
    d = TabsElement.default_data()
    assert d["display"] == "tabs"
    assert d["label_pos"] == "above"


@pytest.mark.django_db
def test_display_settings_agrees_with_the_normalizer_on_hostile_input():
    """One _coerce_enum helper, three call sites — they must not drift."""
    for hostile in (None, 42, "CAROUSEL", [], {}):
        obj = TabsElement(data={"tabs": [], "display": hostile, "label_pos": hostile})
        norm = TabsElement.normalize_labels_and_ids(obj.data)
        assert obj.display_settings() == {
            "display": norm["display"],
            "label_pos": norm["label_pos"],
        }
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_tabs_element.py -k "new_keys or hostile or round_trips or carries_the_keys or save_round_trip or self_describing or display_settings" -v
```
Expected: FAIL — `AttributeError: type object 'TabsElement' has no attribute 'display_settings'` and `KeyError: 'display'`.

- [ ] **Step 3: Add the constants and the coercion helper**

At the top of `courses/models.py`, add to the existing translation imports:

```python
from django.utils.translation import pgettext_lazy
```

(`pgettext_lazy` is already imported at line 18 — verify before adding a duplicate.)

Inside `class TabsElement(ElementBase)`, immediately after `TAB_ID_RE`:

```python
    # Ordered (value, lazy_label) pairs are the SINGLE declaration of each enum; the
    # membership collection is derived from it. A bare set plus a separate label map
    # would be two declarations that can silently disagree — a member with no label
    # renders a blank <option>, a label with no member coerces to the default on save.
    #
    # pgettext_lazy, not gettext_lazy: these are one-word adjectives whose Polish forms
    # are gendered ("Ukryta" agrees with *etykieta*) and would be wrong the moment the
    # bare msgid is reused for a masculine noun. Same reasoning as ImageElement.Size.
    DISPLAY_CHOICES = (
        ("tabs", pgettext_lazy("tabs display", "Tabs")),
        ("carousel", pgettext_lazy("tabs display", "Carousel")),
    )
    # TUPLE, deliberately not frozenset: `[] in frozenset(...)` raises TypeError on an
    # unhashable value, which would make the "never raises" normalizer raise and would
    # 500 _val_tabs on a hostile archive. `in` against a tuple uses == and never hashes.
    DISPLAYS = tuple(v for v, _label in DISPLAY_CHOICES)
    DEFAULT_DISPLAY = "tabs"

    LABEL_POS_CHOICES = (
        ("above", pgettext_lazy("tabs label position", "Above")),
        ("below", pgettext_lazy("tabs label position", "Below")),
        ("hidden", pgettext_lazy("tabs label position", "Hidden")),
    )
    LABEL_POSITIONS = tuple(v for v, _label in LABEL_POS_CHOICES)
    DEFAULT_LABEL_POS = "above"

    @staticmethod
    def _coerce_enum(value, allowed, default):
        """The ONE place the enum coercion lives. Called by normalize_labels_and_ids,
        display_settings and the form's editor accessors — three hand-copied versions
        would be the same drift hazard the *_CHOICES single source exists to prevent.
        The isinstance guard is belt-and-braces over the tuple membership."""
        return value if isinstance(value, str) and value in allowed else default
```

- [ ] **Step 4: Thread the keys through all three literal-rebuild sites**

**Site 1** — `normalize_labels_and_ids`, replace the final `return {"tabs": tabs}` with:

```python
        return {
            "tabs": tabs,
            # save() assigns this return to self.data, so a key omitted HERE is
            # silently dropped on every write — no exception, no log.
            "display": TabsElement._coerce_enum(
                data.get("display"), TabsElement.DISPLAYS, TabsElement.DEFAULT_DISPLAY
            ),
            "label_pos": TabsElement._coerce_enum(
                data.get("label_pos"),
                TabsElement.LABEL_POSITIONS,
                TabsElement.DEFAULT_LABEL_POS,
            ),
        }
```

**Site 2** — `normalize_data`, replace its final `return {"tabs": tabs}` with:

```python
        # Builds its OWN literal from norm["tabs"], so it inherits nothing for free.
        return {"tabs": tabs, "display": norm["display"], "label_pos": norm["label_pos"]}
```

**Site 3** — `default_data`, add both keys to the returned dict:

```python
        return {
            "tabs": [
                {"id": first, "label": "Tab 1"},
                {"id": second, "label": "Tab 2"},
            ],
            "display": TabsElement.DEFAULT_DISPLAY,
            "label_pos": TabsElement.DEFAULT_LABEL_POS,
        }
```

- [ ] **Step 5: Add `display_settings()`**

Immediately after the `normalized_data` property:

```python
    def display_settings(self):
        """The two enums, coerced, with NO tab-list work at all.

        render() uses this rather than normalized_data: it already passes
        resolved_tabs(), which calls normalize_data internally, so reading the enums
        from normalize_data too would run the DESTRUCTIVE normalizer twice per
        response — re-minting ids and re-padding a damaged blob, producing two
        disagreeing tab lists in one render."""
        data = self.data if isinstance(self.data, dict) else {}
        return {
            "display": self._coerce_enum(
                data.get("display"), self.DISPLAYS, self.DEFAULT_DISPLAY
            ),
            "label_pos": self._coerce_enum(
                data.get("label_pos"), self.LABEL_POSITIONS, self.DEFAULT_LABEL_POS
            ),
        }
```

- [ ] **Step 6: Amend the `_CONTAINER_REGISTRY` contract comment**

In `courses/builder.py`, the registry's docstring says "CONTRACT: each normalizer returns `{slot_list_key: [{slot_id_key: <id>}, ...]}`". `normalize_labels_and_ids` now returns three keys. No consumer breaks (`resolve_scope` and `paste_allowed` index by `list_key`), but the comment becomes false where a reader goes to learn the contract. Change that clause to:

```
# CONTRACT: each normalizer returns AT LEAST {slot_list_key: [{slot_id_key: <id>}, ...]};
# extra keys are permitted and ignored (TabsElement also returns display/label_pos).
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tabs_element.py -k "new_keys or hostile or round_trips or carries_the_keys or save_round_trip or self_describing or display_settings" -v
```
Expected: PASS (all).

- [ ] **Step 8: Falsify — three mutants, each must go RED**

1. Revert `normalize_labels_and_ids` to `return {"tabs": tabs}` → `test_save_round_trip_preserves_both_keys` must FAIL. Revert the mutant.
2. Revert `normalize_data` to `return {"tabs": tabs}` → `test_normalize_data_carries_the_keys_through_padding_and_truncation` must FAIL. Revert.
3. Change `DISPLAYS = tuple(...)` to `frozenset(...)` → the `[]` and `{}` parametrisations of `test_normalizers_coerce_hostile_values_without_raising` must FAIL with `TypeError: unhashable type`. Revert.

Record each observed failure before reverting. If any mutant leaves the file green, the test is not guarding what it claims.

- [ ] **Step 9: Run the existing tabs tests for regressions**

```bash
uv run pytest tests/test_tabs_element.py tests/test_tabs_partial.py -q
```
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add courses/models.py courses/builder.py tests/test_tabs_element.py
git commit -m "feat(tabs): add display/label_pos to the TabsElement data model

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Form — thread both keys, including the early-return branch

**Files:**
- Modify: `courses/element_forms.py` (`TabsElementForm`, ~line 1654-1720)
- Test: `tests/test_tabs_form.py` (existing file — append; create if absent)

**Interfaces:**
- Consumes: `TabsElement.DISPLAYS`, `.LABEL_POSITIONS`, `._coerce_enum`, `.default_data()` from Task 1.
- Produces: `TabsElementForm.editor_display -> str` and `.editor_label_pos -> str` (both `cached_property`), read by the template in Task 3.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from courses.element_forms import TabsElementForm
from courses.models import TabsElement


def _bound(payload_json):
    return TabsElementForm(data={"data": payload_json})


@pytest.mark.django_db
def test_clean_data_threads_both_keys():
    form = _bound(
        '{"tabs":[{"id":"taaaaaa","label":"A"},{"id":"tbbbbbb","label":"B"}],'
        '"display":"carousel","label_pos":"below"}'
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["display"] == "carousel"
    assert form.cleaned_data["data"]["label_pos"] == "below"


@pytest.mark.django_db
def test_the_tabs_is_none_early_return_branch_keeps_the_submitted_display():
    """`tabs` absent is the documented add-and-save-without-editing path; it returns
    default_data() and would otherwise drop a submitted display with no error."""
    form = _bound('{"display":"carousel","label_pos":"hidden"}')
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["display"] == "carousel"
    assert form.cleaned_data["data"]["label_pos"] == "hidden"
    assert len(form.cleaned_data["data"]["tabs"]) == TabsElement.MIN_TABS


@pytest.mark.django_db
def test_out_of_enum_coerces_rather_than_raising():
    form = _bound(
        '{"tabs":[{"id":"taaaaaa","label":"A"},{"id":"tbbbbbb","label":"B"}],'
        '"display":"CAROUSEL","label_pos":"sideways"}'
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["display"] == "tabs"
    assert form.cleaned_data["data"]["label_pos"] == "above"


@pytest.mark.django_db
def test_slide_count_bounds_still_raise():
    form = _bound('{"tabs":[{"id":"taaaaaa","label":"A"}],"display":"carousel"}')
    assert not form.is_valid()


@pytest.mark.django_db
def test_editor_accessors_reflect_submitted_data_on_a_bound_invalid_rerender():
    """One tab -> invalid; the author's Display choice must survive the re-render."""
    form = _bound('{"tabs":[{"id":"taaaaaa","label":"A"}],"display":"carousel","label_pos":"below"}')
    assert not form.is_valid()
    assert form.editor_display == "carousel"
    assert form.editor_label_pos == "below"


@pytest.mark.django_db
def test_editor_accessors_read_the_instance_when_unbound():
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel", "label_pos": "hidden"}
    )
    form = TabsElementForm(instance=obj)
    assert form.editor_display == "carousel"
    assert form.editor_label_pos == "hidden"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_form.py -k "threads_both or early_return or out_of_enum or bounds_still or editor_accessors" -v
```
Expected: FAIL — `KeyError: 'display'` / `AttributeError: 'TabsElementForm' object has no attribute 'editor_display'`.

- [ ] **Step 3: Thread the keys through `clean_data`**

In `TabsElementForm.clean_data`, replace the early-return branch and the final return:

```python
    def clean_data(self):
        raw = self.cleaned_data.get("data")
        raw = raw if isinstance(raw, dict) else {}
        tabs = raw.get("tabs")
        # Both keys ride along on EVERY return path. The normalizer does the coercion;
        # an out-of-enum value defaults rather than raising, matching the gallery's
        # desc_pos — the slide-count bounds below are different, they decide WHICH
        # tabs exist.
        extras = {"display": raw.get("display"), "label_pos": raw.get("label_pos")}
        if tabs is None:
            # Plain add + save with no edit -> the two default tabs. Built explicitly
            # rather than via normalize_data, because normalize_data is the DESTRUCTIVE
            # read-side normalizer and must never be reachable from a write path.
            return TabsElement.normalize_labels_and_ids(
                {**TabsElement.default_data(), **extras}
            )
        if not isinstance(tabs, list):
            raise forms.ValidationError(_("A tabs element needs a list of tabs."))
        if len(tabs) < TabsElement.MIN_TABS:
            raise forms.ValidationError(
                _("A tabs element must keep at least %(n)d tabs.")
                % {"n": TabsElement.MIN_TABS}
            )
        if len(tabs) > TabsElement.MAX_TABS:
            raise forms.ValidationError(
                _("A tabs element is limited to %(n)d tabs.")
                % {"n": TabsElement.MAX_TABS}
            )
        # Mints ids for new rows and preserves existing unique ones. Doing it HERE is
        # what lets save_element diff old-vs-new ids without ever touching a raw row.
        return TabsElement.normalize_labels_and_ids({"tabs": tabs, **extras})
```

- [ ] **Step 4: Add the two editor accessors**

Immediately after the `editor_rows` `cached_property`:

```python
    @cached_property
    def editor_display(self):
        """Same bound/unbound source selection as editor_rows, so an invalid
        re-render keeps the author's choice instead of snapping to the default."""
        source = self._raw_data_json() if self.is_bound else getattr(self.instance, "data", {})
        source = source if isinstance(source, dict) else {}
        return TabsElement._coerce_enum(
            source.get("display"), TabsElement.DISPLAYS, TabsElement.DEFAULT_DISPLAY
        )

    @cached_property
    def editor_label_pos(self):
        source = self._raw_data_json() if self.is_bound else getattr(self.instance, "data", {})
        source = source if isinstance(source, dict) else {}
        return TabsElement._coerce_enum(
            source.get("label_pos"),
            TabsElement.LABEL_POSITIONS,
            TabsElement.DEFAULT_LABEL_POS,
        )
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_tabs_form.py -v
```
Expected: PASS (all, including the pre-existing tests).

- [ ] **Step 6: Falsify**

Delete `**extras` from the `tabs is None` branch → `test_the_tabs_is_none_early_return_branch_keeps_the_submitted_display` must FAIL. Revert.
Delete `**extras` from the final return → `test_clean_data_threads_both_keys` must FAIL. Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py tests/test_tabs_form.py
git commit -m "feat(tabs): thread display/label_pos through TabsElementForm

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Editor UI — the two selects, the serializer, and `editor.css`

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (`tabs_bounds`, ~line 177)
- Modify: `templates/courses/manage/editor/_edit_tabs.html`
- Modify: `courses/static/courses/js/tabs_editor.js`
- Modify: `courses/static/courses/css/editor.css`
- Test: `tests/test_tabs_editor_partial.py` (append)

**Interfaces:**
- Consumes: `form.editor_display`, `form.editor_label_pos` (Task 2); `TabsElement.DISPLAY_CHOICES`, `.LABEL_POS_CHOICES` (Task 1).
- Produces: the hidden `name="data"` JSON now carries `display` and `label_pos`; DOM hooks `data-tab-display`, `data-tab-label-pos`, and the row class `tabs-editor__setting`.

- [ ] **Step 1: Write the failing tests**

```python
def test_tabs_editor_renders_both_setting_selects(client):
    html = _served_tabs_form(client)          # reuse the existing helper in this file
    assert "data-tab-display" in html
    assert "data-tab-label-pos" in html
    # No name= : the hidden name="data" field is the sole authoritative input.
    assert 'name="display"' not in html
    assert 'name="label_pos"' not in html


def test_every_choice_label_renders_as_non_empty_option_text(client):
    """Has teeth: goes RED if someone reintroduces a hand-written label map that
    drifts from DISPLAY_CHOICES. (Asserting DISPLAYS == the tuple's values would be
    tautological — it is derived from it one line below.)"""
    from courses.models import TabsElement
    html = _served_tabs_form(client)
    for _value, label in TabsElement.DISPLAY_CHOICES + TabsElement.LABEL_POS_CHOICES:
        assert f">{label}<" in html, f"missing option text for {label!r}"


def test_tabs_mode_renders_the_label_position_row_hidden_from_first_paint(client):
    """Server-rendered, not JS-only: a JS-only toggle means the row flashes visible
    until wire() runs, and this assertion would have nothing to assert."""
    html = _served_tabs_form(client)          # a fresh element defaults to display=tabs
    row = html.split('data-tab-label-pos-row')[0].rsplit("<", 1)[1]
    assert "hidden" in html.split("data-tab-label-pos-row")[0][-200:]


def test_editor_css_pairs_a_hidden_rule_for_every_flex_setting_row():
    """A [hidden] row that is display:flex stays visible — the UA rule loses to any
    author `display` regardless of specificity. Same trap editor.css records for
    .view-toggle."""
    css = (EDITOR_CSS).read_text(encoding="utf-8")
    assert ".tabs-editor__setting[hidden]" in css
    assert "display: none" in css.split(".tabs-editor__setting[hidden]")[1][:80]
```

Reuse the file's existing `_served_tabs_form` / `EDITOR_CSS` helpers; if the served-form helper does not exist, model it on `test_served_tabs_form_carries_the_bounds_the_js_reads`.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_editor_partial.py -k "setting_selects or choice_label or first_paint or pairs_a_hidden" -v
```
Expected: FAIL on missing `data-tab-display`.

- [ ] **Step 3: Extend `tabs_bounds`**

```python
def tabs_bounds():
    """Bounds the tabs label editor renders into data-* attributes, plus the two
    display-setting enums as ordered (value, label) pairs. Sourced from the model
    constants so the template never hardcodes a member or a label."""
    return {
        "min": TabsElement.MIN_TABS,
        "max": TabsElement.MAX_TABS,
        "label_max": TabsElement.LABEL_MAX,
        "displays": TabsElement.DISPLAY_CHOICES,
        "label_positions": TabsElement.LABEL_POS_CHOICES,
    }
```

- [ ] **Step 4: Add the two selects to `_edit_tabs.html`**

Insert immediately after the hidden `data` input, before `<ol class="tabs-editor__rows">`:

```html
  {% comment %}Wrapped <label>, not for="…": a for= reference needs stable collision-free
  ids in a partial injected by fragment swap, and _edit_gallery.html already uses the
  wrapping form. Neither select carries a name — the hidden name="data" field above is the
  SOLE authoritative input and tabs_editor.js mirrors these into it.

  data-tab-* here, but data-display / data-label-pos on the STUDENT root: test_tabs_partial
  asserts html.count("data-tab-label") == 2 against the student markup, and naming the
  student attribute data-tab-label-pos would push that to 3. Do NOT harmonise the two.{% endcomment %}
  <div class="tabs-editor__setting">
    <label>{% trans "Display" %}
      <select data-tab-display>
        {% for value, text in tb.displays %}
          <option value="{{ value }}" {% if form.editor_display == value %}selected{% endif %}>{{ text }}</option>
        {% endfor %}
      </select>
    </label>
  </div>
  <div class="tabs-editor__setting" data-tab-label-pos-row {% if form.editor_display != "carousel" %}hidden{% endif %}>
    <label>{% trans "Label position" %}
      <select data-tab-label-pos>
        {% for value, text in tb.label_positions %}
          <option value="{{ value }}" {% if form.editor_label_pos == value %}selected{% endif %}>{{ text }}</option>
        {% endfor %}
      </select>
    </label>
  </div>
```

- [ ] **Step 5: Update `tabs_editor.js`**

Inside `wire(editor)`, after the `rows`/`addBtn` lookups:

```js
    var displaySel = editor.querySelector("[data-tab-display]");
    var labelPosSel = editor.querySelector("[data-tab-label-pos]");
    var labelPosRow = editor.querySelector("[data-tab-label-pos-row]");
```

Replace `serialize()`'s final line so it reads the selects' **live** values:

```js
      hidden.value = JSON.stringify({
        tabs: tabs,
        // Read from the DOM, never from a captured initial value: this function is the
        // only thing that writes the authoritative field, and a saved carousel that
        // re-serialises without these silently reverts to tabs on a no-op Save.
        display: displaySel ? displaySel.value : "tabs",
        label_pos: labelPosSel ? labelPosSel.value : "above",
      });
```

Add the row toggle and the change listeners, then invoke the toggle once at the end of `wire()`:

```js
    function syncLabelPosRow() {
      if (!labelPosRow) return;
      var on = displaySel && displaySel.value === "carousel";
      if (on) { labelPosRow.removeAttribute("hidden"); }
      else { labelPosRow.setAttribute("hidden", ""); }
    }
    if (displaySel) displaySel.addEventListener("change", function () {
      syncLabelPosRow();
      serialize();
    });
    if (labelPosSel) labelPosSel.addEventListener("change", serialize);
```

and just above the existing `if (hidden.value === "") serialize();`:

```js
    // Once at init, not only from the change listener: wire() runs once per editor and
    // `change` fires only on interaction, so a listener-only version shows the row on
    // every saved TABS element until the author touches the Display select. The
    // template renders the initial `hidden` too — this is the idempotent re-assertion.
    syncLabelPosRow();
```

- [ ] **Step 6: Add the `editor.css` rules**

```css
/* Tabs editor display settings. REQUIRED: .tabs-editor__setting is flex, and an author
   `display` overrides the UA [hidden]{display:none} rule regardless of specificity —
   without the paired rule the label-position row would still show in tabs mode. Same
   trap as .view-toggle[hidden] above. */
.tabs-editor__setting { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.tabs-editor__setting[hidden] { display: none; }
.tabs-editor__setting label { display: inline-flex; align-items: center; gap: var(--space-2); font-size: .82rem; color: var(--text-secondary); }
```

- [ ] **Step 7: Run to verify pass**

```bash
uv run pytest tests/test_tabs_editor_partial.py -v
```
Expected: PASS (all, including `test_editor_css_styles_every_tabs_editor_class`, which scans the partial for `tabs-editor__*` classes).

- [ ] **Step 8: Falsify**

Delete `.tabs-editor__setting[hidden] { display: none; }` → `test_editor_css_pairs_a_hidden_rule_for_every_flex_setting_row` must FAIL. Revert.
Remove the `{% if form.editor_display != "carousel" %}hidden{% endif %}` → `test_tabs_mode_renders_the_label_position_row_hidden_from_first_paint` must FAIL. Revert.

- [ ] **Step 9: Commit**

```bash
git add courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_edit_tabs.html courses/static/courses/js/tabs_editor.js courses/static/courses/css/editor.css tests/test_tabs_editor_partial.py
git commit -m "feat(tabs): add Display and Label position controls to the tabs editor

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Student template — the stage wrapper and the two data attributes

**Files:**
- Modify: `templates/courses/elements/tabselement.html`
- Modify: `courses/models.py` (`TabsElement.render`)
- Test: `tests/test_tabs_partial.py` (append)

**Interfaces:**
- Consumes: `display_settings()` (Task 1).
- Produces: markup contract `.el--tabs[data-display][data-label-pos] > .tabs__stage > .tabs__section`, relied on by every CSS child chain (Task 6) and by `ownSections` (Task 7).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_render_emits_both_data_attributes():
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel", "label_pos": "below"}
    )
    Element.objects.create(unit=_unit(), content_object=obj)
    html = obj.render()
    assert 'data-display="carousel"' in html
    assert 'data-label-pos="below"' in html


@pytest.mark.django_db
def test_the_stage_wrapper_is_present_in_both_modes():
    for display in ("tabs", "carousel"):
        obj = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": display}
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        assert 'class="tabs__stage"' in obj.render()


@pytest.mark.django_db
def test_markup_is_identical_between_modes_apart_from_the_two_attributes():
    """This is what pins the no-JS and print fallback: the server emits ONE layout."""
    rendered = {}
    for display in ("tabs", "carousel"):
        obj = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": display}
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        rendered[display] = obj.render().replace(f'data-display="{display}"', "DISPLAY")
    # tab ids are random per element; normalise them before comparing
    assert _strip_tab_ids(rendered["tabs"]) == _strip_tab_ids(rendered["carousel"])


@pytest.mark.django_db
def test_the_caption_node_is_present_in_all_three_label_positions():
    """Hidden by CSS, never omitted — dropping it would strip the title from print."""
    for pos in ("above", "below", "hidden"):
        obj = TabsElement.objects.create(
            data={**TabsElement.default_data(), "display": "carousel", "label_pos": pos}
        )
        Element.objects.create(unit=_unit(), content_object=obj)
        assert obj.render().count("data-tab-label") == 2


@pytest.mark.django_db
def test_render_calls_the_destructive_normalizer_exactly_once(monkeypatch):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=_unit(), content_object=obj)
    calls = []
    original = TabsElement.normalize_data
    monkeypatch.setattr(
        TabsElement, "normalize_data",
        staticmethod(lambda d: (calls.append(1), original(d))[1]),
    )
    obj.render()
    assert len(calls) == 1, "render must read the enums via display_settings(), not normalize_data"
```

Add a module-level `_strip_tab_ids(html)` helper using `re.sub(r"t[0-9a-f]{6}", "TID", html)`.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_partial.py -k "data_attributes or stage_wrapper or identical_between or all_three_label or exactly_once" -v
```
Expected: FAIL — no `data-display` in the markup.

- [ ] **Step 3: Rewrite the template**

Replace `templates/courses/elements/tabselement.html` entirely:

```html
{% load courses_extras %}
{% comment %}
Student-facing tabs, in TWO display modes. `tabs` is [(tab, [child Element rows])] from
TabsElement.resolved_tabs(); EVERY tab is emitted, including empty ones, because a new
tabs element is born with two empty tabs.

THE SERVER EMITS ONE LAYOUT FOR BOTH MODES — all sections visible, each under its
heading. That markup IS the no-JS fallback and is exactly what @media print shows;
`data-display` only tells the enhancer which way to upgrade it.

  display="tabs"     -> tabs.js builds a role=tablist strip and hides inactive panels
                        with the `hidden` ATTRIBUTE (never an inline display:none, which
                        a print rule could not override).
  display="carousel" -> tabs.js builds a ‹ › + dots nav and hides inactive SECTIONS with
                        position:absolute + opacity:0 + aria-hidden + inert, so they stay
                        laid out and measurable. NOT the `hidden` attribute: display:none
                        would zero offsetHeight and collapse the height reservation.

.tabs__stage is server-rendered in BOTH modes even though only the carousel styles it.
Having the JS create it and re-parent the sections would RELOAD any <iframe> inside a
slide (a video or GeoGebra embed is a legal child), and the editor preview re-enhances
after every save/add/reorder swap.

DOM ids are namespaced with the join row pk (`eid`): a tab id is unique only WITHIN one
element and two tabs elements on one page may legitimately share one.

data-label-pos here, NOT data-tab-label-pos: test_tabs_partial counts the
"data-tab-label" substring to assert the caption count, and the longer name would
inflate it. The editor partial uses the data-tab-* prefix for its own controls; the two
namespaces are deliberately NOT harmonised.
{% endcomment %}
<div class="el el--tabs" data-tabs data-tabs-eid="{{ eid }}"
     data-display="{{ display }}" data-label-pos="{{ label_pos }}">
  <div class="tabs__stage">
    {% for tab, children in tabs %}
      <section class="tabs__section">
        <h3 class="tabs__panel-label" data-tab-label id="tabs-{{ eid }}-{{ tab.id }}-label">{{ tab.label }}</h3>
        <div class="tabs__panel" data-tab-panel data-tab-id="{{ tab.id }}"
             id="tabs-{{ eid }}-{{ tab.id }}-panel">
          {% for child in children %}
            <div class="tabs__child">{% render_element child %}</div>
          {% endfor %}
        </div>
      </section>
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 4: Feed the two keys into the render context**

In `TabsElement.render`, splat `display_settings()`:

```python
        return render_to_string(
            "courses/elements/tabselement.html",
            {
                "el": self,
                "tabs": self.resolved_tabs(),
                "eid": element.pk if element is not None else 0,
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
                # display_settings(), NOT normalized_data: resolved_tabs() already runs
                # normalize_data once, and running the DESTRUCTIVE normalizer twice per
                # response would re-mint ids on a damaged blob.
                **self.display_settings(),
            },
        )
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_tabs_partial.py -v
```
Expected: PASS (all, including the pre-existing `data-tab-panel == 2` / `data-tab-label == 2` counts).

- [ ] **Step 6: Falsify**

Change `**self.display_settings()` to `**self.normalized_data` → `test_render_calls_the_destructive_normalizer_exactly_once` must FAIL (2 calls). Revert.
Remove the `<div class="tabs__stage">` wrapper → `test_the_stage_wrapper_is_present_in_both_modes` must FAIL. Revert.

- [ ] **Step 7: Regression-check the container siblings**

The wrapper is new markup inside a container that other suites render.

```bash
uv run pytest tests/test_tabs_partial.py tests/test_nesting_rule.py tests/test_tabs_transfer.py -q
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/elements/tabselement.html courses/models.py tests/test_tabs_partial.py
git commit -m "feat(tabs): server-render the stage wrapper and the display data attributes

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: i18n — the carousel strings in all three templates

**Files:**
- Modify: `templates/courses/lesson_unit.html:80`, `templates/courses/quiz_unit.html:33`, `templates/courses/manage/editor/editor.html:168`
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_tabs_css.py` (append — it already loops these three paths)

**Interfaces:**
- Produces: `window.TABS_I18N` keys `carouselNav`, `prevSlide`, `nextSlide`, `goToSlide`, `slidePos`, consumed by Task 7.

- [ ] **Step 1: Write the failing test**

```python
TABS_I18N_TEMPLATES = [           # the SAME three paths the loads-tabs-js test walks
    TEMPLATES / "courses/lesson_unit.html",
    TEMPLATES / "courses/quiz_unit.html",
    TEMPLATES / "courses/manage/editor/editor.html",
]
CAROUSEL_I18N_KEYS = ["carouselNav", "prevSlide", "nextSlide", "goToSlide", "slidePos"]


@pytest.mark.parametrize("path", TABS_I18N_TEMPLATES)
def test_every_tabs_i18n_template_carries_every_carousel_key(path):
    """The literal is duplicated in three templates. A template missing a key does NOT
    fall back to English: tabs.js reads `window.TABS_I18N || {…}`, so the defaults
    object is used only when the global is ENTIRELY absent — a partial object yields
    undefined and throws on .replace."""
    html = path.read_text(encoding="utf-8")
    for key in CAROUSEL_I18N_KEYS:
        assert f"{key}:" in html, f"{path.name} is missing TABS_I18N.{key}"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_css.py -k carousel_key -v
```
Expected: FAIL for all three paths.

- [ ] **Step 3: Extend the literal in all three templates, identically**

```html
  <script>window.TABS_I18N = { nav: "{% trans 'Tabs' %}", prev: "{% trans 'Scroll tabs left' %}", next: "{% trans 'Scroll tabs right' %}", carouselNav: "{% trans 'Carousel' %}", prevSlide: "{% trans 'Previous slide' %}", nextSlide: "{% trans 'Next slide' %}", goToSlide: "{% trans 'Go to slide {n}' %}", slidePos: "{% trans 'Slide {n} of {total}' %}" };</script>
```

Apply the **same** line to all three files. `carouselNav` is separate from `nav` on purpose — reusing `nav` would announce the carousel's landmark as "Tabs".

- [ ] **Step 4: Regenerate and translate the catalog**

```bash
uv run python manage.py makemessages -l pl
```

Open `locale/pl/LC_MESSAGES/django.po` and fill in every new msgid. ⚠️ `makemessages` pre-fills near-matches as **fuzzy with a WRONG translation** — clearing one means deleting *two* things: the `#, fuzzy` flag **and** the wrong `msgstr`. Translations:

| msgid | msgstr |
|---|---|
| `Carousel` (ctxt `tabs display`) | `Karuzela` |
| `Tabs` (ctxt `tabs display`) | `Zakładki` |
| `Above` (ctxt `tabs label position`) | `Nad` |
| `Below` (ctxt `tabs label position`) | `Pod` |
| `Hidden` (ctxt `tabs label position`) | `Ukryta` |
| `Display` | `Wyświetlanie` |
| `Label position` | `Pozycja etykiety` |
| `Carousel` (no ctxt, the nav landmark) | `Karuzela` |
| `Previous slide` | `Poprzedni slajd` |
| `Next slide` | `Następny slajd` |
| `Go to slide {n}` | `Przejdź do slajdu {n}` |
| `Slide {n} of {total}` | `Slajd {n} z {total}` |

```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/test_tabs_css.py -k "carousel_key or loads_tabs_js" -v
```
Expected: PASS.

- [ ] **Step 6: Falsify**

Remove `prevSlide` from `quiz_unit.html` only → the `quiz_unit.html` parametrisation must FAIL while the other two pass. Revert.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/lesson_unit.html templates/courses/quiz_unit.html templates/courses/manage/editor/editor.html locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_tabs_css.py
git commit -m "feat(tabs): add the carousel i18n strings to all three TABS_I18N surfaces

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: CSS — carousel styles, the four scoped rules, and the print resets

**Files:**
- Modify: `courses/static/courses/css/courses.css` (`.el--tabs` block ~1488-1548)
- Modify: `tests/test_tabs_partial.py` (`_print_block`, `_screen_label_rule` helpers + new assertions)

**Interfaces:**
- Consumes: the markup contract from Task 4; the `.tabs--carousel` gate class and the JS-built class names from Task 7.
- Produces: the visual contract the e2e in Task 11 asserts against.

- [ ] **Step 1: Widen the two test helpers FIRST, then write the failing assertions**

Replace `_print_block`'s slice — keep the existing `.el--tabs` chunk-selection loop and clip the **selected chunk** at its closing brace:

```python
def _print_block():
    """The @media print body for .el--tabs. Split on the literal brace so a prose
    comment merely mentioning "@media print" cannot masquerade as the rule."""
    css = CSS.read_text(encoding="utf-8")
    for chunk in css.split("@media print"):
        if ".el--tabs" in chunk[:1200]:
            # Clip at the media block's closing brace, NOT at a character count: past
            # that brace the chunk is ordinary SCREEN css, and a fixed window would let
            # the carousel's screen rules satisfy a "the print block contains …"
            # assertion — a silent green with no print reset at all. Precedent:
            # courses/tests/test_reveal_scope_agreement.py::_print_block.
            m = re.search(r"\{(.*?)\n\}", chunk, re.S)
            assert m, "could not find the closing brace of the .el--tabs print block"
            return m.group(1)
    raise AssertionError("no @media print block found for .el--tabs")
```

Widen `_screen_label_rule`'s matcher — the child chain destroys its old `class space class` substring:

```python
def _screen_label_rule():
    """The rule that hides the per-panel labels on screen once JS enhances.
    Matched by [data-display="tabs"] + .tabs__panel-label rather than by the old
    ".tabs--js .tabs__panel-label" substring: the rule now takes an explicit child
    chain (so it cannot reach a carousel nested inside a tabs panel), which the old
    matcher could never find."""
    css = CSS.read_text(encoding="utf-8")
    line = next(
        ln for ln in css.splitlines()
        if '[data-display="tabs"]' in ln and ".tabs__panel-label" in ln
    )
    decls = line.split("{")[1].split("}")[0]
    props = {p.split(":")[0].strip() for p in decls.split(";") if p.strip()}
    assert props, "the screen label rule must stay on ONE physical line, declarations included"
    assert {"position", "clip"} <= props, f"unexpected screen label rule: {props}"
    return props
```

New assertions:

```python
def test_carousel_print_reset_is_present_and_fully_important():
    """Printing a carousel must not silently lose every slide but the current one.
    A human running print preview is not a defence against a later tidy-up."""
    block = _print_block()
    assert '[data-display="carousel"]' in block
    for line in block.splitlines():
        if '[data-display="carousel"]' not in line:
            continue
        decls = line.split("{")[1].split("}")[0]
        for decl in [d for d in decls.split(";") if d.strip()]:
            assert "!important" in decl, f"print reset declaration lacks !important: {decl.strip()}"


def test_every_slide_hiding_rule_carries_the_carousel_gate():
    """The gate must be .tabs--carousel (added only after a successful show(0)), never
    .tabs--js (added before the branch is even entered) — otherwise a throw part-way
    through init leaves every slide at opacity 0 with nothing to re-show it: blank.

    Keyed on the selector SUBJECT plus the opacity/pointer-events pair unique to the
    slide rule. A substring predicate would flag the legitimate tabs-mode label rule,
    which also contains ".tabs__section" and "position: absolute" on one line."""
    css = CSS.read_text(encoding="utf-8")
    for line in css.splitlines():
        if "{" not in line:
            continue
        selector, decls = line.split("{", 1)
        if not selector.rstrip().endswith(".tabs__section"):
            continue
        if "opacity: 0" in decls and "pointer-events: none" in decls:
            assert ".tabs--carousel" in selector, f"slide rule missing the gate: {selector.strip()}"


def test_carousel_rules_use_child_combinators():
    """A descendant selector would match a NESTED tabs element's sections and render it
    completely blank (the inner instance hides panels with `hidden`, never adds
    .is-active to a section, so nothing restores opacity)."""
    css = CSS.read_text(encoding="utf-8")
    for line in css.splitlines():
        if ".tabs--carousel" not in line or "{" not in line:
            continue
        selector = line.split("{")[0]
        if ".tabs__section" in selector or ".tabs__stage" in selector:
            assert "> .tabs__stage" in selector, f"missing child chain: {selector.strip()}"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_partial.py -k "print_reset or slide_hiding or child_combinators or print_label" -v
```
Expected: FAIL — no carousel rules exist yet, and `_screen_label_rule` raises `StopIteration`.

- [ ] **Step 3: Scope the four existing tabs-mode rules**

In `courses.css`, edit in place. **Keep each label rule on ONE physical line.**

```css
/* Screen, TABS MODE ONLY: once enhanced, the per-panel headings are hidden by CLASS
   (never an inline style) so the print rule below can override them. The child chain is
   mandatory — a descendant selector would clip the captions of a CAROUSEL nested inside
   one of these panels. */
.el--tabs[data-display="tabs"].tabs--js > .tabs__stage > .tabs__section > .tabs__panel-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
```

Scope the panel padding (both halves take the child chain):

```css
.el--tabs[data-display="tabs"] > .tabs__stage > .tabs__section > .tabs__panel { padding-top: var(--space-5); }
```

- [ ] **Step 4: Add the carousel block**

Append after the existing `.el--tabs` screen rules:

```css
/* ---- Carousel mode -------------------------------------------------------------
   Gated on .tabs--carousel, which tabs.js adds ONLY after a successful show(0).
   NOT .tabs--js: that class is applied before the branch is entered, so a throw
   part-way through init would leave every slide absolutely positioned at opacity 0
   with nothing to re-show it — blank, not the stacked fallback.
   Every rule uses an explicit child chain: `tabs` is nestable, and a descendant
   selector would blank a tabs element nested inside a slide. */
.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage { position: relative; }
.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage > .tabs__section { position: absolute; top: 0; left: 0; width: 100%; opacity: 0; pointer-events: none; transition: opacity 320ms ease; }  /* 320ms == FADE_MS in tabs.js */
.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage > .tabs__section.is-active { opacity: 1; pointer-events: auto; }

/* label_pos: "below" is a CSS-only reorder — the h3 always precedes the panel in the
   DOM and the server markup may not change. Scoped to [data-label-pos="below"] and NOT
   applied to every carousel: a flex ancestor's default min-inline-size can defeat a
   nested overflow-x:auto box, and a wide table is this feature's primary payload. */
.el--tabs.tabs--carousel[data-display="carousel"][data-label-pos="below"] > .tabs__stage > .tabs__section { display: flex; flex-direction: column; }
.el--tabs.tabs--carousel[data-display="carousel"][data-label-pos="below"] > .tabs__stage > .tabs__section > .tabs__panel-label { order: 1; }
/* Screen-only. The unscoped !important print reveal still un-clips it, so a printed
   carousel shows every title even when the author hid it — deliberate: a printed page
   has no navigation and untitled slabs would be unreadable. Declares a SUBSET of the
   seven properties that reveal resets; clip-path or margin/border/padding would not be
   undone and would silently lose the captions in print. */
.el--tabs.tabs--carousel[data-display="carousel"][data-label-pos="hidden"] > .tabs__stage > .tabs__section > .tabs__panel-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

/* Caption typography: in tabs mode this h3 is always clipped, so it has never been
   styled as visible text. As a slide caption it must not inherit the heavy global h3. */
.el--tabs[data-display="carousel"] > .tabs__stage > .tabs__section > .tabs__panel-label { font-size: .95rem; font-weight: 500; color: var(--text-secondary); text-align: center; margin: 0 0 var(--space-3); }
/* Spacing, attribute-only (no gate class): it adds nothing but spacing, so it is safe
   unenhanced and keeps the no-JS stacked fallback readable. */
.el--tabs[data-display="carousel"] > .tabs__stage > .tabs__section > .tabs__panel { padding-top: 0; }

/* Nav bar: mirrors .gallery__bar exactly (same navigable-media pattern). */
.el--tabs .tabs__cbar { display: flex; align-items: center; justify-content: center; gap: var(--space-4); margin-top: var(--space-4); }
.el--tabs .tabs__cprev,
.el--tabs .tabs__cnext {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2.15rem; height: 2.15rem; padding: 0;
  border-radius: .5rem; border: 1px solid var(--border-strong);
  background: var(--surface-raised); color: var(--text-primary); cursor: pointer;
}
.el--tabs .tabs__cprev:hover,
.el--tabs .tabs__cnext:hover { border-color: var(--primary); color: var(--primary); }
.el--tabs .tabs__cprev:disabled,
.el--tabs .tabs__cnext:disabled { opacity: .45; pointer-events: none; cursor: default; }
.el--tabs .tabs__cprev .ic,
.el--tabs .tabs__cnext .ic { width: 1.1rem; height: 1.1rem; }
.el--tabs .tabs__dots { display: flex; align-items: center; gap: .5rem; }
.el--tabs .tabs__dot {
  width: 8px; height: 8px; padding: 0; border: 0; border-radius: 50%;
  background: var(--border-strong); cursor: pointer;
  transition: width .3s ease, background .3s ease;
}
.el--tabs .tabs__dot.is-active { width: 20px; border-radius: 5px; background: var(--primary); }
/* Clip-based sr-only: stays in the a11y/text tree so aria-live announces and Playwright
   can read its text — NOT display:none / visibility:hidden. */
.el--tabs .tabs__status {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}

@media (prefers-reduced-motion: reduce) {
  /* Zeroing only the JS settle timer would leave this transition animating under an
     already-inert slide. */
  .el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage > .tabs__section { transition: none; }
}
```

- [ ] **Step 5: Append the print resets (append — never insert before the existing rules)**

Inside the existing `.el--tabs` `@media print` block, **after** its current three rules:

```css
  /* Carousel: the reveal above keys on [role="tabpanel"][hidden], which carousel slides
     do not have — they are hidden by absolute positioning + opacity. Without these,
     printing a carousel silently loses every slide but the current one.
     EVERY declaration needs !important: the screen rule is specificity 0-5-0, and the
     stage's min-height is set INLINE by measure(), which no author rule can override
     without it. `display: block` also neutralises the label_pos:"below" flex order, so
     a printed slide always shows its title above its content. */
  .el--tabs[data-display="carousel"] > .tabs__stage { position: static !important; min-height: 0 !important; }
  .el--tabs[data-display="carousel"] > .tabs__stage > .tabs__section { position: static !important; opacity: 1 !important; display: block !important; }
  .el--tabs .tabs__cbar, .el--tabs .tabs__status { display: none !important; }
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_tabs_partial.py -v
```
Expected: PASS (all, including the two pre-existing print tests).

- [ ] **Step 7: Falsify — four mutants**

1. Change one print-reset declaration to drop `!important` → `test_carousel_print_reset_is_present_and_fully_important` FAILS.
2. Change the slide rule's gate from `.tabs--carousel` to `.tabs--js` → `test_every_slide_hiding_rule_carries_the_carousel_gate` FAILS.
3. Change a carousel selector's `> .tabs__stage >` to a descendant space → `test_carousel_rules_use_child_combinators` FAILS.
4. Reflow the tabs-mode label rule onto two lines → `_screen_label_rule`'s non-vacuity assertion FAILS (this is the guard that stops the print-reset test passing vacuously).

Revert each.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_tabs_partial.py
git commit -m "feat(tabs): add carousel-mode styles, scoped rules and print resets

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `tabs.js` — the carousel branch, ported from `gallery.js::show`

**Files:**
- Modify: `courses/static/courses/js/tabs.js`
- Test: `tests/test_tabs_css.py` (append source assertions)

**Interfaces:**
- Consumes: markup from Task 4, CSS classes from Task 6, `TABS_I18N` keys from Task 5.
- Produces: `.tabs--carousel` on a successfully-initialised carousel; the nav DOM (`tabs__cbar`, `tabs__cprev`, `tabs__cnext`, `tabs__dots`, `tabs__dot`, `tabs__status`); `show(n)`, consumed by Task 8's keyboard handler.

> **⚠️ THE NORMATIVE INSTRUCTION FOR THIS TASK: PORT `courses/static/courses/js/gallery.js::show` — DO NOT RE-DERIVE IT.** Open that file and transcribe. The permitted departures are exactly five: the `dead` guard, step 4b (the boundary focus transfer), the `libli:reveal` dispatches, the four-filter `rescueFocus` predicate (Task 8), and the absence of the `useDots`/counter branch. **Before calling this task done, diff your `show()` against `gallery.js::show` line by line; any other difference is a defect.** Several drafts of the spec tried to restate this function from intent and each dropped a guard that produced a silent total failure.

- [ ] **Step 1: Write the failing source assertions**

```python
JS = STATIC / "courses/js/tabs.js"


def test_the_carousel_gate_class_is_added_after_show_zero():
    """The gate must go on LAST. .tabs--js is applied before the branch is entered, so
    gating on it would leave a half-initialised carousel blank rather than stacked."""
    js = JS.read_text(encoding="utf-8")
    assert 'classList.add("tabs--carousel")' in js
    assert js.index("show(0)") < js.index('classList.add("tabs--carousel")'), \
        "the gate class must be added after show(0) succeeds"


def test_the_carousel_branch_has_a_catch_that_clears_inert_and_aria_hidden():
    """A class gate closes only the CSS half. inert/aria-hidden are JS-written
    ATTRIBUTES — no class can un-apply them, and the rest-init loop sets both on every
    section before show(0) runs."""
    js = JS.read_text(encoding="utf-8")
    assert "catch" in js
    tail = js[js.index("catch"):]
    assert 'removeAttribute("inert")' in tail
    assert 'removeAttribute("aria-hidden")' in tail
    assert 'classList.remove("tabs--js")' in tail
    assert 'classList.remove("tabs--carousel")' in tail


def test_every_new_carousel_class_is_a_single_token_literal():
    """The drift guard is re.findall(r'className = "([\\w-]*tabs__[\\w-]+)"'). A space is
    not in [\\w-], so a base+modifier literal matches NOTHING and both classes ship
    unguarded. Also: no classList.add for a styled base class."""
    js = JS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js))
    for cls in ["tabs__cbar", "tabs__cprev", "tabs__cnext", "tabs__dots", "tabs__dot", "tabs__status"]:
        assert cls in emitted, f"{cls} is invisible to the style-drift guard"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_css.py -k "gate_class or catch_that_clears or single_token" -v
```
Expected: FAIL.

- [ ] **Step 3: Extend the i18n defaults, per key**

At the top of `tabs.js`, replace the `i18n` line:

```js
  // Per-key defaults. `window.TABS_I18N || {…}` uses the fallback object ONLY when the
  // global is entirely absent — and all three templates always define it. So a template
  // missing a carousel key yields undefined, not English: aria-label="undefined" and a
  // throw on .replace. Read every key through t().
  var i18n = window.TABS_I18N || {};
  function t(key, fallback) {
    var v = i18n[key];
    return typeof v === "string" ? v : fallback;
  }
  var FADE_MS = 320;  // MUST match the .el--tabs carousel transition in courses.css
```

Replace the three existing `i18n.nav` / `i18n.prev` / `i18n.next` reads in the tabs branch with `t("nav", "Tabs")`, `t("prev", "Scroll tabs left")`, `t("next", "Scroll tabs right")`.

- [ ] **Step 4: Branch in `initOne`**

Immediately after `container.classList.add("tabs--js");`:

```js
    // EXACT match only: null, "", a stale cached fragment or a future third mode all
    // fall through to the tab strip. There is no undefined third path. (The CSS keys
    // tabs-mode rules on the literal [data-display="tabs"] — a deliberate asymmetry,
    // since a blank element is a worse failure than a duplicated label.)
    if (container.getAttribute("data-display") === "carousel") {
      initCarousel(container, sections, eid);
      return;
    }
```

- [ ] **Step 5: Write `initCarousel`**

Add above `initTabs`. Transcribe `show` from `gallery.js`; the annotated departures are marked.

```js
  function iconBtn(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = cls;              // single-token literal: the drift guard needs it
    b.setAttribute("aria-label", label);
    b.title = label;
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initCarousel(container, sections, eid) {
    var stage = container.querySelector(".tabs__stage");
    if (!stage || sections.length < 2) return;

    // PER-INSTANCE closure state, declared together (gallery.js:31-32). Never at module
    // scope: a shared `pending` would let one carousel finalise another's in-flight
    // fade, and a carousel may legally contain a carousel.
    var idx = -1, dead = false, pending = null;
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");

    var nav = document.createElement("nav");
    nav.className = "tabs__cbar";
    nav.setAttribute("aria-label", t("carouselNav", "Carousel"));
    var prev = iconBtn("tabs__cprev", "M15 6l-6 6 6 6", t("prevSlide", "Previous slide"));
    var next = iconBtn("tabs__cnext", "M9 6l6 6-6 6", t("nextSlide", "Next slide"));
    var dotWrap = document.createElement("div");
    dotWrap.className = "tabs__dots";
    var dots = sections.map(function (_s, k) {
      var d = document.createElement("button");
      d.type = "button";
      d.className = "tabs__dot";
      d.setAttribute("aria-label", t("goToSlide", "Go to slide {n}").replace("{n}", k + 1));
      d.addEventListener("click", function () { show(k); });
      dotWrap.appendChild(d);
      return d;
    });
    var status = document.createElement("span");
    status.className = "tabs__status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    nav.appendChild(prev); nav.appendChild(dotWrap); nav.appendChild(next); nav.appendChild(status);

    function clamp(n) { return Math.max(0, Math.min(sections.length - 1, n)); }

    function settleHidden(el) {
      el.classList.remove("is-active");
      el.style.opacity = "";
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("inert", "");
    }

    function finalizePending() {
      if (!pending) return;          // REQUIRED: pending is unset for the first TWO calls
      clearTimeout(pending.timer);
      if (pending.out && pending.out !== pending.inn) settleHidden(pending.out);
      pending.inn.classList.add("is-active");
      pending.inn.style.opacity = "";
      pending = null;
    }

    function updateIndicator() {
      dots.forEach(function (d, k) {
        d.classList.toggle("is-active", k === idx);
        if (k === idx) { d.setAttribute("aria-current", "true"); }
        else { d.removeAttribute("aria-current"); }
      });
      // Folded in here exactly as gallery.js does (:95), NOT deferred: the first show
      // must evaluate this string — the forced-throw e2e depends on it.
      status.textContent = t("slidePos", "Slide {n} of {total}")
        .replace("{n}", idx + 1).replace("{total}", sections.length);
    }

    function show(n) {
      if (dead) return;                                     // DEPARTURE: error-bail guard
      var target = clamp(n);
      if (idx !== -1 && target === idx) return;             // sentinel-aware
      finalizePending();
      var focusedArrow = document.activeElement === prev ? prev
                       : document.activeElement === next ? next : null;   // capture, see 4b
      var out = sections[idx];       // undefined on the first call, because idx === -1
      idx = target;
      var inn = sections[idx];
      updateIndicator();
      prev.disabled = idx === 0;
      prev.setAttribute("aria-disabled", idx === 0 ? "true" : "false");
      next.disabled = idx === sections.length - 1;
      next.setAttribute("aria-disabled", idx === sections.length - 1 ? "true" : "false");
      // 4b, DEPARTURE: disabling the focused element blurs it to <body>, which puts
      // focus outside the container and kills the keydown handler. Mutually exclusive
      // with rescueFocus by construction (that returns early when focus is on the bar).
      if (focusedArrow && focusedArrow.disabled) {
        (focusedArrow === prev ? next : prev).focus();
      }
      inn.removeAttribute("aria-hidden");
      inn.removeAttribute("inert");   // must precede any focus move into this subtree
      if (!out) {                     // first show — no rescue, no fade
        inn.style.opacity = "";
        inn.classList.add("is-active");
        inn.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
        return;
      }
      rescueFocus(out, inn);
      out.setAttribute("aria-hidden", "true");
      out.setAttribute("inert", "");
      inn.style.opacity = "0";
      void inn.offsetWidth;
      inn.classList.add("is-active");
      inn.style.opacity = "1";
      out.style.opacity = "0";
      var delay = reduce && reduce.matches ? 0 : FADE_MS;
      pending = { out: out, inn: inn, timer: null };
      pending.timer = setTimeout(function () {
        settleHidden(out); inn.style.opacity = ""; pending = null;
      }, delay);
      // DEPARTURE: bubbles is load-bearing — a nested gallery's own container listener
      // cannot see an event dispatched on an ancestor section; only the
      // document-delegated listener rescues it, and that needs the event to reach it.
      inn.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
    }

    // rescueFocus and the keyboard handler are added in Task 8. Stub for now:
    function rescueFocus(_out, _inn) {}

    function bail() {
      dead = true;
      sections.forEach(function (s) {
        s.removeAttribute("inert");
        s.removeAttribute("aria-hidden");
        s.classList.remove("is-active");
        s.style.opacity = "";
      });
      if (nav.parentNode) nav.parentNode.removeChild(nav);
      stage.style.minHeight = "";
      container.classList.remove("tabs--carousel");
      // .tabs--js too: courses.css separates stacked slides with
      // `:not(.tabs--js) .tabs__section + .tabs__section { margin-top }`, and the class
      // is added before the branch is entered. Leaving it makes the slides butt together.
      container.classList.remove("tabs--js");
    }

    try {
      sections.forEach(function (s) {
        s.setAttribute("role", "group");
        s.setAttribute("aria-roledescription", "slide");
        // A named bare <section> maps to `region` — a LANDMARK — per HTML-AAM; without
        // the group role, 10 slides would become 10 landmarks per carousel.
        var label = ownPart(s, "[data-tab-label]");
        if (label && label.id) s.setAttribute("aria-labelledby", label.id);
        s.setAttribute("aria-hidden", "true");
        s.setAttribute("inert", "");
      });
      container.appendChild(nav);
      prev.addEventListener("click", function () { show(idx - 1); });
      next.addEventListener("click", function () { show(idx + 1); });
      show(0);
      container.classList.add("tabs--carousel");   // LAST: the gate
    } catch (e) {
      bail();
      if (window.console && console.error) console.error(e);
    }
  }
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/test_tabs_css.py -v
```
Expected: PASS.

- [ ] **Step 7: Diff against the reference**

Open `courses/static/courses/js/gallery.js` and compare `show` line by line against yours. Confirm the only differences are the five annotated departures. Fix anything else.

- [ ] **Step 8: Falsify**

Move `classList.add("tabs--carousel")` above `show(0)` → `test_the_carousel_gate_class_is_added_after_show_zero` FAILS. Revert.
Rename `tabs__cprev` to `carousel__prev` → `test_every_new_carousel_class_is_a_single_token_literal` FAILS. Revert.

- [ ] **Step 9: Commit**

```bash
git add courses/static/courses/js/tabs.js tests/test_tabs_css.py
git commit -m "feat(tabs): add the carousel branch to tabs.js, ported from gallery.js::show

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `tabs.js` — keyboard, `rescueFocus`, and the height reservation

**Files:**
- Modify: `courses/static/courses/js/tabs.js` (inside `initCarousel`)
- Modify: `tests/test_e2e_imagezoom.py` (comment citations only)

**Interfaces:**
- Consumes: `show`, `sections`, `stage`, `nav`, `dead`, `container` from Task 7.
- Produces: the keyboard and focus behaviour the e2e in Task 11 asserts.

- [ ] **Step 1: Replace the `rescueFocus` stub**

```js
    function focusable(root) {
      var sel = 'a[href],button,input,select,textarea,[tabindex]';
      var nodes = root.querySelectorAll(sel);
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n.disabled) continue;
        if (n.getAttribute("tabindex") === "-1") continue;
        if (n.closest("[inert]")) continue;                 // a nested carousel's rest slides
        if (!n.offsetParent && n.offsetHeight === 0) continue;  // a nested tabs' display:none panel
        // Ownership: a candidate inside a NESTED instance would satisfy the rescue but
        // then fail the keydown guard below, killing navigation after one step.
        if (n.closest("[data-tabs], [data-gallery]") !== container) continue;
        return n;
      }
      return null;
    }

    // Inerting a subtree blurs focus inside it to <body>, and the keydown handler bails
    // when focus is outside the container — so without this, keyboard navigation dies
    // after exactly one step. The gallery's .imgzoom-trigger target does NOT generalise:
    // the headline case, a slide holding one table, has no focusable node at all, so the
    // nav-bar fallback is the EXPECTED outcome, not an edge case.
    function rescueFocus(out, inn) {
      if (!out.contains(document.activeElement)) return;   // focus is on the bar
      var target = focusable(inn) || nav.querySelector("button:not([disabled])");
      if (!target) { container.setAttribute("tabindex", "-1"); target = container; }
      target.focus();
    }
```

Delete the stub declaration from Task 7.

- [ ] **Step 2: Add the keyboard handler**

```js
    container.addEventListener("keydown", function (e) {
      if (dead) return;                     // BEFORE preventDefault, or we swallow keys
      var delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      var jump = e.key === "Home" ? 0 : e.key === "End" ? sections.length - 1 : null;
      if (!delta && jump === null) return;
      var el = e.target;
      var tag = el && el.tagName;
      // Guard 1: form controls own their arrow keys.
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (el && el.isContentEditable)) return;
      // Guard 2: a box that is ACTUALLY scrollable horizontally owns them too. Measured,
      // not a class list: `.el--table__scroll` on a narrow table has nothing to scroll,
      // and a class-only check would make the arrow key do nothing at all.
      for (var n = el; n && n !== container; n = n.parentElement) {
        var ox = getComputedStyle(n).overflowX;
        if ((ox === "auto" || ox === "scroll") && n.scrollWidth > n.clientWidth) return;
      }
      // Guard 3: node OWNERSHIP, not containment. A keypress in a nested instance
      // bubbles to an outer container that also contains it — and neither the tabs strip
      // handler nor gallery.js calls stopPropagation after preventDefault, so one press
      // would advance both. [data-gallery] is not optional: a gallery is nestable in a
      // slide and binds its own arrow handler.
      if (e.defaultPrevented) return;
      if (el.closest("[data-tabs], [data-gallery]") !== container) return;
      e.preventDefault();
      show(jump === null ? idx + delta : jump);
    });
```

- [ ] **Step 3: Add the height reservation**

```js
    // Stable-frame reservation, ported from gallery.js:179-227. Slides have no intrinsic
    // aspect ratio, so without it every arrow click reflows the page.
    var measureScheduled = false;
    function measure() {
      if (dead) return;
      stage.style.minHeight = "";          // clear BEFORE measuring: otherwise the second
      var max = 0;                         // pass reads the reserve back as the natural
      sections.forEach(function (s) {      // height and the frame can only ever grow
        max = Math.max(max, s.offsetHeight);
      });
      stage.style.minHeight = max + "px";
    }
    var ro = window.ResizeObserver ? new ResizeObserver(scheduleMeasure) : null;
    function scheduleMeasure() {
      if (dead || measureScheduled) return;
      measureScheduled = true;
      // rAF-coalesced: measure() mutates the very elements the observer watches, so an
      // uncoalesced version re-enters and logs "ResizeObserver loop limit exceeded".
      window.requestAnimationFrame(function () {
        measureScheduled = false;
        // A preview-pane swap detaches the container but leaves these bound.
        if (!container.isConnected) { teardownMeasure(); return; }
        measure();
      });
    }
    function teardownMeasure() {
      if (ro) ro.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      container.removeEventListener("libli:reveal", scheduleMeasure);
      document.removeEventListener("libli:reveal", onDocReveal);
    }
    function onDocReveal(e) {
      if (e.target.contains && e.target.contains(container)) scheduleMeasure();
    }
    if (ro) sections.forEach(function (s) { ro.observe(s); });
    window.addEventListener("resize", scheduleMeasure);
    // Reveal-gates and outer tab panels are the only two dispatchers in the codebase.
    // A <details>-based spoiler dispatches nothing — there the ResizeObserver is what
    // rescues the measurement when the subtree stops being skipped.
    container.addEventListener("libli:reveal", scheduleMeasure);
    document.addEventListener("libli:reveal", onDocReveal);
```

Call `measure();` immediately after `show(0);` inside the `try`, and add `teardownMeasure();` to `bail()`.

- [ ] **Step 4: Re-point the stale source citations**

`tests/test_e2e_imagezoom.py` carries **four** `tabs.js:<line>` citations in comments (the strip loop, `panel.tabIndex = 0`, the roving tabindex, the `hidden` re-application). All four are already stale against the current file, and this task shifts them again. Replace each with a symbol reference — e.g. "the strip-building loop in `initOne`", "where `initOne` sets `panel.tabIndex = 0`", "`select()`'s roving tabindex", "`select()`'s `hidden` re-application" — no line numbers.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check courses/ tests/
git add courses/static/courses/js/tabs.js tests/test_e2e_imagezoom.py
git commit -m "feat(tabs): add carousel keyboard, focus rescue and height reservation

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Transfer — serialize, validate, build, and the `FORMAT_VERSION` bump

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_tabs`, ~line 234)
- Modify: `courses/transfer/payloads.py` (`_val_tabs`, ~line 707)
- Modify: `courses/transfer/importer.py` (`_build_tabs`, ~line 783)
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION`, line 14)
- Modify: 5 test files across **two** roots (see Step 5)
- Test: `tests/test_tabs_transfer.py` (append)

**Interfaces:**
- Consumes: `TabsElement.DISPLAYS`, `.LABEL_POSITIONS`, `.DEFAULT_DISPLAY`, `.DEFAULT_LABEL_POS`.
- Produces: the archive payload `{tabs, display, label_pos}` at `FORMAT_VERSION` 8.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_carousel_round_trips_through_export_and_import():
    ...  # build a carousel-mode element, export, validate, import, assert both keys


@pytest.mark.django_db
def test_a_legacy_payload_without_the_keys_imports_with_defaults():
    """A pre-change archive must still import: _exact_keys both REQUIRES every listed
    key and REJECTS every unlisted one, so the optional-key setdefault pattern is
    mandatory in both directions."""
    data = {"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]}
    _val_tabs(data, "el-1", {})
    assert data["display"] == "tabs"
    assert data["label_pos"] == "above"


@pytest.mark.django_db
def test_an_out_of_enum_value_is_REPAIRED_not_rejected():
    """Follows _val_image, whose comment states the rule: a cosmetic field with a
    lossless default must never fail an import — `tabs` IS the pre-feature rendering.
    (Contrast _val_callout, which rejects an unknown kind: a kind has no safe fallback.)"""
    data = {"tabs": [...], "display": "CAROUSEL", "label_pos": "sideways"}
    _val_tabs(data, "el-1", {})
    assert data["display"] == "tabs"
    assert data["label_pos"] == "above"


@pytest.mark.django_db
def test_an_unhashable_value_is_repaired_rather_than_raising_TypeError():
    data = {"tabs": [...], "display": [], "label_pos": {}}
    _val_tabs(data, "el-1", {})     # must not raise
    assert data["display"] == "tabs"


@pytest.mark.django_db
def test_duplicating_a_carousel_keeps_it_a_carousel():
    """duplicate_element -> _copy_below -> build_element_export + graft_elements, so
    duplicate and paste are governed ENTIRELY by the three transfer functions. A missed
    key degrades a duplicate silently, with a 200."""
    ...  # duplicate a carousel-mode element via builder.duplicate_element, assert display


def test_format_version_is_8():
    assert FORMAT_VERSION == 8
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_transfer.py -v
```

- [ ] **Step 3: Edit the three transfer functions**

`_ser_tabs`:

```python
def _ser_tabs(el, ids):
    # Labels + stable ids + the two display settings. NON-DESTRUCTIVE normalizer
    # (mirrors save()): never pad/truncate the tab list.
    norm = el.normalize_labels_and_ids(el.data)
    return {
        "tabs": [dict(t) for t in norm["tabs"]],
        "display": norm["display"],
        "label_pos": norm["label_pos"],
    }
```

`_val_tabs` — `setdefault` **before** `_exact_keys`, then repair:

```python
def _val_tabs(data, elid, media_kinds):
    from courses.models import TabsElement

    # display/label_pos are optional (added in FORMAT_VERSION 8). setdefault first so a
    # legacy archive gains them and passes the exact-keys check, and so _build_tabs never
    # KeyErrors. Mirrors the image `size` precedent at :133.
    if isinstance(data, dict):
        data.setdefault("display", TabsElement.DEFAULT_DISPLAY)
        data.setdefault("label_pos", TabsElement.DEFAULT_LABEL_POS)
    _exact_keys(data, ["tabs", "display", "label_pos"], _("tabs data"))
    # REPAIR, never reject: a cosmetic field with a lossless default must not fail an
    # import — `tabs` IS the pre-feature rendering. The isinstance guard + tuple
    # membership keeps an unhashable value from raising TypeError.
    if not (isinstance(data["display"], str) and data["display"] in TabsElement.DISPLAYS):
        data["display"] = TabsElement.DEFAULT_DISPLAY
    if not (
        isinstance(data["label_pos"], str)
        and data["label_pos"] in TabsElement.LABEL_POSITIONS
    ):
        data["label_pos"] = TabsElement.DEFAULT_LABEL_POS
    tabs = data["tabs"]
    ...  # the rest is unchanged
```

`_build_tabs`:

```python
def _build_tabs(data, assets):
    # Tab ids pass through VERBATIM. setdefault mutated the validated dict in place, so
    # both new keys are guaranteed present here.
    return _clean_save(TabsElement(data={
        "tabs": data["tabs"],
        "display": data["display"],
        "label_pos": data["label_pos"],
    })), ()
```

- [ ] **Step 4: Bump `FORMAT_VERSION`**

`courses/transfer/schema.py:14` → `FORMAT_VERSION = 8`.

- [ ] **Step 5: Update all FIVE pinned assertions, across TWO test roots**

| File | Change |
|---|---|
| `tests/test_link_transfer.py:53-54` | rename `test_format_version_is_7` → `_is_8`, assert `== 8` |
| `tests/test_tabs_transfer.py:57-58` | rename `test_format_version_is_7` → `_is_8`, assert `== 8` |
| `tests/test_transfer_schema.py:57` | assert `== 8` (inside another test; no rename) |
| `tests/test_transfer_export.py:220` | `manifest["format_version"] == 8` (no rename) |
| **`courses/tests/test_image_size_transfer.py:41`** | assert `== 8` — ⚠️ **different test root**; `test_format_version_is_bumped` is version-agnostic in name, so no rename |

Also update the stale `7` in the comment at `tests/test_table_transfer.py:265`.

- [ ] **Step 6: Run — explicitly spanning both roots (the documented exception to narrow runs)**

```bash
uv run pytest tests/test_tabs_transfer.py tests/test_link_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py courses/tests/test_image_size_transfer.py -v
```
Expected: PASS (all).

- [ ] **Step 7: Falsify**

Drop `"display": norm["display"]` from `_ser_tabs` → the round-trip test FAILS. Revert.
Change `DISPLAYS` back to a `frozenset` in `models.py` → `test_an_unhashable_value_is_repaired_rather_than_raising_TypeError` FAILS with `TypeError`. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/ tests/test_tabs_transfer.py tests/test_link_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py tests/test_table_transfer.py courses/tests/test_image_size_transfer.py
git commit -m "feat(tabs): transfer display/label_pos and bump FORMAT_VERSION to 8

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Builder summary — name the mode in the element list

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (`element_summary`, ~line 140)
- Modify: `locale/pl/LC_MESSAGES/django.po` + `.mo`
- Test: `tests/test_tabs_partial.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_a_carousel_summary_names_the_mode():
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel"}
    )
    assert "carousel" in element_summary(obj).lower()


@pytest.mark.django_db
def test_a_tabs_summary_is_byte_identical_to_todays():
    """The change must not regress every existing element's row."""
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    assert element_summary(obj) == "2 tabs"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_tabs_partial.py -k "summary" -v
```

- [ ] **Step 3: Implement**

```python
    if name == "TabsElement":
        norm = TabsElement.normalize_labels_and_ids(el.data)
        n = len(norm["tabs"])
        # ngettext (not the lazy `_`) so the plural form is chosen against the
        # request's active locale at render time. Polish has three plural forms.
        summary = ngettext("%(n)d tab", "%(n)d tabs", n) % {"n": n}
        if norm["display"] == "carousel":
            # Display is otherwise an invisible setting: without this the builder tree
            # shows "3 tabs" for a carousel with nothing to distinguish it.
            summary = _("%(summary)s · carousel") % {"summary": summary}
        return summary
```

This reads the **non-destructive** normalizer, so it depends on trap site 1 from Task 1.

- [ ] **Step 4: Translate**

`makemessages -l pl`, add `msgstr "%(summary)s · karuzela"`, `compilemessages -l pl`.

- [ ] **Step 5: Run, falsify, commit**

```bash
uv run pytest tests/test_tabs_partial.py -k summary -v
```
Mutant: revert `normalize_labels_and_ids` to `return {"tabs": tabs}` → the carousel summary test FAILS with `KeyError`. Revert.

```bash
git add courses/templatetags/courses_manage_extras.py locale/pl/LC_MESSAGES/ tests/test_tabs_partial.py
git commit -m "feat(tabs): name the carousel mode in the builder element summary

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: e2e — drive the real carousel UI

**Files:**
- Modify: `tests/test_e2e_tabs.py` (append — a new file would change what a narrow `-k` run covers)

> **Run e2e in the FOREGROUND, this file only. Never the full `-m e2e` suite** — that spawns dozens of `chrome-headless-shell.exe` windows and disrupts the user. The controller owns the full-suite gate.

- [ ] **Step 1: Build the fixture through the real UI**

Author a unit with a carousel-mode tabs element holding **slides of deliberately different natural heights** — a 3-row table on slide 1, a 10-row table on slide 2 — created by driving the editor, not by constructing model objects. A height assertion against similar slides passes trivially on a broken build.

- [ ] **Step 2: Write the assertions**

Each bullet is one test. Sync on conditions, never on sleeps.

- [ ] **Init:** slide 1 is `.is-active` and **not** `inert` after load. *(Mutants: initialise `idx` to `0` instead of `-1`; delete the first-show branch — either → RED. Both are "the feature silently never runs" failures a normal e2e reports as a hundred unrelated errors.)*
- [ ] **Advance:** click ›; slide 2's table is visible and slide 1 is **not** visible. ⚠️ Use `check_visibility({"opacityProperty": True, "visibilityProperty": True})` or assert computed `opacity`/`.is-active` — plain `checkVisibility()` defaults `opacityProperty` to **false**, so it only sees `display:none` and returns `true` for every opacity-hidden slide; Playwright's `to_be_visible()` shares the blind spot. Assert the **negative** direction too; the positive alone is vacuous.
- [ ] **Inert:** slide 1 is `aria-hidden` and `inert`, and an input inside an inactive slide is not reachable by tabbing.
- [ ] **Height:** `.tabs__stage`'s height is unchanged between slides **and** ≥ the tallest section's own `bounding_box()["height"]`. Stability alone is vacuous — once sections are absolutely positioned the stage's height *is* `min-height` by construction, so a build reserving only slide 1's height passes a stability check while the tall slide overflows the nav. Also assert the nav bar's `y` is identical on both slides.
- [ ] **Status:** `.tabs__status` reads "Slide 2 of N", and the active dot carries `aria-current="true"`.
- [ ] **Boundaries:** `prev` is `disabled` on slide 1, `next` on the last; ArrowLeft on slide 1 and ArrowRight on slide N leave the index unchanged with **no console error**.
- [ ] **Boundary focus (the only case that can see step 4b):** click › to the last slide, assert `document.activeElement` is the `prev` button — **not `<body>`** — then ArrowLeft actually decrements. *(Mutant: delete step 4b → RED.)*
- [ ] **Focus into the slide:** with a slide holding a link, ArrowRight → `document.activeElement` is inside the incoming section, **not** in `.tabs__cbar`. *(Guards against an over-strict `rescueFocus` predicate silently degrading to the fallback.)*
- [ ] **Two presses:** ArrowRight **twice** — a build broken at steps 5/7/8 survives exactly one press.
- [ ] **Nested tabs:** a slide holding a tabs element; ArrowRight twice still advances the outer carousel.
- [ ] **Nested gallery:** a gallery in a slide; one ArrowRight with focus inside it moves the gallery by one and leaves the carousel's index unchanged.
- [ ] **Scroll containers:** Left/Right inside a **wide** table's scroll box scrolls the table and does not advance; Left/Right inside a **narrow** table (nothing to scroll) still advances.
- [ ] **Mid-fade:** click › twice inside the fade window; exactly one slide ends `.is-active` and opaque.
- [ ] **Nesting, all three directions:** tabs-in-carousel, carousel-in-carousel, and **carousel-in-tabs** each render visible and operable. The third is the regression test for the label rules (failure: the inner carousel silently loses every caption); the first two for the child combinators (failure: a completely blank inner element).
- [ ] **`label_pos: "below"`:** a wide table in a `below` slide still scrolls horizontally rather than widening the stage.
- [ ] **No-op re-save:** reopen the saved carousel in the real editor, save without touching a control, reload — still a carousel. **A Django form test cannot catch this**: it builds the POST body by hand and always includes `display`, so it passes on a build where the browser drops it.
- [ ] **Error bail:** inject the throw with an **accessor**, not a plain global write:

```python
page.add_init_script("""
  Object.defineProperty(window, "TABS_I18N", {
    configurable: true,
    get() { return this.__t; },
    set(v) { this.__t = Object.assign({}, v, {slidePos: 42}); },
  });
""")
```

A bare `window.TABS_I18N = {...}` init script does **not** work — all three templates assign the global wholesale in an inline script before the deferred `tabs.js`, so a document-start write is simply overwritten and the carousel initialises normally, failing these assertions against a *correct* implementation. Then assert: every section non-`inert`, not `aria-hidden`, content reachable by tabbing, **no `.tabs__cbar`**, `.tabs--js` removed, and the stage carries no inline `min-height`. Then press ArrowRight and assert the state is **still** clean (the `dead` flag). *(Mutants: empty the `catch` body; leave the keydown listener bound — both → RED.)*

- [ ] **Step 3: Screenshots — light and dark, judged separately**

Capture both themes. A dark screenshot is not verified by a light one passing. For dark, set `user.theme` — **not** the cookie.

- [ ] **Step 4: Run**

```bash
uv run pytest tests/test_e2e_tabs.py -m e2e -v
```

If a run dies with `DuplicateDatabase`, a previous run was orphaned: drop the DB or pass `--create-db`. If teardown deadlocks with SQLSTATE 40P01, retry — prevention cannot close that window.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_tabs.py
git commit -m "test(tabs): e2e coverage for the carousel display mode

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Branch gate (controller, after Task 11)

- [ ] `uv run pytest -q --verbosity=0` — the full non-e2e suite. (Doubled `-q` suppresses the summary; use `--verbosity=0`.)
- [ ] `uv run pytest -m e2e tests/test_e2e_tabs.py tests/test_e2e_depth3.py tests/test_e2e_imagezoom.py -v` — the carousel plus the two suites that touch `tabs.js`'s shared code.
- [ ] `uv run ruff check .`
- [ ] Manual print preview of a unit containing a carousel, including one with `label_pos: "below"`: every slide appears, in order, each with its title **above** its content, nav bar and status region absent. Not covered by any headless assertion.
- [ ] Verify `django.mo` is regenerated and committed.

## Self-Review Notes

**Spec coverage:** data model → T1; form → T2; editor → T3; template/render → T4; i18n → T5; CSS + print + test helpers → T6; carousel JS → T7/T8; transfer + FORMAT_VERSION → T9; element_summary → T10; e2e → T11. The `_CONTAINER_REGISTRY` comment is in T1; the `test_e2e_imagezoom` citations in T8.

**Type consistency:** `_coerce_enum(value, allowed, default)` is defined in T1 and called in T1, T2. `display_settings()` returns `{"display", "label_pos"}` and is splatted into the render context in T4, matching the template's `{{ display }}` / `{{ label_pos }}`. `show(n)`, `sections`, `stage`, `nav`, `dead`, `container` are defined in T7 and consumed in T8. `DISPLAY_CHOICES`/`LABEL_POS_CHOICES` are defined in T1 and consumed in T3 (`tabs_bounds`) and T9 (`_val_tabs` via `DISPLAYS`/`LABEL_POSITIONS`).
