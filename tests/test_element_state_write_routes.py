"""Guard: the set of code paths that WRITE UnitProgress.element_state.

courses.state.stateful_element_model_names() enumerates the element types whose
practice state can be cleared from the unit page, and it is derived from exactly two
write routes (state.VALIDATORS and QuestionElement.RESTORABLE_IN_LESSON). A THIRD
route would ship a state-bearing type with no reset affordance -- silently.

This counts WRITES, not save_element_state() calls, because a direct write is the
house style here: progress_reset does `rows.update(element_state={})`, and migration
0050 did `up.element_state = ...`. A third route of that shape would never touch the
helper.
"""

import re
from pathlib import Path

from django.apps import apps

ROOT = Path(__file__).resolve().parent.parent

# Keyed on the surrounding OPERATION, because the confounders are textually adjacent:
# `rows.update(element_state={})` is a write but `rows.exclude(element_state={})` is a
# read, and any token keyed on `element_state=` alone matches both.
WRITE = re.compile(
    r"\.update\(\s*element_state=|element_state\.pop\(|element_state\[[^\]]*\]\s*="
    r"|\.element_state\s*=(?!=)"
)

# BLIND SPOTS, stated honestly: this catches .update(), .pop(), subscript assignment
# and attribute assignment. It does NOT catch setattr(), .bulk_update(), an
# F-expression, or a write spelled through a local alias. A tripwire, not a proof.

EXPECTED_WRITE_FILES = {"courses/views.py"}
# views.py only: progress_reset's update, plus the helper's pop and subscript assign.
EXPECTED_WRITE_COUNT = 3


def _first_party_roots():
    """Every in-tree Python root: the 9 first-party apps, plus config/,
    scripts/ and manage.py.

    Filters app configs by `path.parent == ROOT` -- NOT "path is under ROOT". The
    virtualenv lives INSIDE the checkout (.venv/), so "under ROOT" keeps every
    third-party app config and drags site-packages into the walk.
    """
    roots = []
    for cfg in apps.get_app_configs():
        path = Path(cfg.path).resolve()
        if path.parent != ROOT:
            continue
        if any(p in {".venv", "site-packages", "node_modules"} for p in path.parts):
            continue
        roots.append(path)
    return roots


def _source_files():
    for root in _first_party_roots() + [ROOT / "config", ROOT / "scripts"]:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if "migrations" in parts or "tests" in parts:
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            yield path
    yield ROOT / "manage.py"


def test_the_first_party_app_set_is_what_we_think_it_is():
    # If a tenth app ships, this guard must be re-read rather than silently skipping it.
    assert {p.name for p in _first_party_roots()} == {
        "core",
        "accounts",
        "institution",
        "courses",
        "grouping",
        "notes",
        "notifications",
        "tags",
        "integrations",
        "support",
    }


def test_element_state_write_routes_are_unchanged():
    hits = []
    for path in _source_files():
        for _ in WRITE.finditer(path.read_text(encoding="utf-8")):
            # as_posix(): this is a Windows box, so str() yields backslashes and the
            # comparison would fail for a reason unrelated to the invariant.
            hits.append(path.relative_to(ROOT).as_posix())

    assert len(hits) == EXPECTED_WRITE_COUNT and set(hits) == EXPECTED_WRITE_FILES, (
        f"element_state write routes changed: found {len(hits)} in "
        f"{sorted(set(hits))}, expected {EXPECTED_WRITE_COUNT} in "
        f"{sorted(EXPECTED_WRITE_FILES)}. A NEW WRITE ROUTE into "
        "UnitProgress.element_state must extend "
        "courses.state.stateful_element_model_names() in lockstep -- else whatever "
        "it persists becomes unresettable from the unit page. Read that contract "
        "before bumping this number."
    )
