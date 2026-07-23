"""Whole-catalog health guards for the gettext .po files.

Owns every assertion about the catalogs AS FILES: no fuzzy entries, no obsolete
entries, and no untranslated Polish string. These previously existed as a
`test_po_catalog_clean` duplicated verbatim in tests/test_i18n_auth.py and
tests/test_i18n_notes.py -- two copies of one assertion about files belonging to
neither module. That orphaned ownership is why nobody ever extended them to
catch a blank msgstr, and a msgid once shipped untranslated as a result.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PL_PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"
EN_PO = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"

# Keyed by locale code, because both files are named "django.po" -- a failure
# message built from path.name could not tell you which catalog broke.
CATALOGS = {"pl": PL_PO, "en": EN_PO}

# Failure-message formatting, shared by all three guards: every one of them can
# have many offenders at once (a bad sweep reintroduces dozens).
MAX_MSGID_CHARS = 80
MAX_LISTED = 20

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _joined(lines):
    """The concatenated payload of one or more .po string lines.

    A .po value may be split across continuation lines, each its own quoted
    string; emptiness can only be judged after joining them."""
    return "".join(part for ln in lines for part in _QUOTED.findall(ln))


def _entries(path):
    """Parse a .po file into entries.

    Each entry is {msgid, msgstrs, fuzzy, obsolete, plural}. `msgstrs` holds one
    string for a singular entry and one per plural form for a plural entry, so
    emptiness is judged uniformly across both.

    Two deliberate decisions:

    * Obsolete (`#~`) entries are RETAINED and marked, never dropped.
      test_no_obsolete_entries must see them to flag them, while the
      untranslated scan filters them out. Dropping them here would leave the
      obsolete guard asserting over a list its own subject had been removed
      from -- passing vacuously.
    * The header entry (msgid "") is likewise retained, not skipped. msgmerge
      marks a stale HEADER `#, fuzzy`, and the assertion this file replaces
      (`"#, fuzzy" not in text`) would have caught that; skipping the header
      here would silently weaken the fuzzy guard. It is excluded from the
      untranslated scan only, by msgid emptiness.
    """
    text = path.read_text(encoding="utf-8")
    entries = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.splitlines()
        if not lines:
            continue
        fuzzy = any(re.match(r"#,.*\bfuzzy\b", ln) for ln in lines)
        obsolete = any(ln.startswith("#~") for ln in lines)
        # Strip the obsolete marker so one state machine handles both shapes,
        # and drop ordinary comment/flag/reference lines.
        body = []
        for ln in lines:
            if ln.startswith("#~"):
                body.append(ln[2:].lstrip())
            elif not ln.startswith("#"):
                body.append(ln)
        msgid_lines, msgstr_lines, plural, current = [], {}, False, None
        for ln in body:
            if ln.startswith("msgid_plural"):
                plural = True
                current = None  # the plural SOURCE text is not needed
            elif ln.startswith("msgid"):
                current = msgid_lines
                current.append(ln)
            elif ln.startswith("msgstr["):
                idx = int(ln[len("msgstr[") : ln.index("]")])
                current = msgstr_lines.setdefault(idx, [])
                current.append(ln)
            elif ln.startswith("msgstr"):
                current = msgstr_lines.setdefault(0, [])
                current.append(ln)
            elif ln.startswith('"') and current is not None:
                current.append(ln)
        if not msgid_lines:
            continue
        entries.append(
            {
                "msgid": _joined(msgid_lines),
                "msgstrs": [_joined(msgstr_lines[k]) for k in sorted(msgstr_lines)],
                "fuzzy": fuzzy,
                "obsolete": obsolete,
                "plural": plural,
            }
        )
    return entries


def _nplurals(path):
    """How many plural forms this catalog declares.

    Read from the Plural-Forms header rather than assumed: Polish declares 3 and
    English declares 2, so any hardcoded number is wrong for one of them."""
    m = re.search(r"nplurals\s*=\s*(\d+)", path.read_text(encoding="utf-8"))
    return int(m.group(1)) if m else 1


def _format_offenders(msgids):
    """A stable, bounded failure list, shared by all three guards."""
    shown = [
        (m[:MAX_MSGID_CHARS] + "…") if len(m) > MAX_MSGID_CHARS else m
        for m in msgids[:MAX_LISTED]
    ]
    out = "\n".join(f"  - {m!r}" for m in shown)
    if len(msgids) > MAX_LISTED:
        out += f"\n  … and {len(msgids) - MAX_LISTED} more"
    return out


def _untranslated(path):
    """Live entries whose translation is missing or partially missing."""
    required = _nplurals(path)
    bad = []
    for e in _entries(path):
        if e["obsolete"] or not e["msgid"]:
            continue  # obsolete entries and the header are not translations
        need = required if e["plural"] else 1
        if len(e["msgstrs"]) < need or any(not s for s in e["msgstrs"]):
            bad.append(e["msgid"])
    return bad


def test_no_fuzzy_entries():
    for locale, path in CATALOGS.items():
        bad = [e["msgid"] for e in _entries(path) if e["fuzzy"]]
        assert not bad, (
            f"locale/{locale}: fuzzy entries present — review and clear the flag:\n"
            + _format_offenders(bad)
        )


def test_no_obsolete_entries():
    for locale, path in CATALOGS.items():
        bad = [e["msgid"] for e in _entries(path) if e["obsolete"]]
        assert not bad, (
            f"locale/{locale}: obsolete entries present — delete them:\n"
            + _format_offenders(bad)
        )


def test_pl_has_no_untranslated_msgid():
    """Polish only, deliberately.

    English msgstrs are intentionally empty: gettext falls back to the msgid, so
    locale/en legitimately carries hundreds of blanks and a guard covering it
    would be permanently red. No test pins that count, and none should — it
    drifts with every string added or removed."""
    bad = _untranslated(PL_PO)
    assert not bad, (
        "untranslated Polish msgid(s) — add a msgstr for each:\n"
        + _format_offenders(bad)
    )


# --- falsification fixtures -------------------------------------------------
# Each scenario writes a synthetic .po to tmp_path. Nothing real is touched, so
# nothing needs reverting and nothing races a parallel xdist worker.

_HEADER = (
    'msgid ""\n'
    'msgstr ""\n'
    '"MIME-Version: 1.0\\n"\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    '"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : 1);\\n"\n'
)


def _po(tmp_path, body, name="django.po"):
    p = tmp_path / name
    p.write_text(_HEADER + "\n" + body, encoding="utf-8")
    return p


def test_untranslated_scan_flags_a_blank_msgstr(tmp_path):
    p = _po(tmp_path, 'msgid "Save"\nmsgstr ""\n')
    assert _untranslated(p) == ["Save"]


def test_untranslated_scan_flags_one_missing_plural_form(tmp_path):
    """The subtlest branch: forms 0 and 1 are filled, form 2 is not."""
    p = _po(
        tmp_path,
        'msgid "%d file"\n'
        'msgid_plural "%d files"\n'
        'msgstr[0] "%d plik"\n'
        'msgstr[1] "%d pliki"\n'
        'msgstr[2] ""\n',
    )
    assert _untranslated(p) == ["%d file"]


def test_untranslated_scan_ignores_an_obsolete_blank_entry(tmp_path):
    """The false-positive direction: an obsolete entry with an empty
    translation must NOT be reported as untranslated."""
    p = _po(tmp_path, '#~ msgid "Gone"\n#~ msgstr ""\n')
    assert _untranslated(p) == []


def test_untranslated_scan_never_reports_the_header(tmp_path):
    """The header (msgid "") must never reach the report.

    This scenario deliberately does NOT use the _po()/_HEADER helper. A real
    header carries metadata continuation lines, so its joined msgstr is
    NON-empty -- which means the untranslated scan would skip it even with the
    header rule removed, and a test built on _HEADER would pass whether or not
    the rule existed. That is the same accidental-coverage trap the rule exists
    to guard against, and it must not be baked into the fixture proving it.

    So: an artificial header with a genuinely EMPTY msgstr. Now the header is
    excluded ONLY by the msgid-emptiness rule, and deleting that rule makes
    this test fail -- see the falsification in Step 5."""
    p = tmp_path / "django.po"
    p.write_text('msgid ""\nmsgstr ""\n\nmsgid "Real"\nmsgstr ""\n', encoding="utf-8")
    assert _untranslated(p) == ["Real"]


def test_entries_marks_a_fuzzy_entry(tmp_path):
    """Proves test_no_fuzzy_entries can fail. Against the real catalogs it
    asserts over an empty set and would stay green even if fuzzy parsing were
    broken entirely."""
    p = _po(tmp_path, '#, fuzzy\nmsgid "Save"\nmsgstr "Zapisz"\n')
    assert [e["msgid"] for e in _entries(p) if e["fuzzy"]] == ["Save"]


def test_entries_marks_an_obsolete_entry(tmp_path):
    """Proves test_no_obsolete_entries can fail. Note this is the OPPOSITE
    direction from the ignore-obsolete scenario above: the untranslated scan
    must skip obsolete entries while this guard must detect them. Both hold
    only because _entries() retains and marks them rather than dropping them."""
    p = _po(tmp_path, '#~ msgid "Gone"\n#~ msgstr "Zniknęło"\n')
    assert [e["msgid"] for e in _entries(p) if e["obsolete"]] == ["Gone"]
