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

**Text** — the workhorse block. A rich-text field supporting headings, lists,
bold/italic, links, and inline math written with KaTeX delimiters (e.g.
`$x^2$`). Use it for explanations, instructions, and any prose between other
elements.

**Image** — embeds a picture from the course's media library. Pick an existing
upload or upload a new one on the spot (see [Media manager](media-manager));
add optional **alt text** for accessibility (leave it blank only for a purely
decorative image) and an optional **caption** shown under the picture.

**Video** — embeds a video two ways: pick an uploaded video file from the
media library, *or* paste a link to a hosted video (YouTube, Vimeo, and
similar are auto-normalized to their embeddable form). Provide exactly one of
the two — not both, not neither.

**Iframe** — embeds any external interactive page by pasting its share link or
full `<iframe>` snippet, most commonly a GeoGebra applet. Pasting a GeoGebra
link is canonicalized to its worksheet view automatically, and the embed keeps
the original aspect ratio when the source provided width/height. Give it a
descriptive **title** for accessibility. Only domains the platform admin has
allow-listed can be embedded.

**Math** — a standalone display-style math block. Enter LaTeX; it renders
client-side with KaTeX. Use this for a formula that deserves its own line
rather than inline text; for a short inline expression, put it inside a Text
element instead.

**HTML** — raw HTML/CSS/JS for authors who need something the other block
types can't do (a custom widget, an animation, a bespoke interactive). It runs
in a sandboxed frame isolated from the rest of the page, and the course's
shared CSS/JS (configured elsewhere in the course settings) is available to
every HTML block in that course. Use it sparingly — it is not sanitized, so
only trusted authors should use it, and it is harder to maintain than the
other block types.

**Table** — a WYSIWYG grid editor: click a cell to edit its rich text (bold,
italic, underline, inline math, and text/vertical alignment) in place, and use
the row/column handles to insert or delete rows and columns. Toggle
**Header row** and **Header column** to style the first row/column
differently, and choose a **Borders** style (**Grid**, **Rows**,
**Header only**, or **None**).

**Gallery** — a carousel of images shown one at a time with navigation
controls. Click **Add image** to pick from the media library, give each image
an optional rich-text description, and reorder or remove images with the row
controls. **Description position** places each caption **Below image** or
**Above image**.

**Callout** — a framed, always-visible aside for a note that should stand out
from the surrounding text. Choose a **Kind** (Example, Note, Tip, or Warning —
each with its own accent colour and icon), an optional **Heading** (falls back
to a default per kind when left blank), and rich-text body content.

**Tabs** — a container that splits its content into labelled tabs a student
switches between; add, remove, reorder, and label tabs from the editor's row
list. Each tab holds its own nested elements, added from that tab's own
**Add element** menu — see "Containers and nesting" below for what can go
inside.

**Columns** — a container that lays its content out side by side in 2 to 4
columns; set the **Number of columns** and fill each column from its own
group in the element list below the editor. Shrinking the count keeps the
leftmost columns and moves the content of any dropped column into the last
remaining one, rather than deleting it. See "Containers and nesting" below
for what can go inside.

## Structure

**Slide break** — a marker, not a content block: it carries no fields and
renders nothing itself. Adding one or more Slide breaks to a lesson splits it
into a paginated slideshow/deck view instead of one long scroll, with each
break starting a new slide. A break at the very start or end, or two breaks in
a row, never produces an empty slide — it's simply absorbed.

## Containers and nesting

Tabs and Columns are the two container types. Inside either one, a nested
**Add element** menu offers only the nine non-container Content types — Text,
Image, Video, Iframe, Math, HTML, Table, Gallery, Callout — and the nine
[Interactive elements](interactive-elements) self-checks (Show more, Fill in &
confirm, Choose & confirm, Switch grid, Fill-in table, Spoiler, Step-by-step,
Checklist, Guess the number). A container cannot hold another container, a
question, or a Slide break — those stay top-level.

Interactive elements are lesson-only: the Interactive group doesn't appear at
all when editing a quiz, so inside a quiz a Tabs or Columns container's
add-menu offers Content types only.

## Tips

- Prefer Text for anything that's mostly prose; reach for Math or HTML only
  when you need their specific capability.
- Reuse media: uploading the same picture twice wastes storage and clutters
  the library — pick the existing asset from the media picker instead.
- Preview the unit as a student would see it before publishing a course, to
  catch layout issues (long captions, oversized iframes) early.

## See also

- [Quiz editors](quiz-editors) — the question element types, used in both
  lessons (as practice) and quizzes (as assessment).
- [Interactive elements](interactive-elements) — the lesson-only self-check
  types nestable inside Tabs and Columns.
- [Media manager](media-manager) — uploading and organizing images and videos.
- [Building a course](builder) — where units live in the course outline.
