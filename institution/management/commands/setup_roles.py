from django.core.management.base import BaseCommand

from institution.roles import seed_roles


class Command(BaseCommand):
    help = "Create the four libli role Groups (idempotent)."

    def handle(self, *args, **options):
        seed_roles()
        self.stdout.write(self.style.SUCCESS("Roles ensured."))
