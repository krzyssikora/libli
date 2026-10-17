"""Server-render tests for the builder phone-layout scaffolding (Task 1).

Every hook is server-rendered on every layout; only CSS/JS decide whether it shows.
Selectors, never substring counts."""

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
