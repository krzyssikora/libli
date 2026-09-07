"""Guards on the shipped markdown, in the style of test_public_pages_guards.py.

The retention guard works only because it asserts f-strings embedding each
constant INSIDE the surrounding prose -- a bare `"30" in text` is worthless.
"""

from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR, "docs", "public")
EN = (ROOT / "for-schools.md").read_text(encoding="utf-8")
PL = (ROOT / "for-schools.pl.md").read_text(encoding="utf-8")


def _backup_sh():
    return Path(settings.BASE_DIR, "backup.sh").read_text(encoding="utf-8")


def _backup_constant(name):
    line = next(
        line for line in _backup_sh().splitlines() if line.startswith(f"{name}=")
    )
    return int(line.split("=", 1)[1].split()[0].strip('"'))


def test_retention_periods_match_backup_sh():
    """SIX f-string patterns, not three bare substrings.

    A bare `str(daily) in text` is satisfied by any stray 30 and CANNOT see the
    cheap, worse mutant the original guard names: swapping which SENTENCE
    describes which period. Each constant is therefore asserted together with the
    words that say what it is a period FOR -- which is why Content 5 requires the
    privacy notices' sentences be reused character for character.

    The "about 13 months" consequence sentence is deliberately NOT asserted here:
    /for-schools/ carries the three period sentences only.
    """
    daily = _backup_constant("RETAIN_DAILY_DAYS")
    monthly = _backup_constant("RETAIN_MONTHLY_MONTHS")
    prune = _backup_constant("MIRROR_PRUNE_DAYS")

    assert f"A nightly copy is kept for **{daily} days**" in EN
    assert f"one copy per month for a further **{monthly} months**" in EN
    assert f"stay in the backup for **{prune} days**" in EN
    assert f"Kopię nocną przechowujemy **{daily} dni**" in PL
    assert f"kopię miesięczną przez kolejne **{monthly} miesięcy**" in PL
    assert f"pozostają w kopii **{prune} dni**" in PL


def test_plans_heading_has_prose_before_each_block_token():
    for token in ("{libli:pricing_plans}", "{libli:vat_note}"):
        for text in (EN, PL):
            before = text.split(token)[0].rstrip().splitlines()[-1]
            assert not before.startswith("#"), f"{token} sits directly under a heading"


@pytest.mark.parametrize("text", [EN, PL])
def test_the_timeline_does_not_promise_a_port_25_wait(text):
    """The settled default is a transactional provider on port 587, which Hetzner
    has never blocked; Direct Send is the documented exception.

    The disjunction this replaces (`"port 25" not in text or "587" in text`) could
    never fail: any file mentioning 587 was free to say anything about port 25.
    Asserted per LINE instead -- no line may pair port 25 with a waiting period.
    """
    for line in text.lower().splitlines():
        if "port 25" in line or "portu 25" in line:
            assert not any(
                w in line for w in ("month", "weeks", "miesi", "tygod", "wait", "czeka")
            ), f"the timeline promises a port-25 wait: {line!r}"


@pytest.mark.parametrize("text", [EN, PL])
def test_carries_no_demo_notice_token(text):
    assert "{libli:demo_notice}" not in text


@pytest.mark.parametrize(
    "text,generates_phrase,private_phrase,never_hold_phrase,reversed_phrase",
    [
        (
            EN,
            "you generate the new encryption key",
            "the private half never leaves your hands",
            "we never hold your private key",
            "hand you that key",
        ),
        (
            PL,
            "to Ty generujesz nowy klucz szyfrujący",
            "część prywatna nigdy nie opuszcza Twoich rąk",
            "nigdy nie mamy dostępu do Twojego klucza prywatnego",
            "przekazujemy Ci ten klucz",
        ),
    ],
)
def test_handover_states_the_school_generates_the_key(
    text, generates_phrase, private_phrase, never_hold_phrase, reversed_phrase
):
    """Round-1 review defect: section 6 originally read "we generate a fresh
    encryption key ... and hand you that key", reversing who generates the keypair.
    If libli generated it, libli's systems would necessarily hold the private half
    at least transiently before handover -- exactly the guarantee this section
    exists to rule out.

    Asserted as phrases inside the surrounding prose, not the bare word
    "key"/"klucz", which any sentence about encryption would satisfy regardless of
    who holds what -- see test_retention_periods_match_backup_sh's docstring for
    why a bare-word check is worthless here too.
    """
    assert generates_phrase in text
    assert private_phrase in text
    assert never_hold_phrase in text
    assert reversed_phrase not in text
