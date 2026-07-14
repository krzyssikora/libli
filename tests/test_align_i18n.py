from django.utils import translation


def test_polish_alignment_strings():
    cases = {
        "Align left": "Wyrównaj do lewej",
        "Align center": "Wyśrodkuj",
        "Align right": "Wyrównaj do prawej",
    }
    with translation.override("pl"):
        for src, expected in cases.items():
            assert translation.gettext(src) == expected, src
