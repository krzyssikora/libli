"""Title filtering for the builder tree, for one request.

Deliberately free of view imports and of the ORM: everything arrives as
arguments, so the whole module is unit-testable without a database. The
builder already loads the full children-map in one query; this module
selects matches from it in memory and walks `parent_id` upward, so the
filter adds no query (spec section 1).
"""

import unicodedata

MIN_QUERY = 2  # chars of the FOLDED query, after stripping -- see spec 1a
MATCH_CAP = 100  # matches kept, in (order, pk) order


def _build_fold_table():
    """Three sources, and all three are load-bearing (spec 1b).

    1. U+00C0-U+024F decomposed via NFKD, keeping entries whose stripped base
       is ASCII.
    2. `l` and `L` with stroke, which NFKD cannot reach -- U+0142 has NO
       decomposition, so a generic fold silently leaves every one in place
       and `laka` stops matching `Łąka`.
    3. The combining marks themselves, DELETED, so decomposed (NFD) input
       folds the same as precomposed. Titles imported from external HTML
       arrive NFD; without this, fold(NFD("k\u0105ty")) is "ka\u0328ty" --
       base `a` plus a DANGLING combining ogonek, NOT the precomposed
       "k\u0105ty" it renders identically to -- and an ASCII query misses
       that node with no symptom.
    """
    table = {}
    for cp in range(0x00C0, 0x0250):
        ch = chr(cp)
        base = "".join(
            c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)
        )
        if base != ch and base and base.isascii():
            table[cp] = base
    table[0x0142] = "l"
    table[0x0141] = "L"
    table.update({cp: None for cp in range(0x0300, 0x0370)})
    return str.maketrans(table)


_FOLD_TABLE = _build_fold_table()


def fold(s):
    """Case- and diacritic-insensitive form. `translate` BEFORE `casefold`
    so the table can carry both cases."""
    return s.translate(_FOLD_TABLE).casefold()


def is_active(q):
    """The floor test, alone -- needs no cmap.

    Its own function because one consumer runs where no tree exists: the
    reorder guard in node_move's `mode == "reorder"` branch fires before any
    children-map is loaded (spec 3m), so it can call neither filtered_map nor
    _filter_context. Re-testing the floor inline anywhere else is forbidden;
    this is the single copy.
    """
    return len(fold((q or "").strip())) >= MIN_QUERY


def _copy(cmap):
    """A NEW outer dict with NEW lists, always -- even on the blank path.

    Returning `cmap` itself would make the restricted and full maps the same
    object on the most common path, at which point effect 2's insertion
    (spec 3e) mutates the map _open_ids and _open_descendants read from in
    the same request.
    """
    return {parent: list(kids) for parent, kids in cmap.items()}


def filtered_map(cmap, q):
    """(restricted cmap, chain ids, shown, total, q_active).

    `chain_ids` is every matched CONTAINER plus every ancestor of every
    match -- the node itself included, or a matched chapter arrives collapsed
    and the row the author searched for is the one they cannot see.
    """
    if not is_active(q):
        return _copy(cmap), set(), 0, 0, False

    needle = fold(q.strip())
    index = {n.pk: n for kids in cmap.values() for n in kids}
    matches = [n for n in index.values() if needle in fold(n.title)]
    matches.sort(key=lambda n: (n.order, n.pk))
    total = len(matches)
    kept = matches[:MATCH_CAP]

    keep_pks = set()
    chains = set()
    for node in kept:
        keep_pks.add(node.pk)
        if node.kind != "unit":
            chains.add(node.pk)
        cur = node.parent_id
        while cur is not None and cur in index:
            keep_pks.add(cur)
            chains.add(cur)
            cur = index[cur].parent_id

    restricted = {}
    for parent, kids in cmap.items():
        rows = [n for n in kids if n.pk in keep_pks]
        if rows:
            restricted[parent] = rows
    return restricted, chains, len(kept), total, True
