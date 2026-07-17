# Cohorts

A **cohort** is a platform-wide grouping of students, independent of any
one course — typically a year group or intake. Manage cohorts from
**Admin → Cohorts** (Platform Admin only; Course Admins can see cohort
names when picking students into a group, but not manage this list).

## The Default cohort

Every student who isn't otherwise assigned belongs to the **Default**
cohort. It cannot be deleted or archived, and its slug is permanently
reserved — you can rename any cohort, but nothing else can claim the name
"Default" as its identity.

## Creating and archiving cohorts

Use **New cohort** to create one with a name (its slug is generated and
then frozen — cohort URLs stay stable even if you rename it later).
**Archive** retires a cohort you no longer assign students to — and
reassigns its current members to the Default cohort, so an archived
cohort is always empty by the time you **Un-archive** it. **Make
default** makes a different cohort the new Default (promoting an
archived cohort also un-archives it). **Delete** works the same way as
**Archive**: it moves any remaining members to the Default cohort first,
then removes the cohort — there's no minimum-membership requirement, and
no need to empty a cohort yourself before deleting it.

## Assigning students

Open a cohort to see its members and add students to it from the list of
students not already in that cohort. A student belongs to exactly one
cohort at a time — adding them to a new one moves them out of their
previous cohort automatically.

## Where cohorts matter

Beyond grouping students for your own reference, cohorts can restrict a
course's self-enrolment: an **Open** course may be limited to specific
**Self enroll cohorts** — see [Creating a course](create-a-course) — so
only students in those cohorts see it in the catalog.
