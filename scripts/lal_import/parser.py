"""CLI + orchestration: seed a part's manifest + unit JSON + flags.json."""

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from scripts.lal_import.emit import seed_hash
from scripts.lal_import.emit import unit_payload
from scripts.lal_import.grouping import group_into_chapters
from scripts.lal_import.lesson import parse_lesson
from scripts.lal_import.naming import lesson_title
from scripts.lal_import.naming import part_title_placeholder
from scripts.lal_import.naming import quiz_title
from scripts.lal_import.ordering import duplicate_token_warnings
from scripts.lal_import.ordering import ordered_html_files
from scripts.lal_import.quiz import parse_quiz

_THREE_DIGIT = re.compile(r"^\d{3}")


def _three_digit_folders(source_root):
    return sorted(
        p.name
        for p in Path(source_root).iterdir()
        if p.is_dir() and _THREE_DIGIT.match(p.name)
    )


def _part_order(source_root, folder):
    return _three_digit_folders(source_root).index(folder)


def _parse_unit(part_dir, source_html, unit_type):
    html = (part_dir / source_html).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    if unit_type == "quiz":
        elements, flags = parse_quiz(html)
        title = quiz_title(source_html)
    else:
        elements, flags = parse_lesson(html, source_html)
        title = lesson_title(soup, source_html)
    return elements, flags, title


def seed_part(source_root, folder, out_root, mode="seed"):
    source_root = Path(source_root)
    out_root = Path(out_root)
    part_dir = source_root / folder
    out_dir = out_root / folder

    if out_dir.exists() and mode == "seed":
        raise FileExistsError(
            f"{out_dir} already seeded; "
            "use --refresh-unmapped/--refresh-elements/--force"
        )

    names = [p.name for p in part_dir.glob("*.html")]
    ordered = ordered_html_files(names)
    all_flags = list(duplicate_token_warnings(ordered))
    chapters_src = group_into_chapters(ordered)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "part": {
            "source_folder": folder,
            "order": _part_order(source_root, folder),
            "title": part_title_placeholder(folder),
        },
        "chapters": [],
    }
    for c_i, ch in enumerate(chapters_src):
        units_meta = []
        for u_i, u in enumerate(ch["units"]):
            src = u["source_html"]
            unit_json = src[:-5] + ".json"
            elements, flags, title = _parse_unit(part_dir, src, u["unit_type"])
            for f in flags:
                f["unit_json"] = unit_json
            all_flags.extend(flags)
            _write_unit(out_dir / unit_json, unit_payload(elements, flags), mode)
            units_meta.append(
                {
                    "order": u_i,
                    "unit_json": unit_json,
                    "source_html": src,
                    "source_dir": folder,
                    "unit_type": u["unit_type"],
                    "title": title,
                }
            )
        manifest["chapters"].append(
            {
                "order": c_i,
                "title": f"__PLACEHOLDER chapter {c_i + 1}__",
                "units": units_meta,
            }
        )

    # Only seed/force write the manifest. seed runs only on a fresh dir (guarded
    # above), so its manifest is brand-new; force intentionally discards names.
    # refresh-* NEVER touch the manifest — hand-edited part/chapter/unit titles are
    # fully preserved (spec §4.1, I4). flags.json (a derived worklist) is always
    # regenerated.
    if mode in ("seed", "force"):
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        manifest = json.loads((out_dir / "manifest.json").read_text("utf-8"))
    (out_dir / "flags.json").write_text(
        json.dumps(all_flags, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _write_unit(path, payload, mode):
    """Honor the re-parse guard for an individual unit file."""
    if not path.exists() or mode == "force":
        _dump(path, payload)
        return
    existing = json.loads(path.read_text(encoding="utf-8"))
    stored = existing.get("seed_hash")
    untouched = stored == seed_hash(existing)
    if mode == "refresh-unmapped" and not existing.get("fully_mapped") and untouched:
        _dump(path, payload)
    elif mode == "refresh-elements" and untouched:
        _dump(path, payload)
    # else: preserve the edited unit (do nothing)


def _dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description="Seed LAL import JSON for one part.")
    ap.add_argument("folder")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--json-dir", default="scripts/lal_import/out")
    ap.add_argument("--refresh-unmapped", action="store_true")
    ap.add_argument("--refresh-elements", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    mode = (
        "force"
        if args.force
        else "refresh-elements"
        if args.refresh_elements
        else "refresh-unmapped"
        if args.refresh_unmapped
        else "seed"
    )
    seed_part(args.source_root, args.folder, args.json_dir, mode=mode)


if __name__ == "__main__":
    main()
