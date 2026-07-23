import json
from pathlib import Path

from scripts.lal_import.parser import seed_part


def _make_source(root: Path):
    part = root / "005_demo"
    (part / "static").mkdir(parents=True)
    (part / "010_intro.html").write_text(
        "<h2>Intro</h2><p>Witaj \\(x<y\\)</p>", encoding="utf-8"
    )
    (part / "039_x_quiz.html").write_text("<p>Ile?</p>\n= 2\n", encoding="utf-8")
    return part


def test_seed_writes_manifest_units_and_flags(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make_source(root)
    out = tmp_path / "out"
    manifest = seed_part(root, "005_demo", out, mode="seed")

    assert manifest["part"]["source_folder"] == "005_demo"
    assert manifest["part"]["title"] == "demo"  # ASCII placeholder
    assert len(manifest["chapters"]) == 1
    units = manifest["chapters"][0]["units"]
    assert [u["unit_type"] for u in units] == ["lesson", "quiz"]

    intro = json.loads((out / "005_demo" / units[0]["unit_json"]).read_text("utf-8"))
    body = " ".join(e.get("body", "") for e in intro["elements"])
    assert r"\(x&lt;y\)" in body  # math escaped
    assert intro["fully_mapped"] is True
    assert (out / "005_demo" / "flags.json").exists()


def test_seed_refuses_second_seed(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make_source(root)
    out = tmp_path / "out"
    seed_part(root, "005_demo", out, mode="seed")
    try:
        seed_part(root, "005_demo", out, mode="seed")
        raise AssertionError("expected refusal on re-seed")
    except FileExistsError:
        pass


def test_manifest_part_order_from_scan(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "005_demo").mkdir()
    (root / "010_next").mkdir()
    _make_source(root)  # fills 005_demo
    (root / "010_next" / "010_a.html").write_text("<p>hi</p>", "utf-8")
    out = tmp_path / "out"
    m0 = seed_part(root, "005_demo", out, mode="seed")
    m1 = seed_part(root, "010_next", out, mode="seed")
    assert m0["part"]["order"] == 0
    assert m1["part"]["order"] == 1


def test_refresh_preserves_hand_edited_manifest_titles(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    _make_source(root)
    out = tmp_path / "out"
    seed_part(root, "005_demo", out, mode="seed")
    # Simulate the Phase-1 hand-edit of a unit title in the manifest.
    mpath = out / "005_demo" / "manifest.json"
    m = json.loads(mpath.read_text("utf-8"))
    m["chapters"][0]["units"][0]["title"] = "Human Intro Title"
    mpath.write_text(json.dumps(m), "utf-8")
    # A refresh must NOT clobber that edited unit title.
    seed_part(root, "005_demo", out, mode="refresh-elements")
    after = json.loads(mpath.read_text("utf-8"))
    assert after["chapters"][0]["units"][0]["title"] == "Human Intro Title"
