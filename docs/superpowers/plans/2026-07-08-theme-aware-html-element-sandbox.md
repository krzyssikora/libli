# Theme-aware HTML-element sandbox + mat-pp CSS rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sandboxed HTML-element content follow the app's light/dark theme — for the `mat-pp` course, fully (Option B: app brand palette) — while leaving every other course rendering exactly as today.

**Architecture:** The opaque-origin sandbox iframe learns the theme three ways: a four-part CSS token block (`@media` fallback), a server-baked `<html data-theme>` for explicit prefs, and a live `postMessage` bridge on the existing `courses/static/courses/js/html_element.js`. The shared layer is strictly additive (colour *variables* only; `_BASE_STYLE` unchanged); the `mat-pp` course opts into theming in its own CSS, shipped via a reversible data migration.

**Tech Stack:** Django 5, Python 3.13, `uv` for tooling, pytest, Playwright (e2e), vanilla JS (no framework), CSS custom properties + `color-mix`.

## Global Constraints

- Run all tooling via `uv run` (bash `ruff`/`pytest`/`python` are not on PATH). E.g. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`.
- The sandbox iframe is `sandbox="allow-scripts"` (opaque origin) — no `allow-same-origin`; cross-document `postMessage` uses target origin `"*"`.
- Colour-only for the `mat-pp` rewrite: selectors, layout, `!important`, images, `figure`/`embed`, structural table borders, and the entire `html_js` stay byte-for-byte except colour values.
- Message contract type string is exactly `"libli:htmlel:theme"`; theme values are exactly `"light"` / `"dark"`.
- Do not add hardcoded test passwords; use `tests.factories.TEST_PASSWORD` where a password is needed.
- No new third-party dependencies.

---

## File structure

- `courses/htmlsandbox.py` (modify) — token block builder, themed `build_srcdoc(theme=...)`, theme listener. Owns srcdoc assembly.
- `courses/models.py` (modify) — `HtmlElement.render(unit, course, theme=None)`.
- `courses/templatetags/courses_extras.py` (modify) — `render_element` gains `takes_context=True` and threads the theme.
- `courses/static/courses/js/html_element.js` (modify) — parent-side theme bridge (`postTheme`, `pingFrame` fold, `MutationObserver`).
- `courses/migrations/00NN_mat_pp_theme_css.py` (create) — reversible data migration.
- `courses/migrations/_mat_pp_baseline/html_css.txt`, `html_css_themed.txt`, `html_js.txt` (create) — committed baseline snapshot + rewritten CSS.
- Tests: `tests/test_htmlsandbox.py` (modify), `tests/test_html_element.py` (modify), `tests/test_e2e_html_element.py` (modify), `tests/test_mat_pp_theme.py` (create).

---

### Task 1: Sandbox token block, themed `build_srcdoc`, theme listener

**Files:**
- Modify: `courses/htmlsandbox.py`
- Test: `tests/test_htmlsandbox.py`

**Interfaces:**
- Consumes: existing `build_srcdoc(html, css, js, seed, *, origin)`, `_BASE_STYLE`, `_RESIZE_REPORTER`, `_katex_assets` pattern (`finders.find` + `lru_cache`).
- Produces: `build_srcdoc(html, css, js, seed, *, origin, theme=None)`; module constants `_theme_tokens()` (memoised), `_THEME_LISTENER`, `_NON_COLOUR_TOKEN_PREFIXES`, `_NON_COLOUR_TOKEN_NAMES`.

- [ ] **Step 1: Write the failing tests** in `tests/test_htmlsandbox.py`:

```python
from courses import htmlsandbox
from courses.htmlsandbox import build_srcdoc, _theme_tokens

ORIGIN = "https://sandbox.example"

def _doc(**kw):
    return build_srcdoc("<p>x</p>", "", "", "", origin=ORIGIN, **kw)

def test_base_style_unchanged_light_locked():
    # The shared base must NOT theme html/body — that would regress other courses.
    assert htmlsandbox._BASE_STYLE == "html,body{background:#fff;color:#111}"

def test_theme_tokens_four_part_and_colour_only():
    block = _theme_tokens()
    # light on :root, dark under @media and [data-theme="dark"], light restored under [data-theme="light"]
    assert ":root{" in block
    assert "@media(prefers-color-scheme:dark){:root{" in block
    assert ':root[data-theme="dark"]{' in block
    assert ':root[data-theme="light"]{' in block
    # a representative colour token appears with both its light and dark values
    assert "--surface-raised:#FFFFFF" in block or "--surface-raised: #FFFFFF" in block
    assert "--surface-raised:#2C2925" in block or "--surface-raised: #2C2925" in block
    # non-colour tokens are excluded
    assert "--radius-" not in block
    assert "--shadow-" not in block
    assert "--space-" not in block
    assert "--heading-letter-spacing" not in block
    # no color-scheme in the shared block (it belongs to the opting-in course)
    assert "color-scheme" not in block

def test_theme_tokens_brand_inputs_light_only():
    block = _theme_tokens()
    # --brand-primary is declared only under :root in tokens.css; it must appear
    # exactly once (light arm), never repeated into a dark arm.
    assert block.count("--brand-primary:") == 1

def test_build_srcdoc_bakes_data_theme_for_explicit_theme():
    assert '<html data-theme="dark">' in _doc(theme="dark")
    assert '<html data-theme="light">' in _doc(theme="light")

def test_build_srcdoc_no_data_theme_when_none():
    assert "data-theme" not in _doc(theme=None).split("<head>")[0]

def test_token_block_inserted_after_base_before_base_style():
    doc = _doc(theme="dark")
    i_base = doc.index("<base ")
    i_tokens = doc.index(":root[data-theme=")
    i_basestyle = doc.index(htmlsandbox._BASE_STYLE)
    assert i_base < i_tokens < i_basestyle

def test_theme_listener_present():
    assert "libli:htmlel:theme" in _doc()

def test_theme_tokens_match_tokens_css_full_set():
    # Anti-drift (spec-mandated): the sandbox block must define the SAME colour token
    # set as tokens.css, with equal values, for both themes — no missing/extra token.
    # A set-equality test (not spot-checks) is what catches a dropped token.
    import re as _re
    from pathlib import Path
    from django.contrib.staticfiles import finders
    from courses.htmlsandbox import _colour_decls  # shares the exclusion constant

    src = Path(finders.find("core/css/tokens.css")).read_text(encoding="utf-8")
    def _pairs(selector_re):
        m = _re.search(selector_re + r"\s*\{([^}]*)\}", src)
        decls = _colour_decls(m.group(1)) if m else ""
        return dict(
            (d.split(":", 1)[0].strip(), d.split(":", 1)[1].strip())
            for d in decls.split(";") if d.strip()
        )
    light = _pairs(r":root")
    dark = _pairs(r'\[data-theme="dark"\]')
    block = _theme_tokens()
    # every light token appears with its light value
    for name, val in light.items():
        assert f"{name}:{val}" in block, f"missing light {name}"
    # every dark token appears with its dark value (brand inputs are light-only,
    # so they are absent from `dark` and correctly not required here)
    for name, val in dark.items():
        assert f"{name}:{val}" in block, f"missing dark {name}"
    # representative tokens that a comment-swallowing bug would have dropped
    for name in ("--brand-primary", "--primary", "--surface-base", "--success"):
        assert name in light
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_htmlsandbox.py -k "theme or base_style or token" -v`
Expected: FAIL (`_theme_tokens` undefined / `theme` kwarg unexpected).

- [ ] **Step 3: Implement** in `courses/htmlsandbox.py`.

Add near the top (after imports), leaving `_BASE_STYLE` **unchanged**:

```python
# Colour tokens only: everything in tokens.css that is NOT one of these is a colour.
_NON_COLOUR_TOKEN_PREFIXES = ("--radius-", "--shadow-", "--font-", "--space-")
_NON_COLOUR_TOKEN_NAMES = ("--heading-letter-spacing",)

# Sets documentElement's data-theme from a parent postMessage. Sibling of _RESIZE_REPORTER.
_THEME_LISTENER = (
    "window.addEventListener('message',function(e){"
    "var d=e.data;"
    "if(d&&d.type==='libli:htmlel:theme'&&(d.theme==='light'||d.theme==='dark')){"
    "document.documentElement.setAttribute('data-theme',d.theme);}});"
)


def _colour_decls(block):
    # Strip CSS comments FIRST. tokens.css introduces each group with a comment on
    # the line above its first token; without this, that comment + the first token
    # land in one ";"-segment that fails the "--" check and the token is dropped
    # (would silently lose --brand-primary, --primary, --surface-base, --success, ...).
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    out = []
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl.startswith("--"):
            continue
        name = decl.split(":", 1)[0].strip()
        if name.startswith(_NON_COLOUR_TOKEN_PREFIXES) or name in _NON_COLOUR_TOKEN_NAMES:
            continue
        out.append(decl + ";")
    return "".join(out)


@lru_cache(maxsize=1)
def _theme_tokens():
    """Emit the app's colour tokens (from tokens.css) in the four-part theme pattern.

    Read-once/​memoised, mirroring _katex_assets. Single source of truth = tokens.css,
    so the sandbox palette can never drift from the app. tokens.css declares light on
    :root and dark on [data-theme="dark"]; brand inputs live only on :root, so the dark
    arms simply omit them and they inherit their light value (exactly as the app does)."""
    css = Path(finders.find("core/css/tokens.css")).read_text(encoding="utf-8")

    def _block(selector_re):
        m = re.search(selector_re + r"\s*\{([^}]*)\}", css)
        return m.group(1) if m else ""

    light = _colour_decls(_block(r":root"))
    dark = _colour_decls(_block(r'\[data-theme="dark"\]'))
    return (
        f":root{{{light}}}"
        f"@media(prefers-color-scheme:dark){{:root{{{dark}}}}}"
        f':root[data-theme="dark"]{{{dark}}}'
        f':root[data-theme="light"]{{{light}}}'
    )
```

Change `build_srcdoc`'s signature and head assembly:

```python
def build_srcdoc(html, css, js, seed, *, origin, theme=None):
    html = html or ""
    seed = (seed or "").strip()
    math = has_math_delimiters(html)
    html_open = (
        f'<html data-theme="{theme}">' if theme in ("light", "dark") else "<html>"
    )
    parts = [
        "<!doctype html>" + html_open + "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_csp(origin)}">',
        f'<base href="{origin}/">',
        f"<style>{_theme_tokens()}</style>",   # tokens: after <base>, before base style
        f"<style>{_BASE_STYLE}</style>",
    ]
```

Append the theme listener next to the resize reporter (find the line that appends `_RESIZE_REPORTER` and add, right before it):

```python
    parts.append(f"<script>{_THEME_LISTENER}</script>")
    parts.append(f"<script>{_RESIZE_REPORTER}</script>")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_htmlsandbox.py -v`
Expected: PASS (including the pre-existing tests — `build_srcdoc`'s existing positional calls are unaffected by the new keyword-only `theme`).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/htmlsandbox.py tests/test_htmlsandbox.py
uv run ruff format courses/htmlsandbox.py tests/test_htmlsandbox.py
git add courses/htmlsandbox.py tests/test_htmlsandbox.py
git commit -m "feat(htmlsandbox): inject app colour tokens + theme bake/listener into the sandbox"
```

---

### Task 2: Thread the resolved theme through render

**Files:**
- Modify: `courses/models.py` (`HtmlElement.render`)
- Modify: `courses/templatetags/courses_extras.py` (`render_element`)
- Test: `tests/test_html_element.py`

**Interfaces:**
- Consumes: `build_srcdoc(..., theme=...)` (Task 1); context vars `theme_pref` (`auto|light|dark`) and `data_theme` (`light|dark`) from `core/context_processors.py`.
- Produces: `HtmlElement.render(self, unit, course, theme=None)`; `render_element` now `takes_context=True`.

- [ ] **Step 1: Write the failing tests** in `tests/test_html_element.py`:

```python
import html as _html
from django.template import Context, Template

def _render(unit_el, **ctx):
    # render_element -> HtmlElement.render -> template srcdoc="{{ doc }}", which
    # HTML-attribute-escapes the whole srcdoc. Unescape so we can assert on the raw
    # sandbox document. NOTE: the token block always contains :root[data-theme="dark"];
    # to detect the BAKE specifically, assert on the "<html data-theme=" opening tag,
    # which the token block never produces.
    tpl = Template("{% load courses_extras %}{% render_element el %}")
    return _html.unescape(tpl.render(Context({"el": unit_el, **ctx})))

@pytest.mark.django_db
def test_render_element_bakes_explicit_dark(html_element_join):  # fixture: an Element w/ HtmlElement
    out = _render(html_element_join, theme_pref="dark", data_theme="dark")
    assert '<html data-theme="dark">' in out

@pytest.mark.django_db
def test_render_element_bakes_explicit_light(html_element_join):
    out = _render(html_element_join, theme_pref="light", data_theme="light")
    assert '<html data-theme="light">' in out

@pytest.mark.django_db
def test_render_element_no_bake_for_auto(html_element_join):
    out = _render(html_element_join, theme_pref="auto", data_theme="light")
    assert "<html data-theme=" not in out       # token block's [data-theme=...] is fine

@pytest.mark.django_db
def test_render_element_no_bake_when_context_absent(html_element_join):
    out = _render(html_element_join)            # no theme keys
    assert "<html data-theme=" not in out
```

Add a small fixture near the top of the file if one does not already exist (reuse the module's existing course/unit/HtmlElement construction pattern):

```python
@pytest.fixture
def html_element_join(db):
    from courses.models import Course, ContentNode, HtmlElement, Element
    course = Course.objects.create(title="C", slug="c-theme", html_css="", html_js="")
    unit = ContentNode.objects.create(course=course, kind="unit",
                                      unit_type="lesson", title="U")
    el = HtmlElement.objects.create(html="<p>x</p>")
    return Element.objects.create(unit=unit, content_object=el)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_html_element.py -k "bake or no_bake" -v`
Expected: FAIL (theme not baked; `render_element` ignores context).

- [ ] **Step 3: Implement.**

`courses/models.py` — `HtmlElement.render`:

```python
    def render(self, unit, course, theme=None):
        from django.conf import settings
        from courses import htmlsandbox

        doc = htmlsandbox.build_srcdoc(
            self.html, course.html_css, course.html_js, unit.html_seed_js,
            origin=settings.HTMLEL_SANDBOX_ORIGIN, theme=theme,
        )
        return render_to_string("courses/elements/htmlelement.html", {"doc": doc})
```

`courses/templatetags/courses_extras.py` — add `takes_context=True` and thread the theme:

```python
@register.simple_tag(takes_context=True)
def render_element(
    context,
    element,
    feedback_for_pk=None,
    # ... (all existing params unchanged) ...
):
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        pref = context.get("theme_pref")
        theme = context.get("data_theme") if pref in ("light", "dark") else None
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course, theme=theme))  # noqa: S308
    # ... rest unchanged ...
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_html_element.py -v`
Expected: PASS. Then confirm no direct-Python callers break and templates still render:
Run: `uv run pytest tests/test_courses_elements.py tests/test_html_element.py -v`
Expected: PASS (the existing `{% render_element el %}` call sites are unaffected by `takes_context`).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/models.py courses/templatetags/courses_extras.py tests/test_html_element.py
uv run ruff format courses/models.py courses/templatetags/courses_extras.py tests/test_html_element.py
git add courses/models.py courses/templatetags/courses_extras.py tests/test_html_element.py
git commit -m "feat(courses): thread resolved theme into HtmlElement.render via render_element"
```

---

### Task 3: Parent-side theme bridge in `html_element.js`

**Files:**
- Modify: `courses/static/courses/js/html_element.js`
- Test: `tests/test_htmlsandbox.py` (a static-presence assertion; behavioural coverage is the e2e in Task 4)

**Interfaces:**
- Consumes: existing `pingFrame(frame)` + `.html-el iframe` enumeration; the srcdoc `_THEME_LISTENER` (Task 1); `<html data-theme>` kept current by `base.html` pre-paint + `ui.js` toggle.
- Produces: `postTheme(frame)` folded into `pingFrame`; a `MutationObserver` on `document.documentElement[data-theme]`. **No `ui.js` change.**

- [ ] **Step 1: Write the failing test** (static presence) in `tests/test_htmlsandbox.py`:

```python
from pathlib import Path
from django.contrib.staticfiles import finders

def test_html_element_js_has_theme_bridge():
    src = Path(finders.find("courses/js/html_element.js")).read_text(encoding="utf-8")
    assert "libli:htmlel:theme" in src
    assert "MutationObserver" in src
    assert "data-theme" in src
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_htmlsandbox.py::test_html_element_js_has_theme_bridge -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — extend `courses/static/courses/js/html_element.js` inside the existing IIFE.

Add a theme helper and fold it into `pingFrame`'s `ask`:

```javascript
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme");  // live resolved value
  }
  function postTheme(frame) {
    var t = currentTheme();
    if (t !== "light" && t !== "dark") return;
    try { frame.contentWindow.postMessage({ type: "libli:htmlel:theme", theme: t }, "*"); }
    catch (err) { /* frame not ready; its load handler retries */ }
  }
```

In `pingFrame`, extend `ask` to also push the theme:

```javascript
  function pingFrame(frame) {
    function ask() {
      try { frame.contentWindow.postMessage({ type: "libli:htmlel:req" }, "*"); }
      catch (err) { /* frame not ready yet — its load handler will retry */ }
      postTheme(frame);            // send current theme on the same schedule as height
    }
    ask();
    frame.addEventListener("load", ask);
  }
```

At the end of the IIFE (after `requestHeights` is wired), re-broadcast on any theme change:

```javascript
  // Live theme flips: the app toggle (ui.js) stamps data-theme on <html>; mirror it
  // into every HTML-element sandbox. Decoupled through the DOM attribute — no ui.js change.
  new MutationObserver(function () {
    var frames = document.querySelectorAll(".html-el iframe");
    for (var i = 0; i < frames.length; i++) postTheme(frames[i]);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_htmlsandbox.py::test_html_element_js_has_theme_bridge -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/html_element.js tests/test_htmlsandbox.py
git commit -m "feat(html_element.js): live theme bridge for sandbox iframes (postTheme + observer)"
```

---

### Task 4: E2E — the real toggle flips the sandbox theme

**Files:**
- Modify: `tests/test_e2e_html_element.py`
- Test: itself

**Interfaces:**
- Consumes: Tasks 1–3; this file's existing helpers `_make_pa_user(username)`, `_login(page, live_server, username)`, `_seed_html_unit(slug, viewer)` (returns the lesson URL path, enrolls `viewer`); the app theme toggle `[data-theme-toggle]`. The page is login+enrollment gated, and `User.theme` (authed) **wins over** the `libli_theme` cookie (`core/context_processors.py::_resolve_theme_pref`), so determinism comes from the user's DB `theme`, not a cookie.

- [ ] **Step 1: Write the failing test** in `tests/test_e2e_html_element.py`. Read the sandbox's `data-theme` from **inside** the opaque frame (parent `contentDocument` is blocked); make the baseline deterministic by setting the enrolled user's `theme="dark"`.

```python
@pytest.mark.django_db(transaction=True)
def test_toggle_flips_sandbox_theme(live_server, page):
    user = _make_pa_user("theme_viewer")
    user.theme = "dark"          # authed User.theme wins -> deterministic baked data-theme
    user.save(update_fields=["theme"])
    url = _seed_html_unit("theme-course", user)   # enrolls user, returns lesson path
    _login(page, live_server, "theme_viewer")
    page.goto(f"{live_server.url}{url}")

    page.locator("iframe.html-el__frame").first.scroll_into_view_if_needed()
    frame = page.frame_locator("iframe.html-el__frame").first

    def frame_theme():
        return frame.locator(":root").get_attribute("data-theme")

    assert frame_theme() == "dark"                       # baked (User.theme=dark)
    page.click("[data-theme-toggle]")                    # REAL toggle (dark -> auto/light cycle)
    page.wait_for_function(
        "document.documentElement.getAttribute('data-theme') !== 'dark'"
    )
    parent_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    # wait for the postMessage bridge to apply inside the frame (poll, not fixed sleep)
    page.wait_for_function(
        "(t) => { const f=document.querySelector('iframe.html-el__frame');"
        " try { return f.contentDocument === null; } catch(e){ return true; } }", arg=None
    )
    import time; time.sleep(0.1)                          # brief settle for the cross-doc post
    assert frame_theme() == parent_theme                 # sandbox followed the flip
```

(The frame is opaque-origin so `contentDocument` throws/`null`; the assertion reads via the Playwright frame API. If the post-toggle read is flaky, poll `frame_theme()` in a short retry loop rather than lengthening the sleep.)

- [ ] **Step 2: Run to verify pass** (Tasks 1–3 must be in)

Run: `uv run pytest tests/test_e2e_html_element.py::test_toggle_flips_sandbox_theme -v -m e2e`
Expected: PASS. If flaky on the post-toggle read, retry-poll `frame_theme()` for equality with `parent_theme` rather than a fixed sleep.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_html_element.py
git commit -m "test(e2e): real theme toggle flips the sandbox iframe theme"
```

---

### Task 5: `mat-pp` baseline capture, CSS rewrite, reversible migration

**Files:**
- Create: `courses/migrations/_mat_pp_baseline/html_css.txt`, `html_css_themed.txt`, `html_js.txt`
- Create: `courses/migrations/00NN_mat_pp_theme_css.py`
- Create: `tests/test_mat_pp_theme.py`

**Interfaces:**
- Consumes: the app colour tokens now available inside the sandbox (Task 1).
- Produces: a data migration setting `Course.html_css` for `slug="mat-pp"`.

> **Placeholder substitution — do this first.** `00NN` (migration filename), `<NN>` (test import), and `<latest_courses_migration>` (dependency) are placeholders. List `courses/migrations/`, find the highest-numbered migration `NNNN_*`, and substitute the next number consistently into: the migration filename, the `git add` path (Step 5), the `dependencies` entry (Step 3), and the test's `importlib.import_module("courses.migrations.<NN>_mat_pp_theme_css")` (Step 4). No placeholder may remain in any file or command that runs.

- [ ] **Step 1: Capture the baseline (pre-flight gate).** Export the current `mat-pp` CSS/JS from the local DB, UTF-8, into the committed baseline dir. **Abort the task loudly if the export is empty** — never fabricate the ~900 lines.

```bash
mkdir -p courses/migrations/_mat_pp_baseline   # dir must exist before the writes below
uv run python manage.py shell -c "import io; from courses.models import Course; c=Course.objects.get(slug='mat-pp'); io.open('courses/migrations/_mat_pp_baseline/html_css.txt','w',encoding='utf-8').write(c.html_css); io.open('courses/migrations/_mat_pp_baseline/html_js.txt','w',encoding='utf-8').write(c.html_js)"
# verify non-empty:
test -s courses/migrations/_mat_pp_baseline/html_css.txt || { echo "ABORT: baseline empty"; exit 1; }
```

No `__init__.py` is needed in `_mat_pp_baseline/` — nothing imports it as a package; the migration and tests read the `.txt` files by filesystem path only.

- [ ] **Step 2: Produce `html_css_themed.txt`** — the rewritten CSS, derived from `html_css.txt`, applying (verbatim from the spec):
  - **Move 0 — theme adoption** (prepend):
    ```css
    html,body{background:var(--surface-raised);color:var(--text-primary)}
    :root{color-scheme:light}
    @media(prefers-color-scheme:dark){:root{color-scheme:dark}}
    :root[data-theme="dark"]{color-scheme:dark}
    :root[data-theme="light"]{color-scheme:light}
    ```
  - **Move (a) — redefine the course's own `:root` colour vars** (confirm names against the baseline first):
    `--colour-light-background: var(--surface-sunken)`; `--colour-light-blue: var(--primary-subtle)`; `--colour-blue-border: var(--primary)`; `--colour-light-green: var(--success-subtle)`; `--colour-light-red: var(--danger-subtle)`. Leave dimension vars untouched.
  - **Move (b) — sweep literals** onto tokens per the spec's mapping table (surfaces→`--surface-raised/-sunken`; text→`--text-primary/-secondary`; borders→`--border-default/-strong`; question blue/`navy`/`#202060`/`#022A87`→`--primary`; blue button fg white→`--text-inverse`; `orangered`→`--warning`; `green`/`darkgreen`→`--success`; `red`→`--danger`).
  - **Keep** decorative colour-demo literals verbatim (`.red_on_yellow`, `.blue_on_green`, `.magenta_on_gray`, `.yellow_on_gray`), plus any other deliberately-kept literal — each must be listed in `KEPT` (Step 4's allowlist) with a justification.

- [ ] **Step 3: Write the migration** `courses/migrations/00NN_mat_pp_theme_css.py` (set `NN`/dependency to the current latest `courses` migration):

Embed the CSS as **string literals** (spec: no runtime file IO at replay — a migration must not depend on sibling files still existing). Paste the exact contents of the two baseline files into raw triple-quoted strings (CSS contains no `"""` and no trailing backslash, so a raw string is safe; the `_mat_pp_baseline/*.txt` files remain committed as the auditable source the literals are pasted from, and Step 4 asserts the literals match them):

```python
from django.db import migrations

# Paste _mat_pp_baseline/html_css.txt verbatim:
OLD_CSS = r"""...ORIGINAL mat-pp html_css..."""
# Paste _mat_pp_baseline/html_css_themed.txt verbatim:
NEW_CSS = r"""...REWRITTEN themed html_css..."""


def _set(apps, css):
    Course = apps.get_model("courses", "Course")
    Course.objects.filter(slug="mat-pp").update(html_css=css)  # guarded: no-op if absent


def forward(apps, schema_editor):
    _set(apps, NEW_CSS)


def reverse(apps, schema_editor):
    _set(apps, OLD_CSS)


class Migration(migrations.Migration):
    dependencies = [("courses", "<latest_courses_migration>")]
    operations = [migrations.RunPython(forward, reverse)]
```

- [ ] **Step 4: Write completeness + round-trip tests** `tests/test_mat_pp_theme.py`:

```python
import re
from pathlib import Path
import pytest

BASE = Path("courses/migrations/_mat_pp_baseline")
THEMED = (BASE / "html_css_themed.txt").read_text(encoding="utf-8")

# Every literal deliberately kept, matched by selector+declaration (context-scoped), each justified.
KEPT = [
    (".red_on_yellow", "color:red"),      # colour-demo utility: intent is the literal red
    (".red_on_yellow", "background-color:yellow"),
    (".blue_on_green", "color:blue"),
    (".blue_on_green", "background-color:rgb(130,200,130)"),
    (".magenta_on_gray", "color:magenta"),
    (".magenta_on_gray", "background-color:lightgray"),
    (".yellow_on_gray", "color:yellow"),
    (".yellow_on_gray", "background-color:lightgray"),
    # ... add any other deliberately-kept literal discovered during the sweep, with a comment ...
]

# Complete CSS named-colour set (CSS Color Module Level 4). Keep the full list.
NAMED_COLOURS = {
    "aliceblue","antiquewhite","aqua","aquamarine","azure","beige","bisque","black",
    "blanchedalmond","blue","blueviolet","brown","burlywood","cadetblue","chartreuse",
    "chocolate","coral","cornflowerblue","cornsilk","crimson","cyan","darkblue","darkcyan",
    "darkgoldenrod","darkgray","darkgreen","darkgrey","darkkhaki","darkmagenta","darkolivegreen",
    "darkorange","darkorchid","darkred","darksalmon","darkseagreen","darkslateblue","darkslategray",
    "darkslategrey","darkturquoise","darkviolet","deeppink","deepskyblue","dimgray","dimgrey",
    "dodgerblue","firebrick","floralwhite","forestgreen","fuchsia","gainsboro","ghostwhite","gold",
    "goldenrod","gray","green","greenyellow","grey","honeydew","hotpink","indianred","indigo",
    "ivory","khaki","lavender","lavenderblush","lawngreen","lemonchiffon","lightblue","lightcoral",
    "lightcyan","lightgoldenrodyellow","lightgray","lightgreen","lightgrey","lightpink","lightsalmon",
    "lightseagreen","lightskyblue","lightslategray","lightslategrey","lightsteelblue","lightyellow",
    "lime","limegreen","linen","magenta","maroon","mediumaquamarine","mediumblue","mediumorchid",
    "mediumpurple","mediumseagreen","mediumslateblue","mediumspringgreen","mediumturquoise",
    "mediumvioletred","midnightblue","mintcream","mistyrose","moccasin","navajowhite","navy",
    "oldlace","olive","olivedrab","orange","orangered","orchid","palegoldenrod","palegreen",
    "paleturquoise","palevioletred","papayawhip","peachpuff","peru","pink","plum","powderblue",
    "purple","rebeccapurple","red","rosybrown","royalblue","saddlebrown","salmon","sandybrown",
    "seagreen","seashell","sienna","silver","skyblue","slateblue","slategray","slategrey","snow",
    "springgreen","steelblue","tan","teal","thistle","tomato","turquoise","violet","wheat","white",
    "whitesmoke","yellow","yellowgreen",
}
NEUTRAL_KEYWORDS = {"transparent", "currentcolor", "inherit", "initial", "unset", "none"}

def _declarations(css):
    """Yield (selector_context, name, value) for each declaration value (right of : to ;)."""
    # crude but sufficient: strip comments, split rule blocks
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        sel = m.group(1).strip()
        for decl in m.group(2).split(";"):
            if ":" in decl:
                name, _, val = decl.partition(":")
                yield sel, name.strip(), val.strip()

def _is_allowlisted(sel, name, val):
    decl = f"{name}:{val}".replace(" ", "")
    return any(a_sel in sel and a_decl.replace(" ", "") == decl for a_sel, a_decl in KEPT)

def test_no_residual_colour_literals():
    offenders = []
    for sel, name, val in _declarations(THEMED):
        if _is_allowlisted(sel, name, val):
            continue
        # Keep legitimately-kept, non-colour value content out of the scan: image
        # refs (url(icons/red.png)) and quoted strings (content:"...") can contain
        # colour words that are NOT colour literals. The plan keeps images/content
        # byte-for-byte, so strip them before matching.
        scan = re.sub(r"url\([^)]*\)", "", val)
        scan = re.sub(r"\"[^\"]*\"|'[^']*'", "", scan)
        # hex / rgb()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", scan) or re.search(r"\brgba?\(", scan):
            offenders.append((sel, name, val))
            continue
        # named colours as COMPLETE value tokens only (never inside var(--...) / identifiers)
        for tok in re.findall(r"(?<![\w-])[a-zA-Z]+(?![\w-])", scan):
            low = tok.lower()
            if low in NEUTRAL_KEYWORDS:
                continue
            if low in NAMED_COLOURS:
                offenders.append((sel, name, val))
                break
    assert not offenders, f"residual colour literals: {offenders[:20]}"

def test_theme_adoption_preamble_present():
    assert "html,body{background:var(--surface-raised);color:var(--text-primary)}" in THEMED.replace(" ", "").replace("\n", "") or \
           "html,body{background:var(--surface-raised)" in THEMED
    assert "color-scheme:dark" in THEMED
    assert 'var(--colour-light-blue' not in THEMED or "--colour-light-blue:var(--primary-subtle)" in THEMED.replace(" ", "")

@pytest.mark.django_db
def test_migration_roundtrip_and_guarded_noop():
    import importlib
    from django.apps import apps as django_apps
    from courses.models import Course

    # <NN> substituted with the real migration number (see the placeholder note above)
    mig = importlib.import_module("courses.migrations.<NN>_mat_pp_theme_css")

    # the embedded literals must equal the committed baseline source files (no paste drift)
    assert mig.NEW_CSS == THEMED
    assert mig.OLD_CSS == (BASE / "html_css.txt").read_text(encoding="utf-8")

    # guarded no-op when the course is absent
    mig.forward(django_apps, None)  # must not raise

    c = Course.objects.create(title="M", slug="mat-pp", html_css=mig.OLD_CSS, html_js="x")
    mig.forward(django_apps, None)
    c.refresh_from_db()
    assert c.html_css == mig.NEW_CSS and c.html_js == "x"   # forward applied, js untouched
    mig.reverse(django_apps, None)
    c.refresh_from_db()
    assert c.html_css == mig.OLD_CSS                        # reverse restores baseline exactly
```

- [ ] **Step 5: Run + verify + commit**

```bash
uv run python manage.py makemigrations --check --dry-run   # ensure no model drift
uv run pytest tests/test_mat_pp_theme.py -v
```
Expected: PASS. Iterate on `html_css_themed.txt` until `test_no_residual_colour_literals` passes with only the justified `KEPT` entries.

```bash
git add courses/migrations/_mat_pp_baseline courses/migrations/00NN_mat_pp_theme_css.py tests/test_mat_pp_theme.py
git commit -m "feat(mat-pp): theme-aware CSS rewrite via reversible data migration"
```

---

### Task 6: Apply migration, visual QA, full regression

**Files:** none (verification task)

- [ ] **Step 1: Apply the migration** against the local DB and confirm the `mat-pp` course updated:

```bash
uv run python manage.py migrate courses
```

- [ ] **Step 2: Visual QA** (per the "verify UI with screenshots" rule). Launch the app, open a `mat-pp` lesson containing HTML elements, screenshot in **light** and **dark** (toggle via the header control). Self-critique contrast/legibility of: question boxes, worked examples, equation boxes, `.important` notes, true/false + single-choice widgets, tables, correct/wrong states, and action buttons. Confirm the button is no longer low-contrast white-on-pale-blue. Note (do not fix) the accepted post-toggle lazy-frame one-frame flash if seen.

- [ ] **Step 3: Full regression**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Expected: all green. If any i18n catalog test runs, ensure no translatable strings were altered (none expected).

- [ ] **Step 4: Commit** any QA-driven colour tweaks to `html_css_themed.txt` (re-run Task 5 tests first), else nothing to commit.

```bash
git add -A && git commit -m "chore(mat-pp): visual-QA colour adjustments" || echo "no QA changes"
```

---

## Self-review notes

- **Spec coverage:** Component 1 → Task 1; Components 2–3 → Task 2; Component 4 → Task 3; live-bridge e2e → Task 4; Component 5 (delivery + rewrite + all rewrite tests) → Task 5; visual QA + regression → Task 6. Token sync/anti-drift is satisfied by construction (Task 1 reads tokens.css) and asserted in Task 1's tests.
- **Types:** `build_srcdoc(..., theme=None)` and `HtmlElement.render(..., theme=None)` and `render_element(context, ...)` are consistent across Tasks 1–2. Message contract `{type:"libli:htmlel:theme", theme}` is identical in the srcdoc listener (Task 1) and `postTheme` (Task 3).
- **Determinism:** the residual scan matches named colours only as complete value tokens (`(?<![\w-])…(?![\w-])`), so `var(--colour-light-blue)` etc. never false-positive; neutral keywords exempt; allowlist context-scoped.
