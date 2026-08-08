# Content editors

A **lesson** unit is a sequence of content elements — text, media, and embeds —
that students read top to bottom. Open a lesson from the builder to reach its
**editor**, a two-pane screen — Editor and live Preview, with an
Editor/Split/Preview view toggle. The Editor pane's outline lists its elements
in order, and its **Add element** button opens a type menu; at the top level
of a lesson it shows four groups — Content, Interactive, Questions, and
Structure (Interactive is absent when editing a quiz). See
[Quiz editors](quiz-editors) for the Questions group. See
[Interactive elements](interactive-elements) for the Interactive group.

![The lesson editor with content blocks](static:core/img/help/content-editor.en.png)

## Working with elements

Each element is added, edited, and saved independently:

- Click **Add element** and pick a type card to insert a new element at the
  end of the unit.
- Click an existing element in the outline to open its editor form in place.
- Drag elements in the outline to reorder them; the reading order updates
  immediately.
- Delete an element using the 🗑 button on its row; its editor form offers
  only **Save** and **Cancel**.

Every element also carries an optional **Label (optional)** field (placeholder
*Shown in the element list*), used only to label it in the outline — students
never see it.

## Content element types

{el:text} **Text** — the workhorse block. A rich-text field supporting headings, lists,
bold/italic, links, and inline math written with KaTeX delimiters (e.g.
`$x^2$`). Use it for explanations, instructions, and any prose between other
elements.

{el:image} **Image** — embeds a picture from the course's media library. Pick an existing
upload or upload a new one on the spot (see [Media manager](media-manager));
add optional **alt text** for accessibility (leave it blank only for a purely
decorative image) and an optional **caption** shown under the picture. Choose
a **Size** — Small, Medium, Large, or Full — to set how big the picture
appears: each is a bounding box, so the image scales to fit inside a box this
big while keeping its shape, never stretching or cropping. **Full** is the
default and matches the picture's original behavior; at every size, a picture
is never taller than the reader's screen.

{el:video} **Video** — embeds a video two ways: pick an uploaded video file from the
media library, *or* paste a link to a hosted video (YouTube, Vimeo, and
similar are auto-normalized to their embeddable form). Provide exactly one of
the two — not both, not neither.

{el:iframe} **Iframe** — embeds any external interactive page by pasting its share link or
full `<iframe>` snippet, most commonly a GeoGebra applet. Pasting a GeoGebra
link is canonicalized to its worksheet view automatically, and the embed keeps
the original aspect ratio when the source provided width/height. Give it a
descriptive **title** for accessibility. Only domains the platform admin has
allow-listed can be embedded.

{el:math} **Math** — a standalone display-style math block. Enter LaTeX; it renders
client-side with KaTeX. Use this for a formula that deserves its own line
rather than inline text; for a short inline expression, put it inside a Text
element instead.

{el:html} **HTML** — raw HTML/CSS/JS for authors who need something the other block
types can't do (a custom widget, an animation, a bespoke interactive). It runs
in a sandboxed frame isolated from the rest of the page, and the course's
shared CSS/JS (configured elsewhere in the course settings) is available to
every HTML block in that course. Use it sparingly — it is not sanitized, so
only trusted authors should use it, and it is harder to maintain than the
other block types.

{el:table} **Table** — a WYSIWYG grid editor whose toolbar is always visible, with
cell-scoped tools (bold, italic, underline, inline math, and text/vertical
alignment) disabled until you focus a cell, then applied to it in place. Use
the row/column handles to insert or delete rows and columns. Toggle
**Header row** and **Header column** to style the first row/column
differently, and choose a **Borders** style (**Grid**, **Rows**,
**Header only**, or **None**). A cell holds rich text *or* a picture, never
both: focus a cell and click **Image cell** to pick one from the media
library (see [Media manager](media-manager)) — this replaces any text the
cell already held — then add optional **alt text** and choose a **Size** —
Small, Medium, Large, or Full — each a bounding box the picture scales to
fit without stretching or cropping; Small/Medium/Large stay a fixed size
whatever the column ends up being, while Full instead fills the column.
**Remove image** brings back the cell's original text if you converted it
to a picture earlier in the same visit — but only if you haven't inserted
or deleted a row/column, or merged or split cells, in between; any of those
structural edits clears the held text, so Remove image then leaves an empty
cell instead. Reopening a saved table and removing its picture there
instead leaves an empty text cell too, since nothing survives a save to
restore. Select a range of cells with Shift+click, or
extend it a slot at a time with **Alt+Shift+Arrow**, then press **Merge
cells** to combine the range into one cell — only the top-left cell's
content is kept, text or picture alike, and you're asked to confirm first if
any of the other cells in the range weren't empty. **Split cell** undoes a
merge, leaving the freed cells empty. **Header cell** toggles a single cell
between plain and header styling; it's greyed out — unavailable while the
row or column header option covers this cell — whenever **Header row** or
**Header column** already promotes that cell, since those toggles already
control it there. In a table with **Header column** on, merging away a
row's first cell promotes
the next cell in that row to a header for students, even though the editor
keeps showing it as a plain cell. A table can't be grown past 50 rows by 20
columns; a table imported larger than that stays fully saveable as long as
you don't try to make it even larger, but shrinking it back below the limit
is one-way — you won't be able to widen it past the cap again afterwards.

{el:gallery} **Gallery** — a carousel of images shown one at a time with navigation
controls. Click **Add image** to pick from the media library, give each image
an optional rich-text description, and reorder or remove images with the row
controls. **Description position** places each caption **Below image** or
**Above image**.

{el:callout} **Callout** — a framed, always-visible aside for a note that should stand out
from the surrounding text. Choose a **Kind** (Example, Note, Tip, Important, or Task —
each with its own accent colour and icon), an optional **Heading** (falls back
to a default per kind when left blank), and rich-text body content. A callout
is also a container: it can hold nested elements added below the body from
its own **Add element** menu — see "Containers and nesting" below for what
can go inside.

{el:tabs} **Tabs** — a container that splits its content into labelled tabs a student
switches between; add, remove, reorder, and label tabs from the editor's row
list. Each tab holds its own nested elements, added from that tab's own
**Add element** menu — see "Containers and nesting" below for what can go
inside.

{el:twocolumn} **Columns** — a container that lays its content out side by side in 2 to 4
columns; set the **Number of columns** and fill each column from its own
group in the element list below the editor. Shrinking the count keeps the
leftmost columns and moves the content of any dropped column into the last
remaining one, rather than deleting it. See "Containers and nesting" below
for what can go inside.

{el:beforeafter} **Before / after** — a container with two fixed slots, **Before** and
**After**, that a student flips between with a single toggle button; unlike
Tabs and Columns it always has exactly two slots. Fill each slot from its own
group in the element list below the editor. Give the button an optional
**Button label** shown as its text; leave it blank and the button shows only
an icon, with "Switch content" as its accessible name. See "Containers and
nesting" below for what can go inside — quiz questions can't go in either
slot.

## Structure

{el:slidebreak} **Slide break** — a marker, not a content block: it carries no fields and
renders nothing itself. Adding one or more Slide breaks to a lesson splits it
into a paginated slideshow/deck view instead of one long scroll, with each
break starting a new slide. A break at the very start or end, or two breaks in
a row, never produces an empty slide — it's simply absorbed.

## Containers and nesting

Tabs, Columns, Spoiler, Callout, and Before / after are the five container
types. A container can hold another container, up to three container levels
— for example a Spoiler holding a Tabs container that holds another Spoiler.
Ordinary content sits inside that third level, so a nested element can be
four levels down. The third-level container's own **Add element** menu
offers leaves only: no further container, question, or Slide break.

Inside any container, a nested **Add element** menu offers the non-container
Content types — Text, Image, Video, Iframe, Math, HTML, Table, Gallery —
plus, where depth still allows it, the Tabs, Columns, Spoiler, Callout, and
Before / after container cards themselves. In a lesson it also offers the
[Interactive elements](interactive-elements) self-checks (Show more, Fill in
& confirm, Choose & confirm, Switch grid, Fill-in table, Step-by-step,
Checklist, Guess the number) and Fill in the blanks.

Interactive elements are lesson-only: the Interactive group doesn't appear at
all when editing a quiz. So inside a quiz, a nested add-menu offers the
Content types plus — where depth allows — Tabs, Columns, Callout, and
Before / after; Spoiler and Fill in the blanks are never offered nested in a
quiz.

## Tips

- Prefer Text for anything that's mostly prose; reach for Math or HTML only
  when you need their specific capability.
- Reuse media: uploading the same picture twice wastes storage and clutters
  the library — pick the existing asset from the media picker instead.
- Preview the unit as a student would see it before publishing a course, to
  catch layout issues (long captions, oversized iframes) early.

![A lesson page as students see it](static:core/img/help/content-consume.en.png)

## See also

- [Quiz editors](quiz-editors) — the question element types, used in both
  lessons (as practice) and quizzes (as assessment).
- [Interactive elements](interactive-elements) — the lesson-only self-check
  types; see "Containers and nesting" above for how deep they nest and which
  containers accept them.
- [Media manager](media-manager) — uploading and organizing images and videos.
- [Building a course](builder) — where units live in the course outline.
