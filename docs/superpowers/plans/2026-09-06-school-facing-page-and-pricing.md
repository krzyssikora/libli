# School-facing page and editable pricing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a vendor-only `/for-schools/` public page carrying editable pricing plans, and trim `/getting-started/` back to sign-in help.

**Architecture:** A `PricingPlan` model (three migration-seeded rows, no `Institution` FK) plus four `Institution` fields reach the public renderer through the existing cached `cfg` bundle. Three new **block** tokens render the plans table, the VAT note and a conditional cross-pointer. A new `VENDOR_INSTANCE` deploy setting gates the page, its footer links and a new Pricing settings tab, so a hosted school never publishes our price list.

**Tech Stack:** Django 5.2.15, PostgreSQL, `nh3` + `python-markdown` for public pages, `pytest`/`pytest-django`, Playwright for captures, `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-09-06-school-facing-page-and-pricing-design.md`

## Global Constraints

- **All tooling runs through `uv`**: `uv run pytest <paths>`, `uv run ruff check --no-cache .`, `uv run ruff format .`. Bare `pytest`/`ruff` are not on PATH.
- **Start the test DB first**: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. Without it a run hangs for ~4m21s before erroring.
- **Never pass `-q` to pytest** — `addopts` already has it; a second one suppresses the `N passed` summary line.
- **Both ruff gates before any commit**: `uv run ruff check --no-cache .` AND `uv run ruff format --check .`. CI gates on them separately.
- **`_` in `core/public_pages.py` is `gettext_lazy`** and must stay that way (`PAGES` resolves it at import). New strings in that module use eager, unaliased `from django.utils.translation import gettext`.
- **`CheckConstraint(condition=...)`, never `check=`** — `check=` emits `RemovedInDjango60Warning` on every model import.
- **Every block token value is `""` or one-or-more complete block elements**, never bare inline content — `_block_re` swallows the enclosing `<p>`.
- **Amount format:** `f"{d.quantize(Decimal('0.01')):,f}".replace(",", "\u00a0")`. Separator is U+00A0. No currency symbol per cell.
- **Seed rows exist in every test database** (no `--nomigrations`). Fixtures **UPDATE** `PricingPlan.objects.order_by("order")`; they never `create()`.
- **Never `{# #}` across two lines** in a template — use `{% comment %}`. This has shipped five times.
- Django's `{#`-comment and i18n `.po` work is Task 15; do not run `makemessages` mid-plan.

---

### Task 1: `PricingPlan` model, `Institution` fields, and the seeded migration

**Files:**
- Modify: `institution/models.py`
- Create: `institution/migrations/0012_pricingplan_and_institution_pricing_fields.py`
- Test: `tests/test_pricing_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `institution.models.PricingPlan` with fields `order` (unique `PositiveSmallIntegerField`), `pupils_min`, `pupils_max` (`PositiveIntegerField`), `annual_price` (`DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)`), `support_hours_per_term`, `courses_included`, `video_hours_included` (`PositiveSmallIntegerField`); `Meta.ordering = ["order"]`; constraint `pricingplan_band_is_ordered`. `Institution.currency`, `.vat_note_en`, `.vat_note_pl`, `.storage_allowance_gb`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_model.py
"""PricingPlan's shape, its database constraint, and the migration seed.

The constraint is a BACKSTOP for out-of-band writes. The admin-facing check is
the pricing form's clean() (Task 14) -- Django never calls full_clean() on
save(), so a model clean() here would be dead code.
"""

import pytest
from decimal import Decimal
from django.db import IntegrityError, transaction

from institution.models import Institution, PricingPlan


@pytest.mark.django_db
def test_migration_seeds_three_bands_priceless():
    """The shipped state: three gap-free monotonic bands, no prices."""
    rows = list(PricingPlan.objects.order_by("order"))
    assert [(r.order, r.pupils_min, r.pupils_max) for r in rows] == [
        (1, 1, 150),
        (2, 151, 400),
        (3, 401, 800),
    ]
    assert [r.annual_price for r in rows] == [None, None, None]
    assert [r.support_hours_per_term for r in rows] == [6, 8, 12]
    assert [r.courses_included for r in rows] == [3, 6, 12]
    assert [r.video_hours_included for r in rows] == [10, 20, 40]


@pytest.mark.django_db
def test_seeded_bands_are_gap_free_and_monotonic():
    """The seed must satisfy the form's own cross-row rules, or the settings tab
    rejects the shipped state on an operator's first save."""
    rows = list(PricingPlan.objects.order_by("order"))
    for lo, hi in zip(rows, rows[1:]):
        assert hi.pupils_min == lo.pupils_max + 1


@pytest.mark.django_db
def test_constraint_rejects_a_reversed_band():
    """Wrapped in atomic(): an IntegrityError poisons the surrounding pytest-django
    transaction, and any later ORM call would raise TransactionManagementError and
    read as an unrelated failure."""
    row = PricingPlan.objects.get(order=1)
    row.pupils_min, row.pupils_max = 300, 200
    with pytest.raises(IntegrityError), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_institution_pricing_field_defaults():
    inst = Institution.load()
    assert inst.currency == "PLN"
    assert inst.vat_note_en == ""
    assert inst.vat_note_pl == ""
    assert inst.storage_allowance_gb is None


@pytest.mark.django_db
def test_annual_price_accepts_two_decimal_places():
    row = PricingPlan.objects.get(order=1)
    row.annual_price = Decimal("4800.00")
    row.save()
    assert PricingPlan.objects.get(order=1).annual_price == Decimal("4800.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_model.py`
Expected: FAIL — `ImportError: cannot import name 'PricingPlan' from 'institution.models'`

- [ ] **Step 3: Add the model and the Institution fields**

```python
# institution/models.py -- append near BrandColor; add the imports at the top:
#   from django.db.models import F, Q

class PricingPlan(models.Model):
    """One published pricing band. Three rows, seeded by migration 0012.

    NO Institution FK, unlike BrandColor: libli is single-tenant per box, so a FK
    would buy nothing -- but the consequence is load-bearing, because
    core.services._build() cannot reach these rows through the Institution
    instance and must query them BEFORE its no-Institution early return.

    Plans carry no NAME. The row label is the pupil band, which is a number and
    therefore identical in English and Polish -- that is what makes the EN/PL
    figure-parity guard achievable at all.

    Validation lives in the pricing form's clean() and in the constraint below,
    never in a model clean(): Django does not call full_clean() on save(), and
    neither write path (the migration's historical model, the form's field
    assignment) would invoke one.
    """

    order = models.PositiveSmallIntegerField(unique=True)
    # Stored explicitly, NOT derived from the previous row's max: derivation is
    # unstated cleverness that silently produces nonsense on non-monotonic input.
    pupils_min = models.PositiveIntegerField()
    # The open-ended top tier is emitted by the renderer, so there is no null case.
    pupils_max = models.PositiveIntegerField()
    # Null => "by arrangement". max_digits AND decimal_places are both mandatory:
    # Django's system checks reject a DecimalField missing either (E132 / E130).
    annual_price = models.DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True
    )
    support_hours_per_term = models.PositiveSmallIntegerField()
    courses_included = models.PositiveSmallIntegerField()
    video_hours_included = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            # condition=, NOT check=: check= emits RemovedInDjango60Warning on
            # every model import (noise on every test session) and stops working
            # in Django 6.0.
            models.CheckConstraint(
                condition=Q(pupils_min__lt=F("pupils_max")),
                name="pricingplan_band_is_ordered",
            )
        ]

    def __str__(self):
        return f"{self.pupils_min}-{self.pupils_max}"
```

```python
# institution/models.py -- inside class Institution, beside controller_name:

    # Pricing, published on /for-schools/ (vendor instances only).
    currency = models.CharField(
        max_length=3,
        default="PLN",
        verbose_name=_("Currency"),
        help_text=_("ISO 4217 code, shown in the price column header."),
    )
    # PER-LANGUAGE, and that is forced: plans carry no name precisely because only
    # language-neutral values may be stored once. A VAT note is prose, so one field
    # would print a Polish tax statement on the English page while the numeric
    # parity test stayed green.
    vat_note_en = models.TextField(blank=True, default="")
    vat_note_pl = models.TextField(blank=True, default="")
    # Null => the allowance sentence is omitted entirely.
    storage_allowance_gb = models.PositiveIntegerField(null=True, blank=True)
```

- [ ] **Step 4: Generate the migration and add the seed**

Run: `uv run python manage.py makemigrations institution -n pricingplan_and_institution_pricing_fields`

Then hand-add the `RunPython` **last** in `operations`. The autodetector emits `CreateModel`, four `AddField`s and a separate `AddConstraint` (it pops `constraints` out of the model options) — that is correct, do not fight it.

```python
# institution/migrations/0012_...py -- add above Migration, then append to operations

def seed_plans(apps, schema_editor):
    """Three structural placeholder bands, priceless.

    get_or_create, never update_or_create: a re-run must never overwrite a
    school's edited prices. defaults= is MANDATORY -- five fields are
    non-nullable with no default, so a bare get_or_create(order=N) raises
    IntegrityError on a fresh database.
    """
    PricingPlan = apps.get_model("institution", "PricingPlan")
    for order, lo, hi, hours, courses, video in (
        (1, 1, 150, 6, 3, 10),
        (2, 151, 400, 8, 6, 20),
        (3, 401, 800, 12, 12, 40),
    ):
        PricingPlan.objects.get_or_create(
            order=order,
            defaults={
                "pupils_min": lo,
                "pupils_max": hi,
                "annual_price": None,
                "support_hours_per_term": hours,
                "courses_included": courses,
                "video_hours_included": video,
            },
        )


# ... in Migration.operations, AFTER CreateModel / AddField / AddConstraint:
        migrations.RunPython(seed_plans, migrations.RunPython.noop),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_model.py`
Expected: PASS (5 tests)

- [ ] **Step 6: Confirm no model-check regressions**

Run: `uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run`
Expected: no issues, no pending migrations.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add institution/models.py institution/migrations/0012_*.py tests/test_pricing_model.py
git commit -m "feat(pricing): PricingPlan model, Institution pricing fields, seeded bands"
```

---

### Task 2: The `VENDOR_INSTANCE` setting and its test pin

**Files:**
- Modify: `config/settings/base.py`, `config/settings/test.py`, `.env.production.example`, `docs/deployment.md`
- Test: `tests/test_vendor_instance_setting.py`

**Interfaces:**
- Produces: `settings.VENDOR_INSTANCE` (bool, default `False`), read from env `LIBLI_VENDOR_INSTANCE`. Pinned `False` in the test settings.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vendor_instance_setting.py
"""VENDOR_INSTANCE is a DEPLOY fact, not a school-editable preference.

It gates /for-schools/, its footer links and the Pricing settings tab, so a
hosted school never publishes our price list. It is a setting rather than an
Institution field precisely so a school admin cannot toggle it.
"""

from django.conf import settings
from django.test import override_settings


def test_defaults_to_false_under_test_settings():
    """PINNED in config/settings/test.py, not merely defaulted.

    base.py does env.read_env(BASE_DIR/".env"), which copies a developer's local
    .env into os.environ, and test.py does `from base import *`. Whoever builds
    this page will set LIBLI_VENDOR_INSTANCE=true in their own .env to see the
    page on runserver -- and without the pin that flips the flag for the ENTIRE
    test run, reddening every gate-off assertion for a reason unrelated to the
    code. tests/test_transfer_caps_env.py records this exact leak happening
    before.
    """
    assert settings.VENDOR_INSTANCE is False


def test_the_pin_is_in_the_test_settings_module_not_just_the_env():
    """Falsification: reading the source proves the pin exists, where asserting
    the value alone would pass on a machine that simply has no .env."""
    from pathlib import Path

    source = Path(settings.BASE_DIR, "config", "settings", "test.py").read_text(
        encoding="utf-8"
    )
    assert "VENDOR_INSTANCE = False" in source


@override_settings(VENDOR_INSTANCE=True)
def test_tests_opt_back_in_with_override_settings():
    assert settings.VENDOR_INSTANCE is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vendor_instance_setting.py`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'VENDOR_INSTANCE'`

- [ ] **Step 3: Add the setting and the pin**

```python
# config/settings/base.py -- beside GEOGEBRA_API_LOOKUP
# This box is the VENDOR's own instance (libli.pl), not a school's. Gates
# /for-schools/, its footer links and the Pricing settings tab. Env var carries
# the LIBLI_ prefix, the setting drops it -- same convention as
# ALLOW_HTTP_IMAGE_FETCH and GEOGEBRA_API_LOOKUP.
VENDOR_INSTANCE = env.bool("LIBLI_VENDOR_INSTANCE", default=False)
```

```python
# config/settings/test.py -- beside GEOGEBRA_API_LOOKUP = False
# The suite must never see the vendor page by accident. Pinned rather than
# inherited because base.py reads a developer's .env into os.environ, and whoever
# is building the page will have LIBLI_VENDOR_INSTANCE=true set there. Tests that
# exercise the vendor page opt back in with override_settings(VENDOR_INSTANCE=True)
# -- never through the environment.
VENDOR_INSTANCE = False
```

- [ ] **Step 4: Document it for the operator**

```bash
# .env.production.example -- append with a comment
# Set to true ONLY on the vendor's own instance (libli.pl). Publishes
# /for-schools/ with the price list and the Pricing settings tab. Leave unset or
# false on every school box.
LIBLI_VENDOR_INSTANCE=false
```

Add one line to `docs/deployment.md` in the environment-variable section noting that turning the school-facing page on is a **deploy** step (edit `.env.production`, then `up -d`), not a settings toggle.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vendor_instance_setting.py`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add config/settings/base.py config/settings/test.py .env.production.example docs/deployment.md tests/test_vendor_instance_setting.py
git commit -m "feat(pricing): VENDOR_INSTANCE deploy setting, pinned False in tests"
```

---

### Task 3: Pricing data in the `cfg` bundle, and cache invalidation

**Files:**
- Modify: `core/services.py`, `core/apps.py`
- Test: `tests/test_public_pages_config.py` (extend), `tests/test_pricing_config_bundle.py` (create)

**Interfaces:**
- Consumes: `institution.models.PricingPlan`, `Institution.currency` / `.vat_note_en` / `.vat_note_pl` / `.storage_allowance_gb` (Task 1).
- Produces: `cfg["pricing_plans"]` — a list of dicts ordered by `order`, each `{"order", "pupils_min", "pupils_max", "annual_price", "support_hours_per_term", "courses_included", "video_hours_included"}` where `annual_price` is `Decimal | None`. Plus `cfg["currency"]`, `cfg["vat_note_en"]`, `cfg["vat_note_pl"]`, `cfg["storage_allowance_gb"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_config_bundle.py
"""The plan rows reach the renderer through cfg, and a price edit is visible now.

substitute_tokens takes cfg as an argument and core/services.py documents the
bundle as the injectable single source of truth that NEVER writes -- so the
renderer must do no ORM query of its own, or every render of /privacy/ would pay
for it too.
"""

import pytest
from decimal import Decimal
from django.core.cache import cache

from core.services import _DEFAULTS, get_site_config
from institution.models import Institution, PricingPlan


@pytest.mark.django_db
def test_bundle_carries_the_seeded_plans_in_order():
    plans = get_site_config()["pricing_plans"]
    assert [p["order"] for p in plans] == [1, 2, 3]
    assert plans[0]["pupils_min"] == 1
    assert plans[-1]["pupils_max"] == 800


@pytest.mark.django_db
def test_annual_price_is_a_decimal_not_a_preformatted_string():
    """Formatting stays in the renderer, which is the layer the parity test reads."""
    PricingPlan.objects.filter(order=1).update(annual_price=Decimal("4800.00"))
    cache.clear()
    assert get_site_config()["pricing_plans"][0]["annual_price"] == Decimal("4800.00")


@pytest.mark.django_db
def test_plans_survive_the_no_institution_row_path():
    """THE early-return trap. PricingPlan has no FK to Institution, and _build()
    returns dict(_DEFAULTS) early when there is no Institution row -- so a query
    placed after that branch hands back [] with the rows sitting unread in the
    database, and the page shows the no-prices fallback while priced plans exist.

    A price is set first because with all prices null the two builds are
    byte-identical downstream and this test could not discriminate.
    """
    PricingPlan.objects.filter(order=1).update(annual_price=Decimal("4800.00"))
    Institution.objects.all().delete()
    cache.clear()
    plans = get_site_config()["pricing_plans"]
    assert [p["order"] for p in plans] == [1, 2, 3]
    assert plans[0]["annual_price"] == Decimal("4800.00")


@pytest.mark.django_db
def test_defaults_carry_the_pricing_keys():
    assert _DEFAULTS["pricing_plans"] == []
    assert _DEFAULTS["currency"] == "PLN"
    assert _DEFAULTS["vat_note_en"] == ""
    assert _DEFAULTS["vat_note_pl"] == ""
    assert _DEFAULTS["storage_allowance_gb"] is None


@pytest.mark.django_db
def test_a_price_edit_invalidates_the_cache():
    """PRIME THE CACHE FIRST. tests/conftest.py's autouse _clear_site_cache calls
    cache.clear() before every test, so a test that edits and THEN reads finds an
    empty cache, rebuilds from the database, and sees the new price whether or not
    PricingPlan is in core/apps.py's signal tuple -- the mutant survives.
    """
    assert get_site_config()["pricing_plans"][0]["annual_price"] is None  # primes
    row = PricingPlan.objects.get(order=1)
    row.annual_price = Decimal("5100.00")
    row.save()
    assert get_site_config()["pricing_plans"][0]["annual_price"] == Decimal("5100.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_config_bundle.py`
Expected: FAIL — `KeyError: 'pricing_plans'`

- [ ] **Step 3: Add the keys, querying plans before the early return**

```python
# core/services.py -- add to _DEFAULTS
    "pricing_plans": [],
    "currency": "PLN",
    "vat_note_en": "",
    "vat_note_pl": "",
    "storage_allowance_gb": None,
```

```python
# core/services.py -- add above _build()
def _pricing_plans():
    """Plan rows as plain dicts, ordered.

    annual_price stays a Decimal (or None): formatting belongs to the renderer,
    which is the layer the EN/PL parity guard reads.
    """
    from institution.models import PricingPlan

    return [
        {
            "order": p.order,
            "pupils_min": p.pupils_min,
            "pupils_max": p.pupils_max,
            "annual_price": p.annual_price,
            "support_hours_per_term": p.support_hours_per_term,
            "courses_included": p.courses_included,
            "video_hours_included": p.video_hours_included,
        }
        # Explicit order_by even though Meta.ordering supplies it: belt and braces
        # on the one query whose output order is publicly visible.
        for p in PricingPlan.objects.order_by("order")
    ]
```

```python
# core/services.py -- in _build(), BEFORE the inst-is-None branch
def _build():
    from institution.models import Institution

    # BEFORE the early return, and that ordering is load-bearing: PricingPlan has
    # no FK to Institution, so on a box where the migration has seeded plans but
    # nothing has created the Institution row yet, querying after the branch would
    # hand back [] with the rows unread.
    plans = _pricing_plans()

    inst = Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    if inst is None:
        return {**_DEFAULTS, "pricing_plans": plans}
    ...
    return {
        ...
        "pricing_plans": plans,
        "currency": inst.currency or _DEFAULTS["currency"],
        "vat_note_en": inst.vat_note_en,
        "vat_note_pl": inst.vat_note_pl,
        "storage_allowance_gb": inst.storage_allowance_gb,
    }
```

```python
# core/apps.py -- add PricingPlan to the signal tuple
        from institution.models import BrandColor
        from institution.models import Institution
        from institution.models import PricingPlan

        for model in (Institution, BrandColor, PricingPlan):
```

- [ ] **Step 4: Extend the two existing bundle-parity tests**

In `tests/test_public_pages_config.py`, add the five keys to `NEW_KEYS`, and add value assertions to `test_defaults_carry_every_new_key_with_the_right_values` — `currency == "PLN"`, `pricing_plans == []`, `storage_allowance_gb is None`, and slot `vat_note_en` / `vat_note_pl` into that test's existing `== ""` loop. `NEW_KEYS` alone only strengthens key parity; without the value assertions a `currency` default of `""` ships green and prints `Annual price ()` as a column header.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_config_bundle.py tests/test_public_pages_config.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/services.py core/apps.py tests/test_pricing_config_bundle.py tests/test_public_pages_config.py
git commit -m "feat(pricing): plan rows and pricing fields in the cached site bundle"
```

---

### Task 4: Thread the resolved language through `substitute_tokens`

**Files:**
- Modify: `core/public_pages.py`, `tests/test_public_pages.py`, `tests/test_public_pages_content.py`
- Test: `tests/test_public_pages_language.py` (create)

**Interfaces:**
- Produces: `substitute_tokens(html, cfg, lang)` — `lang` positional-required. `_block_values(cfg, lang)` as a module-level helper mirroring `_inline_values`, so the block map can be asserted directly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_language.py
"""The renderer resolves tokens under the PAGE's language, not the thread's.

core/help.localized_doc_path falls back to the English base when a .pl.md file is
absent, so resolved == "en" while the active language is still "pl". Every other
test in the suite runs where the two agree, so without this file a build that
ignores the lang argument and calls translation.get_language() passes everything.
"""

from django.utils import translation

from core.public_pages import _block_values, render_markdown, substitute_tokens
from tests.test_public_pages import cfg


def _headers(html):
    return html


def test_block_values_resolve_under_the_passed_language_not_the_active_one():
    """THE discriminating pairing. Active language pl, page language en."""
    with translation.override("pl"):
        values = _block_values(cfg(vat_note_en="EN note", vat_note_pl="PL note"), "en")
    assert "EN note" in values["vat_note"]
    assert "PL note" not in values["vat_note"]


def test_the_converse_pairing():
    with translation.override("en"):
        values = _block_values(cfg(vat_note_en="EN note", vat_note_pl="PL note"), "pl")
    assert "PL note" in values["vat_note"]
    assert "EN note" not in values["vat_note"]


def test_lang_is_required_not_defaulted():
    """A lang="en" default would keep all eight existing call sites green while
    silently pinning English into the content guards."""
    import inspect

    sig = inspect.signature(substitute_tokens)
    assert sig.parameters["lang"].default is inspect.Parameter.empty


def test_inline_values_parity_assert_exists():
    """The block pass has an assert; the inline pass did not, so a half-done edit
    there was a KeyError rather than a clear failure."""
    from core.public_pages import INLINE_TOKENS, _inline_values

    assert set(_inline_values(cfg())) == INLINE_TOKENS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_public_pages_language.py`
Expected: FAIL — `ImportError: cannot import name '_block_values'`

- [ ] **Step 3: Extract `_block_values` and add the `lang` parameter**

```python
# core/public_pages.py -- add the import at the top, UNALIASED
from django.utils import translation
from django.utils.translation import gettext
# `_` must stay bound to gettext_lazy: PAGES resolves it at module import, so
# rebinding it to eager gettext would freeze every title to the import-time
# language.
```

```python
# core/public_pages.py -- replace the inline block_values dict
def _block_values(cfg, lang):
    """The block token values, each already a complete block element or "".

    lang is the page's RESOLVED language, not translation.get_language(): those
    diverge exactly when a .pl.md file is absent and the English base is served.

    translation.override wraps ONLY this function's gettext calls. Wrapping the
    whole of substitute_tokens would also change _demo_notice_html() and
    _inline_values()' retention_phrase on any page that fell back to English --
    a behaviour change to /privacy/ that is not intended here.
    """
    address = cfg["controller_address"]
    with translation.override(lang):
        return {
            "demo_notice": _demo_notice_html() if cfg["demo_instance"] else "",
            "controller_address": (
                "<p>" + _nl2br(html_lib.escape(str(address))) + "</p>"
                if address
                else ""
            ),
        }


def substitute_tokens(html, cfg, lang):
    """Block pass then inline pass. Runs AFTER sanitisation."""
    block_values = _block_values(cfg, lang)
    assert set(block_values) == set(BLOCK_TOKENS)
    for name in BLOCK_TOKENS:
        value = block_values[name]
        html = _block_re(name).sub(lambda m, v=value: v, html)
    ...
```

```python
# core/public_pages.py -- add the symmetric assert in the inline pass
    values = _inline_values(cfg)
    # Symmetric with the block-pass assert above. Without it a name added to
    # INLINE_TOKENS but not to _inline_values is a bare KeyError at render time.
    assert set(values) == set(INLINE_TOKENS)
```

```python
# core/public_pages.py -- in render_public_page, pass the resolved language
    html = substitute_tokens(render_markdown(source), cfg, resolved)
```

- [ ] **Step 4: Update the eight call sites and rebuild `BASE_CFG`**

`tests/test_public_pages.py`: change `render()` to `substitute_tokens(render_markdown(source), cfg(**over), lang)` with a `lang="en"` parameter on `render` itself (the helper may default; the production function may not). Rebuild `BASE_CFG` from `_DEFAULTS` so it cannot fall behind again:

```python
# tests/test_public_pages.py
from core.services import _DEFAULTS

# Derived, not hand-built: this dict is imported by test_public_pages_content.py
# and test_public_pages_render.py, so a missing key is a KeyError across roughly
# every token test and reads as an unrelated mass failure.
BASE_CFG = {**_DEFAULTS, "name": "Greenfield School"}


def cfg(**over):
    return {**BASE_CFG, **over}


def render(source, lang="en", **over):
    return substitute_tokens(render_markdown(source), cfg(**over), lang)
```

Update the **six** `substitute_tokens(...)` calls in `tests/test_public_pages_content.py` to pass a language.

- [ ] **Step 5: Run the full public-pages suite**

Run: `uv run pytest tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_render.py tests/test_public_pages_language.py tests/test_public_pages_config.py`
Expected: PASS, no `KeyError`, no `TypeError` about a missing positional argument.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/public_pages.py tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_language.py
git commit -m "refactor(public-pages): thread the resolved language into substitute_tokens"
```

---

### Task 5: The `pricing_plans` block token

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_pricing_token.py`

**Interfaces:**
- Consumes: `cfg["pricing_plans"]`, `cfg["currency"]`, `cfg["storage_allowance_gb"]`, `cfg["contact_email"]` (Task 3); `_block_values(cfg, lang)` (Task 4).
- Produces: `BLOCK_TOKENS` gains `"pricing_plans"`; `_block_values` gains the matching entry.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_token.py
"""{libli:pricing_plans} -- the table, the fourth tier, and the shipped fallback."""

import re
from decimal import Decimal

import pytest

from core.public_pages import BLOCK_TOKENS, INLINE_TOKENS, _block_values
from tests.test_public_pages import cfg, render

AMOUNT_RE = re.compile("<td>([\\d\\u00a0]+\\.\\d{2})</td>")


def _plans(*prices):
    """Three bands matching the migration seed, priced as given."""
    rows = [(1, 1, 150, 6, 3, 10), (2, 151, 400, 8, 6, 20), (3, 401, 800, 12, 12, 40)]
    return [
        {
            "order": o,
            "pupils_min": lo,
            "pupils_max": hi,
            "annual_price": p,
            "support_hours_per_term": h,
            "courses_included": c,
            "video_hours_included": v,
        }
        for (o, lo, hi, h, c, v), p in zip(rows, prices)
    ]


def test_token_is_a_block_token_and_not_an_inline_one():
    """Block tokens are absent from the inline map precisely so a misplaced one
    renders literally instead of as escaped markup."""
    assert "pricing_plans" in BLOCK_TOKENS
    assert "pricing_plans" not in INLINE_TOKENS


def test_empty_plan_list_renders_the_fallback_not_a_table():
    """_DEFAULTS and BASE_CFG both carry [], so this is the state every direct
    substitute_tokens unit test runs under. Ruled out: a lone by-arrangement row,
    and a header-only empty <table>."""
    html = render("{libli:pricing_plans}\n", pricing_plans=[])
    assert "<table" not in html
    assert "on request" in html


def test_all_prices_null_renders_the_same_fallback():
    """The shipped state on merge."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "<table" not in html
    assert "on request" in html


def test_fallback_uses_the_existing_contact_fallback_when_email_is_blank():
    """Reuses _inline_values' string rather than inventing a second one for the
    same question."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "the person who runs this site" in html


def test_priced_plans_render_a_table_with_a_scroll_wrapper():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), Decimal("7200"), Decimal("10800")),
    )
    assert 'class="public-page__scroll"' in html
    assert "<table" in html


def test_amounts_use_a_nonbreaking_thousands_separator_and_no_symbol():
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("10800"), None, None))
    assert "10\u00a0800.00" in html
    # Split on the first row end: the renderer emits <table><tr>header</tr>...
    # with no <thead>/<tbody>, so those are not available as landmarks.
    assert "PLN" not in html.split("</tr>", 1)[1]  # currency lives in the header only


def test_currency_appears_in_the_column_header(): 
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, None),
        currency="EUR",
    )
    assert "EUR" in html.split("</tr>", 1)[0]  # the header row


def test_by_arrangement_is_scoped_to_the_null_priced_row():
    """A bare `"by arrangement" in html` is green on a build where the null price
    renders blank, None or 0.00 -- because the renderer emits that phrase
    unconditionally in the fourth tier."""
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, Decimal("10800")),
    )
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    band2 = next(r for r in rows if "151" in r and "400" in r)
    band1 = next(r for r in rows if "1" in r and "150" in r)
    assert "arrangement" in band2
    assert "4\u00a0800.00" in band1
    assert "arrangement" not in band1


def test_the_fourth_tier_interpolates_the_last_bands_ceiling():
    """A static "Larger schools" would leave a visible gap above 800."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("4800"), None, None)
    )
    assert "801" in html


def test_allowance_sentence_is_absent_when_the_field_is_null():
    """The shipped default."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "GB" not in html


def test_allowance_sentence_appears_when_the_field_is_set():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(None, None, None),
        storage_allowance_gb=50,
    )
    assert "50 GB" in html


def test_block_value_is_never_bare_inline_content():
    """_block_re swallows the enclosing <p>, so a bare string lands between block
    elements. Nothing in the existing guards catches it."""
    for lang in ("en", "pl"):
        value = _block_values(cfg(pricing_plans=[]), lang)["pricing_plans"]
        assert value.startswith("<p") or value.startswith("<div")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_token.py`
Expected: FAIL — `AssertionError` on `set(block_values) == set(BLOCK_TOKENS)` or `KeyError: 'pricing_plans'`

- [ ] **Step 3: Implement the renderer**

```python
# core/public_pages.py
BLOCK_TOKENS = frozenset({"demo_notice", "controller_address", "pricing_plans"})
```

```python
# core/public_pages.py -- add above _block_values
def _amount(value):
    """Bare numeral, U+00A0 thousands separator, no currency symbol.

    str(Decimal) emits no separator at all, so it is inserted deliberately;
    quantize takes an exponent Decimal, not an int. U+00A0 rather than a plain
    space so an amount never wraps mid-number. The parity guard compares these
    strings byte for byte, which is why no locale-dependent formatting is used.
    """
    from decimal import Decimal

    return f"{value.quantize(Decimal('0.01')):,f}".replace(",", "\u00a0")


def _plans_html(cfg):
    """The plans table, or the no-prices fallback. Always block-level.

    Emits the storage-allowance sentence too: it lives inside this token so the
    fallback branch can own it. The VAT note does NOT -- that is a separate token
    placed independently in the markdown, which this branch cannot suppress.

    Callers must already be inside translation.override(lang); every gettext here
    is eager and unaliased, because `_` in this module is gettext_lazy and a lazy
    proxy would resolve at format time under the ambient language.
    """
    plans = cfg["pricing_plans"]
    allowance = ""
    if cfg["storage_allowance_gb"]:
        allowance = format_html(
            "<p>{}</p>",
            gettext(
                "Storage allowance: %(gb)s GB, advisory and reconciled at renewal."
            )
            % {"gb": cfg["storage_allowance_gb"]},
        )

    if not any(p["annual_price"] is not None for p in plans):
        contact = cfg["contact_email"] or gettext("the person who runs this site")
        return (
            format_html(
                "<p>{} {}</p>",
                gettext("Prices for your school are quoted on request."),
                gettext("Ask %(contact)s, and see the five numbers above.")
                % {"contact": contact},
            )
            + allowance
        )

    header = format_html(
        "<tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr>",
        gettext("Pupils"),
        gettext("Annual price (%(currency)s)") % {"currency": cfg["currency"]},
        gettext("Support"),
        gettext("Courses"),
        gettext("Video"),
    )
    body = format_html_join(
        "",
        "<tr><td>{}-{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
        (
            (
                p["pupils_min"],
                p["pupils_max"],
                _amount(p["annual_price"])
                if p["annual_price"] is not None
                else gettext("by arrangement"),
                gettext("%(n)s h / term") % {"n": p["support_hours_per_term"]},
                p["courses_included"],
                gettext("%(n)s h") % {"n": p["video_hours_included"]},
            )
            for p in plans
        ),
    )
    # The open-ended tier is emitted here, not stored and not written in markdown:
    # the token substitutes a complete <table> for its enclosing <p>, so markdown
    # outside it can only make a sibling paragraph, never a <tr> inside this table.
    tail = format_html(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
        gettext("%(above)s and above") % {"above": plans[-1]["pupils_max"] + 1},
        gettext("by arrangement"),
        gettext("by arrangement"),
        gettext("by arrangement"),
        gettext("by arrangement"),
    )
    return (
        format_html(
            '<div class="public-page__scroll"><table>{}{}{}</table></div>',
            header,
            body,
            tail,
        )
        + allowance
    )
```

Add `"pricing_plans": _plans_html(cfg)` inside `_block_values`' `translation.override(lang)` block, and import `format_html_join` alongside `format_html`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_token.py`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/public_pages.py tests/test_pricing_token.py
git commit -m "feat(pricing): pricing_plans block token with table and no-prices fallback"
```

---

### Task 6: The `vat_note` block token

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_vat_note_token.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vat_note_token.py
"""{libli:vat_note} -- per-language, escaped, block-level."""

from core.public_pages import BLOCK_TOKENS, INLINE_TOKENS
from tests.test_public_pages import render


def test_is_a_block_token():
    assert "vat_note" in BLOCK_TOKENS
    assert "vat_note" not in INLINE_TOKENS


def test_selects_the_note_for_the_pages_resolved_language():
    en = render("{libli:vat_note}\n", lang="en", vat_note_en="EN tax", vat_note_pl="PL tax")
    pl = render("{libli:vat_note}\n", lang="pl", vat_note_en="EN tax", vat_note_pl="PL tax")
    assert "EN tax" in en and "PL tax" not in en
    assert "PL tax" in pl and "EN tax" not in pl


def test_blank_note_renders_nothing_at_all():
    """Empty string, so the block substitution removes the enclosing <p> rather
    than leaving <p></p> on the page."""
    assert render("{libli:vat_note}\n", vat_note_en="") .strip() == ""


def test_admin_markup_is_escaped_not_rendered():
    """Block values are inserted AFTER nh3, so they reach the browser
    unsanitised, and this is the one value on the page that is free
    admin-authored text."""
    html = render("{libli:vat_note}\n", vat_note_en="<b>bold</b>")
    assert "<b>" not in html
    assert "&lt;b&gt;" in html


def test_newlines_become_line_breaks():
    """Same treatment as controller_address: the inline pass has no _nl2br, so a
    two-line note would otherwise render as one run-on line."""
    html = render("{libli:vat_note}\n", vat_note_en="line one\nline two")
    assert "<br>" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vat_note_token.py`
Expected: FAIL — assertion on `BLOCK_TOKENS`

- [ ] **Step 3: Implement**

```python
# core/public_pages.py
BLOCK_TOKENS = frozenset(
    {"demo_notice", "controller_address", "pricing_plans", "vat_note"}
)
```

```python
# inside _block_values, within the translation.override(lang) block:
        note = cfg["vat_note_pl"] if lang == "pl" else cfg["vat_note_en"]
        ...
            "vat_note": (
                "<p>" + _nl2br(html_lib.escape(str(note))) + "</p>" if note else ""
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vat_note_token.py`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/public_pages.py tests/test_vat_note_token.py
git commit -m "feat(pricing): per-language vat_note block token"
```

---

### Task 7: The `for_schools_link` block token

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_for_schools_link_token.py`

**Note:** this token reads `settings.VENDOR_INSTANCE` directly — a deliberate exception to "cfg is the single source of truth for tokens", because a deploy-time flag does not belong in the ORM bundle. Its cost is that tests steer it with `override_settings`, not `cfg(**over)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_for_schools_link_token.py
"""{libli:for_schools_link} -- present on the vendor box, absent everywhere else."""

import pytest
from django.test import override_settings

from core.public_pages import BLOCK_TOKENS
from tests.test_public_pages import render


def test_is_a_block_token():
    assert "for_schools_link" in BLOCK_TOKENS


@override_settings(VENDOR_INSTANCE=False)
def test_renders_nothing_off_vendor():
    assert render("{libli:for_schools_link}\n").strip() == ""


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_an_anchor_on_the_vendor_box():
    html = render("{libli:for_schools_link}\n")
    assert 'href="/for-schools/"' in html


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_href_comes_from_reverse_not_a_hardcoded_path():
    """A hardcoded path would also escape test_every_root_relative_link_resolves,
    which only sees links present in the markdown."""
    import inspect

    from core import public_pages

    assert 'reverse("core:for_schools")' in inspect.getsource(public_pages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_for_schools_link_token.py`
Expected: FAIL — assertion on `BLOCK_TOKENS`

- [ ] **Step 3: Implement**

```python
# core/public_pages.py -- add imports
from django.conf import settings
from django.urls import reverse
```

```python
# BLOCK_TOKENS gains "for_schools_link"; inside _block_values, in the override:
            "for_schools_link": (
                format_html(
                    '<p><a href="{}">{}</a></p>',
                    reverse("core:for_schools"),
                    gettext("Considering libli for a school?"),
                )
                if settings.VENDOR_INSTANCE
                else ""
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_for_schools_link_token.py`
Expected: FAIL on `reverse` — `core:for_schools` does not exist yet. That is expected; Task 8 registers it. Mark this task's step as blocked and complete Task 8, then re-run.

> **Sequencing note:** Tasks 7 and 8 are mutually dependent (`reverse` needs the route; the route's page uses the token). Implement Task 7's code, then Task 8's route, then run both test files together.

- [ ] **Step 5: Commit (after Task 8's route exists)**

```bash
git add core/public_pages.py tests/test_for_schools_link_token.py
git commit -m "feat(pricing): for_schools_link block token, gated on VENDOR_INSTANCE"
```

---

### Task 8: Register `/for-schools/`, gate the view, and fix the three breaking tests

**Files:**
- Modify: `core/public_pages.py`, `core/urls.py`, `core/views_public.py`, `tests/test_public_pages.py`, `tests/test_public_pages_content.py`, `tests/test_public_pages_settings.py`
- Test: `tests/test_for_schools_route.py` (create)

**Interfaces:**
- Produces: `PAGES["for-schools"]`, `core:for_schools` URL name, `views_public.for_schools`, `core.public_pages.DEMO_NOTICE_SLUGS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_for_schools_route.py
"""The vendor page exists only on the vendor box."""

import pytest
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_404s_on_a_school_box(client):
    """404 rather than 403 or an empty 200: the page genuinely does not exist
    there, and a school must never see our price list."""
    assert client.get(reverse("core:for_schools")).status_code == 404


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_anonymously_on_the_vendor_box(client):
    response = client.get(reverse("core:for_schools"))
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_in_polish(client):
    response = client.get(reverse("core:for_schools"), headers={"accept-language": "pl"})
    assert response.status_code == 200


def test_demo_notice_slugs_lives_in_production_code_and_excludes_for_schools():
    """_page_overrides() (production) cannot import a set from tests/, and SHIPPED
    holds markdown PATHS while _page_overrides iterates SLUGS -- so the canonical
    set is slugs, defined beside PAGES."""
    from core.public_pages import DEMO_NOTICE_SLUGS

    assert DEMO_NOTICE_SLUGS == {"privacy", "getting-started"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_for_schools_route.py`
Expected: FAIL — `NoReverseMatch: 'for_schools' is not a valid view function or pattern name`

- [ ] **Step 3: Register the page, the route and the gated view**

```python
# core/public_pages.py -- add to PAGES
    "for-schools": Page(
        "for-schools",
        "public/for-schools.md",
        _("libli for schools"),
        _(
            "What a school gets, what we need from you, where the data lives, "
            "and what it costs."
        ),
    ),

# Beside PAGES: the pages that must carry {libli:demo_notice}. /for-schools/ is a
# vendor sales page and deliberately carries none, so it is exempt from both the
# content guard and _page_overrides()' missing_demo_notice flag.
DEMO_NOTICE_SLUGS = frozenset({"privacy", "getting-started"})
```

```python
# core/urls.py
    path("for-schools/", views_public.for_schools, name="for_schools"),
```

```python
# core/views_public.py
def for_schools(request):
    """The vendor's own school-facing page. Absent on a school's box.

    Reads the flag from settings, never Institution.load() -- that is
    get_or_create, a write, which core/services.py forbids on a GET render path.
    """
    if not settings.VENDOR_INSTANCE:
        raise Http404
    return _public_page(request, "for-schools")
```

- [ ] **Step 4: Fix the three tests that break by construction**

1. `tests/test_public_pages.py::test_pages_registry_shape` — `set(PAGES) == {"privacy", "getting-started", "for-schools"}`, plus the matching `PAGES["for-schools"].path` assertion in the same shape the file already uses.
2. `tests/test_public_pages_content.py` — add `public/for-schools.md` and `public/for-schools.pl.md` to `SHIPPED`. **Re-parametrise `test_demo_notice_is_placed_where_the_block_regex_matches` IN FULL** over a `DEMO_NOTICE_SLUGS`-derived path subset. It cannot be split: all three of its assertions are false for a page that carries no token. The other six parametrised guards keep the full sweep. Also drive `test_no_block_token_has_a_heading_immediately_above_it` off `BLOCK_TOKENS` instead of its two hard-coded literals — it is otherwise blind to all three new tokens, and `for_schools_link` renders as `""` off-vendor, which is exactly the orphaned-heading case.
3. `tests/test_public_pages_settings.py::test_panel_uses_the_coalesced_language_list_not_the_stored_one` — rewrite the count against the `_page_overrides()`-derived length or parametrise over the flag. **Do not relax it to `<=`.**

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_for_schools_route.py tests/test_for_schools_link_token.py tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_settings.py`
Expected: PASS. `test_public_pages_content.py` will fail on missing markdown files until Task 10 — create empty placeholders with a single `# heading` to keep it green, and fill them in Task 10.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/public_pages.py core/urls.py core/views_public.py tests/
git commit -m "feat(pricing): register and gate the /for-schools/ route"
```

---

### Task 9: Deliver the flag to templates and add the footer links

**Files:**
- Modify: `core/context_processors.py`, `templates/core/_public_footer.html`, `templates/core/landing.html`
- Test: `tests/test_for_schools_footer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_for_schools_footer.py
"""The "For schools" link, over every surface, both directions.

There are TWO footers: templates/core/_public_footer.html (included by
public_page.html AND allauth/layouts/entrance.html) and a DUPLICATED link block
in templates/core/landing.html. tests/test_public_pages_footer.py already asserts
them separately for exactly this reason -- someone editing "the footer" misses
the landing page, which is where an anonymous school visitor actually arrives.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

SURFACES = ["/", "/privacy/", "/accounts/login/"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", SURFACES)
@override_settings(VENDOR_INSTANCE=True)
def test_link_present_on_every_surface_on_the_vendor_box(client, path):
    body = client.get(path).content.decode()
    assert reverse("core:for_schools") in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", SURFACES)
@override_settings(VENDOR_INSTANCE=False)
def test_link_absent_on_every_surface_on_a_school_box(client, path):
    body = client.get(path).content.decode()
    assert "/for-schools/" not in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_context_processor_exposes_the_flag(client):
    response = client.get("/")
    assert response.context["vendor_instance"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_for_schools_footer.py`
Expected: FAIL — the link is absent on the vendor box.

- [ ] **Step 3: Implement**

```python
# core/context_processors.py -- in institution_branding
def institution_branding(request):
    cfg = get_site_config()
    # Read from settings, NOT through cfg: cfg is the never-writes ORM bundle and
    # a deploy-time flag does not belong in it. Templates cannot reach
    # django.conf.settings on their own, and there is no shared view to hang a
    # per-view key on -- landing.html has its own view, _public_footer.html is
    # included by two unrelated layouts.
    return {
        "site": cfg,
        "institution": cfg,
        "vendor_instance": settings.VENDOR_INSTANCE,
    }
```

In both `templates/core/_public_footer.html` and `templates/core/landing.html`, wrap a new link in `{% if vendor_instance %}`:

```html
{% if vendor_instance %}
  <a href="{% url 'core:for_schools' %}">{% trans "For schools" %}</a>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_for_schools_footer.py tests/test_public_pages_footer.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add core/context_processors.py templates/core/_public_footer.html templates/core/landing.html tests/test_for_schools_footer.py
git commit -m "feat(pricing): conditional For schools link on both footers and landing"
```

---

### Task 10: Write the `/for-schools/` content, EN and PL

**Files:**
- Create: `docs/public/for-schools.md`, `docs/public/for-schools.pl.md`
- Test: `tests/test_for_schools_content.py`

**Content:** the eight sections from the spec's Content section. Two rules that are testable and therefore load-bearing:

- **Section 5 reuses the privacy notices' EXACT retention sentences**, EN and PL, so the existing f-string guard patterns extend unchanged. Carry the **three period sentences** in each language; **not** the derived "about 13 months" consequence sentence, which reads as compliance boilerplate here.
- **Prose must sit between the "Plans" heading and each of `{libli:pricing_plans}` and `{libli:vat_note}`** — the heading-adjacency guard now sweeps these files.
- The timeline carries **no port-25 month**. Port 587 is the default and was never blocked; Direct Send is a conditional branch only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_for_schools_content.py
"""Guards on the shipped markdown, in the style of test_public_pages_guards.py.

The retention guard works only because it asserts f-strings embedding each
constant INSIDE the surrounding prose -- a bare `"30" in text` is worthless.
"""

from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR, "docs", "public")
EN = (ROOT / "for-schools.md").read_text(encoding="utf-8")
PL = (ROOT / "for-schools.pl.md").read_text(encoding="utf-8")


def _backup_constant(name):
    line = next(
        line
        for line in Path(settings.BASE_DIR, "backup.sh").read_text(encoding="utf-8").splitlines()
        if line.startswith(f"{name}=")
    )
    return int(line.split("=", 1)[1].split()[0].strip('"'))


@pytest.mark.parametrize("text", [EN, PL])
def test_retention_periods_match_backup_sh(text):
    daily = _backup_constant("RETAIN_DAILY_DAYS")
    monthly = _backup_constant("RETAIN_MONTHLY_MONTHS")
    prune = _backup_constant("MIRROR_PRUNE_DAYS")
    assert str(daily) in text and str(monthly) in text and str(prune) in text


def test_plans_heading_has_prose_before_each_block_token():
    for token in ("{libli:pricing_plans}", "{libli:vat_note}"):
        for text in (EN, PL):
            before = text.split(token)[0].rstrip().splitlines()[-1]
            assert not before.startswith("#"), f"{token} sits directly under a heading"


@pytest.mark.parametrize("text", [EN, PL])
def test_the_timeline_does_not_promise_a_port_25_month(text):
    """The settled default is a transactional provider on port 587, which Hetzner
    has never blocked. Direct Send is the documented exception."""
    assert "port 25" not in text.lower() or "587" in text


@pytest.mark.parametrize("text", [EN, PL])
def test_carries_no_demo_notice_token(text):
    assert "{libli:demo_notice}" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_for_schools_content.py`
Expected: FAIL — the placeholder files have none of this content.

- [ ] **Step 3: Write both markdown files to this exact skeleton**

One `#` H1 (the content guard asserts exactly one), then eight `##` sections in this order. Move the product description out of `docs/public/getting-started.md`'s "Evaluating libli?" section **verbatim** into section 1 rather than rewriting it, and copy the retention sentences from `docs/public/privacy.md` / `privacy.pl.md` **character for character** — this task's guard asserts the `backup.sh` constants inside that prose, so a reworded sentence fails it.

```markdown
# libli for schools

## What you get
<the product description, moved verbatim from getting-started.md>

## What we need from you
<the A record + SPF + DKIM ask, bundled into one email: same person, same day>

## What we do not need
<no server, no hardware, no procurement, no software on pupil devices>

## Two DNS traps worth knowing
<a CAA record that omits letsencrypt.org; a stale AAAA>

## Where the data lives
<Hetzner, Germany; nightly encrypted backups; then the THREE retention sentences
copied verbatim from privacy.md — NOT the "about 13 months" consequence sentence,
which reads as compliance boilerplate here>

## What happens if you leave
<handover is a key ROTATION under a key the school generates, never disclosure of
the shared age key>

## Timeline
<port 587 by default; port 25 appears ONLY as a conditional branch for a school
that insists on Exchange Direct Send, and even then the gate is 30 days of
account age, not a fee>

## Plans

At signup we agree five numbers: pupils on the platform, courses you plan, videos
per course, typical video length, and how many people author content.

{libli:pricing_plans}

Prices are quoted per school year.

{libli:vat_note}
```

⚠️ The prose lines above each token are **required, not decorative**: the heading-adjacency guard now sweeps these files (Task 8 drove it off `BLOCK_TOKENS`), and a token as the first non-blank line under a heading fails it.

⚠️ This section **owns** the list of five contract numbers. The no-prices fallback paragraph only points at it — emitting them in both places would print the list twice in the shipped state and once in the priced state.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_for_schools_content.py tests/test_public_pages_content.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/public/for-schools.md docs/public/for-schools.pl.md tests/test_for_schools_content.py
git commit -m "feat(pricing): the /for-schools/ page content, EN and PL"
```

---

### Task 11: Trim both `/getting-started/` files

**Files:**
- Modify: `docs/public/getting-started.md`, `docs/public/getting-started.pl.md`
- Test: `tests/test_getting_started_trim.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_getting_started_trim.py
"""The trim keeps the sign-in help and fixes the premise, without stranding the
/privacy/ link that another guard's non-vacuity check depends on."""

from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR, "docs", "public")
EN = (ROOT / "getting-started.md").read_text(encoding="utf-8")
PL = (ROOT / "getting-started.pl.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_false_premise_is_gone(text):
    """Krzysztof hosts, one box per school -- the school does not run it itself."""
    assert "runs for itself" not in text
    assert "prowadzi u siebie" not in text


@pytest.mark.parametrize("text", [EN, PL])
def test_the_sign_in_help_survives(text):
    assert "/accounts/password/reset/" in text


def test_a_root_relative_privacy_link_survives_somewhere_in_shipped():
    """test_every_root_relative_link_resolves asserts
    {"/privacy/", "/accounts/password/reset/"} <= set(found) as an explicit
    non-vacuity check across the whole SHIPPED sweep. The paragraph carrying
    /privacy/ is the one being moved, so it must land somewhere."""
    everything = "".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "getting-started.md",
            "getting-started.pl.md",
            "for-schools.md",
            "for-schools.pl.md",
            "privacy.md",
            "privacy.pl.md",
        )
    )
    assert "/privacy/" in everything


@pytest.mark.parametrize("text", [EN, PL])
def test_the_cross_pointer_token_is_present_with_prose_above_it(text):
    assert "{libli:for_schools_link}" in text
    before = text.split("{libli:for_schools_link}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_demo_notice_token_still_has_prose_above_it(text):
    before = text.split("{libli:demo_notice}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_getting_started_trim.py`
Expected: FAIL on the premise assertion.

- [ ] **Step 3: Trim both files**

Replace the opening sentence with one true on a school's box (their school's platform, not one they run). Cut the "Evaluating libli?" product pitch — it now lives on `/for-schools/`. **Keep `{libli:demo_notice}` and the contact + privacy-notice paragraphs**, moving them under the sign-in help with prose above the token. Add `{libli:for_schools_link}` with prose above it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_getting_started_trim.py tests/test_public_pages_content.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/public/getting-started.md docs/public/getting-started.pl.md tests/test_getting_started_trim.py
git commit -m "fix(public): getting-started keeps sign-in help, loses the false premise"
```

---

### Task 12: Whole-page guards that need the full stack

**Files:**
- Modify: `tests/test_public_pages_content.py`, `tests/test_public_pages_settings.py`
- Test: `tests/test_for_schools_page.py` (create)

These are the Testing items that cannot live in a unit task because they need the route, the
content files and the tokens all present at once. They run last for that reason.

**Interfaces:**
- Consumes: everything from Tasks 1–11.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_for_schools_page.py
"""Guards that need the route, the markdown and the tokens together."""

import re

import pytest
from django.test import override_settings
from django.urls import reverse

from institution.models import Institution, PricingPlan, PublicPage

AMOUNTS = re.compile("<td>([\\d\\u00a0]+\\.\\d{2})</td>")


@pytest.fixture
def priced_plans(db):
    """UPDATES the migration-seeded rows; never creates.

    pyproject.toml's addopts sets no --nomigrations, so RunPython(seed, ...) runs
    against every test database and orders 1/2/3 already exist -- create(order=1)
    raises IntegrityError on the unique `order`. Creating 4/5/6 instead would
    silently make a six-row, gapped, non-monotonic band set that breaks the
    three-row invariant and shifts the fourth tier's label.
    """
    for order, price in ((1, "4800.00"), (2, "7200.00"), (3, "10800.00")):
        PricingPlan.objects.filter(order=order).update(annual_price=price)
    return PricingPlan.objects.order_by("order")


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_english_and_polish_show_identical_figures(client, priced_plans):
    """THE guard that justifies the whole token approach.

    Assert the Polish page actually resolved as Polish FIRST: localized_doc_path
    falls back to the English base when for-schools.pl.md is absent, so a naive
    version compares English against English and is green with no Polish page at
    all -- the exact adjacent-thing shape.
    """
    en = client.get(reverse("core:for_schools"), headers={"accept-language": "en"})
    pl = client.get(reverse("core:for_schools"), headers={"accept-language": "pl"})
    assert pl.context["resolved_lang"] == "pl"

    en_amounts = AMOUNTS.findall(en.content.decode())
    pl_amounts = AMOUNTS.findall(pl.content.decode())
    assert len(en_amounts) >= 3, "non-vacuity: no amounts extracted"
    assert en_amounts == pl_amounts


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_row_order_survives_editing_a_middle_band(client, priced_plans):
    PricingPlan.objects.filter(order=2).update(annual_price="7300.00")
    body = client.get(reverse("core:for_schools")).content.decode()
    amounts = AMOUNTS.findall(body)
    assert amounts == ["4\u00a0800.00", "7\u00a0300.00", "10\u00a0800.00"]


def test_the_explicit_order_by_is_pinned_at_the_source():
    """Named honestly: with Meta.ordering present, dropping the explicit
    .order_by leaves the rendered-order test green, so a behavioural test cannot
    kill that mutant. Pin it the way
    test_demo_instance_is_a_bare_read_not_a_coalesced_one pins its rule."""
    import inspect

    from core import services

    assert 'order_by("order")' in inspect.getsource(services._pricing_plans)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("lang", ["en", "pl"])
def test_anonymous_access_to_all_three_public_pages(client, lang):
    for name in ("core:privacy", "core:getting_started", "core:for_schools"):
        response = client.get(reverse(name), headers={"accept-language": lang})
        assert response.status_code == 200


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_publicpage_override_still_wins_for_the_new_page(client):
    PublicPage.objects.create(
        slug="for-schools", language="en", body_markdown="# Overridden\n\nBody.\n"
    )
    body = client.get(reverse("core:for_schools")).content.decode()
    assert "Overridden" in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("path", ["/", "/for-schools/"])
def test_no_django_template_comment_leaks(client, path):
    """The settings-page surface is covered in Task 14; these are the other two
    the change touches (landing.html is edited, /for-schools/ is new)."""
    assert "{#" not in client.get(path).content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_for_schools_page.py`
Expected: FAIL — several, including `KeyError: 'resolved_lang'` if the view does not expose it. Add it to the template context in `_public_page` if absent.

- [ ] **Step 3: Add the two parametrised-axis guards**

In `tests/test_public_pages_content.py`, parametrise the token guards over the **vendor flag** as well as `demo_instance`. `{libli:for_schools_link}` makes the vendor flag a second configuration axis for the shipped files, and with it defaulting False the link-emitting branch is never swept for unresolved tokens, tokens-in-attributes or empty paragraphs.

In `tests/test_public_pages_settings.py`, add the overrides-panel filter in **both** directions: with the flag on, the panel renders `len(PAGES) * 2` textareas and a posted `override-for-schools-en` persists (`_page_overrides()` doubles as the *write* loop's iteration set, so the filter silently gates saving too); with it off, neither the textarea nor the write path exists. Note next to `test_panel_renders_one_textarea_per_page_per_language`'s hard-coded `== 4` that it now depends on the flag defaulting False.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_for_schools_page.py tests/test_public_pages_content.py tests/test_public_pages_settings.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add tests/
git commit -m "test(pricing): whole-page guards for parity, ordering, overrides and gating"
```

---

### Task 13: The mobile scroller CSS

**Files:**
- Modify: `core/static/core/css/app.css`
- Test: `tests/test_public_page_scroll_css.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_page_scroll_css.py
"""The scroller rule must come AFTER .public-page table, not merely exist.

.public-page table and .public-page__scroll table are BOTH (0,1,1) -- a
specificity TIE, decided by source order. A block placed above the existing rule
is completely inert while reading exactly like the design, and this repo has
shipped that failure before.
"""

from pathlib import Path

from django.conf import settings

CSS = Path(settings.BASE_DIR, "core", "static", "core", "css", "app.css").read_text(
    encoding="utf-8"
)


def test_the_scroller_rule_exists():
    assert ".public-page__scroll" in CSS
    assert "overflow-x: auto" in CSS.split(".public-page__scroll", 1)[1][:200]


def test_the_table_rule_defeats_the_width_100_percent_rule_by_SOURCE_ORDER():
    """The A in the A/B: without this ordering the scroller never engages,
    because the table shrinks to the wrapper and every column wraps instead."""
    base = CSS.index(".public-page table")
    scoped = CSS.index(".public-page__scroll table")
    assert scoped > base, "the scoped rule must come after .public-page table"


def test_the_table_is_allowed_to_exceed_the_wrapper():
    scoped = CSS.split(".public-page__scroll table", 1)[1][:200]
    assert "max-content" in scoped
    assert "min-width" in scoped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_public_page_scroll_css.py`
Expected: FAIL — `.public-page__scroll` is not in `app.css`.

- [ ] **Step 3: Add the rules immediately after `.public-page table`**

```css
/* Wraps the plans table only (emitted by the pricing_plans token, after nh3 --
   PUBLIC_PAGE_TAGS has no `div`, so a markdown-authored wrapper is stripped).
   MUST sit after `.public-page table`: both selectors are (0,1,1), so source
   order decides, and above it this block is inert. */
.public-page__scroll { overflow-x: auto; }
/* overflow-x alone is not enough: `.public-page table` is width:100%, so the
   table shrinks to the wrapper and the scroller never engages. */
.public-page__scroll table { width: max-content; min-width: 100%; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_public_page_scroll_css.py`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/static/core/css/app.css tests/test_public_page_scroll_css.py
git commit -m "feat(pricing): scroll the plans table on narrow viewports"
```

---

### Task 14: The Pricing settings tab

**Files:**
- Modify: `institution/forms.py`, `institution/views_manage.py`, `institution/urls.py`, `templates/institution/manage/_tabs.html`, `templates/institution/manage/settings.html`, `tests/test_settings_action_method_guard.py`
- Create: `templates/institution/manage/_pricing_tab.html`
- Test: `tests/test_pricing_settings_tab.py`

**Interfaces:**
- Consumes: `PricingPlan` (Task 1), `settings.VENDOR_INSTANCE` (Task 2).
- Produces: `institution:settings_pricing` URL name; `PricingForm` (an `Institution` ModelForm).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_settings_tab.py
"""The Pricing tab: gated like the page, and validating like an admin surface.

The tab is gated for the same reason /for-schools/ is, only more strongly -- on a
school's box a school admin would otherwise edit OUR pupil bands and prices,
pre-seeded with our structural placeholders.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

from institution.models import PricingPlan
from tests.factories import make_pa


def _post_data(bands):
    """bands: [(min, max), ...] for orders 1..3."""
    data = {}
    for order, (lo, hi) in enumerate(bands, start=1):
        data[f"plan_{order}_pupils_min"] = lo
        data[f"plan_{order}_pupils_max"] = hi
        data[f"plan_{order}_annual_price"] = ""
        data[f"plan_{order}_support_hours_per_term"] = 6
        data[f"plan_{order}_courses_included"] = 3
        data[f"plan_{order}_video_hours_included"] = 10
    data["currency"] = "PLN"
    return data


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_tab_404s_on_a_school_box(client):
    make_pa(client)
    response = client.post(reverse("institution:settings_pricing"), _post_data(
        [(1, 150), (151, 400), (401, 800)]
    ))
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_tab_is_absent_from_the_settings_page_on_a_school_box(client):
    make_pa(client)
    body = client.get(reverse("institution:settings")).content.decode()
    assert "?tab=pricing" not in body
    assert "plan_1_pupils_min" not in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_tab_is_present_on_the_vendor_box(client):
    """Drives the PER-REQUEST evaluation. A module-level conditional TABS tuple is
    evaluated once at import, so override_settings never reaches it -- the tab
    link would render while ?tab=pricing fell back to branding."""
    make_pa(client)
    body = client.get(reverse("institution:settings") + "?tab=pricing").content.decode()
    assert "plan_1_pupils_min" in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_reversed_band_is_a_form_error_not_a_500(client):
    """THE regression this validation exists for. (1,150),(151,400),(401,300) has
    no gap and no overlap BETWEEN CONSECUTIVE ROWS, so a clean() carrying only the
    cross-row rules passes it -- and save() then hits the CheckConstraint, raising
    IntegrityError out of _action, which has no handler. An admin who types two
    numbers the wrong way round gets a 500.
    """
    make_pa(client)
    response = client.post(
        reverse("institution:settings_pricing"),
        _post_data([(1, 150), (151, 400), (401, 300)]),
    )
    assert response.status_code == 200  # re-rendered with errors, not 302, not 500


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize(
    "bands",
    [
        [(1, 150), (100, 400), (401, 800)],   # overlap
        [(1, 150), (200, 400), (401, 800)],   # gap
        [(1, 150), (401, 800), (151, 400)],   # non-monotonic
    ],
)
def test_cross_row_band_rules_are_rejected(client, bands):
    make_pa(client)
    response = client.post(reverse("institution:settings_pricing"), _post_data(bands))
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_valid_save_persists_and_redirects(client):
    make_pa(client)
    data = _post_data([(1, 150), (151, 400), (401, 900)])
    data["plan_3_annual_price"] = "10800.00"
    response = client.post(reverse("institution:settings_pricing"), data)
    assert response.status_code == 302
    row = PricingPlan.objects.get(order=3)
    assert row.pupils_max == 900
    assert str(row.annual_price) == "10800.00"


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_no_django_template_comment_leaks_into_the_settings_page(client):
    """{# #} is single-line only; a two-line one renders as visible text. Shipped
    five times. _pricing_tab.html is the largest new template in this change, and
    /for-schools/ renders none of these templates."""
    make_pa(client)
    body = client.get(reverse("institution:settings") + "?tab=pricing").content.decode()
    assert "{#" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pricing_settings_tab.py`
Expected: FAIL — `NoReverseMatch: 'settings_pricing'`

- [ ] **Step 3: Write the form**

```python
# institution/forms.py
PLAN_FIELDS = (
    "pupils_min",
    "pupils_max",
    "annual_price",
    "support_hours_per_term",
    "courses_included",
    "video_hours_included",
)
# SIX per row, not five. order is the row key, not an input, and the cross-row
# clean() needs BOTH bounds submitted -- an implementer working from a "five
# fields" count would most plausibly drop pupils_min, which the model explicitly
# forbids deriving.


class PricingForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = ["currency", "vat_note_en", "vat_note_pl", "storage_allowance_gb"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Iterates the rows that EXIST, not range(1, 4): a fourth row created
        # out-of-band would otherwise render on the public page while this tab
        # silently ignored it, and clean() would validate a band set that is not
        # the one rendered. One order_by, no per-row queries -- _settings_context
        # builds every form unbound on every settings render, so this runs on all
        # nine tabs.
        self._plans = list(PricingPlan.objects.order_by("order"))
        for plan in self._plans:
            for name in PLAN_FIELDS:
                field = PricingPlan._meta.get_field(name).formfield()
                # required=False on annual_price so the shipped null state can be
                # re-saved without inventing a price.
                if name == "annual_price":
                    field.required = False
                self.fields[f"plan_{plan.order}_{name}"] = field
                self.initial.setdefault(
                    f"plan_{plan.order}_{name}", getattr(plan, name)
                )

    def clean(self):
        cleaned = super().clean()
        bands = []
        for plan in self._plans:
            lo = cleaned.get(f"plan_{plan.order}_pupils_min")
            hi = cleaned.get(f"plan_{plan.order}_pupils_max")
            if lo is None or hi is None:
                return cleaned
            # PER-ROW, and it must be here as well as in the CheckConstraint:
            # (1,150),(151,400),(401,300) has no gap and no overlap between
            # consecutive rows, so the cross-row rules below pass it and save()
            # would raise IntegrityError out of _action -- a 500 on a typo.
            if lo >= hi:
                self.add_error(
                    f"plan_{plan.order}_pupils_max",
                    _("The upper bound must be greater than the lower bound."),
                )
                return cleaned
            bands.append((plan.order, lo, hi))
        for (_o1, _lo1, hi1), (o2, lo2, _hi2) in zip(bands, bands[1:]):
            if lo2 != hi1 + 1:
                self.add_error(
                    f"plan_{o2}_pupils_min",
                    _("Bands must run consecutively with no gap and no overlap."),
                )
                break
        return cleaned

    def save(self, commit=True):
        # atomic for the same reason BrandingForm.save() is: the band rules are a
        # CROSS-ROW invariant the per-row CheckConstraint cannot restore, so a
        # failure between row 1 and row 2 would commit a band set the form
        # validated as a whole.
        with transaction.atomic():
            inst = super().save(commit=commit)
            for plan in self._plans:
                # .get(), not get_or_create: the field set is derived from rows
                # that already exist, so the create branch is unreachable.
                row = PricingPlan.objects.get(order=plan.order)
                for name in PLAN_FIELDS:
                    setattr(row, name, self.cleaned_data[f"plan_{plan.order}_{name}"])
                row.save()
        return inst
```

- [ ] **Step 4: Wire the seven points, with the flag read per request**

```python
# institution/views_manage.py -- replace the TABS tuple with a function
_BASE_TABS = (
    "branding", "access", "uploads", "sso", "notifications",
    "integrations", "support", "public-pages",
)


def _tabs():
    """Per REQUEST, not at import. A module-level conditional tuple is evaluated
    once, so override_settings(VENDOR_INSTANCE=True) would never reach it and the
    gate would half-work: the tab link renders, ?tab=pricing falls back to
    branding, and the panel never opens."""
    return _BASE_TABS + (("pricing",) if settings.VENDOR_INSTANCE else ())


def _active_tab(request):
    tab = request.GET.get("tab", "branding")
    return tab if tab in _tabs() else "branding"


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_pricing(request):
    if not settings.VENDOR_INSTANCE:
        raise Http404
    return _action(request, PricingForm, "pricing", "pricing", _("Pricing saved."))
```

Then: the URL (`path("manage/settings/pricing/", views_manage.settings_pricing, name="settings_pricing")`), the `_settings_context` keyword `pricing` (a valid identifier, which is why the ctx_key and tab slug can diverge — `settings_public_pages` documents that trap), the `_tabs.html` include guarded by `{% if vendor_instance %}`, the new `_pricing_tab.html` partial with its `action` pointing at `institution:settings_pricing`, and its panel div in `settings.html`.

Filter the gated page out of `_page_overrides()` when the flag is false, exempt `for-schools` from `missing_demo_notice` via `DEMO_NOTICE_SLUGS`, and **correct both stale docstrings**: `_page_overrides()`'s "Takes no argument" is now false, and `_settings_context`'s counts were **already wrong before this change** (it says seven forms / four institution forms where there are eight and five) — set them to the real post-change numbers, nine and six.

- [ ] **Step 5: Add the URL name to the existing method-guard test**

In `tests/test_settings_action_method_guard.py`, insert `"institution:settings_pricing"` **inside the `_action` group** (the list is ordered) and update the comment above it from "The first five" to "The first six". Give the new entry `override_settings(VENDOR_INSTANCE=True)` — without the flag it 404s and the guard would assert nothing.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_pricing_settings_tab.py tests/test_settings_action_method_guard.py tests/test_public_pages_settings.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
uv run ruff check --no-cache . && uv run ruff format .
git add institution/ templates/institution/ tests/
git commit -m "feat(pricing): gated Pricing settings tab with band validation"
```

---

### Task 15: Translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo`

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl`

- [ ] **Step 2: Clear every fuzzy flag on the new msgids**

Run: `grep -n "#, fuzzy" -A 3 locale/pl/LC_MESSAGES/django.po`

⚠️ Fuzzy entries are **ignored at runtime and render English**. Clearing one is TWO deletions — the `#, fuzzy` line and any wrong pre-filled `msgstr`. Also confirm `%(currency)s` and `%(above)s` survive verbatim into the Polish strings; a dropped placeholder is a runtime `KeyError`.

- [ ] **Step 3: Compile and verify**

Run: `uv run python manage.py compilemessages -l pl && uv run pytest tests/test_po_catalog_clean.py`
Expected: PASS, and no `#~` obsolete entries (the project forbids them).

- [ ] **Step 4: Commit**

```bash
git add locale/
git commit -m "i18n(pricing): Polish strings for the plans table and school page"
```

---

### Task 16: Screenshots

**Files:**
- Create: `tests/capture_for_schools_screenshots.py`

- [ ] **Step 1: Write the capture test**

Follow `tests/capture_tabs_panel_rule_screenshots.py`: `@pytest.mark.e2e`, `live_server`, `@override_settings(VENDOR_INSTANCE=True, ...)`, writing to `docs/superpowers/screenshots/`. Capture **two** states at phone width (390px) in **both** themes: the **fallback paragraph** (the state the branch actually ships in) and the **table** (fixture sets three prices by UPDATING the seeded rows).

⚠️ **Do NOT add `VENDOR_INSTANCE=True` to `tests/capture_help_screenshots.py`.** It hardcodes a 1280×800 light-only viewport and writes to `core/static/core/img/help/` — the shipped help documentation. Its `branding`, `sso`, `integrations` and `notifications` captures all clip `section.settings`, which contains `nav.settings__tabs`, so enabling the flag there would regenerate every committed help image showing schools a Pricing tab they do not have.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/capture_for_schools_screenshots.py -m e2e`
Expected: PASS, four PNGs written.

- [ ] **Step 3: Judge dark mode separately**

Read all four images. Dark is not "light with inverted colours" — check contrast on the table borders and the scroller edge independently.

- [ ] **Step 4: Commit**

```bash
git add tests/capture_for_schools_screenshots.py docs/superpowers/screenshots/
git commit -m "test(pricing): phone-width captures of both plan states"
```

---

## Definition of Done

- [ ] `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`
- [ ] `uv run pytest -m "not e2e"` — **grep the summary line**, do not trust the exit code (it can report 0 with failures)
- [ ] `uv run pytest -m e2e` for the capture and any new e2e
- [ ] `uv run ruff check --no-cache .` and `uv run ruff format --check .` both clean
- [ ] `uv run python manage.py makemigrations --check --dry-run` — no pending migrations
- [ ] `uv run python manage.py check`
- [ ] Screenshots reviewed in light **and** dark
- [ ] Falsification pass: for each new test, name the production edit that keeps it green and confirm that edit is not the bug
