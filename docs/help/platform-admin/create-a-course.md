# Creating a course

Open **Studio** and click **New course** to create a course. The form on this
page sets up the course shell; you fill it with content afterwards in the
builder.

## Core fields

- **Title** — shown throughout the platform and the catalog.
- **Slug** *(optional)* — the URL segment; leave it blank and it is generated
  from the title, with a numeric suffix if that slug is already taken.
- **Structure** — one of four presets (**Flat**, **Chapters**, **Parts**,
  **Full**) that decides which content levels the course uses. Pick the
  shallowest one that fits; you can deepen it later without losing existing
  units, but you cannot later remove a level that already holds content.

## Subjects and visibility

Tick one or more **Subjects** to place the course in the subject taxonomy
used by the catalog and analytics filters — see [Subjects](subjects) if the
one you need does not exist yet. **Visibility** controls how students reach
the course: **Open** courses appear in the student catalog for
self-enrolment (optionally limited to specific **Self enroll cohorts**),
while **Assigned** courses are only reachable via a teacher/admin enrolment
or a group.

## Owner (course admin)

The **Owner** field assigns the course's Course Admin — the person who can
build and edit it day to day. As a Platform Admin you can set this to
yourself or to any Course Admin; leave it blank when creating and it
defaults to you. You can reassign ownership later from the course's edit
form.

## Grade-sync code

If this course's results should flow to your school information system, set
**Register subject code** to the subject code your SIS/e-register expects.
Leave it blank to keep this course out of grade sync entirely — see
[Integrations](integrations).

## After creation

Saving takes you straight to the **builder**, where you add chapters,
lessons and quizzes. You can transfer content into or out of a course at
any time — see [Course export & import](export-import).
