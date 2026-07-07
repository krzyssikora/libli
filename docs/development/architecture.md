# Architecture

A map of the codebase — enough to know which app owns what and where to make a
change. This describes the current code; the [`docs/planning/`](../planning/)
notes and [`docs/roadmap.md`](../roadmap.md) are the original vision and may be
stale where they disagree with the code.

## The apps

libli is a single Django project (`config/`) with nine local apps:

| App | Owns |
| --- | --- |
| `core` | The UI shell (`base.html`), design tokens + theme + i18n middleware, the in-app `/help/` system, cached site config, shared views (home, landing, settings). |
| `accounts` | The custom `User` model, authentication (django-allauth), OIDC **SSO** provisioning, admin-issued **invitations**, and the `init_platform` bootstrap. |
| `institution` | The `Institution` **singleton** (branding, platform settings), the RBAC **role groups** (`setup_roles`), and colour/branding validation. |
| `courses` | The heart of the app: the **content model** (below), the authoring **builder** + per-type editors + media library, the **quiz engine** (9 question types), analytics, and course export/import. |
| `grouping` | **Cohorts**, **groups**, and **collections** of students, plus `Enrollment`. Drives who sees which course and the teacher analytics scope. |
| `notes` | Personal, author-scoped notes attached to lesson blocks. |
| `tags` | Personal tags on units. |
| `notifications` | Event notifications: in-app list, bell dropdown, email delivery, and a retention/purge command. |
| `integrations` | The outbound **SIS / e-register grade-sync webhook** and its public receiver guide. |

## The content model

This is the one pattern worth understanding before touching `courses`. It
follows the Packt "educa" approach.

- **`ContentNode`** is a single self-referential tree. Each node has a `kind`
  ordered `part < chapter < section < unit`, and there is one `OrderField`
  ordering space **per parent** — so levels can be skipped and siblings
  interleaved freely (no mptt/treebeard; plain adjacency list). A course's
  structure "depth" (flat / chapters / parts / full) is a per-course preset over
  this one uniform tree.
- **Units** are the leaves students consume. A unit is either a **lesson** or a
  **quiz**.
- **`Element`** is a generic-foreign-key join row that attaches a piece of
  content to a unit, in order. Each `Element` points at a **concrete per-type
  model** — `TextElement`, `ImageElement`, `VideoElement`, `IframeElement`,
  `MathElement`, an HTML element, and the question types. Question types subclass
  a shared `QuestionElement` base. To add a content type you add a concrete
  model and wire it into the `Element` GFK + the renderer/editor dispatch.
- **Progress** is per-element "seen" tracking: `UnitProgress` records
  `seen_element_ids` and a `completed` flag (auto-completed when all elements are
  seen, with a "Mark as done" fallback).

```
Course
  └── ContentNode (kind: part|chapter|section|unit, ordered per parent)
        └── Unit (lesson | quiz)
              └── Element (GFK, ordered) ──▶ TextElement / ImageElement /
                                             MathElement / QuestionElement(...) / …
```

Quiz submissions persist as `QuizSubmission → QuestionResponse → Attempt`;
scoring is a pure `courses/scoring.py` boundary (the only float→Decimal
conversion point). Question types that need a human ("review") leave a seam the
teacher review queue consumes.

## Request / consumption flow

Students reach content through a course **outline** view, which links into
**lesson** and **quiz** unit views. Enrollment and role scoping
(`courses/scoping.py`, `grouping`) gate access. Teachers reach the **analytics
matrix** for groups they teach. Everything is server-rendered; interactive
pieces (theme toggle, quiz answering, drag-and-drop, the builder) are
progressive-enhancement JS over a working no-JS base.

## Layout

- **Settings** — `config/settings/{base,local,test,production}.py`.
  `DJANGO_SETTINGS_MODULE` selects one; `base.py` reads `.env` if present. `test`
  pins non-manifest static storage + a local-memory cache for stable tests.
- **Templates** — project-level in `templates/`, plus per-app template
  directories. `templates/base.html` is the app shell.
- **Static** — `core/static/core/` for the design system (tokens, reset, app CSS,
  self-hosted Inter); vendored **KaTeX** and **MathLive** live under
  `courses/static/courses/vendor/`.
- **i18n** — English + real Polish under `locale/`.
- **Management commands** — `init_platform`, `setup_roles`, `seed_demo_course`,
  `flush_webhooks`, `purge_notifications`.
- **Tests** — one top-level `tests/` package (see
  [`conventions.md`](conventions.md)).

## Historical context

The original brainstorming that shaped the above lives in
[`docs/planning/`](../planning/): `main_idea.md` (the pitch),
`roles.md` (the four roles + cohorts/groups/collections), `views.md`, and
`differences.md`. [`docs/roadmap.md`](../roadmap.md) tracks the phases. Where any
of these disagree with the code, the code wins.
