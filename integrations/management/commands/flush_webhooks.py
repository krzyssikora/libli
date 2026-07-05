from django.core.management.base import BaseCommand

from integrations.flush import flush_pending


class Command(BaseCommand):
    help = "POST pending result-finalized webhook deliveries to the register."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = flush_pending(limit=options["limit"])
        self.stdout.write(
            f"webhooks flushed: sent={result['sent']} skipped={result['skipped']}"
        )
