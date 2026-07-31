"""Walk the parser output and build the key -> coloured-value map.

Two stages with different filters, and conflating them is a real source of
confusion. `walk_source` emits one Occurrence per non-empty (json_file, field_path)
registry field -- ALL of them, colour or not. `build_key_map` is what applies the
palette filter: an occurrence carrying no palette colour produces no key and is not
counted, because there is nothing to restore and rewriting the field merely to strip
a gray span would touch content for no gain.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from courses.recolour.colouriser import has_palette_colour
from courses.recolour.colouriser import roundtrip_is_lossless
from courses.recolour.regions import region_verdict
from courses.recolour.replay import SHAPE_CELL
from courses.recolour.replay import SHAPE_COMPOSED
from courses.recolour.replay import SHAPE_HTML
from courses.recolour.replay import SHAPE_STEM
from courses.recolour.replay import key_for
from courses.recolour.replay import value_for

SKIP_REGION = "protected-region"
SKIP_CONFLICT = "conflicting-colouring"
SKIP_UNCHANGED = "value-equals-key"
SKIP_FIDELITY = "bs4-round-trip-lossy"

# Files under a part directory that are not unit payloads. flags.json is a JSON
# LIST, so a walk that does not skip it dies with
# `AttributeError: 'list' object has no attribute 'get'`.
#
# PUBLIC (no leading underscore) because the management command imports it to
# validate --json-dir. Same rule as colouriser.soup(): a cross-module reach for an
# underscore-private name is coupling nobody notices until someone renames it.
NOT_UNIT_JSON = {"manifest.json", "flags.json"}


class Occurrence(NamedTuple):
    part: str
    json_file: str
    field_path: str
    shape: str
    raw: str


class KeyMap(NamedTuple):
    entries: dict  # key -> coloured value
    produced: list  # [(Occurrence, key)] for the keys that survived into entries
    producers: int  # occurrences carrying palette colour (the gate's DENOMINATOR)
    emitted: int  # tc-* classes across DISTINCT keys (what the map would write)
    emitted_occurrences: int  # tc-* classes across ALL producing occurrences
    skips: list  # [(Occurrence, reason)]
    per_part: dict  # part -> {"producers": int, "emitted": int}


# TWO emitted counts, because they answer different questions and the spec's
# source-side expectation is stated per OCCURRENCE. MEASURED on the real corpus with
# the two parts excluded: emitted (distinct keys) = 500, emitted_occurrences = 557.
# The spec predicts 588 palette elements minus the 29 in the excluded parts = 559,
# and the residual 2 are the SwitchGrid line stems, which are out of backfill scope.
# Comparing the distinct-key figure against a per-occurrence expectation is what
# makes the span-only-colouriser diagnostic in Task 8 give no verdict at all.


# The denominator deliberately counts EVERY palette-bearing occurrence, including
# the ones later refused for a protected region or a conflicting colouring. A
# refusal is a real shortfall in delivered colour and should drag the rate down
# where an operator sees it, not be quietly excluded from the arithmetic.


def _emit(out, part, jf, path, shape, raw):
    if isinstance(raw, str) and raw:
        out.append(Occurrence(part, jf, path, shape, raw))


def _walk_element(el, out, part, jf, path):
    if not isinstance(el, dict):
        return
    if el.get("flagged"):
        # builders.py:76 tests `flagged` BEFORE any type dispatch and stores el["raw"]
        # into HtmlElement.html, which is explicitly NOT sanitised (models.py:662).
        # So a flagged element's colour was never lost and there is nothing to restore
        # -- and emitting an occurrence for one would produce a key that can never
        # match, surfacing only as an unattributable dip in the gate rate. MEASURED:
        # the corpus holds exactly ONE flagged element, of type `html`, so this is
        # inert today; it is closed for the same reason the other never-executing
        # branches here are.
        return
    etype = el.get("type")
    # Mirrors builders.py's TYPE DISPATCH (not its flagged branch, handled above).
    # `explanation` is absent
    # because no builder branch writes one; SwitchGridElement.lines[*].stem and
    # Choice.text/feedback are absent because they are out of backfill scope.
    if etype in ("text", "spoiler"):
        _emit(out, part, jf, f"{path}.body", SHAPE_HTML, el.get("body"))
    if etype in ("choice", "numeric", "shorttext"):
        _emit(out, part, jf, f"{path}.stem", SHAPE_HTML, el.get("stem"))
    if etype in ("fill_gate", "switch_gate", "guess_number"):
        _emit(out, part, jf, f"{path}.stem", SHAPE_STEM, el.get("stem"))
    if etype == "guess_number":
        _emit(
            out,
            part,
            jf,
            f"{path}.success_message",
            SHAPE_HTML,
            el.get("success_message"),
        )
    if etype == "fillblank":
        _emit(out, part, jf, f"{path}.stem", SHAPE_COMPOSED, el.get("stem"))
    if etype in ("table", "fill_table"):
        data = el.get("data")
        if isinstance(data, dict):
            for r, row in enumerate(data.get("cells") or []):
                if not isinstance(row, list):
                    continue
                for c, cell in enumerate(row):
                    if isinstance(cell, dict):
                        _emit(
                            out,
                            part,
                            jf,
                            f"{path}.data.cells[{r}][{c}].html",
                            SHAPE_CELL,
                            cell.get("html"),
                        )
    for i, child in enumerate(el.get("elements") or []):
        _walk_element(child, out, part, jf, f"{path}.elements[{i}]")
    for t, tab in enumerate(el.get("tabs") or []):
        if isinstance(tab, dict):
            for i, child in enumerate(tab.get("elements") or []):
                _walk_element(child, out, part, jf, f"{path}.tabs[{t}].elements[{i}]")


def walk_source(json_dir, excluded_dirs):
    """Every field occurrence in every eligible part, in a stable order."""
    excluded = set(excluded_dirs or ())
    out = []
    for jf in sorted(Path(json_dir).glob("*/*.json")):
        if jf.name in NOT_UNIT_JSON or jf.parent.name in excluded:
            continue
        payload = json.loads(jf.read_text("utf-8"))
        if not isinstance(payload, dict):
            continue
        for i, el in enumerate(payload.get("elements") or []):
            _walk_element(el, out, jf.parent.name, str(jf), f"elements[{i}]")
    return out


def build_key_map(occurrences):
    """The key -> value map, plus everything the report and the gate need."""
    entries = {}
    produced = []
    origin = {}  # key -> the first Occurrence that produced it
    refused = set()  # keys retracted for a conflict -- NEVER re-enter the map
    emitted_by_key = {}  # key -> tc-* classes it contributed, for exact retraction
    occ_emitted_by_key = {}  # key -> tc-* classes across EVERY agreeing occurrence
    # so far (not just the origin's), for exact retraction of emitted_occurrences
    skips = []
    producers = 0
    emitted = 0
    emitted_occurrences = 0
    per_part = defaultdict(lambda: {"producers": 0, "emitted": 0})

    for occ in occurrences:
        if not has_palette_colour(occ.raw):
            continue
        producers += 1
        per_part[occ.part]["producers"] += 1
        if not roundtrip_is_lossless(occ.raw):
            skips.append((occ, SKIP_FIDELITY))
            continue
        refusal = region_verdict(
            occ.raw, sentinel_tokens=occ.shape in (SHAPE_STEM, SHAPE_COMPOSED)
        )
        if refusal:
            skips.append((occ, f"{SKIP_REGION}: {refusal}"))
            continue
        key = key_for(occ.raw, occ.shape)
        if key in refused:
            # Stickiness matters: without it a THIRD occurrence carrying the
            # FIRST colouring silently re-inserts a key two occurrences already
            # disagreed about, and the conflict guard becomes a no-op on exactly
            # the shape it exists for. Corpus conflicts are 0 today, so the real
            # run would never expose this.
            skips.append((occ, SKIP_CONFLICT))
            continue
        value, n = value_for(occ.raw, occ.shape)
        if value == key:
            # A colouriser that delivered nothing. The gate's `value != key`
            # clause is what stops this scoring as a success.
            skips.append((occ, SKIP_UNCHANGED))
            continue
        if key in entries and entries[key] != value:
            # The one shape that could colour something WRONG. Refuse both, and
            # retract the entry AND the earlier occurrence's claim on it.
            n_first = emitted_by_key.pop(key, 0)
            skips.append((occ, SKIP_CONFLICT))
            skips.append((origin[key], SKIP_CONFLICT))
            del entries[key]
            refused.add(key)
            produced[:] = [p for p in produced if p[1] != key]
            # Undo the retracted entry's contribution to the tc-* counters. Task 8
            # Step 5 reads `tc-* classes (occurrences)` against ~559 to detect a
            # span-only colouriser, so leaving classes in that will never be written
            # feeds a wrong number into a live diagnostic. Corpus conflicts are 0, so
            # this is inert today -- closed for the same reason as the other
            # never-executing branches in this module.
            # `emitted` and `per_part[...]["emitted"]` are per-KEY, so n_first (the
            # origin occurrence's contribution) is the whole thing to undo. But
            # `emitted_occurrences` was incremented once per AGREEING occurrence, not
            # just the origin's, so subtracting n_first alone strands any occurrence
            # that agreed with the origin before this conflict arrived. Subtract the
            # accumulated per-key occurrence total instead. This occurrence's own `n`
            # was never added to it: `occ_emitted_by_key[key] = ...` sits below the
            # `continue`, so the conflicting occurrence's own contribution is not in
            # the popped total.
            emitted -= n_first
            emitted_occurrences -= occ_emitted_by_key.pop(key, 0)
            per_part[origin[key].part]["emitted"] -= n_first
            continue
        produced.append((occ, key))
        emitted_occurrences += n
        occ_emitted_by_key[key] = occ_emitted_by_key.get(key, 0) + n
        if key in entries:
            # Same colouring twice -- 0 conflicts measured on the corpus. Both
            # occurrences count towards the numerator, so both are in `produced`.
            # (Post-exclusion: 227 distinct keys across 265 occurrences.)
            continue
        entries[key] = value
        origin[key] = occ
        emitted_by_key[key] = n  # so a later retraction can undo exactly this much
        emitted += n
        per_part[occ.part]["emitted"] += n

    return KeyMap(
        entries,
        produced,
        producers,
        emitted,
        emitted_occurrences,
        skips,
        dict(per_part),
    )
