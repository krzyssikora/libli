# Content editors

A **lesson** unit is a sequence of content elements — text, media, and embeds —
that students read top to bottom. Open a lesson from the builder to reach its
**editor**; the outline on the left lists its elements in order, and the
**+ Add element** button opens a type menu split into a **Content** group and a
**Questions** group (see [Quiz editors](quiz-editors) for the latter).

## Working with elements

Each element is added, edited, and saved independently:

- Click **+ Add element** and pick a type card to insert a new element at the
  end of the unit.
- Click an existing element in the outline to open its editor form in place.
- Drag elements in the outline to reorder them; the reading order updates
  immediately.
- Delete an element from its editor form when it's no longer needed.

Every element also carries an optional author-only **title**, used only to
label it in the outline — students never see it.

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
- [Media manager](media-manager) — uploading and organizing images and videos.
- [Building a course](builder) — where units live in the course outline.
