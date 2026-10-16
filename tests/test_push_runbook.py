"""PWA C2 §9: the push runbook carries the commands and rules that matter."""

from pathlib import Path

from django.conf import settings

TEXT = (Path(settings.BASE_DIR) / "docs/deployment.md").read_text(encoding="utf-8")


def _section():
    start = TEXT.index("### Push notifications")
    return TEXT[start : TEXT.index("\n### ", start + 1)]


def test_runbook_steps():
    s = _section()
    assert "bash manage.sh generate_vapid_keys" in s
    assert "LIBLI_VAPID_SUBJECT=mailto:" in s
    assert "up -d --force-recreate app" in s
    assert "never copy them between schools" in s.lower() or "never copy" in s
    assert "rotate" in s
    assert "slows" in s
    # replace-if-present, append-if-not (a blind append would duplicate keys)
    assert 'grep -q "^$1=" .env.production' in s
    assert 'sed -i "s|^$1=.*|$1=$2|" .env.production' in s
    assert "set_env LIBLI_VAPID_PUBLIC_KEY" in s
    # turning it off
    assert "sed -i 's/^LIBLI_VAPID_" in s
    assert "docker compose restart" in s  # named, as the thing NOT to do


def test_restore_section_mentions_vapid_keys():
    start = TEXT.index("### Rolling back across a migration: restore in place")
    block = TEXT[start : TEXT.index("\n### ", start + 1)]
    assert "VAPID" in block


def test_env_example_lists_the_three_vars():
    path = Path(settings.BASE_DIR) / ".env.production.example"
    text = path.read_text(encoding="utf-8")
    for var in (
        "LIBLI_VAPID_PUBLIC_KEY=",
        "LIBLI_VAPID_PRIVATE_KEY=",
        "LIBLI_VAPID_SUBJECT=",
    ):
        assert f"\n{var}\n" in text
