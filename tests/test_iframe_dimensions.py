from unittest.mock import patch

import pytest
from django.template.loader import render_to_string

from courses.element_forms import IframeElementForm
from courses.models import IframeElement

URL = "https://www.geogebra.org/material/iframe/id/abc"

# render tests only — example.com is NOT whitelisted, so a form test would raise
OTHER_RENDER_URL = "https://example.com/embed/abc"
# NOT a new string: tests/test_iframe_dimensions.py:7 already defines URL with exactly
# this value. Alias it rather than restating it -- two names for one literal is the
# same ambiguity the _render replacement above exists to avoid.
SIZED_BASE = URL
SIZED_URL = f"{SIZED_BASE}/width/880/height/660"


def _render_url(url, width=None, height=None):
    el = IframeElement(url=url, title="P", width=width, height=height)
    return render_to_string("courses/elements/iframeelement.html", {"el": el})


def _render(width, height):
    """The pre-existing helper, REPLACED IN PLACE (not appended) by this one line.

    Keeps the name so the two surviving callers are untouched, but leaves ONE
    implementation -- two near-identical render helpers would leave the next reader
    unable to tell which is canonical.
    """
    return _render_url(URL, width, height)


def test_render_uses_aspect_ratio_when_dimensions_known():
    html = _render(800, 760)
    assert "embed-frame" in html
    assert "aspect-ratio: 800 / 760" in html


def test_render_geogebra_without_dimensions_uses_geogebras_own_default():
    html = _render_url(URL)
    assert "aspect-ratio: 800 / 600" in html


@pytest.mark.parametrize("w,h", [(800, None), (None, 600), (0, 0)])
def test_render_geogebra_partial_or_zero_pair_uses_the_default(w, h):
    assert "aspect-ratio: 800 / 600" in _render_url(URL, w, h)


def test_render_non_geogebra_without_dimensions_keeps_the_css_default():
    html = _render_url(OTHER_RENDER_URL)
    assert "embed-frame" in html
    assert "aspect-ratio:" not in html   # the .embed-frame 16:9 default stands


@pytest.mark.parametrize("w,h", [(800, None), (0, 0)])
def test_render_non_geogebra_partial_or_zero_pair_keeps_the_css_default(w, h):
    assert "aspect-ratio:" not in _render_url(OTHER_RENDER_URL, w, h)


def test_render_non_geogebra_with_a_usable_pair_still_gets_its_ratio():
    # Guards that step 1 does not swallow other providers.
    assert "aspect-ratio: 640 / 360" in _render_url(OTHER_RENDER_URL, 640, 360)


def test_render_url_sized_applet_reads_the_ratio_from_the_url():
    assert "aspect-ratio: 880 / 660" in _render_url(SIZED_URL)


def test_render_url_sized_applet_beats_a_disagreeing_stored_pair():
    # THE step-0-vs-step-2 ordering test. The stored pair deliberately DISAGREES with
    # the URL tail; a step-2-first build emits 880 / 660 around a 2:1 applet while
    # geogebra_sized_src leaves the src alone ("width" in segments), violating the
    # "never a frame ratio the src does not back up" invariant.
    url = "https://www.geogebra.org/material/iframe/id/abc/width/800/height/400"
    html = _render_url(url, 880, 660)
    assert "aspect-ratio: 800 / 400" in html
    # Both halves in ONE render. frame_ratio's contract is "never claim a ratio the src
    # does not back up", but every other test here measures only the frame -- so a
    # future change to geogebra_sized_src's guard could break the invariant with all of
    # them still green. Asserting the src alongside is what actually pins the pair.
    assert f'src="{url}"' in html


def test_render_material_url_that_sized_src_will_not_rewrite_claims_no_ratio():
    # THE step-1-vs-step-2 ordering test. /m/<id> carries a material id but is not a
    # shape geogebra_sized_src rewrites, so emitting the stored ratio would frame
    # GeoGebra's 800x600 default in an 880x660 box. Reachable via the admin.
    # This FAILS against the obvious three-branch implementation.
    html = _render_url("https://www.geogebra.org/m/dcjktevj", 880, 660)
    assert "aspect-ratio:" not in html


def test_render_geogebra_host_without_a_material_id_keeps_the_css_default():
    assert "aspect-ratio:" not in _render_url("https://www.geogebra.org/x")


@pytest.mark.parametrize("stored", [(None, None), (880, 660)])
def test_render_degenerate_shapes_follow_the_stored_pair(stored):
    # The two stricter-than-sized_src divergences. geogebra_material_id returns "" for
    # both, so step 1 is SKIPPED and the outcome depends entirely on the stored columns.
    for url in (
        "https://www.geogebra.org/material/iframe/id",
        "https://www.geogebra.org/material/iframe/id/ab%20cd",
    ):
        html = _render_url(url, *stored)
        if stored == (880, 660):
            assert "aspect-ratio: 880 / 660" in html   # step 2
        else:
            assert "aspect-ratio:" not in html          # step 4


def test_render_rejects_style_injection_from_the_url():
    # ';' and ':' are legal path characters and Django's autoescape leaves them alone.
    # Assert on the STYLE attribute only: the injected text legitimately survives inside
    # src="{{ el.embed_src }}", where it is inert, so asserting its absence from the
    # whole document would be RED against a correct build. Sanitising embed_src is NOT
    # in scope.
    hostile = (
        "https://www.geogebra.org/material/iframe/id/abc"
        "/width/1;position:fixed;top:0;height:100vh/height/1"
    )
    html = _render_url(hostile)
    assert 'style="aspect-ratio:' not in html


@pytest.mark.parametrize(
    "url",
    [
        f"{SIZED_BASE}/width/abc/height/def",
        f"{SIZED_BASE}/width/880",
        f"{SIZED_BASE}/width/0/height/0",
        f"{SIZED_BASE}/height/660/width/880",
    ],
)
def test_render_step0_rejection_cases_fall_through_to_no_inline_ratio(url):
    # These are covered at the geogebra_url_size unit level too, but "(None, None)"
    # is NOT the same claim as "the wrapper carries no inline ratio" -- the render
    # outcome depends on steps 1 and 2 running afterwards, which a unit test cannot
    # exercise. That fall-through is exactly what these pin.
    #
    # ACCEPTED GAP, not an oversight: all four keep the CSS 16:9 AND get no badge
    # (size_unknown is False, because "width" in segments makes is_geogebra_iframe_url
    # False). See the note under this block for why 800/600 is NOT the right answer
    # here. If you are tempted to "fix" this, read that note first.
    assert "aspect-ratio:" not in _render_url(url)


def test_render_geogebras_real_embed_tail_gets_the_urls_own_ratio():
    # The other half of the len(segments) >= 8 rule, at render level: GeoGebra's own
    # published embed src (12 segments) must take its ratio from the URL. Under a
    # len == 8 rule this renders 16:9 while the src imposes 1600/763 -- the defect.
    url = (
        "https://www.geogebra.org/material/iframe/id/egZJdjsC"
        "/width/1600/height/763/border/888888/sfsb/true"
    )
    html = _render_url(url)
    assert "aspect-ratio: 1600 / 763" in html
    assert f'src="{url}"' in html   # the frame matches the src it is framing


def test_render_non_geogebra_url_with_width_height_segments_gets_no_ratio():
    # geogebra_url_size is GeoGebra-scoped; a bare "path contains width" rule would
    # have given this provider an inline ratio it does not have today.
    url = "https://player.vimeo.com/video/1/width/4/height/3"
    assert "aspect-ratio:" not in _render_url(url)


def test_render_never_raises_on_a_malformed_authority():
    # frame_ratio's step 0 runs FIRST, so an unguarded urlsplit here would 500 the
    # student unit page before any fallback could be reached.
    assert "embed-frame" in _render_url("https://[::1")


# No explicit django_db marker needed -- tests/conftest.py::_enable_db_access is
# autouse, so every test in the suite already has DB access. The instance below is
# unsaved regardless, so this test touches no table either way.
@pytest.mark.parametrize(
    "url,width,height,expected",
    [
        (URL, None, None, True),            # canonical GeoGebra, no size -> badge
        (URL, 880, 660, False),             # sized -> no badge
        (URL, 800, None, True),             # partial pair mirrors frame_ratio
        # not the canonical shape sized_src rewrites
        ("https://www.geogebra.org/m/dcjktevj", None, None, False),
        ("https://www.geogebra.org/x", None, None, False),
        (OTHER_RENDER_URL, None, None, False),   # non-GeoGebra
    ],
)
def test_size_unknown_drives_the_editor_badge(url, width, height, expected):
    el = IframeElement(url=url, width=width, height=height)
    assert el.size_unknown is expected


@pytest.mark.django_db
def test_url_change_with_a_failed_lookup_leaves_the_element_badged():
    # The badge half of Task 6's
    # test_form_url_change_with_a_failed_lookup_does_not_keep_the_old_pair, which could
    # not assert it there: size_unknown does not exist until this task. Together they
    # pin the full outcome -- the new material neither inherits the old 880x660 nor
    # renders a confidently wrong frame with no badge to explain it.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    new_url = "https://www.geogebra.org/material/iframe/id/other123"
    form = IframeElementForm(data={"url": new_url, "title": "P"}, instance=obj)
    with patch(
        "courses.element_forms.fetch_geogebra_dimensions", return_value=(None, None)
    ):
        assert form.is_valid(), form.errors
    assert form.save().size_unknown is True


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
