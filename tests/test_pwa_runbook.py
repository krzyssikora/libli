"""PWA C1: the kill-switch runbook carries the commands that actually work."""

from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)


def _section():
    text = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    start = text.index("### PWA kill switch")
    return text[start : text.index("\n## ", start)]


def test_runbook_recreates_rather_than_restarts():
    section = _section()
    assert "up -d --force-recreate app" in section
    assert "docker compose restart" in section  # named, as the thing NOT to do
    assert "LIBLI_SW_KILL" in section
    assert "grep -c LIBLI_SW_KILL" in section
    # a box provisioned before the worker shipped has no line: the command appends
    assert "echo 'LIBLI_PWA_KILL_SWITCH=true' >> .env.production" in section
    assert '[ -n "$(tail -c1 .env.production)" ] && echo >> .env.production' in section
    assert "grep -x 'LIBLI_PWA_KILL_SWITCH=true' .env.production" in section


def test_env_example_documents_both_variables():
    text = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    assert "\nLIBLI_PWA_KILL_SWITCH=\n" in text
    assert "\n# LIBLI_PWA_ENABLED=" in text  # commented: unset means on
