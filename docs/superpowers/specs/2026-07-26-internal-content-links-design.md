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

- **In this course** — pick a node (part / chapter / section / unit) from the course tree; the link
  text defaults to the node's title.
- **Web address** — an ordinary URL, but now with an edit path instead of a one-shot prompt.

## Scope

**In scope**

- A slug-free permalink route + view resolving a `ContentNode` to its reader-facing page.
- Per-node anchors on the course outline, so non-unit nodes are linkable at all.
- The link dialog: server-rendered partials plus `link_dialog.js`, and the `text_toolbar.js`
  change that opens it.
- A picker endpoint serving the course tree to the dialog.
- Student-side styling distinguishing internal from external links.

**Files touched.** No toolbar template changes — but the editor page itself does change, and the
list is enumerated here rather than left implicit:

| file | change |
|---|---|
| `courses/urls.py` | two routes: `node_permalink`, `manage_link_picker` |
| `courses/views.py` | `node_permalink` |
| `courses/views_manage.py` | `link_picker` |
| `templates/courses/manage/editor/editor.html` | `{% include %}` of the dialog partial **outside every `[data-scope]`** (see §4); `<script src="link_dialog.js" defer>` |
| `templates/courses/manage/editor/_link_dialog.html` | **new** — the dialog markup, all strings `{% trans %}`, carries `data-link-picker-url` on its root |
| `templates/courses/manage/editor/_link_picker.html` | **new** — the root `<ol>`; the template `link_picker` actually renders |
| `templates/courses/manage/editor/_link_picker_node.html` | **new** — one `<li>` + its nested child list, self-including |
| `templates/courses/_outline_node.html` | per-node `id` |
| `courses/static/courses/js/link_dialog.js` | **new** |
| `courses/static/courses/js/text_toolbar.js` | `case "link":` only |
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
  sanitiser strips `target`, so such a checkbox would silently do nothing. Stated here so nobody
  helpfully adds one.

- **Table and fill-table cells.** `sanitize_cell` allows `CELL_TAGS = {strong, b, em, i, u, br}` —
  no `<a>` at all. A link authored into a cell would be silently stripped on save. Making cells
  link-bearing is a sanitiser change with its own blast radius; it is not part of this.

- **Cross-course links.** The picker shows one tree: the course being edited. A link to another
  course would land any student not enrolled there on a 404, and — see part 2 — could not be
  rewritten on export anyway, since the archive only knows about the exported course. Pasting an
  absolute URL in the *Web address* tab remains possible for an author who really wants this.

- **Changing who can read a unit page.** §1 records a predicate mismatch (a manager who is not an
  accessor 404s on a link they authored). Widening that is an app-wide access change, not a linking
  feature; it is named, tested and left alone.

- **A link audit page.** Listing every internal link in a course and flagging the broken ones is a
  reasonable follow-up; it is not needed to ship the feature.

- **`core.help` role manuals.** This adds a visible authoring affordance that the Course Admin
  manual's toolbar description will eventually want a sentence about, but that is bilingual
  documentation work with its own review. Follow-up, matching how the unit-editor-link change
  handled the same question. No committed help screenshot covers the editor toolbar, so none needs
  regenerating.

## Architecture / components

Five pieces.

### 1. The permalink route — `courses/urls.py`, `courses/views.py`

```python
path("courses/n/<int:node_pk>/", views.node_permalink, name="node_permalink"),
```

Verified free: `resolve("/courses/n/12/")` raises `Resolver404` against the current URLconf. No
collision with `courses/<slug:slug>/`, which matches two path segments where this matches three.
(`/courses/n/` — a course whose slug is literally `n` — still resolves to `course_outline`, as it
does today. Both facts get a resolver test; see §Testing.)

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
course you cannot see 404s. The permalink carries no slug to scope against, so returning 403 here
would make it the one route in the app that answers "does node 4711 exist?" for any logged-in user
— a node and course enumeration oracle. Returning 404 keeps the existing indistinguishability.

**Known: a manager who is not an accessor 404s on their own link.** The two predicates are not
nested. `can_manage_course` is *owner OR the `courses.change_course` perm*, and its docstring notes
it deliberately does **not** key on `is_staff`; `can_access_course` is *staff OR owner OR enrolled OR
teaches a non-archived group*. So a Platform Admin holding `change_course` who neither owns the
course, is enrolled, nor is `is_staff` — the production shape of that role — can open the editor,
fetch the picker, insert a link, and then get a 404 following it.

Widening the permalink's check would not actually help: it redirects to `lesson_unit` / `quiz_unit`,
which run `can_access_course` themselves and would 403. Such a user cannot read *any* unit page
today, by any route — this is a pre-existing property of the app, not something the permalink
introduces, and changing it is an access-model decision well outside a linking feature. It is
therefore recorded here, listed in §Error handling, and pinned by a test so it is a known behaviour
rather than a surprise.

The quiz branch is explicit rather than delegated. `lesson_unit` does redirect a quiz unit onward to
`quiz_unit`, so delegating would work — but it would cost a second redirect hop on every quiz link,
and it would couple this view to an implementation detail of another one.

Storing a slug-free permalink is the point of the route: `/courses/n/1234/` keeps working when a
course is re-slugged, and the redirect target can change (route renames, a future chapter page)
without touching a single stored body.

**Nothing in JavaScript constructs this URL.** The picker partial emits it per row with `{% url %}`
(§3) and the JS copies the attribute verbatim, so the route name is the single source of the URL
shape *for the JS path*. The CSS selector in §5 is the one place the literal prefix is duplicated,
and §Testing ties the two together with a guard.

### 2. Outline anchors — `templates/courses/_outline_node.html`, `courses.css`

The `<li>` gains `id="node-{{ item.node.pk }}"`. Uniformly, for every kind — the `<li>` is shared
markup and a `{% if %}` around an `id` earns nothing. Units already link to their own page and will
not normally be reached by fragment, but the attribute is harmless and keeps the rule "every node
has an anchor" true.

**The `id` goes on the `<li>`; the highlight does not.** A non-unit `<li>` in `_outline_node.html`
contains both `.outline-node__head` *and* the nested `<ul>` of every descendant, so a rule like
`li:target { background: … }` would tint an entire part's subtree — most of the page — which conveys
nothing. The `<li>` is the scroll target; the highlight is scoped to the row inside it, and the two
branches of the template render different row elements, so both are needed:

```css
.outline-node:target > .outline-node__head { /* non-unit rows */ }
.outline-node:target > .outline-unit       { /* unit rows */ }
```

`scroll-margin-top` goes on the `<li>`. **Its reason is breathing room, not sticky chrome** —
measured: `.app-header` is `position: relative` (`core/static/core/css/app.css:22`) and `outline.html`
renders `.outline` in the normal `.app-main` flow, so nothing overlays the target row. Without the
declaration the row lands flush against the viewport top with no context above it; a
`var(--space-4)`-ish offset restores a line of context. If implementation finds the flush landing
acceptable, dropping the declaration is fine — what must not survive is a false justification for
keeping it.

The highlight must be legible in both themes — judged separately, per house rule, not inferred from
the light screenshot.

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
`<ol class="link-picker__scope">` iterating `top_nodes` — which `{% include %}`s
`_link_picker_node.html` per row. The row partial emits one `<li>`, and includes **itself** for each
child inside a nested `<ol>`, in the manner of `templates/courses/_outline_node.html`. Both are
rendered **standalone** (no `base.html` extension), because the dialog injects the markup directly.

**The row partial must `{% load courses_manage_extras %}` and reach its children with
`children_map|get_item:n.pk`.** A Django template cannot index a dict by a variable key at all —
that is why `_tree_node.html:44` uses the same filter — so without this the recursion is simply
unimplementable. (The alternative, having the view build a nested list of dicts the way
`build_outline` does, is available but buys nothing here: the filter already exists and the map is
already one query.)

Row shape, mirroring how `_tree_node.html` puts the rowhead and the child scope inside one `<li>`:

```html
<li class="link-picker__item">
  <button type="button" class="link-picker__row" data-node="…" data-href="…" data-title="…"
          aria-pressed="false" tabindex="-1">…badge… …title…</button>
  {# nested <ol class="link-picker__scope"> with the children, when there are any #}
</li>
```

- `data-node="{{ n.pk }}"` — the pk, for prefill matching;
- `data-href="{% url 'courses:node_permalink' node_pk=n.pk %}"` — the href, reversed server-side;
- `data-title="{{ n.title }}"` — the default link text;
- `aria-pressed` — the selected state, and the single source of the internal tab's target.

A `<button>` rather than a `<div>` with a click handler: the picker is the primary control of the
whole feature, and a div-with-listener is unreachable by keyboard. Selection is exactly one pressed
row; pressing another moves the pressed state.

**The chip mirrors the builder's vocabulary, including the unit branch.** `_tree_node.html` does not
render `get_kind_display` for units — it renders an `L` or `Q` chip
(`tree__badge tree__badge--unit tree__badge--lesson|--quiz`) with `title="{{ n.get_unit_type_display }}"`,
and the kind label only for non-units. The picker does the same, and not merely for consistency: the
permalink sends a lesson unit and a quiz unit to *different pages*, so an author choosing a target
must be able to tell them apart. Note `--lesson` / `--quiz` carry no declarations in `builder.css`
today — they are markup hooks — so only `.tree__badge`, `--part/--chapter/--section` and `--unit`
have rules to duplicate.

**Keyboard model: roving tabindex.** The tree is **one** tab stop, not ~925. Exactly one row holds
`tabindex="0"` — the selected row, else the first row in the roving set — and every other holds
`tabindex="-1"`; Up/Down move focus within the roving set, Home/End jump to its ends, and Enter or
Space presses the focused row.

The **roving set is the visible, non-`aria-disabled` rows**. Ancestor-context rows surfaced by a
filter are marked `aria-disabled="true"` with a click no-op — deliberately *not* the `disabled`
attribute, which would make them unfocusable and could leave the tree with no reachable tab stop at
all. The tab stop is re-assigned to the first row of the roving set whenever the filter changes; when
the set is empty, focus stays in the filter input and the tree holds no tab stop.

**Per-row `{% url %}` is a real cost, accepted with its number.** The permalink is per-node, so —
unlike the builder's rename URL — it cannot be hoisted out of the loop: a 925-node picker pays ~925
reversals, which at the ~64 µs the builder's own comment records is on the order of 60 ms. It is
accepted because it is paid **once per editor page** (the response is cached in the dialog module),
not on every page load, and because the alternative — emitting a template against a sentinel pk and
substituting in JS — puts URL construction back into JavaScript, which §1 exists to prevent. If the
cost ever shows up in practice, that sentinel-template hoist is the escape hatch, and the
`data-href == reverse(...)` test would move to the substituted value.

**Styling: only the badge is borrowed.** Layout uses picker-local `.link-picker__*` classes defined
in `editor.css` (the nested `<ol>` indentation, the row, its hover/pressed/`aria-disabled` states).
The builder's `.tree__scope` / `.tree__row` / `.tree__rowhead` are *not* referenced, because they live
in `builder.css`, which the editor page does not load — borrowing the names would ship an unindented,
unstyled list. The one exception is the `.tree__badge*` rules (`builder.css:35-37`), duplicated into
`editor.css` with a comment naming its twin, so the chip reads the same in both places. Adding
`builder.css` to the editor page instead is not merely undesirable but already forbidden:
`tests/test_editor_styles.py` asserts the editor page does not load it (that stylesheet carries
`.tree__title` overrides for the inline-rename `<input>` which exist to win a specificity fight with
`app.css`). The duplication is guarded by a real drift test, not a class-name substring check — see
§Testing.

The tree mount carries an explicit `max-height` and `overflow-y: auto`. A UA `<dialog>` caps at
roughly the viewport, so without it a 925-row list either overflows or grows the dialog past the
screen.

Whole-tree-in-one-response is a deliberate choice over server-side search. The largest real course
(`mat-pp`) is ~925 nodes; at roughly 150–200 bytes per row that is on the order of 150–200 KB —
an order-of-magnitude estimate, not a measurement, and worth re-checking against the real row markup
during implementation. The media picker searches server-side because a media library is unbounded
and its rows carry thumbnails; a course tree is neither.

**Fetch policy.** The request sends `X-Requested-With: fetch`, matching `media_picker.js`; the view
does not gate on it. Only a **successful** response is cached, for the life of the page. A failure
is retried on the next `open()` (the error line carries a retry control), so one transient blip
cannot disable the feature's headline capability for the rest of a long-lived editor session. A
second `open()` while a fetch is in flight reuses the pending request rather than issuing another,
and a fetch still in flight when the dialog closes is aborted.

**The fetched markup is assigned with `innerHTML`.** It is server-rendered and autoescaped, so this
is correct and intended; the never-`innerHTML` rule in §4 governs only author-supplied strings
crossing into an editing surface.

**Cache staleness is accepted.** A node renamed or added in another tab will not appear until the
editor page is reloaded. The tree is fetched once because the editor page is long-lived and
`editor.js` swaps element fragments repeatedly; re-fetching per open would cost a ~200 KB round trip
for a tree that changes rarely during an editing session.

**The unit being edited is included** in the tree, and selectable. A self-link is odd but harmless,
and excluding it would need the picker to know which unit hosts the element — context it otherwise
does not need.

**Filtering** matches a case-insensitive substring of the node title only (not the kind label, which
is a translated word and would match half the tree in Polish). A matching row keeps its ancestors
visible, `aria-disabled` and visually recessed if they do not themselves match, so the indentation
still reads as a path rather than a flat list. The message region carries `aria-live="polite"` and a
match count, so a screen-reader user learns that the tree collapsed to nothing or that the row count
changed — the rest of this design is carefully keyboard- and SR-accessible, and a silent filter
would be the one hole in it.

Because the tree DOM is cached and `aria-pressed` is the only record of the target, **every `open()`
resets the panel first**: filter input cleared, every row un-pressed and re-shown, roving tabindex
reset, URL and link-text fields cleared — and only then is any preselection from `existing` applied.
Without this, the second open would arrive pre-armed with the previous session's target and filter,
and *Insert* would be enabled against a node the author never chose this time.

Picker states, defined rather than left to chance:

| state | behaviour |
|---|---|
| tree not yet fetched (first open) | pre-rendered translated "Loading…" line; *Insert* disabled on this tab. A preselection requested before the payload arrives is applied when it resolves, unless the author has already pressed a row. |
| fetch failed | pre-rendered inline error plus a retry control; not cached, so the next open retries. The *Web address* tab still works, so the dialog is never a dead end. |
| course has no nodes | translated "This course has no content yet."; *Insert* stays disabled on this tab |
| filter matches nothing | translated "No matches."; the tree is hidden, not emptied; focus stays in the filter |
| filter cleared | the full tree returns, with any prior selection still pressed |
| the selected row is hidden by the filter | the selection **survives** — it is the tab's target regardless of visibility, so typing an unrelated filter string cannot silently retarget an insert |

### 4. The dialog — partial + `link_dialog.js` (new), `text_toolbar.js` (changed)

**The dialog markup is server-rendered**, as `_link_dialog.html`, included once by `editor.html`.
This is not a stylistic choice: the repo has **no** `JavaScriptCatalog` / `jsi18n` route (grepped:
zero hits), so `makemessages` cannot extract a string that exists only inside a `.js` file. Every
other JS-driven UI here works around that by rendering strings into `data-msg-*` attributes
(`math_input.js` reads `data-msg-insert` / `-cancel` / `-math` off `.editor`). A dialog with a dozen
or so strings would turn that workaround into a sprawl, so the markup — tabs, labels, buttons,
placeholder, every message — is a `{% trans %}` template and the JS only wires behaviour to it. No
new `data-msg-*` attributes are needed.

**The include must sit outside every `[data-scope]` element.** `editor.js` replaces the
`[data-scope="editor"]` and `[data-scope="preview"]` panes — children of `div.editor-grid` inside
`_editor_scope.html` — and then re-runs `window.libliInitRte`. Dropped inside a swapped pane, the
`<dialog>` and every listener bound to it at load are destroyed on the first save, producing an
intermittent dead toolbar button that is painful to attribute. The include goes as a child of
`section.editor`, after the `{% include %}` of `_editor_scope.html`. The static test is phrased on
the invariant, not the position: *the dialog markup is outside every `[data-scope]` element*.

**Feature detection — two conditions, both leaving `window.libliLinkDialog` undefined.**
`link_dialog.js` bails when `typeof document.createElement("dialog").showModal !== "function"`
(following `imagezoom.js`) **and** when `document.querySelector(".link-dialog")` is null. The export
is the capability signal, not merely a platform signal: a page that loaded the script without the
include would otherwise pass `text_toolbar.js`'s guard and then throw on a null query. In either
case the link button does nothing — an accepted regression from today's `window.prompt` on browsers
lacking `<dialog>`, on the same grounds `imagezoom.js` already accepted.

**Markup** (`<dialog class="link-dialog">`, in the page from first paint, closed):

- `data-link-picker-url` on the dialog root — the module owns the fetch, so it owns the URL. It is
  deliberately *not* on `section.editor`: putting it there would make `text_toolbar.js` responsible
  for a picker concern and pass it through `open()`, muddying the ownership split below.
- a translated dialog title, referenced by `aria-labelledby` on the `<dialog>` (the cited precedent
  does set one — `math_input.js` applies `aria-label` from `data-msg-math` — so omitting it would
  regress against the repo's own bar);
- an inner wrapper element holding all content; the `<dialog>` itself carries no padding, so a click
  whose `e.target` is the dialog means the backdrop and nothing else (see Dismissal);
- two tab `<button type="button">`s reusing the existing `.picker__tabs` / `.picker__tab` /
  `.picker__panel` classes;
- the **In this course** panel: a filter `<input type="search">`, the tree mount, and an
  `aria-live="polite"` message region holding the pre-rendered loading / empty / no-match /
  fetch-error (with retry) / target-not-in-this-course lines;
- the **Web address** panel: a URL `<input type="url">` and one pre-rendered message element per
  distinct rejection (disallowed scheme, protocol-relative, other relative path);
- a shared **Link text** `<input type="text">`;
- **Remove link** / **Cancel** / **Insert**, all `type="button"`.

Every button carries an explicit `type="button"`, including the tabs. `editor.html` is full of
forms, and a bare `<button>` that ends up form-associated defaults to `type="submit"` — Insert would
post the element form. The repo's own toolbars set it on every control for the same reason.

**The reused tab classes come with a contract:** `editor.css` styles the active tab as
`.picker__tab.is-on` and hides panels via `.picker__panel[hidden]` — the pair `media_picker.js`
already toggles. The JS must add/remove `is-on` on the tab and set/remove `hidden` on the panel, or
both panels render at once. The tabs carry `role="tab"` / `aria-selected` — deliberately a different
ARIA model from the rows' `aria-pressed`, so "which tab" and "which node" are not conflated.

**Default tab** on a fresh open (no `existing`) is **In this course** — it is the feature's reason to
exist. An existing link opens on the tab matching what is stored. **Initial focus** is the filter
input on the internal tab and the URL input on *Web address*. `showModal()` genuinely traps focus
because the dialog has focusable children — the caveat recorded from the image-zoom work (a dialog
with *no* focusable child does not trap) does not apply.

**Messages are shown, never composed.** Each message is a pre-rendered element that JS only toggles,
so no string is assembled in JavaScript and `makemessages` sees all of them.

**Ownership is split, and the split is the interface.** `link_dialog.js` owns its own dialog DOM —
tabs, fetch, filter, validation — and nothing else; it never touches an editing surface. The
callback returns a decision, and `text_toolbar.js` performs every mutation. This mirrors
`window.libliMathInput.open(cb)`, which `text_toolbar.js` already calls for the ∑ button.

```js
// link_dialog.js — owns only its own dialog. Knows nothing about the surface or the Range.
window.libliLinkDialog.open({ existing, touchedAnchors, selectionText }, cb);
//   existing:       {href, text} | null   — set iff exactly one anchor ENCLOSES the range (below)
//   touchedAnchors: integer               — how many anchors the range intersects
//   selectionText:  string                — "" when the range is collapsed
//   cb(result):     {href, text} | {remove: true} | null      (null = dismissed)
```

`text_toolbar.js`'s `case "link":` — the only place it changes — does all of the following:

1. guards with `if (!window.libliLinkDialog) break;`, exactly as the math command guards on
   `window.libliMathInput`;
2. stashes the current `Range` **before** `showModal()` moves focus (the discipline the math
   command already uses);
3. enumerates the anchors the range touches (below) and derives `existing` and `touchedAnchors`;
4. calls `open()`;
5. **on a non-null result:** re-focuses the surface, restores the `Range`, performs the mutation,
   collapses the selection **after** the resulting anchor (for a removal, at the end of the recovered
   text), and dispatches `new Event("input")` on the surface — which is what drives `sync()` into the
   hidden textarea;
6. **on `null`:** re-focuses the surface and re-applies the stashed `Range`, so the caret returns
   where the author left it. This is a real step, not an assumption — `showModal()` moves focus out
   of the contenteditable, and nothing else in the flow would put it back.

Collapsing after the anchor matters: the math command does the same, and without it the caret sits
*inside* the new link so every subsequent keystroke silently extends the link text.

**Anchor enumeration.** `closest("a")` from the range boundaries is **not** sufficient: for the
canonical spanning case — the selection starts in plain text before link A and ends in plain text
after link B — both boundary walks return `null`, so *Remove link* would be disabled and rule 2
would unwrap nothing, contradicting their stated behaviour. The touched set is therefore

```js
[...surface.querySelectorAll("a")].filter(a => range.intersectsNode(a))
```

plus the two boundary `closest("a")` hops as belt-and-braces for the enclosing case. Those hops must
step off a text node first — `(n.nodeType === 3 ? n.parentNode : n).closest("a")` — because
`Range.startContainer` is usually a text node, which has no `closest`; `currentBlock` in the same
file already does this hop. For a **collapsed** range sitting at an anchor's edge, `intersectsNode`
reports true for adjacent nodes in some engines, so the collapsed case is decided by the enclosing
predicate alone and the `intersectsNode` result is ignored.

**One containment predicate, used everywhere.** An anchor **encloses** a range when both boundary
points are within it — `A.contains(range.startContainer) && A.contains(range.endContainer)`, where
`contains` includes `A` itself. This covers both a caret inside a link and a selection exactly
coextensive with the link's text. Anchors do not nest (the sanitiser's output never does, and no
browser produces nested `<a>`), so at most one anchor can enclose a range. `existing` is non-null
exactly when rule 1 below fires — one predicate, one wording, no gap between the contract and the
rules.

**Insertion semantics** — an ordered decision, first match wins, and provably total over ranges:

| # | state | on Insert |
|---|---|---|
| 1 | an anchor **encloses** the range | that anchor is edited in place (see below) |
| 2 | otherwise, the range is **non-empty** | every touched anchor is unwrapped, then the range is replaced by **one** anchor holding the link text |
| 3 | otherwise (collapsed, enclosed by nothing) | a new anchor is inserted at the caret |

Rule 1 covers the most common re-link gesture — double-clicking a one-word link, or clicking into a
longer one — as well as a partial selection inside a link: the *whole* link is retargeted.

**Rule 1 preserves inline markup when the text was not edited.** If the *Link text* field comes back
byte-identical to what was prefilled, only `href` is updated and the anchor's children are left
untouched — so `<b>`, `<em>` or an inline `\(math\)` span inside a link survives an author who only
wanted to fix the URL. If the text *was* edited, the contents are replaced by a single text node.

**Rule 2 unlinks the unselected remainder of every anchor it touches**, and that is a real loss worth
stating as plainly as rule 1's: a selection covering the tail of link A, some plain text, and the
head of link B leaves *both* A and B fully unlinked, including the parts the author never selected,
with no undo. The alternative — splitting A and B so only the selected fragments are relinked —
would produce three anchors from one gesture and break the "one anchor, always" guarantee that makes
the link text editable at all. §Testing pins the exact surviving state for that overlap case, so the
behaviour is a decision rather than a discovery.

**Rule 2 must not mutate the DOM out from under the live Range.** Unwrapping an anchor removes the
element a boundary container may *be* (an offset within `<a>`, which happens when a selection starts
at a link's edge), leaving the range pointing at a detached node so the following
`deleteContents()` / `insertNode()` misbehave or throw. The order is therefore: insert two marker
nodes at the range's boundaries, unwrap every touched anchor, normalise the affected text nodes,
re-derive the range from the markers, then remove the markers and insert the single anchor. §Testing
requires a rule-2 case whose selection starts at an anchor's first character.

**Remove link** is enabled whenever `touchedAnchors > 0`, and unwraps **all** touched anchors,
keeping their text. Defining it over the range rather than over `existing` is what makes it
meaningful for a selection spanning two links, where `existing` is `null`. It uses the same
marker-node protection as rule 2 — the boundary can sit inside an anchor about to be unwrapped —
and afterwards the text nodes are normalised, the caret is collapsed at the end of the recovered
text, and `input` is dispatched.

One anchor, always — not `execCommand("createLink")`, which splits a multi-block selection into
several anchors and leaves the link text uneditable. A selection spanning block boundaries therefore
collapses to a single link; the selection's text content is offered as the default link text, so the
author sees what they are about to flatten before confirming.

**The stashed Range should belong to the invoking surface.** Before restoring, step 5 requires
`surface.contains(range.commonAncestorContainer)`; otherwise it falls back to appending at the end
of `surface`, matching the math command's own `else` branch.

The motivating scenario is **a claim to be measured, not an established fact**: several RTE surfaces
are live at once on the editor page (`_edit_choicequestion.html` mounts a `data-rte-source` textarea
for the stem *and* another for the explanation, each with its own toolbar), and the existing math
command captures `sel.getRangeAt(0)` with no containment check. *However*, `applyCmd` calls
`surface.focus()` on its first line, before any branch reads the selection, and focusing a
contenteditable normally moves the selection into it — which may mean the wrong-surface insert
cannot actually occur. Implementation must reproduce the mis-insert against today's code **before**
adding the guard, and record the result. The containment check is cheap and correct defensive code
either way; what must not survive is an asserted mechanism nobody measured. If the mis-insert proves
impossible, the §Testing case for it is dropped rather than written to pass vacuously.

**The surface must still be attached.** `editor.js` can replace the pane while the dialog is open
(the page carries `data-msg-conflict="This changed elsewhere — reloaded to the latest."`, so a
background reload path exists). Step 5 therefore checks `surface.isConnected` first and, when false,
discards the result with that conflict message rather than mutating an orphaned node — which would
look like a successful insert and then lose the link on save.

**One dialog at a time.** `open()` while a call is pending is rejected (the pending callback stands);
it does not supersede. The module is a singleton, like `math_input.js`, whose module-level callback
would otherwise be silently overwritten.

**The anchor's text is written as a text node** (`document.createTextNode` / `textContent`), never
`innerHTML`, and the *Link text* field is populated with `.value` from `data-title`. Node titles are
author-supplied and may contain `<`, `&` or a stray quote; routing them through `innerHTML` would
interpret them as markup on the way into a surface whose `innerHTML` is then saved.

**Link-text prefill precedence.** Whenever an anchor **encloses** the range — i.e. whenever rule 1
will fire — `existing.text` wins, so the field shows the *whole* text the mutation will operate on.
Otherwise a non-empty `selectionText` wins, else the selected node's title on the internal tab.

That ordering is load-bearing, not cosmetic. For a partial selection inside a link, prefilling from
`selectionText` would put `vertex` in a field whose edit replaces `the vertex form unit` — the author
would be shown one thing and silently lose three words of another, with no undo. The node-title
re-seed fires only on the internal tab and only while the field is blank, so an author who
deliberately cleared and retyped the text never has it overwritten.

**Accepted cost: native undo.** Direct `Range` mutation is invisible to the contenteditable undo
stack, so Ctrl+Z will not undo an inserted link. The math command already behaves this way, so this
is consistent rather than novel — recorded here so it is not later filed as a bug of unknown origin.

**Empty fields.** *Insert* is disabled while the *Link text* field is blank, and while the active
tab's target is unset (no node selected / empty or invalid URL). An anchor with empty text is
invisible in the surface and cannot be clicked into, which would make *Remove link* unreachable — an
unrecoverable state.

**URL contract on the Web address tab.** The contract is **total over input shapes** — a scheme
allowlist alone would not be, because a value with no scheme is never tested by one:

| input | behaviour |
|---|---|
| `http:` / `https:` / `mailto:` scheme | accepted as typed |
| any other scheme (`javascript:`, `ftp:`, `libli:`) | rejected, inline message |
| starts `//` (protocol-relative) | rejected, inline message |
| absolute same-origin permalink `https://host/courses/n/<pk>/` | normalised to `/courses/n/<pk>/` |
| looks like a bare host — first segment contains a dot, no whitespace, does not start with `/` or `.` | prefixed `https://`, and the normalised value is shown before insert |
| anything else relative (`/path`, `../foo`) | rejected, inline message |

Three of those rows come from measurements against the real sanitiser, and each is a silent failure
without them:

- `<a href="www.example.com">` survives **untouched**, becoming a *relative* href that resolves under
  the current unit URL and 404s.
- `<a href="//evil.com/x">` also survives **untouched**. It is an off-site link wearing a relative
  disguise: it matches neither `.el a[href^="/courses/n/"]` nor `.el a[href^="http"]`, so it would
  render with no marker at all. Rejecting it costs the author one `https://`.
- `<a href="javascript:alert(1)">` comes back as `<a>` — the href is dropped **at save**, after the
  author saw a working-looking link in the editing surface. Rejecting it in the dialog turns a
  silent post-save surprise into an immediate message.

**Opening on an existing link** prefills. The internal-link test is the anchored pattern
`^/courses/n/(\d+)/$` — anything else, including a query string or fragment suffix
(`/courses/n/12/?x=1`, `/courses/n/12#f`) or a missing trailing slash, is treated as an ordinary URL
and opens the *Web address* tab. If the pattern matches but the pk is **not in this course's tree** —
a deleted node, or a body copied in from elsewhere — the internal tab opens with no selection and the
pre-rendered "This link's target is not in this course." line, while the *Web address* tab shows the
raw stored href so the author can still see and edit exactly what is stored.

**Link text does not track the node title.** Renaming a node later leaves existing link text alone.
The text is authored prose — it may be inflected, abbreviated, or mid-sentence ("as shown in *the
vertex form unit*"), and silently rewriting it would be wrong far more often than right.

**Dismissal.** Cancel, the Escape key, and a backdrop click all dismiss. Escape is native; the other
two are **not** — a modal `<dialog>` does not close on a backdrop click by itself, so it must be
wired: `dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); })`. This is
exactly why the content lives in an inner wrapper and the dialog carries no padding — otherwise a
click on the card's own padding would read as `e.target === dialog` and close it mid-edit. Note the
one `<dialog>` precedent in the repo, `imagezoom.js`, closes on *every* click inside it; copying that
here would make the dialog unusable. All three paths route through a single `close` handler, which
invokes the callback **exactly once** — with `null` unless a result was committed by *Insert* or
*Remove link*.

**Enter** presses *Insert* when *Insert* is enabled and focus is in the URL field or on a picker row.
Enter in the filter field is inert (it would otherwise fire an insert while the author is still
narrowing the tree). There is no `<form>` in the dialog and every button is `type="button"`, so
without this rule Enter would do nothing anywhere.

**No-JS baseline is unchanged.** With JS off the textarea submits raw HTML and the server sanitises
it, exactly as today; an author can hand-type `<a href="/courses/n/12/">` and it will survive. The
dialog is progressive enhancement, like the rest of the RTE.

### 5. Link styling

**Student-side — `courses/static/courses/css/courses.css`.** Two concrete treatments, scoped to
`.el`, the wrapper every rendered element carries (`el el--text`, `el el--question`, and the
callout/spoiler bodies), so site chrome and navigation are untouched:

- `.el a[href^="/courses/n/"]` — an internal link reads as part of the course: the body link colour
  with a solid underline, and a small leading corner-arrow glyph via `::before`, `aria-hidden`
  through `content` (a CSS-generated glyph is not copied with the text and is not announced, which
  is what we want — the link text alone must carry the meaning).
- `.el a[href^="http"]` — an outbound marker via `::after`, same rationale.

Keying off the href prefix is what lets this work with no sanitiser change — recall that a `class`
on `<a>` would be stripped. Both rules are judged in light **and** dark separately, per house rule,
like the `:target` highlight and the dialog's `::backdrop`.

The selector duplicates the route's literal path, which the route *name* does not protect: changing
`path("courses/n/<int:node_pk>/", …)` would keep every reverse-based test green while silently
stripping the marker off every internal link. §Testing ties them together, and the CSS carries a
comment naming its twin.

Two acknowledged misclassifications, both benign and both cheaper to accept than to fix:

- A `mailto:` link matches neither selector and gets no marker. Acceptable — it is rare in course
  prose, and the alternative is a third rule for a case authors barely use.
- An absolute same-origin permalink would match the *outbound* rule. The dialog normalises those to
  relative form (§4), so this only affects hand-typed HTML.

**Editor-side — `courses/static/courses/css/editor.css`.** Inside the editor's preview pane these are
real links (`editor.html` loads `courses.css`), so clicking one navigates away from the editor and
discards whatever is open in the edit form. `[data-scope="preview"] .el a { pointer-events: none; }`
makes them inert — no JS, and nothing a fragment swap can defeat. The rule lives in `editor.css`, not
`courses.css`: `[data-scope]` exists only on the editor page, and shipping an editor-only selector in
the student stylesheet would put it on every course page for no reason.

This assumes the app is served from the domain root; a `SCRIPT_NAME` prefix would break the prefix
match. That is true of the deployment today and is stated here as an assumption rather than
discovered later. The JS side does not share the assumption — it copies `data-href` from the picker
rather than building a path.

## Data flow

```text
author clicks 🔗
  -> text_toolbar.js guards on window.libliLinkDialog, stashes the Range,
     enumerates touched anchors -> existing {href,text}|null + touchedAnchors
  -> libliLinkDialog.open({existing, touchedAnchors, selectionText}, cb)
  -> dialog RESETS (filter, presses, fields), fetches the picker once per page
     (successes only; retry on next open after a failure), applies preselection
  -> author presses a row  =>  {href: row.dataset.href, text: link-text field}
     or types a URL        =>  total contract: scheme-checked, https:// prefixed,
                               permalink normalised, protocol-relative rejected
     or dismisses          =>  null   (Cancel / Escape / backdrop, callback fires exactly once)
  -> non-null: text_toolbar.js checks surface.isConnected and range containment,
     restores the Range, applies rule 1/2/3 (or removal), collapses after, fires "input"
     null: re-focus the surface and re-apply the stashed Range
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
| target node deleted | `get_object_or_404` → illustrated 404 (#167). Part 2 adds a delete-time warning so this is rare rather than routine. |
| target's course not accessible | 404, **not** 403 — see §1. |
| **manager who is not an accessor** follows their own link | 404 — the predicate mismatch named in §1. Pre-existing app-wide behaviour (they cannot read any unit page), recorded and tested, not fixed here. |
| **target now lives in another course** | See below — the one risk part 1 carries. |
| URL rejected by the contract | inline message in the dialog, before it can be silently stripped or silently mis-rendered at save. |
| scheme-less URL that looks like a host | auto-prefixed `https://`; the author sees the normalised value before inserting. |
| stored href's pk is not in this course's tree | internal tab opens unselected with an explanatory line; the raw href stays visible and editable on the Web address tab. |
| picker fetch fails | inline error + retry on the internal tab; not cached, so the next open retries. The *Web address* tab still works. |
| `<dialog>` unsupported, or the dialog partial absent | `window.libliLinkDialog` is never defined; the toolbar guard makes the button a no-op. Accepted, per `imagezoom.js`. |
| surface detached while the dialog is open | the result is discarded with the existing conflict message; nothing is written to an orphaned node. |
| stashed range not inside the invoking surface | falls back to appending at the end of that surface, as the math command does. |
| author dismisses | callback receives `null` once; the surface is untouched and the caret restored by step 6. |

**Target now lives in another course.** A stored href is a bare global pk, so any operation that
copies an element body without rewriting it leaves the copy pointing at the *original* node. Two
such operations exist: the export→import round trip (exactly what part 2 fixes) and "Duplicate a
unit" (#160), which deep-copies bodies verbatim — harmless within one course, since the original
target is still the right one, but not if the duplicate is later moved elsewhere.

The failure is silent in a specific way worth naming: the reader is not blocked. If they can access
the other course — a Platform Admin, a teacher, a student enrolled in both — they simply land on
unrelated content, with no 404 and no 403 to signal it. It cannot be fixed inside the permalink
view, which has no way to know which course the *link* was authored in.

This is an accepted, stated risk for part 1 shipping alone, on the grounds that no stored internal
links exist yet (nothing to have gone stale) and that the only same-install producer of stale links
is duplicate-unit within one course, where the target remains correct. Part 2 is what closes it, and
should not lag far behind.

## Testing

Per house rule, every guard is falsified before it is trusted: delete the behaviour it protects and
require RED. A test that has never failed is not evidence.

**Python**

- `node_permalink`: lesson unit → `lesson_unit` URL; quiz unit → `quiz_unit` URL;
  chapter/section/part → outline URL ending `#node-<pk>`; unknown pk → 404; course not accessible →
  **404** (asserting the absence of the enumeration oracle, so a later "helpful" switch to 403 is
  caught); anonymous → login redirect.
- **Manager-not-accessor**: a user with `courses.change_course` who does not own the course, is not
  enrolled and is not `is_staff` gets 404 — pinning the known mismatch as behaviour rather than
  accident.
- The quiz assertion is on the **first hop's `Location`**, with the fixture pinned to *no
  submission*. `views.quiz_unit` itself 302s to `quiz_results` when the student's submission is
  `SUBMITTED`, so a followed redirect chain — or a submitted fixture — would fail for a reason
  unrelated to the branch under test.
- **Resolver regression:** `resolve("/courses/n/12/")` → `node_permalink` and `resolve("/courses/n/")`
  → `course_outline`. The no-collision claim is one urls.py reordering away from silently breaking a
  course slugged `n`, and prose is not a guard.
- **Route-literal/CSS twin:** `reverse("courses:node_permalink", kwargs={"node_pk": 1})` starts with
  the exact prefix `courses.css` selects on. Without this, changing the route path keeps every
  reverse-based test green while every internal link loses its styling.
- Sanitiser passthrough: an internal-link anchor survives `sanitize_html` byte-identically. This
  pins the assumption the whole design rests on, so a future sanitiser tightening fails loudly here
  instead of silently voiding every stored link.
- `link_picker`: 200 + every node present for a manager; 403 for a non-manager; 404 for an unknown
  slug; the response is a bare partial (no `<html>`). Each row's `data-href` equals
  `reverse("courses:node_permalink", kwargs={"node_pk": n.pk})`; a quiz unit renders the `Q` chip and
  a lesson unit the `L` chip. Query count pinned as a **concrete total for the whole request**, with
  a comment naming which one is `_children_map` — the point is that a regression to one query per row
  goes red, and `assertNumQueries(1)` would simply be wrong (the view also resolves the course and
  checks the perm).
- `_outline_node.html` renders `id="node-<pk>"` for each kind.

**Static/asset**

- The dialog markup is outside every `[data-scope]` element in `editor.html`.
- `text_toolbar.js` no longer contains `window.prompt`, and guards on `window.libliLinkDialog`
  before use. Script *order* is convention only and gets no assertion: the guard makes order
  irrelevant, so an order test could never go red for a real defect — and a test that cannot fail is
  not evidence.
- `editor.css` defines every class the new markup uses — `.link-dialog*`, `.link-picker__*` — plus
  the preview-inert rule.
- **Badge drift guard**, in the spirit of `tests/test_editor_twin_drift.py`: the duplicated
  `.tree__badge*` declarations in `editor.css` are compared against their originals in `builder.css`
  and must match. A class-name substring check cannot catch the failure this duplication actually
  risks — the two copies diverging — so the guard compares declarations, not names.

**JS behaviour** (jsdom-level or e2e, whichever the repo's existing habit favours)

- URL contract, one case per row of the table — including `//evil.com/x` → rejected,
  `example.com` → `https://example.com`, `javascript:alert(1)` → rejected, `../foo` → rejected,
  `https://host/courses/n/12/` → `/courses/n/12/`, and `/courses/n/12/?x=1` → treated as an ordinary
  URL (the anchored-pattern rule).
- Insertion rules 1, 2 and 3, plus the totality claim: a selection **coextensive** with a link's text
  takes rule 1 (this is the gesture a "strictly inside" reading would have left undefined).
- Rule 1 with the link text returned unmodified leaves inline `<b>` inside the anchor intact; with
  the text edited, it is replaced.
- **Partial selection inside a link:** the *Link text* field is prefilled with the anchor's **full**
  text, and editing it does not delete the unselected words.
- Rule 2 with a selection starting at an anchor's **first character** — the marker-node ordering case
  — asserting exactly one anchor afterwards and no exception.
- **Rule 2 overlap:** a selection covering the tail of one link and the head of another — asserting
  exactly what remains linked, so the destructive scope is pinned rather than discovered.
- *Remove link* over a range spanning two anchors unwraps both, and the caret lands at the end of the
  recovered text.
- The caret after an insert sits **outside** the anchor: typing appends unlinked text.
- On dismissal the caret returns to where it was (step 6).
- A second `open()` starts clean — no pressed row, no filter text carried from the first.
- **One dialog at a time:** a second `open()` while one is pending is rejected, and the first
  callback still fires exactly once.
- **Detached surface:** a result delivered after `surface.isConnected` goes false writes nothing and
  surfaces the conflict message.
- **Tab toggle contract:** switching tabs adds/removes `.is-on` and sets/removes `[hidden]`, so both
  panels are never visible at once.
- A node title containing `<b>` is inserted as literal text, not markup.
- The callback fires exactly once per dismissal path (Cancel, Escape, backdrop).
- **Wrong-surface case: only if the mis-insert is first reproduced against today's code.** If
  `applyCmd`'s leading `surface.focus()` already makes it impossible, this test is dropped rather
  than written to pass vacuously, and the finding is recorded in the PR.

**e2e (`-m e2e`, real browser, mandatory marker)**

Driving the real gesture, never `page.evaluate` shortcuts:

1. Open a unit editor, add a text element, type prose, select a word.
2. Click the toolbar link button; assert *In this course* is already the active tab; type in the
   filter and assert matching rows keep their ancestors visible; type a string matching nothing and
   assert the no-match line; clear it; press a chapter row; confirm the link-text field prefilled;
   Insert.
3. **Keyboard-only pass:** Tab once into the tree, move with Up/Down, press with Enter, and complete
   an insert — no mouse interaction at all. This is what makes the roving-tabindex model real.
4. Save; assert the stored body holds `<a href="/courses/n/<pk>/">`.
5. Visit the unit as a student and click the link. Assert the URL ends `#node-<pk>` **and** that the
   row element inside `#node-<pk>` (`.outline-node__head`, or `.outline-unit` for a unit) has a
   non-default computed background — "highlighted" is not otherwise an assertable condition, and a
   `:target` rule mis-scoped to the `<li>` would pass a weaker check. Repeat for a unit target,
   asserting arrival on the unit page.
6. Re-open the editor, place the caret in the link, re-open the dialog, assert the tab and fields
   prefilled, click *Remove link*, assert the anchor is gone and the text remains.

**Visual**

Playwright screenshots, light and dark, of the dialog (both tabs, including the scrolled tree) and
of a rendered internal link (and an external one, for the outbound marker), judged separately per
theme. The `::backdrop` is judged with them.

## i18n

Every new string lives in `_link_dialog.html` as `{% trans %}` — tab labels, the dialog title, *Link
text*, *Remove link*, *Insert*, *Cancel*, the filter placeholder, the loading / empty-tree /
no-match / fetch-error+retry / target-not-in-this-course lines, and one message per URL-rejection
row. Because they are template strings, `makemessages -l pl -l en --no-obsolete` extracts them
normally; no `JavaScriptCatalog` route is introduced, and none is needed.

The two picker partials contribute **no new msgids**: a row's only text is the node title (author
data) and the kind chip, which renders `get_kind_display` or the builder's literal `L` / `Q` with a
`get_unit_type_display` title — all existing model choice labels. No `{% trans %}` belongs there, and
adding one would create duplicate catalog entries.

`tests/test_i18n_po_health.py` owns the whole-catalog guards, and two of them bind here: no fuzzy
entries, and **no untranslated Polish msgstr** (`test_pl_has_no_untranslated_msgid`). Every new
string must therefore ship with a real Polish translation — an empty msgstr turns that test red for a
reason unrelated to the feature. Fuzzy entries must be cleared properly: both the `#, fuzzy` line and
the `#| msgid` comment, since a fuzzy match arrives pre-filled from an unrelated msgid. Both `.mo`
files are regenerated as part of the change.
