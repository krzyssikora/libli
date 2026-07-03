from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from notifications.retention import format_purge_result
from notifications.retention import purge_notifications


class Command(BaseCommand):
    help = "Delete read-and-aged and orphaned notifications (retention purge)."

    def add_arguments(self, parser):
        # type=int is required: a str window would hit a TypeError in the
        # service's numeric guards that our except ValueError would miss.
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            counts = purge_notifications(
                days=options["days"], dry_run=options["dry_run"]
            )
        except ValueError as exc:  # out-of-range window → clean CLI error
            raise CommandError(str(exc)) from exc
        self.stdout.write(format_purge_result(counts, dry_run=options["dry_run"]))
