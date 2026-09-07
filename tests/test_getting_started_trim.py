"""The trim keeps the sign-in help and fixes the premise, without stranding the
/privacy/ link that another guard's non-vacuity check depends on."""

from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR, "docs", "public")
EN = (ROOT / "getting-started.md").read_text(encoding="utf-8")
PL = (ROOT / "getting-started.pl.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_false_premise_is_gone(text):
    """Krzysztof hosts, one box per school -- the school does not run it itself."""
    assert "runs for itself" not in text
    assert "prowadzi u siebie" not in text


@pytest.mark.parametrize("text", [EN, PL])
def test_the_sign_in_help_survives(text):
    assert "/accounts/password/reset/" in text


def test_a_root_relative_privacy_link_survives_somewhere_in_shipped():
    """test_every_root_relative_link_resolves asserts
    {"/privacy/", "/accounts/password/reset/"} <= set(found) as an explicit
    non-vacuity check across the whole SHIPPED sweep. The paragraph carrying
    /privacy/ is the one being moved, so it must land somewhere."""
    everything = "".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "getting-started.md",
            "getting-started.pl.md",
            "for-schools.md",
            "for-schools.pl.md",
            "privacy.md",
            "privacy.pl.md",
        )
    )
    assert "/privacy/" in everything


@pytest.mark.parametrize("text", [EN, PL])
def test_the_cross_pointer_token_is_present_with_prose_above_it(text):
    assert "{libli:for_schools_link}" in text
    before = text.split("{libli:for_schools_link}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_demo_notice_token_still_has_prose_above_it(text):
    before = text.split("{libli:demo_notice}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")
