import pytest

from courses.models import IframeElement

URL = "https://www.geogebra.org/material/iframe/id/abc"


@pytest.mark.django_db
def test_iframe_element_stores_nullable_dimensions():
    el = IframeElement.objects.create(url=URL, title="t", width=800, height=760)
    el.refresh_from_db()
    assert (el.width, el.height) == (800, 760)


@pytest.mark.django_db
def test_iframe_element_dimensions_default_null():
    el = IframeElement.objects.create(url=URL, title="t")
    el.refresh_from_db()
    assert (el.width, el.height) == (None, None)
