# tests/test_e2e_questions_2dii.py
"""Playwright e2e for Phase-2d-ii drag-to-image.

dnd.js is SHARED by dragfill, matchpair, and drag-to-image. For drag-to-image it
builds absolutely-positioned OVERLAY drop-targets on the image stage (one per
[data-zone] badge) and a shared tap-to-assign state machine; the native
<select name="slot"> stays the source of truth + no-JS fallback, so drag, tap,
keyboard, and no-JS all funnel through setSelect() and record byte-identical answers.

These tests prove:
  - JS drag: drag chips onto the overlay targets → the linked selects take the tokens.
  - tap-to-assign: tap chip then tap target records the SAME answer as drag.
  - no-JS (<select>): post slot values directly → same payload; quiz withholds the
    correct label pre-reveal (no-leak).
  - quiz reveal: exhaust attempts → reveal shows accepted labels; pre-reveal fragment
    has NO accepted-label text.
  - tap state table: armed+filled OVERWRITES (not clears); unarmed+filled CLEARS.
  - KaTeX: a \\(x\\) label typesets (a .katex node) in the chip + reveal, while the
    native <option> shows the raw \\(x\\) source.
  - no-JS authoring edit-existing: edit a zone's numeric coords + label, save, persist.

Authoring canvas (zone-editor.js, opened via the live editor ✎ edit flow):
  - existing zones draw on load (incl. an x=0,y=0,w=0.5,h=0.5 corner zone).
  - draw a new zone → uses zones-1-* (real index, NOT __prefix__) → saves.
  - DELETE a drawn zone (row stays with DELETE ticked) → order recompacts to 0 → saves.
  - MutationObserver: setting data-media-url on a new form builds the stage.

Marked e2e (run with -m e2e). Mirrors the harness in test_e2e_questions_2d.py
EXACTLY (fixtures, _login, the CSRF-cookie no-JS POST workaround, the
.question__form button[type="submit"] selector, wait_for(".is-correct")).

Harness notes (carried from 2d):
  - The DnD question element is rendered via render_to_string() without a request, so
    {% csrf_token %} produces an empty token; a no-JS button click would be rejected
    with "CSRF token missing". We post directly with the CSRF cookie instead.
  - The factory MediaAsset.file points at a non-served path, so the stage <img> would
    collapse to ~0px and the overlay targets would be undraggable. _size_stage()
    swaps in a 1x1 data-URI image and pins the stage to a fixed pixel size so the
    percentage-positioned overlay targets have real, draggable geometry. This is a
    pure presentation fixup; the answer path (setSelect → select value) is untouched.
"""

import os
import re
import urllib.parse

import pytest

from courses.models import ContentNode
from courses.models import Course
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import Enrollment
from courses.models import MediaAsset
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# A 1x1 transparent PNG so the stage <img> loads (the factory's file path is not
# served by the test server; without this the stage collapses and overlay targets
# have no geometry to drag onto).
_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


def _size_stage(page, w=400, h=300):
    """Give the stage a fixed pixel size and a loadable image so the percentage-
    positioned overlay targets have real, draggable geometry. Returns once the stage
    and its overlay targets have non-zero size."""
    page.wait_for_selector("[data-dragimage-stage]")
    page.evaluate(
        """([w, h, src]) => {
            const stage = document.querySelector('[data-dragimage-stage]');
            stage.style.width = w + 'px';
            stage.style.height = h + 'px';
            stage.style.position = 'relative';
            stage.style.display = 'block';
            const img = stage.querySelector('img');
            if (img) {
                img.src = src;
                img.style.width = w + 'px';
                img.style.height = h + 'px';
            }
        }""",
        [w, h, _PNG_DATA_URI],
    )
    # The overlay targets are sized in % of the stage; once the stage has px size they
    # become draggable. Wait until the first target reports a non-zero box.
    page.wait_for_function(
        """() => {
            const t = document.querySelector('.dragimage__target');
            if (!t) return false;
            const r = t.getBoundingClientRect();
            return r.width > 4 && r.height > 4;
        }"""
    )


# ── Seeding ──────────────────────────────────────────────────────────────────


def _make_media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _add_zones(q, labels):
    """Two well-separated zones so the overlay targets do not overlap (drag aim)."""
    DragZone.objects.create(
        question=q, correct_label=labels[0], x=0.1, y=0.1, w=0.3, h=0.3, order=0
    )
    DragZone.objects.create(
        question=q, correct_label=labels[1], x=0.6, y=0.6, w=0.3, h=0.3, order=1
    )


def _seed_dragimage_lesson(
    username, slug, *, labels=("Heart", "Lung"), distractors="Liver"
):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = DragToImageQuestionElement.objects.create(
        media=_make_media(course), alt="Diagram", distractors=distractors
    )
    _add_zones(q, labels)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


def _seed_dragimage_quiz(
    username, slug, *, labels=("Heart", "Lung"), distractors="Liver"
):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Q"
    )
    q = DragToImageQuestionElement.objects.create(
        media=_make_media(course),
        alt="Diagram",
        distractors=distractors,
        marking_mode="A",
        max_attempts=2,
    )
    _add_zones(q, labels)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


# ── Student answering: JS drag onto overlay targets ──────────────────────────


@pytest.mark.django_db(transaction=True)
def test_dragimage_js_drag_path(live_server, page):
    """JS: drag each chip onto its OVERLAY target → the linked selects take the tokens
    → submit → correct feedback."""
    course, unit, el = _seed_dragimage_lesson("djs", "di-js")
    _login(page, live_server, "djs")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Heart"]').drag_to(targets.nth(0))
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))

    selects = page.locator('select[name="slot"]')
    assert selects.nth(0).input_value() == "Heart"
    assert selects.nth(1).input_value() == "Lung"

    page.locator('.question__form button[type="submit"]').click()
    page.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)
    assert page.locator(".is-correct").count() >= 1


@pytest.mark.django_db(transaction=True)
def test_dragimage_js_drag_partial(live_server, page):
    """JS: drag a DISTRACTOR onto zone 1 + the right chip onto zone 2 → partial
    (not fully correct)."""
    course, unit, el = _seed_dragimage_lesson("djp", "di-jp")
    _login(page, live_server, "djp")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Liver"]').drag_to(targets.nth(0))  # wrong
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))  # right

    page.locator('.question__form button[type="submit"]').click()
    page.locator("[data-question-feedback]").wait_for(timeout=6000)
    page.wait_for_timeout(500)
    # Not fully correct: the form must NOT report .is-correct at the question level.
    assert page.locator("[data-question-feedback] .is-correct").count() == 0


# ── Student answering: tap-to-assign records the SAME answer as drag ──────────


@pytest.mark.django_db(transaction=True)
def test_dragimage_tap_to_assign_equals_drag(live_server, page):
    """Tap a chip then tap its overlay target → assign; the recorded answer equals the
    drag answer (both go through setSelect)."""
    course, unit, el = _seed_dragimage_lesson("dtap", "di-tap")
    _login(page, live_server, "dtap")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    # tap chip → armed; tap empty target → assign.
    page.locator('.dnd__chip[data-token="Heart"]').click()
    targets.nth(0).click()
    page.locator('.dnd__chip[data-token="Lung"]').click()
    targets.nth(1).click()

    selects = page.locator('select[name="slot"]')
    assert selects.nth(0).input_value() == "Heart"
    assert selects.nth(1).input_value() == "Lung"

    page.locator('.question__form button[type="submit"]').click()
    page.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)
    assert page.locator(".is-correct").count() >= 1


# ── Tap state table: armed+filled OVERWRITES; unarmed+filled CLEARS ──────────


@pytest.mark.django_db(transaction=True)
def test_dragimage_tap_state_table(live_server, page):
    """Spec tap state table:
    armed + filled  → overwrite (NOT clear)
    unarmed + filled→ clear
    unarmed + empty → no-op
    """
    course, unit, el = _seed_dragimage_lesson("dtst", "di-tst")
    _login(page, live_server, "dtst")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    selects = page.locator('select[name="slot"]')

    # Assign Heart to target 0 (armed + empty → assign).
    page.locator('.dnd__chip[data-token="Heart"]').click()
    targets.nth(0).click()
    assert selects.nth(0).input_value() == "Heart"

    # armed + FILLED → OVERWRITE (must become Liver, NOT cleared).
    page.locator('.dnd__chip[data-token="Liver"]').click()
    targets.nth(0).click()
    assert selects.nth(0).input_value() == "Liver", "armed+filled must overwrite"

    # unarmed + FILLED → CLEAR. (No chip is armed now — the previous tap disarmed.)
    targets.nth(0).click()
    assert selects.nth(0).input_value() == "", "unarmed+filled must clear"

    # unarmed + EMPTY → no-op (stays empty, no error).
    targets.nth(0).click()
    assert selects.nth(0).input_value() == ""


# ── No-JS: post slot values directly (CSRF-cookie workaround) ─────────────────


@pytest.mark.django_db(transaction=True)
def test_dragimage_no_js_select_path(live_server, browser):
    """No-JS: post the two correct slot values directly, see the correct mark in the
    rendered full-page HTML. Same CSRF workaround as the 2d no-JS tests."""
    course, unit, el = _seed_dragimage_lesson("dnojs", "di-nojs")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _login(page, live_server, "dnojs")
    lesson_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)

    cookies = context.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to lesson page"

    check_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/q/{el.pk}/check/"
    # Order matters: slot[0]=zone0, slot[1]=zone1 (positional invariant).
    body_parts = [
        ("csrfmiddlewaretoken", csrf_token),
        ("slot", "Heart"),
        ("slot", "Lung"),
    ]
    encoded = urllib.parse.urlencode(body_parts)
    resp = page.request.post(
        check_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": lesson_url,
        },
        data=encoded,
    )
    assert resp.ok, f"check_answer POST failed with status {resp.status}"
    html = resp.text()

    result_page = context.new_page()
    result_page.set_content(html)
    assert result_page.locator(".is-correct").count() >= 1
    result_page.close()
    context.close()


# ── Quiz: exhaust attempts → reveal; pre-reveal no-leak ──────────────────────


@pytest.mark.django_db(transaction=True)
def test_dragimage_quiz_withhold_then_reveal_js(live_server, browser):
    """Quiz JS flow: wrong (attempt left) → accepted labels withheld (no-leak);
    wrong again (last attempt) → reveal shows the accepted labels."""
    course, unit, el = _seed_dragimage_quiz("dqjs", "di-qjs")
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "dqjs")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")
    _size_stage(page)

    feedback = page.locator("[data-question-feedback]").first

    def _set_slots(*values):
        page.evaluate(
            """(vals) => {
                const sels = document.querySelectorAll('select[name="slot"]');
                vals.forEach((v, i) => {
                    if (sels[i]) {
                        sels[i].value = v;
                        sels[i].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                });
            }""",
            values,
        )

    # Wrong, attempt remaining → withhold: the reveal partial must not render and no
    # accepted label may appear in the pre-reveal fragment (no-leak, spec §7.1).
    _set_slots("Liver", "Liver")
    page.locator('.question__form button[type="submit"]').first.click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    page.wait_for_timeout(300)
    content = page.content()
    assert "question__reveal" not in content, (
        "reveal must not render with attempts left"
    )
    assert "Correct label:" not in content, "accepted label leaked pre-reveal"

    # Wrong on the last attempt → reveal shows the accepted labels.
    _set_slots("Liver", "Liver")
    page.locator('.question__form button[type="submit"]').first.click()
    page.locator("[data-question-feedback] .is-incorrect").wait_for(timeout=6000)
    page.wait_for_timeout(500)
    revealed = page.content()
    assert "Correct label:" in revealed, (
        "reveal must show accepted labels after last attempt"
    )
    assert "Heart" in revealed and "Lung" in revealed
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_dragimage_quiz_no_js_no_leak(live_server, browser):
    """No-JS quiz: POST a wrong answer with an attempt remaining → full-page re-render
    must NOT contain the accepted-label reveal text (no-leak)."""
    course, unit, el = _seed_dragimage_quiz("dqnojs", "di-qnojs")
    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "dqnojs")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)

    cookies = ctx.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to quiz page"

    answer_url = (
        f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    )
    body_parts = [
        ("csrfmiddlewaretoken", csrf_token),
        ("slot", "Liver"),
        ("slot", "Liver"),
    ]
    encoded = urllib.parse.urlencode(body_parts)
    resp = page.request.post(
        answer_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": quiz_url,
        },
        data=encoded,
    )
    assert resp.ok, f"quiz_answer POST failed with status {resp.status}"
    html = resp.text()
    assert "Correct label:" not in html, "accepted label leaked pre-reveal (no-JS)"
    ctx.close()


# ── KaTeX: a \(x\) label typesets in chip + reveal; <option> shows raw source ─


@pytest.mark.django_db(transaction=True)
def test_dragimage_katex_in_chip_and_reveal(live_server, browser):
    r"""A label containing \(x\) typesets to a .katex node in the JS chip and in the
    reveal, while the native <option> carries the raw \(x\) source (KaTeX never runs on
    <option> text)."""
    course, unit, el = _seed_dragimage_quiz(
        "dkat", "di-kat", labels=(r"\(x\)", "Lung"), distractors="Liver"
    )
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "dkat")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")
    _size_stage(page)

    # The chip pool should contain a typeset .katex node for the \(x\) label.
    page.wait_for_selector(".dnd__pool .katex", timeout=6000)
    assert page.locator(".dnd__pool .katex").count() >= 1, (
        "KaTeX did not typeset in chip"
    )

    # The native <option> must carry the RAW source (no KaTeX on <option> text).
    option_texts = page.locator('select[name="slot"] option').all_inner_texts()
    assert any(r"\(x\)" in t for t in option_texts), (
        f"raw \\(x\\) source missing from <option>s: {option_texts!r}"
    )

    # Exhaust attempts to trigger reveal; confirm the accepted \(x\) typesets there.
    def _set_slots(*values):
        page.evaluate(
            """(vals) => {
                const sels = document.querySelectorAll('select[name="slot"]');
                vals.forEach((v, i) => {
                    if (sels[i]) {
                        sels[i].value = v;
                        sels[i].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                });
            }""",
            values,
        )

    feedback = page.locator("[data-question-feedback]").first
    _set_slots("Liver", "Liver")
    page.locator('.question__form button[type="submit"]').first.click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    _set_slots("Liver", "Liver")
    page.locator('.question__form button[type="submit"]').first.click()
    page.locator("[data-question-feedback] .is-incorrect").wait_for(timeout=6000)
    page.wait_for_timeout(500)
    # The reveal lists the accepted label; KaTeX should have typeset it (a .katex node
    # inside the reveal block).
    page.wait_for_selector(".question__reveal .katex", timeout=6000)
    assert page.locator(".question__reveal .katex").count() >= 1, (
        "KaTeX did not typeset the accepted \\(x\\) label in the reveal"
    )
    ctx.close()


# ── Authoring (no-JS edit-existing): edit numeric coords + label, persist ─────


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db(transaction=True)
def test_authoring_no_js_edit_existing_zone(live_server, browser):
    """No-JS authoring: open an existing drag-to-image question's editor, read its live
    formset field names + values + the unit token, POST an edit of one zone's numeric
    coords + label via element_save, confirm the zone persisted with the new values.

    This drives the SAME save endpoint a no-JS author's full-page form submit would hit
    (no X-Requested-With → full-page redirect), proving the formset round-trips without
    the canvas JS."""
    from tests.factories import CourseFactory

    owner = _make_pa_user("auth_nojs")
    course = CourseFactory(slug="auth-nojs", owner=owner)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    q = DragToImageQuestionElement.objects.create(
        media=_make_media(course), alt="Diagram", distractors=""
    )
    DragZone.objects.create(
        question=q, correct_label="Old", x=0.1, y=0.1, w=0.2, h=0.2, order=0
    )
    el = Element.objects.create(unit=unit, content_object=q)

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "auth_nojs")

    editor_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    form_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/element/{el.pk}/form/"
    )
    save_url = f"{live_server.url}/manage/courses/{course.slug}/build/element/save/"

    # Read the unit token off the editor page (what a no-JS form submit carries).
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')
    token = page.locator('[data-scope="editor"]').get_attribute("data-updated")

    # GET the existing element's edit-form fragment (the .el-select edit flow target) —
    # this is the no-JS-reachable host form with the live formset field names/values.
    frag_resp = page.request.get(form_url, headers={"Referer": editor_url})
    assert frag_resp.ok, f"element_form GET failed: {frag_resp.status}"
    frag = frag_resp.text()

    # Parse every named input/textarea value out of the fragment so the POST mirrors
    # what the rendered no-JS form would submit. Attribute order varies, so read name
    # and value independently from each tag. Drop the __prefix__ template inputs (the
    # empty_form clone source — a no-JS submit never sends those).
    form_fields = {}
    for tag in re.findall(r"<input\b[^>]*>", frag):
        nm = re.search(r'\bname="([^"]+)"', tag)
        if not nm or "__prefix__" in nm.group(1):
            continue
        name = nm.group(1)
        vm = re.search(r'\bvalue="([^"]*)"', tag)
        value = vm.group(1) if vm else ""
        if 'type="checkbox"' in tag:
            if "checked" in tag:
                form_fields[name] = value or "on"
        else:
            form_fields[name] = value
    for m in re.finditer(
        r'<textarea\b[^>]*\bname="([^"]+)"[^>]*>(.*?)</textarea>', frag, re.S
    ):
        if "__prefix__" not in m.group(1):
            form_fields[m.group(1)] = m.group(2)

    # Locate the existing zone row's field prefix via its management-form structure:
    # the formset prefix is "zones"; the existing row is index 0 (zones-0-*).
    prefix = "zones-0-"
    assert prefix + "x" in form_fields, (
        f"existing zone row fields (zones-0-*) missing from fragment: "
        f"{sorted(form_fields)!r}"
    )

    # Edit the label + numeric coords on that row.
    form_fields[prefix + "correct_label"] = "New"
    form_fields[prefix + "x"] = "0.4"
    form_fields[prefix + "y"] = "0.4"
    form_fields[prefix + "w"] = "0.25"
    form_fields[prefix + "h"] = "0.25"

    csrf = ctx.cookies()
    csrf_token = next((c["value"] for c in csrf if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set"

    payload = dict(form_fields)
    payload.update(
        {
            "ctx": "editor",
            "type": "dragtoimagequestion",
            "element": str(el.pk),
            "unit": str(unit.pk),
            "unit_token": token,
            # Top-level form fields (selects/required FKs the regex doesn't capture).
            "media": str(q.media_id),
            "alt": "Diagram",
            "marking_mode": q.marking_mode,
            "max_attempts": str(q.max_attempts) if q.max_attempts is not None else "",
            "csrfmiddlewaretoken": csrf_token,
        }
    )

    resp = page.request.post(save_url, form=payload, headers={"Referer": editor_url})
    assert resp.ok, f"no-JS authoring save failed: {resp.status}"

    q.refresh_from_db()
    zone = q.zones.get()
    assert zone.correct_label == "New", "label edit did not persist"
    assert abs(zone.x - 0.4) < 1e-6 and abs(zone.w - 0.25) < 1e-6, (
        "coords did not persist"
    )
    ctx.close()


# ── Authoring canvas (zone-editor.js) ────────────────────────────────────────
# These drive the live editor: click ✎ on an existing drag-to-image element, the
# editor swaps in the edit-form fragment and (via editor.js applyFragments →
# window.libliZoneEditor) mounts the zone-drawing canvas. The factory image is not
# served, so the canvas stage collapses to 0px; _size_zone_stage() pins it to a fixed
# size with a loadable data-URI so pointer-draw math has real geometry.


def _seed_pa_dragimage(username, slug, *, zones):
    """PA-owned course + lesson unit + a drag-to-image element with `zones`
    (list of dicts: correct_label/x/y/w/h)."""
    from tests.factories import CourseFactory

    owner = _make_pa_user(username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    q = DragToImageQuestionElement.objects.create(
        media=_make_media(course), alt="Diagram", distractors=""
    )
    for i, z in enumerate(zones):
        DragZone.objects.create(question=q, order=i, **z)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, q, el


def _open_existing_editor(page, live_server, course, unit, el):
    """Open the live editor, click ✎ on the element's row → the canvas mounts."""
    editor_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f'.el-row[data-element="{el.pk}"] .el-act-edit').click()
    page.wait_for_selector("[data-zone-editor] .zone-stage")
    return editor_url


def _size_zone_stage(page, w=400, h=300):
    """Pin the zone-editor canvas to a fixed pixel size with a loadable image so the
    pointer-draw fraction math (getBoundingClientRect) works. Returns once non-zero."""
    page.evaluate(
        """([w, h, src]) => {
            const wrap = document.querySelector('.zone-stage-wrap');
            const img = document.querySelector('.zone-stage__img');
            const stage = document.querySelector('.zone-stage');
            if (img) {
                img.src = src;
                img.style.width = w + 'px';
                img.style.height = h + 'px';
            }
            if (wrap) { wrap.style.width = w + 'px'; wrap.style.height = h + 'px'; }
            if (stage) { stage.style.width = w + 'px'; stage.style.height = h + 'px'; }
        }""",
        [w, h, _PNG_DATA_URI],
    )
    page.wait_for_function(
        """() => {
            const s = document.querySelector('.zone-stage');
            if (!s) return false;
            const r = s.getBoundingClientRect();
            return r.width > 50 && r.height > 50;
        }"""
    )


def _draw_zone(page, x0_frac, y0_frac, x1_frac, y1_frac):
    """Pointer-drag on the canvas from one fraction-coord to another to draw a zone.

    zone-editor.js wires Pointer Events (pointerdown/move/up) + setPointerCapture, so we
    dispatch real PointerEvents with explicit client coords (more deterministic than
    Playwright's mouse synthesis, which doesn't always satisfy setPointerCapture)."""
    page.evaluate(
        """([x0, y0, x1, y1]) => {
            const stage = document.querySelector('.zone-stage');
            const r = stage.getBoundingClientRect();
            const pt = (fx, fy) => (
                { x: r.left + r.width * fx, y: r.top + r.height * fy }
            );
            const a = pt(x0, y0), m = pt((x0 + x1) / 2, (y0 + y1) / 2), b = pt(x1, y1);
            function fire(type, p) {
                stage.dispatchEvent(new PointerEvent(type, {
                    bubbles: true, cancelable: true, pointerId: 1, isPrimary: true,
                    clientX: p.x, clientY: p.y,
                }));
            }
            // setPointerCapture needs the element to have the pointer; stub it so the
            // handler's capture call is a harmless no-op under synthetic events.
            stage.setPointerCapture = function () {};
            fire('pointerdown', a);
            fire('pointermove', m);
            fire('pointermove', b);
            fire('pointerup', b);
        }""",
        [x0_frac, y0_frac, x1_frac, y1_frac],
    )


@pytest.mark.django_db(transaction=True)
def test_canvas_existing_zone_drawn_including_corner_origin(live_server, page):
    """Existing zones draw on load at their fractional positions; a zone at
    x=0,y=0,w=0.5,h=0.5 DOES render (the canvas skips only w/h<0.001)."""
    course, unit, q, el = _seed_pa_dragimage(
        "cv_draw",
        "cv-draw",
        zones=[
            {"correct_label": "Corner", "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5},
            {"correct_label": "Mid", "x": 0.6, "y": 0.6, "w": 0.2, "h": 0.2},
        ],
    )
    _login(page, live_server, "cv_draw")
    _open_existing_editor(page, live_server, course, unit, el)
    _size_zone_stage(page)
    # Both existing zones must be drawn as rects (the x=0,y=0 corner zone included).
    assert page.locator(".zone-stage .zone-rect").count() == 2, (
        "both existing zones (including the x=0,y=0 corner zone) must render"
    )


@pytest.mark.django_db(transaction=True)
def test_canvas_draw_zone_creates_zones_0_fields_and_saves(live_server, page):
    """Draw a brand-new zone on a question that starts with ONE zone; the canvas clones
    the empty_form with the REAL formset index (zones-1-*, NOT zones-__prefix__-*), so
    Django parses it. Fill its label, save, confirm the new zone persisted."""
    course, unit, q, el = _seed_pa_dragimage(
        "cv_new",
        "cv-new",
        zones=[{"correct_label": "First", "x": 0.05, "y": 0.05, "w": 0.2, "h": 0.2}],
    )
    _login(page, live_server, "cv_new")
    _open_existing_editor(page, live_server, course, unit, el)
    _size_zone_stage(page)

    assert page.locator(".zone-stage .zone-rect").count() == 1

    # Draw a second zone in the lower-right quadrant.
    _draw_zone(page, 0.55, 0.55, 0.85, 0.85)
    page.wait_for_function(
        "() => document.querySelectorAll('.zone-stage .zone-rect').length === 2"
    )
    # The new row uses the REAL index zones-1-* (not __prefix__).
    new_label = page.locator('[data-zone-rows] [name="zones-1-correct_label"]')
    assert new_label.count() == 1, (
        "new zone row must use zones-1-* (real index), not zones-__prefix__-*"
    )
    new_label.fill("Second")

    # Save via the open edit form's submit (full JS save path).
    page.locator("[data-edit-slot] button[type='submit']").click()
    # The preview re-renders; wait until the DB shows two zones.
    page.wait_for_timeout(800)
    q.refresh_from_db()
    labels = sorted(z.correct_label for z in q.zones.all())
    assert labels == ["First", "Second"], f"drawn zone did not save: {labels!r}"


@pytest.mark.django_db(transaction=True)
def test_canvas_delete_then_order_recompacts_and_saves(live_server, page):
    """Delete the order=0 zone via its × button (row stays with DELETE ticked); after
    save the surviving zone removed-and-recompacted to order=0."""
    course, unit, q, el = _seed_pa_dragimage(
        "cv_del",
        "cv-del",
        zones=[
            {"correct_label": "Gone", "x": 0.05, "y": 0.05, "w": 0.2, "h": 0.2},
            {"correct_label": "Stay", "x": 0.6, "y": 0.6, "w": 0.2, "h": 0.2},
        ],
    )
    _login(page, live_server, "cv_del")
    _open_existing_editor(page, live_server, course, unit, el)
    _size_zone_stage(page)
    assert page.locator(".zone-stage .zone-rect").count() == 2

    # Delete the FIRST drawn rect (order=0, "Gone") via its × delete button.
    page.locator(".zone-stage .zone-rect").first.locator(".zone-rect__del").click()
    page.wait_for_function(
        "() => document.querySelectorAll('.zone-stage .zone-rect').length === 1"
    )
    # The deleted row stays in the DOM with DELETE ticked (so Django removes it).
    assert page.locator('[data-zone-rows] [name$="-DELETE"]:checked').count() == 1

    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_timeout(800)
    q.refresh_from_db()
    survivors = list(q.zones.all())
    assert len(survivors) == 1, f"expected 1 surviving zone, got {len(survivors)}"
    assert survivors[0].correct_label == "Stay"
    assert survivors[0].order == 0, "surviving zone must recompact to order=0"


@pytest.mark.django_db(transaction=True)
def test_canvas_mutationobserver_builds_stage_after_media_pick(live_server, page):
    """Open a NEW drag-to-image form (no image yet → no stage); pick an image via the
    media picker → the MutationObserver on [data-media-preview]'s data-media-url fires
    and the canvas stage appears."""
    # Seed an uploadable image asset on the course so the picker has something to pick.
    owner = _make_pa_user("cv_mo")
    from tests.factories import CourseFactory

    course = CourseFactory(slug="cv-mo", owner=owner)
    _make_media(course)  # one image asset for the picker grid
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    _login(page, live_server, "cv_mo")
    editor_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')

    # Add a new drag-to-image element.
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='dragtoimagequestion']").click()
    page.wait_for_selector("[data-zone-editor]")
    # No image chosen yet → no stage.
    assert page.locator(".zone-stage").count() == 0

    # Drive the MutationObserver directly: set data-media-url on the preview (exactly
    # what media_picker.js does after a pick). The observer must build the stage.
    page.evaluate(
        """([src]) => {
            const p = document.querySelector('[data-zone-editor] [data-media-preview]');
            p.setAttribute('data-media-url', src);
        }""",
        [_PNG_DATA_URI],
    )
    page.wait_for_selector("[data-zone-editor] .zone-stage", timeout=6000)
    assert page.locator(".zone-stage").count() == 1, (
        "MutationObserver must build the canvas stage after the image URL is set"
    )
