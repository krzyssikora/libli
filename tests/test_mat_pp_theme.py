import re
from pathlib import Path

import pytest

BASE = Path("courses/migrations/_mat_pp_baseline")
THEMED = (BASE / "html_css_themed.txt").read_text(encoding="utf-8")

# Every literal deliberately kept, matched by selector+declaration
# (context-scoped), each justified.
KEPT = [
    (".red_on_yellow", "color:red"),  # colour-demo utility: intent is the literal red
    (".red_on_yellow", "background-color:yellow"),
    (".blue_on_green", "color:blue"),
    (".blue_on_green", "background-color:rgb(130,200,130)"),
    (".magenta_on_gray", "color:magenta"),
    (".magenta_on_gray", "background-color:lightgray"),
    (".yellow_on_gray", "color:yellow"),
    (".yellow_on_gray", "background-color:lightgray"),
]

# Complete CSS named-colour set (CSS Color Module Level 4). Keep the full list.
NAMED_COLOURS = {
    "aliceblue",
    "antiquewhite",
    "aqua",
    "aquamarine",
    "azure",
    "beige",
    "bisque",
    "black",
    "blanchedalmond",
    "blue",
    "blueviolet",
    "brown",
    "burlywood",
    "cadetblue",
    "chartreuse",
    "chocolate",
    "coral",
    "cornflowerblue",
    "cornsilk",
    "crimson",
    "cyan",
    "darkblue",
    "darkcyan",
    "darkgoldenrod",
    "darkgray",
    "darkgreen",
    "darkgrey",
    "darkkhaki",
    "darkmagenta",
    "darkolivegreen",
    "darkorange",
    "darkorchid",
    "darkred",
    "darksalmon",
    "darkseagreen",
    "darkslateblue",
    "darkslategray",
    "darkslategrey",
    "darkturquoise",
    "darkviolet",
    "deeppink",
    "deepskyblue",
    "dimgray",
    "dimgrey",
    "dodgerblue",
    "firebrick",
    "floralwhite",
    "forestgreen",
    "fuchsia",
    "gainsboro",
    "ghostwhite",
    "gold",
    "goldenrod",
    "gray",
    "green",
    "greenyellow",
    "grey",
    "honeydew",
    "hotpink",
    "indianred",
    "indigo",
    "ivory",
    "khaki",
    "lavender",
    "lavenderblush",
    "lawngreen",
    "lemonchiffon",
    "lightblue",
    "lightcoral",
    "lightcyan",
    "lightgoldenrodyellow",
    "lightgray",
    "lightgreen",
    "lightgrey",
    "lightpink",
    "lightsalmon",
    "lightseagreen",
    "lightskyblue",
    "lightslategray",
    "lightslategrey",
    "lightsteelblue",
    "lightyellow",
    "lime",
    "limegreen",
    "linen",
    "magenta",
    "maroon",
    "mediumaquamarine",
    "mediumblue",
    "mediumorchid",
    "mediumpurple",
    "mediumseagreen",
    "mediumslateblue",
    "mediumspringgreen",
    "mediumturquoise",
    "mediumvioletred",
    "midnightblue",
    "mintcream",
    "mistyrose",
    "moccasin",
    "navajowhite",
    "navy",
    "oldlace",
    "olive",
    "olivedrab",
    "orange",
    "orangered",
    "orchid",
    "palegoldenrod",
    "palegreen",
    "paleturquoise",
    "palevioletred",
    "papayawhip",
    "peachpuff",
    "peru",
    "pink",
    "plum",
    "powderblue",
    "purple",
    "rebeccapurple",
    "red",
    "rosybrown",
    "royalblue",
    "saddlebrown",
    "salmon",
    "sandybrown",
    "seagreen",
    "seashell",
    "sienna",
    "silver",
    "skyblue",
    "slateblue",
    "slategray",
    "slategrey",
    "snow",
    "springgreen",
    "steelblue",
    "tan",
    "teal",
    "thistle",
    "tomato",
    "turquoise",
    "violet",
    "wheat",
    "white",
    "whitesmoke",
    "yellow",
    "yellowgreen",
}
NEUTRAL_KEYWORDS = {
    "transparent",
    "currentcolor",
    "inherit",
    "initial",
    "unset",
    "none",
}


def _declarations(css):
    """Yield (selector_context, name, value) for each declaration value."""
    # crude but sufficient: strip comments, split rule blocks
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        sel = m.group(1).strip()
        for decl in m.group(2).split(";"):
            if ":" in decl:
                name, _, val = decl.partition(":")
                yield sel, name.strip(), val.strip()


def _is_allowlisted(sel, name, val):
    decl = f"{name}:{val}".replace(" ", "")
    return any(
        a_sel in sel and a_decl.replace(" ", "") == decl for a_sel, a_decl in KEPT
    )


def test_no_residual_colour_literals():
    offenders = []
    for sel, name, val in _declarations(THEMED):
        if _is_allowlisted(sel, name, val):
            continue
        # Keep legitimately-kept, non-colour value content out of the scan: image
        # refs (url(icons/red.png)) and quoted strings (content:"...") can contain
        # colour words that are NOT colour literals. The plan keeps images/content
        # byte-for-byte, so strip them before matching.
        scan = re.sub(r"url\([^)]*\)", "", val)
        scan = re.sub(r"\"[^\"]*\"|'[^']*'", "", scan)
        # hex / rgb()
        if re.search(r"#[0-9a-fA-F]{3,8}\b", scan) or re.search(r"\brgba?\(", scan):
            offenders.append((sel, name, val))
            continue
        # named colours as COMPLETE value tokens only (never inside var(--...))
        for tok in re.findall(r"(?<![\w-])[a-zA-Z]+(?![\w-])", scan):
            low = tok.lower()
            if low in NEUTRAL_KEYWORDS:
                continue
            if low in NAMED_COLOURS:
                offenders.append((sel, name, val))
                break
    assert not offenders, f"residual colour literals: {offenders[:20]}"


def test_theme_adoption_preamble_present():
    assert (
        "html,body{background:var(--surface-raised);color:var(--text-primary)}"
        in THEMED.replace(" ", "").replace("\n", "")
        or "html,body{background:var(--surface-raised)" in THEMED
    )
    assert "color-scheme:dark" in THEMED
    assert (
        "var(--colour-light-blue" not in THEMED
        or "--colour-light-blue:var(--primary-subtle)" in THEMED.replace(" ", "")
    )


@pytest.mark.django_db
def test_migration_roundtrip_and_guarded_noop():
    import importlib

    from django.apps import apps as django_apps

    from courses.models import Course

    # leading-digit module name: importlib takes the dotted string, so it imports fine
    mig = importlib.import_module("courses.migrations.0031_mat_pp_theme_css")

    # embedded literals must equal the committed baseline files (no paste drift)
    assert mig.NEW_CSS == THEMED
    assert mig.OLD_CSS == (BASE / "html_css.txt").read_text(encoding="utf-8")

    # guarded no-op when the course is absent
    mig.forward(django_apps, None)  # must not raise

    c = Course.objects.create(
        title="M", slug="mat-pp", html_css=mig.OLD_CSS, html_js="x"
    )
    mig.forward(django_apps, None)
    c.refresh_from_db()
    assert (
        c.html_css == mig.NEW_CSS and c.html_js == "x"
    )  # forward applied, js untouched
    mig.reverse(django_apps, None)
    c.refresh_from_db()
    assert c.html_css == mig.OLD_CSS  # reverse restores baseline exactly
