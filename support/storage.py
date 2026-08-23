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
