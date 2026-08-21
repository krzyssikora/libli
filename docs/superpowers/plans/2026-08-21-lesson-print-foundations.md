# Lesson print foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two pre-existing defects that make `Ctrl+P` on a lesson produce a wrong page — dark theme printing white-on-white, and multi-slide lessons printing only the active slide.

**Architecture:** Three appended `@media print` blocks and nothing else. One in `tokens.css` restating the dark palette with `:root`'s values; one in `courses.css` doing the same for `--callout-accent`, which lives in a later sheet the tokens block cannot reach; one in `courses.css` revealing slideshow deck slides. No JS, no templates, no migration.

**Tech Stack:** Plain CSS (`@media print`, `color-mix()`), pytest, Playwright (`page.emulate_media`).

**Spec:** `docs/superpowers/specs/2026-08-21-lesson-print-foundations-design.md`

## Global Constraints

- **Every new CSS rule is APPENDED at the end of its file.** No insertion mid-file — the spec and its neighbours cite line numbers heavily, and an insertion rots them.
- **`@media print` adds no specificity.** Where a print rule ties its screen counterpart, it wins only by source order — which appending guarantees. Where it must beat a higher weight, it carries `!important`.
- **The `tokens.css` print block must sit AFTER the `[data-theme="dark"]` block** (which is `tokens.css:79–111`). `:root` and `[data-theme="dark"]` are both (0,1,0); an override above line 79 is silently inert.
- **`tokens.css` is a global path** (`tests/test_affected_tests.py:133`), so this branch selects the **whole suite**. Budget for a full run, not a scoped one.
- **`uv` is not on PATH.** Every command below uses the resolved absolute path:
  `C:/Users/krzys/.local/bin/uv.exe`. Copy the commands verbatim; a bare `uv` will not resolve.
- **Never pass `-q` on the command line.** `pyproject.toml:49` sets
  `addopts = "-q -m 'not e2e'"`, so a CLI `-q` makes it `-qq`, which suppresses the short test
  summary — disabling the very safeguard the next bullet depends on.
- **pytest can exit 0 with failures.** Grep the summary line; never trust the exit code alone.
- `-m e2e` is **mandatory** for e2e tests, or they all deselect and the run exits 5.
- **Ruff:** `pyproject.toml:36` selects `["E", "F", "I", "UP", "B", "S"]` with no `line-length`
  override, so the **88-character default applies** and unused imports are errors. Every code block
  below is already within 88 columns — keep it that way when editing.
- **Both CSS files are CRLF on disk.** Append with an editor or a tool that preserves CRLF, not a
  heredoc, or the file ends up mixed. Verify with `git diff --stat` after each append: a whole-file
  rewrite in the stat means the line endings flipped.
- The test-DB container must be running before any DB test. Check with `docker ps | grep libli-test-db`.
- **Never run two pytest processes at once** across worktrees — they share the test database.

---

### Task 1: Dark-theme token override in `tokens.css`

**Files:**
- Modify: `core/static/core/css/tokens.css` (append at end, after line 111)
- Modify: `tests/test_colour_map_drift.py` (final assertion at `:58`, replaced by 3 lines)
- Create: `tests/test_print_tokens_css.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an `@media print { [data-theme="dark"] { … } }` block at the end of `tokens.css`, restating all 33 dark-declared token names with `:root`'s declarations. Task 2 extends the same test file with a callout check.

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_print_tokens_css.py`:

```python
"""The @media print override must restate the dark palette with :root's values.

A dark-theme student printing any page gets near-white text on white paper: the
dark block sets --text-primary: #F2EFE9 and browsers strip backgrounds. The fix
duplicates :root's values inside @media print, and duplication is exactly what
drifts, so this test pins it.

The two [data-theme="dark"] blocks are located STRUCTURALLY, never by line
number: the file is partitioned at "@media print", so the screen block and the
print block are in disjoint strings and cannot resolve to the same text. That is
the failure mode tests/test_text_colour_css.py:68's first-match _block() helper
would have here.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parent.parent / "core/static/core/css/tokens.css"
).read_text(encoding="utf-8")

SCREEN, _sep, PRINT = CSS.partition("@media print")


def _decls(body):
    """{token-name: value} for one declaration block body.

    THE NEWLINE EXCLUSION IN THE VALUE CLASS IS WHAT MATTERS. tokens.css:44-48 is
    prose containing "--surface-overlay:", and a naive [^;]+ (which matches
    newlines) swallows from there to the next semicolon: --surface-overlay comes
    back as "nothing of the page may\n show through. */\n --scrim-solid: ..." and
    --scrim-solid never gets a key at all, making this test RED on a CORRECT build.
    Measured against the real file, [^;{}\n]+ alone gives the right answer.

    The comment strip below is belt-and-braces for a future comment that fits a
    whole "--x: y;" on one line; today it changes nothing. Do not mistake it for
    the load-bearing part -- battery row 14 mutates the value class, not this.
    """
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    return {
        name: " ".join(value.split())
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}\n]+);", body)
    }


def _block(source, pattern):
    match = re.search(pattern + r"\s*\{(.*?)\n\s*\}", source, re.DOTALL | re.MULTILINE)
    assert match, f"tokens.css: no block matching {pattern!r}"
    return _decls(match.group(1))


def test_print_block_exists_and_is_after_the_dark_block():
    assert _sep, "tokens.css must have an @media print block"
    # Structural, not a substring check: the print block's own header COMMENT
    # mentions [data-theme="dark"] and travels with it, so `in SCREEN` stays true
    # even when the block is moved above line 79 -- the exact mutant this guards.
    assert re.search(r'^\[data-theme="dark"\]\s*\{', SCREEN, re.M), (
        "the screen dark block must precede @media print"
    )
    assert '[data-theme="dark"]' in PRINT, (
        "@media print must scope its override to [data-theme=dark]"
    )


def test_print_override_restates_every_dark_token_with_the_root_value():
    root = _block(SCREEN, r"^:root")
    dark = _block(SCREEN, r'^\[data-theme="dark"\]')
    printed = _block(PRINT, r'\[data-theme="dark"\]')

    missing = sorted(set(dark) - set(printed))
    assert not missing, (
        f"@media print omits {len(missing)} token(s) the dark "
        f"block declares: {missing}. "
        "Every one must be restated or a dark-theme printout keeps that dark value."
    )
    for name in sorted(dark):
        assert printed[name] == root[name], (
            f"{name} prints as {printed[name]!r} but :root declares {root[name]!r}; "
            "the print block must copy :root verbatim (color-mix formulas included)"
        )


def test_scrim_solid_is_not_in_the_print_override():
    # Declared only in :root, never in the dark block, so it has nothing to undo.
    assert "--scrim-solid" not in _block(PRINT, r'\[data-theme="dark"\]')
```

- [ ] **Step 2: Prove the helper parses the real file correctly**

Before trusting the test, check the two tokens that a naive regex mangles:

```bash
C:/Users/krzys/.local/bin/uv.exe run python -c "import tests.test_print_tokens_css as t; r = t._block(t.SCREEN, r'^:root'); print(repr(r['--surface-overlay'])); print('--scrim-solid' in r)"
```
(One line — the repo's primary shell is PowerShell, where `\` is not a line continuation.)
Expected: `'rgba(30,28,24,0.45)'` and `True`. If `--surface-overlay` comes back as prose, the
comment-stripping pass is missing and every later assertion is meaningless.

- [ ] **Step 3: Run the test and watch it fail**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v`
Expected: **3 failed** - all three, not one. With no `@media print` in the file, `PRINT` is
the empty string, so `test_print_block_exists_...` fails on its own message while the other
two fail inside `_block(PRINT, ...)` with `no block matching`. Three failures here is the
correct red phase, not a sign the new file is broken.

- [ ] **Step 4: Append the print block to `tokens.css`**

Append to the **end** of `core/static/core/css/tokens.css` (after the closing `}` of the dark block at line 111). Every value is `:root`'s, copied verbatim:

```css

/* ── Print: restore the light palette ──────────────────────────────────────
   A dark-theme student printing any page gets near-white text on white paper:
   browsers strip backgrounds by default, and --text-primary is #F2EFE9. This
   block restates EVERY token the [data-theme="dark"] block declares, using
   :root's declaration for each -- color-mix() formulas included, because dark
   mixes toward white and light toward black, so the formulas genuinely differ.

   Placement is load-bearing: :root and [data-theme="dark"] are both (0,1,0) and
   both match <html>, so this wins only by source order. Anywhere above the dark
   block (tokens.css:79) it is silently inert. Keep it last in the file.
   tests/test_print_tokens_css.py pins both the placement and every value. */
@media print {
  [data-theme="dark"] {
    /* brand lift — :root mixes toward black, the dark block toward white */
    --primary:        var(--brand-primary);
    --primary-hover:  color-mix(in srgb, var(--brand-primary) 88%, black);
    --primary-active: color-mix(in srgb, var(--brand-primary) 78%, black);
    --primary-subtle: color-mix(in srgb, var(--brand-primary) 16%, var(--surface-raised));
    --accent:         var(--brand-accent);
    --accent-hover:   color-mix(in srgb, var(--brand-accent) 88%, black);
    --accent-subtle:  color-mix(in srgb, var(--brand-accent) 18%, var(--surface-raised));

    /* surfaces / text / borders */
    --surface-base: #F4F1EA; --surface-raised: #FFFFFF; --surface-sunken: #FAF8F3;
    --surface-overlay: rgba(30,28,24,0.45);
    --scroll-edge: rgba(30,28,24,0.16);
    --text-primary: #1E1C18; --text-secondary: #5A544A; --text-tertiary: #8A8477;
    --text-inverse: #FBF9F4;
    --border-subtle: #EDE8DE; --border-default: #E7E1D6; --border-strong: #D6CFC1;

    /* semantic */
    --success: #5A7D3C; --success-subtle: #E3ECD7;
    --warning: #B8811F; --warning-subtle: #F4E8CD;
    --danger:  #A8392E; --danger-subtle:  #F2D9D5;

    /* Author-selectable body-text colours. Easy to miss and the most visible
       omission: without these a lesson using coloured text still prints
       near-white-on-white, which is the exact defect this block exists to fix. */
    --tc-red: #B2372A; --tc-blue: #1F61AD; --tc-green: #3F6B24; --tc-orange: #8A5514;

    --shadow-xs: 0 1px 2px rgba(30,28,24,.06);
    --shadow-sm: 0 2px 6px rgba(30,28,24,.08);
    --shadow-md: 0 6px 16px rgba(30,28,24,.10);
    --shadow-lg: 0 16px 40px rgba(30,28,24,.14);
  }
}
```

- [ ] **Step 5: Run the parity test and lint — both must pass**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v`
Expected: 3 passed.

Format and lint the new test now, rather than deferring — an E501 found three tasks later means
re-opening a committed file, and **`ruff format --check` is a CI gate** (`.github/workflows/ci.yml:21`)
that no other step here runs:

```
C:/Users/krzys/.local/bin/uv.exe run ruff format tests/test_print_tokens_css.py
C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/test_print_tokens_css.py
C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/test_print_tokens_css.py
```
Run `ruff format` (no flag) **first** so it fixes wrapping, then `--check` to confirm. Hand-wrapped
code that merely fits in 88 columns is not necessarily what ruff format produces.

- [ ] **Step 6: Run the test that this change breaks, and confirm it breaks**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_colour_map_drift.py -v`
Expected: FAIL — `expected 4 slots x 2 themes in tokens.css, found 12`.

This is not a regression. `test_colour_map_drift.py:50–58` scans the **whole file** for `--tc-{slot}` and asserts `seen == 8`; the print block legitimately adds a third occurrence set.

- [ ] **Step 7: Update the count in `tests/test_colour_map_drift.py`**

Change the final assertion (line 58) from:

```python
    assert seen == 8, f"expected 4 slots x 2 themes in tokens.css, found {seen}"
```

to:

```python
    # 4 slots x 3 occurrence sets: :root, [data-theme="dark"], and the
    # @media print override that restates the light values for printing.
    assert seen == 12, f"expected 4 slots x 3 blocks in tokens.css, found {seen}"
```

Do **not** narrow the regex to dodge the count. Scanning every occurrence is what makes this test catch a drifted value anywhere in the file — including in the new block, whose values must map to the same slots.

- [ ] **Step 8: Run it and confirm green**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_colour_map_drift.py -v`
Expected: PASS. The per-value `SLOTS.get(normalise_colour(value)) == slot` assertion inside the loop passes untouched, because the print block restates `:root`'s values, which already map correctly.

- [ ] **Step 9: Run the other tests that read `tokens.css`, to prove appending is safe**

Run:
```
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_text_colour_css.py \
  tests/test_border_contrast_css.py tests/test_imagezoom_render.py tests/test_htmlsandbox.py
```
Expected: all pass. They locate blocks with first-match `re.search`, so a block appended at the end is invisible to them. If any fails, stop — the append point is wrong.

- [ ] **Step 10: Verify the append kept CRLF, then commit**

Run: `git diff --stat -- core/static/core/css/tokens.css`
Expected: a small insertion count. If the stat shows the whole file rewritten, the append flipped
the line endings — restore and re-append preserving CRLF.

```bash
git add core/static/core/css/tokens.css tests/test_print_tokens_css.py tests/test_colour_map_drift.py
git commit -m "fix(print): restore the light palette when printing in dark theme

A dark-theme student printing any page got near-white text on white paper:
browsers strip backgrounds and --text-primary is #F2EFE9. An @media print
block at the end of tokens.css restates all 33 dark-declared tokens with
:root's values, color-mix formulas included.

test_colour_map_drift counts --tc-* across the whole file, so its expected
count moves 8 -> 12. The regex is deliberately NOT narrowed: scanning every
occurrence is what makes it catch a drifted value in the new block too."
```

---

### Task 2: Callout accents in `courses.css`

**Files:**
- Modify: `courses/static/courses/css/courses.css` (append at end)
- Modify: `tests/test_print_tokens_css.py` (add **two** tests: the callout parity check and the
  repo-wide sweep the spec requires)

**Interfaces:**
- Consumes: Task 1's `tokens.css` print block (independent, but the same defect class).
- Produces: an `@media print` block at the end of `courses.css` restating the five `--callout-accent` values.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_print_tokens_css.py`:

```python
COURSES_CSS = (
    Path(__file__).resolve().parent.parent / "courses/static/courses/css/courses.css"
).read_text(encoding="utf-8")

CALLOUT_KINDS = ("example", "note", "tip", "warning", "task")


def _callout_accents(source):
    """{kind: value} for every .callout--KIND { --callout-accent: … } in `source`."""
    return {
        kind: value.strip()
        for kind, value in re.findall(
            r"\.callout--([a-z]+)\s*\{\s*--callout-accent:\s*([^;]+);", source
        )
    }


def test_print_restates_every_dark_callout_accent_with_the_light_value():
    """--callout-accent is declared in courses.css, a LATER sheet at (0,2,0), so
    tokens.css's print block cannot reach it. Without its own print block a
    dark-theme lesson with callouts prints #7db0f7 headings on white (2.23:1)."""
    # Whitespace-exact by necessity, and unique in courses.css today (checked
    # against all 9 existing @media print blocks). If a reformat ever breaks it,
    # the failure reads "no @media print block" rather than "wrong value" -- so
    # check the marker before believing that message.
    marker = '@media print {\n  [data-theme="dark"]'
    screen, sep, printed = COURSES_CSS.partition(marker)
    assert sep, (
        "courses.css must have an @media print block scoped to [data-theme=dark]"
    )

    # Light values live on the bare modifier classes; dark ones on the
    # [data-theme="dark"] .callout--KIND rules. Split the screen half on the
    # dark selector so the two are never confused.
    light_half, _d, dark_half = screen.partition('[data-theme="dark"] .callout--')
    light = _callout_accents(light_half)
    print_side = _callout_accents(printed)

    for kind in CALLOUT_KINDS:
        assert kind in print_side, (
            f".callout--{kind} has a dark accent but no print override; a dark-theme "
            "printout keeps the light-on-white tint"
        )
        assert print_side[kind] == light[kind], (
            f"print .callout--{kind} is {print_side[kind]!r} but the light rule "
            f"declares {light[kind]!r}; the source is the light-theme declaration of "
            "the same selector, NOT :root (--callout-accent is never declared there)"
        )
```

Also append the repo-wide sweep, which the spec requires so a **new** unclassified dark rule
cannot appear unnoticed:

```python
def test_every_dark_rule_in_a_shipped_stylesheet_is_classified():
    """A new [data-theme="dark"] rule must not slip in unnoticed: it either needs a
    print counterpart or a recorded reason it does not.

    Deliberately limited to COLUMN-0 rules. error.css:50's dark rule is indented
    inside a media query and is not matched; that is accepted, because dropping the
    anchor would also match the prose mentions in notes.css:17 and tags.css:2.
    """
    root = Path(__file__).resolve().parent.parent
    covered = {  # has a print counterpart
        "core/static/core/css/tokens.css",
        "courses/static/courses/css/courses.css",
    }
    excluded = {  # deliberately no print counterpart, reason recorded
        # Editor chrome; never on a page this feature prints.
        "courses/static/courses/css/editor.css",
        # tags.css IS loaded by lesson_unit.html:36, but .tag-delete-confirm is
        # built only by wireDeleteConfirm() (tags.js:103,108) from
        # .tag-section__manage delete links, which exist only in
        # _tag_section.html -> my_tags.html. The element never reaches a lesson.
        "tags/static/tags/css/tags.css",
    }
    found = set()
    for css in root.glob("*/static/**/*.css"):
        if ".venv" in css.parts or "staticfiles" in css.parts:
            continue
        text = css.read_text(encoding="utf-8")
        if re.search(r'^\[data-theme="dark"\]', text, re.M):
            found.add(css.relative_to(root).as_posix())
    unclassified = found - covered - excluded
    assert not unclassified, (
        f"unclassified [data-theme=\"dark\"] rule(s): {sorted(unclassified)}. "
        "Add a print counterpart, or record why one is not needed."
    )
```

- [ ] **Step 2: Run both and watch them fail**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v`
Expected: the callout test FAILS with `courses.css must have an @media print block scoped to
[data-theme=dark]`. The sweep test should already PASS (all four found files are classified) —
it is a tripwire for future rules, not for this change.

- [ ] **Step 3: Append the block to `courses.css`**

Append at the **end** of `courses/static/courses/css/courses.css`:

```css

/* ── Print: callout accents ────────────────────────────────────────────────
   courses.css:2010-2014 declares dark-only --callout-accent values, in a sheet
   loaded AFTER tokens.css and at (0,2,0), so tokens.css's print override cannot
   reach them. Without this a dark-theme lesson prints its callout headings and
   rails at #7db0f7 (2.23:1) or #e8b761 on white.

   The value source is the LIGHT declaration of the same selector
   (courses.css:2004-2008), not :root -- --callout-accent is never declared on
   :root at all. tests/test_print_tokens_css.py pins each pair. */
@media print {
  [data-theme="dark"] .callout--example { --callout-accent: #2563c9; }
  [data-theme="dark"] .callout--note    { --callout-accent: #55606b; }
  [data-theme="dark"] .callout--tip     { --callout-accent: #1f8a52; }
  [data-theme="dark"] .callout--warning { --callout-accent: #b06f0f; }
  [data-theme="dark"] .callout--task    { --callout-accent: #a8318f; }
}
```

- [ ] **Step 4: Run the tests — all must pass**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v`
Expected: **5 passed** (3 from Task 1, plus the callout parity check and the sweep).

Run: `C:/Users/krzys/.local/bin/uv.exe run ruff format tests/ && \
  C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/ && \
  C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/`
Expected: clean.

- [ ] **Step 5: Run the other tests that read `courses.css`, and check CRLF**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_tabs_partial.py tests/test_table_css.py`
Expected: all pass.

Run: `git diff --stat -- courses/static/courses/css/courses.css`
Expected: a small insertion count, not a whole-file rewrite.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_print_tokens_css.py
git commit -m "fix(print): restore light callout accents when printing in dark theme

--callout-accent is declared dark-only in courses.css:2010-2014, a later sheet
at (0,2,0), so the tokens.css print override cannot reach it. A dark-theme
lesson with callouts printed its headings at 2.23:1 on white."
```

---

### Task 3: Slideshow print reveal in `courses.css`

**Files:**
- Modify: `courses/static/courses/css/courses.css` (append at end, after Task 2's block)
- Modify: `tests/test_print_tokens_css.py` (adds the two Step-2 checks)

**Interfaces:**
- Consumes: `COURSES_CSS`, defined in Task 2's Step 1 additions to the same test file.
- Produces: an `@media print` block revealing every `.slideshow-deck .slide`. Task 4's e2e rows 4 and 5 exercise it.

- [ ] **Step 1: Read the runtime DOM this block targets — do not skip**

`slideshow.js:49–56` **moves** every slide out of `[data-slideshow]` into a JS-built wrapper:

```
[data-slideshow] > .slideshow-deck > .slideshow-stage > .slide
                                   > .slideshow-bar     (footer, slideshow.js:95)
```

So the three server-side rules that hide slides — `courses.css:348`, the FOUC pre-hide at `:355` (0,5,1), and the `hidden` attribute — **stop matching once the deck is built**. `courses.css:361–363` says so in its own comment. **Any print rule written against `[data-slideshow] > .slide` is inert, and so is any mutant of it.** Write against `.slideshow-deck`.

- [ ] **Step 2: Add a source-level check for this block, and run it RED — before appending**

Without this, Task 3 would commit ~30 lines of CSS with no verification until Task 4; a typo'd
selector would surface two tasks later. This step comes **before** the append so the red phase is
real. Add to `tests/test_print_tokens_css.py`:

```python
SLIDESHOW_PRINT_REQUIRED = (
    ".slideshow-deck .slide[hidden]",
    "position: static !important",
    "opacity: 1 !important",
    "transition: none !important",
    ".slideshow-bar",
)


def test_slideshow_print_block_declares_the_load_bearing_rules():
    """Cheap tripwire, not a cascade proof: a rule can be present and still inert,
    which only the e2e A/B in Task 4 can catch. This exists so a typo or a dropped
    declaration fails in Task 3 rather than two tasks later."""
    marker = ".slideshow-deck {\n    overflow: visible"
    _screen, sep, printed = COURSES_CSS.partition(marker)
    assert sep, "courses.css must have a print block for the slideshow deck"
    block = sep + printed
    for needle in SLIDESHOW_PRINT_REQUIRED:
        assert needle in block, f"slideshow print block is missing {needle!r}"


def test_courses_css_braces_balance():
    """Green BEFORE the append too — courses.css already balances (559/559). This
    is a regression tripwire for a malformed hand-edit, not part of the red phase,
    and battery row 14 is what proves it can go red at all."""
    text = re.sub(r"/\*.*?\*/", "", COURSES_CSS, flags=re.DOTALL)
    assert text.count("{") == text.count("}"), (
        "unbalanced braces in courses.css — an appended block is malformed"
    )
```

Run it now — **before** the append in Step 3:

```
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v
```
Expected: `test_slideshow_print_block_declares_the_load_bearing_rules` **FAILS** with
"courses.css must have a print block for the slideshow deck". The brace-balance test passes
already — see the note in its docstring.

- [ ] **Step 3: Append the block to `courses.css`**

Append at the **end** of `courses/static/courses/css/courses.css`, after Task 2's block:

```css

/* ── Print: reveal every slideshow slide ───────────────────────────────────
   A multi-slide lesson printed only the ACTIVE slide. The carousel block at
   :1852 already carries this lesson in its own comment ("printing a carousel
   silently loses every slide but the current one"); the identical defect in
   slideshows was never fixed.

   Written against the POST-ENHANCEMENT DOM. slideshow.js moves slides into
   .slideshow-deck > .slideshow-stage, so [data-slideshow] > .slide matches
   nothing at runtime and a rule written that way would be inert.

   display:block alone is not enough: the slides are position:absolute inset:0
   inside a fixed-height clipping stage, so revealing them would just stack them
   invisibly on one spot. Mirrors the carousel precedent at :1868-1870 in full. */
@media print {
  .slideshow-deck {
    overflow: visible !important;
    /* Screen chrome for a widget paper does not have. */
    border: 0; border-radius: 0; box-shadow: none; background: none; margin-block: 0;
  }
  /* The stage also carries .scroll-y (app.css:1886, position:relative), which is
     why the position reset is needed at all. */
  .slideshow-stage { position: static !important; height: auto !important; }
  /* The stage's .scroll-y ::before/::after are position:absolute (app.css:1886-1892).
     Removing the stage's position:relative reparents them to the next positioned
     ancestor, so their boxes can land anywhere on the sheet. They are gradient
     shading for a scroller paper does not have -- drop them outright. */
  .slideshow-stage::before, .slideshow-stage::after { display: none !important; }
  .slideshow-deck .slide,
  .slideshow-deck .slide[hidden] {
    display: block !important; position: static !important;
    overflow: visible !important;
    /* opacity beats an INLINE style: slideshow.js:187 sets the OUTGOING slide to
       opacity 0 and holds it for FADE_MS=320 until settleHidden() at :191, during
       which that slide is not yet [hidden] and so is revealed by the rules above.
       (:180 sets the incoming slide to 0 too, but :186 restores it synchronously
       three statements later, so it is never observably transparent.)

       transition:none is required ALONGSIDE it, and winning the cascade is not
       enough without it: :393 puts `transition: opacity 320ms ease` on this very
       rule, so changing the computed value starts an ANIMATION rather than
       applying it, and the print snapshot samples mid-fade. The
       prefers-reduced-motion block at :398-400 is the precedent for this shape. */
    opacity: 1 !important; transition: none !important;
  }
  /* Prev/Next is meaningless ink once every slide prints -- same principle the
     carousel block applies to .tabs__cbar / .tabs__status at :1870. */
  .slideshow-bar { display: none !important; }
}
```

- [ ] **Step 4: Run the checks**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py -v`
Expected: **7 passed**.

Run: `C:/Users/krzys/.local/bin/uv.exe run ruff format tests/ && \
  C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/ && \
  C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/`
Expected: clean.

Run: `git diff --stat -- courses/static/courses/css/courses.css`
Expected: a small insertion count, not a whole-file rewrite (CRLF preserved).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_print_tokens_css.py
git commit -m "fix(print): print every slideshow slide, not just the active one

slideshow.js moves slides into a JS-built .slideshow-deck > .slideshow-stage,
so the three server-side hiding rules stop matching and no print reveal existed
-- a multi-slide lesson printed one slide. Mirrors the carousel precedent at
courses.css:1868-1870, including the stage/geometry reset that display:block
alone does not achieve, and transition:none, without which opacity:1 only
starts a 320ms animation the print snapshot samples mid-way."
```

---

### Task 4: e2e coverage and the falsification battery

**Files:**
- Create: `tests/test_e2e_print_foundations.py`

**Interfaces:**
- Consumes: Tasks 1–3's CSS blocks.
- Produces: five e2e assertions, each with a mutant proven to turn it RED.

- [ ] **Step 1: Write the e2e suite**

Create `tests/test_e2e_print_foundations.py`:

```python
"""Playwright e2e for the two pre-existing print defects.

Print media is entered with page.emulate_media(media="print"), which re-evaluates
CSS media queries. No JS lifecycle is involved -- this PR ships no JS.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os
import re

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _contrast_on_white(css_colour):
    """WCAG contrast ratio of a computed CSS colour against #FFFFFF.

    Asserting a RATIO is the point: on every mutant build below the wrong value
    is still non-white and non-transparent, so "the colour changed" or "is not
    white" would pass on the broken build.
    """
    nums = re.findall(r"[\d.]+", css_colour)
    r, g, b = (int(float(n)) for n in nums[:3])

    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return 1.05 / (lum + 0.05)


def _dark_lesson(slug, body_html=None):
    """A published lesson unit owned by a student whose STORED THEME is dark.

    The user's stored theme is what matters, never the libli_theme cookie:
    base.html:17-26 consults the cookie only when data-theme-pref is absent, so a
    cookie-based fixture silently does nothing and every assertion below would
    measure a LIGHT page -- passing on a build with the override deleted.
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import ContentNode
    from courses.models import Enrollment
    from courses.models import TextElement
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Printable",
        published=True,
    )
    if body_html:
        add_element(unit, TextElement.objects.create(body=body_html))
    # Explicit per-slug email: User.email is unique=True and the factory default
    # is shared, so two fixtures using the default would collide.
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    student.theme = "dark"
    student.save(update_fields=["theme"])
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, student


def _open_lesson(page, live_server, course, unit, student, wait_for):
    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(wait_for, state="attached")
    # A mis-wired fixture must fail loudly rather than measure a light page.
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"


@pytest.mark.django_db(transaction=True)
def test_dark_theme_body_text_prints_dark(page, live_server):
    """Row 1. Correct: --text-primary #1E1C18, 17.0:1. Mutant: #F2EFE9, 1.06:1."""
    course, unit, student = _dark_lesson(
        "e2e-print-dark", "<p>Body text on paper.</p>"
    )
    _open_lesson(page, live_server, course, unit, student, ".el--text p")

    page.emulate_media(media="print")
    colour = page.evaluate(
        "getComputedStyle(document.querySelector('.el--text p')).color"
    )
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"printed body text is {colour} = {ratio:.2f}:1 on white; the tokens.css "
        "@media print override is missing or sits above the dark block"
    )


@pytest.mark.django_db(transaction=True)
def test_dark_theme_author_text_colour_prints_dark(page, live_server):
    """Row 2. Correct: --tc-red #B2372A, 6.05:1. Mutant: #EA8A82, 2.48:1.

    Measures the REAL painted element. `.tc-red { color: var(--tc-red) }`
    (courses.css:1290) is the rule that paints author-coloured text, and
    sanitize_html preserves the class (courses/tests/test_sanitize_colour.py).
    Reading the token off <html> with a synthetic probe would leave that render
    path untested.
    """
    course, unit, student = _dark_lesson(
        "e2e-print-tc", '<p>Warning: <span class="tc-red">do not divide</span>.</p>'
    )
    _open_lesson(page, live_server, course, unit, student, ".tc-red")

    page.emulate_media(media="print")
    colour = page.evaluate(
        "getComputedStyle(document.querySelector('.tc-red')).color"
    )
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"author-coloured text prints {colour} = {ratio:.2f}:1 on white; the "
        "--tc-* group is missing from the print override"
    )


@pytest.mark.django_db(transaction=True)
def test_dark_theme_callout_heading_prints_dark(page, live_server):
    """Row 3. Correct: #2563c9, 5.67:1. Mutant: #7db0f7, 2.23:1.

    `.callout__heading` carries `color: var(--callout-accent)` (courses.css:1966),
    so this reads the painted heading directly.
    """
    from courses.models import CalloutElement
    from tests.factories import add_element

    course, unit, student = _dark_lesson("e2e-print-callout")
    add_element(
        unit,
        CalloutElement.objects.create(
            kind="example", heading="Worked", body="<p>x</p>"
        ),
    )
    _open_lesson(page, live_server, course, unit, student, ".callout__heading")

    page.emulate_media(media="print")
    colour = page.evaluate(
        "getComputedStyle(document.querySelector('.callout__heading')).color"
    )
    ratio = _contrast_on_white(colour)
    assert ratio >= 4.5, (
        f"callout heading prints {colour} = {ratio:.2f}:1 on white; the courses.css "
        "--callout-accent print block is missing"
    )


def _slideshow_lesson(slug):
    """A unit with two slides: text, slide break, text.

    Uses tests.factories.seed_slideshow_unit, which already builds a unit from a
    "t"/"brk"/"q" layout -- do not hand-roll the element creation. It goes through
    ContentNodeFactory, whose `published` default is False (migration 0057), so the
    flag must be set explicitly or the student cannot reach the unit.
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import make_verified_user
    from tests.factories import seed_slideshow_unit

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = seed_slideshow_unit(course, layout=["t", "brk", "t"])
    unit.published = True
    unit.save(update_fields=["published"])
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, student


@pytest.mark.django_db(transaction=True)
def test_every_slide_prints_stacked_in_flow(page, live_server):
    """Row 4.

    The discriminator is GEOMETRIC, not visibility. Under the "keep only
    display:block" mutant every slide is display:block, opacity 1, visible, with a
    non-zero box -- they all occupy the IDENTICAL rect inside the stage's fixed
    height. checkVisibility() and bounding_box() presence both pass on that
    mutant; only strictly increasing y separates them.
    """
    course, unit, student = _slideshow_lesson("e2e-print-deck")

    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    # The print rules target the post-enhancement DOM; entering print before the
    # deck exists leaves courses.css:355's FOUC pre-hide in charge and the test
    # would be RED on a correct build.
    page.wait_for_selector(".slideshow-deck", state="attached")

    page.emulate_media(media="print")
    ys = page.evaluate(
        """[...document.querySelectorAll('.slideshow-deck .slide')]
             .map(s => s.getBoundingClientRect().top)"""
    )
    assert len(ys) == 2, f"fixture should render 2 slides, got {len(ys)}"
    assert ys[1] > ys[0], (
        f"slides print stacked at identical y ({ys}); the deck/stage geometry reset "
        "is missing, so display:block alone leaves them absolutely positioned"
    )
    bar_visible = page.evaluate(
        """(() => { const b = document.querySelector('.slideshow-bar');
                    return b ? b.checkVisibility() : false; })()"""
    )
    assert not bar_visible, (
        "Prev/Next navigation printed; the .slideshow-bar hide is missing"
    )


@pytest.mark.django_db(transaction=True)
def test_mid_fade_slide_prints_opaque(page, live_server):
    """Row 5.

    ORDER IS LOAD-BEARING. The mid-fade state is injected on the SCREEN cascade
    and a style flush is forced, THEN print media is entered. Injecting after
    entering print means the inline 0 loses to opacity:1 !important immediately,
    the computed value never changes, no transition ever starts, and the
    `transition: none` mutant reads a solid 1 and stays GREEN.
    slideshow.js:184 (`void inn.offsetWidth; // force reflow so opacity
    transitions`) is the in-repo proof that the flush is required.
    """
    course, unit, student = _slideshow_lesson("e2e-print-fade")

    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".slideshow-deck", state="attached")

    page.evaluate(
        """(() => {
             const slide = document.querySelector('.slideshow-deck .slide[hidden]');
             slide.removeAttribute('hidden');
             slide.style.opacity = '0';
             // Tag the exact node, so the read below cannot drift to a different
             // slide if the fixture ever grows one -- a non-mutated slide carries
             // no inline opacity and would read a solid 1 on BOTH mutants.
             slide.setAttribute('data-probe', '1');
             void slide.offsetWidth;          // establish 0 as the before-change style
           })()"""
    )
    page.emulate_media(media="print")
    # A transition triggered by the media switch starts at the NEXT style/animation
    # frame. Reading before that frame can legitimately return the after-change
    # value 1, which would leave the `transition: none` mutant GREEN for a timing
    # reason. Wait two frames so a started transition is observably mid-flight.
    page.evaluate(
        "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )

    opacity = page.evaluate(
        "getComputedStyle(document.querySelector('[data-probe]')).opacity"
    )
    assert float(opacity) == 1.0, (
        f"a mid-fade slide prints at opacity {opacity}; either opacity:1 !important "
        "is missing (inline style wins) or transition:none is missing (the reveal "
        "only starts a 320ms animation the snapshot samples mid-way)"
    )
```

- [ ] **Step 2: Confirm the test-DB container is up**

Run: `docker ps --format "{{.Names}}" | grep libli-test-db`
Expected: `libli-test-db`. If absent, `docker compose -f docker-compose.test.yml up -d` and wait for healthy — otherwise the run looks hung for minutes.

- [ ] **Step 3: Run the e2e suite**

Run:
```
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_e2e_print_foundations.py -m e2e -v
```
Expected: 5 passed. `-m e2e` is mandatory; without it every test deselects and pytest exits 5.

Then format and lint:
```
C:/Users/krzys/.local/bin/uv.exe run ruff format tests/
C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/
C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/
```
Expected: clean. `ruff format --check` is a CI gate (`.github/workflows/ci.yml:21`).

**Grep the summary line.** pytest can exit 0 with failures present.

- [ ] **Step 4: Falsify every assertion — this is the real gate**

For each mutant below: apply it **by hand-editing the file**, run the named test, confirm **RED**,
then **edit the mutant back out by hand**. Never `git checkout` to revert — this repo has lost work
to that three times; see the project notes.

**There is deliberately no mutant for "the print locator silently resolves to the screen
block."** That failure is structurally impossible: `CSS.partition("@media print")` puts the
two blocks in **disjoint strings**, so `_block(PRINT, ...)` cannot reach the screen block by
any edit short of rewriting the partition itself -- at which point the test fails
unconditionally and distinguishes nothing. A mutant that always reddens proves as little as
one that never does.

**Use these exact commands.** Rows 1-9 and 10a target e2e tests; 10b and 11-14 target non-e2e:

```
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_e2e_print_foundations.py::<name> -m e2e -v
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_tokens_css.py::<name> -v
```

**`no tests ran` / exit 5 is NOT red.** Omitting `-m e2e` deselects every e2e test and exits 5 with
no failure, which reads exactly like a passing run. If a mutant produces that, the command was
wrong — re-run it, do not record the mutant as green or as red.

Read `git diff` after the battery and confirm it is **empty**. Note *why*: Tasks 1-3 are
committed by now, and `tests/test_e2e_print_foundations.py` is still **untracked** at this
point (it is committed in Step 7), so it never appears in `git diff` at all. An empty diff
therefore means "every mutant was reverted", which is what this check is for. Also run
`git status` and confirm the only untracked file is that e2e test.

| # | Mutant | Must turn RED |
|---|---|---|
| 1 | Delete the whole `@media print` block from `tokens.css` | `test_dark_theme_body_text_prints_dark` |
| 2 | Move the `tokens.css` print block **above** line 79 (before the dark block) | `test_dark_theme_body_text_prints_dark` |
| 3 | Delete the `--tc-red/-blue/-green/-orange` line from the print block | `test_dark_theme_author_text_colour_prints_dark` |
| 4 | Delete the `courses.css` `--callout-accent` print block | `test_dark_theme_callout_heading_prints_dark` |
| 5 | In the slideshow block, keep only `display: block !important` — remove the `position`/`height`/`overflow` resets | `test_every_slide_prints_stacked_in_flow` |
| 6 | Delete `.slideshow-bar { display: none !important; }` | `test_every_slide_prints_stacked_in_flow` |
| 7 | Delete `opacity: 1 !important` from the slide reveal | `test_mid_fade_slide_prints_opaque` |
| 8 | Delete `transition: none !important` from the slide reveal | `test_mid_fade_slide_prints_opaque` |
| 9 | Rewrite the slide reveal against `[data-slideshow] > .slide` instead of `.slideshow-deck .slide` | `test_every_slide_prints_stacked_in_flow` (proves the selector is not inert) |
| 10a | Delete the **entire** slideshow `@media print` block - *e2e command* | `test_every_slide_prints_stacked_in_flow` |
| 10b | The same mutant - *non-e2e command* | `test_slideshow_print_block_declares_the_load_bearing_rules` |
| 11 | Change one value in the `tokens.css` print block | `test_print_override_restates_every_dark_token_with_the_root_value` |
| 12 | Delete the `--primary*` group from the print block | same |
| 13 | Widen `_decls`'s value class from `[^;{}\n]+` to `[^;]+` (i.e. let it match newlines) | `test_print_override_restates_every_dark_token_with_the_root_value` — RED on `--surface-overlay`, which the regex then scrapes out of the `:root` comment at `tokens.css:44-48`. *Deleting the comment-strip line instead is a **dead** mutant: measured, it changes nothing, because the newline exclusion already does the whole job* |
| 14 | Delete one closing `}` from the appended slideshow block | `test_courses_css_braces_balance` — the only row that proves this tripwire can go red |

If any mutant leaves its test GREEN, the assertion is not measuring what it claims. Fix the assertion, not the mutant.

- [ ] **Step 5: Full-suite gate**

`tokens.css` is a global path, so the affected-tests selection is the whole suite. Run it:

Run:
```
C:/Users/krzys/.local/bin/uv.exe run pytest
C:/Users/krzys/.local/bin/uv.exe run pytest -m e2e
```
Expected: green. **Grep both summary lines** — no `-q` here, deliberately: `addopts` already
supplies one, and a second would suppress the summary this step exists to read.

- [ ] **Step 6: Manual print-preview check**

`break-inside` and page-level appearance cannot be observed by `emulate_media`, which does not paginate. Open a multi-slide lesson with a callout in the browser, in **both light and dark theme**, and use the browser's print preview. Confirm: every slide appears, text is legible, the callout heading is readable, no Prev/Next bar.

- [ ] **Step 7: Commit**

```bash
git add tests/test_e2e_print_foundations.py
git commit -m "test(print): e2e coverage for the dark-theme and slideshow print fixes

Five assertions, each falsified against a named mutant. Contrast is asserted as
a RATIO because every mutant value is still non-white -- a 'colour changed'
predicate would pass on the broken build. The slide row's discriminator is
geometric (strictly increasing y), because under the display:block-only mutant
every slide is visible with a non-zero box at the IDENTICAL rect."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 dark theme override, placement, full token set, color-mix rule, `--scrim-solid` exclusion | Task 1 |
| §1 `test_colour_map_drift` collision | Task 1, Steps 6–8 |
| §2 `--callout-accent`, light-declaration-of-same-selector contract | Task 2 |
| §3 slideshow post-enhancement DOM, geometry reset, `opacity`, `transition`, `.slideshow-bar` | Task 3 |
| Testing rows 1–5 | Task 4, Step 1 |
| Token-parity test + structural extraction contract | Task 1 Step 1, Task 2 Step 1 |
| Repo-wide `[data-theme="dark"]` sweep dispositions | Task 2, Step 1 |
| Manual print-preview check | Task 4, Step 6 |
| Falsification battery | Task 4, Step 4 |

**Gap found and closed:** the spec requires the repo-wide `[data-theme="dark"]` sweep so a
*new* unclassified rule fails the suite. It is implemented as
`test_every_dark_rule_in_a_shipped_stylesheet_is_classified` in **Task 2, Step 1** — the source
lives there and only there, so an implementer working task-by-task cannot miss it and cannot
copy a stale second version from this appendix.

**Placeholder scan:** none — every step carries the literal file content or command.

**Type consistency:** `_decls`, `_block`, `_callout_accents`, `_contrast_on_white`, `_dark_lesson`, `_open_lesson`, `_slideshow_lesson`, `_login` are each defined once and used with matching signatures. `CALLOUT_KINDS` matches `CalloutElement.Kind` values (`example`, `note`, `tip`, `warning`, `task` — note `warning`'s label is "Important" but its stored value is `warning`).
