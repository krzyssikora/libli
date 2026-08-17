"""Populate MediaAsset image derivatives.

Blank is the safe state, so this command may be interrupted, re-run, or never
run: the only consequence is that un-backfilled assets keep serving originals.
"""

from django.core.management.base import BaseCommand

from courses.derivatives import delete_derivative_files
from courses.derivatives import generate_derivatives
from courses.models import DerivativesState
from courses.models import MediaAsset

_FIELDS = ["width", "height", "thumb", "web", "derivatives_state"]
# "" (never attempted) and failed are reprocessed; ok and skipped are left alone
# unless --force. Filtering against the TextChoices rather than string literals
# is what makes a typo'd state a hard error instead of a row silently
# reprocessed forever.
_PENDING = ["", DerivativesState.FAILED]


class Command(BaseCommand):
    help = "Generate thumb/web derivatives for MediaAsset images."

    def add_arguments(self, parser):
        parser.add_argument("--course", dest="course", default=None)
        parser.add_argument("--start-at", dest="start_at", type=int, default=None)
        parser.add_argument("--dry-run", dest="dry_run", action="store_true")
        parser.add_argument("--force", dest="force", action="store_true")

    def handle(self, *args, **opts):
        qs = MediaAsset.objects.filter(kind="image").order_by("pk")
        if opts["course"]:
            qs = qs.filter(course__slug=opts["course"])
        if opts["start_at"]:
            qs = qs.filter(pk__gte=opts["start_at"])
        if not opts["force"]:
            qs = qs.filter(derivatives_state__in=_PENDING)

        if opts["dry_run"]:
            # Counts only -- no per-row decode, and nothing written to storage
            # or the DB. Whether a given row WOULD produce derivatives is only
            # knowable by decoding it, so a richer report would reintroduce
            # exactly the work this flag exists to avoid.
            by_state = {}
            for state in [
                "",
                DerivativesState.OK,
                DerivativesState.SKIPPED,
                DerivativesState.FAILED,
            ]:
                by_state[state or "(pending)"] = qs.filter(
                    derivatives_state=state
                ).count()
            self.stdout.write(f"would process {qs.count()} asset(s): {by_state}")
            return

        tally = {
            DerivativesState.OK: 0,
            DerivativesState.SKIPPED: 0,
            DerivativesState.FAILED: 0,
        }
        for i, asset in enumerate(qs.iterator(), start=1):
            old_thumb, old_web = asset.thumb.name, asset.web.name
            storage = asset.thumb.storage
            state = generate_derivatives(asset)  # never raises
            asset.save(update_fields=_FIELDS)
            # --force regenerates over non-blank fields, so retire whatever it
            # superseded -- same != guard as replace_asset step 6.
            stale = [
                n
                for n, new in (
                    (old_thumb, asset.thumb.name),
                    (old_web, asset.web.name),
                )
                if n and n != new
            ]
            delete_derivative_files(stale, storage)
            tally[state] = tally.get(state, 0) + 1
            if i % 50 == 0:
                self.stdout.write(f"  {i} processed…")

        self.stdout.write(
            self.style.SUCCESS(
                f"done: {tally[DerivativesState.OK]} generated, "
                f"{tally[DerivativesState.SKIPPED]} skipped, "
                f"{tally[DerivativesState.FAILED]} failed"
            )
        )
