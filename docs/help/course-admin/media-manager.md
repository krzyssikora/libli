# Media manager

Every course keeps its own library of uploaded images and videos, reused
across all its lessons and quizzes. Open it from **Manage courses** on your
dashboard: open your course's **Build**er, then press **Media library**.

## Uploading a file

At the top of the library, choose a **kind** (Image or Video), pick a **file**
(or drag it onto the drop zone), optionally give it a friendlier **name** than
its original filename, and click **Upload**. The platform admin sets the
allowed file types and maximum size per kind (images and videos each have
their own extension allow-list and size ceiling) under the platform's Uploads
settings; an upload that doesn't fit those limits is rejected with an
explanation.

## Browsing and organizing

The library grid shows every asset as a thumbnail with its name and a
**usage count** — how many elements across the course currently reference it.
Use the **kind filter** and the **search box** above the grid to narrow a
large library down by filename or name.

From an asset's cell you can:

- **Rename** it in place — this only changes the display name shown in the
  library and pickers, not the underlying file.
- **Delete** it — allowed only when its usage count is zero. If it's still
  referenced by any element, deletion is refused; remove it from every
  element first (or replace it there), then delete it here.

Because assets are shared, uploading the same picture or clip twice just
clutters the library. Search for it first — someone (maybe you, in an
earlier unit) may have already uploaded it.

## Picking media inside an element editor

You don't have to visit the Media manager page to attach a file: any editor
field that needs one (Image and Video content blocks, the Drag to image
question) has a **Choose media** button that opens the same library in a
picker dialog, with two tabs:

- **Library** — search and pick from assets already uploaded to the course.
- **Upload** — upload a new file on the spot; it's added to the course
  library and selected immediately, so you never have to leave the editor.

Whichever way you attach a file, it becomes a permanent library asset,
available to reuse in any other element afterwards.

## See also

- [Content editors](content-editors) — the Image, Video, and other block types
  that consume media assets.
- [Quiz editors](quiz-editors) — the Drag to image question, which needs an
  image with marked zones.
