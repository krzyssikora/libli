"""Runbook §9 "Outgoing email": the variables it sets are the ones production reads."""

import re
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)
TEXT = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")


def _section():
    start = TEXT.index("### Outgoing email")
    return TEXT[start : TEXT.index("\n### ", start + 1)]


def test_runbook_sets_exactly_the_vars_production_reads():
    prod = (ROOT / "config/settings/production.py").read_text(encoding="utf-8")
    read = set(re.findall(r'"(DJANGO_(?:EMAIL_\w+|DEFAULT_FROM_EMAIL))"', prod))
    assert "DJANGO_EMAIL_HOST" in read  # the regex still finds them
    set_by_runbook = set(re.findall(r"^set_env (\w+) ", _section(), re.M))
    assert set_by_runbook == read


def test_runbook_steps():
    s = _section()
    assert "port 587" in s.lower() or "**port 587**" in s
    assert "up -d --force-recreate app" in s
    assert "docker compose restart" in s  # named, as the thing NOT to do
    assert "sendtestemail" in s
    assert "never** as libli.pl" in s  # school boxes send from the school's domain
    assert 'grep -q "^$1=" .env.production' in s
