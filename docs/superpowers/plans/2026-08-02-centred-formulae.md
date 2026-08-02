# Centred Formulae Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a display-math formula split across sibling *aligned* blocks (`class="ta-center"` on every line) reflow, preserving the alignment on the merged result.

**Architecture:** `courses/static/courses/js/math_reflow.js` gains `alignToken(el)` (`""` / one token / `null`), a five-kind partition classifier, a run *signature* — the `(alignToken, tagName)` pair — and a second rewrite branch that reuses the first covered block as a wrapper instead of hoisting content into the parent. Unsigned runs keep today's code path byte-for-byte, because that is the path the six real `</p><p>` repairs travel.

**Tech Stack:** Vanilla ES5-style browser JS (no build step), Django templates, pytest + pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-08-02-centred-formulae-design.md` — read it before Task 2. Every non-obvious rule has a recorded "why", usually with a measurement, and the falsification table went through six corrections before it stopped being vacuous.

## Global Constraints

- **Render-only.** No save path changes, no model changes, no migrations, no management commands.
- **Do not touch `findEndOfMath` or `findSpans`.** They are a pinned port of auto-render's `splitAtDelimiters`; this slice has no reason to go near them.
- **Tooling:** `ruff`, `pytest` and `python` are NOT on PATH — always `uv run <tool>`. Run all commands from the worktree root `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/centred-formulae`.
- **e2e is opt-in and the MARKER selects, not the filename.** `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`. Omitting `-m e2e` silently deselects everything and exits 5, which reads like a pass. Both math-reflow test files already declare `pytestmark` and the session-scoped `DJANGO_ALLOW_ASYNC_UNSAFE` autouse fixture — keep both.
- **Doubled `-q` hides the verdict.** `addopts` already carries `-q`; adding another stacks to quiet-2 and prints no pass/fail line. Pass `--verbosity=0` when you want the summary.
- **Never background a pytest run.** A backgrounded run in this repo orphans a Postgres connection and the next run dies with `DuplicateDatabase`. Foreground only.
- **Do not run the full suite during tasks 1–5.** It exceeds the tool timeout. Task 6 owns it.
- **Browser JS style:** IIFE, `"use strict"`, `var`, no arrow functions, no `let`/`const` — match the surrounding file.
- **Ruff:** the repo selects `["E","F","I","UP","B","S"]`; `UP031` forbids `"…%s…" % x`, `E741` forbids `l` as a name, `E501` caps lines at 88. Lint every Python file you touch before committing.
- **Baseline:** `master` at `671c57f0`; full non-e2e **4566 passed**; `tests/test_e2e_math_reflow_dom.py` collects **66**; `tests/test_e2e_math_reflow.py` collects 11.

---

### Task 1: Classifier and signature-aware partition — no behaviour change

Lands the riskiest shared change (the run-partition loop, which every merge flows through) with the attribute test **not yet widened**, so no block can carry an align token and every run's signature is `""`. The deliverable is therefore *provable*: all 66 DOM cases and all 11 page cases stay green.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`

**Interfaces:**
- Produces: `alignToken(el)` → `""` | `"ta-left"` | `"ta-center"` | `"ta-right"` | `null`; `classifyChild(node, extraSelector)` → `"WS_TEXT"|"TEXT"|"BR"|"BLOCK"|"BARRIER"`; `runs[r]` becomes `{indices, token, tag, sawTextOrBr}` instead of a bare index array.
- Consumes: existing `isIgnored`, `isBareBr`, `isMergeableBlock`.

- [ ] **Step 1: Add `alignToken` above `isBareBr`**

Insert immediately after `noEffectiveAttributes` (which stays exactly as it is — `isBareBr` still uses it):

```js
  // The three values courses/sanitize.py's ALIGN_CLASS_VALUES permits on a block.
  var ALIGN_TOKENS = { "ta-left": true, "ta-center": true, "ta-right": true };

  // "" = no align class; one of the three = exactly one; null = INELIGIBLE (two or
  // more align tokens, or any token outside the three). nh3 filters class values
  // token-wise, so <p class="ta-center ta-left"> survives sanitising with BOTH
  // tokens -- measured against this repo's real config -- and has to be decided
  // rather than assumed away.
  //
  // Parsed as a token SET, never as the raw attribute string, so class=" ta-center "
  // and class="ta-center" agree. One deliberate side effect: class=" " yields an
  // empty set and therefore "", where noEffectiveAttributes (value === "") made it a
  // barrier. A whitespace-only class has no rendering effect, so the widening is
  // harmless; it is pinned by a test rather than left to be rediscovered.
  function alignToken(el) {
    var raw = el.getAttribute("class");
    if (raw === null) return "";
    var parts = raw.split(/\s+/);
    var found = "";
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      if (!ALIGN_TOKENS[parts[i]]) return null;
      if (found) return null;
      found = parts[i];
    }
    return found;
  }
```

- [ ] **Step 2: Add `classifyChild` immediately after `isMergeable`**

```js
  // Five kinds, because the partition now needs more than isMergeable's single
  // boolean: compatibility is pairwise, and WS_TEXT / TEXT / BR / BLOCK each behave
  // differently when they meet a signed run.
  //
  // The leading isIgnored test is load-bearing, and specifically for BR: a bare <br>
  // is classified via isBareBr and never reaches isMergeableBlock, so this guard is
  // the ONLY thing keeping an ignored <br> out of a run. isMergeable used to provide
  // it at its line-169 check; this function replaces isMergeable's only call site.
  function classifyChild(node, extraSelector) {
    if (node.nodeType === 3) return /\S/.test(node.data) ? "TEXT" : "WS_TEXT";
    if (node.nodeType !== 1) return "BARRIER";
    if (isIgnored(node, extraSelector)) return "BARRIER";
    if (isBareBr(node)) return "BR";
    if (isMergeableBlock(node, extraSelector)) return "BLOCK";
    return "BARRIER";
  }
```

- [ ] **Step 3: Replace the partition loop in `mergeChildren`**

Replace exactly this block:

```js
    var runs = [];
    var current = [];
    var i;
    for (i = 0; i < children.length; i++) {
      if (isMergeable(children[i], extraSelector)) current.push(i);
      else { if (current.length) runs.push(current); current = []; }
    }
    if (current.length) runs.push(current);
```

with:

```js
    // A run now carries a SIGNATURE: the (alignToken, tagName) pair of its first
    // BLOCK member. `token === null` means not yet established; `""` means
    // established-unsigned; a non-empty string means signed. Membership rules M1-M5
    // are spelled out in the spec's Architecture section.
    var runs = [];
    var current = null;
    var i;

    function endRun() {
      if (current && current.indices.length) runs.push(current);
      current = null;
    }

    function newRun(index, token, tag, sawTextOrBr) {
      return { indices: [index], token: token, tag: tag, sawTextOrBr: sawTextOrBr };
    }

    for (i = 0; i < children.length; i++) {
      var kind = classifyChild(children[i], extraSelector);
      if (kind === "BARRIER") { endRun(); continue; }
      if (!current) {
        current = { indices: [], token: null, tag: null, sawTextOrBr: false };
      }

      if (kind === "WS_TEXT") {
        // M4: transparent. Never establishes a signature, never ends a run. nh3
        // preserves inter-tag newlines and the imported corpus has 505 of them
        // between sibling divs, so treating these as breaks would make the whole
        // feature a no-op on real content while every fixture stayed green.
        current.indices.push(i);
        continue;
      }

      if (kind === "TEXT" || kind === "BR") {
        if (current.token) {
          // M3: ends a signed run AND becomes the first member of a new one -- it is
          // not excluded from every run. Excluding it would regress a shape that
          // merges on master: <div class="ta-center">x</div>\[a<div>b\]</div>.
          endRun();
          current = newRun(i, null, null, true);
        } else {
          current.indices.push(i);
          current.sawTextOrBr = true;
        }
        continue;
      }

      var tok = alignToken(children[i]);
      var tag = children[i].tagName;
      if (current.token === null) {
        if (tok !== "" && current.sawTextOrBr) {
          // M5: a SIGNED block arriving into a run that already accumulated TEXT/BR
          // members breaks it rather than signing it retroactively. WS_TEXT is
          // deliberately NOT in that condition -- a run holding only transparent
          // whitespace stays joinable, which is the corpus shape.
          endRun();
          current = newRun(i, tok, tag, false);
        } else {
          current.indices.push(i);                  // M1: establishes the signature
          current.token = tok;
          current.tag = tag;
        }
      } else {
        // M2: compatible iff both unsigned (tag irrelevant, so DIV/P may mix), or
        // same token AND same tag.
        var ok = current.token === ""
          ? tok === ""
          : (tok === current.token && tag === current.tag);
        if (ok) current.indices.push(i);
        else { endRun(); current = newRun(i, tok, tag, false); }
      }
    }
    endRun();
```

- [ ] **Step 4: Adapt the rewrite loop's header to the new run shape**

Replace:

```js
      var indices = runs[r];
```

with:

```js
      var indices = runs[r].indices;
      var runToken = runs[r].token;
```

`runToken` is unused in this task (every run's token is `""` or `null` while the attribute test is unwidened) — Task 2 consumes it. Leave it assigned; a `var` that a later task reads is not dead code in a plan executed in order.

- [ ] **Step 5: Delete `isMergeable`**

It is now referenced nowhere. Leaving a dead predicate behind invites a future reader to treat it as authoritative. Confirm before deleting:

```
grep -n "isMergeable\b" courses/static/courses/js/math_reflow.js
```
Expected after the delete: only `isMergeableBlock` matches remain.

- [ ] **Step 6: Run both math-reflow files and confirm NO behaviour change**

```
uv run pytest tests/test_e2e_math_reflow_dom.py tests/test_e2e_math_reflow.py -m e2e --verbosity=0
```
Expected: **77 passed** (66 + 11), exactly as before the task. Any failure here is a real regression in the partition rewrite, not an expected consequence — this task is defined as behaviour-preserving.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/math_reflow.js
git commit -m "refactor(math-reflow): signature-aware run partition, no behaviour change"
```

---

### Task 2: Widen the attribute test and add the reuse rewrite

Turns the inert machinery on. After this task a centred formula merges and keeps its alignment.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py`

**Interfaces:**
- Consumes: `alignToken`, `classifyChild`, `runs[r].token` (Task 1).
- Produces: signed-run merging with wrapper reuse.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_e2e_math_reflow_dom.py`:

```python
def test_centred_siblings_merge_into_one_wrapper(page):
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_centred_paragraphs_merge_and_keep_the_p_tag(page):
    """Tag equality is load-bearing in the compatibility table, and the only other
    <p> case is a barrier — without this, restricting the reuse path to DIV would
    pass every other test."""
    out = _reflow_html(
        page,
        '<p class="ta-center">\\[a</p><p class="ta-center">b\\]</p>',
    )
    assert out == '<p class="ta-center">\\[a\nb\\]</p>'


@pytest.mark.parametrize("token", ["ta-left", "ta-right"])
def test_other_align_tokens_merge_too(page, token):
    """Nothing may be hardcoded to centre."""
    out = _reflow_html(
        page, f'<div class="{token}">\\[a</div><div class="{token}">b\\]</div>'
    )
    assert out == f'<div class="{token}">\\[a\nb\\]</div>'


def test_unsigned_mixed_tag_run_still_merges(page):
    """<p>…</p><div>…</div> is ordinary Chromium contenteditable output (courses.css
    :24-25): Enter emits a <div> while the first block may be a <p>. It is also the
    ONLY shape that distinguishes "tag equality when signed" from "tag equality
    always" — the </p><p> repairs that motivate the rule are same-tag."""
    assert _reflow_html(page, "<p>\\[a</p><div>b\\]</div>") == "\\[a\nb\\]"


def test_whitespace_between_centred_blocks_is_transparent(page):
    """The corpus shape: nh3 preserves inter-tag newlines, and scripts/lal_import/out
    has 505 of them between sibling divs. Anchored to the SIGNED shape deliberately —
    an unsigned whitespace fixture passes on master and under every mutant."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div>\n<div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_empty_centred_line_between_the_lines_collapses(page):
    """<div><br></div> is Chromium's empty line, and centring a multi-line selection
    aligns it too. It contributes zero characters to run.text, so it appears in
    `nodes` and in the group range but never in run.map — the index-based removal
    loop is what takes it out."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div>'
        '<div class="ta-center"><br></div>'
        '<div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_whitespace_only_class_merges(page):
    """alignToken parses a token SET, so class=" " yields "" and is mergeable, where
    noEffectiveAttributes (value === "") called it a barrier. Deliberate widening."""
    assert _reflow_html(page, '<div class=" ">\\[a</div><div class=" ">b\\]</div>') == (
        "\\[a\nb\\]"
    )


def test_partial_coverage_leaves_the_uncovered_block(page):
    out = _reflow_html(
        page,
        '<div class="ta-center">x</div>'
        '<div class="ta-center">\\[a</div>'
        '<div class="ta-center">b\\]</div>',
    )
    assert out == (
        '<div class="ta-center">x</div><div class="ta-center">\\[a\nb\\]</div>'
    )


def test_two_spans_in_one_signed_run_keep_the_boundary_newline(page):
    """Group 1's endOffset extends past the span to include the synthetic boundary
    newline mapping to child 1, so on the reuse path that newline lands INSIDE the
    first wrapper rather than staying a bare text node between the groups. It is
    deliberately not trimmed: dropping a synthetic newline is what glued author
    prose together in the predecessor's "tailhead" defect."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>'
        '<div class="ta-center">\\[c</div><div class="ta-center">d\\]</div>',
    )
    assert out == (
        '<div class="ta-center">\\[a\nb\\]\n</div>'
        '<div class="ta-center">\\[c\nd\\]</div>'
    )


def test_nested_signed_run_preserves_one_nesting_level(page):
    """The unsigned rewrite hoists content into the parent, so one nesting level
    disappears; the reuse path keeps the wrapper, so the level count is preserved.
    The wrapper MUST survive to carry the alignment — this is the price of the
    feature, and it is asserted so it stays a decision."""
    out = _reflow_html(
        page,
        '<div><div class="ta-center">\\[a</div>'
        '<div class="ta-center">b\\]</div></div>',
    )
    assert out == '<div><div class="ta-center">\\[a\nb\\]</div></div>'
```

- [ ] **Step 2: Run them and watch them fail**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: the 11 new cases FAIL (each returns the input unchanged, because a `ta-*` block is still a barrier), the existing 66 pass. `test_unsigned_mixed_tag_run_still_merges` and `test_whitespace_only_class_merges` are the exceptions — mixed-tag unsigned already passes on master, and `class=" "` fails until Step 3.

- [ ] **Step 3: Widen the attribute test**

In `isMergeableBlock`, replace:

```js
    if (!noEffectiveAttributes(node)) return false;
```

with:

```js
    if (!blockAttributesOk(node)) return false;
```

and add `blockAttributesOk` immediately after `alignToken`:

```js
  // The block-level attribute test. Differs from noEffectiveAttributes (which stays
  // as-is for isBareBr) in exactly one way: a `class` is judged by alignToken rather
  // than required to be empty. `style` must still be empty, and any other attribute
  // is still disqualifying.
  function blockAttributesOk(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      var attr = el.attributes[i];
      if (attr.name === "style" && attr.value === "") continue;
      if (attr.name === "class") continue;      // validity decided by alignToken
      return false;
    }
    return alignToken(el) !== null;
  }
```

- [ ] **Step 4: Add the reuse branch to the rewrite**

Replace exactly this block at the end of the group loop:

```js
        var anchor = nodes[group.first];
        for (i = 0; i < replacement.length; i++) {
          element.insertBefore(replacement[i], anchor);
        }
        for (i = group.first; i <= group.last; i++) {
          if (nodes[i] && nodes[i].parentNode === element) {
            element.removeChild(nodes[i]);
          }
        }
```

with:

```js
        if (runToken) {
          // SIGNED run: reuse the first covered block as the wrapper so the align
          // class survives. run.map never holds a zero-character member (buildRun
          // skips whitespace-only text nodes), and in a signed run every non-BLOCK
          // member is exactly such a node -- so nodes[group.first] is always a block.
          //
          // The ORDER below is a fault-tolerance requirement, not an arbitrary
          // choice. Snapshot first: after the insert, the replacement nodes are
          // themselves children of the wrapper, so "the original children" is only
          // recoverable from a snapshot -- a `while (wrapper.firstChild) remove()`
          // reading empties the wrapper and loses the merged line. Insert before
          // removing: today's unsigned path inserts then removes, so a throw between
          // the loops leaves duplicated content, which is survivable; clearing first
          // would lose the line outright.
          var wrapper = nodes[group.first];
          var original = [].slice.call(wrapper.childNodes);
          for (i = 0; i < replacement.length; i++) {
            wrapper.appendChild(replacement[i]);
          }
          for (i = 0; i < original.length; i++) {
            // Removed unconditionally, NOT "those represented in the replacement": a
            // child contributing zero characters (a leading <br> whose newline
            // pushBlockText suppressed) is represented nowhere and must still go,
            // exactly as the unsigned path drops it by deleting the whole block.
            if (original[i].parentNode === wrapper) wrapper.removeChild(original[i]);
          }
          for (i = group.first + 1; i <= group.last; i++) {
            // first + 1, never first: removing the wrapper would delete the content
            // just placed in it.
            if (nodes[i] && nodes[i].parentNode === element) {
              element.removeChild(nodes[i]);
            }
          }
        } else {
          var anchor = nodes[group.first];
          for (i = 0; i < replacement.length; i++) {
            element.insertBefore(replacement[i], anchor);
          }
          for (i = group.first; i <= group.last; i++) {
            if (nodes[i] && nodes[i].parentNode === element) {
              element.removeChild(nodes[i]);
            }
          }
        }
```

- [ ] **Step 5: Run the tests and watch them pass**

```
uv run pytest tests/test_e2e_math_reflow_dom.py tests/test_e2e_math_reflow.py -m e2e --verbosity=0
```
Expected: **87 passed, 1 failed.** The single failure is `test_centred_display_math_is_not_reflowed` — the page-level test that deliberately pins the old limitation. That failure is the feature working; Task 5 inverts that test. Do not "fix" it by weakening the new behaviour, and do not invert it early — Task 5 owns it so the inversion lands with the stale docstrings and section header it belongs to.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format tests/test_e2e_math_reflow_dom.py && uv run ruff check tests/test_e2e_math_reflow_dom.py
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math-reflow): merge sibling blocks sharing an align class"
```

---

### Task 3: The barrier set and per-mutant falsification

The conservative rule is only real if something pins it. This task is where the feature earns its trust.

**Files:**
- Modify: `tests/test_e2e_math_reflow_dom.py`

**Interfaces:**
- Consumes: the merged behaviour from Task 2.

- [ ] **Step 1: Move the `ta-center` case out of the existing barrier test and add the new barrier cases**

In `test_barriers_are_not_merged_across`, delete this parametrize entry:

```python
        '<div class="ta-center">\\[x</div><div class="ta-center">y\\]</div>',
```

Deleting a barrier case weakens that test, so replace it with these, appended to the file:

```python
@pytest.mark.parametrize(
    "html",
    [
        # 1. signed + unsigned
        '<div class="ta-center">\\[a</div><div>b\\]</div>',
        # 2. two different tokens
        '<div class="ta-center">\\[a</div><div class="ta-right">b\\]</div>',
        # 3. same token, different tag
        '<p class="ta-center">\\[a</p><div class="ta-center">b\\]</div>',
        # 4. signed run interrupted by NON-whitespace text
        '<div class="ta-center">\\[a</div>stray<div class="ta-center">b\\]</div>',
        # 5. signed run interrupted by a bare <br>
        '<div class="ta-center">\\[a</div><br><div class="ta-center">b\\]</div>',
        # 6. ineligible multi-token class (nh3 keeps BOTH tokens -- measured)
        '<div class="ta-center ta-left">\\[a</div>'
        '<div class="ta-center ta-left">b\\]</div>',
        # 7. signed block holding an element child -- the child-shape check
        '<div class="ta-center">\\[a<em>x</em></div>'
        '<div class="ta-center">b\\]</div>',
    ],
)
def test_signed_barriers_are_not_merged_across(page, html):
    assert _reflow_html(page, html) == html


def test_ignored_tag_suppresses_a_signed_block(page):
    """Barrier 8. The root must be <section>, not <div>: reflow's root guard
    (`root.closest(extra)`) would make a <div> root pass for the wrong reason — the
    same trap test_caller_ignored_tags_are_unioned_in records."""
    html = (
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>'
    )
    page.set_content(f"<!DOCTYPE html><section id='root'>{html}</section>")
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r, {ignoredTags: ['div']});"
        "        return r.innerHTML; }"
    )
    assert out == html


def test_ignored_br_still_breaks_a_run(page):
    """Barrier 9 — the ONLY case that reaches the classifier's isIgnored guard. A
    bare <br> is classified via isBareBr and never reaches isMergeableBlock, so that
    guard is the sole thing keeping an ignored <br> out of a run; case 8's <div> is
    still caught by isMergeableBlock's own check. Deleting isMergeable removed the
    line that used to enforce this, so without this test the regression ships with
    every other case green."""
    html = "<div>\\[a</div><br><div>b\\]</div>"
    page.set_content(f"<!DOCTYPE html><section id='root'>{html}</section>")
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r, {ignoredTags: ['br']});"
        "        return r.innerHTML; }"
    )
    assert out == html


def test_text_after_a_signed_run_starts_a_new_run(page):
    """M3: a TEXT that ends a signed run becomes the first member of a NEW run
    rather than being excluded from every run. Excluding it regresses a shape that
    merges on master."""
    out = _reflow_html(
        page, '<div class="ta-center">x</div>\\[a<div>b\\]</div>'
    )
    assert out == '<div class="ta-center">x</div>\\[a\nb\\]'


def test_text_leading_a_signed_run_is_untouched(page):
    """M5's only coverage. An M5 violation moves the synthetic boundary newline
    INSIDE the wrapper — a single whitespace character, which a startswith/endswith
    assertion would not catch. Hence exact equality."""
    out = _reflow_html(
        page,
        'lead <div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == 'lead <div class="ta-center">\\[a\nb\\]</div>'


def test_text_trailing_a_signed_run_is_untouched(page):
    """Pinned by a DIFFERENT mutant from the leading case: here the run is already
    signed when the text arrives, so the text is ended by M3, not M5. Discriminating
    against "signed runs admit TEXT and BR members"."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div> trail',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div> trail'


def test_whitespace_leading_a_signed_run_does_not_break_it(page):
    """M5's WS_TEXT carve-out. REGRESSION GUARD ONLY — no mutant can redden it,
    because every reading of a leading WS_TEXT yields identical DOM. Listed here so
    its unfalsifiability is a recorded decision rather than an oversight."""
    out = _reflow_html(
        page,
        '\n<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '\n<div class="ta-center">\\[a\nb\\]</div>'


def test_centred_inline_align_comes_out_merged_and_promoted(page):
    """Phase 2 interaction. Uses align*, NOT cases: DISPLAY_ONLY_ENVS is ten exact
    literals and `cases` is deliberately not among them, so a \\(\\begin{cases}…\\)
    span merges but never promotes."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\(\\begin{align*}a&amp;=1</div>'
        '<div class="ta-center">\\end{align*}\\)</div>',
    )
    assert out.startswith('<div class="ta-center">\\[')
    assert out.endswith('\\]</div>')
```

- [ ] **Step 2: Run and watch the new cases pass**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: all pass. If barrier 9 fails, the classifier's `isIgnored` guard is missing — fix the guard, not the test.

- [ ] **Step 3: Falsify every new test against its own mutant**

"Revert the change" is **vacuous** for barriers (with the feature reverted every `ta-*` block is already a barrier, so all of them stay green). Apply each mutant below, record the RED output, then restore and re-confirm GREEN. Six drafts of this table were wrong before it stopped being vacuous — verify each row rather than assuming it.

| test(s) | mutant |
|---|---|
| the 11 Task-2 happy-path cases (signed ones) | revert Task 2's Step 3 (`blockAttributesOk` → `noEffectiveAttributes`) |
| `test_unsigned_mixed_tag_run_still_merges` | in M2, require `tag === current.tag` even when `current.token === ""` |
| `test_whitespace_only_class_merges` | make `alignToken` compare the raw class string instead of a parsed token set |
| signed barriers 1–3 | in M2, always accept — a run adopts its first block's signature |
| signed barriers 4–5 | in M3, let `TEXT`/`BR` join a signed run instead of ending it |
| signed barrier 6 | make `alignToken` return the first token instead of `null` for multi-token |
| signed barrier 7 | delete the child-shape loop from `isMergeableBlock` |
| `test_ignored_tag_suppresses_a_signed_block` | delete **both** the classifier's `isIgnored` guard and `isMergeableBlock`'s own check — either alone is vacuous, since the other short-circuits the case |
| `test_ignored_br_still_breaks_a_run` | delete the classifier's `isIgnored` guard **only** — a single deletion suffices here, because the classifier routes a `<br>` to `BR` and never consults `isMergeableBlock` |
| `test_text_after_a_signed_run_starts_a_new_run` | in M3, drop the ended `TEXT` instead of starting a new run with it |
| `test_text_leading_a_signed_run_is_untouched` | delete M5 (a signed block joins a run already holding `TEXT`) |
| `test_text_trailing_a_signed_run_is_untouched` | in M3, let `TEXT`/`BR` join a signed run |
| `test_whitespace_between_centred_blocks_is_transparent` | in M4, let `WS_TEXT` end a signed run |
| `test_two_spans_in_one_signed_run_keep_the_boundary_newline` | trim a trailing synthetic newline from the wrapper |
| `test_whitespace_leading_a_signed_run_does_not_break_it` | **none — regression guard.** Record that no mutant exists. |

`test_nested_signed_run_preserves_one_nesting_level` documents behaviour; reverting Task 2 changes it, which is coverage enough.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff format tests/test_e2e_math_reflow_dom.py && uv run ruff check tests/test_e2e_math_reflow_dom.py
git add tests/test_e2e_math_reflow_dom.py
git commit -m "test(math-reflow): barrier set and per-mutant falsification for signed runs"
```

---

### Task 4: Idempotence

`renderMathInElement` runs repeatedly on the same DOM. This module has been non-idempotent twice, both times in code adjacent to this change, and both times the reasoning that it "obviously" converged was wrong.

**Files:**
- Modify: `tests/test_e2e_math_reflow_dom.py`

- [ ] **Step 1: Add the three signed idempotence fixtures**

```python
@pytest.mark.parametrize(
    "html",
    [
        # 1. LITERAL markup, not "a signed block with an intra-block <br>-split
        #    span". The trailing `prose \[a` AND the second signed block are what
        #    make the textFragment leaf guard fire -- the guard only executes from an
        #    enclosing merge's covered-but-unspanned range. Reduced to
        #    <div class="ta-center">\(x<br>y\)</div> both textFragment calls are
        #    empty, the outer span is a leaf skip, and the fixture stays green under
        #    its own mutant while still looking like it merged.
        '<div class="ta-center">\\(x<br>y\\) prose \\[a</div>'
        '<div class="ta-center">b\\]</div>',
        # 2. two spans with prose between the groups
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\] mid</div>'
        '<div class="ta-center">\\[c</div><div class="ta-center">d\\]</div>',
        # 3. the signed analogue of the map-vs-leaf discriminating shape recorded in
        #    math_reflow.js's rule-4 comment
        '<div class="ta-center">c<br>z$$x</div>'
        '<div class="ta-center">$$c<br><br>$$x<br> x$$c</div>',
    ],
)
def test_signed_reflow_is_idempotent(page, html):
    _page(page, html)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r); return [r.innerHTML === a, a]; }"
    )
    assert out[0], f"pass 2 diverged from pass 1: {out[1]!r}"
    # Positive precondition: without this a no-op satisfies the test trivially,
    # which is exactly how a suppress-the-merge mutant would pass.
    assert out[1] != html, "pass 1 did not change the markup"
```

- [ ] **Step 2: Verify fixture 3 actually discriminates**

The recorded shape was measured against the *unsigned* rewrite, which hoists into the parent; the reuse path leaves a different node layout going into pass 2. Apply the map-based rule-4 mutant (`if (first !== last) continue;` in place of the leaf comparison) and confirm fixture 3 goes RED. **If it does not, search for a shape that does and replace it** — keeping an unfalsifiable fixture here would defeat the task.

- [ ] **Step 3: Falsify fixtures 1 and 2**

Their mutant is different from fixture 3's: remove the `!run.leaf[i]` guard from `textFragment`, so an already-merged `\n` is re-split into `text` / `<br>` / `text`. Confirm RED for 1 and 2, then restore.

- [ ] **Step 4: Add the committed cross-product enumeration**

```python
_TEMPLATES = {
    "whole": '<{t}{c}>\\[a</{t}>{sep}<{t}{c}>b\\]</{t}>',
    "trailing": '<{t}{c}>\\[a</{t}>{sep}<{t}{c}>b\\] tail</{t}>',
    "intra_br": '<{t}{c}>\\[a<br>b\\]</{t}>{sep}<{t}{c}>c</{t}>',
}
_SEPARATORS = {"none": "", "ws": "\n", "br": "<br>", "text": "sep"}


@pytest.mark.parametrize("placement", sorted(_TEMPLATES))
@pytest.mark.parametrize("sep_name", sorted(_SEPARATORS))
@pytest.mark.parametrize("token", ["", "ta-center", "ta-right"])
@pytest.mark.parametrize("tag", ["div", "p"])
def test_idempotent_across_the_shape_cross_product(page, tag, token, sep_name, placement):
    """The merge-expected predicate is DATA, stated in the spec, not derived from the
    implementation's output — deriving it from what the code does would make the
    anti-vacuity assertion circular, which is the whole reason it exists."""
    cls = f' class="{token}"' if token else ""
    html = _TEMPLATES[placement].format(t=tag, c=cls, sep=_SEPARATORS[sep_name])
    merge_expected = (
        placement == "intra_br" or token == "" or sep_name in ("none", "ws")
    )

    _page(page, html)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r);"
        "        return [r.innerHTML === a, a, r.textContent]; }"
    )
    assert out[0], f"pass 2 diverged from pass 1: {out[1]!r}"

    # "All whitespace removed", NOT "normalised". A merge legitimately INTRODUCES
    # characters that were never in textContent -- buildRun's synthetic boundary
    # newlines -- so collapse-runs-to-one-space would redden every merging shape
    # against a correct implementation.
    def squash(s):
        return "".join(s.split())

    _page(page, html)
    before = page.evaluate("() => document.getElementById('root').textContent")
    assert squash(out[2]) == squash(before), "text loss"

    if merge_expected:
        assert out[1] != html, "expected a merge, markup unchanged"
```

- [ ] **Step 5: Run everything**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: all pass, including the 72 cross-product cells. If a cell disagrees with the predicate, **the predicate is the spec** — investigate the implementation before touching the table, and if you conclude the table is wrong, say so in your report rather than editing it silently.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format tests/test_e2e_math_reflow_dom.py && uv run ruff check tests/test_e2e_math_reflow_dom.py
git add tests/test_e2e_math_reflow_dom.py
git commit -m "test(math-reflow): idempotence fixtures and shape cross-product"
```

---

### Task 5: Invert the page-level pinning test and clear stale references

**Files:**
- Modify: `tests/test_e2e_math_reflow.py`
- Modify: `tests/test_e2e_math_reflow_dom.py`

- [ ] **Step 1: Invert the limitation test**

In `tests/test_e2e_math_reflow.py`, replace the section header

```python
# ---- Step 3: the named-limitation case ----------------------------------------
```

with

```python
# ---- Step 3: centred display math ---------------------------------------------
```

and replace `test_centred_display_math_is_not_reflowed` entirely with:

```python
def test_centred_display_math_is_reflowed(page, live_server):
    """The limitation PR #206 pinned deliberately, now closed. Every line div carries
    class="ta-center", so each was a barrier and the formula never reflowed; sibling
    blocks sharing an align token now merge into one wrapper that keeps the class."""
    unit = _open_pa_session(page, live_server, "mr_centred", "mr-centred")
    body = (
        '<div class="ta-center">\\[\\begin{align*}</div>'
        '<div class="ta-center">a&amp;=b\\\\</div>'
        '<div class="ta-center">\\end{align*}\\]</div>'
    )
    add_element(unit, TextElement.objects.create(body=body))

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text")
    assert page.locator(".el--text .katex").count() == 1
    assert page.locator(".katex-error").count() == 0
    html = page.locator(".el--text").inner_html()
    assert 'class="ta-center"' in html  # the alignment survived the merge
    assert "</div><div" not in html  # and the three lines became one block
```

- [ ] **Step 2: Fix both stale case counts**

Both are **already wrong on master** — `--collect-only` on the DOM file reports 66 while the recorded figures say 65 and 63 — so do not adjust them by this slice's delta. Measure:

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --collect-only -q | tail -3
```

Then set both to the measured number (they describe the same quantity and must end up equal):
- `tests/test_e2e_math_reflow.py` module docstring: "already proves the module's DOM mechanics in isolation (65 cases)"
- `tests/test_e2e_math_reflow_dom.py`, inside the `_allow_sync_orm_under_playwright` fixture docstring: "all 63 cases ERROR with SynchronousOnlyOperation"

- [ ] **Step 3: Retarget the stale `isMergeable` reference**

`tests/test_e2e_math_reflow_dom.py`, in `test_caller_ignored_tags_are_unioned_in`'s docstring, says "the divs merge unless extraSelector is threaded into `isMergeable`". Task 1 deleted that function. Rewrite the sentence to name `classifyChild` and `isMergeableBlock` instead.

- [ ] **Step 4: Run both files**

```
uv run pytest tests/test_e2e_math_reflow_dom.py tests/test_e2e_math_reflow.py -m e2e --verbosity=0
```
Expected: all pass, including the inverted test.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format tests/test_e2e_math_reflow.py tests/test_e2e_math_reflow_dom.py
uv run ruff check tests/test_e2e_math_reflow.py tests/test_e2e_math_reflow_dom.py
git add tests/test_e2e_math_reflow.py tests/test_e2e_math_reflow_dom.py
git commit -m "test(math-reflow): invert the centred-formula limitation test"
```

---

### Task 6: Definition of done

- [ ] **Step 1: Full non-e2e suite**

```
uv run pytest -n 4 --verbosity=0
```
Expected: **4566 passed**, unchanged — every test this slice adds is e2e. A higher number means an e2e file landed in the default run for want of a `pytestmark`.

- [ ] **Step 2: Full e2e suite**

Run in chunks; the whole suite exceeds the tool timeout even at `-n 4`:

```
uv run pytest -m e2e -n 4 --verbosity=0 $(ls tests/test_e2e_*.py | awk 'NR<=27' | tr '\n' ' ')
uv run pytest -m e2e -n 4 --verbosity=0 $(ls tests/test_e2e_*.py | awk 'NR>27 && NR<=40' | tr '\n' ' ')
uv run pytest -m e2e -n 4 --verbosity=0 $(ls tests/test_e2e_*.py | awk 'NR>40 && NR<=54' | tr '\n' ' ')
uv run pytest -m e2e -n 4 --verbosity=0 $(ls tests/test_e2e_*.py | awk 'NR>54 && NR<=68' | tr '\n' ' ')
uv run pytest -m e2e -n 4 --verbosity=0 $(ls tests/test_e2e_*.py | awk 'NR>68' | tr '\n' ' ')
```

Two failures are known pre-existing parallel-load flakes and are **not** this slice's:
`test_e2e_builder_filter.py::test_collapse_everything_filter_clear_comes_back_EMPTY` and
`test_e2e_inline_rename.py::test_tabbing_across_a_row_issues_one_panel_fetch`. Re-run each in isolation to confirm it passes; if either fails in isolation too, that IS this slice's problem.

- [ ] **Step 3: Lint and format**

```
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 4: The required visual verification**

Render a centred three-line formula in the browser, **light and dark**, before and after, and record the measured paragraph spacing. Three centred line divs currently receive `margin-top: var(--space-3)` between them from the adjacent-sibling rule at `courses/static/courses/css/courses.css:27-32`; collapsing them to one block removes those gaps and substitutes KaTeX's own `.katex-display { margin: 1em 0 }`. That is the intended outcome, but it is a real spacing change and no automated test covers it. Save the four screenshots outside the repo and attach them to the PR.

- [ ] **Step 5: Confirm no regression against real data**

The six records the predecessor repaired (`CalloutElement` 86, `ChoiceQuestionElement` 218/226/227, `ShortNumericQuestionElement` 76/77) are all unsigned `</p><p>` shapes and must still render merged with zero `.katex-error`. This slice should not touch them; confirm it does not.

- [ ] **Step 6: Push and open the PR**

The DoD artefacts belong in the PR body, not the repo, so there may be nothing left to commit — do not run a bare `git commit` that exits 1, and do not use `git add -A`.

PR body must record: the non-e2e count, the light/dark screenshots, the deliberate `class=" "` widening, the nested-cascade asymmetry (one nesting level is preserved on the signed path), and the two-span trailing-newline behaviour.

---

## Self-Review

**Spec coverage.** `alignToken` and the eligibility table → Task 1 Step 1 + Task 2 Step 3. The classifier and its `isIgnored` guard → Task 1 Step 2. Membership rules M1–M5 → Task 1 Step 3. The compatibility table → Task 1 Step 3 (M2). The reuse rewrite with its snapshot/insert/remove ordering and the `parentNode === element` guard → Task 2 Step 4. Deleting `isMergeable` → Task 1 Step 5. All nine barrier cases → Task 3. Every happy-path case → Task 2 and Task 3. The three idempotence fixtures and the cross-product with its normative predicate → Task 4. The inverted page test, both stale counts and the stale `isMergeable` reference → Task 5. DoD → Task 6. Every falsification-table row appears in Task 3 Step 3 or Task 4 Steps 2–3.

**Deliberately NOT covered: performance.** The predecessor makes no performance claim and neither does this plan. The partition loop now allocates a small object per run instead of an array, and `alignToken` runs a split per block per pass — both trivially bounded, neither measured. A measurement is a reasonable follow-up; per the repo's "measure the window, not the event" lesson it would need the DOM rebuilt per A/B variant.

**Known risk, stated rather than hidden:** Task 1 claims to be behaviour-preserving and its whole gate is "77 tests still pass". If the partition rewrite has a defect that no existing test covers, Task 1 will pass and Task 2 will inherit it. The mitigation is Task 3's mutant table, which targets the partition rules directly — but a reviewer should treat Task 1's diff as the highest-risk change in this plan, not the lowest.

**Type consistency.** `alignToken(el) → string|null`, `blockAttributesOk(el) → bool`, `classifyChild(node, extraSelector) → string`, `isMergeableBlock(node, extraSelector) → bool`, `isBareBr(node) → bool`, `noEffectiveAttributes(el) → bool`, and `runs[r] = {indices: number[], token: string|null, tag: string|null, sawTextOrBr: bool}` — each defined once and used with the same signature throughout. `runToken` is read only in Task 2's rewrite branch.
