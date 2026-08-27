"""Set the django.contrib.sites Site domain from --domain or DJANGO_SITE_DOMAIN.

Called unconditionally by the container entrypoint after `migrate`, so that an
install is never *born* with dead invitation links. A no-op (with a warning)
when no domain is configured, because aborting here would stop an otherwise
healthy instance from booting.
"""

import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from institution.site_domain import PLACEHOLDER_DOMAIN
from institution.site_domain import set_site_domain


class Command(BaseCommand):
    help = "Set the Site domain used to build invitation and reset links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default=None,
            help="Public hostname, e.g. libli.example.org (optional :port).",
        )
        parser.add_argument(
            "--name", default=None, help="Human-readable site name (optional)."
        )
        parser.add_argument(
            "--only-if-placeholder",
            action="store_true",
            help="Write only while the Site still holds Django's example.com "
            "placeholder. The entrypoint uses this so a hostname corrected "
            "through the settings UI is not reverted on the next restart.",
        )

    def handle(self, *args, **options):
        domain = options["domain"] or os.environ.get("DJANGO_SITE_DOMAIN", "")
        domain = domain.strip()
        if not domain:
            self.stdout.write(
                self.style.WARNING(
                    "No --domain and no DJANGO_SITE_DOMAIN; leaving the Site "
                    "record unchanged. Invitation and password-reset links will "
                    "point at whatever it currently holds."
                )
            )
            return
        if options["only_if_placeholder"]:
            from django.contrib.sites.models import Site

            current = Site.objects.get_current().domain
            if current != PLACEHOLDER_DOMAIN:
                self.stdout.write(
                    f"Site domain is already {current!r}; leaving it alone "
                    f"(--only-if-placeholder)."
                )
                return
        try:
            site = set_site_domain(domain, name=options["name"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(f"Site domain set to {site.domain}"))
