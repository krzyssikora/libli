"""seed_hash canonicalization and the unit-payload shape."""

import hashlib
import json

_EXCLUDED = {"seed_hash", "fully_mapped"}


def is_fully_mapped(elements):
    return not any(e.get("flagged") for e in elements)


def seed_hash(payload):
    core = {k: v for k, v in payload.items() if k not in _EXCLUDED}
    canonical = json.dumps(
        core, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def unit_payload(elements, flags):
    payload = {
        "elements": elements,
        "fully_mapped": is_fully_mapped(elements) and not flags,
    }
    payload["seed_hash"] = seed_hash(payload)
    return payload
