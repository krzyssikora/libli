# Subjects

Subjects are the taxonomy courses are tagged with — they drive catalog
filtering and analytics grouping. Manage them from **Admin → Subjects**.

![The subjects list](static:core/img/help/subjects.en.png)

## Managing the list

- **New subject** creates a new subject with a **Title (English)** (required),
  an optional **Title (Polish)** (falls back to the English title when
  blank), and a **Slug** (generated from the **English title** if left
  blank, with a numeric suffix on collision).
- Existing subjects can be renamed or removed using the **Edit** and
  **Delete** buttons on their row.
- The list shows each subject's **used by N courses** link — it filters
  the course list down to courses carrying that subject — so you can see
  how widely it is used before deleting it; deleting a subject only
  unlinks it from its courses — the courses and their content are
  untouched.
- The list is shown in locale-aware alphabetical order, so it reads
  correctly for a Polish-language admin as well as an English one.

## Assigning subjects to a course

A course can carry more than one subject. Tick the ones that apply on the
course's form — see [Creating a course](create-a-course) — either at
creation or later by clicking **Edit** on that course's row in **Studio**.

## Keeping the list tidy

Favor a small, stable set of subjects over a fine-grained one; a course can
always carry several. Rename rather than delete-and-recreate when a subject
needs a new label, so existing course assignments are preserved.
