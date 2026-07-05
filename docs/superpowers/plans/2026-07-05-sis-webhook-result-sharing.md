# SIS / e-register grade-sync webhook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a student's quiz result is finalized, enqueue a denormalized delivery to a durable outbox and have a cron-run command POST it (HMAC-signed) to one platform-configured external register endpoint.

**Architecture:** A new `integrations` Django app owns two models (`WebhookEndpoint` config singleton, `WebhookDelivery` outbox) and a single `emit_result_finalized(submission)` choke-point called inside the three quiz-finalize `atomic()` blocks. A `flush_webhooks` management command sends pending rows with exponential backoff. External-register identity is carried by optional `external_id` fields on `User`, `Course`, and `Group`. Configuration lives on a new "Integrations" tab in the existing `/manage/settings/` surface.

**Tech Stack:** Python 3.13 + Django 5.2, PostgreSQL, pytest + factory_boy, stdlib `urllib.request` + `hmac` (no new dependency), `uv` tooling.

## Global Constraints

- **Tooling:** `uv run ruff check .`, `uv run ruff format .`, `uv run pytest`, `uv run python manage.py …`. Bare `ruff`/`pytest`/`python` are NOT on PATH. CI runs `ruff format --check`, so run `uv run ruff format .` before every commit.
- **No new runtime dependency.** Use stdlib `urllib.request`/`urllib.error`/`hmac`/`hashlib`. `requests` is not vendored — do not add it.
- **New-app pattern** mirrors `notifications`/`notes`/`tags`: own `models`, `services`, `forms`, `management/commands`, `tests`, migrations.
- **Emit is called inside the caller's existing `transaction.atomic()` block** via **function-local imports** of `integrations.services` (the sites import from `courses`/`grouping`, so a top-level import would cycle).
- **Config read on the finalize hot path is read-only:** `WebhookEndpoint.objects.filter(pk=1).first()`, never the write-capable `.load()`.
- **i18n:** `gettext_lazy` for model choices/labels, `{% trans %}` in templates; EN + PL `.po` updated (clear `#, fuzzy`, verify machine guesses), `.mo` compiled.
- **Tests never hard-code passwords** — use `tests.factories.TEST_PASSWORD` and the `make_pa` / `make_login` helpers.
- **Every settings surface ships styled** — the Integrations tab uses libli's token CSS, verified light + dark; no undefined classes.
- **Decimal money discipline:** `score`/`max_score` are `DecimalField`; serialize as strings, never floats.

Spec: [`../specs/2026-07-05-sis-webhook-result-sharing-design.md`](../specs/2026-07-05-sis-webhook-result-sharing-design.md).

---

## File structure

**Create:**
- `integrations/__init__.py`, `integrations/apps.py`
- `integrations/models.py` — `WebhookEndpoint`, `WebhookDelivery`
- `integrations/services.py` — `emit_result_finalized`, `build_payload`, `dedupe_key`, supersede/fan-out
- `integrations/delivery.py` — `deliver_one(delivery)`: sign + opener + POST + outcome/backoff (pure send primitive)
- `integrations/forms.py` — `IntegrationsForm`
- `integrations/migrations/0001_initial.py` (generated)
- `integrations/management/__init__.py`, `integrations/management/commands/__init__.py`, `integrations/management/commands/flush_webhooks.py`
- `integrations/tests/__init__.py` + test modules
- `templates/institution/manage/_integrations_tab.html`

**Modify:**
- `config/settings/base.py` — add `"integrations"` to local apps
- `accounts/models.py` (`User`) + `accounts/forms.py` (`UserEditForm`) — `external_id`
- `courses/models.py` (`Course`) + `courses/forms.py` (`CourseForm`) — `external_id`
- `grouping/models.py` (`Group`) + `grouping/forms.py` (`GroupForm`) — `external_id`
- `courses/views.py::quiz_finish` (~627) + `courses/review.py::force_submit_quiz` (~74) + `courses/review.py::review_response` (~34) — emit wiring
- `institution/views_manage.py` (TABS, `_settings_context`, `settings_integrations`) + `institution/urls.py` + `templates/institution/manage/settings.html` — Integrations tab

No `integrations/urls.py`/`views.py` — the only web surface (the settings tab + recent-deliveries panel) is served by the `institution` app; the external-id fields ride existing forms.

---

### Task 1: Scaffold `integrations` app + outbox models

**Files:**
- Create: `integrations/__init__.py` (empty), `integrations/apps.py`, `integrations/models.py`, `integrations/tests/__init__.py` (empty), `integrations/tests/test_models.py`
- Modify: `config/settings/base.py` (local-apps block, after `"tags"`)
- Create (generated): `integrations/migrations/0001_initial.py`

**Interfaces:**
- Produces: `integrations.models.WebhookEndpoint` (singleton via `load()`, fields `enabled: bool`, `url: str`, `secret: str`); `integrations.models.WebhookDelivery` (fields `event`, `dedupe_key: str`, `payload: dict`, `status`, `attempts: int`, `next_attempt_at`, `last_error`, `created_at`, `delivered_at`; choices `WebhookDelivery.Status.{PENDING,DELIVERED,DEAD,SUPERSEDED}`, `WebhookDelivery.Event.RESULT_FINALIZED`).

- [ ] **Step 1: Register the app**

In `config/settings/base.py`, add `"integrations"` to the local-apps list immediately after `"tags"`:

```python
    "notes",
    "notifications",
    "tags",
    "integrations",
]
```

- [ ] **Step 2: Create the app package**

`integrations/__init__.py` — empty file.

`integrations/apps.py`:

```python
from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
```

- [ ] **Step 3: Write the failing test**

`integrations/tests/__init__.py` — empty file.

`integrations/tests/test_models.py`:

```python
import pytest
from django.utils import timezone

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def test_endpoint_load_is_singleton():
    a = WebhookEndpoint.load()
    a.enabled = True
    a.url = "https://register.example/hook"
    a.save()
    b = WebhookEndpoint.load()
    assert a.pk == 1 and b.pk == 1
    assert b.enabled is True
    assert b.url == "https://register.example/hook"
    assert WebhookEndpoint.objects.count() == 1


def test_delivery_defaults():
    row = WebhookDelivery.objects.create(dedupe_key="7:3", payload={"x": 1})
    assert row.status == WebhookDelivery.Status.PENDING
    assert row.event == WebhookDelivery.Event.RESULT_FINALIZED
    assert row.attempts == 0
    assert row.last_error == ""
    assert row.delivered_at is None
    # default=timezone.now makes a fresh row immediately due
    assert row.next_attempt_at <= timezone.now()
```

- [ ] **Step 4: Run the test, verify it fails**

Run: `uv run pytest integrations/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.models'` (or import error).

- [ ] **Step 5: Write the models**

`integrations/models.py`:

```python
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class WebhookEndpoint(models.Model):
    """Single-row (pk=1) config for the one outbound endpoint. Holds a secret and
    is read only by the flush command + the settings form — never on the render
    hot path (emit reads it read-only via filter(pk=1).first())."""

    enabled = models.BooleanField(default=False)
    url = models.URLField(blank=True)  # http/https; scheme checked in the form
    secret = models.CharField(max_length=255, blank=True)  # HMAC key, plaintext
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class WebhookDelivery(models.Model):
    """One outbox row = one pending/attempted POST of one finalized result."""

    class Event(models.TextChoices):
        RESULT_FINALIZED = "result_finalized", _("Result finalized")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        DELIVERED = "delivered", _("Delivered")
        DEAD = "dead", _("Dead")
        SUPERSEDED = "superseded", _("Superseded")

    event = models.CharField(
        max_length=32, choices=Event.choices, default=Event.RESULT_FINALIZED
    )
    dedupe_key = models.CharField(max_length=128)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["dedupe_key", "status"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at", "-id"]
```

- [ ] **Step 6: Make the migration**

Run: `uv run python manage.py makemigrations integrations`
Expected: creates `integrations/migrations/0001_initial.py` with both models. (`makemigrations` also creates `integrations/migrations/__init__.py`.)

- [ ] **Step 7: Run the test, verify it passes**

Run: `uv run pytest integrations/tests/test_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations config/settings/base.py
git commit -m "feat(integrations): scaffold app + WebhookEndpoint/WebhookDelivery outbox models"
```

---

### Task 2: `external_id` fields on User, Course, Group

**Files:**
- Modify: `accounts/models.py` (`class User`), `courses/models.py` (`class Course` ~line 110), `grouping/models.py` (`class Group` ~line 83)
- Create (generated): one migration per app (`accounts`, `courses`, `grouping`)
- Create: `integrations/tests/test_external_id.py`

**Interfaces:**
- Produces: `User.external_id`, `Course.external_id`, `Group.external_id` — each `CharField(max_length=64, blank=True, default="")`.

- [ ] **Step 1: Write the failing test**

`integrations/tests/test_external_id.py`:

```python
import pytest

from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_external_id_defaults_blank_and_persists():
    u = UserFactory()
    c = CourseFactory()
    g = GroupFactory()
    assert u.external_id == "" and c.external_id == "" and g.external_id == ""
    u.external_id = "S-123"
    c.external_id = "MATH-A"
    g.external_id = "7B"
    u.save(update_fields=["external_id"])
    c.save(update_fields=["external_id"])
    g.save(update_fields=["external_id"])
    u.refresh_from_db()
    c.refresh_from_db()
    g.refresh_from_db()
    assert u.external_id == "S-123"
    assert c.external_id == "MATH-A"
    assert g.external_id == "7B"
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `uv run pytest integrations/tests/test_external_id.py -v`
Expected: FAIL — `AttributeError: 'User' object has no attribute 'external_id'` (or similar).

- [ ] **Step 3: Add the model fields**

In `accounts/models.py`, add to `class User` (near the other profile fields such as `display_name`):

```python
    external_id = models.CharField(max_length=64, blank=True, default="")
```

In `courses/models.py`, add to `class Course` immediately after the `self_enroll_cohorts` M2M (~line 110):

```python
    external_id = models.CharField(max_length=64, blank=True, default="")
```

In `grouping/models.py`, add to `class Group` (near `name`):

```python
    external_id = models.CharField(max_length=64, blank=True, default="")
```

- [ ] **Step 4: Make the migrations**

Run: `uv run python manage.py makemigrations accounts courses grouping`
Expected: three migrations, each `Add field external_id to <model>`.

- [ ] **Step 5: Run the test, verify it passes**

Run: `uv run pytest integrations/tests/test_external_id.py -v`
Expected: PASS.

- [ ] **Step 6: Sanity-check migrations apply cleanly**

Run: `uv run python manage.py migrate`
Expected: applies the three new migrations with no errors.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts courses grouping integrations/tests/test_external_id.py
git commit -m "feat(integrations): external_id register-key fields on User/Course/Group"
```

---

### Task 3: Surface `external_id` in the three edit forms

**Files:**
- Modify: `courses/forms.py` (`CourseForm.Meta.fields` ~line 61, `labels` ~line 77, `help_texts` ~line 97)
- Modify: `grouping/forms.py` (`GroupForm.Meta.fields` ~line 24)
- Modify: `accounts/forms.py` (`UserEditForm` ~line 69: add field + persist in `save()`)
- Modify: `templates/grouping/group_form.html` (renders fields **explicitly** — must add `external_id`)
- Modify: `templates/accounts/manage/user_form.html` (renders fields **explicitly** — must add `external_id`)
- Create: `integrations/tests/test_form_fields.py`

**Interfaces:**
- Consumes: `User/Course/Group.external_id` (Task 2).
- Produces: all three edit forms accept, persist, **and render** `external_id`.

> **Why the template edits matter:** `course_form.html` renders via
> `{% for field in form.visible_fields %}`, so `external_id` appears automatically —
> but `group_form.html` and `user_form.html` render each field **explicitly**
> (`{{ form.name }}`, `{{ form.display_name }}`, …). Adding `external_id` to those two
> forms without editing their templates ships the field **uneditable**, and the
> `form.save()` tests below would still pass. Steps 6–7 close that gap.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_form_fields.py`:

```python
import pytest

from accounts.forms import UserEditForm
from courses.forms import CourseForm
from grouping.forms import GroupForm
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_course_form_saves_external_id():
    c = CourseFactory()
    form = CourseForm(
        data={
            "title": c.title,
            "slug": c.slug,
            "language": c.language,
            "overview": "",
            "visibility": c.visibility,
            "structure": "flat",
            "external_id": "MATH-A",
            "html_css": "",
            "html_js": "",
        },
        instance=c,
    )
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert c.external_id == "MATH-A"


def test_group_form_saves_external_id():
    g = GroupFactory()
    form = GroupForm(
        data={"name": g.name, "external_id": "7B"}, instance=g
    )
    assert form.is_valid(), form.errors
    form.save()
    g.refresh_from_db()
    assert g.external_id == "7B"


def test_user_edit_form_saves_external_id():
    u = UserFactory()
    form = UserEditForm(
        data={"display_name": u.display_name, "external_id": "S-9"},
        instance=u,
        editing_self=True,
    )
    assert form.is_valid(), form.errors
    form.save()
    u.refresh_from_db()
    assert u.external_id == "S-9"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_form_fields.py -v`
Expected: FAIL — the forms ignore `external_id` (Course/Group assert fails on refreshed value; User form has no such field).

- [ ] **Step 3: Add `external_id` to CourseForm**

In `courses/forms.py`, add `"external_id"` to `Meta.fields` (after `"self_enroll_cohorts"`), and a help text in the `help_texts`/`labels` structure:

```python
        fields = [
            "title", "slug", "subjects", "language", "overview",
            "visibility", "self_enroll_cohorts", "external_id", "owner",
            "html_css", "html_js",
        ]
```

`CourseForm.Meta` already has populated `labels` (lines ~77-88) and `help_texts`
(lines ~97-117) dicts — **add a key to each existing dict, do not replace them** (a
fresh single-key dict would wipe the slug/visibility/html help texts). Add to
`Meta.labels`:

```python
            "external_id": _("Register subject code"),
```

Add to `Meta.help_texts`:

```python
            "external_id": _(
                "Subject code in your external register; leave blank to disable "
                "result sync for this course."
            ),
```

(The `_()` label is required — every other CourseForm field has one; without it the
field renders an untranslated auto-derived "External id" that stays English under PL.)

- [ ] **Step 4: Add `external_id` to GroupForm**

In `grouping/forms.py`, extend `Meta.fields` and `labels`:

```python
        fields = ["name", "course", "teachers", "external_id"]
        widgets = {"teachers": forms.CheckboxSelectMultiple}
        labels = {
            "name": _("Name"),
            "course": _("Course"),
            "teachers": _("Teachers"),
            "external_id": _("Register class code"),
        }
        help_texts = {"external_id": _("Class code in your external register.")}
```

- [ ] **Step 5: Add the manual `external_id` field to UserEditForm**

In `accounts/forms.py`, inside `class UserEditForm` add the field declaration alongside the others:

```python
    external_id = forms.CharField(
        max_length=64,
        required=False,
        label=_("Register student id"),
        help_text=_("Student number in your external register."),
    )
```

In `__init__`, seed its initial from the instance. **Placement matters:** `self.fields`
does not exist until `super().__init__(...)` runs (~line 86), so this line must go
**after** `super().__init__()` — put it alongside the existing post-super field setup
(e.g. next to the `self.fields["role"].choices = …` line), NOT after the
`self.instance = instance` assignment (~line 84, which precedes `super().__init__` and
would raise `KeyError`/`AttributeError`):

```python
        self.fields["external_id"].initial = self.instance.external_id
```

In `save()`, persist it inside the existing `with transaction.atomic():` block, extending the `update_fields`:

```python
            user.display_name = self.cleaned_data.get("display_name", "")
            user.email = new_email
            user.external_id = self.cleaned_data.get("external_id", "")
            user.save(update_fields=["display_name", "email", "external_id"])
```

- [ ] **Step 6: Render `external_id` in `group_form.html`**

Open `templates/grouping/group_form.html`. It renders fields explicitly (e.g.
`{{ form.name }}`, `{{ form.teachers }}` each wrapped in the form's field markup).
Add an `external_id` field block **matching the sibling field markup exactly** — copy
the wrapper of an adjacent text field (e.g. the `name` field's `<div>`/label/error
structure) and swap in `external_id`:

```html
<div class="form-row">
  <label for="{{ form.external_id.id_for_label }}">{{ form.external_id.label }}</label>
  {{ form.external_id }}
  {% if form.external_id.help_text %}<p class="form-help">{{ form.external_id.help_text }}</p>{% endif %}
  {% if form.external_id.errors %}<p class="form-error">{{ form.external_id.errors }}</p>{% endif %}
</div>
```

Use the **actual** wrapper class names from that template (they may be `.manage__field`,
`.form-row`, etc.) — mirror the `name` field's block rather than the placeholder classes above.

- [ ] **Step 7: Render `external_id` in `user_form.html`**

Open `templates/accounts/manage/user_form.html`. It renders `{{ form.display_name }}`,
`{{ form.email }}`, `{{ form.role }}` explicitly. Add an `external_id` block mirroring
the `display_name` field's wrapper markup (same pattern as Step 6, swapping the field
name and the template's real wrapper classes).

- [ ] **Step 8: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_form_fields.py -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Regression-check the touched apps**

Run: `uv run pytest accounts courses grouping -q`
Expected: PASS (no existing form/view tests broken).

- [ ] **Step 10: Visual check the rendered fields (light + dark)**

Launch the app (`uv run python manage.py runserver`), log in as a PA, and confirm the
`external_id` field renders (labeled, styled) on: the course settings/edit form, a
group edit form, and a `/manage/people/` user edit form — in both light and dark
themes. This is the guard that catches the "field added to form but not to template"
gap that `form.save()` tests miss. (A throwaway Playwright screenshot harness is fine;
delete it after.)

- [ ] **Step 11: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts courses grouping templates/grouping/group_form.html templates/accounts/manage/user_form.html integrations/tests/test_form_fields.py
git commit -m "feat(integrations): edit external_id on course/group/user forms + templates"
```

---

### Task 4: Payload builder + emit gate + per-group fan-out (no supersede yet)

**Files:**
- Create: `integrations/services.py`
- Create: `integrations/tests/test_emit.py`

**Interfaces:**
- Consumes: `WebhookDelivery` (Task 1); `external_id` fields (Task 2); `courses.review.submission_review_state`; `courses.quiz.compute_scores` (already populates `submission.score`/`max_score`); `grouping.models.Group`.
- Produces: `integrations.services.emit_result_finalized(submission, *, already_final=False) -> None`; `integrations.services.dedupe_key(submission_pk, group) -> str`; `integrations.services.build_payload(submission, course, group) -> dict`.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_emit.py`:

```python
from decimal import Decimal

import pytest
from django.db import transaction

from grouping.models import GroupMembership
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from integrations.services import emit_result_finalized
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory

pytestmark = pytest.mark.django_db


def _enable_endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled = True
    ep.url = "https://register.example/hook"
    ep.secret = "shh"
    ep.save()


def _finalized_submission(course_external_id="MATH-A"):
    """A SUBMITTED, auto-marked (no [R]) submission with a scored result."""
    sub = QuizSubmissionFactory(
        status="submitted", score=Decimal("8.00"), max_score=Decimal("10.00")
    )
    course = sub.unit.course
    course.external_id = course_external_id
    course.save(update_fields=["external_id"])
    return sub


def test_no_endpoint_configured_is_noop():
    sub = _finalized_submission()  # endpoint row absent / disabled
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    assert WebhookDelivery.objects.count() == 0


def test_course_without_external_id_is_noop():
    _enable_endpoint()
    sub = _finalized_submission(course_external_id="")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    assert WebhookDelivery.objects.count() == 0


def test_no_group_yields_one_null_group_delivery():
    _enable_endpoint()
    sub = _finalized_submission()
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 1
    assert rows[0].payload["group"] is None
    assert rows[0].dedupe_key == f"{sub.pk}:"


def test_payload_shape_and_score():
    _enable_endpoint()
    sub = _finalized_submission()
    student = sub.student
    student.external_id = "S-123"
    student.save(update_fields=["external_id"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    p = WebhookDelivery.objects.get().payload
    assert p["event"] == "result_finalized"
    assert p["student"]["external_id"] == "S-123"
    assert p["course"]["external_id"] == "MATH-A"
    assert p["unit"]["id"] == sub.unit_id
    assert p["score"] == {"earned": "8.00", "max": "10.00", "percent": 80.0}
    assert "T" in p["finalized_at"]  # ISO-8601


def test_fanout_two_groups_blank_external_id_both_survive():
    _enable_endpoint()
    sub = _finalized_submission()
    course = sub.unit.course
    g1 = GroupFactory(course=course)  # external_id blank (default)
    g2 = GroupFactory(course=course)
    GroupMembership.objects.create(group=g1, student=sub.student)
    GroupMembership.objects.create(group=g2, student=sub.student)
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 2  # keyed on group_id, not blank external_id
    keys = {r.dedupe_key for r in rows}
    assert keys == {f"{sub.pk}:{g1.pk}", f"{sub.pk}:{g2.pk}"}
    ids = {r.payload["group"]["id"] for r in rows}
    assert ids == {g1.pk, g2.pk}


def test_archived_group_excluded():
    _enable_endpoint()
    sub = _finalized_submission()
    course = sub.unit.course
    live = GroupFactory(course=course)
    archived = GroupFactory(course=course, archived=True)
    GroupMembership.objects.create(group=live, student=sub.student)
    GroupMembership.objects.create(group=archived, student=sub.student)
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 1
    assert rows[0].payload["group"]["id"] == live.pk
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_emit.py -v`
Expected: FAIL — `ImportError: cannot import name 'emit_result_finalized'`.

- [ ] **Step 3: Write `services.py` (gate + fan-out + payload; direct create, supersede added in Task 5)**

`integrations/services.py`:

```python
"""Outbound grade-sync: the emit choke-point. Called INSIDE the caller's
transaction.atomic() block via a function-local import (the emit sites import
from courses/grouping, so a top-level import here would cycle)."""

from django.utils import timezone

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint


def dedupe_key(submission_pk, group):
    """Delivery identity: submission (pins student+unit+course) + the stable
    Group.pk (NOT the blankable external_id — two unmapped groups must not
    collide). Empty group segment for the no-group delivery."""
    return f"{submission_pk}:{group.pk if group is not None else ''}"


def _percent(earned, maximum):
    if not maximum:
        return 0
    return round(float(earned) / float(maximum) * 100, 2)


def build_payload(submission, course, group):
    student = submission.student
    unit = submission.unit
    return {
        "event": WebhookDelivery.Event.RESULT_FINALIZED.value,
        "finalized_at": timezone.now().isoformat(),
        "student": {
            "external_id": student.external_id,
            "email": student.email or "",
            "name": student.display_name or student.username,
        },
        "course": {
            "external_id": course.external_id,
            "slug": course.slug,
            "title": course.title,
        },
        "group": (
            None
            if group is None
            else {"id": group.pk, "external_id": group.external_id, "name": group.name}
        ),
        "unit": {"id": unit.pk, "title": unit.title},
        "score": {
            "earned": str(submission.score),
            "max": str(submission.max_score),
            "percent": _percent(submission.score, submission.max_score),
        },
    }


def _student_groups(course, student):
    from grouping.models import Group

    return list(
        Group.objects.filter(
            course=course, archived=False, memberships__student=student
        ).distinct()
    )


def emit_result_finalized(submission, *, already_final=False):
    """Enqueue outbox deliveries for a finalized quiz result. No-op unless the
    endpoint is enabled AND the course has a subject code. Call inside the
    caller's atomic() block. `already_final=True` (review-completion path) skips
    the auto-final check; the submit paths pass False and this checks it."""
    endpoint = WebhookEndpoint.objects.filter(pk=1).first()
    if endpoint is None or not endpoint.enabled:
        return
    course = submission.unit.course
    if not course.external_id:
        return
    if not already_final:
        from courses.review import submission_review_state

        if submission_review_state(submission)["total"] != 0:
            return  # has [R] questions → not final at submit time
    assert submission.score is not None and submission.max_score is not None, (
        "emit_result_finalized called before score/max_score were populated"
    )
    groups = _student_groups(course, submission.student) or [None]
    for group in groups:
        _enqueue(submission, course, group)


def _enqueue(submission, course, group):
    WebhookDelivery.objects.create(
        dedupe_key=dedupe_key(submission.pk, group),
        payload=build_payload(submission, course, group),
    )
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_emit.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations/services.py integrations/tests/test_emit.py
git commit -m "feat(integrations): emit_result_finalized gate + fan-out + payload"
```

---

### Task 5: Emit-time supersede of prior pending deliveries

**Files:**
- Modify: `integrations/services.py` (`_enqueue`)
- Create: `integrations/tests/test_supersede.py`

**Interfaces:**
- Consumes: `emit_result_finalized`, `dedupe_key` (Task 4).
- Produces: `_enqueue` now retires same-`dedupe_key` `PENDING` rows to `SUPERSEDED` (via `select_for_update(skip_locked=True)`) before creating the new row.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_supersede.py`:

```python
from decimal import Decimal

import pytest
from django.db import transaction

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from integrations.services import emit_result_finalized
from tests.factories import QuizSubmissionFactory

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def _sub(score="8.00"):
    sub = QuizSubmissionFactory(
        status="submitted", score=Decimal(score), max_score=Decimal("10.00")
    )
    c = sub.unit.course
    c.external_id = "MATH-A"
    c.save(update_fields=["external_id"])
    return sub


def test_correction_supersedes_prior_pending():
    _enable()
    sub = _sub("8.00")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    sub.score = Decimal("9.00")
    sub.save(update_fields=["score"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.order_by("id"))
    assert len(rows) == 2
    assert rows[0].status == WebhookDelivery.Status.SUPERSEDED
    assert rows[1].status == WebhookDelivery.Status.PENDING
    assert rows[1].payload["score"]["earned"] == "9.00"


def test_delivered_row_is_not_superseded():
    _enable()
    sub = _sub("8.00")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    first = WebhookDelivery.objects.get()
    first.status = WebhookDelivery.Status.DELIVERED
    first.save(update_fields=["status"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    first.refresh_from_db()
    assert first.status == WebhookDelivery.Status.DELIVERED  # untouched
    assert WebhookDelivery.objects.filter(
        status=WebhookDelivery.Status.PENDING
    ).count() == 1
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_supersede.py -v`
Expected: FAIL — `test_correction_supersedes_prior_pending` finds both rows still `PENDING`.

- [ ] **Step 3: Add supersede to `_enqueue`**

In `integrations/services.py`, replace `_enqueue` with:

```python
def _enqueue(submission, course, group):
    key = dedupe_key(submission.pk, group)
    # Retire not-yet-sent earlier deliveries for the same identity. skip_locked
    # so this never blocks on a row the flusher currently holds mid-POST; that
    # in-flight older row then sends and the receiver reconciles via finalized_at.
    stale_ids = list(
        WebhookDelivery.objects.select_for_update(skip_locked=True)
        .filter(dedupe_key=key, status=WebhookDelivery.Status.PENDING)
        .values_list("pk", flat=True)
    )
    if stale_ids:
        WebhookDelivery.objects.filter(pk__in=stale_ids).update(
            status=WebhookDelivery.Status.SUPERSEDED
        )
    WebhookDelivery.objects.create(
        dedupe_key=key,
        payload=build_payload(submission, course, group),
    )
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_supersede.py integrations/tests/test_emit.py -v`
Expected: PASS (all — fan-out still yields distinct keys so no self-supersede).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations/services.py integrations/tests/test_supersede.py
git commit -m "feat(integrations): emit-time supersede of prior pending deliveries"
```

---

### Task 6: Wire emit at the auto-final sites (quiz_finish + force_submit_quiz)

**Files:**
- Modify: `courses/views.py::quiz_finish` (~line 631, inside the `if submission.status != SUBMITTED:` branch)
- Modify: `courses/review.py::force_submit_quiz` (~line 88, after `finalize_submission(locked.unit, locked)`)
- Create: `integrations/tests/test_wire_autofinal.py`

**Interfaces:**
- Consumes: `emit_result_finalized` (Tasks 4–5).
- Produces: auto-graded self-finish and force-submit enqueue one delivery each; a review-required quiz does not.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_wire_autofinal.py`:

```python
import pytest

from courses.review import force_submit_quiz
from courses.models import QuizSubmission
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import make_quiz_unit
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def test_force_submit_autograded_enqueues_from_locked_instance():
    """force_submit passes the finalized `locked` row, not the un-finalized
    parameter — so score/max_score are non-null and the enqueue succeeds."""
    _enable()
    unit = make_quiz_unit()  # no [R] questions → auto-final on submit
    unit.course.external_id = "MATH-A"
    unit.course.save(update_fields=["external_id"])
    student = UserFactory()
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS
    )
    teacher = UserFactory()
    force_submit_quiz(sub, by=teacher)
    assert WebhookDelivery.objects.count() == 1
    row = WebhookDelivery.objects.get()
    assert row.payload["score"]["earned"] is not None


def test_quiz_finish_enqueues_once_and_rehit_does_not_duplicate(client):
    """Student self-finish of an auto-graded quiz emits exactly one delivery; a
    second POST to the finish URL (already SUBMITTED) does NOT re-emit — proving
    the emit sits inside the `status != SUBMITTED` guard, not merely in atomic()."""
    _enable()
    unit = make_quiz_unit()  # no [R] questions → auto-final
    course = unit.course
    course.external_id = "MATH-A"
    course.save(update_fields=["external_id"])
    student = _enrolled_student(client, course)  # see note
    url = reverse("courses:quiz_finish", kwargs={"slug": course.slug, "node_pk": unit.pk})
    client.post(url)
    assert WebhookDelivery.objects.count() == 1
    client.post(url)  # re-hit: submission already SUBMITTED
    assert WebhookDelivery.objects.count() == 1  # no duplicate
```

Add `from django.urls import reverse` to the test imports.

> **Note for the implementer:** `make_quiz_unit()` builds a quiz with no review-required questions, so `submission_review_state(...)["total"] == 0` and the submission is auto-final. If the factory's default already includes an `[R]` question, seed a plain auto-marked question instead so the auto-final path holds.
>
> `_enrolled_student(client, course)` is a small local helper you write in this test module: create a user, enrol them in `course` (mirror how the existing `courses` quiz-flow tests set up an enrolled student who can hit `quiz_finish` — grep `courses/tests/` for the current enrolment + `make_login`/force-login pattern and reuse it), log the client in as them, and return the user. If wiring a real client POST proves heavy, an acceptable fallback is to call the `quiz_finish` **view function** directly with a `RequestFactory` request whose `.user` is the enrolled student — but keep the two-POST assertion (the status-guard regression is the point of this test).

- [ ] **Step 2: Run the test, verify it fails**

Run: `uv run pytest integrations/tests/test_wire_autofinal.py -v`
Expected: FAIL — `WebhookDelivery.objects.count() == 0` (no wiring yet).

- [ ] **Step 3: Wire `quiz_finish`**

In `courses/views.py`, inside `quiz_finish`, within the existing `if submission.status != QuizSubmission.Status.SUBMITTED:` block, right after the existing `notify_needs_review(submission, actor=request.user)` line:

```python
            from integrations.services import emit_result_finalized

            emit_result_finalized(submission)
```

(The `submission` here is the finalized object — `finalize_submission` mutated it in place. `emit_result_finalized` runs its own gate + auto-final check, so this is a no-op unless the webhook is enabled and the quiz is auto-final.)

- [ ] **Step 4: Wire `force_submit_quiz`**

In `courses/review.py::force_submit_quiz`, after `notify_needs_review(locked, actor=by)` (inside the same `atomic()`), add — passing **`locked`**, the finalized instance:

```python
        from integrations.services import emit_result_finalized

        emit_result_finalized(locked)
```

- [ ] **Step 5: Run the test, verify it passes**

Run: `uv run pytest integrations/tests/test_wire_autofinal.py -v`
Expected: PASS.

- [ ] **Step 6: Regression-check the quiz flow**

Run: `uv run pytest courses -q`
Expected: PASS (existing quiz-finish/force-submit tests unaffected — emit is gated off by default).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add courses integrations/tests/test_wire_autofinal.py
git commit -m "feat(integrations): emit result_finalized at quiz_finish + force_submit"
```

---

### Task 7: Wire emit at review completion + correction (review_response)

**Files:**
- Modify: `courses/review.py::review_response` (~lines 34–65, inside the `with transaction.atomic():` / lock block)
- Create: `integrations/tests/test_wire_review.py`

**Interfaces:**
- Consumes: `emit_result_finalized(..., already_final=True)`.
- Produces: emit fires on the `not_fully → fully_reviewed` transition and on a post-completion score change; **not** on a feedback-only re-grade or a no-op re-save.

- [ ] **Step 1: Read the current `review_response` to capture the pre-save score under the lock**

Open `courses/review.py`. Note line 37 already does `submission.__class__.objects.select_for_update().get(pk=submission.pk)` but **discards** the result, and line 38 computes `was_fully`. You will capture the pre-save score off the freshly-locked row.

- [ ] **Step 2: Write the failing tests**

`integrations/tests/test_wire_review.py`:

```python
from decimal import Decimal

import pytest

from courses.review import review_response
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import make_review_submission  # see note below
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def test_completion_enqueues_and_recorrection_re_pushes():
    _enable()
    ctx = make_review_submission(course_external_id="MATH-A")  # 1 [R] question
    reviewer = ctx["reviewer"]
    element = ctx["review_element"]
    submission = ctx["submission"]
    # Complete the review → completion transition emits once.
    review_response(
        submission=submission, element=element,
        earned_marks=Decimal("3.00"), feedback="ok", reviewer=reviewer,
    )
    assert WebhookDelivery.objects.filter(
        status=WebhookDelivery.Status.PENDING
    ).count() == 1
    # A correction that changes the score re-pushes (supersede + new).
    review_response(
        submission=submission, element=element,
        earned_marks=Decimal("2.00"), feedback="revised", reviewer=reviewer,
    )
    pending = WebhookDelivery.objects.filter(status=WebhookDelivery.Status.PENDING)
    assert pending.count() == 1
    assert pending.get().payload["score"]["earned"] != "3.00"


def test_feedback_only_correction_does_not_re_push():
    _enable()
    ctx = make_review_submission(course_external_id="MATH-A")
    reviewer, element, submission = ctx["reviewer"], ctx["review_element"], ctx["submission"]
    review_response(
        submission=submission, element=element,
        earned_marks=Decimal("3.00"), feedback="ok", reviewer=reviewer,
    )
    before = WebhookDelivery.objects.count()
    # Same marks, different feedback → score unchanged → no new delivery.
    review_response(
        submission=submission, element=element,
        earned_marks=Decimal("3.00"), feedback="typo fixed", reviewer=reviewer,
    )
    assert WebhookDelivery.objects.count() == before
```

> **Note for the implementer — build `make_review_submission` concretely.** Two tests
> depend on it, and `review_response` asserts `earned_marks <= question.max_marks`
> (`courses/review.py:32`). The tests pass `earned_marks=Decimal("3.00")`, so the
> question's `max_marks` **must be ≥ 3** or that bounds `assert` fires and both tests
> fail confusingly. Add the helper to `tests/factories.py` (or the test module) with:
>
> 1. A quiz unit (`ContentNode`, kind `unit`, quiz) on a fresh course; set
>    `course.external_id` from the `course_external_id` kwarg.
> 2. Exactly **one** `[R]` (`MarkingMode.REVIEW`) `QuestionElement` with
>    **`max_marks = Decimal("5.00")`** (≥ 3), plus its `Element` join-row on the unit.
> 3. A `QuizSubmission` (status `SUBMITTED`) for a student on that unit, with an
>    **unreviewed** `QuestionResponse` for the `[R]` element (so
>    `submission_review_state` reports `total=1, fully_reviewed=False` before review).
> 4. A `reviewer` user granted review scope over the course (mirror how the existing
>    Phase 3c-i review tests grant reviewer scope — grep `courses/tests/` /
>    `integrations`-sibling tests for the `[R]`-question + reviewer setup and reuse it
>    rather than inventing new plumbing).
> 5. `return {"submission": …, "review_element": <the Element join-row>, "reviewer": …}`
>    — note the tests pass `element=ctx["review_element"]` to `review_response`, which
>    expects the **`Element`** row (its `.content_object` is the `QuestionElement`),
>    matching the real signature.

- [ ] **Step 3: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_wire_review.py -v`
Expected: FAIL — no deliveries created (emit not wired).

- [ ] **Step 4: Wire `review_response`**

In `courses/review.py::review_response`, inside the `with transaction.atomic():` block, capture the pre-save score from the freshly-locked row. Change the discarded lock line to bind it:

```python
        locked = submission.__class__.objects.select_for_update().get(pk=submission.pk)
        was_fully = submission_review_state(submission)["fully_reviewed"]
        prev_score = locked.score  # pre-save score, read under the lock (M2)
```

Then, after the existing recompute + `submission.save()` and the existing `notify_graded` block, add the emit — firing on completion transition OR a post-completion score change:

```python
        now_fully = submission_review_state(submission)["fully_reviewed"]
        completed = not was_fully and now_fully
        corrected = was_fully and now_fully and submission.score != prev_score
        if completed or corrected:
            from integrations.services import emit_result_finalized

            emit_result_finalized(submission, already_final=True)
```

(If the existing code already computes `submission_review_state(submission)["fully_reviewed"]` for the `notify_graded` guard, reuse that value instead of recomputing — do not add a redundant query.)

- [ ] **Step 5: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_wire_review.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Regression-check review flow**

Run: `uv run pytest courses -q`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add courses integrations/tests/test_wire_review.py tests/factories.py
git commit -m "feat(integrations): emit result_finalized on review completion + correction"
```

---

### Task 8: Delivery primitive — sign, opener, POST, outcome/backoff

**Files:**
- Create: `integrations/delivery.py`
- Create: `integrations/tests/test_delivery.py`

**Interfaces:**
- Consumes: `WebhookEndpoint`, `WebhookDelivery` (Task 1).
- Produces: `integrations.delivery.deliver_one(delivery, endpoint) -> None` (mutates + saves the row to `delivered`/`pending`+rescheduled/`dead`); module constants `BACKOFF = [1, 5, 15, 60, 180, 360, 720]`, `MAX_ATTEMPTS = 8`; `integrations.delivery.sign(secret: str, body: bytes) -> str` returning `"sha256=<hex>"`; `integrations.delivery._build_opener()`.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_delivery.py`:

```python
import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.utils import timezone

from integrations import delivery
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def _endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/hook", "topsecret"
    ep.save()
    return ep


def _row():
    return WebhookDelivery.objects.create(dedupe_key="1:", payload={"event": "x"})


def test_sign_prefixes_and_matches():
    sig = delivery.sign("topsecret", b'{"a":1}')
    expected = hmac.new(b"topsecret", b'{"a":1}', hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


def test_deliver_success_marks_delivered():
    ep = _endpoint()
    row = _row()
    resp = mock.MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: resp
    resp.__exit__ = lambda *a: False
    opener = mock.MagicMock()
    opener.open.return_value = resp
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.DELIVERED
    assert row.delivered_at is not None
    # signature header computed over the exact bytes sent
    sent_req = opener.open.call_args.args[0]
    body = sent_req.data
    assert sent_req.headers["X-libli-signature"] == delivery.sign(ep.secret, body)


def test_deliver_failure_reschedules_by_backoff():
    import urllib.error

    ep = _endpoint()
    row = _row()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    before = timezone.now()
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.PENDING
    assert row.attempts == 1
    assert row.last_error
    # first failure → BACKOFF[0] == 1 minute out
    assert (row.next_attempt_at - before).total_seconds() >= 55


def test_deliver_dead_after_max_attempts():
    import urllib.error

    ep = _endpoint()
    row = _row()
    row.attempts = delivery.MAX_ATTEMPTS - 1  # this failure is the 8th
    row.save(update_fields=["attempts"])
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.DEAD
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.delivery'`.

- [ ] **Step 3: Write `delivery.py`**

`integrations/delivery.py`:

```python
"""Send one WebhookDelivery: sign, POST via stdlib urllib, record outcome with
exponential backoff. No new dependency; no redirects (SSRF); 4xx/5xx raise."""

import hashlib
import hmac
import json
import logging
import socket
import urllib.error
import urllib.request
from datetime import timedelta

from django.utils import timezone

from integrations.models import WebhookDelivery

logger = logging.getLogger(__name__)

BACKOFF = [1, 5, 15, 60, 180, 360, 720]  # minutes; index by (attempts-1), clamped
MAX_ATTEMPTS = 8
TIMEOUT_SECONDS = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _build_opener():
    # build_opener keeps HTTPErrorProcessor (so 4xx/5xx raise HTTPError); we only
    # swap the redirect handler for one that refuses redirects.
    return urllib.request.build_opener(_NoRedirect)


def sign(secret, body):
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _schedule(attempts):
    return BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]


def deliver_one(delivery, endpoint):
    body = json.dumps(delivery.payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Libli-Event": delivery.event,
            "X-Libli-Delivery": str(delivery.pk),
            "X-Libli-Signature": sign(endpoint.secret, body),
        },
    )
    try:
        opener = _build_opener()
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
        if not (200 <= status < 300):
            raise urllib.error.HTTPError(endpoint.url, status, "non-2xx", None, None)
    except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout) as exc:
        _record_failure(delivery, exc)
        return
    delivery.status = WebhookDelivery.Status.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "delivered_at", "last_error"])


def _record_failure(delivery, exc):
    delivery.attempts += 1
    delivery.last_error = f"{type(exc).__name__}: {exc}"[:2000]
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.DEAD
    else:
        delivery.next_attempt_at = timezone.now() + timedelta(
            minutes=_schedule(delivery.attempts)
        )
    delivery.save(
        update_fields=["attempts", "last_error", "status", "next_attempt_at"]
    )
    logger.warning("webhook delivery %s failed: %s", delivery.pk, delivery.last_error)
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_delivery.py -v`
Expected: PASS (4 tests).

> If `test_deliver_success` fails on `sent_req.headers` casing, note Django/urllib title-cases header keys (`X-Libli-Signature` → `X-libli-signature`); assert with the title-cased key as shown.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations/delivery.py integrations/tests/test_delivery.py
git commit -m "feat(integrations): deliver_one send primitive (HMAC, no-redirect, backoff)"
```

---

### Task 9: `flush_webhooks` management command

**Files:**
- Create: `integrations/management/__init__.py` (empty), `integrations/management/commands/__init__.py` (empty), `integrations/management/commands/flush_webhooks.py`
- Create: `integrations/flush.py` (the loop logic, so the command stays thin)
- Create: `integrations/tests/test_flush.py`

**Interfaces:**
- Consumes: `deliver_one` (Task 8), `WebhookEndpoint`, `WebhookDelivery`.
- Produces: `integrations.flush.flush_pending(limit=100) -> dict` (counts) processing due `PENDING` rows in per-row `skip_locked` transactions; the `flush_webhooks` command wraps it.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_flush.py`:

```python
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from integrations import flush
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def _pending(**kw):
    return WebhookDelivery.objects.create(dedupe_key="1:", payload={"e": "x"}, **kw)


def test_flush_noop_when_disabled():
    _pending()  # endpoint absent/disabled
    result = flush.flush_pending()
    assert result["sent"] == 0
    assert WebhookDelivery.objects.get().status == WebhookDelivery.Status.PENDING


def test_flush_sends_only_due_rows():
    _enable()
    due = _pending()
    _pending(next_attempt_at=timezone.now() + timedelta(hours=1))  # future

    def fake_deliver(row, endpoint):
        row.status = WebhookDelivery.Status.DELIVERED
        row.save(update_fields=["status"])

    with mock.patch.object(flush, "deliver_one", side_effect=fake_deliver) as m:
        flush.flush_pending()
    assert m.call_count == 1
    due.refresh_from_db()
    assert due.status == WebhookDelivery.Status.DELIVERED


def test_flush_respects_limit():
    _enable()
    for _ in range(3):
        _pending()
    with mock.patch.object(flush, "deliver_one") as m:
        flush.flush_pending(limit=2)
    assert m.call_count == 2
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_flush.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.flush'`.

- [ ] **Step 3: Write `flush.py`**

`integrations/flush.py`:

```python
"""Flush loop: select candidate ids first (no long lock), then process each in
its own short skip_locked transaction so a slow POST never holds locks across
unrelated rows."""

from django.db import transaction
from django.utils import timezone

from integrations.delivery import deliver_one
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint


def flush_pending(limit=100):
    endpoint = WebhookEndpoint.objects.filter(pk=1).first()
    if endpoint is None or not endpoint.enabled or not endpoint.url:
        return {"sent": 0, "skipped": 0}
    ids = list(
        WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.PENDING,
            next_attempt_at__lte=timezone.now(),
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    sent = skipped = 0
    for pk in ids:
        with transaction.atomic():
            row = (
                WebhookDelivery.objects.select_for_update(skip_locked=True)
                .filter(pk=pk, status=WebhookDelivery.Status.PENDING)
                .first()
            )
            if row is None:  # taken by a concurrent run, or superseded
                skipped += 1
                continue
            deliver_one(row, endpoint)
            sent += 1
    return {"sent": sent, "skipped": skipped}
```

- [ ] **Step 4: Write the command**

`integrations/management/__init__.py` — empty. `integrations/management/commands/__init__.py` — empty.

`integrations/management/commands/flush_webhooks.py`:

```python
from django.core.management.base import BaseCommand

from integrations.flush import flush_pending


class Command(BaseCommand):
    help = "POST pending result-finalized webhook deliveries to the register."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = flush_pending(limit=options["limit"])
        self.stdout.write(
            f"webhooks flushed: sent={result['sent']} skipped={result['skipped']}"
        )
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_flush.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Smoke-test the command**

Run: `uv run python manage.py flush_webhooks --limit 5`
Expected: prints `webhooks flushed: sent=0 skipped=0` (no endpoint configured on a fresh DB).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations/flush.py integrations/management integrations/tests/test_flush.py
git commit -m "feat(integrations): flush_webhooks command (per-row skip_locked loop)"
```

---

### Task 10: `IntegrationsForm` (endpoint config + secret discipline)

**Files:**
- Create: `integrations/forms.py`
- Create: `integrations/tests/test_form.py`

**Interfaces:**
- Consumes: `WebhookEndpoint` (Task 1).
- Produces: `integrations.forms.IntegrationsForm` (ModelForm over `WebhookEndpoint`, fields `enabled`, `url`, `secret`) with: http/https-only `url`; `url` + `secret` required when `enabled`; blank `secret` preserves the stored value; a `http`-scheme cleartext warning surfaced as a non-field message.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_form.py`:

```python
import pytest

from integrations.forms import IntegrationsForm
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def test_enable_requires_url_and_secret():
    ep = WebhookEndpoint.load()
    form = IntegrationsForm(
        data={"enabled": True, "url": "", "secret": ""}, instance=ep
    )
    assert not form.is_valid()


def test_rejects_non_http_scheme():
    ep = WebhookEndpoint.load()
    form = IntegrationsForm(
        data={"enabled": True, "url": "ftp://x/y", "secret": "s"}, instance=ep
    )
    assert not form.is_valid()
    assert "url" in form.errors


def test_blank_secret_preserves_existing():
    ep = WebhookEndpoint.load()
    ep.secret = "keepme"
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": ""},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == "keepme"


def test_new_secret_replaces():
    ep = WebhookEndpoint.load()
    ep.secret = "old"
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": "new"},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == "new"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_form.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.forms'`.

- [ ] **Step 3: Write `forms.py`**

Key subtlety captured below: `secret` must be preserved on a blank submit, but by the time `save()` runs, `ModelForm._post_clean` has already copied the blank `cleaned_data["secret"]` onto `self.instance`. So capture the **original** secret in `__init__` (before binding overwrites it) and restore from that. The `http` scheme is a **warning**, not a hard error — it is surfaced via `messages.warning` in the view (Task 11), NOT here; this form only rejects non-`http`/`https` schemes.

`integrations/forms.py`:

```python
from urllib.parse import urlparse

from django import forms
from django.utils.translation import gettext_lazy as _

from integrations.models import WebhookEndpoint


class IntegrationsForm(forms.ModelForm):
    # required=False + preserve-on-blank: a blank submit keeps the stored secret.
    secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label=_("Signing secret"),
        help_text=_("Leave blank to keep the current secret."),
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["enabled", "url", "secret"]
        labels = {"enabled": _("Enable result sync"), "url": _("Endpoint URL")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot the stored secret BEFORE _post_clean overwrites self.instance.
        self._existing_secret = self.instance.secret

    def clean_url(self):
        url = self.cleaned_data.get("url", "")
        if url and urlparse(url).scheme not in ("http", "https"):
            raise forms.ValidationError(_("URL must use http or https."))
        return url

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        url = cleaned.get("url")
        has_secret = bool(cleaned.get("secret")) or bool(self._existing_secret)
        if enabled and not url:
            self.add_error("url", _("A URL is required to enable result sync."))
        if enabled and not has_secret:
            self.add_error(
                "secret", _("A signing secret is required to enable result sync.")
            )
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not self.cleaned_data.get("secret"):
            obj.secret = self._existing_secret  # preserve when blank
        if commit:
            obj.save()
        return obj
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_form.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add integrations/forms.py integrations/tests/test_form.py
git commit -m "feat(integrations): IntegrationsForm with scheme + enable-guards + secret preserve"
```

---

### Task 11: Integrations settings tab (view + template + recent-deliveries panel)

**Files:**
- Modify: `institution/views_manage.py` (`TABS` line 23; `_settings_context` lines 31–66; add `settings_integrations` view + import `IntegrationsForm` and `WebhookEndpoint`)
- Modify: `institution/urls.py` (add the POST route)
- Create: `templates/institution/manage/_integrations_tab.html`
- Modify: `templates/institution/manage/settings.html` (include the new partial + add the tab to the tab nav)
- Create: `integrations/tests/test_settings_tab.py`

**Interfaces:**
- Consumes: `IntegrationsForm` (Task 10), `WebhookEndpoint`/`WebhookDelivery` (Task 1).
- Produces: `GET /manage/settings/?tab=integrations` renders the config form + last-20 deliveries panel (PA-only); `POST institution:settings_integrations` saves the endpoint.

- [ ] **Step 1: Write the failing tests**

`integrations/tests/test_settings_tab.py`:

```python
import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_integrations_tab_renders_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=integrations")
    assert resp.status_code == 200
    # the config form action is present (tab panel rendered)
    assert reverse("institution:settings_integrations").encode() in resp.content
    # the nav entry is present (tab reachable), not just the panel
    assert b"?tab=integrations" in resp.content


def test_non_pa_cannot_post(client):
    make_login(client, "joe")  # ordinary user
    resp = client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "", "url": "", "secret": ""},
    )
    assert resp.status_code in (302, 403)
    assert WebhookEndpoint.objects.filter(enabled=True).count() == 0


def test_pa_saves_endpoint(client):
    make_pa(client, "pa")
    resp = client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "on", "url": "https://r.example/h", "secret": "shh"},
    )
    assert resp.status_code == 302
    ep = WebhookEndpoint.load()
    assert ep.enabled is True
    assert ep.url == "https://r.example/h"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `uv run pytest integrations/tests/test_settings_tab.py -v`
Expected: FAIL — `NoReverseMatch: 'settings_integrations'`.

- [ ] **Step 3: Add the tab to the view layer**

In `institution/views_manage.py`:

Add to imports:

```python
from integrations.forms import IntegrationsForm
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
```

Extend `TABS`:

```python
TABS = ("branding", "access", "uploads", "sso", "notifications", "integrations")
```

In `_settings_context`, add an `integrations=None` kwarg and include the form in the
returned dict. **Gate the deliveries query to the integrations tab (M3)** so the other
five tabs don't issue a `WebhookDelivery` query they never render — `_settings_context`
runs on every settings render:

```python
        "integrations": integrations or IntegrationsForm(instance=WebhookEndpoint.load()),
        "recent_deliveries": (
            WebhookDelivery.objects.all()[:20] if active_tab == "integrations" else []
        ),
```

(Use whatever the function's active-tab parameter is actually named — it is the `tab`/
`active_tab` argument already threaded into `_settings_context`; match the existing name.)

Add the POST view (mirrors the other per-tab views but binds `WebhookEndpoint.load()`, not `Institution`, and adds the http cleartext warning):

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_integrations(request):
    if request.method == "GET":
        return redirect(_index_url("integrations"))
    endpoint = WebhookEndpoint.load()
    form = IntegrationsForm(request.POST, instance=endpoint)
    if form.is_valid():
        obj = form.save()
        if obj.url.startswith("http://"):
            messages.warning(
                request,
                _("Endpoint uses http — grades transit in cleartext. Prefer https."),
            )
        messages.success(request, _("Integration settings saved."))
        return redirect(_index_url("integrations"))
    ctx = _settings_context(request, Institution.load(), "integrations", integrations=form)
    return render(request, "institution/manage/settings.html", ctx)
```

- [ ] **Step 4: Add the URL**

In `institution/urls.py`, add alongside the other per-tab POST routes:

```python
    path("manage/settings/integrations/", views_manage.settings_integrations,
         name="settings_integrations"),
```

(Match the existing import/reference style in that file — it may reference the view via a `views_manage` module alias or a direct import.)

- [ ] **Step 5: Create the tab partial**

`templates/institution/manage/_integrations_tab.html`:

```html
{% load i18n %}
<form class="settings__form" method="post" action="{% url 'institution:settings_integrations' %}">
  {% csrf_token %}
  {{ integrations.non_field_errors }}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "External register (webhook)" %}</h2>
    <div class="settings__field">
      <label class="settings__checkbox">
        {{ integrations.enabled }}
        {% trans "Enable result sync" %}
      </label>
    </div>
    <div class="settings__field">
      <label class="settings__label" for="{{ integrations.url.id_for_label }}">{{ integrations.url.label }}</label>
      {{ integrations.url }}
      {% if integrations.url.errors %}<p class="settings__error">{{ integrations.url.errors }}</p>{% endif %}
    </div>
    <div class="settings__field">
      <label class="settings__label" for="{{ integrations.secret.id_for_label }}">{{ integrations.secret.label }}</label>
      {{ integrations.secret }}
      <p class="settings__help">{{ integrations.secret.help_text }}</p>
      {% if integrations.secret.errors %}<p class="settings__error">{{ integrations.secret.errors }}</p>{% endif %}
    </div>
    <div class="settings__actions">
      <button class="btn" type="submit">{% trans "Save integration settings" %}</button>
    </div>
  </div>
</form>

<div class="settings__section">
  <h2 class="settings__section-title">{% trans "Recent deliveries" %}</h2>
  {% if recent_deliveries %}
  <table class="table">
    <thead>
      <tr>
        <th>{% trans "Event" %}</th>
        <th>{% trans "Status" %}</th>
        <th>{% trans "Attempts" %}</th>
        <th>{% trans "Created" %}</th>
        <th>{% trans "Last error" %}</th>
      </tr>
    </thead>
    <tbody>
      {% for d in recent_deliveries %}
      <tr>
        <td>{{ d.get_event_display }}</td>
        <td><span class="badge">{{ d.get_status_display }}</span></td>
        <td>{{ d.attempts }}</td>
        <td>{{ d.created_at }}</td>
        <td>{{ d.last_error|truncatechars:60 }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="settings__help">{% trans "No deliveries yet." %}</p>
  {% endif %}
</div>
```

> Use the same field/label/button classes the sibling partials use — open `_notifications_tab.html` and match its markup so the panel inherits the token CSS. If the sibling uses a `.table`/`.badge` variant with different names, use those.

- [ ] **Step 6: Wire the partial into `settings.html`** (nav entry + panel)

Open `templates/institution/manage/settings.html`. It has (a) a **tab-nav list** of
per-tab links/buttons and (b) one **panel wrapper** per tab. Do both:

1. **Nav entry** — find the existing nav entry for an adjacent tab (e.g. the
   `notifications` one; it will look like a link carrying `?tab=notifications` and an
   `{% trans %}` label, with an active-state class keyed on `active_tab`). **Copy that
   exact entry**, swapping `notifications` → `integrations` and the label to
   `{% trans "Integrations" %}`. Matching the sibling is what makes the tab reachable
   and correctly highlighted.
2. **Panel** — add the panel wrapper next to the sibling panels:

```html
<div data-tab="integrations" {% if active_tab != "integrations" %}hidden{% endif %}>
  {% include "institution/manage/_integrations_tab.html" %}
</div>
```

(Match the sibling panels' actual wrapper attributes if they differ from the
`data-tab`/`hidden` shape shown — mirror `_notifications`'s panel wrapper.)

- [ ] **Step 7: Run the tests, verify they pass**

Run: `uv run pytest integrations/tests/test_settings_tab.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Regression-check the settings surface**

Run: `uv run pytest institution -q`
Expected: PASS (existing settings-tab tests unaffected — the `_settings_context` signature change is additive with a default).

- [ ] **Step 9: Visual check (light + dark)**

Launch the app (`uv run python manage.py runserver`), log in as a PA, open `/manage/settings/?tab=integrations`. Confirm the form + recent-deliveries table render styled in both themes (toggle the theme switch). Fix any undefined-class fallbacks before committing. (Per project convention, a throwaway Playwright screenshot harness is acceptable; delete it after.)

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff format .
uv run ruff check .
git add institution templates/institution/manage integrations/tests/test_settings_tab.py
git commit -m "feat(integrations): Integrations settings tab + recent-deliveries panel"
```

---

### Task 12: i18n (EN/PL) + end-to-end + full-suite green

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Create: `integrations/tests/test_e2e.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en`
Expected: new `msgid`s for the Integrations tab labels, `WebhookDelivery` choice labels, form help/errors, and the cleartext warning appear in both `.po` files.

- [ ] **Step 2: Fill in Polish translations + clear fuzzy flags**

Edit `locale/pl/LC_MESSAGES/django.po`: provide `msgstr` for every new `msgid` (e.g. `"Enable result sync"` → `"Włącz synchronizację wyników"`, `"Endpoint URL"` → `"Adres URL punktu końcowego"`, `"Signing secret"` → `"Klucz podpisujący"`, `"Recent deliveries"` → `"Ostatnie wysyłki"`, `"Pending"` → `"Oczekuje"`, `"Delivered"` → `"Dostarczono"`, `"Dead"` → `"Nieudane"`, `"Superseded"` → `"Zastąpione"`, `"Result finalized"` → `"Wynik sfinalizowany"`). **Remove any `#, fuzzy` flags** on the new entries and verify machine-guessed strings are correct (grep for the new msgids and eyeball each).

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`
Expected: writes `.mo` files with no errors.

- [ ] **Step 4: Verify the PL strings load**

`integrations/tests/test_e2e.py` (i18n assertion + config e2e):

```python
import pytest
from django.urls import reverse
from django.utils import translation

pytestmark = pytest.mark.django_db


def test_status_label_translates_pl():
    from integrations.models import WebhookDelivery

    with translation.override("pl"):
        label = str(WebhookDelivery.Status.PENDING.label)
    assert label == "Oczekuje"


def test_pa_configures_endpoint_and_panel_renders(client):
    from tests.factories import make_pa
    from integrations.models import WebhookDelivery

    make_pa(client, "pa")
    # Configure via the real form POST.
    client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "on", "url": "https://r.example/h", "secret": "shh"},
    )
    # A delivery exists → the panel lists it.
    WebhookDelivery.objects.create(dedupe_key="1:", payload={"event": "x"})
    resp = client.get(reverse("institution:settings") + "?tab=integrations")
    assert resp.status_code == 200
    assert b"Recent deliveries" in resp.content or "Ostatnie".encode() in resp.content
```

Run: `uv run pytest integrations/tests/test_e2e.py -v`
Expected: PASS (2 tests). If `test_status_label_translates_pl` fails, the PL `msgstr` or `.mo` compile is wrong — fix and re-compile.

- [ ] **Step 5: Full suite + lint**

Run:
```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```
Expected: all green. Investigate and fix any failure before committing (do not skip).

- [ ] **Step 6: Fresh-DB migrate check**

Run: `uv run python manage.py migrate` on a clean database (or inspect `makemigrations --check --dry-run` shows nothing pending).
Expected: all `integrations` + `external_id` migrations apply cleanly; no missing migrations.

- [ ] **Step 7: Commit**

```bash
git add locale integrations/tests/test_e2e.py
git commit -m "feat(integrations): EN/PL translations + config e2e; grade-sync webhook complete"
```

---

## Operator note (for the DoD / docs, not a code task)

`flush_webhooks` is cron-run. Document a cadence (e.g. every 5 minutes:
`*/5 * * * * cd <app> && uv run python manage.py flush_webhooks`) in the
deployment runbook. Retention/purge of old `delivered`/`dead`/`superseded`
rows is a deferred follow-up (spec §9), not part of this slice.

---

## Self-review notes (coverage against spec)

- Spec §1 model → Task 1 (both models, indexes, singleton, defaults). §1b external ids → Task 2 (+ forms Task 3).
- §2 emit (gate-first, fan-out, `.distinct()`, payload, dedupe_key on group_id, non-null assertion, `already_final`) → Task 4; supersede (skip_locked) → Task 5; three emit sites incl. force-submit `locked` + correction pre-save score + feedback-only + quiz_finish status-guard placement → Tasks 6–7.
- §3 delivery (build_opener minus redirect, HTTPError/URLError/timeout, non-2xx defensive, backoff timedelta table, HMAC sha256= + encode, per-row skip_locked flush, --limit, disabled no-op) → Tasks 8–9.
- §4 config (IntegrationsForm scheme + enable-guards + secret preserve, http cleartext warning in the view, Integrations tab + recent-deliveries panel, external-id form fields) → Tasks 3, 10, 11.
- §5 permissions (PA-only tab) → Task 11. §6 i18n → Task 12. §7 tests distributed per task; §7 e2e → Task 12. §8 DoD → Task 12 + operator note.
- §9 deferrals (multiple endpoints/adapters, async, purge, SSRF private-IP, encryption, test button) are intentionally **not** implemented.
