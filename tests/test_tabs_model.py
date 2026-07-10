import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.sanitize import sanitize_label

pytestmark = pytest.mark.django_db


def test_new_tab_id_format_and_uniqueness():
    tid = TabsElement.new_tab_id()
    assert TabsElement.TAB_ID_RE.fullmatch(tid), tid
    assert len(tid) == 7
    assert TabsElement.new_tab_id({tid}) != tid


def test_default_data_has_min_tabs_with_distinct_ids():
    data = TabsElement.default_data()
    assert len(data["tabs"]) == TabsElement.MIN_TABS
    ids = [t["id"] for t in data["tabs"]]
    assert len(set(ids)) == len(ids)


def test_sanitize_label_strips_tags_and_truncates():
    assert sanitize_label("<b>Hi</b> there") == "Hi there"
    assert len(sanitize_label("x" * 200)) == 80
    assert sanitize_label(None) == ""


def test_normalize_labels_and_ids_is_non_destructive():
    """It may never change WHICH tabs exist — only their labels/ids."""
    raw = {"tabs": [{"id": "tabcdef", "label": "A"}]}
    out = TabsElement.normalize_labels_and_ids(raw)
    assert len(out["tabs"]) == 1  # NOT padded to MIN_TABS
    assert out["tabs"][0]["id"] == "tabcdef"


def test_normalize_labels_and_ids_fills_blank_label_and_missing_id():
    out = TabsElement.normalize_labels_and_ids({"tabs": [{}, {"label": "  "}]})
    assert out["tabs"][0]["label"] == "Tab 1"
    assert out["tabs"][1]["label"] == "Tab 2"
    assert all(TabsElement.TAB_ID_RE.fullmatch(t["id"]) for t in out["tabs"])


def test_normalize_labels_and_ids_keeps_first_duplicate_regenerates_later():
    out = TabsElement.normalize_labels_and_ids(
        {"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "taaaaaa", "label": "B"}]}
    )
    assert out["tabs"][0]["id"] == "taaaaaa"
    assert out["tabs"][1]["id"] != "taaaaaa"


def test_normalize_data_pads_and_truncates():
    padded = TabsElement.normalize_data({"tabs": [{"id": "taaaaaa", "label": "A"}]})
    assert len(padded["tabs"]) == TabsElement.MIN_TABS
    many = {"tabs": [{"label": f"T{i}"} for i in range(30)]}
    assert len(TabsElement.normalize_data(many)["tabs"]) == TabsElement.MAX_TABS


@pytest.mark.parametrize("blob", [None, {}, {"tabs": None}, {"tabs": "x"}, "junk", []])
def test_normalize_data_never_raises(blob):
    out = TabsElement.normalize_data(blob)
    assert len(out["tabs"]) >= TabsElement.MIN_TABS


def test_save_does_not_pad_or_truncate():
    """save() runs only the non-destructive normalizer."""
    el = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "Solo"}]})
    el.save()
    el.refresh_from_db()
    assert len(el.data["tabs"]) == 1  # padding is read-side only


def test_save_never_rewrites_an_existing_unique_id():
    el = TabsElement.objects.create(data={"tabs": [{"id": "tbbbbbb", "label": "A"}]})
    el.data["tabs"][0]["label"] = "renamed"
    el.save()
    el.refresh_from_db()
    assert el.data["tabs"][0]["id"] == "tbbbbbb"


def test_element_defaults_to_top_level():
    f = Element._meta.get_field("parent")
    assert f.null is True
    assert Element._meta.get_field("tab_id").default == ""
