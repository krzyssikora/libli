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


def test_sanitize_label_collapses_whitespace_and_truncates():
    assert sanitize_label("  Hi   there \n") == "Hi there"
    assert len(sanitize_label("x" * 200)) == 80
    assert sanitize_label(None) == ""


@pytest.mark.parametrize(
    "label",
    [
        r"\(a<b\)",
        r"\(x_{1}<x_{2}\)",
        r"\[a<b<c\]",
        r"Wzór \(x^2\)",
        r"Case \(n>1\)",
    ],
)
def test_sanitize_label_keeps_latex_verbatim(label):
    """`<` followed by a letter is a tag start to an HTML parser, so an HTML
    sanitiser silently ate the rest of the label: `\\(a<b\\)` was stored as `\\(a`.
    A label is plain TEXT that may carry LaTeX, and every sink escapes it (see
    test_tabs_partial.test_a_label_carrying_markup_renders_escaped), so it must
    survive byte-for-byte."""
    assert sanitize_label(label) == label


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


def test_normalizers_default_the_new_keys_on_an_empty_blob():
    norm = TabsElement.normalize_labels_and_ids({})
    assert norm["display"] == "tabs"
    assert norm["label_pos"] == "above"


@pytest.mark.parametrize("hostile", [None, 42, True, "CAROUSEL", [], {}, ["carousel"]])
def test_normalizers_coerce_hostile_values_without_raising(hostile):
    norm = TabsElement.normalize_labels_and_ids(
        {"display": hostile, "label_pos": hostile}
    )
    assert norm["display"] == "tabs"
    assert norm["label_pos"] == "above"


def test_the_membership_collections_accept_an_unhashable_probe():
    """⚠️ This — NOT the hostile-value test above — is the guard for the
    tuple-not-frozenset decision. `_coerce_enum` is
    `isinstance(value, str) and value in allowed`, and `and` SHORT-CIRCUITS: for `[]`
    the membership test is never evaluated, so swapping the tuple for a frozenset
    leaves that test green. Only a direct membership probe observes the collection's
    type."""
    assert [] not in TabsElement.DISPLAYS  # TypeError under a frozenset
    assert {} not in TabsElement.LABEL_POSITIONS


@pytest.mark.parametrize("display", ["tabs", "carousel"])
@pytest.mark.parametrize("pos", ["above", "below", "hidden"])
def test_every_enum_member_round_trips(display, pos):
    norm = TabsElement.normalize_labels_and_ids({"display": display, "label_pos": pos})
    assert (norm["display"], norm["label_pos"]) == (display, pos)


def test_normalize_data_carries_the_keys_through_padding_and_truncation():
    padded = TabsElement.normalize_data(
        {"tabs": [], "display": "carousel", "label_pos": "below"}
    )
    assert len(padded["tabs"]) == TabsElement.MIN_TABS
    assert padded["display"] == "carousel"
    assert padded["label_pos"] == "below"

    over = [
        {"id": f"t{i:06x}", "label": f"T{i}"} for i in range(TabsElement.MAX_TABS + 3)
    ]
    truncated = TabsElement.normalize_data(
        {"tabs": over, "display": "carousel", "label_pos": "hidden"}
    )
    assert len(truncated["tabs"]) == TabsElement.MAX_TABS
    assert truncated["display"] == "carousel"
    assert truncated["label_pos"] == "hidden"


@pytest.mark.django_db
def test_save_round_trip_preserves_both_keys():
    """THE critical one. save() calls normalize_labels_and_ids and assigns its return
    to self.data, so a key missing from that literal is silently dropped on write."""
    obj = TabsElement.objects.create(
        data={**TabsElement.default_data(), "display": "carousel", "label_pos": "below"}
    )
    obj.refresh_from_db()
    assert obj.data["display"] == "carousel"
    assert obj.data["label_pos"] == "below"


def test_default_data_is_self_describing():
    d = TabsElement.default_data()
    assert d["display"] == "tabs"
    assert d["label_pos"] == "above"


@pytest.mark.django_db
def test_display_settings_agrees_with_the_normalizer_on_hostile_input():
    """One _coerce_enum helper, three call sites — they must not drift."""
    for hostile in (None, 42, "CAROUSEL", [], {}):
        obj = TabsElement(data={"tabs": [], "display": hostile, "label_pos": hostile})
        norm = TabsElement.normalize_labels_and_ids(obj.data)
        assert obj.display_settings() == {
            "display": norm["display"],
            "label_pos": norm["label_pos"],
        }
