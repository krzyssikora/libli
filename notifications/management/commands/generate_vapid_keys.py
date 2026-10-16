from django.core.management.base import BaseCommand

from notifications.push import generate_vapid_pair


class Command(BaseCommand):
    help = "Print a fresh VAPID key pair as .env.production lines. Writes nothing."

    def handle(self, *args, **options):
        public, private = generate_vapid_pair()
        self.stdout.write(f"LIBLI_VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"LIBLI_VAPID_PRIVATE_KEY={private}")
