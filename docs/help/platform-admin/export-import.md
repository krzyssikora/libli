# Course export & import

libli can package a whole course — or a single subtree of it — into a `.zip`
archive, and load that archive back in, either as a brand-new course or as
content merged into an existing one.

## Exporting

From a course's **builder**, use **Export** to download the entire
course, or the **Export subtree** icon on any node (a part, chapter, section
or unit) to download just that subtree. The archive carries the full
structure, all lesson and quiz content, and referenced media.

If some referenced media cannot be packaged, export does not fail outright:
you land on an **Export — missing media** page listing the problems, where
you can **Export anyway** or **Cancel** and fix the source first. What
happens to each affected item depends on the problem:

- a missing **image** is exported as a placeholder;
- a missing **video** has its block left out of the export;
- a **broken** content block is likewise left out of the export.

## Importing

![The course import screen](static:core/img/help/import.en.png)

Use **Studio** and click **Import course** to upload a `.zip` and create a
new course from it, or **Import content** inside a course's builder to
insert a subtree into that course at a chosen point. Either way the flow
is:

1. **Upload and preview** the archive. It is validated and staged, not yet
   applied.
2. Review the **Import preview** page — what will be created, including
   where a subtree will be inserted (only structurally valid insertion
   points are offered).
3. **Confirm import** to apply it, or **Cancel** to discard the staged
   upload.

A staged upload expires after a while; if you return to a stale preview,
re-upload the archive. Very large archives are rejected up front against
this instance's configured size ceiling rather than partway through the
upload.

## When to use which

- Moving a course between environments (e.g. staging → production): export
  the whole course, import it as new on the target.
  See [Creating a course](create-a-course) for the fields a fresh import
  still lets you edit afterwards.
- Reusing a chapter or unit across courses: export just that subtree and
  import it into the target course's builder.
