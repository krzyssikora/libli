import pytest
from django.utils import translation

# Exact msgids introduced by the view toggle (Task 1). Keep character-for-character
# in sync with the {% trans %} strings in editor.html.
VIEW_TOGGLE_MSGIDS = [
    "View",
    "Editor view",
    "Editor",
    "Split",
    "Preview",
]


@pytest.mark.parametrize("msgid", VIEW_TOGGLE_MSGIDS)
def test_view_toggle_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        out = translation.gettext(msgid)
    assert out and out != msgid, f"view-toggle msgid not translated to PL: {msgid!r}"
