"""Generate image derivatives for freshly imported media, off the request thread.

The importer creates media with generate=False (see importer._create_media):
decoding up to 1000 images inside the import's transaction would hold a write
transaction open for a minute. Instead the import VIEW schedules this job with
transaction.on_commit, so it starts only once the rows are committed and runs
in a daemon thread while the author is already looking at the builder.

Blank is the safe state: until the job reaches an asset, it serves its
original. If the process dies mid-job (a deploy, a worker recycle), the
remaining assets stay blank ("" state) and `backfill_media_derivatives` still
fills them in. An image interrupted between writing its derivative files and
saving the row leaves those files unreferenced -- a storage leak, never a
broken image.

The job runs for minutes on a big import while the author is already editing,
so every asset is re-read just before it is processed and the result is
written with a CONDITIONAL update: only if the row still has the same original
file and is still never-attempted. A concurrent replace_asset, a deletion, a
second job or a backfill run on the same rows makes the update hit 0 rows, and
the files this job just wrote are deleted instead of overwriting newer work.

Only the web views call this. The CLI import must not: a management command
exits as soon as it returns, killing a daemon thread mid-image.
"""

import logging
import threading

from django.db import connection
from django.db import transaction

from courses.derivatives import delete_derivative_files
from courses.derivatives import generate_derivatives
from courses.models import MediaAsset

logger = logging.getLogger(__name__)


def _process(pk):
    asset = MediaAsset.objects.filter(pk=pk, kind="image", derivatives_state="").first()
    if asset is None:  # deleted, or already handled elsewhere
        return
    original = asset.file.name
    storage = asset.thumb.storage
    generate_derivatives(asset)  # never raises
    updated = MediaAsset.objects.filter(
        pk=pk, file=original, derivatives_state=""
    ).update(
        width=asset.width,
        height=asset.height,
        thumb=asset.thumb.name or "",
        web=asset.web.name or "",
        derivatives_state=asset.derivatives_state,
    )
    if not updated:  # lost a race: never overwrite, never leak
        delete_derivative_files([asset.thumb.name, asset.web.name], storage)


def run_for_assets(asset_pks):
    """Generate derivatives for these assets, if still never-attempted ("").

    "" only, NOT failed: retrying FAILED rows is the backfill command's job.
    One bad asset never stops the rest.
    """
    for pk in sorted(asset_pks):
        try:
            _process(pk)
        except Exception:
            logger.exception(
                "derivative generation failed for media asset %s; "
                "backfill_media_derivatives will retry it",
                pk,
            )


def _close_connection():
    connection.close()


def _worker(asset_pks):
    try:
        run_for_assets(asset_pks)
    finally:
        # A thread's DB connection is its own: close it, or every import
        # leaks one connection until the worker process exits.
        _close_connection()


def _spawn(target, args):
    threading.Thread(
        target=target, args=args, name="import-derivatives", daemon=True
    ).start()


def schedule_for_import(report):
    """Start the job after the current transaction commits, for exactly the
    media this import created (report["media_pks"], filled by the importer).

    Skipped for a text-only archive, which carries nothing to generate.
    """
    asset_pks = list(report.get("media_pks", ()))
    if not asset_pks:
        return
    transaction.on_commit(lambda: _spawn(_worker, (asset_pks,)))
