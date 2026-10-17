"""Server-render tests for the builder phone-layout scaffolding (Task 1).

Every hook is server-rendered on every layout; only CSS/JS decide whether it shows.
Selectors, never substring counts."""

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import seed_course

SINGLE_HOOKS = [
    "[data-sheet]",
    "[data-sheet-dim]",
    "[data-sheet-shell]",
    "[data-sheet-grab]",
    "[data-sheet-close]",
    "[data-sheet-body]",
    "[data-sheet-tools]",
    "[data-toast]",
    "[data-row-menu]",
    "[data-sheet-course]",
]

MENU_ACTIONS = ["rename", "up", "down", "move", "duplicate", "export", "delete"]


@pytest.fixture
def soup(client):
    user = make_pa_user("pa")
    client.force_login(user)
    seeded = seed_course()
    response = client.get(f"/manage/courses/{seeded['course'].slug}/build/?open=all")
    assert response.status_code == 200
    return BeautifulSoup(response.content.decode(), "html.parser")


@pytest.mark.django_db
def test_builder_renders_phone_scaffolding(soup):
    for sel in SINGLE_HOOKS:
        assert len(soup.select(sel)) == 1, sel

    moves = [el["data-phone-move"] for el in soup.select("[data-phone-move]")]
    assert moves == ["io", "bulk", "legends"]

    assert soup.select_one("[data-sheet-body] [data-panel]") is not None
    assert len(soup.select("[data-panel]")) == 1

    menu = soup.select_one("[data-row-menu]")
    assert menu in soup.select(".builder__tree [data-row-menu]")
    assert soup.select_one("#row-menu") is menu

    actions = [el["data-menu-action"] for el in menu.select("[data-menu-action]")]
    assert actions == MENU_ACTIONS


@pytest.mark.django_db
def test_every_row_has_ptitle_and_more(soup):
    rows = soup.select("li.tree__row")
    assert len(rows) >= 9
    for row in rows:
        form = row.select_one(":scope > form.tree__rowhead")
        title_input = form.select_one("input.tree__title")
        ptitles = form.select(":scope > button.tree__ptitle[type=button]")
        assert len(ptitles) == 1
        assert ptitles[0].get_text() == title_input["value"]
        mores = form.select(
            ":scope > button.tree__more[type=button][aria-expanded=false]"
            "[aria-controls=row-menu]"
        )
        assert len(mores) == 1
        first_submit = form.select_one("button[type=submit]")
        assert "visually-hidden" in first_submit.get("class", [])


@pytest.mark.django_db
def test_container_badges_carry_a_letter(soup):
    containers = soup.select(
        ".tree__badge--part, .tree__badge--chapter, .tree__badge--section"
    )
    assert len(containers) == 4
    for badge in containers:
        assert badge["data-letter"] == badge.get_text().strip()[0].upper()
    units = soup.select(".tree__badge--unit")
    assert units
    for badge in units:
        assert not badge.has_attr("data-letter")


@pytest.mark.django_db
def test_header_order_unchanged(soup):
    head = soup.select_one("header.manage__head")
    matched = head.select(
        "h1, .builder__kurs, a.btn, form.builder__filter, "
        "[data-expand-all], [data-collapse-all]"
    )
    seen, order = set(), []
    for el in matched:
        if id(el) in seen or el.has_attr("data-filter-clear"):
            continue
        seen.add(id(el))
        if el.name == "h1":
            order.append("h1")
        elif "builder__kurs" in el.get("class", []):
            order.append("kurs")
        elif el.name == "form":
            order.append("filter")
        elif el.has_attr("data-expand-all"):
            order.append("expand")
        elif el.has_attr("data-collapse-all"):
            order.append("collapse")
        elif "import" in el["href"]:
            order.append("import")
        elif "export" in el["href"]:
            order.append("export")
        else:
            order.append(el["href"])
    assert order == ["h1", "kurs", "import", "export", "filter", "expand", "collapse"]


# --- Task 2: phone CSS source --------------------------------------------------

_BUILDER_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "builder.css"
)
_PHONE_MEDIA = "@media (pointer: coarse) and (max-width: 959.98px)"


def _match_brace(text, open_at):
    """Index of the `}` closing the `{` at `open_at`."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced braces in builder.css")


def _selector_lists(body):
    """Every rule prelude inside `body`, descending into nested at-rules."""
    out, pos = [], 0
    while True:
        brace = body.find("{", pos)
        if brace == -1:
            return out
        prelude = body[pos:brace].strip()
        end = _match_brace(body, brace)
        if prelude.startswith("@"):
            out.extend(_selector_lists(body[brace + 1 : end]))
        else:
            out.append(prelude)
        pos = end + 1


def test_phone_rules_are_js_scoped():
    css = re.sub(r"/\*.*?\*/", "", _BUILDER_CSS.read_text(encoding="utf-8"), flags=re.S)
    blocks, pos = [], 0
    while (start := css.find(_PHONE_MEDIA, pos)) != -1:
        brace = css.index("{", start)
        end = _match_brace(css, brace)
        blocks.append(css[brace + 1 : end])
        pos = end + 1
    assert blocks, "no phone media block in builder.css"
    preludes = [p for block in blocks for p in _selector_lists(block)]
    assert preludes, "phone media block holds no rules"
    for prelude in preludes:
        for selector in prelude.split(","):
            selector = " ".join(selector.split())
            assert selector.startswith((".js ", "html.js")), selector


def test_no_any_pointer():
    assert "any-pointer" not in _BUILDER_CSS.read_text(encoding="utf-8")


def _phone_rules():
    """(selector, declarations) for every top-level rule in the phone block."""
    css = re.sub(r"/\*.*?\*/", "", _BUILDER_CSS.read_text(encoding="utf-8"), flags=re.S)
    start = css.index(_PHONE_MEDIA)
    brace = css.index("{", start)
    body = css[brace + 1 : _match_brace(css, brace)]
    rules, pos = [], 0
    while (open_at := body.find("{", pos)) != -1:
        end = _match_brace(body, open_at)
        prelude = " ".join(body[pos:open_at].split())
        if not prelude.startswith("@"):
            for selector in prelude.split(","):
                rules.append(
                    (selector.strip(), " ".join(body[open_at + 1 : end].split()))
                )
        pos = end + 1
    return rules


def test_phone_legends_hidden_before_js_moves_them():
    """The legends block is a direct child of .builder__tree until builder.js moves
    it into the sheet tools: hidden from first paint, so a phone load never
    flashes it above the tree."""
    decls = [
        d
        for sel, d in _phone_rules()
        if sel == ".js .builder__tree > .builder__movable"
    ]
    assert any(re.search(r"(^|;)\s*display:\s*none\b", d) for d in decls), decls


def test_expand_all_reason_is_not_generated_content():
    """Generated content inside the button would join the link's accessible name."""
    offenders = [
        sel for sel, _ in _phone_rules() if "expand-all" in sel and "::" in sel
    ]
    assert offenders == []


@pytest.mark.django_db
def test_expand_all_reason_rendered_only_over_the_ceiling(client, monkeypatch):
    from courses import builder_open

    user = make_pa_user("pa")
    client.force_login(user)
    seeded = seed_course()
    url = f"/manage/courses/{seeded['course'].slug}/build/"

    def reasons():
        soup = BeautifulSoup(client.get(url).content.decode(), "html.parser")
        return soup, soup.select("[data-expand-all-reason]")

    soup, found = reasons()
    assert found == []
    monkeypatch.setattr(builder_open, "CEILING", 1)
    soup, found = reasons()
    assert len(found) == 1
    assert found[0].get_text() == "This course is too large to expand at once."
    bulk = soup.select_one('[data-phone-move="bulk"]')
    assert found[0].parent is bulk
    assert found[0].find_previous_sibling() is bulk.select_one("[data-expand-all]")
