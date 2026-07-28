"""Which tree scopes are open, for one request.

The builder renders a child <ol> only for nodes in this set (spec section 1),
so this module is the single authority for the precedence rules in spec
section 2. It is deliberately free of view imports: everything it needs
arrives as arguments.
"""

from dataclasses import dataclass

from courses.models import ContentNode

CEILING = 500  # max open scopes after resolution; also bounds `open=all`
SIZE_THRESHOLD = 150  # courses at or under this open fully on a bare page load
SESSION_SLUG_LIMIT = 20  # per-key slug bound for the session dicts
SESSION_OPEN_LIMIT = 60  # per-slug pk budget for the no-JS carrier

LAST_NODE_KEY = "builder_last_node"
OPEN_KEY = "builder_open"


@dataclass(frozen=True)
class OpenSet:
    """`ids` is a frozenset so `frozen=True` actually protects it: frozen blocks
    attribute rebinding but not mutation of a mutable field, and a plain set
    would also make the generated __hash__ raise."""

    ids: frozenset[int]
    truncated: bool = False
    explicit: bool = False  # resolved by step 1 or 2 -> safe to persist


def nodes_by_pk(cmap):
    """pk -> node, over every node in the course.

    NOT `cmap` itself: _children_map only creates a KEY for a parent that has
    children, so `pk in cmap` silently discards every childless container.
    """
    return {n.pk: n for kids in cmap.values() for n in kids}


def container_pks(cmap):
    """Every non-unit pk. A unit owns no scope, so it can never be 'open'."""
    return {
        pk for pk, n in nodes_by_pk(cmap).items() if n.kind != ContentNode.Kind.UNIT
    }


def _finalize(ids, containers, *, explicit=False):
    """Sanitise against this course's containers, then apply the one ceiling.

    Truncation keeps the LOWEST pks: a set has no truncation order, and the
    outcome has to be reproducible across runs for the guard test to mean
    anything.
    """
    kept = set(ids) & containers
    if len(kept) > CEILING:
        return OpenSet(frozenset(sorted(kept)[:CEILING]), True, explicit)
    return OpenSet(frozenset(kept), False, explicit)


def _parse(raw, containers):
    if raw == "all":
        return set(containers)
    out = set()
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            out.add(int(token))
    return out


def _chain(pk, index):
    """Ancestor chain of `pk`, plus the node itself when it is a container.

    Including the node is why the ceiling is 4 scopes, not 3: otherwise an
    author returns to the course with the very chapter they were working in
    closed.
    """
    node = index.get(pk)
    if node is None:
        return set()
    out = set()
    if node.kind != ContentNode.Kind.UNIT:
        out.add(node.pk)
    cur = node.parent_id
    while cur is not None and cur in index:
        out.add(cur)
        cur = index[cur].parent_id
    return out


def _raw_open(request):
    """Presence, not truthiness. `.get()` returns "" for both absent and
    explicitly-empty, and "" is falsy -- which would re-seed from the session
    the moment the author collapses the last scope."""
    if "open" in request.POST:
        return request.POST["open"], True
    if "open" in request.GET:
        return request.GET["open"], True
    return "", False


_MISSING = object()


def _stored_open(request, slug):
    """Returns _MISSING when the key is absent, the (possibly EMPTY) list
    otherwise.

    `.get(slug) or []` would conflate the two, and stored-empty is meaningful:
    it is how "I collapsed everything" survives a no-JS mutation. Conflated,
    the tree springs back open and _remember_open then writes that derived set
    over the author's real one.
    """
    return request.session.get(OPEN_KEY, {}).get(slug, _MISSING)


def open_ids(request, course, cmap, *, mode="fragment", q_chain=None):
    """Resolve the open set. `mode` is one of "page" | "notice" | "fragment".

    Steps run per mode (spec section 2):
      page     -> 1, 2, 3, 4, 5, 6
      notice   -> 2, 3, 4, 5, 6 + a direct builder_open read
      fragment -> 2, 3, 6 only  (never touches the session; the size rule is a
                  LANDING rule for a page, not a rule about a re-render)

    `.explicit` on the result records whether step 1 or 2 resolved it, so
    _remember_open can persist ONLY author-chosen sets. Keying that off the
    raw presence of the parameter would persist the derived fall-through of
    `open=session`.
    """
    index = nodes_by_pk(cmap)
    containers = container_pks(cmap)  # one copy of the "a unit owns no scope" rule
    raw, present = _raw_open(request)

    # Step 1 -- the no-JS post-mutation sentinel, page mode only.
    if present and raw == "session" and mode == "page":
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            return _finalize(stored, containers, explicit=True)
        present = False  # missing/flushed -> fall through to 3-6

    # Step 2 -- an explicit value wins, including the empty string.
    if present:
        return _finalize(_parse(raw, containers), containers, explicit=True)

    # A no-JS conflict/validation re-render is the same author, same tab,
    # mid-loop -- it cannot be a bookmark, so reading the carrier is safe and
    # keeps a FAILED mutation showing the same tree as a successful one.
    if mode == "notice":
        stored = _stored_open(request, course.slug)
        if stored is not _MISSING:
            # explicit=False: safe to RENDER from, not safe to write back.
            # Marking it True would hand a future caller a wrong
            # "author chose this" signal.
            return _finalize(stored, containers, explicit=False)

    # Step 3 -- the filter's chains (slice 2; always None here).
    if q_chain is not None:
        return _finalize(q_chain, containers)

    if mode == "fragment":
        return _finalize(set(), containers)  # step 6

    # Step 4 -- small courses open fully, BEFORE the seed. Ordered the other
    # way round, node_panel stores a pk on the first click and from the
    # author's second visit a small course would arrive with only the chain.
    if len(index) <= SIZE_THRESHOLD:
        return _finalize(containers, containers)

    # Step 5 -- the last node this author touched, at most 4 scopes.
    last = request.session.get(LAST_NODE_KEY, {}).get(course.slug)
    if last is not None:
        chain = _chain(last, index)
        if chain:
            return _finalize(chain, containers)

    return _finalize(set(), containers)  # step 6
