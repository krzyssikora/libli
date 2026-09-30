"""PWA C1: /sw.js (spec §2, §3) -- the truth table, the rendered values and
source guards on both worker templates."""

import json
import re

import pytest
from django.conf import settings as dj_settings
from django.template.loader import get_template
from django.urls import reverse

from core import pwa

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    pwa._manifest_bytes.cache_clear()
    yield
    pwa._manifest_bytes.cache_clear()


def _sw(client):
    return client.get("/sw.js")


def test_sw_route_is_the_root_path():
    assert reverse("core:service_worker") == "/sw.js"


def test_normal_worker_headers_and_values(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    r = _sw(client)
    assert r.status_code == 200
    assert r["Content-Type"] == "text/javascript; charset=utf-8"
    assert r["Cache-Control"] == "no-cache"
    body = r.content.decode()
    assert f"const VERSION = {json.dumps(pwa.worker_version())};" in body
    assert 'const PRECACHE = ["/offline/"];' in body
    assert "const CACHE_STATIC = false;" in body  # plain storage in the suite
    assert 'const PASSTHROUGH_PREFIXES = ["/media/"];' in body
    assert 'const PASSTHROUGH_SUFFIXES = ["/export/"];' in body
    assert "respondWith" in body
    assert "LIBLI_SW_KILL" not in body


def test_normal_worker_reports_cache_static_true_with_the_override(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PWA_CACHE_UNHASHED_STATIC = True
    assert "const CACHE_STATIC = true;" in _sw(client).content.decode()


@pytest.mark.parametrize("enabled,kill", [(True, True), (False, False), (False, True)])
def test_every_other_row_serves_the_kill_worker(client, settings, enabled, kill):
    settings.PWA_ENABLED = enabled
    settings.PWA_KILL_SWITCH = kill
    r = _sw(client)
    assert r.status_code == 200
    assert r["Cache-Control"] == "no-cache"
    body = r.content.decode()
    for needle in ("LIBLI_SW_KILL", "unregister", "caches.delete", "libli-"):
        assert needle in body, needle
    assert "respondWith" not in body


def test_download_routes_match_a_passthrough_suffix():
    """Renaming an export route must not silently stream a GB download through
    the worker."""
    for path in (
        reverse("courses:manage_course_export", kwargs={"slug": "c"}),
        reverse("courses:manage_node_export", kwargs={"slug": "c", "pk": 1}),
        reverse("courses:manage_analytics_export", kwargs={"slug": "c"}),
    ):
        assert path.endswith(pwa.PASSTHROUGH_SUFFIXES), path


def test_media_url_matches_a_passthrough_prefix():
    assert dj_settings.MEDIA_URL.startswith(pwa.PASSTHROUGH_PREFIXES)


def _outside_verbatim(source):
    return re.sub(r"\{% verbatim %\}.*?\{% endverbatim %\}", "", source, flags=re.S)


@pytest.mark.parametrize("name", ["core/sw.js", "core/sw_kill.js"])
def test_worker_js_lives_inside_verbatim(name):
    """Outside {% verbatim %} only Django comments and `const X = {{ y|safe }};`
    value slots may appear, so no JS can be eaten by the template engine."""
    source = get_template(name).template.source
    assert "{% verbatim %}" in source
    for line in _outside_verbatim(source).splitlines():
        line = line.strip()
        if not line:
            continue
        assert re.fullmatch(
            r"\{#.*#\}|const [A-Z_]+ = \{\{ [a-z_]+\|safe \}\};", line
        ), line


def test_normal_worker_source_guards():
    source = get_template("core/sw.js").template.source
    assert "LIBLI_SW_KILL" not in source
    assert "unregister" not in source
    assert "navigationPreload" not in source
    assert "new URL(request.url)" in source and ".pathname" in source
    assert 'request.destination === "document"' in source
    # A hit must not caches.open() (which recreates a deleted cache).
    assert "caches.match(request, { cacheName: STATIC_CACHE })" in source
    assert "ignoreVary: true" in source


def test_passthrough_matches_on_the_pathname_only():
    """Aimed at passthrough() itself, not at substrings found elsewhere in the
    file: the archive download is `.../export/?confirm=1`, so a path built from
    the full URL (or pathname + search) would stream a GB through the worker."""
    source = get_template("core/sw.js").template.source
    body = source[source.index("function passthrough(") :]
    body = body[: body.index("\n}\n")]
    assert "const path = url.pathname;" in body
    assert "url.search" not in body
    assert "url.href" not in body
    assert body.count("request.url") == 1  # only inside new URL(request.url)


def test_kill_worker_source_guards():
    source = get_template("core/sw_kill.js").template.source
    assert "LIBLI_SW_KILL" in source
    assert 'addEventListener("fetch"' not in source
