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
- The link dialog: a server-rendered partial plus `link_dialog.js`, and the `text_toolbar.js`
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
| `templates/courses/manage/editor/editor.html` | `data-link-picker-url` on `section.editor`; `{% include %}` of the dialog partial **outside the swapped region** (see §4); `<script src="link_dialog.js" defer>` |
| `templates/courses/manage/editor/_link_dialog.html` | **new** — the dialog markup, all strings `{% trans %}` |
| `templates/courses/manage/editor/_link_picker_node.html` | **new** — one tree row, self-including for children |
| `templates/courses/_outline_node.html` | per-node `id` |
| `courses/static/courses/js/link_dialog.js` | **new** |
| `courses/static/courses/js/text_toolbar.js` | `case "link":` only |
| `courses/static/courses/css/editor.css` | dialog + picker styling, incl. duplicated `.tree__badge*` rules |
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

The quiz branch is explicit rather than delegated. `lesson_unit` does redirect a quiz unit onward to
`quiz_unit`, so delegating would work — but it would cost a second redirect hop on every quiz link,
and it would couple this view to an implementation detail of another one.

Storing a slug-free permalink is the point of the route: `/courses/n/1234/` keeps working when a
course is re-slugged, and the redirect target can change (route renames, a future chapter page)
without touching a single stored body.

**Nothing constructs this URL by string concatenation.** The picker partial emits it per row with
`{% url %}` (§3) and the JS copies the attribute verbatim, so the route name is the single source of
the URL shape. A test asserts the emitted value equals `reverse("courses:node_permalink", ...)`, so
renaming the route fails a test instead of silently invalidating every future link.

### 2. Outline anchors — `templates/courses/_outline_node.html`, `courses.css`

The `<li>` gains `id="node-{{ item.node.pk }}"`. Uniformly, for every kind — the `<li>` is shared
markup and a `{% if %}` around an `id` earns nothing. Units already link to their own page and will
not normally be reached by fragment, but the attribute is harmless and keeps the rule "every node
has an anchor" true.

CSS adds a `:target` highlight so the reader can see which row they were sent to, plus
`scroll-margin-top`. **The reason for `scroll-margin-top` is breathing room, not sticky chrome** —
measured: `.app-header` is `position: relative` (`core/static/core/css/app.css:22`) and `outline.html`
renders `.outline` in the normal `.app-main` flow, so nothing overlays the target row. Without the
declaration the row lands flush against the viewport top with no context above it; a
`var(--space-4)`-ish offset restores a line of context. If implementation finds the flush landing
acceptable, dropping the declaration is fine — what must not survive is a false justification for
keeping it.

The highlight must be legible in both themes — judged separately, per house rule, not inferred from
the light screenshot.

### 3. Picker endpoint — `courses/views_manage.py`, `templates/courses/manage/editor/_link_picker_node.html`

```python
path("manage/courses/<slug:slug>/link-picker/", views_manage.link_picker,
     name="manage_link_picker"),
```

`@login_required`, `can_manage_course` or `PermissionDenied`, then renders the course tree from the
existing `_children_map(course)` helper — one query, `parent_id -> [children]`, already used by the
builder view. Like `builder`, the view passes `children_map` **plus** `top_nodes = cmap.get(None, [])`:
`_children_map` keys roots under `None`, which a template cannot index. The view renders the
**partial standalone** (no `base.html` extension), because the dialog fetches it and injects the
markup directly.

**Recursion: one self-including partial**, like `templates/courses/_outline_node.html`, which
`{% include %}`s itself for each child inside a nested `<ol>`.

This deliberately differs from the builder tree, and the difference is worth stating because the
builder is the obvious thing to copy. `_tree_node.html` does **not** include itself: it includes
`_scope.html` (`_tree_node.html:44`), which loops and includes `_tree_node.html` back
(`_scope.html:8`) — mutual recursion. That two-file split exists to hoist work the picker does not
have: `_scope.html` reverses `manage_node_rename` **once per scope** rather than once per row (its
own comment records an 840-node course paying 840 reversals), and it emits the add-affordance and
`data-scope` / `data-updated` metadata for drag-and-drop. A read-only picker has no rename URL, no
add button and no scope tokens, so it takes the simpler single-partial form. There is likewise no
`depth` variable anywhere in the builder tree — indentation is structural, from the nested lists.

Each row is a **`<button type="button">`** carrying:

- `data-node="{{ n.pk }}"` — the pk, for prefill matching;
- `data-href="{% url 'courses:node_permalink' node_pk=n.pk %}"` — the href, reversed server-side;
- `data-title="{{ n.title }}"` — the default link text;
- `aria-pressed` — the selected state, and the single source of the internal tab's target;
- a `tree__badge tree__badge--{{ n.kind }}` chip plus the title text.

A `<button>` rather than a `<div>` with a click handler: the picker is the primary control of the
whole feature, and a div-with-listener is unreachable by keyboard. Selection is exactly one pressed
row; clicking another moves the pressed state. §Testing requires a keyboard-only path to a
selection, so this cannot regress silently.

**Styling: only the badge is borrowed.** Layout uses picker-local `.link-picker__*` classes defined
in `editor.css` (the nested `<ol>` indentation, the row, its hover and pressed states). The builder's
`.tree__scope` / `.tree__row` / `.tree__rowhead` are *not* referenced, because they live in
`builder.css`, which the editor page does not load — borrowing the names would ship an unindented,
unstyled list. The one exception is `.tree__badge` and its four kind modifiers (`builder.css:35-37`),
duplicated into `editor.css` with a comment naming its twin, so the chip reads identically in both
places. Adding `builder.css` to the editor page instead is not merely undesirable but already
forbidden: `tests/test_editor_styles.py` asserts the editor page does not load it (that stylesheet
carries `.tree__title` overrides for the inline-rename `<input>` which exist to win a specificity
fight with `app.css`). The "ships styled" assertion in §Testing covers every class the picker uses,
not just the badge.

Whole-tree-in-one-response is a deliberate choice over server-side search. The largest real course
(`mat-pp`) is ~925 nodes; at roughly 150–200 bytes per row that is on the order of 150–200 KB —
an order-of-magnitude estimate, not a measurement, and worth re-checking against the real row markup
during implementation. One fetch per editor page, cached in the dialog module after the first open,
filtered client-side thereafter. The media picker searches server-side because a media library is
unbounded and its rows carry thumbnails; a course tree is neither.

**Cache lifetime is the page load, and staleness is accepted.** A node renamed or added in another
tab will not appear until the editor page is reloaded. The tree is fetched once because the editor
page is long-lived and `editor.js` swaps element fragments repeatedly; re-fetching per open would
cost a ~200 KB round trip for a tree that changes rarely during an editing session.

**The unit being edited is included** in the tree, and selectable. A self-link is odd but harmless,
and excluding it would need the picker to know which unit hosts the element — context it otherwise
does not need.

**Filtering** matches a case-insensitive substring of the node title only (not the kind label, which
is a translated word and would match half the tree in Polish). A matching row keeps its ancestors
visible, `disabled` and visually recessed if they do not themselves match, so the indentation still
reads as a path rather than a flat list. Four states are defined rather than left to chance:

| state | behaviour |
|---|---|
| course has no nodes | the panel shows a translated "This course has no content yet." line; *Insert* stays disabled on this tab |
| filter matches nothing | a translated "No matches." line; the tree is hidden, not emptied |
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

**The include must sit outside the region `editor.js` swaps.** `editor.js` replaces the editor
pane's `innerHTML` on every element-form swap and then re-runs `window.libliInitRte(editorPane)`.
`editor.html` already includes partials *inside* `section.editor`, so "included once by editor.html"
is not precise enough: dropped into the swapped region, the `<dialog>` and every listener bound to
it at load are destroyed on the first save, producing an intermittent dead toolbar button that is
painful to attribute. The include goes at the end of `section.editor`, as a sibling of the swapped
pane. A static test asserts the dialog markup is not inside the swapped scope.

**Markup** (`<dialog class="link-dialog">`, in the page from first paint, closed):

- a translated dialog title, referenced by `aria-labelledby` on the `<dialog>` (the cited precedent
  does set one — `math_input.js` applies `aria-label` from `data-msg-math` — so omitting it would
  regress against the repo's own bar);
- two tab `<button type="button">`s reusing the existing `.picker__tabs` / `.picker__tab` /
  `.picker__panel` classes (verified: unnested top-level rules in `editor.css`, so they are reusable
  inside a `<dialog>`);
- the **In this course** panel: a filter `<input type="search">`, an empty mount point the tree is
  injected into, and the pre-rendered empty/no-match lines;
- the **Web address** panel: a URL `<input type="url">` and one pre-rendered message element per
  distinct rejection (disallowed scheme, protocol-relative, other relative path) plus the
  picker-fetch error;
- a shared **Link text** `<input type="text">`;
- **Remove link** / **Cancel** / **Insert**, all `type="button"`.

Every button carries an explicit `type="button"`, including the tabs. `editor.html` is full of
forms, and a bare `<button>` that ends up form-associated defaults to `type="submit"` — Insert would
post the element form. The repo's own toolbars set it on every control for the same reason.

**Messages are shown, never composed.** Each message is a pre-rendered element that JS only
toggles, so no string is assembled in JavaScript and `makemessages` sees all of them.

**Initial focus** is the filter input on the *In this course* tab and the URL input on *Web
address*. `showModal()` genuinely traps focus here because the dialog has focusable children — the
caveat recorded from the image-zoom work (a dialog with *no* focusable child does not trap) does not
apply.

**Ownership is split, and the split is the interface.** `link_dialog.js` owns its own dialog DOM —
tabs, fetch, filter, validation — and nothing else; it never touches an editing surface. The
callback returns a decision, and `text_toolbar.js` performs every mutation. This mirrors
`window.libliMathInput.open(cb)`, which `text_toolbar.js` already calls for the ∑ button.

```js
// link_dialog.js — owns only its own dialog. Knows nothing about the surface or the Range.
window.libliLinkDialog.open({ pickerUrl, existing, touchedAnchors, selectionText }, cb);
//   existing:       {href, text} | null   — set only when exactly ONE anchor wholly contains the range
//   touchedAnchors: integer               — how many anchors the range intersects
//   selectionText:  string                — "" when the range is collapsed
//   cb(result):     {href, text} | {remove: true} | null      (null = dismissed)
```

`text_toolbar.js`'s `case "link":` — the only place it changes — does all of the following:

1. guards with `if (!window.libliLinkDialog) break;`, exactly as the math command guards on
   `window.libliMathInput`;
2. stashes the current `Range` **before** `showModal()` moves focus (the discipline the math
   command already uses);
3. computes the anchors intersecting the range, within `surface`, and from them `existing` and
   `touchedAnchors`. The upward walk must hop off a text node first —
   `(n.nodeType === 3 ? n.parentNode : n).closest("a")` — because `Range.startContainer` is usually
   a text node, which has no `closest`; `currentBlock` in the same file already does this hop;
4. calls `open()`;
5. on a non-null result, re-focuses the surface, restores the `Range`, performs the mutation below,
   and dispatches `new Event("input")` on the surface — which is what drives `sync()` into the
   hidden textarea.

**The stashed Range must belong to the invoking surface.** Before restoring, step 5 requires
`surface.contains(range.commonAncestorContainer)`; otherwise it falls back to appending at the end
of `surface`, matching the math command's own `else` branch. This is not hypothetical: several RTE
surfaces are live at once on the editor page (`_edit_choicequestion.html` mounts a `data-rte-source`
textarea for the stem *and* another for the explanation, each with its own toolbar), and the
existing math command captures `sel.getRangeAt(0)` with no containment check at all. Clicking the
*explanation* toolbar while the selection sits in the *stem* would otherwise insert the anchor into
the wrong surface — whose `input` listener never fires, so the change would never be synced and
would vanish on save.

**The surface must still be attached.** `editor.js` can replace the pane while the dialog is open
(the page carries `data-msg-conflict="This changed elsewhere — reloaded to the latest."`, so a
background reload path exists). Step 5 therefore checks `surface.isConnected` first and, when false,
discards the result with the same inline conflict message rather than mutating an orphaned node —
which would look like a successful insert and then lose the link on save.

**One dialog at a time.** `open()` while a call is pending is rejected (the pending callback stands);
it does not supersede. The module is a singleton, like `math_input.js`, whose module-level callback
would otherwise be silently overwritten.

**Insertion semantics.** An ordered decision, first match wins — the conditions overlap, so ordering
is part of the specification. "Inside" means within `surface`:

| # | state | on Insert |
|---|---|---|
| 1 | the range lies **strictly inside exactly one** anchor (collapsed or not) | that anchor is edited in place: `href` updated, contents replaced by the link text |
| 2 | the range is non-empty and touches anchors that do **not** wholly contain it (or touches none) | every touched anchor is unwrapped, then the range is replaced by **one** anchor holding the link text |
| 3 | the range is collapsed and inside no anchor | a new anchor is inserted at the caret |

Rule 1 covers a partial selection inside an existing link — select one word of a five-word link and
Insert, and the *whole* link is retargeted. The alternative reading (unwrap, then re-link only the
selected word) would silently strip the anchor off the other four words with no undo available, and
"I put my caret in a link and pressed the link button" much more plausibly means *edit this link*.
Rule 2's unwrap clause is what keeps "one anchor, always" true for a selection that starts inside a
link and ends outside it, or spans two links.

One anchor, always — not `execCommand("createLink")`, which splits a multi-block selection into
several anchors and leaves the link text uneditable. A selection spanning block boundaries therefore
collapses to a single link; the selection's text content is offered as the default link text, so the
author sees what they are about to flatten before confirming.

**Remove link** is enabled whenever `touchedAnchors > 0`, and unwraps **all** touched anchors,
keeping their text. Defining it over the range rather than over `existing` is what makes it
meaningful for a selection spanning two links, where `existing` is `null`.

**The anchor's text is written as a text node** (`document.createTextNode` / `textContent`), never
`innerHTML`, and the *Link text* field is populated with `.value` from `data-title`. Node titles are
author-supplied and may contain `<`, `&` or a stray quote; routing them through `innerHTML` would
interpret them as markup on the way into a surface whose `innerHTML` is then saved.

**Link-text prefill precedence**, since up to three sources can supply it: a non-empty
`selectionText` wins, else `existing.text`, else — on the internal tab, once a node is selected —
that node's title. The node-title re-seed fires only on the internal tab and only while the field is
blank, so an author who deliberately cleared and retyped the text never has it overwritten.

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

**Opening on an existing link** prefills: the *Web address* tab for an ordinary URL, the *In this
course* tab with that node preselected when the href matches `/courses/n/<pk>/`.

**Link text does not track the node title.** Renaming a node later leaves existing link text alone.
The text is authored prose — it may be inflected, abbreviated, or mid-sentence ("as shown in *the
vertex form unit*"), and silently rewriting it would be wrong far more often than right.

**Dismissal.** Cancel, the Escape key, and a backdrop click all dismiss; all three route through a
single `close` event handler, which invokes the callback **exactly once** — with `null` unless a
result was committed by *Insert* or *Remove link*. Stating this pins the classic double-fire, where
a button handler and a `close` handler both call back.

**No-JS baseline is unchanged.** With JS off the textarea submits raw HTML and the server sanitises
it, exactly as today; an author can hand-type `<a href="/courses/n/12/">` and it will survive. The
dialog is progressive enhancement, like the rest of the RTE.

### 5. Student-side styling — `courses/static/courses/css/courses.css`

Two concrete treatments, scoped to `.el` — the wrapper every rendered element carries
(`el el--text`, `el el--question`, and the callout/spoiler bodies) — so site chrome and navigation
are untouched:

- `.el a[href^="/courses/n/"]` — an internal link reads as part of the course: the body link colour
  with a solid underline, and a small leading corner-arrow glyph via `::before`, `aria-hidden`
  through `content` (a CSS-generated glyph is not copied with the text and is not announced, which
  is what we want — the link text alone must carry the meaning).
- `.el a[href^="http"]` — an outbound marker via `::after`, same rationale.

Keying off the href prefix is what lets this work with no sanitiser change — recall that a `class`
on `<a>` would be stripped. Both rules are judged in light **and** dark separately, per house rule,
like the `:target` highlight.

Two acknowledged misclassifications, both benign and both cheaper to accept than to fix:

- A `mailto:` link matches neither selector and gets no marker. Acceptable — it is rare in course
  prose, and the alternative is a third rule for a case authors barely use.
- An absolute same-origin permalink would match the *outbound* rule. The dialog normalises those to
  relative form (§4), so this only affects hand-typed HTML.

This assumes the app is served from the domain root; a `SCRIPT_NAME` prefix would break the prefix
match. That is true of the deployment today and is stated here as an assumption rather than
discovered later. The JS side does not share the assumption — it copies `data-href` from the picker
rather than building a path.

## Data flow

```text
author clicks 🔗
  -> text_toolbar.js guards on window.libliLinkDialog, stashes the Range,
     computes intersecting anchors -> existing {href,text}|null + touchedAnchors
  -> libliLinkDialog.open({pickerUrl, existing, touchedAnchors, selectionText}, cb)
  -> dialog fetches /manage/courses/<slug>/link-picker/ (once per page, then cached)
  -> author presses a row  =>  {href: row.dataset.href, text: link-text field}
     or types a URL        =>  total contract: scheme-checked, https:// prefixed,
                               permalink normalised, protocol-relative rejected
     or dismisses          =>  null   (Cancel / Escape / backdrop, callback fires exactly once)
  -> text_toolbar.js checks surface.isConnected and range containment,
     restores the Range, applies insertion rule 1/2/3, fires "input"
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
| target's course not accessible | 404, **not** 403 — see §1. Cannot normally happen for same-course links, which is why the picker is same-course only. |
| **target now lives in another course** | See below — the one risk part 1 carries. |
| URL rejected by the contract | inline message in the dialog, before it can be silently stripped or silently mis-rendered at save. |
| scheme-less URL that looks like a host | auto-prefixed `https://`; the author sees the normalised value before inserting. |
| picker fetch fails | the *In this course* tab shows an inline error; the *Web address* tab still works. The dialog never becomes a dead end. |
| surface detached while the dialog is open | the result is discarded with the existing conflict message; nothing is written to an orphaned node. |
| stashed range not inside the invoking surface | falls back to appending at the end of that surface, as the math command does. |
| author dismisses | callback receives `null` once; the surface is untouched and the caret restored. |

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
- The quiz assertion is on the **first hop's `Location`**, with the fixture pinned to *no
  submission*. `views.quiz_unit` itself 302s to `quiz_results` when the student's submission is
  `SUBMITTED`, so a followed redirect chain — or a submitted fixture — would fail for a reason
  unrelated to the branch under test.
- **Resolver regression:** `resolve("/courses/n/12/")` → `node_permalink` and `resolve("/courses/n/")`
  → `course_outline`. The no-collision claim is one urls.py reordering away from silently breaking a
  course slugged `n`, and prose is not a guard.
- Sanitiser passthrough: an internal-link anchor survives `sanitize_html` byte-identically. This
  pins the assumption the whole design rests on, so a future sanitiser tightening fails loudly here
  instead of silently voiding every stored link.
- `link_picker`: 200 + every node present for a manager; 403 for a non-manager; 404 for an unknown
  slug; the response is a bare partial (no `<html>`). Each row's `data-href` equals
  `reverse("courses:node_permalink", kwargs={"node_pk": n.pk})`, so a route rename fails here rather
  than in production. Query count asserted — `_children_map` is one query and must stay one.
- `_outline_node.html` renders `id="node-<pk>"` for each kind.

**Static/asset**

- The dialog partial is included by `editor.html` **outside** the region `editor.js` swaps.
- `text_toolbar.js` no longer contains `window.prompt`, and guards on `window.libliLinkDialog`
  before use. Script *order* is convention only and gets no assertion: the guard makes order
  irrelevant, so an order test could never go red for a real defect — and a test that cannot fail is
  not evidence.
- `editor.css` defines every class the picker markup uses — the `.link-picker__*` layout classes and
  the duplicated `.tree__badge*` rules. Appended to `tests/test_editor_styles.py`, which already
  owns the "editor page does not load builder.css" assertion this depends on.

**JS behaviour** (jsdom-level or e2e, whichever the repo's existing habit favours)

- URL contract, one case per row of the table — including `//evil.com/x` → rejected,
  `example.com` → `https://example.com`, `javascript:alert(1)` → rejected, `../foo` → rejected, and
  `https://host/courses/n/12/` → `/courses/n/12/`.
- Insertion rules 1, 2 and 3. Rule 1 is exercised by a selection *strictly inside* a single anchor,
  asserting the whole anchor is retargeted and no text loses its link. Rule 2 is exercised by a
  selection that starts inside an anchor and ends outside it, asserting exactly one anchor
  afterwards.
- *Remove link* over a range spanning two anchors unwraps both.
- Two live surfaces: with the selection in the stem and the *explanation* toolbar clicked, nothing
  is written into the stem.
- A node title containing `<b>` is inserted as literal text, not markup.
- The callback fires exactly once per dismissal path (Cancel, Escape, backdrop).

**e2e (`-m e2e`, real browser, mandatory marker)**

Driving the real gesture, never `page.evaluate` shortcuts:

1. Open a unit editor, add a text element, type prose, select a word.
2. Click the toolbar link button; the dialog opens; switch to *In this course*; type in the filter
   and assert matching rows keep their ancestors visible; type a string matching nothing and assert
   the no-match line; clear it; press a chapter row; confirm the link-text field prefilled; Insert.
3. **Keyboard-only pass:** reach and press a row using Tab/arrow keys and Enter alone, with no mouse
   interaction, and complete an insert.
4. Save; assert the stored body holds `<a href="/courses/n/<pk>/">`.
5. Visit the unit as a student, click the link, assert arrival on the outline with the target row
   highlighted; repeat for a unit target asserting arrival on the unit page.
6. Re-open the editor, place the caret in the link, re-open the dialog, assert the tab and fields
   prefilled, click *Remove link*, assert the anchor is gone and the text remains.

**Visual**

Playwright screenshots, light and dark, of the dialog (both tabs) and of a rendered internal link
(and an external one, for the outbound marker), judged separately per theme.

## i18n

Every new string lives in `_link_dialog.html` and `_link_picker_node.html` as `{% trans %}` — tab
labels, the dialog title, *Link text*, *Remove link*, *Insert*, *Cancel*, the filter placeholder,
the empty-tree and no-match lines, one message per URL-rejection row, and the picker-fetch error.
Because they are template strings, `makemessages -l pl -l en --no-obsolete` extracts them normally;
no `JavaScriptCatalog` route is introduced, and none is needed. Fuzzy entries must be cleared
properly — both the `#, fuzzy` line and the `#| msgid` comment — since a fuzzy match arrives
pre-filled from an unrelated msgid.
