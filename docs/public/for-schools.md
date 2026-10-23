# libli for schools

## What we offer

- a platform for building courses out of rich, interactive learning content
- each course can be split into parts, chapters and sections; lessons or quizzes sit at the
  bottom of that structure
- around thirty kinds of content element: text, images, video, tables, galleries, tabbed
  panels, callouts, multi-column layouts, spoilers, mathematical notation set with LaTeX, and a
  range of interactive elements such as drag-and-drop onto an image, fill-in-the-blank,
  matching pairs, answer grids, and embedded GeoGebra worksheets or other iframe embeds
- quizzes with automatic marking: questions with a fixed answer are marked the moment they are
  submitted. Open-ended answers are queued for a teacher to read and mark. When more than one
  attempt is allowed, every attempt is stored, not only the last one
- teacher analytics: a progress-and-results matrix for a group, detailed results for each
  student, the details of every quiz, plus a results export
- an interface in Polish or English, per user's choice

## Try a demo

We can set up a private demo for your school: a teacher login and a student login on our
high-school maths course, together with an example class whose results show the analytics at
work. The student login belongs to that class and is a "starter" account — it has no progress
yet. Its data appears as you work through lessons and quizzes, so you can watch the teacher's
view change. The course content is in Polish. Access lasts two weeks.

Want to try it? Write to {libli:contact_email}.

## What we need from you

If you want to use libli at your_subdomain.libli.pl — we need nothing from you. Once the
contract is signed, we get to work.

If you want to use libli at your own domain (e.g. libli.your-domain.example), we need three DNS
records from you: an **A** record pointing your domain at the server, and **SPF** and **DKIM**
records so mail sent on your school's behalf does not land in spam. We ask for all three in one
email, to the same person who manages your domain. They can usually be set the same day.

### Two DNS traps worth knowing

Both apply only to a custom domain — on a your_subdomain.libli.pl subdomain we manage the
**CAA** and **AAAA** records ourselves, so neither trap can arise.

1. A **CAA** record that omits `letsencrypt.org`.

    Most school domains carry no CAA record at all, in which case there is nothing to do. If
    yours has one but it omits `letsencrypt.org`, the server cannot obtain a certificate and the
    site never comes up over HTTPS.

2. A stale **AAAA** record.

    An old IPv6 address left over from a previous website sends some visitors to the wrong
    place, and the fault only shows up on networks that support IPv6. Clear it at the same time
    as the DNS change above.

## What we do not need

No server. No hardware. No procurement process. No software installed on a student's device — a
browser is enough. Optionally, you can also install the app.

## Where the data lives

Your school's data is stored on its own server (not shared with other institutions), located
within the European Union, under European law. One server per school, never shared with
another school's data.

### Backups

The server is backed up every night to encrypted storage, also within the European Union. A nightly copy is kept for **30 days**, and one copy per month for a further **12 months**. Files removed from a course stay in the backup for **90 days** so that an accidental deletion can be undone. After that, they are deleted too.

## What happens if you leave

You can leave at any time and take your data with you. Handover works as a **key rotation**: you generate the new encryption key, on your own machine, and give us only its **public half** — the private half never leaves your hands. We re-encrypt a current backup to that public key and hand over the resulting archive. We never disclose the shared key that protects every other school's backups, and we never hold your private key.

If you later decide to come back to libli, the same restore process brings the server back to the state in which it was archived.

## Timeline

Once the DNS change above is in place, your site can be running the same day.

There is one limitation we know of. A school that wants to use Microsoft Exchange Direct Send
can do so, over a port the server provider blocks by default. The port is unblocked only for an
established, paying account — in practice, one that has existed for at least 30 days and has at
least one cleared invoice. There is no fee for the unblock; tell us early if you already know
you will need it.

## Plans

At signup we discuss five numbers:

- the maximum number of students on the platform,
- the number of courses planned,
- an estimated number of videos per course,
- typical video length,
- and the number of people authoring content.

{libli:pricing_plans}

{libli:vat_note}
