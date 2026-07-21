"""Media resolution + durable content-hash dedup for the LAL import loader."""

import hashlib
from pathlib import Path

from django.core.files.base import ContentFile

from courses.models import MediaAsset


def resolve_source(source_root, source_dir, media_src):
    return Path(source_root) / source_dir / media_src


def source_present(source_root, source_dir, media_src):
    """True iff media_src resolves to an existing local source file.

    A remote (http/https) src can never be a local file — the LAL parser
    sometimes captures an external ``<img src="https://…">`` as a media_src —
    so it reads as absent and the loader skips it tolerantly rather than
    aborting the whole part on a bare FileNotFoundError.
    """
    if isinstance(media_src, str) and media_src.startswith(("http://", "https://")):
        return False
    try:
        return resolve_source(source_root, source_dir, media_src).exists()
    except OSError:  # e.g. a URL-ish src with path-illegal chars on Windows
        return False


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def get_or_create_asset(course, kind, path):
    path = Path(path)
    data = path.read_bytes()
    digest = _sha256(data)
    existing = MediaAsset.objects.filter(course=course, content_hash=digest).first()
    if existing is not None:
        return existing
    asset = MediaAsset(
        course=course, kind=kind, original_filename=path.name, content_hash=digest
    )
    asset.file.save(path.name, ContentFile(data), save=False)
    asset.save()
    return asset
