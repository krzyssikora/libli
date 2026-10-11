# Print Layout for Units Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A printed lesson, quiz or quiz-results page shows only the unit's content, framed by 15 mm margins, a running header ("libli · <title>" + "Page n / N"), with images and questions never split across pages.

**Architecture:** Pure CSS + one template partial. A global `@page` margin and the header/flash/main print rules are appended to the END of `core/static/core/css/app.css`; every unit-page print rule is appended as one block at the END of `courses/static/courses/css/courses.css` (appending puts each rule after every screen rule it overrides, and never shifts an existing line). The per-unit running header is an inline `<style data-print-page>` emitted by a new partial, built from `unit.title` through a new `css_string` filter. No JS, model, view or migration change.

**Tech Stack:** Django templates, plain CSS (`@page` margin boxes, Chromium 131+), pytest + pytest-django, Playwright (sync) for e2e.

**Spec:** `docs/superpowers/specs/2026-10-11-print-layout-for-units-design.md` — read it alongside this plan; every rule below cites the spec section it implements.

## Global Constraints

- Owner decisions D1–D7 in the spec are VERBATIM and binding; do not reverse any of them.
- `@page { margin: 15mm; }` (D4).
- Header: `"libli · <title>"` top-left, `"<Page> " counter(page) " / " counter(pages)` top-right; Polish label `Strona` via `{% translate "Page" context "print page counter" as page_label %}` (D5, spec §1).
- Header typography literals (never `var(...)`): `font-size: 8pt; color: #5A544A; font-family: "Inter", "libli-dice", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;`.
- Title pipeline exactly: `{{ unit.title|strip_math_delimiters|truncatechars:70|css_string }}`. Do NOT change `strip_math_delimiters`.
- `css_string` escapes EXACTLY `\ " ' < > &` and U+0000–U+001F, U+007F as `\<minimal lowercase hex> ` (one trailing space); nothing else; `None` → `""`; never raises; returns a SafeString.
- Every new print `display: none` carries `!important` (spec §3).
- Image print caps: existing 45/75/110/170 mm unchanged; new `.dragimage__img { max-height: 170mm; }` and `.el--gallery .gallery__frame { max-height: 170mm; }` (D6).
- CSS comments must name selectors, never line numbers (`tests/test_css_citations_are_durable.py` enforces this).
- Never write `{# … #}` across multiple lines in a template (Django renders it literally); use `{% comment %}`.
- Never pass `-q` to pytest (`addopts` already has it). e2e needs `-m e2e`. Start the test DB container before any test run (Task 1, Step 1).
- After ANY CSS edit, run every `tests/test_*css*.py` and `courses/tests/test_*css*.py`.
- **Lint gate before EVERY commit** (CI runs both on the whole repo), scoped to the task's Python files:
  `uv run ruff format <files>` then `uv run ruff check --no-cache <files>` then `uv run ruff format --check <files>`.
  Line length is 88: wrap long string literals / JS snippets in parentheses or split them; never name a variable `l` (E741). Every `mark_safe` needs `# noqa: S308 — <reason>` (repo convention).
- Commit with explicit paths, never `git add -A`. End every commit message with:
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6`

## Review Focus

1. **A title containing `"`, `&`, `\` or `</style>`** — the header must show the literal characters and the page must not break (stylesheet must not end early). Pinned by Task 1 (filter) and Task 2 (`Funkcja \(f(x)\) "x" </style>` render test).
2. **A dark-theme student printing** — no dark header band, no dark surfaces. Pinned by Task 3's e2e run in both stored themes.
3. **A unit printed before JS finishes booting** (stepper pre-hide still active, gallery not yet enhanced) — steps must still print. Pinned by Task 4's source test asserting the pre-boot stepper selector is in the reveal rule.
4. **Printing on small paper (A5)** — the open mobile drawer's `max-width: 640px` rule must not print. Pinned by `!important` on `.unit-drawer` (Task 4 source test) and the A5 PDF in Task 6.
5. **A submitted quiz** — the student prints the results page, which must get the same header and break rules. Pinned by Task 2 (header render on `quiz_results`) and Task 4/5 e2e on the results page.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `courses/templatetags/courses_extras.py` | modify (add filter after `strip_math_delimiters`) | `css_string` filter |
| `templates/courses/_print_page_header.html` | create | inline `<style data-print-page>` with the `@page` margin boxes |
| `templates/courses/lesson_unit.html`, `quiz_unit.html`, `quiz_results.html` | modify (`extra_css` block) | include the partial |
| `templates/base.html` | modify (flash loop) | `alert--flash` marker class |
| `locale/pl/LC_MESSAGES/django.po` + `.mo`, `locale/en/LC_MESSAGES/django.po` + `.mo` | modify | `msgctxt "print page counter"` entry |
| `core/static/core/css/app.css` | append | `@page` margin; header/main/flash print rules |
| `courses/static/courses/css/courses.css` | append | all unit-page print rules |
| `tests/test_css_string_filter.py` | create | filter unit tests (spec test 1) |
| `tests/test_print_page_header.py` | create | header render tests (spec test 2) + flash marker |
| `tests/test_print_layout_css.py` | create | CSS source tests (spec test 3) |
| `tests/test_e2e_print_layout.py` | create | e2e (spec tests 4–10) |

---

### Task 1: `css_string` template filter

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add directly after the `strip_math_delimiters` function)
- Test: `tests/test_css_string_filter.py`

**Interfaces:**
- Produces: `css_string(value) -> SafeString` registered as template filter `css_string` in the `courses_extras` library.

- [ ] **Step 1: Environment setup (once per worktree)**

```bash
cp "C:/Users/krzys/Documents/Python/own/libli/.env" "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/print-layout-for-units/.env"
cd "C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/print-layout-for-units"
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```
`.env` is untracked, so the new worktree has none; without it tests hit the wrong DB. Never `git add .env`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_css_string_filter.py`:

```python
"""css_string: the inside of a CSS double-quoted string, safe inside <style>.

Spec 2026-10-11-print-layout-for-units §2. The escape set is CLOSED: exactly
\\ " ' < > & and the C0 controls + DEL; everything else passes through.
"""

import pytest
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy

from courses.templatetags.courses_extras import css_string


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ('"', "\\22 "),
        ("'", "\\27 "),
        ("\\", "\\5c "),
        ("<", "\\3c "),
        (">", "\\3e "),
        ("&", "\\26 "),
        ("\n", "\\a "),
        ("\r", "\\d "),
        ("\x00", "\\0 "),
        ("\x1f", "\\1f "),
        ("\x7f", "\\7f "),
    ],
)
def test_each_escaped_character(raw, escaped):
    assert css_string(raw) == escaped


def test_everything_else_passes_through():
    s = "Zażółć gęślą jaźń (f(x)) ·…"
    assert css_string(s) == s


def test_style_close_tag_has_no_literal_angle_bracket():
    out = css_string("</style><script>")
    assert "<" not in out and ">" not in out
    assert out == "\\3c /style\\3e \\3c script\\3e "


def test_returns_safestring():
    assert isinstance(css_string("x"), SafeString)


def test_none_is_empty_string():
    assert css_string(None) == ""


def test_lazy_string_is_stringified():
    assert css_string(gettext_lazy("Page")) == "Page"


def test_non_string_does_not_raise():
    assert css_string(42) == "42"
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_css_string_filter.py`
Expected: FAIL — `ImportError: cannot import name 'css_string'`.

- [ ] **Step 4: Implement**

In `courses/templatetags/courses_extras.py`, directly after `strip_math_delimiters` (ensure `from django.utils.safestring import mark_safe` is imported at the top — add it if missing):

```python
# Spec 2026-10-11-print-layout-for-units §2. A CLOSED set: escaping anything
# else (e.g. parentheses) would change the exact header text tests pin.
_CSS_STRING_SPECIALS = frozenset("\\\"'<>&")


@register.filter
def css_string(value):
    """Escape a value for the INSIDE of a CSS double-quoted string in <style>.

    Escapes exactly \\ " ' < > & and U+0000-U+001F, U+007F as a CSS hex escape:
    backslash, minimal lowercase hex, one space. Escaping < and > makes a title
    containing </style> inert. None -> "" (str(None) would be "None"); anything
    else -> str(value). Never raises: a raising filter takes down the page.
    """
    if value is None:
        return mark_safe("")  # noqa: S308 — constant empty string
    out = []
    for ch in str(value):
        cp = ord(ch)
        if ch in _CSS_STRING_SPECIALS or cp < 0x20 or cp == 0x7F:
            out.append(f"\\{cp:x} ")
        else:
            out.append(ch)
    return mark_safe("".join(out))  # noqa: S308 — every special/control char is hex-escaped
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_css_string_filter.py`
Expected: all PASS (grep the summary line for `passed`, not just the exit code).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --no-cache courses/templatetags/courses_extras.py tests/test_css_string_filter.py
uv run ruff format --check courses/templatetags/courses_extras.py tests/test_css_string_filter.py
git add courses/templatetags/courses_extras.py tests/test_css_string_filter.py
git commit -m "feat(print): css_string filter for CSS string literals in <style>

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6"
```

---

### Task 2: Running header partial + flash marker

**Files:**
- Create: `templates/courses/_print_page_header.html`
- Modify: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`, `templates/courses/quiz_results.html` (each `{% block extra_css %}`)
- Modify: `templates/base.html` (flash loop, the `<div class="alert alert--{{ message.tags }}">` line)
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` + compiled `.mo`
- Test: `tests/test_print_page_header.py`

**Interfaces:**
- Consumes: `css_string` (Task 1), `strip_math_delimiters` (existing).
- Produces: `<style data-print-page>` block in `<head>` of the three pages; class `alert--flash` on every Django flash message.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_print_page_header.py`:

```python
"""Running print header (spec 2026-10-11-print-layout-for-units §1, test 2)."""

from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login

HOSTILE = 'Funkcja \\(f(x)\\) "x" </style>'
HOSTILE_EXPECTED = 'content: "libli · Funkcja f(x) \\22 x\\22  \\3c /style\\3e ";'
EN_COUNTER = 'content: "Page " counter(page) " / " counter(pages);'
PL_COUNTER = 'content: "Strona " counter(page) " / " counter(pages);'


def _block(html):
    """From <style data-print-page> to the FIRST following </style>."""
    assert html.count("<style data-print-page>") == 1, "partial missing or doubled"
    return html.split("<style data-print-page>", 1)[1].split("</style>", 1)[0]


def _unit(kind, title):
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=kind, title=title)
    if kind == "lesson":
        add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    else:
        add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    return course, unit


def _get(client, kind, title, *, submitted=False, polish=False):
    user = make_login(client, "printer")
    course, unit = _unit(kind, title)
    EnrollmentFactory(course=course, student=user)
    if polish:
        client.post(reverse("core:set_ui_language"), {"language": "pl", "next": "/"})
    name = {"lesson": "courses:lesson_unit", "quiz": "courses:quiz_unit"}[kind]
    if submitted:
        QuizSubmission.objects.create(
            student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
        )
        name = "courses:quiz_results"
    resp = client.get(reverse(name, kwargs={"slug": course.slug, "node_pk": unit.pk}))
    assert resp.status_code == 200
    return resp.content.decode()


PAGES = [("lesson", False), ("quiz", False), ("quiz", True)]


@pytest.mark.django_db
@pytest.mark.parametrize(("kind", "submitted"), PAGES)
def test_hostile_title_is_escaped_and_block_is_intact(client, kind, submitted):
    block = _block(_get(client, kind, HOSTILE, submitted=submitted))
    # If </style> leaked unescaped, the slice would end early and BOTH would be missing.
    assert HOSTILE_EXPECTED in block
    assert EN_COUNTER in block


@pytest.mark.django_db
@pytest.mark.parametrize(("kind", "submitted"), PAGES)
def test_polish_ui_label(client, kind, submitted):
    block = _block(_get(client, kind, "Lekcja", submitted=submitted, polish=True))
    assert PL_COUNTER in block


@pytest.mark.django_db
def test_long_title_truncated_to_70(client):
    title = ("abcdefghij " * 19)[:200]  # letters and spaces only: nothing escapes
    block = _block(_get(client, "lesson", title))
    line = next(ln for ln in block.splitlines() if 'content: "libli · ' in ln)
    shown = line.split('content: "libli · ', 1)[1].rsplit('";', 1)[0]
    assert len(shown) <= 70
    assert shown.endswith("…")


@pytest.mark.django_db
def test_header_uses_literal_typography(client):
    block = _block(_get(client, "lesson", "T"))
    assert "var(" not in block
    assert "#5A544A" in block
    assert (
        '"Inter", "libli-dice", -apple-system, BlinkMacSystemFont, '
        '"Segoe UI", sans-serif'
    ) in block


def test_flash_messages_carry_marker_class():
    base = (Path(__file__).resolve().parent.parent / "templates/base.html").read_text(
        encoding="utf-8"
    )
    assert 'class="alert alert--flash alert--{{ message.tags }}"' in base
```

Check `make_login`'s signature in `tests/factories.py` (it takes `(client, username)` and returns the logged-in user). If `quiz_unit` redirects a submitted quiz, the `submitted=True` path deliberately GETs `quiz_results` directly.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_print_page_header.py`
Expected: FAIL — `AssertionError: partial missing or doubled` and the flash-marker assertion.

- [ ] **Step 3: Create the partial**

Create `templates/courses/_print_page_header.html` (no line-number citations; `{% comment %}` for multi-line comments):

```django
{% load i18n courses_extras %}{% comment %}
Running print header (spec 2026-10-11-print-layout-for-units section 1). @page margin
boxes are Chromium 131+; other engines ignore them silently and keep app.css's
@page margin. Colour and font are LITERAL because custom properties do not reach
margin boxes reliably. The title is truncated server-side so the result does not
depend on the engine honouring text-overflow in a margin box.
{% endcomment %}{% translate "Page" context "print page counter" as page_label %}<style data-print-page>
@page {
  @top-left {
    content: "libli · {{ unit.title|strip_math_delimiters|truncatechars:70|css_string }}";
    font-family: "Inter", "libli-dice", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 8pt;
    color: #5A544A;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @top-right {
    content: "{{ page_label|css_string }} " counter(page) " / " counter(pages);
    font-family: "Inter", "libli-dice", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 8pt;
    color: #5A544A;
  }
}
</style>
```

- [ ] **Step 4: Include it in the three templates**

In each of `lesson_unit.html`, `quiz_unit.html`, `quiz_results.html`, add as the LAST line inside `{% block extra_css %}` (just before its `{% endblock %}`):

```django
  {% include "courses/_print_page_header.html" %}
```

- [ ] **Step 5: Flash marker**

In `templates/base.html` change
`<div class="alert alert--{{ message.tags }}">{{ message }}</div>` to
`<div class="alert alert--flash alert--{{ message.tags }}">{{ message }}</div>`.
Then `grep -rn 'alert alert--{{ message' templates tests courses` — no other occurrence may assume the old class string.

- [ ] **Step 6: Translations**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```
In `locale/pl/LC_MESSAGES/django.po` find the new entry with `msgctxt "print page counter"`. makemessages pre-fills it from the existing un-contexted `"Page"` and marks it fuzzy. Make it exactly:

```
msgctxt "print page counter"
msgid "Page"
msgstr "Strona"
```
Delete its `#, fuzzy` line AND any `#| msgctxt …`/`#| msgid …` lines above it (two deletions). In `locale/en/LC_MESSAGES/django.po` the same entry keeps `msgstr ""` and must also carry no `#, fuzzy`/`#|` lines. Then:

```bash
uv run python manage.py compilemessages
git diff --stat locale/
```
`git diff locale/` must show only the new entry (plus the `POT-Creation-Date` header) per catalog; if makemessages rewrote unrelated entries, revert those hunks by hand.

- [ ] **Step 7: Run to verify they pass**

Run: `uv run pytest tests/test_print_page_header.py tests/test_print_button_template.py`
Then the catalog hygiene tests: `uv run pytest -k "catalog or fuzzy or obsolete or i18n"`
Expected: all PASS.

- [ ] **Step 8: Commit**

Lint first: `uv run ruff format tests/test_print_page_header.py`, then `uv run ruff check --no-cache` and `uv run ruff format --check` on it; both must be clean.

```bash
git add templates/courses/_print_page_header.html templates/courses/lesson_unit.html templates/courses/quiz_unit.html templates/courses/quiz_results.html templates/base.html locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo tests/test_print_page_header.py
git commit -m "feat(print): running page header with unit title and page n / N

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6"
```

---

### Task 3: Page frame in `app.css` (margins, header, main, flash)

**Files:**
- Modify: `core/static/core/css/app.css` (APPEND at end of file)
- Test: `tests/test_print_layout_css.py` (create; Task 4/5 extend it)
- Test: `tests/test_e2e_print_layout.py` (create; Tasks 4/5 extend it)

**Interfaces:**
- Consumes: `alert--flash` (Task 2).
- Produces: marker comment `/* == Print page frame (spec 2026-10-11-print-layout-for-units) == */` in app.css; the e2e module's helpers `_login`, `_student`, `_url`, `_inject_alerts`, `_hidden`, `_shown` reused by Tasks 4/5.

- [ ] **Step 1: Write the failing source tests**

Create `tests/test_print_layout_css.py`:

```python
"""Source tests for the unit print layout (spec 2026-10-11-print-layout-for-units, test 3).

Both new blocks are APPENDED to their sheets and found by their marker comment,
so each screen rule they override is provably earlier in the file.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "core/static/core/css/app.css").read_text(encoding="utf-8")
APP_MARK = "/* == Print page frame (spec 2026-10-11-print-layout-for-units) == */"


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _after(css, marker):
    """(marker index, comment-free text of everything from the marker on)."""
    i = css.find(marker)
    assert i >= 0, f"marker missing: {marker}"
    return i, _strip_comments(css[i:])


def _before(css, anchor, i):
    """Last occurrence of `anchor` strictly BEFORE index i (the new block itself
    repeats several screen selectors, so a whole-file rfind would find those)."""
    j = css.rfind(anchor, 0, i)
    assert j >= 0, f"screen anchor not found before the print block: {anchor!r}"
    return j


def _hides_are_important(block):
    bad = re.findall(r"display:\s*none(?!\s*!important)", block)
    assert not bad, f"print hide without !important: {bad}"


def test_page_margin():
    assert re.search(r"@page\s*\{\s*margin:\s*15mm;\s*\}", APP)


def test_app_block_after_screen_rules():
    i, _ = _after(APP, APP_MARK)
    for anchor in (
        ".app-header {",
        ".app-header__cluster {",
        ".app-main {",
        "  .app-header { flex-wrap: wrap;",
        "  .app-main { padding: var(--space-5)",
    ):
        _before(APP, anchor, i)
    # Nothing after the block may restyle these (the block must be LAST for them).
    tail = _strip_comments(APP[i:])
    assert tail.count(".app-main {") == 1 and tail.count(".app-header {") == 1


HIDE = r"\s*\{\s*display:\s*none\s*!important"


def test_app_block_contents():
    _, block = _after(APP, APP_MARK)
    _hides_are_important(block)
    assert re.search(r"\.app-header__spacer,\s*\.app-header__cluster" + HIDE, block)
    assert re.search(r"\.alert--flash" + HIDE, block)
    assert re.search(r"\.app-header\s*\{[^}]*background:\s*none[^}]*border:\s*0", block)
    assert re.search(r"\.app-main\s*\{[^}]*padding:\s*0[^}]*max-width:\s*none", block)
```

Before relying on the anchors, run `grep -n "^\.app-header__cluster {\|^\.app-header {\|^\.app-main {\|  \.app-header { flex-wrap\|  \.app-main { padding" core/static/core/css/app.css` and make each anchor string match the file exactly (each must be found).

- [ ] **Step 2: Write the failing e2e test (spec tests 4 + 7, app.css half)**

Create `tests/test_e2e_print_layout.py`:

```python
"""e2e for the unit print layout (spec 2026-10-11-print-layout-for-units, tests 4-10).

Print media is entered with page.emulate_media(media="print"). emulate_media keeps
the browser viewport, NOT the A4 page area, so page-width layout is covered by the
manual page.pdf() check (plan Task 6), not here. Every "hidden in print" assertion
is preceded by an attached (and where possible screen-visible) precondition, so it
cannot pass vacuously.
"""

import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 900}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _student(username, course, theme="light"):
    user = make_verified_user(
        username=username, email=f"{username}@test.example.com", password=TEST_PASSWORD
    )
    user.theme = theme
    user.save(update_fields=["theme"])
    EnrollmentFactory(course=course, student=user)
    return user


def _login(page, live_server, user):
    # Scoped: base.html renders one submit button per language in the header.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda u: "/accounts/login/" not in u)


def _url(live_server, name, unit):
    path = reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    return f"{live_server.url}{path}"


def _inject_alerts(page):
    """A flash (hidden in print) and a content alert (printed), both direct children of .app-main."""
    page.evaluate(
        """() => {
          const m = document.querySelector('.app-main');
          const p = document.createElement('p');
          p.className = 'alert alert--warning'; p.id = 'content-alert'; p.textContent = 'y';
          m.prepend(p);
          const d = document.createElement('div');
          d.className = 'alert alert--flash alert--info'; d.textContent = 'x';
          m.prepend(d);
        }"""
    )


def _shown(page, sel):
    loc = page.locator(sel)
    assert loc.count() >= 1, f"{sel} not attached"
    for i in range(loc.count()):
        assert loc.nth(i).is_visible(), f"{sel}[{i}] not visible"


def _hidden(page, sel):
    loc = page.locator(sel)
    assert loc.count() >= 1, f"{sel} not attached (assertion would be vacuous)"
    for i in range(loc.count()):
        assert not loc.nth(i).is_visible(), f"{sel}[{i}] still visible in print"


def _lesson(username, theme="light"):
    from courses.models import ShortTextQuestionElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="Printable")
    add_element(unit, TextElement.objects.create(body="<p>Body.</p>"))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    return course, unit, _student(username, course, theme)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_page_frame_header_and_flash(page, live_server, theme):
    course, unit, user = _lesson(f"pf-{theme}", theme)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    assert page.evaluate("document.documentElement.dataset.theme") == theme
    _inject_alerts(page)
    _shown(page, ".app-header__cluster")
    _shown(page, ".alert--flash")

    page.emulate_media(media="print")
    _hidden(page, ".app-header__cluster")
    _hidden(page, ".alert--flash")
    _shown(page, "#content-alert")
    _shown(page, ".brand")
    style = page.evaluate(
        """() => { const s = getComputedStyle(document.querySelector('.app-header'));
                   return [s.backgroundColor, s.backgroundImage, s.borderBottomWidth]; }"""
    )
    assert style == ["rgba(0, 0, 0, 0)", "none", "0px"], style
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py
```
Expected: source tests FAIL (`marker missing`); e2e FAILS on `.app-header__cluster[0] still visible in print`.

- [ ] **Step 4: Implement — append to the END of `core/static/core/css/app.css`**

```css

/* == Print page frame (spec 2026-10-11-print-layout-for-units) == */
/* Global on purpose: every page extending base.html prints with safe margins and
   without nav chrome or flash messages. The per-unit running header lives in
   templates/courses/_print_page_header.html. Appended LAST so it follows every
   `.app-header`, `.app-header__cluster` and `.app-main` screen rule, including the
   max-width: 640px block (print on small paper matches it). Every hide is
   !important so position and specificity never decide it. */
@page { margin: 15mm; }
@media print {
  .app-header__spacer, .app-header__cluster { display: none !important; }
  .app-header { padding: 0 0 var(--space-4); background: none; border: 0; }
  .app-main { padding: 0; max-width: none; }
  /* Only marked flash messages: content alerts that are direct children of
     .app-main (e.g. support's "Not emailed" warning) must keep printing. */
  .alert--flash { display: none !important; }
}
```

- [ ] **Step 5: Run to verify they pass, plus every CSS test**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py
uv run pytest tests/test_*css*.py courses/tests/test_*css*.py
```
Expected: all PASS. If the e2e header style assertion fails with a non-transparent colour, grep app.css for a `[data-theme="dark"] .app-header` or other heavier background rule and raise the print selector's weight to match — do not drop the assertion.

- [ ] **Step 6: Commit**

Lint first: `uv run ruff format tests/test_print_layout_css.py tests/test_e2e_print_layout.py`, then `uv run ruff check --no-cache` and `uv run ruff format --check` on the same two files; both must be clean.

```bash
git add core/static/core/css/app.css tests/test_print_layout_css.py tests/test_e2e_print_layout.py
git commit -m "feat(print): 15mm page margins; hide header nav and flash messages in print

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6"
```

---

### Task 4: Unit chrome, controls and steppers in `courses.css`

**Files:**
- Modify: `courses/static/courses/css/courses.css` (APPEND at end of file)
- Test: `tests/test_print_layout_css.py`, `tests/test_e2e_print_layout.py` (extend)

**Interfaces:**
- Consumes: Task 3's e2e helpers (`_login`, `_student`, `_url`, `_inject_alerts`, `_shown`, `_hidden`, `_lesson`, `VIEWPORT`).
- Produces: marker `/* == Print layout for units (spec 2026-10-11-print-layout-for-units) == */` opening ONE `@media print { … }` block at the end of courses.css; Task 5 adds its rules INSIDE this same block.

- [ ] **Step 1: Write the failing source tests** — append to `tests/test_print_layout_css.py`:

```python
COURSES = (ROOT / "courses/static/courses/css/courses.css").read_text(encoding="utf-8")
COURSES_MARK = "/* == Print layout for units (spec 2026-10-11-print-layout-for-units) == */"
TEMPLATES = "\n".join(
    p.read_text(encoding="utf-8") for p in (ROOT / "templates/courses").rglob("*.html")
)
EXTRAS = (ROOT / "courses/templatetags/courses_extras.py").read_text(encoding="utf-8")
GALLERY_JS = (ROOT / "courses/static/courses/js/gallery.js").read_text(encoding="utf-8")

CHROME_HIDES = [
    ".unit-foot", ".unit-tree", ".unit-drawer", ".unit-strip", ".draft-banner",
    ".unit-done", ".lesson-unit__reset", ".quiz-finish", ".quiz-results > .btn",
    '.el--question .question__form button[type="submit"]',
]
ACTION_HIDES = [
    ".filltable__confirm", ".markdone__save", ".fillgate__confirm", ".stepper__next",
    ".switchgate__confirm", ".switchgrid__confirm", "[data-guess-check]",
]
STEPPER_REVEALS = [
    ".stepper.is-stepping [data-stepper-step]:not(.stepper-shown)",
    ".stepper-armed .stepper [data-stepper-step]:not(.stepper-shown):not(:first-child)",
]


def _courses_block():
    i, block = _after(COURSES, COURSES_MARK)
    return i, block


def _rule_selectors(block, decl_regex):
    """Selectors of every rule in `block` whose body matches decl_regex.

    `block` comes from _after(), which has already stripped /* comments */ — a
    comment before a rule would otherwise be glued onto its first selector."""
    block = _strip_comments(block)
    sels = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
        if re.search(decl_regex, m.group(2)):
            sels += [s.strip() for s in m.group(1).split(",")]
    return sels


def test_courses_block_hides_are_important():
    _, block = _courses_block()
    _hides_are_important(block)


def test_chrome_and_action_hides_present():
    _, block = _courses_block()
    hidden = _rule_selectors(block, r"display:\s*none\s*!important")
    for sel in CHROME_HIDES + ACTION_HIDES:
        assert sel in hidden, f"{sel} not hidden in print"


def test_action_hide_names_exist_in_source():
    src = TEMPLATES + EXTRAS
    for name in ["filltable__confirm", "markdone__save", "fillgate__confirm", "stepper__next",
                 "switchgate__confirm", "switchgrid__confirm", "data-guess-check",
                 "unit-done", "lesson-unit__reset", "quiz-finish", "draft-banner", "unit-strip"]:
        assert name in src, f"{name} matches nothing in templates/templatetags"


def test_stepper_reveal_covers_post_and_pre_boot():
    _, block = _courses_block()
    revealed = _rule_selectors(block, r"display:\s*revert\s*!important")
    for sel in STEPPER_REVEALS:
        assert sel in revealed


def test_unit_shell_block_is_scoped():
    _, block = _courses_block()
    blocks = _rule_selectors(block, r"display:\s*block")
    assert "[data-unit-shell]" in blocks
    assert "[data-unit-shell] > .unit-shell__main" in blocks
    assert ".unit-shell" not in blocks  # review_submission.html reuses .unit-shell


STEPPER_SCREEN_HIDE = (
    ".stepper.is-stepping [data-stepper-step]:not(.stepper-shown)"
    " { display: none !important; }"
)


def test_courses_block_after_screen_rules():
    i, _ = _courses_block()
    for anchor in (
        ".unit-shell { display: flex;",
        "  .unit-shell { display: block; }",
        STEPPER_SCREEN_HIDE,
        ".unit-strip { display: flex;",
        ".draft-banner {",
    ):
        _before(COURSES, anchor, i)
```

Verify each anchor with grep first (`grep -n "^\.unit-strip {\|^\.draft-banner {\|^\.unit-shell {\|  \.unit-shell { display: block" courses/static/courses/css/courses.css`) and adjust the string to the file's exact text.

- [ ] **Step 2: Write the failing e2e tests** — append to `tests/test_e2e_print_layout.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_lesson_unit_chrome_hidden(page, live_server):
    """Spec test 4 (courses.css half)."""
    course, unit, user = _lesson("chrome-stu")
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    for sel in (".unit-foot", ".unit-strip", ".unit-done",
                '.el--question .question__form button[type="submit"]'):
        _shown(page, sel)
    assert page.locator(".unit-tree").count() >= 1

    page.emulate_media(media="print")
    for sel in (".unit-foot", ".unit-strip", ".unit-done",
                '.el--question .question__form button[type="submit"]'):
        _hidden(page, sel)
    assert page.evaluate("getComputedStyle(document.querySelector('.unit-tree')).display") == "none"
    _shown(page, ".unit-crumbs")
    _shown(page, ".unit-kind-chip")
    shell_x, main_x = page.evaluate(
        """() => [document.querySelector('[data-unit-shell]').getBoundingClientRect().left,
                  document.querySelector('[data-unit-shell] > .unit-shell__main').getBoundingClientRect().left]"""
    )
    assert abs(shell_x - main_x) <= 1, (shell_x, main_x)


@pytest.mark.django_db(transaction=True)
def test_toc_pin_hidden_in_print_when_collapsed(page, live_server):
    """Pre-existing coverage kept for completeness (spec §3): NOT evidence for new rules."""
    course, unit, user = _lesson("pin-stu")
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    page.evaluate("document.documentElement.classList.add('unit-tree-collapsed')")
    _shown(page, ".unit-toc-pin")
    page.emulate_media(media="print")
    _hidden(page, ".unit-toc-pin")


@pytest.mark.django_db(transaction=True)
def test_draft_banner_hidden_for_author(page, live_server):
    from courses.models import TextElement

    owner = make_verified_user(username="owner-pr", email="owner-pr@test.example.com",
                               password=TEST_PASSWORD)
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson",
                              title="Draft", published=False)
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, owner)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".lesson-unit__title")
    _shown(page, ".draft-banner")
    page.emulate_media(media="print")
    _hidden(page, ".draft-banner")


@pytest.mark.django_db(transaction=True)
def test_quiz_multi_slide_prints_every_question(page, live_server):
    """Spec test 5."""
    from tests.factories import seed_slideshow_unit

    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q", "brk", "q"])
    user = _student("quiz-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_unit", unit))
    page.wait_for_selector(".slideshow-bar")
    _inject_alerts(page)
    for sel in (".app-header__cluster", ".unit-foot", ".unit-strip", ".slideshow-bar"):
        _shown(page, sel)
    assert page.locator(".quiz-finish").count() >= 1

    page.emulate_media(media="print")
    for sel in (".app-header__cluster", ".unit-foot", ".unit-strip", ".alert--flash",
                ".slideshow-bar", ".quiz-finish"):
        _hidden(page, sel)
    for sel in (".brand", ".unit-crumbs", ".unit-kind-chip"):
        _shown(page, sel)
    assert page.locator(".el--question").count() == 3
    _shown(page, ".el--question")


@pytest.mark.django_db(transaction=True)
def test_single_slide_quiz_finish_hidden(page, live_server):
    from tests.factories import seed_slideshow_unit

    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q"])
    user = _student("quiz1-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_unit", unit))
    page.wait_for_selector(".quiz-finish")
    _shown(page, ".quiz-finish")
    page.emulate_media(media="print")
    _hidden(page, ".quiz-finish")


@pytest.mark.django_db(transaction=True)
def test_action_buttons_hidden_and_stepper_prints_all(page, live_server):
    """Spec test 10."""
    from courses.models import FillTableElement
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import StepperElement
    from courses.models import StepperStep

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="Stateful")
    ft = FillTableElement.objects.create(
        data=FillTableElement.normalize_data({
            "header_row": False, "header_col": False, "border": "grid",
            "prompt": "", "case_sensitive": False,
            "cells": [[{"kind": "answer", "answer": "4", "halign": "left", "valign": "top"}]],
        })
    )
    add_element(unit, ft)
    md = MarkDoneElement.objects.create(prompt="Do it")
    MarkDoneItem.objects.create(element=md, content="a")
    add_element(unit, md)
    st = StepperElement.objects.create(prompt="")
    for c in ("one", "two", "three"):
        StepperStep.objects.create(stepper=st, content=c)
    add_element(unit, st)
    user = _student("act-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".stepper.is-stepping")  # proves stepper.js booted
    _shown(page, ".stepper__next")
    _shown(page, ".filltable__confirm")
    _shown(page, ".lesson-unit__reset")
    assert page.locator(".markdone__save").count() >= 1
    steps = page.locator("[data-stepper-step]")
    assert steps.count() == 3
    assert [steps.nth(i).is_visible() for i in range(3)] == [True, False, False]

    page.emulate_media(media="print")
    for sel in (".filltable__confirm", ".markdone__save", ".stepper__next", ".lesson-unit__reset"):
        _hidden(page, sel)
    _shown(page, "[data-stepper-step]")
```

If a fixture constructor signature differs (e.g. `MarkDoneItem` field names, `FillTableElement.normalize_data` keys), copy the working construction from `tests/test_e2e_markdone.py`, `tests/test_e2e_filltable.py`, `tests/test_e2e_stepper.py` — do not weaken the assertions.

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py
```
Expected: new source tests FAIL (`marker missing`); new e2e tests FAIL with `… still visible in print` (the TOC-pin test may already PASS — it is pre-existing coverage).

- [ ] **Step 4: Implement — append to the END of `courses/static/courses/css/courses.css`**

```css

/* == Print layout for units (spec 2026-10-11-print-layout-for-units) == */
/* ONE print block, appended last, so it follows every screen rule it overrides
   (`.unit-shell`, `.unit-strip`, `.draft-banner`, the stepper hide, the gallery
   carousel). Every hide is !important: e.g. app.css's
   `.guessnumber button[data-guess-check]` outweighs a bare attribute selector
   wherever it sits. */
@media print {
  /* D1: screen chrome and controls. Kept: .unit-kind-chip, .answer-switch, the
     switch cyclers (their text IS the student's value), .question__feedback,
     notes, and closed spoilers (they keep their on-screen state). */
  .unit-foot, .unit-tree, .unit-drawer, .unit-strip, .draft-banner,
  .unit-done, .lesson-unit__reset,
  .quiz-finish, .quiz-results > .btn,
  .el--question .question__form button[type="submit"],
  .filltable__confirm, .markdone__save, .fillgate__confirm, .stepper__next,
  .switchgate__confirm, .switchgrid__confirm, [data-guess-check] { display: none !important; }

  /* Block flow, scoped by attribute: manage/review_submission.html reuses the
     bare `.unit-shell` wrapper for its own two-column layout. */
  [data-unit-shell], [data-unit-shell] > .unit-shell__main { display: block; }

  /* Steppers print every step (reveal-gate precedent). First selector: after
     stepper.js boots; second: lesson_unit.html's pre-boot `.stepper-armed` hide. */
  .stepper.is-stepping [data-stepper-step]:not(.stepper-shown),
  .stepper-armed .stepper [data-stepper-step]:not(.stepper-shown):not(:first-child) { display: revert !important; }
}
```

- [ ] **Step 5: Run to verify they pass, plus every CSS test**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py
uv run pytest tests/test_*css*.py courses/tests/test_*css*.py
uv run pytest -m e2e tests/test_e2e_print_foundations.py tests/test_e2e_print_lesson_notes.py tests/test_e2e_stepper.py
```
Expected: all PASS.

- [ ] **Step 6: Commit**

Lint first: `uv run ruff format tests/test_print_layout_css.py tests/test_e2e_print_layout.py`, then `uv run ruff check --no-cache` and `uv run ruff format --check` on the same two files; both must be clean.

```bash
git add courses/static/courses/css/courses.css tests/test_print_layout_css.py tests/test_e2e_print_layout.py
git commit -m "feat(print): hide unit chrome and controls; print every stepper step

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6"
```

---

### Task 5: Keep images and questions whole (D6) + gallery carousel in print

**Files:**
- Modify: `courses/static/courses/css/courses.css` (inside the Task 4 `@media print` block, before its closing `}`)
- Test: `tests/test_print_layout_css.py`, `tests/test_e2e_print_layout.py` (extend)

**Interfaces:**
- Consumes: Task 4's block and helpers.
- Produces: none for later tasks.

- [ ] **Step 0: Correct the spec's false claim**

In `docs/superpowers/specs/2026-10-11-print-layout-for-units-design.md`, Testing #5,
replace the sentence beginning "The fixture quiz includes a **drag-to-image** question"
(through "…before the computed-style check.") with:
"Every `QuestionElement` subclass sets `SUPPORTS_REVEAL = True` (verified in
`courses/models.py`), so every results row currently wraps a rendered `.el--question`
and the non-reveal branch of `quiz_results.html` is unreachable; the test asserts
`break-inside: avoid` on a `.quiz-results__item` row (count ≥ 1 first). The
`.quiz-results__item` rule still covers the non-reveal branch should it become reachable."
Commit it on its own:
`git add docs/superpowers/specs/2026-10-11-print-layout-for-units-design.md` and
`git commit -m "docs(print-layout-for-units): correct SUPPORTS_REVEAL claim in spec"` (with the two trailer lines).

- [ ] **Step 1: Write the failing source tests** — append to `tests/test_print_layout_css.py`:

```python
D6_AVOID = [".el--image", ".el--gallery .gallery__item", "img.cell-img",
            ".dragimage__stage", ".el--question", ".quiz-results__item"]


def test_d6_break_inside_list():
    _, block = _courses_block()
    avoid = _rule_selectors(block, r"break-inside:\s*avoid")
    for sel in D6_AVOID:
        assert sel in avoid, f"{sel} missing from break-inside: avoid"
    assert ".el__qnum" in _rule_selectors(block, r"break-after:\s*avoid")


def test_d6_class_names_exist():
    src = TEMPLATES + GALLERY_JS
    for name in ("el--image", "gallery__item", "cell-img", "dragimage__stage",
                 "el--question", "quiz-results__item", "el__qnum", "gallery__bar",
                 "gallery__status", "gallery__stage", "gallery--js"):
        assert name in src, f"{name} matches nothing"


def test_d6_caps():
    _, block = _courses_block()
    assert ".dragimage__img" in _rule_selectors(block, r"max-height:\s*170mm")
    assert ".el--gallery .gallery__frame" in _rule_selectors(block, r"max-height:\s*170mm")


def _decl(block, selector):
    """Body of the rule whose selector list contains exactly `selector`."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(block)):
        if selector in [s.strip() for s in m.group(1).split(",")]:
            return m.group(2)
    raise AssertionError(f"no rule for {selector}")


def test_gallery_carousel_reset():
    _, block = _courses_block()
    item = _decl(block, ".el--gallery.gallery--js .gallery__item")
    assert re.search(r"position:\s*static\s*!important", item)
    assert re.search(r"opacity:\s*1\s*!important", item)
    stage = _decl(block, ".el--gallery.gallery--js .gallery__stage")
    assert re.search(r"position:\s*static\s*!important", stage)
    assert re.search(r"min-height:\s*0\s*!important", stage)
    desc = _decl(block, ".el--gallery.gallery--js .gallery__desc")
    assert re.search(r"min-height:\s*0\s*!important", desc)
    hidden = _rule_selectors(block, r"display:\s*none\s*!important")
    assert ".el--gallery .gallery__bar" in hidden
    assert ".el--gallery .gallery__status" in hidden


def test_d6_block_after_screen_rules():
    i, _ = _courses_block()
    for anchor in (
        ".dragimage__img {",
        ".el--gallery .gallery__frame {",
        ".el--gallery.gallery--js .gallery__item {",
    ):
        _before(COURSES, anchor, i)
```

- [ ] **Step 2: Write the failing e2e tests** — append to `tests/test_e2e_print_layout.py`:

```python
def _png(size, rgb=(90, 120, 200)):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", size, rgb).save(buf, "PNG")
    return buf.getvalue()


MM170_PX = 170 / 25.4 * 96  # 642.5


@pytest.mark.django_db(transaction=True)
def test_break_inside_cascade(page, live_server):
    """Spec test 6: CASCADE check only; actual pagination is the Task 6 PDF check."""
    from courses.models import ImageElement
    from courses.models import ShortTextQuestionElement
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="b.png", raw=_png((400, 300)))
    add_element(unit, ImageElement.objects.create(media=asset, alt="b", size="medium"))
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    user = _student("brk-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".el--image img")
    page.emulate_media(media="print")
    for sel in (".el--image", ".el--question"):
        assert page.evaluate(f"getComputedStyle(document.querySelector('{sel}')).breakInside") == "avoid"


@pytest.mark.django_db(transaction=True)
def test_tall_dragimage_capped_and_badges_aligned(page, live_server):
    """Spec test 8."""
    from courses.models import DragToImageQuestionElement
    from courses.models import DragZone
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="tall.png", raw=_png((600, 1600)))
    q = DragToImageQuestionElement.objects.create(media=asset, alt="Tall")
    for n, (x, y) in enumerate([(0.2, 0.2), (0.5, 0.5), (0.8, 0.8)]):
        DragZone.objects.create(question=q, correct_label=f"L{n}", x=x, y=y, w=0.1, h=0.1, order=n)
    add_element(unit, q)
    user = _student("drag-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    img = page.locator(".dragimage__img").first
    img.wait_for()
    page.wait_for_function("el => el.complete && el.naturalWidth > 0", arg=img.element_handle())
    assert img.bounding_box()["height"] > MM170_PX + 1, "fixture too short: cap would not engage"

    page.emulate_media(media="print")
    geo = page.evaluate(
        """() => {
          const stage = document.querySelector('.dragimage__stage');
          const img = stage.querySelector('.dragimage__img').getBoundingClientRect();
          const st = stage.getBoundingClientRect();
          const badges = [...stage.querySelectorAll('.dragimage__badge')].map(b => {
            const r = b.getBoundingClientRect();
            return {cx: r.left + r.width / 2, cy: r.top + r.height / 2,
                    x: parseFloat(b.dataset.x), y: parseFloat(b.dataset.y)};
          });
          return {img: [img.left, img.top, img.width, img.height], stageW: st.width, badges};
        }"""
    )
    left, top, w, h = geo["img"]
    assert h <= MM170_PX + 0.5, h
    assert abs(geo["stageW"] - w) <= 1, (geo["stageW"], w)
    assert len(geo["badges"]) == 3
    for b in geo["badges"]:
        assert abs(b["cx"] - (left + b["x"] * w)) <= 2, b
        assert abs(b["cy"] - (top + b["y"] * h)) <= 2, b


@pytest.mark.django_db(transaction=True)
def test_js_gallery_prints_every_image(page, live_server):
    """Spec test 9."""
    from courses.models import GalleryElement
    from tests.factories import make_image_asset

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    assets = [make_image_asset(course, filename=f"g{n}.png", raw=_png((400, 300), (40 * n, 120, 200)))
              for n in range(3)]
    add_element(unit, GalleryElement.objects.create(
        data={"images": [{"media": a.pk, "desc": ""} for a in assets], "desc_pos": "below"}))
    user = _student("gal-stu", course)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:lesson_unit", unit))
    page.wait_for_selector(".el--gallery.gallery--js")
    _shown(page, ".el--gallery .gallery__bar")

    page.emulate_media(media="print")
    _hidden(page, ".el--gallery .gallery__bar")
    boxes = page.evaluate(
        """() => [...document.querySelectorAll('.gallery__item')].map(it => {
          const r = it.getBoundingClientRect(); const img = it.querySelector('img');
          const ir = img.getBoundingClientRect();
          return {top: r.top, bottom: r.bottom, imgW: ir.width, imgH: ir.height,
                  opacity: getComputedStyle(it).opacity};
        })"""
    )
    assert len(boxes) == 3
    for b in boxes:
        assert b["imgW"] > 0 and b["imgH"] > 0 and b["opacity"] == "1", b
    for a, b in zip(boxes, boxes[1:]):
        assert a["bottom"] <= b["top"] + 0.5, (a, b)  # stacked, not overlapping


@pytest.mark.django_db(transaction=True)
def test_quiz_results_chrome_and_row_break(page, live_server):
    """Spec test 5, results half.

    Every QuestionElement subclass sets SUPPORTS_REVEAL = True, so today every
    results row wraps a rendered .el--question; the "non-reveal row" branch of
    quiz_results.html is unreachable (the spec's drag-to-image claim was wrong and
    is corrected in Step 0). The rule is on .quiz-results__item itself, so the
    row's own computed break-inside is what is asserted."""
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", title="Done")
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
    user = _student("res-stu", course)
    QuizSubmission.objects.create(student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED)
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_url(live_server, "courses:quiz_results", unit))
    page.wait_for_selector(".quiz-results")
    _shown(page, ".unit-strip")
    _shown(page, ".quiz-results > .btn")
    assert page.locator(".quiz-results__item").count() >= 1

    page.emulate_media(media="print")
    _hidden(page, ".unit-strip")
    _hidden(page, ".quiz-results > .btn")
    row_break = page.evaluate(
        "getComputedStyle(document.querySelector('.quiz-results__item')).breakInside"
    )
    assert row_break == "avoid"
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py -k "break_inside or dragimage or gallery or quiz_results"
```
Expected: FAIL (`missing from break-inside`, `h > 642`, overlapping gallery items, `row_break == "auto"`). `test_quiz_results_chrome_and_row_break`'s `.unit-strip` / `.btn` hides are already green from Task 4 — the `row_break` assertion is the new red.

- [ ] **Step 4: Implement** — insert INSIDE the Task 4 `@media print` block, after the stepper rule, before the closing `}`:

```css

  /* D6: never split an image (with its caption) or a single question. Long
     text, callouts and tables flow normally. img.cell-img is an atomic box
     anyway; listed for coverage. */
  .el--image, .el--gallery .gallery__item, img.cell-img, .dragimage__stage,
  .el--question, .quiz-results__item { break-inside: avoid; }
  .el__qnum { break-after: avoid; }

  /* D6 caps (A4 minus 2 x 15mm = 267mm of content height). The drag stage is
     shrink-to-fit, so capping the <img> scales its width and the percent-placed
     badges follow. The gallery's screen `70vh` is not a print bound. */
  .dragimage__img { max-height: 170mm; }
  .el--gallery .gallery__frame { max-height: 170mm; }

  /* gallery.js stacks every card absolutely at opacity 0 except the active one
     and sets inline min-heights; on paper every card prints, stacked. */
  .el--gallery.gallery--js .gallery__stage { position: static !important; min-height: 0 !important; }
  .el--gallery.gallery--js .gallery__item { position: static !important; opacity: 1 !important; transition: none !important; }
  .el--gallery.gallery--js .gallery__item + .gallery__item { margin-top: var(--space-4); }
  .el--gallery.gallery--js .gallery__desc { min-height: 0 !important; }
  .el--gallery .gallery__bar, .el--gallery .gallery__status { display: none !important; }
```

- [ ] **Step 5: Run to verify they pass, plus every CSS test and neighbouring e2e**

```bash
uv run pytest tests/test_print_layout_css.py
uv run pytest -m e2e tests/test_e2e_print_layout.py
uv run pytest tests/test_*css*.py courses/tests/test_*css*.py
uv run pytest -m e2e tests/test_e2e_gallery.py tests/test_e2e_dark_image_plate.py tests/test_e2e_image_float_notes.py
```
Expected: all PASS. Run e2e files one command at a time in the foreground (never two pytest runs at once — they share the test DB).

- [ ] **Step 6: Commit**

Lint first: `uv run ruff format tests/test_print_layout_css.py tests/test_e2e_print_layout.py`, then `uv run ruff check --no-cache` and `uv run ruff format --check` on the same two files; both must be clean.

```bash
git add courses/static/courses/css/courses.css tests/test_print_layout_css.py tests/test_e2e_print_layout.py
git commit -m "feat(print): keep images and questions on one page; print every gallery image

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MZiddHy9T3UgRttXEkkir6"
```

---

### Task 6: Visual verification with real PDFs + mutation check

**Files:** none committed. Scratch only: `C:\Users\krzys\AppData\Local\Temp\claude\C--Users-krzys-Documents-Python-own-libli\dfdb22bc-bd2e-491e-b305-c6349e51118a\scratchpad\print-pdfs\`.

- [ ] **Step 1: Falsify the key tests (they must go RED on a broken build)**

Edit by hand (never `git checkout` to revert — it destroys uncommitted work; restore with the inverse hand edit), one at a time, run the named test, confirm FAIL, restore, confirm PASS:
1. In courses.css's print block delete `!important` from the hide rule → `test_courses_block_hides_are_important` FAILS.
2. Remove `.quiz-results__item` from the break-inside list → `test_quiz_results_chrome_and_row_break` FAILS at the `row_break == "avoid"` assertion (check the failure line — a failure anywhere else means the mutant was not what turned it red).
3. Change `.dragimage__img { max-height: 170mm; }` to `400mm` → `test_tall_dragimage_capped_and_badges_aligned` FAILS.
4. In `_print_page_header.html` drop `|css_string` from the title → `test_hostile_title_is_escaped_and_block_is_intact` FAILS.
Run `git diff` after each restore: it must be empty for the touched file.

- [ ] **Step 2: Generate PDFs**

Write a TEMPORARY `tests/test_zz_print_pdfs.py` (it must live under `tests/` to get the repo conftest, `live_server` and DB setup; run it with `uv run pytest -m e2e tests/test_zz_print_pdfs.py`; write PDFs into the scratchpad `print-pdfs/` dir; delete the file before any commit and confirm with `git status`) that builds, logs in and calls `page.pdf(path=…, format="A4", print_background=False)` for:
- a long lesson: 15 paragraphs, a `full` image, a `medium` float-right image placed after ~6 paragraphs (near a page boundary), a 3-image gallery, a tall drag-to-image question, a stepper, a 200-character title;
- the same lesson as `format="A5"`;
- a 3-slide quiz;
- a submitted quiz's results page;
- the lesson in the dark stored theme.

- [ ] **Step 3: Inspect every PDF**

Open each with the Read tool (it renders PDF pages). Check and write down, per PDF: running header `libli · …` top-left and `Page n / N` top-right on EVERY page; margins ≈ 15 mm; no image or question split across a page boundary; no header nav, footer bar, tags strip, buttons; gallery shows all 3 images; all stepper steps present; A5 shows no drawer; dark-theme PDF is dark-on-white. Any defect → fix in CSS, add a test that pins it, re-run Tasks 3–5 test commands.

- [ ] **Step 4: Record**

Save 2–3 representative page screenshots (Playwright `page.screenshot` under `emulate_media("print")`, or PDF page renders) in the scratchpad for the PR description. Delete any temporary test file; `git status` must show a clean tree except intended commits.

---

## Self-Review

- **Spec coverage:** §1 header → Task 2; §2 filter → Task 1; §3 chrome/flash/controls/stepper/shell/scope → Tasks 3–4; §4 D6 breaks, caps, gallery → Task 5; §5 quiz → Task 4 (multi/single slide); §6 results page → Tasks 2, 4 (`.btn` hide), 5 (row break); spec tests 1–10 → Tasks 1–5; manual PDF check → Task 6. Spoilers/notes/answer-switch/cyclers/kind chip deliberately untouched (comment in the CSS block).
- **Placeholder scan:** none; every code step has full code. Fixture-construction fallbacks point at named existing e2e files.
- **Type consistency:** `css_string` (Task 1) used in Task 2's partial; markers `APP_MARK`/`COURSES_MARK` defined once and reused; helpers `_shown`/`_hidden`/`_inject_alerts`/`_lesson`/`_student`/`_login`/`_url` defined in Task 3, used in Tasks 4–5; `_png`/`MM170_PX` defined in Task 5 before use.
