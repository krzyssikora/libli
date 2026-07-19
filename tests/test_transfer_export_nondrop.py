from courses.models import Element, ImageElement
from courses.transfer.export import build_export
from tests.factories import make_course_with_unit, make_image_asset


def _unit_with_missing_image():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "gone.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    # Remove the backing file so the export's on-disk probe reports it missing.
    asset.file.storage.delete(asset.file.name)
    return course, unit, asset


def _entry_for(media_assets, asset):
    return [(m, a, p) for (m, a, p) in media_assets if a.pk == asset.pk]


def test_missing_media_defaults_to_placeholder():
    course, unit, asset = _unit_with_missing_image()
    _manifest, document, media_assets, _problems = build_export(course, node=unit)
    entry = _entry_for(media_assets, asset)
    assert entry, "asset should still be represented"
    assert entry[0][2] is True  # is_placeholder — degraded in default mode


def test_drop_missing_media_false_keeps_asset_real():
    course, unit, asset = _unit_with_missing_image()
    _manifest, document, media_assets, _problems = build_export(
        course, node=unit, drop_missing_media=False
    )
    entry = _entry_for(media_assets, asset)
    assert entry, "every referenced mid must survive into media_assets"
    assert entry[0][2] is False  # treated as real, not placeholder
    assert len(document["elements"]) == 1  # element not dropped
