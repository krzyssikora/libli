import pytest

from courses.element_forms import IframeElementForm
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


_FULL_TAG = (
    '<iframe title="Pythagoras" '
    'src="https://www.geogebra.org/material/iframe/id/dc2j6xqt/width/800/height/760" '
    'width="800px" height="760px" style="border:0px;"> </iframe>'
)
_OTHER_TAG = (
    '<iframe src="https://www.geogebra.org/material/iframe/id/other" '
    'width="640" height="480"></iframe>'
)
_OVERSIZED_TAG = (
    '<iframe src="https://www.geogebra.org/material/iframe/id/big" '
    'width="9999999999px" height="500px"></iframe>'
)


@pytest.mark.django_db
def test_form_captures_dimensions_from_full_iframe():
    form = IframeElementForm(data={"url": _FULL_TAG, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert (obj.width, obj.height) == (800, 760)


@pytest.mark.django_db
def test_form_plain_url_edit_preserves_existing_dimensions():
    obj = IframeElement.objects.create(url=URL, title="P", width=800, height=760)
    # Re-open to edit only the title; the field shows the canonical plain URL.
    form = IframeElementForm(data={"url": URL, "title": "renamed"}, instance=obj)
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (800, 760)  # unchanged
    assert saved.title == "renamed"


@pytest.mark.django_db
def test_form_re_paste_overwrites_dimensions():
    obj = IframeElement.objects.create(url=URL, title="P", width=800, height=760)
    form = IframeElementForm(data={"url": _OTHER_TAG, "title": "P"}, instance=obj)
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (640, 480)


@pytest.mark.django_db
def test_form_bare_url_paste_leaves_dimensions_none():
    form = IframeElementForm(data={"url": URL, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert (obj.width, obj.height) == (None, None)


@pytest.mark.django_db
def test_form_oversized_paste_degrades_without_500():
    form = IframeElementForm(data={"url": _OVERSIZED_TAG, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()  # must not raise "integer out of range"
    assert (obj.width, obj.height) == (None, None)  # falls back to 16:9
