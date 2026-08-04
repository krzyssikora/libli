"""Helpers a data migration can import without touching live model classes."""

import html
import re

_TAG = re.compile(r"<[^>]*>")


def body_is_empty_ish(body):
    """True when a rich-text body carries no visible content.

    strip tags -> unescape entities -> strip whitespace. `str.strip()` with no
    argument removes U+00A0 too ('\xa0'.isspace() is True), so no explicit nbsp
    pass is needed. Must catch
    `<br>`, `<p><br></p>`, `<div>&nbsp;</div>` and a decoded-nbsp body: both `div`
    and `p` are in ALLOWED_TAGS, and the RTE's normal empty output is `<p><br></p>`,
    not a bare `<br>`.
    """
    text = html.unescape(_TAG.sub("", body or ""))
    # str.strip() with no argument removes U+00A0 too: ' '.isspace() is True in
    # Python 3. No explicit nbsp pass is needed.
    return text.strip() == ""
