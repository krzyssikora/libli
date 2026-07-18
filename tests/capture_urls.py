"""Capture-only ROOT_URLCONF: the real routes plus an unconditional /media/ route.

Django's `static()` helper returns [] when DEBUG is False (test settings set
DEBUG=False), and `config/urls.py` only wires media under `if settings.DEBUG`, so a
lesson-consumption capture would 404 on its MEDIA image. This urlconf serves media
directly via `django.views.static.serve`, reading MEDIA_ROOT at request time so an
`override_settings(MEDIA_ROOT=...)` in tests takes effect. Activated by the capture
harness via `override_settings(ROOT_URLCONF="tests.capture_urls")`.
"""

from django.conf import settings
from django.urls import re_path
from django.views.static import serve

from config.urls import urlpatterns as _base_urlpatterns


def _serve_media(request, path):
    # document_root read per-request so override_settings(MEDIA_ROOT=...) applies.
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = list(_base_urlpatterns) + [
    re_path(r"^media/(?P<path>.*)$", _serve_media),
]
