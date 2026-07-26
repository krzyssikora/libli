# Internal content links — dialog and permalink

Part 1 of two. Part 2 (`2026-07-26-internal-link-durability-design.md`) makes these links survive
export→import and warns before a linked node is deleted. Part 1 is shippable on its own, with one
named risk carried until part 2 lands (see §Error handling, "target now lives in another course").

## Purpose

A Course Admin writing a lesson cannot point at another place in the same course. "See the section
on quadratics" is prose the student has to act on by hand — back to the outline, scan, click. The
only linking affordance in the rich-text toolbar is a chain-link button that calls
`window.prompt("URL")` and `document.execCommand("createLink")`: no way to see or edit the URL of a
link already in the text, no way to remove one, no way to set the link text, and nothing whatsoever
about the course being edited.

This replaces that button's behaviour with a real dialog covering both kinds of link:

- **In this course** — pick a node (part / chapter / section / unit) from the course tree; when there
  is no selected text, the link text defaults to the node's title.
- **Web address** — an ordinary URL, but now with an edit path instead of a one-shot prompt.

## Scope

**In scope**

- A slug-free permalink route + view resolving a `ContentNode` to its reader-facing page.
- Per-node anchors on the course outline, so non-unit nodes are linkable at all.
- The link dialog: server-rendered partials, `link_dialog.js`, and `link_apply.js` — the extracted,
  testable mutation module — plus the `text_toolbar.js` change that wires them together.
- A picker endpoint serving the course tree to the dialog.
- Student-side styling distinguishing internal from external links.

**Files touched**

| file | change |
|---|---|
| `courses/urls.py` | two routes: `node_permalink`, `manage_link_picker` |
| `courses/views.py` | `node_permalink` |
| `courses/views_manage.py` | `link_picker` |
| `templates/courses/manage/editor/editor.html` | `{% include %}` of the dialog partial **outside every `[data-scope]`** (see §4); `<script>` tags for `link_apply.js` and `link_dialog.js` |
| `templates/courses/manage/editor/_link_dialog.html` | **new** — the dialog markup, all strings `{% trans %}`, carries `data-link-picker-url` on its root |
| `templates/courses/manage/editor/_link_picker.html` | **new** — the root `<ol role="tree">`; the template `link_picker` renders |
| `templates/courses/manage/editor/_link_picker_node.html` | **new** — one `<li>` + its nested child list, self-including |
| `templates/courses/_outline_node.html` | per-node `id` |
| `courses/static/courses/js/link_apply.js` | **new** — anchor enumeration + insertion rules + removal, exported as `window.libliLinkApply` so it is testable (see §Testing) |
| `courses/static/courses/js/link_dialog.js` | **new** — the dialog itself |
| `courses/static/courses/js/text_toolbar.js` | `case "link":` — stash the range, call the dialog, hand the result to `libliLinkApply` |
| `courses/static/courses/css/editor.css` | dialog + picker styling, duplicated `.tree__badge*` rules, and the preview-inert rule |
| `courses/static/courses/css/courses.css` | `:target` highlight, internal/external link affordances |

**Out of scope, deliberately**

- *Any change to `courses/sanitize.py`.* Measured, not assumed: `sanitize_html` already passes
  relative hrefs through untouched. Run against the current sanitiser —

  ```text
  '<a href="/courses/x/u/12/">u</a>'   -> '<a href="/courses/x/u/12/">u</a>'
  '<a href="/courses/x/#node-3">c</a>' -> '<a href="/courses/x/#node-3">c</a>'
  '<a href="libli:node:12">x</a>'      -> '<a>x</a>'                    # href stripped
  '<a href="/a/" data-node="12">y</a>' -> '<a href="/a/">y</a>'         # data-* stripped
  '<a href="/a/" class="internal">z</a>'-> '<a href="/a/">z</a>'        # class stripped
  ```

  The first two lines are why an internal link can be a plain relative anchor. The last three are
  why it *must* be — a custom scheme, a marker attribute, or a marker class would all need the
  sanitiser widened, and none of them buy anything the href prefix does not already give us.

- **An "open in a new tab" control.** `ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}}` — the
  sanitiser strips `target`, so such a checkbox would silently do nothing.

- **Table and fill-table cells.** `sanitize_cell` allows `CELL_TAGS = {strong, b, em, i, u, br}` —
  no `<a>` at all. A link authored into a cell would be silently stripped on save.

- **Cross-course links.** The picker shows one tree: the course being edited. A link to another
  course would land any student not enrolled there on a 404, and — see part 2 — could not be
  rewritten on export anyway. Pasting an absolute URL in the *Web address* tab remains possible.

- **Changing who can read a unit page.** §1 records a predicate mismatch (a manager who is not an
  accessor 404s on a link they authored). Widening that is an app-wide access change, not a linking
  feature; it is named, tested and left alone.

- **A link audit page**, and **`core.help` role manuals.** Both reasonable follow-ups; neither needed
  to ship. No committed help screenshot covers the editor toolbar, so none needs regenerating.

## Architecture / components

### 1. The permalink route — `courses/urls.py`, `courses/views.py`

```python
path("courses/n/<int:node_pk>/", views.node_permalink, name="node_permalink"),
```

Verified free: `resolve("/courses/n/12/")` raises `Resolver404` against the current URLconf. No
collision with `courses/<slug:slug>/`, which matches two path segments where this matches three.
(`/courses/n/` — a course whose slug is literally `n` — still resolves to `course_outline`.)

```python
@login_required
def node_permalink(request, node_pk):
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if not can_access_course(request.user, node.course):
        raise Http404("node is not accessible")     # NOT PermissionDenied — see below
    if node.kind == ContentNode.Kind.UNIT:
        name = ("courses:quiz_unit" if node.unit_type == ContentNode.UnitType.QUIZ
                else "courses:lesson_unit")
        return redirect(name, slug=node.course.slug, node_pk=node.pk)
    return redirect(
        reverse("courses:course_outline", kwargs={"slug": node.course.slug})
        + f"#node-{node.pk}"
    )
```

**404, not 403, for an inaccessible node.** This follows the convention `get_node_or_404` states in
its own docstring: *"Access (403) is checked by the caller AFTER this returns, so a foreign node
always 404s before any 403."* Every other node-addressed view scopes by slug first, so a node in a
course you cannot see 404s. The permalink carries no slug to scope against, so returning 403 would
make it the one route that answers "does node 4711 exist?" for any logged-in user — a node and
course enumeration oracle.

**Known: a manager who is not an accessor 404s on their own link.** The two predicates are not
nested. `can_manage_course` is *owner OR the `courses.change_course` perm*, and its docstring notes
it deliberately does **not** key on `is_staff`; `can_access_course` is *staff OR owner OR enrolled OR
teaches a non-archived group*. A Platform Admin holding `change_course` who neither owns the course,
is enrolled, nor is `is_staff` — the production shape of that role — can open the editor, insert a
link, and then get a 404 following it.

Widening the permalink's check would not help: it redirects to `lesson_unit` / `quiz_unit`, which run
`can_access_course` themselves and would 403. Such a user cannot read *any* unit page today, by any
route — a pre-existing property of the app, not something the permalink introduces. Recorded here,
listed in §Error handling, and pinned by a test.

The quiz branch is explicit rather than delegated. `lesson_unit` does redirect a quiz unit onward to
`quiz_unit`, so delegating would work — but it would cost a second redirect hop on every quiz link
and couple this view to another's implementation detail.

Storing a slug-free permalink is the point: `/courses/n/1234/` keeps working when a course is
re-slugged, and the redirect target can change without touching a single stored body.

**Nothing in JavaScript constructs this URL.** The picker partial emits it per row with `{% url %}`
(§3) and the JS copies the attribute verbatim. The CSS selector in §5 is the one place the literal
prefix is duplicated, and §Testing ties the two together.

### 2. Outline anchors — `templates/courses/_outline_node.html`, `courses.css`

The `<li>` gains `id="node-{{ item.node.pk }}"`, uniformly for every kind — the `<li>` is shared
markup and a `{% if %}` around an `id` earns nothing.

**The `id` goes on the `<li>`; the highlight does not.** A non-unit `<li>` contains both
`.outline-node__head` *and* the nested `<ul>` of every descendant, so `li:target { background: … }`
would tint an entire part's subtree — most of the page. The `<li>` is the scroll target; the
highlight is scoped to the row, and the template's two branches render different row elements:

```css
.outline-node:target > .outline-node__head { /* non-unit rows */ }
.outline-node:target > .outline-unit       { /* unit rows */ }
```

`scroll-margin-top` goes on the `<li>`. **Its reason is breathing room, not sticky chrome** —
measured: `.app-header` is `position: relative` (`app.css:22`) and `outline.html` renders `.outline`
in the normal `.app-main` flow, so nothing overlays the target row. If implementation finds the flush
landing acceptable, dropping the declaration is fine; what must not survive is a false justification
for keeping it.

The highlight must be legible in both themes — judged separately, not inferred from the light
screenshot.

### 3. Picker endpoint — `courses/views_manage.py`, `_link_picker.html`, `_link_picker_node.html`

```python
path("manage/courses/<slug:slug>/link-picker/", views_manage.link_picker,
     name="manage_link_picker"),
```

`@login_required`, `can_manage_course` or `PermissionDenied`, then renders the course tree from the
existing `_children_map(course)` helper — one query, `parent_id -> [children]`, already used by the
builder view. Like `builder`, the view passes `children_map` **plus** `top_nodes = cmap.get(None, [])`:
`_children_map` keys roots under `None`, which a template cannot index.

**Two templates, because a view cannot loop.** `link_picker` renders `_link_picker.html` — the root
`<ol class="link-picker__scope" role="tree">` iterating `top_nodes` — which includes
`_link_picker_node.html` per row. Both render **standalone** (no `base.html`), because the dialog
injects the markup directly.

**The row partial must `{% load courses_manage_extras %}` and reach its children with
`children_map|get_item:n.pk`.** A Django template cannot index a dict by a variable key — that is why
`_tree_node.html:44` uses the same filter — so without it the recursion is unimplementable.

Row shape, with the recursive include written out in full, because the rebind is the other half of
the same hazard — omit it and you get infinite recursion on the same node, or silently empty children:

```html
{% load courses_manage_extras %}
<li class="link-picker__item" role="none">
  <button type="button" class="link-picker__row" role="treeitem"
          aria-level="{{ level }}" aria-selected="false" tabindex="-1"
          data-node="{{ n.pk }}" data-title="{{ n.title }}"
          data-href="{% url 'courses:node_permalink' node_pk=n.pk %}">…badge… {{ n.title }}</button>
  {% with children=children_map|get_item:n.pk %}
    {% if children %}
      <ol class="link-picker__scope" role="group">
        {% for child in children %}
          {% include "courses/manage/editor/_link_picker_node.html" with n=child children_map=children_map level=level|add:1 %}
        {% endfor %}
      </ol>
    {% endif %}
  {% endwith %}
</li>
```

A `<button>` rather than a `<div>` with a click handler: the picker is the primary control of the
whole feature, and a div-with-listener is unreachable by keyboard.

**Tree semantics, not a list of buttons.** The root carries `role="tree"`, nested lists
`role="group"`, and each row `role="treeitem"` with `aria-level` and `aria-selected`. This is not
decoration: a roving-tabindex, arrow-key control that announces itself as a plain list of buttons
gives a screen-reader user movement they have no reason to expect and conveys none of the nesting the
indentation carries — "Quadratics" at depth 3 would be indistinguishable from a top-level part, which
is exactly the disambiguation the L/Q chip decision says matters. `role="tree"` is also what makes
the arrow-key model the *expected* contract rather than a surprise. Selection is `aria-selected`
throughout — deliberately not `aria-pressed`, so the tabs (§4) and the tree never share a vocabulary.

**The chip mirrors the builder's vocabulary, including the unit branch.** `_tree_node.html` does not
render `get_kind_display` for units — it renders an `L` or `Q` chip
(`tree__badge tree__badge--unit tree__badge--lesson|--quiz`) with `title="{{ n.get_unit_type_display }}"`,
and the kind label only for non-units. The picker does the same, and not merely for consistency: the
permalink sends a lesson unit and a quiz unit to *different pages*, so an author choosing a target
must be able to tell them apart. Note `--lesson` / `--quiz` carry no declarations in `builder.css`
today — they are markup hooks — so only `.tree__badge`, `--part/--chapter/--section` and `--unit`
have rules to duplicate.

**Keyboard model: roving tabindex.** The tree is **one** tab stop, not ~925. Up/Down move focus
within the roving set, Home/End jump to its ends, and **Enter or Space presses the focused row** —
Enter here selects a row; it never fires *Insert* (see §4).

The **roving set is the visible, non-`aria-disabled` rows**. Ancestor-context rows surfaced by a
filter are marked `aria-disabled="true"` with a click no-op — deliberately *not* the `disabled`
attribute, which would make them unfocusable and could leave the tree with no reachable tab stop.

The tab stop is a function of the roving set alone: **the selected row if it is in the roving set,
else the first row in the roving set, else no tab stop at all** (focus stays in the filter input). The
qualifier matters — a filter that hides the selected row would otherwise put `tabindex="0"` on a
hidden, unfocusable element and strand the tree, reintroducing by another route exactly the failure
the `aria-disabled` decision avoided. The tab stop is re-assigned whenever the filter changes.

**Per-row `{% url %}` is a real cost, accepted with its number.** The permalink is per-node, so —
unlike the builder's rename URL — it cannot be hoisted: a 925-node picker pays ~925 reversals, on the
order of 60 ms at the ~64 µs the builder's own comment records. Accepted because it is paid **once
per editor page** (the response is cached), and because the alternative — emitting a template against
a sentinel pk and substituting in JS — puts URL construction back into JavaScript, which §1 exists to
prevent. That hoist is the escape hatch if the cost ever shows up.

**Styling: only the badge is borrowed.** Layout uses picker-local `.link-picker__*` classes defined
in `editor.css`. The builder's `.tree__scope` / `.tree__row` / `.tree__rowhead` are *not* referenced,
because they live in `builder.css`, which the editor page does not load — borrowing the names would
ship an unindented, unstyled list. The one exception is the `.tree__badge*` rules
(`builder.css:35-37`), duplicated into `editor.css` with a comment naming its twin.

That the editor page does not load `builder.css` is **convention, not currently asserted**:
`tests/test_editor_styles.py` says so in its module docstring, but its single test only checks that
`editor.css` contains `.tree__act` and friends — adding `builder.css` to the editor page today would
keep the suite green. §Testing adds the missing guard rather than continuing to cite prose as a
mechanism.

The tree mount carries an explicit `max-height` and `overflow-y: auto`. A UA `<dialog>` caps at
roughly the viewport, so without it a 925-row list either overflows or grows the dialog past the
screen.

Whole-tree-in-one-response is deliberate. The largest real course (`mat-pp`) is ~925 nodes; at
roughly 150–200 bytes per row that is on the order of 150–200 KB — an order-of-magnitude estimate
worth re-checking against the real row markup. The media picker searches server-side because a media
library is unbounded and its rows carry thumbnails; a course tree is neither.

**Fetch policy.** The request sends `X-Requested-With: fetch`, matching `media_picker.js`; the view
does not gate on it. Only a **successful** response is cached, for the life of the page. A failure is
retried on the next `open()` (the error line carries a retry control), so one transient blip cannot
disable the feature for the rest of a long-lived session. A second `open()` while a fetch is in
flight reuses the pending request; a fetch still in flight when the dialog closes is aborted.

**The fetched markup is assigned with `innerHTML`.** It is server-rendered and autoescaped, so this
is correct; the never-`innerHTML` rule in §4 governs only author-supplied strings crossing into an
editing surface.

**Cache staleness is accepted.** A node renamed in another tab will not appear until the editor page
is reloaded. Re-fetching per open would cost a ~200 KB round trip for a tree that rarely changes
during an editing session.

**The unit being edited is included** and selectable. A self-link is odd but harmless, and excluding
it would need the picker to know which unit hosts the element.

**Filtering** matches a case-insensitive substring of the node title only (not the kind label, which
is a translated word and would match half the tree in Polish). A matching row keeps its ancestors
visible, `aria-disabled` and visually recessed if they do not themselves match, so the indentation
still reads as a path.

The message region carries `aria-live="polite"` and a match count, **announced on a short debounce**
(and on transitions into or out of the zero-match state). Without the debounce a polite region
re-announces on every keystroke, queueing one utterance per character and drowning the "No matches."
case it exists to convey.

Because the tree DOM is cached and `aria-selected` is the only record of the target, **every `open()`
resets the panel first**: filter cleared, every row deselected and re-shown, roving tabindex reset,
URL and link-text fields cleared — and only then is any preselection applied. Without this the second
open arrives pre-armed with the previous session's target and filter.

**A preselected row is scrolled into view** with `scrollIntoView({block: "nearest"})`, on both the
immediate and the deferred (payload-arrives-late) path. In a capped scroll box, selecting a row 600
rows down otherwise leaves the author looking at an apparently unselected tree — with the tab stop on
a row they cannot see — in exactly the re-edit flow this dialog exists to provide.

Picker states, defined rather than left to chance:

| state | behaviour |
|---|---|
| tree not yet fetched (first open) | pre-rendered translated "Loading…" line; *Insert* disabled on this tab. A preselection requested before the payload arrives is applied when it resolves, unless the author has already pressed a row. |
| fetch failed | pre-rendered inline error plus a retry control; not cached, so the next open retries. The *Web address* tab still works. |
| course has no nodes | translated "This course has no content yet."; *Insert* stays disabled on this tab |
| filter matches nothing | translated "No matches."; the tree is hidden, not emptied; focus stays in the filter |
| filter cleared | the full tree returns, with any prior selection still selected |
| the selected row is hidden by the filter | the selection **survives** (it is the tab's target regardless of visibility), and the tab stop moves to the first row of the roving set |

### 4. The dialog — `_link_dialog.html`, `link_dialog.js`, `link_apply.js`, `text_toolbar.js`

**The dialog markup is server-rendered**, as `_link_dialog.html`, included once by `editor.html`.
Not a stylistic choice: the repo has **no** `JavaScriptCatalog` / `jsi18n` route, so `makemessages`
cannot extract a string that exists only inside a `.js` file. Every other JS-driven UI works around
that with `data-msg-*` attributes (`math_input.js` reads `data-msg-insert` / `-cancel` / `-math`); a
dialog with a dozen strings would turn that workaround into a sprawl.

**The include must sit outside every `[data-scope]` element.** `editor.js` replaces the
`[data-scope="editor"]` and `[data-scope="preview"]` panes and re-runs `window.libliInitRte`. Dropped
inside a swapped pane, the `<dialog>` and its listeners are destroyed on the first save — an
intermittent dead toolbar button that is painful to attribute. The include goes as a child of
`section.editor`, after `_editor_scope.html`. The static test is phrased on the invariant: *the
dialog markup is outside every `[data-scope]` element*.

**Feature detection — two conditions, both leaving `window.libliLinkDialog` undefined.**
`link_dialog.js` bails when `typeof document.createElement("dialog").showModal !== "function"`
(following `imagezoom.js`) **and** when `document.querySelector(".link-dialog")` is null. The export
is the capability signal, not merely a platform signal: a page that loaded the script without the
include would otherwise pass `text_toolbar.js`'s guard and throw on a null query. In either case the
link button does nothing — an accepted regression from `window.prompt` on browsers lacking
`<dialog>`, on the grounds `imagezoom.js` already accepted.

**Markup** (`<dialog class="link-dialog">`, in the page from first paint, closed):

- `data-link-picker-url="{% url 'courses:manage_link_picker' slug=course.slug %}"` on the dialog
  root, mirroring how `editor.html:12` emits `data-picker-url`. The module owns the fetch, so it owns
  the URL; putting it on `section.editor` would make `text_toolbar.js` responsible for a picker
  concern and pass it through `open()`.
- a translated dialog title, referenced by `aria-labelledby` on the `<dialog>` (the precedent sets
  one — `math_input.js` applies `aria-label` from `data-msg-math`);
- an inner wrapper holding all content; the `<dialog>` itself carries no padding, so a click whose
  `e.target` is the dialog means the backdrop and nothing else (see Dismissal);
- a **complete tablist**: `role="tablist"` on `.picker__tabs`, two `<button type="button" role="tab"
  aria-selected>` tabs, and `role="tabpanel"` + `aria-labelledby` on each `.picker__panel`, with
  Left/Right moving between the two tabs as a single tab stop. Half the pattern — `role="tab"`
  without the tablist and panels — would be worse than the media picker's role-free tabs it borrows
  the classes from: AT would announce orphaned tabs with no position or count, and imply a keyboard
  contract nothing implements.
- the **In this course** panel: a filter `<input type="search">`, the tree mount, and an
  `aria-live="polite"` message region holding the pre-rendered loading / empty / no-match /
  fetch-error+retry / target-not-in-this-course lines;
- the **Web address** panel: a URL `<input type="url">` and one pre-rendered message element per
  distinct rejection;
- a shared **Link text** `<input type="text">`;
- **Remove link** / **Cancel** / **Insert**, all `type="button"`.

Every button carries an explicit `type="button"`, including the tabs — `editor.html` is full of
forms, and a form-associated bare `<button>` defaults to `type="submit"`, so Insert would post the
element form.

**The reused tab classes come with a contract:** `editor.css` styles the active tab as
`.picker__tab.is-on` and hides panels via `.picker__panel[hidden]` — the pair `media_picker.js`
already toggles. The JS must add/remove `is-on` and set/remove `hidden`, or both panels render at
once.

**Default tab** on a fresh open is **In this course** — the feature's reason to exist. An existing
link opens on the tab matching what is stored. **Initial focus** is the filter input on the internal
tab and the URL input on *Web address*. `showModal()` traps focus because the dialog has focusable
children — the image-zoom caveat (a dialog with *no* focusable child does not trap) does not apply.

**Messages are shown, never composed** — each is a pre-rendered element JS only toggles, so no string
is assembled in JavaScript.

**Ownership is split three ways.**

- `link_dialog.js` owns its own dialog DOM — tabs, fetch, filter, validation — and never touches an
  editing surface. It returns a decision.
- `link_apply.js` owns every surface mutation: anchor enumeration, insertion rules 1/2/3, and
  removal. It is a separate module **because it must be testable** — see §Testing; there is no jsdom
  in this repo, and the only way to unit-test JS here is to load a module in a real browser and call
  its exports.
- `text_toolbar.js` wires them: stash the range, ask the dialog, hand the result to the applier.

```js
// link_dialog.js — owns only its own dialog. Knows nothing about the surface or the Range.
window.libliLinkDialog.open({ existing, touchedAnchors, selectionText }, cb);
//   existing:       {href, text} | null   — set iff exactly one anchor ENCLOSES the range
//   touchedAnchors: integer               — see enumeration below
//   selectionText:  string                — "" when the range is collapsed
//   cb(result):     {href, text} | {remove: true} | null      (null = dismissed)

// link_apply.js — pure DOM, no dialog, no network. Testable in a real browser.
window.libliLinkApply.anchorsFor(surface, range);   // -> [<a>, ...]
window.libliLinkApply.enclosing(surface, range);    // -> <a> | null
window.libliLinkApply.apply(surface, range, result);// -> performs rule 1/2/3 or removal
```

`text_toolbar.js`'s `case "link":`:

1. guards with `if (!window.libliLinkDialog) break;`, as the math command guards on
   `window.libliMathInput`;
2. stashes **`sel.getRangeAt(0).cloneRange()`** — see below;
3. derives `existing` and `touchedAnchors` via `libliLinkApply`;
4. calls `open()`;
5. **on a non-null result:** re-focuses the surface, re-derives `window.getSelection()`, restores the
   stashed range, calls `libliLinkApply.apply(...)`, collapses the selection **after** the resulting
   anchor (for a removal, at the end of the recovered text), and dispatches `new Event("input")` —
   which drives `sync()` into the hidden textarea;
6. **on `null`:** re-focuses the surface and re-applies the stashed range, so the caret returns where
   the author left it. A real step, not an assumption — `showModal()` moves focus out of the
   contenteditable and nothing else would put it back.

**The range must be cloned, and this is a correction to the precedent.** `text_toolbar.js:111` is
`sel.getRangeAt(0)` with no `cloneRange()`, which per DOM returns the selection's **live** Range —
not a snapshot. `showModal()` focuses the dialog's first focusable child, collapsing or replacing the
document selection and therefore mutating the very object steps 5 and 6 depend on. Every insertion
rule, the removal path and the dismissal caret-restore rest on those boundaries surviving. The math
command has the same unguarded pattern, but its modal is a plain `div`, not a `showModal()` dialog
that also makes the rest of the document inert — so "the math command does it this way" is not
evidence here. Clone at capture, and re-derive `sel` at restore rather than closing over it.

**Anchor enumeration.** `closest("a")` from the range boundaries is **not** sufficient: for the
canonical spanning case — the selection starts in plain text before link A and ends in plain text
after link B — both boundary walks return `null`, so *Remove link* would be disabled and rule 2 would
unwrap nothing. The touched set is therefore

```js
[...surface.querySelectorAll("a")].filter(a => range.intersectsNode(a))
```

plus the two boundary `closest("a")` hops as belt-and-braces for the enclosing case. Those hops must
step off a text node first — `(n.nodeType === 3 ? n.parentNode : n).closest("a")` — because
`Range.startContainer` is usually a text node, which has no `closest`; `currentBlock` in the same
file already does this hop.

**`touchedAnchors` is pinned for both cases**, because *Remove link* is gated on it: for a
**collapsed** range it is `1` when an anchor encloses the caret and `0` otherwise — `intersectsNode`
reports true for merely adjacent nodes in some engines, so it is not consulted for a caret. For a
non-collapsed range it is the length of the filtered set above. Without this, a caret inside a link —
the most common removal gesture, and e2e step 6 — would report 0 and disable the button.

**One containment predicate, used everywhere.** An anchor **encloses** a range when both boundary
points are within it — `A.contains(range.startContainer) && A.contains(range.endContainer)`, where
`contains` includes `A` itself. This covers both a caret inside a link and a selection exactly
coextensive with the link's text. Anchors do not nest, so at most one anchor can enclose a range.
`existing` is non-null exactly when rule 1 fires — one predicate, one wording.

**Insertion semantics** — an ordered decision, first match wins, total over ranges:

| # | state | on Insert |
|---|---|---|
| 1 | an anchor **encloses** the range | that anchor is edited in place (see below) |
| 2 | otherwise, the range is **non-empty** | every touched anchor is unwrapped, then the range is replaced by **one** anchor holding the link text |
| 3 | otherwise (collapsed, enclosed by nothing) | a new anchor is inserted at the caret |

**Rule 1 preserves inline markup when the text was not edited.** If the *Link text* field comes back
byte-identical to what was prefilled, only `href` is updated and the anchor's children are left
untouched — so `<b>`, `<em>` or an inline `\(math\)` span survives an author who only wanted to fix
the URL. If the text *was* edited, the contents are replaced by a single text node. The comparison is
against **`anchor.textContent`**, which is also what `existing.text` carries (`innerText` and
`innerHTML` would each give a different answer for an anchor containing markup).

**Rule 2 unlinks the unselected remainder of every anchor it touches**, and that is a real loss worth
stating plainly: a selection covering the tail of link A, some plain text, and the head of link B
leaves *both* fully unlinked, including the parts never selected, with no undo. The alternative —
splitting A and B so only the selected fragments are relinked — would produce three anchors from one
gesture and break the "one anchor, always" guarantee that makes the link text editable at all.

**Rule 2 and removal must not mutate the DOM out from under the live range.** Unwrapping an anchor
removes the element a boundary container may *be*, leaving the range pointing at a detached node. The
sequence, with the API spelled out because this is where it silently goes wrong:

1. insert marker nodes (empty text nodes) at the range boundaries via `insertNode` on collapsed
   clones of the start and end;
2. unwrap every touched anchor (`replaceWith(...a.childNodes)`);
3. re-derive the range: `setStartAfter(startMarker)` and `setEndBefore(endMarker)` — *after*/`before`,
   so the markers themselves are outside the range and removing them cannot shift the boundaries;
4. `deleteContents()`, then insert the single anchor (rule 2) or leave the recovered text (removal);
5. remove both markers, then call **`surface.normalize()`** to merge the text-node fragments the
   unwrap and markers created.

Normalising is deliberately *last* and receives `surface`: run while the markers are still in the DOM
it cannot merge the fragments they sit between, which is the whole point of the step; and a narrower
receiver would leave sibling fragments unmerged across the unwrap boundary. This ordering is a claim
the rule-2 first-character test must confirm, not an assumption to build on.

**Remove link** is enabled whenever `touchedAnchors > 0` and unwraps **all** touched anchors, keeping
their text, via the same sequence; afterwards the caret is collapsed at the end of the recovered text
and `input` is dispatched. Defining it over the range rather than over `existing` is what makes it
meaningful for a selection spanning two links.

One anchor, always — not `execCommand("createLink")`, which splits a multi-block selection into
several anchors and leaves the link text uneditable.

**The stashed range should belong to the invoking surface.** Before restoring, step 5 requires
`surface.contains(range.commonAncestorContainer)`; otherwise it falls back to appending at the end of
`surface`, matching the math command's `else` branch.

The motivating scenario is **a claim to be measured, not an established fact**: several RTE surfaces
are live at once (`_edit_choicequestion.html` mounts a `data-rte-source` textarea for the stem *and*
one for the explanation, each with its own toolbar), and the math command captures the range with no
containment check. *However*, `applyCmd` calls `surface.focus()` on its first line, before any branch
reads the selection, and focusing a contenteditable normally moves the selection into it — which may
mean the wrong-surface insert cannot occur. Implementation must reproduce it against today's code
**before** adding the guard, and record the result. The check is cheap and correct either way; what
must not survive is an asserted mechanism nobody measured.

**The surface must still be attached.** `editor.js` can replace the pane while the dialog is open
(the page carries `data-msg-conflict`, so a background reload path exists). Step 5 checks
`surface.isConnected` first and, when false, discards the result with that conflict message rather
than mutating an orphaned node — which would look like a successful insert and lose the link on save.

**One dialog at a time.** `open()` while a call is pending is rejected (the pending callback stands).
The module is a singleton, like `math_input.js`, whose module-level callback would otherwise be
silently overwritten.

**The anchor's text is written as a text node** (`createTextNode` / `textContent`), never
`innerHTML`, and the *Link text* field is populated with `.value` from `data-title`. Node titles are
author-supplied and may contain `<`, `&` or a stray quote.

**Link-text prefill precedence.** Whenever an anchor **encloses** the range — i.e. whenever rule 1
will fire — `existing.text` wins, so the field shows the *whole* text the mutation will operate on.
Otherwise a non-empty `selectionText` wins, else the selected node's title on the internal tab.

That ordering is load-bearing. For a partial selection inside a link, prefilling from `selectionText`
would put `vertex` in a field whose edit replaces `the vertex form unit` — the author shown one thing
and silently losing three words of another, with no undo. The node-title seed therefore applies only
when there is no selected text, which is what §Purpose promises; the re-seed on the internal tab
fires only while the field is blank.

**Accepted cost: native undo.** Direct range mutation is invisible to the contenteditable undo stack,
so Ctrl+Z will not undo an inserted link. The math command already behaves this way — recorded so it
is not later filed as a bug of unknown origin.

**Empty fields.** *Insert* is disabled while *Link text* is blank, and while the active tab's target
is unset. An anchor with empty text is invisible in the surface and cannot be clicked into, making
*Remove link* unreachable — an unrecoverable state.

**URL contract on the Web address tab** — an **ordered decision, first match wins**, exactly like the
insertion rules. Order is load-bearing: an absolute same-origin permalink satisfies both the
normalisation row and the scheme-allowlist row, and evaluating the allowlist first would accept it
verbatim and then trip the §5 misclassification it exists to prevent.

| # | input | behaviour |
|---|---|---|
| 1 | starts `//` (protocol-relative) | rejected, inline message |
| 2 | absolute permalink whose origin equals `location.origin` exactly, matching `^/courses/n/(\d+)/$` after the origin | normalised to the relative `/courses/n/<pk>/` |
| 3 | leading token matches a URI scheme (`[A-Za-z][A-Za-z0-9+.-]*:`) **and contains no dot** | accepted if the scheme is `http`/`https`/`mailto`, rejected otherwise |
| 4 | looks like a bare host — first segment contains a dot, no whitespace, does not start with `/` or `.` | prefixed `https://`; the normalised value is shown before insert |
| 5 | anything else relative (`/path`, `../foo`) | rejected, inline message |

Row 2 compares `location.origin` (scheme + host + port) exactly, so `http://` against an `https://`
deployment, or a different port, is *not* treated as same-origin and falls through. Row 3's dot
exclusion is what stops `example.com:8080/x` — a plausible self-hosted address whose leading token is
a syntactically valid scheme — from being rejected with a message about schemes; it falls to row 4
and is prefixed.

Three rows come from measurements against the real sanitiser, each a silent failure without them:

- `<a href="www.example.com">` survives **untouched**, becoming a *relative* href that resolves under
  the current unit URL and 404s.
- `<a href="//evil.com/x">` also survives **untouched** — an off-site link wearing a relative
  disguise, matching neither `.el a[href^="/courses/n/"]` nor `.el a[href^="http"]`, so it renders
  with no marker at all.
- `<a href="javascript:alert(1)">` comes back as `<a>` — the href dropped **at save**, after the
  author saw a working-looking link.

**Opening on an existing link** prefills. The internal-link test is the anchored pattern
`^/courses/n/(\d+)/$` — anything else, including a query or fragment suffix or a missing trailing
slash, is an ordinary URL and opens *Web address*. If the pattern matches but the pk is **not in this
course's tree**, the internal tab opens with no selection and the pre-rendered "This link's target is
not in this course." line, while *Web address* shows the raw stored href.

**Link text does not track the node title.** Renaming a node later leaves existing link text alone —
it is authored prose, possibly inflected or mid-sentence.

**Dismissal.** Cancel, Escape, and a backdrop click all dismiss. Escape is native; the other two are
**not** — a modal `<dialog>` does not close on a backdrop click by itself, so it must be wired:
`dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); })`. That is why the
content lives in an inner wrapper and the dialog carries no padding — otherwise a click on the card's
own padding would read as the backdrop. Note `imagezoom.js` closes on *every* click inside it;
copying that here would make the dialog unusable. All three paths route through one `close` handler,
invoking the callback **exactly once** — `null` unless a result was committed.

**Enter** presses *Insert* from the URL field and the *Link text* field only. On a focused picker row
Enter selects that row (§3) and never inserts — otherwise arrowing to a new row and pressing Enter
would fire *Insert* against the previously selected node. There is no `<form>` in the dialog and every
button is `type="button"`, so without this rule Enter would do nothing anywhere.

**No-JS baseline is unchanged.** With JS off the textarea submits raw HTML and the server sanitises
it; an author can hand-type `<a href="/courses/n/12/">` and it survives.

### 5. Link styling

**Student-side — `courses.css`.** Two treatments, scoped to `.el`, the wrapper every rendered element
carries, so site chrome is untouched:

- `.el a[href^="/courses/n/"]` — the body link colour with a solid underline and a small leading
  corner-arrow glyph via `::before`, `aria-hidden` through `content` (a CSS-generated glyph is not
  copied with the text and is not announced — the link text alone must carry the meaning).
- `.el a[href^="http"]` — an outbound marker via `::after`, same rationale.

Keying off the href prefix is what lets this work with no sanitiser change. Both rules are judged in
light **and** dark separately, like the `:target` highlight and the dialog's `::backdrop`.

The selector duplicates the route's literal path, which the route *name* does not protect: changing
`path("courses/n/<int:node_pk>/", …)` would keep every reverse-based test green while stripping the
marker off every internal link. §Testing ties them together, and the CSS carries a comment naming its
twin.

Two acknowledged misclassifications, both benign: a `mailto:` link matches neither selector and gets
no marker; an absolute same-origin permalink would match the *outbound* rule, though the dialog
normalises those away (row 2 above), so it only affects hand-typed HTML.

**Editor-side — `editor.css`.** In the preview pane these are real links (`editor.html` loads
`courses.css`), so clicking one navigates away and discards unsaved work.
`[data-scope="preview"] .el a { pointer-events: none; }` makes them inert — no JS, nothing a fragment
swap can defeat. The rule lives in `editor.css` because that stylesheet is loaded only by
`editor.html`. Note `data-scope` is **not** editor-only — `_scope.html:6` puts it on every builder
tree scope — so the selector must stay pinned to `="preview"` and must not be "simplified" to a bare
`[data-scope]`.

This assumes the app is served from the domain root; a `SCRIPT_NAME` prefix would break the prefix
match. True of the deployment today, stated as an assumption rather than discovered later. The JS
side does not share it — it copies `data-href` from the picker.

## Data flow

```text
author clicks 🔗
  -> text_toolbar.js guards on window.libliLinkDialog, stashes getRangeAt(0).cloneRange(),
     asks libliLinkApply for touched anchors -> existing {href,text}|null + touchedAnchors
  -> libliLinkDialog.open({existing, touchedAnchors, selectionText}, cb)
  -> dialog RESETS (filter, selection, fields), fetches the picker once per page
     (successes only; retry next open), applies + scrolls to any preselection
  -> author presses a row  =>  {href: row.dataset.href, text: link-text field}
     or types a URL        =>  ordered contract: //-reject, permalink-normalise,
                               scheme-allowlist, bare-host prefix, else reject
     or dismisses          =>  null   (Cancel / Escape / backdrop, callback fires exactly once)
  -> non-null: check surface.isConnected + range containment, restore the range,
     libliLinkApply.apply() -> rule 1/2/3 or removal, collapse after, fire "input"
     null: re-focus the surface and re-apply the stashed range
  -> sync() copies surface.innerHTML into the hidden textarea
  -> POST -> sanitize_html keeps <a href> verbatim -> stored

student clicks the link
  -> GET /courses/n/1234/
  -> 404 if the node is gone OR the course is not accessible (no existence oracle)
  -> 302 to lesson_unit / quiz_unit, or to the outline + #node-1234
```

## Error handling

| condition | behaviour |
|---|---|
| target node deleted | `get_object_or_404` → illustrated 404 (#167). Part 2 adds a delete-time warning. |
| target's course not accessible | 404, **not** 403 — see §1. |
| **manager who is not an accessor** follows their own link | 404 — the predicate mismatch named in §1. Pre-existing app-wide behaviour, recorded and tested, not fixed here. |
| **target now lives in another course** | See below — the one risk part 1 carries. |
| URL rejected by the contract | inline message, before it can be silently stripped or mis-rendered at save. |
| scheme-less URL that looks like a host | auto-prefixed `https://`; the normalised value is shown before inserting. |
| stored href's pk is not in this course's tree | internal tab opens unselected with an explanatory line; the raw href stays editable on *Web address*. |
| picker fetch fails | inline error + retry; not cached, so the next open retries. *Web address* still works. |
| `<dialog>` unsupported, or the dialog partial absent | `window.libliLinkDialog` never defined; the toolbar guard makes the button a no-op. |
| surface detached while the dialog is open | result discarded with the conflict message; nothing written to an orphaned node. |
| stashed range not inside the invoking surface | falls back to appending at the end of that surface. |
| author dismisses | callback receives `null` once; the surface is untouched and the caret restored by step 6. |

**Target now lives in another course.** A stored href is a bare global pk, so any operation that
copies an element body without rewriting it leaves the copy pointing at the *original* node: the
export→import round trip (what part 2 fixes) and "Duplicate a unit" (#160), which deep-copies bodies
verbatim — harmless within one course, but not if the duplicate is later moved.

The failure is silent in a specific way: the reader is not blocked. If they can access the other
course they simply land on unrelated content, with no 404 and no 403. It cannot be fixed inside the
permalink view, which has no way to know which course the *link* was authored in.

Accepted for part 1 shipping alone, on the grounds that no stored internal links exist yet and the
only same-install producer of stale links is duplicate-unit within one course, where the target
remains correct. Part 2 closes it, and should not lag far behind.

## Testing

Per house rule, every guard is falsified before it is trusted: delete the behaviour it protects and
require RED.

**Python**

- `node_permalink`: lesson unit → `lesson_unit` URL; quiz unit → `quiz_unit` URL;
  chapter/section/part → outline URL ending `#node-<pk>`; unknown pk → 404; course not accessible →
  **404** (asserting the absence of the enumeration oracle); anonymous → login redirect.
- **Manager-not-accessor**: a user with `courses.change_course` who does not own the course, is not
  enrolled and is not `is_staff` gets 404 — pinning the known mismatch as behaviour.
- The quiz assertion is on the **first hop's `Location`**, fixture pinned to *no submission*:
  `views.quiz_unit` itself 302s to `quiz_results` for a `SUBMITTED` submission, so a followed chain
  would fail for an unrelated reason.
- **Resolver regression:** `resolve("/courses/n/12/")` → `node_permalink`, `resolve("/courses/n/")` →
  `course_outline`.
- **Route-literal/CSS twin:** `reverse("courses:node_permalink", kwargs={"node_pk": 1})` starts with
  the exact prefix `courses.css` selects on.
- Sanitiser passthrough: an internal-link anchor survives `sanitize_html` byte-identically.
- `link_picker`: 200 + every node present for a manager; 403 for a non-manager; 404 for an unknown
  slug; a bare partial (no `<html>`). Each row's `data-href` equals `reverse(...)`; a quiz unit
  renders the `Q` chip and a lesson unit the `L`; rows carry `role="treeitem"` and the right
  `aria-level`. Query count pinned as a **concrete whole-request total**, with a comment naming which
  one is `_children_map` — `assertNumQueries(1)` would simply be wrong (the view also resolves the
  course and checks the perm), and the point is that one-query-per-row goes red.
- `_outline_node.html` renders `id="node-<pk>"` for each kind.

**Static/asset**

- The dialog markup is outside every `[data-scope]` element in `editor.html`.
- **`editor.html` links no `builder.css`** — the guard that does not exist today. The badge
  duplication is justified by this constraint, so the constraint needs an assertion rather than a
  docstring.
- **Badge drift guard**, in the spirit of `tests/test_editor_twin_drift.py`: the duplicated
  `.tree__badge*` declarations in `editor.css` are compared against their originals in `builder.css`
  and must match. A class-name substring check cannot catch the failure this duplication risks.
- `text_toolbar.js` no longer contains `window.prompt`, and guards on `window.libliLinkDialog`.
  Script *order* gets no assertion: the guard makes it irrelevant, so such a test could never go red
  for a real defect.
- `editor.css` defines every class the new markup uses — `.link-dialog*`, `.link-picker__*` — plus
  the preview-inert rule.

**JS behaviour — Playwright-as-a-JS-runtime, following `tests/test_table_grid_algebra.py`.**
There is no jsdom option: the repo has no `package.json`, no vitest/jest config, and no Node in CI.
The one precedent loads a module with `page.add_script_tag` and calls its exports through
`page.evaluate`. That is *why* the mutation logic lives in `link_apply.js` rather than inside
`text_toolbar.js`'s IIFE — logic private to that closure would be reachable only through full `-m e2e`
runs, which are excluded from the default suite. These cases mount a contenteditable fixture, build
ranges, and call `window.libliLinkApply`:

- Insertion rules 1, 2 and 3, plus totality: a selection **coextensive** with a link's text takes
  rule 1 (the gesture a "strictly inside" reading would have left undefined).
- Rule 1 with the link text returned unmodified leaves inline `<b>` intact; with the text edited, it
  is replaced.
- **Partial selection inside a link:** `existing.text` is the anchor's **full** `textContent`, and
  editing it does not delete the unselected words.
- Rule 2 with a selection starting at an anchor's **first character** — the marker-node ordering case
  — asserting exactly one anchor afterwards, no exception, and no leftover marker or split text node.
- **Rule 2 overlap:** a selection covering the tail of one link and the head of another, asserting
  exactly what remains linked.
- `touchedAnchors` is 1 for a caret inside a link and 0 for a caret outside one; *Remove link* over a
  range spanning two anchors unwraps both and leaves the caret at the end of the recovered text.
- The caret after an insert sits **outside** the anchor: typing appends unlinked text.
- A node title containing `<b>` is inserted as literal text, not markup.
- URL contract, one case per row **in order** — `//evil.com/x` → rejected; `https://<origin>/courses/n/12/`
  → `/courses/n/12/`; the same path on a *different* origin → not normalised;
  `javascript:alert(1)` → rejected; `example.com:8080/x` → `https://example.com:8080/x` (the dot-free
  scheme rule); `example.com` → `https://example.com`; `../foo` → rejected;
  `/courses/n/12/?x=1` → treated as an ordinary URL.

**Dialog behaviour** (e2e, since it needs the real `<dialog>` and the real fetch)

- A second `open()` starts clean — no selected row, no filter text carried over.
- **One dialog at a time:** a second `open()` while one is pending is rejected, and the first callback
  still fires exactly once.
- **Detached surface:** a result delivered after `surface.isConnected` goes false writes nothing and
  surfaces the conflict message.
- **Tab toggle contract:** switching tabs adds/removes `.is-on` and sets/removes `[hidden]`, so both
  panels are never visible at once.
- The callback fires exactly once per dismissal path (Cancel, Escape, backdrop), and on dismissal the
  caret returns to where it was (step 6) — the case that would silently regress if the range were not
  cloned.
- **Wrong-surface case: only if the mis-insert is first reproduced against today's code.** If
  `applyCmd`'s leading `surface.focus()` already makes it impossible, this test is dropped rather than
  written to pass vacuously, and the finding is recorded in the PR.

**e2e (`-m e2e`, real browser, mandatory marker)**

Driving the real gesture, never `page.evaluate` shortcuts:

1. Open a unit editor, add a text element, type prose, select a word.
2. Click the toolbar link button; assert *In this course* is already the active tab; type in the
   filter and assert matching rows keep their ancestors visible; type a string matching nothing and
   assert the no-match line; clear it; press a chapter row; assert the *Link text* field holds **the
   selected word** (not the node title — the precedence rule); Insert.
3. Repeat with a **collapsed caret** and assert the field holds **the node title**, which is the other
   half of the precedence rule and what §Purpose promises.
4. **Keyboard-only pass:** Tab once into the tree, move with Up/Down, press the row with Enter, Tab to
   *Insert*, press Enter — no mouse at all. This is the exact sequence the Enter rules define.
5. Save; assert the stored body holds `<a href="/courses/n/<pk>/">`.
6. Visit the unit as a student and click the link. Assert the URL ends `#node-<pk>` **and** that the
   row element inside `#node-<pk>` (`.outline-node__head`, or `.outline-unit` for a unit) has a
   non-default computed background — a `:target` rule mis-scoped to the `<li>` would pass a weaker
   check. Repeat for a unit target, asserting arrival on the unit page.
7. Re-open the editor, place the caret in the link, re-open the dialog; assert the tab and fields
   prefilled **and that the preselected row is scrolled into view**; click *Remove link*; assert the
   anchor is gone and the text remains.

**Visual**

Playwright screenshots, light and dark, of the dialog (both tabs, including the scrolled tree) and of
a rendered internal link (and an external one), judged separately per theme. The `::backdrop` is
judged with them.

## i18n

Every new string lives in `_link_dialog.html` as `{% trans %}` — tab labels, the dialog title, *Link
text*, *Remove link*, *Insert*, *Cancel*, the filter placeholder, the loading / empty-tree /
no-match / fetch-error+retry / target-not-in-this-course lines, and one message per URL-rejection
row. Because they are template strings, `makemessages -l pl -l en --no-obsolete` extracts them
normally; no `JavaScriptCatalog` route is introduced.

The two picker partials contribute **no new msgids**: a row's only text is the node title (author
data) and the kind chip, which renders `get_kind_display` or the builder's literal `L` / `Q` with a
`get_unit_type_display` title — all existing model choice labels.

`tests/test_i18n_po_health.py` owns the whole-catalog guards, and two bind here: no fuzzy entries,
and **no untranslated Polish msgstr** (`test_pl_has_no_untranslated_msgid`). Every new string must
ship with a real Polish translation — an empty msgstr turns that test red for a reason unrelated to
the feature. Fuzzy entries must be cleared properly: both the `#, fuzzy` line and the `#| msgid`
comment. Both `.mo` files are regenerated as part of the change.
