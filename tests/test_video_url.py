import pytest
from django.core.exceptions import ValidationError

from courses.video_url import _parse_duration
from courses.video_url import canonicalize_video_url


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90", 90),
        ("90s", 90),
        ("1m30s", 90),
        ("1h2m3s", 3723),
        ("2h", 7200),
        ("90m", 5400),
        ("0", 0),
        ("", 0),
        ("   ", 0),
        ("1m30sxyz", 0),  # trailing garbage
        ("s", 0),  # bare unit, no number
        ("1s30m", 0),  # out of order
    ],
)
def test_parse_duration(value, expected):
    assert _parse_duration(value) == expected


YT = "https://www.youtube.com/embed/lk5_OSsawz4"


@pytest.mark.parametrize(
    "raw,expected",
    [
        # watch / share / shorts / live / legacy, all → embed, cruft dropped
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&source_ve_path=MTc4", YT),
        ("https://youtu.be/lk5_OSsawz4?si=xMBEVds6TCuZdtQO", YT),
        ("https://www.youtube.com/shorts/lk5_OSsawz4", YT),
        ("https://www.youtube.com/live/lk5_OSsawz4", YT),
        ("https://www.youtube.com/v/lk5_OSsawz4", YT),
        ("https://m.youtube.com/watch?v=lk5_OSsawz4", YT),
        ("https://music.youtube.com/embed/lk5_OSsawz4", YT),
        ("https://www.youtube-nocookie.com/embed/lk5_OSsawz4", YT),
        # already-embed: idempotent (with and without start)
        (YT, YT),
        (YT + "?start=90", YT + "?start=90"),
        # scheme-less and scheme-relative paste
        ("youtu.be/lk5_OSsawz4", YT),
        ("www.youtube.com/watch?v=lk5_OSsawz4", YT),
        ("//youtu.be/lk5_OSsawz4", YT),
        # mixed-case host
        ("https://YOUTU.BE/lk5_OSsawz4", YT),
        ("https://WWW.YouTube.com/watch?v=lk5_OSsawz4", YT),
        # start time, all forms
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90s", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=1m30s", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&start=120", YT + "?start=120"),
        ("https://youtu.be/lk5_OSsawz4?t=90", YT + "?start=90"),  # share-link start
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=2h", YT + "?start=7200"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90m", YT + "?start=5400"),
        # query-value selection
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=&start=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=10&t=90", YT + "?start=10"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=s&start=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=0", YT),  # start=0 dropped
        # empty input
        ("", ""),
        ("   ", ""),
        # unrecognized host: stripped input returned unchanged (no lowercasing)
        ("https://www.geogebra.org/m/abc", "https://www.geogebra.org/m/abc"),
        ("https://Www.GeoGebra.org/m/abc", "https://Www.GeoGebra.org/m/abc"),
    ],
)
def test_canonicalize_youtube_and_passthrough(raw, expected):
    assert canonicalize_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch",  # no v=
        "https://www.youtube.com/watch?v=",  # empty v=
        "https://youtu.be/playlist",  # segment fails 11-char regex
        "https://youtu.be/watch",
        "https://youtu.be/aaaaaaaaaaaa",  # 12 chars → reject
        "https://youtu.be/",  # empty first segment
        "https://youtu.be",  # bare host, no path
        "https://youtu.be//lk5_OSsawz4",  # leading empty segment
        "https://www.youtube.com/channel/UCabc",  # recognized host, no ID → reject
    ],
)
def test_canonicalize_youtube_rejects(raw):
    with pytest.raises(ValidationError) as ei:
        canonicalize_video_url(raw)
    assert "YouTube" in str(ei.value)


def test_canonicalize_accepts_clean_11_char_id():
    # boundary: exactly 11 chars accepted
    assert canonicalize_video_url("https://youtu.be/abcdefghijk") == (
        "https://www.youtube.com/embed/abcdefghijk"
    )


V = "https://player.vimeo.com/video/123456"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://vimeo.com/123456", V),
        ("https://www.vimeo.com/123456", V),
        (V, V),  # idempotent
        ("vimeo.com/123456", V),  # scheme-less
        ("https://vimeo.com/channels/staffpicks/123456", V),
        # unlisted: privacy hash preserved
        ("https://vimeo.com/123456/abc123", V + "?h=abc123"),
        ("https://player.vimeo.com/video/123456?h=abc123", V + "?h=abc123"),
        ("https://player.vimeo.com/video/123456/abc123", V + "?h=abc123"),
        (V + "?h=abc123", V + "?h=abc123"),  # idempotent
        # hash containing - / _ is preserved (not dropped)
        ("https://vimeo.com/123456/ab-c_1", V + "?h=ab-c_1"),
        # start from fragment only; query t ignored
        ("https://vimeo.com/123456#t=90s", V + "#t=90s"),
        ("https://vimeo.com/123456#t=1m30s", V + "#t=90s"),  # normalized
        ("https://vimeo.com/123456?t=90", V),  # query t ignored
        # hash + start ordering and idempotency
        ("https://vimeo.com/123456/abc123#t=90s", V + "?h=abc123#t=90s"),
        (V + "?h=abc123#t=90s", V + "?h=abc123#t=90s"),  # idempotent
        # extra path segments are NOT a hash
        ("https://vimeo.com/123456/review/xyz", V),
    ],
)
def test_canonicalize_vimeo(raw, expected):
    assert canonicalize_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://vimeo.com/user12345",  # non-numeric, no ID
        "https://vimeo.com/channels/staffpicks",  # no numeric segment
    ],
)
def test_canonicalize_vimeo_rejects(raw):
    with pytest.raises(ValidationError) as ei:
        canonicalize_video_url(raw)
    assert "Vimeo" in str(ei.value)
