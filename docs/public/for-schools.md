# libli for schools

## What you get

What the platform does:

- **Courses, lessons and quizzes.** A course is a tree of chapters and units. A unit is either a
  lesson to read and work through, or a quiz that is submitted and scored.
- **Around thirty kinds of content element.** Text, images, video, tables, galleries, tabbed
  panels, callouts, two-column layouts, spoilers and reveal gates; mathematical notation set with
  LaTeX; and interactive elements — drag-and-drop onto an image, fill-in-the-blank, matching
  pairs, answer grids, steppers, before-and-after sliders, embedded GeoGebra worksheets.
- **Quizzes with automatic marking.** Questions with a fixed answer are marked the moment they are
  submitted. Open-ended answers are queued for a teacher to read and mark. Every attempt is
  stored, not only the last one.
- **Teacher analytics.** A progress-and-results matrix for a group, drillable down to one student
  and one question, plus a gradebook export.
- **English and Polish**, interface and content, switchable per user.

## What we need from you

Three DNS records, requested together: an **A** record pointing your hostname at your server, and
**SPF** and **DKIM** records so mail sent on your school's behalf is not marked as spam. We ask
for all three in one email, to the same person who manages your domain, and they can usually be
set on the same day.

## What we do not need

No server. No hardware. No procurement process. No software installed on a pupil's device — a web
browser on whatever the pupil already has is enough.

## Two DNS traps worth knowing

**A `CAA` record that omits `letsencrypt.org`.** Most school domains carry no CAA record at all,
in which case there is nothing to do. If yours has one and it lists only another certificate
authority, your server cannot obtain a certificate and the site never comes up over HTTPS.

**A stale `AAAA` record.** An old IPv6 address left over from a previous website sends
IPv6-preferring visitors to the wrong place, and the fault only shows up on networks that offer
it. Clear it at the same time as the DNS change above.

## Where the data lives

Your school's data lives on its own server at Hetzner, in Germany — one box per school, never
shared with another school's data.

**Backups.** The server is backed up every night to encrypted storage in the European Union. A nightly copy is kept for **30 days**, and one copy per month for a further **12 months**. Files removed from a course stay in the backup for **90 days** so that an accidental deletion can be undone, and are then deleted too.

## What happens if you leave

You can leave at any time and take your data with you. Handover works as a **key rotation**: you generate the new encryption key, on your own machine, and give us only its **public half** — the private half never leaves your hands. We re-encrypt a current backup to that public key and hand over the resulting archive. We never disclose the shared key that protects every other school's backups, and we never hold your private key. From there, the same restore process that recovers a server after an outage stands your data up wherever you choose to run it next.

## Timeline

Send the DNS request above and your site can be running the same day. Outgoing mail — password
resets, notifications — goes out over port 587, the default for every school and a port Hetzner
has never blocked.

A school that insists on Microsoft Exchange **Direct Send** instead can have it, over port 25.
Hetzner blocks that port by default and unblocks it only for an established, paying account — in
practice, one that is **30 days** old with at least one cleared invoice. There is no fee for the
unblock; tell us early if you already know you will need it.

## Plans

At signup we agree five numbers: pupils on the platform, courses you plan, videos per course,
typical video length, and how many people author content.

{libli:pricing_plans}

Prices are quoted per school year.

{libli:vat_note}
