"""Polish-aware collation for sorting names/text in true Polish alphabetical
order.

Python's default string sort compares Unicode codepoints, which mis-places the
Polish diacritic letters (ą ć ę ł ń ó ś ź ż): most sit *above* "z" in Unicode,
so e.g. "Łata" sorts after "Zych", and "Górski" sorts after "Grabski" (ó should
fall right after o, before r). This maps each letter to its position in the
Polish alphabet so a diacritic sorts immediately after its base letter.

Dependency-free and Polish-specific (the platform is EN/PL only). Characters
outside the Polish alphabet fall back to their codepoint, ranked after Polish
letters; whitespace ranks before letters so the space in a "Last First" sort key
orders a shorter surname ahead of a longer one that extends it.
"""

# The 32-letter Polish alphabet, in order (plus the foreign q/v/x that Polish
# dictionaries interleave at their Latin positions).
_PL_ALPHABET = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
_PL_INDEX = {ch: i for i, ch in enumerate(_PL_ALPHABET)}

# Rank buckets: whitespace/separators first, then Polish-ordered letters, then
# any other character by codepoint. Kept as small ints so keys compare cheaply.
_RANK_SPACE = 0
_RANK_LETTER = 1
_RANK_OTHER = 2


def polish_sort_key(text):
    """A case-insensitive sort key placing `text` in Polish alphabetical order.

    Use as ``sorted(names, key=polish_sort_key)`` (optionally paired with a
    stable tiebreaker, e.g. ``key=lambda u: (polish_sort_key(u.name), u.pk)``).
    """
    key = []
    for ch in text.casefold():
        idx = _PL_INDEX.get(ch)
        if idx is not None:
            key.append((_RANK_LETTER, idx))
        elif ch.isspace():
            key.append((_RANK_SPACE, 0))
        else:
            key.append((_RANK_OTHER, ord(ch)))
    return key
