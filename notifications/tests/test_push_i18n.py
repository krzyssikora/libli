"""Every new push msgid has a real Polish translation (no fuzzy, no empty)."""

import pytest
from django.utils import translation

NEW = {
    "Notifications": "Powiadomienia",
    "Choose which events email you and which send a push notification. "
    "The bell always shows everything.": (
        "Wybierz, o których zdarzeniach chcesz dostawać e-mail, a o których "
        "powiadomienie push. Dzwonek zawsze pokazuje wszystko."
    ),
    "Push notifications on this device": "Powiadomienia push na tym urządzeniu",
    "On a shared computer, log out when you finish.": (
        "Na wspólnym komputerze wyloguj się, gdy skończysz."
    ),
    "This browser can't show push notifications.": (
        "Ta przeglądarka nie obsługuje powiadomień push."
    ),
    "To get push notifications on this device, tick 'Remember me' when you log in.": (
        "Aby dostawać powiadomienia push na tym urządzeniu, zaznacz "
        "„Zapamiętaj mnie” przy logowaniu."
    ),
    "On iPhone and iPad, add libli to your Home Screen first.": (
        "Na iPhonie i iPadzie najpierw dodaj libli do ekranu początkowego."
    ),
    "How to install": "Jak zainstalować",
    "Notifications are blocked for libli in this browser's settings.": (
        "Powiadomienia z libli są zablokowane w ustawieniach tej przeglądarki."
    ),
    "Email": "E-mail",
    "Push": "Push",
    "When a quiz I submitted is graded.": "Gdy mój przesłany quiz zostanie oceniony.",
    "When I'm enrolled in a course.": "Gdy zostanę zapisany(-a) na kurs.",
    "When a student's quiz needs my review.": (
        "Gdy quiz ucznia wymaga mojego sprawdzenia."
    ),
    "Couldn't change push notifications. Try again.": (
        "Nie udało się zmienić powiadomień push. Spróbuj ponownie."
    ),
    "Get notifications on this device": "Otrzymuj powiadomienia na tym urządzeniu",
    "Turn on": "Włącz",
    "Dismiss": "Zamknij",
    "Email: %(label)s": "E-mail: %(label)s",
    "Push: %(label)s": "Push: %(label)s",
}


@pytest.mark.parametrize("msgid", sorted(NEW))
def test_polish_translation(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) == NEW[msgid]


@pytest.mark.parametrize("msgid", sorted(k for k, v in NEW.items() if k == v))
def test_identical_translations_are_really_filled(msgid):
    """gettext returns the msgid for an EMPTY msgstr, so for entries whose Polish
    equals the English the comparison above cannot fail; read the .po instead."""
    from pathlib import Path

    from django.conf import settings as dj_settings

    path = Path(dj_settings.BASE_DIR) / "locale/pl/LC_MESSAGES/django.po"
    po = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    entry = po.split(f'msgid "{msgid}"\n', 1)[1].split("\n\n", 1)[0]
    assert f'msgstr "{NEW[msgid]}"' in entry


@pytest.mark.django_db
def test_settings_and_bell_render_polish(client, settings):
    """Every server-rendered push line (state lines, help, bell row, error string)
    renders in Polish -- push.js only toggles them, so this is where pl is proven."""
    from django.urls import reverse

    from notifications.tests.push_helpers import logged_in_user
    from notifications.tests.push_helpers import push_settings

    push_settings(settings)
    logged_in_user(client, language="pl")
    url = reverse("core:user_settings")
    html = client.get(url, HTTP_ACCEPT_LANGUAGE="pl").content.decode()
    for msgid in (
        "This browser can't show push notifications.",
        "To get push notifications on this device, tick 'Remember me' when you log in.",
        "On iPhone and iPad, add libli to your Home Screen first.",
        "Notifications are blocked for libli in this browser's settings.",
        "On a shared computer, log out when you finish.",
        "Get notifications on this device",
        "Push notifications on this device",
        "Turn on",
        "How to install",
        "Push",
    ):
        assert NEW[msgid] in html, msgid
    assert f'aria-label="{NEW["Dismiss"]}"' in html
    # the error string travels in an attribute, HTML-escaped
    assert "Nie udało się zmienić powiadomień push" in html
