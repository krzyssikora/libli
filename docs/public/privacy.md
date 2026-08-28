# Privacy notice

Effective 29 August 2026.

This notice applies to the libli site published under the name: {libli:site_name}. It says what
the site stores about you, who can see it, how long it is kept, and how to ask for it to be
changed or removed.

## Who is responsible

The controller of your personal data is {libli:controller_name}.

{libli:controller_address}

The address for questions about this notice, and for any of the requests described under "Your
rights" below, is {libli:contact_email}.

{libli:demo_notice}

## What we hold, and why

**Account and identity.** A username, which every account has. An email address, which is
optional — libli needs one only for password resets, invitations and email notifications. A
display name, and a first and last name where your school supplies them. An external ID, when
your school signs you in through its own identity provider, so that libli can match you to the
record held there. The role your account holds: Student, Teacher, Course Admin or Platform Admin.

**Your learning record.** Which lessons you have opened and which you have marked complete; which
courses you are enrolled in; your quiz submissions, with the time you submitted them and the score
and maximum score recorded for each; and the answers themselves, including a teacher's written
feedback on them. Practice work you do inside a lesson — a drag-and-drop you rearranged, a blank
you filled in outside a quiz — is stored against your account too, and is not shown in the
teacher's analytics.

**Every answer you submit to a question is kept, with the time you submitted it — not only your
latest one.** If you answer the same question three times, all three answers remain, each stamped
with when it was sent. Reworking an answer does not erase the earlier ones.

**Groups and classes.** Which groups you belong to, which course each group sits on, and which
teachers teach it.

**Your own notes, tags and uploads.** The private notes you attach to a lesson and the coloured
tags you put on lessons are stored under your account. Files added to a course's media library
are stored with the account that added them.

**Preferences.** Your interface language, your light or dark appearance setting, and whether you
want notifications by email.

**Support reports.** If you send a problem report, libli stores what you wrote, the page you were
on and its title, any screenshot you chose to attach, your name, username, email address and the
roles you held at the time, and a short technical snapshot of your browser: its user-agent string,
window and screen size, device pixel ratio, appearance setting, interface language, language
header and time zone.

All of this exists so that the courses work, so that a teacher can mark your work and give you
feedback, and so that your school can administer its accounts. The lawful basis for the processing
is decided by the organisation named above as controller, not by libli; ask them at the address
above if you need it in writing.

## What libli does not collect

- **No IP addresses in the application.** No part of libli reads or stores the address your
  browser connects from. (The web server in front of it does keep access logs — see "Other
  services" below.)
- **No analytics and no tracking.** There is no analytics package, no tracking pixel and no
  third-party script on libli's own pages. The stylesheets, scripts and fonts a page needs are
  served from this site.
- **No advertising**, and no data passed to any advertising network.
- **No profiling and no automated decision-making.** Quiz questions with a fixed answer are marked
  automatically against their answer key, and a teacher can change any mark; open-ended answers are
  read by a person. Nothing here produces a decision about you by automated means alone.
- **Nothing is sold, and nothing is shared for marketing.**
- **No cookies beyond the functional ones listed below.**

## Cookies and local storage

libli sets four cookies, all first-party, all functional:

| Cookie | Purpose | Lifetime |
| --- | --- | --- |
| `sessionid` | Keeps you logged in and, before you log in, remembers your language choice | Two weeks. It is a persistent cookie, not a session cookie: it survives closing the browser |
| `csrftoken` | The anti-forgery check on every form you submit | About a year. It carries no identifier |
| `messages` | Carries a one-off confirmation or error message from one page to the next | Short-lived; it is cleared as soon as the message has been shown |
| `libli_theme` | Your light or dark appearance choice | One year |

libli also keeps a few interface preferences in your browser's local storage — which panels you
left open in a course outline, whether a navigation or roster panel is collapsed, which view mode
you last used in the course editor. These are written by libli's own scripts under keys beginning
`libli_`, `libli:` or `libli-`. They never leave your browser, they contain no identifier, and
clearing your browser's site data removes them. They are described by prefix rather than listed
one by one so that this paragraph stays true when a feature adds one.

## Other services

**Embedded material.** A teacher can place a video or an interactive worksheet from another
provider inside a lesson. Which providers are permitted is fixed by the operator of this site.
Currently: {libli:embed_domains}. Your browser contacts one of them only on a page where a teacher
actually placed such an embed — on every other page, including this one, it does not. Where it does, that provider receives your IP address and
the request for the embedded material, and **may set its own cookies and storage in your browser**
under its own terms, which libli does not control.

**Single sign-on.** If your school signs you in through its own identity provider, that provider
tells libli who you are — an identifier and, where the school configures it, your name and email
address. libli sends no learning record back to it.

**Email.** Password resets, invitations and notifications are sent through the mail server the
operator of this site configures. That server handles your email address and the contents of those
messages.

**Results webhook.** An administrator can switch on a webhook that forwards finalised quiz results
to another system — a school register, for example. It is off unless an administrator turns it on,
and it applies only to courses given an external code. When it is on, each finalised result sends
your external ID, your email address, your name, the course, the group and the score to the
address the administrator configured.

**Web server access logs.** The web server that serves this site keeps access logs, and **those
logs do record IP addresses**, even though the application itself never stores one. How long they
are kept is set by whoever runs the server, not by libli.

**Images added by URL.** When a teacher adds an image by pasting a link, **the server** fetches
that image from an allow-listed host and stores a copy here; readers' browsers never contact the
original host. The fetch carries no information about you or any other user. The same is true of
the size lookup libli makes at geogebra.org when a teacher pastes a GeoGebra link.

## Who can see your information

- **You** see your own record.
- **A teacher** sees the work of students in the groups they teach, on the courses those groups
  sit on, and nothing about students in other groups.
- **A Course Admin** sees the courses they own, including the record of every student enrolled on
  them.
- **A Platform Admin** can reach everything on the site: every account, every course and every
  learning record. That is what the role is for.
- **Students see nothing about one another.** No other student's answers, scores or progress are
  shown to you, and yours are not shown to them.
- **Your notes and your tags are yours alone.** No teacher screen and no administrator screen
  displays them.

Anyone with direct access to the server or its database can of course read anything stored there.
That access belongs to the organisation named above and to whoever it engages to run the service.

## How long we keep it

A notification you have read is removed {libli:retention_phrase}. Two qualifications matter. Where
a time limit applies, the application does not enforce it by itself: the rows go when the purge
job runs, which the operator's deployment has to schedule, or when a Platform Admin runs it from
the settings panel — on a deployment where nobody set that schedule up, nothing is removed on age
at all. And notifications you have **not** read are never removed because of their age.

Your learning record — enrolments, progress, submissions, answers and attempts — has **no
automatic expiry.** It is kept for as long as the account exists, and removing it is a manual act
by an administrator.

## Your rights

You can ask for access to the personal data held about you, for it to be corrected, for it to be
erased, for its processing to be restricted, for a copy of it in a portable form, and you can
object to its processing. Where processing rests on consent, you can withdraw that consent, which
does not affect anything done before you withdrew it.

You can also complain to a supervisory authority. The authority is: {libli:supervisory_authority}.

Three practical points, stated plainly because they change what you should expect:

- **There is no self-service export and no self-service delete.** libli has no button that
  downloads your data or removes your account.
- **Requests are handled by hand.** Send yours to the contact address given under "Who is
  responsible" above, and a person will act on it.
- **Deactivating an account is not erasure.** A deactivated account can no longer sign in, but the
  account and everything attached to it stay in the database until someone deletes them.

## Children

libli is built for schools, and many of the people using it are children. Accounts are created and
managed by the school, and the school decides what identifying information goes into them. Where
consent is needed for a child's data, that is a matter between the school and the child's parent
or guardian — libli asks children for no consent of its own and collects nothing beyond what this
notice describes.

## Security

The production configuration this site runs under redirects plain HTTP to HTTPS and marks the
session and anti-forgery cookies as secure, so they are sent only over an encrypted connection.
Keeping that configuration, the server and its backups safe is the responsibility of the
organisation named above.

Independently of any deployment choice: passwords are never stored, only a salted hash of them,
using Django's password hashing; what an account may see is decided by its role on every single
request rather than by hiding links; and screenshots attached to problem reports are stored
outside the web-served media directory and are delivered only to a Platform Admin.

## Changes to this notice

The effective date at the top of this page changes whenever this notice does. The organisation
that runs this site may publish its own version of this page in place of the one libli ships; the
text you are reading is the one in force for this site.
