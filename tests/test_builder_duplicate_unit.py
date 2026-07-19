import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.builder import ConflictError
from courses.builder import duplicate_unit
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset


def _tok(node):
    return node.updated.isoformat()


def _rich_unit():
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    q = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    Choice.objects.create(question=q, text="a", is_correct=True)
    Choice.objects.create(question=q, text="b")
    Element.objects.create(unit=unit, content_object=q)
    asset = make_image_asset(course, "pic.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(media=asset, alt="a", figcaption=""),
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="tabbed"),
        parent=join,
        tab_id=t2,
    )
    return course, unit, asset


def _images(node):
    # Filter to top-level elements so [0] doesn't hinge on implicit cross-scope order.
    return [
        e.content_object
        for e in node.elements.filter(parent__isnull=True)
        if isinstance(e.content_object, ImageElement)
    ]


def _texts(node):
    return [
        e.content_object
        for e in node.elements.filter(parent__isnull=True)
        if isinstance(e.content_object, TextElement)
    ]


def test_duplicate_rich_unit_equal_structure_and_shared_media():
    course, unit, asset = _rich_unit()
    src_elements = unit.elements.count()
    src_choices = Choice.objects.count()

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.pk != unit.pk
    assert copy.title == unit.title
    assert copy.elements.count() == src_elements
    assert Choice.objects.count() == src_choices * 2  # choices deep-copied
    assert MediaAsset.objects.filter(course=course).count() == 1  # media shared
    assert _images(copy)[0].media_id == asset.pk


def test_duplicate_is_immediate_next_sibling():
    course, unit, _asset = _rich_unit()
    copy = duplicate_unit(course, unit.pk, token=_tok(unit))
    siblings = list(
        ContentNode.objects.filter(course=course, parent=unit.parent).order_by(
            "order", "pk"
        )
    )
    i = [n.pk for n in siblings].index(unit.pk)
    assert siblings[i + 1].pk == copy.pk


def test_duplicate_independence():
    course, unit, _asset = _rich_unit()
    copy = duplicate_unit(course, unit.pk, token=_tok(unit))
    ct = _texts(copy)[0]
    ct.body = "<p>changed</p>"
    ct.save()
    assert _texts(unit)[0].body == "<p>hi</p>"


def test_duplicate_nested_unit_is_next_sibling_in_parent():
    # The core feature at a NON-top-level unit: exercises the parent-not-None
    # place_node path and the skipped course.updated bump.
    course, _top = make_course_with_unit()
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="Ch")
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U", parent=chapter
    )
    ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U2", parent=chapter
    )

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.parent_id == chapter.pk
    sibs = list(
        ContentNode.objects.filter(course=course, parent=chapter).order_by(
            "order", "pk"
        )
    )
    i = [n.pk for n in sibs].index(unit.pk)
    assert sibs[i + 1].pk == copy.pk


def test_duplicate_missing_video_kept_and_shared():
    # The asymmetric case the flag exists for: a missing VIDEO is "dropped" in
    # default export mode; drop_missing_media=False must keep it and share the asset.
    course, unit = make_course_with_unit()
    video = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("v.mp4", b"x"),
        original_filename="v.mp4",
        name="V",
    )
    Element.objects.create(
        unit=unit, content_object=VideoElement.objects.create(media=video, url="")
    )
    video.file.storage.delete(video.file.name)  # file gone on disk

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.elements.count() == 1  # video element NOT dropped
    assert copy.elements.get().content_object.media_id == video.pk  # shared asset
    assert MediaAsset.objects.filter(course=course).count() == 1


def test_duplicate_absent_media_keeps_real_shared_asset():
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "gone.png")
    Element.objects.create(
        unit=unit,
        content_object=ImageElement.objects.create(media=asset, alt="a", figcaption=""),
    )
    asset.file.storage.delete(asset.file.name)

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.elements.count() == 1
    assert copy.elements.get().content_object.media_id == asset.pk
    assert MediaAsset.objects.filter(course=course).count() == 1


def test_duplicate_dangling_element_is_skipped():
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>keep</p>")
    )
    orphan = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>gone</p>")
    )
    # Make the join DANGLE without cascading (deleting the concrete row would
    # cascade the join via GenericRelation): repoint object_id at a nonexistent
    # row so content_object resolves to None.
    Element.objects.filter(pk=orphan.pk).update(object_id=orphan.object_id + 10_000_000)

    copy = duplicate_unit(course, unit.pk, token=_tok(unit))

    assert copy.elements.count() == 1  # broken row silently skipped


def test_duplicate_stale_token_conflict():
    course, unit = make_course_with_unit()
    with pytest.raises(ConflictError):
        duplicate_unit(course, unit.pk, token="2000-01-01T00:00:00+00:00")


def test_duplicate_non_unit_raises_transfer_error():
    course, unit = make_course_with_unit()
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="C")
    with pytest.raises(TransferError):
        duplicate_unit(course, chapter.pk, token=chapter.updated.isoformat())
