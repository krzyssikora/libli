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
retention/purge, logo-in-email, and a `List-Unsubscribe` header (a deliverability
enhancement for near-bulk mail — deferred; the in-body "Manage email preferences" link
is the opt-out surface for now). These remain deferred (see roadmap).

---

## Design decisions (resolved in brainstorming)

- **Opt-out granularity:** per-kind (not a single toggle, not all-on-no-opt-out).
- **Cadence:** immediate, one email per event (reuses the invite-email
  `transaction.on_commit` cadence, but sends multipart via `EmailMultiAlternatives`
  rather than the invite's plaintext `send_mail`; no scheduler).
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
created lazily by the settings view — only when the user **saves** the preferences form
(`notif_form.save()` on POST) — never eagerly per user and never on a GET (see §4).

```python
def email_enabled(user, kind):
    pref = NotificationEmailPreference.objects.filter(user=user).first()
    if pref is None:
        return True          # default-on
    return getattr(pref, kind)
```

`kind` is always a valid `Notification.Kind` value (it comes from a `Notification`
row), so `getattr` is safe; no `default` fallback needed. (`email_enabled` lives in
`emails.py` beside its only caller — see §6 — shown here for the storage semantics.)

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
    from notifications.emails import deliver_notification_email  # function-local: see below
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
- **Accepted latency tradeoff.** `on_commit` callbacks run during the committing
  request, before the response returns, so an event that fans out to N recipients blocks
  that request on N sequential SMTP sends. This is an accepted cost of "immediate, no
  Celery" delivery at this scale; a task queue (Celery) is the deferred mitigation if
  fan-out latency ever bites.

`from django.db import transaction` is added to `services.py`.

**Import direction (avoids a cycle).** `emails.py` imports `notification_url` from
`services.py` at **module top level** (one-way: `emails → services`). A matching
top-level `services → emails` import would cycle at load; so `notify()` imports
`deliver_notification_email` **function-locally** (shown above), deferring the `emails`
import to call time — the same function-local-import idiom slice 1 already uses for its
emit helpers. Net graph: `services` (top-level, acyclic) ← `emails` (top-level) ←
`services.notify()` (deferred).

### 2.2 `deliver_notification_email(notification)` — new `notifications/emails.py`

```python
def deliver_notification_email(notification):
    recipient = notification.recipient
    if not recipient.email:
        return                                  # nothing to send to
    try:
        if not email_enabled(recipient, notification.kind):
            return                              # opted out of this kind
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
    except Exception:                            # noqa: BLE001 — never break the request / fan-out
        logger.exception("notification email delivery failed (notification %s)", notification.pk)
```

- **Preference gates email only, never the in-app row.** The `Notification` is always
  created; `email_enabled` is checked here, at send time. The bell/list is unaffected
  by email opt-outs.
- **Any per-recipient failure is swallowed (log, don't raise).**
  `deliver_notification_email` runs in a post-`on_commit` callback, *after* the
  `Notification` row has already committed, so a raise cannot roll anything back — it
  would only surface an exception in the request cycle. Critically,
  `notify_needs_review` queues **one `on_commit` callback per teacher**, and Django runs
  queued callbacks in order and stops at the first that raises — so an unguarded failure
  for teacher #1 would silently skip teachers #2..N. The guard therefore wraps the whole
  per-recipient body — `email_enabled`, `email_content` (which can `raise ValueError` on
  an unknown kind), `render_to_string`, `Site`/`get_site_config` lookups, **and**
  `send()` — not just `send()`, because any of those raising would break the fan-out the
  same way. Only the cheap `recipient.email` blank-check sits outside the try (it can't
  raise). Log-and-swallow keeps each recipient independent and never orphans a committed
  row. (This is stricter than the invite precedent, which sends a single un-guarded
  email; the fan-out here makes isolation matter.) `logger =
  logging.getLogger(__name__)` at module top of `emails.py`.
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
list. `_absolute_url` is called twice per email (`cta_url`, `manage_url`), each
invoking `Site.objects.get_current()`; with `SITE_ID` set Django caches the current
Site, so these are not extra DB hits per call — no need to hoist the lookup.

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
        body_line = _("Your submission for %(unit)s in %(course)s has been reviewed.") % {
            "unit": d.get("unit_title", ""),
            "course": d.get("course_title", ""),
        }
    elif notification.kind == Notification.Kind.ENROLLED:
        # course_title lands in the Subject header → collapse any newline (see below);
        # reuse the collapsed value for the body too so headline and body agree.
        course = " ".join((d.get("course_title") or "").split())
        subject = _("You've been enrolled in %(course)s") % {"course": course}
        body_line = _("You now have access to %(course)s.") % {"course": course}
    else:
        raise ValueError(f"email_content: no copy for kind {notification.kind!r}")
    headline = subject   # headline mirrors subject; kept separate for future divergence
    return subject, headline, body_line
```

Called inside `translation.override`, so `_()` (eager `gettext`) yields the recipient's
language. `%(name)s` interpolation (not f-strings) keeps the msgids translatable.
**`emails.py` imports the eager alias — `from django.utils.translation import gettext
as _`** — NOT `gettext_lazy` (which `models.py` binds to `_`): a lazy proxy would defer
interpolation until *outside* the `override` block and localize to the wrong language.
The explicit `else: raise` means a future kind added before its copy fails loudly here
rather than raising a bare `UnboundLocalError`.

**Subject-header safety.** The `enrolled` subject interpolates the user-controlled
`course_title` into the email `Subject:` header (the two quiz subjects are static). A
newline in a title would trigger Django's `BadHeaderError` at `send()`. `Course.title`
is a single-line `CharField`, so this is unlikely; still, the code block above collapses
whitespace (`" ".join((course_title or "").split())`) before interpolating into the
subject. Under the §2.2 whole-body guard a `BadHeaderError` would otherwise be logged
and the email dropped (the in-app row already exists) — the collapse avoids the silent
drop.

### 3.2 Templates

- `notifications/email/notification.html` — branded shell: a header bar tinted with the
  institution **primary** brand color showing the institution **name**; then the
  headline, the body line, a CTA button (*"View in libli →"*, linking `cta_url`), and a
  footer sentence *"You're receiving this because you have email notifications enabled
  for your libli account."* followed by a *"Manage email preferences"* link to
  `manage_url`. Inline styles only (email clients strip `<style>`/external CSS).
- `notifications/email/notification.txt` — plaintext: headline, body line, bare CTA URL,
  the same footer sentence, and the manage-preferences URL.

**Template-level copy is `{% trans %}`-wrapped.** The strings that live in the
templates rather than in `email_content` — the CTA label (*"View in libli →"*), the
footer sentence, and the *"Manage email preferences"* link text — must be wrapped in
`{% trans %}`/`{% blocktrans %}` so they localize under `translation.override` along
with the rest of the email (and get msgids + PL translations per §5). The rendering
already runs inside the `override` block, so wrapped tags pick up the recipient's
language. Both email templates begin with `{% load i18n %}` — without it the
`{% trans %}` tags raise `TemplateSyntaxError`, which the §2.2 whole-body guard would
silently swallow (email dropped, only a log line).

`headline`/`body_line` embed user-controlled strings (course/unit titles, student
name). The HTML template renders them **auto-escaped** — `{{ body_line }}` /
`{{ headline }}`, never `|safe` — so a title containing `<`/`&` cannot inject markup
into the email.

**Institution branding** comes from `core.services.get_site_config()` — the same
cached bundle the context processors already use — which returns `name`, `primary`,
and `logo_url`. Template reads `site.name` and `site.primary`.

**`site.primary` is frequently `None` — the template MUST hardcode a fallback.**
`_build()` sets `"primary": _safe_color(colors.get("primary"))`, which returns `None`
whenever an `Institution` row exists but has no *valid* `primary` brand color (the
common case); the `_DEFAULTS["primary"] = "#147E78"` fallback only applies when there
is **no** `Institution` row at all. On-page CSS tolerates this (a CSS var falls back),
but an email has no external stylesheet, so `background-color: {{ site.primary }}`
would render `background-color: ;` (Django prints `None` as empty) → an uncolored
header. The template must supply the fallback explicitly, e.g.
`{{ site.primary|default:"#147E78" }}` (matching `PRIMARY_DEFAULT`), on every use of
the color.

**Logo is deferred**: `logo_url` is a relative media path (`inst.logo.url`), so email
use would need an absolute URL + image hosting this single-tenant deploy hasn't set
up — name + color only.

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
- `NotificationEmailForm` — a `ModelForm` over `NotificationEmailPreference` with
  **`Meta.fields = ["quiz_needs_review", "quiz_graded", "enrolled"]`** (the `user`
  OneToOne is excluded — it's supplied via `instance=pref`). Do **not** use
  `fields = "__all__"`: that would include the required editable `user` field, making
  `notif_form.is_valid()` fail and — because saving is gated on both forms validating —
  silently blocking the entire settings POST. The three booleans render as checkboxes
  in an **"Email notifications"** section under the current user-settings form, styled
  to match existing settings sections (every view ships styled).
- **POST control flow (pinned).** The `notif_form` instance is resolved read-only:
  `pref = NotificationEmailPreference.objects.filter(user=request.user).first() or
  NotificationEmailPreference(user=request.user)` — an **unsaved** instance when no row
  exists, so a plain GET stays side-effect-free (no write on a safe method; consistent
  with §1's "never eagerly per user"). On GET, `notif_form` is instantiated
  `instance=pref` and **unbound**. On POST it binds `request.POST` to that same
  `instance=pref` alongside `form` (the existing `UserSettingsForm`); the view saves —
  inside the existing `transaction.atomic()` — only when **both** validate
  (`if form.is_valid() and notif_form.is_valid():`), and `notif_form.save()` then INSERTs
  or UPDATEs the row as needed. It then redirects with the success message as today; the
  invalid path falls through to the same re-render. `notif_form` MUST be present in the
  `render(...)` context on every non-redirect path (GET and invalid-POST re-render) —
  otherwise those paths raise a template error on the new section. A single Save button
  submits both.
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
- **CTA link:** the rendered email body contains the **absolute** target URL
  (`scheme://domain/...` via `_absolute_url`) — resolving to `notification_url(...)` for a
  normal notification, and falling back to the absolute `/notifications/` list URL when
  `notification_url` returns `None` (exercises the `or reverse("notifications:list")`
  branch).
- **`notify()` wiring:** creating a notification registers an `on_commit` email
  (transaction-capture test / `transaction=True` + locmem outbox); a self-suppressed
  `notify()` sends nothing.
- **Opt-out keeps the in-app row (invariant, end-to-end):** with a user opted out of a
  kind, a full `notify()` (on-commit fired) still creates the `Notification` row while
  the outbox stays empty — guards against a regression that moved the opt-out check into
  `notify()` and dropped the in-app row.
- **Subject newline-strip:** a notification whose `course_title` contains an embedded
  newline delivers a single-line `Subject` header and `send()` does not raise
  `BadHeaderError`.
- **Per-recipient language:** `notify_needs_review` to two teachers of different
  languages produces two emails in the respective languages.
- **Settings form/view:** saving the form persists the three booleans; the page still
  saves the primary user-settings form in the same POST.
- **e2e (Playwright, real gestures):** load `/settings/`, toggle a notification-email
  checkbox, save, reload, assert it persisted (drives the real UI, not `page.evaluate`).
- **Slice-1 regression audit:** adding the email hook to the `notify()` choke-point
  means every existing commit-firing path (and any slice-1 test using
  `django_capture_on_commit_callbacks(execute=True)` or `transaction=True`) now also
  runs the mail backend. Run the full existing suite and confirm no assertion drift
  (locmem backend swallows the sends; the send-failure `try/except` prevents a bad
  fixture address from breaking an unrelated test).
- **i18n:** new msgids extracted + PL translations added, fuzzy flags cleared, `.mo`
  compiled; verify no shared-msgid clobber.

---

## 6. Files touched / added

**Added**
- `notifications/emails.py` — `deliver_notification_email`, `email_content`,
  `email_enabled`, `_absolute_url`.
- `notifications/forms.py` — `NotificationEmailForm`.
- `notifications/migrations/0002_notificationemailpreference.py`.
- `notifications/templates/notifications/email/notification.html`
- `notifications/templates/notifications/email/notification.txt`
- Tests under `notifications/tests/` (delivery, preferences, wiring, form, e2e).

**Modified**
- `notifications/models.py` — `NotificationEmailPreference` model only. `email_enabled`
  lives in `emails.py` (co-located with the sole caller, `deliver_notification_email`;
  it imports the model one-way, no cycle) — not in `services.py`, which would deepen the
  `emails → services` dependency discussed in §2.1.
- `notifications/services.py` — `transaction.on_commit(deliver_notification_email)` in
  `notify()`; `import transaction`.
- `core/views.py` — bind/save `NotificationEmailForm` in `user_settings`. This adds a
  new `core.views → notifications.forms` top-level import edge; it stays acyclic only
  because `notifications.forms`/`models` do **not** top-level-import `core` (and
  `notifications.emails`, which *does* import `core.services`, is itself imported
  function-locally by `notify()`). Keep `forms`/`models` free of top-level `core`
  imports.
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
