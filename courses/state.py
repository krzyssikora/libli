"""Per-student practice state: the validator registry and its contract.

A pure module (no views, no writes) mirroring courses/quiz.py. Each participating
element type registers a validator that normalizes ITS OWN blob on save; the
storage layer never interprets a blob.

The contract -- validate(element, obj, payload) -> dict | EMPTY | REJECT:

  dict    STORE this (normalized) blob under the element's key.
  EMPTY   DELETE the key. The student asserted "nothing here" (all items unticked).
  REJECT  LEAVE the stored key untouched. The payload was malformed.

EMPTY and REJECT are OPPOSITE outcomes and are deliberately distinct truthy
sentinels: collapsing both into None/{}/False makes a malformed blob wipe the
student's prior good state -- a silent data-loss bug no 500 or log would reveal.

Validators check SHAPE and REFERENTIAL VALIDITY only; they never re-verify
correctness. Practice state is ungraded, absent from analytics, and the DOM is
already client-forgeable; the *_check endpoints remain the real check path.
"""

import logging

logger = logging.getLogger(__name__)


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name


EMPTY = _Sentinel("EMPTY")
REJECT = _Sentinel("REJECT")


def _int_or_none(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _val_markdone(element, obj, payload):
    """{"items": [MarkDoneItem.pk, ...]} -- intersected with THIS element's items."""
    if not isinstance(payload, dict):
        return REJECT
    raw = payload.get("items")
    if not isinstance(raw, list):
        return REJECT
    incoming = {p for p in (_int_or_none(x) for x in raw) if p is not None}
    valid = set(obj.items.values_list("pk", flat=True))
    checked = sorted(incoming & valid)
    return {"items": checked} if checked else EMPTY


def _val_open_gate(element, obj, payload):
    """{"open": True} -- monotone. Shared by every answered/clicked reveal gate
    (plain, fill, switch): a correct answer or a click is the whole gesture, and
    the blob has exactly one reachable value.

    A false/absent `open` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT (which would preserve a stale key on a well-formed request).
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"open": True} if payload.get("open") else EMPTY


def _val_done(element, obj, payload):
    """{"done": True} -- monotone. A graded self-check (switch grid / fill-in table /
    guess-the-number) that has been answered fully correctly. The whole gesture has one
    reachable value; the completed answer is NOT stored -- it is rendered server-side
    from the element's own answers, gated on this flag.

    A false/absent `done` is a well-formed "nothing to restore" -> EMPTY (drop the key),
    never REJECT.
    """
    if not isinstance(payload, dict):
        return REJECT
    return {"done": True} if payload.get("done") else EMPTY


def _val_stepper(element, obj, payload):
    """{"shown": N} -- how many steps the student has walked open (step 0 is always
    visible, so a fresh stepper is N=1). The FIRST count-valued blob in the registry.

    Clamped to obj.steps.count() so a later author edit that removes steps self-heals
    (a too-large stored N -> all steps shown). N<2 is a well-formed "nothing to restore"
    (only step 0, which is the default render) -> EMPTY, never REJECT. Writes are
    order-sensitive (a count, not the gates' idempotent flag); the race is accepted at
    human click cadence -- see the spec.
    """
    if not isinstance(payload, dict):
        return REJECT
    n = _int_or_none(payload.get("shown"))
    if n is None:
        return REJECT
    n = min(n, obj.steps.count())
    return {"shown": n} if n >= 2 else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# and NOT the transfer key. Those three namespaces have been a recurring trap; the
# registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
    "revealgateelement": _val_open_gate,
    "fillgateelement": _val_open_gate,
    "switchgateelement": _val_open_gate,
    "switchgridelement": _val_done,
    "filltableelement": _val_done,
    "guessnumberelement": _val_done,
    "stepperelement": _val_stepper,
}


def validate_state(element, obj, payload):
    """Dispatch to the per-type validator. Unknown type or any exception -> REJECT."""
    fn = VALIDATORS.get(element.content_type.model)
    if fn is None:
        return REJECT
    try:
        return fn(element, obj, payload)
    except Exception:
        logger.exception("state validator failed for %s", element.content_type.model)
        return REJECT
