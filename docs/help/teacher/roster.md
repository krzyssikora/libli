# Roster management

A group's roster — its students and teachers — is something a teacher can
always **see**: opening a group from **My groups** takes you to a read-only
page listing everyone on it, the same roster that drives your analytics and
quiz review for that group. Editing it — adding or removing anyone — isn't
something a teacher does: it's a Course Admin's job, done inside the group's
own edit form. There's no separate **Edit** button; on the **Manage** tab a
group's own **name** is itself the edit link, its row otherwise carrying only
**Archive**/**Un-archive** and **Delete**, and a Course Admin starts a new
group there with **New group**. The page you land on from **My groups** has
no edit control anywhere on it.

The rest of this topic explains how a Course Admin builds that roster —
worth knowing, since it explains what you're looking at.

## Picking students

The student picker a Course Admin fills in is a checkbox list — but it isn't
scoped to the group's course: it lists **every non-staff user on the whole
platform**, and the course is never consulted. Two filters narrow the
*view*, not the underlying list:

- **Cohort** — a dropdown offering *All cohorts* plus each cohort by name.
  Picking one narrows the list to that intake.
- **Search by name** — a text box that matches any part of a name,
  case-insensitively, as it's typed.

A live counter shows **shown / total** while filtering, so it's always clear
how much of the list a filter is hiding. A separate **Added: N** count tracks
the current selection, with a **(saved: N)** hint when it differs from what
was last saved — a reminder of unsaved changes.

## Adding and removing

Ticking a student adds them; unticking removes them. Saving applies the
change: any student left unticked is removed from the group. Filtering never
drops a selection — every checkbox stays on the page the whole time, so a
student ticked under one filter is still saved even if a later filter hides
them.

The teacher picker works the same way, with just the name search.

## Cohorts are assigned elsewhere

Moving a student *between* cohorts is a separate action too, and it isn't
done here either: a platform admin does it from a cohort's own edit page,
picking students from a checkbox list captioned "Assign students to this
cohort (moves them from their current cohort)" and confirming with
**Assign**. The cohort filter on this page only *filters* the roster — it
never changes which cohort a student belongs to.

## Related topics

- [Groups & collections](groups-collections)
- [The analytics matrix](analytics)
- [Quiz review](quiz-review)
