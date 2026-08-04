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

    FROZEN: `courses/migrations/0053_spoiler_body_cleanup.py` depends on this
    exact behaviour and will run in environments (e.g. the mat-pp production
    cutover) that have not applied it yet. A migration that runs later must see
    the same classification it was reviewed against, so this function must not
    be broadened or narrowed after the fact -- add a new function instead of
    changing this one, even for a future callout/table cleanup.
    """
    text = html.unescape(_TAG.sub("", body or ""))
    # str.strip() with no argument removes U+00A0 too: ' '.isspace() is True in
    # Python 3. No explicit nbsp pass is needed.
    return text.strip() == ""
