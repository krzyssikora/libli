# Illustrated error pages (404 / 403) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two bare error cards with an illustrated, bilingual (EN/PL) 404 and 403 sharing one masked learner watermark that re-tints itself from the theme token.

**Architecture:** One derived `LA`-mode PNG acts as a CSS mask; a new per-page sheet `error.css` paints it as a fixed, bottom-anchored, decorative `::after` filled with `var(--text-primary)`. Both templates keep `base.html` (header, nav, language switch stay) and add a body class plus the stylesheet link. No new views, no new URLs, no models, no migrations — Django's built-in `page_not_found` / `permission_denied` already render these templates.

**Tech Stack:** Django 5.2 templates, plain CSS with custom properties, Pillow (one-shot asset derivation), pytest + pytest-django, Playwright (screenshots only).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-23-illustrated-error-pages-design.md` — read it before Task 1. It carries measurements and rationale this plan does not repeat.
- **Working directory:** `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/illustrated-error-pages`. All paths below are relative to it.
- **Tooling:** bash `python`/`pytest`/`ruff` are NOT on PATH. Always `uv run python …`, `uv run pytest …`, `uv run ruff …`.
- **Test DB:** this worktree's `.env` already names `libli_errpages`. **Verify it, never overwrite it** — `.env` is untracked, so a clobber is unrecoverable.
- **`templates/500.html` is out of scope.** Do not touch it. Its `Back to home` is an untranslated literal and stays.
- **No raw hex in `error.css`.** Colours are tokens only (`test_error_page_styles.py` asserts this).
- **Polish copy rules (user-set, non-negotiable):** use `link`, never `odnośnik`; informal `ty` register; no gendered past-tense forms (`trafiłeś`/`trafiłaś`).
- **Never `|safe` on `request_path`.**
- **Falsify every test:** each test must be seen to FAIL before its implementation exists. A passing test that has never been red proves nothing.
- **Commit after every task.** Never `git add -A` / `git add .` — always explicit paths.

---

### Task 1: Derive the watermark asset

**Files:**
- Create: `core/static/core/img/learner.png`
- Test: `tests/test_error_page_styles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `core/static/core/img/learner.png` — `LA` mode, exactly `1600×672`, ≤ 60 KB. Tasks 2 and 6 depend on it existing at that exact path and size.

- [ ] **Step 1: Write the failing test**

Create `tests/test_error_page_styles.py`:

```python
"""Static-asset and stylesheet guards for the error pages.

Mirrors the convention in test_auth_styles.py / test_settings_styles.py: a new
per-page sheet ships with a regression guard for its vocabulary and its assets.
See docs/superpowers/specs/2026-07-23-illustrated-error-pages-design.md.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LEARNER = ROOT / "core" / "static" / "core" / "img" / "learner.png"


def test_learner_asset_exists_and_is_an_alpha_mask():
    # Not a nicety: production uses CompressedManifestStaticFilesStorage, whose
    # post-processing RAISES on a url() target that is missing -- so an absent
    # asset aborts collectstatic and stops the deploy.
    assert LEARNER.exists(), "learner.png missing -- collectstatic would abort"
    with Image.open(LEARNER) as im:
        assert im.mode == "LA", f"mask must be LA (alpha-only), got {im.mode}"
        assert im.size == (1600, 672), (
            "error.css hard-codes aspect-ratio: 1600 / 672; a re-derivation at a "
            f"different size would silently break the layout. Got {im.size}"
        )


def test_learner_asset_is_within_budget():
    size = LEARNER.stat().st_size
    assert size <= 60 * 1024, f"learner.png is {size} bytes; budget is 60 KB"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_error_page_styles.py -v`
Expected: FAIL — `assert LEARNER.exists()` (the file does not exist yet).

- [ ] **Step 3: Derive the asset**

The source is a one-off local input, **not** committed: `C:/Users/krzys/Downloads/learner_bw.png` (opaque RGB, 1600×672, black scene on white). Run this once:

```bash
uv run python - <<'PY'
from PIL import Image

SRC = r"C:/Users/krzys/Downloads/learner_bw.png"
DST = "core/static/core/img/learner.png"

src = Image.open(SRC).convert("L")
W, H = src.size
alpha = src.point(lambda v: 255 - v)   # inverted luminance keeps anti-aliased edges

start, span = 0.60 * H, 0.40 * H
px = alpha.load()
for y in range(H):
    if y <= start:
        continue
    t = min(max((y - start) / span, 0.0), 1.0)
    f = 1.0 - (3 * t * t - 2 * t * t * t)          # smoothstep
    for x in range(W):
        px[x, y] = int(px[x, y] * f)

# Image.merge (not a mutated source) so no ICC/EXIF metadata is carried over.
out = Image.merge("LA", (Image.new("L", (W, H), 0), alpha))
out.save(DST, optimize=True)

with Image.open(DST) as chk:
    import os
    print(chk.mode, chk.size, os.path.getsize(DST), "bytes")
PY
```

Expected output: `LA (1600, 672) 17902 bytes` (±a few bytes across Pillow versions).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_error_page_styles.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/static/core/img/learner.png tests/test_error_page_styles.py
git commit -m "feat(error-pages): derive the learner watermark mask asset"
```

---

### Task 2: The stylesheet

**Files:**
- Create: `core/static/core/css/error.css`
- Modify: `tests/test_error_page_styles.py` (append)

**Interfaces:**
- Consumes: `core/static/core/img/learner.png` (Task 1), referenced as `url("../img/learner.png")`.
- Produces: the class vocabulary Tasks 3 and 4 apply in markup — `.error-page` (body class), `.error-page__main`, `__inner`, `__code`, `__title`, `__lead`, `__path`, `__note`, `__actions`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_error_page_styles.py`:

```python
import re

ERROR_CSS = ROOT / "core" / "static" / "core" / "css" / "error.css"


def test_error_css_defines_the_error_page_vocabulary():
    css = ERROR_CSS.read_text(encoding="utf-8")
    for cls in (
        ".error-page__main",
        ".error-page__inner",
        ".error-page__code",
        ".error-page__title",
        ".error-page__lead",
        ".error-page__path",
        ".error-page__note",
        ".error-page__actions",
    ):
        assert cls in css, f"error.css must style {cls}"


def test_error_css_guards_mask_support_and_prefixes_every_longhand():
    # The @supports arm deliberately admits prefix-only engines; those engines
    # ignore the UNPREFIXED longhands, so dropping a -webkit- form would let them
    # through the guard and paint the mask tiled at 1600x672, top-left.
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert "@supports" in css
    for prop in (
        "-webkit-mask-image",
        "-webkit-mask-repeat",
        "-webkit-mask-position",
        "-webkit-mask-size",
    ):
        assert prop in css, f"{prop} missing -- prefix-only engines would misrender"
    # mask-mode is the documented exception: no -webkit- form exists in any engine.
    assert "mask-mode: alpha" in css
    assert "-webkit-mask-mode" not in css, "-webkit-mask-mode is not a real property"


def test_error_css_pins_the_asset_aspect_ratio():
    # Fails together with the 1600x672 assertion above if the PNG is re-derived
    # at another size -- the asset and the stylesheet must agree.
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert "aspect-ratio: 1600 / 672" in css


def test_error_css_is_token_only_no_raw_hex():
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "use tokens, not raw hex"
    assert "background-color: var(--text-primary)" in css


def test_error_css_stacking_invariant():
    """watermark 0 < .error-page__main 1 < .app-header 2.

    Inverting this reproduces a regression that has already shipped once (see the
    'Log out looks see-through and can't be tapped' comment in app.css).
    """
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert ".app-main" not in css, (
        "keep .app-main out of error.css -- a global rule would make every <main> "
        "a stacking context and trap .modal / .unit-drawer / .math-modal"
    )

    def z(selector):
        block = re.search(re.escape(selector) + r"[^{]*\{[^}]*\}", css, re.S)
        assert block, f"no rule found for {selector}"
        m = re.search(r"z-index:\s*(-?\d+)", block.group(0))
        assert m, f"no z-index in the {selector} rule"
        return int(m.group(1))

    assert z("body.error-page::after") < z(".error-page__main")
    assert z(".error-page__main") < z("body.error-page .app-header")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_error_page_styles.py -v`
Expected: the five new tests FAIL with `FileNotFoundError` on `error.css`; the two asset tests still pass.

- [ ] **Step 3: Write the stylesheet**

Create `core/static/core/css/error.css`:

```css
/* Error pages (404 / 403). Bespoke per-page sheet — linked only from
   templates/404.html and templates/403.html, never from app.css.

   ── The watermark asset ──────────────────────────────────────────────────
   core/static/core/img/learner.png was derived ONE-OFF from a local
   black-on-white source image that is deliberately NOT committed.

   To reproduce it byte-for-byte FROM A BLACK-ON-WHITE SOURCE:
     alpha  = 255 - L                              (inverted luminance; keeps
                                                    anti-aliased edges)
     t      = clamp((y - 0.60*H) / (0.40*H), 0, 1)
     alpha *= 1 - (3t^2 - 2t^3)                    (smoothstep fade)
     image  = Image.merge("LA", (L=0, alpha)); save(optimize=True)
   -> 1600x672, ~17 KB. Build via Image.merge, never by mutating the source,
   so no ICC/EXIF metadata is carried into a file nothing samples.

   The fade exists because the artwork's bottom quarter is near-solid ink (the
   desk band, onset y=525 at 61% coverage). Unfaded it paints a full-width
   rectangle with a hard horizontal top edge. A linear ramp from 0.72*H still
   left that edge at 78% strength; the smoothstep from 0.60*H cuts it to ~57%.

   RECOVERY — rebuilding from the COMMITTED png is a DIFFERENT procedure: take
   its alpha channel as the finished silhouette and apply NEITHER step. Its
   luminance is 0 everywhere, so 255-L would yield 255 for every pixel (a solid
   rectangle), and re-applying the ramp would double-fade the bottom.
   ────────────────────────────────────────────────────────────────────────── */

@supports (mask-image: none) or (-webkit-mask-image: none) {
  body.error-page::after {
    content: "";
    position: fixed; left: 0; right: 0; bottom: 0;
    /* The clamp below shrinks the box to keep its aspect-ratio, which
       over-constrains left/right/width. CSS resolves that by IGNORING `right`,
       so without auto inline margins the watermark goes flush left with the
       whole gutter on one side. */
    margin-inline: auto;
    aspect-ratio: 1600 / 672;
    max-height: 60dvh;
    background-color: var(--text-primary);
    -webkit-mask-image: url("../img/learner.png");
            mask-image: url("../img/learner.png");
    -webkit-mask-repeat: no-repeat;       mask-repeat: no-repeat;
    -webkit-mask-position: center bottom; mask-position: center bottom;
    -webkit-mask-size: contain;           mask-size: contain;
                                          mask-mode: alpha;
    opacity: .07;
    z-index: 0;
    pointer-events: none;
  }
  [data-theme="dark"] body.error-page::after { opacity: .10; }
}

/* Vertical centring derived from layout, not from a hard-coded header height:
   the auth sheet's calc(100vh - padding) works only because auth pages REPLACE
   the header block; these pages keep it (~69px, taller when it wraps). */
body.error-page { display: flex; flex-direction: column; min-height: 100dvh; }

/* Stacking: watermark 0 < main 1 < header 2. The header must sit strictly
   ABOVE main -- giving it a z-index makes it a stacking context, re-scoping its
   dropdown panels (z-index 50/40) inside it; if main shared layer 1, DOM order
   would let it paint and hit-test over them. */
body.error-page .app-header { z-index: 2; }

.error-page__main {
  position: relative; z-index: 1;
  flex: 1;
  display: flex; flex-direction: column;
  /* `safe`, not bare `center`: request.path is attacker-controlled in LENGTH,
     and centring an over-tall column pushes its top out of reach. */
  justify-content: safe center;
}

.error-page__inner { max-width: 40rem; margin-inline: auto; }

.error-page__code {
  margin: 0 0 var(--space-2);
  font-size: 3rem; font-weight: 700; line-height: 1;
  letter-spacing: var(--heading-letter-spacing);
  color: var(--accent);
}
.error-page__title {
  margin: 0 0 var(--space-4);
  font-size: 1.75rem; font-weight: 600;
  letter-spacing: var(--heading-letter-spacing);
  color: var(--text-primary);
}
.error-page__lead {
  margin: 0 0 var(--space-4);
  font-size: 1.0625rem; line-height: 1.6;
  color: var(--text-primary);
}
.error-page__path {
  margin: 0 0 var(--space-4);
  font-size: .875rem; color: var(--text-tertiary);
  overflow-wrap: anywhere;
}
.error-page__path code {
  padding: .1em .4em;
  font-family: var(--font-mono); font-size: .875rem;
  color: var(--text-secondary);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow-wrap: anywhere;
}
.error-page__note {
  margin: 0 0 var(--space-6);
  font-size: .9375rem; line-height: 1.6;
  color: var(--text-secondary);
}
.error-page__actions {
  margin: 0;
  display: flex; flex-wrap: wrap; gap: var(--space-3);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_error_page_styles.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/static/core/css/error.css tests/test_error_page_styles.py
git commit -m "feat(error-pages): add error.css with the themed watermark and page vocabulary"
```

---

### Task 3: The 404 page

**Files:**
- Modify: `templates/404.html` (full rewrite)
- Create: `tests/test_error_pages.py`

**Interfaces:**
- Consumes: `error.css` and its vocabulary (Task 2); `{% url 'landing' %}`.
- Produces: the rendered 404. Task 5's Polish test re-requests `/no-such-page/`; Task 6 screenshots it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_error_pages.py`:

```python
"""Behaviour of the illustrated 404 / 403 pages.

Django forces DEBUG=False under test, so client.get() renders the REAL
templates -- no override_settings needed.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_404_renders_the_illustrated_page(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    body = resp.content
    assert b"Nothing here" in body
    assert "We appreciate your eagerness to discover".encode() in body
    assert b"report it to your administrator" in body
    assert b"couldn" not in body.split(b"<main")[1], "old copy still present"


def test_404_echoes_the_attempted_path_in_a_code_element(client):
    resp = client.get("/no-such-page/")
    # Deliberately NOT a bare substring check: base.html's language-switch form
    # renders <input type="hidden" name="next" value="{{ request.path }}"> on
    # every page, so "/no-such-page/" is already in the body whether or not the
    # path line exists. Assert the element.
    assert b"<code>/no-such-page/</code>" in resp.content


def test_404_never_emits_a_raw_tag_from_the_attempted_path(client):
    # quote() in Django's page_not_found percent-encodes < > " ' & ( ) BEFORE the
    # template sees the value, so this cannot catch a stray |safe (the bytes are
    # identical either way). What it DOES catch is someone swapping
    # {{ request_path }} for the un-quoted {{ request.path }}.
    # Note: a bare b"<script>" assertion would be vacuous -- base.html emits
    # three literal <script> tags of its own.
    resp = client.get("/x/<script>alert(1)</script>/")
    assert resp.status_code == 404
    assert b"<script>alert" not in resp.content
    assert b"%3Cscript%3Ealert" in resp.content
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_error_pages.py -v`
Expected: all three FAIL — the old template has none of the new copy, no `<code>` element, and no path echo.

- [ ] **Step 3: Rewrite the template**

Replace the entire contents of `templates/404.html`:

```django
{% extends "base.html" %}
{% load static i18n %}
{% block head_title %}{% trans "Page not found" %} · libli{% endblock %}
{% block body_class %}error-page{% endblock %}
{% block main_class %}app-main error-page__main{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/error.css' %}">{% endblock %}
{% block content %}
<div class="error-page__inner">
  <p class="error-page__code">404</p>
  <h1 class="error-page__title">{% trans "Nothing here" %}</h1>
  <p class="error-page__lead">{% trans "We appreciate your eagerness to discover, but there's nothing at this address. Check the address you entered, or go back to the main page." %}</p>
  {% if request_path %}
  <p class="error-page__path">{% trans "You tried:" %} <code>{{ request_path }}</code></p>
  {% endif %}
  <p class="error-page__note">{% trans "If a link inside the app brought you here, please report it to your administrator, describing the steps that led to this page." %}</p>
  <p class="error-page__actions">
    <a class="btn" href="{% url 'landing' %}">{% trans "Back to main page" %}</a>
  </p>
</div>
{% endblock %}
```

Three things that are load-bearing and easy to get wrong:

1. `{% load static i18n %}` — the old file loaded only `i18n`, and `base.html`'s own load tag does **not** propagate to children. A bare `{% static %}` without it is a `TemplateSyntaxError`.
2. `<code>{{ request_path }}</code>` carries **no attributes and no surrounding whitespace** — the test asserts that exact string.
3. `{% url 'landing' %}`, **not** `{% url 'home' %}`. `home` is `@login_required`, so a `home`-targeted button bounces an anonymous visitor to the login form. `landing` is the public entry at `""` and redirects authenticated users onward, so one URL is right for both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_error_pages.py tests/test_error_page_styles.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add templates/404.html tests/test_error_pages.py
git commit -m "feat(error-pages): illustrated 404 with the attempted address echoed"
```

---

### Task 4: The 403 page

**Files:**
- Modify: `templates/403.html` (full rewrite)
- Modify: `tests/test_error_pages.py` (append)

**Interfaces:**
- Consumes: `error.css` (Task 2); `{% url 'landing' %}`, `{% url 'account_login' %}`.
- Produces: the rendered 403 and the **no-access fixture shape** reused by Task 5's Polish test and Task 6's shots — a non-staff, non-superuser user who does not own, is not enrolled in, and teaches no group attached to the course.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_error_pages.py`:

```python
def _no_access(client, username="outsider"):
    """A logged-in user with NO access to a course, plus that course.

    courses/access.py grants access on is_staff OR owner OR enrolled OR
    teaching a non-archived group on the course -- "no access" is four
    negatives. make_login builds a plain non-staff user, and make_course gives
    the course a different (factory) owner, so none of the four hold.
    """
    from tests.factories import make_course, make_login

    user = make_login(client, username)
    course = make_course()
    assert not user.is_staff and not user.is_superuser
    assert course.owner != user
    return user, course


def test_403_renders_the_illustrated_page(client):
    from django.urls import reverse

    _, course = _no_access(client)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 403
    assert b"Not for you" in resp.content
    assert b"have permission to open it" in resp.content


def test_403_hides_the_login_action_from_an_authenticated_user(client):
    from django.urls import reverse

    _, course = _no_access(client)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert b"/accounts/login/?next=" not in resp.content


def test_403_offers_a_login_action_to_an_anonymous_visitor(rf):
    """Rendered directly, not via a request.

    Every first-party `raise PermissionDenied` sits behind @login_required, so
    no first-party URL can produce an anonymous 403 -- a live request would get
    a 302 to login instead. (allauth can reach it, which is why the branch is
    kept.)
    """
    from django.contrib.auth.models import AnonymousUser
    from django.template.loader import render_to_string

    request = rf.get("/courses/secret/?tab=notes")
    request.user = AnonymousUser()
    html = render_to_string("403.html", {}, request=request)

    assert "/accounts/login/?next=" in html
    # get_full_path, not path -- the query string must survive the round trip.
    assert "tab%3Dnotes" in html or "tab=notes" in html
    # Exactly once: base.html renders its OWN "Log in" CTA for anonymous
    # visitors, so this is what pins the hide_auth_cta header suppression.
    # (RequestFactory leaves resolver_match None -> hide_auth_cta is False from
    # the context processor, so only the template's {% with %} can suppress it.)
    assert html.count("Log in") == 1, "header CTA not suppressed -- duplicate label"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_error_pages.py -v -k 403`
Expected: all three FAIL — the old template has none of the new copy and no login action.

- [ ] **Step 3: Rewrite the template**

Replace the entire contents of `templates/403.html`:

```django
{% extends "base.html" %}
{% load static i18n %}
{% block head_title %}{% trans "Access denied" %} · libli{% endblock %}
{% block body_class %}error-page{% endblock %}
{% block main_class %}app-main error-page__main{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/error.css' %}">{% endblock %}
{% comment %} Suppress base.html's own anonymous "Log in" CTA so it does not
duplicate the in-page action below. hide_auth_cta is computed per-request by
core.context_processors.ui_prefs and is False here, and Django's built-in
permission_denied view renders with a fixed context we cannot extend -- so we
shadow the value around the inherited header instead. BlockNode.super()
re-renders the parent block against the same mutable Context, so the {% with %}
layer is live. {% endcomment %}
{% block header %}{% with hide_auth_cta=1 %}{{ block.super }}{% endwith %}{% endblock %}
{% block content %}
<div class="error-page__inner">
  <p class="error-page__code">403</p>
  <h1 class="error-page__title">{% trans "Not for you" %}</h1>
  <p class="error-page__lead">{% trans "This page exists, but your account doesn't have permission to open it. If you think you should have access, ask your administrator." %}</p>
  <p class="error-page__actions">
    {% if user.is_authenticated %}
      <a class="btn" href="{% url 'landing' %}">{% trans "Back to main page" %}</a>
    {% else %}
      <a class="btn" href="{% url 'account_login' %}?next={{ request.get_full_path|urlencode }}">{% trans "Log in" %}</a>
      <a class="btn--ghost" href="{% url 'landing' %}">{% trans "Back to main page" %}</a>
    {% endif %}
  </p>
</div>
{% endblock %}
```

Notes: there is deliberately **no path line** (`permission_denied` passes only `{"exception": …}`, no `request_path`) and **no separate note paragraph** — the 403's advice is folded into the lead, so it uses four of the six classes. For an anonymous visitor `Log in` is the primary `.btn` and comes first, because logging in is the actual fix.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_error_pages.py tests/test_error_page_styles.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add templates/403.html tests/test_error_pages.py
git commit -m "feat(error-pages): illustrated 403 with a login action for anonymous visitors"
```

---

### Task 5: Translations and catalogs

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.mo`
- Modify: `docs/development/conventions.md:48`
- Create: `tests/test_i18n_error_pages.py`

**Interfaces:**
- Consumes: the seven new msgids emitted by Tasks 3 and 4.
- Produces: compiled catalogs. Nothing later depends on them except Task 6's shots (which run in EN).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_i18n_error_pages.py`:

```python
"""Polish rendering of the error pages + catalog hygiene.

Mirrors tests/test_i18n_catalog.py (render) and
tests/test_i18n_auth.py::test_po_catalog_clean (hygiene).
"""

from pathlib import Path

import pytest

from tests.factories import make_course, make_login

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent


def _speak_polish(client):
    # LocaleMiddleware re-activates the language per request from the session /
    # Accept-Language; translation.override() alone does NOT control what the
    # test client renders. The session write must come AFTER any login, because
    # logging in cycles the session and would discard it.
    session = client.session
    session["_language"] = "pl"
    session.save()


def test_404_renders_in_polish(client):
    _speak_polish(client)
    resp = client.get("/no-such-page/", HTTP_ACCEPT_LANGUAGE="pl")
    body = resp.content
    assert "Nic tu nie ma".encode() in body
    assert "Doceniamy zapał do odkrywania".encode() in body
    assert "Próbowano otworzyć:".encode() in body
    assert b"Nothing here" not in body
    assert b"We appreciate your eagerness" not in body


def test_403_renders_in_polish(client):
    from django.urls import reverse

    make_login(client, "outsider")          # login first...
    _speak_polish(client)                   # ...then set the language
    course = make_course()
    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]),
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    assert resp.status_code == 403
    body = resp.content
    assert "Nie dla ciebie".encode() in body
    assert "nie ma uprawnień".encode() in body
    assert b"Not for you" not in body


@pytest.mark.parametrize("locale", ["pl", "en"])
def test_po_catalog_clean(locale):
    # The three existing guards (test_i18n_auth / test_i18n_notes / test_tags_i18n)
    # read locale/pl ONLY, so without the "en" case here half of this change's
    # catalog churn would ship unguarded.
    text = (ROOT / "locale" / locale / "LC_MESSAGES" / "django.po").read_text(
        encoding="utf-8"
    )
    assert "#, fuzzy" not in text, f"{locale}: fuzzy entries are ignored at runtime"
    assert "#~" not in text, f"{locale}: obsolete entries present -- drop them"


@pytest.mark.parametrize("locale", ["pl", "en"])
def test_retired_msgids_are_gone(locale):
    text = (ROOT / "locale" / locale / "LC_MESSAGES" / "django.po").read_text(
        encoding="utf-8"
    )
    for retired in (
        'msgid "Back to home"',
        'msgid "We couldn\'t find that page."',
        'msgid "You don\'t have permission to view this page."',
    ):
        assert retired not in text, f"{locale}: {retired} is no longer referenced"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_i18n_error_pages.py -v`
Expected: the two render tests FAIL (no PL translations yet); `test_retired_msgids_are_gone` FAILS (the msgids are still in both catalogs).

- [ ] **Step 3: Regenerate both catalogs**

```bash
uv run python manage.py makemessages -l pl -l en
```

`-l pl -l en`, **both**. `docs/development/conventions.md` documents `-l pl` only; following that literally would never touch `locale/en/LC_MESSAGES/django.po`, leaving the retired msgids live there and making the new EN guard pass vacuously against a file nobody regenerated.

- [ ] **Step 4: Fill in the Polish, and clear the fuzzy flag**

In `locale/pl/LC_MESSAGES/django.po`, set these seven msgstrs:

| msgid | msgstr |
|---|---|
| `Nothing here` | `Nic tu nie ma` |
| `We appreciate your eagerness to discover, but there's nothing at this address. Check the address you entered, or go back to the main page.` | `Doceniamy zapał do odkrywania, ale pod tym adresem nic nie ma. Sprawdź wpisany adres lub wróć na stronę główną.` |
| `If a link inside the app brought you here, please report it to your administrator, describing the steps that led to this page.` | `Jeśli ta strona otworzyła się po kliknięciu linku w aplikacji, zgłoś to administratorowi, opisując kroki, które do niej doprowadziły.` |
| `You tried:` | `Próbowano otworzyć:` |
| `Back to main page` | `Powrót do strony głównej` |
| `Not for you` | `Nie dla ciebie` |
| `This page exists, but your account doesn't have permission to open it. If you think you should have access, ask your administrator.` | `Ta strona istnieje, ale twoje konto nie ma uprawnień, żeby ją otworzyć. Jeśli uważasz, że powinno je mieć, zwróć się do administratora.` |

Copy rules, non-negotiable: **`link`, never `odnośnik`** (the catalog uses `link` throughout and `odnośnik` appears zero times); informal `ty`; **no gendered past-tense forms** — hence the impersonal `otworzyła się` and `Próbowano otworzyć:` rather than `trafiłeś`/`trafiłaś`.

Then do the cleanup, in both `locale/pl` and `locale/en`:

- **Delete** every `#~` obsolete block (the three retired msgids). The tests assert `#~` is absent — leaving them commented out is not the same as removing them.
- **Strip every `#, fuzzy` flag.** One is near-certain: the retired `Back to home` already carries the PL msgstr `Powrót do strony głównej`, byte-identical to the new `Back to main page`, so `makemessages` will resurrect it as a fuzzy match. **A fuzzy entry is ignored at runtime**, so leaving it produces the maddening failure of a red test with a perfectly correct translation sitting in the file.
- Leave the EN msgstrs empty (Django falls back to the msgid) unless the file's existing convention differs — match whatever the surrounding entries do.

- [ ] **Step 5: Compile, and fix the doc that caused the trap**

```bash
uv run python manage.py compilemessages
```

Both `.mo` files are tracked in git and are part of this diff.

In `docs/development/conventions.md` line 48, change `makemessages -l pl` to `makemessages -l pl -l en`, and note that both catalogs are tracked. Routing around the doc for this change alone would leave the next contributor to walk into the same trap — and the new EN guard would keep passing vacuously for them.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_i18n_error_pages.py tests/test_i18n_auth.py tests/test_i18n_notes.py tests/test_tags_i18n.py -v`
Expected: all pass — including the three pre-existing catalog guards, which must not regress.

- [ ] **Step 7: Run the whole non-e2e suite**

Run: `uv run pytest -q`
Expected: no failures. If anything unrelated fails, check whether it is a pre-existing flake before touching it — a genuinely unrelated flaky test belongs in its own PR, never inside this diff.

- [ ] **Step 8: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo \
        locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo \
        docs/development/conventions.md tests/test_i18n_error_pages.py
git commit -m "i18n(error-pages): Polish copy, catalog cleanup, and both-locale makemessages"
```

---

### Task 6: Visual verification

**Files:**
- Create: `tests/test_e2e_error_pages.py`

**Interfaces:**
- Consumes: everything above.
- Produces: seven screenshots written to the scratchpad — **verification artifacts, not committed**.

- [ ] **Step 1: Write the screenshot module**

Create `tests/test_e2e_error_pages.py`:

```python
"""Playwright screenshots of the illustrated error pages.

Seven shots covering BOTH watermark regimes -- see the spec's shot matrix.
Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_html_element.py.
"""

import os
from pathlib import Path

import pytest

from tests.factories import TEST_PASSWORD, make_course, make_verified_user

pytestmark = pytest.mark.e2e

SHOTS = Path(
    os.environ.get("LIBLI_SHOT_DIR")
    or Path(__file__).resolve().parent.parent / "_shots"
)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "name,theme,width,height",
    [
        ("404-light-1280x900", "light", 1280, 900),
        ("404-dark-1280x900", "dark", 1280, 900),
        ("404-light-390x844", "light", 390, 844),
        ("404-light-1280x720-clamped", "light", 1280, 720),
    ],
)
def test_shoot_404(page, live_server, name, theme, width, height):
    SHOTS.mkdir(exist_ok=True)
    page.set_viewport_size({"width": width, "height": height})
    # Anonymous: the pre-paint script's `if (!pref)` branch DOES consult the
    # cookie, because data-theme-pref is empty for a logged-out visitor.
    page.context.add_cookies(
        [{"name": "libli_theme", "value": theme, "url": live_server.url}]
    )
    page.goto(f"{live_server.url}/no-such-page/")
    page.screenshot(path=str(SHOTS / f"{name}.png"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "name,theme,width,height",
    [
        ("403-light-1280x900", "light", 1280, 900),
        ("403-dark-1280x900", "dark", 1280, 900),
        ("403-light-390x844", "light", 390, 844),
    ],
)
def test_shoot_403(page, live_server, name, theme, width, height):
    SHOTS.mkdir(exist_ok=True)
    user = make_verified_user(
        username="outsider", email="outsider@t.example.com", password=TEST_PASSWORD
    )
    # An AUTHENTICATED user's User.theme wins outright -- _resolve_theme_pref's
    # docstring: "User.theme is never empty, so for an authed user the later
    # rungs are unreachable". The cookie would be silently ignored here and the
    # dark shot would come out light.
    user.theme = theme
    user.save(update_fields=["theme"])
    course = make_course()
    assert course.owner != user and not user.is_staff

    page.set_viewport_size({"width": width, "height": height})
    _login(page, live_server, "outsider")
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    page.screenshot(path=str(SHOTS / f"{name}.png"))
```

- [ ] **Step 2: Run the shots**

Run: `uv run pytest tests/test_e2e_error_pages.py -m e2e -v`
Expected: 7 passed, seven PNGs under `_shots/`.

**Run this in the foreground only.** Backgrounding an e2e sweep in this project has produced runaway browser processes.

If `page`/`live_server` fixtures are unavailable, check that `pytest-playwright` is installed and that browsers are present (`uv run playwright install chromium`).

- [ ] **Step 3: Look at all seven and self-critique**

Read each PNG and check, explicitly:

- the watermark reads as **atmosphere, not a picture** — and never fights the text for contrast, in either theme;
- **no hard horizontal rule** where the desk band begins (the smoothstep ramp's whole job);
- **the figure's head is in frame** — it sits at y=6 in the source, so any vertical crop is immediately visible;
- the lower third of the figure and the laptop base **are expected to be faded** — that is the ramp working, not a bug;
- the whole scene is present at 390 px;
- text and header paint **above** the watermark;
- on the clamped shot (`404-light-1280x720-clamped`), the **left and right gutters are equal** — an unequal gutter is the signature of `margin-inline: auto` having been dropped. This is the only shot where that check is reachable, which is why it exists.

Fix anything that fails, re-shoot, and re-check before proceeding.

- [ ] **Step 4: Confirm the shots are not committed**

Run: `git status --short`
Expected: `_shots/` does not appear as tracked content. If it shows as untracked, leave it untracked — these are verification artifacts. (This differs from the help-shot substrate, which commits its PNGs because they are shipped page content.)

- [ ] **Step 5: Lint and run the full suite one last time**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```
Expected: clean, and no test failures.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_error_pages.py
git commit -m "test(error-pages): Playwright shots across both watermark regimes"
```

---

## Self-Review

**Spec coverage.** Asset derivation → T1. `error.css`, watermark, stacking, layout, visual tokens → T2. 404 template + tests 1–3 → T3. 403 template + tests 4–5 → T4. Copy tables, catalog churn, `conventions.md`, tests 6–7 → T5. Test 8 (static/wiring guard) → split across T1 (asset) and T2 (CSS); the "both templates emit the stylesheet link and body class" clause is covered implicitly by T3/T4's render tests, which would fail outright without the link. Seven-shot matrix and self-critique → T6. CSRF 403 and `500.html` are explicitly out of scope in the spec and have no task, correctly.

**Placeholders.** None — every step carries the literal file content, command, or table it needs.

**Type/name consistency.** Class names in `error.css` (T2) match the markup in T3/T4 and the assertions in T1/T2. `_no_access` is defined once in T4 and reused only within that file; T5's Polish 403 test rebuilds the same shape inline rather than importing it across modules. `{% url 'landing' %}` is used consistently in both templates and nowhere is `home` used.

**One gap, deliberately left:** test 8's stylesheet-link assertion is folded into T3/T4 rather than written as a standalone check, on the grounds that a missing `{% block extra_css %}` cannot pass those render tests. If the executing agent prefers an explicit assertion, adding it to `tests/test_error_page_styles.py` is harmless.
