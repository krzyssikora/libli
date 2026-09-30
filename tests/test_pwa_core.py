"""PWA C1 core decisions (core/pwa.py) and the pwa_enabled context flag."""

import io

import pytest
from django.urls import reverse

from core import pwa
from core.services import PRIMARY_DEFAULT
from core.services import default_name
from core.services import get_site_config
from institution.models import BrandColor
from institution.models import Institution

pytestmark = pytest.mark.django_db


class _ManifestStorage:
    """Stands in for CompressedManifestStaticFilesStorage: only the surface
    _manifest_bytes() reads."""

    manifest_name = "staticfiles.json"

    def __init__(self, data):
        self.data = data

    def exists(self, name):
        return name == self.manifest_name

    def open(self, name):
        return io.BytesIO(self.data)


class _PlainStorage:
    """Stands in for StaticFilesStorage: no manifest_name at all."""


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    pwa._manifest_bytes.cache_clear()
    yield
    pwa._manifest_bytes.cache_clear()


@pytest.fixture
def storage(monkeypatch):
    def _use(obj):
        pwa._manifest_bytes.cache_clear()
        monkeypatch.setattr(pwa, "_storage", lambda: obj)

    return _use


def test_plain_storage_has_no_manifest(storage):
    storage(_PlainStorage())
    assert pwa._manifest_bytes() == pwa.NO_MANIFEST


def test_manifest_storage_bytes_are_read(storage):
    storage(_ManifestStorage(b'{"paths": {"a.css": "a.123.css"}}'))
    assert pwa._manifest_bytes() == b'{"paths": {"a.css": "a.123.css"}}'


def test_manifest_name_without_the_file_is_no_manifest(storage):
    class _Missing(_ManifestStorage):
        def exists(self, name):
            return False

    storage(_Missing(b"x"))
    assert pwa._manifest_bytes() == pwa.NO_MANIFEST


def test_manifest_is_read_through_manifest_storage_when_present(storage):
    inner = _ManifestStorage(b"via-manifest-storage")

    class _Outer(_ManifestStorage):
        manifest_storage = inner

        def exists(self, name):
            return False  # the outer storage must NOT be the one consulted

    storage(_Outer(b"outer"))
    assert pwa._manifest_bytes() == b"via-manifest-storage"


def test_cache_static_is_false_without_a_manifest(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = False
    storage(_PlainStorage())
    assert pwa.cache_static() is False


def test_cache_static_is_true_with_the_test_override(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = True
    storage(_PlainStorage())
    assert pwa.cache_static() is True


def test_cache_static_is_true_with_a_manifest(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = False
    storage(_ManifestStorage(b"{}"))
    assert pwa.cache_static() is True


@pytest.mark.parametrize(
    "enabled,kill,expected",
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    ],
)
def test_serve_normal_truth_table(settings, enabled, kill, expected):
    settings.PWA_ENABLED = enabled
    settings.PWA_KILL_SWITCH = kill
    assert pwa.serve_normal() is expected


def test_offline_branding_without_an_institution_row_creates_nothing():
    Institution.objects.all().delete()
    assert pwa.offline_branding() == (default_name(), PRIMARY_DEFAULT)
    assert Institution.objects.count() == 0


def test_offline_branding_strips_and_falls_back_on_a_blank_name():
    inst = Institution.load()
    Institution.objects.filter(pk=inst.pk).update(name="   ")
    assert pwa.offline_branding()[0] == default_name()


def _set_primary(inst, value):
    # institution/migrations/0002_seed_branding.py SEEDS the primary row and
    # BrandColor is unique on (institution, key): update it, never create() it.
    # update() is also signal-free, so the site-config cache is left stale.
    BrandColor.objects.filter(institution=inst, key="primary").update(value=value)


def test_offline_branding_reads_the_primary_brand_colour():
    inst = Institution.load()
    _set_primary(inst, "#123456")
    assert pwa.offline_branding()[1] == "#123456"


def test_offline_branding_rejects_an_invalid_colour():
    inst = Institution.load()
    # Signal-free write of a value the validator would refuse.
    _set_primary(inst, "red;}")
    assert pwa.offline_branding()[1] == PRIMARY_DEFAULT


def test_version_follows_a_signal_free_rename():
    """The DB, not the per-process site-config cache: warm the cache, then write
    with update() (no post_save, so the cache really is stale). Reading
    get_site_config() instead would leave the version unchanged."""
    inst = Institution.load()
    get_site_config()  # warm
    before = pwa.worker_version()
    Institution.objects.filter(pk=inst.pk).update(name="Fresh Name School")
    assert get_site_config()["name"] != "Fresh Name School"  # cache is stale
    assert pwa.offline_branding()[0] == "Fresh Name School"
    assert pwa.worker_version() != before


def test_version_follows_a_signal_free_recolour():
    inst = Institution.load()
    _set_primary(inst, "#112233")
    get_site_config()  # warm
    before = pwa.worker_version()
    _set_primary(inst, "#445566")
    assert pwa.offline_branding()[1] == "#445566"
    assert pwa.worker_version() != before


def test_version_follows_the_manifest_bytes(storage):
    storage(_ManifestStorage(b"one"))
    first = pwa.worker_version()
    storage(_ManifestStorage(b"two"))
    assert pwa.worker_version() != first


def test_version_is_stable_with_nothing_changed():
    Institution.load()
    assert pwa.worker_version() == pwa.worker_version()
    assert len(pwa.worker_version()) == 12
    int(pwa.worker_version(), 16)  # hex


def test_context_flag_on_only_in_the_first_row(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    assert client.get(reverse("account_login")).context["pwa_enabled"] is True
    settings.PWA_KILL_SWITCH = True
    assert client.get(reverse("account_login")).context["pwa_enabled"] is False
