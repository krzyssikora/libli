"""Render contract of courses/_course_glance.html and its placements."""

import re

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.utils import translation


def _render(**ctx):
    ctx.setdefault("progress_done", 0)
    ctx.setdefault("progress_total", 0)
    ctx.setdefault("results_pct", None)
    html = render_to_string("courses/_course_glance.html", ctx)
    return BeautifulSoup(html, "html.parser")


def _tracks(soup):
    return soup.select(".glance__track")


@pytest.mark.parametrize(
    ("width", "fill", "dot"),
    [(None, False, False), (0, False, True), (1, True, False), (100, True, False)],
)
def test_results_fill_rules(width, fill, dot):
    soup = _render(progress_width=None, results_width=width, results_pct=width)
    track = _tracks(soup)[1]
    assert bool(track.select(".glance__fill")) is fill
    assert bool(track.select(".glance__dot")) is dot
    if fill:
        assert track.select_one(".glance__fill")["style"] == f"width: {width}%"


def test_progress_zero_of_n_draws_neither_fill_nor_dot():
    soup = _render(progress_width=None, results_width=None, progress_total=4)
    track = _tracks(soup)[0]
    assert not track.select(".glance__fill") and not track.select(".glance__dot")


def test_progress_fill_width():
    soup = _render(
        progress_width=37, results_width=None, progress_done=3, progress_total=8
    )
    assert _tracks(soup)[0].select_one(".glance__fill")["style"] == "width: 37%"


def test_labels_are_hidden_and_tracks_carry_names():
    soup = _render(
        progress_width=50,
        results_width=80,
        progress_done=1,
        progress_total=2,
        results_pct=80,
    )
    for label in soup.select(".glance__label"):
        assert label["aria-hidden"] == "true"
    progress, results = _tracks(soup)
    assert progress["role"] == "img" and results["role"] == "img"
    assert progress["aria-label"] == "Progress: 1 of 2 lessons"
    assert results["aria-label"] == "Results: 80%"


def test_english_plural_uses_count():
    one = _tracks(
        _render(
            progress_width=None, results_width=None, progress_done=0, progress_total=1
        )
    )[0]
    two = _tracks(
        _render(
            progress_width=None, results_width=None, progress_done=0, progress_total=2
        )
    )[0]
    assert one["aria-label"] == "Progress: 0 of 1 lesson"
    assert two["aria-label"] == "Progress: 0 of 2 lessons"


def test_none_figures_are_spoken():
    progress, results = _tracks(_render(progress_width=None, results_width=None))
    assert progress["aria-label"] == "Progress: no lessons to track"
    assert results["aria-label"] == "Results: no scores yet"


def test_no_visible_digits():
    soup = _render(
        progress_width=37,
        results_width=80,
        progress_done=3,
        progress_total=8,
        results_pct=80,
    )
    assert not re.search(r"\d", soup.select_one(".glance").get_text())


def test_decorative_emits_no_roles_or_labels():
    soup = _render(progress_width=70, results_width=85, decorative=True)
    for track in _tracks(soup):
        assert not track.has_attr("role") and not track.has_attr("aria-label")
    assert len(soup.select(".glance__fill")) == 2


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (1, "Postęp: 0 z 1 lekcji"),
        (3, "Postęp: 0 z 3 lekcji"),
        (5, "Postęp: 0 z 5 lekcji"),
    ],
)
def test_polish_progress_label(total, expected):
    with translation.override("pl"):
        track = _tracks(
            _render(
                progress_width=None,
                results_width=None,
                progress_done=0,
                progress_total=total,
            )
        )[0]
    assert track["aria-label"] == expected


def test_polish_results_and_labels():
    with translation.override("pl"):
        soup = _render(progress_width=None, results_width=80, results_pct=80)
    assert _tracks(soup)[1]["aria-label"] == "Wyniki: 80%"  # single %, not %%
    labels = [x.get_text(strip=True) for x in soup.select(".glance__label")]
    assert labels == ["Postęp", "Wyniki"]
    with translation.override("pl"):
        none = _tracks(_render(progress_width=None, results_width=None))
    assert none[0]["aria-label"] == "Postęp: brak lekcji obowiązkowych"
    assert none[1]["aria-label"] == "Wyniki: jeszcze brak punktów"


def test_every_polish_plural_index_is_filled():
    from pathlib import Path

    from django.conf import settings

    po = (Path(settings.BASE_DIR) / "locale/pl/LC_MESSAGES/django.po").read_text(
        encoding="utf-8"
    )
    block = po.split('msgid "Progress: %(done)s of %(counter)s lesson"', 1)[1]
    block = block.split("\n\n", 1)[0]
    for i in range(3):
        m = re.search(rf'msgstr\[{i}\] "(.*)"', block)
        assert m and m.group(1), f"msgstr[{i}] is empty"
