# Demo access — PR 3: the admin tab — design

**Status:** approved in brainstorming 2026-09-12. Not yet planned, not yet built.
**Parent:** `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md` (below: "the
parent"). PR 3 is scoped at the parent's §6; §4.4 and §4.6 are the service and command surfaces
this tab wraps. PR 1 and PR 2 are merged (#318) and deployed.

**Scope:** a "Demo access" tab in institution settings that issues, lists, extends and revokes
school demo kits by calling `demo/services.py`; the narrowing of the kit Teacher's course access
that a web form makes mandatory; and one service fix the form exposes.

---

## 1. Decisions

| # | Decision | Why, and what was rejected |
|---|----------|----------------------------|
| A1 | **The kit Teacher is created non-staff.** `provision_kit` sets `is_staff = False` after `set_user_role(TEACHER)`. | `accessible_courses` returns every course for any staff user (`courses/access.py:22-23`), and the form offers every course (§4.2), so one kit's Teacher could read any course on the box. Rejected: exempting demo users inside `accessible_courses` (the core read gate would learn about the `demo` app and change on every box); narrowing the Teacher role for everyone (a product change for real school teachers). |
| A2 | **PR 3 ships dark.** It merges with `LIBLI_VENDOR_INSTANCE` still unset on prod; the flag is switched on after PR 5, as the parent's §5 step 1 and §6 already order. | The same flag publishes `/for-schools/`, whose "one pupil and one question" claim is true only once PR 5 ships. Nothing is lost by waiting: the page is dark, so no enquiry can arrive through it. Rejected: a second flag (the parent rejected it — a second thing to get wrong on a school box); flipping at merge. |
| A3 | **`provision_kit` runs inline in the request.** No worker, no progress surface. | Measured 37.2 s for a 20-pupil kit on `mat-pp` (PR 2). The request timeout is not the constraint (§2.1); a dropped connection is, and §4.4 handles it. |
| A4 | **Credentials render at the top of the Demo panel from a session list, and survive a dropped connection.** | §4.4. Rejected: a dedicated result page (after a disconnect the operator never lands on it); no recovery (revoke and recreate, another ~40 s). |
| A5 | **Non-POST to an action view is a 302 to `?tab=demo`, not a 405.** | The parent §4.6 and T10 say 405, but every settings action view redirects (`institution/views_manage.py:169-170`) and `tests/test_settings_action_method_guard.py:73-78` asserts 302 across the family. The family wins; the parent is amended (§7). |
| A6 | **The tab never advertises teacher marking.** | The "awaiting review" queue is structurally empty — any quiz holding a REVIEW question is skipped whole (parent R3), confirmed live on `mat-pp` (review queue "Oczekuje na ocenę 0"). Non-goal N9 of the parent. The same rule binds PR 4's copy. |

## 2. Findings that constrain the design

Each was read on 2026-09-12 at the cited line.

### 2.1 The request timeout is nowhere near the provision

- gunicorn runs `--timeout "${GUNICORN_TIMEOUT:-1800}"` and `--graceful-timeout
  "${GUNICORN_GRACEFUL_TIMEOUT:-120}"` (`docker-entrypoint.sh:81-82`), sized for 25-minute course
  imports; `--threads` > 1, so workers are `gthread`.
- Caddy's `reverse_proxy app:8000` (`Caddyfile:35`) sets no response timeout.
- So 37.2 s — or roughly twice that at `MAX_PUPILS = 40`, given the measured ~137 queries per
  extra pupil — fits comfortably. ⚠️ **The prod wall-clock is unmeasured**: 37.2 s is local. The
  first throwaway kit after the flag flip measures it (§6).
- **The real failure is a dropped connection**, which the parent §4.6 named: the browser gives
  up, the transaction still commits, and the operator never sees the passwords. gthread does not
  abort a view when the client disconnects.
- ⚠️ **A deploy mid-provision** SIGTERMs gunicorn, which lets in-flight requests finish for up
  to 120 s. A provision that outlives that is killed, its transaction rolls back, and no kit
  exists. Stated, not handled.

### 2.2 The session survives a disconnect; the cache does not

- `SessionMiddleware` saves a modified session in `process_response`, before gunicorn writes a
  byte, so credentials put in the session are persisted even when the client has gone.
- No `SESSION_ENGINE`, `SESSION_SAVE_EVERY_REQUEST`, `CSRF_USE_SESSIONS` or `MESSAGE_STORAGE`
  is set anywhere in `config/` — all Django defaults: DB-backed sessions, JSON serializer,
  session saved only when modified, CSRF token in a cookie, messages in a cookie (session only on
  overflow).
- ⚠️ **No `CACHES` is configured outside `config/settings/test.py`**, so prod runs
  `LocMemCache`, which is **per process**. With 2–4 gunicorn workers the redirect's GET can land
  on a different process and find nothing. The parent §4.6 let the plan "carry it in the cache if
  that is cheap"; it is not cheap, it is wrong.

### 2.3 `is_staff` has few readers

In non-test code (full grep, 2026-09-12):

- `courses/access.py:22` — `accessible_courses`' read-all branch. The one that matters.
- `grouping/services.py:30,41,50` — `student_users`, `teacher_users`, `is_staff_user`. **All three
  also test the Teacher/Course Admin/Platform Admin role groups**, so a non-staff Teacher is still
  staff to them: it stays out of cohorts and stays pickable as a group teacher.
- `templates/core/home.html:79` — also tests `is_teacher`, which is role-derived
  (`core/context_processors.py:99`), so a non-staff Teacher renders identically.
- Django admin login (`is_staff` required).
- `accounts/services.py:36`, `accounts/management/commands/init_platform.py:104-107`,
  `seed_demo_course.py:199` — writers, not readers.

Analytics, the drill-down, the review queue and force-submit gate on `scoping.can_review_course`
(parent §3.3), never `is_staff`. Nothing re-derives `is_staff` on save, and `Group.teachers`
(`grouping/models.py:89-91`) carries no staff restriction.

### 2.4 What the narrowing actually buys

The parent's pinned test (`tests/demo/test_provision.py:306-330`) says a demo login "can read
every other course hosted on the vendor instance, including another school's kit". **Kit pupil
data is not what leaks**: analytics is already group-scoped, and parent T9 proves kit A's
Teacher sees none of kit B's pupils. What `is_staff` leaks is **course content across courses**
(the form offers any course, so kits need not share one) and an **`/admin/` login**. The spec and
the renamed test say exactly that.

### 2.5 The service does not catch the concurrent-create race

The parent §4.4 step 0 says an `IntegrityError` during user creation "is caught and re-raised as
the same named collision error". **`demo/services.py` contains no such catch** — there is no
`IntegrityError` handling anywhere in `demo/`. A double-clicked Create is precisely that race:
the second request's `_taken` scan (`demo/services.py:105-126`) cannot see the first request's
uncommitted users, resolves the same base, blocks on the unique index while the first commits,
then raises a bare `IntegrityError` — a 500 after ~40 s.

### 2.6 Other facts the design reads

- A course a user cannot access returns **403**: `course_outline` raises `PermissionDenied`
  (`courses/views.py:648-649`).
- `_active_tab` falls back to `"branding"` for a tab not in `_tabs()`
  (`institution/views_manage.py:59-61`), and `_settings_context` builds every panel's context on
  every render (`:64-145`).
- `tests/test_settings_action_method_guard.py:33-46` is a **hand-kept** `ACTION_URL_NAMES` list,
  and `:73` calls `reverse(url_name)` with no arguments.
- `DemoWarning.reason` is an untranslated English diagnostic — class names, fractions, the
  webhook URL (`demo/content.py:76-181`, `demo/generator.py:348-355`, `demo/services.py:366`).
- `DemoKit.status_key` returns `active` / `pending_purge` / `closed_<reason>`
  (`demo/models.py:88-97`); its docstring promises PR 3 the translated display map.
- A generic `form[data-confirm]` script exists at `support/static/support/js/confirm.js` (and a
  near-copy in `courses/static/courses/js/review_roster.js:16-22`). No submit-once helper exists.
- The kit Teacher's cohort path today: `create_user` inserts a non-staff user with no groups, so
  `ensure_cohort_membership` (`grouping/signals.py:12-26`) adds it to Default; `set_user_role`'s
  `groups.set` then fires `sync_cohort_on_role_change` (`:29-47`), which removes it.
- Parent T14 ("a kit Teacher's `/admin/` index lists zero models") **was never implemented** —
  no test in `tests/` asserts it.

## 3. The narrowing and the service fix (changes in `demo/services.py`)

### 3.1 The kit Teacher is non-staff

Immediately after the Teacher's `_make_user(..., role=TEACHER)` returns
(`demo/services.py:258-263`):

```python
teacher.is_staff = False  # A1: read only the kit's course; no /admin/ login
teacher.save(update_fields=["is_staff"])
```

- **After, never before**: `set_user_role` is the last writer of the flag
  (`accounts/services.py:36-37`), so setting it earlier is overwritten. `_make_user` still takes no
  `staff` parameter, for the reason its docstring gives (`:145-153`).
- **Cohorts are unaffected**: the save fires `post_save` with `created=False`, which
  `ensure_cohort_membership` ignores (`grouping/signals.py:22-23`); the membership was already
  removed by the role change (§2.6); and `is_staff_user` would treat the Teacher as staff anyway
  (§2.3).
- **The Teacher keeps**: its role's permissions (`institution/roles.py:80-86`);
  `can_review_course` via `group.teachers`, hence analytics, the drill-down, the review queue and
  force-submit; and read and preview access to the kit's course through `accessible_courses`'
  taught-groups branch (`courses/access.py:24-29`), which requires the group non-archived —
  true for the kit's whole life, since purge deletes the group.
- **The Teacher loses**: read access to every other course, and the `/admin/` login.
- **Invariant**: `set(accessible_courses(kit.teacher)) == {kit.course}` while the kit is open.
- **Known way to undo it, accepted and documented, not guarded**: a Platform Admin changing that
  user's role on the People page calls `set_user_role` and re-grants staff.
- The `_make_user` docstring's closing line ("`role_is_staff(TEACHER)` is True, which IS the
  course-access widening documented above") and the `role=TEACHER` comment at `:262` are updated
  to say the widening is undone at the call site.

### 3.2 A concurrent create becomes `UsernameCollision`

The three user-creation sites in `provision_kit` (Teacher, Student, the pupil loop) run inside a
small context manager that turns `django.db.IntegrityError` into `errors.UsernameCollision`:

- **It raises straight out, with no query and no retry.** Once an `IntegrityError` surfaces in an
  `atomic` block the transaction is marked for rollback; any ORM call before unwinding raises
  `TransactionManagementError` and buries the named error (the parent §4.4 step 0 said this).
- **It wraps user creation only**, not the whole service, so an `IntegrityError` from a
  generator bug is not mislabelled as a collision.
- It lives in the service, so `demo_access create` gets the same answer as the tab.
- The message names the slug and says **another create for it may still be running or may just
  have finished — check the kit list before creating again**. Neutral on purpose: it reads correctly under the
  command (where the list is `demo_access list`) and under the tab (where the list is on the page),
  and never names a command a web operator cannot run. It never says "retry": the
  realistic cause is a double run whose other half committed a live kit, which is as true for the
  command's reader as for the tab's, and the tab appends this text verbatim (§4.2).
  `raise ... from exc` keeps the cause.

## 4. The tab

### 4.1 URLs, gating, placement

Three action views in `institution/views_manage.py`, beside `settings_pricing`, routed in
`institution/urls.py` under the institution namespace:

| name | path | calls |
|---|---|---|
| `settings_demo_create` | `manage/settings/demo/create/` | `provision_kit` |
| `settings_demo_extend` | `manage/settings/demo/<int:kit_id>/extend/` | `extend_kit` |
| `settings_demo_revoke` | `manage/settings/demo/<int:kit_id>/revoke/` | `revoke_kit` |

Each view, in this order — `settings_pricing`'s (`institution/views_manage.py:479-484`):

1. `@login_required`, `@permission_required("institution.change_institution",
   raise_exception=True)`;
2. `if not django_settings.VENDOR_INSTANCE: raise Http404` — the module's `settings` name is a
   view (`:33-37`), so the alias is mandatory;
3. `if request.method != "POST": return redirect(_index_url("demo"))` — never `== "GET"`
   (#307; A5);
4. extend and revoke resolve the kit with `DemoKit.objects.filter(pk=kit_id).first()` and raise
   `Http404` when absent — the view's own 404, so `KitNotFound` is never raised on this path.

Placement:

- `_tabs()` appends `"demo"` under the same flag as `"pricing"`, after it.
- `_tabs.html` adds the link inside the existing `{% if vendor_instance %}` block
  (`templates/institution/manage/_tabs.html:19-22`; the flag reaches templates from
  `core/context_processors.py:29`). Label: "Demo access".
- `settings.html` adds a `data-tab="demo"` panel including
  `templates/institution/manage/_demo_tab.html`, inside `{% if vendor_instance %}`.
- `_settings_context` gains a `demo_form=None` parameter and builds the demo context — the form
  and the kit list — **only when `active_tab == "demo"`**. Every other render gets `None`; the
  settings view builds every panel on each GET (§2.6), so without this every tab pays for the list
  and course queries. `_settings_context` **never touches pending credentials** — that belongs to
  the settings view alone (§4.4).
- `_demo_tab.html` wraps its **whole body, both `<script>` tags included**, in
  `{% if active_tab == "demo" %}`, so the hidden panel on every other tab renders nothing against
  the `None` context. The tabs are plain links (`_tabs.html`), so switching to Demo is a full GET
  and the panel is always rendered fresh when shown.

⚠️ **The tab's Revoke 404s on a non-vendor box, on purpose.** Parent R8 exempts revoke from the
vendor guard so that cleanup can never be blocked; that exemption belongs to the service and to
`demo_access revoke`, which stay unguarded. The web surface is vendor-only like the rest of the
tab.

### 4.2 The create form

`DemoKitForm`, a plain `forms.Form` in `institution/forms.py` beside `PricingForm`:

| field | type | notes |
|---|---|---|
| `course` | `ModelChoiceField(Course.objects.order_by("title"))` | required, no initial selection — the parent §4.6 forbids a default |
| `label` | `CharField` | required |
| `days` | `IntegerField`, `initial=DEFAULT_DAYS` | required |
| `pupils` | `IntegerField`, `initial=DEFAULT_PUPILS` | required |

⚠️ **No `max_length`, `min_value` or `max_value` on any field.** The bounds live in
`provision_kit` (`demo/services.py:187-200`) and the form inherits them by calling it. Required-
ness and integer coercion are type-level and stay.

The view calls `provision_kit(label, course=, days=, pupils=, created_by=request.user)` — no
`frontier_part`, no `seed`. It carries `@sensitive_post_parameters()` and
`@sensitive_variables()` (the parent §4.4's mechanism behind "never logged"). ⚠️ **So does every
other frame that holds a plaintext password**: the `settings` view (its context carries the cards),
`_pending_demo_results`, `_discard_shown_results`, and whatever helper builds §4.3's entry. Django's error reporter dumps frame
locals; `config/` sets no `ADMINS` or `LOGGING` today, so nothing is mailed yet, but the mechanism
must not depend on that staying true (parent Risk 6).

**Service errors map onto the form:**

| raised | rendered as |
|---|---|
| `InvalidLabel` | error on `label`: "Enter a label of at most %(max)s characters." from `LABEL_MAX` |
| `InvalidBounds(field)` with `field` in the form | error on that field: "Must be between %(min)s and %(max)s." from the matching `MIN_*`/`MAX_*` constants |
| `InvalidBounds(field)` with `field` not in the form (`InvalidFrontierPart`; unreachable while the form omits the field) | non-field error |
| `UsernameCollision` | non-field error: **"A kit for this label may have just been created. Open the Demo tab — its credentials appear there — before creating again."**, with "Open the Demo tab" a link to `_index_url("demo")`. ⚠️ **One msgid for the whole sentence**, with brace placeholders around the link text — `"A kit for this label may have just been created. {link_start}Open the Demo tab{link_end} — its credentials appear there — before creating again."` — rendered as `format_html(gettext(msgid), link_start=format_html('<a href="{}">', url), link_end=mark_safe("</a>"))`. The translation is the format string, so Polish word order is free; the **URL enters only as an escaped argument**, never inside the translated text. (A translated string is trusted markup here exactly as every `{% blocktrans %}` output already is: `.po` files are committed to the repo.) This page deliberately shows no card (§4.4), so without the link an operator who sees the new kit in the list and no passwords anywhere concludes they are lost, when one GET would show them; and the link steers away from reloading this POST response, which would re-submit and mint another kit (§4.2 "Inline provisioning"). ⚠️ Not "try again": from the tab the realistic cause is a double submit (§3.2) whose other request has just committed a live kit, so a retry mints a third kit. Genuine exhaustion of `MAX_DISAMBIGUATOR = 999` is not a realistic tab path |
| `EmptyCourse` | non-field error: this course cannot hold a demo |
| `EmptyKit` | non-field error: the generated class came out empty and was rolled back |
| `NamePoolExhausted` | non-field error: ran out of distinct pupil names; use fewer pupils |
| any other `DemoKitError` | non-field error: the kit could not be created |

Each non-field message is a translated sentence followed by the service's own English text in a
`<code>` element — those messages are not translated (`demo/services.py:192-232`), and the
sentence keeps the panel translated while the detail stays diagnosable. ⚠️ **Built with
`format_html("{} <code>{}</code>", sentence, str(exc))`, never `mark_safe` over an f-string**: a
plain string passed to `add_error` is autoescaped (the tags would show literally), and the obvious
`mark_safe` workaround would un-escape interpolated service text — slugs, usernames, and whatever a
future `DemoKitError` message carries. P8 asserts an exception message containing `<` renders
escaped. The `MIN_*`/`MAX_*`
lookup in the field-error message is **display only**: enforcement stays in the service, and P8
proves the form holds no bound of its own. `ImproperlyConfigured` cannot occur (the 404 gate runs
first) and is deliberately not caught.

**Inline provisioning:**

- Help text beside the button: creating a kit can take a minute or more; keep this page open. **If
  the page stops responding, wait a couple of minutes, then reopen the Demo tab — the credentials
  appear there once the kit exists; do not create again until it shows in the list.**
- A tab-local `institution/static/institution/js/demo_tab.js` disables the Create button and sets
  `aria-busy="true"` on submit, and re-enables it on `pageshow` so a Back navigation restored from
  bfcache is not left with a dead button. No submit-once helper exists to reuse (§2.6). ⚠️ **The
  Create button carries no `name`**: the browser builds the form data after `submit` fires, so a
  named button disabled in the handler would silently drop its pair from the POST. The same script
  disables each row's **Extend** button on submit (also unnamed): two POSTs would each run
  `max(expires_at, now) + DEFAULT_DAYS`, extending by 28 days and possibly crossing
  `LONG_LIVED_DAYS`. **Revoke is not disabled** — its confirm dialog already stops a double click,
  and a button disabled by the submit handler would stay dead after a cancelled confirm. The `pageshow` handler re-enables **every** button the
  script disabled, the Extend buttons included — a Back navigation to the list after an extend is
  the same bfcache case as after a create.
- A double submit that gets past the script is still safe: §3.2 turns the loser into a
  `UsernameCollision` form error, and **the create view's error path neither pops nor writes the
  session** (§4.4), so it cannot overwrite the winner's credentials — even when older entries are
  already pending.
- ⚠️ **Reloading any create error page re-POSTs.** The error re-render is a 200 answer to a POST,
  so a reload (past the browser's resubmit prompt) runs `provision_kit` again; after a double
  submit the winner has committed, `_free_base` finds the `-2` base free, and a further kit is
  provisioned. Accepted: the collision message links to the Demo tab instead, and an unwanted kit
  is visible in the list and revocable.

### 4.3 On success

The view builds one entry, merges it into the session list `demo_kit_results`, and redirects to
`_index_url("demo")`. The entry is plain JSON (the session serializer, §2.2):

```
{
  "kit_id": int, "label": str,
  "teacher_username": str, "teacher_password": str,
  "student_username": str, "student_password": str,
  "expires_at": ISO-8601 str (aware, from kit.expires_at.isoformat()),
  "stored_at": POSIX seconds (float),
  "warnings": {kind: {"count": int, "unit_ids": [int, ...], "detail": str | null}, ...}
}
```

- **`warnings` is a per-kind summary, not the raw list.** A `mat-pp` provision emits warnings per
  question and per variant — the command groups them for that reason
  (`demo/management/commands/demo_access.py:90-95`) — and storing every one would put a large blob
  in `django_session` beside the passwords for nothing §4.5 displays. The view builds it from
  `result.warnings`: `count` per kind; `unit_ids` = the first 3 **distinct** non-null `unit_id`s in
  emission order; `detail` = the `reason` for `active_webhook_endpoint` (the endpoint URL) and
  `null` for every other kind.
- **A list, not one key**: two kits created before either is viewed must not overwrite each
  other.
- ⚠️ **Written through a FRESH store, never through `request.session`.** The request loaded its
  session when it began, ~40 s earlier. In between, other requests may have saved: a Demo-tab GET
  that popped entries, another create that added one (the operator who reopened the tab and pressed
  Create again, §4.4), or any other tab writing its own keys — `_language` (`core/views.py:173`),
  course-import staging tokens (`courses/views_transfer.py:144`), `element_clip`
  (`courses/views_manage.py:1734`), `builder_open`, `setup_skipped`. **Anything that marks
  `request.session` modified makes `SessionMiddleware` save the request's whole start-of-request
  snapshot over all of them** — a staged course upload lost because a kit finished. So the view:
  1. `fresh = SessionStore(session_key=request.session.session_key)`, with `SessionStore` from
     `import_module(django_settings.SESSION_ENGINE)`;
  2. `existing = fresh.get("demo_kit_results", [])` — the store's own **cached** read, which calls
     the backend's `load()` exactly once and keeps the result; **if `fresh.session_key is None`
     afterwards, it stops here and writes nothing**;
  3. `fresh["demo_kit_results"] = [*existing, entry]`, then **`fresh.save()`, called explicitly** —
     the backend writes the store's whole data on `save()` whatever its modified flag, and skipping
     the call is P7's mutant;
  4. **never assigns to `request.session` on its own account.** ⚠️ But something else may already
     have modified it: `LanguageSeederMiddleware` writes `_language` before the view whenever the
     stored language is disabled, or absent with an undeliverable candidate
     (`core/middleware.py:28-36`), and Django's `get_user` cycles the key after a `SECRET_KEY`
     fallback rotation. A modified `request.session` is saved whole at the end of the request —
     overwriting the entry just written with the start-of-request snapshot. So, **immediately
     before returning the response, if `request.session.modified` is True, the view mirrors the
     same change into it** (`request.session["demo_kit_results"] = <the list it saved>`) — **only after a successful
     `fresh.save()`**. On the guard-stop and caught-`UpdateError` paths nothing was saved and
     nothing is mirrored: mirroring `[*existing, entry]` there would put both passwords into
     `request.session`, and so into `SessionMiddleware`'s frame outside any `sensitive_variables`
     wrapper, for a save that fails anyway, and the
     end-of-request save agrees with the fresh store. (The rest of that snapshot still overwrites
     other tabs' keys, as it does on any request the seeder touches — pre-existing behaviour, not
     this design's.) P19.

  The lost-update window shrinks from the provision's duration to the milliseconds between the
  store's read and `fresh.save()`, **for every key**, not only this one. P14.
- ⚠️ **Never call `fresh.load()` directly.** `SessionBase.load()` returns the data **without**
  filling `_session_cache` (`django/contrib/sessions/backends/base.py`, `_get_session`; the plan
  cites the lines), so the next item access loads a second time. A row deleted between those two
  loads nulls the key *after* the guard has passed, and `save()` then `create()`s the very orphan
  row the guard exists to prevent — while the merged list comes from one load and every other key
  from the other. P16(b) carries it as a mutant.
- ⚠️ **Why the `session_key is None` guard.** On the DB backend a missing row — the operator logged
  out in another tab, or the session expired, during the ~40 s — makes `_get_session_from_db` set
  that store's `_session_key = None` (`django/contrib/sessions/backends/db.py`; the plan cites the
  line), and `save()` on a key-less store calls `create()`. Without the guard, `fresh.save()` would
  write an **orphan session row holding both passwords** under a key no cookie points at. (Done on
  `request.session` instead, the same path writes the request's in-memory data, `_auth_user_id`
  included, under a new key with a new cookie — the logout silently undone; and an assignment to
  `request.session` without `load()` force-updates the missing row, raising `UpdateError`, which
  `SessionMiddleware` turns into a 400 `SessionInterrupted`.) With the guard, the kit exists, its
  credentials go with the ended session, and the redirect lands on the login page; the operator
  revokes the kit. P16(a).
- ⚠️ **`fresh.save()` can still meet a row deleted after the read.** The DB backend's forced update
  then raises `django.contrib.sessions.backends.base.UpdateError`; the view **catches exactly that
  and continues to the same redirect**, writing nothing — the guard's outcome by another route.
  P16(b).
- No success message: the credentials card is the confirmation.

### 4.4 The credentials card and its lifetime

**Pending credentials are taken in exactly one place: the `settings` view, on a real GET of the
Demo tab.** When `active_tab == "demo"` **and** `request.method == "GET"` **and** the request is
not a speculative load (neither a `Sec-Purpose` nor a `Purpose` header contains `prefetch` or
`prerender`), the view calls a helper `_pending_demo_results(request)` — **before** `_settings_context` — which:

1. **reads** the entries through a fresh store, exactly as §4.3 does —
   `fresh = SessionStore(session_key=request.session.session_key)`;
   `entries = fresh.get("demo_kit_results")` (the cached read, never `fresh.load()`) — and
   **writes nothing**. If `fresh.session_key is None` or `entries` is empty, nothing is pending;
2. checks **every** entry's kit in one query (`DemoKit.objects.filter(pk__in=…,
   closed_at__isnull=True)`): an entry whose kit is **missing or closed** — revoked by another admin
   or by `demo_access revoke`, or purged, before the tab was opened — becomes the notice "Kit #N was
   closed before its credentials were displayed.", **whatever its age**. A password for deleted
   users is never shown, and a closed kit is never called revocable;
3. splits the rest by age: `stored_at` within `DEMO_RESULT_TTL = 15 * 60` seconds become cards,
   with `expires_at` parsed back by `datetime.fromisoformat`; older ones become the notice
   "Credentials for kit #N were never displayed and are gone; revoke it and create another." The
   constant lives beside the view, not in `demo.constants` — it is a property of the tab;
4. builds each card's **warning lines** from its stored summary: an ordered list of
   `(text, count, detail, titles)` — `active_webhook_endpoint` first, then every other kind in `DISPLAY`'s declaration
   order; `text = DISPLAY[kind]`; `titles` from **one** `ContentNode` title query over every card's
   `unit_ids`, a deleted unit skipped. Built here because a template can neither index `DISPLAY` by
   a variable nor sort by declaration order; the template only loops;
5. returns `(cards, notices)`, which the view puts in the context as `demo_results` and
   `demo_notices`.

The view then builds the context and renders the response, and **only after the render has
succeeded, immediately before returning**, calls `_discard_shown_results(request, kit_ids)` with
the kit id of every card and notice it rendered. **When `kit_ids` is empty — nothing was pending —
it is not called at all**, so a routine Demo-tab GET opens no second store and writes nothing; and
it skips `fresh.save()` when `remaining` equals the list it read:

- a **second** fresh store, the same cached read; if its `session_key is None`, nothing;
  otherwise `remaining = [e for e in current if e["kit_id"] not in kit_ids]`, assigned back (or the
  key popped when `remaining` is empty), then `fresh.save()`, catching `UpdateError` exactly as
  §4.3 does;
- an entry a create saved **while this page rendered** is not in `kit_ids`, so it survives for the
  next GET — the discard removes what was shown, never the whole key;
- then, **only after a successful `fresh.save()`**, §4.3 step 4's mirror rule: if
  `request.session.modified`, it is given **the same `remaining` list that store saved** (or the key
  popped when that list was empty) — never a filter over `request.session`'s own start-of-request
  list, which lacks any entry a create saved mid-render. Skipped entirely when the guard stopped or
  `UpdateError` was caught.

**`request.session` is otherwise never modified**, and each fresh store's read-modify-save spans
milliseconds, so neither the read nor the discard saves a stale snapshot over a create's entry or
any other key another tab wrote (P18). **Why the discard waits for the render:** an exception
after the read — the title query, `_settings_context`, the template — propagates before anything is
removed, so the entries stay for the next GET instead of vanishing with a 500 (P20). **What it does
not cover:** a response dropped on its way to the browser; the entries are already discarded when
its bytes leave (§4.4 "Residual loss").

⚠️ **Why nowhere else:**

- **Not on HEAD, OPTIONS or a prefetch.** The `settings` view has no method guard
  (`institution/views_manage.py:148-153`), so a HEAD from an uptime monitor, link prefetcher or
  scanner inside the admin session — the threat `tests/test_settings_action_method_guard.py:10-15`
  names — would pop and save while the body is discarded, and the credentials would vanish with no
  notice. P15.
  A **speculative GET** that finds `demo_kit_results` present reads it **without popping** and
  renders only the notice "Credentials are waiting — reload this page." Chrome *activates* an
  omnibox prerender (`Sec-Purpose: prefetch;prerender`) with no second request, so without the
  notice the operator — just told the credentials appear on this tab — would see an empty panel
  while the entry still waits, and might revoke. The notice carries no password and lives in its own context key, **`demo_waiting`** — a bool set from a
  plain `request.session.get("demo_kit_results")`, a read that never modifies the session — which
  deliberately does **not** trigger `add_never_cache_headers`, so it needs no
  `no-store`.
- **Not in the create view's error re-render.** That page is the answer to a POST: a reload
  re-submits and mints another kit (§4.2), and the collision message tells the operator to leave it
  for the Demo tab. Passwords do not belong on a page the operator is told to leave and must not
  reload. The error re-render shows the form errors only; pending entries wait for the next GET. P9.
- **Not in `_settings_context`**, which every render path calls.

Each card shows: the label and kit id; Teacher username and password; Student username and
password, each in `<code>`; the absolute login URL
(`request.build_absolute_uri(reverse("account_login"))`); the expiry date, rendered with the `date`
filter in the active timezone; and "These passwords are not stored — copy them now." Warnings
follow (§4.5).

**When `demo_results` or `demo_notices` is non-empty, the settings view calls
`django.utils.cache.add_never_cache_headers(response)`** — the only view that can render either,
so those two context keys are the whole signal (`demo_waiting` is deliberately not one). `no-store` *discourages* Back and bfcache from bringing
the passwords back but is not a guarantee: Chrome has been restoring `no-store` pages from bfcache
when no cookie changed. So `demo_tab.js` also **removes the card elements on `pageshow` when
`event.persisted`**, and the local pass (§5) checks Back after reading a card.

⚠️ **What the 15 minutes bounds, honestly:** display, not storage. An unread entry stays in the
`django_session` row until the Demo tab is next opened, the operator logs out (logout flushes the
session), or the session expires. That is a narrow, accepted contradiction of the parent's
"never stored", the same one the parent §4.6 already accepted.

**Why this survives a dropped connection** (A4): the entry is saved by the view's own
`fresh.save()` (§4.3), before the response is even built — let alone written (§2.2) — so an
operator whose browser gave up reopens the Demo tab and sees the card.

⚠️ **Reopening too early.** If the operator reopens the tab while the provision is still running,
there is no card and the uncommitted kit is not in the list; that GET pops nothing and writes
nothing. Pressing Create again then goes one of two ways: a label with the **same slug** — the
same label, or one differing only in punctuation or case ("SP 12" and "SP-12"), or any two labels
that both fall back to `demo` — blocks on the first request's uncommitted usernames and ends in the
`UsernameCollision` message (§4.2), which points at the list; a label with a **different slug**
provisions a second kit, and §4.3's merge against the persisted list keeps both kits' entries. The help text (§4.2) tells the operator to wait rather than
re-create.

⚠️ **Residual loss, accepted:** the merge narrows the lost-update race to the milliseconds between
§4.3's fresh read and the save; and an operator whose session ends mid-provision (a logout in
another tab, an expiry) — **or whose session key is cycled** (logging in again in another tab,
`update_session_auth_hash` after a password change), which deletes the old row while the operator
stays logged in — loses the pending entry with it, deliberately, since §4.3 refuses to recreate a
vanished row. After a logout the redirect lands on the login page; after a key cycle it lands on
an empty Demo tab, with no card and no notice. The **GET side** reads and discards through fresh
stores too (§4.4), so its windows are likewise milliseconds, for every key — but **a Demo-tab
response dropped on its way to the browser loses what it showed**, since the discard runs before
the bytes leave. And a **message-storage overflow** can still undo a write:
`MessageMiddleware` sits inside `SessionMiddleware` (`config/settings/base.py:48-54`), so its
`process_response` runs after the view's mirror check but before the session save, and once queued
messages exceed the cookie limit `FallbackStorage` writes its session key — marking the session
modified and saving the stale snapshot over the fresh store's write. It needs over ~2 KB of queued
messages; accepted, and named so the mirror rule is never read as complete. In every case the list shows a kit whose credentials were never displayed — with **no**
"never displayed" notice, since the entry is gone, so the operator matches the kit by its label
and created time — and revokes it.

### 4.5 Warnings

Rendered under their card by looping over the lines `_pending_demo_results` builds from the stored
summary (§4.3; §4.4 step 4), inside one wrapper element carrying `data-demo-warnings` (the hook P10
scopes its assertions to — the hidden Integrations panel prints the same endpoint URL higher up the
page, §5), one line per kind:

- each line shows the translated `demo.warnings.DISPLAY[kind]` and its `count`;
- **`active_webhook_endpoint` first** — the data-protection signal (parent §3.2) — with its
  `detail`, the endpoint URL;
- then the other kinds in `DISPLAY`'s declaration order;
- a kind with `unit_ids` lists those units' titles (at most 3), fetched in one query over every
  card's ids; a unit deleted since is skipped;
- **no `reason` text is rendered** for any other kind — the summary does not even store it: it is
  an English diagnostic (§2.6), and the panel must be fully translated.

### 4.6 The kit list

Below the form:

- **Default: open kits only** (`closed_at IS NULL`, i.e. `active` and `pending_purge`);
  `?tab=demo&all=1` adds closed kits — the same filter as `demo_access list`
  (`demo/management/commands/demo_access.py:120-123`), and for the same reason (parent §4.6: the
  pending-purge row must not be buried). Read as `request.GET.get("all") == "1"`; any other value
  shows the default. The create view's error re-render always shows the default list.
- ⚠️ **Every link and form action in `_demo_tab.html` is absolute, built from `{% url %}`** — as
  `_tabs.html` builds its links. The panel also renders on the create view's error page, served at
  `manage/settings/demo/create/`, so a bare `href="?tab=demo&all=1"` would resolve to
  `…/demo/create/?tab=demo&all=1`, whose GET hits the create view's non-POST redirect and silently
  drops `all=1`. P11 follows the "show closed kits" link's `href` from a create error page and
  asserts it reaches the settings view with `all=1`.
- Order: the model's `["-created_at", "-pk"]` (`demo/models.py:83`).
- Columns: id, label, course (`course_slug` — it survives the course's deletion,
  `demo/models.py:40-42`), pupils, teacher username (`—` once the FK is nulled), created, expires,
  status.
- **Status** renders `STATUS_DISPLAY[kit.status_key]`, a new map in `demo/models.py` beside the
  property that produces the keys, with translated labels: Active; Expired — pending purge;
  Closed (expired); Closed (revoked). It sits with the keys exactly as `demo.warnings.DISPLAY`
  sits with `KINDS`.
- An empty state when no kit matches.
- Each row is `<tr data-demo-kit="{{ kit.pk }}">`. P11 and P13 locate rows by that attribute, never
  by an id substring — course, group and user pks share the page
  ([[independent-pk-sequences-make-substring-assertions-flaky]]).

### 4.7 Row actions

Shown **only on open rows** (`closed_at IS NULL`, including `pending_purge`). When the list is
showing closed kits, every action form carries a hidden `<input name="all" value="1">`; the view
reads `request.POST.get("all") == "1"` — any other value is ignored, never echoed — and redirects
to `?tab=demo&all=1`, otherwise to `?tab=demo`.

- **Extend.** A POST form to `settings_demo_extend`; the button reads "Extend by %(days)s days"
  from `DEFAULT_DAYS`, never a literal 14. **Both day-count strings in this section** — this label and the long-lived
  warning — are built with `ngettext` (or `{% blocktrans count %}`), with every Polish plural form
  filled: the constants exist so the numbers can change, and *dzień* / *dni* differ. The view calls `extend_kit(kit, days=DEFAULT_DAYS)`,
  then:
  - `messages.success`: "Kit #%(id)s now expires on %(date)s.", with `date` =
    `django.utils.formats.date_format(timezone.localtime(result.new_expires_at))` — the same local
    date the card and the list render, never the aware datetime's `str()`;
  - when `result.long_lived`: `messages.warning`: "After this extension the kit will have been
    open for more than %(days)s days." from `LONG_LIVED_DAYS` — the parent's Risk 3 mitigation,
    which the parent §4.6 requires the tab to render. ⚠️ Worded to match the computation:
    `long_lived` is `kit.expires_at - kit.created_at > LONG_LIVED_DAYS` on the **new** expiry
    (`demo/services.py:423`), the kit's total lifespan, not its age — "has been alive for over 60
    days" would be false about the 50-day-old kit P12 uses. (`demo_access extend` prints the
    inaccurate wording; correcting the command is out of scope.)
  - `KitAlreadyClosed`: `messages.error`, expiry untouched;
  - `InvalidBounds` cannot occur with `DEFAULT_DAYS`, and is not caught.
  - ⚠️ **Accepted race with the nightly purge:** if the 03:45 run closes a pending-purge kit
    between the view's lookup and `extend_kit`, `_require_open` checks the stale in-memory row and
    passes, and `save(update_fields=["expires_at"])` writes a new expiry onto a closed kit; the
    operator reads "now expires on …" for a kit whose logins are gone. The row stays closed and is
    never purged again, and the list shows it closed on the next render. Locking belongs in
    `extend_kit`, not the tab; not done here.
- **Revoke.** A POST form to `settings_demo_revoke` carrying `data-confirm` ("Revoke this demo
  kit? Its logins are deleted immediately."), handled by the existing
  `support/static/support/js/confirm.js`. ⚠️ That script binds once, to the `form[data-confirm]`
  elements that exist when it runs, so **both `<script>` tags in `_demo_tab.html` carry `defer`**
  — placement-independent, as `review_roster.js` is loaded for the review page. Without it a tag
  that lands above the list binds nothing and Revoke deletes the logins unprompted; the e2e
  asserts the dialog fired (§5). The view calls
  `revoke_kit(kit)`, then:
  - `messages.success`: "Kit #%(id)s revoked; its logins were deleted.";
  - `KitAlreadyClosed` — a stale page whose kit was already closed: `messages.error`. (Two
    truly simultaneous revokes both pass `_require_open`, which takes no lock, and both purge; the
    second merely rewrites `closed_at`. Harmless, not guarded.)
- A closed row renders no action forms; a hand-made POST against a closed kit still reaches the
  service's refusal.

### 4.8 Copy and translation

- **Intro, one paragraph:** a kit is a Teacher login — class analytics, per-pupil progress, and
  force-submitting an unfinished quiz — a pupil login that starts with a blank record, and an
  example class of generated pupils; it lasts the chosen number of days and is then deleted
  automatically.
- ⚠️ **No marking, anywhere in the tab** (A6): nothing about marking answers, grading written
  work, or the awaiting-review queue.
  **No automated guard, deliberately.** A banned-words test cannot work in Polish, where *ocena*
  is both "score" and "marking": it either flags legitimate score wording or passes a paraphrase.
  It is a named item in the PR's human review instead.
- Every string translatable; `pl` filled; **0 fuzzy**, which `tests/test_i18n_po_health.py`
  enforces. `makemessages` fuzzy-prefills near-miss translations — clear each one fully
  ([[makemessages-fuzzy-prefills-wrong-translation]]).
- ⚠️ **The Polish needs a native read**, especially `STATUS_DISPLAY`: #318 ships
  `ClosedReason` labels as the neuter *Wygasłe* / *Cofnięte*, a guess at the implied noun. The
  two maps must agree; if the noun changes, change both.

## 5. Testing

Every test that provisions runs under `override_settings(VENDOR_INSTANCE=True)` with a fixed
`seed`, on the `small` fixture (`tests/demo/fixtures.py`). ⚠️ **The view passes no seed** (§4.2), so
the service would draw one from `secrets`. Two mechanisms, one rule: a test that builds a kit to act
on calls `tests/demo/helpers.py::provision_for_test` directly; **a test that provisions through the
tab — the e2e included — patches `institution.views_manage.provision_kit` with a thin wrapper that
calls the real service with `seed=` added**. Tests that need their own wrapper (P14) compose with
it. Without this, P8's four-pupil case — where the band partition is at its thinnest — would pass or
roll back `EmptyKit` by the dice. **Every tab-driven create posts `pupils=MIN_PUPILS`** (P8's bound
cases excepted), and the e2e overwrites the field to `MIN_PUPILS` before submitting: the form's
initial is `DEFAULT_PUPILS` (20), and at ~137 queries per pupil a test copying it pays for four
times the class it needs, per create. Each test is falsified against its
named mutant, run and observed red ([[falsify-tests-not-run-them]]).

| # | Asserts | Mutant |
|---|---|---|
| **P1** | **Narrowing, driven as the role** ([[access-widening-reachability-tests]]). After provisioning with a second course present: `kit.teacher.is_staff` is False; `set(accessible_courses(kit.teacher)) == {kit.course}`; logged in as the Teacher, the other course's outline is **403**, the kit course's outline, a published lesson and a published quiz (the previewer) are 200, `manage_analytics` and `manage_review_queue` for the kit course are 200; `/admin/` redirects to the admin login. `test_the_demo_teacher_can_read_every_course_on_the_box` is **replaced** by this test (renamed `…reads_only_its_kit_course`, docstring rewritten per §2.4), and `test_provision.py:25` becomes `assert not kit.teacher.is_staff and not kit.student.is_staff`. (No `CohortMembership` assertion here: it holds on every build — the Teacher role group keeps the user out of cohorts whatever `is_staff` says, §3.1, and the sync is a no-op without a Default cohort, `grouping/services.py:62-63` — so it would prove nothing about this change; parent T8 already locks it for kits.) | delete the `is_staff = False` line |
| **P2** | **Collision.** A user already holds `<slug>-nauczyciel`; `demo.services._taken` is monkeypatched to return False so the scan misses it. `provision_kit` raises `UsernameCollision` whose `__cause__` is an `IntegrityError`, and no `DemoKit` row survives. Deterministic, no threads. And an `IntegrityError` raised from a patched `demo.services.generate` propagates as `IntegrityError`, **not** `UsernameCollision` — the catch wraps user creation only (§3.2). | remove the catch; wrap the whole `provision_kit` body in it |
| **P3** | **Gating.** Flag off: the settings page has no `?tab=demo` link and no demo panel markup; `?tab=demo` renders the branding panel with 200; each of the three action views returns 404 **to a POST** from a Platform Admin — ⚠️ **extend and revoke POST to a REAL open kit** built with the flag on (`provision_for_test`), and afterwards that kit is still open with an unchanged `expires_at`. Against a missing id, §4.1 step 4's own 404 keeps the assertion green with the flag check deleted. Flag on: a user without `institution.change_institution` gets 403. The three URL names join `ACTION_URL_NAMES`, whose test gains per-name `kwargs` for the two `kit_id` routes and asserts 302 for every non-POST method; that file's docstring (`:67-69`, "needed only for settings_pricing … none of which read the flag") and its "first six share `_action`" comment are updated in the same change, since four views then read the flag. | delete the `VENDOR_INSTANCE` check from the three action views — flag-off POSTs then reach the redirect or the service (`ImproperlyConfigured`), and the 404 assertions go red. ⚠️ Not the parent T10's "gate on `_tabs()` instead": `_tabs()` holds `"demo"` exactly when the flag is on (`institution/views_manage.py:56`), so that mutant is equivalent to the real check and can never go red |
| **P4** | **Create, shown once.** POST valid data → 302 to `?tab=demo`; a `DemoKit` exists with `created_by` the Platform Admin; GET `?tab=demo` contains both usernames and both passwords, with `Cache-Control` containing `no-store`; both passwords authenticate their users; a second GET contains neither password; the session no longer holds `demo_kit_results`; the list page shows the kit without either password. | render the card on the POST response; keep the entry after rendering |
| **P5** | **Self-heal.** After a successful POST, GET `?tab=branding` leaves `demo_kit_results` in the session and renders no password; a following GET `?tab=demo` shows the card. | take pending results on every settings GET, whatever the active tab |
| **P6** | **TTL.** A session entry written directly — ⚠️ its `kit_id` a **real open kit** from `provision_for_test`, or §4.4 step 2 makes it a "closed before" notice on every build — with `stored_at` 16 minutes in the past renders no password, renders the "never displayed" notice naming its kit id and **not** the "closed before" text, and is gone afterwards. | skip the age check |
| **P7** | **Two pending results, through the real write path.** Two successful create POSTs (different labels) before any GET; one GET of `?tab=demo` then shows both cards. | store a single entry under one key; skip `fresh.save()` |
| **P8** | **The form holds no bounds.** `pupils=4` → `response.context["demo_form"].errors["pupils"]` contains `MIN_PUPILS` and `MAX_PUPILS` (asserted on the form's errors, never a page substring — "5" and "40" appear elsewhere on the page), and no kit; blank `label` → error on `label`; a course with no published unit → the `EmptyCourse` non-field error. Then with `demo.services.MIN_PUPILS` monkeypatched to 3, `pupils=4` provisions. And a `DemoKitError` whose message contains `<b>` (the service patched at the name the view resolves) renders it escaped inside `<code>`. | `min_value=5` on the form's `pupils`; build the non-field message with `mark_safe` over an f-string |
| **P9** | **A failed create leaves pending credentials alone.** With an entry X pending — its `kit_id` a **real open kit** from `provision_for_test` — a create POST that fails with `UsernameCollision` (forced as in P2) renders the form error; the `django_session` row still decodes to a `demo_kit_results` holding X, and a following GET shows X's card. The error page's text (translated sentence and appended service detail alike) contains no "retry". ⚠️ The link is asserted **inside `response.context["demo_form"].non_field_errors()`**, never on the page: with the flag on, the tab nav on every settings page already carries `href="…?tab=demo"`. | pop pending results in the create view's error re-render; drop the link from the `UsernameCollision` message |
| **P10** | **Warnings.** A provision over `small_course(quiz_with_review_question=True)` (the flag that yields a whole-quiz skip, `tests/demo/fixtures.py:217-228`) with an enabled `WebhookEndpoint` stores the §4.3 summary shape. Every rendering assertion is **scoped to the `data-demo-warnings` element**, never the page — the hidden Integrations panel prints the same URL above it (`_integrations_tab.html:13`): inside it the endpoint URL precedes the translated `quiz_skipped` text, the webhook line appears **exactly once** (`active_webhook_endpoint` is itself a `DISPLAY` key, so a first-then-loop rendering duplicates it), the title "Reviewed quiz" is listed, and no `reason` text of any other kind appears. Separately, a session entry whose summary carries **every** kind in `demo.warnings.KINDS` (built from the set, never a hand list) — ⚠️ with `kit_id` pointing at a **real open kit** from `provision_for_test`, or §4.4 step 2 turns it into a notice and no warning renders at all — shows, **inside `data-demo-warnings`**, each kind's translated `DISPLAY` text. Not "renders with 200": a missing template key renders an empty string, never an error. | render `reason` for every kind; render the webhook line after the others; drop `detail`; render only kinds found in a hand-kept list in the view |
| **P11** | **List.** With an active, a pending-purge and a closed kit: the default shows the first two in `("-created_at", "-pk")` order, read from the rows' `data-demo-kit` attributes; `all=1` adds the third; a purged kit's teacher column shows `—`; `set(STATUS_DISPLAY) == {"active", "pending_purge"} ∪ {f"closed_{v}" for v in DemoKit.ClosedReason.values}`. | drop the default filter |
| **P12** | **Extend.** On an **active** kit, POST → `expires_at` moves by `DEFAULT_DAYS` and the success message names the date; on a **pending-purge** kit, the new `expires_at` is now + `DEFAULT_DAYS` (within a minute) and its status key returns to `active` (`extend_kit`'s `max(expires_at, now)`); a kit created 50 days ago gets the §4.7 long-lived warning wording, **and the fresh active kit's extend adds no warning message**; a closed kit gets the error message and an unchanged `expires_at`. With `all=1` posted the redirect is `?tab=demo&all=1`; with `all=x`, `?tab=demo` — extend has its own view and redirect, so P13's revoke case does not cover it. | ignore `result.long_lived`; always emit the warning; ignore `all` in the extend view |
| **P13** | **Revoke.** POST → the kit is closed with `closed_reason="revoked"` and its users are gone; a closed kit gets the error message; on `?tab=demo&all=1`, **within the closed kit's row** (`[data-demo-kit="<pk>"]`), no extend or revoke form renders (the default list excludes closed kits, so asserting there is vacuous — second mutant: render the actions unconditionally). With `all=1` posted, the redirect is `?tab=demo&all=1`; with `all=x`, `?tab=demo`. | skip the `revoke_kit` call and still report success |
| **P14** | **The write goes through a fresh store and touches nothing else.** The provisioning call (patched at the name the view resolves, wrapping the real service) first writes, through a separate `SessionStore(session_key=…)` saved to the operator's **stored** session, an entry Y into `demo_kit_results` **and an unrelated key `element_clip = "mid-provision"`** — standing in for other tabs that saved while the kit was being built. After the POST, the stored session holds Y, the new entry, **and `element_clip == "mid-provision"`**. | build the new list from `request.session.get(...)` (Y lost); assign the merged list to `request.session` instead of saving `fresh` (the request's start-of-request snapshot overwrites `element_clip`) |
| **P15** | **Only a real GET takes credentials.** With an entry pending — its `kit_id` a **real open kit** from `provision_for_test` — HEAD `?tab=demo` leaves it in the session; a GET of `?tab=demo` carrying `Sec-Purpose: prefetch;prerender` leaves it, renders no password, and renders the "credentials are waiting — reload this page" notice (§4.4); a plain GET then shows the card. | pop on any request method; render nothing on a speculative load |
| **P16** | **An ended session is not resurrected, and leaves no orphan.** (a) The provisioning wrapper deletes the operator's `django_session` row before returning (standing in for a logout in another tab). The POST response is a **302 to `?tab=demo`**, sets no session cookie, **`Session.objects.count()` is 0 afterwards** (no row was created under any key), and the kit exists. (b) The row is deleted **right after the store's first database read**: inside the provisioning wrapper, `SessionStore._get_session_from_db` is patched to delete the row after its first call returns — started with `monkeypatch.setattr`, so it stays active until the request finishes (a `with mock.patch` block inside the wrapper is undone when the wrapper returns, before the view's fresh store reads, and the test would fail for a construction reason) — the request's own session was loaded (by `login_required`) before the wrapper ran, so that first call is the fresh store's. Again a 302, no cookie, `Session.objects.count()` 0. | (1) drop the guard — in (a) `fresh.save()` on a nulled key `create()`s an orphan row holding both passwords; (2) call `fresh.load()` directly, then assign — the assignment's second load finds no row and nulls the key after the guard passed, and (b) leaves an orphan row; (3) assign the merged list to `request.session` instead of saving `fresh` — in (b) the middleware's save force-updates the deleted row and the response is a 400 `SessionInterrupted`; (4) drop the `UpdateError` catch — in (b) the POST raises `UpdateError` inside the test (the test client re-raises by default; there is no 500 response to assert) |
| **P17** | **No card for a closed kit.** A pending entry whose kit was revoked (`revoke_kit`) before the GET renders the "closed before its credentials were displayed" notice and neither password. | skip the open-kit check in `_pending_demo_results` |
| **P18** | **Taking credentials writes nothing else.** With an entry pending (its `kit_id` a real open kit), `institution.views_manage._settings_context` is wrapped to first write `element_clip = "mid-render"` into the operator's stored session through a separate store — standing in for another tab saving while the Demo tab renders, between §4.4's read and its discard — **and to append a second entry Z** (another real open kit) the same way, standing in for a create that finished mid-render. After the GET: the shown card rendered, the stored session's `demo_kit_results` holds **only Z**, and `element_clip == "mid-render"`. | pop from `request.session` instead of the fresh stores (the end-of-request save restores the start-of-request snapshot over `element_clip` and Z); discard by popping the whole key (Z lost) |
| **P19** | **A middleware-modified session does not undo the fresh store.** Before each request the operator's stored `_language` is set to a code outside `enabled_languages` (e.g. `"de"`), so `LanguageSeederMiddleware` modifies `request.session` on that request (`core/middleware.py:34-36`). (a) A create POST: afterwards the stored session holds the new entry. (b) A Demo-tab GET showing that entry: afterwards the stored session holds no `demo_kit_results`, and a following GET shows no card. | drop the `request.session.modified` mirror — (a) the end-of-request save overwrites the entry; (b) it restores the discarded entry and the card shows twice |
| **P20** | **A render failure keeps the credentials.** With an entry pending (its `kit_id` a real open kit), `institution.views_manage._settings_context` is patched to raise; the GET raises inside the test (the client re-raises); afterwards the stored session still holds the entry, and an unpatched GET shows its card. | discard inside `_pending_demo_results`, before the render |

**One e2e test** (`tests/test_e2e_demo_tab.py`, `@pytest.mark.e2e`): a Platform Admin opens the
Demo tab, fills the form against the `small` fixture course, submits, and reads the credentials
card. A **separate browser context** logs in as the Teacher with the displayed password and loads
the kit course's analytics. Back as the Platform Admin, Revoke is clicked with an explicit
`page.on("dialog", ...)` handler that **records the dialog's message** and accepts it — Playwright
auto-dismisses a `confirm()` otherwise, which reads as a cancel
([[playwright-auto-dismisses-confirm]]) — and the test asserts **a dialog fired with the §4.7
revoke prompt** before asserting the row disappears from the default list. Without the recording,
a Revoke that never prompts still removes the row. Mutant: drop `defer` from the `confirm.js` tag
and place it above the list. Synchronise on conditions, never sleeps.

**Beyond the suite:**

- Locally against `mat-pp`: create a 20-pupil kit through the tab, record the wall-clock seen by
  the browser, read the warnings panel at real volume, screenshot the tab light and dark
  ([[verify-ui-with-screenshots]]), from the card page navigate to another tab, then press
  Back — and separately Back then Forward — and confirm no password is restored (§4.4's
  `no-store` and `pageshow` clearing; pressing Back *from* the card page only reaches the form page,
  which never held one), log in as both kit users, then revoke.
- Read the tab's copy against A6 and the Polish against §4.8, as named PR review items.

## 6. Delivery

- **One PR, no migration.** `STATUS_DISPLAY` is code; §3 is service code.
- **No back-fill.** Prod has never been able to create a kit (`create` refuses without the flag),
  so no staff kit Teacher exists there. The plan's first step confirms it on prod with
  `demo_access list --all` (read-only; exempt from the vendor guard).
- **The flag stays off** (A2). After PR 5 merges and the flag goes on, the parent's §5 step 1
  order applies unchanged — provision and revoke one throwaway kit **through this tab** — which
  also gives the first prod wall-clock (§2.1).
- **Runbook** (`docs/deployment.md`, the demo-kit section): one line — kits can also be issued
  from Settings → Demo access once the flag is on.

## 7. Amendments to the parent spec

Made in the same PR, so the parent stops contradicting what ships:

- **§3.3** "A Teacher **is** staff … grants read access to **every** course": a kit Teacher is
  non-staff since PR 3 and reads only its kit's course; the `/admin/` paragraph is kept as history
  for non-kit Teachers.
- **Risk 2** and **§5 step 0's "Rep visibility" standing check**: retired for kit Teachers.
- **§4.4 step 0**: the `IntegrityError` → named-collision catch is recorded as restored in PR 3
  (§3.2), with the note that PR 2 shipped without it.
- **§4.6 "every action view rejects non-POST with 405"** and **T10's "non-POST → 405"**: 302 to
  `?tab=demo` (A5).
- **§4.6**'s "the plan may instead carry it in the cache": struck (§2.2).
- **T14**: superseded by P1's `/admin/` assertion.
- **§6 "PR 3 — admin tab … No new business logic: every action calls PR 2's services"**: PR 3
  also carries two service changes (§3).
- **§4.6's "redirect to a result page that reads the credentials and the `warnings` from a
  one-shot session key, popped on read"**: superseded by the in-panel card (§4.3–4.4), which also
  stores a warnings summary rather than the raw list.
- **T11** ("the result page", "the list page") and **T22** ("after PR 3's result page is read
  once"): superseded by P4–P6, P9 and P15.
- **§3.7 "the Teacher does not (staff are skipped)"** and **§4.4 step 2 "created with
  `is_staff=True` in the initial `create_user` call"**: neither matches the code — the Teacher is
  created non-staff, joins Default on insert, and leaves on `set_user_role`'s role change (§2.6);
  since PR 3 its cohort exclusion rests on the Teacher role group alone (§3.1).

## 8. Non-goals

- A copy-to-clipboard button, a pre-written email to the school, a per-kit detail page.
- A `frontier_part` or `seed` field on the form (the service and command keep both).
- A worker, job queue or progress surface (A3).
- Guarding the kit Teacher's role against later edits (§3.1).
- Recovering credentials after the 15-minute TTL, or after §4.4's residual lost-update window.

## 9. Open questions

None blocking. The native read of the Polish strings (§4.8) is a review item, not a design
question.
