"""Issue #153 hardening: MEDIA_URL / STATIC_URL are configured root-absolute.

IMPORTANT — what these tests do and do NOT prove.

The original issue premised that `MEDIA_URL = "media/"` (no leading slash) makes
`FileField.url` emit a *relative* src that 404s on a nested lesson page. That
premise does not hold under Django 5.2: `LazySettings.__getattr__` runs
`_add_script_prefix()` on every MEDIA_URL/STATIC_URL read, and `get_script_prefix()`
never returns empty, so `"media/"` already resolves to `/media/...` at a root
deployment. The end-to-end src is therefore absolute either way.

So the *falsifiable* guard here is not "the rendered src is absolute" (that passes
regardless of the leading slash and would be vacuous). It is that the value
*configured in settings* is root-absolute — read raw from the settings module,
bypassing the script-prefix normalization. Reverting the settings edit to
`"media/"` / `"static/"` turns `test_configured_*_url_is_root_absolute` red.

`test_uploaded_image_src_is_root_relative_on_nested_lesson_page` is kept as an
end-to-end integration guard (uploaded image renders + resolves absolute on a
genuinely nested URL). It does not falsify the leading-slash change on its own.
"""

import re

import pytest

from courses.models import Element
from courses.models import Enrollment
from courses.models import GalleryElement
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_configured_media_url_is_root_absolute():
    """Falsifier for the issue #153 edit. Reads the RAW module attribute, not
    django.conf.settings.MEDIA_URL — the latter is normalized by
    `_add_script_prefix` and would read `/media/` even for a relative config,
    hiding a revert. Revert to `"media/"` and this goes red."""
    from config.settings import base

    assert base.MEDIA_URL.startswith("/"), (
        f"MEDIA_URL should be configured root-absolute, got {base.MEDIA_URL!r}"
    )


def test_configured_static_url_is_root_absolute():
    from config.settings import base

    assert base.STATIC_URL.startswith("/"), (
        f"STATIC_URL should be configured root-absolute, got {base.STATIC_URL!r}"
    )


def test_uploaded_image_src_is_root_relative_on_nested_lesson_page(client):
    """End-to-end guard: an uploaded image on a nested `/courses/<slug>/u/<pk>/`
    lesson page renders an absolute `/media/...` src (so it would not resolve
    against the current path). NB this passes under Django 5.2 regardless of the
    leading slash — it documents the property, it is not the revert falsifier."""
    course, unit = make_course_with_unit()
    a1 = make_image_asset(course, filename="one.png")
    a2 = make_image_asset(course, filename="two.png")
    gallery = GalleryElement.objects.create(
        data={"images": [{"media": a1.pk, "desc": ""}, {"media": a2.pk, "desc": ""}]}
    )
    Element.objects.create(unit=unit, content_object=gallery)

    student = make_verified_user(username="mediastu", email="mediastu@school.edu")
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)

    from django.urls import reverse

    url = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    assert "/u/" in url  # the page URL is genuinely nested
    resp = client.get(url)
    assert resp.status_code == 200

    srcs = re.findall(rb'<img[^>]+src="([^"]+)"', resp.content)
    media_srcs = [s.decode() for s in srcs if b"media" in s]
    assert media_srcs, "expected at least one uploaded-image <img> on the page"
    for src in media_srcs:
        assert src.startswith("/media/"), (
            f"uploaded-image src {src!r} is not root-relative; on a nested page it "
            "would resolve against the current path and 404 (issue #153)"
        )
