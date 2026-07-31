"""Two products of one imported HTML fragment: its key form and its coloured form.

strip_spans(html)  -- the fragment with EVERY <span> unwrapped. The pre-slice-1
                      sanitiser did exactly this (span was never in ALLOWED_TAGS),
                      so it is the input the KEY replay needs. Unwrapping only
                      COLOURED spans would replay to `<span class="">...` while the
                      DB holds the fully-unwrapped value -- a silent zero-match.

colourise(html)    -- the fragment with every PALETTE colour turned into a tc-*
                      class on a LEGAL carrier, every other inline colour dropped,
                      and every span that did not earn a tc-* class unwrapped.

The carrier rule is the part a naive implementation gets wrong. 142 of the 588
palette-coloured elements sit on a tag other than `span`; a span-only colouriser
leaves <strong style="color:red"> untouched, the sanitiser strips `style`, and the
written value comes out BYTE-IDENTICAL TO THE KEY -- a silent no-op that the
acceptance gate would score as success were it not for its `value != key` clause.

Serialisation goes through decode_contents(), never str(Tag): this repo has a
recorded trap where str(Tag) re-escapes entities while str(NavigableString) decodes
them. One entity difference in one span silently zeroes that key with no error.
"""

from bs4 import BeautifulSoup

from courses.colour import TC_CLASS_TAGS
from courses.colour import slot_for_style


def soup(html):
    """Parse one fragment. Public because regions.py parses the same way, and a
    cross-module reach for an underscore-private name is the kind of coupling that
    goes unnoticed until someone renames it."""
    return BeautifulSoup(html or "", "html.parser")


def strip_spans(html):
    """The fragment with every <span> unwrapped, children kept."""
    parsed = soup(html)
    for span in parsed.find_all("span"):
        span.unwrap()
    return parsed.decode_contents()


def has_palette_colour(html):
    """True when at least one element carries a colour this palette can restore."""
    return any(
        slot_for_style(tag.get("style")) for tag in soup(html).find_all(style=True)
    )


def roundtrip_is_lossless(html):
    """True when parsing and re-serialising returns the source byte-for-byte.

    MEASURED over the whole corpus: 0 of 319 colour-bearing values differ. The
    guard stays because a future corpus change that broke it would otherwise
    corrupt content silently instead of being skipped and reported.
    """
    return soup(html).decode_contents() == (html or "")


def _add_colour_class(tag, slot):
    classes = [c for c in (tag.get("class") or []) if not c.startswith("tc-")]
    classes.append(f"tc-{slot}")
    tag["class"] = classes


def colourise(html):
    """(coloured_html, tc_classes_emitted). See the module docstring."""
    parsed = soup(html)
    emitted = 0
    # find_all materialises the list before any mutation, so wrapping a block
    # carrier's children cannot disturb the iteration -- a nested coloured span
    # is still visited afterwards, at its new depth.
    for tag in parsed.find_all(style=True):
        slot = slot_for_style(tag.get("style"))
        # Both sanitisers strip `style` wholesale (it is in neither
        # ALLOWED_ATTRIBUTES nor sanitize_cell's empty attribute map), so no
        # other declaration on this attribute could have survived anyway.
        del tag["style"]
        if slot is None:
            # Unmapped colour, or a style carrying no colour at all. Dropped, not
            # restored: D1's palette is four slots and the rest are accepted losses.
            continue
        if tag.name.lower() in TC_CLASS_TAGS:
            _add_colour_class(tag, slot)
        else:
            # p / li / figcaption ...: the sanitiser strips tc-* from a tag outside
            # TC_CLASS_TAGS (and strips figcaption entirely), so the colour moves
            # onto a NEW span wrapping the children. Mirrors the editor's
            # "never leave tc-* on a tag outside TC_CLASS_TAGS" rule.
            wrapper = parsed.new_tag("span")
            wrapper["class"] = [f"tc-{slot}"]
            for child in list(tag.contents):
                wrapper.append(child.extract())
            tag.append(wrapper)
        emitted += 1
    for span in parsed.find_all("span"):
        if not any(c.startswith("tc-") for c in (span.get("class") or [])):
            span.unwrap()
    return parsed.decode_contents(), emitted
