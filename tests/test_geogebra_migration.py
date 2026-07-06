import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "courses"
BEFORE = "0028_extend_element_models"
AFTER = "0029_backfill_geogebra_urls"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def test_backfill_canonicalizes_existing_geogebra_rows():
    old_apps = _migrate(BEFORE)
    Iframe = old_apps.get_model(APP, "IframeElement")
    share = Iframe.objects.create(url="https://www.geogebra.org/m/abc", title="share")
    cruft = Iframe.objects.create(
        url="https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600",
        title="cruft",
    )
    canonical = Iframe.objects.create(
        url="https://www.geogebra.org/material/iframe/id/keep", title="canonical"
    )
    other = Iframe.objects.create(
        url="https://player.vimeo.com/video/123", title="other"
    )

    new_apps = _migrate(AFTER)
    NewIframe = new_apps.get_model(APP, "IframeElement")
    assert NewIframe.objects.get(pk=share.pk).url == (
        "https://www.geogebra.org/material/iframe/id/abc"
    )
    assert NewIframe.objects.get(pk=cruft.pk).url == (
        "https://www.geogebra.org/material/iframe/id/abc123"
    )
    assert NewIframe.objects.get(pk=canonical.pk).url == (
        "https://www.geogebra.org/material/iframe/id/keep"
    )
    assert NewIframe.objects.get(pk=other.pk).url == (
        "https://player.vimeo.com/video/123"
    )

    _migrate(AFTER)  # leave the DB migrated forward for the rest of the suite
