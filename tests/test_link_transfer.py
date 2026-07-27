import pytest

from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element


def _text(body):
    """A saved TextElement. There is no TextElementFactory; this is the repo's idiom
    (see tests/test_guessnumber_endpoint.py). Note save() sanitises the body -- a
    relative href passes through untouched, which is the whole premise."""
    obj = TextElement(body=body)
    obj.save()
    return obj


pytestmark = pytest.mark.django_db


def _course_with_link():
    course = CourseFactory()
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    el = _text(f'<a href="/courses/n/{chapter.pk}/">ch</a>')
    add_element(unit, el)
    return course, chapter, unit


def test_export_records_in_scope_link_targets():
    course, chapter, _unit = _course_with_link()
    _manifest, document, _assets, _problems = build_export(course)
    assert str(chapter.pk) in document["link_nodes"]
    assert document["link_nodes"][str(chapter.pk)].startswith("n")


def test_export_leaves_bodies_byte_identical():
    course, chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    bodies = [e["data"]["body"] for e in document["elements"] if e["type"] == "text"]
    assert bodies == [f'<a href="/courses/n/{chapter.pk}/">ch</a>']


def test_format_version_is_6():
    assert FORMAT_VERSION == 6


def test_subtree_documents_carry_link_nodes_too():
    course, chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course, node=chapter)
    assert "link_nodes" in document
    # target_allowed_kinds is REQUIRED for kind="subtree": validate_document computes
    # `allowed = list(target_allowed_kinds or [])`, so omitting it rejects every node
    # ("The archive contains a 'chapter' node, which this structure does not allow").
    # Matches how importer.py:392 and tests/test_transfer_validation.py:63 call it.
    validate_document(
        document, kind="subtree", target_allowed_kinds=["chapter", "unit"]
    )


def test_v5_document_without_link_nodes_still_validates():
    # setdefault BEFORE _exact_keys is what makes the key optional in both directions:
    # without it a v5 doc fails "missing the key", and a new doc fails "unknown key".
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    del document["link_nodes"]
    validate_document(document, kind="course")  # must not raise


@pytest.mark.parametrize(
    "bad",
    [
        [],  # not a dict
        {"abc": "n1"},  # non-decimal key
        {"1": 2},  # non-string value
        {"1" * 20: "n1"},  # over-long key
    ],
)
def test_malformed_link_nodes_is_a_transfer_error(bad):
    course, _chapter, _unit = _course_with_link()
    _m, document, _a, _p = build_export(course)
    document["link_nodes"] = bad
    with pytest.raises(TransferError):
        validate_document(document, kind="course")
