"""Media resolution + durable content-hash dedup for the LAL import loader."""

import hashlib
from pathlib import Path

from django.core.files.base import ContentFile

from courses.models import MediaAsset


def resolve_source(source_root, source_dir, media_src):
    return Path(source_root) / source_dir / media_src


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
