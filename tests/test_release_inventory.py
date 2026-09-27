"""scripts/release/inventory.py -- SCHOOL_HOSTS (spec §6)."""

import json
import os
import subprocess
import sys

import pytest

from tests.release_harness import ROOT

INV = ROOT / "scripts/release/inventory.py"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def entry(host="203.0.113.10", domain="szkola.pl", host_key=KEY):
    return {"host": host, "domain": domain, "host_key": host_key}


def _run(raw, *args):
    env = dict(os.environ)
    env["SCHOOL_HOSTS"] = raw
    env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, str(INV), *args], capture_output=True, text=True, env=env
    )


def test_all_resolves_every_code_sorted_and_masks_every_value(tmp_path):
    """Review focus 4."""
    raw = json.dumps(
        {"school-02": entry(host="h2.example"), "school-01": entry(domain="lo1.pl")}
    )
    out = tmp_path / "out"
    result = _run(raw, "plan", "all", "--output", str(out))
    assert result.returncode == 0, result.stderr
    assert out.read_text().strip() == 'codes=["school-01", "school-02"]'
    for value in ("h2.example", "lo1.pl", "203.0.113.10", "szkola.pl"):
        assert f"::add-mask::{value}" in result.stdout


def test_a_single_entry_and_all_is_a_matrix_of_one(tmp_path):
    out = tmp_path / "out"
    assert (
        _run(
            json.dumps({"school-01": entry()}), "plan", "all", "--output", str(out)
        ).returncode
        == 0
    )
    assert out.read_text().strip() == 'codes=["school-01"]'


def test_a_single_code_resolves_to_itself(tmp_path):
    out = tmp_path / "out"
    raw = json.dumps({"school-01": entry(), "school-02": entry()})
    assert _run(raw, "plan", "school-02", "--output", str(out)).returncode == 0
    assert out.read_text().strip() == 'codes=["school-02"]'


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("not json", "not valid JSON"),
        ("[]", "JSON object"),
        ("{}", "no schools"),
        (json.dumps({"liceum-krakow": entry()}), "school-NN"),
        (
            json.dumps({"school-01": {"host": "h", "host_key": KEY}}),
            "school-01: domain is empty",
        ),
        (json.dumps({"school-01": entry(host="")}), "school-01: host is empty"),
        (
            json.dumps({"school-01": entry(host="bad host")}),
            "school-01: host is malformed",
        ),
        (
            json.dumps({"school-01": entry(host="-oProxyCommand=x")}),
            "school-01: host is malformed",
        ),
        (
            json.dumps({"school-01": entry(domain="liceum,krakow.pl")}),
            "school-01: domain is malformed",
        ),
        (
            json.dumps({"school-01": entry(host_key="AAAA")}),
            "school-01: host_key is malformed",
        ),
    ],
)
def test_malformed_inventories_are_refused_without_echoing_values(
    tmp_path, raw, reason
):
    """Mutant: include the offending value in the message."""
    result = _run(raw, "plan", "all", "--output", str(tmp_path / "out"))
    assert result.returncode != 0
    assert reason in result.stderr
    for leaked in (
        "liceum",
        "bad host",
        "ProxyCommand",
        "AAAA",
        "203.0.113.10",
        "szkola",
    ):
        assert leaked not in result.stderr + result.stdout


def test_an_unknown_code_is_refused(tmp_path):
    result = _run(
        json.dumps({"school-01": entry()}),
        "plan",
        "school-09",
        "--output",
        str(tmp_path / "o"),
    )
    assert result.returncode != 0
    assert "unknown school code" in result.stderr


def test_entry_masks_first_then_writes_the_files(tmp_path):
    raw = json.dumps({"school-01": entry(host="h1.example", domain="lo1.pl")})
    d = tmp_path / "box"
    result = _run(raw, "entry", "school-01", "--dir", str(d))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:2] == [
        "::add-mask::h1.example",
        "::add-mask::lo1.pl",
    ]
    assert (d / "host").read_text() == "h1.example\n"
    assert (d / "known_hosts").read_text() == f"h1.example {KEY}\n"


def test_an_ipv6_host_is_accepted(tmp_path):
    """Review focus 3."""
    raw = json.dumps({"school-01": entry(host="2001:db8::10")})
    d = tmp_path / "box"
    result = _run(raw, "entry", "school-01", "--dir", str(d))
    assert result.returncode == 0, result.stderr
    assert (d / "known_hosts").read_text() == f"2001:db8::10 {KEY}\n"
