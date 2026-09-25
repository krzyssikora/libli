"""The correct-answer copy's HTML post-pass (spec 2026-09-25 §2.2).

The answer controls are built in Python with hard-coded names (fillblank
render_inputs -> name="blank", dnd -> name="slot", grids -> name="row_<pk>"), so no
builder changes: this ONE pass neutralises the second render instead. It runs on
the rendered controls include only -- never on the form, buttons or feedback box.

html.parser + decode_contents(): a NavigableString decodes entities and a Tag
re-escapes them, so serialising the soup's CONTENTS round-trips author LaTeX such
as \\(a&lt;b\\) unchanged (the known bs4 trap).
"""

from bs4 import BeautifulSoup

KEY_SUFFIX = "-key"
_REF_ATTRS = ("for", "aria-labelledby", "aria-describedby", "aria-controls")
_EMBEDS = ("iframe", "embed", "object")
_CONTROLS = ("input", "select", "textarea")


def neutralise_key_copy(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_EMBEDS):
        tag.decompose()  # a second GeoGebra applet is heavy and pointless
    ids = set()
    for tag in soup.find_all(id=True):
        ids.add(tag["id"])
        tag["id"] = tag["id"] + KEY_SUFFIX
    for attr in _REF_ATTRS:
        for tag in soup.find_all(attrs={attr: True}):
            # Rewrite a reference only when its target is inside this copy; one
            # pointing outside (e.g. a stem hint) stays as it is.
            tag[attr] = " ".join(
                ref + KEY_SUFFIX if ref in ids else ref
                for ref in str(tag[attr]).split()
            )
    for tag in soup.find_all(_CONTROLS):
        name = tag.attrs.pop("name", None)
        if tag.name == "select" and name == "slot":
            tag["data-slot"] = ""
        tag["disabled"] = ""
    return soup.decode_contents()
