import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


@pytest.fixture
def course_and_manager(client):
    # make_pa, NOT UserFactory + force_login -- see the note in Task 9's fixture.
    pa = make_pa(client, "pa")
    return CourseFactory(owner=pa), pa


def _fetched(course, source_url):
    asset = MediaAssetFactory(course=course, kind="image")
    # .update(), not .save(): a malformed authority would not survive full_clean(),
    # and the point is a row that is ALREADY in that state.
    MediaAsset.objects.filter(pk=asset.pk).update(source_url=source_url)
    asset.refresh_from_db()
    # attach_usage sets the img_uses/vid_uses/di_uses the cell template reads
    from courses import media as media_svc

    return media_svc.attach_usage(asset)


def test_video_picker_has_two_tabs_and_no_fetch_panel(course_and_manager):
    course, _ = course_and_manager
    html = render_to_string(
        "courses/manage/media/_picker.html",
        {"course": course, "kind": "video", "assets": []},
    )
    # NOTE: counting via data-tab="..." occurrences, not 'class="picker__tab' --
    # the latter also matches the wrapping <div class="picker__tabs"> (its plural
    # class is a substring-prefix collision), which the wrapper is never touched
    # by this task and cannot be renamed without a JS/CSS sweep out of scope here.
    # Only <button> tabs carry data-tab; panels carry data-panel instead.
    assert len(re.findall(r'data-tab="', html)) == 2
    assert "data-picker-url" not in html


def test_image_picker_has_three_tabs_and_a_hidden_fetch_panel(course_and_manager):
    course, _ = course_and_manager
    html = render_to_string(
        "courses/manage/media/_picker.html",
        {"course": course, "kind": "image", "assets": []},
    )
    assert len(re.findall(r'data-tab="', html)) == 3
    assert "data-picker-url" in html
    assert "data-msg-fetch-failed" in html
    # Every tab's data-tab must have a matching data-panel, or the delegated handler
    # (p.hidden = data-panel !== data-tab) hides EVERY panel on the first click.
    assert set(re.findall(r'data-tab="([^"]+)"', html)) == set(
        re.findall(r'data-panel="([^"]+)"', html)
    )
    # The panel MUST ship hidden -- without it it stacks on top of the library panel
    # until the first tab click, a visible layout break no other assertion catches.
    assert re.search(r'data-panel="fetch"[^>]*\shidden', html)
    # ...and its tab must NOT be is-on: exactly one tab is, the library one.
    assert html.count("is-on") == 1
    assert re.search(r'data-tab="library"[^>]*is-on|is-on[^>]*data-tab="library"', html)


def test_manager_form_posts_to_the_fetch_route(client, course_and_manager):
    course, _ = course_and_manager
    html = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()
    fetch_url = reverse("courses:manage_media_fetch", kwargs={"slug": course.slug})
    # Scope to the NEW form. Bare substring checks all pass WITHOUT it:
    # manager.html:20's .media-upload already carries method="post", every
    # .asset-del form in the included grid carries method="post" + csrf_token,
    # and the fetch URL appears in the data-fetch-url attribute regardless.
    form = re.search(r'<form[^>]*class="media-fetch"[^>]*>.*?</form>', html, re.S)
    assert form, "no .media-fetch form rendered"
    markup = form.group(0)
    assert 'method="post"' in markup
    assert f'action="{fetch_url}"' in markup
    assert "csrfmiddlewaretoken" in markup
    assert 'name="url"' in markup and "data-fetch-submit" in markup
    # These two live on the .media-manager root, OUTSIDE the form
    assert "data-fetch-url" in html and "data-msg-fetch-failed" in html


def test_cell_renders_a_source_link_for_a_fetched_asset(course_and_manager):
    course, _ = course_and_manager
    url = "https://upload.wikimedia.org/Foo.png"
    asset = _fetched(course, url)
    html = render_to_string(
        "courses/manage/media/_asset_cell.html", {"course": course, "asset": asset}
    )
    assert 'rel="noopener noreferrer"' in html
    assert 'target="_blank"' in html
    assert ">upload.wikimedia.org<" in html  # hostname is the LABEL
    assert url in html  # full URL in title
    # The region matters, not just the link: editor.css's .asset-source rule
    # (margin-inline-start: auto, and the three-child space-between behaviour) only
    # applies inside .asset-foot. A mutant that moves the anchor into .asset-names
    # would still satisfy every assertion above.
    foot = re.search(r'<div class="asset-foot">.*?</div>\s*</div>', html, re.S)
    assert foot, "no .asset-foot region rendered"
    assert 'class="asset-source"' in foot.group(0)


def test_cell_renders_no_link_for_a_malformed_source(course_and_manager):
    course, _ = course_and_manager
    asset = _fetched(course, "https://[bad-ipv6/x.png")
    html = render_to_string(
        "courses/manage/media/_asset_cell.html", {"course": course, "asset": asset}
    )
    assert "asset-source" not in html
