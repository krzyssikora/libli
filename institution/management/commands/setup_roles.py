"""Management command: create or reconcile the RBAC role groups."""

from django.core.management.base import BaseCommand

from institution.roles import seed_roles


class Command(BaseCommand):
    help = (
        "Create the four libli role Groups and assign Phase-0 permissions "
        "to Platform Admin (idempotent)."
    )

    def handle(self, *args, **options):
        seed_roles()
        self.stdout.write(self.style.SUCCESS("Roles ensured."))
