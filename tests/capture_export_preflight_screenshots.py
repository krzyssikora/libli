"""Light + dark capture of the export pre-flight page's cap report.

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_export_preflight_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when this
path is passed explicitly. Mirrors tests/capture_publish_screenshots.py.

Why it exists: tests/test_transfer_export_preflight.py proves `.export-limits`
has a RULE, which is not the same as proving the panel reads well next to the
missing-media list it now shares a treatment with. This repo has shipped an
entire UI family with zero CSS past a green suite before.

Dark is set through User.theme, NOT the libli_theme cookie: for an authenticated
user _resolve_theme_pref lets User.theme win outright, so a cookie is silently
ignored and the "dark" shot would come back light.

Output goes to SHOT_DIR (env) or ./.superpowers/shots/, both gitignored.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def test_capture(page, live_server, settings):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Every count over its cap at once, so the panel is shot at its most
    # crowded -- five rows is the realistic worst case, and a one-row shot
    # would hide any spacing/rhythm problem between rows.
    settings.TRANSFER_MAX_NODES = 0
    settings.TRANSFER_MAX_ELEMENTS = 0
    settings.TRANSFER_MAX_MEDIA_ENTRIES = 0
    settings.TRANSFER_MAX_COURSE_JSON_BYTES = 1
    settings.TRANSFER_MAX_COMPRESSED_BYTES = 1
    settings.TRANSFER_MAX_UNCOMPRESSED_BYTES = 1

    owner = make_verified_user(
        username="shotexp", email="shotexp@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="shots-export", owner=owner, title="Export shots")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="A lesson"
    )
    # An element AND a media asset, so that elements/media_entries/archive_bytes
    # are all non-zero and therefore all over their zeroed caps. Without these,
    # `0 > 0` is False and the panel shoots with two rows instead of five --
    # hiding any rhythm problem between rows, which is half of what the shot is
    # for.
    from courses.models import Element
    from courses.models import ImageElement

    asset = make_image_asset(course)
    Element.objects.create(
        unit=unit, title="", content_object=ImageElement.objects.create(media=asset)
    )

    path = reverse("courses:manage_course_export", args=[course.slug])
    url = f"{live_server.url}{path}"

    _login(page, live_server, "shotexp")
    page.goto(url)
    page.wait_for_selector(".export-limits")
    page.screenshot(path=str(OUT_DIR / "export-preflight-light.png"), full_page=True)

    owner.theme = "dark"
    owner.save(update_fields=["theme"])
    page.goto(url)
    page.wait_for_selector(".export-limits")
    page.screenshot(path=str(OUT_DIR / "export-preflight-dark.png"), full_page=True)
