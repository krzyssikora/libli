# Course export & import

libli can package a whole course — or a single subtree of it — into a `.zip`
archive, and load that archive back in, either as a brand-new course or as
content merged into an existing one.

## Exporting

From a course's **builder**, use **Export course** to download the entire
course, or **Export** on any node (a part, chapter, section or unit) to
download just that subtree. The archive carries the full structure, all
lesson and quiz content, and referenced media.

If some referenced media cannot be packaged (for example a file that has
since been deleted from storage), export does not fail outright: you land on
a **pre-flight page** listing the problems, and can choose to continue —
affected media is replaced with a clearly labelled placeholder in the
exported content — or cancel and fix the source first.

## Importing

Use **Manage → Courses → Import** to upload a `.zip` and create a new
course from it, or **Import** inside a course's builder to insert a subtree
into that course at a chosen point. Either way the flow is:

1. **Upload** the archive. It is validated and staged, not yet applied.
2. **Preview** — review what will be created, including where a subtree
   will be inserted (only structurally valid insertion points are offered).
3. **Confirm** to apply it, or **Cancel** to discard the staged upload.

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
