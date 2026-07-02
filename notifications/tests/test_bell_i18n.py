from django.utils.translation import gettext
from django.utils.translation import override


def test_new_bell_strings_have_polish():
    with override("pl"):
        assert gettext("See all") == "Zobacz wszystkie"
        assert (
            gettext("You have no notifications yet.")
            == "Nie masz jeszcze żadnych powiadomień."
        )
        assert gettext("%(time)s ago") % {"time": "5 minut"} == "5 minut temu"
