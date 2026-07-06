import pytest
from django.core.exceptions import ValidationError

from courses.embed import extract_embed_url
from courses.embed import parse_iframe_dimensions

VALID = (
    '<iframe scrolling="no" title="demo" '
    'src="https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600" '
    'width="800" height="600" style="border:0px;"> </iframe>'
)


def test_geogebra_share_url_is_canonicalized():
    assert (
        extract_embed_url("https://www.geogebra.org/m/abc")
        == "https://www.geogebra.org/material/iframe/id/abc"
    )


def test_valid_snippet_extracts_src():
    assert extract_embed_url(VALID) == (
        "https://www.geogebra.org/material/iframe/id/abc123"
    )


def test_wrapper_div_with_single_iframe_is_valid():
    raw = '<div class="wrap">' + VALID + "</div>"
    assert extract_embed_url(raw).startswith("https://www.geogebra.org/")


def test_non_whitelisted_host_rejected():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="https://evil.example.com/x"></iframe>')
    assert "allow-list" in str(ei.value)


def test_non_snippet_non_whitelisted_url_rejected():
    with pytest.raises(ValidationError):
        extract_embed_url("https://evil.example.com/x")


def test_no_iframe_img_rejected():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<img src=x onerror="alert(1)">')
    assert "iframe" in str(ei.value).lower()


def test_script_embed_hits_no_iframe():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url(
            '<script src="https://www.geogebra.org/apps/deployggb.js"></script>'
        )
    assert "iframe" in str(ei.value).lower()


def test_javascript_src_rejected_via_https_check():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="javascript:alert(1)"></iframe>')
    assert "https" in str(ei.value).lower()


def test_scheme_relative_src_rejected_via_https_check():
    # spec §D: scheme-relative //host parses with scheme="" -> fails the https check
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src="//evil.example.com/x"></iframe>')
    assert "https" in str(ei.value).lower()


def test_two_iframes_rejected_multi():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a"></iframe>'
        '<iframe src="https://www.geogebra.org/material/iframe/id/b"></iframe>'
    )
    with pytest.raises(ValidationError) as ei:
        extract_embed_url(raw)
    assert "single" in str(ei.value).lower()


def test_empty_src_is_missing_src_not_https():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url('<iframe src=""></iframe>')
    msg = str(ei.value).lower()
    assert "src" in msg and "https" not in msg


def test_absent_src_is_missing_src():
    with pytest.raises(ValidationError) as ei:
        extract_embed_url("<iframe></iframe>")
    assert "src" in str(ei.value).lower()


def test_blank_input_rejected():
    with pytest.raises(ValidationError):
        extract_embed_url("   ")


@pytest.mark.django_db
def test_iframe_form_stores_only_src():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(data={"url": VALID, "title": "Demo"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.geogebra.org/material/iframe/id/abc123"


@pytest.mark.django_db
def test_iframe_form_canonicalizes_share_link():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/m/egZJdjsC", "title": "Geo"}
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.geogebra.org/material/iframe/id/egZJdjsC"


def test_non_geogebra_iframe_src_passes_through_unchanged():
    raw = '<iframe src="https://player.vimeo.com/video/123456"></iframe>'
    assert extract_embed_url(raw) == "https://player.vimeo.com/video/123456"


@pytest.mark.django_db
def test_iframe_form_rejects_non_whitelisted_snippet():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(
        data={"url": '<iframe src="https://evil.example.com/x"></iframe>', "title": ""}
    )
    assert not form.is_valid()
    assert "url" in form.errors


_REAL_TAG = (
    '<iframe scrolling="no" title="Pythagoras" '
    'src="https://www.geogebra.org/material/iframe/id/dc2j6xqt/width/800/height/760" '
    'width="800px" height="760px" style="border:0px;"> </iframe>'
)


def test_dimensions_from_px_attributes():
    assert parse_iframe_dimensions(_REAL_TAG) == (800, 760)


def test_dimensions_from_bare_integer_attributes():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="560" height="315"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (560, 315)


def test_dimension_junk_values_become_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="100%" height="800.5"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimension_zero_and_negative_become_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="0" height="-5"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimension_over_int_ceiling_becomes_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="9999999999" height="300"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, 300)


def test_dimensions_missing_attributes_are_none():
    raw = '<iframe src="https://www.geogebra.org/material/iframe/id/a"></iframe>'
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimensions_plain_url_is_none_none():
    assert parse_iframe_dimensions("https://www.geogebra.org/m/abc") == (None, None)


def test_dimensions_two_iframes_is_none_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="800" height="600"></iframe>'
        '<iframe src="https://www.geogebra.org/material/iframe/id/b" '
        'width="400" height="300"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimensions_empty_input_is_none_none():
    assert parse_iframe_dimensions("") == (None, None)
