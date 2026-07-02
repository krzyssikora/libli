# Notifications Slice 3 — Bell Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a header-cluster notification **bell** that carries the unread badge and opens a server-rendered dropdown of the user's recent notifications; clicking a row navigates to its target and marks it read; the old text "Notifications" nav link is removed.

**Architecture:** Pure reuse of the Slice-1/2 substrate. One context-processor extension exposes `recent_for(user, 8)` to every authenticated page; a new standalone template partial renders the panel inside the existing `.menu` dropdown component; two small additions to the existing `ui.js` IIFE enhance the anchor trigger and fire a keepalive mark-read `fetch`; CSS styles the panel; EN/PL strings are added. **No new model, migration, view, or URL.**

**Tech Stack:** Django 5.2 server-rendered templates, vanilla JS (`core/js/ui.js`), token-driven CSS (`app.css`), pytest + factory_boy, Playwright for e2e, Django i18n (`.po`/`.mo`).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI checks `ruff format --check`, so run `uv run ruff format` (not just `ruff check`) per task.
- **No new model / migration / view / URL.** This is a read/surface slice reusing the existing *services* (`recent_for`, `unread_count`, `notification_url`), the existing *URL routes/views* (`notifications:mark_read`, `notifications:mark_all_read` — `@require_POST` views in `notifications/views.py`), the `.menu` component, and the theme-toggle `fetch` idiom.
- **Bilingual:** every user-facing string is wrapped for translation and given an EN + PL entry; recompile `.mo` (`uv run python manage.py compilemessages`). `makemessages` re-marks copied translations `#, fuzzy` (ignored at runtime) and can mis-guess — grep new msgids and verify.
- **No hardcoded test passwords:** use `tests.factories.TEST_PASSWORD` (GitGuardian CI flags new password literals).
- **e2e must drive the real UI:** no `page.evaluate` shortcut — click the actual bell/rows.
- **Icons are monochrome `currentColor` line SVGs** using the shared `.icon` class (stroke-based, `viewBox="0 0 24 24"`), never multicolour emoji.
- **Commit-message trailers:** end each commit body with the repo's `Co-Authored-By:` and `Claude-Session:` trailers per the environment's git instructions.

## File Structure

- `core/context_processors.py` — **modify** `notifications_badge` to also expose `notifications_recent`; add module constant `BELL_RECENT_LIMIT`.
- `notifications/templates/notifications/_bell_panel.html` — **create** the dropdown panel partial (standalone, no `{% extends %}`).
- `templates/base.html` — **modify** the header: add the bell `.menu` in `.app-header__cluster` (outside `#primary-nav`), remove the old text "Notifications" nav link, move the badge onto the bell.
- `core/static/core/js/ui.js` — **modify** the shared `.menu` trigger handler (anchor-aware `preventDefault`) and add a document-level click-marks-read handler.
- `core/static/core/css/app.css` — **modify**: add `.bell*` and `.notif-menu*` rules.
- `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ `.mo`) — **modify**: new strings.
- Tests (**create**): `notifications/tests/test_bell_context.py`, `notifications/tests/test_bell_render.py`, `notifications/tests/test_e2e_bell.py`, `notifications/tests/test_bell_i18n.py`.

---

### Task 1: Context processor — expose `notifications_recent`

**Files:**
- Modify: `core/context_processors.py` (the `notifications_badge` function, currently lines ~93-100)
- Test: `notifications/tests/test_bell_context.py` (create)

**Interfaces:**
- Consumes: `notifications.services.recent_for(user, limit)`, `unread_count(user)`, `notification_url(n)` (all existing).
- Produces: module constant `BELL_RECENT_LIMIT = 8` in `core.context_processors`; template context keys `notifications_recent` (a `list[Notification]`, each with a `.url` str-or-`None` attribute) and `notifications_unread` (int), for authenticated users only.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_bell_context.py`:

```python
import pytest
from django.urls import reverse

from core.context_processors import BELL_RECENT_LIMIT
from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_recent_exposed_and_capped(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    for _ in range(BELL_RECENT_LIMIT + 3):
        services.notify_enrolled(user, course)
    resp = client.get(reverse("courses:my_courses"))
    recent = resp.context["notifications_recent"]
    assert len(recent) == BELL_RECENT_LIMIT
    assert all(hasattr(n, "url") for n in recent)
    assert resp.context["notifications_unread"] == BELL_RECENT_LIMIT + 3


def test_recent_url_none_when_unresolvable(client):
    user = make_login(client, "owner")
    # Empty data → notification_url can't resolve a slug → None.
    Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=1,
        data={},
    )
    resp = client.get(reverse("courses:my_courses"))
    assert resp.context["notifications_recent"][0].url is None


def test_anonymous_gets_neither(client):
    resp = client.get(reverse("account_login"))
    assert not resp.context.get("notifications_recent")
    assert not resp.context.get("notifications_unread")


def test_one_added_query_no_n_plus_one(rf, django_assert_num_queries):
    user = make_verified_user(username="q", email="q@test.example.com")
    course = CourseFactory()
    for _ in range(5):
        services.notify_enrolled(user, course)
    from core.context_processors import notifications_badge

    request = rf.get("/")
    request.user = user
    # Exactly two queries: unread_count() + recent_for(); notification_url is
    # pure Python (reverse()) and adds none regardless of row count.
    with django_assert_num_queries(2):
        ctx = notifications_badge(request)
    assert len(ctx["notifications_recent"]) == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_bell_context.py -v`
Expected: FAIL — `ImportError: cannot import name 'BELL_RECENT_LIMIT'` (and `notifications_recent` missing from context).

- [ ] **Step 3: Implement the context-processor change**

In `core/context_processors.py`, replace the existing `notifications_badge` function with the version below and add the module-level constant immediately above it:

```python
# Single source of truth for how many rows the bell dropdown shows.
BELL_RECENT_LIMIT = 8


def notifications_badge(request):
    """Unread count + recent list for the nav bell. Absent for anonymous."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from notifications.services import notification_url
    from notifications.services import recent_for
    from notifications.services import unread_count

    recent = list(recent_for(user, BELL_RECENT_LIMIT))
    for n in recent:
        # Safe monkey-patch: Notification has no `url` field/property.
        n.url = notification_url(n)
    return {
        "notifications_unread": unread_count(user),
        "notifications_recent": recent,
    }
```

**Accepted global cost:** this adds the `recent_for` query to *every* authenticated page across the app (not just `/notifications/`), because the bell + panel render in the shared header everywhere. That is intended and cheap — one indexed query (`recipient, -created_at`) alongside the existing `unread_count` count; `notification_url` is pure Python and adds none. The `assertNumQueries(2)` guard in Step 1 pins this so it can't silently grow into an N+1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest notifications/tests/test_bell_context.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format core/context_processors.py notifications/tests/test_bell_context.py
uv run ruff check core/context_processors.py notifications/tests/test_bell_context.py
git add core/context_processors.py notifications/tests/test_bell_context.py
git commit -m "feat(notifications): expose recent notifications to the nav bell context"
```

---

### Task 2: Bell markup — trigger in base.html, remove old nav link, panel partial

**Files:**
- Create: `notifications/templates/notifications/_bell_panel.html`
- Modify: `templates/base.html` (remove old nav link at ~lines 77-80; add bell `.menu` between `</nav>` at ~line 129 and the account `<div class="menu" data-account-menu>` at ~line 130)
- Test: `notifications/tests/test_bell_render.py` (create)

**Interfaces:**
- Consumes: `notifications_recent`, `notifications_unread` (Task 1); URL names `notifications:list`, `notifications:mark_read`, `notifications:mark_all_read`.
- Produces: DOM contract for Task 3/4 — trigger `a.bell__trigger[data-menu-trigger]`, panel `div.notif-menu[data-menu-panel]`, badge `span.nav-badge` on the trigger. Each row is `a.notif-menu__row` **when `n.url` is truthy** (carrying `data-mark-read-url` only when *also* unread) and `div.notif-menu__row` otherwise (no href/attr); the click-marks-read selector `.notif-menu__row[data-mark-read-url]` therefore only ever matches the anchor variant.

- [ ] **Step 1: Write the failing render tests**

Create `notifications/tests/test_bell_render.py`:

```python
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

AUTHED_PAGE = "courses:my_courses"


def _get_html(client):
    return client.get(reverse(AUTHED_PAGE)).content.decode()


def test_bell_trigger_is_a_link_without_role_button(client):
    make_login(client, "owner")
    html = _get_html(client)
    m = re.search(r"<a[^>]*bell__trigger[^>]*>", html)
    assert m, "bell trigger anchor not found"
    tag = m.group(0)
    assert reverse("notifications:list") in tag  # no-JS fallback href
    assert 'data-menu-trigger' in tag
    assert 'aria-haspopup="true"' in tag
    assert "role=" not in tag  # stays a link, not role=button


def test_old_notifications_nav_link_removed(client):
    make_login(client, "owner")
    html = _get_html(client)
    # The old link used the app-nav__link class pointing at the list; it's gone.
    assert 'app-nav__link" href="%s"' % reverse("notifications:list") not in html


def test_badge_shows_exact_count_when_small(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    services.notify_enrolled(user, course)
    assert '<span class="nav-badge">2</span>' in _get_html(client)


def test_badge_caps_at_99_plus(client):
    user = make_login(client, "owner")
    Notification.objects.bulk_create(
        Notification(
            recipient=user,
            kind=Notification.Kind.ENROLLED,
            target_type="course",
            target_id=1,
            data={},
        )
        for _ in range(100)
    )
    assert "99+" in _get_html(client)


def test_panel_renders_kind_message_and_unread_row(client):
    user = make_login(client, "owner")
    course = CourseFactory(title="Astronomy")
    services.notify_enrolled(user, course)
    html = _get_html(client)
    assert "You were enrolled in Astronomy" in html
    assert "notif-menu__row--unread" in html


def test_unread_resolvable_row_carries_mark_read_attr(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    n = Notification.objects.filter(recipient=user).first()
    html = _get_html(client)
    assert 'data-mark-read-url="%s"' % reverse("notifications:mark_read", args=[n.pk]) in html


def test_read_row_omits_mark_read_attr_but_stays_row(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    Notification.objects.filter(recipient=user).update(read_at=timezone.now())
    html = _get_html(client)
    assert "notif-menu__row" in html
    assert "data-mark-read-url" not in html


def test_urlless_row_is_non_link_row(client):
    user = make_login(client, "owner")
    Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=1,
        data={},
    )
    html = _get_html(client)
    assert "notif-menu__row" in html
    assert "data-mark-read-url" not in html


def test_mark_all_read_only_when_unread(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    assert reverse("notifications:mark_all_read") in _get_html(client)
    Notification.objects.filter(recipient=user).update(read_at=timezone.now())
    assert reverse("notifications:mark_all_read") not in _get_html(client)


def test_see_all_footer_present_with_rows(client):
    user = make_login(client, "owner")
    services.notify_enrolled(user, CourseFactory())
    assert "See all" in _get_html(client)


def test_empty_state_when_no_notifications(client):
    make_login(client, "owner")
    assert "You have no notifications yet." in _get_html(client)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_bell_render.py -v`
Expected: FAIL — bell markup and partial don't exist yet (TemplateDoesNotExist for the include, or missing-substring assertions).

- [ ] **Step 3: Create the panel partial**

Create `notifications/templates/notifications/_bell_panel.html`:

```html
{% load i18n %}
{% if notifications_recent %}
<div class="notif-menu__head">
  <p class="notif-menu__title">{% trans "Notifications" %}</p>
  {% if notifications_unread %}
  <form method="post" action="{% url 'notifications:mark_all_read' %}">
    {% csrf_token %}
    <button type="submit" class="btn btn--small">{% trans "Mark all read" %}</button>
  </form>
  {% endif %}
</div>
<ul class="notif-menu__list">
  {% for n in notifications_recent %}
  <li>
    {% if n.url %}
    <a class="notif-menu__row{% if not n.read_at %} notif-menu__row--unread{% endif %}"
       href="{{ n.url }}"{% if not n.read_at %} data-mark-read-url="{% url 'notifications:mark_read' n.pk %}"{% endif %}>
    {% else %}
    <div class="notif-menu__row{% if not n.read_at %} notif-menu__row--unread{% endif %}">
    {% endif %}
      <span class="notif-menu__body">
        {% if n.kind == 'quiz_needs_review' %}
          {% blocktrans with student=n.data.student_name unit=n.data.unit_title %}{{ student }} submitted a quiz for review: {{ unit }}{% endblocktrans %}
        {% elif n.kind == 'quiz_graded' %}
          {% blocktrans with unit=n.data.unit_title %}Your quiz was graded: {{ unit }}{% endblocktrans %}
        {% elif n.kind == 'enrolled' %}
          {% blocktrans with course=n.data.course_title %}You were enrolled in {{ course }}{% endblocktrans %}
        {% endif %}
      </span>
      <span class="notif-menu__time">{% blocktrans with time=n.created_at|timesince %}{{ time }} ago{% endblocktrans %}</span>
    {% if n.url %}</a>{% else %}</div>{% endif %}
  </li>
  {% endfor %}
</ul>
<a class="notif-menu__seeall" href="{% url 'notifications:list' %}">{% trans "See all" %} →</a>
{% else %}
<p class="notif-menu__empty">{% trans "You have no notifications yet." %}</p>
{% endif %}
```

- [ ] **Step 4: Remove the old nav link in `templates/base.html`**

Delete these lines from the `#primary-nav` block (currently ~lines 77-80):

```html
          <a class="app-nav__link" href="{% url 'notifications:list' %}">
            {% trans "Notifications" %}
            {% if notifications_unread %}<span class="nav-badge">{{ notifications_unread }}</span>{% endif %}
          </a>
```

- [ ] **Step 5: Add the bell `.menu` in `templates/base.html`**

Insert the following as a direct child of `.app-header__cluster`, immediately **after** the closing `</nav>` of `#primary-nav` and **before** `<div class="menu" data-account-menu>`:

```html
        <div class="menu bell">
          <a class="btn--icon bell__trigger" href="{% url 'notifications:list' %}"
            data-menu-trigger aria-haspopup="true" aria-expanded="false"
            aria-label="{% trans 'Notifications' %}">
            <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            {% if notifications_unread %}<span class="nav-badge">{% if notifications_unread > 99 %}99+{% else %}{{ notifications_unread }}{% endif %}</span>{% endif %}
          </a>
          <div class="menu__panel notif-menu" data-menu-panel hidden aria-label="{% trans 'Notifications' %}">
            {% include "notifications/_bell_panel.html" %}
          </div>
        </div>
```

- [ ] **Step 6: Run the render tests to verify they pass**

Run: `uv run pytest notifications/tests/test_bell_render.py -v`
Expected: PASS (11 passed).

- [ ] **Step 7: Confirm no other reference to the removed link + suite green**

Run: `git grep -n "app-nav__link" -- templates/base.html` → Expected: the remaining `app-nav__link` entries (Courses, My tags, Manage, …) but **none** pointing at `notifications:list` — the bell trigger uses `bell__trigger`, not `app-nav__link`.
Run: `uv run pytest notifications -q` → Expected: PASS. (No existing notifications test asserted the old nav link; if any test elsewhere fails on the missing link, update it to assert `.bell__trigger` instead of re-adding the link.)

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff format notifications/tests/test_bell_render.py
uv run ruff check notifications/tests/test_bell_render.py
git add templates/base.html notifications/templates/notifications/_bell_panel.html notifications/tests/test_bell_render.py
git commit -m "feat(notifications): render the nav bell dropdown; drop the text nav link"
```

---

### Task 3: `ui.js` interactions + Playwright e2e

**Files:**
- Modify: `core/static/core/js/ui.js` (the `.menu` trigger handler at ~lines 52-66; add a new document-level click handler inside the same IIFE)
- Test: `notifications/tests/test_e2e_bell.py` (create)

**Interfaces:**
- Consumes: the Task-2 DOM — `a.bell__trigger[data-menu-trigger]` and `.notif-menu__row[data-mark-read-url]` (only unread-and-resolvable rows carry that attribute; url-less rows are non-matching `div`s) — plus the existing `getCookie` helper in `ui.js` and `notifications:mark_read`.
- Produces: no new JS exports — behaviour only (anchor trigger toggles the panel on a plain primary click; modified clicks fall through to the href; row click fires a keepalive mark-read POST and lets navigation proceed).

- [ ] **Step 1: Write the failing e2e test**

Create `notifications/tests/test_e2e_bell.py`:

```python
"""Playwright e2e for the notification bell dropdown (slice 3).

Real browser gestures only (project lesson: e2e that bypasses the real gesture
ships broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os
import re

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e

# mark_read's path is /notifications/<pk>/read/ (the URL *name* "mark_read" is
# not in the path). \d+ before /read excludes mark_all_read's /notifications/read-all/.
_MARK_READ_PATH = re.compile(r"/notifications/\d+/read/?$")


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


@pytest.mark.django_db(transaction=True)
def test_bell_opens_and_row_click_marks_read_and_navigates(page, live_server):
    from grouping import services as grouping_svc
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import GroupFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-bell", title="Astronomy")
    student = make_verified_user(
        username="e2e_bell_student", email="e2e_bell_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    group = GroupFactory(course=course)
    grouping_svc.add_students_to_group(group, [student])
    outline_path = reverse("courses:course_outline", kwargs={"slug": course.slug})

    _login(page, live_server, "e2e_bell_student")
    page.goto(f"{live_server.url}/notifications/")

    # Badge shows the unread count on the bell.
    expect(page.locator(".nav-badge")).to_have_text("1")

    trigger = page.locator(".bell__trigger")
    panel = page.locator(".notif-menu[data-menu-panel]")
    expect(panel).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")

    # A plain click opens the panel (does NOT navigate to the list).
    trigger.click()
    expect(panel).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")

    # Clicking the row fires the mark-read POST AND navigates to the target.
    # Synchronize on the POST's response so the badge check can't race it: a bare
    # `to_have_count(0)` after page.goto only re-queries the already-rendered DOM
    # (it never re-navigates), so if mark_read hadn't committed before that GET
    # rendered, the badge would be baked in as "1" and the auto-retry could never
    # recover. Waiting for the mark_read response guarantees it committed first.
    with page.expect_response(
        lambda r: r.request.method == "POST" and _MARK_READ_PATH.search(r.url)
    ):
        panel.locator(".notif-menu__row", has_text="Astronomy").click()
    expect(page).to_have_url(f"{live_server.url}{outline_path}")

    # mark_read has now committed server-side → reload the list; the badge is gone.
    page.goto(f"{live_server.url}/notifications/")
    expect(page.locator(".nav-badge")).to_have_count(0)
```

- [ ] **Step 2: Run the e2e test to verify it fails**

Run: `uv run pytest notifications/tests/test_e2e_bell.py -m e2e -v`
Expected: FAIL — with the unpatched handler the bell `<a>` both toggles and navigates, so the browser leaves for `/notifications/` and `expect(panel).to_be_visible()` fails (and no row click occurs).

- [ ] **Step 3: Make the shared trigger handler anchor-aware**

In `core/static/core/js/ui.js`, replace the existing trigger click listener (currently):

```javascript
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = panel.hidden;
      menus.forEach(function (other) { if (other !== menu) closeMenu(other); });
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
```

with:

```javascript
    trigger.addEventListener("click", function (e) {
      // Anchor triggers (the notifications bell) navigate via href with no JS.
      // With JS, a plain primary click toggles the panel instead — but let
      // modified clicks (ctrl/cmd/shift or non-primary button) through so
      // "open in new tab" on the underlying href still works.
      if (trigger.tagName === "A") {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
      }
      e.stopPropagation();
      var open = panel.hidden;
      menus.forEach(function (other) { if (other !== menu) closeMenu(other); });
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
```

- [ ] **Step 4: Add the click-marks-read handler**

In `core/static/core/js/ui.js`, inside the same IIFE (e.g. immediately before the "Primary nav" block near the end), add:

```javascript
  // Notification bell rows: mark-read on click without blocking navigation.
  // Fire-and-forget POST (keepalive survives the unload); the <a href> still
  // navigates. redirect:"manual" stops at mark_read's 302 so the fetch doesn't
  // follow it into a wasted list render. Same CSRF idiom as the theme toggle.
  document.addEventListener("click", function (e) {
    var row = e.target.closest(".notif-menu__row[data-mark-read-url]");
    if (!row) return;
    fetch(row.getAttribute("data-mark-read-url"), {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
      keepalive: true,
      redirect: "manual",
    }).catch(function () {});
  });
```

- [ ] **Step 5: Run the e2e test to verify it passes**

Run: `uv run pytest notifications/tests/test_e2e_bell.py -m e2e -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Confirm the existing notifications e2e still passes**

Run: `uv run pytest notifications/tests/test_e2e_notifications.py -m e2e -v`
Expected: PASS — the badge is still `.nav-badge` (now on the bell) and the list page is unchanged.

- [ ] **Step 7: Commit**

```bash
git add core/static/core/js/ui.js notifications/tests/test_e2e_bell.py
git commit -m "feat(notifications): enhance bell trigger + click-marks-read fetch"
```

---

### Task 4: Styling (`app.css`) + light/dark screenshot verification

**Files:**
- Modify: `core/static/core/css/app.css` (append a bell/notif-menu block near the existing notifications styles at ~line 664)

**Interfaces:**
- Consumes: existing tokens (`--surface-raised`, `--surface-sunken`, `--border-subtle`, `--primary`, `--text-primary`, `--text-secondary`, `--space-*`) and the `.menu__panel` base (already `position:absolute; right:0; z-index:50` — the notif-menu inherits this).
- Produces: `.bell`, `.bell__trigger`, `.notif-menu`, `.notif-menu__head/__title/__list/__row/__row--unread/__body/__time/__seeall/__empty` styles. No JS/DOM contract changes.

This is a **visual** task (no unit test) — verified with a throwaway Playwright screenshot harness per the `verify-ui-with-screenshots` convention.

- [ ] **Step 1: Add the CSS**

Append to `core/static/core/css/app.css`:

```css
/* Notification bell dropdown (Phase: notifications slice 3) */
.bell { position: relative; }
.bell__trigger { position: relative; display: inline-flex; }
/* Overlap the badge on the top-right of the bell icon (the base .nav-badge is
   tuned for an inline text link, so reset its inline margin here). */
.bell .nav-badge { position: absolute; top: -.25rem; right: -.25rem; margin: 0; }
.notif-menu { width: 20rem; max-width: calc(100vw - var(--space-4));
  max-height: min(28rem, calc(100vh - 5rem)); overflow-y: auto; padding: 0; }
.notif-menu__head { display: flex; align-items: center; justify-content: space-between;
  gap: .5rem; padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-subtle); }
.notif-menu__title { font-weight: 600; margin: 0; }
.notif-menu__list { list-style: none; margin: 0; padding: 0; }
.notif-menu__row { display: flex; align-items: baseline; justify-content: space-between;
  gap: .5rem; padding: var(--space-2) var(--space-3); text-decoration: none;
  color: var(--text-primary); border-bottom: 1px solid var(--border-subtle); }
a.notif-menu__row:hover { background: var(--surface-sunken); }
.notif-menu__row--unread { background: var(--surface-raised); }
.notif-menu__row--unread .notif-menu__body { font-weight: 600; }
.notif-menu__body { flex: 1; }
.notif-menu__time { color: var(--text-secondary); font-size: .75rem; white-space: nowrap; }
.notif-menu__seeall { display: block; padding: var(--space-2) var(--space-3);
  color: var(--primary); text-decoration: none; font-weight: 600; }
.notif-menu__seeall:hover { text-decoration: underline; }
.notif-menu__empty { color: var(--text-secondary); padding: var(--space-3); margin: 0; }
```

- [ ] **Step 2: Write a throwaway screenshot test**

Create `notifications/tests/test_shot_bell.py` (temporary — deleted in Step 4). It reuses the same fixtures/helpers as the e2e task and saves screenshots to the session scratchpad:

```python
import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e

SHOTS = os.path.expanduser("~/bell_shots")  # throwaway; removed in Step 4


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


@pytest.mark.django_db(transaction=True)
def test_shoot_bell(page, live_server):
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notifications import services
    from tests.factories import CourseFactory
    from tests.factories import make_verified_user

    os.makedirs(SHOTS, exist_ok=True)
    seed_roles()
    student = make_verified_user(username="shot", email="shot@test.example.com")
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    for i in range(6):
        services.notify_enrolled(student, CourseFactory(title=f"Course {i}"))

    _login(page, live_server, "shot")
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        for width, tag in ((1200, "desktop"), (390, "mobile")):
            page.set_viewport_size({"width": width, "height": 800})
            page.goto(f"{live_server.url}/notifications/")
            page.locator(".bell__trigger").click()
            page.locator(".notif-menu[data-menu-panel]").wait_for(state="visible")
            page.screenshot(path=f"{SHOTS}/bell_{theme}_{tag}.png")
```

- [ ] **Step 3: Run it and self-review the screenshots**

Run: `uv run pytest notifications/tests/test_shot_bell.py -m e2e -v`
Then open the four PNGs in `~/bell_shots`. Confirm: the badge sits on the bell's top-right corner; the panel is readable in both themes; row hover + unread tint look right; on the 390px mobile shot the panel clamps within the viewport (no horizontal overflow) and, because the 6-row list can exceed the height, the panel scrolls internally so the last row and the "See all" link stay reachable (the §5 vertical-overflow + mobile-clamp checks). **Also confirm the header cluster itself stays on one line at 390px** — the bell is a new 5th always-visible control alongside the lang-switch, theme toggle, hamburger, and avatar, so verify it doesn't wrap or overflow the header row. Fix `app.css` and re-run until correct.

- [ ] **Step 4: Delete the throwaway test + screenshots, then commit**

```bash
rm -f notifications/tests/test_shot_bell.py
rm -rf ~/bell_shots
git add core/static/core/css/app.css
git commit -m "style(notifications): style the bell dropdown panel (light + dark)"
```

---

### Task 5: i18n — EN/PL strings + compile

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `notifications/tests/test_bell_i18n.py` (create)

**Interfaces:**
- Consumes: the new msgids introduced by Task 2's partial — `"See all"`, `"%(time)s ago"`, `"You have no notifications yet."`. (`"Notifications"` and `"Mark all read"` already exist and are translated.)
- **Deliberate divergence:** the bell's `"You have no notifications yet."` is intentionally distinct from `list.html`'s `"You have no notifications."` (spec §2 chose the warmer "yet." for the dropdown). This is a **separate** msgid on purpose — do not "unify" the two; if either is reworded later, update both consciously.
- Produces: PL translations for the three new strings; recompiled `.mo`.

- [ ] **Step 1: Write the failing PL test**

Create `notifications/tests/test_bell_i18n.py`. This mirrors the existing
`notifications/tests/test_i18n.py` `translation.override("pl")` pattern — which
already passes in the suite, proving the compiled `.mo` catalogs load under test
settings (via `LOCALE_PATHS`). So a failure here reflects a *missing translation*,
not i18n plumbing:

```python
from django.utils.translation import gettext
from django.utils.translation import override


def test_new_bell_strings_have_polish():
    with override("pl"):
        assert gettext("See all") == "Zobacz wszystkie"
        assert gettext("You have no notifications yet.") == "Nie masz jeszcze żadnych powiadomień."
        assert gettext("%(time)s ago") % {"time": "5 minut"} == "5 minut temu"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest notifications/tests/test_bell_i18n.py -v`
Expected: FAIL — the msgstr are empty, so `gettext` echoes the English msgid.

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l en -l pl`
This adds the three new msgids to both `.po` files. Note `makemessages` may mark copied entries `#, fuzzy` — those are ignored at runtime, so clear the flag on any entry you fill.

- [ ] **Step 4: Fill in the translations**

In `locale/pl/LC_MESSAGES/django.po`, set (removing any `#, fuzzy` line above each):

```
msgid "See all"
msgstr "Zobacz wszystkie"

msgid "You have no notifications yet."
msgstr "Nie masz jeszcze żadnych powiadomień."

msgid "%(time)s ago"
msgstr "%(time)s temu"
```

In `locale/en/LC_MESSAGES/django.po`, leave the English `msgstr` empty (msgid is the source text) unless the project convention fills EN explicitly; match the surrounding entries.

- [ ] **Step 5: Verify no unresolved new msgids + compile**

Run: `git grep -n "See all\|You have no notifications yet\|%(time)s ago" -- locale/pl/LC_MESSAGES/django.po` → confirm each has a non-empty, non-fuzzy `msgstr`.
Run: `uv run python manage.py compilemessages`
Expected: compiles `locale/pl/LC_MESSAGES/django.mo` (and `en`) with no errors.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest notifications/tests/test_bell_i18n.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.mo notifications/tests/test_bell_i18n.py
git commit -m "i18n(notifications): EN/PL strings for the bell dropdown"
```

---

### Final verification (after all tasks)

- [ ] Run the full unit suite: `uv run pytest -q` → all green.
- [ ] Run the e2e suite: `uv run pytest -m e2e -q` → all green (real gestures).
- [ ] `uv run ruff format --check .` and `uv run ruff check .` → clean.
- [ ] Manually confirm (or via the delete-after-review screenshot harness) the bell renders correctly light + dark, desktop + mobile, and that the old "Notifications" nav link is gone everywhere.

---

## Notes for the implementer

- **`recipient == actor` self-suppression, email delivery, and the full `/notifications/` list page are untouched.** Do not modify `notifications/views.py`, `services.py` (beyond nothing), `emails.py`, or `list.html`.
- **The blocktrans row messages in the partial must match `list.html` verbatim** so they share already-translated msgids — do not reword them.
- **Do not add a migration or model field.** The `n.url` attribute is a request-time monkey-patch, not a DB field.
- If a pre-existing test elsewhere asserted the old text "Notifications" nav link (none found at plan time — `git grep` to confirm), update it to target `.bell__trigger` rather than re-adding the link.
