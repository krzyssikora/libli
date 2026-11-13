"""Generate image derivatives for an imported course, off the request thread.

The importer creates media with generate=False (see importer._create_media):
decoding up to 1000 images inside the import's transaction would hold a write
transaction open for a minute. Instead the import VIEW schedules this job with
transaction.on_commit, so it starts only once the rows are committed and runs
in a daemon thread while the author is already looking at the builder.

Blank is the safe state: until the job reaches an asset, it serves its
original. If the process dies mid-job (a deploy, a worker recycle), the
remaining assets stay blank ("" state) and `backfill_media_derivatives` still
repairs them -- nothing is ever left broken.

Only the web views call this. The CLI import must not: a management command
exits as soon as it returns, killing a daemon thread mid-image.
"""

import logging
import threading

from django.db import connection
from django.db import transaction

from courses.derivatives import generate_derivatives
from courses.models import MediaAsset

logger = logging.getLogger(__name__)

_FIELDS = ["width", "height", "thumb", "web", "derivatives_state"]


def run_for_course(course_pk):
    """Generate derivatives for the course's never-attempted images.

    "" only, NOT failed: a FAILED image would fail again on every import into
    the same course; retrying those is the backfill command's job.
    """
    qs = MediaAsset.objects.filter(
        course_id=course_pk, kind="image", derivatives_state=""
    ).order_by("pk")
    for asset in qs.iterator():
        generate_derivatives(asset)  # never raises
        asset.save(update_fields=_FIELDS)


def _close_connection():
    connection.close()


def _worker(course_pk):
    try:
        run_for_course(course_pk)
    except Exception:
        logger.exception(
            "derivative generation failed for course %s; "
            "run backfill_media_derivatives to finish it",
            course_pk,
        )
    finally:
        # A thread's DB connection is its own: close it, or every import
        # leaks one connection until the worker process exits.
        _close_connection()


def _spawn(target, args):
    threading.Thread(
        target=target, args=args, name="import-derivatives", daemon=True
    ).start()


def schedule_for_course(course, document):
    """Start the job after the current transaction commits.

    Skipped for a text-only archive, which carries nothing to generate.
    """
    if not document["media"]:
        return
    course_pk = course.pk
    transaction.on_commit(lambda: _spawn(_worker, (course_pk,)))
