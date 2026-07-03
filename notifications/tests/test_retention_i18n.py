from django.utils.translation import gettext
from django.utils.translation import override

from notifications.retention import format_purge_result


def test_purge_message_translated_and_interpolates_pl():
    with override("pl"):
        msg = format_purge_result({"read_aged": 3, "orphaned": 1}, dry_run=False)
    assert "3" in msg and "1" in msg
    assert "read:" not in msg  # the label itself is translated, not left English


def test_retention_strings_have_polish():
    with override("pl"):
        assert gettext("Save retention settings") == "Zapisz ustawienia przechowywania"
        assert (
            gettext("Purge old notifications now")
            == "Wyczyść stare powiadomienia teraz"
        )
