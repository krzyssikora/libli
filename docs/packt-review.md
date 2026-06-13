# Packt "educa" Review — Build-vs-Reuse for libli

*Reviewed: 2026-06-13. Source of truth: `Chapter17/educa/` (final cumulative code). PDF consulted only for rationale.*

This document reviews the **educa** platform from *Django 5 By Example* (chapters 12–17) to decide whether **libli** should be built **on** educa's codebase, **from scratch borrowing its patterns**, or **fully from scratch**.

**TL;DR:** educa is a small, clean teaching project (~600 lines of app code across three apps). Its content model is one shallow level deep with no quiz engine, no RBAC, no grouping, and no metrics — exactly the parts libli needs most. The patterns are excellent and worth stealing; the schema and views are not worth carrying. **Recommendation: build from scratch, borrowing educa's patterns.**

---

## 1. Overview

educa is a Django 5.2 project named `educa` with three apps plus the project package.

| App | Purpose | Notable files |
|-----|---------|---------------|
| `courses` | The core: content model, CMS course-builder, public course list/detail, DRF API, caching, fixtures. | `models.py`, `views.py`, `fields.py`, `forms.py`, `api/` |
| `students` | Student registration, enrollment (M2M add), "my courses" list + course-consumption detail view. | `models.py` (empty), `views.py`, `forms.py` |
| `chat` | Per-course real-time chat over Channels/WebSockets (ch.16). **Out of scope for libli.** | `consumers.py`, `routing.py`, `models.py` |

**Stack / key dependencies** (`requirements.txt`, `settings/base.py`, `Dockerfile`):

- **Django ~=5.2**, **DRF 3.15** — aligns with libli's target (Django 5.2 + DRF). 
- **PostgreSQL 16** (prod), **Redis 7** for cache + channel layer. Aligns with libli.
- `django-braces` (CSRF-exempt JSON mixins for the reorder endpoints), `django-embed-video` (the *entire* video element implementation), `Pillow` (images).
- `channels[daphne]` + `channels-redis` — **chat only**; cleanly droppable (see §4).
- Deployment: `Dockerfile` (Python **3.12.3** — libli targets 3.13), `docker-compose.yml` (db / cache / web=uWSGI / nginx / daphne), uWSGI + nginx, `python-decouple` for env config. **No `uv`, no pytest, no factory_boy, no ruff** — educa uses bare `unittest`-style `tests.py` (mostly empty) and is `pip`/`requirements.txt`-based.
- `students/management/commands/enroll_reminder.py` — a nice idiomatic management-command example (mass email to non-enrolled users).

Settings are split `base/local/prod` via `DJANGO_SETTINGS_MODULE` — a sane convention libli can mirror.

---

## 2. Data model

### `courses` app (`courses/models.py`)

```
Subject(title, slug)
Course(owner→User, subject→Subject, title, slug, overview, created, students M2M→User)
Module(course→Course, title, description, order=OrderField(for_fields=['course']))
Content(module→Module, content_type→ContentType, object_id, item=GenericForeignKey, order=OrderField(for_fields=['module']))
ItemBase (abstract: owner→User, title, created, updated; .render())
 ├─ Text(content: TextField)
 ├─ File(file: FileField upload_to='files')
 ├─ Image(file: FileField upload_to='images')
 └─ Video(url: URLField)
```

Key relationships and mechanics:

- **Hierarchy is exactly two levels:** `Course → Module → Content`. `Content` is a *join row* that points (via generic relation) at one of the four concrete item models. **There is no notion of part / chapter / section / unit / element** — `Module` is the only grouping, `Content` is the only "thing on a page".
- **Polymorphic content via `ContentType` + `GenericForeignKey`** (`models.py:62-71`). `Content.content_type` is `limit_choices_to={'model__in': ('text','video','image','file')}`. The actual payload lives in separate tables (`Text`, `File`, `Image`, `Video`), all subclassing the abstract `ItemBase`.
- **`ItemBase.render()`** (`models.py:91-95`) renders `courses/content/{model_name}.html` — the polymorphism is resolved at render time by template convention, not by `if/elif`.
- **`OrderField`** custom field (`fields.py`) auto-assigns the next integer within a sibling scope (`for_fields`) on save when blank. Used for both `Module.order` and `Content.order`.
- `Course.students` is a plain `ManyToManyField` to `auth.User` — **enrollment is just M2M membership**, no through-model, no per-student state.
- Uses Django's **default `auth.User`** directly (imported in `models.py:1`). No custom user model, no `settings.AUTH_USER_MODEL` (except chat, which does use it).

### `students` app (`students/models.py`)

**Empty** — `# Create your models here.` and nothing else. All student-side behaviour is views over `courses` models + the `Course.students` M2M. There is no `Enrollment`, no progress, no results, no grouping model anywhere.

### `chat` app (`chat/models.py`)

`Message(user→User PROTECT, course→Course PROTECT, content, sent_on)`. Standalone, FK to `Course` only. Trivially removable.

**Bottom line on the data model:** it is a clean *generic-content-blocks-in-ordered-modules* schema. It models roughly **2 of libli's 6 hierarchy levels** and **0 of the 9 question types, 0 metrics, 0 grouping, 0 roles**.

---

## 3. Key patterns & solutions worth knowing

| Pattern | Where | Verdict |
|---------|-------|---------|
| **`OrderField` custom field** | `courses/fields.py` | **Genuinely clever, directly reusable.** Auto-incrementing order scoped to siblings. libli needs ordering at every hierarchy level — lift this almost verbatim. |
| **Polymorphic `Content` via `ContentType`/GFK + `ItemBase`/`render()`** | `models.py:58-111` | **Borrow the idea, redesign the shape.** The "join-row points at one of N concrete element tables, each renders its own template by convention" pattern is exactly libli's element model. But libli has ~12 element/question types with rich per-type data and validation, so the concrete models differ entirely. The *technique* (GFK + `limit_choices_to` + convention-based `render()`) is the reusable kernel. (Note: GFK has no DB-level FK integrity and complicates queries; for 12+ types weigh GFK vs. a single JSON-payload table vs. multi-table inheritance.) |
| **CMS course-builder with formsets** | `views.py:64-90` (`CourseModuleUpdateView` + `inlineformset_factory` in `forms.py`) | **Borrow idea only.** Clean inline-formset-for-modules pattern, but libli's 6-level tree + per-element editors will need a richer (likely tree-aware, possibly JS-driven) builder. The formset approach won't scale to the depth. |
| **Dynamic per-type forms via `modelform_factory`** | `views.py:99-146` (`ContentCreateUpdateView.get_model`/`get_form`) | **Borrow idea.** One view handles create/update for all content types by resolving the model from a URL kwarg and building a `ModelForm` on the fly. Elegant; libli can use the same trick for its element editors. |
| **Drag-to-reorder via JSON endpoints** | `views.py:170-185` (`ModuleOrderView`/`ContentOrderView`, `CsrfExemptMixin`+`JsonRequestResponseMixin` from `django-braces`) + `content_list.html:75-124` (html5sortable + `fetch`) | **Borrow idea, modernize.** Works, but CSRF-exempt is a smell; libli should keep CSRF and use vanilla `fetch`. Good reference for the UX. |
| **Ownership mixins** | `views.py:22-31` (`OwnerMixin.get_queryset` filters `owner=request.user`; `OwnerEditMixin` sets owner on save) | **Borrow idea — but insufficient for libli.** These hardcode single-owner checks; libli needs granular RBAC + group/course scoping, not `owner==me`. Pattern of "queryset-narrowing mixin" is reusable; the specific checks are not. |
| **CBV + `PermissionRequiredMixin` using Django model perms** | `views.py:46-61` (`permission_required = 'courses.view_course'` etc.) | **Reuse the mechanism.** This is exactly the "use Django's permission framework, not role string checks" approach libli's roles.md asks for. Good news: educa already leans on `auth` permissions, so libli's granular-permission requirement is *compatible* with educa's grain — it just needs many more permissions + role→permission grouping (Groups). |
| **DRF nested serializers + `render()` bridge** | `api/serializers.py` (`CourseWithContentsSerializer` → `ModuleWithContentsSerializer` → `ContentSerializer` → `ItemRelatedField.to_representation` calls `item.render()`) | **Borrow idea.** Neat read-only nested API; the `ItemRelatedField` returning rendered HTML is a clever shortcut. libli's API will be richer (write paths, per-element JSON), but the nesting structure is a useful template. |
| **DRF `@action` + custom `IsEnrolled` permission** | `api/views.py:30-49`, `api/permissions.py` | **Reuse the technique.** `enroll`/`contents` actions and object-level permission class. libli's permissions are more complex but the shape holds. |
| **Low-level cache with manual keys + annotate** | `views.py:193-214` (`cache.get/set('all_subjects')`, `subject_{id}_courses`) | **Borrow idea.** Standard Redis caching; fine reference. Note: no invalidation shown — libli must add cache invalidation on writes. |
| **Subdomain→course middleware** | `courses/middleware.py` | **Not applicable / borrow loosely.** Maps `course-slug.host` to a course. libli is single-tenant-per-institution; if anything the *institution* gets the subdomain, not the course. |
| **Convention-based template dispatch** (`{{ item|model_name }}`, `content/{model_name}.html`) | `templatetags/course.py`, `content_list.html` | **Reusable convention.** Pairs with the `render()` pattern. |
| **Settings split + decouple, fixtures** | `settings/*`, `fixtures/subjects.json` | **Reuse conventions** (libli already plans this; educa's are minimal but sane). |

**Overall:** the patterns are the valuable export. educa is a textbook of *good small-Django idioms* — `OrderField`, GFK content blocks, factory-built forms, CBV mixins, nested DRF. None are large; all are re-implementable in a day.

---

## 4. Gap analysis vs libli

Legend: **None** = educa has nothing; **Partial** = a seed exists; **Has** = usable as-is.

| libli requirement | educa status | Gap size & notes |
|---|---|---|
| **Multi-language EN/PL (i18n)** | Partial | `USE_I18N=True` default only; no `gettext`, no `LocaleMiddleware`, no translated strings, no `django-parler`/translated model fields. libli needs translatable *content*, which educa never addresses. **Large.** |
| **RBAC, 4 re-sliceable roles, granular perms** | Partial | educa uses Django `auth` model permissions on a few CBVs (`courses.view_course`) and ad-hoc `owner==user` checks. No roles, no Groups, no role→permission mapping, no Teacher/CourseAdmin/PlatformAdmin distinction, nothing group-scoped. The *foundation* (Django permissions) is the right one and re-sliceable via Groups — but essentially all of it must be built. **Large.** |
| **Student grouping: cohorts / groups / collections** | None | No grouping models at all; enrollment is a flat `Course.students` M2M. Cohorts (1:1 student), groups (1 group↔1 course, students↔many groups, teachers assigned), collections (unions of groups) are entirely new. **Large.** |
| **Deep hierarchy course>part>chapter>section>unit>element (skippable middles)** | Partial | educa has `Course→Module→Content` = ~2 levels, both mandatory, no skipping. libli needs up to 6 levels with optional intermediate levels. The `OrderField`/tree idioms transfer; the schema is a full redesign. **Large.** |
| **Unit = lesson or quiz, one screen at a time, composed of elements** | None | educa's `Module` displays all `Content` together; no "unit" concept, no single-screen pagination, no lesson/quiz type, no slideshow. **Large.** |
| **Element types: styled text, image+figcaption, video (whitelist or upload), iframe, HTML (+course CSS/JS, per-unit JS, MathJax), math block** | Partial | educa has `Text`, `Image` (no figcaption), `Video` (URL only, via `embed_video` — no domain whitelist, no upload-as-element), `File`. **No iframe, no HTML element, no course-wide CSS/JS, no per-unit JS, no MathJax/LaTeX, no math block.** The GFK element pattern is reusable; the element *catalogue* is mostly new. **Large.** |
| **Quiz engine: 9 question types** | **None** | educa has **zero** quiz functionality. All 9 types (single/multi MCQ, fill-blanks, drag-fill, short text, short numeric w/ tolerance, extended response w/ required/forbidden keywords, match pairs, drag-to-image) are net-new. **Very large — the single biggest build.** |
| **Marking modes (auto/not-marked/requires-review) + quiz-vs-question-type rules + max marks + max attempts** | None | No marking, no attempts, no scoring rules. Entirely new. **Very large.** |
| **Metrics per student/course: progress (0–1), results, attempts** | None | No through-model on enrollment, no progress tracking, no results, no attempt counters. Entirely new. **Large.** |
| **Per-user notes anchored to content blocks** | None | No notes model, no anchoring. New. **Medium.** |
| **Per-user tags on units + filtering** | None | No tags. New. **Medium.** |
| **Branding (logo/palette), easy for non-technical admin** | None | Single hardcoded `base.css`/`base.html`; no theming, no per-institution config UI. New. **Medium.** |
| **SSO, easy to configure** | None | Only `UserCreationForm` + `authenticate/login` (`students/views.py`). No SSO, no SAML/OIDC, no admin-friendly config. New. **Medium–large** (likely `django-allauth` / `mozilla-django-oidc`). |
| **Self-hosted single-tenant per institution, non-technical startup** | Partial | Docker Compose exists but assumes a Django-savvy operator (uWSGI, nginx templates, decouple env). "Non-technical institution can start it" is a new requirement. **Medium.** |
| **Chat OUT of scope** | Has (to drop) | `chat` app is self-contained: its only coupling is `Message.course → courses.Course` and `ASGI_APPLICATION`/`CHANNEL_LAYERS` in settings + `asgi.py`/`routing.py`. **Cleanly droppable** — confirmed. Removing it also removes the only reason for Channels/daphne. |

**Coverage estimate:** of libli's ~14 major capability areas, educa fully satisfies **0**, partially seeds **~6**, and is absent on **~8** — including the two largest (quiz engine, metrics). The schema overlap is essentially `Subject/Course` + the *idea* of ordered content blocks.

---

## 5. Reusability verdict per area

| Subsystem | Verdict | Rationale |
|---|---|---|
| **Content hierarchy & rendering** | **Borrow idea only** | The GFK-element + convention-`render()` pattern is gold; the 2-level schema is a full redesign for 6 levels + units. |
| **Course-builder CMS** | **Borrow idea only** | Formset/`modelform_factory`/reorder idioms are great references; won't scale to libli's depth + element editors as-is. |
| **Content-element model** | **Adapt (pattern), rebuild (catalogue)** | Keep `ItemBase`/`render()`/`OrderField` shape; rewrite the concrete types and add 9 question types. |
| **Auth / roles** | **Borrow idea only** | Correct foundation (Django model permissions + CBV mixins), but ~0% of the actual RBAC, groups, or role mapping exists. |
| **Enrollment / grouping** | **Not applicable** | Flat M2M; cohorts/groups/collections + progress-preserving membership are entirely new. |
| **API (DRF)** | **Adapt** | Nested serializer structure + `@action` + object permissions are a solid starting template; needs write paths and richer payloads. |
| **Templates / frontend** | **Borrow idea only** | Minimal templates, no Bootstrap, no dark mode, no i18n, no branding. libli's design goals (light/dark, mobile/desktop, branding) start fresh; vanilla-JS reorder is a good reference. |
| **Deployment config** | **Adapt** | Compose/nginx/Postgres/Redis topology is reusable as a starting point; must migrate to uv/3.13, drop daphne/Channels (no chat), and add "non-technical operator" ergonomics. |
| **`OrderField`** | **Reuse directly** | Copy the file. |
| **`enroll_reminder` management command** | **Borrow idea** | Good idiom reference; libli's grouping changes the query. |
| **chat app** | **Not applicable** | Drop entirely. |

---

## 6. Recommendation

### Build **from scratch, borrowing educa's ideas and patterns**.

**Why not build ON educa's codebase:**

- The two subsystems that dominate libli's effort — the **quiz engine (9 types + marking + attempts)** and **per-student metrics** — do not exist in educa at all. educa contributes nothing to them.
- The data model that *does* exist (`Course→Module→Content`, flat `students` M2M, default `auth.User`) is a **shape mismatch**, not a subset, of what libli needs (6-level skippable hierarchy, units, cohorts/groups/collections, custom user, granular RBAC). Carrying it forward means migrating away from it almost immediately — net negative.
- The whole app is **small (~600 lines)**. There is no large body of battle-tested code whose reuse would save months; the value is in *idioms*, and idioms are cheap to re-apply on a clean schema.
- educa's stack diverges from the fijit-playbook in ways that touch project scaffolding anyway: **pip→uv, Python 3.12→3.13, no pytest/factory_boy/ruff, no i18n, no Bootstrap, no custom user model.** A fresh start lets libli adopt these from day one instead of retrofitting.
- educa's auth is partly `owner==request.user` hardcoding — the *exact* anti-pattern roles.md warns against. Starting fresh avoids inheriting it.

**What to carry forward (concrete):**

1. Copy `OrderField` (`courses/fields.py`) almost verbatim; apply at each tree level.
2. Reuse the **GFK element + `ItemBase.render()` + `{model_name}.html` convention** as the basis of libli's `Element`/question models (after deciding GFK vs JSON-payload vs MTI given ~12 types).
3. Reuse **`modelform_factory` dynamic per-type forms** and the **JSON reorder endpoint** UX (but keep CSRF, vanilla `fetch`).
4. Reuse the **nested DRF serializer structure** and **object-level permission class** shape.
5. Adopt educa's **settings split + Docker topology** as a starting skeleton, minus Channels/daphne (no chat).
6. Use **Django Groups + model permissions** as the RBAC substrate (educa already points this way) so the 4 roles are re-sliceable later.

**Custom user model from day one** — libli needs roles, branding association, SSO identities. educa's use of bare `auth.User` is the one decision you must *not* copy; a swap later is painful.

### Risks

- **From-scratch risk:** re-deriving idioms costs a little time and you forgo educa's (minimal) free tests. Mitigated by the small surface and this catalogue of patterns.
- **Build-ON risk (the path not taken):** silent coupling to a schema you'll outgrow, migration churn, and inheriting the `owner==user` auth pattern — higher long-term cost.
- **Hidden-complexity risk in libli itself:** the quiz engine + marking rules + metrics are the real project. educa offers no head start there, so plan/spec those first regardless of this decision.
