"""Behaviour tests for link_dialog.js against the REAL rendered partial.

Playwright as a JS runtime (see tests/test_table_grid_algebra.py). The picker fetch is
stubbed with page.route so no server is needed; everything else -- <dialog>, focus,
tabs, keyboard -- is the genuine browser.
"""

import os
from pathlib import Path

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.e2e

JS_DIR = (
    Path(__file__).resolve().parent.parent / "courses" / "static" / "courses" / "js"
)

# page.set_content leaves the document on about:blank, where a ROOT-RELATIVE fetch
# throws "Failed to parse URL" before it ever reaches the network -- so page.route
# never fires and every test hangs. MEASURED, not assumed. A <base> gives the injected
# document a real origin; the value is arbitrary because the fetch is stubbed.
BASE = "<base href='https://example.test/'>"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Every e2e file in this repo sets this; the fixture below touches the ORM inside a
    # live Playwright session, which raises SynchronousOnlyOperation without it.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


TREE_HTML = """
<ol class="link-picker__scope" role="none">
  <li class="link-picker__item" role="treeitem" aria-level="1" aria-selected="false"
      tabindex="-1" data-node="1" data-title="Algebra" data-href="/courses/n/1/">
    <span class="link-picker__row">Algebra</span>
    <ol class="link-picker__scope" role="group">
      <li class="link-picker__item" role="treeitem" aria-level="2" aria-selected="false"
          tabindex="-1" data-node="2" data-title="Quadratics" data-href="/courses/n/2/">
        <span class="link-picker__row">Quadratics</span>
      </li>
    </ol>
  </li>
</ol>
"""


@pytest.fixture
def dialog_page(page, db):
    """A blank page holding the rendered dialog partial plus both JS modules.

    Yields (rather than returns) so the teardown can assert no uncaught JS error was
    raised anywhere -- including inside a setTimeout or an event listener.
    """
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    routed = {"n": 0}

    def _serve(route):
        routed["n"] += 1
        route.fulfill(status=200, body=TREE_HTML)

    page.route("**/link-picker/", _serve)
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    page.__routed = routed  # so _open can prove the stub was really hit
    # Most of this module runs in listeners, timers and promise catches, where an
    # exception never reaches page.evaluate -- so a broken build can leave assertions
    # green while throwing on every keystroke. Fail loudly instead.
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.__errors = errors
    yield page
    assert not errors, f"uncaught JS errors: {errors}"


def _open(page, **opts):
    page.evaluate(
        """(opts) => {
            window.__result = "PENDING";
            window.__calls = 0;
            window.libliLinkDialog.open(opts, (r) => {
                window.__calls += 1;
                window.__result = r;
            });
        }""",
        {"existing": None, "touchedAnchors": 0, "selectionText": "", **opts},
    )
    page.locator(".link-picker__item").first.wait_for()
    # Prove the stub was actually reached. Without this, a regression to about:blank
    # shows up as an opaque wait_for timeout instead of a clear cause.
    assert page.__routed["n"] >= 1


def _await_dismissed(page, n=1):
    """Wait until the close HANDLER has actually invoked its callback, not merely
    until dialog.close() has run.

    dialog.close() clears the `open` attribute SYNCHRONOUSLY but only QUEUES the
    `close` event as a task (HTML spec: "queue an element task"), so a
    .click()/.press() that triggers it can return before link_dialog.js's own close
    listener -- and therefore the caller's callback, the LAST thing that listener
    does -- has actually run. Reading window.__result, or issuing a second open()
    right after a dismissal, is a genuine race: open()'s `if (callback) return;`
    guard (link_dialog.js) only clears once the handler resets `callback` to null,
    which happens in the SAME queued task as the callback invocation.

    This repo hit the identical class of bug in imagezoom.js (commit b1ec23f3, "wait
    for the close HANDLER, not just for the dialog to shut") and this file
    reproduced it directly under load: a diagnostic that timed dialog.close() against
    its own 'close' event observed the order
    ['after-close-call', 'callback', 'close-event'] (see task-6-report.md).

    window.__calls is incremented INSIDE that same callback by _open()'s wrapper (and
    by the two standalone tests below, which track it the same way), so waiting for
    it to reach `n` proves the handler has fully completed.
    """
    page.wait_for_function(f"() => window.__calls === {n}")


def test_module_exports_when_markup_is_present(dialog_page):
    assert dialog_page.evaluate("() => typeof window.libliLinkDialog") == "object"


def test_module_is_undefined_when_showmodal_is_absent(page, db):
    # The capability gate IS the cross-task contract Task 7 depends on: the export's
    # mere presence is what text_toolbar.js checks before wiring the toolbar button,
    # so a browser lacking <dialog>.showModal must see it absent, not a stub that
    # would throw on first use. Delete the prototype method BEFORE the module runs,
    # on a page that otherwise has the real partial mounted.
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    page.evaluate("() => { delete HTMLDialogElement.prototype.showModal; }")
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    assert (
        page.evaluate("() => typeof document.createElement('dialog').showModal")
        == "undefined"
    )
    assert page.evaluate("() => typeof window.libliLinkDialog") == "undefined"


def test_module_is_undefined_when_markup_is_absent(page):
    # The other half of the same gate: a page that loads this script without Task 5's
    # partial mounted must not export either, or text_toolbar.js's capability check
    # would pass and then throw on a null query.
    #
    # The uncaught-error assertion is load-bearing, not decoration: the guard this
    # covers is `if (!dialog) return;` (link_dialog.js), and removing JUST that line
    # still leaves `typeof window.libliLinkDialog` "undefined" -- the very next
    # statement dereferences the null `dialog` and throws, which ALSO stops the
    # export from being reached. Without checking for that thrown error, this test
    # cannot tell a graceful early-return from an accidental crash.
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_content(f"{BASE}<main><p>no dialog here</p></main>")
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    assert page.evaluate("() => typeof window.libliLinkDialog") == "undefined"
    assert not errors, f"uncaught JS errors: {errors}"


def test_initial_focus_is_the_filter_input(dialog_page):
    # showModal() autofocuses the first focusable DESCENDANT -- which is the first tab
    # button -- so the focus call must happen AFTER showModal, not before.
    _open(dialog_page)
    focused = dialog_page.evaluate(
        "() => document.activeElement.getAttribute('data-link-filter') !== null"
    )
    assert focused is True


def test_default_tab_is_in_this_course(dialog_page):
    _open(dialog_page)
    assert (
        dialog_page.locator("[data-tab='node']").get_attribute("aria-selected")
        == "true"
    )


def test_tab_toggle_sets_is_on_and_hidden(dialog_page):
    # editor.css styles the active tab as .picker__tab.is-on and hides panels via
    # .picker__panel[hidden]. Without BOTH, two panels render at once.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    assert dialog_page.locator("[data-tab='url']").evaluate(
        "el => el.classList.contains('is-on')"
    )
    assert dialog_page.locator("[data-panel='node']").is_hidden()
    assert dialog_page.locator("[data-panel='url']").is_visible()


def test_tabs_are_a_single_tab_stop_with_arrow_keys(dialog_page):
    # role="tab" implies the tablist keyboard contract. Half the pattern -- roles
    # without roving tabindex and Left/Right -- is worse than no roles at all.
    _open(dialog_page)
    tabindexes = dialog_page.evaluate(
        "() => Array.from(document.querySelectorAll('.picker__tab'))"
        ".map(t => t.tabIndex)"
    )
    assert sorted(tabindexes) == [-1, 0]
    dialog_page.locator("[data-tab='node']").focus()
    dialog_page.keyboard.press("ArrowRight")
    assert (
        dialog_page.locator("[data-tab='url']").get_attribute("aria-selected") == "true"
    )


def test_enter_selects_a_row_and_never_inserts(dialog_page):
    _open(dialog_page)
    dialog_page.keyboard.press("Tab")  # filter -> the tree's single tab stop
    dialog_page.keyboard.press("Enter")
    assert dialog_page.locator("[aria-selected='true'][data-node]").count() == 1
    assert dialog_page.evaluate("() => window.__result") == "PENDING"


def test_arrow_down_moves_within_the_roving_set(dialog_page):
    _open(dialog_page)
    dialog_page.keyboard.press("Tab")
    dialog_page.keyboard.press("ArrowDown")
    dialog_page.keyboard.press("Enter")
    assert (
        dialog_page.locator("[aria-selected='true'][data-node]").get_attribute(
            "data-node"
        )
        == "2"
    )


def test_enter_in_the_url_field_inserts(dialog_page):
    # Spec: "Enter presses Insert from the URL field and the Link text field only ...
    # without this rule Enter would do nothing anywhere." Nothing else exercises it.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill("https://ok.test/a")
    dialog_page.locator("[data-link-text]").fill("Ref")
    dialog_page.locator("[data-link-url]").press("Enter")
    _await_dismissed(dialog_page)
    assert dialog_page.evaluate("() => window.__result") == {
        "href": "https://ok.test/a",
        "text": "Ref",
    }


def test_insert_returns_href_and_text(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-node='2']").click()
    dialog_page.locator("[data-link-text]").fill("Quadratics")
    dialog_page.locator("[data-link-insert]").click()
    _await_dismissed(dialog_page)
    assert dialog_page.evaluate("() => window.__result") == {
        "href": "/courses/n/2/",
        "text": "Quadratics",
    }


def test_url_is_normalised_in_the_field_before_insert(dialog_page):
    # The spec promises "the normalised value is shown before inserting". Normalising
    # only inside the insert handler would close the dialog on the next statement, so
    # the author would never see it.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill("example.com")
    dialog_page.locator("[data-link-url]").blur()
    assert dialog_page.locator("[data-link-url]").input_value() == "https://example.com"


@pytest.mark.parametrize(
    "value,key",
    [
        ("javascript:alert(1)", "scheme"),
        ("//evil.com/x", "protocol-relative"),
        ("/path", "relative"),
    ],
)
def test_rejected_url_shows_its_own_message_and_disables_insert(
    dialog_page, value, key
):
    # All THREE reject keys, because msg() no-ops silently when a key has no element:
    # rename one and the author gets a disabled Insert with no explanation, suite green.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill(value)
    dialog_page.locator("[data-link-text]").fill("x")
    assert dialog_page.locator(f"[data-msg='{key}']").is_visible()
    assert dialog_page.locator("[data-link-insert]").is_disabled()


@pytest.mark.parametrize("how", ["cancel", "escape", "backdrop"])
def test_every_dismissal_path_fires_the_callback_exactly_once(dialog_page, how):
    _open(dialog_page)
    if how == "cancel":
        dialog_page.locator("[data-link-cancel]").click()
    elif how == "escape":
        dialog_page.keyboard.press("Escape")
    else:
        # A modal <dialog> does NOT close on a backdrop click by itself; the content
        # lives in an inner card so e.target === dialog means the backdrop.
        # Click demonstrably OUTSIDE the dialog's own box: bounding_box() returns the
        # <dialog>, not the backdrop, and the card fills it (padding: 0), so a point
        # just inside the corner hits the card and only "works" if the border-radius
        # happens to reject that pixel -- a coincidence, not a contract.
        box = dialog_page.locator(".link-dialog").bounding_box()
        x, y = 10, 10
        assert x < box["x"] or y < box["y"], (x, y, box)
        dialog_page.mouse.click(x, y)
    _await_dismissed(dialog_page)
    assert dialog_page.evaluate("() => window.__calls") == 1
    assert dialog_page.evaluate("() => window.__result") is None


def test_a_second_open_while_pending_is_rejected(dialog_page):
    _open(dialog_page)
    dialog_page.evaluate(
        "() => { window.__second = 0;"
        " window.libliLinkDialog.open({existing: null, touchedAnchors: 0,"
        " selectionText: ''}, () => { window.__second += 1; }); }"
    )
    dialog_page.locator("[data-link-cancel]").click()
    _await_dismissed(dialog_page)
    # The FIRST callback stands and fires once; the second never registers.
    assert dialog_page.evaluate("() => window.__calls") == 1
    assert dialog_page.evaluate("() => window.__second") == 0


def test_a_second_open_starts_clean(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-node='2']").click()
    dialog_page.locator("[data-link-filter]").fill("quad")
    dialog_page.locator("[data-link-cancel]").click()
    # Without this wait, open()'s `if (callback) return;` guard (link_dialog.js:300)
    # can still see the FIRST session's callback -- reset only once the close
    # handler's queued task runs -- and silently no-op this second open() entirely.
    _await_dismissed(dialog_page)
    _open(dialog_page)
    assert dialog_page.locator("[data-link-filter]").input_value() == ""
    assert dialog_page.locator("[aria-selected='true'][data-node]").count() == 0
    assert dialog_page.locator("[data-link-text]").input_value() == ""


def test_existing_internal_link_preselects_its_row(dialog_page):
    _open(
        dialog_page,
        existing={"href": "/courses/n/2/", "text": "Quadratics"},
        touchedAnchors=1,
    )
    assert (
        dialog_page.locator("[aria-selected='true'][data-node]").get_attribute(
            "data-node"
        )
        == "2"
    )
    assert dialog_page.locator("[data-link-remove]").is_enabled()


def test_remove_returns_remove_true(dialog_page):
    # Task 4's test_link_apply.py proves link_apply.js correctly consumes an
    # already-formed {remove: true}; nothing proved link_dialog.js's own Remove
    # button (link_dialog.js:265, commit({remove: true})) actually EMITS it.
    _open(
        dialog_page,
        existing={"href": "/courses/n/2/", "text": "Quadratics"},
        touchedAnchors=1,
    )
    dialog_page.locator("[data-link-remove]").click()
    _await_dismissed(dialog_page)
    assert dialog_page.evaluate("() => window.__result") == {"remove": True}


def test_target_not_in_this_course_explains_itself(dialog_page):
    _open(
        dialog_page,
        existing={"href": "/courses/n/999/", "text": "gone"},
        touchedAnchors=1,
    )
    assert dialog_page.locator("[data-msg='foreign']").is_visible()
    assert dialog_page.locator("[data-link-url]").input_value() == "/courses/n/999/"


def test_no_match_hides_the_tree_and_says_so(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-link-filter]").fill("zzz-nothing")
    assert dialog_page.locator("[data-msg='nomatch']").is_visible()
    # The zero-match line must sit INSIDE the live region, or the state the debounce
    # exists to convey is never announced.
    assert dialog_page.locator("[data-link-status] [data-msg='nomatch']").count() == 1


def test_the_live_region_announces_a_labelled_count(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-link-filter]").fill("quad")
    dialog_page.wait_for_timeout(600)  # past the 400ms debounce
    text = dialog_page.locator("[data-link-count]").inner_text().strip()
    assert text.startswith("1 ")
    assert len(text) > 2, "a naked digit is not an announcement"


def test_filter_keeps_ancestor_context_and_hides_dead_branches(dialog_page):
    """The two behaviours the ancestor loop exists for.

    Deleting that loop wholesale leaves every other test green: they all read `shown`,
    which is computed BEFORE it runs. So this is the only guard on it.
    """
    _open(dialog_page)
    # "quad" matches the child only. Its parent must stay VISIBLE as path context, but
    # aria-disabled so it cannot be selected.
    dialog_page.locator("[data-link-filter]").fill("quad")
    parent = dialog_page.locator("[data-node='1']")
    assert parent.is_visible()
    assert parent.get_attribute("aria-disabled") == "true"
    assert (
        dialog_page.locator("[data-node='2']").get_attribute("aria-disabled") == "false"
    )

    # "algebra" matches the parent only. The child has no matching descendant, so it is
    # hidden outright rather than left as dead context.
    dialog_page.locator("[data-link-filter]").fill("algebra")
    assert dialog_page.locator("[data-node='1']").is_visible()
    assert dialog_page.locator("[data-node='2']").is_hidden()


def test_the_tree_keeps_exactly_one_tab_stop_when_the_filter_hides_the_selection(
    dialog_page,
):
    """The stranding hazard setTabStop's comment names, in the only state reaching it.

    Every other test runs with an empty filter, where nothing is hidden or
    aria-disabled -- so rovingSet's two exclusions and setTabStop's
    `set.indexOf(sel) !== -1` guard are never exercised at all.
    """
    _open(dialog_page)
    dialog_page.locator("[data-node='2'] > .link-picker__row").click()
    dialog_page.locator("[data-link-filter]").fill("algebra")  # hides the selection

    stops = dialog_page.evaluate(
        "() => Array.from("
        "document.querySelectorAll('[data-link-tree] .link-picker__item')"
        ").filter(r => r.tabIndex === 0).map(r => r.dataset.node)"
    )
    assert stops == ["1"], stops
    # The selection itself SURVIVES being filtered out -- it is the tab's target
    # regardless of visibility.
    assert (
        dialog_page.locator("[data-node='2']").get_attribute("aria-selected") == "true"
    )


def test_a_failed_fetch_is_not_cached_and_retries_on_the_next_open(page, db):
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    calls = {"n": 0}

    def handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=500, body="nope")
        else:
            route.fulfill(status=200, body=TREE_HTML)

    page.route("**/link-picker/", handler)
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))

    # window.__calls, tracked the same way _open() tracks it, lets this standalone
    # test reuse _await_dismissed below rather than a bespoke wait.
    page.evaluate(
        """() => {
            window.__calls = 0;
            window.libliLinkDialog.open(
                {existing: null, touchedAnchors: 0, selectionText: ''},
                () => { window.__calls += 1; }
            );
        }"""
    )
    page.locator("[data-msg='fetch']").wait_for()
    page.locator("[data-link-cancel]").click()
    # This is the exact race this test reproduced under load (see task-6-report.md):
    # without waiting for the close handler's queued task, the second open() below
    # can arrive while `callback` is still non-null and get silently rejected --
    # which then hangs the .link-picker__item wait_for for its full 30s timeout.
    _await_dismissed(page)

    page.evaluate(
        "() => window.libliLinkDialog.open("
        "{existing: null, touchedAnchors: 0, selectionText: ''}, () => {})"
    )
    page.locator(".link-picker__item").first.wait_for()
    assert calls["n"] == 2


def test_dismissing_mid_fetch_does_not_paint_a_fetch_error(page, db):
    # A deliberate abort must be distinguishable from a failure, or a clean dismissal
    # toggles the error line on.
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    page.route("**/link-picker/", lambda route: None)  # never resolves
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    page.evaluate(
        "() => window.libliLinkDialog.open("
        "{existing: null, touchedAnchors: 0, selectionText: ''}, () => {})"
    )
    page.locator("[data-link-cancel]").click()
    assert page.locator("[data-msg='fetch']").is_hidden()
