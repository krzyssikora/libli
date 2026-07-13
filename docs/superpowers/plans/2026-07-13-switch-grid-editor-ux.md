# Switch grid editor UX redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `SwitchGridElement` authoring editor so cyclers are **stem-driven** (derived live from `{{choice}}` markers), everything is removable, nothing is auto-padded, and the layout reads as a clear nested hierarchy — fixing the observed creator confusion. Backend model/render/endpoint/transfer are unchanged.

**Architecture:** The server parse (`SwitchGridElementForm.clean()`) and the field-name contract (`line-{i}-stem` / `line-{i}-c{j}-opt` / `line-{i}-c{j}-ans`) are **unchanged**. Changes: (1) `line_rows()` stops padding; (2) the edit partial is rewritten (3 clone templates, no "Add cycler" button, remove-× controls, seed via a Python constant); (3) `switchgrid_editor.js` becomes stem-driven (count markers → add/remove cycler blocks at the tail, per-editor stash, remove handlers, min-guards, radio re-sequencing, monotonic line index, submit-flush + all-blank guard, reconcile-on-load + "Cycler N" labels); (4) new `.el-editor--switchgrid` CSS (frontend-design). The student runtime (`switchgrid.js`, `render_switch_grid`) is untouched.

**Tech Stack:** Django templates, vanilla JS (IIFE, global `document` delegation, `<template>` cloning), token-driven CSS (light+dark), pytest + Playwright (e2e).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-13-switch-grid-editor-ux-design.md` — authoritative.
- **Backend parse unchanged:** do NOT touch `SwitchGridElementForm.clean()`, `_line_indices`, `_cycler_indices`, `_opts_for`, `save`, `_posted_lines`, or the model/render/endpoint/transfer. Only `line_rows()` and the module seed/min constants change on the Python side.
- **Field-name scheme is identical in 4 places** — form regexes (`_LINE_STEM_RE`/`_CYC_RE`), the partial's `name=` attrs, the clone templates' `__i__`/`__j__` placeholders, and the JS `rewrite()`. Keep them exactly `line-{i}-stem`, `line-{i}-c{j}-opt`, `line-{i}-c{j}-ans`.
- **Seed:** the create/Add-line seed stem is the fixed literal `2 {{choice}} 2 = 4` (a math literal, NOT translated). Single source = a Python constant `_SG_SEED_STEM`, injected into the template via **context** (or `{% verbatim %}`) so Django does not parse `{{choice}}` as a variable and render `2  2 = 4`.
- **Positional radio-value invariant:** after EVERY option add/remove and on cycler-block creation, re-sequence all of a cycler's radio `value`s to DOM position (0…n-1). The server reads the answer by position.
- **Cyclers are dense positional `c0..cN-1`, count-matched at the TAIL** (existing blocks never renamed). **Line indices come from a monotonic counter / `max(existing)+1`, NEVER DOM child count** (post-remove line indices are intentionally gappy; the server compacts).
- **Min-guards:** ≥2 options per cycler, ≥1 line (× disabled/hidden at the minimum); server `clean()` remains the backstop.
- **Stem textareas are plain `<textarea>`s** (class `rte-source` is inert — the RTE selects `[data-rte-source]`, which these lack). So `textarea.value` holds the literal `{{choice}}` and fires native `input` events. Do NOT convert them to RTE.
- **Tooling:** Windows; use `uv run` for python/pytest/ruff. **Isolate the test DB** (concurrent pipeline): set a unique `DATABASE_URL` env for this worktree's test runs (see Task 1 Step 0). Run e2e **focused + foreground only**. If xdist flakes, `-p no:xdist`.
- **i18n:** wrap new user-facing strings (button labels, remove-× aria, "Cycler N" label prefix, the all-blank error) EN + PL; the seed stem is NOT translated.

---

### Task 0 (do first, once): test-DB isolation for this worktree

Another pipeline runs concurrently on the same Postgres; both default to `test_libli` and collide (errors + spurious failures). Before running any test in this worktree, export a unique test DB name.

- [ ] **Step 1: Determine the isolation mechanism**

Inspect how the test settings pick the DB: `grep -rn "DATABASE_URL\|test_libli\|databases" config/settings/` and read `config/settings/test.py`. The project reads `DATABASE_URL` (dj-database-url style) or a `TEST NAME`. Whichever it is, the isolation is: run pytest with a `DATABASE_URL` pointing at a distinct database name, e.g.:

```bash
export DATABASE_URL="postgres://<user>:<pass>@localhost:5432/libli_editorux"
```

Use the same credentials/host the existing `DATABASE_URL` uses (read it from the env or `.env`); only change the database **name** to a worktree-unique one (`libli_editorux`). Pytest-django appends the `test_` prefix, creating `test_libli_editorux`, isolated from the other worktree's `test_libli`.

- [ ] **Step 2: Verify isolation**

Run one existing test with the override and `--create-db`:
```bash
uv run pytest courses/tests/test_switchgrid_form.py -q -p no:xdist --create-db
```
Expected: passes, and the teardown does NOT report "database ... is being accessed by other users". **Use this same `DATABASE_URL` export for every test run in every task below.** (No commit — this is environment setup.)

---

### Task 1: Form `line_rows()` — remove padding + seed constant + tests

**Files:**
- Modify: `courses/element_forms.py` (`line_rows()`; add `_SG_SEED_STEM`; retire `_SG_MIN_*` padding)
- Test: `courses/tests/test_switchgrid_form.py`

**Interfaces:**
- Produces: `_SG_SEED_STEM = "2 {{choice}} 2 = 4"`. `line_rows()` returns the **exact, unpadded** structure `[{index, stem, cyclers: [{index, options: [{value, checked}]}]}]`: unbound create → one seeded line (stem `_SG_SEED_STEM`, one cycler, exactly two empty option inputs); bound/edit → exactly the posted/stored lines, cyclers, and options (no `+1` blank line/cycler, no padded option rows).

- [ ] **Step 1: Update the failing tests first**

The three existing `line_rows`-shape tests (`test_edit_repopulate_round_trip` L153, `test_line_rows_mirrors_posted_data_on_validation_error` L171, `test_line_rows_bound_preserves_checked_answer` L189) currently tolerate padding via slicing (`[:2]`, `[:3]`). Tighten them to assert the exact no-padding shape, and add the new tests. Edit `courses/tests/test_switchgrid_form.py`:

Change the slices to exact-length assertions in the three tests, e.g. in `test_line_rows_mirrors_posted_data_on_validation_error` replace `opt_vals = [... for o in rows[0]["cyclers"][0]["options"][:3]]` / `assert opt_vals == ["+","-","x"]` with:
```python
    opt_vals = [o["value"] for o in rows[0]["cyclers"][0]["options"]]
    assert opt_vals == ["+", "-", "x"]  # exactly the posted options, no padding
```
and in `test_edit_repopulate_round_trip` replace `[o["value"] for o in cyc["options"][:2]] == ["+", "-"]` with `== ["+", "-"]` on the full list.

Add these new tests:
```python
def test_line_rows_create_is_single_seeded_line_no_padding():
    from courses.element_forms import _SG_SEED_STEM
    form = SwitchGridElementForm()  # unbound create
    rows = form.line_rows()
    assert len(rows) == 1
    assert rows[0]["stem"] == _SG_SEED_STEM            # "2 {{choice}} 2 = 4"
    assert len(rows[0]["cyclers"]) == 1                # one marker -> one cycler
    assert len(rows[0]["cyclers"][0]["options"]) == 2  # exactly two empty inputs
    assert all(o["value"] == "" for o in rows[0]["cyclers"][0]["options"])
    assert not any(o["checked"] for o in rows[0]["cyclers"][0]["options"])  # unchecked


def test_line_rows_edit_renders_exact_stored_counts():
    from courses import fillblank
    tok = fillblank.SENTINEL + "0" + fillblank.SENTINEL
    el = SwitchGridElement.objects.create(
        prompt="P",
        lines=[{"stem": tok, "cyclers": [{"options": ["a", "b", "c", "d"], "answer": 3}]}],
    )
    rows = SwitchGridElementForm(instance=el).line_rows()
    assert len(rows) == 1
    assert len(rows[0]["cyclers"][0]["options"]) == 4   # exact, not padded to 5
    assert rows[0]["cyclers"][0]["options"][3]["checked"] is True


def test_gappy_line_indices_compact_to_two_ordered_lines():
    # shape produced after a middle-line ×-removal: line-0 + line-2, no line-1
    pairs = [
        ("line-0-stem", "a {{choice}} b"),
        ("line-0-c0-opt", "+"), ("line-0-c0-opt", "-"), ("line-0-c0-ans", "0"),
        ("line-2-stem", "c {{choice}} d"),
        ("line-2-c0-opt", "x"), ("line-2-c0-opt", "y"), ("line-2-c0-ans", "1"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert len(obj.lines) == 2                      # compacted, no collision/merge
    assert obj.lines[0]["cyclers"][0]["options"] == ["+", "-"]
    assert obj.lines[1]["cyclers"][0]["options"] == ["x", "y"]


def test_static_zero_marker_line_round_trips():
    pairs = [
        ("line-0-stem", "Just static text, no marker"),   # zero-marker static line
        ("line-1-stem", "a {{choice}} b"),
        ("line-1-c0-opt", "+"), ("line-1-c0-opt", "-"), ("line-1-c0-ans", "0"),
    ]
    form = SwitchGridElementForm(data=_post(pairs))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert len(obj.lines) == 2                       # static line NOT dropped
    assert obj.lines[0]["cyclers"] == []             # kept with empty cyclers
    # and it re-populates via line_rows on reload
    rows = SwitchGridElementForm(instance=obj).line_rows()
    assert rows[0]["stem"] == "Just static text, no marker"
    assert rows[0]["cyclers"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_form.py -q -p no:xdist`
Expected: the new tests FAIL (padding still present; `_SG_SEED_STEM` undefined) and the tightened old tests FAIL on exact-length.

- [ ] **Step 3: Add the seed constant and rewrite `line_rows()`**

In `courses/element_forms.py`, replace the three `_SG_MIN_*` constants (lines 330–332) with:
```python
_SG_SEED_STEM = "2 {{choice}} 2 = 4"  # create/Add-line seed (math literal, not translated)
```
(Delete `_SG_MIN_LINES`/`_SG_MIN_CYCLERS`/`_SG_MIN_OPT_INPUTS` — the ≥2-option / ≥1-line minimums stay enforced in `clean()` and via the JS guards, not by padding.)

Rewrite `line_rows()` (lines 464–500) to build a `source` and emit it **without padding**, with the create case seeded:
```python
    def line_rows(self):
        """Editor-partial structure (NO padding): {index, stem, cyclers:[{index,
        options:[{value, checked}]}]}. Bound form mirrors posted data (422 keeps the
        author's grid); edit mirrors instance.lines; create = one seeded line."""
        if self.is_bound:
            source = self._posted_lines()
        elif self.instance.pk:
            source = [
                {
                    "stem": switchgrid.to_author_stem_multi(line["stem"]),
                    "cyclers": line.get("cyclers", []) or [],
                }
                for line in (self.instance.lines or [])
            ]
        else:
            # create default: one seeded line, one cycler, two empty option inputs
            source = [{"stem": _SG_SEED_STEM, "cyclers": [{"options": ["", ""], "answer": -1}]}]

        rows = []
        for i, line in enumerate(source):
            cyclers = []
            for j, cyc in enumerate(line.get("cyclers", []) or []):
                opts = (cyc or {}).get("options", []) or []
                answer = cyc.get("answer", -1) if cyc else -1
                cyclers.append({
                    "index": j,
                    "options": [
                        {"value": o, "checked": k == answer} for k, o in enumerate(opts)
                    ],
                })
            rows.append({"index": i, "stem": line.get("stem", ""), "cyclers": cyclers})
        return rows
```
Notes: this emits **exactly** the source rows (no `range(n_lines)` padding). For the create case the seed has a two-empty-option cycler so the partial renders two option inputs, unchecked (`answer=-1`). `_posted_lines()` and the edit branch are unchanged in shape, just no longer padded.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_form.py -q -p no:xdist`
Expected: PASS (all existing + new tests). Then run the whole switchgrid slice to catch fallout: `uv run pytest courses/tests/ -k switchgrid -q -p no:xdist`.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/element_forms.py courses/tests/test_switchgrid_form.py
uv run ruff format courses/element_forms.py courses/tests/test_switchgrid_form.py
git add courses/element_forms.py courses/tests/test_switchgrid_form.py
git commit -m "feat(switch-grid-editor): line_rows no-padding + seed constant"
```

---

### Task 2: Rewrite the edit partial + authoring tests

**Files:**
- Modify: `templates/courses/manage/editor/_edit_switchgrid.html` (full rewrite)
- Modify: `courses/views_manage.py` (pass `_SG_SEED_STEM` into the render context for the partial — see note)
- Test: `courses/tests/test_switchgrid_authoring.py`

**Interfaces (DOM contract the JS in Task 3 depends on — keep exact):**
- Root `[data-switchgrid-editor]`; `[data-lines]`; per line `.el-editor__line[data-line-row][data-line-index]` containing a stem `<textarea name="line-{i}-stem">`, a `[data-cyclers]` container, and a per-line remove control `[data-remove-line]`; per cycler `.el-editor__cycler[data-cycler-row][data-cycler-index]` containing a `[data-cycler-label]` span, a `[data-options]` container, and an `[data-add-option]` button; per option `.el-editor__option-row` = radio `name="line-{i}-c{j}-ans"` + text `name="line-{i}-c{j}-opt"` + `[data-remove-option]` button. A page-level `[data-add-line]` button.
- **No `[data-add-cycler]` button anywhere** (cyclers are stem-driven).
- Three `<template>`s: `data-line-template` (a line with a **seeded** stem textarea, empty `[data-cyclers]`, remove-line control), `data-cycler-template` (a cycler block: label span, empty `[data-options]`, Add-option button — NO starter option rows; the JS seeds two by cloning the option-row template), `data-option-template` (one option row: radio + text + remove-option). Placeholders `__i__`/`__j__` as today.

- [ ] **Step 1: Write the failing authoring tests**

Update `courses/tests/test_switchgrid_authoring.py`:
```python
def test_element_add_renders_seeded_editor(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "switchgrid", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "data-switchgrid-editor" in html
    assert "2 {{choice}} 2 = 4" in html          # exact seed present (context-injected)
    assert "data-add-cycler" not in html          # Add-cycler button removed
    assert "data-remove-line" in html and "data-remove-option" in html
    assert "data-cycler-template" in html         # cycler-block template retained
    # seed renders exactly two option inputs (no padding)
    assert html.count('name="line-0-c0-opt"') == 2
```
Keep `test_save_creates_switchgrid_element` and the two label tests as-is (unchanged contract).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest courses/tests/test_switchgrid_authoring.py -q -p no:xdist`
Expected: FAIL (old partial has `data-add-cycler`, padded options, empty seed).

- [ ] **Step 3: Pass the seed constant into the render context**

The partial's line `<template>` must server-render the seed WITHOUT Django parsing `{{choice}}`. In `courses/views_manage.py` `_render_open_form` (~lines 838–855, where the `_host_form.html` context dict is built), add `_SG_SEED_STEM` to the context (import it): e.g. add `"sg_seed_stem": _SG_SEED_STEM` to the context dict. The partial reads `{{ sg_seed_stem }}` (an escaped context variable — Django does NOT re-parse its value, so the literal `{{choice}}` survives). Import at top of `views_manage.py`: `from courses.element_forms import _SG_SEED_STEM`.

> If `_host_form.html` passes only a fixed set of context keys to the included partial, verify `{% include %}` forwards context (it does by default) or add the key to the include. Confirm by the Step-1 test asserting the seed appears.

- [ ] **Step 4: Write the new partial**

Replace `templates/courses/manage/editor/_edit_switchgrid.html` entirely:
```django
{% load i18n %}
<div class="el-editor el-editor--switchgrid" data-switchgrid-editor>
  <label class="el-editor__label">{% trans "Instruction (optional)" %}</label>
  <textarea name="prompt" rows="2">{{ form.prompt.value|default:"" }}</textarea>

  <p class="el-editor__hint">{% trans "Each line: type your text and write {{choice}} where a cycler should appear. A cycler block appears for each {{choice}}." %}</p>

  <div data-lines>
    {% for line in form.line_rows %}
      <div class="el-editor__line" data-line-row data-line-index="{{ line.index }}">
        <div class="el-editor__line-head">
          <textarea name="line-{{ line.index }}-stem" rows="1" data-stem>{{ line.stem }}</textarea>
          <button type="button" class="el-editor__remove" data-remove-line
                  aria-label="{% trans 'Remove line' %}" title="{% trans 'Remove line' %}">&times;</button>
        </div>
        <div class="el-editor__cyclers" data-cyclers>
          {% for cyc in line.cyclers %}
            <div class="el-editor__cycler" data-cycler-row data-cycler-index="{{ cyc.index }}">
              <span class="el-editor__cycler-label" data-cycler-label></span>
              <div class="el-editor__options" data-options>
                {% for opt in cyc.options %}
                  <div class="el-editor__option-row">
                    <input type="radio" name="line-{{ line.index }}-c{{ cyc.index }}-ans"
                           value="{{ forloop.counter0 }}"{% if opt.checked %} checked{% endif %}
                           aria-label="{% trans 'Correct option' %}">
                    <input type="text" name="line-{{ line.index }}-c{{ cyc.index }}-opt"
                           value="{{ opt.value }}" placeholder="{% trans 'Option' %} {{ forloop.counter }}">
                    <button type="button" class="el-editor__remove" data-remove-option
                            aria-label="{% trans 'Remove option' %}" title="{% trans 'Remove option' %}">&times;</button>
                  </div>
                {% endfor %}
              </div>
              <button type="button" class="btn btn--small" data-add-option>{% trans "Add option" %}</button>
            </div>
          {% endfor %}
        </div>
      </div>
    {% endfor %}
  </div>
  <button type="button" class="btn btn--small el-editor__add-line" data-add-line>{% trans "Add line" %}</button>

  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  {# --- clone templates (__i__/__j__ rewritten by switchgrid_editor.js) --- #}
  <template data-line-template>
    <div class="el-editor__line" data-line-row data-line-index="__i__">
      <div class="el-editor__line-head">
        <textarea name="line-__i__-stem" rows="1" data-stem>{{ sg_seed_stem }}</textarea>
        <button type="button" class="el-editor__remove" data-remove-line
                aria-label="{% trans 'Remove line' %}" title="{% trans 'Remove line' %}">&times;</button>
      </div>
      <div class="el-editor__cyclers" data-cyclers></div>
    </div>
  </template>
  <template data-cycler-template>
    <div class="el-editor__cycler" data-cycler-row data-cycler-index="__j__">
      <span class="el-editor__cycler-label" data-cycler-label></span>
      <div class="el-editor__options" data-options></div>
      <button type="button" class="btn btn--small" data-add-option>{% trans "Add option" %}</button>
    </div>
  </template>
  <template data-option-template>
    <div class="el-editor__option-row">
      <input type="radio" name="line-__i__-c__j__-ans" value="0" aria-label="{% trans 'Correct option' %}">
      <input type="text" name="line-__i__-c__j__-opt" placeholder="{% trans 'Option' %}">
      <button type="button" class="el-editor__remove" data-remove-option
              aria-label="{% trans 'Remove option' %}" title="{% trans 'Remove option' %}">&times;</button>
    </div>
  </template>
</div>
```
Notes: dropped the inert `class="rte-source"` (it did nothing). The line template's stem textarea carries `{{ sg_seed_stem }}` (context var, Django-safe). The cycler template has an **empty** `[data-options]` — the JS seeds two option rows on clone. `data-stem` marks the stem textarea for the JS input listener.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest courses/tests/test_switchgrid_authoring.py -q -p no:xdist`
Expected: PASS. (The seed appears via context; no `data-add-cycler`; two option inputs.)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check courses/views_manage.py; uv run ruff format courses/views_manage.py
git add templates/courses/manage/editor/_edit_switchgrid.html courses/views_manage.py courses/tests/test_switchgrid_authoring.py
git commit -m "feat(switch-grid-editor): rewrite edit partial (stem-driven, remove controls, seed)"
```

---

### Task 3: Rewrite `switchgrid_editor.js` (stem-driven)

**Files:**
- Modify: `courses/static/courses/js/switchgrid_editor.js` (full rewrite)
- Modify: `courses/static/courses/js/editor.js` (call `libliInitSwitchGridEditors(editorPane)` after a fragment swap)
- Test: `courses/tests/test_switchgrid_authoring.py` (add a wiring assertion that the editor page loads the script — if a wiring test exists for it; else rely on the e2e in Task 5)

**Interfaces:**
- Produces `window.libliInitSwitchGridEditors(root)` — now a REAL initializer: reconciles every line in `root` (renders cyclers to match markers, seeds option rows, applies "Cycler N" labels, re-sequences radio values). Idempotent. Called on `DOMContentLoaded` and after each editor-pane swap.

- [ ] **Step 1: Write the full new `switchgrid_editor.js`**

```javascript
(function () {
  "use strict";

  var SEED_STEM = "2 {{choice}} 2 = 4"; // must match _SG_SEED_STEM (server)
  var MARKER = "{{choice}}";
  var MIN_OPTIONS = 2;
  var DEBOUNCE_MS = 150;

  // Per-editor stash of removed cycler data, keyed by editor root -> "i:j" -> {options, answer}.
  var stashByEditor = new WeakMap();
  function stashFor(editor) {
    var m = stashByEditor.get(editor);
    if (!m) { m = {}; stashByEditor.set(editor, m); }
    return m;
  }

  function countMarkers(stem) {
    if (!stem) return 0;
    return stem.split(MARKER).length - 1;
  }

  function rewrite(frag, subs) {
    frag.querySelectorAll("*").forEach(function (n) {
      ["name", "data-line-index", "data-cycler-index"].forEach(function (a) {
        if (n.hasAttribute(a)) {
          var v = n.getAttribute(a);
          Object.keys(subs).forEach(function (k) { v = v.split(k).join(subs[k]); });
          n.setAttribute(a, v);
        }
      });
    });
  }

  function tpl(editor, sel) {
    return editor.querySelector("template[" + sel + "]").content.cloneNode(true);
  }

  function optionRows(cyc) {
    return Array.prototype.slice.call(cyc.querySelectorAll(".el-editor__option-row"));
  }

  // Re-sequence a cycler's radio values to DOM position (server reads answer by position).
  function resequence(cyc) {
    var radios = cyc.querySelectorAll('input[type="radio"]');
    for (var r = 0; r < radios.length; r++) radios[r].value = r;
  }

  function makeOptionRow(editor, i, j) {
    var frag = tpl(editor, "data-option-template");
    rewrite(frag, { "__i__": i, "__j__": j });
    return frag.firstElementChild;
  }

  function makeCyclerBlock(editor, i, j) {
    var frag = tpl(editor, "data-cycler-template");
    rewrite(frag, { "__i__": i, "__j__": j });
    var block = frag.firstElementChild;
    var opts = block.querySelector("[data-options]");
    // seed two empty option rows, unchecked (matches server create render)
    opts.appendChild(makeOptionRow(editor, i, j));
    opts.appendChild(makeOptionRow(editor, i, j));
    resequence(block);
    return block;
  }

  function readCyclerData(cyc) {
    var options = [];
    var answer = -1;
    optionRows(cyc).forEach(function (row, k) {
      options.push(row.querySelector('input[type="text"]').value);
      if (row.querySelector('input[type="radio"]').checked) answer = k;
    });
    return { options: options, answer: answer };
  }

  function writeCyclerData(editor, cyc, i, j, data) {
    var opts = cyc.querySelector("[data-options]");
    opts.innerHTML = "";
    var vals = (data && data.options) || ["", ""];
    if (vals.length < MIN_OPTIONS) vals = vals.concat(["", ""]).slice(0, MIN_OPTIONS);
    vals.forEach(function (v, k) {
      var row = makeOptionRow(editor, i, j);
      row.querySelector('input[type="text"]').value = v;
      if (data && data.answer === k) row.querySelector('input[type="radio"]').checked = true;
      opts.appendChild(row);
    });
    resequence(cyc);
  }

  // Reconcile ONE line: cycler block count == marker count (tail add/remove), labels, stash.
  function reconcileLine(editor, line) {
    var i = line.getAttribute("data-line-index");
    var stem = line.querySelector("[data-stem]");
    var want = countMarkers(stem ? stem.value : "");
    var cycWrap = line.querySelector("[data-cyclers]");
    var blocks = Array.prototype.slice.call(cycWrap.querySelectorAll("[data-cycler-row]"));
    var stash = stashFor(editor);

    // shrink from tail: stash removed blocks by (i,j)
    while (blocks.length > want) {
      var gone = blocks.pop();
      var gj = gone.getAttribute("data-cycler-index");
      stash[i + ":" + gj] = readCyclerData(gone);
      gone.remove();
    }
    // grow at tail: restore from stash if present, else a fresh seeded block
    while (blocks.length < want) {
      var j = String(blocks.length); // dense: next index == current count
      var block = makeCyclerBlock(editor, i, j);
      cycWrap.appendChild(block);
      var key = i + ":" + j;
      if (stash[key]) { writeCyclerData(editor, block, i, j, stash[key]); delete stash[key]; }
      blocks.push(block);
    }
    // (re)label positionally
    blocks.forEach(function (b, pos) {
      var label = b.querySelector("[data-cycler-label]");
      if (label) label.textContent = "Cycler " + (pos + 1); // i18n: see note
    });
  }

  function reconcileAll(root) {
    (root || document).querySelectorAll("[data-switchgrid-editor]").forEach(function (editor) {
      editor.querySelectorAll("[data-line-row]").forEach(function (line) {
        reconcileLine(editor, line);
      });
    });
  }

  function nextLineIndex(editor) {
    // monotonic: max(existing)+1, NEVER child count (post-remove indices are gappy)
    var max = -1;
    editor.querySelectorAll("[data-line-row]").forEach(function (l) {
      var v = parseInt(l.getAttribute("data-line-index"), 10);
      if (!isNaN(v) && v > max) max = v;
    });
    return max + 1;
  }

  // ---- events ----
  var debounceTimer = null;
  function onInput(e) {
    var stem = e.target.closest("[data-stem]");
    if (!stem) return;
    var editor = stem.closest("[data-switchgrid-editor]");
    if (!editor) return;
    var line = stem.closest("[data-line-row]");
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () { reconcileLine(editor, line); }, DEBOUNCE_MS);
  }

  function flushPending() { if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; } }

  function onClick(e) {
    var editor = e.target.closest("[data-switchgrid-editor]");
    if (!editor) return;

    if (e.target.closest("[data-add-line]")) {
      var i = nextLineIndex(editor);
      var frag = tpl(editor, "data-line-template");
      rewrite(frag, { "__i__": i });
      editor.querySelector("[data-lines]").appendChild(frag);
      var newLine = editor.querySelector('[data-line-row][data-line-index="' + i + '"]');
      reconcileLine(editor, newLine); // seeded stem has a marker -> materialize its cycler
      return;
    }
    var remLine = e.target.closest("[data-remove-line]");
    if (remLine) {
      var lines = editor.querySelectorAll("[data-line-row]");
      if (lines.length <= 1) return; // min 1 line
      var lr = remLine.closest("[data-line-row]");
      var li = lr.getAttribute("data-line-index");
      var stash = stashFor(editor);
      Object.keys(stash).forEach(function (k) { if (k.indexOf(li + ":") === 0) delete stash[k]; });
      lr.remove();
      return;
    }
    var addOpt = e.target.closest("[data-add-option]");
    if (addOpt) {
      var cyc = addOpt.closest("[data-cycler-row]");
      var li2 = cyc.closest("[data-line-row]").getAttribute("data-line-index");
      var cj = cyc.getAttribute("data-cycler-index");
      cyc.querySelector("[data-options]").appendChild(makeOptionRow(editor, li2, cj));
      resequence(cyc);
      return;
    }
    var remOpt = e.target.closest("[data-remove-option]");
    if (remOpt) {
      var cyc2 = remOpt.closest("[data-cycler-row]");
      if (optionRows(cyc2).length <= MIN_OPTIONS) return; // min 2 options
      remOpt.closest(".el-editor__option-row").remove();
      resequence(cyc2); // checked row may be gone -> that's fine (server backstop)
      return;
    }
  }

  // Submit guard: flush pending reconcile, then block all-blank cyclers with a clear message.
  function onSubmit(e) {
    var form = e.target;
    if (!form.querySelector) return;
    var editor = form.querySelector("[data-switchgrid-editor]");
    if (!editor) return;
    flushPending();
    reconcileAll(editor); // ensure DOM matches stems before POST
    var bad = null, badPos = 0;
    editor.querySelectorAll("[data-line-row]").forEach(function (line) {
      Array.prototype.slice.call(line.querySelectorAll("[data-cycler-row]")).forEach(function (cyc, pos) {
        var anyFilled = optionRows(cyc).some(function (row) {
          return row.querySelector('input[type="text"]').value.trim() !== "";
        });
        if (!anyFilled && !bad) { bad = cyc; badPos = pos + 1; }
      });
    });
    if (bad) {
      e.preventDefault();
      e.stopPropagation();
      showBlankError(editor, bad, badPos);
    }
  }

  function showBlankError(editor, cyc, pos) {
    // minimal inline message; styled by CSS (.el-editor__inline-error)
    var msg = cyc.querySelector("[data-inline-error]");
    if (!msg) {
      msg = document.createElement("p");
      msg.className = "el-editor__inline-error field-error";
      msg.setAttribute("data-inline-error", "");
      cyc.appendChild(msg);
    }
    msg.textContent = "Cycler " + pos + ": fill in its options, or remove its {{choice}} marker.";
    cyc.scrollIntoView({ block: "center" });
    var firstText = cyc.querySelector('input[type="text"]');
    if (firstText) firstText.focus();
  }

  document.addEventListener("click", onClick);
  document.addEventListener("input", onInput);
  document.addEventListener("submit", onSubmit, true); // capture: run before the POST

  window.libliInitSwitchGridEditors = function (root) { reconcileAll(root); };
  document.addEventListener("DOMContentLoaded", function () { reconcileAll(document); });
})();
```
> **i18n note:** the "Cycler N" label prefix and the all-blank error string are user-facing. Since this is static JS (not template-rendered), expose them as translated strings the page provides — simplest: read them from `data-*` attributes on the `[data-switchgrid-editor]` root that the partial renders via `{% trans %}` (e.g. `data-cycler-label-prefix="{% trans 'Cycler' %}"` and `data-blank-error="{% trans 'Cycler %(n)s: fill in its options, or remove its marker.' %}"`), and have the JS read + interpolate them. Add those attributes to the partial's root in Task 2 (or as a follow-up edit here) and update the JS `textContent` lines to use them; fall back to the English literals above if absent. Wire this so PL translations in Task-... i18n step cover them.

- [ ] **Step 2: Wire the editor-pane re-init in `editor.js`**

In `courses/static/courses/js/editor.js` `applyFragments`, next to the other `editorPane` re-inits (~lines 82–90), add:
```javascript
    if (editorPane && window.libliInitSwitchGridEditors) window.libliInitSwitchGridEditors(editorPane);
```
This runs reconcile (cyclers + "Cycler N" labels) over a freshly-swapped-in editor partial (create open, 422 re-render, edit open). The global `click`/`input`/`submit` listeners persist across swaps (attached to `document` once).

- [ ] **Step 3: Verify (no JS unit tests exist)**

There are no JS unit tests in this project; behavior is covered by the Task 5 e2e. For this task, verify the script is syntactically loadable and the wiring is present:
```bash
node --check courses/static/courses/js/switchgrid_editor.js   # if node available; else skip
uv run pytest courses/tests/ -k switchgrid -q -p no:xdist       # nothing broke server-side
```
Confirm `editor.js` includes the new re-init line (grep). Full behavioral verification is the Task 5 e2e + the Task 4 visual QA.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/switchgrid_editor.js courses/static/courses/js/editor.js
git commit -m "feat(switch-grid-editor): stem-driven editor JS (reconcile, remove, stash, guards)"
```

---

### Task 4: CSS + frontend-design nested-card layout + visual QA

**Files:**
- Modify: `core/static/core/css/app.css` (new `.el-editor--switchgrid` block; light + dark)

**REQUIRED SUB-SKILL:** load and follow **frontend-design:frontend-design** for this task — the layout must read as an intentional nested hierarchy, not a templated default.

- [ ] **Step 1: Study the design system**

Read the existing token usage near the switchgrid runtime CSS (`core/static/core/css/app.css` ~lines 1082–1266) and `tokens.css` for the real variable names (`--space-*`, `--primary`, `--primary-subtle`, `--border-*`, `--surface-*`, `--text-*`, `--radius-*`, `--danger*`). Reuse them; no invented colors. Note the shared pill/`--primary-subtle` visual language of the fillgate/switchgate/switchgrid family.

- [ ] **Step 2: Add the editor CSS**

Append a `.el-editor--switchgrid` block to `app.css` implementing:
- **Line card:** `.el-editor__line` as a bordered/`--surface` card with padding and vertical spacing between cards.
- **Line head:** `.el-editor__line-head` flex row = full-width stem textarea + a right-aligned remove-× (`.el-editor__remove`).
- **Cyclers:** `.el-editor__cyclers` indented under the stem (left padding / left border) to show containment; `.el-editor__cycler` a subtle inner card with `.el-editor__cycler-label` ("Cycler N") as a small heading.
- **Options:** reuse/extend `.el-editor__option-row` (radio + text + remove-×), indented within the cycler.
- **Buttons:** `.el-editor__add-line` and the per-cycler "Add option" clearly separated (no overlap — the old bug); the remove-× small, secondary, `--danger` on hover, with a visible focus ring.
- **Inline error:** `.el-editor__inline-error` (the all-blank-cycler message) styled as a field error.
- **Both themes:** verify against `@media (prefers-color-scheme: dark)` / the project's dark selector; ensure borders/contrast read in dark.

- [ ] **Step 3: Visual QA (frontend-design screenshot pass)**

Launch the app (or use the existing e2e harness/live_server) and Playwright-screenshot the manage editor with a Switch grid open, in **light and dark**, for: (a) the create default (one line, one cycler, two options), (b) a line after typing a second `{{choice}}` (two cycler blocks with "Cycler 1/2" labels), (c) a cycler with 4 options + remove-×s, (d) a two-line grid with a static line. Self-critique for hierarchy clarity, button separation, remove-× affordance, and dark-mode contrast; iterate the CSS until it reads cleanly. Save the screenshots to the scratch dir and reference them in the task report. (Per the project's "verify UI with screenshots" practice.)

- [ ] **Step 4: Commit**

```bash
uv run ruff check . ; # css not linted by ruff, but keep the repo clean
git add core/static/core/css/app.css
git commit -m "feat(switch-grid-editor): nested-card editor CSS (frontend-design, light+dark)"
```

---

### Task 5: e2e (editor-driving) + i18n

**Files:**
- Modify: `tests/test_e2e_switchgrid.py` (add editor-driving cases; keep the two runtime cases green)
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

- [ ] **Step 1: Add editor-driving e2e (focused + foreground only)**

Mirror the authoring harness (a PA/owner via `make_pa` + `CourseFactory` + a lesson unit; navigate to the manage editor URL and open a Switch grid). Add tests driving REAL gestures (no `page.evaluate` shortcuts):
- (a) open create → assert one line, one cycler ("Cycler 1"), two option inputs; type a second `{{choice}}` into the stem → assert a second cycler block ("Cycler 2") appears; delete it → block removed; re-type it → stashed options restored.
- (b) click a remove-× on an option → row removed; on a line (2nd line) → line removed; min-guards: the × on the last line / on a 2-option cycler does nothing.
- (c) remove a MIDDLE line, then Add line, fill it, Save → assert the element saves with the expected ordered `lines` (no field collision).
- (d) a multi-`{{choice}}` line with one cycler's options left blank → click Save → assert the inline "Cycler N: fill in its options…" message appears and the POST did not create/replace the element (guard fired), NOT the server marker-mismatch error.
- (e) author a full valid grid via the editor and Save → assert stored `lines` correct.

Determine the manage-editor URL from the codebase (the builder/editor page for a unit — grep for the route the editor page uses; the `manage_element_add`/`save` are fetch endpoints, but the editor is opened on the unit's builder page). Reuse `make_pa`/`CourseFactory` from `tests.factories`.

- [ ] **Step 2: Run e2e focused + foreground**

Run (with the isolated `DATABASE_URL`): `uv run pytest tests/test_e2e_switchgrid.py -q -p no:xdist` (foreground). Expected: all pass (the two existing runtime cases + the new editor cases).

- [ ] **Step 3: i18n**

`uv run python manage.py makemessages -l pl -l en` (or the project's invocation). Translate the new PL strings ("Remove line/option", "Add line/option", "Instruction (optional)" already exists, the "Cycler" label prefix, the all-blank-cycler error, the hint). Clear any `#, fuzzy` on new entries; no `#~` obsolete entries. `uv run python manage.py compilemessages`. Run the catalog-consistency tests: `uv run pytest -k "i18n or catalog or po_" -q -p no:xdist`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_switchgrid.py locale/
git commit -m "test+i18n(switch-grid-editor): editor-driving e2e + EN/PL strings"
```

---

## Definition of Done (controller)

- All tasks committed; with the isolated `DATABASE_URL`: `uv run pytest -q -m "not e2e" -p no:xdist` fully green; `uv run pytest tests/test_e2e_switchgrid.py -q -p no:xdist` green (foreground).
- `uv run ruff check .` + `ruff format --check .` clean.
- `uv run python manage.py makemigrations --check --dry-run` → no changes (no model change expected).
- Visual QA screenshots (light+dark) attached/referenced; the editor reads as a clear nested hierarchy with working remove controls and no button overlap.
- Manual smoke: create a Switch grid, type/delete a `{{choice}}` and watch cyclers appear/disappear with labels; remove an option and a line; leave a cycler blank and Save → clear inline message; fill and Save → persists; edit it → re-populates exactly.

---

## Self-Review

**Spec coverage:** stem-driven reconcile + tail-managed positional cyclers + stash (Task 3); 3 templates + no Add-cycler + remove controls + seed-via-context (Task 2); `line_rows()` no-padding + seed constant (Task 1); monotonic line index, radio re-sequence, min-guards, submit-flush + all-blank guard, reconcile-on-load + Cycler-N labels (Task 3); nested-card CSS via frontend-design + light/dark + visual QA (Task 4); form tests incl. gappy-line + static-line round-trip (Task 1), authoring seed/no-padding (Task 2), editor-driving e2e incl. all-blank guard + middle-line-remove (Task 5); i18n (Task 5); test-DB isolation (Task 0). All spec sections map to a task.

**Placeholder scan:** no TBD/TODO; full code for the JS, partial, `line_rows`, CSS guidance, and every test. The one delegated piece — exact CSS values and the manage-editor URL — is explicitly a "read the real code / follow frontend-design" instruction, not a vague gap.

**Type/name consistency:** field-name scheme `line-{i}-stem`/`line-{i}-c{j}-opt`/`line-{i}-c{j}-ans` identical across form regexes (unchanged), partial, templates, and JS `rewrite()`. `line_rows()` shape `{index, stem, cyclers:[{index, options:[{value, checked}]}]}` identical between Task 1 and the partial. Seed literal `2 {{choice}} 2 = 4` identical between `_SG_SEED_STEM` (Python), the `sg_seed_stem` context var, and the JS `SEED_STEM` constant. `window.libliInitSwitchGridEditors` is the shared init name (JS export + editor.js call + DOMContentLoaded). Data hooks (`data-line-row`/`data-line-index`/`data-cyclers`/`data-cycler-row`/`data-cycler-index`/`data-options`/`data-stem`/`data-remove-line`/`data-remove-option`/`data-add-option`/`data-add-line`/`data-cycler-label`) identical between the partial and the JS selectors.
