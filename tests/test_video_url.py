import pytest

from courses.video_url import _parse_duration


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
