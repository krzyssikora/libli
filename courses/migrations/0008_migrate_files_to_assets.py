import os

from django.db import migrations, models
import django.db.models.deletion


def _short_name(name, limit=255):
    """basename truncated to limit, preserving extension (matches media.truncate_filename;
    inlined so the migration stays self-contained)."""
    base = os.path.basename(name or "")
    if len(base) <= limit:
        return base
    stem, dot, ext = base.rpartition(".")
    if dot and len(ext) + 1 < limit:
        return stem[: limit - len(ext) - 1] + "." + ext
    return base[:limit]


def copy_files_to_assets(apps, schema_editor):
    MediaAsset = apps.get_model("courses", "MediaAsset")
    ImageElement = apps.get_model("courses", "ImageElement")
    # 0007 RETAINS ImageElement.image for this copy; fail loudly if it doesn't, so a
    # mis-authored 0007 can't pass as a silent zero-copy.
    field_names = {f.name for f in ImageElement._meta.get_fields()}
    assert "image" in field_names, "0007 must retain ImageElement.image for the data copy"
    # Only image files exist in the seed; videos are url-only. Copy the storage
    # REFERENCE (the field's .name), never the bytes — CI-safe when the file is absent.
    for img in ImageElement.objects.all():
        name = getattr(img.image, "name", "") or ""
        if not name:
            continue
        asset = MediaAsset.objects.create(
            course_id=img_course_id(apps, img),
            kind="image",
            file=name,
            original_filename=_short_name(name),
        )
        img.media_id = asset.id
        img.save(update_fields=["media"])


def img_course_id(apps, img):
    # ImageElement -> Element join-row -> unit (ContentNode) -> course.
    Element = apps.get_model("courses", "Element")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get(app_label="courses", model="imageelement")
    join = Element.objects.filter(content_type=ct, object_id=img.id).first()
    if join is None:  # orphan element (no join-row) — not a supported runtime state
        raise RuntimeError(f"ImageElement {img.id} has no Element join-row; cannot map to a course")
    return join.unit.course_id


class Migration(migrations.Migration):
    dependencies = [("courses", "0007_mediaasset")]

    operations = [
        # IRREVERSIBLE DATA: reverse restores the schema (RemoveField re-adds the old
        # columns, AlterField re-allows null) but NOT the data — the copied file
        # references are not written back, so reversing yields empty image/file columns.
        # The data copy's reverse is a deliberate no-op.
        migrations.RunPython(copy_files_to_assets, migrations.RunPython.noop),
        # image files are now on assets; make the FK required and drop old columns.
        migrations.AlterField(
            model_name="imageelement",
            name="media",
            field=models.ForeignKey(
                limit_choices_to={"kind": "image"},
                on_delete=django.db.models.deletion.PROTECT,
                to="courses.mediaasset",
            ),
        ),
        migrations.RemoveField(model_name="imageelement", name="image"),
        migrations.RemoveField(model_name="videoelement", name="file"),
    ]
