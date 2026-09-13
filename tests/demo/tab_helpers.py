"""Shared helpers for the PR 3 demo-tab tests."""

from bs4 import BeautifulSoup
from django.urls import reverse


def demo_tab_url(show_all=False):
    url = reverse("institution:settings") + "?tab=demo"
    return f"{url}&all=1" if show_all else url


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def row_ids(response):
    """Kit pks of the list rows, in page order. Located by the data-demo-kit hook,
    never by an id substring — course, group and user pks share the page."""
    return [
        int(tr["data-demo-kit"]) for tr in soup(response).select("tr[data-demo-kit]")
    ]
