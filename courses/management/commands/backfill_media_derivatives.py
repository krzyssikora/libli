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
        parser.add_argument("--verify", dest="verify", action="store_true")

    def _verify(self, qs, dry_run):
        """Reset rows whose derivative FILES are gone, so the next pass regenerates.

        A blank derivative is safe -- the tag falls back to the original. A name
        that is SET while its file is absent is not: it renders a broken image,
        and the default work set can never repair it, because such rows read
        `ok`. Without this, recovery means --force over the whole library.

        Rows with both names blank are excluded: blank is the legal terminal
        state for skipped/failed rows, not a missing file.

        This costs one storage stat per referenced name, which is why it is an
        opt-in flag rather than the default -- on a remote backend that is a
        network round trip per derivative.
        """
        repaired = []
        for asset in qs.exclude(thumb="", web="").iterator():
            storage = asset.thumb.storage
            names = [n for n in (asset.thumb.name, asset.web.name) if n]
            # Blank is guarded twice on purpose: the queryset excludes
            # both-blank rows, and this filter drops a single blank name so it
            # can never be probed as "missing". Either layer alone suffices.
            if all(storage.exists(n) for n in names):
                continue
            repaired.append(asset.pk)
            if dry_run:
                continue
            # Retire the SURVIVING sibling too. Blanking both fields without
            # this would strand it: nothing would reference it and post_delete
            # could never find it. delete_derivative_files tolerates the name
            # that is already gone.
            delete_derivative_files(names, storage)
            asset.thumb = ""
            asset.web = ""
            asset.width = None
            asset.height = None
            asset.derivatives_state = ""
            asset.save(update_fields=_FIELDS)
        return repaired

    def handle(self, *args, **opts):
        qs = MediaAsset.objects.filter(kind="image").order_by("pk")
        if opts["course"]:
            qs = qs.filter(course__slug=opts["course"])
        if opts["start_at"]:
            qs = qs.filter(pk__gte=opts["start_at"])

        if opts["verify"]:
            # Runs BEFORE the work-set filter, and deliberately unfiltered by
            # state: the rows this repairs are `ok`, so the filter below would
            # hide them. Resetting them to "" is what puts them back in scope.
            repaired = self._verify(qs, opts["dry_run"])
            if opts["dry_run"]:
                self.stdout.write(
                    f"verify: {len(repaired)} row(s) reference a missing "
                    f"derivative file"
                )
            else:
                self.stdout.write(f"verify: {len(repaired)} repaired")

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
