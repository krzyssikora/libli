from scripts.lal_import.emit import is_fully_mapped
from scripts.lal_import.emit import seed_hash
from scripts.lal_import.emit import unit_payload


def test_fully_mapped_true_when_no_flag():
    assert is_fully_mapped([{"type": "text", "body": "x"}]) is True


def test_fully_mapped_false_with_flag():
    assert is_fully_mapped([{"type": "html", "flagged": True, "raw": "x"}]) is False


def test_seed_hash_excludes_self_and_fully_mapped():
    p = unit_payload([{"type": "text", "body": "x"}], [])
    # Adding/altering the excluded keys must NOT change the hash.
    p2 = dict(p)
    p2["seed_hash"] = "different"
    p2["fully_mapped"] = not p2["fully_mapped"]
    assert seed_hash(p) == seed_hash(p2)


def test_seed_hash_changes_with_payload():
    a = unit_payload([{"type": "text", "body": "x"}], [])
    b = unit_payload([{"type": "text", "body": "y"}], [])
    assert a["seed_hash"] != b["seed_hash"]


def test_payload_stamps_hash_and_flag():
    p = unit_payload([{"type": "text", "body": "x"}], [])
    assert p["fully_mapped"] is True
    assert p["seed_hash"] == seed_hash(p)


def test_flag_record_alone_marks_not_fully_mapped():
    # A warning-only flag (no flagged element) still forces fully_mapped=false.
    p = unit_payload(
        [{"type": "choice", "stem": "x", "multiple": True, "choices": []}],
        [{"kind": "unknown_hint", "reason": "…", "raw_excerpt": ""}],
    )
    assert p["fully_mapped"] is False
