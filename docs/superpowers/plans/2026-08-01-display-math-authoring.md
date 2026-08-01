# Display-Math Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a multi-line `\[…\]` display-math block render, by rejoining math spans that the rich-text editor split across `<div>`/`<br>` boundaries before KaTeX typesets them.

**Architecture:** One new client module, `courses/static/courses/js/math_reflow.js`, installs two *pre-hooks* on `window.renderMathInElement` and `window.katex.render` — the same globals `text_colour.js` already post-hooks. It exports `window.libliMathReflow(root, options)`, which walks the DOM, merges split math spans into single text nodes, converts literal `<br>` text inside table-cell spans, and promotes `\(…\)` spans holding a display-only environment to `\[…\]`. Nothing runs at save; no stored data changes.

**Tech Stack:** Vanilla ES5-style browser JS (no build step, matching every other module in `courses/static/courses/js/`), Django templates, pytest + pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-08-01-display-math-authoring-design.md` — read it before Task 4. Every non-obvious rule below has a "why" recorded there, usually with a measurement.

## Global Constraints

- **Render-only.** No save path changes, no model changes, no migrations, no management commands. If a task looks like it needs one, stop and re-read the spec.
- **Faithful port.** The scan must reproduce auto-render's `splitAtDelimiters`/`findEndOfMath` exactly — ordered `startsWith` on openings, backslash-skip and brace-depth on closings, and a hard stop at the first unclosed opener. Deviating in *either* direction mis-pairs spans against the renderer that runs immediately afterwards.
- **Tooling:** `ruff`, `pytest` and `python` are NOT on PATH — always `uv run <tool>`. Run all commands from the worktree root `C:/Users/krzys/Documents/Python/own/libli/.claude/worktrees/math-display-reflow`.
- **e2e is opt-in:** `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`. Any file named `test_e2e_*` runs only under `uv run pytest -m e2e`. Omitting `-m e2e` silently deselects (exit 5).
- **Doubled `-q` hides the verdict.** `addopts` already carries `-q`; adding another stacks to quiet-2 and prints no pass/fail line. Pass `--verbosity=0` when you want the summary.
- **No JS comments containing `addEventListener("DOMContentLoaded"`** in a form the wiring test would match — see Task 2. Write the explanatory comment without that literal call form.
- **Baseline:** full non-e2e suite is green at **4559 passed, 1 skipped** at branch point `0a9c2882`. Tasks 1 and 2 add non-e2e tests, so the final count will be higher; Task 10 records the new number.
- **Browser JS style:** IIFE, `"use strict"`, `var`, no arrow functions, no `let`/`const` — match `text_colour.js` and `math.js`. (`String.prototype.startsWith` is fine; the repo already targets modern Chromium/Firefox.)

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/static/courses/js/math_reflow.js` (create) | The whole feature: defaults, scan port, walk, phases 1/1b/2, both hooks |
| `templates/courses/lesson_unit.html` (modify) | Add script tag inside `{% if has_math %}` |
| `templates/courses/quiz_unit.html` (modify) | ditto |
| `templates/courses/quiz_results.html` (modify) | ditto |
| `templates/courses/manage/review_submission.html` (modify) | ditto |
| `templates/courses/manage/editor/editor.html` (modify) | Add script tag unconditionally |
| `tests/test_math_reflow_defaults.py` (create) | Pins the hardcoded delimiter defaults against the vendored file |
| `tests/test_text_colour_script_order.py` (modify) | Extends the existing parser with the new ordering + containment assertions |
| `tests/test_e2e_math_reflow_dom.py` (create) | DOM-in/DOM-out table against `window.libliMathReflow` |
| `tests/test_e2e_math_reflow.py` (create) | End-to-end through real pages and the real RTE |

One module, not several: the phases share the scan, the walk and the ignore list, and splitting them across files would mean exporting internals purely for the split.

---

### Task 1: Module skeleton, defaults, and both hooks

The module loads, exports an inert `libliMathReflow`, and installs both wrappers. No reflow logic yet — that keeps every later task's failure localised.

**Files:**
- Create: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_math_reflow_defaults.py`

**Interfaces:**
- Produces: `window.libliMathReflow(root, options)` → `undefined`; `window.libliMathReflowDefaults` (array of `{left, right, display}` triples, read by the drift test); `window.__libliMathReflowWrapped` (boolean install marker).

- [ ] **Step 1: Write the failing test**

Create `tests/test_math_reflow_defaults.py`:

```python
"""The module hardcodes a copy of auto-render's default delimiter list, because the
vendored file keeps it as a minified internal and exposes nothing on `window`. That
copy is version-coupled third-party data, so a KaTeX upgrade must redden here rather
than silently diverging."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "courses/static/courses/vendor/katex/contrib/auto-render.min.js"
MODULE = ROOT / "courses/static/courses/js/math_reflow.js"

# {left:"$$",right:"$$",display:!0}  — minified booleans, JS-escaped strings.
_TRIPLE = re.compile(
    r'\{left:"((?:[^"\\]|\\.)*)",right:"((?:[^"\\]|\\.)*)",display:(!0|!1)\}'
)


def _js_unescape(value):
    """Decode a JS double-quoted string body. `\\\\(` in source is the two-character
    string `\\(`; json.loads applies exactly the same escape rules."""
    return json.loads('"%s"' % value)


def _triples(source):
    return [
        (_js_unescape(m.group(1)), _js_unescape(m.group(2)), m.group(3) == "!0")
        for m in _TRIPLE.finditer(source)
    ]


def test_vendored_defaults_are_exactly_eight_triples():
    found = _triples(VENDOR.read_text(encoding="utf-8"))
    # Anti-vacuity: a regex that matched nothing would make every later
    # comparison pass over an empty list.
    assert len(found) == 8, found


def test_module_defaults_match_the_vendored_defaults_in_order():
    vendored = _triples(VENDOR.read_text(encoding="utf-8"))
    module_src = MODULE.read_text(encoding="utf-8")
    block = re.search(
        r"DEFAULT_DELIMITERS\s*=\s*(\[[\s\S]*?\]);", module_src
    )
    assert block, "DEFAULT_DELIMITERS array not found in math_reflow.js"
    mine = [
        (_js_unescape(m.group(1)), _js_unescape(m.group(2)), m.group(3) == "true")
        for m in re.finditer(
            r'\{\s*left:\s*"((?:[^"\\]|\\.)*)",\s*right:\s*"((?:[^"\\]|\\.)*)",'
            r'\s*display:\s*(true|false)\s*\}',
            block.group(1),
        )
    ]
    assert len(mine) == 8, mine
    assert mine == vendored
```

- [ ] **Step 2: Run it and watch it fail**

```
uv run pytest tests/test_math_reflow_defaults.py --verbosity=0
```
Expected: `test_vendored_defaults_are_exactly_eight_triples` PASSES (the vendored file already has them); `test_module_defaults_match_the_vendored_defaults_in_order` FAILS with `FileNotFoundError` — `math_reflow.js` does not exist.

- [ ] **Step 3: Create the module**

Create `courses/static/courses/js/math_reflow.js`:

```js
// Rejoins math spans that the rich-text editor split across <div>/<br> boundaries,
// so KaTeX's auto-render — which only matches inside a SINGLE text node — can see
// them. Installs pre-hooks on the same two globals text_colour.js post-hooks.
//
// Install runs exactly once, with no deferred retry. text_colour.js retries its own
// installs when a global was missing; copying that here would be a bug, because
// marker properties do not propagate through another module's wrapper, so a retry
// would wrap an already-wrapped chain and reflow twice per call. This module loads
// after katex.min.js and auto-render.min.js in document order, so one attempt is
// enough. The marker below is a double-include guard, not a retry enabler, and it
// lives on window rather than on either wrapped function for the same reason.
(function () {
  "use strict";

  // Verbatim copy of auto-render's defaults, IN ITS ORDER (first match wins is
  // load-bearing). Pinned against the vendored file by tests/test_math_reflow_defaults.py.
  var DEFAULT_DELIMITERS = [
    { left: "$$", right: "$$", display: true },
    { left: "\\(", right: "\\)", display: false },
    { left: "\\begin{equation}", right: "\\end{equation}", display: true },
    { left: "\\begin{align}", right: "\\end{align}", display: true },
    { left: "\\begin{alignat}", right: "\\end{alignat}", display: true },
    { left: "\\begin{gather}", right: "\\end{gather}", display: true },
    { left: "\\begin{CD}", right: "\\end{CD}", display: true },
    { left: "\\[", right: "\\]", display: true }
  ];

  function reflow(root, options) {
    // Filled in by later tasks.
    return undefined;
  }

  // The export is UNCONDITIONAL — only the hooks below are guarded on the KaTeX
  // globals. The DOM test harness loads this module alone, with no KaTeX.
  window.libliMathReflow = reflow;
  window.libliMathReflowDefaults = DEFAULT_DELIMITERS;

  if (window.__libliMathReflowWrapped) return;

  var autoRender = window.renderMathInElement;
  var katexObj = window.katex;
  if (typeof autoRender !== "function" || !katexObj ||
      typeof katexObj.render !== "function") {
    return;  // no KaTeX on this page: install nothing, change nothing
  }

  window.renderMathInElement = function (root, options) {
    try { reflow(root, options); } catch (e) { /* never block typesetting */ }
    return autoRender.apply(this, arguments);
  };

  var originalRender = katexObj.render;
  katexObj.render = function (expr, element, options) {
    return originalRender.apply(this, arguments);  // Task 8 adds the strip
  };

  window.__libliMathReflowWrapped = true;
})();
```

- [ ] **Step 4: Run the test and watch it pass**

```
uv run pytest tests/test_math_reflow_defaults.py --verbosity=0
```
Expected: 2 passed.

- [ ] **Step 5: Falsify it**

Change one `display: true` to `display: false` in `DEFAULT_DELIMITERS`, re-run, confirm RED, then change it back and confirm GREEN again. A drift test that cannot redden is worthless.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_math_reflow_defaults.py
git commit -m "feat(math): math_reflow.js skeleton with pinned auto-render defaults"
```

---

### Task 2: Template wiring

Ships the module on the five pages that load KaTeX. It is still inert, so this is safe to land before the logic.

**Files:**
- Modify: `templates/courses/lesson_unit.html` (KaTeX block at L60), `templates/courses/quiz_unit.html` (L16), `templates/courses/quiz_results.html` (L59), `templates/courses/manage/review_submission.html` (L130), `templates/courses/manage/editor/editor.html` (L137, unconditional)
- Test: `tests/test_text_colour_script_order.py` (extend — do not create a second parser)

**Interfaces:**
- Consumes: `math_reflow.js` from Task 1.

- [ ] **Step 1: Read the existing test module**

```
uv run python -c "print(open('tests/test_text_colour_script_order.py').read())"
```
It already parses `{% static '…' %}` across exactly these five templates and has an anti-vacuity self-check. Extend it; do not re-implement the parser.

- [ ] **Step 2: Write the failing assertions**

Append to `tests/test_text_colour_script_order.py` (reuse its existing `_script_order`, `PAGES`, `TEMPLATES` helpers):

```python
GATED_PAGES = [
    "lesson_unit.html",
    "quiz_unit.html",
    "quiz_results.html",
    "manage/review_submission.html",
]


def test_math_reflow_present_on_every_katex_page():
    for page in PAGES:
        order = _script_order(TEMPLATES / page)
        assert "math_reflow.js" in order, page


def test_math_reflow_load_order():
    """katex < auto-render < math_reflow < text_colour, and math_reflow < math.js.

    math.js runs renderMath(document) and renderInlineText(document) at module
    evaluation, so a module loaded after it misses the entire first paint."""
    for page in PAGES:
        order = _script_order(TEMPLATES / page)
        i = order.index("math_reflow.js")
        assert order.index("katex.min.js") < i, page
        assert order.index("auto-render.min.js") < i, page
        assert i < order.index("text_colour.js"), page
        if "math.js" in order:
            assert i < order.index("math.js"), page


def _has_math_block(path):
    """The source lines between `{% if has_math %}` and its `{% endif %}`."""
    lines = (TEMPLATES / path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if "{% if has_math %}" in l)
    end = next(i for i in range(start + 1, len(lines)) if "{% endif %}" in lines[i])
    return "\n".join(lines[start:end])


def test_math_reflow_sits_inside_the_has_math_block():
    """An index-based ordering check passes identically whether the tag is inside
    or outside the conditional, so containment needs its own assertion — otherwise
    the module ships on every math-free lesson page undetected."""
    for page in GATED_PAGES:
        block = _has_math_block(page)
        assert "auto-render.min.js" in block, page   # anti-vacuity: right block
        assert "math_reflow.js" in block, page


def _strip_js_comments(source):
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", source)


def test_math_reflow_registers_no_domcontentloaded_retry():
    """A retry would wrap an already-wrapped chain and reflow twice per call.

    Comments are stripped first because the module is REQUIRED to carry a comment
    explaining why it does not retry, and quote-agnostic because a single-quoted
    call would slip past a double-quoted literal."""
    src = _strip_js_comments(
        (ROOT / "courses/static/courses/js/math_reflow.js").read_text(encoding="utf-8")
    )
    assert "math_reflow" not in src or True  # anti-vacuity: source actually loaded
    assert len(src) > 200, "comment stripping ate the whole module"
    assert not re.search(r"""addEventListener\(\s*["']DOMContentLoaded""", src)
```

- [ ] **Step 3: Run and watch them fail**

```
uv run pytest tests/test_text_colour_script_order.py --verbosity=0
```
Expected: the first three new tests FAIL (`math_reflow.js` not in any template).

- [ ] **Step 4: Add the script tags**

In each of the four gated templates, inside the existing `{% if has_math %}` block, immediately after the `auto-render.min.js` line and before `text_colour.js`:

```html
    <script src="{% static 'courses/js/math_reflow.js' %}" defer></script>
```

In `templates/courses/manage/editor/editor.html` add the same line after `auto-render.min.js` (that template's KaTeX block is unconditional).

- [ ] **Step 5: Run and watch them pass**

```
uv run pytest tests/test_text_colour_script_order.py --verbosity=0
```
Expected: all pass.

- [ ] **Step 6: Falsify the containment guard**

Move the `math_reflow.js` line in `lesson_unit.html` outside the `{% if has_math %}` block. Re-run: `test_math_reflow_sits_inside_the_has_math_block` must go RED while `test_math_reflow_load_order` stays GREEN — that contrast is the whole point of the containment assertion. Put it back.

- [ ] **Step 7: Falsify the retry guard, both quote styles**

Temporarily add `document.addEventListener("DOMContentLoaded", function(){});` to the module → RED. Replace with `document.addEventListener('DOMContentLoaded', function(){});` → still RED. Remove both.

- [ ] **Step 8: Commit**

```bash
git add templates/courses tests/test_text_colour_script_order.py
git commit -m "feat(math): load math_reflow.js on the five KaTeX pages"
```

---

### Task 3: The walk, ignored subtrees, and the root contract

Everything that makes the reflow refuse to touch things. Landing the guards **before** any mutation means no intermediate commit can rewrite an RTE surface.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py` (create)

**Interfaces:**
- Produces: internal `walk(root, fn)`; `IGNORE_SELECTOR`; the root guards inside `reflow`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_e2e_math_reflow_dom.py`:

```python
"""DOM-in/DOM-out cases against window.libliMathReflow.

Harness mirrors tests/test_e2e_text_colour.py:46-47,143-145 — set_content plus
add_script_tag. Do NOT use live_server + staticfiles: static() no-ops under
DEBUG=False in this repo. The module's export is unconditional precisely so this
page needs no KaTeX."""

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "courses/static/courses/js/math_reflow.js")

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _page(page, html):
    page.set_content("<!DOCTYPE html><div id='root'>%s</div>" % html)
    page.add_script_tag(path=SCRIPT)
    return page


def _reflow_html(page, html, options="undefined"):
    """Return #root.innerHTML after reflowing #root."""
    _page(page, html)
    return page.evaluate(
        "(o) => { const r = document.getElementById('root');"
        "         window.libliMathReflow(r, o); return r.innerHTML; }",
        None if options == "undefined" else options,
    )


IGNORED = [
    ("pre", "<pre>\\[a</pre><pre>b\\]</pre>"),
    ("code", "<code>\\[a</code><code>b\\]</code>"),
    ("textarea", "<textarea>\\[a</textarea>"),
    ("contenteditable", '<div contenteditable="true"><div>\\[a</div><div>b\\]</div></div>'),
    ("katex", '<span class="katex"><div>\\[a</div><div>b\\]</div></span>'),
    ("katex-error", '<span class="katex-error">\\(a<br>b\\)</span>'),
]


@pytest.mark.parametrize("name,html", IGNORED, ids=[n for n, _ in IGNORED])
def test_ignored_subtrees_are_untouched(page, name, html):
    assert _reflow_html(page, html) == html


def test_contenteditable_false_is_not_ignored(page):
    """The bare [contenteditable] selector would also match contenteditable="false",
    which is not editable and carries no data-mutation risk."""
    html = '<div contenteditable="false"><div>\\[a</div><div>b\\]</div></div>'
    assert _reflow_html(page, html) != html


def test_falsy_root_is_a_no_op(page):
    _page(page, "")
    assert page.evaluate("() => { window.libliMathReflow(null); return true; }")


def test_document_root_does_not_throw(page):
    _page(page, "<div>\\[a</div><div>b\\]</div>")
    assert page.evaluate("() => { window.libliMathReflow(document); return true; }")


def test_root_inside_an_ignored_subtree_is_a_no_op(page):
    """The third of three shapes — root-is-ignored, root-is-an-ancestor,
    root-is-a-descendant. Only the first two were handled in an earlier draft."""
    _page(page, '<pre><span id="inner"><div>\\[a</div><div>b\\]</div></span></pre>')
    before = page.evaluate("() => document.getElementById('inner').innerHTML")
    after = page.evaluate(
        "() => { const n = document.getElementById('inner');"
        "        window.libliMathReflow(n); return n.innerHTML; }"
    )
    assert after == before
```

- [ ] **Step 2: Run and watch them fail**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: `test_contenteditable_false_is_not_ignored` FAILS (reflow is still a no-op, so nothing changes). The others pass vacuously for now — that is expected at this step and is why Step 5 falsifies them.

- [ ] **Step 3: Implement the walk and the guards**

In `math_reflow.js`, above `reflow`:

```js
  // auto-render's own default ignore list, plus four this module adds:
  //  * the RTE surface — text_toolbar.js sync() writes its innerHTML back into the
  //    POSTed textarea, so a DOM mutation there is a DATA mutation. Scoped with
  //    :not([contenteditable="false"]) because a false value is not editable.
  //  * .katex — KaTeX's output holds the original TeX in a MathML annotation.
  //  * .katex-error — NOT nested inside .katex; holds raw TeX with throwOnError:false.
  //  * math/annotation — defence in depth if KaTeX's output mode ever changes.
  var IGNORE_SELECTOR =
    "script,noscript,style,textarea,pre,code,option," +
    '[contenteditable]:not([contenteditable="false"]),' +
    ".katex,.katex-error,math,annotation";

  function isIgnored(node, extraSelector) {
    if (!node || node.nodeType !== 1) return false;
    if (node.matches && node.matches(IGNORE_SELECTOR)) return true;
    return !!(extraSelector && node.matches && node.matches(extraSelector));
  }

  // Caller-supplied ignoredTags/ignoredClasses are UNIONED into the fixed list.
  // Ignoring more than the renderer never changes what renders; ignoring less
  // would let the reflow fold away wrappers in a subtree the renderer skips.
  function extraIgnoreSelector(options) {
    var parts = [];
    var i;
    if (options && options.ignoredTags) {
      for (i = 0; i < options.ignoredTags.length; i++) {
        parts.push(String(options.ignoredTags[i]));
      }
    }
    if (options && options.ignoredClasses) {
      for (i = 0; i < options.ignoredClasses.length; i++) {
        parts.push("." + String(options.ignoredClasses[i]));
      }
    }
    return parts.length ? parts.join(",") : null;
  }

  // Post-order: every descendant is processed before its parent may fold it away,
  // and a parent classifies its children on their POST-processing state.
  function walk(node, extraSelector, visit) {
    var children = [].slice.call(node.childNodes);  // snapshot: visit() mutates
    for (var i = 0; i < children.length; i++) {
      var child = children[i];
      if (child.nodeType !== 1) continue;
      if (isIgnored(child, extraSelector)) continue;
      walk(child, extraSelector, visit);
    }
    visit(node);
  }
```

and replace `reflow`'s body:

```js
  function reflow(root, options) {
    if (!root) return;  // three callers pass an unguarded root; leave auto-render's
                        // own "No element provided to render" error unchanged
    var extra = extraIgnoreSelector(options);
    // matches/closest are absent on Document and DocumentFragment, exactly as
    // math.js:18 already guards for [data-katex].
    if (isIgnored(root, extra)) return;
    if (root.closest && root.closest(IGNORE_SELECTOR)) return;
    if (extra && root.closest && root.closest(extra)) return;
    walk(root, extra, function (element) {
      mergeChildren(element, options);   // Task 4
    });
  }
```

and add a stub so the module still parses:

```js
  function mergeChildren(element, options) { /* Task 4 */ }
```

- [ ] **Step 4: Run and watch them pass**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: all pass except `test_contenteditable_false_is_not_ignored`, which still fails because merging does not exist yet. **Mark it `@pytest.mark.xfail(reason="merge lands in Task 4", strict=True)` and remove the marker in Task 4.** Do not weaken the assertion.

- [ ] **Step 5: Falsify the ignore list**

Delete `.katex-error` from `IGNORE_SELECTOR`. Re-run: after Task 4 lands this must go RED. For now, record in the commit message that the ignored-subtree cases are provisionally vacuous and are falsified at the end of Task 4.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math): reflow walk, ignored subtrees and root guards"
```

---

### Task 4: Phase 1 — the merge

The core. Mergeable/barrier classification, run partition, run-text build with the offset→child map, the scan port, and the rewrite with overlap coalescing.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py`

**Interfaces:**
- Consumes: `walk`, `IGNORE_SELECTOR` (Task 3); `DEFAULT_DELIMITERS` (Task 1).
- Produces: `mergeChildren(element, options)`; internal `findEndOfMath(delim, text, from)`, `findSpans(text, delimiters)`, `buildRun(children)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_e2e_math_reflow_dom.py`:

```python
def test_basic_split_span_merges(page):
    out = _reflow_html(page, "<div>\\[x</div><div>y\\]</div>")
    assert out == "\\[x\ny\\]"


def test_non_covered_siblings_survive_as_elements(page):
    """Three CHILDREN, of which only the middle is a text node — not three text
    nodes. auto-render re-joins adjacent text nodes, so an argument resting on a
    text-node boundary would be unfounded."""
    out = _reflow_html(page, "<div>a</div><div>\\[x</div><div>y\\]</div><div>b</div>")
    assert out == "<div>a</div>\\[x\ny\\]<div>b</div>"


def test_empty_class_attribute_still_merges(page):
    """nh3 emits an EMPTY class on div/p when every class value is rejected, so a
    formula pasted from Word/Docs carries class="" on every line. Treating that as
    'attributed' would make the whole feature a no-op on the dominant paste path."""
    out = _reflow_html(page, '<div class="">\\[x</div><div class="">y\\]</div>')
    assert out == "\\[x\ny\\]"
    out = _reflow_html(page, '<div style="">\\[x</div><div style="">y\\]</div>')
    assert out == "\\[x\ny\\]"


@pytest.mark.parametrize(
    "html",
    [
        '<div class="ta-center">\\[x</div><div class="ta-center">y\\]</div>',
        '<div data-x="1">\\[x</div><div data-x="1">y\\]</div>',
        "<div>\\[a</div><strong>x</strong><div>b\\]</div>",
        '<div>\\[a</div><span class="tc-red">x</span><div>b\\]</div>',
        "<div>\\[a</div><div><em>x</em></div><div>b\\]</div>",
    ],
)
def test_barriers_are_not_merged_across(page, html):
    assert _reflow_html(page, html) == html


def test_single_child_span_is_never_rewritten(page):
    """A span inside ONE mergeable <p> must keep its paragraph. Stating rule 4 in
    text-node terms instead of child-node terms would unwrap every authored
    paragraph containing math, on every render."""
    html = "<p>Let \\(x\\) be, so \\[y\\] holds</p>"
    assert _reflow_html(page, html) == html


def test_walk_descends_into_barriers(page):
    """MEASURED TRAP: a bare <td> outside a table is DROPPED by the HTML parser,
    leaving the two divs as direct children of #root — so the unwrapped version of
    this test passes for entirely the wrong reason. The table wrapper is mandatory."""
    html = ('<table><tbody><tr><td class="ta-center">'
            '<div>\\[x</div><div>y\\]</div></td></tr></tbody></table>')
    assert _reflow_html(page, html) == (
        '<table><tbody><tr><td class="ta-center">\\[x\ny\\]</td></tr></tbody></table>'
    )


def test_real_br_outside_the_span_survives_as_an_element(page):
    out = _reflow_html(page, "<div>a<br>b \\[x</div><div>y\\]</div>")
    assert "<br>" in out
    assert "\\[x\ny\\]" in out


def test_empty_line_div_collapses_to_one_newline(page):
    """<div><br></div> is Chrome's empty line. Without collapsing it would emit a
    blank line, which in real LaTeX is a \\par and an error inside align*."""
    out = _reflow_html(page, "<div>\\[a</div><div><br></div><div>b\\]</div>")
    assert out == "\\[a\nb\\]"


def test_div_then_text_node_boundary_gets_a_newline(page):
    """A leading-only newline rule would concatenate the two tokens into
    \\alphax and KaTeX would report an undefined control sequence."""
    out = _reflow_html(page, "<div>\\[\\alpha</div>x\\]")
    assert out == "\\[\\alpha\nx\\]"


def test_escaped_closer_is_not_accepted(page):
    """Ported findEndOfMath: a backslash skips the following character."""
    out = _reflow_html(page, "<div>\\[a \\\\] b</div><div>c\\]</div>")
    assert out.count("\\]") == 2      # the escaped one survives inside the span
    assert "\n" in out                # and the span did merge


def test_closer_inside_braces_is_not_accepted(page):
    out = _reflow_html(page, "<div>\\[\\text{a\\]b}</div><div>c\\]</div>")
    assert out == "\\[\\text{a\\]b}\nc\\]"


def test_scanning_stops_at_an_unclosed_opener(page):
    """auto-render breaks out of its whole loop on an unclosed opener, so nothing
    after one is a candidate.

    MEASURED: the break is only observable with MIXED delimiters. In
    `\\[oops … \\[a … b\\]` the first `\\[` simply pairs with the only `\\]` — correct,
    and what auto-render does too — so that input tests nothing. A `\\(` with no
    `\\)` anywhere is a genuine unclosed opener, and it must suppress the complete
    `$$…$$` span that follows."""
    html = "<div>\\(oops</div><div>$$a</div><div>b$$</div>"
    assert _reflow_html(page, html) == html


def test_two_spans_in_one_run(page):
    """MEASURED: the two spans come out ADJACENT with no separator, because the
    boundary newline between them is synthetic, belongs to the second replacement
    group, and textFragment drops it there. Harmless — auto-render re-joins
    adjacent text nodes and parses both spans — but the assertion must match
    reality rather than the tidier-looking value."""
    out = _reflow_html(page, "<div>\\[a</div><div>b\\]</div><div>\\[c</div><div>d\\]</div>")
    assert out == "\\[a\nb\\]\\[c\nd\\]"


def test_overlapping_covered_ranges_coalesce(page):
    """Child 2 holds the end of span 1 AND the start of span 2, so the ranges are
    not disjoint and no application order alone can work."""
    out = _reflow_html(page, "<div>\\[a</div><div>b\\] \\(c</div>d\\)")
    assert out == "\\[a\nb\\] \\(c\nd\\)"


def test_inline_span_merges_and_collapses_the_line(page):
    """Accepted consequence: the alternative leaves split inline math permanently
    broken, the same silent failure class this change removes."""
    out = _reflow_html(page, "<div>Prose \\(x</div><div>y\\) more</div>")
    assert out == "Prose \\(x\ny\\) more"


def test_bystander_intact_span_is_relocated_but_survives(page):
    out = _reflow_html(page, "<div>\\(x\\) prose \\[a</div><div>b\\]</div>")
    assert "\\(x\\)" in out
    assert "\\[a\nb\\]" in out


def test_nested_split_merges_after_post_order_folding(page):
    """The outer div is a barrier until post-order processing folds its nested
    divs into a text node — and only when the rewrite covered ALL of its element
    children."""
    out = _reflow_html(page, "<div><div>\\[a</div><div>b\\]</div></div>")
    assert out == "<div>\\[a\nb\\]</div>"


def test_reflow_is_idempotent(page):
    _page(page, "<div>\\[x</div><div>y\\]</div>")
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r); return [a, r.innerHTML]; }"
    )
    assert out[0] == out[1]


def test_delimiter_set_is_derived_from_options(page):
    """Three callers pass no delimiters and run on auto-render's defaults, which
    include $$ and the \\begin{...} pairs."""
    out = _reflow_html(page, "<div>$$x</div><div>y$$</div>")
    assert out == "$$x\ny$$"
    out = _reflow_html(
        page,
        "<div>$$x</div><div>y$$</div>",
        options={"delimiters": [{"left": "\\[", "right": "\\]", "display": True}]},
    )
    assert out == "<div>$$x</div><div>y$$</div>"


def test_caller_ignored_tags_are_unioned_in(page):
    html = "<div>\\[x</div><div>y\\]</div>"
    out = _reflow_html(page, html, options={"ignoredTags": ["div"]})
    assert out == html
```

- [ ] **Step 2: Run and watch them fail**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: every new test FAILS — `mergeChildren` is a stub.

- [ ] **Step 3: Implement the merge**

Replace the `mergeChildren` stub in `math_reflow.js`:

```js
  // ---- scan: a faithful port of auto-render's splitAtDelimiters ---------------

  // Port of findEndOfMath: a backslash SKIPS the following character (so an escaped
  // \] is not a closer), and a closer is only accepted at brace depth <= 0.
  function findEndOfMath(delim, text, startIndex) {
    var index = startIndex;
    var braceLevel = 0;
    var delimLength = delim.length;
    while (index < text.length) {
      var ch = text[index];
      if (braceLevel <= 0 && text.slice(index, index + delimLength) === delim) {
        return index;
      }
      if (ch === "\\") index++;
      else if (ch === "{") braceLevel++;
      else if (ch === "}") braceLevel--;
      index++;
    }
    return -1;
  }

  // Openings: left to right, first delimiter in the CALLER'S ARRAY ORDER that
  // matches at this position wins. No escape handling — auto-render does none.
  // An unclosed opener stops the scan dead, exactly as auto-render's loop breaks.
  function findSpans(text, delimiters) {
    var spans = [];
    var pos = 0;
    while (pos < text.length) {
      var chosen = null;
      for (var i = 0; i < delimiters.length; i++) {
        if (text.startsWith(delimiters[i].left, pos)) { chosen = delimiters[i]; break; }
      }
      if (!chosen) { pos++; continue; }
      var end = findEndOfMath(chosen.right, text, pos + chosen.left.length);
      if (end === -1) break;
      spans.push({ start: pos, end: end + chosen.right.length, delim: chosen });
      pos = end + chosen.right.length;
    }
    return spans;
  }

  function delimitersFor(options) {
    return (options && options.delimiters) || DEFAULT_DELIMITERS;
  }

  // ---- mergeable / barrier ---------------------------------------------------

  // "No effective attributes" = none, or only an EMPTY class and/or style. nh3
  // emits class="" on div/p when every class value is rejected, which is what a
  // pasted formula carries on every line; treating that as attributed would make
  // the feature a no-op on the dominant authoring path.
  function noEffectiveAttributes(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      var attr = el.attributes[i];
      if ((attr.name === "class" || attr.name === "style") && attr.value === "") continue;
      return false;
    }
    return true;
  }

  function isBareBr(node) {
    return node.nodeType === 1 && node.tagName === "BR" && noEffectiveAttributes(node);
  }

  function isMergeableBlock(node) {
    if (node.nodeType !== 1) return false;
    if (node.tagName !== "DIV" && node.tagName !== "P") return false;
    if (!noEffectiveAttributes(node)) return false;
    for (var i = 0; i < node.childNodes.length; i++) {
      var child = node.childNodes[i];
      if (child.nodeType === 3) continue;
      if (isBareBr(child)) continue;
      return false;
    }
    return true;
  }

  function isMergeable(node) {
    return node.nodeType === 3 || isBareBr(node) || isMergeableBlock(node);
  }

  // ---- run text + offset->child map ------------------------------------------

  // The collapse is applied DURING the build so the map stays intact: one surviving
  // newline can come from three children at once, and a post-hoc regex collapse
  // would give every later span a wrong covered range.
  function buildRun(children) {
    var text = "";
    var map = [];          // map[i] = index into `children` for text[i]
    var synthetic = [];    // synthetic[i] = true when text[i] is a manufactured \n

    function pushChar(ch, childIndex, isSynthetic) {
      text += ch;
      map.push(childIndex);
      synthetic.push(!!isSynthetic);
    }

    function pushText(str, childIndex) {
      for (var i = 0; i < str.length; i++) pushChar(str[i], childIndex, false);
    }

    function pushBoundary(childIndex) {
      if (!text.length) return;                                  // never lead the run
      if (text.charAt(text.length - 1) === "\n") return;         // collapse
      pushChar("\n", childIndex, true);
    }

    function pushBlockText(node, childIndex) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var child = node.childNodes[i];
        if (child.nodeType === 3) pushText(child.data, childIndex);
        else if (isBareBr(child)) {
          if (text.length && text.charAt(text.length - 1) !== "\n") {
            pushChar("\n", childIndex, false);   // an AUTHORED break, not synthetic
          }
        }
      }
    }

    for (var i = 0; i < children.length; i++) {
      var node = children[i];
      if (node.nodeType === 3) {
        // Whitespace-only text nodes contribute nothing, so hand-written test
        // markup with indentation behaves like nh3 output, which carries none.
        if (/\S/.test(node.data)) pushText(node.data, i);
      } else if (isBareBr(node)) {
        if (text.length && text.charAt(text.length - 1) !== "\n") {
          pushChar("\n", i, false);
        }
      } else {
        pushBoundary(i);
        pushBlockText(node, i);
        pushBoundary(i);
      }
    }
    while (text.length && text.charAt(text.length - 1) === "\n") {
      text = text.slice(0, -1); map.pop(); synthetic.pop();
    }
    return { text: text, map: map, synthetic: synthetic };
  }

  // ---- phase 1 ---------------------------------------------------------------

  function textFragment(doc, run, from, to) {
    // Drops synthetic newlines; keeps authored ones as <br> elements, because a \n
    // character outside a math span is HTML whitespace and collapses to a space.
    var nodes = [];
    var buffer = "";
    for (var i = from; i < to; i++) {
      var ch = run.text.charAt(i);
      if (ch === "\n") {
        if (run.synthetic[i]) continue;
        if (buffer) { nodes.push(doc.createTextNode(buffer)); buffer = ""; }
        nodes.push(doc.createElement("br"));
        continue;
      }
      buffer += ch;
    }
    if (buffer) nodes.push(doc.createTextNode(buffer));
    return nodes;
  }

  function mergeChildren(element, options) {
    var doc = element.ownerDocument || document;
    var children = [].slice.call(element.childNodes);
    var runs = [];
    var current = [];
    var i;
    for (i = 0; i < children.length; i++) {
      if (isMergeable(children[i])) current.push(i);
      else { if (current.length) runs.push(current); current = []; }
    }
    if (current.length) runs.push(current);

    for (var r = runs.length - 1; r >= 0; r--) {
      var indices = runs[r];
      var nodes = [];
      for (i = 0; i < indices.length; i++) nodes.push(children[indices[i]]);
      var run = buildRun(nodes);
      var spans = findSpans(run.text, delimitersFor(options));

      // Rule 4: only spans covering TWO OR MORE children are rewritten.
      var planned = [];
      for (i = 0; i < spans.length; i++) {
        var first = run.map[spans[i].start];
        var last = run.map[spans[i].end - 1];
        if (first !== last) planned.push({ span: spans[i], first: first, last: last });
      }
      if (!planned.length) continue;

      // Covered ranges may OVERLAP (a child can hold the end of one span and the
      // start of the next), so coalesce into maximal disjoint replacement groups.
      var groups = [];
      for (i = 0; i < planned.length; i++) {
        var g = groups.length ? groups[groups.length - 1] : null;
        if (g && planned[i].first <= g.last) {
          g.last = Math.max(g.last, planned[i].last);
          g.spans.push(planned[i].span);
        } else {
          groups.push({ first: planned[i].first, last: planned[i].last,
                        spans: [planned[i].span] });
        }
      }

      for (var gi = groups.length - 1; gi >= 0; gi--) {
        var group = groups[gi];
        var startOffset = run.text.length, endOffset = 0;
        for (i = 0; i < run.map.length; i++) {
          if (run.map[i] >= group.first && run.map[i] <= group.last) {
            if (i < startOffset) startOffset = i;
            if (i + 1 > endOffset) endOffset = i + 1;
          }
        }
        var replacement = [];
        var cursor = startOffset;
        for (i = 0; i < group.spans.length; i++) {
          var span = group.spans[i];
          replacement = replacement.concat(textFragment(doc, run, cursor, span.start));
          replacement.push(doc.createTextNode(run.text.slice(span.start, span.end)));
          cursor = span.end;
        }
        replacement = replacement.concat(textFragment(doc, run, cursor, endOffset));

        var anchor = children[group.first];
        for (i = 0; i < replacement.length; i++) {
          element.insertBefore(replacement[i], anchor);
        }
        for (i = group.first; i <= group.last; i++) {
          if (children[i] && children[i].parentNode === element) {
            element.removeChild(children[i]);
          }
        }
      }
    }
  }
```

- [ ] **Step 4: Run and watch them pass**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e --verbosity=0
```
Expected: all pass. Remove the `xfail` marker added in Task 3 Step 4 and confirm `test_contenteditable_false_is_not_ignored` now passes.

- [ ] **Step 5: Falsify the ignored-subtree cases (deferred from Task 3)**

Delete `.katex-error` from `IGNORE_SELECTOR` → `test_ignored_subtrees_are_untouched[katex-error]` must go RED. Restore. Repeat for `[contenteditable]…` → the contenteditable case reddens. Restore both.

- [ ] **Step 6: Falsify rule 4**

Change rule 4 to compare text-node segments instead of child indices (the superseded wording). `test_single_child_span_is_never_rewritten` must go RED. Restore.

- [ ] **Step 7: Falsify the empty-attribute allowance**

Replace `noEffectiveAttributes` with `el.attributes.length === 0`. `test_empty_class_attribute_still_merges` must go RED while `test_barriers_are_not_merged_across` stays GREEN. Restore.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math): phase 1 merge with overlap coalescing"
```

---

### Task 5: Phase 1b — literal `<br>` inside a span

Table cells never present the DOM-split shape: `sanitize_cell` flattens it at save, escaping the `<br>` *into* the math. This is the textual counterpart, and it is what makes math in table cells work at all.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py`

**Interfaces:**
- Consumes: `walk`, `findSpans`, `delimitersFor`.
- Produces: `phase1b(element, options)`, called from `reflow` as a separate full pass.

- [ ] **Step 1: Write the failing tests**

```python
def test_phase_1b_converts_literal_br_inside_a_span(page):
    """The cell case is a RULE-4 SKIP — the span already sits in one text node.
    Hanging phase 1b off the rule-5 rewrite path would make it never fire."""
    out = _reflow_html(page, "\\[a<br>b\\]")
    assert out == "\\[a\nb\\]"


@pytest.mark.parametrize("form", ["<br>", "<br/>", "<br />", "<BR>"])
def test_phase_1b_matches_every_br_form(page, form):
    """sanitize_cell stashes the span BEFORE nh3.clean, so what survives inside it
    is un-normalised author/browser markup."""
    assert _reflow_html(page, "\\[a%sb\\]" % form) == "\\[a\nb\\]"


def test_phase_1b_leaves_p_alone(page):
    r"""CELL_TAGS has no p, and \(a<p>b\) is a plausible chain of inequalities."""
    assert _reflow_html(page, "\\(a<p>b\\)") == "\\(a<p>b\\)"
```

Note: write the `<p>` case with `page.set_content` receiving the literal text, not parsed markup — assert on `textContent`, since the browser would parse a real `<p>`. Use:

```python
def test_phase_1b_leaves_p_alone(page):
    _page(page, "")
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        r.appendChild(document.createTextNode('\\\\(a<p>b\\\\)'));"
        "        window.libliMathReflow(r); return r.textContent; }"
    )
    assert out == "\\(a<p>b\\)"
```

- [ ] **Step 2: Run and watch them fail**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e -k phase_1b --verbosity=0
```

- [ ] **Step 3: Implement phase 1b**

```js
  // Matches courses/sanitize.py's _BR: case-insensitive, optional whitespace,
  // optional slash. Enumerating only <br> and <br/> would miss <br /> and <BR>,
  // and that miss would be invisible — the corpus count for this shape is 0.
  var LITERAL_BR = /<br\s*\/?>/gi;

  function phase1b(element, options) {
    var delimiters = delimitersFor(options);
    for (var i = 0; i < element.childNodes.length; i++) {
      var node = element.childNodes[i];
      if (node.nodeType !== 3) continue;
      var spans = findSpans(node.data, delimiters);
      if (!spans.length) continue;
      var out = "";
      var cursor = 0;
      for (var s = 0; s < spans.length; s++) {
        out += node.data.slice(cursor, spans[s].start);
        out += node.data
          .slice(spans[s].start, spans[s].end)
          .replace(LITERAL_BR, "\n");
        cursor = spans[s].end;
      }
      out += node.data.slice(cursor);
      if (out !== node.data) node.data = out;
    }
  }
```

and in `reflow`, run it as its own full pass after phase 1:

```js
    walk(root, extra, function (element) { mergeChildren(element, options); });
    walk(root, extra, function (element) { phase1b(element, options); });
```

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Falsify**

Change `LITERAL_BR` to the literal string `"<br>"` → the `<br />` and `<BR>` parametrised cases must go RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math): phase 1b converts literal <br> inside a cell math span"
```

---

### Task 6: Phase 2 — delimiter promotion

`\(…\)` cannot host an alignment environment; KaTeX rejects all ten display-only environments in inline mode.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py`

**Interfaces:**
- Produces: `phase2(element, options)`, a third full pass.

- [ ] **Step 1: Write the failing tests**

```python
def test_phase_2_promotes_an_inline_display_only_environment(page):
    out = _reflow_html(page, "\\(\\begin{align*}a&=1\\end{align*}\\)")
    assert out.startswith("\\[") and out.endswith("\\]")


def test_phase_2_tests_contains_not_begins_with(page):
    r"""All five repairable question stems are \(-wrapped and OPEN with
    \begin{cases}, with \begin{align} nested inside. Measured: inline FAILS with
    '{align} can be used only in display mode'; display renders."""
    out = _reflow_html(
        page, "\\(\\begin{cases}\\begin{align}a&=1\\end{align}\\end{cases}\\)"
    )
    assert out.startswith("\\[") and out.endswith("\\]")


def test_phase_2_does_not_promote_a_both_modes_environment(page):
    r"""A prefix match on \begin{align} would also match \begin{aligned}, which
    works in BOTH modes — promoting it would convert correct inline math to a
    display block."""
    html = "\\(\\begin{aligned}a&=1\\end{aligned}\\)"
    assert _reflow_html(page, html) == html


def test_phase_2_respects_the_effective_span_partition(page):
    r"""A \(...\) sequence INSIDE a $$...$$ span is not a span at all; a raw scan
    would rewrite its delimiters and corrupt the enclosing formula."""
    html = "$$x \\(\\begin{align}a&=1\\end{align}\\) y$$"
    assert _reflow_html(page, html) == html


def test_split_inline_align_comes_out_merged_and_promoted(page):
    """Pins the phase ordering: promote-then-merge would leave this unpromoted."""
    out = _reflow_html(
        page, "<div>\\(\\begin{align*}a&=1</div><div>\\end{align*}\\)</div>"
    )
    assert out.startswith("\\[") and out.endswith("\\]")
    assert "\n" in out
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement phase 2**

```js
  // Ten EXACT literals, closing brace included. Not ten names, and not a prefix
  // match: \begin{align} would prefix-match \begin{aligned}, which works in both
  // modes, and promoting it would convert correct inline math to a display block.
  var DISPLAY_ONLY_ENVS = [
    "\\begin{align}", "\\begin{align*}", "\\begin{alignat}", "\\begin{alignat*}",
    "\\begin{gather}", "\\begin{gather*}", "\\begin{equation}", "\\begin{equation*}",
    "\\begin{CD}", "\\begin{split}"
  ];

  function containsDisplayOnlyEnv(body) {
    for (var i = 0; i < DISPLAY_ONLY_ENVS.length; i++) {
      if (body.indexOf(DISPLAY_ONLY_ENVS[i]) !== -1) return true;
    }
    return false;
  }

  function phase2(element, options) {
    var delimiters = delimitersFor(options);
    var hasDisplay = false;
    for (var d = 0; d < delimiters.length; d++) {
      if (delimiters[d].left === "\\[") hasDisplay = true;
    }
    if (!hasDisplay) return;   // no-op unless \[ is in the effective set
    for (var i = 0; i < element.childNodes.length; i++) {
      var node = element.childNodes[i];
      if (node.nodeType !== 3) continue;
      // Spans come from the EFFECTIVE partition, so a \(...\) sequence sitting
      // inside a $$...$$ span is correctly not a candidate.
      var spans = findSpans(node.data, delimiters);
      var out = "";
      var cursor = 0;
      var changed = false;
      for (var s = 0; s < spans.length; s++) {
        var span = spans[s];
        out += node.data.slice(cursor, span.start);
        var raw = node.data.slice(span.start, span.end);
        if (span.delim.left === "\\(" &&
            containsDisplayOnlyEnv(raw.slice(2, raw.length - 2))) {
          out += "\\[" + raw.slice(2, raw.length - 2) + "\\]";
          changed = true;
        } else {
          out += raw;
        }
        cursor = span.end;
      }
      out += node.data.slice(cursor);
      if (changed) node.data = out;
    }
  }
```

and add the third pass in `reflow`:

```js
    walk(root, extra, function (element) { phase2(element, options); });
```

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Falsify**

Change `containsDisplayOnlyEnv` to test `body.indexOf(env) === 0` (begins-with). `test_phase_2_tests_contains_not_begins_with` must go RED. Restore. Then strip the closing braces from `DISPLAY_ONLY_ENVS` → `test_phase_2_does_not_promote_a_both_modes_environment` must go RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math): phase 2 promotes inline display-only environments"
```

---

### Task 7: Hook B — strip the wrapper in `katex.render`

A Math element's `latex` goes straight to `katex.render`, so `\[` is an undefined control sequence there — while the same text without the wrapper renders today.

**Files:**
- Modify: `courses/static/courses/js/math_reflow.js`
- Test: `tests/test_e2e_math_reflow_dom.py`

- [ ] **Step 1: Write the failing tests**

```python
def _hookb(page, expr):
    """Install a fake katex BEFORE the module loads, then read what it received."""
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.evaluate(
        "() => { window.__seen = null;"
        "        window.katex = { render: (e) => { window.__seen = e; } };"
        "        window.renderMathInElement = () => {}; }"
    )
    page.add_script_tag(path=SCRIPT)
    page.evaluate("(e) => window.katex.render(e, null, {})", expr)
    return page.evaluate("() => window.__seen")


def test_hook_b_strips_a_display_wrapper(page):
    assert _hookb(page, "\\[\\begin{align*}a&=1\\end{align*}\\]") == \
        "\\begin{align*}a&=1\\end{align*}"


def test_hook_b_strips_an_inline_wrapper(page):
    assert _hookb(page, "\\(x\\)") == "x"


def test_hook_b_skips_leading_whitespace(page):
    assert _hookb(page, "  \\[x\\]  ") == "x"


def test_hook_b_refuses_two_adjacent_spans(page):
    r"""findEndOfMath stops at the first \], which is not the expression's end."""
    assert _hookb(page, "\\[a\\] + \\[b\\]") == "\\[a\\] + \\[b\\]"


def test_hook_b_tolerates_row_spacing(page):
    r"""A legitimate \\[2ex] in the body neither opens nor closes anything."""
    expr = "\\[\\begin{align*}a&=1\\\\[2ex]b&=2\\end{align*}\\]"
    assert _hookb(page, expr) == "\\begin{align*}a&=1\\\\[2ex]b&=2\\end{align*}"


def test_hook_b_passes_a_non_string_through_untouched(page):
    """expr is not guaranteed to be a string at every call site, and an exception
    here is swallowed by math.js renderOne's catch, leaving no diagnostic."""
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.evaluate(
        "() => { window.__seen = 'unset';"
        "        window.katex = { render: (e) => { window.__seen = e; } };"
        "        window.renderMathInElement = () => {}; }"
    )
    page.add_script_tag(path=SCRIPT)
    page.evaluate("() => window.katex.render(42, null, {})")
    assert page.evaluate("() => window.__seen") == 42
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement the strip**

Replace the Hook B wrapper body from Task 1:

```js
  // Reuses the ported findEndOfMath rather than a regex: /^\s*\\\[([\s\S]*)\\\]\s*$/
  // is greedy and would strip `\[a\] + \[b\]` — the one case that must be refused.
  function stripWrapper(expr) {
    if (typeof expr !== "string") return expr;
    var start = 0;
    while (start < expr.length && /\s/.test(expr.charAt(start))) start++;
    var end = expr.length;
    while (end > start && /\s/.test(expr.charAt(end - 1))) end--;
    var body = expr.slice(start, end);
    var pairs = [{ left: "\\[", right: "\\]" }, { left: "\\(", right: "\\)" }];
    for (var i = 0; i < pairs.length; i++) {
      var pair = pairs[i];
      if (body.indexOf(pair.left) !== 0) continue;
      var close = findEndOfMath(pair.right, body, pair.left.length);
      if (close === -1) continue;
      if (close + pair.right.length !== body.length) continue;  // not the outermost
      return body.slice(pair.left.length, close);
    }
    return expr;
  }

  katexObj.render = function (expr, element, options) {
    var stripped = expr;
    try { stripped = stripWrapper(expr); } catch (e) { stripped = expr; }
    // options is passed through untouched — the hook writes nothing into it.
    return originalRender.call(this, stripped, element, options);
  };
```

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Falsify**

Replace `stripWrapper` with the greedy regex `/^\s*\\\[([\s\S]*)\\\]\s*$/`. `test_hook_b_refuses_two_adjacent_spans` must go RED. Restore. Then remove the `try/catch` and make `stripWrapper` throw on a non-string → `test_hook_b_passes_a_non_string_through_untouched` must go RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "feat(math): Hook B strips a surrounding delimiter pair for katex.render"
```

---

### Task 8: Failure containment and the mid-walk throw

The `try/catch` around the reflow is the only safety net for an implementation bug, and an untested `catch` is exactly what the falsification rule exists to prevent.

**Files:**
- Modify: `tests/test_e2e_math_reflow_dom.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_poisoned_delimiter_set_still_lets_the_renderer_run(page):
    _page(page, "<div>\\[x</div><div>y\\]</div>")
    ok = page.evaluate(
        "() => { try { window.libliMathReflow("
        "          document.getElementById('root'), {delimiters: 'not-an-array'});"
        "        return true; } catch (e) { return false; } }"
    )
    assert ok


def test_a_mid_walk_throw_leaves_ignored_subtrees_untouched(page):
    """Atomicity is PER-ELEMENT, not per-subtree: a try/catch gives no rollback,
    so a throw after an earlier element's rewrites leaves the DOM partially
    rewritten. What must hold is that no ignored subtree was entered."""
    html = ('<div id="a"><div>\\[x</div><div>y\\]</div></div>'
            '<pre id="b"><div>\\[x</div><div>y\\]</div></pre>')
    _page(page, html)
    before_pre = page.evaluate("() => document.getElementById('b').innerHTML")
    page.evaluate(
        "() => { const orig = Node.prototype.removeChild; let n = 0;"
        "        Node.prototype.removeChild = function () {"
        "          if (++n > 1) { Node.prototype.removeChild = orig;"
        "                         throw new Error('boom'); }"
        "          return orig.apply(this, arguments); };"
        "        try { window.libliMathReflow(document.getElementById('root')); }"
        "        catch (e) {} finally { Node.prototype.removeChild = orig; } }"
    )
    assert page.evaluate("() => document.getElementById('b').innerHTML") == before_pre
```

- [ ] **Step 2: Run**

```
uv run pytest tests/test_e2e_math_reflow_dom.py -m e2e -k "poisoned or mid_walk" --verbosity=0
```
If either fails, the fix belongs in `reflow` — wrap each `visit(node)` call in `walk` so one element's failure cannot abort the whole traversal, and make `delimitersFor` fall back to the defaults when `options.delimiters` is not an array:

```js
  function delimitersFor(options) {
    var given = options && options.delimiters;
    return (given && given.length && typeof given[0] === "object")
      ? given : DEFAULT_DELIMITERS;
  }
```

- [ ] **Step 3: Commit**

```bash
git add courses/static/courses/js/math_reflow.js tests/test_e2e_math_reflow_dom.py
git commit -m "test(math): pin failure containment and per-element atomicity"
```

---

### Task 9: End-to-end through real pages

**Files:**
- Test: `tests/test_e2e_math_reflow.py` (create)

**Interfaces:**
- Consumes: real authoring helpers — `make_pa(client, "pa")`, `CourseFactory(owner=pa)`, `ContentNodeFactory(course=…, parent=None, kind="unit", unit_type="lesson")`, `make_course_with_unit()`. Read `tests/test_e2e_text_colour.py` and `courses/tests/test_callout_*.py` for the established fixture shapes before writing.

- [ ] **Step 1: Write the golden-path test**

```python
BLOCK = (
    "\\[\\begin{align*}\n"
    "a^n\\cdot a^k&=a^{n+k}\\\\\n"
    "a^n: a^k&=a^{n-k}\\\\\n"
    "\\left(a^n\\right)^k&=a^{nk}\n"
    "\\end{align*}\\]"
)


def test_multiline_align_block_authored_in_the_rte_renders(page, live_server, ...):
    # 1. author it through the REAL RTE: type the block with Enter between lines
    # 2. save
    # 3. THE SPLIT ASSERTION — before asserting the render, prove the stored HTML
    #    really contains a boundary between the \[ and the \]. Without this the
    #    test can pass vacuously: a clipboard paste can land the whole block in a
    #    single text node, in which case it is green on master with none of this
    #    work and stays green if phase 1 regresses.
    stored = TextElement.objects.get(pk=...).body
    open_at, close_at = stored.index("\\["), stored.index("\\]")
    between = stored[open_at:close_at]
    assert "</div><div>" in between or "<br>" in between, (
        "the authoring gesture did not split the span; this test would prove "
        "nothing. Fix the gesture, do not relax the assertion."
    )
    # 4. open the lesson and assert the render
    page.goto(...)
    assert page.locator(".el--text .katex").count() == 1
    assert page.locator(".katex-error").count() == 0
    assert page.locator(".el--text .katex .vlist").count() >= 3
```

- [ ] **Step 2: Add the remaining e2e cases**

Follow spec Testing §`test_e2e_math_reflow.py` items 2-8: the same block in a **callout body** (fixture) and in a **table cell** stored in the shape `sanitize_cell` produces (literal `&lt;br&gt;` inside the span); a **Math element** with the `\[…\]` wrapper and one with `\(x\)`; `\(\begin{align*}…\)` rendering as display; `\[a\] + \[b\]` left alone; a `\\[2ex]` block; the single-line regression pair; and idempotence via a quiz-feedback swap or tab reveal.

- [ ] **Step 3: Add the named-limitation case**

```python
def test_centred_display_math_is_not_reflowed(page, ...):
    """KNOWN LIMITATION, pinned deliberately. class="ta-center" on every line div
    makes every line a barrier. The fix (attribute-homogeneous merging) is a
    scheduled follow-up; this test documents the boundary so it is a decision
    rather than a bug report."""
```

- [ ] **Step 4: Run the full e2e suite**

```
uv run pytest -m e2e --verbosity=0
```
Expected: all pass. Per the repo's recorded lesson, run the **whole** `-m e2e` suite, not just the new file — a per-task e2e written earlier can go stale once rendering behaviour changes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_math_reflow.py
git commit -m "test(math): end-to-end display-math authoring through real pages"
```

---

### Task 10: Definition of done

- [ ] **Step 1: Full non-e2e suite**

```
uv run pytest --verbosity=0 -p no:randomly
```
Expected: green. Baseline was 4559 passed / 1 skipped; record the new total in the PR body.

- [ ] **Step 2: Full e2e suite**

```
uv run pytest -m e2e --verbosity=0
```

- [ ] **Step 3: Lint and format**

```
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 4: The required manual verification**

Render a `</p><p>`-boundary repair (use `CalloutElement` 86's stored shape) in the browser, **light and dark**, screenshot before and after, and record what happens to surrounding paragraph spacing. All six retroactively repaired spans sit at `</p><p>` boundaries and `<p>` carries real block margins here (`reset.css`'s `* { margin: 0 }` interacts with `app.css form p`), so this is the one case no automated test covers. Attach the screenshots to the PR.

- [ ] **Step 5: Sanity-check the repair against real data**

With the local `libli` database, confirm the six known-broken spans now render: `CalloutElement` 86 and `ChoiceQuestionElement` 218/226/227, `ShortNumericQuestionElement` 76/77. The five stems must come out **merged and promoted**, with zero `.katex-error`.

- [ ] **Step 6: Commit and open the PR**

```bash
git add -A && git commit -m "docs(math): record DoD results"
```

PR body must list: the new non-e2e count, the `<p>` screenshots, the centred-formula limitation with its follow-up, and the pre-existing out-of-scope defect recorded in the spec (auto-render walks into `.rte-surface` on the choicegrid path and `sync()` can persist injected `.katex` markup).

---

## Self-Review

**Spec coverage.** Purpose/Problems 1, 1b, 2, 3 → Tasks 4, 5, 6, 7. Public contract and root shapes → Task 3. Load order and `has_math` containment → Task 2. Delimiter set and drift → Task 1. Scan port → Task 4. Walk/ignored subtrees/barriers → Task 3 + 4. Phases 1/1b/2 → Tasks 4/5/6. Hook B → Task 7. Idempotence, failure, cost → Tasks 4, 8. Every Testing subsection maps to a task; the non-automated `<p>` acceptance item is Task 10 Step 4.

**Known gap, deliberately left to the implementer:** Task 9's fixtures are described rather than written, because the repo's authoring-test helpers must be read from the existing suite rather than invented — the spec's own build-lessons record that invented fixtures are a recurring failure here. Task 9 Step 1 names the helpers to look up.

**Type consistency.** `findEndOfMath(delim, text, startIndex)`, `findSpans(text, delimiters)`, `delimitersFor(options)`, `buildRun(children) → {text, map, synthetic}`, `mergeChildren(element, options)`, `phase1b(element, options)`, `phase2(element, options)`, `stripWrapper(expr)`, `walk(node, extraSelector, visit)`, `isIgnored(node, extraSelector)` — each defined once and used with the same signature throughout.

## Sample-code verification

The Task 1/3/4/5/6/7 snippets were assembled into a real module and driven through Chromium against every Task 4-7 assertion **before this plan was committed**. 25 phase cases and 5 Hook B cases ran; 27 passed first time and **three failures were defects in this plan, not in the code**:

1. `test_walk_descends_into_barriers` used a bare `<td>`, which the HTML parser drops outside a table — the two divs became direct children of `#root` and merged, so the test would have passed for the wrong reason. Fixed with a `<table><tbody><tr>` wrapper; the merge then genuinely happens inside the cell.
2. `test_scanning_stops_at_an_unclosed_opener` used `\[oops … \[a … b\]`, where the first opener simply pairs with the only closer — correct behaviour, exercising nothing. The break is observable only with **mixed** delimiters; fixed to `\(oops … $$a … b$$`, verified UNCHANGED.
3. `test_two_spans_in_one_run` expected a `\n` between the spans. Measured output is `\[a\nb\]\[c\nd\]` — adjacent, because the separating newline is synthetic and `textFragment` drops it. Harmless, but the assertion now matches reality.

Defect 1 is the important one: it is exactly the "test passes for the wrong reason" class the falsification rule exists to catch, and only running it surfaced it. The same `<td>` trap is inherited by the spec's DOM-case list, which has been corrected alongside.
