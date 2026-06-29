# Phase 5c — Branding & Platform-Settings Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a Platform Admin a bespoke `/manage/settings/` page to edit branding (logo + primary/accent colours), upload limits (file-type toggles + size caps), and the email-domain allowlist — surfacing and completing settings that already live on the `Institution` singleton.

**Architecture:** No new models. Four new fields on the `Institution` singleton back the upload limits; brand colours stay in existing `BrandColor` rows. `courses/validators.py` gains a code-level "safe set" ceiling plus `effective_*()` readers that intersect admin choices with that ceiling and read from the cached site config. A new `institution/views_manage.py` renders one tabbed page (`institution:settings`) with three POST-only action views; the old `/settings/institution/` URL becomes a redirect that keeps its name bound. An additive build (new forms/views alongside the old) with a single late **cutover** task keeps the test suite green throughout.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + factory_boy, Playwright (e2e), `uv` for tooling, gettext i18n (EN/PL).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff …`, `uv run pytest …`, `uv run python manage.py …`.
- **Per-task lint:** run `uv run ruff check <changed files incl. tests>` AND `uv run ruff format <changed files>` every task. CI runs `ruff format --check` — formatting drift fails it. Include test files in the `ruff check` target (F841/I001 in tests have slipped to the DoD gate before).
- **No hardcoded test passwords:** always use `tests.factories.TEST_PASSWORD`. New password literals trip GitGuardian CI.
- **Translatable strings:** wrap all user-facing copy in `_()`. Module-level label dicts MUST use `gettext_lazy` (eager `gettext` freezes labels to the import-time language — a shipped-3× footgun).
- **PA test helper:** `from tests.factories import make_pa` → `make_pa(client, "pa")` seeds roles, logs in a verified Platform Admin, clears perm caches. Use it for every PA-gated view test.
- **Migrations must serialize:** JSONField list defaults are module-level callables (never literal lists), mirroring `institution/models.py:default_languages`.
- **Colour invariant:** brand colour form fields are 6-digit `#rrggbb` hex, validated case-insensitively, stored lowercased.
- **Security ceiling:** the admin can only ever *narrow* uploads (extensions ⊆ safe set; size ≤ ceiling). The code constants are the permanent ceiling.
- Spec: `docs/superpowers/specs/2026-06-29-phase-5c-branding-and-platform-settings-design.md`.

---

## File Structure

**Created:**
- `institution/views_manage.py` — index `settings` view + 3 action views + `_settings_context` helper.
- `institution/urls.py` — `app_name = "institution"`, mounts `/manage/settings/...`.
- `templates/institution/manage/settings.html` — tabbed page shell.
- `templates/institution/manage/_tabs.html`, `_branding_tab.html`, `_access_tab.html`, `_uploads_tab.html` — tab partials.
- `static/css/settings.css` — page styling.
- `tests/test_settings_5c_validators.py`, `tests/test_settings_5c_forms.py`, `tests/test_settings_5c_views.py`, `tests/test_invite_domain_warning.py`, `tests/test_e2e_settings_5c.py` — new tests.

**Modified:**
- `courses/validators.py` — safe-set constants, callable defaults, `effective_*()` readers, dynamic per-kind validators.
- `courses/models.py` — `MediaAsset.clean()` calls the dynamic validators.
- `institution/models.py` — 4 new upload fields + migration.
- `core/services.py` — upload keys into `_DEFAULTS` + `_build()`.
- `institution/forms.py` — `BrandingForm`, `AccessForm`, `UploadsForm`; retire `InstitutionSettingsForm` (cutover task).
- `accounts/provisioning.py` — factor `normalized_allowlist()`; reuse in `evaluate_sso_provisioning`.
- `accounts/views_manage.py` — invite-domain non-blocking warning.
- `core/views.py`, `core/urls.py` — redirect old path, keep `core:institution_settings` name bound (cutover).
- `templates/base.html`, `templates/core/home.html` — repoint nav link (cutover).
- `tests/test_settings_forms.py`, `tests/test_e2e_settings.py`, `tests/test_settings_styles.py`, `tests/test_surfaces.py`, `tests/test_i18n_ws4.py` — migrate (cutover).
- `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ `.mo`).

---

## Task 1: Upload safe-set constants, effective readers, and dynamic validators

**Files:**
- Modify: `courses/validators.py`
- Test: `tests/test_settings_5c_validators.py` (create)

**Interfaces:**
- Produces (all in `courses.validators`):
  - `SAFE_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")`, `SAFE_VIDEO_EXTENSIONS = ("mp4", "webm", "ogg", "mov")`
  - `MAX_IMAGE_MIB_CEILING = 5`, `MAX_VIDEO_MIB_CEILING = 200`
  - `default_image_extensions() -> list[str]`, `default_video_extensions() -> list[str]` (migration-serializable callables)
  - `effective_image_extensions() -> list[str]`, `effective_video_extensions() -> list[str]` (stored ∩ safe, order = safe-set order)
  - `effective_max_image_bytes() -> int`, `effective_max_video_bytes() -> int` (min(stored_mib, ceiling) × 1 MiB)
  - `validate_image_file(file)`, `validate_video_file(file)` — extension + size; both skip committed `FieldFile`s
- Consumes: `core.services.get_site_config()` (imported **inside** function bodies to avoid a `core`↔`courses` import cycle). The config keys `allowed_image_extensions` / `allowed_video_extensions` / `max_image_mib` / `max_video_mib` may be absent at this task's stage — readers use `.get(key, <default>)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_5c_validators.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from courses import validators as v


class _FakeUpload:
    """Stand-in for a new (uncommitted) upload: has .name and .size, no _committed."""

    def __init__(self, name, size):
        self.name = name
        self.size = size


class _FakeCommitted(_FakeUpload):
    _committed = True


def _cfg(monkeypatch, **over):
    cfg = {
        "allowed_image_extensions": list(v.SAFE_IMAGE_EXTENSIONS),
        "allowed_video_extensions": list(v.SAFE_VIDEO_EXTENSIONS),
        "max_image_mib": v.MAX_IMAGE_MIB_CEILING,
        "max_video_mib": v.MAX_VIDEO_MIB_CEILING,
    }
    cfg.update(over)
    monkeypatch.setattr(v, "_site_config", lambda: cfg)


def test_defaults_are_fresh_lists():
    a, b = v.default_image_extensions(), v.default_image_extensions()
    assert a == list(v.SAFE_IMAGE_EXTENSIONS) and a is not b  # not a shared mutable


def test_effective_extensions_default_is_full_safe_set(monkeypatch):
    _cfg(monkeypatch)
    assert v.effective_image_extensions() == list(v.SAFE_IMAGE_EXTENSIONS)


def test_effective_extensions_narrows(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png", "jpg"])
    assert v.effective_image_extensions() == ["png", "jpg"]


def test_effective_extensions_intersects_away_forged_values(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png", "svg", "exe"])
    assert v.effective_image_extensions() == ["png"]  # svg/exe not in safe set


def test_effective_extensions_empty_stored_is_fail_closed(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=[])
    assert v.effective_image_extensions() == []


def test_effective_extensions_missing_key_falls_back_to_safe(monkeypatch):
    monkeypatch.setattr(v, "_site_config", lambda: {})  # institution-absent path
    assert v.effective_image_extensions() == list(v.SAFE_IMAGE_EXTENSIONS)


def test_effective_max_bytes_respects_ceiling(monkeypatch):
    _cfg(monkeypatch, max_image_mib=999)  # tampered above ceiling
    assert v.effective_max_image_bytes() == v.MAX_IMAGE_MIB_CEILING * 1024 * 1024


def test_effective_max_bytes_honours_narrower(monkeypatch):
    _cfg(monkeypatch, max_image_mib=1)
    assert v.effective_max_image_bytes() == 1 * 1024 * 1024


def test_validate_image_file_rejects_disabled_extension(monkeypatch):
    _cfg(monkeypatch, allowed_image_extensions=["png"])
    with pytest.raises(ValidationError):
        v.validate_image_file(_FakeUpload("clip.gif", 10))


def test_validate_image_file_rejects_oversize(monkeypatch):
    _cfg(monkeypatch, max_image_mib=1)
    with pytest.raises(ValidationError):
        v.validate_image_file(_FakeUpload("ok.png", 2 * 1024 * 1024))


def test_validate_image_file_accepts_within_limits(monkeypatch):
    _cfg(monkeypatch)
    v.validate_image_file(_FakeUpload("ok.png", 10))  # no raise


def test_validate_image_file_skips_committed(monkeypatch):
    # Narrow so gif is disabled AND cap is tiny; a committed file must STILL pass
    # (no retroactive rejection, no storage .size read).
    _cfg(monkeypatch, allowed_image_extensions=["png"], max_image_mib=1)
    v.validate_image_file(_FakeCommitted("old.gif", 9_999_999))  # no raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings_5c_validators.py -q`
Expected: FAIL (AttributeError: module `courses.validators` has no attribute `SAFE_IMAGE_EXTENSIONS` / `_site_config` / etc.).

- [ ] **Step 3: Rewrite `courses/validators.py`**

Replace the whole file with:

```python
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

# --- Upload safe set: the permanent security CEILING. Admins may only narrow. ---
SAFE_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")
SAFE_VIDEO_EXTENSIONS = ("mp4", "webm", "ogg", "mov")
MAX_IMAGE_MIB_CEILING = 5
MAX_VIDEO_MIB_CEILING = 200

_MIB = 1024 * 1024


def default_image_extensions():
    # Module-level callable (not a literal) so migrations can serialize the default.
    return list(SAFE_IMAGE_EXTENSIONS)


def default_video_extensions():
    return list(SAFE_VIDEO_EXTENSIONS)


def _site_config():
    # Function-scope import: courses/validators is imported at model-load time, so a
    # top-level `from core.services import ...` risks a core<->courses import cycle.
    from core.services import get_site_config

    return get_site_config()


def _effective_extensions(key, safe):
    stored = _site_config().get(key, list(safe))
    chosen = set(stored)
    return [e for e in safe if e in chosen]  # order = safe-set order; stored ∩ safe


def effective_image_extensions():
    return _effective_extensions("allowed_image_extensions", SAFE_IMAGE_EXTENSIONS)


def effective_video_extensions():
    return _effective_extensions("allowed_video_extensions", SAFE_VIDEO_EXTENSIONS)


def effective_max_image_bytes():
    mib = _site_config().get("max_image_mib", MAX_IMAGE_MIB_CEILING)
    return min(mib, MAX_IMAGE_MIB_CEILING) * _MIB


def effective_max_video_bytes():
    mib = _site_config().get("max_video_mib", MAX_VIDEO_MIB_CEILING)
    return min(mib, MAX_VIDEO_MIB_CEILING) * _MIB


def _validate_file(file, *, extensions, max_bytes, too_big_msg):
    """Extension + size check, skipping already-committed FieldFiles.

    Committed files are skipped for BOTH checks so admin narrowing applies to NEW
    uploads only (never a retroactive rejection on an unrelated edit) and reading
    `.size` never hits absent storage (FileNotFoundError in tests/remote storage).
    New uploads (InMemory/Temporary) lack `_committed`, so getattr -> False.
    """
    if getattr(file, "_committed", False):
        return
    FileExtensionValidator(allowed_extensions=list(extensions))(file)
    if file.size > max_bytes:
        raise ValidationError(too_big_msg)


def validate_image_file(file):
    _validate_file(
        file,
        extensions=effective_image_extensions(),
        max_bytes=effective_max_image_bytes(),
        too_big_msg=_("Image file too large (max %(mib)d MiB).")
        % {"mib": effective_max_image_bytes() // _MIB},
    )


def validate_video_file(file):
    _validate_file(
        file,
        extensions=effective_video_extensions(),
        max_bytes=effective_max_video_bytes(),
        too_big_msg=_("Video file too large (max %(mib)d MiB).")
        % {"mib": effective_max_video_bytes() // _MIB},
    )


def validate_embed_url(url):
    """Require https and a host that equals or is a subdomain of a whitelisted host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("Embed URLs must use https.")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_EMBED_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError("Embed domain is not on the allow-list.")
```

Note: the tests monkeypatch `validators._site_config`, so the readers must call the module-level `_site_config()` (not import `get_site_config` directly in each reader).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_settings_5c_validators.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check courses/validators.py tests/test_settings_5c_validators.py
uv run ruff format courses/validators.py tests/test_settings_5c_validators.py
git add courses/validators.py tests/test_settings_5c_validators.py
git commit -m "feat(5c): upload safe-set ceiling + effective readers + dynamic validators"
```

---

## Task 2: Institution upload fields + migration

**Files:**
- Modify: `institution/models.py`
- Create: `institution/migrations/00NN_upload_settings.py` (generated)
- Test: `tests/test_settings_5c_views.py` (create — model section)

**Interfaces:**
- Produces: `Institution.allowed_image_extensions` / `allowed_video_extensions` (JSONField, callable defaults), `Institution.max_image_mib` / `max_video_mib` (PositiveIntegerField, defaults 5 / 200).
- Consumes: `courses.validators.default_image_extensions`, `default_video_extensions`, `MAX_IMAGE_MIB_CEILING`, `MAX_VIDEO_MIB_CEILING`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_5c_views.py`:

```python
import pytest

from courses import validators as cv
from institution.models import Institution


@pytest.mark.django_db
def test_institution_upload_field_defaults():
    inst = Institution.load()
    assert inst.allowed_image_extensions == list(cv.SAFE_IMAGE_EXTENSIONS)
    assert inst.allowed_video_extensions == list(cv.SAFE_VIDEO_EXTENSIONS)
    assert inst.max_image_mib == cv.MAX_IMAGE_MIB_CEILING
    assert inst.max_video_mib == cv.MAX_VIDEO_MIB_CEILING
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_settings_5c_views.py -q`
Expected: FAIL (`AttributeError`/`FieldError`: no `allowed_image_extensions`).

- [ ] **Step 3: Add the fields**

In `institution/models.py`, add the import at top and the four fields to `Institution` (after `allowed_email_domains`):

```python
from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import MAX_VIDEO_MIB_CEILING
from courses.validators import default_image_extensions
from courses.validators import default_video_extensions
```

```python
    allowed_image_extensions = models.JSONField(default=default_image_extensions, blank=True)
    allowed_video_extensions = models.JSONField(default=default_video_extensions, blank=True)
    max_image_mib = models.PositiveIntegerField(default=MAX_IMAGE_MIB_CEILING)
    max_video_mib = models.PositiveIntegerField(default=MAX_VIDEO_MIB_CEILING)
```

If a top-level `institution` ← `courses` import proves circular at load time (courses imports institution anywhere), move the four imports inside a module-level block guarded by `TYPE_CHECKING` is not enough for defaults — instead define thin local callables in `institution/models.py` that delegate (`def _img_default(): from courses.validators import default_image_extensions; return default_image_extensions()`). Verify with `uv run python manage.py check` before generating the migration. (Expected: `courses` does not import `institution` at module top, so the direct import is fine — confirm.)

- [ ] **Step 4: Generate, apply, and verify the migration**

```bash
uv run python manage.py makemigrations institution
uv run python manage.py migrate
uv run pytest tests/test_settings_5c_views.py -q
```
Expected: a new `institution/migrations/00NN_*.py` with 4 `AddField`s; test PASS.
Then confirm no missing migrations: `uv run python manage.py makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/models.py tests/test_settings_5c_views.py
uv run ruff format institution/models.py tests/test_settings_5c_views.py
git add institution/models.py institution/migrations/ tests/test_settings_5c_views.py
git commit -m "feat(5c): Institution upload-limit fields + migration"
```

---

## Task 3: Wire upload keys into site config; switch MediaAsset.clean() to dynamic validators

**Files:**
- Modify: `core/services.py`, `courses/models.py`
- Test: `tests/test_settings_5c_views.py` (append)

**Interfaces:**
- Consumes: Task 1 validators, Task 2 fields.
- Produces: `get_site_config()` now carries `allowed_image_extensions` / `allowed_video_extensions` / `max_image_mib` / `max_video_mib`. `MediaAsset.clean()` validates via `validate_image_file` / `validate_video_file`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_5c_views.py`:

```python
import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError

from core.services import get_site_config
from institution.models import Institution
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_site_config_carries_upload_keys():
    cache.clear()
    cfg = get_site_config()
    assert "allowed_image_extensions" in cfg
    assert "max_video_mib" in cfg


@pytest.mark.django_db
def test_site_config_upload_keys_present_when_institution_absent():
    cache.clear()
    Institution.objects.all().delete()  # institution-absent path -> dict(_DEFAULTS)
    cfg = get_site_config()
    assert cfg["allowed_image_extensions"]  # key present, not KeyError downstream
    assert cfg["max_image_mib"]


def _png_upload(name="a.png", size_pad=0):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue() + b"\0" * size_pad, "image/png")


@pytest.mark.django_db
def test_mediaasset_clean_rejects_disabled_extension():
    inst = Institution.load()
    inst.allowed_image_extensions = ["jpg"]  # gif/png disabled
    inst.save()  # fires cache invalidation
    cache.clear()
    from courses.models import MediaAsset

    asset = MediaAsset(
        course=CourseFactory(), kind="image",
        file=_png_upload("x.png"), original_filename="x.png",
    )
    with pytest.raises(ValidationError):
        asset.clean()


@pytest.mark.django_db
def test_mediaasset_clean_accepts_within_limits():
    cache.clear()
    from courses.models import MediaAsset

    asset = MediaAsset(
        course=CourseFactory(), kind="image",
        file=_png_upload("x.png"), original_filename="x.png",
    )
    asset.clean()  # no raise — defaults allow png
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_views.py -q`
Expected: FAIL (`test_site_config_carries_upload_keys` KeyError-absent; clean tests fail because `clean()` still uses the static `IMAGE_VALIDATORS` ignoring the admin narrowing).

- [ ] **Step 3a: Add upload keys to `core/services.py`**

In `_DEFAULTS` add (after `"signup_policy": "invite",`):

```python
    "allowed_image_extensions": list(SAFE_IMAGE_EXTENSIONS),
    "allowed_video_extensions": list(SAFE_VIDEO_EXTENSIONS),
    "max_image_mib": MAX_IMAGE_MIB_CEILING,
    "max_video_mib": MAX_VIDEO_MIB_CEILING,
```

Add the import near the top of `core/services.py`:

```python
from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import MAX_VIDEO_MIB_CEILING
from courses.validators import SAFE_IMAGE_EXTENSIONS
from courses.validators import SAFE_VIDEO_EXTENSIONS
```

In `_build()`'s returned dict, add (after `"signup_policy": ...`):

```python
        "allowed_image_extensions": inst.allowed_image_extensions or _DEFAULTS["allowed_image_extensions"],
        "allowed_video_extensions": inst.allowed_video_extensions or _DEFAULTS["allowed_video_extensions"],
        "max_image_mib": inst.max_image_mib or _DEFAULTS["max_image_mib"],
        "max_video_mib": inst.max_video_mib or _DEFAULTS["max_video_mib"],
```

Note: `inst.allowed_image_extensions or default` means a stored **empty** list falls back to the full safe set in the *cached config*. That is intentional and consistent with `effective_*` only narrowing via a NON-empty stored subset; the fail-closed empty state is reachable only through forged DB values bypassing `UploadsForm` (which requires ≥1). The `effective_image_extensions()` reader still intersects, so the ceiling holds either way.

- [ ] **Step 3b: Switch `MediaAsset.clean()` (`courses/models.py`)**

Replace the `IMAGE_VALIDATORS` / `VIDEO_VALIDATORS` class attributes and `clean()` body. Update the import of validators at the top of `courses/models.py` (it currently imports `FileExtensionValidator`, `validate_image_size`, `validate_video_size`) to import `validate_image_file`, `validate_video_file` instead (keep `FileExtensionValidator` only if still used elsewhere in the file — grep; remove if now unused). New `clean()`:

```python
    def clean(self):
        # Single validation authority for the file (extension + size, by kind),
        # reading the admin-configured effective limits. Skip when no file is set.
        if not self.file:
            return
        from courses.validators import validate_image_file
        from courses.validators import validate_video_file

        if self.kind == self.Kind.IMAGE:
            validate_image_file(self.file)
        else:
            validate_video_file(self.file)
```

Delete the now-unused `IMAGE_VALIDATORS` / `VIDEO_VALIDATORS` class lists. Grep first: `IMAGE_VALIDATORS` is referenced in `tests/test_courses_elements.py` — if so, update those tests to call `validate_image_file` (or assert via `MediaAsset.clean()`); fold that edit into this task so the suite stays green.

- [ ] **Step 4: Run the full media + new tests**

```bash
uv run pytest tests/test_settings_5c_views.py tests/test_courses_elements.py -q
```
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check core/services.py courses/models.py tests/test_settings_5c_views.py tests/test_courses_elements.py
uv run ruff format core/services.py courses/models.py tests/test_settings_5c_views.py tests/test_courses_elements.py
git add core/services.py courses/models.py tests/
git commit -m "feat(5c): upload limits in site config + MediaAsset dynamic validation"
```

---

## Task 4: BrandingForm (logo/name/languages/theme + primary/accent hex)

**Files:**
- Modify: `institution/forms.py`
- Test: `tests/test_settings_5c_forms.py` (create)

**Interfaces:**
- Produces: `institution.forms.BrandingForm` (ModelForm on `Institution`, fields `name, logo, enabled_languages, default_language, default_theme` + extra `primary, accent`); `institution.forms.normalize_hex(value) -> str | None`. Keeps `MAX_LOGO_BYTES`.
- Consumes: `core.services.PRIMARY_DEFAULT`, `ACCENT_DEFAULT`; `institution.models.BrandColor`.
- `BrandingForm.save()` writes the `Institution` + the `primary`/`accent` `BrandColor` rows inside one `transaction.atomic()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_5c_forms.py`:

```python
import pytest

from institution.forms import BrandingForm
from institution.forms import normalize_hex
from institution.models import BrandColor
from institution.models import Institution


def _branding_data(**over):
    data = {
        "name": "Greenfield",
        "enabled_languages": ["en", "pl"],
        "default_language": "en",
        "default_theme": "auto",
        "primary": "#123ABC",
        "accent": "#abcdef",
    }
    data.update(over)
    return data


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("#abc", "#aabbcc"),
        ("#AABBCC", "#aabbcc"),
        ("#147E78", "#147e78"),
        ("rgb(1,2,3)", None),
        ("nonsense", None),
        ("", None),
    ],
)
def test_normalize_hex(raw, expected):
    assert normalize_hex(raw) == expected


@pytest.mark.django_db
def test_branding_form_saves_colours_lowercased():
    inst = Institution.load()
    form = BrandingForm(_branding_data(primary="#123ABC"), instance=inst)
    assert form.is_valid(), form.errors
    form.save()
    assert BrandColor.objects.get(institution=inst, key="primary").value == "#123abc"
    assert BrandColor.objects.get(institution=inst, key="accent").value == "#abcdef"


@pytest.mark.django_db
def test_branding_form_rejects_non_hex_colour():
    inst = Institution.load()
    form = BrandingForm(_branding_data(primary="rgb(1,2,3)"), instance=inst)
    assert not form.is_valid()
    assert "primary" in form.errors


@pytest.mark.django_db
def test_branding_form_seeds_from_existing_brandcolor():
    inst = Institution.load()
    BrandColor.objects.create(institution=inst, key="primary", value="#fff")
    form = BrandingForm(instance=inst)  # unbound GET render
    assert form.initial["primary"] == "#ffffff"  # #fff expanded + lowercased


@pytest.mark.django_db
def test_branding_form_seeds_default_when_no_row():
    from core.services import PRIMARY_DEFAULT

    inst = Institution.load()
    form = BrandingForm(instance=inst)
    assert form.initial["primary"] == PRIMARY_DEFAULT.lower()


@pytest.mark.django_db
def test_branding_form_uppercase_stored_row_still_saves():
    # A pre-existing uppercase 6-hex row must seed AND a name-only save must succeed.
    inst = Institution.load()
    BrandColor.objects.create(institution=inst, key="primary", value="#AABBCC")
    seed = BrandingForm(instance=inst).initial
    form = BrandingForm(
        _branding_data(name="Renamed", primary=seed["primary"], accent=seed["accent"]),
        instance=inst,
    )
    assert form.is_valid(), form.errors
    form.save()
    assert Institution.load().name == "Renamed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_forms.py -q`
Expected: FAIL (`ImportError: cannot import name 'BrandingForm'`).

- [ ] **Step 3: Add `normalize_hex` + `BrandingForm` to `institution/forms.py`**

Add near the top (keep the existing `InstitutionSettingsForm` untouched for now):

```python
import re

from django.db import transaction

from core.services import ACCENT_DEFAULT
from core.services import PRIMARY_DEFAULT
from institution.models import BrandColor

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")


def normalize_hex(value):
    """Return a lowercased #rrggbb hex, expanding #rgb; None if not coercible."""
    v = (value or "").strip()
    if _HEX3.match(v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    if _HEX6.match(v):
        return v.lower()
    return None


def _hex_field(label):
    field = forms.RegexField(
        regex=_HEX6, label=label,
        error_messages={"invalid": _("Enter a 6-digit hex colour like #147E78.")},
    )
    field.widget.attrs["data-hex"] = "1"  # JS hook to mirror the <input type=color>
    return field
```

```python
class BrandingForm(forms.ModelForm):
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled languages"),
    )
    default_language = forms.ChoiceField(
        choices=settings.LANGUAGES, label=_("Default language")
    )
    primary = _hex_field(_("Primary colour"))
    accent = _hex_field(_("Accent colour"))

    class Meta:
        model = Institution
        fields = ["name", "logo", "enabled_languages", "default_language", "default_theme"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed the colour fields from existing BrandColor rows, normalized to
        # 6-digit lowercase hex so a pre-existing #fff / #AABBCC / rgb() value can
        # never start the field in a state that rejects an unrelated save.
        rows = {c.key: c.value for c in self.instance.brand_colors.all()} if self.instance.pk else {}
        self.initial.setdefault("primary", normalize_hex(rows.get("primary")) or PRIMARY_DEFAULT.lower())
        self.initial.setdefault("accent", normalize_hex(rows.get("accent")) or ACCENT_DEFAULT.lower())

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError(_("Enable at least one language."))
        return value

    def clean_logo(self):
        value = self.cleaned_data.get("logo")
        if not value:
            return value
        if getattr(value, "size", 0) > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("Logo must be 2 MB or smaller."))
        return value

    def clean_primary(self):
        return self.cleaned_data["primary"].lower()

    def clean_accent(self):
        return self.cleaned_data["accent"].lower()

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error("default_language", _("Default language must be an enabled language."))
        return cleaned

    def save(self, commit=True):
        with transaction.atomic():
            inst = super().save(commit=commit)
            for key in ("primary", "accent"):
                BrandColor.objects.update_or_create(
                    institution=inst, key=key,
                    defaults={"value": self.cleaned_data[key]},
                )
        return inst
```

(`RegexField` is case-insensitive only if we lowercase in `clean_*`; the regex itself accepts `A-Fa-f`, so uppercase validates, and `clean_primary`/`clean_accent` lowercase before save.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_settings_5c_forms.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/forms.py tests/test_settings_5c_forms.py
uv run ruff format institution/forms.py tests/test_settings_5c_forms.py
git add institution/forms.py tests/test_settings_5c_forms.py
git commit -m "feat(5c): BrandingForm with normalized hex colours + atomic BrandColor save"
```

---

## Task 5: AccessForm (signup policy + email-domain allowlist)

**Files:**
- Modify: `institution/forms.py`
- Test: `tests/test_settings_5c_forms.py` (append)

**Interfaces:**
- Produces: `institution.forms.AccessForm` (ModelForm on `Institution`, fields `signup_policy`, `allowed_email_domains`); the domain field is a custom `CharField`+`Textarea` (one domain per line) cleaning to a normalized list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_5c_forms.py`:

```python
from institution.forms import AccessForm


@pytest.mark.django_db
def test_access_form_normalizes_domains():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "open", "allowed_email_domains": "  @School.EDU \nschool.edu\nmail.example.com\n"},
        instance=inst,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_email_domains"] == ["school.edu", "mail.example.com"]


@pytest.mark.django_db
def test_access_form_accepts_subdomains():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "invite", "allowed_email_domains": "mail.example.com"},
        instance=inst,
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_access_form_rejects_garbage_domain():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "invite", "allowed_email_domains": "not a domain"},
        instance=inst,
    )
    assert not form.is_valid()
    assert "allowed_email_domains" in form.errors


@pytest.mark.django_db
def test_access_form_blank_allowlist_is_empty_list():
    inst = Institution.load()
    form = AccessForm({"signup_policy": "invite", "allowed_email_domains": "  \n "}, instance=inst)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_email_domains"] == []


@pytest.mark.django_db
def test_access_form_seeds_textarea_from_list():
    inst = Institution.load()
    inst.allowed_email_domains = ["a.com", "b.org"]
    inst.save()
    form = AccessForm(instance=inst)
    assert form.initial["allowed_email_domains"] == "a.com\nb.org"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_forms.py -k access -q`
Expected: FAIL (`ImportError: cannot import name 'AccessForm'`).

- [ ] **Step 3: Add `AccessForm`**

Add to `institution/forms.py`:

```python
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*)(\.[a-z0-9](-?[a-z0-9])*)+$")


class AccessForm(forms.ModelForm):
    # allowed_email_domains is a JSONField; the default ModelForm widget would
    # demand literal JSON. Override with a plain textarea (one domain per line).
    allowed_email_domains = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        label=_("Allowed email domains"),
        help_text=_("One domain per line. Leave blank to allow any domain."),
    )

    class Meta:
        model = Institution
        fields = ["signup_policy"]  # allowed_email_domains handled manually below

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "allowed_email_domains" not in self.initial:
            self.initial["allowed_email_domains"] = "\n".join(
                self.instance.allowed_email_domains or []
            )

    def clean_allowed_email_domains(self):
        raw = self.cleaned_data.get("allowed_email_domains", "")
        out = []
        for line in raw.splitlines():
            d = line.strip().lower().lstrip("@").strip()
            if not d:
                continue
            if not _DOMAIN_RE.match(d):
                raise forms.ValidationError(_("“%(d)s” is not a valid domain.") % {"d": d})
            if d not in out:  # order-stable dedupe
                out.append(d)
        return out

    def save(self, commit=True):
        self.instance.allowed_email_domains = self.cleaned_data["allowed_email_domains"]
        return super().save(commit=commit)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_settings_5c_forms.py -k access -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/forms.py tests/test_settings_5c_forms.py
uv run ruff format institution/forms.py tests/test_settings_5c_forms.py
git add institution/forms.py tests/test_settings_5c_forms.py
git commit -m "feat(5c): AccessForm with one-per-line normalized email-domain allowlist"
```

---

## Task 6: UploadsForm (extension toggles + size caps)

**Files:**
- Modify: `institution/forms.py`
- Test: `tests/test_settings_5c_forms.py` (append)

**Interfaces:**
- Produces: `institution.forms.UploadsForm` (ModelForm on `Institution`, fields `allowed_image_extensions, allowed_video_extensions, max_image_mib, max_video_mib`); extension fields are `MultipleChoiceField`/`CheckboxSelectMultiple` over the safe set, cleaning to a list with ≥1 enforced per kind; size caps bounded `1 ≤ n ≤ ceiling`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_5c_forms.py`:

```python
from courses import validators as cv
from institution.forms import UploadsForm


def _uploads_data(**over):
    data = {
        "allowed_image_extensions": ["png", "jpg"],
        "allowed_video_extensions": ["mp4"],
        "max_image_mib": "3",
        "max_video_mib": "100",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_uploads_form_saves_subset():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(), instance=inst)
    assert form.is_valid(), form.errors
    form.save()
    inst.refresh_from_db()
    assert inst.allowed_image_extensions == ["png", "jpg"]
    assert inst.max_image_mib == 3


@pytest.mark.django_db
def test_uploads_form_rejects_out_of_safe_set():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(allowed_image_extensions=["png", "svg"]), instance=inst)
    assert not form.is_valid()
    assert "allowed_image_extensions" in form.errors


@pytest.mark.django_db
def test_uploads_form_requires_at_least_one_per_kind():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(allowed_image_extensions=[]), instance=inst)
    assert not form.is_valid()
    assert "allowed_image_extensions" in form.errors


@pytest.mark.django_db
def test_uploads_form_rejects_over_ceiling():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(max_image_mib=str(cv.MAX_IMAGE_MIB_CEILING + 1)), instance=inst)
    assert not form.is_valid()
    assert "max_image_mib" in form.errors


@pytest.mark.django_db
def test_uploads_form_rejects_zero_cap():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(max_image_mib="0"), instance=inst)
    assert not form.is_valid()
    assert "max_image_mib" in form.errors
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_forms.py -k uploads -q`
Expected: FAIL (`ImportError: cannot import name 'UploadsForm'`).

- [ ] **Step 3: Add `UploadsForm`**

Add to `institution/forms.py` (add `from courses import validators as _cv` near the top):

```python
class UploadsForm(forms.ModelForm):
    allowed_image_extensions = forms.MultipleChoiceField(
        choices=[(e, e) for e in _cv.SAFE_IMAGE_EXTENSIONS],
        widget=forms.CheckboxSelectMultiple,
        label=_("Allowed image types"),
    )
    allowed_video_extensions = forms.MultipleChoiceField(
        choices=[(e, e) for e in _cv.SAFE_VIDEO_EXTENSIONS],
        widget=forms.CheckboxSelectMultiple,
        label=_("Allowed video types"),
    )
    max_image_mib = forms.IntegerField(
        min_value=1, max_value=_cv.MAX_IMAGE_MIB_CEILING, label=_("Max image size (MiB)"),
        help_text=_("Up to %(n)d MiB.") % {"n": _cv.MAX_IMAGE_MIB_CEILING},
    )
    max_video_mib = forms.IntegerField(
        min_value=1, max_value=_cv.MAX_VIDEO_MIB_CEILING, label=_("Max video size (MiB)"),
        help_text=_("Up to %(n)d MiB.") % {"n": _cv.MAX_VIDEO_MIB_CEILING},
    )

    class Meta:
        model = Institution
        fields = [
            "allowed_image_extensions", "allowed_video_extensions",
            "max_image_mib", "max_video_mib",
        ]

    def clean_allowed_image_extensions(self):
        value = self.cleaned_data["allowed_image_extensions"]
        if not value:
            raise forms.ValidationError(_("Enable at least one image type."))
        return value

    def clean_allowed_video_extensions(self):
        value = self.cleaned_data["allowed_video_extensions"]
        if not value:
            raise forms.ValidationError(_("Enable at least one video type."))
        return value
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_settings_5c_forms.py -k uploads -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/forms.py tests/test_settings_5c_forms.py
uv run ruff format institution/forms.py tests/test_settings_5c_forms.py
git add institution/forms.py tests/test_settings_5c_forms.py
git commit -m "feat(5c): UploadsForm with safe-set extension toggles + bounded size caps"
```

---

## Task 7: URLs, index GET view, shared context helper

**Files:**
- Create: `institution/views_manage.py`, `institution/urls.py`
- Modify: `config/urls.py`
- Test: `tests/test_settings_5c_views.py` (append)

**Interfaces:**
- Produces URL names: `institution:settings` (`/manage/settings/`), `institution:settings_branding` (`/manage/settings/branding/`), `institution:settings_access` (`/manage/settings/access/`), `institution:settings_uploads` (`/manage/settings/uploads/`).
- Produces `institution.views_manage._settings_context(inst, active_tab, *, branding=None, access=None, uploads=None)` returning the three-form context dict.
- This task ships the index view + the URL stubs for the actions (actual action bodies in Task 8). To keep URLs importable now, define the three action views as minimal `require_POST` stubs that save-and-redirect; Task 8 fleshes out the error path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_5c_views.py`:

```python
from django.urls import reverse

from tests.factories import make_login
from tests.factories import make_pa


@pytest.mark.django_db
def test_settings_index_pa_only(client):
    make_login(client, "plain")  # non-PA
    assert client.get(reverse("institution:settings")).status_code == 403


@pytest.mark.django_db
def test_settings_index_renders_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings"))
    assert resp.status_code == 200
    assert "branding" in resp.context
    assert "access" in resp.context
    assert "uploads" in resp.context
    assert resp.context["active_tab"] == "branding"


@pytest.mark.django_db
def test_settings_index_unknown_tab_falls_back(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=garbage")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "branding"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_views.py -k settings_index -q`
Expected: FAIL (`NoReverseMatch: 'institution' is not a registered namespace`).

- [ ] **Step 3a: Create `institution/views_manage.py`**

```python
"""Platform-admin settings surface: Branding / Access / Uploads tabs."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.forms import UploadsForm
from institution.models import Institution

TABS = ("branding", "access", "uploads")


def _active_tab(request):
    tab = request.GET.get("tab", "branding")
    return tab if tab in TABS else "branding"


def _settings_context(inst, active_tab, *, branding=None, access=None, uploads=None):
    """Assemble the three-form context. Any form passed in (an errored bound form)
    is used as-is; the rest are unbound, seeded from `inst`. Single source of truth
    for the GET index and every action-view error re-render."""
    return {
        "active_tab": active_tab,
        "branding": branding or BrandingForm(instance=inst),
        "access": access or AccessForm(instance=inst),
        "uploads": uploads or UploadsForm(instance=inst),
    }


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    ctx = _settings_context(inst, _active_tab(request))
    return render(request, "institution/manage/settings.html", ctx)


def _save_tab(request, form_cls, ctx_key, active_tab, success_msg):
    inst = Institution.load()
    form = form_cls(request.POST, request.FILES, instance=inst)
    if form.is_valid():
        form.save()  # fires post_save -> invalidate_site_config
        messages.success(request, success_msg)
        return redirect(f"{request.path_info}".replace(active_tab + "/", "").rstrip("/"))
    ctx = _settings_context(inst, active_tab, **{ctx_key: form})
    return render(request, "institution/manage/settings.html", ctx)


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_branding(request):
    return _save_tab(request, BrandingForm, "branding", "branding", _("Branding saved."))


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_access(request):
    return _save_tab(request, AccessForm, "access", "access", _("Access settings saved."))


@require_POST
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_uploads(request):
    return _save_tab(request, UploadsForm, "uploads", "uploads", _("Upload settings saved."))
```

Note: the redirect target in `_save_tab` is refined in Task 8 to a clean `reverse("institution:settings") + "?tab=..."`; for now keep it simple and correct (Task 8 replaces `_save_tab`).

- [ ] **Step 3b: Create `institution/urls.py`**

```python
from django.urls import path

from institution import views_manage

app_name = "institution"

urlpatterns = [
    path("manage/settings/", views_manage.settings, name="settings"),
    path("manage/settings/branding/", views_manage.settings_branding, name="settings_branding"),
    path("manage/settings/access/", views_manage.settings_access, name="settings_access"),
    path("manage/settings/uploads/", views_manage.settings_uploads, name="settings_uploads"),
]
```

- [ ] **Step 3c: Mount it in `config/urls.py`**

Add to `urlpatterns` (alongside the other app includes):

```python
    path("", include("institution.urls")),
```

- [ ] **Step 3d: Minimal template so the GET render works**

Create `templates/institution/manage/settings.html` (a functional stub — full styling in Task 9):

```django
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% trans "Settings" %}</h1>
<nav>{% include "institution/manage/_tabs.html" %}</nav>
<section data-tab="branding" {% if active_tab != "branding" %}hidden{% endif %}>
  <form method="post" action="{% url 'institution:settings_branding' %}" enctype="multipart/form-data">
    {% csrf_token %}{{ branding.as_p }}
    <button type="submit">{% trans "Save branding" %}</button>
  </form>
</section>
<section data-tab="access" {% if active_tab != "access" %}hidden{% endif %}>
  <form method="post" action="{% url 'institution:settings_access' %}">
    {% csrf_token %}{{ access.as_p }}
    <button type="submit">{% trans "Save access" %}</button>
  </form>
</section>
<section data-tab="uploads" {% if active_tab != "uploads" %}hidden{% endif %}>
  <form method="post" action="{% url 'institution:settings_uploads' %}">
    {% csrf_token %}{{ uploads.as_p }}
    <button type="submit">{% trans "Save uploads" %}</button>
  </form>
</section>
{% endblock %}
```

Create `templates/institution/manage/_tabs.html`:

```django
{% load i18n %}
<a href="{% url 'institution:settings' %}?tab=branding">{% trans "Branding" %}</a>
<a href="{% url 'institution:settings' %}?tab=access">{% trans "Access" %}</a>
<a href="{% url 'institution:settings' %}?tab=uploads">{% trans "Uploads" %}</a>
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_settings_5c_views.py -k settings_index -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/views_manage.py institution/urls.py config/urls.py tests/test_settings_5c_views.py
uv run ruff format institution/views_manage.py institution/urls.py config/urls.py tests/test_settings_5c_views.py
git add institution/views_manage.py institution/urls.py config/urls.py templates/institution/ tests/test_settings_5c_views.py
git commit -m "feat(5c): /manage/settings/ index view + tabbed URLs + shared context"
```

---

## Task 8: Action views — PRG, on-error re-render, method contract

**Files:**
- Modify: `institution/views_manage.py`
- Test: `tests/test_settings_5c_views.py` (append)

**Interfaces:**
- Each action view: valid POST → save + success message + `redirect(reverse("institution:settings") + "?tab=<tab>")`; invalid POST → re-render the full index page (200) with the errored form + the other two unbound + that tab active; GET → redirect to the index with `?tab=<tab>` (method contract).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_5c_views.py`:

```python
from institution.models import BrandColor


def _branding_post(**over):
    data = {
        "name": "Greenfield", "enabled_languages": ["en", "pl"],
        "default_language": "en", "default_theme": "auto",
        "primary": "#123abc", "accent": "#abcdef",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_branding_post_saves_and_redirects(client):
    make_pa(client, "pa")
    resp = client.post(reverse("institution:settings_branding"), _branding_post())
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=branding")
    assert BrandColor.objects.get(key="primary").value == "#123abc"


@pytest.mark.django_db
def test_branding_invalid_post_rerenders_full_page(client):
    make_pa(client, "pa")
    resp = client.post(reverse("institution:settings_branding"), _branding_post(primary="nope"))
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "branding"
    assert resp.context["branding"].errors  # errored bound form
    assert resp.context["access"] is not None  # the other two present
    assert resp.context["uploads"] is not None


@pytest.mark.django_db
def test_action_view_get_redirects(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings_access"))
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=access")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_5c_views.py -k "branding_post or action_view" -q`
Expected: FAIL (`test_action_view_get_redirects` 405 not 302; redirect-suffix assertions fail because the stub's redirect target is wrong).

- [ ] **Step 3: Replace the action plumbing in `institution/views_manage.py`**

Replace `_save_tab` and the three action views with:

```python
from django.urls import reverse


def _index_url(tab):
    return f"{reverse('institution:settings')}?tab={tab}"


def _action(request, form_cls, ctx_key, tab, success_msg):
    if request.method == "GET":
        return redirect(_index_url(tab))  # method contract: actions are POST targets
    inst = Institution.load()
    form = form_cls(request.POST, request.FILES, instance=inst)
    if form.is_valid():
        form.save()  # fires post_save -> invalidate_site_config
        messages.success(request, success_msg)
        return redirect(_index_url(tab))
    ctx = _settings_context(inst, tab, **{ctx_key: form})
    return render(request, "institution/manage/settings.html", ctx)


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_branding(request):
    return _action(request, BrandingForm, "branding", "branding", _("Branding saved."))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_access(request):
    return _action(request, AccessForm, "access", "access", _("Access settings saved."))


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_uploads(request):
    return _action(request, UploadsForm, "uploads", "uploads", _("Upload settings saved."))
```

Remove the `@require_POST` decorator and the now-unused `_save_tab`/`from django.views.decorators.http import require_POST` import (the GET branch handles method routing). Keep `ctx_key` matching `_settings_context`'s kwargs (`branding`/`access`/`uploads`).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_settings_5c_views.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/views_manage.py tests/test_settings_5c_views.py
uv run ruff format institution/views_manage.py tests/test_settings_5c_views.py
git add institution/views_manage.py tests/test_settings_5c_views.py
git commit -m "feat(5c): settings action views (PRG, invalid re-render, method contract)"
```

---

## Task 9: Templates + settings.css + screenshot verification

**Files:**
- Modify: `templates/institution/manage/settings.html`, `_tabs.html`
- Create: `templates/institution/manage/_branding_tab.html`, `_access_tab.html`, `_uploads_tab.html`, `static/css/settings.css`
- Test: manual screenshot harness (throwaway, delete after).

This task is presentation only — no Python behavior changes, so it has no pytest cycle; its gate is the screenshots + the existing view tests staying green.

- [ ] **Step 1: Build the real tab partials and page**

Flesh out `settings.html` to: load `settings.css` via `{% block extra_css %}` (match how other manage pages link per-page CSS — grep `analytics_matrix.html` or `people.html` for the pattern), render a proper tab bar (`is-on` active class like `accounts/manage/_tabs.html`), and `{% include %}` the three tab partials. Each tab partial renders its form fields with labels/help text and a Save button, reusing shared `.btn` / form-input tokens. For the Branding tab, render each colour as a paired `<input type="color">` + the hex text field, wired by a tiny inline script that mirrors the two (`data-hex` hook from Task 4). Use `{% comment %}` for any multi-line template comments (single-line `{# #}` only — a shipped-3× footgun).

- [ ] **Step 2: Screenshot light + dark + mobile**

Write a throwaway Playwright script under the scratchpad dir (NOT `tests/`) that logs in as a PA, visits `/manage/settings/?tab=branding|access|uploads`, and screenshots each at desktop + mobile widths in light and dark. Save PNGs to scratchpad.

Run: `uv run python <scratchpad>/shoot_settings.py`

- [ ] **Step 3: Self-review the screenshots**

Open each PNG. Check: colour pickers visible on dark cards (watch `--border-strong`); checkbox groups legible; tab bar active state clear; mobile stacks without overflow. Fix CSS until clean. Delete the harness + PNGs when satisfied.

- [ ] **Step 4: Confirm view tests still pass**

Run: `uv run pytest tests/test_settings_5c_views.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check institution/  # no python changed, but cheap to confirm
git add templates/institution/ static/css/settings.css
git commit -m "feat(5c): style /manage/settings/ tabs (light/dark/mobile verified)"
```

---

## Task 10: Invite-domain non-blocking warning

**Files:**
- Modify: `accounts/provisioning.py`, `accounts/views_manage.py`
- Test: `tests/test_invite_domain_warning.py` (create)

**Interfaces:**
- Produces `accounts.provisioning.normalized_allowlist(domains) -> set[str]` (lowercased, `@`/whitespace-stripped); `evaluate_sso_provisioning` reuses it.
- `accounts.views_manage.invitation_send` attaches a warning message when an allowlist is set and the invited domain is outside it. Invite still succeeds.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_invite_domain_warning.py`:

```python
import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from accounts.provisioning import normalized_allowlist
from institution.models import Institution
from tests.factories import make_pa


def test_normalized_allowlist():
    assert normalized_allowlist([" @School.EDU ", "b.com"]) == {"school.edu", "b.com"}


def _send(client, email):
    return client.post(
        reverse("accounts:invitation_send"),
        {"email": email, "role": "student"},
        follow=True,
    )


@pytest.mark.django_db
def test_warns_on_out_of_domain_invite(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    resp = _send(client, "new@outside.com")
    texts = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("outside.com" in t for t in texts)


@pytest.mark.django_db
def test_no_warning_for_in_domain_invite(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    resp = _send(client, "new@school.edu")
    texts = " ".join(m.message for m in get_messages(resp.wsgi_request))
    assert "not in your allowed" not in texts


@pytest.mark.django_db
def test_no_warning_when_allowlist_empty(client):
    make_pa(client, "pa")  # default allowlist is empty
    resp = _send(client, "new@anywhere.com")
    texts = " ".join(m.message for m in get_messages(resp.wsgi_request))
    assert "not in your allowed" not in texts
```

Confirm the `role` value: check `accounts/forms.py:SendInvitationForm` / `institution/roles.py` for the exact role key (likely `"student"`); adjust the test payload to a valid choice.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_invite_domain_warning.py -q`
Expected: FAIL (`ImportError: cannot import name 'normalized_allowlist'`).

- [ ] **Step 3a: Factor the helper in `accounts/provisioning.py`**

Add:

```python
def normalized_allowlist(allowed_email_domains):
    """The stored allowlist as a normalized set (lowercased, @/whitespace-stripped)."""
    return {entry.strip().lower().lstrip("@") for entry in allowed_email_domains}
```

Replace the inline set-comprehension in `evaluate_sso_provisioning` with `allowed = normalized_allowlist(allowed_email_domains)`.

- [ ] **Step 3b: Add the warning in `accounts/views_manage.py:invitation_send`**

In the success branch, before `return redirect(...)`:

```python
            messages.success(request, _("Invitation sent."))
            from accounts.provisioning import email_domain
            from accounts.provisioning import normalized_allowlist
            from institution.models import Institution

            allowed = normalized_allowlist(Institution.load().allowed_email_domains)
            domain = email_domain(form.cleaned_data["email"])
            if allowed and domain not in allowed:
                messages.warning(
                    request,
                    _("Note: %(domain)s is not in your allowed email domains.")
                    % {"domain": domain},
                )
            return redirect("accounts:people_invitations")
```

(Plain text, no backticks — Django messages render verbatim.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_invite_domain_warning.py -q`
Expected: PASS. Also run the existing provisioning tests to confirm the refactor is behaviour-preserving: `uv run pytest tests/ -k provisioning -q`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check accounts/provisioning.py accounts/views_manage.py tests/test_invite_domain_warning.py
uv run ruff format accounts/provisioning.py accounts/views_manage.py tests/test_invite_domain_warning.py
git add accounts/provisioning.py accounts/views_manage.py tests/test_invite_domain_warning.py
git commit -m "feat(5c): non-blocking out-of-domain invite warning (factored allowlist normalizer)"
```

---

## Task 11: Cutover — retire old form/view, redirect old URL, repoint nav, migrate tests

**Files:**
- Modify: `core/views.py`, `core/urls.py`, `institution/forms.py`, `templates/base.html`, `templates/core/home.html`
- Modify (migrate): `tests/test_settings_forms.py`, `tests/test_e2e_settings.py`, `tests/test_settings_styles.py`, `tests/test_surfaces.py`, `tests/test_i18n_ws4.py`

This single task does the breaking changes and their test migrations together so the suite never goes red between commits.

- [ ] **Step 1: Grep for every reference**

```bash
uv run python - <<'PY'
import subprocess
for term in ("institution_settings", "InstitutionSettingsForm", "settings/institution"):
    print("==", term)
    print(subprocess.run(["git", "grep", "-n", term], capture_output=True, text=True).stdout)
PY
```
Catalogue every hit outside `docs/` and `locale/`. Expect: `core/views.py`, `core/urls.py`, `institution/forms.py`, `templates/base.html`, `templates/core/home.html`, and the 5 test files.

- [ ] **Step 2: Redirect the old URL, keep the name bound (`core/views.py` + `core/urls.py`)**

In `core/views.py`, replace the `institution_settings` view with a redirect (drop the `InstitutionSettingsForm` import):

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def institution_settings(request):
    """Retired in 5c: the settings UI moved to /manage/settings/. Kept as a named
    redirect so existing reverses/bookmarks resolve."""
    return redirect("institution:settings")
```

`core/urls.py` keeps the `path("settings/institution/", views.institution_settings, name="institution_settings")` line unchanged (name stays bound). Confirm the redirect is a 302 (Django `redirect()` default).

- [ ] **Step 3: Retire `InstitutionSettingsForm` and repoint nav**

In `institution/forms.py`, delete the `InstitutionSettingsForm` class (keep `MAX_LOGO_BYTES` — `test_settings_forms.py` imports it and `BrandingForm` uses it).

In `templates/base.html:116` and `templates/core/home.html:44`, change `{% url 'core:institution_settings' %}` → `{% url 'institution:settings' %}` and update the link label if desired (`"Institution settings"` → `"Settings"`). Leave the surrounding `is_platform_admin` guards intact.

- [ ] **Step 4: Migrate the existing tests**

- `tests/test_settings_forms.py`: the `InstitutionSettingsForm` block (the `_inst_data` helper + its 6 tests, lines ~91-159) is superseded by `tests/test_settings_5c_forms.py`. Delete that block and the now-unused `InstitutionSettingsForm` import; keep the `UserSettingsForm` tests and the `MAX_LOGO_BYTES` import only if still referenced (it no longer is here — remove it).
- `tests/test_e2e_settings.py`, `tests/test_settings_styles.py`, `tests/test_surfaces.py`, `tests/test_i18n_ws4.py`: re-point any request to `/settings/institution/` or `reverse("core:institution_settings")` at `reverse("institution:settings")`. For an assertion that the redirect itself works, add/keep a check that `GET /settings/institution/` returns 302 → `/manage/settings/`. Read each test and adjust the URL + any asserted page copy to the new page. Delete assertions that targeted the retired single-form layout if they no longer map.

- [ ] **Step 5: Run the full suite (non-e2e), lint, commit**

```bash
uv run pytest -q -m "not e2e"
uv run ruff check core/views.py core/urls.py institution/forms.py tests/test_settings_forms.py tests/test_settings_styles.py tests/test_surfaces.py tests/test_i18n_ws4.py
uv run ruff format core/views.py core/urls.py institution/forms.py tests/
git add core/ institution/forms.py templates/base.html templates/core/home.html tests/
git commit -m "feat(5c): cut over to /manage/settings/ (redirect old URL, repoint nav, migrate tests)"
```
Expected: full non-e2e suite green.

---

## Task 12: i18n — EN/PL strings

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en` (or the project's documented invocation — grep prior plans for the exact flags).

- [ ] **Step 2: Translate the new msgids in `locale/pl/LC_MESSAGES/django.po`**

Provide PL translations for every new 5c string: "Settings", "Branding", "Access", "Uploads", "Primary colour", "Accent colour", "Allowed email domains", "One domain per line. Leave blank to allow any domain.", "Allowed image types", "Allowed video types", "Max image size (MiB)", "Max video size (MiB)", "Enable at least one image type.", "Enable at least one video type.", "Enter a 6-digit hex colour like #147E78.", "Branding saved.", "Access settings saved.", "Upload settings saved.", "Note: %(domain)s is not in your allowed email domains.", the size "max %(mib)d MiB" messages, etc.

- [ ] **Step 3: Clear stale fuzzy flags and verify**

`makemessages` re-marks copied translations `#, fuzzy` (ignored at runtime). Remove the `#, fuzzy` line above every 5c msgid you translated, and verify it didn't mis-guess (e.g. grep the new msgids and eyeball the `msgstr`). Compile: `uv run python manage.py compilemessages`.

- [ ] **Step 4: Spot-check under PL**

Run a quick check (or a throwaway request with `LANGUAGE_CODE='pl'`) that the settings page renders Polish labels. Confirm no missing/garbled msgstrs for the new keys.

- [ ] **Step 5: Commit**

```bash
git add locale/
git commit -m "i18n(5c): EN/PL strings for /manage/settings/"
```

---

## Task 13: e2e — colour applied, extension narrowing rejects, invite warning

**Files:**
- Create: `tests/test_e2e_settings_5c.py`

Mirror `tests/test_e2e_subjects.py` (the `_make_pa_user` / `_login` / `_logout` helpers; `pytestmark = pytest.mark.e2e`; `@pytest.mark.django_db(transaction=True)`).

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_settings_5c.py` with one test that, driving the real UI:
1. logs in a PA, goes to `/manage/settings/?tab=branding`, sets the **primary** hex field to a distinctive value (e.g. `#ff0000`) and saves; reloads any page and asserts the rendered `<style>` from `{% brand_vars %}` contains `--brand-primary: #ff0000`.
2. goes to `/manage/settings/?tab=uploads`, unchecks `gif`, saves; opens a course media manager and attempts to upload a `.gif`, asserting the rejection message appears.
3. goes to `/manage/settings/?tab=access`, sets an allowlist (`school.edu`), saves; sends an invite to `someone@outside.com` via the People → Invitations UI and asserts the non-blocking warning text appears alongside the success message.

Use real gestures (`fill`, `check`/`uncheck`, `click`), `wait_for_url` / `wait_for_selector` between steps. Use `TEST_PASSWORD`. Keep each sub-flow assertion specific with a helpful failure message (include `page.content()[:600]`).

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest tests/test_e2e_settings_5c.py -m e2e -q`
Expected: PASS (real Playwright). If the media-upload sub-flow is brittle, scope it to the smallest reliable gesture that proves the narrowed extension is rejected.

- [ ] **Step 3: Run the full e2e marker to confirm no regressions**

Run: `uv run pytest -m e2e -q`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check tests/test_e2e_settings_5c.py
uv run ruff format tests/test_e2e_settings_5c.py
git add tests/test_e2e_settings_5c.py
git commit -m "test(5c): e2e — brand colour applied, extension narrowing, invite warning"
```

---

## Definition of Done (whole branch)

- [ ] Full non-e2e suite green: `uv run pytest -q -m "not e2e"`.
- [ ] e2e green: `uv run pytest -q -m e2e`.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean.
- [ ] No missing migrations: `uv run python manage.py makemigrations --check --dry-run`.
- [ ] `uv run python manage.py migrate` clean from empty; `/manage/settings/` reachable PA-only; `/settings/institution/` 302s to it.
- [ ] PL `.mo` compiled; new strings render under PL.
- [ ] Screenshots reviewed (light/dark/mobile) and harness deleted.

## Self-Review (author checklist — done)

- **Spec coverage:** branding palette+logo (T4, T9), upload toggles+caps with safe-set ceiling (T1-T3, T6), email-domain editable (T5) + invite warning (T10), `/manage/settings/` tabbed with redirect+name retention (T7, T8, T11), i18n (T12), e2e (T13), existing-test migration (T11). All spec sections map to a task.
- **Boundary items from spec:** `_committed` skip for both extension+size (T1), fail-closed empty-list + ≥1-per-kind (T1/T6), `cfg.get` fallback + `_DEFAULTS` keys (T3), callable JSON defaults (T2), uppercase/`#rgb` colour-seed normalization (T4), function-scope import (T1), `transaction.atomic` (T4), `?tab=` fallback + method contract (T7/T8) — each has an explicit test.
- **Type consistency:** `effective_*` / `validate_image_file` / `normalize_hex` / `normalized_allowlist` / `_settings_context` / `BrandingForm`/`AccessForm`/`UploadsForm` / `institution:settings*` names are used consistently across producing and consuming tasks.
