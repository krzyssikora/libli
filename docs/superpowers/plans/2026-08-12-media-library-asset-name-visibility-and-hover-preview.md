# Media library: asset name visibility and hover preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make similarly-named media assets distinguishable in the course media manager — names contained inside their card instead of spilling under the neighbour, plus a non-modal hover preview that shows the un-cropped image.

**Architecture:** Four independent pieces. A server-side `middle_truncate` filter caps the rendered name at 32 characters while preserving its tail; three CSS declarations on `.asset-dname` stop the spill and keep the ✎ button on line 1; a seed fix in `media_picker.js` stops the truncated text reaching the database; and a new `media_preview.js` owns a single body-level overlay driven by delegated pointer events.

**Tech Stack:** Django templates + template filters, vanilla ES5-style JS (no build step, no framework), token-driven CSS, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-12-media-library-asset-name-visibility-and-hover-preview-design.md` — read it before starting. It carries the reasoning behind every non-obvious choice below, and several of those choices look wrong until you read why.

## Global Constraints

- **Test DB container must be running before any pytest run.** If it is down the suite looks hung for ~4 minutes. Start it first.
- **Run tests through `uv run`** — `pytest`, `ruff` and `python` are not on PATH.
- **e2e tests need `-m e2e`** or they are silently deselected (pytest exits 5). Non-e2e runs exclude them by default (`pyproject.toml:49`).
- **Never run two pytest sessions at once** across worktrees — they share the test database.
- **Scope every test run narrowly** (single file or single test). Whole-repo sweeps are a branch gate, not a task step.
- **`ruff check --no-cache` and `ruff format --check` are separate CI gates.** Run both before each commit.
- **`MEDIA_ROOT` redirection differs by test file.** In `tests/test_media_manager.py` there is **no** autouse fixture: take `settings, tmp_path` in the signature and set `settings.MEDIA_ROOT = str(tmp_path)` as the first statement, exactly as `:635` does. `make_image_asset` writes real bytes through storage, so skipping it deposits PNGs into the repo's own `media/` directory. In `tests/test_e2e_media_manager.py` the autouse `_isolated_media` fixture (`:41-53`) already does this — new e2e rows need **neither** the parameters nor the assignment.
- **Decorators differ by test file too.** `tests/test_media_manager.py` has no module-level `pytestmark`, so every test there needs an explicit `@pytest.mark.django_db`. `tests/test_e2e_media_manager.py` sets `pytestmark = pytest.mark.e2e` at `:23`, so `@pytest.mark.e2e` on a row there is redundant; the file's convention (documented at `:25-27`) is to write `@pytest.mark.django_db(transaction=True)` on every test so the DB contract is visible.
- **The grid renders newest-first.** `courses/media.py:86` ends `assets_with_usage` with `.order_by("-created")`, and `MediaAsset.created` is `auto_now_add`. The **last** asset seeded is rendered **first**, so `nth(0)` is not the first `make_image_asset` call. Resolve anchors by name — `page.locator('.asset-cell:has([data-name="X"]) [data-asset-preview]')` — rather than by ordinal wherever two or more assets are in play.
- Any comment added to `templates/courses/manage/media/_asset_cell.html` must be a **single-line** `{# … #}`. `tests/test_media_manager.py:629` rejects `{#`, `#}`, `{%`, `%}` appearing in the rendered body, and Django strips single-line comments but not multi-line ones.
- **JS is ES5-flavoured vanilla** — match `media_picker.js` and `imagezoom.js`: `var`, `function`, no arrow functions, no `const`/`let`, no optional chaining. Wrap modules in an IIFE with `"use strict"`.
- **CSS uses design tokens only** (`var(--surface-raised)`, `var(--space-2)`, …). No raw colours.
- The filter's return value must stay a plain `str` — **never** `mark_safe`. `display_name` falls back to `original_filename`, which comes from an uploaded file's name and is attacker-controllable.
- **Never revert a mutant with `git checkout`** — it discards the whole task's work. Edit the mutant out by hand.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `courses/templatetags/courses_manage_extras.py` | + `middle_truncate` filter (existing manage-side filter library, `register` at `:26`) |
| `tests/test_middle_truncate.py` | **New.** Unit tests for the filter |
| `templates/courses/manage/media/_asset_cell.html` | `{% load %}`, truncated name + `title`, conditional `.asset-fname` + its `title`, `data-asset-preview` hook |
| `courses/static/courses/js/media_picker.js` | Rename seed reads `data-name` instead of the truncated `textContent` |
| `courses/static/courses/css/editor.css` | `.asset-dname` / `.asset-names` fixes; new `.asset-preview` block |
| `courses/static/courses/js/media_preview.js` | **New.** The whole overlay: state, delegation, open/close, placement, image lifecycle |
| `templates/courses/manage/media/manager.html` | `:59` — load the new script with `defer` |
| `tests/test_media_manager.py` | + cell-rendering assertions (title, conditional fname, preview hook, escaping) |
| `tests/test_e2e_media_manager.py` | Repoint 6 existing assertions; + geometry, overlay and lifecycle rows; refresh screenshots |

**Task order note.** The rename seed fix (Task 3) comes immediately after the markup change (Task 2) that makes it necessary. Task 2's commit ships a truncated span while the old `textContent` seed is still live, so the tree carries a live data-corruption bug between those two commits; nothing may be inserted between them.

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
    assert result == value[:17] + "…" + value[-14:]   # head = 32 - 1 - 14
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
    # Django hands filter args through as parsed, so {{ x|middle_truncate:"16" }}
    # delivers a str and max("16", 0) would raise TypeError.
    value = "z" * 40
    assert middle_truncate(value, "16") == middle_truncate(value, 16)


def test_value_with_no_extension():
    value = "n" * 50
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith("n" * 14)


def test_non_ascii_value():
    value = "żółw_" * 12  # 60 code points; contains non-ASCII code points
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith(value[-14:])


def test_value_shorter_than_tail_with_small_budget_reaches_the_fallback():
    # At the DEFAULT budget this exits at the first guard and proves nothing.
    assert middle_truncate("ab.png", 5) == "ab.p" + "…"


def test_returns_a_plain_str_not_a_safestring():
    # display_name falls back to original_filename, which is attacker-controlled.
    # A mark_safe() "fix" here would be a stored XSS, and every other case in
    # this file uses innocuous ASCII that would survive it. Both CONSTRUCTED
    # returns are checked -- on a short value this would only re-prove that the
    # input was a plain str.
    assert not isinstance(middle_truncate("q" * 100 + ".png"), SafeString)
    assert not isinstance(middle_truncate("q" * 100, 15), SafeString)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_middle_truncate.py -v`
Expected: FAIL — `ImportError: cannot import name 'middle_truncate'`

- [ ] **Step 3: Add the import**

In `courses/templatetags/courses_manage_extras.py`, add to the imports at the top (the module currently imports nothing from `django.template.defaultfilters`):

```python
from django.template.defaultfilters import stringfilter
```

- [ ] **Step 4: Write the filter**

Append near the other `@register.filter` functions:

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
Expected: at least four tests FAIL — `test_over_budget_keeps_head_ellipsis_and_tail`, `test_over_budget_result_length_equals_budget`, `test_budget_16_is_the_first_middle_truncating_budget`, and `test_budget_15_falls_back_to_end_truncation` (head becomes 1, so it takes the middle branch).
Then **edit the mutant back out by hand.**

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

Append to `tests/test_media_manager.py`. The first test shows the full setup shape; the rest follow it. **Each needs its own course slug** and its own `MEDIA_ROOT` redirect.

```python
@pytest.mark.django_db
def test_asset_cell_title_carries_the_untruncated_name(client, settings, tmp_path):
    """The visible name is truncated; the tooltip must be a SUPERSET of it."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "title-pa")
    course = CourseFactory(owner=pa, slug="cell-title")
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    make_image_asset(course, filename=long_name)
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert f'title="{long_name}"' in body          # full, in the attribute
    assert f">{long_name}<" not in body            # truncated, in the body
    assert "…" in body


@pytest.mark.django_db
def test_asset_fname_is_suppressed_when_it_equals_the_display_name(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "fname-off-pa")
    course = CourseFactory(owner=pa, slug="cell-fname-off")
    make_image_asset(course, filename="plain.png")   # no custom name
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    assert 'class="asset-fname"' not in resp.content.decode()


@pytest.mark.django_db
def test_asset_fname_renders_with_its_own_title_when_it_differs(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "fname-on-pa")
    course = CourseFactory(owner=pa, slug="cell-fname-on")
    asset = make_image_asset(course, filename="original.png")
    asset.name = "Custom name"
    asset.save()
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert 'class="asset-fname"' in body
    assert 'title="original.png"' in body


@pytest.mark.django_db
def test_preview_hook_is_on_image_thumbs_only(client, settings, tmp_path):
    """Seeding BOTH kinds is the point: with only an image asset, `count == 1`
    would be true whether or not the video branch carried the hook."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "hook-pa")
    course = CourseFactory(owner=pa, slug="cell-hook")
    make_image_asset(course, filename="pic.png")
    MediaAsset.objects.create(
        course=course, kind="video", original_filename="clip.mp4", file="clip.mp4"
    )
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "asset-thumb--video" in body          # the video cell DID render
    assert body.count("data-asset-preview") == 1  # ...and carries no hook


@pytest.mark.django_db
def test_a_markup_bearing_name_is_escaped_in_body_and_title(client, settings, tmp_path):
    """original_filename comes from an uploaded file name. If middle_truncate is
    ever mark_safe()d, this is the test that goes red instead of shipping XSS."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "xss-pa")
    course = CourseFactory(owner=pa, slug="cell-xss")
    make_image_asset(course, filename="<img src=x onerror=1>.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    body = resp.content.decode()
    assert "<img src=x onerror=1>" not in body
    assert "&lt;img src=x onerror=1&gt;" in body
```

Add `from courses.models import MediaAsset` to the file's imports if it is not already there.

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

Line 15:
```django
    {% if asset.original_filename != asset.display_name %}<span class="asset-fname" title="{{ asset.original_filename }}">{{ asset.original_filename }}</span>{% endif %}
```

- [ ] **Step 4: Run the client tests**

Run: `uv run pytest tests/test_media_manager.py -v`
Expected: PASS — including the pre-existing tests. They assert on the response body rather than selectors, and `:461` passes because its fixture carries `name="Cover art"`.

- [ ] **Step 5: Repoint the six e2e assertions**

In `tests/test_e2e_media_manager.py`, change `.asset-fname` to `.asset-dname` at `:136`, `:250`, `:259`, `:309`, `:401`, `:436`. All six fixture names are under the 32-character budget and render whole, so the `:has-text` strings do not change.

Rewrite the two comments. They record **two different things** and both must survive.

`:129-134`:
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

`:245-248`:
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

## Task 3: Rename seed fix

**Files:**
- Modify: `courses/static/courses/js/media_picker.js:337-338`
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: `data-name` on the cell root (pre-existing, `_asset_cell.html:3`), and Task 2's truncated span.
- Produces: nothing other tasks depend on.

**Why this comes immediately after Task 2:** `:338` seeds the rename input from `dname.textContent.trim()`, and `:375` commits on `blur`. With the span now rendering `head…tail`, clicking ✎ and then clicking anywhere else writes the ellipsised string into `MediaAsset.name` permanently — after which `display_name` returns it forever. Task 2's commit opens that window; nothing may be inserted before this closes it.

- [ ] **Step 1: Add the `expect` import and a seeding helper**

Two pieces of scaffolding that every later e2e row in this plan depends on.

**(a)** `tests/test_e2e_media_manager.py` currently imports `os`, `BytesIO`, `pytest`, `PIL.Image`, `courses.models` and `tests.factories`, and uses `page.wait_for_selector(...)` throughout — there is **no** `expect`. Add to the import block (one import per line, matching the file's style):

```python
from playwright.sync_api import expect
```

**(b)** The file's existing `_seed(username, slug, *, with_element=True)` helper creates an asset named `original.png` of its own. Reusing it for the overlay and geometry rows would add a cell that shifts every index and an extra `.asset-dname` the geometry probes might measure. Add a helper that seeds **only** the named assets:

```python
def _seed_assets(username, slug, *specs):
    """Course + exactly the named assets, nothing else.

    Distinct from _seed(): that one creates an `original.png` of its own, which
    would add an unrelated cell to every grid the preview rows measure.

    NOTE the grid order: courses/media.py:86 sorts by "-created", so the LAST
    spec here renders FIRST. Resolve anchors by name, not by nth().
    """
    user = make_verified_user(username)
    course = CourseFactory(owner=user, slug=slug)
    for filename, size in specs:
        make_image_asset(course, filename=filename, size=size)
    return user, course


def _anchor(page, filename):
    """The [data-asset-preview] of the cell whose data-name is `filename`.

    data-name lives on the .asset-cell ROOT (_asset_cell.html:3), not on a
    descendant -- so this is an attribute selector on the cell itself. Do not
    "fix" it to `.asset-cell:has([data-name=...])`: :has() takes a relative
    selector defaulting to the descendant combinator and would match nothing.
    """
    return page.locator(f'.asset-cell[data-name="{filename}"] [data-asset-preview]')
```

Match the file's existing `_seed`/`_open_manager` signatures when wiring these — read them first.

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.django_db(transaction=True)
def test_rename_prefills_the_untruncated_name(page, live_server):
    """The span now renders head...tail. Seeding the input from its textContent
    and letting blur commit would write the ellipsis into the DB permanently.
    """
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    user, course = _seed_assets("rename-pa", "rename-seed", (long_name, (400, 300)))
    _open_manager(page, live_server, "rename-pa", course)
    page.locator("[data-rename-asset]").first.click()
    value = page.locator(".asset-rename-input").input_value()
    # Cancel BEFORE anything moves focus: blur commits with save=true, so on a
    # broken build simply finishing the test would write the truncated name.
    page.keyboard.press("Escape")
    assert value == long_name
    assert "…" not in value
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename_prefills -v`
Expected: FAIL — the value carries the ellipsis.

- [ ] **Step 4: Fix the seed**

`courses/static/courses/js/media_picker.js` — replace **lines 337-338** (line 337 is already `var input = document.createElement("input");`, so replacing 338 alone would declare `input` twice):

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

- [ ] **Step 5: Run it, then falsify**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename_prefills -v` → PASS.
Restore `input.value = dname.textContent.trim()`, re-run, confirm RED, edit the mutant back out by hand.

- [ ] **Step 6: Verify the whole rename flow**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k rename -v`
Expected: PASS — including the pre-existing rename tests.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/media_picker.js tests/test_e2e_media_manager.py
git commit -m "fix(media): seed the rename input from data-name, not the truncated span"
```

---

## Task 4: Card CSS, measured

**Files:**
- Modify: `courses/static/courses/css/editor.css:719-720`
- Test: `tests/test_e2e_media_manager.py` (append)

**Interfaces:**
- Consumes: the markup from Task 2.
- Produces: `.asset-dname` contained inside its card, wrapping, with the ✎ button on line 1. No JS depends on this.

- [ ] **Step 1: Measure first, before writing any test**

Write a throwaway e2e **inside `tests/`**, named `tests/test_zz_scratch_measure.py`, that opens the manager at 360×900 and prints the measured card width, the `.asset-dname` width, and the number of text-run rects for a 32-character name.

It must live in `tests/` rather than the scratchpad: pytest derives rootdir from its args, so a file outside the repo picks up neither `pyproject.toml`'s `[tool.pytest.ini_options]` (no `DJANGO_SETTINGS_MODULE`, no `e2e` marker) nor the repo's `conftest.py` — `live_server` and the settings bootstrap would both be missing and it would error before measuring anything. Step 8 deletes it.

```python
card = page.locator(".asset-cell").first
span = page.locator(".asset-dname").first
print(card.bounding_box(), span.bounding_box())
print(page.evaluate("""() => {
    const s = document.querySelector('.asset-dname');
    const r = document.createRange(); r.selectNodeContents(s);
    return r.getClientRects().length;
}"""))
```

Run it once and record the three numbers as a comment in `tests/test_e2e_media_manager.py`. **Delete `tests/test_zz_scratch_measure.py`** before Step 8, and confirm with `git status` that it is not staged.

Expect **two** columns at 360 px, each materially wider than 128 px — `minmax(8rem, 1fr)` makes 128 px a floor, not the rendered width. The docstring at `:594-596` claims otherwise and is wrong; Step 7 fixes it.

Three later decisions depend on these numbers: whether a ≤32-character name can overflow three lines (Step 7), how long the clamp fixture must be (Step 7), and which fixture wraps to ≥2 lines for the alignment row (Step 2).

- [ ] **Step 2: Write the failing geometry tests**

Fixture names must contain **no hyphen, space, or other soft-wrap opportunity** — underscores and digits only. Both containment mutants depend on the name's min-content width being the whole string; a hyphenated name has natural break opportunities and would stay inside the card even on a broken build.

```python
@pytest.mark.django_db(transaction=True)
def test_a_long_name_stays_inside_its_card(page, live_server):
    """The reported bug: .asset-dname had NO truncation rule, so as a flex item
    with min-width:auto it refused to shrink below the whole string's
    min-content width and spilled under the next card, which painted over it.
    """
    user, course = _seed_assets(
        "geo1-pa", "geo1", ("przykladowa_parabola_0_2.png", (400, 300))
    )
    _open_manager(page, live_server, "geo1-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    rects = page.evaluate("""() => {
        const s = document.querySelector('.asset-dname');
        const r = document.createRange(); r.selectNodeContents(s);
        return Array.from(r.getClientRects()).map(x => ({right: x.right, bottom: x.bottom}));
    }""")
    card = page.locator(".asset-cell").first.bounding_box()
    assert rects, "no text runs measured"
    for rect in rects:
        assert rect["right"] <= card["x"] + card["width"] + 1


@pytest.mark.django_db(transaction=True)
def test_two_similar_names_each_paint_their_own_suffix_inside_the_card(page, live_server):
    """`:has-text()` is NOT an acceptable probe here -- it matches the element's
    text CONTENT, which is unchanged when the text is merely clipped, so the
    mutant would stay green. Measure the rect covering the suffix instead.

    _seed_assets, NOT the file's _seed(): this row iterates EVERY .asset-cell
    and compares the suffix set, so _seed's own `original.png` would add a third
    cell (suffix "inal.png") and the row would be red on a correct build.
    """
    user, course = _seed_assets(
        "geo2-pa", "geo2",
        ("przykladowa_parabola_0_1.png", (400, 300)),
        ("przykladowa_parabola_0_2.png", (400, 300)),
    )
    _open_manager(page, live_server, "geo2-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    painted = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('.asset-cell')).map(cell => {
            const s = cell.querySelector('.asset-dname');
            const text = s.textContent;
            const start = text.length - 8;            // "_0_1.png"
            const r = document.createRange();
            r.setStart(s.firstChild, start);
            r.setEnd(s.firstChild, text.length);
            const rect = r.getBoundingClientRect();
            const card = cell.getBoundingClientRect();
            return {
                suffix: text.slice(start),
                inside: rect.width > 0 && rect.right <= card.right + 1
                        && rect.bottom <= card.bottom + 1,
            };
        });
    }""")
    assert {p["suffix"] for p in painted} == {"_0_1.png", "_0_2.png"}
    assert all(p["inside"] for p in painted)


@pytest.mark.django_db(transaction=True)
def test_the_pencil_button_stays_on_the_first_line(page, live_server):
    """Flex line breaking uses each item's HYPOTHETICAL main size, so with the
    default flex-basis:auto the span's max-content width pushes the button onto
    flex line 2. align-items cannot fix that -- it aligns WITHIN a line.

    The fixture must wrap to at least two lines at the MEASURED card width
    (Step 1): on a single-line name both mutants leave the button vertically
    coincident with the span and this row passes on a broken build.
    """
    user, course = _seed_assets(
        "geo3-pa", "geo3", ("przykladowa_parabola_0_2.png", (400, 300))
    )
    _open_manager(page, live_server, "geo3-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    lines = page.evaluate("""() => {
        const s = document.querySelector('.asset-dname');
        const r = document.createRange(); r.selectNodeContents(s);
        return r.getClientRects().length;
    }""")
    assert lines >= 2, "fixture does not wrap; the mutants cannot discriminate"
    span = page.locator(".asset-dname").first.bounding_box()
    # The pencil is opacity:0 until its cell is hovered (editor.css:725-726),
    # so probe bounding_box() -- do NOT assert visibility.
    pen = page.locator("[data-rename-asset]").first.bounding_box()
    assert abs(pen["y"] - span["y"]) <= 1
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "stays_inside_its_card or paint_their_own_suffix or pencil_button_stays" -v`
Expected: FAIL — text-run rects extend past the card's right edge, the suffix rects are outside it, and the pencil sits on flex line 2 (its `y` differs from the span's by roughly one line height).

- [ ] **Step 4: Write the CSS**

`courses/static/courses/css/editor.css`, replacing lines 719-720:

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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "stays_inside_its_card or paint_their_own_suffix or pencil_button_stays" -v`
Expected: PASS, 3 tests

- [ ] **Step 6: Falsify each row**

One at a time: edit the mutant in, re-run, confirm RED, **edit it back out by hand.**

| Mutant | Row that must go red |
| --- | --- |
| delete **both** `overflow: hidden` and `overflow-wrap: anywhere` | `stays_inside_its_card` (either alone still contains the text — that is why the mutant drops both) |
| delete `overflow-wrap: anywhere` only | `paint_their_own_suffix` (renders as one clipped line, suffix unpainted) |
| `flex: 1 1 0` → default | `pencil_button_stays` |
| `align-items: start` → `center` | `pencil_button_stays` |

- [ ] **Step 7: Resolve the clamp, and fix the false docstring**

Using Step 1's rect count, decide whether a ≤32-character name can overflow three lines at the measured width.

- **If yes:** add a row asserting exactly 3 text-run rects for that fixture, mutant `drop -webkit-line-clamp: 3`. First spike whether Blink removes clamped lines from the layout tree (so `getClientRects()` returns 3) or lays them out and clips the paint (so it returns 4+ on *both* builds, making the row unfalsifiable). If rects do not discriminate, probe `scrollHeight > clientHeight` instead. The fixture must also be ≤32 characters, or `middle_truncate` shortens it first and the budget decides the count on both builds — assert its rendered length equals its source length so a later budget change fails loudly.
- **If no:** the clamp is unreachable in production too. Delete **all four** declarations — `display: -webkit-box`, `-webkit-box-orient`, `-webkit-line-clamp` **and `overflow: hidden`** — leaving `overflow-wrap: anywhere` as the sole containment rule, and collapse the first mutant above to dropping that one rule. Re-run the containment rows afterwards; removing `-webkit-box` changes the layout the probe measures.

Either way, correct the docstring at `tests/test_e2e_media_manager.py:594-596`: 360 px yields two `1fr`-widened columns, **not** the 8rem floor.

- [ ] **Step 8: Delete the scratch file and commit**

```bash
git add courses/static/courses/css/editor.css tests/test_e2e_media_manager.py
git commit -m "fix(media): contain the asset name in its card and keep the pencil on line 1"
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
- Produces: `div.asset-preview` on `document.body`, closed via the `hidden` attribute, containing `img[data-asset-preview-img]` and `div.asset-preview__caption`. Tasks 6 and 7 extend this module. Task 6 adds `teardownOpenBindings()`, which Task 7's listeners rely on.

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

    // Bound ONCE at creation, not per open: per-open addEventListener without
    // removal accumulates one handler per hover for the page's lifetime.
    // These must exist from Task 5 -- on a COLD open the image is not yet
    // complete, so the synchronous reveal in open() does not fire and `load`
    // is the only thing that ever lifts overlayImg.hidden.
    overlayImg.addEventListener("load", function () {
      if (!openAnchor) return;                                    // closed since
      if (overlayImg.getAttribute("src") !== expectedSrc) return; // stale source
      overlayImg.hidden = false;
      place();   // the first measurement saw a caption-only box
    });
    overlayImg.addEventListener("error", function () {
      if (!openAnchor) return;
      if (overlayImg.getAttribute("src") !== expectedSrc) return;
      overlayImg.hidden = true;
    });

    // document.body, NOT .media-manager: position:fixed resolves against the
    // nearest ancestor with transform/filter/contain/will-change, so nesting it
    // would make the overlay hostage to any future such property on the shell.
    document.body.appendChild(overlay);
  }

  function place() {
    if (!openAnchor) return;
    // The reference box is the CELL, not the thumb: the thumb is inset by the
    // cell's padding and border and is materially shorter.
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

**Note:** `mouseout` closes immediately here. Task 6 replaces it with the 300 ms grace that makes the in-place swap reachable by a real pointer, restructures `open()` so its bindings are torn down on re-entry, and replaces the `error` handler's bare hide with `captionOnly()` (which also nulls `expectedSrc`).

- [ ] **Step 3: Wire the script**

`templates/courses/manage/media/manager.html:59`:

```django
{% block extra_js %}<script src="{% static 'courses/js/media_picker.js' %}" defer></script><script src="{% static 'courses/js/media_preview.js' %}" defer></script>{% endblock %}
```

`defer` is required — without it the delegated listeners bind before `.media-manager` exists and the module is silently dead.

- [ ] **Step 4: Write the tests**

Every one of these opens with hover + an explicit visibility wait. The dwell is 250 ms, so a `page.evaluate` or `bounding_box()` fired straight after `hover()` reads the **closed** state — and `bounding_box()` on a `display: none` element returns `None`, so the failure is a `TypeError` rather than a clean assertion.

```python
def _open_preview(page, filename):
    """Hover the named thumb and wait past the dwell. Every overlay test uses it.

    By NAME, never by nth(): the grid sorts "-created" (courses/media.py:86), so
    the last asset seeded renders first.
    """
    _anchor(page, filename).hover()
    expect(page.locator(".asset-preview")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_hover_opens_the_overlay_with_the_thumbnails_source(page, live_server):
    # size= is mandatory: make_image_asset defaults to (1,1) (factories.py:150),
    # which makes "larger than the thumb" unachievable or true for the wrong
    # reason.
    user, course = _seed_assets("hov-pa", "hov", ("wide_0_1.png", (800, 200)))
    _open_manager(page, live_server, "hov-pa", course)
    _open_preview(page, "wide_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    # getAttribute("src"), not currentSrc: src is set synchronously in open(),
    # whereas currentSrc is populated by the source-selection step and can still
    # be "" when read in the same tick -- a flake, not a deterministic red.
    same = page.evaluate("""() => {
        const img = document.querySelector('[data-asset-preview-img]');
        const thumb = document.querySelector('[data-asset-preview]');
        return img.getAttribute('src') === thumb.getAttribute('src');
    }""")
    assert same
    box = page.locator(".asset-preview").bounding_box()
    thumb = _anchor(page, "wide_0_1.png").bounding_box()
    assert box["width"] > thumb["width"]


@pytest.mark.django_db(transaction=True)
def test_a_non_4_3_source_shows_its_full_extent(page, ...):
    """The crop comes from .asset-thumb's OWN aspect-ratio + object-fit:cover.
    The overlay image is a separate element that simply does not carry them.

    Fixture and viewport are chosen so the image does NOT hit the container's
    max-height: at 1280x900 the budget is ~884px and a 200x400 source in a
    ~302px content box wants ~604px. A taller source would be SHRUNK by
    flex:0 1 auto (which the tall-portrait row asserts), so its element box
    would no longer carry the source's ratio.
    """
    page.set_viewport_size({"width": 1280, "height": 900})
    make_image_asset(course, filename="portret_0_1.png", size=(200, 400))
    # ... open the manager
    _open_preview(page, "portret_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    ratio = page.evaluate("""() => {
        const r = document.querySelector('[data-asset-preview-img]').getBoundingClientRect();
        return r.width / r.height;
    }""")
    assert abs(ratio - 200 / 400) < 0.05


@pytest.mark.django_db(transaction=True)
def test_a_small_source_still_previews_larger_than_the_thumb(page, ...):
    # Short name + small size, both deliberate: with a normal-length name the
    # mutant's shrink-wrapped box would be sized by the caption (~160px, already
    # wider than a ~115px thumb) and the row would stay green.
    make_image_asset(course, filename="s.png", size=(40, 30))
    # ... open the manager
    _open_preview(page, "s.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    img = page.locator("[data-asset-preview-img]").bounding_box()
    thumb = page.locator("[data-asset-preview]").first.bounding_box()
    assert img["width"] > thumb["width"]


@pytest.mark.django_db(transaction=True)
def test_an_over_budget_name_is_readable_in_the_caption(page, ...):
    make_image_asset(course, filename="przykladowa_bardzo_dluga_nazwa_0_2.png", size=(400, 300))
    # ... open the manager
    _open_preview(page, "przykladowa_bardzo_dluga_nazwa_0_2.png")
    clipped = page.evaluate("""() => {
        const cap = document.querySelector('.asset-preview__caption');
        return cap.scrollWidth > cap.clientWidth;
    }""")
    assert not clipped


@pytest.mark.django_db(transaction=True)
def test_the_caption_is_written_as_text_not_markup(page, ...):
    """getAttribute returns data-name FULLY DECODED, so the server-side escaping
    that protects the card gives the overlay no protection at all. Nothing else
    in the suite would go red if textContent became innerHTML."""
    hostile = "<img src=x onerror=1>.png"
    make_image_asset(course, filename=hostile, size=(400, 300))
    # ... open the manager
    _open_preview(page, hostile)
    assert page.locator(".asset-preview__caption").text_content() == hostile
    injected = page.evaluate(
        """() => document.querySelectorAll('.asset-preview img').length"""
    )
    assert injected == 1          # only [data-asset-preview-img]


@pytest.mark.django_db(transaction=True)
def test_a_tall_source_is_clamped_and_lands_centred_at_360(page, ...):
    """Centred is the LAST branch of place()'s five-way ladder and the only one
    any test reaches -- assert it was taken, or the clamp alone would satisfy
    an inside-the-viewport check from any branch."""
    make_image_asset(course, filename="wysoki_0_1.png", size=(400, 2000))
    page.set_viewport_size({"width": 360, "height": 900})
    # ... open the manager
    _open_preview(page, "wysoki_0_1.png")
    # Without this wait the image is display:none, its rect is all zeros, and
    # `inside(i)` is trivially true -- which would let the min-height mutant pass.
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    result = page.evaluate("""() => {
        const vw = document.documentElement.clientWidth;
        const vh = document.documentElement.clientHeight;
        const o = document.querySelector('.asset-preview').getBoundingClientRect();
        const i = document.querySelector('[data-asset-preview-img]').getBoundingClientRect();
        const inside = b => b.left >= 0 && b.top >= 0 && b.right <= vw && b.bottom <= vh;
        return {
            fits: inside(o) && inside(i),
            imgHeight: i.height,
            dx: Math.abs((o.left + o.width / 2) - vw / 2),
            dy: Math.abs((o.top + o.height / 2) - vh / 2),
        };
    }""")
    assert result["imgHeight"] > 0, "a zero rect would satisfy `fits` vacuously"
    assert result["fits"]
    assert result["dx"] <= 2 and result["dy"] <= 2


@pytest.mark.django_db(transaction=True)
def test_hovering_the_covered_neighbour_switches_the_overlay(page, ...):
    """pointer-events:none is load-bearing: the overlay necessarily covers the
    neighbouring cell, and without it Playwright reports the overlay
    intercepting and the neighbour can never be hovered."""
    make_image_asset(course, filename="jeden_0_1.png", size=(400, 300))
    make_image_asset(course, filename="dwa_0_2.png", size=(400, 300))
    # ... open the manager at 1280x900
    _open_preview(page, "jeden_0_1.png")
    # Identify the covered neighbour from the MEASURED overlay box rather than
    # assuming which cell it lands on -- and return its NAME, not an ordinal:
    # a cell index and a [data-asset-preview] index only align while every
    # asset is an image.
    covered = page.evaluate("""() => {
        const o = document.querySelector('.asset-preview').getBoundingClientRect();
        const hit = Array.from(document.querySelectorAll('.asset-cell')).find(c => {
            const r = c.getBoundingClientRect();
            return r.left < o.right && r.right > o.left
                && r.top < o.bottom && r.bottom > o.top
                && c.getAttribute('data-name') !== 'jeden_0_1.png';
        });
        return hit ? hit.getAttribute('data-name') : null;
    }""")
    assert covered and covered != "jeden_0_1.png", "the overlay covers no neighbour"
    _open_preview(page, covered)
    expect(page.locator(".asset-preview__caption")).to_have_text(covered)


@pytest.mark.django_db(transaction=True)
def test_a_cell_from_a_swapped_in_grid_still_opens_the_overlay(page, ...):
    """The whole justification for delegating mouseover/mouseout: the debounced
    filter replaces the entire .asset-grid, and per-node listeners bound at load
    would go silently dead on every swapped-in cell."""
    make_image_asset(course, filename="filtrowany_0_1.png", size=(400, 300))
    # ... open the manager, then type in the filter box and wait for the swap
    page.fill("[data-filter-q]", "filtrowany")
    page.wait_for_selector('.asset-grid .asset-dname:has-text("filtrowany_0_1.png")')
    _open_preview(page, "filtrowany_0_1.png")
    expect(page.locator(".asset-preview__caption")).to_have_text("filtrowany_0_1.png")


@pytest.mark.django_db(transaction=True)
def test_a_grid_swap_during_the_dwell_opens_nothing(page, ...):
    """A detached anchor measures as zeros, so "fits on the right" trivially
    passes and the overlay pins to the corner with no anchor left to close it."""
    make_image_asset(course, filename="znikajacy_0_1.png", size=(400, 300))
    # ... open the manager
    page.locator("[data-asset-preview]").first.hover()      # start the dwell
    page.fill("[data-filter-q]", "brak-dopasowania")        # swap mid-dwell
    page.wait_for_timeout(600)                              # outlive the dwell
    expect(page.locator(".asset-preview")).to_be_hidden()
```

- [ ] **Step 5: Run, then falsify each row**

Run: `uv run pytest tests/test_e2e_media_manager.py -m e2e -k "hover_opens or non_4_3 or small_source or readable_in_the_caption or caption_is_written or tall_source or covered_neighbour or swapped_in_grid or during_the_dwell" -v`

| Mutant | Row |
| --- | --- |
| remove the `mouseover` listener | `hover_opens` |
| give the overlay image `aspect-ratio: 4/3; object-fit: cover` | `non_4_3` |
| `.asset-preview` `width` → `max-width` | `small_source` |
| drop the caption's `overflow-wrap: anywhere` | `readable_in_the_caption` |
| `overlayCaption.textContent` → `.innerHTML` | `caption_is_written` |
| drop the image's `min-height: 0` | `tall_source` (no longer fits) |
| delete the centred `else` branch of `place()` | `tall_source` (no longer centred) |
| move `place()` before `overlay.hidden = false` | `tall_source` (measures zeros) |
| drop `pointer-events: none` | `covered_neighbour` (Playwright reports interception) |
| bind `mouseenter` per node at load instead of delegating | `swapped_in_grid` |
| drop the `isConnected` check in the dwell timer | `during_the_dwell` |

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
- Produces: `teardownOpenBindings()`, called at the top of `open()` and from `close()` — Task 7 registers the observer and the scroll/Escape listeners inside it. Also the caption-only state and the 300 ms hide grace.

- [ ] **Step 1: Restructure `open()` before adding anything**

Two structural problems must be fixed first, or Task 7 layers onto a broken shape:

1. **An in-place swap re-enters `open()` without an intervening `close()`.** Task 7 will register a `MutationObserver` and scroll/resize/keydown listeners inside `open()`, whose only teardown lives in `close()` — so every swap would leak one observer and one listener set, unbounded across a sweep.
2. **The caption-only branch (Step 3 below) returns early**, so anything Task 7 appends to the tail of `open()` would never run for a broken image — leaving that overlay with no Escape, scroll or resize handler at all.

Restructure so both are impossible:

```js
  function teardownOpenBindings() {
    // Everything open() registers. Called from open() itself (an in-place swap
    // re-enters without closing) and from close(). Task 7 adds the observer and
    // the scroll/resize/keydown listeners here.
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
  }

  function open(anchor) {
    if (!overlay) build();
    var cell = anchor.closest(".asset-cell");
    if (!cell) return;
    teardownOpenBindings();
    cancelHide();
    generation += 1;
    overlayImg.hidden = true;
    overlayCaption.textContent = cell.getAttribute("data-name") || "";
    openAnchor = anchor;

    var src = anchor.currentSrc || anchor.getAttribute("src") || "";
    if (!src || (anchor.complete && anchor.naturalWidth === 0)) {
      // The thumbnail itself failed, so there is nothing to copy. Assigning ""
      // does not reliably fire error and can leave the previous image showing.
      captionOnly();
    } else {
      overlayImg.src = src;
      expectedSrc = src;
      if (overlayImg.getAttribute("src") === expectedSrc
          && overlayImg.complete && overlayImg.naturalWidth > 0) {
        overlayImg.hidden = false;   // ahead of measure -- see Task 5
      }
    }

    // ONE shared tail, reached by both branches.
    overlay.style.visibility = "hidden";
    overlay.hidden = false;
    place();
    overlay.style.visibility = "";
    bindOpenListeners();             // Task 7 fills this in; a no-op until then
  }

  function bindOpenListeners() {}    // Task 7

  function close() {
    teardownOpenBindings();
    cancelHide();
    if (!overlay) return;
    overlay.hidden = true;
    overlayImg.hidden = true;
    openAnchor = null;
    expectedSrc = null;
  }
```

- [ ] **Step 2: Spike the route/cache premise before writing the two route-driven rows**

Spec §5 claims "**No new request.** The overlay reuses the thumbnail's own
`currentSrc`, so the browser serves it from cache." If that holds literally,
assigning the same URL to the overlay `<img>` is a memory-cache hit and issues
**no network request** for a `page.route` handler to intercept — which would
make both the 404 row and the in-flight row unfalsifiable. In practice enabling
`page.route` disables the HTTP cache, which is why they work; that is an
unstated premise and it also suspends the very "no new request" property while
those tests run.

Verify before writing them: install a `page.on("request", …)` counter and a
passthrough `page.route("**/*", lambda r: r.continue_())`, hover a thumb, and
assert the overlay's URL was requested a second time. If it is not, switch both
rows to a fulfilled route that serves a deliberately broken body rather than
relying on interception of a cached URL.

- [ ] **Step 3: Write the failing tests**

```python
@pytest.mark.django_db(transaction=True)
def test_sweeping_a_to_b_swaps_in_place(page, live_server):
    """The thumbs are not adjacent: 8+1+12+1+8 = 30px of non-anchor space sits
    between them (padding, border, grid gap). Without a close grace a physically
    moving pointer always exits to a non-anchor, so B re-pays the full dwell and
    the in-place swap is reachable only by a TELEPORTING pointer -- which is
    exactly what hover(A) then hover(B) produces. Drive the real path."""
    make_image_asset(course, filename="jeden_0_1.png", size=(400, 300))
    make_image_asset(course, filename="dwa_0_2.png", size=(400, 300))
    # ... open the manager at 1280x900
    _open_preview(page, "jeden_0_1.png")
    # Correct build and mutant reach the SAME terminal state and differ only in
    # a transient, so record the transitions instead of reading after the fact.
    page.evaluate("""() => {
        window.__hiddenLog = [];
        const o = document.querySelector('.asset-preview');
        new MutationObserver(() => window.__hiddenLog.push(o.hidden))
            .observe(o, {attributes: true, attributeFilter: ['hidden']});
    }""")
    # BY NAME: the grid sorts "-created", so dwa_0_2 renders FIRST and nth(1)
    # would sweep the pointer back onto jeden_0_1.
    b = _anchor(page, "dwa_0_2.png").bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    expect(page.locator(".asset-preview__caption")).to_have_text("dwa_0_2.png")
    assert page.evaluate("() => window.__hiddenLog") == []


@pytest.mark.django_db(transaction=True)
def test_a_drift_into_the_cell_padding_and_back_keeps_the_overlay(page, ...):
    """mouseover fires only on ENTRY, so if the grace expires under a resting
    pointer nothing can reopen the overlay. Aim just outside the thumb but
    inside its cell -- 4px above the thumb's top edge is inside the cell's 8px
    padding."""
    make_image_asset(course, filename="dryf_0_1.png", size=(400, 300))
    # ... open the manager at 1280x900
    _open_preview(page, "dryf_0_1.png")
    t = page.locator("[data-asset-preview]").first.bounding_box()
    cx = t["x"] + t["width"] / 2
    page.mouse.move(cx, t["y"] - 4)            # into the cell's padding
    page.wait_for_timeout(100)                 # well inside the 300ms grace
    page.mouse.move(cx, t["y"] + t["height"] / 2)   # back onto the thumb
    page.wait_for_timeout(400)                 # outlive the grace
    expect(page.locator(".asset-preview")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_reopening_the_same_anchor_shows_the_image_and_sizes_to_it(page, ...):
    """Re-assigning an identical src to a complete <img> may not re-queue
    `load`; without the synchronous reveal the image stays hidden forever. And
    the reveal must happen BEFORE measure, or the overlay is placed against a
    caption-only box."""
    make_image_asset(course, filename="powrot_0_1.png", size=(400, 300))
    # ... open the manager at 1280x900
    _open_preview(page, "powrot_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    first_height = page.locator(".asset-preview").bounding_box()["height"]
    page.mouse.move(5, 5)
    page.wait_for_timeout(600)                 # outlive the grace
    expect(page.locator(".asset-preview")).to_be_hidden()
    _open_preview(page, "powrot_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    assert abs(page.locator(".asset-preview").bounding_box()["height"] - first_height) <= 2


@pytest.mark.django_db(transaction=True)
def test_a_404_source_shows_the_caption_and_no_image_box(page, ...):
    """Abort the overlay's request but NOT the thumbnail's, so this exercises
    the `error` handler rather than the empty-currentSrc guard."""
    user, course = _seed_assets("err-pa", "err", ("zepsuty_0_1.png", (400, 300)))
    seen = {"n": 0}

    def block_second_fetch(route):
        # Request 1 is the THUMBNAIL's, request 2 is the overlay's. The route
        # must be installed BEFORE the manager loads, or the thumbnail's fetch
        # happens un-intercepted and the overlay's becomes request 1 -- which
        # this handler would then continue, and the row would be red on a
        # correct build.
        seen["n"] += 1
        if seen["n"] > 1:
            route.abort()
        else:
            route.continue_()

    page.route("**/zepsuty_0_1*", block_second_fetch)
    _open_manager(page, live_server, "err-pa", course)
    _open_preview(page, "zepsuty_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_hidden()
    expect(page.locator(".asset-preview__caption")).to_have_text("zepsuty_0_1.png")


@pytest.mark.django_db(transaction=True)
def test_a_thumbnail_that_never_loaded_shows_the_caption_only(page, ...):
    """The OTHER caption-only source: the thumb itself failed, so currentSrc is
    empty and there is nothing to copy. Abort every request for this asset,
    including the thumbnail's."""
    make_image_asset(course, filename="martwy_0_1.png", size=(400, 300))
    page.route("**/martwy_0_1*", lambda route: route.abort())
    # ... open the manager
    _open_preview(page, "martwy_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_hidden()
    expect(page.locator(".asset-preview__caption")).to_have_text("martwy_0_1.png")


@pytest.mark.django_db(transaction=True)
def test_a_broken_asset_then_a_good_one_restores_the_image_box(page, ...):
    """The overlay is a SINGLETON: without an unconditional reset at open, one
    broken thumbnail leaves every later preview on the page caption-only."""
    make_image_asset(course, filename="martwy_0_1.png", size=(400, 300))
    make_image_asset(course, filename="zdrowy_0_2.png", size=(400, 300))
    page.route("**/martwy_0_1*", lambda route: route.abort())
    # ... open the manager
    _open_preview(page, "martwy_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_hidden()
    page.mouse.move(5, 5)
    page.wait_for_timeout(600)
    _open_preview(page, "zdrowy_0_2.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_b_s_caption_never_appears_over_a_s_image(page, ...):
    """Hold B's source unresolved with a route so the window is bounded and
    observable -- the natural window is a cached decode, far shorter than any
    poll interval, so sampling for it would be a race, not an assertion."""
    make_image_asset(course, filename="pierwszy_0_1.png", size=(400, 300))
    make_image_asset(course, filename="drugi_0_2.png", size=(400, 300))
    released = {"route": None}
    page.route("**/drugi_0_2*", lambda route: released.__setitem__("route", route))
    # ... open the manager at 1280x900
    _open_preview(page, "pierwszy_0_1.png")
    # BY NAME -- see the ordering note above. With nth(1) the pointer would land
    # on `pierwszy`, no request for drugi would ever be suspended, and
    # released["route"] would stay None (AttributeError, not a clean failure).
    b = _anchor(page, "drugi_0_2.png").bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    expect(page.locator(".asset-preview__caption")).to_have_text("drugi_0_2.png")
    # B's caption is up and B's image is still in flight: the <img> must be
    # hidden, NOT still painting A's frame.
    expect(page.locator("[data-asset-preview-img]")).to_be_hidden()
    released["route"].continue_()
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
```

- [ ] **Step 4: Run them to verify they fail**

- [ ] **Step 5: Add the grace and the caption-only state**

Add near the other constants:

```js
  var GRACE_MS = 300;
  var hideTimer = null;
```

The `load` / `error` handlers already exist from Task 5's `build()`. Change the `error` handler's body from the bare `overlayImg.hidden = true` to `captionOnly()`, which additionally nulls `expectedSrc`. Then add:

```js
  function captionOnly() {
    overlayImg.hidden = true;
    // Null the expected source, or a load still in flight for a PREVIOUS asset
    // would still compare equal (this branch assigns no src) and would un-hide
    // the image, painting A's frame under B's caption.
    expectedSrc = null;
  }

  function startHide() {
    cancelHide();
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

Replace the `mouseover`/`mouseout` handlers:

```js
    root.addEventListener("mouseover", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      hoveredAnchor = anchor;
      cancelHide();          // ANY anchor entry cancels a pending hide
      if (anchor === openAnchor) return;   // same anchor: the cancel above IS
                                           // the work -- not a bare no-op
      if (openAnchor) { open(anchor); return; }   // in-place swap, no dwell
      if (dwellTimer !== null) return;
      dwellTimer = setTimeout(function () {
        dwellTimer = null;
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
      // Arm ONLY for the open anchor. Otherwise the A-hovered/B-open case tears
      // itself down: pointer on A, user Tabs into cell B, pointer drifts off A,
      // and 300ms later a mouse twitch kills a keyboard user's overlay.
      if (anchor !== openAnchor) return;
      startHide();
    });
```

- [ ] **Step 6: Run the tests to verify they pass**

- [ ] **Step 7: Falsify each row**

| Mutant | Row |
| --- | --- |
| `mouseout` closes immediately instead of arming the grace | `sweeping_a_to_b` |
| same-anchor `mouseover` returns before `cancelHide()` | `drift_into_the_cell_padding` |
| drop the synchronous `complete && naturalWidth > 0` reveal | `reopening_the_same_anchor` |
| reveal **after** `place()` instead of before | `reopening_the_same_anchor` (height assertion) |
| drop the `error` listener | `404_source` |
| drop the empty-`currentSrc` guard | `thumbnail_that_never_loaded` |
| drop the unconditional `overlayImg.hidden = true` reset in `open()` | `broken_asset_then_a_good_one` |
| drop `expectedSrc = null` from `captionOnly()` | `b_s_caption_never_appears` |

- [ ] **Step 8: Commit**

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
- Consumes: Tasks 5 and 6, in particular `teardownOpenBindings()` and `bindOpenListeners()`.
- Produces: the complete module.

- [ ] **Step 1: Write the failing tests — one per behaviour**

```python
def _tab_to_a_card_button(page, limit=40):
    """Tab until focus lands inside an .asset-cell, or fail loudly.

    The number of stops before the first card button depends on the header
    link, the upload form's controls, the kind <select> and the search input --
    do not hardcode it.
    """
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate("() => !!document.activeElement.closest('.asset-cell')"):
            return
    raise AssertionError("focus never reached a card button")


@pytest.mark.django_db(transaction=True)
def test_escape_closes_the_overlay(page, live_server):
    user, course = _seed_assets("esc-pa", "esc", ("escape_0_1.png", (400, 300)))
    _open_manager(page, live_server, "esc-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "escape_0_1.png")
    page.keyboard.press("Escape")
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_scroll_and_resize_each_close_the_overlay(page, live_server):
    # Enough assets that the grid is TALLER than the viewport, or mouse.wheel
    # produces no scroll event at all and the row passes vacuously.
    specs = [(f"przewijany_{i}_0.png", (400, 300)) for i in range(24)]
    user, course = _seed_assets("scr-pa", "scr", *specs)
    _open_manager(page, live_server, "scr-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})

    _open_preview(page, "przewijany_0_0.png")
    page.mouse.wheel(0, 200)
    expect(page.locator(".asset-preview")).to_be_hidden()

    # Move the pointer AWAY before re-opening: mouseover fires only on ENTRY, so
    # hovering a thumb the pointer already rests on dispatches nothing and the
    # second _open_preview would time out.
    page.mouse.move(5, 5)
    page.wait_for_timeout(400)
    _open_preview(page, "przewijany_0_0.png")
    page.set_viewport_size({"width": 1100, "height": 900})
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_focusout_does_not_close_a_pointer_opened_overlay(page, live_server):
    """An unscoped focusout would dismiss the preview the user is actively
    hovering whenever focus moved anywhere -- e.g. a Tab out of the filter box."""
    user, course = _seed_assets("fo-pa", "fo", ("fokus_0_1.png", (400, 300)))
    _open_manager(page, live_server, "fo-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "fokus_0_1.png")
    page.locator("[data-filter-q]").focus()
    page.keyboard.press("Tab")
    page.wait_for_timeout(400)
    expect(page.locator(".asset-preview")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_tabbing_to_a_card_button_opens_it_and_it_stays_open(page, live_server):
    """Seed enough assets that the grid is taller than the viewport, so the
    focus-induced scroll actually fires. focus() scrolls the element into view
    and that scroll event is dispatched AFTER the focusin handler ran -- a
    synchronously-bound scroll listener would close the overlay it just opened.
    """
    specs = [(f"kafelek_{i}_0.png", (400, 300)) for i in range(24)]
    user, course = _seed_assets("tab-pa", "tab", *specs)
    _open_manager(page, live_server, "tab-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _tab_to_a_card_button(page)
    expect(page.locator(".asset-preview")).to_be_visible()
    page.wait_for_timeout(400)          # outlive any deferred scroll close
    expect(page.locator(".asset-preview")).to_be_visible()


# NOTE: there is deliberately no "same-frame open and close" row.
#
# The obvious one -- focus a card button and synchronously dispatch Escape in
# the same page.evaluate -- cannot discriminate: onKeydown is registered INSIDE
# the rAF in bindOpenListeners(), so a keydown dispatched before that frame
# reaches no handler at all and the close never happens on either build. And
# even if it did, the rAF body already bails on `gen !== generation ||
# !openAnchor`, and close() nulls openAnchor -- so dropping
# cancelAnimationFrame still binds nothing.
#
# cancelAnimationFrame therefore stays in teardownOpenBindings() as documented
# defence-in-depth against a future close path that does not null openAnchor,
# explicitly NOT as a falsified line. Do not add a row that appears to test it.


@pytest.mark.django_db(transaction=True)
def test_a_replace_commit_does_not_leave_the_overlay_open(page, live_server):
    """focusTrigger(fresh) at media_picker.js:550 focuses the fresh cell's own
    replace button after every commit. Without the :focus-visible gate that
    raises a 320px overlay unprompted, in five other tests and the screenshots.
    """
    # ... drive a replace to completion, per the file's existing replace tests:
    #     click [data-replace-asset], set_files on the chooser, click
    #     [data-replace-commit], wait for [data-replace-strip] to detach.
    page.wait_for_timeout(600)   # negative assertions must outlive the dwell
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_hovering_a_thumb_while_a_rename_input_is_open_does_not_open(page, live_server):
    """A one-shot close is defeated by moving the pointer back 300ms later.
    The gate is a STANDING condition, re-checked at every open attempt."""
    user, course = _seed_assets("gate-pa", "gate", ("brama_0_1.png", (400, 300)))
    _open_manager(page, live_server, "gate-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator("[data-rename-asset]").first.click()
    expect(page.locator(".asset-rename-input")).to_be_visible()
    _anchor(page, "brama_0_1.png").hover()
    page.wait_for_timeout(600)
    expect(page.locator(".asset-preview")).to_be_hidden()
    page.keyboard.press("Escape")   # cancel the rename; never commit


@pytest.mark.django_db(transaction=True)
def test_hovering_a_thumb_while_a_replace_strip_is_open_does_not_open(page, live_server):
    # ... raise the replace confirm strip (click [data-replace-asset] and choose
    #     a file), then hover that cell's thumb via _anchor()
    page.wait_for_timeout(600)
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_a_keyboard_driven_pencil_leaves_no_observer_behind(page, live_server):
    """Two traps this row exists to avoid.

    (1) Drive the pencil by KEYBOARD, not by click. media_picker.js:339 focuses
    the rename INPUT, whose focusin the handler filters out at its own first
    line, and the preceding click-focus on the ✎ button fails :focus-visible --
    so a pointer-driven pencil never reaches open() and the row would be green
    on both builds.

    (2) Count LIVENESS, not constructions. bindOpenListeners() constructs one
    observer per open either way, so a construction count is identical on both
    builds; only a connect/disconnect balance discriminates.
    """
    page.add_init_script("""
        window.__live = 0;
        const Real = MutationObserver;
        function Shim(cb) {
            const o = new Real(cb);
            const realObserve = Real.prototype.observe.bind(o);
            const realDisconnect = Real.prototype.disconnect.bind(o);
            let counted = false;
            o.observe = function () { 
                if (!counted) { window.__live += 1; counted = true; }
                return realObserve.apply(null, arguments);
            };
            o.disconnect = function () {
                if (counted) { window.__live -= 1; counted = false; }
                return realDisconnect();
            };
            return o;
        }
        Shim.prototype = Real.prototype;   // keep instanceof and the proto chain
        window.MutationObserver = Shim;
    """)
    specs = [(f"olowek_{i}_0.png", (400, 300)) for i in range(24)]
    user, course = _seed_assets("pen-pa", "pen", *specs)
    _open_manager(page, live_server, "pen-pa", course)
    for _ in range(3):
        _tab_to_a_card_button(page)     # the cell's ✎ / ⇄ / 🗑, keyboard-focused
        page.keyboard.press("Enter")
        page.keyboard.press("Escape")
    assert page.evaluate("() => window.__live") == 0


@pytest.mark.django_db(transaction=True)
def test_a_sweep_does_not_accumulate_observers(page, live_server):
    """An in-place swap re-enters open() without closing; without the shared
    teardown it would leak one live observer per card."""
    # ... the same add_init_script liveness shim as above
    user, course = _seed_assets(
        "swp-pa", "swp",
        ("a_0_1.png", (400, 300)), ("b_0_2.png", (400, 300)), ("c_0_3.png", (400, 300)),
    )
    _open_manager(page, live_server, "swp-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "a_0_1.png")
    for name in ("b_0_2.png", "c_0_3.png"):
        box = _anchor(page, name).bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
        expect(page.locator(".asset-preview__caption")).to_have_text(name)
    assert page.evaluate("() => window.__live") == 1


@pytest.mark.django_db(transaction=True)
def test_a_filter_swap_closes_a_pointer_opened_overlay(page, live_server):
    user, course = _seed_assets("fsp-pa", "fsp", ("znikam_0_1.png", (400, 300)))
    _open_manager(page, live_server, "fsp-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "znikam_0_1.png")
    page.fill("[data-filter-q]", "brak-dopasowania")
    page.wait_for_selector(".asset-grid .asset-cell", state="detached")
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_a_filter_swap_closes_a_focus_opened_overlay(page, live_server):
    """The focus-opened variant is what discriminates connect-at-open from
    connect-at-dwell-start: the focus path has no dwell to connect at."""
    specs = [(f"znikam_{i}_0.png", (400, 300)) for i in range(24)]
    user, course = _seed_assets("fsf-pa", "fsf", *specs)
    _open_manager(page, live_server, "fsf-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _tab_to_a_card_button(page)
    expect(page.locator(".asset-preview")).to_be_visible()
    # Do NOT page.fill() here: filling focuses the input, which blurs the card
    # button and fires focusout on root. openedBy() is "focus" at that moment,
    # so the overlay would close BEFORE the debounced swap ever runs -- the row
    # would pass with the observer never connected, and the connect-at-dwell
    # mutant would survive. Set the value and dispatch `input` without moving
    # focus.
    page.evaluate("""() => {
        const q = document.querySelector('[data-filter-q]');
        q.value = 'brak-dopasowania';
        q.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    page.wait_for_selector(".asset-grid .asset-cell", state="detached")
    expect(page.locator(".asset-preview")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_the_pointer_can_still_hold_a_focus_opened_overlay(page, live_server):
    """The A-hovered / B-focus-opened configuration. The pointer must be RESTING
    on A when the Tab happens -- if it has already left, no mouseout on A ever
    fires afterwards and the mutant has no event to mishandle."""
    specs = [("a_0_1.png", (400, 300))] + [
        (f"b_{i}_0.png", (400, 300)) for i in range(24)
    ]
    user, course = _seed_assets("hold-pa", "hold", *specs)
    _open_manager(page, live_server, "hold-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "a_0_1.png")          # pointer rests on A, overlay on A
    _tab_to_a_card_button(page)               # focus-open swaps the overlay to B
    caption = page.locator(".asset-preview__caption").text_content()
    assert caption != "a_0_1.png"
    page.mouse.move(5, 5)                     # NOW leave A
    page.wait_for_timeout(500)                # outlive the grace
    expect(page.locator(".asset-preview")).to_be_visible()
    assert page.locator(".asset-preview__caption").text_content() == caption
```

- [ ] **Step 2: Run them to verify they fail**

- [ ] **Step 3: Implement**

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

  function onKeydown(e) {
    // Bubble phase, and NEVER preventDefault/stopPropagation:
    // media_picker.js:371-373 handles Escape on the rename input to cancel, and
    // swallowing the key would be a latent regression. This deliberately is not
    // imagezoom's capture-phase arbitration -- a non-modal overlay has no claim
    // to exclusivity.
    if (e.key === "Escape") close();
  }
```

Extend `teardownOpenBindings()` (Task 6) to cover everything `open()` registers:

```js
  function teardownOpenBindings() {
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
    if (observer) { observer.disconnect(); observer = null; }
    if (scrollRaf !== null) { cancelAnimationFrame(scrollRaf); scrollRaf = null; }
    if (onScroll) {
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("keydown", onKeydown);
      onScroll = null;
    }
  }
```

Add the gate to `open()`, immediately after the `cell` lookup and **before** anything is registered:

```js
    if (gated()) return;
```

Fill in `bindOpenListeners()`:

```js
  function bindOpenListeners() {
    observer = new MutationObserver(function () {
      if (!openAnchor) return;                       // no-op when closed
      if (!openAnchor.isConnected) { close(); return; }
      if (gated()) close();
    });
    observer.observe(root, { childList: true, subtree: true });

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
  }
```

The focus path, armed unconditionally (**not** behind `canHover`):

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
    open(anchor);   // immediately, no dwell; open() cancels the pending dwell
  });

  root.addEventListener("focusout", function () {
    if (openedBy() === "focus") close();
  });
```

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Falsify each row**

| Mutant | Row |
| --- | --- |
| drop the `keydown` binding | `escape_closes` |
| drop the `scroll` / `resize` binding in turn | `scroll_and_resize` |
| drop the `openedBy() === "focus"` scoping | `focusout_does_not_close` |
| bind the scroll listener synchronously instead of in the rAF | `tabbing_to_a_card_button` |
| drop the `:focus-visible` check | `replace_commit_does_not_leave` |
| make the gate one-shot instead of standing | `rename_input_is_open`, `replace_strip_is_open` |
| move `if (gated()) return;` to *after* `bindOpenListeners()` | `rename_input_is_open`, `replace_strip_is_open` — **not** the pencil row: there every `open()` happens before any input exists, so the gate is not yet true and the mutant is a no-op |
| drop the `observer.disconnect()` from `teardownOpenBindings()` | `sweep_does_not_accumulate` |
| drop the `MutationObserver` entirely | both `filter_swap_closes_*` rows |
| connect the observer at dwell start instead of at open | `filter_swap_closes_a_focus_opened_overlay` (the focus path has no dwell, so it would never connect) |
| arm the hide timer on every anchor exit, not just `openAnchor`'s | `pointer_can_still_hold` |
| drop `\|\| hideTimer !== null` from `openedBy()` | `focusout_does_not_close` (during the grace) |

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

**Settle this by spike first:** in Chromium the `hover`/`pointer` media features follow the device-emulation configuration, which Playwright derives from `is_mobile`, not from `has_touch` alone. If `has_touch=True` leaves `(hover: hover) and (pointer: fine)` matching, the gate arms and this row is red on a correct build. Prefer a full device descriptor (`**playwright.devices["Pixel 5"]`, which sets both; `is_mobile` is Chromium-only). Verify by evaluating the media query in the new context before writing the assertion.

```python
@pytest.mark.django_db(transaction=True)
def test_a_tap_does_not_open_the_overlay_on_touch(browser, playwright, ...):
    context = browser.new_context(**playwright.devices["Pixel 5"])
    page = context.new_page()
    # ... open the manager
    assert not page.evaluate(
        """() => matchMedia('(hover: hover) and (pointer: fine)').matches"""
    )
    page.locator("[data-asset-preview]").first.tap()
    page.wait_for_timeout(600)   # negative assertions must outlive the dwell
    expect(page.locator(".asset-preview")).to_be_hidden()
    context.close()
```

Mutant: drop the `matchMedia` gate.

- [ ] **Step 2: Refresh the screenshots**

`test_screenshots_light_and_dark` takes **element** screenshots (`unused_cell.screenshot(...)`), which clip to the element's own box — a body-appended, fixed overlay placed outside the card can never appear in one.

The existing test sets 360×900 **once at `:600`, before `_login` and before the
`for theme` loop**. Insert the new steps **inside** that loop, immediately after
its `assert page.locator("html").get_attribute("data-theme") == theme` — the
hover needs the grid to exist, so it cannot precede the `page.goto`. Keep the
pre-loop `set_viewport_size(360)` where it is; step 6 below restores 360 px
after each theme's overlay shot, so the four element shots still run at the
width their docstring describes.

Per theme, in this exact order:

1. `page.set_viewport_size({"width": 1280, "height": 900})`
2. `page.locator("[data-asset-preview]").first.hover()`
3. `expect(page.locator(".asset-preview")).to_be_visible()` — **required**; without it the capture races the 250 ms dwell and can shoot an empty grid, which is the failure a screenshot review is least likely to notice
4. `page.screenshot(path=f"…/media-overlay-{theme}.png")`
5. `page.mouse.move(5, 5)` and wait for the overlay to hide
6. `page.set_viewport_size({"width": 360, "height": 900})`
7. the four existing element shots, unchanged

Card height changes in those four, and the ✎ button moves to the card's right edge — visible only on a hovered cell, since it is `opacity: 0` otherwise, so shot 1 shows no pencil at all.

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

**Spec coverage, row by row.** §1 → Task 1. §2 → Task 2. §3 → Task 4. §4 → Task 3. §5 → Tasks 5–7.

Every row in the spec's Testing table maps to a named test:

| Spec row | Test |
| --- | --- |
| text-run rects inside the card | Task 4 `stays_inside_its_card` |
| suffix painted inside the card | Task 4 `paint_their_own_suffix` |
| ✎ aligned to the first line | Task 4 `pencil_button_stays` |
| clamp produces 3 rects | Task 4 Step 7, **conditional on measurement** |
| head + … + tail | Task 1 unit tests |
| rename prefills the full name | Task 3 `rename_prefills` |
| hover opens with the thumb's src | Task 5 `hover_opens` |
| non-4:3 shows full extent | Task 5 `non_4_3` |
| small source previews larger | Task 5 `small_source` |
| caption readable | Task 5 `readable_in_the_caption` |
| caption is text, not markup | Task 5 `caption_is_written` |
| tall portrait fits + centred | Task 5 `tall_source` |
| covered neighbour switches | Task 5 `covered_neighbour` |
| post-swap grid still opens | Task 5 `swapped_in_grid` |
| swap during the dwell | Task 5 `during_the_dwell` |
| A→B swaps in place | Task 6 `sweeping_a_to_b` |
| drift and return | Task 6 `drift_into_the_cell_padding` |
| re-open shows the image | Task 6 `reopening_the_same_anchor` |
| 404 and never-loaded | Task 6 `404_source`, `thumbnail_that_never_loaded` |
| broken then good | Task 6 `broken_asset_then_a_good_one` |
| A's frame never under B's caption | Task 6 `b_s_caption_never_appears` |
| mouseout / Escape / focusout / scroll / resize | Task 7 (four rows) |
| focus opens; rename and replace do not | Task 7 (three rows) |
| filter swap closes | Task 7 `filter_swap_closes` |
| touch tap does not open | Task 8 `tap_does_not_open` |

**Deferred by design:** the WCAG 1.4.13 "hoverable" clause is knowingly unmet — `pointer-events: none` means the pointer can never move onto the overlay, traded against the strobe loop. Spec §5 records the reasoning; do not "fix" it without reading that.

**Three engine premises are spiked, not assumed**, each inside the task that depends on it:

1. Whether `-webkit-line-clamp` removes lines from the layout tree, so `getClientRects()` can discriminate (Task 4 Step 7).
2. Whether an overlay `<img>` assigned the thumbnail's own URL produces an interceptable request under `page.route`, given spec §5's "no new request … served from cache" (Task 6 Step 2). Both route-driven rows rest on it.
3. Whether Playwright's `has_touch` actually flips `(hover: hover) and (pointer: fine)` (Task 8 Step 1).

**Naming consistency:** `openAnchor`, `hoveredAnchor`, `expectedSrc`, `generation`, `dwellTimer`, `hideTimer`, `scrollRaf`, `onScroll`, `observer`, `gated()`, `openedBy()`, `startHide()`, `cancelHide()`, `captionOnly()`, `place()`, `open()`, `close()`, `build()`, `teardownOpenBindings()`, `bindOpenListeners()`, `onKeydown()` — used identically across Tasks 5, 6 and 7. The test helpers `_seed_assets(username, slug, *specs)` and `_anchor(page, filename)` are defined in Task 3, `_open_preview(page, filename)` — **by name, never by ordinal** — in Task 5, and `_tab_to_a_card_button(page)` in Task 7. Each is reused by every later task.

**One mutant is deliberately unmapped:** `cancelAnimationFrame` in `teardownOpenBindings()` has no falsifying row, because the only sequence that would exercise it dispatches Escape before `onKeydown` is bound and so closes nothing on either build. It is kept as stated defence-in-depth; Task 7 Step 1 records why, so nobody adds a row that appears to test it.
