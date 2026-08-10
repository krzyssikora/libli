"""Shared helpers for the editor row-mechanics tests. Plain functions, not fixtures:
the tests call them directly rather than injecting them.

"element" throughout means the `Element` JOIN ROW, never the content object — the
POST's `element` key, `form_url` and `reopen` all take the join-row pk, while the
per-type payload (`.pairs`, `.options`) lives on `element.content_object`."""

from bs4 import BeautifulSoup
from django.urls import reverse


def save_url(course):
    """courses:manage_element_save takes only the course slug; the element and unit
    travel in the POST body (see views_manage.element_save)."""
    return reverse("courses:manage_element_save", kwargs={"slug": course.slug})


def form_url(course, element):
    return reverse(
        "courses:manage_element_form", kwargs={"slug": course.slug, "pk": element.pk}
    )


def open_element_form(client, course, element):
    """GET the element's edit fragment and return its HTML."""
    resp = client.get(form_url(course, element))
    assert resp.status_code == 200
    return resp.content.decode()


def base_post(course, unit, element, type_key):
    """The host-form keys every element save requires.

    `unit` is mandatory — views_manage.element_save reads request.POST['unit'] and
    filters ContentNode on it.

    `unit_token` is an OPTIMISTIC-CONCURRENCY token, not an id: _host_form.html:9
    posts `unit.updated.isoformat`, and builder._check_token does
    parse_datetime(token) and raises ConflictError unless it equals unit.updated.
    Passing unit.pk parses to None and every save returns **409**, not 200 — and
    409 is easy to misdiagnose, because it looks like neither the 404 of a missing
    unit nor the 422 of a validation error.

    `parent`/`tab` are deliberately ABSENT: builder.save_element reads them only on
    the create path (`join is None`), and every caller here edits an existing
    element. `el_title` is absent too — but note that it is read unconditionally
    (`builder.py:1432`), so a save without it BLANKS the join row's title. Harmless
    for elements seeded without one; add `"el_title": element.title` if a future
    test seeds a titled element."""
    return {
        "type": type_key,
        "element": element.pk,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
    }


def rendered_rows(html):
    """Rows actually in the list, with <template> content removed first.

    bs4 exposes <template> children as ordinary nodes, so a plain
    select("[data-fsrow-item]") also matches the blueprint row — an assertion that
    passes even when the list renders nothing."""
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    listing = soup.select_one("[data-fsrows-list]")
    return listing.select("[data-fsrow-item]") if listing else []


def reopen(page, element_pk, ready="[data-fsrows-list]"):
    """Re-open an element's editor after a save, and wait for the swapped fragment.

    The edit trigger lives in the element ROW HEAD (`_element_row.html:33` and the
    other branches), NOT inside [data-edit-slot] — the slot is where the form is
    swapped IN. Scoping the click to the slot finds nothing and the test hangs
    until timeout.

    `ready` is overridable because the retrofit no-regression test runs against
    MASTER, where [data-fsrows-list] does not exist yet (_edit_stepper.html is
    `data-stepper-rows`). Defaulting it and hardcoding the wait would make that
    'GREEN on master' test red on master, silently voiding the guarantee."""
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').first.click()
    page.locator(ready).first.wait_for(timeout=8000)
