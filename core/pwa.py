"""Service-worker decisions for the PWA (spec:
docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md).

Everything the worker's behaviour depends on is decided here, once: which body
/sw.js serves, the version that retires old caches, whether /static/ may be
cached, and what the offline page shows."""

import functools
import hashlib

from django.conf import settings
from django.core.files.storage import storages
from django.template.loader import get_template

from core.services import PRIMARY_DEFAULT
from core.services import _safe_color
from core.services import default_name
from core.services import effective_primary

# Paths the worker never touches, not even as navigations: /media/ keeps HTTP
# Range for video seeking and keeps GBs of media out of the cache; /export/ is the
# course/subtree archive download (up to ~1 GiB) and the analytics CSV.
PASSTHROUGH_PREFIXES = ("/media/",)
PASSTHROUGH_SUFFIXES = ("/export/",)
PRECACHE = ("/offline/",)
NO_MANIFEST = b"nomanifest"

_VERSIONED_TEMPLATES = ("core/sw.js", "core/offline.html")


def _storage():
    return storages["staticfiles"]


@functools.lru_cache(maxsize=1)
def _manifest_bytes():
    """The staticfiles manifest's bytes, or NO_MANIFEST. THE one place that decides
    whether the storage has a manifest. Memoised per process: the manifest cannot
    change without a restart."""
    storage = _storage()
    name = getattr(storage, "manifest_name", None)
    if not name:
        return NO_MANIFEST
    reader = getattr(storage, "manifest_storage", None) or storage
    if not reader.exists(name):
        return NO_MANIFEST
    with reader.open(name) as fh:
        return fh.read()


def cache_static():
    return _manifest_bytes() != NO_MANIFEST or settings.PWA_CACHE_UNHASHED_STATIC


def serve_normal():
    """First row of the spec's §1 table; every other row serves the kill worker."""
    return bool(settings.PWA_ENABLED and not settings.PWA_KILL_SWITCH)


def offline_branding():
    """(name, primary) for the offline page, read from the DATABASE.

    Never get_site_config(): that cache is per-process with a 300 s TTL, so after
    a rename different gunicorn workers would serve different /sw.js bytes and a
    device could flip between versions. Never Institution.load(): that is
    get_or_create, a write on an anonymous GET."""
    from institution.models import Institution

    inst = Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    if inst is None:
        return default_name(), PRIMARY_DEFAULT
    colors = {c.key: c.value for c in inst.brand_colors.all()}
    name = (inst.name or "").strip() or default_name()
    return name, effective_primary({"primary": _safe_color(colors.get("primary"))})


def worker_version():
    # Not hashed: the compiled .mo catalogs. A release that changes ONLY the
    # offline page's translations leaves devices on the old wording until the next
    # VERSION change -- accepted in the spec (§2, beside the language-switch note).
    h = hashlib.sha256()
    h.update(_manifest_bytes())
    for name in _VERSIONED_TEMPLATES:
        h.update(b"\0")
        h.update(get_template(name).template.source.encode())
    for value in offline_branding():
        h.update(b"\0")
        h.update(str(value).encode())
    return h.hexdigest()[:12]
