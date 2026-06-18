# Phase 1b-iii — HTML element (sandboxed author HTML/CSS/JS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sandboxed **HTML element** type that runs author-supplied HTML/CSS/JS inside an opaque-origin iframe, with course-wide CSS/JS + a per-unit JS seed injected server-side, KaTeX auto-render for `\(…\)`/`\[…\]` math, and a single integer-only resize channel — rendering identically in the student lesson view and the 1b-ii editor preview.

**Architecture:** A new `HtmlElement` concrete element model stores raw `html` (no sanitization — containment is the iframe, not nh3). At render time a pure assembly module (`courses/htmlsandbox.py`) builds one complete HTML document string from the element's `html` + the course's `html_css`/`html_js` + the unit's `html_seed_js` + (gated) vendored KaTeX + a resize reporter, and the element template drops that document into `<iframe sandbox="allow-scripts" srcdoc="…">` (Django auto-escapes the attribute). `render_element` resolves unit/course from the `Element` join-row and calls a contextual `HtmlElement.render(unit, course)` override. A small parent-side `html_element.js` listens for the iframe's height message and sizes it.

**Tech Stack:** Django 5.2 (server-rendered), pytest + pytest-django, Playwright (e2e), vendored KaTeX 0.16.11 (+ its auto-render extension), WhiteNoise static serving, django-environ settings.

## Global Constraints

- **`sandbox="allow-scripts"` only — `allow-same-origin` is NEVER set** on the HTML-element iframe (this omission is the entire security guarantee). No other `allow-*` flags.
- **No nh3 / no sanitization** on `HtmlElement.html`: it is stored and rendered verbatim. The element template MUST NOT use the `{% sanitize %}` filter, and the form MUST NOT add any tag-stripping `clean_html`.
- **`srcdoc` is attribute-escaped** by Django auto-escaping (the assembly module returns the raw document string; the template places it in `srcdoc="{{ doc }}"`). Never `mark_safe` the document string itself.
- **Resize message contract (single source of truth):** `{ type: "libli:htmlel:height", h: <integer px> }`. Height clamped to `[MIN_IFRAME_HEIGHT, MAX_IFRAME_HEIGHT] = [40, 20000]`. Listener validates by `event.source` identity against `.html-el iframe` only.
- **`<APP_ORIGIN>`** for the in-sandbox CSP and `<base href>` comes from a trusted setting `HTMLEL_SANDBOX_ORIGIN`, never from the request `Host` header.
- **In-sandbox CSP** (inside the srcdoc): `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src <APP_ORIGIN> data:; font-src <APP_ORIGIN> data:; connect-src 'none'`.
- **Math gating predicate:** inject KaTeX iff the raw `html` contains the substring `\(` or `\[`. Delimiters: `\(…\)` inline, `\[…\]` display. `$$` is NOT supported.
- **DoD gate (Task 10):** `uv run pytest -q` (+ e2e), `uv run ruff check .`, `uv run ruff format --check .`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check` (the one new migration applied), `uv run python manage.py collectstatic --noinput`, `uv run python manage.py compilemessages -l pl` — all clean.
- Run all Python via `uv run` (uv manages 3.13). Commit after every task.

---

## File Structure

- **Create** `courses/htmlsandbox.py` — pure srcdoc assembly: `build_srcdoc()`, `has_math_delimiters()`, cached KaTeX asset loader (+ absolute font-URL rewrite), CSP builder, height constants, the in-sandbox reporter + auto-render JS strings.
- **Create** `templates/courses/elements/htmlelement.html` — `.html-el` wrapper + escaped-`srcdoc` iframe.
- **Create** `templates/courses/manage/editor/_edit_html.html` — the HTML-body code textarea editor partial.
- **Create** `courses/static/courses/js/html_element.js` — parent-side resize listener.
- **Create** `courses/static/courses/vendor/katex/contrib/auto-render.min.js` — vendored KaTeX auto-render (0.16.11).
- **Create** `tests/test_htmlsandbox.py`, `tests/test_html_element.py`, `tests/test_e2e_html_element.py`.
- **Modify** `courses/models.py` — `HtmlElement` model, `Course.html_css`/`html_js`, `ContentNode.html_seed_js`, `ELEMENT_MODELS`.
- **Modify** `courses/templatetags/courses_extras.py` — `render_element` dispatch.
- **Modify** `courses/element_forms.py` — `HtmlElementForm` + `FORM_FOR_TYPE`.
- **Modify** `courses/views_manage.py` — `"html"` in the two type-key tuples; `_editor_rows` select_related.
- **Modify** `courses/views.py` — lesson queryset select_related + `has_html` context.
- **Modify** `courses/forms.py` — `CourseForm` gains `html_css`/`html_js`.
- **Modify** `templates/courses/manage/editor/_add_menu.html` — 6th "HTML" card.
- **Modify** `templates/courses/lesson_unit.html` — load `html_element.js` gated on `has_html`.
- **Modify** `templates/courses/manage/editor/editor.html` — load `html_element.js` unconditionally.
- **Modify** `courses/static/courses/css/courses.css` — `.html-el` styles.
- **Modify** `config/settings/base.py`, `config/settings/test.py` — `HTMLEL_SANDBOX_ORIGIN`.
- **New migration** `courses/migrations/0010_htmlelement_and_html_fields.py` (Task 1).

---

### Task 1: `HtmlElement` model + course/unit HTML fields + migration

**Files:**
- Modify: `courses/models.py` (add fields after `Course.updated`; add `html_seed_js` after `ContentNode.updated`; add `HtmlElement` after `MathElement`; extend `ELEMENT_MODELS`)
- Create: `courses/migrations/0010_htmlelement_and_html_fields.py` (via makemigrations)
- Test: `tests/test_html_element.py`

**Interfaces:**
- Produces: `HtmlElement(html: TextField)` with `elements = GenericRelation(Element)` and an override `render(self, unit, course) -> str` (the override body lands in Task 4; in this task `HtmlElement` may temporarily inherit the base `render`). **Ordering constraint:** nothing may *render* an HtmlElement-backed `Element` until Task 4 — the `htmlelement.html` template and the `render_element` dispatch land together there, so calling the base zero-arg `render()` before then raises `TemplateDoesNotExist`. Task 1's delete test constructs an `Element` but never renders it, so it is safe. `Course.html_css`, `Course.html_js`, `ContentNode.html_seed_js` (all `TextField(blank=True)`). `ELEMENT_MODELS` includes `"htmlelement"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_element.py
import pytest

from courses.models import (
    Course,
    ContentNode,
    Element,
    HtmlElement,
    ELEMENT_MODELS,
)


def test_htmlelement_in_element_models():
    assert "htmlelement" in ELEMENT_MODELS


@pytest.mark.django_db
def test_htmlelement_stores_raw_html_unsanitized():
    el = HtmlElement.objects.create(html='<script>alert(1)</script><b>x</b>')
    el.refresh_from_db()
    # Containment is the iframe, not sanitization — markup is stored verbatim.
    assert el.html == '<script>alert(1)</script><b>x</b>'


@pytest.mark.django_db
def test_course_and_unit_html_fields_default_empty():
    course = Course.objects.create(title="C", slug="c")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    assert course.html_css == "" and course.html_js == ""
    assert unit.html_seed_js == ""


@pytest.mark.django_db
def test_htmlelement_cascades_join_row_on_delete():
    course = Course.objects.create(title="C", slug="c2")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    el = HtmlElement.objects.create(html="<p>hi</p>")
    Element.objects.create(unit=unit, content_object=el)
    assert Element.objects.count() == 1
    el.delete()  # concrete-first delete cascades the join row via GenericRelation
    assert Element.objects.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_html_element.py -q`
Expected: FAIL (`ImportError: cannot import name 'HtmlElement'`).

- [ ] **Step 3: Add the model + fields**

In `courses/models.py`, add to `Course` (after the `updated` field):

```python
    html_css = models.TextField(blank=True)
    html_js = models.TextField(blank=True)
```

Add to `ContentNode` (after its `updated` field):

```python
    html_seed_js = models.TextField(blank=True)  # per-unit seed; dormant on non-units
```

Add after the `MathElement` class:

```python
class HtmlElement(ElementBase):
    html = models.TextField(blank=True)  # raw author HTML/CSS/JS — NOT sanitized
    elements = GenericRelation(Element)
    # render(self, unit, course) override is added in Task 4.
```

Extend `ELEMENT_MODELS`:

```python
ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
    "htmlelement",
]
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses --name htmlelement_and_html_fields`
Expected: creates `courses/migrations/0010_htmlelement_and_html_fields.py` adding `HtmlElement`, `Course.html_css`, `Course.html_js`, `ContentNode.html_seed_js`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_html_element.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/0010_htmlelement_and_html_fields.py tests/test_html_element.py
git commit -m "feat(1b-iii): HtmlElement model + course/unit HTML fields"
```

---

### Task 2: Vendor the KaTeX auto-render extension

**Files:**
- Create: `courses/static/courses/vendor/katex/contrib/auto-render.min.js`

**Interfaces:**
- Produces: a vendored `auto-render.min.js` (KaTeX 0.16.11) that defines the global `renderMathInElement`, consumed by the assembly module in Task 3.

> This task acquires a static asset (no code/test cycle). The file must match the **already-vendored KaTeX 0.16.11** (`courses/static/courses/vendor/katex/katex.min.js`). Obtain `dist/contrib/auto-render.min.js` from the KaTeX 0.16.11 release (the same distribution the existing `katex.min.js`/`katex.min.css` came from). **If network access is unavailable in the execution environment, pause and ask the user to drop the file at the path above** before continuing.

- [ ] **Step 1: Place the file**

Save the KaTeX 0.16.11 `auto-render.min.js` to `courses/static/courses/vendor/katex/contrib/auto-render.min.js`.

- [ ] **Step 2: Verify it is the right asset**

Run: `grep -c "renderMathInElement" courses/static/courses/vendor/katex/contrib/auto-render.min.js`
Expected: ≥ 1 (the file defines/exports `renderMathInElement`).

- [ ] **Step 3: Verify collectstatic picks it up**

Run: `uv run python manage.py collectstatic --noinput`
Expected: completes without error; the contrib file is among the collected files.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/vendor/katex/contrib/auto-render.min.js
git commit -m "chore(1b-iii): vendor KaTeX auto-render extension (0.16.11)"
```

---

### Task 3: `courses/htmlsandbox.py` — srcdoc assembly + settings origin

**Files:**
- Create: `courses/htmlsandbox.py`
- Modify: `config/settings/base.py` (add `HTMLEL_SANDBOX_ORIGIN`), `config/settings/test.py` (pin it)
- Test: `tests/test_htmlsandbox.py`

**Interfaces:**
- Consumes: vendored KaTeX files (Task 2) via staticfiles finders.
- Produces:
  - `MIN_IFRAME_HEIGHT = 40`, `MAX_IFRAME_HEIGHT = 20000`
  - `has_math_delimiters(html: str) -> bool`
  - `build_srcdoc(html: str, css: str, js: str, seed: str, *, origin: str) -> str` — returns the full, **un-escaped** HTML document string.

- [ ] **Step 1: Add the setting**

In `config/settings/base.py` (near other env-driven settings):

```python
# Absolute origin (scheme+host, no trailing slash) baked into the HTML-element
# sandbox CSP + <base href>. Trusted/configured — never derived from request Host.
HTMLEL_SANDBOX_ORIGIN = env("DJANGO_HTMLEL_SANDBOX_ORIGIN", default="http://localhost:8000")
```

In `config/settings/test.py` (deterministic value for tests; Django's test client host is `testserver`):

```python
HTMLEL_SANDBOX_ORIGIN = "http://testserver"
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_htmlsandbox.py
from courses import htmlsandbox as hs

ORIGIN = "http://testserver"


def test_has_math_delimiters():
    assert hs.has_math_delimiters(r"x \( a+b \) y") is True
    assert hs.has_math_delimiters(r"x \[ a \] y") is True
    assert hs.has_math_delimiters("no math here") is False
    assert hs.has_math_delimiters("$$x$$") is False  # $$ unsupported


def test_build_srcdoc_core_structure_and_csp():
    doc = hs.build_srcdoc("<p>hi</p>", "", "", "", origin=ORIGIN)
    assert doc.startswith("<!doctype html>")
    assert "<p>hi</p>" in doc
    assert f'<base href="{ORIGIN}/">' in doc
    assert "default-src 'none'" in doc
    assert "connect-src 'none'" in doc
    assert f"img-src {ORIGIN} data:" in doc
    assert f"font-src {ORIGIN} data:" in doc
    # inline author/seed/KaTeX scripts + styles must be permitted to run/apply:
    assert "script-src 'unsafe-inline'" in doc
    assert "style-src 'unsafe-inline'" in doc
    # 'self' is inert under an opaque origin — assert it never appears IN THE CSP
    # (scope to the CSP meta, not the whole doc: inlined KaTeX JS may contain "'self'").
    import re as _re
    csp = _re.search(r'Content-Security-Policy" content="([^"]*)"', doc).group(1)
    assert "'self'" not in csp
    assert 'libli:htmlel:height' in doc  # resize reporter always present


def test_build_srcdoc_block_order_seed_before_course_js():
    doc = hs.build_srcdoc("<p>x</p>", "", "COURSE_JS_MARK", "SEED_MARK", origin=ORIGIN)
    assert doc.index("SEED_MARK") < doc.index("COURSE_JS_MARK")


def test_build_srcdoc_omits_empty_blocks():
    doc = hs.build_srcdoc("<p>x</p>", "", "", "", origin=ORIGIN)
    assert "<style></style>" not in doc
    assert "<script></script>" not in doc


def test_build_srcdoc_injects_css():
    doc = hs.build_srcdoc("<p>x</p>", ".q{color:red}", "", "", origin=ORIGIN)
    assert "<style>.q{color:red}</style>" in doc


def test_katex_gated_on_delimiters():
    no_math = hs.build_srcdoc("<p>plain</p>", "", "", "", origin=ORIGIN)
    assert "renderMathInElement" not in no_math
    with_math = hs.build_srcdoc(r"<p>\( a \)</p>", "", "", "", origin=ORIGIN)
    assert "renderMathInElement" in with_math


def test_katex_font_urls_rewritten_absolute():
    doc = hs.build_srcdoc(r"<p>\( a \)</p>", "", "", "", origin=ORIGIN)
    # No bare relative font refs survive; all point at the absolute static path.
    assert "url(fonts/" not in doc
    assert f"{ORIGIN}/static/courses/vendor/katex/fonts/" in doc
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_htmlsandbox.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'courses.htmlsandbox'`).

- [ ] **Step 4: Write the assembly module**

```python
# courses/htmlsandbox.py
"""Assemble the sandboxed srcdoc for HtmlElement.

Containment is the iframe's opaque origin (sandbox="allow-scripts", NO
allow-same-origin) — not sanitization. See the 1b-iii design spec. The string
returned here is the raw document; the element template attribute-escapes it
into srcdoc="{{ doc }}".
"""
import re
from functools import lru_cache
from pathlib import Path

from django.contrib.staticfiles import finders
from django.templatetags.static import static

MIN_IFRAME_HEIGHT = 40
MAX_IFRAME_HEIGHT = 20000

# KaTeX auto-render: \(..\) inline, \[..\] display. The doubled backslashes here
# emit the JS-string literal "\\(" (a JS string containing the two chars \( ).
_AUTORENDER_CALL = (
    "renderMathInElement(document.body,{delimiters:["
    '{left:"\\\\(",right:"\\\\)",display:false},'
    '{left:"\\\\[",right:"\\\\]",display:true}],throwOnError:false});'
)

# In-sandbox reporter: posts the height contract upward. Measures body (not
# documentElement, which would feed back from the applied iframe height).
_RESIZE_REPORTER = (
    "(function(){"
    "function r(){var b=document.body;if(!b)return;"
    "var h=Math.max(b.scrollHeight,Math.ceil(b.getBoundingClientRect().height));"
    'parent.postMessage({type:"libli:htmlel:height",h:h},"*");}'
    "if(window.ResizeObserver){new ResizeObserver(r).observe(document.body);}"
    "window.addEventListener('load',r);"
    "if(document.fonts&&document.fonts.ready){document.fonts.ready.then(r);}"
    "r();})();"
)


def has_math_delimiters(html):
    """True iff the raw html contains an inline \\( or a display \\[ delimiter."""
    html = html or ""
    return ("\\(" in html) or ("\\[" in html)


def _csp(origin):
    return (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        f"img-src {origin} data:; font-src {origin} data:; connect-src 'none'"
    )


@lru_cache(maxsize=8)
def _katex_assets(origin):
    """Read + cache vendored KaTeX. lru_cache makes this read-once-per-origin
    (≤8 origins), satisfying the spec's "read once, never per render" intent via
    lazy memoization rather than import-time. Rewrites EVERY url(fonts/...) —
    woff2, woff, ttf alike — to an absolute static URL, because the inlined CSS
    would otherwise resolve those relative refs against <base> to a 404."""
    css = Path(finders.find("courses/vendor/katex/katex.min.css")).read_text(encoding="utf-8")
    katex_js = Path(finders.find("courses/vendor/katex/katex.min.js")).read_text(encoding="utf-8")
    autorender_js = Path(
        finders.find("courses/vendor/katex/contrib/auto-render.min.js")
    ).read_text(encoding="utf-8")

    def _abs(m):
        # Strip any leading slash from static() before joining so the result is
        # single-slash regardless of whether STATIC_URL has a leading slash.
        # (libli uses STATIC_URL="static/" → static() returns "static/…" with no
        # leading slash; lstrip is a no-op there but robust if it ever changes.)
        name = m.group(1)
        rel = static("courses/vendor/katex/fonts/" + name).lstrip("/")
        return f"url({origin}/{rel})"

    css = re.sub(r"url\(fonts/([^)]+)\)", _abs, css)
    return css, katex_js, autorender_js


def build_srcdoc(html, css, js, seed, *, origin):
    html = html or ""
    math = has_math_delimiters(html)
    parts = [
        "<!doctype html><html><head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_csp(origin)}">',
        f'<base href="{origin}/">',
    ]
    if math:
        katex_css, katex_js, autorender_js = _katex_assets(origin)
        parts.append(f"<style>{katex_css}</style>")
    if css:
        parts.append(f"<style>{css}</style>")
    parts.append("</head><body>")
    parts.append(html)
    if seed:
        parts.append(f"<script>{seed}</script>")   # seed first: defines vars
    if js:
        parts.append(f"<script>{js}</script>")     # course JS: reads vars
    if math:
        parts.append(f"<script>{katex_js}</script>")
        parts.append(f"<script>{autorender_js}</script>")
        parts.append(f"<script>{_AUTORENDER_CALL}</script>")
    parts.append(f"<script>{_RESIZE_REPORTER}</script>")
    parts.append("</body></html>")
    return "".join(parts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_htmlsandbox.py -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/htmlsandbox.py config/settings/base.py config/settings/test.py tests/test_htmlsandbox.py
git commit -m "feat(1b-iii): srcdoc assembly module + sandbox origin setting"
```

---

### Task 4: `HtmlElement.render` + element template + `render_element` dispatch

**Files:**
- Modify: `courses/models.py` (`HtmlElement.render` override)
- Create: `templates/courses/elements/htmlelement.html`
- Modify: `courses/templatetags/courses_extras.py` (`render_element` dispatch)
- Test: `tests/test_html_element.py` (append)

**Interfaces:**
- Consumes: `htmlsandbox.build_srcdoc` (Task 3); `Element.unit`, `unit.course` (existing FKs).
- Produces: rendered iframe markup with exactly `sandbox="allow-scripts"`, escaped `srcdoc`, `referrerpolicy="no-referrer"`. `render_element(element)` dispatches `HtmlElement` to `render(unit, course)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_html_element.py`)

```python
from django.template import Context, Template


def _render_tag(element):
    tpl = Template("{% load courses_extras %}{% render_element el %}")
    return tpl.render(Context({"el": element}))


@pytest.mark.django_db
def test_render_emits_locked_down_iframe():
    course = Course.objects.create(title="C", slug="c-r1", html_css=".q{color:red}")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON, html_seed_js="var SEED=1;",
    )
    el = HtmlElement.objects.create(html='<b>hi</b>')
    join = Element.objects.create(unit=unit, content_object=el)

    out = _render_tag(join)
    assert 'sandbox="allow-scripts"' in out
    assert "allow-same-origin" not in out
    assert 'referrerpolicy="no-referrer"' in out
    assert "srcdoc=" in out
    assert 'class="html-el"' in out


@pytest.mark.django_db
def test_srcdoc_is_attribute_escaped_no_breakout():
    course = Course.objects.create(title="C", slug="c-r2")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    # Author content with a double-quote + a </script> + an ampersand.
    el = HtmlElement.objects.create(html='<i a="x">&</i><script>"</script>')
    join = Element.objects.create(unit=unit, content_object=el)
    out = _render_tag(join)
    # The raw, unescaped author markup must NOT appear verbatim in the page
    # (it is attribute-escaped inside srcdoc).
    assert '<i a="x">' not in out
    assert "&quot;" in out  # the double-quote was escaped


@pytest.mark.django_db
def test_render_element_other_types_unchanged():
    from courses.models import TextElement
    course = Course.objects.create(title="C", slug="c-r3")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    te = TextElement.objects.create(body="<p>plain</p>")
    join = Element.objects.create(unit=unit, content_object=te)
    out = _render_tag(join)
    assert "plain" in out
    assert "srcdoc=" not in out  # text element is not iframed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_html_element.py -q`
Expected: FAIL (`TemplateDoesNotExist: courses/elements/htmlelement.html` / dispatch missing).

- [ ] **Step 3: Add the `render` override** (in `courses/models.py`, inside `HtmlElement`, replacing the Task-1 placeholder comment)

```python
    def render(self, unit, course):
        from django.conf import settings

        from courses import htmlsandbox

        doc = htmlsandbox.build_srcdoc(
            self.html,
            course.html_css,
            course.html_js,
            unit.html_seed_js,
            origin=settings.HTMLEL_SANDBOX_ORIGIN,
        )
        return render_to_string("courses/elements/htmlelement.html", {"doc": doc})
```

- [ ] **Step 4: Create the element template**

```django
{# templates/courses/elements/htmlelement.html #}
{% load i18n %}
<div class="html-el">
  <span class="html-el__label">{% trans "interactive content" %}</span>
  <iframe class="html-el__frame" sandbox="allow-scripts"
          srcdoc="{{ doc }}"
          referrerpolicy="no-referrer" loading="lazy"></iframe>
</div>
```

(`{{ doc }}` is auto-escaped — do not add `|safe`.)

- [ ] **Step 5: Update `render_element` dispatch** (`courses/templatetags/courses_extras.py`)

Add at the top with the other imports:

```python
from courses.models import HtmlElement
```

Replace the body of `render_element`:

```python
@register.simple_tag
def render_element(element):
    """Render one Element's concrete payload.

    Returns empty string if the target was deleted.
    """
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        # HtmlElement needs course-wide CSS/JS + the unit seed, resolved from
        # the join-row (element.unit -> unit.course). The template escapes srcdoc.
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_html_element.py -q`
Expected: PASS (all, including the 3 new).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py templates/courses/elements/htmlelement.html courses/templatetags/courses_extras.py tests/test_html_element.py
git commit -m "feat(1b-iii): HtmlElement.render + sandboxed iframe template + dispatch"
```

---

### Task 5: Editor wiring — form, type allowlist, edit partial, add-menu card

**Files:**
- Modify: `courses/element_forms.py` (`HtmlElementForm` + `FORM_FOR_TYPE`)
- Modify: `courses/views_manage.py` (add `"html"` to both type-key tuples)
- Create: `templates/courses/manage/editor/_edit_html.html`
- Modify: `templates/courses/manage/editor/_add_menu.html` (6th card)
- Test: `tests/test_html_element.py` (append)

**Interfaces:**
- Consumes: existing element machinery (`element_add`, `element_save`, `element_form`, `_render_open_form`, `builder.save_element`).
- Produces: `HtmlElementForm(ModelForm, fields=["html"])` registered as `FORM_FOR_TYPE["html"]`; `"html"` accepted by add/save; the `_edit_html.html` partial.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_html_element.py`)

```python
from django.urls import reverse

from tests.factories import make_pa  # established PA login helper


@pytest.mark.django_db
def test_html_form_registered_and_plain():
    from courses.element_forms import FORM_FOR_TYPE, HtmlElementForm
    assert FORM_FOR_TYPE["html"] is HtmlElementForm
    # Plain ModelForm: constructs with no course=/unit= kwargs.
    form = HtmlElementForm()
    assert list(form.fields) == ["html"]


@pytest.mark.django_db
def test_add_and_save_html_element(client):
    user = make_pa(client)  # logs the client in as a Platform Admin
    course = Course.objects.create(title="C", slug="c-add", owner=user)
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    # Open the add form for the html type (render-only).
    add_url = reverse("courses:manage_element_add", kwargs={"slug": course.slug})
    r = client.post(add_url, {"unit": unit.pk, "type": "html"},
                    HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200
    assert b'name="html"' in r.content  # textarea rendered

    # Persist (create-on-first-save via element=new).
    save_url = reverse("courses:manage_element_save", kwargs={"slug": course.slug})
    r = client.post(
        save_url,
        {"unit": unit.pk, "type": "html", "element": "new",
         "html": "<button id=b>go</button>", "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert r.status_code == 200
    assert HtmlElement.objects.filter(html="<button id=b>go</button>").exists()
```

> Check the exact URL names against `courses/urls.py` (use the existing `manage_element_add` / `manage_element_save` / etc. names; adjust the `reverse()` names if they differ). The POST field names (`unit`, `type`, `element`, `unit_token`) mirror the existing element-save contract used by the other element types — confirm against `element_save` in `views_manage.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_html_element.py -q -k "html_form or add_and_save"`
Expected: FAIL (`KeyError: 'html'` in `FORM_FOR_TYPE` / `HttpResponseBadRequest` "bad type").

- [ ] **Step 3: Add the form** (`courses/element_forms.py`)

Add `HtmlElement` to the model imports at the top, then before `FORM_FOR_TYPE`:

```python
class HtmlElementForm(forms.ModelForm):
    class Meta:
        model = HtmlElement
        fields = ["html"]
        widgets = {
            "html": forms.Textarea(
                attrs={"class": "code", "rows": 12, "spellcheck": "false"}
            )
        }
    # No clean_html: the raw markup is stored verbatim (sandbox is the boundary).
```

Register it:

```python
FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
    "html": HtmlElementForm,
}
```

- [ ] **Step 4: Allow the `"html"` type** (`courses/views_manage.py`)

In **both** `element_add` and `element_save`, change the guard tuple:

```python
    if type_key not in ("text", "image", "video", "iframe", "math", "html"):
```

(Leave the `extra = {"course": …} if type_key in ("image", "video")` branches untouched — the HTML form needs no `course=`.)

- [ ] **Step 5: Create the edit partial**

```django
{# templates/courses/manage/editor/_edit_html.html #}
{% load i18n %}
<div class="edit-html">
  <label class="edit-html__label" for="id_html">{% trans "HTML / CSS / JS" %}</label>
  {{ form.html }}
  <p class="edit-html__help">
    {% trans "Runs in an isolated sandbox. Uses the course-wide CSS/JS and this unit's seed script, and supports inline and display LaTeX math." %}
  </p>

  {# NOTE: keep literal backslash LaTeX delimiters OUT of {% trans %} strings — #}
  {# they double-escape through makemessages/PO and break the i18n gate. Describe #}
  {# the feature in prose instead (as above). #}
</div>
```

> Open one of the existing `_edit_<type>.html` partials (e.g. `_edit_math.html`) and match its outer wrapper / form-field markup so the new partial drops into `_render_open_form`'s host consistently (same field name `id_html` produced by `{{ form.html }}`).

- [ ] **Step 6: Add the add-menu card** (`templates/courses/manage/editor/_add_menu.html`, after the math card)

```django
    <button type="button" class="typecard" data-add-type="html"><span class="ic">&lt;/&gt;</span>{% trans "HTML" %}</button>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_html_element.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py templates/courses/manage/editor/_edit_html.html templates/courses/manage/editor/_add_menu.html tests/test_html_element.py
git commit -m "feat(1b-iii): editor wiring for the HTML element (form, type, partial, add card)"
```

---

### Task 6: Course-wide CSS/JS fields on the course form

**Files:**
- Modify: `courses/forms.py` (`CourseForm.Meta`)
- Test: `tests/test_html_element.py` (append)

**Interfaces:**
- Produces: `CourseForm` exposes `html_css`/`html_js` as monospace textareas (rendered automatically by the existing `{{ form.as_p }}` in `course_form.html`).

- [ ] **Step 1: Write the failing test** (append)

```python
@pytest.mark.django_db
def test_course_form_has_html_css_js_fields():
    from courses.forms import CourseForm
    form = CourseForm()
    assert "html_css" in form.fields
    assert "html_js" in form.fields
    # persists through the form
    form = CourseForm(data={
        "title": "C", "slug": "c-form", "language": "en",
        "overview": "", "visibility": "assigned",
        "html_css": ".q{color:red}", "html_js": "var X=1;",
    })
    assert form.is_valid(), form.errors
    course = form.save()
    assert course.html_css == ".q{color:red}" and course.html_js == "var X=1;"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_html_element.py -q -k course_form_has_html`
Expected: FAIL (`assert "html_css" in form.fields`).

- [ ] **Step 3: Extend `CourseForm.Meta`** (`courses/forms.py`)

```python
    class Meta:
        model = Course
        fields = [
            "title",
            "slug",
            "subject",
            "language",
            "overview",
            "visibility",
            "owner",
            "html_css",
            "html_js",
        ]
        widgets = {
            "html_css": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
            ),
            "html_js": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
            ),
        }
```

(The existing `__init__` owner-pop and `clean_slug` are unchanged. `course_form.html` renders via `{{ form.as_p }}`, so the new fields appear with no template edit.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_html_element.py -q -k course_form_has_html`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/forms.py tests/test_html_element.py
git commit -m "feat(1b-iii): course-wide HTML CSS/JS fields on CourseForm"
```

---

### Task 7: Lesson/editor querysets + `has_html` flag

**Files:**
- Modify: `courses/views.py` (lesson view: select_related + `has_html`)
- Modify: `courses/views_manage.py` (`_editor_rows` select_related)
- Test: `tests/test_html_element.py` (append)

**Interfaces:**
- Consumes: the `render_element` dispatch (Task 4) which reads `element.unit.course`.
- Produces: `has_html` in the lesson template context; both feeding querysets `select_related("unit__course")` so rendering N HTML elements adds no per-element FK query.

- [ ] **Step 1: Write the failing tests** (append)

```python
@pytest.mark.django_db
def test_lesson_sets_has_html():
    from django.test import Client
    from courses.models import Enrollment
    c = Client()
    user = make_pa(c)
    course = Course.objects.create(title="C", slug="c-les", owner=user)
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    Enrollment.objects.get_or_create(student=user, course=course)
    Element.objects.create(unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>"))
    url = reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    r = c.get(url)
    assert r.status_code == 200
    assert r.context["has_html"] is True


@pytest.mark.django_db
def test_lesson_html_render_query_count_invariant(client):
    # The real guarantee: rendering MORE HTML elements must NOT add per-element
    # unit/course FK queries. Compare a 1-element page vs a 3-element page and
    # assert the query count is identical (select_related("unit__course") folds
    # the FK chain in; prefetch_related("content_object") is one query per type,
    # independent of element count).
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from courses.models import Enrollment

    user = make_pa(client)

    def build(slug, n):
        course = Course.objects.create(title="C", slug=slug, owner=user)
        unit = ContentNode.objects.create(
            course=course, kind=ContentNode.Kind.UNIT, title="U",
            unit_type=ContentNode.UnitType.LESSON,
        )
        Enrollment.objects.get_or_create(student=user, course=course)
        for i in range(n):
            Element.objects.create(
                unit=unit, content_object=HtmlElement.objects.create(html=f"<p>{i}</p>")
            )
        return reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})

    url1 = build("c-q1", 1)
    url3 = build("c-q3", 3)
    with CaptureQueriesContext(connection) as q1:
        assert client.get(url1).status_code == 200
    with CaptureQueriesContext(connection) as q3:
        assert client.get(url3).status_code == 200
    assert len(q3) == len(q1), f"per-element queries leaked: {len(q1)} vs {len(q3)}"
```

> Confirm the lesson URL name (`courses:lesson_unit`) and the enrollment/access path against `courses/urls.py` and `courses/access.py`; reuse whatever helper the existing lesson tests use to make a unit viewable. The invariance test deliberately avoids a magic `N` — it asserts the count does not grow with element count, which is exactly the select_related property.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_html_element.py -q -k has_html`
Expected: FAIL (`KeyError: 'has_html'`).

- [ ] **Step 3: Update the lesson view** (`courses/views.py`)

Add `HtmlElement` to the model imports. Change the elements queryset and add the flag (around lines 52–56):

```python
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    has_math = any(el.content_type_id == math_ct_id for el in elements)
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    has_html = any(el.content_type_id == html_ct_id for el in elements)
```

Add `"has_html": has_html,` to the render context dict (next to `"has_math": has_math,`). (Only `.select_related("unit__course")` is inserted into the existing chain — call order among `order_by`/`select_related`/`prefetch_related` is immaterial.)

- [ ] **Step 4: Update the editor rows helper** (`courses/views_manage.py`, `_editor_rows`)

```python
        unit.elements.select_related("content_type", "unit__course").order_by("order", "pk")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_html_element.py -q -k has_html`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/views_manage.py tests/test_html_element.py
git commit -m "feat(1b-iii): has_html flag + select_related unit__course on feeding views"
```

---

### Task 8: Parent-side resize listener + CSS + template wiring

**Files:**
- Create: `courses/static/courses/js/html_element.js`
- Modify: `courses/static/courses/css/courses.css` (`.html-el` styles)
- Modify: `templates/courses/lesson_unit.html` (load JS gated on `has_html`)
- Modify: `templates/courses/manage/editor/editor.html` (load JS unconditionally)
- Test: `tests/test_html_element.py` (append — template-level wiring)

**Interfaces:**
- Consumes: the `{ type: "libli:htmlel:height", h }` contract; `has_html` (Task 7).
- Produces: `html_element.js` (single `message` listener, `.html-el iframe`-scoped, clamps `[40, 20000]`); `.html-el` styles.

- [ ] **Step 1: Write the failing wiring tests** (append)

```python
@pytest.mark.django_db
def test_lesson_loads_html_js_only_when_has_html(client):
    user = make_pa(client)
    from courses.models import Enrollment
    # course WITH an html element
    c1 = Course.objects.create(title="A", slug="c-js-1", owner=user)
    u1 = ContentNode.objects.create(course=c1, kind=ContentNode.Kind.UNIT, title="U",
                                    unit_type=ContentNode.UnitType.LESSON)
    Enrollment.objects.get_or_create(student=user, course=c1)
    Element.objects.create(unit=u1, content_object=HtmlElement.objects.create(html="<p>x</p>"))
    # course WITHOUT
    c2 = Course.objects.create(title="B", slug="c-js-2", owner=user)
    u2 = ContentNode.objects.create(course=c2, kind=ContentNode.Kind.UNIT, title="U",
                                    unit_type=ContentNode.UnitType.LESSON)
    Enrollment.objects.get_or_create(student=user, course=c2)
    from courses.models import TextElement
    Element.objects.create(unit=u2, content_object=TextElement.objects.create(body="<p>x</p>"))

    r1 = client.get(reverse("courses:lesson_unit", kwargs={"slug": c1.slug, "node_pk": u1.pk}))
    r2 = client.get(reverse("courses:lesson_unit", kwargs={"slug": c2.slug, "node_pk": u2.pk}))
    assert b"html_element.js" in r1.content
    assert b"html_element.js" not in r2.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_html_element.py -q -k loads_html_js`
Expected: FAIL (`html_element.js` not in content).

- [ ] **Step 3: Write the listener**

```javascript
// courses/static/courses/js/html_element.js
(function () {
  "use strict";
  var MIN = 40, MAX = 20000;
  function clamp(h) {
    h = parseInt(h, 10);
    if (isNaN(h)) return null;
    return Math.max(MIN, Math.min(MAX, h));
  }
  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || d.type !== "libli:htmlel:height") return;  // only our contract
    var h = clamp(d.h);
    if (h === null) return;
    // Resolve sender among HTML-element iframes ONLY (never other iframes,
    // e.g. GeoGebra). Enumerated at message time → survives preview swaps.
    var frames = document.querySelectorAll(".html-el iframe");
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].contentWindow === e.source) {
        frames[i].style.height = h + "px";
        return;
      }
    }
  });
})();
```

- [ ] **Step 4: Add the CSS** (append to `courses/static/courses/css/courses.css`)

```css
/* Sandboxed HTML element (1b-iii) */
.html-el {
  position: relative;
  border: 1px solid var(--border, #d0d0d0);
  border-radius: 6px;
  margin: 1rem 0;
}
.html-el__label {
  position: absolute;
  top: -0.6em;
  left: 0.6em;
  padding: 0 0.4em;
  font-size: 0.7rem;
  background: var(--surface, #fff);
  color: var(--muted, #666);
}
.html-el__frame {
  display: block;
  width: 100%;
  min-height: 40px;   /* fallback floor — never collapses (matches MIN clamp) */
  border: 0;
  overflow: auto;
}
```

- [ ] **Step 5: Wire the lesson template** (`templates/courses/lesson_unit.html`, in `{% block extra_js %}`, after the math scripts)

```django
  {% if has_html %}<script src="{% static 'courses/js/html_element.js' %}" defer></script>{% endif %}
```

- [ ] **Step 6: Wire the editor template** (`templates/courses/manage/editor/editor.html`, in `{% block extra_js %}`, after `editor.js`)

```django
  <script src="{% static 'courses/js/html_element.js' %}" defer></script>
```

- [ ] **Step 7: Run test + collectstatic**

Run: `uv run pytest tests/test_html_element.py -q -k loads_html_js`
Expected: PASS.
Run: `uv run python manage.py collectstatic --noinput`
Expected: includes `html_element.js`.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/html_element.js courses/static/courses/css/courses.css templates/courses/lesson_unit.html templates/courses/manage/editor/editor.html tests/test_html_element.py
git commit -m "feat(1b-iii): parent-side resize listener + .html-el styles + template wiring"
```

---

### Task 9: i18n — extract + Polish + compile

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: none (verified by compile + the i18n gate convention)

**Interfaces:**
- Produces: Polish translations for every new user-facing string: `"interactive content"` (the §2.6 frame label), `"HTML"` (add card), `"HTML / CSS / JS"` (editor label), the editor help text, and the `CourseForm` field labels if surfaced.

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: new `msgid`s appear in `locale/pl/LC_MESSAGES/django.po` (interactive content, HTML, HTML / CSS / JS, the help string).

- [ ] **Step 2: Fill in the Polish `msgstr`s**

Open `locale/pl/LC_MESSAGES/django.po` and, for each newly extracted `msgid`,
**copy the `msgid` exactly as `makemessages` wrote it** (do not retype — match its
escaping byte-for-byte) and fill the `msgstr`. Translations:
- `"interactive content"` → `"treść interaktywna"`
- `"HTML"` → `"HTML"`
- `"HTML / CSS / JS"` → `"HTML / CSS / JS"`
- the help string → a faithful Polish rendering of "Runs in an isolated sandbox…".

(The help text deliberately contains no `\(`/`\[` LaTeX tokens — see the Task 5
note — so there is no backslash-escaping hazard in the PO round-trip.)

Ensure no new `#, fuzzy` markers and no empty `msgstr ""` for the new ids.

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: compiles without error.

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(1b-iii): Polish strings for the HTML element"
```

---

### Task 10: Playwright e2e + DoD gate

**Files:**
- Create: `tests/test_e2e_html_element.py`
- Test: the file itself

**Interfaces:**
- Consumes: the full feature (author flow + lesson render + resize + isolation).

> Mirror the harness in the existing `tests/test_e2e_editor_ws3.py` / `tests/test_e2e_*` files: the `e2e` pytest marker (excluded from the default run via `addopts -m 'not e2e'`), `live_server`, sync Playwright, the **session-scoped autouse `DJANGO_ALLOW_ASYNC_UNSAFE` fixture defined inside this test module**, and the established login helper. Scope all page-form submit selectors past the 0d shell header (it has its own submit buttons).

> **Lazy-load:** the iframe carries `loading="lazy"`, so a below-the-fold HTML element does not load (and never reports height) until scrolled near the viewport. Before asserting resize / independent sizing, **scroll each iframe into view** (`frame.scroll_into_view_if_needed()` / `page.mouse.wheel`) and wait for the height to settle.

> **CSP execution coverage:** the unit tests only assert *presence* of the inline `<script>` blocks and the `'unsafe-inline'` CSP directives; the only place the inline scripts are proven to actually **execute** under the in-sandbox CSP is this e2e suite, which is excluded from the default `pytest -q` (`-m 'not e2e'`). The DoD (Step 2/3) therefore MUST run the e2e suite at least once — do not treat a green default `pytest -q` as sufficient for this feature.

- [ ] **Step 1: Write the e2e tests**

```python
# tests/test_e2e_html_element.py
import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "1"
    yield


def _seed_html_unit(slug, *, n=1, tall=False):
    """Create a course + unit + n HtmlElement(s) with a per-unit seed and a
    button that reads the seeded variable; enroll the viewer. Returns the lesson
    URL path. Reuse the ORM helpers used by the other e2e tests."""
    # course.html_js: define a global that the button handler calls.
    # unit.html_seed_js: 'var ANSWER = 42;'
    # element.html: '<button id="b">go</button><output id="o"></output>'
    #   + an inline <script> that wires the button to write ANSWER into #o.
    ...


def test_html_element_runs_and_resizes_in_lesson(live_server, page):
    # 1. Author/seed the unit (ORM), log in, open the lesson page.
    # 2. The iframe is present with sandbox="allow-scripts" and no allow-same-origin.
    # 3. Click the in-iframe button; assert #o shows the seeded value (JS ran,
    #    seed reached the element).
    # 4. Assert the iframe's rendered height grew beyond the 40px floor
    #    (resize bridge fired).
    ...


def test_runtime_containment(live_server, page):
    # Inside the iframe, evaluate code that touches localStorage / document.cookie
    # and assert it throws / returns no parent data (opaque-origin enforced).
    # If asserting the cross-origin throw is flaky in Playwright, assert instead
    # that the iframe has sandbox="allow-scripts" without allow-same-origin
    # (the attribute set that guarantees isolation) — documented fallback.
    ...


def test_two_elements_size_independently(live_server, page):
    # Two HtmlElements of different content heights on one unit → two iframes
    # with different applied heights.
    ...


def test_non_html_iframe_not_resized(live_server, page):
    # Add an iframe element (e.g. a whitelisted embed) alongside an HTML element;
    # post the {type:"libli:htmlel:height"} shape from a non-.html-el iframe (or
    # assert the listener only targets `.html-el iframe`) → embed keeps its size.
    ...
```

> Fill in the helper bodies and Playwright calls following the existing e2e files (login, navigation, `frame_locator` for in-iframe interaction). Keep the four behaviors as separate test functions.

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest tests/test_e2e_html_element.py -q -m e2e`
Expected: PASS (4 tests).

- [ ] **Step 3: Run the full DoD gate**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py collectstatic --noinput
uv run python manage.py compilemessages -l pl
```
Expected: all clean (default `pytest -q` green with e2e excluded; `makemigrations --check` reports no missing migration beyond the committed `0010`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_html_element.py
git commit -m "test(1b-iii): Playwright e2e for the sandboxed HTML element + DoD gate"
```

---

## Self-Review

**Spec coverage (each spec section → task):**
- §2.2/§2.3 sandbox flags → Task 4 (template) + tests assert `allow-scripts`, no `allow-same-origin`, `referrerpolicy`.
- §2.4 in-sandbox CSP (explicit app-origin, `connect-src 'none'`) → Task 3 (`_csp`) + test.
- §2.5 resize contract + clamp `[40,20000]` + source-identity → Task 3 (reporter) + Task 8 (listener) + tests.
- §3.1 `HtmlElement` (no nh3) → Task 1 + verbatim-storage test.
- §3.2 `Course.html_css`/`html_js` → Task 1 (fields) + Task 6 (form).
- §3.3 `ContentNode.html_seed_js` (dormant on non-units) → Task 1.
- §3.5 authoring UX (textareas, machinery edits, add card) → Tasks 5–6.
- §4.1 assembly skeleton + `<base href>` + order → Task 3.
- §4.2 render mechanism (join-row → `render(unit,course)`; select_related) → Task 4 + Task 7.
- §4.3 KaTeX gating predicate + font-URL rewrite (woff2/woff/ttf) + read-once cache → Task 2 (vendor) + Task 3.
- §4.4 reporter (`body.scrollHeight`, re-report on load/fonts/RO) + listener (`.html-el` only) → Tasks 3, 8.
- §5 templates/static (htmlelement.html, `_edit_html.html`, html_element.js, `.html-el` CSS, auto-render) → Tasks 2,4,5,8.
- §6.1 preview parity → Task 4 (`render_element` shared by both) + Task 7 (`_editor_rows`).
- §6.2 progress "seen" unchanged → no task needed (wrapper `<section>` untouched).
- §6.3 no-JS/lazy fallback (`min-height`, `overflow:auto`) → Task 8 CSS.
- §7 error handling (empty blocks omitted, per-block isolation) → Task 3 (omit) + e2e.
- §8 tests (escape, propagation, query-count, cascade-delete, runtime containment, non-`.html-el`) → Tasks 1,3,4,7,10.
- §8.4 i18n → Task 9.

**Gaps found & closed:** course-CSS **propagation** test (§8 "central correctness property") — add to Task 3's suite an assertion that rendering reflects a changed `course.html_css` without touching the element row:

```python
@pytest.mark.django_db
def test_course_css_propagates_on_next_render():  # add in tests/test_html_element.py (Task 4)
    course = Course.objects.create(title="C", slug="c-prop", html_css=".q{color:red}")
    unit = ContentNode.objects.create(course=course, kind=ContentNode.Kind.UNIT,
        title="U", unit_type=ContentNode.UnitType.LESSON)
    join = Element.objects.create(unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>"))
    assert ".q{color:red}" in _render_tag(join)
    course.html_css = ".q{color:blue}"; course.save(update_fields=["html_css"])
    join.refresh_from_db()
    assert ".q{color:blue}" in _render_tag(join)  # element row untouched
```

(Implementers: add this test in Task 4 alongside the other render tests.)

**Placeholder scan:** the e2e helper bodies (Task 10) are intentionally described rather than fully coded because they must mirror the project's existing e2e harness (login/fixtures/`frame_locator`) which varies; every other step contains complete code. No `TODO`/`TBD` in shipping code.

**Type consistency:** `build_srcdoc(html, css, js, seed, *, origin)`, `has_math_delimiters(html)`, `HtmlElement.render(self, unit, course)`, `FORM_FOR_TYPE["html"]`, message `{type:"libli:htmlel:height", h}`, clamp `[40,20000]`, `ELEMENT_MODELS` literal `"htmlelement"` — used consistently across Tasks 3, 4, 5, 8, 10.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-18-phase-1b-iii-html-element.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage spec/quality review between tasks, fast iteration (the established libli rhythm).

**2. Inline Execution** — execute tasks in this session via executing-plans, batch execution with checkpoints.

**Which approach?**
