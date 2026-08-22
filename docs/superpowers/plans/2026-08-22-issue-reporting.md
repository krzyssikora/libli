# Issue Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Platform-Admin-chosen audience report a problem from the page they are on, with an optional screenshot and diagnostic telemetry, stored in the database and emailed to the Platform Admins plus any extra addresses.

**Architecture:** A new self-contained `support` Django app owns the policy (`SupportSettings` singleton + `can_report`), the record (`IssueReport`), private screenshot storage outside `MEDIA_ROOT`, email delivery, and a PA triage surface. The reporter surface is a `<dialog>` included once from `base.html`, gated by a context-processor flag, posting JSON to one endpoint. The PA configures it from a seventh tab on the existing institution settings page plus a dedicated roster page.

**Tech Stack:** Python 3.13 · Django 5.2 · PostgreSQL 16 · uv · server-rendered templates + vanilla JS (no build step, no React, no Bootstrap) · pytest / pytest-django · Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-22-issue-reporting-design.md` — read it alongside this plan. The plan implements the spec; where a step says "because…", the full reasoning is in the spec.

## Global Constraints

- **Test commands need `uv run`** — the tooling is not on `PATH`. Unit/integration: `uv run pytest <paths> -v`. e2e: `uv run pytest -m e2e <paths> -v` (the `-m e2e` is mandatory; without it e2e tests are deselected and pytest exits 5).
- **Grep the pytest summary, do not trust the exit code** — this suite can exit 0 while reporting `1 failed`.
- **Scope test runs narrowly.** Run only the files a task touches. Whole-repo sweeps are a branch gate, not a task step.
- **Lint gates are separate:** `uv run ruff check --no-cache` and `uv run ruff format --check` both must pass. `--no-cache` is required.
- **The code blocks in this plan are illustrative, not pre-formatted.** Before each task's `ruff format --check` gate, run `uv run ruff format <the files that task touched>`. Ruff selects `["E", "F", "I", "UP", "B", "S"]` with a line length of 88 and `force-single-line` imports, so transcribed blocks will need line wrapping, and any import you end up not using must be deleted (`F401`) rather than left for symmetry.
- **Never use `UserFactory` + `force_login` for permission tests** — that user carries no role Group and reads as silently unprivileged. Use `make_pa` / `make_ca` / `make_teacher` / `make_student` from `tests/factories.py`, which call `seed_roles()` and attach the Group.
- **All user-facing strings** use `gettext_lazy as _` in models/forms/templates. The email module uses **eager `gettext`** inside its `translation.override(...)` block.
- **Icons are monochrome inline SVG using `currentColor`.** Never emoji.
- **No hardcoded test passwords** — use `TEST_PASSWORD` from `tests/factories.py`.
- **Every new view ships styled in both light and dark themes.**
- **Named constants only.** No test asserts a bare literal that also appears in `support/constants.py` or `support/telemetry.py`.

---

### Task 1: App scaffold, settings, storage, models, migration

**Files:**
- Create: `support/__init__.py`, `support/apps.py`, `support/constants.py`, `support/storage.py`, `support/validators.py`, `support/models.py`, `support/signals.py`, `support/migrations/__init__.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS, `SUPPORT_SCREENSHOT_DIR`), `.gitignore`
- Test: `tests/test_support_models.py`

**Interfaces:**
- Consumes: `courses.validators` (`SAFE_IMAGE_EXTENSIONS`, `MAX_IMAGE_MIB_CEILING`, `_validate_file`)
- Produces: `support.models.SupportSettings` (`.Audience`, `.load()`), `support.models.IssueReport` (`.Status`), `support.storage.ScreenshotStorage`, `support.validators.validate_screenshot_file`, `support.constants.*`

- [ ] **Step 1: Create the app package and settings entries**

`support/__init__.py` — empty.

`support/apps.py`:

```python
from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "support"

    def ready(self):
        from support import signals  # noqa: F401  (receivers register on import)
```

**Create `support/signals.py` and `support/models.py` as empty files in this step**, even though their contents come in Steps 5–6. `ready()` runs during app-registry population, so with `"support"` in `INSTALLED_APPS` and no `support/signals.py` on disk, **the entire test suite fails to start** — not just this task's file — with `ModuleNotFoundError: No module named 'support.signals'`. Creating them empty keeps the repo bootable between steps.

`support/constants.py`:

```python
"""Every cap and limit the support app enforces, named so tests assert on a name."""

from datetime import timedelta

DESCRIPTION_MAX_LENGTH = 4000
PAGE_URL_MAX_LENGTH = 2000
PAGE_TITLE_MAX_LENGTH = 300
REPORTER_LABEL_MAX_LENGTH = 200
REPORTER_ROLES_MAX_LENGTH = 200
THROTTLE_MAX_REPORTS = 5  # per user, per window
THROTTLE_WINDOW = timedelta(hours=1)
EXTRA_EMAILS_MAX = 20
SUPPORT_CONFIG_CACHE_KEY = "support:config"
SUPPORT_CONFIG_TTL = 300  # seconds; mirrors core.services.CACHE_TTL
LIST_PAGE_SIZE = 25
```

In `config/settings/base.py`, add `"support",` to the end of `INSTALLED_APPS` (after `"integrations",`), and add this beside `TRANSFER_STAGING_DIR`:

```python
# NOT under MEDIA_ROOT: report screenshots may contain another student's name,
# answers or grades and must never be web-served. Served only by the PA-only
# support:screenshot view. Mirrors TRANSFER_STAGING_DIR above.
SUPPORT_SCREENSHOT_DIR = BASE_DIR / "support_screenshots"
```

In `.gitignore`, add `support_screenshots/` beneath the existing `transfer_staging/` line.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_support_models.py`:

```python
"""Model, storage and validator behaviour for the support app."""

import os

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.models import IssueReport
from support.models import SupportSettings
from support.models import screenshot_upload_to
from support.storage import ScreenshotStorage
from support.validators import validate_screenshot_file

pytestmark = pytest.mark.django_db


def _png_bytes():
    """Smallest valid PNG (1x1) — real bytes, so ImageField's Pillow check passes."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_supportsettings_is_a_singleton():
    first = SupportSettings.load()
    first.audience = SupportSettings.Audience.ALL
    first.save()
    second = SupportSettings()
    second.save()
    assert SupportSettings.objects.count() == 1
    assert SupportSettings.load().pk == 1


def test_supportsettings_defaults_to_admins_only():
    assert SupportSettings().audience == SupportSettings.Audience.ADMINS


def test_storage_resolves_the_directory_on_every_access(tmp_path):
    """Two DIFFERENT override values in ONE process.

    A single override would pass even against a storage that froze the path on
    first access, because that first access happens inside the override.
    """
    storage = ScreenshotStorage()
    one = tmp_path / "one"
    two = tmp_path / "two"
    with override_settings(SUPPORT_SCREENSHOT_DIR=one):
        assert storage.location == os.path.abspath(one)
    with override_settings(SUPPORT_SCREENSHOT_DIR=two):
        assert storage.location == os.path.abspath(two)


def test_storage_url_raises_rather_than_emitting_a_media_link():
    with pytest.raises(NotImplementedError):
        ScreenshotStorage().url("screenshots/2026/08/x.png")


def test_upload_to_discards_the_client_filename():
    name = screenshot_upload_to(IssueReport(), "../../evil name.PNG")
    assert name.startswith("screenshots/")
    assert name.endswith(".png")  # lower-cased
    assert "evil" not in name
    assert ".." not in name


def test_upload_to_defaults_the_extension_when_there_is_none():
    assert screenshot_upload_to(IssueReport(), "myscreenshot").endswith(".png")


def test_upload_to_clamps_an_unlisted_extension():
    assert screenshot_upload_to(IssueReport(), "payload.php").endswith(".png")


def test_validator_accepts_a_file_well_under_the_ceiling():
    upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    validate_screenshot_file(upload)  # must not raise


def test_validator_rejects_a_disallowed_extension():
    upload = SimpleUploadedFile("shot.txt", b"nope", content_type="text/plain")
    with pytest.raises(ValidationError):
        validate_screenshot_file(upload)


def test_reporter_label_is_truncated_not_overflowed():
    report = IssueReport.objects.create(
        reporter_label="x" * 500, description="hi"
    )
    report.refresh_from_db()
    assert len(report.reporter_label) <= REPORTER_LABEL_MAX_LENGTH


def test_reporter_roles_truncates_on_a_comma_boundary():
    """Mutant: use a blind slice — it stores a trailing fragment like
    "Course Adm", which role_labels() then renders as a role nobody held."""
    long_name = "R" * 90
    roles = ",".join([long_name, long_name, long_name])  # 272 chars
    report = IssueReport.objects.create(reporter_roles=roles, description="hi")
    report.refresh_from_db()
    assert report.reporter_roles == f"{long_name},{long_name}"
    assert all(part == long_name for part in report.reporter_roles.split(","))


def test_a_screenshot_still_validates_after_narrowing_institution_extensions():
    """The whole reason support/validators.py exists rather than reusing
    courses.validators.validate_image_file. Mutant: use validate_image_file."""
    from django.core.cache import cache

    from institution.models import Institution

    inst = Institution.load()
    inst.allowed_image_extensions = ["jpg"]
    inst.save()
    cache.clear()  # the site-config bundle feeds validate_image_file
    upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    validate_screenshot_file(upload)  # must still not raise


def test_deleting_a_report_deletes_its_screenshot(tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        report = IssueReport.objects.create(description="hi")
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        path = report.screenshot.path
        assert os.path.exists(path)
        report.delete()
        assert not os.path.exists(path)
```

Note `test_reporter_label_is_truncated_not_overflowed` asserts the **model** truncates on save, so the label is safe no matter which caller builds it.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_support_models.py -v`
Expected: collection error — `ImportError: cannot import name 'SupportSettings' from 'support.models'` (the module exists but is empty, per Step 1). If instead you see `ModuleNotFoundError: No module named 'support.signals'`, Step 1's empty-file creation was skipped and **every** test file is now failing to collect, not just this one.

- [ ] **Step 4: Write storage and validators**

`support/storage.py`:

```python
"""Private, non-web-served storage for report screenshots."""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ScreenshotStorage(FileSystemStorage):
    """Screenshots live outside MEDIA_ROOT and are served only by support:screenshot.

    BOTH base_location and location are plain properties. Django 5.2 declares each
    as its own cached_property (location = abspath(base_location)) and every path
    operation goes through `location`, so overriding only base_location would still
    freeze the directory on first access — and StorageSettingsMixin only clears that
    cache for MEDIA_ROOT/MEDIA_URL, never for a custom setting. Freezing it would
    make override_settings(SUPPORT_SCREENSHOT_DIR=...) a silent no-op and every
    screenshot test would write into the developer's working tree.

    url() raises so a template reaching for {{ report.screenshot.url }} fails loudly
    instead of emitting a plausible /media/... link that bypasses the PA-only view
    and resolves to nothing. base_url is pinned to None as well, so the inherited
    cached_property can never quietly resolve to MEDIA_URL.

    The constructor's `location` argument is intentionally INERT: overriding the
    cached_property means FileSystemStorage.__init__ stores self._location and
    nothing reads it. Tests must use override_settings, never
    ScreenshotStorage(location=...), which would silently use the real directory.
    """

    base_url = None

    @property
    def base_location(self):
        return settings.SUPPORT_SCREENSHOT_DIR

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise NotImplementedError(
            "Screenshots are private; link them with "
            "{% url 'support:screenshot' report.pk %}."
        )
```

`support/validators.py`:

```python
"""Screenshot upload validation.

Deliberately NOT courses.validators.validate_image_file: that one applies
Institution.allowed_image_extensions, which a PA may narrow for CONTENT uploads.
A PA restricting course images to jpg/webp would then silently break screenshot
paste, since clipboard images are PNG on Windows. Bug reporting must not depend
on an unrelated setting, so screenshots validate against the permanent ceiling.
"""

from django.utils.translation import gettext_lazy as _

from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import SAFE_IMAGE_EXTENSIONS
from courses.validators import _validate_file

MAX_SCREENSHOT_BYTES = MAX_IMAGE_MIB_CEILING * 1024 * 1024


def validate_screenshot_file(file):
    # Delegates to _validate_file so the `_committed` early-return is inherited:
    # without it, reading .size on an already-stored file raises FileNotFoundError
    # whenever the file is absent from storage (a DB restored against a fresh
    # volume), and any later full_clean() of an existing report would blow up.
    _validate_file(
        file,
        extensions=SAFE_IMAGE_EXTENSIONS,
        # The constant is a MiB COUNT, not bytes — passing it through verbatim
        # would cap screenshots at five bytes.
        max_bytes=MAX_SCREENSHOT_BYTES,
        too_big_msg=_("Screenshot too large (max %(mib)d MiB).")
        % {"mib": MAX_IMAGE_MIB_CEILING},
    )
```

- [ ] **Step 5: Write the models**

`support/models.py`:

```python
"""SupportSettings (who may report, where reports go) and IssueReport (one report)."""

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from courses.validators import SAFE_IMAGE_EXTENSIONS
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.constants import REPORTER_ROLES_MAX_LENGTH
from support.storage import ScreenshotStorage
from support.validators import validate_screenshot_file

DEFAULT_SCREENSHOT_EXT = "png"


def truncate_roles(value):
    """Truncate a comma-joined role snapshot ON A COMMA BOUNDARY.

    A blind slice could store "Course Adm", which role_labels()'s
    raw-name fallback would then faithfully render as a role the user never
    held. The four current roles cannot overflow 200 chars; the cap exists for
    future or renamed Groups, which is exactly the case where a mid-token cut
    would lie.
    """
    if len(value) <= REPORTER_ROLES_MAX_LENGTH:
        return value
    names = value.split(",")
    kept = []
    for name in names:
        candidate = ",".join(kept + [name])
        if len(candidate) > REPORTER_ROLES_MAX_LENGTH:
            break
        kept.append(name)
    return ",".join(kept)


def screenshot_upload_to(instance, filename):
    """screenshots/<YYYY>/<MM>/<uuid4>.<ext> — never any part of the client name.

    upload_to runs from FileField.pre_save on EVERY save, whereas
    validate_screenshot_file only fires under full_clean()/a ModelForm. So the
    extension is clamped here too: the stored name must be safe even on a path
    that skipped validation (a fixture, a management command). A dot-less name
    would otherwise make a naive rsplit return the whole basename.
    """
    ext = PurePosixPath(filename).suffix.lstrip(".").lower()
    if ext not in SAFE_IMAGE_EXTENSIONS:
        ext = DEFAULT_SCREENSHOT_EXT
    now = timezone.now()
    return f"screenshots/{now:%Y}/{now:%m}/{uuid.uuid4().hex}.{ext}"


class SupportSettings(models.Model):
    """Single-row (pk=1) config. Modelled on integrations.WebhookEndpoint.

    READS on a render path MUST use objects.filter(pk=1).first(), never load():
    load()'s get_or_create would write a row during a plain GET. Only the two
    write paths (the Support tab POST and the Allowed reporters POST) use load().
    """

    class Audience(models.TextChoices):
        ADMINS = "admins", _("Platform Admins only")
        COURSE_ADMINS = "course_admins", _("Course Admins and Platform Admins")
        TEACHERS = "teachers", _("Teachers, Course Admins and Platform Admins")
        ALL = "all", _("Everyone, including students")

    audience = models.CharField(
        max_length=16, choices=Audience.choices, default=Audience.ADMINS
    )
    extra_reporters = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+"
    )
    extra_emails = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class IssueReport(models.Model):
    """One submitted report. reporter_label/reporter_roles are denormalised on
    purpose: this repo hard-deletes and keeps no orphan audit rows, so a report
    whose provenance vanishes with the account tells the PA nothing."""

    class Status(models.TextChoices):
        OPEN = "open", pgettext_lazy("issue report status", "Open")
        RESOLVED = "resolved", pgettext_lazy("issue report status", "Resolved")

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issue_reports",
    )
    reporter_label = models.CharField(max_length=REPORTER_LABEL_MAX_LENGTH, blank=True)
    reporter_roles = models.CharField(max_length=REPORTER_ROLES_MAX_LENGTH, blank=True)
    description = models.TextField()
    page_url = models.TextField(blank=True)
    page_title = models.CharField(max_length=PAGE_TITLE_MAX_LENGTH, blank=True)
    screenshot = models.ImageField(
        blank=True,
        storage=ScreenshotStorage,
        upload_to=screenshot_upload_to,
        validators=[validate_screenshot_file],
    )
    telemetry = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            # Serves the throttle's per-user count, which would otherwise scan.
            models.Index(fields=["reporter", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        # Truncate here, not only at the call site: a composed
        # "Display Name (username) <email>" can reach ~560 chars (display_name 150 +
        # username 150 + email 254) and Postgres raises DataError on overflow,
        # which would 500 the submission and lose the report.
        self.reporter_label = self.reporter_label[:REPORTER_LABEL_MAX_LENGTH]
        self.reporter_roles = truncate_roles(self.reporter_roles)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Issue report #{self.pk}"
```

Note the `ImageField` passes the **class** `ScreenshotStorage` as the storage callable, so the migration serialises a class reference rather than this machine's absolute path.

- [ ] **Step 6: Write the screenshot-cleanup signal**

`support/signals.py`:

```python
"""Support receivers: screenshot cleanup (here) and cache invalidation (Task 2)."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from support.models import IssueReport


@receiver(post_delete, sender=IssueReport)
def delete_screenshot_file(sender, instance, **kwargs):
    """Django does not remove files on model delete. Orphaned screenshots of
    student data accumulating on disk is exactly the failure mode to avoid."""
    if instance.screenshot:
        instance.screenshot.delete(save=False)
```

- [ ] **Step 7: Create the migration**

Run: `uv run python manage.py makemigrations support`
Expected: `support/migrations/0001_initial.py` created.

Open it and confirm the `screenshot` field serialises as `storage=support.storage.ScreenshotStorage` — a class path, **not** an absolute filesystem path. If an absolute path appears, the field was given an instance instead of the class; fix `support/models.py` and regenerate.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_support_models.py -v`
Expected: 11 passed. Grep the summary line — do not trust the exit code.

- [ ] **Step 9: Falsify two of them**

Temporarily edit `support/storage.py` to delete the `location` property (leaving only `base_location`). Re-run: `test_storage_resolves_the_directory_on_every_access` must FAIL on the second override. Restore the property **by hand** — never `git checkout`, which would discard the whole task's work.

Then temporarily change `screenshot_upload_to` to `return f"screenshots/{now:%Y}/{now:%m}/{filename}"`. Re-run: `test_upload_to_discards_the_client_filename` must FAIL. Restore by hand.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check --no-cache support tests/test_support_models.py
uv run ruff format --check support tests/test_support_models.py
git add support config/settings/base.py .gitignore tests/test_support_models.py
git commit -m "feat(support): app scaffold, private screenshot storage, models"
```

---

### Task 2: Audience policy, cached config, throttle, context processor

**Files:**
- Create: `support/policy.py`
- Modify: `support/signals.py`, `core/services.py`, `core/context_processors.py`, `config/settings/base.py` (context processor registration)
- Test: `tests/test_support_policy.py`

**Interfaces:**
- Consumes: `support.models.SupportSettings`, `support.constants`, `institution.roles` (`PLATFORM_ADMIN`, `TEACHER`, `COURSE_ADMIN`, `STUDENT`, `ROLE_NAMES`, `ROLE_LABELS`)
- Produces: `support.policy.can_report(user, role_names=None) -> bool`, `support.policy.throttle_exceeded(user) -> bool`, `support.policy.get_support_config() -> dict`, `support.policy.invalidate_support_config(*a, **kw)`, `support.policy.role_snapshot(role_names) -> str` (canonically ordered comma-joined Group names — Task 4 stores its result), `support.policy.role_labels(reporter_roles) -> list[str]`, `support.policy.AUDIENCE_GROUPS`, `core.services.role_names_for(request) -> frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_policy.py`:

```python
"""Audience policy, config caching and throttling."""

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles
from support.constants import THROTTLE_MAX_REPORTS
from support.constants import THROTTLE_WINDOW
from support.models import IssueReport
from support.models import SupportSettings
from support.policy import AUDIENCE_GROUPS
from support.policy import can_report
from support.policy import role_labels
from support.policy import throttle_exceeded
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.factories import make_student

pytestmark = pytest.mark.django_db

Audience = SupportSettings.Audience


@pytest.fixture(autouse=True)
def _clear_config_cache():
    cache.clear()
    yield
    cache.clear()


def _user_with_role(role_name, **kwargs):
    seed_roles()
    user = UserFactory(**kwargs)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    return user


def _set_audience(value):
    settings_row = SupportSettings.load()
    settings_row.audience = value
    settings_row.save()


@pytest.mark.parametrize(
    ("audience", "role", "expected"),
    [
        (Audience.ADMINS, PLATFORM_ADMIN, True),
        (Audience.ADMINS, COURSE_ADMIN, False),
        (Audience.ADMINS, TEACHER, False),
        (Audience.ADMINS, STUDENT, False),
        (Audience.COURSE_ADMINS, PLATFORM_ADMIN, True),
        (Audience.COURSE_ADMINS, COURSE_ADMIN, True),
        (Audience.COURSE_ADMINS, TEACHER, False),
        (Audience.COURSE_ADMINS, STUDENT, False),
        (Audience.TEACHERS, PLATFORM_ADMIN, True),
        (Audience.TEACHERS, COURSE_ADMIN, True),
        (Audience.TEACHERS, TEACHER, True),
        (Audience.TEACHERS, STUDENT, False),
        (Audience.ALL, PLATFORM_ADMIN, True),
        (Audience.ALL, COURSE_ADMIN, True),
        (Audience.ALL, TEACHER, True),
        (Audience.ALL, STUDENT, True),
    ],
)
def test_can_report_matrix(audience, role, expected):
    _set_audience(audience)
    assert can_report(_user_with_role(role)) is expected


def test_audience_groups_covers_every_rung():
    """The matrix parametrisation and the runtime lookup share one constant."""
    assert set(AUDIENCE_GROUPS) == {a.value for a in Audience}


def test_platform_admin_can_always_report_even_on_the_narrowest_rung():
    _set_audience(Audience.ADMINS)
    assert can_report(_user_with_role(PLATFORM_ADMIN)) is True


def test_superuser_outside_the_group_can_report():
    """accounts/services.py treats superusers outside the PA group as a separate
    recovery path — and that account is the one most likely to be debugging."""
    _set_audience(Audience.ADMINS)
    assert can_report(UserFactory(is_superuser=True)) is True


def test_the_all_rung_admits_a_user_holding_no_role_group():
    """Evaluated as a group intersection, 'Everyone' would deny a fresh
    createsuperuser account or an SSO account before role assignment."""
    _set_audience(Audience.ALL)
    assert can_report(UserFactory()) is True


def test_inactive_and_anonymous_cannot_report():
    from django.contrib.auth.models import AnonymousUser

    _set_audience(Audience.ALL)
    assert can_report(UserFactory(is_active=False)) is False
    assert can_report(AnonymousUser()) is False


def test_an_extra_reporter_can_report_immediately_after_being_added():
    """Mutant: remove the m2m_changed invalidation receiver."""
    _set_audience(Audience.ADMINS)
    teacher = _user_with_role(TEACHER)
    assert can_report(teacher) is False
    SupportSettings.load().extra_reporters.add(teacher)
    assert can_report(teacher) is True


def test_changing_the_audience_takes_effect_immediately():
    """Mutant: remove the post_save invalidation receiver."""
    _set_audience(Audience.ADMINS)
    student = _user_with_role(STUDENT)
    assert can_report(student) is False
    _set_audience(Audience.ALL)
    assert can_report(student) is True


def test_with_no_settings_row_nothing_explodes_and_students_cannot_report():
    """The M2M must never be read off an unsaved SupportSettings() fallback —
    that raises ValueError, and can_report runs on every authenticated render."""
    assert SupportSettings.objects.count() == 0
    assert can_report(_user_with_role(STUDENT)) is False


def test_a_warm_cache_costs_no_settings_queries_on_a_render(client):
    """Exercises the RENDER path, not can_report() alone: a context processor
    that bypassed get_support_config() would otherwise go unnoticed. The filter
    also catches the through table, whose name contains this substring."""
    _set_audience(Audience.ALL)
    make_student(client)
    client.get(reverse("home"))  # warm the bundle
    with CaptureQueriesContext(connection) as ctx:
        client.get(reverse("home"))
    settings_queries = [
        q for q in ctx.captured_queries if "support_supportsettings" in q["sql"]
    ]
    assert settings_queries == []


def test_an_authenticated_render_issues_one_role_names_query(client):
    """Only statements selecting auth_group.name count: base.html's perms.*
    lookups make the auth backend join auth_group too, so counting every
    auth_group statement would be FALSE on a correct build."""
    make_pa(client)
    with CaptureQueriesContext(connection) as ctx:
        client.get(reverse("home"))
    role_queries = [
        q for q in ctx.captured_queries if '"auth_group"."name"' in q["sql"]
    ]
    assert len(role_queries) == 1


def test_throttle_uses_a_rolling_window_not_a_clock_hour():
    student = make_student_reporter()
    _backdate(_make_reports(student, THROTTLE_MAX_REPORTS), minutes=61)
    assert throttle_exceeded(student) is False
    _backdate(_make_reports(student, THROTTLE_MAX_REPORTS), minutes=59)
    assert throttle_exceeded(student) is True


def make_student_reporter():
    _set_audience(Audience.ALL)
    return _user_with_role(STUDENT)


def _make_reports(user, count):
    return [
        IssueReport.objects.create(reporter=user, description=f"r{i}")
        for i in range(count)
    ]


def _backdate(reports, *, minutes):
    """created_at is auto_now_add, which IGNORES any value assigned before save() —
    the rows must be backdated with a queryset update afterwards."""
    when = timezone.now() - timezone.timedelta(minutes=minutes)
    IssueReport.objects.filter(pk__in=[r.pk for r in reports]).update(created_at=when)


def test_role_labels_falls_back_to_the_raw_name():
    assert role_labels("Teacher,Retired Role") == ["Teacher", "Retired Role"]
    assert role_labels("") == []


def test_role_snapshot_is_canonically_ordered():
    """Mutant: join the frozenset directly. ROLE_NAMES order is
    [Student, Teacher, Course Admin, Platform Admin], so a set-iteration join
    would produce either ordering depending on the hash seed — making assertions
    flaky and the comma-boundary truncation drop a different role run to run."""
    assert role_snapshot(frozenset({COURSE_ADMIN, TEACHER})) == "Teacher,Course Admin"


def test_role_snapshot_sorts_non_standard_groups_after_the_known_ones():
    assert role_snapshot(frozenset({"Zebra", TEACHER, "Alpha"})) == "Teacher,Alpha,Zebra"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_policy.py -v`
Expected: collection error — `No module named 'support.policy'`.

- [ ] **Step 3: Write the policy module**

`support/policy.py`:

```python
"""Who may report, the cached config bundle, the throttle, and role labelling."""

from django.core.cache import cache
from django.utils import timezone

from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import ROLE_LABELS
from institution.roles import ROLE_NAMES
from institution.roles import TEACHER
from support.constants import SUPPORT_CONFIG_CACHE_KEY
from support.constants import SUPPORT_CONFIG_TTL
from support.constants import THROTTLE_MAX_REPORTS
from support.constants import THROTTLE_WINDOW

# The ladder's semantics, named so the matrix test parametrises off the constant
# instead of restating it. `all` is never consulted at runtime (rule 3
# short-circuits above it) but must exist so the test covers four rungs.
AUDIENCE_GROUPS = {
    "admins": frozenset(),
    "course_admins": frozenset({COURSE_ADMIN}),
    "teachers": frozenset({TEACHER, COURSE_ADMIN}),
    "all": frozenset(ROLE_NAMES),
}

_ALL = "all"


def get_support_config():
    """{"audience": str, "extra_reporter_ids": frozenset[int]}, cached.

    Immediate in the worker that saved; bounded by SUPPORT_CONFIG_TTL elsewhere,
    because the default LocMemCache is per-process — the same property
    core.services.get_site_config has. This bounds REVOCATION latency too.
    """
    bundle = cache.get(SUPPORT_CONFIG_CACHE_KEY)
    if bundle is None:
        bundle = _build_config()
        cache.set(SUPPORT_CONFIG_CACHE_KEY, bundle, SUPPORT_CONFIG_TTL)
    return bundle


def _build_config():
    from support.models import SupportSettings

    row = SupportSettings.objects.filter(pk=1).first()
    if row is None:
        # MUST NOT fall back to an unsaved SupportSettings(): any M2M access on an
        # unsaved instance raises ValueError, and can_report runs from a context
        # processor on every authenticated render — that would 500 the whole site
        # on a fresh install.
        return {
            "audience": SupportSettings.Audience.ADMINS,
            "extra_reporter_ids": frozenset(),
        }
    return {
        "audience": row.audience,
        "extra_reporter_ids": frozenset(
            row.extra_reporters.values_list("id", flat=True)
        ),
    }


def invalidate_support_config(*args, **kwargs):
    """Signal receiver: drop the bundle so the next read rebuilds it."""
    cache.delete(SUPPORT_CONFIG_CACHE_KEY)


def can_report(user, role_names=None):
    """Rules are ordered so 1-3 settle without touching Groups."""
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    config = get_support_config()
    if config["audience"] == _ALL:
        return True
    if role_names is None:
        role_names = frozenset(user.groups.values_list("name", flat=True))
    if PLATFORM_ADMIN in role_names:
        return True
    if role_names & AUDIENCE_GROUPS.get(config["audience"], frozenset()):
        return True
    return user.id in config["extra_reporter_ids"]


def throttle_exceeded(user):
    """Rolling window, not a clock hour. Nobody is exempt: the limit is high
    enough not to obstruct honest use, and an exemption is a branch nobody tests."""
    from support.models import IssueReport

    since = timezone.now() - THROTTLE_WINDOW
    count = IssueReport.objects.filter(reporter=user, created_at__gte=since).count()
    return count >= THROTTLE_MAX_REPORTS


def role_snapshot(role_names):
    """Comma-joined Group names in CANONICAL order.

    role_names is a frozenset, and joining a set yields a hash-seed-dependent
    order: the same user would store "Teacher,Course Admin" in one process and the
    reverse in another, making assertions flaky, making the comma-boundary
    truncation drop a different role run to run, and making the triage role column
    unstable between two reports from the same person.
    """
    ordered = [n for n in ROLE_NAMES if n in role_names]
    ordered += sorted(n for n in role_names if n not in ROLE_NAMES)
    return ",".join(ordered)


def role_labels(reporter_roles):
    """Stored Group names -> display labels, falling back to the raw name.

    One home, consumed by the triage templates AND both email templates. Django
    templates cannot index a dict by a variable key, so this cannot live in a
    template. Note accounts/views_manage.py:_role_labels_for DROPS unknown names —
    the opposite of what a historical snapshot needs — so it must not be reused.
    """
    if not reporter_roles:
        return []
    return [
        ROLE_LABELS.get(name, name)
        for name in (part.strip() for part in reporter_roles.split(","))
        if name
    ]
```

Note there is deliberately **no `STUDENT` import**: `AUDIENCE_GROUPS`'s `all` entry uses `ROLE_NAMES`, so importing `STUDENT` "for symmetry" would fire `F401` and cost a lint round.

- [ ] **Step 4: Connect the cache-invalidation receivers**

**Merge the four imports into the existing import block at the top of
`support/signals.py`**, then append only the two `connect(...)` calls. Appending
imports below the existing receiver would fire `E402` (module-level import not at
top) and `I001` (isort, `force-single-line`), so this task's own lint gate would
fail.

Imports to merge in:

```python
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save

from support.models import SupportSettings
from support.policy import invalidate_support_config
```

Calls to append:

```python
post_save.connect(invalidate_support_config, sender=SupportSettings)
# The m2m receiver is the easy one to omit, and omitting it means a newly-granted
# teacher cannot report until the cache TTL expires — a bug that looks like
# "the setting didn't save".
m2m_changed.connect(
    invalidate_support_config, sender=SupportSettings.extra_reporters.through
)
```

- [ ] **Step 5: Add `role_names_for` and wire the context processor**

Append to `core/services.py`:

```python
def role_names_for(request):
    """Group names of request.user as a frozenset, memoised on the request.

    Both user_roles and support_availability need them, and without the memo an
    authenticated render would run the same auth_group query twice.
    """
    cached = getattr(request, "_libli_role_names", None)
    if cached is not None:
        return cached
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        names = frozenset()
    else:
        names = frozenset(user.groups.values_list("name", flat=True))
    request._libli_role_names = names
    return names
```

In `core/context_processors.py`, rewrite the body of `user_roles` to use it (keep the docstring, replacing the "One cheap query per authed request" sentence with "Group names come from core.services.role_names_for, shared with support_availability"):

```python
    names = role_names_for(request)
```

replacing the existing `names = set(user.groups.values_list("name", flat=True))` line, with `from core.services import role_names_for` added to the imports. Then append:

```python
def support_availability(request):
    """Expose `can_report_issue` so base.html shows the report trigger only to a
    permitted reporter, plus the description cap the dialog's textarea needs
    (the dialog is included from base.html and so has no view context)."""
    from support.constants import DESCRIPTION_MAX_LENGTH
    from support.policy import can_report

    user = getattr(request, "user", None)
    return {
        "can_report_issue": can_report(user, role_names=role_names_for(request)),
        "report_description_max": DESCRIPTION_MAX_LENGTH,
    }
```

In `config/settings/base.py`, add `"core.context_processors.support_availability",` after `"core.context_processors.help_availability",`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_support_policy.py -v`
Expected: all pass (16 matrix cases + 12 others).

- [ ] **Step 7: Falsify three of them**

1. Comment out the `m2m_changed.connect(...)` line → `test_an_extra_reporter_can_report_immediately_after_being_added` must FAIL. Restore by hand.
2. In `can_report`, delete the `if config["audience"] == _ALL: return True` block → `test_the_all_rung_admits_a_user_holding_no_role_group` must FAIL. Restore by hand.
3. In `core/context_processors.py`, revert `user_roles` to its own `user.groups.values_list(...)` call → `test_an_authenticated_render_issues_one_role_names_query` must FAIL with 2. Restore by hand.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --no-cache support core tests/test_support_policy.py
uv run ruff format --check support core tests/test_support_policy.py
git add support core config/settings/base.py tests/test_support_policy.py
git commit -m "feat(support): audience policy, cached config, throttle, context processor"
```

---

### Task 3: Telemetry sanitiser, labels and safe link

**Files:**
- Create: `support/telemetry.py`
- Test: `tests/test_support_telemetry.py`

**Interfaces:**
- Produces: `support.telemetry.sanitise(request) -> dict`, `support.telemetry.telemetry_rows(telemetry) -> list[tuple[str, str, object]]` (**three**-tuples of `(key, label, value)`; the templates unpack all three), `support.telemetry.safe_page_link(url) -> str | None`, `support.telemetry.TELEMETRY_LABELS`, `TELEMETRY_CAPS`, `TELEMETRY_BOUNDS`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_telemetry.py`:

```python
"""Telemetry allow-listing, bounds, rendering rows and page-URL link safety."""

import pytest
from django.contrib.sites.models import Site
from django.test import RequestFactory

from support.telemetry import TELEMETRY_CAPS
from support.telemetry import TELEMETRY_LABELS
from support.telemetry import safe_page_link
from support.telemetry import sanitise
from support.telemetry import telemetry_rows


def _request(post=None, **meta):
    return RequestFactory().post("/report/", data=post or {}, **meta)


def test_unknown_keys_are_dropped():
    data = sanitise(_request({"viewport_w": "800", "evil": "payload"}))
    assert "evil" not in data
    assert data["viewport_w"] == 800


def test_over_long_strings_are_truncated():
    data = sanitise(_request({"timezone": "z" * 500}))
    assert len(data["timezone"]) == TELEMETRY_CAPS["timezone"]


def test_out_of_range_numbers_are_dropped_not_clamped():
    """A clamped 20000px viewport is a plausible-looking lie in a diagnostic
    record; an absent key is honestly absent."""
    data = sanitise(_request({"viewport_w": "999999", "viewport_h": "0"}))
    assert "viewport_w" not in data
    assert "viewport_h" not in data


def test_non_numeric_numbers_are_dropped():
    assert "viewport_w" not in sanitise(_request({"viewport_w": "wide"}))


def test_theme_accepts_only_the_two_real_values():
    assert sanitise(_request({"theme": "dark"}))["theme"] == "dark"
    assert "theme" not in sanitise(_request({"theme": "neon"}))


def test_server_facts_win_over_a_forged_payload():
    request = _request(
        {"user_agent": "forged", "accept_language": "forged"},
        HTTP_USER_AGENT="RealBrowser/1.0",
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    data = sanitise(request)
    assert data["user_agent"] == "RealBrowser/1.0"
    assert data["accept_language"] == "pl"


def test_rows_follow_the_label_order_and_omit_dropped_keys():
    rows = telemetry_rows({"theme": "dark", "viewport_w": 800})
    keys = [key for key, _label, _value in rows]
    assert keys == [k for k in TELEMETRY_LABELS if k in {"theme", "viewport_w"}]
    assert len(rows) == 2


@pytest.mark.django_db
def test_safe_page_link_rejects_javascript_and_foreign_hosts():
    site = Site.objects.get_current()
    site.domain = "libli.example"
    site.save()
    assert safe_page_link("javascript:alert(1)") is None
    assert safe_page_link("https://evil.test/x") is None
    assert safe_page_link("https://libli.example/units/3/") == "https://libli.example/units/3/"


@pytest.mark.django_db
def test_safe_page_link_ignores_the_port_when_matching_the_site():
    site = Site.objects.get_current()
    site.domain = "localhost"
    site.save()
    assert safe_page_link("http://localhost:8000/home/") is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_telemetry.py -v`
Expected: `No module named 'support.telemetry'`.

- [ ] **Step 3: Write the module**

`support/telemetry.py`:

```python
"""Allow-listed, bounded telemetry plus the two shared render helpers.

Everything the client sends is untrusted: the view never stores the payload, it
rebuilds the dict from TELEMETRY_LABELS' keys. No IP address is collected — this
is a platform with student accounts and the diagnostic value does not justify the
personal-data question.
"""

from urllib.parse import urlparse

from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _

# Declared ORDER is the render order, shared by triage and both email templates.
TELEMETRY_LABELS = {
    "viewport_w": _("Viewport width"),
    "viewport_h": _("Viewport height"),
    "screen_w": _("Screen width"),
    "screen_h": _("Screen height"),
    "dpr": _("Device pixel ratio"),
    "theme": _("Theme"),
    "ui_language": _("Interface language"),
    "timezone": _("Time zone"),
    "user_agent": _("Browser"),
    "accept_language": _("Language header"),
}

TELEMETRY_CAPS = {
    "timezone": 64,
    "ui_language": 16,
    "theme": 16,
    "user_agent": 512,
    "accept_language": 256,
}

# (low, high) inclusive; out-of-range values are DROPPED, never clamped.
TELEMETRY_BOUNDS = {
    "viewport_w": (1, 20000),
    "viewport_h": (1, 20000),
    "screen_w": (1, 20000),
    "screen_h": (1, 20000),
}

_CLIENT_STRINGS = ("timezone", "ui_language")
_THEMES = {"light", "dark"}
_DPR_MAX = 10


def sanitise(request):
    """Build the stored telemetry dict from request.POST and request.META.

    Read directly from POST, never through IssueReportForm: these keys are neither
    model fields nor declared form fields, and routing them through the form would
    let a malformed telemetry value REJECT a bug report. Bad telemetry is dropped.
    """
    post = request.POST
    data = {}

    for key in _CLIENT_STRINGS:
        value = (post.get(key) or "").strip()
        if value:
            data[key] = value[: TELEMETRY_CAPS[key]]

    for key, (low, high) in TELEMETRY_BOUNDS.items():
        try:
            number = int(post.get(key, ""))
        except (TypeError, ValueError):
            continue
        if low <= number <= high:
            data[key] = number

    try:
        dpr = round(float(post.get("dpr", "")), 2)
    except (TypeError, ValueError):
        dpr = None
    if dpr is not None and 0 < dpr <= _DPR_MAX:
        data["dpr"] = dpr

    theme = (post.get("theme") or "").strip()
    if theme in _THEMES:
        data["theme"] = theme

    # Server facts win: taken from the request, never from the payload, so a
    # reporter cannot forge the browser identification a PA debugs against.
    for key, header in (
        ("user_agent", "HTTP_USER_AGENT"),
        ("accept_language", "HTTP_ACCEPT_LANGUAGE"),
    ):
        value = (request.META.get(header) or "").strip()
        if value:
            data[key] = value[: TELEMETRY_CAPS[key]]

    return data


def telemetry_rows(telemetry):
    """[(key, label, value)] in TELEMETRY_LABELS order, omitting absent keys.

    A shared dict alone would prevent label drift but not row-order drift between
    triage and email. Dropped keys are omitted rather than rendered as "unknown":
    the sanitiser drops out-of-range values instead of clamping precisely because
    an absent viewport is an honest fact and a clamped one is a plausible lie.
    """
    telemetry = telemetry or {}
    return [
        (key, label, telemetry[key])
        for key, label in TELEMETRY_LABELS.items()
        if key in telemetry
    ]


def safe_page_link(url):
    """The URL when it is safe to render as an href, else None.

    One home, used by the triage template AND both email templates — the email is
    the one output that travels outside the login wall, so a rule living only in
    the triage view could leak a javascript: or foreign-host href into it.

    Keys on the current Site (never request.get_host()), matching
    notifications/emails._absolute_url, so a link cannot be host-spoofed. Compares
    urlparse().hostname (port-stripped, lower-cased) against a port-stripped
    Site.domain: comparing netloc directly would fail on every port-bearing
    deployment and throughout local development. Django's default Site.domain is
    example.com, so an install that never edited the Site row renders every
    page_url as inert text — intended, not a defect.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    site_host = Site.objects.get_current().domain.split(":")[0].lower()
    return url if host and host == site_host else None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_support_telemetry.py -v`
Expected: all pass.

- [ ] **Step 5: Falsify two**

1. Change `sanitise` to `data.update(request.POST.dict())` at the end → `test_unknown_keys_are_dropped` and `test_server_facts_win_over_a_forged_payload` must FAIL. Restore by hand.
2. Change the bounds loop to clamp (`data[key] = min(max(number, low), high)`) → `test_out_of_range_numbers_are_dropped_not_clamped` must FAIL. Restore by hand.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache support tests/test_support_telemetry.py
uv run ruff format --check support tests/test_support_telemetry.py
git add support/telemetry.py tests/test_support_telemetry.py
git commit -m "feat(support): telemetry allow-list, render rows, safe page link"
```

---

### Task 4: The report_create endpoint

**Files:**
- Create: `support/forms.py`, `support/views.py`, `support/urls.py`
- Modify: `config/urls.py`
- Test: `tests/test_support_report_create.py`

**Interfaces:**
- Consumes: `support.policy.can_report/throttle_exceeded/role_snapshot`, `support.telemetry.sanitise`, `core.services.role_names_for`
- Produces: `support.forms.IssueReportForm`, `support.views.report_create`, URL name `support:report_create`, and `support.emails.send_issue_report_email(report)` **called but not yet written** — Task 4 defines a no-op stub in `support/emails.py` that Task 5 replaces.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_report_create.py`:

```python
"""The dialog's POST endpoint: gating, throttling, sanitising, persistence."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from institution.roles import PLATFORM_ADMIN
from support.constants import DESCRIPTION_MAX_LENGTH
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import THROTTLE_MAX_REPORTS
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_student
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db

URL_NAME = "support:report_create"
Audience = SupportSettings.Audience


def _set_audience(value):
    row = SupportSettings.load()
    row.audience = value
    row.save()


def _payload(**overrides):
    data = {
        "description": "The submit button does nothing.",
        "page_url": "https://libli.example/units/3/",
        "page_title": "Fractions",
        "viewport_w": "1280",
        "viewport_h": "800",
        "theme": "dark",
    }
    data.update(overrides)
    return data


def test_a_permitted_user_creates_one_report(client):
    _set_audience(Audience.ALL)
    student = make_student(client)
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 201
    assert response.json()["ok"] is True
    report = IssueReport.objects.get()
    assert report.reporter == student
    assert report.page_url == "https://libli.example/units/3/"
    assert report.telemetry["viewport_w"] == 1280
    assert "Student" in report.reporter_roles
    assert student.username in report.reporter_label


def test_a_student_is_refused_when_the_rung_is_course_admins(client):
    """Hiding the menu item is not access control, and the top rung is Everyone."""
    _set_audience(Audience.COURSE_ADMINS)
    make_student(client)
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 403
    assert IssueReport.objects.count() == 0


def test_a_course_admin_is_allowed_on_that_same_rung(client):
    _set_audience(Audience.COURSE_ADMINS)
    make_ca(client)
    assert client.post(reverse(URL_NAME), _payload()).status_code == 201


def test_anonymous_gets_401_json_not_a_redirect(client):
    """fetch() follows a 302 invisibly: the dialog would see a 200 + HTML login
    page, throw on .json(), and die silently with the user's text still in it."""
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/json")


def test_get_is_rejected(client):
    _set_audience(Audience.ALL)
    make_student(client)
    assert client.get(reverse(URL_NAME)).status_code == 405


def test_an_empty_description_is_a_field_error(client):
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(reverse(URL_NAME), _payload(description="   "))
    assert response.status_code == 400
    assert "description" in response.json()["errors"]
    assert IssueReport.objects.count() == 0


def test_an_over_long_description_is_a_field_error(client):
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(
        reverse(URL_NAME), _payload(description="x" * (DESCRIPTION_MAX_LENGTH + 1))
    )
    assert response.status_code == 400


def test_an_over_long_page_title_is_truncated_not_rejected(client):
    """A ModelForm-derived page_title would carry MaxLengthValidator, which fires
    inside _clean_fields BEFORE clean_page_title and would 400 instead."""
    _set_audience(Audience.ALL)
    make_student(client)
    response = client.post(
        reverse(URL_NAME), _payload(page_title="t" * (PAGE_TITLE_MAX_LENGTH + 50))
    )
    assert response.status_code == 201
    assert len(IssueReport.objects.get().page_title) == PAGE_TITLE_MAX_LENGTH


def test_server_assigned_columns_cannot_be_set_from_the_payload(client):
    """Mutant: widen IssueReportForm to fields = "__all__"."""
    _set_audience(Audience.ALL)
    student = make_student(client)
    # UserFactory, NOT make_pa: make_* logs the new user in, and calling
    # make_student twice would try to create a second user named "student" and
    # raise IntegrityError. The test only needs another user's pk.
    other = UserFactory(username="someone-else")
    client.post(
        reverse(URL_NAME),
        _payload(
            status=IssueReport.Status.RESOLVED,
            reporter=other.pk,
            emailed_at="2020-01-01T00:00:00Z",
            telemetry='{"forged": true}',
        ),
    )
    report = IssueReport.objects.get()
    assert report.status == IssueReport.Status.OPEN
    assert report.emailed_at is None
    assert "forged" not in report.telemetry


def test_the_sixth_report_in_the_window_is_throttled(client):
    _set_audience(Audience.ALL)
    make_student(client)
    for _ in range(THROTTLE_MAX_REPORTS):
        assert client.post(reverse(URL_NAME), _payload()).status_code == 201
    response = client.post(reverse(URL_NAME), _payload())
    assert response.status_code == 429
    assert response.json()["message"]
    assert IssueReport.objects.count() == THROTTLE_MAX_REPORTS


def test_a_screenshot_is_actually_stored(client, tmp_path):
    """Mutant: bind the form without request.FILES — it validates and saves
    cleanly with the screenshot silently discarded."""
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _set_audience(Audience.ALL)
        make_student(client)
        upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        response = client.post(reverse(URL_NAME), _payload(screenshot=upload))
        assert response.status_code == 201
        assert IssueReport.objects.get().screenshot.name


def test_a_failure_inside_save_leaves_no_orphaned_file(client, tmp_path, monkeypatch):
    """The DB row rolls back but the file write does not — without the cleanup the
    screenshot stays on disk forever, with no row and so no post_delete.

    _boom performs the REAL save first and only then fails. Stubbing _persist out
    entirely would mean FileField.pre_save never runs, no file is ever written,
    and the assertion passes vacuously — green even with the whole except/delete
    block removed.
    """
    import support.views as views

    real_persist = views._persist
    written = {}

    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _set_audience(Audience.ALL)
        make_student(client)

        def _boom(report):
            real_persist(report)  # writes the file, inserts the row
            written["path"] = report.screenshot.path
            raise RuntimeError("db is unhappy")

        monkeypatch.setattr(views, "_persist", _boom)
        upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        with pytest.raises(RuntimeError):
            client.post(reverse(URL_NAME), _payload(screenshot=upload))

    # The file really did land on disk mid-transaction...
    assert written["path"]
    # ...and the cleanup removed it, and the row rolled back.
    assert list(tmp_path.rglob("*.png")) == []
    assert IssueReport.objects.count() == 0


def test_a_successful_post_queues_the_email(client, django_capture_on_commit_callbacks):
    """Mutant: delete the transaction.on_commit(...) line — every other test in
    this file and the email file still passes, because those call
    send_issue_report_email directly."""
    from django.contrib.auth.models import Group as AuthGroup
    from django.core import mail

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    admin = UserFactory(username="mailbox", email="pa@school.example")
    admin.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))

    _set_audience(Audience.ALL)
    make_student(client)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(reverse(URL_NAME), _payload()).status_code == 201
    assert len(mail.outbox) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_report_create.py -v`
Expected: `NoReverseMatch: 'support' is not a registered namespace`.

- [ ] **Step 3: Write the form**

`support/forms.py`:

```python
"""Forms for the report dialog and the PA settings surfaces."""

from django import forms
from django.utils.translation import gettext_lazy as _

from support.constants import DESCRIPTION_MAX_LENGTH
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import PAGE_URL_MAX_LENGTH
from support.models import IssueReport


class IssueReportForm(forms.ModelForm):
    """Only the four reporter-supplied columns.

    NEVER fields = "__all__": that would let any permitted reporter POST
    status=resolved, reporter=<someone else's pk>, emailed_at, resolved_by or a
    hand-built telemetry blob, defeating both the sanitiser (which deliberately
    routes around this form) and the triage audit trail. Every other column is
    assigned by the view.
    """

    description = forms.CharField(
        max_length=DESCRIPTION_MAX_LENGTH,
        widget=forms.Textarea,
        label=_("What went wrong?"),
    )
    # Declared explicitly with NO max_length. A ModelForm-derived page_title would
    # carry MaxLengthValidator, which runs inside _clean_fields before
    # clean_page_title — and Django skips a clean_<field> hook when the field
    # itself raised — so an over-long title would 400 instead of being truncated.
    page_title = forms.CharField(required=False, widget=forms.HiddenInput)
    page_url = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = IssueReport
        fields = ["description", "page_url", "page_title", "screenshot"]

    def clean_description(self):
        value = (self.cleaned_data.get("description") or "").strip()
        if not value:
            raise forms.ValidationError(_("Please describe what went wrong."))
        return value

    def clean_page_url(self):
        return (self.cleaned_data.get("page_url") or "")[:PAGE_URL_MAX_LENGTH]

    def clean_page_title(self):
        return (self.cleaned_data.get("page_title") or "")[:PAGE_TITLE_MAX_LENGTH]
```

- [ ] **Step 4: Write the email stub, the view and the URLs**

`support/emails.py` (Task 5 replaces the body):

```python
"""Report notification email. Fully implemented in Task 5."""

import logging

logger = logging.getLogger(__name__)


def send_issue_report_email(report):
    """MUST swallow and log every exception internally.

    Atomic.__exit__ commits and THEN runs the on-commit hooks, both still inside
    the `with` block — so an exception escaping here would propagate into
    report_create's rollback `except`, which is guarded only on saved_name and
    cannot tell a rollback from a post-commit failure. That would delete a
    COMMITTED report's screenshot and 500 a reporter whose report was saved. No
    test can catch it either: django_capture_on_commit_callbacks runs callbacks
    outside the atomic exit, so the interaction never reproduces in the suite.
    """
    return None
```

`support/views.py`:

```python
"""The report dialog's POST endpoint."""

import logging

from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.services import role_names_for
from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.emails import send_issue_report_email
from support.forms import IssueReportForm
from support.policy import can_report
from support.policy import role_snapshot
from support.policy import throttle_exceeded
from support.storage import ScreenshotStorage
from support.telemetry import sanitise

logger = logging.getLogger(__name__)


def _json(payload, status):
    return JsonResponse(payload, status=status)


def _error(message, status):
    return _json({"ok": False, "message": message, "errors": {}}, status)


def build_label(user):
    email = user.email or ""
    label = f"{user.display_name or user.username} ({user.username})"
    if email:
        label = f"{label} <{email}>"
    return label[:REPORTER_LABEL_MAX_LENGTH]


def _persist(report):
    """Isolated so a test can monkeypatch a failure INSIDE the save."""
    report.save()


@require_POST
def report_create(request):
    # No @login_required: fetch() follows a 302 invisibly, so an anonymous POST
    # must be an observable 401 rather than a redirect to the login page.
    if not request.user.is_authenticated:
        return _error(_("Please log in again to send this report."), 401)

    role_names = role_names_for(request)
    if not can_report(request.user, role_names=role_names):
        return _error(_("You do not have access to issue reporting."), 403)

    if throttle_exceeded(request.user):
        return _error(
            _("You have sent a few reports already. Please try again later."), 429
        )

    form = IssueReportForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = {
            field: [item["message"] for item in items]
            for field, items in form.errors.get_json_data().items()
        }
        return _json({"ok": False, "message": None, "errors": errors}, 400)

    saved_name = None
    try:
        with transaction.atomic():
            report = form.save(commit=False)
            report.reporter = request.user
            report.reporter_label = build_label(request.user)
            report.reporter_roles = role_snapshot(role_names)
            report.telemetry = sanitise(request)
            _persist(report)  # <- the screenshot file is written HERE
            saved_name = report.screenshot.name or None
            transaction.on_commit(lambda: send_issue_report_email(report))
    except Exception:
        # Filesystem writes are not transactional: on rollback the row vanishes
        # while the file stays on disk forever — no row means no post_delete, and
        # no PA can ever see or delete it. saved_name is initialised BEFORE the
        # try because the likeliest failure is raised by _persist itself, after
        # the write, leaving `report` unbound.
        if saved_name:
            ScreenshotStorage().delete(saved_name)
        raise

    return _json({"ok": True, "message": _("Thank you — your report was sent.")}, 201)
```

`support/urls.py`:

```python
from django.urls import path

from support import views

app_name = "support"

urlpatterns = [
    path("report/", views.report_create, name="report_create"),
]
```

In `config/urls.py`, add `path("", include("support.urls")),` after the `integrations` include.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_support_report_create.py -v`
Expected: all pass.

- [ ] **Step 6: Falsify three**

1. Delete the `can_report` check from the view → `test_a_student_is_refused_when_the_rung_is_course_admins` must FAIL. Restore by hand.
2. Set `fields = "__all__"` on `IssueReportForm.Meta` → `test_server_assigned_columns_cannot_be_set_from_the_payload` must FAIL. Restore by hand.
3. Bind the form as `IssueReportForm(request.POST)` → `test_a_screenshot_is_actually_stored` must FAIL. Restore by hand.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache support config tests/test_support_report_create.py
uv run ruff format --check support config tests/test_support_report_create.py
git add support config/urls.py tests/test_support_report_create.py
git commit -m "feat(support): report_create endpoint with JSON contract and rollback cleanup"
```

---

### Task 5: Triage views, templates and permissions

**Files:**
- Create: `support/views_manage.py`, `support/templates/support/manage/report_list.html`, `support/templates/support/manage/report_detail.html`
- Modify: `support/urls.py`, `institution/roles.py`, `templates/base.html`
- Test: `tests/test_support_triage.py`

**Interfaces:**
- Consumes: `support.policy.role_labels`, `support.telemetry.telemetry_rows/safe_page_link`, `support.constants.LIST_PAGE_SIZE`
- Produces: URL names `support:report_list`, `support:report_detail`, `support:report_set_status`, `support:report_delete`, `support:screenshot`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_triage.py`:

```python
"""Triage list/detail/status/delete/screenshot, and their permission gates."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from support.models import IssueReport
from tests.factories import make_pa
from tests.factories import make_teacher
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db


def _report(**kwargs):
    kwargs.setdefault("description", "It broke")
    return IssueReport.objects.create(**kwargs)


def test_a_pa_sees_only_open_reports_by_default(client):
    make_pa(client)
    _report(description="still open")
    _report(description="already done", status=IssueReport.Status.RESOLVED)
    body = client.get(reverse("support:report_list")).content.decode()
    assert "still open" in body
    assert "already done" not in body


def test_status_all_shows_both_and_a_bogus_value_falls_back_to_open(client):
    make_pa(client)
    _report(description="still open")
    _report(description="already done", status=IssueReport.Status.RESOLVED)
    both = client.get(reverse("support:report_list"), {"status": "all"})
    assert "already done" in both.content.decode()
    bogus = client.get(reverse("support:report_list"), {"status": "nonsense"})
    assert "already done" not in bogus.content.decode()


def test_a_teacher_gets_403_not_a_login_redirect(client):
    """permission_required defaults to raise_exception=False, which 302s."""
    make_teacher(client)
    report = _report()
    for name, args in (
        ("support:report_list", []),
        ("support:report_detail", [report.pk]),
        ("support:screenshot", [report.pk]),
    ):
        assert client.get(reverse(name, args=args)).status_code == 403


def test_anonymous_is_redirected_to_login_rather_than_403(client):
    report = _report()
    response = client.get(reverse("support:report_detail", args=[report.pk]))
    assert response.status_code == 302
    assert "/login" in response["Location"] or "accounts" in response["Location"]


def test_resolving_records_who_and_when(client):
    pa = make_pa(client)
    report = _report()
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    assert report.status == IssueReport.Status.RESOLVED
    assert report.resolved_by == pa
    assert report.resolved_at is not None


def test_resolving_twice_preserves_the_original_triager(client):
    first = make_pa(client, username="first-pa")
    report = _report()
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    original_at = report.resolved_at
    make_pa(client, username="second-pa")
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.RESOLVED},
    )
    report.refresh_from_db()
    assert report.resolved_by == first
    assert report.resolved_at == original_at


def test_reopening_clears_the_resolution(client):
    make_pa(client)
    report = _report(status=IssueReport.Status.RESOLVED)
    client.post(
        reverse("support:report_set_status", args=[report.pk]),
        {"status": IssueReport.Status.OPEN},
    )
    report.refresh_from_db()
    assert report.status == IssueReport.Status.OPEN
    assert report.resolved_by is None
    assert report.resolved_at is None


def test_a_bogus_status_is_400_and_leaves_the_row_alone(client):
    make_pa(client)
    report = _report()
    response = client.post(
        reverse("support:report_set_status", args=[report.pk]), {"status": "banana"}
    )
    assert response.status_code == 400
    report.refresh_from_db()
    assert report.status == IssueReport.Status.OPEN


def test_a_pa_can_delete_a_report_and_its_file(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        response = client.post(
            reverse("support:report_delete", args=[report.pk]), {"status": "all"}
        )
        assert response.status_code == 302
        # The filter must survive the round-trip; dropping the hidden input and
        # its validation would otherwise leave this test green.
        assert response["Location"].endswith("?status=all")
        assert IssueReport.objects.count() == 0
        assert list(tmp_path.rglob("*.png")) == []


def test_a_bogus_delete_filter_falls_back_to_the_default(client):
    make_pa(client)
    report = _report()
    response = client.post(
        reverse("support:report_delete", args=[report.pk]), {"status": "../evil"}
    )
    assert response["Location"].endswith("?status=open")


def test_a_teacher_cannot_delete_and_get_does_not_delete(client):
    make_teacher(client)
    report = _report()
    assert client.post(
        reverse("support:report_delete", args=[report.pk])
    ).status_code == 403
    make_pa(client)
    assert client.get(
        reverse("support:report_delete", args=[report.pk])
    ).status_code == 405
    assert IssueReport.objects.count() == 1


def test_screenshot_404s_when_absent_or_missing_from_disk(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        empty = _report()
        assert client.get(
            reverse("support:screenshot", args=[empty.pk])
        ).status_code == 404
        withfile = _report()
        withfile.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        path = withfile.screenshot.path
        import os

        os.remove(path)
        assert client.get(
            reverse("support:screenshot", args=[withfile.pk])
        ).status_code == 404


def test_screenshot_is_served_inline_with_a_server_derived_type(client, tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        make_pa(client)
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        response = client.get(reverse("support:screenshot", args=[report.pk]))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["Content-Disposition"].startswith("inline")


def test_a_hostile_page_url_is_never_an_href(client):
    make_pa(client)
    report = _report(page_url="javascript:alert(1)")
    body = client.get(
        reverse("support:report_detail", args=[report.pk])
    ).content.decode()
    assert 'href="javascript:' not in body


def test_an_unmailed_report_is_flagged_in_the_detail_page(client):
    make_pa(client)
    report = _report()
    body = client.get(
        reverse("support:report_detail", args=[report.pk])
    ).content.decode()
    assert "not emailed" in body.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_triage.py -v`
Expected: `NoReverseMatch` for `support:report_list`.

- [ ] **Step 3: Add the permissions**

In `institution/roles.py`, add after `SUBJECT_PERMS`:

```python
# Issue reporting (Phase: support). change_supportsettings guards the Support
# settings tab's POST and the Allowed reporters page — it must be seeded here or
# Django creates it, attaches it to nobody, and every PA 403s on Save.
SUPPORT_PERMS = [
    "support.view_issuereport",
    "support.change_issuereport",
    "support.delete_issuereport",
    "support.view_supportsettings",
    "support.change_supportsettings",
]
```

and add `*SUPPORT_PERMS,` to the end of `PLATFORM_ADMIN_PERMS`.

- [ ] **Step 4: Write the views and URLs**

`support/views_manage.py`:

```python
"""PA triage surface. Every view stacks login_required above permission_required.

raise_exception=True is mandatory, not decoration: permission_required defaults
to False, which redirects to LOGIN_URL (302) instead of raising PermissionDenied,
and every 403 this feature asserts would silently become a 302. login_required on
top gives an anonymous visitor — a stale bookmark, or the report_detail link this
design puts in every email opened after the session expired — log-in-then-return
rather than a bare 403.
"""

import mimetypes

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from support.constants import LIST_PAGE_SIZE
from support.models import IssueReport
from support.policy import role_labels
from support.telemetry import safe_page_link
from support.telemetry import telemetry_rows

STATUS_FILTERS = ("open", "resolved", "all")
DEFAULT_FILTER = "open"


def _filter_value(request):
    value = request.GET.get("status", DEFAULT_FILTER)
    return value if value in STATUS_FILTERS else DEFAULT_FILTER


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def report_list(request):
    status = _filter_value(request)
    reports = IssueReport.objects.all()
    if status != "all":
        reports = reports.filter(status=status)
    page = Paginator(reports, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    for report in page:
        report.role_labels = role_labels(report.reporter_roles)
    return render(
        request,
        "support/manage/report_list.html",
        {"page_obj": page, "status": status, "status_filters": STATUS_FILTERS},
    )


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def report_detail(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    return render(
        request,
        "support/manage/report_detail.html",
        {
            "report": report,
            "roles": role_labels(report.reporter_roles),
            "telemetry": telemetry_rows(report.telemetry),
            "page_link": safe_page_link(report.page_url),
            "status": _filter_value(request),
        },
    )


@require_POST
@login_required
@permission_required("support.change_issuereport", raise_exception=True)
def report_set_status(request, pk):
    target = request.POST.get("status")
    if target not in (IssueReport.Status.OPEN, IssueReport.Status.RESOLVED):
        return HttpResponseBadRequest("unknown status")
    report = get_object_or_404(IssueReport, pk=pk)
    if report.status != target:
        # A no-op on the current status must not overwrite an existing
        # resolved_by/resolved_at and lose who actually triaged it.
        report.status = target
        if target == IssueReport.Status.RESOLVED:
            report.resolved_by = request.user
            report.resolved_at = timezone.now()
        else:
            report.resolved_by = None
            report.resolved_at = None
        report.save(update_fields=["status", "resolved_by", "resolved_at"])
    return redirect("support:report_detail", pk=pk)


@require_POST
@login_required
@permission_required("support.delete_issuereport", raise_exception=True)
def report_delete(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    report.delete()  # post_delete removes the screenshot file
    # The filter arrives as a hidden input on the confirmation form, validated
    # against the same set — never HTTP_REFERER, which is an open redirect.
    status = request.POST.get("status")
    status = status if status in STATUS_FILTERS else DEFAULT_FILTER
    return redirect(f"{reverse('support:report_list')}?status={status}")


@login_required
@permission_required("support.view_issuereport", raise_exception=True)
def screenshot(request, pk):
    report = get_object_or_404(IssueReport, pk=pk)
    if not report.screenshot:
        raise Http404("no screenshot")
    try:
        handle = report.screenshot.open("rb")
    except (FileNotFoundError, OSError) as exc:
        # A DB restored against a fresh volume must 404, not 500.
        raise Http404("screenshot missing from storage") from exc
    # Content type from the STORED extension, never from anything the client sent.
    content_type = (
        mimetypes.guess_type(report.screenshot.name.lower())[0]
        or "application/octet-stream"
    )
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = "inline"
    return response
```

Extend `support/urls.py`:

```python
from django.urls import path

from support import views
from support import views_manage

app_name = "support"

urlpatterns = [
    path("report/", views.report_create, name="report_create"),
    path("manage/issue-reports/", views_manage.report_list, name="report_list"),
    path(
        "manage/issue-reports/<int:pk>/",
        views_manage.report_detail,
        name="report_detail",
    ),
    path(
        "manage/issue-reports/<int:pk>/status/",
        views_manage.report_set_status,
        name="report_set_status",
    ),
    path(
        "manage/issue-reports/<int:pk>/delete/",
        views_manage.report_delete,
        name="report_delete",
    ),
    path(
        "manage/issue-reports/<int:pk>/screenshot/",
        views_manage.screenshot,
        name="screenshot",
    ),
]
```

- [ ] **Step 5: Write the templates**

`support/templates/support/manage/report_list.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Issue reports" %}{% endblock %}
{% block content %}
<h1>{% trans "Issue reports" %}</h1>
<nav class="filter-row" aria-label="{% trans 'Filter by status' %}">
  {% for value in status_filters %}
    <a href="?status={{ value }}" aria-current="{% if value == status %}true{% else %}false{% endif %}">
      {% if value == "open" %}{% trans "Open" %}
      {% elif value == "resolved" %}{% trans "Resolved" %}
      {% else %}{% trans "All" %}{% endif %}
    </a>
  {% endfor %}
</nav>
<div class="scroll-x">
<table class="ledger">
  <thead>
    <tr>
      <th>{% trans "When" %}</th><th>{% trans "Reporter" %}</th>
      <th>{% trans "Role" %}</th><th>{% trans "Description" %}</th>
      <th>{% trans "Screenshot" %}</th><th>{% trans "Status" %}</th>
    </tr>
  </thead>
  <tbody>
  {% for report in page_obj %}
    <tr>
      <td>{{ report.created_at }}</td>
      <td><a href="{% url 'support:report_detail' report.pk %}">{{ report.reporter_label }}</a></td>
      <td>{{ report.role_labels|join:", " }}</td>
      <td>{{ report.description|truncatechars:80 }}</td>
      <td>{% if report.screenshot %}{% trans "Yes" %}{% endif %}</td>
      <td>
        {{ report.get_status_display }}
        {% if not report.emailed_at %} — {% trans "not emailed" %}{% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="6">{% trans "No reports." %}</td></tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
```

`support/templates/support/manage/report_detail.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Issue report" %}{% endblock %}
{% block content %}
<h1>{% trans "Issue report" %} #{{ report.pk }}</h1>

{% if not report.emailed_at %}
  <p class="alert alert--warning">
    {% trans "Not emailed — no message went out for this report." %}
  </p>
{% endif %}

<dl>
  <dt>{% trans "Reported by" %}</dt>
  <dd>{{ report.reporter_label }}{% if roles %} ({{ roles|join:", " }}){% endif %}</dd>
  <dt>{% trans "Page" %}</dt>
  <dd>
    {{ report.page_title }}<br>
    {% comment %}safe_page_link is None for a javascript: or foreign-host URL, so a
    hostile page_url prints as inert escaped text.{% endcomment %}
    {% if page_link %}<a href="{{ page_link }}">{{ report.page_url }}</a>
    {% else %}{{ report.page_url }}{% endif %}
  </dd>
  {% for key, label, value in telemetry %}
  <dt>{{ label }}</dt><dd>{{ value }}</dd>
  {% endfor %}
</dl>

<h2>{% trans "Description" %}</h2>
<p>{{ report.description|linebreaksbr }}</p>

{% if report.screenshot %}
<h2>{% trans "Screenshot" %}</h2>
<a href="{% url 'support:screenshot' report.pk %}">
  <img src="{% url 'support:screenshot' report.pk %}" alt="{% trans 'Screenshot attached to this report' %}" style="max-width:100%">
</a>
{% endif %}

<form method="post" action="{% url 'support:report_set_status' report.pk %}">
  {% csrf_token %}
  {% if report.status == "open" %}
    <input type="hidden" name="status" value="resolved">
    <button type="submit">{% trans "Mark resolved" %}</button>
  {% else %}
    <input type="hidden" name="status" value="open">
    <button type="submit">{% trans "Reopen" %}</button>
  {% endif %}
</form>

{% comment %}The confirmation text goes in a data- attribute, NOT inline in an
onsubmit JS string literal: Task 12 supplies Polish, and a translation containing
an apostrophe would terminate the literal and break the page. Django escapes the
attribute for you. A small handler in support.js reads [data-confirm] and calls
confirm(). Note for any future e2e: Playwright AUTO-DISMISSES confirm() unless the
test registers page.on("dialog", ...), so a delete e2e without that listener
silently does nothing and still passes.{% endcomment %}
<form method="post" action="{% url 'support:report_delete' report.pk %}"
      data-confirm="{% trans 'Delete this report and its screenshot?' %}">
  {% csrf_token %}
  <input type="hidden" name="status" value="{{ status }}">
  <button type="submit" class="btn--danger">{% trans "Delete" %}</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Add the Admin-menu item**

In `templates/base.html`, inside the existing `.menu__panel` for the admin menu, after the People entry:

```django
{% if perms.support.view_issuereport %}
<a class="menu__item" href="{% url 'support:report_list' %}">{% trans "Issue reports" %}</a>
{% endif %}
```

Leave the outer `.app-nav__admin` condition unchanged: `view_issuereport` is PA-only and every PA already satisfies that chain via `perms.institution.change_institution`, so adding a disjunct would be dead.

- [ ] **Step 7: Run to verify pass**

Run: `uv run pytest tests/test_support_triage.py -v`
Expected: all pass. (`tests/test_support_emails.py` does not exist yet — Task 6 adds it, and relies on the `support:report_detail` name this task just registered.)

- [ ] **Step 8: Falsify two**

1. Drop `raise_exception=True` from `report_list` → `test_a_teacher_gets_403_not_a_login_redirect` must FAIL with 302. Restore by hand.
2. Remove the `if report.status != target:` guard → `test_resolving_twice_preserves_the_original_triager` must FAIL. Restore by hand.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check --no-cache support institution tests/test_support_triage.py
uv run ruff format --check support institution tests/test_support_triage.py
git add support institution/roles.py templates/base.html tests/test_support_triage.py
git commit -m "feat(support): PA triage list, detail, status, delete and private screenshot view"
```

---

### Task 6: Email delivery

**Files:**
- Modify: `support/emails.py`
- Create: `support/templates/support/email/issue_report.txt`, `support/templates/support/email/issue_report.html`
- Test: `tests/test_support_emails.py`

**Interfaces:**
- Consumes: `support.telemetry.telemetry_rows/safe_page_link`, `support.policy.role_labels`, `core.services.get_site_config`
- Produces: `support.emails.send_issue_report_email(report)`, `support.emails.resolve_recipients() -> list[str]`, `support.emails._absolute_url(path) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_emails.py`:

```python
"""Recipient resolution, envelope shape and delivery bookkeeping."""

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth.models import Group as AuthGroup
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from institution.models import Institution
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from support.emails import send_issue_report_email
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import UserFactory
from tests.test_support_models import _png_bytes

pytestmark = pytest.mark.django_db


def _pa(email="pa@school.example", **kwargs):
    seed_roles()
    user = UserFactory(email=email, **kwargs)
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _report(**kwargs):
    kwargs.setdefault("description", "It broke")
    kwargs.setdefault("reporter_label", "Ada (ada) <ada@school.example>")
    return IssueReport.objects.create(**kwargs)


def test_recipients_union_pas_and_extra_addresses_in_bcc():
    _pa(email="pa@school.example")
    row = SupportSettings.load()
    row.extra_emails = ["helpdesk@school.example"]
    row.save()
    send_issue_report_email(_report())
    message = mail.outbox[0]
    assert set(message.bcc) == {"pa@school.example", "helpdesk@school.example"}
    assert message.to == [dj_settings.DEFAULT_FROM_EMAIL]


def test_recipients_are_deduplicated_case_insensitively():
    _pa(email="pa@school.example")
    row = SupportSettings.load()
    row.extra_emails = ["PA@School.Example"]
    row.save()
    send_issue_report_email(_report())
    assert len(mail.outbox[0].bcc) == 1


def test_an_inactive_pa_and_an_emailless_pa_are_not_recipients():
    _pa(email="active@school.example")
    _pa(email="inactive@school.example", is_active=False)
    _pa(email="")
    send_issue_report_email(_report())
    assert mail.outbox[0].bcc == ["active@school.example"]


def test_no_recipients_means_no_message_and_no_emailed_at():
    """to=[DEFAULT_FROM_EMAIL] makes an empty bcc a perfectly valid message, so
    without the short-circuit send() would return 1 and emailed_at would lie."""
    report = _report()
    send_issue_report_email(report)
    report.refresh_from_db()
    assert mail.outbox == []
    assert report.emailed_at is None


def test_a_newline_in_the_display_name_cannot_split_the_subject():
    _pa()
    report = _report(reporter_label="Ada\r\nBcc: evil@x.test")
    send_issue_report_email(report)
    assert "\n" not in mail.outbox[0].subject
    assert "\r" not in mail.outbox[0].subject


def test_the_subject_carries_the_report_id():
    """Without it every report from one reporter shares a byte-identical subject
    and mail clients thread them into an undifferentiated pile."""
    _pa()
    report = _report()
    send_issue_report_email(report)
    assert str(report.pk) in mail.outbox[0].subject


def test_the_body_links_to_the_report_detail_page():
    _pa()
    report = _report()
    send_issue_report_email(report)
    path = reverse("support:report_detail", args=[report.pk])
    assert path in mail.outbox[0].body


def test_the_screenshot_is_attached(tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        _pa()
        report = _report()
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        send_issue_report_email(report)
        assert len(mail.outbox[0].attachments) == 1


def test_emailed_at_is_stamped_without_clobbering_a_concurrent_status_change():
    _pa()
    report = _report()
    IssueReport.objects.filter(pk=report.pk).update(
        status=IssueReport.Status.RESOLVED
    )
    send_issue_report_email(report)  # `report` still holds status=open in memory
    report.refresh_from_db()
    assert report.emailed_at is not None
    assert report.status == IssueReport.Status.RESOLVED


def test_a_send_that_raises_still_leaves_the_report(monkeypatch):
    _pa()
    report = _report()

    def _boom(self, *args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "django.core.mail.EmailMultiAlternatives.send", _boom, raising=True
    )
    send_issue_report_email(report)  # must NOT raise
    report.refresh_from_db()
    assert report.emailed_at is None
    assert IssueReport.objects.count() == 1


def test_the_message_uses_the_institution_language_not_the_reporters():
    """An A/B, because a single English check proves nothing: English is both the
    institution default AND the untranslated msgid, so the mutant ("override to
    the reporter's language") would produce an identical subject.

    Run this AFTER Task 12 supplies the Polish catalog. Assert on the observed
    active language rather than catalog text so it does not re-break whenever the
    Polish wording is edited.
    """
    from django.utils import translation

    from core.services import invalidate_site_config

    observed = {}
    real_render = support.emails.render_to_string

    def _spy(template, ctx):
        observed["language"] = translation.get_language()
        return real_render(template, ctx)

    inst = Institution.load()
    inst.default_language = "pl"
    inst.save()
    invalidate_site_config()

    reporter = UserFactory(username="polly", email="polly@school.example")
    _pa()
    with translation.override("en"):  # the REPORTER's language, deliberately not pl
        with mock.patch.object(support.emails, "render_to_string", _spy):
            send_issue_report_email(_report(reporter=reporter))
    assert observed["language"] == "pl"


def test_a_javascript_page_url_is_never_an_href_in_the_email():
    _pa()
    send_issue_report_email(_report(page_url="javascript:alert(1)"))
    html = mail.outbox[0].alternatives[0][0]
    assert 'href="javascript:' not in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_emails.py -v`
Expected: failures — the stub sends nothing.

- [ ] **Step 3: Write the email module**

Replace `support/emails.py`:

```python
"""Report notification email.

Built like notifications/emails.py (EmailMultiAlternatives + render_to_string +
translation.override with EAGER gettext so interpolation resolves inside the
block), with two deliberate divergences, noted here so a later reviewer does not
"restore consistency" and undo them:

  * ONE bcc'd message rather than one message per recipient — the audience is a
    fixed admin list, not a per-user fan-out.
  * The language is the institution default, not the recipient's: a single
    message can only have one language.
"""

import logging

from allauth.account import app_settings as account_settings
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils import translation
from django.utils.translation import gettext as _

from core.services import get_site_config
from institution.roles import PLATFORM_ADMIN
from support.models import SupportSettings
from support.policy import role_labels
from support.telemetry import safe_page_link
from support.telemetry import telemetry_rows

logger = logging.getLogger(__name__)
User = get_user_model()


def _absolute_url(path):
    """Absolute URL from the current Site (never a request Host header, so an
    emailed link cannot be host-spoofed). Local rather than importing
    notifications.emails._absolute_url, which is a private name in another app."""
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"


def resolve_recipients():
    """Active PA-Group members with an email, unioned with extra_emails,
    de-duplicated case-insensitively. Superusers outside the Group are NOT
    included, matching accounts.services.is_last_active_platform_admin."""
    addresses = list(
        User.objects.filter(is_active=True, groups__name=PLATFORM_ADMIN)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    row = SupportSettings.objects.filter(pk=1).first()
    if row is not None:
        addresses += [a for a in (row.extra_emails or []) if a]
    seen, unique = set(), []
    for address in addresses:
        key = address.lower()
        if key not in seen:
            seen.add(key)
            unique.append(address)
    return unique


def send_issue_report_email(report):
    """Never raises. See the module note in Task 4's stub: an exception escaping
    here would reach report_create's rollback `except` — which cannot tell a
    rollback from a post-commit failure — and delete a COMMITTED report's
    screenshot while 500ing a reporter whose report was in fact saved."""
    try:
        recipients = resolve_recipients()
        if not recipients:
            logger.warning(
                "issue report %s has no resolvable recipients; not sending",
                report.pk,
            )
            return
        cfg = get_site_config()
        with translation.override(cfg["default_language"]):
            reporter = " ".join((report.reporter_label or "").split())
            institution = " ".join((cfg["name"] or "").split())
            subject = _("[%(institution)s] Issue report #%(pk)s from %(who)s") % {
                "institution": institution,
                "pk": report.pk,
                "who": reporter,
            }
            ctx = {
                "report": report,
                "detail_url": _absolute_url(
                    reverse("support:report_detail", args=[report.pk])
                ),
                "roles": role_labels(report.reporter_roles),
                "telemetry": telemetry_rows(report.telemetry),
                "page_link": safe_page_link(report.page_url),
                "site": cfg,
            }
            text = render_to_string("support/email/issue_report.txt", ctx)
            html = render_to_string("support/email/issue_report.html", ctx)
        reply_to = [report.reporter.email] if (
            report.reporter and report.reporter.email
        ) else None
        message = EmailMultiAlternatives(
            subject,
            text,
            None,
            # Recipients go in bcc: putting them in `to` would disclose each PA's
            # personal address to a helpdesk alias and to every other recipient.
            to=[dj_settings.DEFAULT_FROM_EMAIL],
            bcc=recipients,
            reply_to=reply_to,
        )
        message.attach_alternative(html, "text/html")
        if report.screenshot:
            report.screenshot.open("rb")
            try:
                message.attach(
                    report.screenshot.name.rsplit("/", 1)[-1],
                    report.screenshot.read(),
                )
            finally:
                report.screenshot.close()
        message.send()
        report.emailed_at = timezone.now()
        # update_fields: a bare save() from a post-commit callback would rewrite
        # every field of a row a PA may have resolved in the meantime.
        report.save(update_fields=["emailed_at"])
    except Exception:  # noqa: BLE001 — must never escape the on_commit hook
        logger.exception("issue report email delivery failed (report %s)", report.pk)
```

- [ ] **Step 4: Write the email templates**

`support/templates/support/email/issue_report.txt`:

```django
{% load i18n %}{% trans "A new issue report was submitted." %}

{% trans "View it here" %}: {{ detail_url }}

{% trans "Reported by" %}: {{ report.reporter_label }}{% if roles %} ({{ roles|join:", " }}){% endif %}
{% trans "Page" %}: {{ report.page_title }}
{% trans "URL" %}: {{ report.page_url }}

{% trans "Description" %}:
{{ report.description }}

{% for key, label, value in telemetry %}{{ label }}: {{ value }}
{% endfor %}
```

`support/templates/support/email/issue_report.html`:

```django
{% load i18n %}
<p>{% trans "A new issue report was submitted." %}</p>
<p><a href="{{ detail_url }}">{% trans "View it here" %}</a></p>
<p>
  <strong>{% trans "Reported by" %}:</strong> {{ report.reporter_label }}
  {% if roles %}({{ roles|join:", " }}){% endif %}
</p>
<p>
  <strong>{% trans "Page" %}:</strong> {{ report.page_title }}<br>
  {% comment %}safe_page_link returns None for a javascript: or foreign-host URL,
  so a hostile page_url renders as inert escaped text. This is the one output
  that travels outside the login wall.{% endcomment %}
  {% if page_link %}<a href="{{ page_link }}">{{ report.page_url }}</a>
  {% else %}{{ report.page_url }}{% endif %}
</p>
<p><strong>{% trans "Description" %}:</strong></p>
<p>{{ report.description|linebreaksbr }}</p>
<table>
  {% for key, label, value in telemetry %}
  <tr><th align="left">{{ label }}</th><td>{{ value }}</td></tr>
  {% endfor %}
</table>
```

These templates reference `support:report_detail`, registered by Task 5. That is why triage comes first: `send_issue_report_email` calls `reverse` at runtime, so every one of this task's tests would raise `NoReverseMatch` without it.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_support_emails.py -v`
Expected: all pass.

- [ ] **Step 6: Falsify three**

1. Move `bcc=recipients` to `to=recipients` (dropping the `to=[DEFAULT_FROM_EMAIL]`) → `test_recipients_union_pas_and_extra_addresses_in_bcc` must FAIL. Restore by hand.
2. Delete the `if not recipients:` short-circuit → `test_no_recipients_means_no_message_and_no_emailed_at` must FAIL. Restore by hand.
3. Change `report.save(update_fields=["emailed_at"])` to `report.save()` → `test_emailed_at_is_stamped_without_clobbering_a_concurrent_status_change` must FAIL. Restore by hand.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache support tests/test_support_emails.py
uv run ruff format --check support tests/test_support_emails.py
git add support tests/test_support_emails.py
git commit -m "feat(support): email delivery to Platform Admins and extra addresses"
```

---

### Task 7: The Allowed reporters page

**Files:**
- Modify: `support/forms.py`, `support/views_manage.py`, `support/urls.py`
- Create: `support/templates/support/manage/reporters.html`
- Test: `tests/test_support_reporters_page.py`

**Interfaces:**
- Produces: `support.forms.ReporterPickerForm`, URL name `support:reporters`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_reporters_page.py`:

```python
"""The dedicated roster page for individually-granted reporters."""

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.core.cache import cache
from django.urls import reverse

from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER
from institution.roles import seed_roles
from support.models import SupportSettings
from support.policy import can_report
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _teacher(username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=TEACHER))
    return user


def test_the_first_ever_save_creates_the_row_and_grants_immediately(client):
    make_pa(client)
    teacher = _teacher("grantme")
    assert SupportSettings.objects.count() == 0
    assert can_report(teacher) is False
    response = client.post(
        reverse("support:reporters"), {"extra_reporters": [teacher.pk]}
    )
    assert response.status_code == 302
    assert SupportSettings.objects.count() == 1
    assert can_report(teacher) is True


def test_an_inactive_existing_grant_survives_a_save_that_adds_someone_else(client):
    """Mutant: scope the roster queryset to active non-PA users alone — the
    absent user is then dropped by save_m2m and the grant is silently revoked."""
    make_pa(client)
    keep = _teacher("keepme")
    row = SupportSettings.load()
    row.extra_reporters.add(keep)
    keep.is_active = False
    keep.save()
    newcomer = _teacher("newcomer")
    client.post(
        reverse("support:reporters"),
        {"extra_reporters": [keep.pk, newcomer.pk]},
    )
    assert set(
        SupportSettings.load().extra_reporters.values_list("pk", flat=True)
    ) == {keep.pk, newcomer.pk}


def test_an_already_selected_user_outside_the_base_roster_is_still_rendered(client):
    make_pa(client)
    promoted = _teacher("promoted")
    SupportSettings.load().extra_reporters.add(promoted)
    promoted.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    body = client.get(reverse("support:reporters")).content.decode()
    # Assert on the pk, not the username: UserFactory sets display_name from
    # Faker and User.__str__ returns display_name or username, so
    # CheckboxSelectMultiple renders the Faker name and the username never
    # appears — the test would fail on a correct build.
    assert f'value="{promoted.pk}"' in body


def test_an_out_of_roster_grant_is_marked_for_the_muted_note(client):
    """The spec requires these to render "checked, with a muted note explaining
    why they are listed". Mutant: drop the create_option override — the grant
    still renders, but indistinguishable from an ordinary roster member."""
    make_pa(client)
    ordinary = _teacher("ordinary")
    stale_grant = _teacher("deactivated")
    row = SupportSettings.load()
    row.extra_reporters.add(ordinary, stale_grant)
    stale_grant.is_active = False
    stale_grant.save()
    body = client.get(reverse("support:reporters")).content.decode()
    assert body.count("data-out-of-roster") == 1


def test_a_teacher_cannot_open_or_save_the_page(client):
    make_teacher(client)
    assert client.get(reverse("support:reporters")).status_code == 403
    assert client.post(reverse("support:reporters"), {}).status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_reporters_page.py -v`
Expected: `NoReverseMatch: 'reporters'`.

- [ ] **Step 3: Write the form**

Append to `support/forms.py`:

```python
class ReporterPickerForm(forms.ModelForm):
    """The roster of individually-granted reporters.

    The queryset is active non-PA users UNIONED with whoever is currently
    selected. Scoped to active non-PA users alone, an already-granted user who
    has since been deactivated or promoted to PA would be absent from the
    rendered list, and the next save_m2m() would silently REVOKE them — a PA
    opening the page to add one person would drop an unrelated grant.
    """

    class Meta:
        model = SupportSettings
        fields = ["extra_reporters"]
        widgets = {"extra_reporters": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        selected = list(self.instance.extra_reporters.values_list("pk", flat=True))
        base = User.objects.filter(is_active=True).exclude(
            groups__name=PLATFORM_ADMIN
        )
        self.fields["extra_reporters"].queryset = (
            User.objects.filter(Q(pk__in=base.values("pk")) | Q(pk__in=selected))
            .distinct()
            .order_by("display_name", "username")
        )
        self.fields["extra_reporters"].required = False
        self.out_of_roster = set(selected) - set(
            base.values_list("pk", flat=True)
        )

    def create_option(self, name, value, *args, **kwargs):
        """Mark grants that survive only because of the union.

        The spec requires already-selected users outside the base roster to render
        "checked, with a muted note explaining why they are listed", and a plain
        CheckboxSelectMultiple cannot express a per-option note. This tags them so
        the template can. Django passes `value` as a ModelChoiceIteratorValue, so
        compare its .value.
        """
        option = super().create_option(name, value, *args, **kwargs)
        pk = getattr(value, "value", value)
        if pk in self.out_of_roster:
            option["attrs"]["data-out-of-roster"] = "1"
        return option
```

`create_option` belongs on the **widget**, not the form, so either subclass
`CheckboxSelectMultiple` and give it an `out_of_roster` attribute set from the
form's `__init__`, or render the note from a separate list in the template. Pick
one and keep the styling muted; the paired test asserts the marker is present for
a deactivated grant and absent for an ordinary one.

Add to `support/forms.py` imports:

```python
from django.contrib.auth import get_user_model
from django.db.models import Q

from institution.roles import PLATFORM_ADMIN
```

- [ ] **Step 4: Write the view and URL**

Append to `support/views_manage.py`:

```python
@login_required
@permission_required("support.change_supportsettings", raise_exception=True)
def reporters(request):
    # load() on BOTH methods, which is a deliberate exception to the spec's
    # "read paths use filter(pk=1).first()" rule — state it rather than let it
    # look like an oversight. ReporterPickerForm.__init__ reads
    # instance.extra_reporters to build the roster union, and an M2M access on an
    # unsaved instance raises ValueError. The page is PA-only and reached
    # deliberately, so materialising pk=1 here costs one row on first visit and
    # never happens on a student render.
    row = SupportSettings.load()
    if request.method == "POST":
        form = ReporterPickerForm(request.POST, instance=row)
        if form.is_valid():
            form.save()
            messages.success(request, _("Allowed reporters updated."))
            return redirect(f"{reverse('institution:settings')}?tab=support")
    else:
        form = ReporterPickerForm(instance=row)
    return render(request, "support/manage/reporters.html", {"form": form})
```

with the corresponding imports (`messages`, `reverse`, `gettext as _`, `ReporterPickerForm`, `SupportSettings`).

Add to `support/urls.py`:

```python
    path("manage/settings/support/reporters/", views_manage.reporters, name="reporters"),
```

- [ ] **Step 5: Write the template**

`support/templates/support/manage/reporters.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Allowed reporters" %}{% endblock %}
{% block content %}
<h1>{% trans "Allowed reporters" %}</h1>
<p>{% trans "These people can report an issue regardless of the audience setting." %}</p>
<form method="post">
  {% csrf_token %}
  {% comment %}The attribute set is load-bearing, not decorative. roster_filter.js
  iterates [data-roster] and RETURNS IMMEDIATELY unless the root contains
  [data-roster-list] — so a plain class="roster" with a bare search input leaves
  the box completely inert. This mirrors templates/grouping/group_form.html.
  [data-roster-count] and [data-roster-selected] are optional.{% endcomment %}
  <fieldset class="roster" data-roster>
    <legend>{% trans "Allowed reporters" %}</legend>
    <div class="roster-filter" data-roster-filter>
      <input type="search" data-roster-search
             placeholder="{% trans 'Type part of a name…' %}" autocomplete="off">
      <p class="roster-filter__count" data-roster-count aria-live="polite" hidden></p>
    </div>
    <div class="checkbox-list" data-roster-list>{{ form.extra_reporters }}</div>
  </fieldset>
  {{ form.extra_reporters.errors }}
  <button type="submit">{% trans "Save" %}</button>
  <a href="{% url 'institution:settings' %}?tab=support">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

The `data-roster-search` hook is bound by the existing `grouping/static/grouping/js/roster_filter.js`. Reuse it rather than writing a second filter — add to this template:

```django
{% block extra_js %}
<script src="{% static 'grouping/js/roster_filter.js' %}" defer></script>
{% endblock %}
```

with `{% load static %}` at the top alongside `{% load i18n %}`.

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_support_reporters_page.py -v`
Expected: all pass.

- [ ] **Step 7: Falsify one**

Change the queryset to the base one only (drop the `| Q(pk__in=selected)`) → `test_an_inactive_existing_grant_survives_a_save_that_adds_someone_else` must FAIL. Restore by hand.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --no-cache support tests/test_support_reporters_page.py
uv run ruff format --check support tests/test_support_reporters_page.py
git add support tests/test_support_reporters_page.py
git commit -m "feat(support): Allowed reporters roster page"
```

---

### Task 8: The Support settings tab

**Files:**
- Modify: `support/forms.py`, `institution/views_manage.py`, `institution/urls.py`, `templates/institution/manage/settings.html`, `templates/institution/manage/_tabs.html`
- Create: `templates/institution/manage/_support_tab.html`
- Test: `tests/test_support_settings_tab.py`

**Neither settings template iterates `TABS`.** `settings.html` hard-codes six `<div data-tab=…>` panels and `_tabs.html` hard-codes six `<a>` links. Adding `"support"` to the `TABS` tuple only makes `?tab=support` a *valid* value — without editing both templates the panel is never rendered and no tab link ever appears, so a PA has no route to it at all.

**Interfaces:**
- Consumes: `support.models.SupportSettings`, `support.constants.EXTRA_EMAILS_MAX`
- Produces: `support.forms.SupportSettingsForm`, URL name `institution:settings_support`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_settings_tab.py`:

```python
"""The seventh settings tab: audience + recipient addresses."""

import pytest
from django.urls import reverse

from support.constants import EXTRA_EMAILS_MAX
from support.models import SupportSettings
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def test_a_settings_get_with_no_row_renders_and_writes_nothing(client):
    """The read path must never touch extra_reporters on an unsaved fallback:
    an M2M access on an unsaved instance raises ValueError, and _settings_context
    builds EVERY panel on EVERY tab — so this would 500 a fresh install."""
    make_pa(client)
    response = client.get(reverse("institution:settings"))
    assert response.status_code == 200
    assert SupportSettings.objects.count() == 0


def test_a_pa_can_save_the_audience_and_addresses(client):
    make_pa(client)
    response = client.post(
        reverse("institution:settings_support"),
        {"audience": "teachers", "extra_emails": "One@X.test\n\nhelp@x.test\n"},
    )
    assert response.status_code == 302
    row = SupportSettings.load()
    assert row.audience == "teachers"
    assert row.extra_emails == ["one@x.test", "help@x.test"]  # lower-cased, blanks gone


def test_addresses_round_trip_one_per_line(client):
    """Mutant: leave `initial` as the raw JSON list — the PA then sees
    ['a@b.test'] in the textarea and the next save is rejected."""
    make_pa(client)
    client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": "a@b.test\nc@d.test"},
    )
    body = client.get(reverse("institution:settings"), {"tab": "support"}).content.decode()
    assert "a@b.test\nc@d.test" in body or "a@b.test&#x0A;c@d.test" in body


def test_a_malformed_address_is_rejected(client):
    """count() == 0 is the assertion, not a detail: binding to load() would
    get_or_create the singleton BEFORE is_valid() runs, so an invalid POST would
    silently materialise the row."""
    make_pa(client)
    response = client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": "not-an-address"},
    )
    assert response.status_code == 200  # re-rendered with the bound form
    assert SupportSettings.objects.count() == 0


def test_too_many_addresses_are_rejected(client):
    make_pa(client)
    addresses = "\n".join(f"a{i}@x.test" for i in range(EXTRA_EMAILS_MAX + 1))
    client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": addresses},
    )
    assert SupportSettings.objects.count() == 0


def test_a_get_redirects_and_writes_no_row(client):
    """Mutant: drop the GET guard — the view then binds an empty QueryDict and
    re-renders the settings page covered in validation errors."""
    make_pa(client)
    response = client.get(reverse("institution:settings_support"))
    assert response.status_code == 302
    assert SupportSettings.objects.count() == 0


def test_the_support_tab_link_is_rendered(client):
    """Mutant: add "support" to TABS but leave _tabs.html alone — ?tab=support
    becomes valid while no link to it ever appears."""
    make_pa(client)
    body = client.get(reverse("institution:settings")).content.decode()
    assert "?tab=support" in body


def test_the_panel_names_the_platform_admins_who_receive_reports(client):
    pa = make_pa(client)
    pa.email = "chief@school.example"
    pa.save()
    body = client.get(reverse("institution:settings")).content.decode()
    assert "chief@school.example" in body


def test_a_teacher_cannot_save_the_support_tab(client):
    make_teacher(client)
    response = client.post(
        reverse("institution:settings_support"), {"audience": "all", "extra_emails": ""}
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_settings_tab.py -v`
Expected: `NoReverseMatch: 'settings_support'`.

- [ ] **Step 3: Write the form**

Append to `support/forms.py`:

```python
class SupportSettingsForm(forms.ModelForm):
    """Audience + recipient addresses. Carries NO M2M field: _settings_context
    renders every panel on every settings render, so a per-user roster here would
    materialise one checkbox per active user on every GET of the Branding tab.
    The roster lives on its own page (support:reporters)."""

    audience = forms.ChoiceField(
        choices=SupportSettings.Audience.choices,
        widget=forms.RadioSelect,
        label=_("Who can report an issue"),
    )
    # Overridden explicitly: left to the ModelForm default a JSONField yields
    # forms.JSONField, whose textarea expects literal JSON — a field that looks
    # right and rejects everything a PA types.
    extra_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("Also send reports to"),
        help_text=_(
            "One address per line. These addresses receive the full report, "
            "including any attached screenshot, which may contain student data."
        ),
    )

    class Meta:
        model = SupportSettings
        fields = ["audience", "extra_emails"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            stored = (self.instance.extra_emails or []) if self.instance else []
            self.initial["extra_emails"] = "\n".join(stored)

    def clean_extra_emails(self):
        raw = self.cleaned_data.get("extra_emails") or ""
        validate = EmailValidator()
        seen, addresses = set(), []
        for line in raw.splitlines():
            address = line.strip().lower()
            if not address:
                continue
            validate(address)
            if address not in seen:
                seen.add(address)
                addresses.append(address)
        if len(addresses) > EXTRA_EMAILS_MAX:
            raise forms.ValidationError(
                _("At most %(count)d addresses.") % {"count": EXTRA_EMAILS_MAX}
            )
        return addresses
```

Add to the imports at the top of `support/forms.py`:

```python
from django.core.validators import EmailValidator

from support.constants import EXTRA_EMAILS_MAX
from support.models import SupportSettings
```

- [ ] **Step 4: Wire the tab**

In `institution/views_manage.py`:

- add `"support"` to `TABS`;
- import `from support.forms import SupportSettingsForm` and `from support.models import SupportSettings`;
- add `support=None` to `_settings_context`'s keyword-only arguments and, in the returned context, build it read-only when not supplied:

```python
    support_row = SupportSettings.objects.filter(pk=1).first() or SupportSettings()
    # Count through the JOIN TABLE, never support_row.extra_reporters.count():
    # before the first save support_row is unsaved, and an M2M access on an
    # unsaved instance raises ValueError — 500ing every settings tab on a fresh
    # install.
    extra_reporter_count = SupportSettings.extra_reporters.through.objects.filter(
        supportsettings_id=1
    ).count()
    # Named, not merely counted: the panel must show WHICH addresses receive
    # reports automatically. Reuses the one resolver so the panel and the mailer
    # can never disagree about who "the Platform Admins" are.
    from support.emails import resolve_pa_recipients

    auto_recipients = resolve_pa_recipients()
```

adding `"support": support or SupportSettingsForm(instance=support_row)`, `"extra_reporter_count": extra_reporter_count` and `"auto_recipients": auto_recipients` to the context dict.

Split `support/emails.py`'s `resolve_recipients()` into two, so the panel can name the automatic half without pulling in `extra_emails`:

```python
def resolve_pa_recipients():
    """Active PA-Group members with an email. The automatic half."""
    return list(
        User.objects.filter(is_active=True, groups__name=PLATFORM_ADMIN)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def resolve_recipients():
    """resolve_pa_recipients() unioned with extra_emails, de-duplicated
    case-insensitively."""
    addresses = resolve_pa_recipients()
    row = SupportSettings.objects.filter(pk=1).first()
    if row is not None:
        addresses += [a for a in (row.extra_emails or []) if a]
    seen, unique = set(), []
    for address in addresses:
        key = address.lower()
        if key not in seen:
            seen.add(key)
            unique.append(address)
    return unique
```

replacing the single `resolve_recipients` shown in Task 6.

- add the view:

```python
@login_required
@permission_required("support.change_supportsettings", raise_exception=True)
def settings_support(request):
    # GET guard first, matching settings_integrations: without it a GET binds an
    # empty QueryDict and re-renders the settings page covered in validation
    # errors.
    if request.method == "GET":
        return redirect(_index_url("support"))
    # Bind to a READ-ONLY instance, not load(). load() is get_or_create, which
    # writes pk=1 before is_valid() is ever called — so an invalid POST would
    # materialise the singleton, and the two rejection tests below (which assert
    # count() == 0) would fail against this very view. SupportSettingsForm holds
    # no M2M, so an unsaved instance is safe here, and save() forces pk=1.
    row = SupportSettings.objects.filter(pk=1).first() or SupportSettings()
    form = SupportSettingsForm(request.POST, instance=row)
    if form.is_valid():
        form.save()
        messages.success(request, _("Support settings saved."))
        return redirect(_index_url("support"))
    return render(
        request,
        "institution/manage/settings.html",
        _settings_context(request, Institution.load(), "support", support=form),
    )
```

Reuse the module's existing `_index_url` helper rather than an inline f-string, as the other tab views do.

Also update `_settings_context`'s docstring: it currently says "Assemble the **six**-form context" and "settings.html renders all **six** panels". Both become seven.

In `institution/urls.py`, add:

```python
    path(
        "manage/settings/support/",
        views_manage.settings_support,
        name="settings_support",
    ),
```

- [ ] **Step 5: Write the panel template and wire it into both settings templates**

Add the seventh panel to `templates/institution/manage/settings.html`, after the integrations `<div>`:

```django
  <div data-tab="support" {% if active_tab != "support" %}hidden{% endif %}>
    {% include "institution/manage/_support_tab.html" %}
  </div>
```

Add the seventh link to `templates/institution/manage/_tabs.html`, after the Integrations anchor:

```django
  <a class="settings__tab{% if active_tab == 'support' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=support">{% trans "Support" %}</a>
```

Then create `templates/institution/manage/_support_tab.html` — note the `_<tab>_tab.html` name, matching all six siblings:

```django
{% load i18n %}
<form method="post" action="{% url 'institution:settings_support' %}">
  {% csrf_token %}
  <fieldset>
    <legend>{% trans "Who can report an issue" %}</legend>
    {{ support.audience }}
    {{ support.audience.errors }}
  </fieldset>

  {% comment %}The spec requires this line to NAME the Platform Admins who will be
  mailed automatically, so "who gets this" is never a guess — a generic sentence
  does not satisfy it.{% endcomment %}
  <p class="field-note">
    {% blocktrans with names=auto_recipients|join:", " %}Platform Admins can always report, and always receive reports: {{ names }}{% endblocktrans %}
  </p>

  <label for="{{ support.extra_emails.id_for_label }}">{{ support.extra_emails.label }}</label>
  {{ support.extra_emails }}
  <p class="field-note field-note--warning">{{ support.extra_emails.help_text }}</p>
  {{ support.extra_emails.errors }}

  <p>
    {% blocktrans count counter=extra_reporter_count %}{{ counter }} other person is also allowed.{% plural %}{{ counter }} other people are also allowed.{% endblocktrans %}
    <a href="{% url 'support:reporters' %}">{% trans "Manage" %}</a>
  </p>

  <button type="submit">{% trans "Save" %}</button>
</form>
```

This references `support:reporters`, registered by Task 7. That ordering is required, not incidental: once this panel is included in `settings.html`, **every** settings render evaluates `{% url 'support:reporters' %}`, so an unregistered name would `NoReverseMatch` and 500 the whole settings page — not just this tab.

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_support_settings_tab.py -v`
Expected: all pass.

- [ ] **Step 7: Falsify two**

1. Change the count to `support_row.extra_reporters.count()` → `test_a_settings_get_with_no_row_renders_and_writes_nothing` must FAIL with `ValueError`. Restore by hand.
2. Delete the `__init__` that newline-joins `initial` → `test_addresses_round_trip_one_per_line` must FAIL. Restore by hand.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check --no-cache support institution tests/test_support_settings_tab.py
uv run ruff format --check support institution tests/test_support_settings_tab.py
git add support institution templates/institution tests/test_support_settings_tab.py
git commit -m "feat(support): Support settings tab (audience + recipient addresses)"
```

---

### Task 9: The report dialog (template, JS, CSS)

**Files:**
- Create: `support/templates/support/_report_dialog.html`, `support/static/support/js/report_dialog.js`, `support/static/support/css/support.css`
- Modify: `templates/base.html`
- Test: `tests/test_support_dialog_markup.py`

**Interfaces:**
- Consumes: context keys `can_report_issue`, `report_description_max`
- Produces: the `#report-dialog` element and its trigger `[data-report-trigger]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_support_dialog_markup.py`:

```python
"""Server-rendered markup for the report dialog."""

import pytest
from django.urls import reverse

from support.constants import DESCRIPTION_MAX_LENGTH
from support.models import SupportSettings
from tests.factories import make_pa
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _set_audience(value):
    row = SupportSettings.load()
    row.audience = value
    row.save()


def test_a_permitted_reporter_gets_the_trigger_and_the_dialog(client):
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert "data-report-trigger" in body
    assert 'id="report-dialog"' in body


def test_a_user_outside_the_audience_gets_neither(client):
    _set_audience(SupportSettings.Audience.ADMINS)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert "data-report-trigger" not in body
    assert 'id="report-dialog"' not in body


def test_the_textarea_carries_a_server_rendered_maxlength(client):
    """Mutant: apply maxlength from JS only — the returned HTML then has none."""
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    assert f'maxlength="{DESCRIPTION_MAX_LENGTH}"' in body


def test_the_dialog_is_not_inside_a_hidden_menu_panel(client):
    """showModal() on a <dialog> inside a hidden subtree does not reliably work,
    and the account-menu panel carries the hidden attribute."""
    _set_audience(SupportSettings.Audience.ALL)
    make_student(client)
    body = client.get(reverse("home")).content.decode()
    dialog_at = body.index('id="report-dialog"')
    panel_at = body.index("account-menu")
    # The dialog must come AFTER the whole header block, at body level.
    assert dialog_at > panel_at
    assert "</header>" in body[:dialog_at]


def test_the_dialog_assets_are_outside_the_overridable_blocks(client):
    """Child templates override extra_css/extra_js; assets placed there would be
    dropped on most pages, giving an inert dialog on some routes only.

    Before running this, confirm the page chosen for the JS half really does
    override {% block extra_js %}; if it does not, pick one that does — an
    assertion on a page with no such block cannot fail.
    """
    _set_audience(SupportSettings.Audience.ALL)
    # core/user_settings.html overrides extra_css ONLY — it has no extra_js block,
    # so asserting the script here would pass even with the <script> moved inside
    # {% block extra_js %}, which is the mutant this test exists for.
    make_student(client)
    css_page = client.get(reverse("core:user_settings")).content.decode()
    assert "support/css/support.css" in css_page


def test_the_dialog_script_survives_a_template_that_overrides_extra_js(client):
    """The JS half of the pair above, on a page that really does override
    {% block extra_js %}. institution:settings is PA-only, hence the PA login."""
    _set_audience(SupportSettings.Audience.ALL)
    make_pa(client)
    js_page = client.get(reverse("institution:settings")).content.decode()
    assert "support/js/report_dialog.js" in js_page
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_support_dialog_markup.py -v`
Expected: assertion failures — no trigger, no dialog.

- [ ] **Step 3: Write the dialog template**

`support/templates/support/_report_dialog.html`:

```django
{% load i18n %}
<dialog id="report-dialog" class="report-dialog" aria-labelledby="report-dialog-title">
  <form method="post" action="{% url 'support:report_create' %}"
        enctype="multipart/form-data" data-report-form>
    {% csrf_token %}
    <h2 id="report-dialog-title">{% trans "Report an issue" %}</h2>

    <p class="report-dialog__banner" data-report-banner hidden></p>

    <label for="report-description">{% trans "What went wrong?" %}</label>
    <textarea id="report-description" name="description" rows="5" required
              maxlength="{{ report_description_max }}"
              data-report-description></textarea>
    <p class="report-dialog__counter" data-report-counter></p>
    <p class="report-dialog__error" data-error-for="description" hidden></p>

    <label for="report-screenshot">{% trans "Screenshot (optional)" %}</label>
    <input type="file" id="report-screenshot" name="screenshot"
           accept="image/png,image/jpeg,image/gif,image/webp" data-report-file>
    <p class="report-dialog__hint">
      {% trans "You can paste an image straight from the clipboard." %}
    </p>
    <p class="report-dialog__error" data-error-for="screenshot" hidden></p>

    {% comment %}Hidden telemetry inputs live INSIDE the form so new FormData(form)
    carries them along with the CSRF token. Building the payload field-by-field in
    JS would omit the token and 403 every submission.{% endcomment %}
    <input type="hidden" name="page_url" data-tel="page_url">
    <input type="hidden" name="page_title" data-tel="page_title">
    <input type="hidden" name="viewport_w" data-tel="viewport_w">
    <input type="hidden" name="viewport_h" data-tel="viewport_h">
    <input type="hidden" name="screen_w" data-tel="screen_w">
    <input type="hidden" name="screen_h" data-tel="screen_h">
    <input type="hidden" name="dpr" data-tel="dpr">
    <input type="hidden" name="timezone" data-tel="timezone">
    <input type="hidden" name="theme" data-tel="theme">
    <input type="hidden" name="ui_language" data-tel="ui_language">

    <details class="report-dialog__disclosure">
      <summary>{% trans "What will be sent" %}</summary>
      <dl data-report-preview></dl>
      <p>
        {% trans "We also record your name and email address, your role, your browser identification and language, and the time." %}
      </p>
    </details>

    <div class="report-dialog__actions">
      <button type="button" data-report-cancel>{% trans "Cancel" %}</button>
      <button type="submit">{% trans "Send report" %}</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 4: Write the JS**

`support/static/support/js/report_dialog.js`:

```javascript
(function () {
  "use strict";

  var dialog = document.getElementById("report-dialog");
  var trigger = document.querySelector("[data-report-trigger]");
  if (!dialog || !trigger) return;

  var form = dialog.querySelector("[data-report-form]");
  var banner = dialog.querySelector("[data-report-banner]");
  var description = dialog.querySelector("[data-report-description]");
  var counter = dialog.querySelector("[data-report-counter]");
  var fileInput = dialog.querySelector("[data-report-file]");
  var preview = dialog.querySelector("[data-report-preview]");
  var maxLength = parseInt(description.getAttribute("maxlength"), 10);

  // image/* -> extension. NOT blob.type.split("/")[1], which yields "svg+xml"
  // and "x-icon" — filenames that fail the extension validator with the very
  // error the re-wrap exists to prevent.
  var MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp"
  };

  function collect() {
    var values = {
      page_url: window.location.href,
      page_title: document.title,
      viewport_w: String(window.innerWidth),
      viewport_h: String(window.innerHeight),
      screen_w: String(window.screen ? window.screen.width : ""),
      screen_h: String(window.screen ? window.screen.height : ""),
      dpr: String(window.devicePixelRatio || 1),
      theme: document.documentElement.getAttribute("data-theme") || "",
      ui_language: document.documentElement.getAttribute("lang") || "",
      timezone: ""
    };
    try {
      values.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) { /* older engines: leave blank, the server drops it */ }
    Object.keys(values).forEach(function (key) {
      var input = form.querySelector('[data-tel="' + key + '"]');
      if (input) input.value = values[key];
    });
    preview.innerHTML = "";
    Object.keys(values).forEach(function (key) {
      if (!values[key]) return;
      var dt = document.createElement("dt");
      dt.textContent = key;
      var dd = document.createElement("dd");
      dd.textContent = values[key];
      preview.appendChild(dt);
      preview.appendChild(dd);
    });
  }

  function clearErrors() {
    banner.hidden = true;
    banner.textContent = "";
    dialog.querySelectorAll("[data-error-for]").forEach(function (node) {
      node.hidden = true;
      node.textContent = "";
    });
  }

  function showBanner(text) {
    banner.textContent = text;
    banner.hidden = false;
  }

  function updateCounter() {
    counter.textContent = description.value.length + " / " + maxLength;
  }

  trigger.addEventListener("click", function (event) {
    event.preventDefault();
    clearErrors();
    collect();          // re-read on EVERY open: the user may have resized
    updateCounter();
    dialog.showModal();
  });

  dialog.querySelector("[data-report-cancel]").addEventListener("click", function () {
    dialog.close();
  });

  description.addEventListener("input", updateCounter);

  // Paste to attach. getAsFile() returns a browser-dependent name that is often
  // extensionless or "blob", and FileExtensionValidator parses the filename — so
  // the blob is re-wrapped with a MIME-derived extension.
  dialog.addEventListener("paste", function (event) {
    var items = (event.clipboardData || {}).items || [];
    for (var i = 0; i < items.length; i += 1) {
      if (items[i].kind !== "file") continue;
      var blob = items[i].getAsFile();
      if (!blob) continue;
      var ext = MIME_EXT[blob.type];
      if (!ext) {
        showBanner(document.documentElement.lang === "pl"
          ? "Ten format obrazu nie jest obsługiwany."
          : "That image format is not supported.");
        return;
      }
      var file = new File([blob], "screenshot." + ext, { type: blob.type });
      var transfer = new DataTransfer();
      transfer.items.add(file);
      fileInput.files = transfer.files;
      event.preventDefault();
      return;
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),          // carries the CSRF token
      headers: { "X-Requested-With": "XMLHttpRequest" }
    }).then(function (response) {
      var type = response.headers.get("content-type") || "";
      // Check Content-Type BEFORE parsing: Django's CSRF failure view returns a
      // 403 with an HTML body, and a 500 or a 405 is not JSON either.
      if (type.indexOf("application/json") === -1) {
        showBanner("Something went wrong. Please try again.");
        return null;
      }
      return response.json().then(function (payload) {
        return { status: response.status, payload: payload };
      });
    }).then(function (result) {
      if (!result) return;
      if (result.status === 201) {
        showBanner(result.payload.message);
        window.setTimeout(function () {
          form.reset();
          fileInput.value = "";     // reset() alone can leave a picked file
          dialog.close();
          clearErrors();
        }, 1500);
        return;
      }
      if (result.payload.errors) {
        Object.keys(result.payload.errors).forEach(function (field) {
          var node = dialog.querySelector('[data-error-for="' + field + '"]');
          var text = result.payload.errors[field].join(" ");
          if (node) {
            node.textContent = text;
            node.hidden = false;
          } else {
            // __all__ and any unknown key go to the banner — otherwise a
            // Form.clean() error is returned and silently dropped.
            showBanner(text);
          }
        });
      }
      if (result.payload.message) showBanner(result.payload.message);
    }).catch(function () {
      showBanner("Something went wrong. Please try again.");
    });
  });
})();
```

- [ ] **Step 5: Write the CSS**

`support/static/support/css/support.css` — a `<dialog>` does not inherit the page theme in this codebase, so its colours must be set explicitly from the tokens:

```css
.report-dialog {
  /* <dialog> renders in the top layer and does NOT inherit the page theme here,
     so every colour is set explicitly from the tokens rather than inherited. */
  background: var(--surface-raised);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 1.25rem;
  max-width: min(36rem, calc(100vw - 2rem));
  width: 100%;
}
.report-dialog::backdrop { background: rgb(0 0 0 / 0.45); }
.report-dialog textarea { width: 100%; }
.report-dialog__counter { color: var(--text-secondary); font-size: 0.875rem; }
.report-dialog__error { color: var(--danger); }
.report-dialog__banner {
  border: 1px solid var(--border-default);
  padding: 0.5rem 0.75rem;
}
.report-dialog__hint { color: var(--text-secondary); font-size: 0.875rem; }
.report-dialog__actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
```

These are the real token names from `core/static/core/css/tokens.css`: `--surface-raised`, `--text-primary`, `--text-secondary`, `--border-default` (**not** `--border`), `--danger`. All of them are redefined under the dark block, so the dialog follows the theme once the values come from tokens.

- [ ] **Step 6: Wire base.html**

Three additions, all guarded by `{% if can_report_issue %}`:

1. In `<head>`, **outside** `{% block extra_css %}`, beside the shell's own stylesheets:

```django
{% if can_report_issue %}<link rel="stylesheet" href="{% static 'support/css/support.css' %}">{% endif %}
```

2. In the account-menu panel, after the Settings link:

```django
{% if can_report_issue %}
<button class="menu__item" type="button" data-report-trigger>{% trans "Report an issue" %}</button>
{% endif %}
```

3. At body level near the closing `</body>`, **outside** `{% block extra_js %}` and outside every `hidden` / `data-menu-panel` container:

```django
{% if can_report_issue %}
  {% include "support/_report_dialog.html" %}
  <script src="{% static 'support/js/report_dialog.js' %}" defer></script>
{% endif %}
```

- [ ] **Step 7: Run to verify pass**

Run: `uv run pytest tests/test_support_dialog_markup.py -v`
Expected: all pass.

- [ ] **Step 8: Falsify one**

Move the `{% include %}` inside the account-menu `div.menu__panel` → `test_the_dialog_is_not_inside_a_hidden_menu_panel` must FAIL. Restore by hand.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check --no-cache support tests/test_support_dialog_markup.py
uv run ruff format --check support tests/test_support_dialog_markup.py
git add support templates/base.html tests/test_support_dialog_markup.py
git commit -m "feat(support): report dialog with paste-to-attach and JSON submit"
```

---

### Task 10: End-to-end test

**Files:**
- Create: `tests/test_e2e_support_report.py`
- Test: itself

- [ ] **Step 1: Start the test database container**

Run: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`

Without it the first e2e run looks hung for over four minutes. Confirm no other pytest run is active first — two concurrent runs corrupt the shared test database, and killing one poisons the survivor with phantom `SystemExit: 2` failures.

- [ ] **Step 2: Write the e2e test**

Create `tests/test_e2e_support_report.py`. The fixtures are `page` and `live_server`, in that order, matching every existing e2e file (e.g. `tests/test_e2e_alignment.py:32`). Log in through the real allauth form, mirroring `_editor_login` in `tests/conftest.py`:

```python
"""End-to-end: open the dialog, paste an image, submit, verify the stored row."""

import pytest
from django.contrib.auth.models import Group

from institution.roles import STUDENT
from institution.roles import seed_roles
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def _student(username="reporter"):
    """A verified Student created directly, so the test can log in through the
    real allauth form rather than force_login."""
    seed_roles()
    user = make_verified_user(
        username=username,
        email=f"{username}@t.example.com",
        password=TEST_PASSWORD,
    )
    user.groups.add(Group.objects.get(name=STUDENT))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()

# A 1x1 PNG as a data: URL, fetched inside the page so the paste carries real
# image bytes. Playwright cannot portably put an image on the OS clipboard, so
# Ctrl+V would paste NOTHING — and because the screenshot is optional the submit
# would still succeed, giving a test that cannot fail. A synthetic ClipboardEvent
# carrying a DataTransfer is the only mechanism that exercises the paste handler.
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)

PASTE_SCRIPT = """
async (dataUrl) => {
  const blob = await (await fetch(dataUrl)).blob();
  const file = new File([blob], "clip", { type: "image/png" });
  const dt = new DataTransfer();
  dt.items.add(file);
  const event = new ClipboardEvent("paste", {
    clipboardData: dt, bubbles: true, cancelable: true
  });
  document.getElementById("report-dialog").dispatchEvent(event);
}
"""


def test_a_student_reports_an_issue_with_a_pasted_screenshot(page, live_server):
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()

    _student()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")

    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    page.wait_for_selector("#report-dialog[open]")

    page.evaluate(PASTE_SCRIPT, PNG_DATA_URL)
    # Synchronise on the condition, never a sleep.
    page.wait_for_function(
        "document.querySelector('[data-report-file]').files.length === 1"
    )

    page.fill("[data-report-description]", "The submit button does nothing.")
    page.click("#report-dialog button[type=submit]")
    page.wait_for_selector("[data-report-banner]:not([hidden])")

    report = IssueReport.objects.get()
    assert report.description == "The submit button does nothing."
    assert report.screenshot.name.endswith(".png")
    assert report.telemetry["viewport_w"] > 0
```

- [ ] **Step 3: Run it**

Run: `uv run pytest -m e2e tests/test_e2e_support_report.py -v`
The `-m e2e` is mandatory — without it the test is deselected and pytest exits 5, which looks like success.
Expected: 1 passed.

- [ ] **Step 4: Falsify it**

Comment out the `dialog.addEventListener("paste", ...)` block in `report_dialog.js`. Re-run: the `wait_for_function` on `files.length === 1` must time out and the test must FAIL. Restore by hand.

- [ ] **Step 5: Capture light and dark screenshots**

Add a second e2e that opens the dialog and screenshots it in both themes. Set the theme on the **user** (`user.theme = "dark"`), not via the cookie — a `<dialog>` does not pick up the cookie-driven theme. Save to `docs/superpowers/screenshots/`. Look at both images and judge the dark one on its own terms, not as "the light one inverted".

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_support_report.py docs/superpowers/screenshots
git commit -m "test(support): e2e report submission with a pasted screenshot"
```

---

### Task 11: Visual design pass

**Files:**
- Modify: `support/static/support/css/support.css`, `support/templates/support/**`, `templates/institution/manage/_support_panel.html`
- Test: re-run Task 9 and Task 10 suites

- [ ] **Step 1: Invoke the frontend-design skill**

Use the `frontend-design` skill and apply it to the four new surfaces: the report dialog, the Support settings panel, the Allowed reporters page, and the triage list and detail. The behaviour is finished and tested by this point, so the visual work happens once, against final markup.

- [ ] **Step 2: Hold the line on the design language**

Token-driven CSS only — no Bootstrap, no utility framework, no new dependency. Icons are monochrome inline SVG using `currentColor`; never emoji. Every surface must read correctly in **both** themes, and the `<dialog>` still needs its colours set explicitly rather than inherited.

- [ ] **Step 3: Re-run the affected suites**

Run: `uv run pytest tests/test_support_dialog_markup.py tests/test_support_triage.py tests/test_support_settings_tab.py -v`
Expected: all still pass. Restyling must not move the hooks the tests assert on (`data-report-trigger`, `#report-dialog`, `maxlength`).

- [ ] **Step 4: Re-capture the screenshots and look at them**

Run the Task 10 screenshot e2e again in light and dark. Open both images. Judge the dark rendering separately.

- [ ] **Step 5: Commit**

```bash
git add support templates
git commit -m "style(support): visual design pass over the dialog, settings and triage views"
```

---

### Task 12: Translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`
- Test: full unit suite

- [ ] **Step 1: Extract the messages**

Run: `uv run python manage.py makemessages -l pl -a`

- [ ] **Step 2: Translate every new string, and clear the fuzzy flags**

Open `locale/pl/LC_MESSAGES/django.po` and fill in the Polish for each new `msgid`. Where `makemessages` has pre-filled a **fuzzy** translation, it has guessed from a similar string and the guess is usually wrong for this feature's copy — clearing it is two deletions: remove the `#, fuzzy` comment **and** replace the wrong `msgstr`.

Grep with care: a `$`-anchored pattern silently matches nothing in these files, because they use CRLF.

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages -l pl`

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/test_support_models.py tests/test_support_policy.py tests/test_support_telemetry.py tests/test_support_report_create.py tests/test_support_emails.py tests/test_support_triage.py tests/test_support_settings_tab.py tests/test_support_reporters_page.py tests/test_support_dialog_markup.py -v`
Expected: all pass. Grep the summary line.

- [ ] **Step 5: Commit**

```bash
git add locale
git commit -m "i18n(support): Polish translations for issue reporting"
```

---

### Task 13: Branch gate

- [ ] **Step 1: Run the whole unit suite**

Run: `uv run pytest`
Expected: no failures. **Grep the summary** — this suite can exit 0 while reporting `1 failed`.

- [ ] **Step 2: Run the lint gates**

Run: `uv run ruff check --no-cache` then `uv run ruff format --check`
Expected: both clean. They are separate gates; passing one says nothing about the other.

- [ ] **Step 3: Confirm the migration graph**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected". If a new migration is proposed, a model changed after `0001_initial` was written — generate it and re-run the suite.

- [ ] **Step 4: Verify the deployment note is actionable**

Confirm `institution/roles.py` lists all five `support.*` codenames in `PLATFORM_ADMIN_PERMS`, and that the spec's deployment note (run `setup_roles` after `migrate`) is reflected wherever this project keeps its release checklist. **No test catches a missed `setup_roles`** — the permissions exist and are attached to nobody, and every PA 403s on Save with nothing to point at the cause.
