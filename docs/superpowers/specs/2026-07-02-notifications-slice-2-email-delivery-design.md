# Notifications Slice 2 — Email delivery — Design

*Drafted 2026-07-02. Second slice of the post-v1 **Notifications** feature. Slice 1
(in-app event notifications + `/notifications/` list + nav badge) shipped as PR #61.
This slice mirrors those notifications to **email**, immediately, per event, with a
per-kind user opt-out.*

Companion docs: [`../../roadmap.md`](../../roadmap.md) (Deferred → Notifications row).

---

## Goal

When a `Notification` row is created via the `notify()` choke-point, also send the
recipient an email — unless they have opted that notification *kind* out. Email is
HTML + plaintext multipart, localized to the recipient's own UI language, and sent
immediately (one email per event, no digest, **no Celery**).

Non-goals (this slice): batched digests, announcements, in-app bell dropdown,
retention/purge, logo-in-email. These remain deferred (see roadmap).

---

## Design decisions (resolved in brainstorming)

- **Opt-out granularity:** per-kind (not a single toggle, not all-on-no-opt-out).
- **Cadence:** immediate, one email per event (reuses the invite-email
  `transaction.on_commit` + `send_mail` pattern; no scheduler).
- **Format:** HTML + plaintext multipart, branded with institution name + primary
  brand color. Logo-in-email deferred.

---

## 1. Per-kind preference storage

A new model in the `notifications` app:

```python
class NotificationEmailPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_email_pref",
    )
    quiz_needs_review = models.BooleanField(default=True)
    quiz_graded = models.BooleanField(default=True)
    enrolled = models.BooleanField(default=True)
```

**The boolean field names deliberately equal the `Notification.Kind` values**
(`"quiz_needs_review"`, `"quiz_graded"`, `"enrolled"`), so a kind resolves to its
field with a direct `getattr(pref, notification.kind)` — no mapping table. Adding a
future kind = add a field named after the new `Kind` value (a migration, alongside
the template/emit-helper work that a new kind already requires).

**Default is all-on.** A user with no preference row receives every kind. The row is
created lazily by the settings view (`get_or_create`), never eagerly per user.

```python
def email_enabled(user, kind):
    pref = NotificationEmailPreference.objects.filter(user=user).first()
    if pref is None:
        return True          # default-on
    return getattr(pref, kind)
```

`kind` is always a valid `Notification.Kind` value (it comes from a `Notification`
row), so `getattr` is safe; no `default` fallback needed.

**Migration:** `notifications/0002_notificationemailpreference.py` (additive, new
table only; no data migration — absence = default-on).

Rejected alternatives: opt-out rows keyed `(user, kind)` (no per-kind migration, but
a hand-rolled checkbox-diff form instead of a ModelForm); three booleans on `User`
(couples `accounts` to notification-kind knowledge).

---

## 2. Delivery seam

### 2.1 Hook at the `notify()` choke-point

`notifications/services.py::notify()` gains one line after the row is created:

```python
def notify(*, recipient, kind, target, actor=None, data=None):
    if actor is not None and recipient == actor:
        return None                      # self-suppressed: no row, no email
    target_type, target_id = _resolve_target(target)
    n = Notification.objects.create(...)
    transaction.on_commit(lambda: deliver_notification_email(n))
    return n
```

- Self-suppressed calls `return None` **before** create → nothing registered → no
  email. (So self-enroll, which passes `actor=student`, sends no email — consistent
  with its no-in-app-row behaviour.)
- `on_commit` means a rolled-back emit sends nothing, and pytest-django's
  transaction-wrapped tests do **not** fire the callback unless they opt in
  (`transaction=True` or an explicit `captureOnCommitCallbacks`) — exactly how the
  existing invite-email tests behave.
- `notify_needs_review` fans to several teachers via separate `notify()` calls →
  separate `on_commit` callbacks → each email renders in its own recipient's
  language.

`from django.db import transaction` is added to `services.py`.

### 2.2 `deliver_notification_email(notification)` — new `notifications/emails.py`

```python
def deliver_notification_email(notification):
    recipient = notification.recipient
    if not recipient.email:
        return                                  # nothing to send to
    if not email_enabled(recipient, notification.kind):
        return                                  # opted out of this kind
    with translation.override(recipient.language):
        subject, headline, body_line = email_content(notification)
        ctx = {
            "headline": headline,
            "body_line": body_line,
            "cta_url": _absolute_url(notification_url(notification) or reverse("notifications:list")),
            "manage_url": _absolute_url(reverse("core:user_settings")),
            "site": get_site_config(),   # cached dict: name + primary color (+ logo_url, unused)
        }
        html = render_to_string("notifications/email/notification.html", ctx)
        text = render_to_string("notifications/email/notification.txt", ctx)
    msg = EmailMultiAlternatives(subject, text, None, [recipient.email])
    msg.attach_alternative(html, "text/html")
    msg.send()
```

- **Preference gates email only, never the in-app row.** The `Notification` is always
  created; `email_enabled` is checked here, at send time. The bell/list is unaffected
  by email opt-outs.
- **`from_email=None` → `DEFAULT_FROM_EMAIL`** (matches `accounts/invitations.py`).
- **Localization** via `translation.override(recipient.language)` around all rendering
  (subject copy included). `recipient.language` is the `en`/`pl` field on `User`.

### 2.3 Absolute links — `_absolute_url(path)`

```python
def _absolute_url(path):
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"
```

Same host-spoof-safe approach as `accounts/invitations.build_accept_url` (Site domain,
never a request Host header). CTA target = `notification_url(notification)` (the
existing slice-1 reverse helper) or, when that returns `None`, the `/notifications/`
list.

---

## 3. Email templates + copy

### 3.1 Kind-specific copy in one localized helper

Rather than 3 kinds × 2 formats of template file, a single helper computes the
kind-specific strings from the **denormalized `data`** (no DB loads):

```python
def email_content(notification):
    """Return (subject, headline, body_line) for the notification's kind,
    localized under the caller's active language. Reads only notification.data."""
    d = notification.data or {}
    if notification.kind == Notification.Kind.QUIZ_NEEDS_REVIEW:
        subject = _("A quiz needs your review")
        body_line = _("%(student)s submitted %(unit)s in %(course)s and it needs review.") % {
            "student": d.get("student_name", ""),
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.QUIZ_GRADED:
        subject = _("Your quiz was graded")
        body_line = _("Your submission for %(unit)s in %(course)s has been reviewed.") % {...}
    elif notification.kind == Notification.Kind.ENROLLED:
        subject = _("You've been enrolled in %(course)s") % {"course": d.get("course_title", "")}
        body_line = _("You now have access to %(course)s.") % {"course": d.get("course_title", "")}
    headline = subject   # headline mirrors subject; kept separate for future divergence
    return subject, headline, body_line
```

Called inside `translation.override`, so `_()` (eager `gettext`) yields the recipient's
language. `%(name)s` interpolation (not f-strings) keeps the msgids translatable.

### 3.2 Templates

- `notifications/email/notification.html` — branded shell: a header bar tinted with the
  institution **primary** brand color showing the institution **name**; then the
  headline, the body line, a CTA button (*"View in libli →"*, linking `cta_url`), and a
  footer line *"You're receiving this because …  Manage email preferences"* linking
  `manage_url`. Inline styles only (email clients strip `<style>`/external CSS).
- `notifications/email/notification.txt` — plaintext: headline, body line, bare CTA URL,
  and the manage-preferences URL.

**Institution branding** comes from `core.services.get_site_config()` — the same
cached bundle the context processors already use — which returns `name`, `primary`
(a validated CSS color, already defaulted when unset), and `logo_url`. Template reads
`site.name` and `site.primary`. **Logo is deferred**: `logo_url` is a relative media
path (`inst.logo.url`), so email use would need an absolute URL + image hosting this
single-tenant deploy hasn't set up — name + color only.

### 3.3 Copy table (EN; PL via msgids)

| Kind | Subject | Body line |
|---|---|---|
| `quiz_needs_review` | A quiz needs your review | {student} submitted {unit} in {course} and it needs review. |
| `quiz_graded` | Your quiz was graded | Your submission for {unit} in {course} has been reviewed. |
| `enrolled` | You've been enrolled in {course} | You now have access to {course}. |

---

## 4. Settings UI

- **Second form on the existing `/settings/` page** (`core/views.py::user_settings`,
  template `core/user_settings.html`).
- `NotificationEmailForm` — a `ModelForm` over `NotificationEmailPreference` exposing the
  three boolean fields as checkboxes, rendered as its own **"Email notifications"**
  section under the current user-settings form, styled to match existing settings
  sections (every view ships styled).
- The view `get_or_create`s the preference row for `request.user`, binds it on GET, and
  on POST saves **both** forms inside the existing `transaction.atomic()` (a single
  Save button; the page already redirects to itself with a success message).
- **All three toggles shown to every user.** A student toggling "quiz needs review" is
  simply inert (they never receive that kind); role-filtering the toggles is extra
  logic for no real gain. Labels make the direction clear (e.g. *"Email me when a quiz
  I submitted is graded"*).

---

## 5. Testing (TDD)

- **Model / preference:** default-on when no row; `email_enabled` returns the field
  value when a row exists (true and false cases); field names match `Kind` values.
- **`deliver_notification_email`:** sends a multipart message to the recipient
  (locmem outbox: 1 message, has HTML alternative + text body); no-op on blank
  `recipient.email`; no-op when the kind is opted out; **PL localization** — a
  recipient with `language="pl"` gets the Polish subject (assert via `override`/outbox).
- **`notify()` wiring:** creating a notification registers an `on_commit` email
  (transaction-capture test / `transaction=True` + locmem outbox); a self-suppressed
  `notify()` sends nothing.
- **Per-recipient language:** `notify_needs_review` to two teachers of different
  languages produces two emails in the respective languages.
- **Settings form/view:** saving the form persists the three booleans; the page still
  saves the primary user-settings form in the same POST.
- **e2e (Playwright, real gestures):** load `/settings/`, toggle a notification-email
  checkbox, save, reload, assert it persisted (drives the real UI, not `page.evaluate`).
- **i18n:** new msgids extracted + PL translations added, fuzzy flags cleared, `.mo`
  compiled; verify no shared-msgid clobber.

---

## 6. Files touched / added

**Added**
- `notifications/emails.py` — `deliver_notification_email`, `email_content`,
  `_absolute_url`.
- `notifications/forms.py` — `NotificationEmailForm`.
- `notifications/migrations/0002_notificationemailpreference.py`.
- `notifications/templates/notifications/email/notification.html`
- `notifications/templates/notifications/email/notification.txt`
- Tests under `notifications/tests/` (delivery, preferences, wiring, form, e2e).

**Modified**
- `notifications/models.py` — `NotificationEmailPreference` + `email_enabled` (or place
  `email_enabled` in `services.py`/`emails.py`).
- `notifications/services.py` — `transaction.on_commit(deliver_notification_email)` in
  `notify()`; `import transaction`.
- `core/views.py` — bind/save `NotificationEmailForm` in `user_settings`.
- `core/templates/.../user_settings.html` — "Email notifications" section.
- `locale/pl/LC_MESSAGES/django.po` (+ `.mo`) — new msgids.

---

## 7. Reserved-hook note

The `notify()` choke-point remains the single domain-event fan-out site. The deferred
**SIS / e-register webhook** item should subscribe at this same seam (a shared
outbound-event dispatcher), not re-instrument the emit sites — consistent with the
roadmap's "shared outbound-event substrate" note. This slice does not build that
substrate, but adding email at the choke-point (rather than at each emit site) keeps
that future refactor to one place.
