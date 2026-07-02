# Notifications Slice 2 — Email Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a `Notification` row is created via `notify()`, also send the recipient an HTML+plaintext email — localized to their language, gated by a new per-kind opt-out — reusing the invite-email `transaction.on_commit` cadence (no Celery).

**Architecture:** A new `NotificationEmailPreference` model stores per-kind booleans (field names == `Notification.Kind` values). A new `notifications/emails.py` holds `email_enabled`, `email_content`, `_absolute_url`, and `deliver_notification_email`. `notify()` registers `transaction.on_commit(deliver_notification_email)` via a **function-local** import (one-way import graph: `emails → services`/`core.services`; `services.notify → emails` deferred). A second form on `/settings/` edits the preference.

**Tech Stack:** Django 5.2, `EmailMultiAlternatives`, `django.contrib.sites`, allauth `DEFAULT_HTTP_PROTOCOL`, Django i18n (EN/PL), pytest + factory_boy, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-07-02-notifications-slice-2-email-delivery-design.md`

## Global Constraints

- **Tooling:** `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff ...`, `uv run pytest ...`, `uv run python manage.py ...`.
- **Lint per task:** run `uv run ruff format` AND `uv run ruff check` before every commit — CI runs `ruff format --check`.
- **Test DB marker:** test modules that hit the DB set `pytestmark = pytest.mark.django_db` (already the pattern in `notifications/tests/`).
- **No hardcoded passwords:** always use `tests.factories.TEST_PASSWORD` (GitGuardian CI flags new password literals).
- **e2e drives the real UI:** Playwright gestures only — never `page.evaluate` shortcuts. e2e tests are `pytest.mark.e2e` (excluded by default; run with `-m e2e`).
- **Eager gettext in Python:** `notifications/emails.py` imports `from django.utils.translation import gettext as _` (NOT `gettext_lazy` — a lazy proxy defers interpolation past the `override` block).
- **Django templates:** email templates begin with `{% load i18n %}`. Multi-line comments use `{% comment %}` (single-line `{# #}` only).
- **i18n:** after adding msgids, run `uv run python manage.py makemessages -l pl`, fill PL `msgstr`s, **clear any `#, fuzzy` flags** (fuzzy = ignored at runtime; makemessages also mis-guesses copied translations), then `uv run python manage.py compilemessages`.
- **Every view ships styled** — the settings section reuses existing `.settings-*` classes.

---

### Task 1: `NotificationEmailPreference` model + migration

**Files:**
- Modify: `notifications/models.py` (append the model)
- Create: `notifications/migrations/0002_notificationemailpreference.py` (via makemigrations)
- Test: `notifications/tests/test_email_preference.py`

**Interfaces:**
- Produces: `NotificationEmailPreference(user OneToOne→AUTH_USER_MODEL, related_name="notification_email_pref", quiz_needs_review/quiz_graded/enrolled: BooleanField default=True)`. Field names deliberately equal `Notification.Kind` values.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_preference.py`:

```python
import pytest

from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_field_names_match_kind_values():
    field_names = {f.name for f in NotificationEmailPreference._meta.get_fields()}
    for kind in Notification.Kind.values:
        assert kind in field_names, f"missing boolean field for kind {kind!r}"


def test_defaults_all_on():
    pref = NotificationEmailPreference.objects.create(user=UserFactory())
    assert pref.quiz_needs_review is True
    assert pref.quiz_graded is True
    assert pref.enrolled is True


def test_one_row_per_user():
    user = UserFactory()
    NotificationEmailPreference.objects.create(user=user)
    with pytest.raises(Exception):  # OneToOne uniqueness
        NotificationEmailPreference.objects.create(user=user)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest notifications/tests/test_email_preference.py -v`
Expected: FAIL with `ImportError` / `cannot import name 'NotificationEmailPreference'`.

- [ ] **Step 3: Append the model to `notifications/models.py`**

At the end of `notifications/models.py` (after the `Notification` class):

```python
class NotificationEmailPreference(models.Model):
    """Per-user, per-kind opt-out for notification EMAILS (never gates the in-app
    row). Absence of a row = all-on (see notifications.emails.email_enabled). The
    boolean field names deliberately equal the Notification.Kind values so a kind
    resolves via getattr(pref, kind) with no mapping table."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_email_pref",
    )
    quiz_needs_review = models.BooleanField(default=True)
    quiz_graded = models.BooleanField(default=True)
    enrolled = models.BooleanField(default=True)

    def __str__(self):
        return f"email prefs for {self.user_id}"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations notifications`
Expected: creates `notifications/migrations/0002_notificationemailpreference.py`. Confirm it only adds the new table (no unexpected alters).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest notifications/tests/test_email_preference.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + verify no migration drift**

Run: `uv run ruff format notifications/ && uv run ruff check notifications/ && uv run python manage.py makemigrations --check --dry-run`
Expected: clean; "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add notifications/models.py notifications/migrations/0002_notificationemailpreference.py notifications/tests/test_email_preference.py
git commit -m "feat(notifications): NotificationEmailPreference model (per-kind email opt-out)"
```

---

### Task 2: `emails.py` foundations — `email_enabled` + `_absolute_url`

**Files:**
- Create: `notifications/emails.py`
- Test: `notifications/tests/test_email_preference.py` (append)

**Interfaces:**
- Consumes: `NotificationEmailPreference` (Task 1).
- Produces:
  - `email_enabled(user, kind) -> bool` — `True` when no row exists, else `getattr(pref, kind)`.
  - `_absolute_url(path: str) -> str` — `f"{scheme}://{domain}{path}"` from the current `Site` + allauth `DEFAULT_HTTP_PROTOCOL`.
  - module-level `logger = logging.getLogger(__name__)`.

- [ ] **Step 1: Write the failing test (append to `notifications/tests/test_email_preference.py`)**

```python
def test_email_enabled_default_true_when_no_row():
    from notifications.emails import email_enabled

    assert email_enabled(UserFactory(), Notification.Kind.QUIZ_GRADED) is True


def test_email_enabled_reflects_row():
    from notifications.emails import email_enabled

    user = UserFactory()
    NotificationEmailPreference.objects.create(user=user, quiz_graded=False)
    assert email_enabled(user, Notification.Kind.QUIZ_GRADED) is False
    assert email_enabled(user, Notification.Kind.ENROLLED) is True


def test_absolute_url_builds_scheme_and_domain():
    from notifications.emails import _absolute_url

    url = _absolute_url("/notifications/")
    assert "://" in url
    assert url.endswith("/notifications/")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_preference.py -k "email_enabled or absolute_url" -v`
Expected: FAIL — `No module named 'notifications.emails'`.

- [ ] **Step 3: Create `notifications/emails.py`**

```python
"""Email delivery for notifications (slice 2).

Imports are one-way: this module top-level-imports notifications.services and
core.services; notifications.services imports THIS module function-locally inside
notify() to avoid a load-time cycle. Uses eager gettext (not gettext_lazy) so
interpolation resolves inside the translation.override() block.
"""

import logging

from allauth.account import app_settings as account_settings
from django.contrib.sites.models import Site

from notifications.models import NotificationEmailPreference

logger = logging.getLogger(__name__)


def email_enabled(user, kind):
    """True when the user has no preference row (default-on), else the per-kind
    boolean. `kind` is always a valid Notification.Kind value (from a Notification
    row), so getattr is safe."""
    pref = NotificationEmailPreference.objects.filter(user=user).first()
    if pref is None:
        return True
    return getattr(pref, kind)


def _absolute_url(path):
    """Absolute URL from the current Site domain (never a request Host header, so the
    emailed link cannot be host-spoofed) + allauth's default scheme."""
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest notifications/tests/test_email_preference.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Lint**

Run: `uv run ruff format notifications/ && uv run ruff check notifications/`

- [ ] **Step 6: Commit**

```bash
git add notifications/emails.py notifications/tests/test_email_preference.py
git commit -m "feat(notifications): email_enabled + _absolute_url helpers"
```

---

### Task 3: `email_content` — per-kind localized copy

**Files:**
- Modify: `notifications/emails.py`
- Test: `notifications/tests/test_email_content.py`

**Interfaces:**
- Consumes: `Notification` (kind + `data` dict).
- Produces: `email_content(notification) -> (subject, headline, body_line)`. `headline == subject`. Reads only `notification.data`. Raises `ValueError` on an unknown kind. The `enrolled` subject/body collapse whitespace in `course_title` (Subject-header safety).

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_content.py`:

```python
import pytest

from notifications.emails import email_content
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _notif(kind, data):
    # Unsaved instance is enough — email_content reads only kind + data.
    return Notification(kind=kind, data=data)


def test_quiz_needs_review_copy():
    subject, headline, body = email_content(
        _notif(
            Notification.Kind.QUIZ_NEEDS_REVIEW,
            {"student_name": "Ann", "unit_title": "Q1", "course_title": "Algebra"},
        )
    )
    assert subject == "A quiz needs your review"
    assert headline == subject
    assert "Ann" in body and "Q1" in body and "Algebra" in body


def test_quiz_graded_copy():
    subject, _h, body = email_content(
        _notif(
            Notification.Kind.QUIZ_GRADED,
            {"unit_title": "Q1", "course_title": "Algebra"},
        )
    )
    assert subject == "Your quiz was graded"
    assert "Q1" in body and "Algebra" in body


def test_enrolled_copy():
    subject, _h, body = email_content(
        _notif(Notification.Kind.ENROLLED, {"course_title": "Algebra"})
    )
    assert subject == "You've been enrolled in Algebra"
    assert "Algebra" in body


def test_enrolled_subject_collapses_newlines():
    subject, _h, _b = email_content(
        _notif(Notification.Kind.ENROLLED, {"course_title": "Line1\nLine2"})
    )
    assert "\n" not in subject
    assert "Line1 Line2" in subject


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        email_content(_notif("bogus_kind", {}))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_content.py -v`
Expected: FAIL — `cannot import name 'email_content'`.

- [ ] **Step 3: Add `email_content` to `notifications/emails.py`**

Add the eager-gettext import at the top of `notifications/emails.py` (with the other imports):

```python
from django.utils.translation import gettext as _

from notifications.models import Notification
```

Then append the function:

```python
def email_content(notification):
    """Return (subject, headline, body_line) for the notification's kind, localized
    under the caller's active language. Reads only notification.data (no DB loads).
    Call inside a translation.override() block."""
    d = notification.data or {}
    if notification.kind == Notification.Kind.QUIZ_NEEDS_REVIEW:
        subject = _("A quiz needs your review")
        body_line = _(
            "%(student)s submitted %(unit)s in %(course)s and it needs review."
        ) % {
            "student": d.get("student_name", ""),
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.QUIZ_GRADED:
        subject = _("Your quiz was graded")
        body_line = _(
            "Your submission for %(unit)s in %(course)s has been reviewed."
        ) % {
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.ENROLLED:
        # course_title lands in the Subject header → collapse any newline; reuse the
        # collapsed value for the body so headline and body agree.
        course = " ".join((d.get("course_title") or "").split())
        subject = _("You've been enrolled in %(course)s") % {"course": course}
        body_line = _("You now have access to %(course)s.") % {"course": course}
    else:
        raise ValueError(f"email_content: no copy for kind {notification.kind!r}")
    headline = subject  # kept separate for future divergence
    return subject, headline, body_line
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest notifications/tests/test_email_content.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format notifications/ && uv run ruff check notifications/
git add notifications/emails.py notifications/tests/test_email_content.py
git commit -m "feat(notifications): email_content per-kind localized copy"
```

---

### Task 4: Email templates + `deliver_notification_email`

**Files:**
- Create: `notifications/templates/notifications/email/notification.html`
- Create: `notifications/templates/notifications/email/notification.txt`
- Modify: `notifications/emails.py`
- Test: `notifications/tests/test_email_delivery.py`

**Interfaces:**
- Consumes: `email_enabled`, `email_content`, `_absolute_url` (Tasks 2–3); `notifications.services.notification_url`; `core.services.get_site_config`.
- Produces: `deliver_notification_email(notification) -> None` — sends one multipart (text + HTML alternative) email to `notification.recipient`; no-op on blank email; **whole body wrapped in log-and-swallow** so any failure (render, content ValueError, send) never breaks the request/fan-out.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_delivery.py`:

```python
import pytest
from django.core import mail

from notifications.emails import deliver_notification_email
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _graded(recipient, course, **data):
    base = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": "Quiz 1",
        "node_pk": 999,
    }
    base.update(data)
    return Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data=base,
    )


def test_sends_multipart_with_html_alternative():
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["stu@example.com"]
    assert msg.subject == "Your quiz was graded"
    assert any(ctype == "text/html" for _content, ctype in msg.alternatives)


def test_blank_email_is_noop():
    recipient = UserFactory(email="")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert mail.outbox == []


def test_opted_out_kind_is_noop():
    recipient = UserFactory(email="stu@example.com")
    NotificationEmailPreference.objects.create(user=recipient, quiz_graded=False)
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert mail.outbox == []


def test_unknown_kind_swallowed_no_email_no_raise():
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=recipient,
        kind="bogus_kind",  # not in Kind.choices; DB has no constraint
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={},
    )
    deliver_notification_email(n)  # must not raise
    assert mail.outbox == []


def test_cta_is_absolute_and_uses_notification_url():
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory(slug="algebra"))
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "://" in html
    assert "/courses/algebra/" in html  # notification_url target, absolute


def test_cta_falls_back_to_list_when_no_target_url():
    # enrolled with no course_slug → notification_url returns None → /notifications/
    recipient = UserFactory(email="stu@example.com")
    n = Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=1,
        data={"course_title": "Algebra"},  # no course_slug
    )
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "/notifications/" in html


def test_html_escapes_user_data():
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    n = _graded(recipient, course, course_title="<b>x</b>")
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html


def test_header_uses_fallback_color_when_primary_none(monkeypatch):
    # An Institution with no valid primary color yields site.primary == None; the
    # template MUST fall back to #147E78 (an email has no external stylesheet).
    import notifications.emails as emails_mod

    monkeypatch.setattr(
        emails_mod, "get_site_config", lambda: {"name": "libli", "primary": None}
    )
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "#147E78" in html
    assert "background-color: ;" not in html  # None must not render as empty
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_delivery.py -v`
Expected: FAIL — `cannot import name 'deliver_notification_email'`.

- [ ] **Step 3: Create the HTML template**

Create `notifications/templates/notifications/email/notification.html`:

```html
{% load i18n %}
<div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1a1a1a;">
  <div style="background-color: {{ site.primary|default:'#147E78' }}; color: #ffffff; padding: 16px 20px; font-size: 18px; font-weight: bold;">
    {{ site.name }}
  </div>
  <div style="padding: 24px 20px; border: 1px solid #e5e5e5; border-top: none;">
    <h1 style="font-size: 18px; margin: 0 0 12px;">{{ headline }}</h1>
    <p style="font-size: 15px; line-height: 1.5; margin: 0 0 24px;">{{ body_line }}</p>
    <p style="margin: 0 0 28px;">
      <a href="{{ cta_url }}" style="display: inline-block; background-color: {{ site.primary|default:'#147E78' }}; color: #ffffff; text-decoration: none; padding: 10px 18px; border-radius: 4px; font-size: 15px;">{% trans "View in libli" %} &rarr;</a>
    </p>
    <p style="font-size: 12px; color: #777777; margin: 0; line-height: 1.5;">
      {% trans "You're receiving this because you have email notifications enabled for your libli account." %}
      <a href="{{ manage_url }}" style="color: {{ site.primary|default:'#147E78' }};">{% trans "Manage email preferences" %}</a>
    </p>
  </div>
</div>
```

- [ ] **Step 4: Create the plaintext template**

Create `notifications/templates/notifications/email/notification.txt`. The whole body is wrapped in `{% autoescape off %}` — Django auto-escapes regardless of file extension, so without it a title like "Math & Science" would render as "Math &amp; Science" in the *plaintext* body. Escaping matters only for the HTML alternative (Step 3), which correctly stays auto-escaped. (Leading blank lines in a plaintext email body are harmless.)

```text
{% load i18n %}{% autoescape off %}{{ headline }}

{{ body_line }}

{% trans "View in libli" %}: {{ cta_url }}

{% trans "You're receiving this because you have email notifications enabled for your libli account." %}
{% trans "Manage email preferences" %}: {{ manage_url }}
{% endautoescape %}
```

- [ ] **Step 5: Add `deliver_notification_email` to `notifications/emails.py`**

Add these imports at the top of `notifications/emails.py`:

```python
from django.conf import settings as dj_settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from core.services import get_site_config
from notifications.services import notification_url
```

Append the function:

```python
def deliver_notification_email(notification):
    """Send one multipart (text + HTML) email for a notification, localized to the
    recipient's language. No-op on a blank email address. The whole body is wrapped
    in log-and-swallow: this runs in a post-on_commit callback AFTER the row has
    committed, and notify_needs_review queues one callback per teacher — Django runs
    them in order and STOPS at the first that raises, so any unguarded failure (render,
    content ValueError, send) would silently skip the remaining recipients."""
    recipient = notification.recipient
    if not recipient.email:
        return
    try:
        if not email_enabled(recipient, notification.kind):
            return
        lang = recipient.language or dj_settings.LANGUAGE_CODE
        with translation.override(lang):
            subject, headline, body_line = email_content(notification)
            ctx = {
                "headline": headline,
                "body_line": body_line,
                "cta_url": _absolute_url(
                    notification_url(notification) or reverse("notifications:list")
                ),
                "manage_url": _absolute_url(reverse("core:user_settings")),
                "site": get_site_config(),
            }
            html = render_to_string("notifications/email/notification.html", ctx)
            text = render_to_string("notifications/email/notification.txt", ctx)
        msg = EmailMultiAlternatives(subject, text, None, [recipient.email])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception:  # noqa: BLE001 — never break the request / fan-out
        logger.exception(
            "notification email delivery failed (notification %s)", notification.pk
        )
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest notifications/tests/test_email_delivery.py -v`
Expected: PASS (8 tests).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format notifications/ && uv run ruff check notifications/
git add notifications/emails.py notifications/templates/notifications/email/ notifications/tests/test_email_delivery.py
git commit -m "feat(notifications): deliver_notification_email + branded email templates"
```

---

### Task 5: Wire delivery into the `notify()` choke-point

**Files:**
- Modify: `notifications/services.py` (add `import transaction`; add `on_commit` in `notify()`)
- Test: `notifications/tests/test_email_wiring.py`

**Interfaces:**
- Consumes: `deliver_notification_email` (Task 4) — imported **function-locally** inside `notify()`.
- Produces: every non-self-suppressed `notify()` registers `transaction.on_commit(lambda: deliver_notification_email(n))`; the in-app row is unchanged.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_wiring.py`:

```python
import pytest
from django.core import mail

from notifications import services
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_notify_sends_email_on_commit(django_capture_on_commit_callbacks):
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient,
            kind=Notification.Kind.ENROLLED,
            target=course,
            data={"course_title": course.title, "course_slug": course.slug},
        )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["stu@example.com"]


def test_self_suppressed_sends_nothing(django_capture_on_commit_callbacks):
    user = UserFactory(email="stu@example.com")
    course = CourseFactory()
    with django_capture_on_commit_callbacks(execute=True):
        result = services.notify(
            recipient=user,
            kind=Notification.Kind.ENROLLED,
            target=course,
            actor=user,
        )
    assert result is None
    assert Notification.objects.count() == 0
    assert mail.outbox == []


def test_opt_out_keeps_in_app_row_but_no_email(django_capture_on_commit_callbacks):
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    NotificationEmailPreference.objects.create(user=recipient, enrolled=False)
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient,
            kind=Notification.Kind.ENROLLED,
            target=course,
            data={"course_title": course.title, "course_slug": course.slug},
        )
    assert Notification.objects.filter(recipient=recipient).count() == 1  # in-app kept
    assert mail.outbox == []  # email suppressed
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_wiring.py -v`
Expected: FAIL — `test_notify_sends_email_on_commit` fails (`mail.outbox` empty; no delivery wired yet).

- [ ] **Step 3: Edit `notifications/services.py`**

Add at the top of `notifications/services.py` (with the other imports):

```python
from django.db import transaction
```

In `notify()`, insert the function-local import + `on_commit` between the `Notification.objects.create(...)` assignment and `return`. The result:

```python
def notify(*, recipient, kind, target, actor=None, data=None):
    """Record a notification. No-op (returns None) when recipient == actor.
    Call inside the emit site's transaction.atomic() block."""
    if actor is not None and recipient == actor:
        return None
    target_type, target_id = _resolve_target(target)
    n = Notification.objects.create(
        recipient=recipient,
        kind=kind,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        data=data or {},
    )
    # Function-local import: emails.py top-level-imports this module, so a top-level
    # import here would cycle at load. Deferring to call time breaks the cycle.
    from notifications.emails import deliver_notification_email

    transaction.on_commit(lambda: deliver_notification_email(n))
    return n
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest notifications/tests/test_email_wiring.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Cross-app regression audit (outbox drift)**

The choke-point now adds a message to `mail.outbox` on every commit-firing notify path. Most tests roll back (default `django_db`) so `on_commit` never fires — but any test that fires a notification under `transaction=True` / `django_capture_on_commit_callbacks(execute=True)` **and** asserts an exact `len(mail.outbox)` will now see an extra email. Run the notifications suite plus the emit-site suites (courses grading/enrollment, grouping, and the surfaces/settings tests):

Run the FULL non-e2e suite here (enumerating app dirs risks missing an emit-site test in an unlisted path; the full run is the reliable drift check, and Task 9 is the final backstop):

Run: `uv run pytest -q`

Expected: all PASS. **If any test fails on an outbox-count assertion**, that is the expected drift, not a bug in this task — fix it by updating that test's expected count to include the notification email(s), or by asserting on the specific invite/verification message rather than total length. Do NOT silence it by weakening the delivery guard. (The log-and-swallow guard only prevents *exceptions*; it does not suppress successfully-sent messages.)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format notifications/ && uv run ruff check notifications/
git add notifications/services.py notifications/tests/test_email_wiring.py
git commit -m "feat(notifications): emit delivery email at the notify() choke-point"
```

---

### Task 6: `NotificationEmailForm` + wire into `/settings/`

**Files:**
- Create: `notifications/forms.py`
- Modify: `core/views.py` (the `user_settings` view)
- Modify: `templates/core/user_settings.html` (new "Email notifications" section)
- Modify: `core/static/core/css/settings.css` (a `.switch` toggle style)
- Test: `notifications/tests/test_email_settings.py`

**Interfaces:**
- Consumes: `NotificationEmailPreference` (Task 1).
- Produces: `NotificationEmailForm(ModelForm)` with `Meta.fields = ["quiz_needs_review", "quiz_graded", "enrolled"]`. The view resolves `pref` read-only (unsaved instance on GET → no write), binds both forms on POST, saves only when **both** validate, and passes `notif_form` in the render context on every non-redirect path.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_settings.py`:

```python
import pytest
from django.urls import reverse

from notifications.models import NotificationEmailPreference
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_get_shows_section_without_creating_row(client):
    user = make_verified_user(username="prefu", email="prefu@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert b"Email notifications" in resp.content
    # GET is side-effect-free: no preference row written.
    assert NotificationEmailPreference.objects.filter(user=user).count() == 0


def test_post_persists_prefs_and_primary_form(client):
    user = make_verified_user(username="prefu2", email="prefu2@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            # primary UserSettingsForm fields (must be valid)
            "theme": "dark",
            "language": "en",
            "display_name": "Pat",
            "email": "prefu2@school.edu",
            # notification prefs: quiz_graded unchecked (absent), others on
            "quiz_needs_review": "on",
            "enrolled": "on",
        },
    )
    assert resp.status_code == 302
    pref = NotificationEmailPreference.objects.get(user=user)
    assert pref.quiz_graded is False  # unchecked → absent → False
    assert pref.enrolled is True
    assert pref.quiz_needs_review is True
    user.refresh_from_db()
    assert user.display_name == "Pat"  # primary form still saved


def test_post_invalid_primary_rerenders_with_notif_form(client):
    user = make_verified_user(username="prefu3", email="prefu3@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "dark",
            "language": "zz",  # not an enabled language → invalid
            "display_name": "Pat",
            "email": "prefu3@school.edu",
            "quiz_graded": "on",
        },
    )
    assert resp.status_code == 200  # re-render, no crash
    assert b"Email notifications" in resp.content
    # nothing saved on the invalid path
    assert NotificationEmailPreference.objects.filter(user=user).count() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_settings.py -v`
Expected: FAIL — `Email notifications` not in content (section not added yet).

- [ ] **Step 3: Create `notifications/forms.py`**

```python
from django import forms

from notifications.models import NotificationEmailPreference


class NotificationEmailForm(forms.ModelForm):
    """Per-kind email opt-out checkboxes. Meta.fields is the three booleans ONLY —
    NOT "__all__", which would include the required editable `user` OneToOne field,
    making the form invalid and (because the settings view gates on both forms
    validating) silently blocking the entire POST. `user` is supplied via
    instance=pref."""

    class Meta:
        model = NotificationEmailPreference
        fields = ["quiz_needs_review", "quiz_graded", "enrolled"]
```

- [ ] **Step 4: Edit `core/views.py` `user_settings`**

Immediately before `if request.method == "POST":` (currently `core/views.py:105`), resolve the preference read-only:

```python
    from notifications.forms import NotificationEmailForm
    from notifications.models import NotificationEmailPreference

    pref = (
        NotificationEmailPreference.objects.filter(user=request.user).first()
        or NotificationEmailPreference(user=request.user)  # unsaved → GET stays read-only
    )
```

In the POST branch, bind `notif_form` and gate on both forms. Replace:

```python
    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            from django.db import transaction

            from accounts.emails import reconcile_primary_email

            with transaction.atomic():
                user = form.save()
                if "email" in form.changed_data:
                    reconcile_primary_email(user)
```

with:

```python
    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        notif_form = NotificationEmailForm(request.POST, instance=pref)
        if form.is_valid() and notif_form.is_valid():
            from django.db import transaction

            from accounts.emails import reconcile_primary_email

            with transaction.atomic():
                user = form.save()
                notif_form.save()
                if "email" in form.changed_data:
                    reconcile_primary_email(user)
```

In the GET `else` branch, replace:

```python
    else:
        form = UserSettingsForm(instance=request.user)
```

with:

```python
    else:
        form = UserSettingsForm(instance=request.user)
        notif_form = NotificationEmailForm(instance=pref)
```

In the final `render(...)` context dict, add `notif_form`:

```python
    return render(
        request,
        "core/user_settings.html",
        {
            "form": form,
            "notif_form": notif_form,
            "sso_account": sso_account,
            "sso_provider_label": sso_provider_label,
        },
    )
```

- [ ] **Step 5: Add the template section**

In `templates/core/user_settings.html`, insert this `<section>` immediately before the `<div class="settings-save-bar">` (currently line 115). Each toggle is a real CSS-only switch (styled in Step 6) whose knob position conveys on/off — so there is NO static "On" text (a hardcoded label would misreport an opted-out toggle). The bare `<input>` carries an `aria-label` because it is hand-rolled (not form-rendered), so screen readers get a name:

Each help sentence is captured once via `{% trans "…" as var %}` and reused for both the
visible help text and the input's `aria-label` — this keeps them a single msgid and
sidesteps the apostrophe-vs-attribute-quote problem (double-quoted `{% trans %}` strings
hold `'` fine; an HTML entity like `&#39;` inside the msgid would create a mismatched
translation key):

```html
    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Email notifications" %}</h2>
      <p class="settings-sec-lede">{% trans "Choose which events email you. In-app notifications are always shown." %}</p>

      {% trans "Email me when a quiz I submitted is graded." as help_graded %}
      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Quiz graded" %}</div>
          <p class="settings-field-help">{{ help_graded }}</p>
        </div>
        <div class="settings-field-control">
          <label class="switch">
            <input type="checkbox" name="quiz_graded" {% if notif_form.quiz_graded.value %}checked{% endif %} aria-label="{{ help_graded }}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
        </div>
      </div>

      {% trans "Email me when I'm enrolled in a course." as help_enrolled %}
      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Course enrollment" %}</div>
          <p class="settings-field-help">{{ help_enrolled }}</p>
        </div>
        <div class="settings-field-control">
          <label class="switch">
            <input type="checkbox" name="enrolled" {% if notif_form.enrolled.value %}checked{% endif %} aria-label="{{ help_enrolled }}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
        </div>
      </div>

      {% trans "Email me when a student's quiz needs my review." as help_review %}
      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Quiz needs review" %}</div>
          <p class="settings-field-help">{{ help_review }}</p>
        </div>
        <div class="settings-field-control">
          <label class="switch">
            <input type="checkbox" name="quiz_needs_review" {% if notif_form.quiz_needs_review.value %}checked{% endif %} aria-label="{{ help_review }}">
            <span class="switch__track" aria-hidden="true"></span>
          </label>
        </div>
      </div>
    </section>
```

- [ ] **Step 6: Add the `.switch` toggle CSS**

`settings.css` is page-scoped (loaded via `{% block extra_css %}` on `user_settings.html`). Append this token-driven, `:checked`-driven switch (works with JS off, matching the file's existing controls) to the end of `core/static/core/css/settings.css`:

```css
/* Email-notification toggles: CSS-only switch (:checked-driven; JS-off safe). */
.switch { display: inline-flex; align-items: center; cursor: pointer; }
.switch input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.switch__track { position: relative; width: 40px; height: 22px; flex: none;
  background: var(--border-strong); border-radius: var(--radius-full);
  transition: background .15s ease; }
.switch__track::after { content: ""; position: absolute; top: 2px; left: 2px;
  width: 18px; height: 18px; background: #fff; border-radius: 50%;
  box-shadow: var(--shadow-sm); transition: transform .15s ease; }
.switch input:checked + .switch__track { background: var(--primary); }
.switch input:checked + .switch__track::after { transform: translateX(18px); }
.switch input:focus-visible + .switch__track { outline: 2px solid var(--primary); outline-offset: 2px; }
```

- [ ] **Step 7: Verify the toggle renders styled (light + dark)**

Per the project screenshot rule, spin up a throwaway Playwright capture of `/settings/` in light and dark, confirm the three toggles render as switches (knob left = off after unchecking, right = on) with adequate contrast, then delete the harness. (See the `verify-ui-with-screenshots` practice.)

- [ ] **Step 8: Run to verify pass**

Run: `uv run pytest notifications/tests/test_email_settings.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Lint + full-suite spot check**

Run: `uv run ruff format notifications/ core/ && uv run ruff check notifications/ core/ && uv run pytest tests/test_surfaces.py -v`
Expected: clean; surfaces tests still pass.

- [ ] **Step 10: Commit**

```bash
git add notifications/forms.py core/views.py templates/core/user_settings.html core/static/core/css/settings.css notifications/tests/test_email_settings.py
git commit -m "feat(notifications): per-kind email prefs on the settings page"
```

---

### Task 7: Polish translations (EN msgids → PL)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `notifications/tests/test_email_i18n.py`

**Interfaces:**
- Consumes: all `_(...)` / `{% trans %}` strings from Tasks 3, 4, 6.
- Produces: Polish `msgstr`s so a `language="pl"` recipient gets a Polish email + settings section.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_email_i18n.py`:

```python
import pytest
from django.core import mail

from notifications.emails import deliver_notification_email
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_polish_recipient_gets_polish_subject():
    recipient = UserFactory(email="pl@example.com", language="pl")
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": "Quiz 1",
            "node_pk": 999,
        },
    )
    deliver_notification_email(n)
    assert mail.outbox[0].subject == "Twój quiz został oceniony"


def test_per_recipient_language_is_independent():
    """Two recipients of the same event get the email in their OWN language — proves
    the per-recipient translation.override (the fan-out localization guarantee)."""
    course = CourseFactory()
    data = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": "Quiz 1",
        "node_pk": 999,
    }
    for lang, email in (("en", "en@example.com"), ("pl", "pl@example.com")):
        recipient = UserFactory(email=email, language=lang)
        n = Notification.objects.create(
            recipient=recipient,
            kind=Notification.Kind.QUIZ_GRADED,
            target_type=Notification.TargetType.COURSE,
            target_id=course.pk,
            data=data,
        )
        deliver_notification_email(n)
    subjects = {m.to[0]: m.subject for m in mail.outbox}
    assert subjects["en@example.com"] == "Your quiz was graded"
    assert subjects["pl@example.com"] == "Twój quiz został oceniony"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest notifications/tests/test_email_i18n.py -v`
Expected: FAIL — subject is the English msgid (no PL translation yet).

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
This adds the new `msgid`s to `locale/pl/LC_MESSAGES/django.po`.

- [ ] **Step 4: Fill in the Polish translations**

**First, the two colliding labels.** The settings toggle labels `"Quiz graded"` and
`"Quiz needs review"` are the SAME msgids as the existing `Notification.Kind` labels in
`notifications/models.py`, already present and translated in the po (currently
`"Quiz oceniony"` / `"Quiz wymaga sprawdzenia"`). `makemessages` will just add a new
source-reference comment to those existing entries — **do NOT re-add or overwrite their
`msgstr`**. (Likewise `"Course enrollment"` is a NEW, distinct msgid — deliberately not
the Kind's `"Enrolled in course"` — so it needs a fresh translation below.)

Then, in `locale/pl/LC_MESSAGES/django.po`, set the `msgstr` for each new `msgid` below,
and **remove any `#, fuzzy` flag line** above these entries (fuzzy entries are ignored at
runtime, and makemessages may have mis-guessed copies):

```
msgid "A quiz needs your review"
msgstr "Quiz wymaga sprawdzenia"

msgid "%(student)s submitted %(unit)s in %(course)s and it needs review."
msgstr "%(student)s przesłał(a) %(unit)s w kursie %(course)s — wymaga sprawdzenia."

msgid "Your quiz was graded"
msgstr "Twój quiz został oceniony"

msgid "Your submission for %(unit)s in %(course)s has been reviewed."
msgstr "Twoja odpowiedź do %(unit)s w kursie %(course)s została sprawdzona."

msgid "You've been enrolled in %(course)s"
msgstr "Zapisano Cię na kurs %(course)s"

msgid "You now have access to %(course)s."
msgstr "Masz teraz dostęp do kursu %(course)s."

msgid "View in libli"
msgstr "Otwórz w libli"

msgid "You're receiving this because you have email notifications enabled for your libli account."
msgstr "Otrzymujesz tę wiadomość, ponieważ masz włączone powiadomienia e-mail na koncie libli."

msgid "Manage email preferences"
msgstr "Zarządzaj powiadomieniami e-mail"

msgid "Email notifications"
msgstr "Powiadomienia e-mail"

msgid "Choose which events email you. In-app notifications are always shown."
msgstr "Wybierz, które zdarzenia wysyłają e-mail. Powiadomienia w aplikacji są zawsze widoczne."

msgid "Email me when a quiz I submitted is graded."
msgstr "Wyślij e-mail, gdy mój przesłany quiz zostanie oceniony."

msgid "Course enrollment"
msgstr "Zapisanie na kurs"

msgid "Email me when I'm enrolled in a course."
msgstr "Wyślij e-mail, gdy zostanę zapisany(a) na kurs."

msgid "Email me when a student's quiz needs my review."
msgstr "Wyślij e-mail, gdy quiz ucznia wymaga mojego sprawdzenia."
```

Note: `"Quiz graded"` and `"Quiz needs review"` are intentionally omitted here — they
already exist and are translated (see the collision note above); leave them untouched.
If `makemessages` surfaces any OTHER of these as pre-existing with a different `msgstr`,
verify with `grep -n 'msgid "<text>"' locale/pl/LC_MESSAGES/django.po` before editing and
do not clobber a shared translation.

- [ ] **Step 5: Compile + run the test**

Run: `uv run python manage.py compilemessages && uv run pytest notifications/tests/test_email_i18n.py -v`
Expected: PASS.

- [ ] **Step 6: Verify no msgid clobber / fuzzy left behind**

Run: `uv run pytest notifications/ tests/test_surfaces.py -q`
Expected: all PASS (confirms no shared translation was broken).

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo notifications/tests/test_email_i18n.py
git commit -m "i18n(notifications): Polish translations for notification emails + prefs"
```

---

### Task 8: e2e — toggle an email preference in the real UI

**Files:**
- Create: `notifications/tests/test_e2e_email_prefs.py`

**Interfaces:**
- Consumes: the settings page + `NotificationEmailForm` (Task 6).
- Produces: a Playwright test driving a real checkbox toggle + save + reload + assert persistence.

- [ ] **Step 1: Write the test**

Create `notifications/tests/test_e2e_email_prefs.py`:

```python
"""Playwright e2e for notifications slice 2: toggle an email preference on /settings/.

Real browser gestures only (project lesson: e2e that bypasses the real gesture ships
broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

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


@pytest.mark.django_db(transaction=True)
def test_email_pref_toggle_persists(page, live_server):
    from institution.roles import seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    make_verified_user(
        username="e2e_prefs", email="e2e_prefs@test.example.com"
    )
    _login(page, live_server, "e2e_prefs")

    page.goto(f"{live_server.url}/settings/")
    box = page.locator("input[name='quiz_graded']")
    expect(box).to_be_checked()  # default on
    box.uncheck()
    page.get_by_role("button", name="Save changes").click()

    # Reload and confirm the toggle stuck.
    page.goto(f"{live_server.url}/settings/")
    expect(page.locator("input[name='quiz_graded']")).not_to_be_checked()
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest notifications/tests/test_e2e_email_prefs.py -m e2e -v`
Expected: PASS (real browser: unchecks the box, saves, reloads, box is unchecked).

- [ ] **Step 3: Commit**

```bash
git add notifications/tests/test_e2e_email_prefs.py
git commit -m "test(notifications): e2e email-preference toggle persists via real UI"
```

---

### Task 9: Full suite + DoD gate

**Files:** none (verification only).

- [ ] **Step 1: Full non-e2e suite**

Run: `uv run pytest -q`
Expected: all pass (no regressions from the choke-point email hook).

- [ ] **Step 2: e2e suite**

Run: `uv run pytest -m e2e -q`
Expected: all e2e pass (slice-1 notification e2e + the new preference toggle).

- [ ] **Step 3: Lint + migration drift**

Run each independently (do NOT chain with `&&` — a ruff failure must not hide a migration-drift result; use the Bash tool):

```
uv run ruff format --check .
uv run ruff check .
uv run python manage.py makemigrations --check --dry-run
```

Expected: `ruff format --check` reports no files need reformatting; `ruff check` clean; migrations report "No changes detected".

- [ ] **Step 4: Final commit (if any lint/format fixups)**

```bash
git add -A
git commit -m "chore(notifications): slice-2 email delivery DoD green" || echo "nothing to commit"
```

---

## Notes for the implementer

- **Import direction is load-bearing.** `notifications/emails.py` top-level-imports `notifications.services` (`notification_url`) and `core.services` (`get_site_config`). `notifications.services.notify()` imports `emails` **function-locally**. Do NOT add a top-level `services → emails` import or a top-level `core`-import into `notifications.forms`/`models` — either would create a cycle.
- **Preference gates email only.** The `Notification` row is always created in `notify()`; `email_enabled` is checked at send time in `deliver_notification_email`. Never move the opt-out check into `notify()` (Task 5's `test_opt_out_keeps_in_app_row_but_no_email` guards this).
- **Checkbox semantics:** an unchecked HTML checkbox is omitted from POST; Django's `BooleanField` treats absence as `False`. That's why `test_post_persists_prefs_and_primary_form` sends `quiz_graded` absent and expects `False`.
- **`Notification.objects.create(kind="bogus")` is legal** — `kind` has `choices` but no DB constraint, so the unknown-kind tests can construct one directly.
- **Template↔form field coupling (accepted).** The settings checkboxes are hand-rolled `<input name="...">` (for full control over the `.switch` markup) rather than `{{ notif_form.<field> }}`. That duplicates the three field names between `NotificationEmailForm.Meta.fields` and the template. Keep them in sync: adding/renaming a kind means editing BOTH the form's `Meta.fields` and the template section. The `name=` attributes MUST exactly match `Meta.fields` or the POST silently won't bind that checkbox.
