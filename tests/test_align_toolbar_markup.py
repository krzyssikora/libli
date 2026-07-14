from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITORS = ROOT / "templates/courses/manage/editor"
IN_SCOPE = ["_edit_text.html", "_edit_callout.html", "_edit_spoiler.html"]


def test_align_buttons_present_in_each_in_scope_toolbar():
    for name in IN_SCOPE:
        html = (EDITORS / name).read_text(encoding="utf-8")
        for cmd, icon in [
            ("alignleft", "#ed-align-left"),
            ("aligncenter", "#ed-align-center"),
            ("alignright", "#ed-align-right"),
        ]:
            assert f'data-cmd="{cmd}"' in html, f"{name} missing {cmd}"
            assert icon in html, f"{name} missing {icon}"


def test_shared_partial_left_untouched():
    shared = (EDITORS / "_rte_toolbar.html").read_text(encoding="utf-8")
    assert "aligncenter" not in shared, "shared toolbar must NOT get align buttons"
