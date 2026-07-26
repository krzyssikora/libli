# Internal content links — dialog and permalink

Part 1 of two. Part 2 (`2026-07-26-internal-link-durability-design.md`) makes these links survive
export→import and warns before a linked node is deleted. Part 1 is shippable on its own.

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
- The link dialog (`link_dialog.js`) and the `text_toolbar.js` change that opens it.
- A picker endpoint serving the course tree to the dialog.
- Student-side styling distinguishing internal from external links.

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

- **Table and fill-table cells.** `sanitize_cell` allows `CELL_TAGS = {strong, b, em, i, u, br}` —
  no `<a>` at all. A link authored into a cell would be silently stripped on save. Making cells
  link-bearing is a sanitiser change with its own blast radius; it is not part of this.

- **Cross-course links.** The picker shows one tree: the course being edited. A link to another
  course would land any student not enrolled there on a 403, and — see part 2 — could not be
  rewritten on export anyway, since the archive only knows about the exported course. Pasting an
  absolute URL in the *Web address* tab remains possible for an author who really wants this.

- **A link audit page.** Listing every internal link in a course and flagging the broken ones is a
  reasonable follow-up; it is not needed to ship the feature.

## Architecture / components

Five pieces.

### 1. The permalink route — `courses/urls.py`, `courses/views.py`

```python
path("courses/n/<int:node_pk>/", views.node_permalink, name="node_permalink"),
```

Verified free: `resolve("/courses/n/12/")` raises `Resolver404` against the current URLconf. No
collision with `courses/<slug:slug>/`, which matches two path segments where this matches three.
(`/courses/n/` — a course whose slug is literally `n` — still resolves to `course_outline`, as it
does today.)

```python
@login_required
def node_permalink(request, node_pk):
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if not can_access_course(request.user, node.course):
        raise PermissionDenied
    if node.kind == ContentNode.Kind.UNIT:
        name = ("courses:quiz_unit" if node.unit_type == ContentNode.UnitType.QUIZ
                else "courses:lesson_unit")
        return redirect(name, slug=node.course.slug, node_pk=node.pk)
    return redirect(
        reverse("courses:course_outline", kwargs={"slug": node.course.slug})
        + f"#node-{node.pk}"
    )
```

The quiz branch is explicit rather than delegated. `lesson_unit` does redirect a quiz unit onward to
`quiz_unit`, so delegating would work — but it would cost a second redirect hop on every quiz link,
and it would couple this view to an implementation detail of another one.

Storing a slug-free permalink is the point of the route: `/courses/n/1234/` keeps working when a
course is re-slugged, and the redirect target can change (route renames, a future chapter page)
without touching a single stored body.

### 2. Outline anchors — `templates/courses/_outline_node.html`, `courses.css`

The `<li>` gains `id="node-{{ item.node.pk }}"`. Uniformly, for every kind — the `<li>` is shared
markup and a `{% if %}` around an `id` earns nothing. Units already link to their own page and will
not normally be reached by fragment, but the attribute is harmless and keeps the rule "every node
has an anchor" true.

CSS adds `scroll-margin-top` (the outline sits under sticky chrome, so a raw fragment jump would
park the target row underneath it) and a `:target` highlight so the reader can see which row they
were sent to. The highlight must be legible in both themes — judged separately, per house rule, not
inferred from the light screenshot.

### 3. Picker endpoint — `courses/views_manage.py`, `templates/courses/manage/editor/_link_picker.html`

```python
path("manage/courses/<slug:slug>/link-picker/", views_manage.link_picker,
     name="manage_link_picker"),
```

`@login_required`, `can_manage_course` or `PermissionDenied`, then renders the whole course tree
from the existing `_children_map(course)` helper — one query, `parent_id -> [children]`, already
used by the builder view. The partial mirrors `_move_picker.html`: one row per node carrying
`data-node="{{ n.pk }}"` and `data-title`, a `tree__badge tree__badge--{{ n.kind }}` chip, indented
by depth.

Whole-tree-in-one-response is a deliberate choice over server-side search. The largest real course
(`mat-pp`) is ~925 nodes, which is roughly 110 KB of markup — one fetch per editor page, cached in
the dialog module after the first open, filtered client-side thereafter. The media picker searches
server-side because a media library is unbounded and its rows carry thumbnails; a course tree is
neither.

### 4. The dialog — `courses/static/courses/js/link_dialog.js` (new), `text_toolbar.js` (changed)

The module exposes one entry point, deliberately shaped like the `window.libliMathInput.open(cb)`
that `text_toolbar.js` already calls for the ∑ button:

```js
window.libliLinkDialog.open({ pickerUrl, existing, selectionText }, function (result) { ... });
// result: {href, text} | {remove: true} | null (cancelled)
```

`text_toolbar.js` changes in exactly one place — `case "link":` in `applyCmd` — from
`window.prompt` to this call. **No template changes.** All four toolbars (`_rte_toolbar.html` plus
the inlined copies in `_edit_text.html`, `_edit_spoiler.html`, `_edit_callout.html`) already carry
`data-cmd="link"`, and the command is dispatched centrally, so the feature reaches every rich-text
surface without touching a single one of them. This is the rare change that does *not* widen the
editor twin-drift surface guarded by #169.

**Markup.** A modal `<dialog>` appended to `document.body` — never inside the contenteditable
surface, which would put dialog markup into the saved body. Two tab buttons reusing the existing
`.picker__tabs` / `.picker__panel` pattern, the tree panel, a URL input, a shared *Link text* field,
and *Remove link* / *Cancel* / *Insert* buttons. `showModal()` genuinely traps focus here because
the dialog has focusable children — the caveat recorded from the image-zoom work (a dialog with *no*
focusable child does not trap) does not apply.

The picker URL reaches the module from `data-link-picker-url` on `section.editor`, alongside the
`data-picker-url` and `data-msg-*` attributes that element already carries.

**Selection.** The caret must be captured *before* `showModal()` moves focus: `open()` stashes the
current `Range`, and the callback re-focuses the surface and restores it before mutating the DOM —
the same discipline the math command already uses.

**Insertion semantics**, stated explicitly because "insert a link" has several defensible readings:

| caret / selection state | on Insert |
|---|---|
| inside an existing `<a>` | that anchor's `href` is updated and its contents replaced by the link text |
| non-empty selection | the selected range is replaced by **one** anchor holding the link text |
| collapsed caret | a new anchor is inserted at the caret |

One anchor, always — not `execCommand("createLink")`, which splits a multi-block selection into
several anchors and leaves the link text uneditable. A selection spanning block boundaries therefore
collapses to a single link; the selection's text content is offered as the default link text, so the
author sees what they are about to flatten before confirming.

Opening with the caret inside an existing anchor prefills: the *Web address* tab for an ordinary
URL, the *In this course* tab with that node preselected when the href matches
`/courses/n/<pk>/`. *Remove link* is enabled only in that state, and unwraps the anchor, keeping its
text.

After any mutation the module dispatches `new Event("input")` on the surface, which is what drives
`text_toolbar.js`'s `sync()` into the hidden textarea.

**Link text does not track the node title.** Renaming a node later leaves existing link text alone.
The text is authored prose — it may be inflected, abbreviated, or mid-sentence ("as shown in *the
vertex form unit*"), and silently rewriting it would be wrong far more often than right.

**No-JS baseline is unchanged.** With JS off the textarea submits raw HTML and the server sanitises
it, exactly as today; an author can hand-type `<a href="/courses/n/12/">` and it will survive. The
dialog is progressive enhancement, like the rest of the RTE.

### 5. Student-side styling — `courses/static/courses/css/courses.css`

```css
.el a[href^="/courses/n/"] { /* internal-link affordance */ }
.el a[href^="http"]        { /* outbound marker */ }
```

Scoped to `.el`, the wrapper every rendered element carries (`el el--text`, `el el--question`, and
the callout/spoiler bodies), so site chrome and navigation are untouched. Keying off the href prefix
is what lets this work with no sanitiser change — recall that a `class` on `<a>` would be stripped.

This assumes the app is served from the domain root; a `SCRIPT_NAME` prefix would break the prefix
match. That is true of the deployment today and is stated here as an assumption rather than
discovered later.

## Data flow

```text
author clicks 🔗
  -> text_toolbar.js applyCmd("link") stashes Range, calls libliLinkDialog.open()
  -> dialog fetches /manage/courses/<slug>/link-picker/ (once, then cached)
  -> author picks a node  =>  href = "/courses/n/1234/", text = node title (editable)
     or types a URL       =>  href = as typed
  -> callback restores the Range, writes one <a> into the surface, fires "input"
  -> sync() copies surface.innerHTML into the hidden textarea
  -> POST -> sanitize_html keeps <a href> verbatim -> stored

student clicks the link
  -> GET /courses/n/1234/
  -> 403 if the course is not accessible; 404 if the node is gone
  -> 302 to lesson_unit / quiz_unit, or to the outline + #node-1234
```

## Error handling

- **Target deleted** → `get_object_or_404` → the illustrated 404 page (#167). Accepted and
  deliberate: part 2 adds a warning at delete time so this is rare rather than routine.
- **No access to the target's course** → `PermissionDenied` → illustrated 403. Cannot normally
  happen for same-course links, which is precisely why the picker is same-course only.
- **Picker fetch fails** → the *In this course* tab shows an inline error and the *Web address* tab
  still works. The dialog never becomes a dead end.
- **Author cancels** → callback receives `null`; the surface is untouched and the caret restored.

## Testing

Per house rule, every guard is falsified before it is trusted: delete the behaviour it protects and
require RED. A test that has never failed is not evidence.

**Python**

- `node_permalink`: lesson unit → `lesson_unit` URL; quiz unit → `quiz_unit` URL (asserting *one*
  redirect, which is the whole reason the branch is explicit); chapter/section/part → outline URL
  ending `#node-<pk>`; unknown pk → 404; course not accessible → 403; anonymous → login redirect.
- Sanitiser passthrough: an internal-link anchor survives `sanitize_html` byte-identically. This
  pins the assumption the whole design rests on, so a future sanitiser tightening fails loudly here
  instead of silently voiding every stored link.
- `link_picker`: 200 + every node present for a manager; 403 for a non-manager; 404 for an unknown
  slug. Query count asserted — `_children_map` is one query and must stay one.
- `_outline_node.html` renders `id="node-<pk>"` for each kind.

**Static/asset**

- `link_dialog.js` is loaded by the editor page, and `text_toolbar.js` no longer contains
  `window.prompt` (the concrete thing being replaced).

**e2e (`-m e2e`, real browser, mandatory marker)**

Driving the real gesture, never `page.evaluate` shortcuts:

1. Open a unit editor, add a text element, type prose, select a word.
2. Click the toolbar link button; the dialog opens; switch to *In this course*; filter; click a
   chapter row; confirm the link-text field prefilled; Insert.
3. Save; assert the stored body holds `<a href="/courses/n/<pk>/">`.
4. Visit the unit as a student, click the link, assert arrival on the outline with the target row
   highlighted; repeat for a unit target asserting arrival on the unit page.
5. Re-open the editor, place the caret in the link, re-open the dialog, assert the tab and fields
   prefilled, click *Remove link*, assert the anchor is gone and the text remains.

**Visual**

Playwright screenshots, light and dark, of the dialog and of a rendered internal link, judged
separately per theme.

## i18n

New UI strings (tab labels, *Link text*, *Remove link*, search placeholder, the picker error) are
translatable and added to both catalogs via `makemessages -l pl -l en --no-obsolete`. Fuzzy entries
must be cleared properly — both the `#, fuzzy` line and the `#| msgid` comment — since a fuzzy match
arrives pre-filled from an unrelated msgid.
