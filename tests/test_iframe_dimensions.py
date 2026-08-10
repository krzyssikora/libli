from unittest.mock import patch

import pytest
from django.template.loader import render_to_string

from courses.element_forms import IframeElementForm
from courses.models import IframeElement

URL = "https://www.geogebra.org/material/iframe/id/abc"


def _render(width, height):
    el = IframeElement(url=URL, title="P", width=width, height=height)
    return render_to_string("courses/elements/iframeelement.html", {"el": el})


def test_render_uses_aspect_ratio_when_dimensions_known():
    html = _render(800, 760)
    assert "embed-frame" in html
    assert "aspect-ratio: 800 / 760" in html


def test_render_falls_back_to_16x9_when_dimensions_unknown():
    html = _render(None, None)
    assert "embed-frame" in html
    assert "aspect-ratio:" not in html  # no inline override → CSS default 16:9


def test_render_falls_back_when_dimensions_partial_or_zero():
    # A lone dimension or a 0 (possible on an imported archive) is falsy in the
    # `{% if el.width and el.height %}` guard → no inline aspect-ratio → 16:9.
    for w, h in [(800, None), (None, 600), (0, 0)]:
        html = _render(w, h)
        assert "embed-frame" in html
        assert "aspect-ratio:" not in html


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
def test_form_bare_url_paste_leaves_dimensions_none_when_lookup_disabled():
    # Passes via the kill switch (GEOGEBRA_API_LOOKUP=False under
    # config.settings.test), not because no lookup is wired up -- this is not
    # independent confirmation that the lookup path is inert.
    form = IframeElementForm(data={"url": URL, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert (obj.width, obj.height) == (None, None)


@pytest.mark.django_db
def test_form_oversized_paste_degrades_without_500():
    # Same caveat as the bare-url-paste test above: this passes via the kill
    # switch, not because no lookup is wired up.
    form = IframeElementForm(data={"url": _OVERSIZED_TAG, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()  # must not raise "integer out of range"
    assert (obj.width, obj.height) == (None, None)  # falls back to 16:9


# --- embed_src: render-ready src, GeoGebra-sized when dimensions are known ---


def test_embed_src_adds_geogebra_dimensions_when_known():
    el = IframeElement(url=URL, width=800, height=760)
    assert el.embed_src == URL + "/width/800/height/760"


def test_embed_src_is_plain_url_without_dimensions():
    el = IframeElement(url=URL)
    assert el.embed_src == URL


def test_render_iframe_src_carries_geogebra_dimensions():
    html = _render(800, 760)
    assert 'src="' + URL + '/width/800/height/760"' in html


# --- clean_url: the API lookup fires only on the three occasions it should ---

OTHER_FORM_URL = "https://player.vimeo.com/video/123"  # example.com is NOT whitelisted


def _patch_lookup(result=(880, 660)):
    return patch("courses.element_forms.fetch_geogebra_dimensions", return_value=result)


@pytest.mark.django_db
def test_form_share_link_paste_canonicalises_then_looks_up():
    # Post the actual SHARE-LINK shape, not the already-canonical URL: this is the
    # input the whole feature exists for, and asserting the lookup arg additionally
    # pins that clean_url gates on the CANONICALISED url, not the raw paste.
    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/m/dcjktevj", "title": "P"}
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (880, 660)
    lookup.assert_called_once_with("dcjktevj")


@pytest.mark.django_db
def test_form_non_geogebra_dimensionless_paste_never_looks_up():
    # THE guard on the `and mid` conjunct. Every other form test either uses a
    # GeoGebra URL (lookup fires anyway) or short-circuits on a usable pair BEFORE
    # mid is consulted -- so without this test a build that DELETES `and mid` stays
    # green while issuing a live GET to
    # https://api.geogebra.org/v1.0/materials/?scope=basic (empty id!) on every
    # dimensionless non-GeoGebra paste, inside the unit row lock.
    form = IframeElementForm(data={"url": OTHER_FORM_URL, "title": "P"})
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_geogebra_host_without_a_material_id_never_looks_up():
    # Second half of the `and mid` guard: a GeoGebra HOST whose URL yields no
    # material id must not trigger a lookup either.
    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/x", "title": "P"}
    )
    with _patch_lookup() as lookup:
        # If extract_embed_url rejects this URL the form is invalid -- that is fine
        # and the assertion below still holds; the point is that no lookup fires.
        form.is_valid()
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_static_embed_paste_never_looks_up():
    form = IframeElementForm(data={"url": _FULL_TAG, "title": "P"})
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_title_only_edit_of_a_sized_element_never_looks_up():
    # The textarea is pre-filled with the stored CANONICAL URL, so
    # parse_iframe_dimensions returns (None, None) on every later edit. Without the
    # instance guard this would fire a network call on every rename and could silently
    # replace the author's captured pair.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    form = IframeElementForm(data={"url": URL, "title": "renamed"}, instance=obj)
    with _patch_lookup((640, 480)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (880, 660)  # the invariant, asserted directly


@pytest.mark.django_db
def test_form_url_change_clears_the_stale_pair_and_looks_up_afresh():
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    new_url = "https://www.geogebra.org/material/iframe/id/other123"
    form = IframeElementForm(data={"url": new_url, "title": "P"}, instance=obj)
    with _patch_lookup((800, 400)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert lookup.call_count == 1
    assert (saved.width, saved.height) == (800, 400)


@pytest.mark.django_db
def test_form_url_change_with_a_failed_lookup_does_not_keep_the_old_pair():
    # THE test for what the stale-clear actually prevents. Every other url-change test
    # patches the lookup to SUCCEED, so its assertion is satisfied by the lookup's own
    # overwrite and would still pass with the clear deleted entirely. Only a FAILED
    # lookup exposes the real failure mode: the new material silently inheriting the
    # previous material's 880x660, rendering a confidently wrong frame with
    # size_unknown False -- so not even a badge to explain it.
    #
    # lookup.call_count in the sibling test does detect the clear indirectly, but only
    # while the guard keeps its current shape; this asserts the user-visible outcome.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    new_url = "https://www.geogebra.org/material/iframe/id/other123"
    form = IframeElementForm(data={"url": new_url, "title": "P"}, instance=obj)
    with _patch_lookup((None, None)):
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (None, None)
    # NOTE: the badge half of this outcome (size_unknown is True) is asserted in Task 7,
    # which is what adds the property. Do NOT add it here -- it would AttributeError.


@pytest.mark.django_db
def test_form_failed_lookup_saves_with_no_dimensions():
    form = IframeElementForm(data={"url": URL, "title": "P"})
    with _patch_lookup((None, None)):
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (None, None)


@pytest.mark.django_db
def test_form_dimensionless_element_retries_the_lookup_on_a_later_save():
    # Firing case 3: the badge invites a retry, so a save of an element whose stored
    # pair is unusable MUST try again. Gating on url_changed alone would kill this.
    obj = IframeElement.objects.create(url=URL, title="P")
    form = IframeElementForm(data={"url": URL, "title": "P"}, instance=obj)
    with _patch_lookup((880, 660)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert lookup.call_count == 1
    assert (saved.width, saved.height) == (880, 660)


@pytest.mark.django_db
def test_form_non_geogebra_url_change_keeps_its_dimensions():
    # The stale-clear is scoped to GeoGebra. Clearing provider-neutrally would wipe a
    # Vimeo element's captured pair on ANY url edit, with no lookup to restore it.
    obj = IframeElement.objects.create(
        url=OTHER_FORM_URL, title="P", width=640, height=360
    )
    form = IframeElementForm(
        data={"url": "https://player.vimeo.com/video/999", "title": "P"}, instance=obj
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (640, 360)


@pytest.mark.django_db
def test_form_geogebra_to_non_geogebra_url_change_keeps_the_geogebra_pair():
    # A KNOWN, ACCEPTED gap: the conjunct tests the NEW url, so swapping a GeoGebra
    # element to a video keeps 880x660. Not a regression (today's code never clears);
    # pinned so a future change to it is deliberate.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    form = IframeElementForm(data={"url": OTHER_FORM_URL, "title": "P"}, instance=obj)
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (880, 660)
