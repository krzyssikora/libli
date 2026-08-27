"""Invitation and password-reset links are built from the django.contrib.sites
Site record (accounts/invitations.py:build_accept_url), deliberately, so they
cannot be host-spoofed. Django ships Site #1 as example.com, so without this
every such link on a fresh deployment is dead."""

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command


@pytest.mark.parametrize(
    "value",
    ["libli.example.org", "libli.example.org:8000", "localhost", "a-b.c-d.example"],
)
def test_valid_hosts_are_accepted(value):
    from institution.site_domain import validate_site_domain

    assert validate_site_domain(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "https://libli.example.org",  # scheme
        "libli.example.org/setup",  # path
        "libli.example.org/",  # trailing slash
        "user@libli.example.org",  # userinfo
        "-libli.example.org",  # leading hyphen in a label
        # 113 chars, every label <= 63: rejected by the LENGTH lookahead, not the
        # per-label rule -- so deleting (?=.{1,100}$) actually turns this red.
        "a" * 50 + "." + "b" * 50 + ".example.org",
        "",
    ],
)
def test_invalid_hosts_are_rejected(value):
    from institution.site_domain import validate_site_domain

    with pytest.raises(ValidationError):
        validate_site_domain(value)


@pytest.mark.django_db
def test_set_site_domain_persists_to_the_database():
    """Read the row back FRESH rather than through get_current(), which would
    hand back the same in-memory object set_site_domain just mutated."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    set_site_domain("libli.example.org", name="libli")
    row = Site.objects.get(pk=dj_settings.SITE_ID)
    assert (row.domain, row.name) == ("libli.example.org", "libli")


@pytest.mark.django_db
def test_set_site_domain_clears_the_sites_cache():
    """Assert on the CACHE, not on get_current().domain.

    get_current() returns the object held in SITE_CACHE, and set_site_domain
    mutates that very object -- so an assertion on get_current().domain reports
    the new value whether or not clear_cache() ran, and the mutant survives.
    The only observable effect of the clear is the cache entry's absence.
    """
    from django.conf import settings as dj_settings
    from django.contrib.sites import models as sites_models
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    # Prime a key Django's own receiver does NOT touch. django.contrib.sites
    # connects clear_site_cache to pre_save (models.py:119) and it deletes only
    # SITE_CACHE[instance.pk] and the OLD domain key -- so asserting on those
    # two passes whether or not set_site_domain cleared anything, and the mutant
    # survives. Only a whole-dict assertion distinguishes the two.
    sites_models.SITE_CACHE["stale.example.org"] = Site.objects.get_current()
    assert dj_settings.SITE_ID in sites_models.SITE_CACHE

    set_site_domain("libli.example.org")
    assert sites_models.SITE_CACHE == {}


@pytest.mark.django_db
def test_set_site_domain_truncates_an_overlong_name():
    """Site.name is max_length=50; Institution.name is longer. A realistic school
    name would otherwise raise DataError inside the form's transaction.atomic(),
    500-ing the Identity step and rolling back the brand colours with it."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    long_name = (
        "Zespol Szkol Ogolnoksztalcacych im. Marii Sklodowskiej-Curie w Warszawie"
    )
    assert len(long_name) > 50
    set_site_domain("libli.example.org", name=long_name)
    assert Site.objects.get(pk=dj_settings.SITE_ID).name == long_name[:50]


@pytest.mark.django_db
def test_command_sets_the_name():
    """The --name wiring, which nothing else exercises: a typo like
    options["site_name"] would otherwise ship green."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    call_command("set_site_domain", "--domain", "demo.example.org", "--name", "Acme")
    assert Site.objects.get(pk=dj_settings.SITE_ID).name == "Acme"


@pytest.mark.django_db
def test_command_sets_the_domain_from_the_argument():
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    call_command("set_site_domain", "--domain", "demo.example.org")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "demo.example.org"


@pytest.mark.django_db
def test_command_reads_the_env_var(monkeypatch):
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "env.example.org")
    call_command("set_site_domain")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "env.example.org"


@pytest.mark.django_db
def test_command_is_a_no_op_when_unset(monkeypatch):
    """The entrypoint calls this unconditionally. With no domain configured it
    must warn and exit cleanly, never abort the boot of a running instance."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    monkeypatch.delenv("DJANGO_SITE_DOMAIN", raising=False)
    call_command("set_site_domain")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "example.com"


@pytest.mark.django_db
def test_command_rejects_a_url(monkeypatch):
    from django.core.management.base import CommandError

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "https://demo.example.org/")
    with pytest.raises(CommandError):
        call_command("set_site_domain")


@pytest.mark.django_db
def test_only_if_placeholder_writes_when_the_site_is_unset():
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    call_command(
        "set_site_domain", "--domain", "first.example.org", "--only-if-placeholder"
    )
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "first.example.org"


@pytest.mark.django_db
def test_only_if_placeholder_leaves_a_configured_site_alone():
    """The entrypoint runs on EVERY boot. Without this the container would
    silently revert a hostname a Platform Admin corrected through the settings
    UI -- and restart: unless-stopped makes reboots routine."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    set_site_domain("chosen-by-the-admin.example.org")
    call_command(
        "set_site_domain",
        "--domain",
        "from-the-env.example.org",
        "--only-if-placeholder",
    )
    assert (
        Site.objects.get(pk=dj_settings.SITE_ID).domain
        == "chosen-by-the-admin.example.org"
    )
