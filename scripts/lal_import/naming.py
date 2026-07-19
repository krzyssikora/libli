"""Human-facing title placeholders derived from filenames/headings.

Diacritics are NOT guessed here — the parser emits an ASCII-folded placeholder and
the Phase-1 reading pass restores Polish diacritics in the manifest by hand.
"""

import re

_LEADING_TOKEN = re.compile(r"^\d+[_-]?")


def deslug(stem):
    """Strip a leading numeric token, then turn separators into spaces."""
    stem = _LEADING_TOKEN.sub("", stem)
    return re.sub(r"[_-]+", " ", stem).strip()


def _stem(source_html):
    return source_html[:-5] if source_html.endswith(".html") else source_html


def part_title_placeholder(folder):
    return deslug(folder)


def lesson_title(soup, source_html):
    h2 = soup.find("h2")
    if h2 is not None and h2.get_text(strip=True):
        return h2.get_text(strip=True)
    return deslug(_stem(source_html))


def quiz_title(source_html):
    return deslug(_stem(source_html))
