# Media library: asset name visibility and hover preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make similarly-named media assets distinguishable in the course media manager — names contained inside their card instead of spilling under the neighbour, plus a non-modal hover preview that shows the un-cropped image.

**Architecture:** Four independent pieces. A server-side `middle_truncate` filter caps the rendered name at 32 characters while preserving its tail; three CSS declarations on `.asset-dname` stop the spill and keep the ✎ button on line 1; a one-line seed fix in `media_picker.js` stops the truncated text reaching the database; and a new `media_preview.js` owns a single body-level overlay driven by delegated pointer events.

**Tech Stack:** Django templates + template filters, vanilla ES5-style JS (no build step, no framework), token-driven CSS, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-12-media-library-asset-name-visibility-and-hover-preview-design.md` — read it before starting. It carries the reasoning behind every non-obvious choice below, and several of those choices look wrong until you read why.

## Global Constraints

- **Test DB container must be running before any pytest run.** If it is down the suite looks hung for ~4 minutes. Start it first.
- **Run tests through `uv run`** — `pytest`, `ruff` and `python` are not on PATH.
- **e2e tests need `-m e2e`** or they are silently deselected (pytest exits 5). Non-e2e runs exclude them by default (`pyproject.toml:49`).
- **Never run two pytest sessions at once** across worktrees — they share the test database.
- **Scope every test run narrowly** (single file or single test). Whole-repo sweeps are a branch gate, not a task step.
- **`ruff check --no-cache` and `ruff format --check` are separate CI gates.** Run both before each commit.
- Any comment added to `templates/courses/manage/media/_asset_cell.html` must be a **single-line** `{# … #}`. `tests/test_media_manager.py:629` rejects `{#`, `#}`, `{%`, `%}` appearing in the rendered body, and Django strips single-line comments but not multi-line ones.
- **JS is ES5-flavoured vanilla** — match `media_picker.js` and `imagezoom.js`: `var`, `function`, no arrow functions, no `const`/`let`, no optional chaining. Wrap modules in an IIFE with `"use strict"`.
- **CSS uses design tokens only** (`var(--surface-raised)`, `var(--space-2)`, …). No raw colours.
- The filter's return value must stay a plain `str` — **never** `mark_safe`. `display_name` falls back to `original_filename`, which comes from an uploaded file's name and is attacker-controllable.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `courses/templatetags/courses_manage_extras.py` | + `middle_truncate` filter (existing manage-side filter library, `register` at `:26`) |
| `tests/test_middle_truncate.py` | **New.** Unit tests for the filter, following `tests/test_title_math_filter.py`'s shape |
| `templates/courses/manage/media/_asset_cell.html` | `{% load %}`, truncated name + `title`, conditional `.asset-fname` + its `title`, `data-asset-preview` hook |
| `courses/static/courses/css/editor.css` | `.asset-dname` / `.asset-names` fixes; new `.asset-preview` block |
| `courses/static/courses/js/media_picker.js` | Rename seed reads `data-name` instead of the truncated `textContent` |
| `courses/static/courses/js/media_preview.js` | **New.** The whole overlay: state, delegation, open/close, placement, image lifecycle |
| `templates/courses/manage/media/manager.html` | `:59` — load the new script with `defer` |
| `tests/test_media_manager.py` | + cell-rendering assertions (title, conditional fname, preview hook, escaping) |
| `tests/test_e2e_media_manager.py` | Repoint 6 existing assertions; + geometry, overlay and lifecycle rows; refresh screenshots |

---

## Task 1: `middle_truncate` filter

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (imports at top; new filter appended near the other `@register.filter` functions)
- Test: `tests/test_middle_truncate.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `middle_truncate(value: str, budget: int = 32) -> str`, registered as a Django template filter named `middle_truncate` in the `courses_manage_extras` library. Task 2 uses it as `{{ asset.display_name|middle_truncate }}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_middle_truncate.py`:

```python
"""middle_truncate: the server-side half of asset-name visibility (spec §1).

The filter caps a rendered filename at `budget` characters while preserving the
TAIL -- the numeric suffix and extension are what distinguish
`przykladowa_parabola_0_1.png` from `..._0_2.png`, and an end-truncating filter
would cut off exactly the discriminating part.
"""

from django.utils.safestring import SafeString

from courses.templatetags.courses_manage_extras import middle_truncate


def test_value_shorter_than_budget_is_unchanged():
    assert middle_truncate("short.png") == "short.png"


def test_value_at_exactly_budget_is_unchanged():
    value = "a" * 28 + ".png"  # 32 chars
    assert len(value) == 32
    assert middle_truncate(value) == value


def test_over_budget_keeps_head_ellipsis_and_tail():
    value = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    result = middle_truncate(value)
    # head = 32 - 1 - 14 = 17
    assert result == "przykladowa_bardz" + "…" + "a_wersja_0_2.png"[-14:]
    assert result.startswith("przykladowa_bardz")
    assert result.endswith(value[-14:])
    assert "…" in result


def test_over_budget_result_length_equals_budget():
    value = "x" * 100 + ".png"
    assert len(middle_truncate(value)) == 32


def test_budget_16_is_the_first_middle_truncating_budget():
    value = "y" * 40
    result = middle_truncate(value, 16)
    assert len(result) == 16
    assert result == "y" + "…" + "y" * 14


def test_budget_15_falls_back_to_end_truncation():
    value = "y" * 40
    result = middle_truncate(value, 15)
    assert len(result) == 15
    assert result == "y" * 14 + "…"


def test_budget_1_returns_a_single_character():
    assert middle_truncate("abcdef", 1) == "a"


def test_negative_budget_is_clamped_to_empty():
    assert middle_truncate("abcdef", -5) == ""


def test_string_budget_from_a_template_is_coerced():
    value = "z" * 40
    assert middle_truncate(value, "16") == middle_truncate(value, 16)


def test_value_with_no_extension():
    value = "n" * 50
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith("n" * 14)


def test_non_ascii_value():
    value = "żółw_" * 12  # 48 chars, all non-ASCII stems
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith(value[-14:])


def test_value_shorter_than_tail_with_small_budget_reaches_the_fallback():
    # At the DEFAULT budget this exits at the first guard and proves nothing.
    assert middle_truncate("ab.png", 5) == "ab.p" + "…"


def test_returns_a_plain_str_not_a_safestring():
    # display_name falls back to original_filename, which is attacker-controlled.
    # A mark_safe() "fix" here would be a stored XSS, and every other case in
    # this file uses innocuous ASCII that would survive it.
    over = middle_truncate("q" * 100 + ".png")
    fallback = middle_truncate("q" * 100, 15)
    assert not isinstance(over, SafeString)
    assert not isinstance(fallback, SafeString)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_middle_truncate.py -v`
Expected: FAIL — `ImportError: cannot import name 'middle_truncate'`

- [ ] **Step 3: Add the import**

In `courses/templatetags/courses_manage_extras.py`, add to the imports at the top of the file (the module currently imports nothing from `django.template.defaultfilters`):

```python
from django.template.defaultfilters import stringfilter
```

- [ ] **Step 4: Write the filter**

Append near the other `@register.filter` functions in `courses/templatetags/courses_manage_extras.py`:

```python
@register.filter
@stringfilter
def middle_truncate(value, budget=32):
    """Cap `value` at `budget` characters, eliding the MIDDLE so the tail lives.

    The tail is the point: asset names differ in a numeric suffix
    (`..._0_1.png` vs `..._0_2.png`), so an end-truncating filter would cut off
    exactly what tells them apart.

    Budget 32 is derived in spec §1 against the grid's 128px column FLOOR, not
    against the width the tests measure -- `.asset-dname` is a single flex item
    sharing line 1 with the pencil button, so all three of its wrapped lines are
    ~76px wide and capacity is ~33 characters, not the ~41 a per-line derivation
    suggests.

    Decorator order matters: @register.filter outermost, @stringfilter innermost,
    so a lazy or non-str value is coerced before len() is taken. The result is
    deliberately NOT marked safe -- the input is user-supplied.
    """
    budget = max(int(budget), 0)
    if len(value) <= budget:
        return value
    tail = 14
    head = budget - 1 - tail
    if head >= 1:
        return value[:head] + "…" + value[-tail:]
    # budget <= 15: a middle truncation cannot preserve both ends.
    if budget >= 2:
        return value[: budget - 1] + "…"
    return value[:budget]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_middle_truncate.py -v`
Expected: PASS, 13 tests

- [ ] **Step 6: Falsify the length arithmetic**

Temporarily change `head = budget - 1 - tail` to `head = budget - tail` and re-run.
Expected: `test_over_budget_result_length_equals_budget` and `test_budget_16_is_the_first_middle_truncating_budget` FAIL.
Then **edit the mutant back out by hand** — do not `git checkout` the file, which would discard the whole task's work.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache courses/templatetags/courses_manage_extras.py tests/test_middle_truncate.py
uv run ruff format --check courses/templatetags/courses_manage_extras.py tests/test_middle_truncate.py
git add courses/templatetags/courses_manage_extras.py tests/test_middle_truncate.py
git commit -m "feat(media): middle_truncate filter preserving the discriminating tail"
```

---

## Task 2: Card markup, and repoint the tests it breaks

**Files:**
- Modify: `templates/courses/manage/media/_asset_cell.html:1,7,12,15`
- Modify: `tests/test_e2e_media_manager.py:130-136,245-250,259,309,401,436`
- Test: `tests/test_media_manager.py` (append)

**Interfaces:**
- Consumes: `middle_truncate` from Task 1.
- Produces: `.asset-dname` carrying `title="<full display_name>"`; `.asset-fname` rendered only when `original_filename != display_name`, carrying `title="<original_filename>"`; `data-asset-preview` on the image thumb. Task 5's JS resolves anchors with `closest("[data-asset-preview]")`.

**Why the repoints are in this task:** suppressing the duplicate `.asset-fname` breaks six existing e2e assertions in the same commit. Splitting them apart leaves the suite red between commits.

- [ ] **Step 1: Write the failing client tests**

Append to `tests/test_media_manager.py` (match the file's existing fixture and login helpers — read a neighbouring test first):

```python
def test_asset_cell_title_carries_the_untruncated_name(client, ...):
    """The visible name is truncated; the tooltip must be a SUPERSET of it."""
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    asset = make_image_asset(course, filename=long_name)
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert f'title="{long_name}"' in body          # full, in the attribute
    assert f">{long_name}<" not in body            # truncated, in the body
    assert "…" in body


def test_asset_fname_is_suppressed_when_it_equals_the_display_name(client, ...):
    asset = make_image_asset(course, filename="plain.png")   # no custom name
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    assert 'class="asset-fname"' not in resp.content.decode()


def test_asset_fname_renders_with_its_own_title_when_it_differs(client, ...):
    asset = make_image_asset(course, filename="original.png")
    asset.name = "Custom name"
    asset.save()
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert 'class="asset-fname"' in body
    assert 'title="original.png"' in body


def test_preview_hook_is_on_image_thumbs_only(client, ...):
    make_image_asset(course, filename="pic.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "data-asset-preview" in body
    # A video cell renders a <span> glyph, which must NOT carry the hook.
    assert body.count("data-asset-preview") == 1


def test_a_markup_bearing_name_is_escaped_in_body_and_title(client, ...):
    """original_filename comes from an uploaded file name. If middle_truncate is
    ever mark_safe()d, this is the test that goes red instead of shipping XSS."""
    make_image_asset(course, filename="<img src=x onerror=1>.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "<img src=x onerror=1>" not in body
    assert "&lt;img src=x onerror=1&gt;" in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_media_manager.py -k "title_carries or fname_is_suppressed or fname_renders or preview_hook or markup_bearing" -v`
Expected: FAIL

- [ ] **Step 3: Edit the template**

`templates/courses/manage/media/_asset_cell.html` — four edits.

Line 1:
```django
{% load i18n courses_manage_extras %}
```
Without this the template raises `TemplateSyntaxError: Invalid filter` on every manager render and every replace/rename/upload fragment. `courses_manage_extras` is not a configured builtin (no `builtins` key in `config/settings/base.py:60-78`); all ten consumer templates load it explicitly.

Line 7 — add the hook to the `<img>` branch only:
```django
    <img class="asset-thumb" src="{{ asset.file.url }}" alt="" data-asset-preview>
```

Line 12:
```django
    <span class="asset-dname" data-asset-dname title="{{ asset.display_name }}">{{ asset.display_name|middle_truncate }}</span>
```

Line 15 — wrap in a condition and add its own `title`:
```django
    {% if asset.original_filename != asset.display_name %}<span class="asset-fname" title="{{ asset.original_filename }}">{{ asset.original_filename }}</span>{% endif %}
```

- [ ] **Step 4: Run the client tests**

Run: `uv run pytest tests/test_media_manager.py -v`
Expected: PASS — including the pre-existing tests in the file (they assert on the response body, not on selectors, so they are unaffected; `:461` passes because its fixture carries `name="Cover art"`).

- [ ] **Step 5: Repoint the six e2e assertions**

In `tests/test_e2e_media_manager.py`, change `.asset-fname` to `.asset-dname` at `:136`, `:250`, `:259`, `:309`, `:401`, `:436`. All six fixture names (`replacement.png`, `first.png`, `second.png`, `late.png`, `after-swap.png`, `after-filter.png`) are under the 32-character budget and render whole, so the `:has-text` strings do not change.

Then rewrite the two explanatory comments. They record **two different things** and both must survive.

`:130-134` becomes:

```python
    # Wait on the STRIP going away, then assert the filename inside
    # `.asset-dname` -- the server-rendered node. A bare
    # `.asset-cell:has-text("replacement.png")` would be satisfied the instant
    # the strip appears, because :has-text matches DESCENDANTS and
    # [data-replace-filename] holds exactly that name. The wait would then be a
    # no-op and everything after it would race the round-trip. `.asset-dname`
    # preserves that property -- [data-replace-filename] is not a descendant of
    # it -- so do NOT "simplify" this back to `.asset-cell`.
```

`:245-248` becomes:

```python
    # Detached-first, then .asset-dname -- see the note in the happy-path test.
    # Getting this wrong is not cosmetic here: a no-op wait would run the click
    # below while replaceBusy is still true, the handler would return early, no
    # chooser would be raised, and the test would time out ON A CORRECT BUILD.
```

- [ ] **Step 6: Run the affected e2e tests**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "replace_swaps or two_consecutive or filter_swap_mid_flight or grid_swap_while or upload_after_filtering" -v`
Expected: PASS, 5 tests

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/media/_asset_cell.html tests/test_media_manager.py tests/test_e2e_media_manager.py
git commit -m "feat(media): truncate the asset name, add tooltips, drop the duplicate line"
```

---

## Task 3: Card CSS, measured

**Files:**
- Modify: `courses/static/courses/css/editor.css:719-720`
- Test: `tests/test_e2e_media_manager.py` (append geometry tests)

**Interfaces:**
- Consumes: the markup from Task 2.
- Produces: `.asset-dname` contained inside its card, wrapping, with the ✎ button on line 1. No JS depends on this.

- [ ] **Step 1: Measure first, before writing any test**

Write a scratch e2e that opens the manager at 360×900 and prints the measured card and `.asset-dname` widths, then run it once and record the numbers in the test file as a comment. Two later decisions depend on them: whether a ≤32-character name can overflow three lines (which decides whether the clamp is testable at all — spec §1), and how long the clamp fixture's name must be.

```python
card = page.locator(".asset-cell").first
print(card.bounding_box(), page.locator(".asset-dname").first.bounding_box())
```

Expect **two** columns at 360 px, each materially wider than 128 px — `minmax(8rem, 1fr)` makes 128 px a floor, not the rendered width. The docstring at `:594-596` claims otherwise and is wrong; Step 6 fixes it.

- [ ] **Step 2: Write the failing geometry tests**

Append to `tests/test_e2e_media_manager.py`. Fixture names must contain **no hyphen, space, or other soft-wrap opportunity** — underscores and digits only. Both mutants below depend on the name's min-content width being the whole string; a hyphenated name has natural break opportunities and would stay inside the card even on a broken build.

```python
@pytest.mark.e2e
def test_a_long_name_stays_inside_its_card(page, live_server, ...):
    """The reported bug: .asset-dname had NO truncation rule, so as a flex item
    with min-width:auto it refused to shrink below the whole string's
    min-content width and spilled under the next card, which painted over it.
    """
    make_image_asset(course, filename="przykladowa_parabola_0_2.png", size=(400, 300))
    page.set_viewport_size({"width": 360, "height": 900})
    ...
    rects = page.evaluate("""() => {
        const span = document.querySelector('.asset-dname');
        const r = document.createRange();
        r.selectNodeContents(span);
        return Array.from(r.getClientRects()).map(x => ({right: x.right, bottom: x.bottom}));
    }""")
    card = page.locator(".asset-cell").first.bounding_box()
    assert rects, "no text runs measured"
    for rect in rects:
        assert rect["right"] <= card["x"] + card["width"] + 1


@pytest.mark.e2e
def test_two_similar_names_each_show_their_own_suffix_inside_the_card(page, ...):
    make_image_asset(course, filename="przykladowa_parabola_0_1.png", size=(400, 300))
    make_image_asset(course, filename="przykladowa_parabola_0_2.png", size=(400, 300))
    page.set_viewport_size({"width": 360, "height": 900})
    ...
    for suffix in ("_0_1.png", "_0_2.png"):
        # inner_text() is NOT an acceptable probe -- it reports the same string
        # whether the text is painted inside the card or clipped away.
        assert page.locator(f'.asset-dname:has-text("{suffix}")').count() == 1
    ...


@pytest.mark.e2e
def test_the_pencil_button_stays_on_the_first_line(page, ...):
    """Flex line breaking uses each item's HYPOTHETICAL main size, so with the
    default flex-basis:auto the span's max-content width pushes the button onto
    flex line 2. align-items cannot fix that -- it aligns within a line.
    """
    make_image_asset(course, filename="przykladowa_parabola_0_2.png", size=(400, 300))
    page.set_viewport_size({"width": 360, "height": 900})
    ...
    span = page.locator(".asset-dname").first.bounding_box()
    # The pencil is opacity:0 until its cell is hovered (editor.css:725-726),
    # so probe bounding_box() -- do NOT assert visibility.
    pen = page.locator("[data-rename-asset]").first.bounding_box()
    assert abs(pen["y"] - span["y"]) <= 1
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "stays_inside_its_card or each_show_their_own_suffix or pencil_button_stays" -v`
Expected: FAIL — the name overflows and the button sits on line 2.

- [ ] **Step 4: Write the CSS**

`courses/static/courses/css/editor.css`, replacing line 719-720:

```css
.asset-names { display: flex; align-items: start; flex-wrap: wrap; gap: 4px; }
.asset-dname {
  font-size: .9rem; font-weight: 600; color: var(--text-primary);
  /* flex: 1 1 0 keeps the pencil on line 1. Flex line breaking happens BEFORE
     shrinking and uses the hypothetical main size; with basis:auto that is the
     whole filename's max-content width, which breaks the line. grow:1 is not
     optional alongside basis:0 -- without it the span is zero-width. */
  flex: 1 1 0;
  /* EITHER of the next two alone collapses the flex automatic minimum size
     (overflow:hidden makes this a scroll container, whose automatic minimum is
     zero; overflow-wrap:anywhere is counted in min-content sizing, unlike
     word-break:break-word). Both are kept: overflow:hidden is what lets the
     clamp clip, overflow-wrap is what makes the string WRAP across three lines
     instead of rendering as one line cut off after ~11 characters. */
  overflow-wrap: anywhere;
  overflow: hidden;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3;
}
```

`min-width: 0` is deliberately absent — it changes nothing observable alongside either rule above and could not be independently falsified.

- [ ] **Step 5: Run the tests to verify they pass, then falsify**

Run the same command. Expected: PASS.

Then, one at a time, edit a mutant in, re-run, confirm RED, and **edit it back out by hand**:

| Mutant | Row that must go red |
| --- | --- |
| delete **both** `overflow: hidden` and `overflow-wrap: anywhere` | `stays_inside_its_card` (either alone still contains the text — that is why the mutant drops both) |
| delete `overflow-wrap: anywhere` only | `each_show_their_own_suffix` (renders as one clipped line, suffix unpainted) |
| `flex: 1 1 0` → default | `pencil_button_stays` |
| `align-items: start` → `center` | `pencil_button_stays` |

Never `git checkout` to revert a mutant — it discards the whole task.

- [ ] **Step 6: Resolve the clamp, and fix the false docstring**

Using Step 1's measurement, decide whether a ≤32-character name can overflow three lines at the measured width.

- **If yes:** add a test with that fixture asserting exactly 3 text-run rects, mutant `drop -webkit-line-clamp: 3`. First spike whether Blink removes clamped lines from the layout tree (so `getClientRects()` returns 3) or lays them out and clips the paint (so it returns 4+ on *both* builds, making the row unfalsifiable). If rects do not discriminate, probe `scrollHeight > clientHeight` instead. The fixture must also be ≤32 characters, or `middle_truncate` shortens it first and the budget decides the rect count on both builds — assert its rendered length equals its source length so a later budget change fails loudly.
- **If no:** the clamp is unreachable in production too. Delete **all four** declarations — `display: -webkit-box`, `-webkit-box-orient`, `-webkit-line-clamp` **and `overflow: hidden`** — leaving `overflow-wrap: anywhere` as the sole containment rule, and collapse the first mutant above to dropping that one rule. Re-run the containment rows afterwards; removing `-webkit-box` changes the layout the probe measures.

Either way, correct the docstring at `tests/test_e2e_media_manager.py:594-596`: 360 px yields two `1fr`-widened columns, **not** the 8rem floor.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/editor.css tests/test_e2e_media_manager.py
git commit -m "fix(media): contain the asset name in its card and keep the pencil on line 1"
```

---

## Task 4: Rename seed fix

**Files:**
- Modify: `courses/static/courses/js/media_picker.js:338`
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: `data-name` on the cell root (pre-existing, `_asset_cell.html:3`), and Task 2's truncated span.
- Produces: nothing other tasks depend on.

**Why this is urgent:** `:338` seeds the rename input from `dname.textContent.trim()`, and `:375` commits on `blur`. With the span now rendering `head…tail`, clicking ✎ and then clicking anywhere else writes the ellipsised string into `MediaAsset.name` as a permanent custom name — after which `display_name` returns it forever. This is silent data corruption, not a cosmetic bug.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.e2e
def test_rename_prefills_the_untruncated_name(page, live_server, ...):
    """The span now renders head...tail. Seeding the input from its textContent
    and letting blur commit would write the ellipsis into the DB permanently.
    """
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    make_image_asset(course, filename=long_name, size=(400, 300))
    ...
    page.locator("[data-rename-asset]").first.click()
    value = page.locator(".asset-rename-input").input_value()
    # Cancel BEFORE anything moves focus: blur commits with save=true, so on a
    # broken build simply finishing the test would write the truncated name.
    page.keyboard.press("Escape")
    assert value == long_name
    assert "…" not in value
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename_prefills -v`
Expected: FAIL — the value carries the ellipsis.

- [ ] **Step 3: Fix the seed**

`courses/static/courses/js/media_picker.js`, replacing line 338:

```js
      // Seed from the cell's data-name, NOT from the span's textContent: the
      // span now renders a middle-truncated name, and the blur handler below
      // commits with save=true -- so seeding from the DOM text would write
      // "head...tail" into MediaAsset.name permanently. No textContent
      // fallback: data-name is unconditional in _asset_cell.html and the pencil
      // only exists in cells rendered by it, so a null here is a broken
      // invariant that should fail loudly rather than silently corrupt a name.
      var seed = cell.getAttribute("data-name");
      if (seed === null) return;
      var input = document.createElement("input");
      input.className = "asset-rename-input input"; input.value = seed.trim();
```

(`cell` is already in scope from `:334`, `pen.closest(".asset-cell")`.)

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename_prefills -v`
Expected: PASS

- [ ] **Step 5: Falsify**

Restore `input.value = dname.textContent.trim()`, re-run, confirm RED, edit the mutant back out by hand.

- [ ] **Step 6: Verify the rename flow still works end to end**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename -v`
Expected: PASS — including any pre-existing rename tests.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/media_picker.js tests/test_e2e_media_manager.py
git commit -m "fix(media): seed the rename input from data-name, not the truncated span"
```

---

## Task 5: Overlay — element, styles, and opening on hover

**Files:**
- Create: `courses/static/courses/js/media_preview.js`
- Modify: `templates/courses/manage/media/manager.html:59`
- Modify: `courses/static/courses/css/editor.css` (append the `.asset-preview` block)
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: `[data-asset-preview]` from Task 2; `data-name` and `data-url` on the cell root.
- Produces: `div.asset-preview` on `document.body`, closed via the `hidden` attribute, containing `img[data-asset-preview-img]` and `div.asset-preview__caption`. Tasks 6 and 7 extend this module.

- [ ] **Step 1: Write the CSS**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- Media manager hover preview (spec §5) --- */
/* [hidden] must be declared: `[hidden]{display:none}` is a UA rule and ANY
   author `display` beats it, so without this the overlay is permanently visible
   from creation. Same reason .math-modal[hidden] exists at :806. */
.asset-preview[hidden] { display: none; }
.asset-preview {
  position: fixed; z-index: 60;
  /* A DEFINITE width, not max-width: a fixed-positioned box with only a
     max-width is shrink-to-fit, and a percentage width on a flex child resolves
     against that indefinite box -- so width:100% on the image would collapse
     back to its natural size and the box would end up sized by the caption. */
  width: min(320px, calc(100vw - 16px));
  max-height: calc(100vh - 16px);
  overflow: hidden;
  display: flex; flex-direction: column; gap: var(--space-1);
  padding: var(--space-2);
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  /* The overlay necessarily covers the neighbouring cell; without this,
     sweeping right fires mouseout then mouseover on the same anchor in a
     strobe loop and the covered neighbour can never be hovered. */
  pointer-events: none;
}
[data-asset-preview-img][hidden] { display: none; }
[data-asset-preview-img] {
  width: 100%; height: auto; min-height: 0; flex: 0 1 auto;
  object-fit: contain;
}
/* A filename has no soft-wrap opportunities, so without this the caption is one
   unbreakable line and overflow:hidden clips the tail it exists to recover.
   No flex override: its automatic minimum size is its content height, so it
   cannot shrink below its text anyway and the image absorbs all shrinkage. */
.asset-preview__caption {
  overflow-wrap: anywhere; font-size: .72rem; color: var(--text-secondary);
}
```

No `align-items` is set: `align-self: stretch` applies only when the item's cross size computes to `auto`, and the image has an explicit `width`.

- [ ] **Step 2: Write the module**

Create `courses/static/courses/js/media_preview.js`:

```js
(function () {
  "use strict";
  // Non-modal hover preview for the media manager grid (spec §5).
  //
  // NOT imagezoom.js: that is a click-triggered modal <dialog>. The task here
  // is SCANNING a row of near-identical thumbnails, where a modal costs a click
  // to open, Escape to dismiss and a click for the next. Being non-modal means
  // this module deliberately re-implements none of imagezoom's modal machinery
  // -- no showModal, no scroll lock, no focus trap, no Escape arbitration.
  var root = document.querySelector(".media-manager");
  if (!root) return;

  var DWELL_MS = 250;
  var GAP = 8;

  var overlay = null, overlayImg = null, overlayCaption = null;
  var hoveredAnchor = null;   // pointer bookkeeping only
  var openAnchor = null;      // the anchor the overlay is RENDERING
  var expectedSrc = null;     // guards the load/error handlers
  var generation = 0;         // guards deferred work
  var dwellTimer = null;

  // Evaluated ONCE at load. On touch a tap synthesises hover events with no
  // matching leave, which would strand the overlay over the grid. The focus
  // path (Task 7) is armed unconditionally -- a keyboard attached to a
  // touch-first device is real, and the touch failure mode does not apply.
  var canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  function build() {
    overlay = document.createElement("div");
    overlay.className = "asset-preview";
    overlay.setAttribute("aria-hidden", "true");
    overlay.hidden = true;
    overlayImg = document.createElement("img");
    overlayImg.setAttribute("data-asset-preview-img", "");
    overlayImg.alt = "";
    overlayImg.hidden = true;
    overlayCaption = document.createElement("div");
    overlayCaption.className = "asset-preview__caption";
    overlay.appendChild(overlayImg);
    overlay.appendChild(overlayCaption);
    // document.body, NOT .media-manager: position:fixed resolves against the
    // nearest ancestor with transform/filter/contain/will-change, so nesting it
    // would make the overlay hostage to any future such property on the shell.
    document.body.appendChild(overlay);
  }

  function place() {
    if (!openAnchor) return;
    var cell = openAnchor.closest(".asset-cell");
    if (!cell) return;
    var c = cell.getBoundingClientRect();
    var o = overlay.getBoundingClientRect();
    // documentElement.clientWidth, not innerWidth or 100vw: those include the
    // scrollbar, and only clientWidth describes the space a fixed box can
    // actually occupy.
    var vw = document.documentElement.clientWidth;
    var vh = document.documentElement.clientHeight;
    var left, top;
    if (vw - c.right - GAP >= o.width) { left = c.right + GAP; top = c.top; }
    else if (c.left - GAP >= o.width) { left = c.left - GAP - o.width; top = c.top; }
    else if (vh - c.bottom - GAP >= o.height) { left = c.left; top = c.bottom + GAP; }
    else if (c.top - GAP >= o.height) { left = c.left; top = c.top - GAP - o.height; }
    else { left = (vw - o.width) / 2; top = (vh - o.height) / 2; }
    // Clamp with an 8px margin so a card near an edge cannot push it offscreen.
    // Top and left win when the box exceeds an axis.
    left = Math.max(GAP, Math.min(left, vw - o.width - GAP));
    top = Math.max(GAP, Math.min(top, vh - o.height - GAP));
    overlay.style.left = left + "px";
    overlay.style.top = top + "px";
  }

  function open(anchor) {
    if (!overlay) build();
    var cell = anchor.closest(".asset-cell");
    if (!cell) return;
    generation += 1;
    // Reset the singleton. Does NOT clear src: both src="" and
    // removeAttribute("src") yield a null selected source and QUEUE AN ERROR
    // that lands after the new source is assigned, flipping a good overlay to
    // caption-only. Assigning over the old source queues nothing.
    overlayImg.hidden = true;
    var src = anchor.currentSrc || anchor.getAttribute("src") || "";
    overlayImg.src = src;
    expectedSrc = src;
    // textContent, NEVER innerHTML: getAttribute returns display_name FULLY
    // DECODED, and it falls back to an attacker-controlled uploaded filename.
    overlayCaption.textContent = cell.getAttribute("data-name") || "";
    openAnchor = anchor;
    // Reveal synchronously when the image is already complete. Re-opening the
    // SAME anchor assigns an identical src, and whether that re-queues `load`
    // on a complete image is engine behaviour we will not bet on -- without
    // this the image would stay hidden forever on the commonest repeat action.
    // Position matters: ahead of measure, because on this path there may be no
    // `load` at all and the measurement below is the only one.
    if (overlayImg.getAttribute("src") === expectedSrc
        && overlayImg.complete && overlayImg.naturalWidth > 0) {
      overlayImg.hidden = false;
    }
    // Measure only after unhiding: a display:none element has no box, so every
    // "does it fit?" test would compare against width 0 and answer yes.
    overlay.style.visibility = "hidden";
    overlay.hidden = false;
    place();
    overlay.style.visibility = "";
  }

  function close() {
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
    if (!overlay) return;
    overlay.hidden = true;
    overlayImg.hidden = true;
    openAnchor = null;
    expectedSrc = null;
  }

  if (canHover) {
    // mouseenter/mouseleave do NOT bubble, so they cannot be delegated -- and
    // the manager replaces cells and grids constantly (upload insertCell,
    // rename/replace cell.replaceWith, every filter keystroke swapping the
    // whole grid). Per-node listeners bound at load would go silently dead on
    // every swapped-in cell. mouseover/mouseout bubble, so no arming pass and
    // no per-cell listener is needed at all.
    root.addEventListener("mouseover", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      // Defensive, not currently reachable: the anchor is a replaced <img> with
      // no descendants, so relatedTarget can never be inside it. Kept against a
      // future non-replaced anchor.
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      hoveredAnchor = anchor;
      if (anchor === openAnchor) return;
      if (openAnchor) { open(anchor); return; }   // in-place swap, no dwell
      if (dwellTimer !== null) return;
      dwellTimer = setTimeout(function () {
        dwellTimer = null;
        // The grid may have been swapped during the dwell, when nothing is
        // observing yet. A detached anchor measures as zeros, "fits on the
        // right" trivially passes, and the overlay pins to the corner with no
        // anchor left to fire mouseout.
        if (!anchor.isConnected) return;
        open(anchor);
      }, DWELL_MS);
    });

    root.addEventListener("mouseout", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
      hoveredAnchor = null;
      if (anchor === openAnchor) close();
    });
  }
})();
```

**Note:** the `mouseout` handler closes immediately here. Task 6 replaces it with the 300 ms grace that makes the in-place swap reachable by a real pointer.

- [ ] **Step 3: Wire the script**

`templates/courses/manage/media/manager.html:59`:

```django
{% block extra_js %}<script src="{% static 'courses/js/media_picker.js' %}" defer></script><script src="{% static 'courses/js/media_preview.js' %}" defer></script>{% endblock %}
```

`defer` is required — without it the delegated listeners bind before `.media-manager` exists and the module is silently dead.

- [ ] **Step 4: Write the tests**

```python
@pytest.mark.e2e
def test_hover_opens_the_overlay_with_the_thumbnails_source(page, ...):
    # size= is mandatory: make_image_asset defaults to (1,1) (factories.py:150),
    # which makes "larger than the thumb" unachievable or true for the wrong
    # reason.
    make_image_asset(course, filename="wide_0_1.png", size=(800, 200))
    ...
    page.locator("[data-asset-preview]").first.hover()
    # Positive assertions must be WAITS -- the dwell is 250ms, so an immediate
    # page.evaluate after hover() reads the closed state.
    expect(page.locator(".asset-preview")).to_be_visible()
    same = page.evaluate("""() => {
        const img = document.querySelector('[data-asset-preview-img]');
        const thumb = document.querySelector('[data-asset-preview]');
        return img.currentSrc === thumb.currentSrc;   // same IDL property both sides
    }""")
    assert same
    box = page.locator(".asset-preview").bounding_box()
    thumb = page.locator("[data-asset-preview]").first.bounding_box()
    assert box["width"] > thumb["width"]


@pytest.mark.e2e
def test_a_non_4_3_source_shows_its_full_extent(page, ...):
    """The crop comes from .asset-thumb's OWN aspect-ratio + object-fit:cover.
    The overlay image is a separate element that simply does not carry them --
    that, not any property on the overlay, is what un-crops it."""
    make_image_asset(course, filename="tall_0_1.png", size=(200, 800))
    ...
    ratio = page.evaluate("""() => {
        const img = document.querySelector('[data-asset-preview-img]');
        const r = img.getBoundingClientRect();
        return r.width / r.height;
    }""")
    assert abs(ratio - 200 / 800) < 0.05


@pytest.mark.e2e
def test_a_small_source_still_previews_larger_than_the_thumb(page, ...):
    # Short name + small size, both deliberate: with a normal-length name the
    # mutant's shrink-wrapped box would be sized by the caption (~160px, already
    # wider than a ~115px thumb) and the row would stay green.
    make_image_asset(course, filename="s.png", size=(40, 30))
    ...
    img = page.locator("[data-asset-preview-img]").bounding_box()
    thumb = page.locator("[data-asset-preview]").first.bounding_box()
    assert img["width"] > thumb["width"]


@pytest.mark.e2e
def test_an_over_budget_name_is_readable_in_the_caption(page, ...):
    make_image_asset(course, filename="przykladowa_bardzo_dluga_nazwa_0_2.png", size=(400, 300))
    ...
    clipped = page.evaluate("""() => {
        const cap = document.querySelector('.asset-preview__caption');
        return cap.scrollWidth > cap.clientWidth;
    }""")
    assert not clipped


@pytest.mark.e2e
def test_a_tall_source_fits_the_viewport_at_360(page, ...):
    make_image_asset(course, filename="portret_0_1.png", size=(400, 2000))
    page.set_viewport_size({"width": 360, "height": 900})
    ...
    fits = page.evaluate("""() => {
        const vw = document.documentElement.clientWidth;
        const vh = document.documentElement.clientHeight;
        const boxes = ['.asset-preview', '[data-asset-preview-img]']
            .map(s => document.querySelector(s).getBoundingClientRect());
        return boxes.every(b => b.left >= 0 && b.top >= 0 && b.right <= vw && b.bottom <= vh);
    }""")
    assert fits
```

- [ ] **Step 5: Run, then falsify each row**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "hover_opens or non_4_3 or small_source or readable_in_the_caption or tall_source" -v`
Expected: PASS.

Mutants, one at a time, each edited back out by hand:

| Mutant | Row |
| --- | --- |
| remove the `mouseover` listener | `hover_opens` |
| give the overlay image `aspect-ratio: 4/3; object-fit: cover` | `non_4_3` |
| `.asset-preview` `width` → `max-width` | `small_source` |
| drop the caption's `overflow-wrap: anywhere` | `readable_in_the_caption` |
| drop the image's `min-height: 0` | `tall_source` |
| move `place()` before `overlay.hidden = false` | `tall_source` (measures zeros, pins beside the card) |

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/media_preview.js courses/static/courses/css/editor.css templates/courses/manage/media/manager.html tests/test_e2e_media_manager.py
git commit -m "feat(media): hover preview overlay with placement and un-cropped image"
```

---

## Task 6: Image lifecycle and the swap grace

**Files:**
- Modify: `courses/static/courses/js/media_preview.js`
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: Task 5's module.
- Produces: `load`/`error` handling, the caption-only state, and the 300 ms hide grace. Task 7 adds the remaining close paths on top.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.e2e
def test_sweeping_a_to_b_swaps_in_place(page, ...):
    """The thumbs are not adjacent: 8+1+12+1+8 = 30px of non-anchor space sits
    between them (padding, border, grid gap). Without a close grace a physically
    moving pointer always exits to a non-anchor, so B re-pays the full dwell and
    the in-place swap is reachable only by a TELEPORTING pointer -- which is
    exactly what hover(A) then hover(B) produces. Drive the real path."""
    make_image_asset(course, filename="jeden_0_1.png", size=(400, 300))
    make_image_asset(course, filename="dwa_0_2.png", size=(400, 300))
    ...
    a = page.locator("[data-asset-preview]").nth(0)
    b = page.locator("[data-asset-preview]").nth(1)
    a.hover()
    expect(page.locator(".asset-preview")).to_be_visible()
    # Correct build and mutant reach the SAME terminal state and differ only in
    # a transient, so record the transitions instead of reading after the fact.
    page.evaluate("""() => {
        window.__hiddenLog = [];
        const o = document.querySelector('.asset-preview');
        new MutationObserver(() => window.__hiddenLog.push(o.hidden))
            .observe(o, {attributes: true, attributeFilter: ['hidden']});
    }""")
    box_b = b.bounding_box()
    page.mouse.move(box_b["x"] + box_b["width"] / 2,
                    box_b["y"] + box_b["height"] / 2, steps=10)
    expect(page.locator(".asset-preview__caption")).to_have_text("dwa_0_2.png")
    assert page.evaluate("() => window.__hiddenLog") == []


@pytest.mark.e2e
def test_a_drift_into_the_cell_padding_and_back_keeps_the_overlay(page, ...):
    ...


@pytest.mark.e2e
def test_reopening_the_same_anchor_shows_the_image(page, ...):
    """Re-assigning an identical src to a complete <img> may not re-queue
    `load`; without the synchronous reveal the image stays hidden forever."""
    ...
    a.hover()
    expect(page.locator(".asset-preview")).to_be_visible()
    page.mouse.move(5, 5)
    page.wait_for_timeout(600)          # outlive the grace
    a.hover()
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()


@pytest.mark.e2e
def test_a_broken_asset_then_a_good_one_restores_the_image_box(page, ...):
    ...


@pytest.mark.e2e
def test_a_404_source_shows_the_caption_and_no_image_box(page, ...):
    ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "swaps_in_place or drift_into or reopening_the_same or broken_asset_then or 404_source" -v`

- [ ] **Step 3: Add the grace, the handlers and the caption-only state**

In `media_preview.js`, add near the other constants:

```js
  var GRACE_MS = 300;
  var hideTimer = null;
```

Add the handlers inside `build()`, bound **once at creation** — per-open `addEventListener` without removal accumulates one handler per hover for the page's lifetime:

```js
    overlayImg.addEventListener("load", function () {
      if (!openAnchor) return;                                   // closed since
      if (overlayImg.getAttribute("src") !== expectedSrc) return; // stale source
      overlayImg.hidden = false;
      place();   // a cached image has no naturalHeight at assignment time, so
                 // the first measurement saw a caption-only box
    });
    overlayImg.addEventListener("error", function () {
      if (!openAnchor) return;
      if (overlayImg.getAttribute("src") !== expectedSrc) return;
      captionOnly();
    });
```

Add:

```js
  function captionOnly() {
    overlayImg.hidden = true;
    // Null the expected source, or a load still in flight for a PREVIOUS asset
    // would still compare equal (this branch assigns no src) and would un-hide
    // the image, painting A's frame under B's caption.
    expectedSrc = null;
  }
```

In `open()`, replace the plain assignment with the guarded form:

```js
    var src = anchor.currentSrc || anchor.getAttribute("src") || "";
    // The thumbnail itself may have failed, leaving nothing to copy. Assigning
    // "" does not reliably fire error and can leave the previous image showing.
    if (!src || (anchor.complete && anchor.naturalWidth === 0)) {
      overlayCaption.textContent = cell.getAttribute("data-name") || "";
      openAnchor = anchor;
      captionOnly();
      overlay.style.visibility = "hidden";
      overlay.hidden = false;
      place();
      overlay.style.visibility = "";
      return;
    }
```

Replace the `mouseout` handler's immediate `close()` with the grace:

```js
    root.addEventListener("mouseout", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
      hoveredAnchor = null;
      // Arm ONLY for the open anchor. Otherwise the A-hovered/B-open case tears
      // itself down: pointer on A, user Tabs into cell B, pointer drifts off A,
      // and 300ms later a mouse twitch kills a keyboard user's overlay.
      if (anchor !== openAnchor) return;
      startHide();
    });
```

with:

```js
  function startHide() {
    if (hideTimer !== null) clearTimeout(hideTimer);
    var gen = generation;
    hideTimer = setTimeout(function () {
      hideTimer = null;
      if (gen !== generation) return;   // a later open superseded this timer
      close();
    }, GRACE_MS);
  }

  function cancelHide() {
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }
  }
```

Call `cancelHide()` at the top of the `mouseover` handler and at the top of `open()` and `close()`. In the `mouseover` handler, a same-anchor re-entry must **not** be a bare no-op — it cancels the pending hide (a 30 px drift into the cell's own padding and back is routine, and letting the timer run would close the overlay under a resting pointer, with nothing able to reopen it since `mouseover` fires only on entry).

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Falsify**

| Mutant | Row |
| --- | --- |
| `mouseout` closes immediately instead of arming the grace | `swaps_in_place` |
| same-anchor `mouseover` returns without `cancelHide()` | `drift_into` |
| drop the synchronous `complete && naturalWidth > 0` reveal | `reopening_the_same` |
| drop `expectedSrc = null` from `captionOnly()` | `broken_asset_then` |
| drop the `error` listener | `404_source` |

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/media_preview.js tests/test_e2e_media_manager.py
git commit -m "feat(media): preview image lifecycle and the anchor-to-anchor swap grace"
```

---

## Task 7: Close paths, focus path, and the standing gate

**Files:**
- Modify: `courses/static/courses/js/media_preview.js`
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: Tasks 5 and 6.
- Produces: the complete module. Nothing later depends on it.

- [ ] **Step 1: Write the failing tests**

One row per behaviour — Escape, scroll, resize, `focusout` scoping, the keyboard open, the two exclusions, the `:focus-visible` gate, the observer teardown, and the same-frame rAF case:

```python
@pytest.mark.e2e
def test_tabbing_to_a_card_button_opens_it_and_it_stays_open(page, ...):
    """Seed enough assets that the grid is taller than the viewport, so the
    focus-induced scroll actually fires. focus() scrolls the element into view
    and that scroll event is dispatched AFTER the focusin handler ran -- so a
    synchronously-bound scroll listener would close the overlay it just opened."""
    ...


@pytest.mark.e2e
def test_a_replace_commit_does_not_leave_the_overlay_open(page, ...):
    """focusTrigger(fresh) at media_picker.js:550 focuses the fresh cell's own
    replace button after every commit. Without the :focus-visible gate that
    raises a 320px overlay unprompted, in five other tests and the screenshots.
    Negative assertions must outlive the dwell before asserting closed."""
    ...
    page.wait_for_timeout(600)
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.e2e
def test_hovering_a_thumb_while_its_rename_input_is_open_does_not_open(page, ...):
    """A one-shot close is defeated by moving the pointer back 300ms later.
    The gate is a STANDING condition, re-checked at every open attempt."""
    ...


@pytest.mark.e2e
def test_a_filter_swap_closes_an_open_overlay(page, ...):
    # Run once pointer-opened and once focus-opened.
    ...
```

- [ ] **Step 2: Run them to verify they fail**

- [ ] **Step 3: Implement**

Add to `media_preview.js`:

```js
  var observer = null;
  var scrollRaf = null;
  var onScroll = null;

  function gated() {
    // Standing gate: never open over a live editing control.
    return !!root.querySelector(".asset-rename-input, [data-replace-strip]");
  }

  function openedBy() {
    if (!openAnchor) return null;
    // Derived from the state that JUSTIFIES the overlay, not from the last
    // event. The pending-hide clause matters: mouseout clears hoveredAnchor, so
    // without it a pointer-opened overlay would read as "focus" for the whole
    // grace and a focusout in that window would close it early.
    if (hoveredAnchor === openAnchor || hideTimer !== null) return "pointer";
    return "focus";
  }
```

In `open()`, after `if (!cell) return;`, add `if (gated()) return;` and then connect the observer — **after** the gates, never before. `media_picker.js:339` focuses the rename input, which is a text field and so always matches `:focus-visible`, so a connect-then-check order would arm one observer per ✎ click that the gate then refuses:

```js
    observer = new MutationObserver(function () {
      if (!openAnchor) return;                       // no-op when closed
      if (!openAnchor.isConnected) { close(); return; }
      if (gated()) close();
    });
    observer.observe(root, { childList: true, subtree: true });
```

In `close()`, disconnect it and tear down the deferred work:

```js
    if (observer) { observer.disconnect(); observer = null; }
    if (scrollRaf !== null) { cancelAnimationFrame(scrollRaf); scrollRaf = null; }
    if (onScroll) {
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("keydown", onKeydown);
      onScroll = null;
    }
```

At the end of `open()`, bind the close listeners — the scroll binding deferred by one frame, and cancellable:

```js
    var gen = generation;
    scrollRaf = requestAnimationFrame(function () {
      scrollRaf = null;
      if (gen !== generation || !openAnchor) return;  // closed inside the frame
      onScroll = function () { close(); };
      // scroll does not bubble from element scrollers to window, so capture is
      // the only way to see one. passive: this never preventDefaults.
      document.addEventListener("scroll", onScroll, { capture: true, passive: true });
      window.addEventListener("resize", onScroll);
      document.addEventListener("keydown", onKeydown);
    });
```

```js
  function onKeydown(e) {
    // Bubble phase, and NEVER preventDefault/stopPropagation:
    // media_picker.js:371-373 handles Escape on the rename input to cancel, and
    // swallowing the key would be a latent regression. This deliberately is not
    // imagezoom's capture-phase arbitration -- a non-modal overlay has no claim
    // to exclusivity.
    if (e.key === "Escape") close();
  }
```

The focus path, armed unconditionally (not behind `canHover`):

```js
  root.addEventListener("focusin", function (e) {
    var target = e.target;
    if (target.closest(".asset-rename-input, [data-replace-strip]")) return;
    // Programmatic focus must not open it: focusTrigger(fresh) restores focus
    // to the fresh cell's replace button after EVERY commit. :focus-visible is
    // false for focus restored after a pointer interaction and true for
    // keyboard traversal -- exactly the distinction wanted. A keyboard-driven
    // commit does open the preview, which is correct for a keyboard user.
    if (!target.matches(":focus-visible")) return;
    var cell = target.closest(".asset-cell");
    if (!cell) return;
    var anchor = cell.querySelector("[data-asset-preview]");
    if (!anchor) return;
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
    open(anchor);   // immediately, no dwell
  });

  root.addEventListener("focusout", function () {
    // Scoped: an unscoped focusout would close a POINTER-opened overlay
    // whenever focus moved anywhere on the page -- a Tab out of the filter box
    // would dismiss the preview the user is actively hovering.
    if (openedBy() === "focus") close();
  });
```

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Falsify each**

| Mutant | Row |
| --- | --- |
| bind the scroll listener synchronously instead of in the rAF | `tabbing_to_a_card_button` |
| drop the `cancelAnimationFrame` on close | same-frame row |
| drop the `:focus-visible` check | `replace_commit_does_not_leave` |
| make the gate one-shot instead of standing | `rename_input_is_open` |
| drop the `MutationObserver` teardown | `filter_swap_closes` |
| connect the observer before the gate check | observer-leak row |
| drop the `openedBy() === "focus"` scoping | `focusout` row |

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/media_preview.js tests/test_e2e_media_manager.py
git commit -m "feat(media): preview close paths, keyboard path and the editing-control gate"
```

---

## Task 8: Touch gate, screenshots, and the branch gate

**Files:**
- Modify: `tests/test_e2e_media_manager.py:588` and append

- [ ] **Step 1: Add the pointer-gate row**

It needs its own browser context. **Settle this by spike first:** in Chromium the `hover`/`pointer` media features follow the device-emulation configuration, which Playwright derives from `is_mobile`, not from `has_touch` alone. If `has_touch=True` leaves `(hover: hover) and (pointer: fine)` matching, the gate arms and this row is red on a correct build. Prefer a full device descriptor (`**playwright.devices["Pixel 5"]`, which sets both; `is_mobile` is Chromium-only).

```python
@pytest.mark.e2e
def test_a_tap_does_not_open_the_overlay_on_touch(browser, ...):
    context = browser.new_context(**playwright.devices["Pixel 5"])
    ...
    page.locator("[data-asset-preview]").first.tap()
    page.wait_for_timeout(600)   # negative assertions must outlive the dwell
    expect(page.locator(".asset-preview")).to_be_hidden()
```

Mutant: drop the `matchMedia` gate.

- [ ] **Step 2: Refresh the screenshots**

`test_screenshots_light_and_dark` takes **element** screenshots (`unused_cell.screenshot(...)`), which clip to the element's own box — a body-appended, fixed overlay placed outside the card can never appear in one. Keep the four existing element shots (card height changes there, and the ✎ button moves to the card's right edge — visible only on a hovered cell, since it is `opacity: 0` otherwise, so shot 1 shows no pencil at all). **Add** viewport-level `page.screenshot(...)` shots with the pointer held over a thumb, in both themes, at **1280×900** — re-set the viewport for those and restore 360 px for the element shots.

Judge dark mode on its own; do not assume it follows from light. Note that a `<dialog>` would ignore the page theme, but this overlay is a plain `div` built from tokens, so both themes resolve from the same rules.

- [ ] **Step 3: Run the full media suites**

```bash
uv run pytest tests/test_media_manager.py tests/test_middle_truncate.py -v
uv run pytest tests/test_e2e_media_manager.py tests/test_e2e_media_picker.py -m e2e -v
```
Expected: all PASS. `test_e2e_media_picker.py` must be green too — the picker shares `.asset-cell` and `.asset-thumb` but renders its own cells from `_picker_grid.html`, so nothing should have moved.

- [ ] **Step 4: Lint**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_media_manager.py
git commit -m "test(media): touch-gate coverage and refreshed light/dark screenshots"
```

---

## Self-Review Notes

**Spec coverage:** §1 → Task 1; §2 → Task 2; §3 → Task 3; §4 → Task 4; §5 → Tasks 5–7; Testing → distributed, with the touch gate and screenshots in Task 8. The two engine premises the spec flags as unsettled are spiked in Task 3 Step 6 (line-clamp rects) and Task 8 Step 1 (`has_touch` vs the media query).

**Deferred by design:** the WCAG 1.4.13 "hoverable" clause is knowingly unmet — `pointer-events: none` means the pointer can never move onto the overlay, traded against the strobe loop. Spec §5 records the reasoning; do not "fix" it without reading that.

**Naming consistency:** `openAnchor`, `hoveredAnchor`, `expectedSrc`, `generation`, `dwellTimer`, `hideTimer`, `scrollRaf`, `observer`, `gated()`, `openedBy()`, `startHide()`, `cancelHide()`, `captionOnly()`, `place()`, `open()`, `close()`, `build()` — used identically across Tasks 5, 6 and 7.
