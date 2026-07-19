from courses.models import ContentNode, Element, ImageElement, MediaAsset
from courses.transfer.export import build_export
from courses.transfer.importer import materialize_duplicate
from tests.factories import make_course_with_unit, make_image_asset


def test_materialize_duplicate_shares_media_and_creates_nodes():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(
            media=asset, alt="a", figcaption=""
        ),
    )
    _manifest, document, media_assets, _problems = build_export(
        course, node=unit, drop_missing_media=False
    )
    media_map = {mid: a for (mid, a, _p) in media_assets}

    before = ContentNode.objects.filter(course=course).count()
    new_root = materialize_duplicate(document, media_map, course, unit.parent)

    assert ContentNode.objects.filter(course=course).count() == before + 1
    assert new_root.pk != unit.pk
    # shared media: the copy's image element points at the SAME asset row
    new_img = new_root.elements.get().content_object
    assert new_img.media_id == asset.pk
    # no new MediaAsset rows were created
    assert MediaAsset.objects.filter(course=course).count() == 1
