# Conventions

The code-level rules a contributor needs. CI
([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)) enforces all of
these; run them locally before pushing.

## Code style

Ruff is the linter **and** the formatter. Both checks are separate and both must
pass:

```bash
uv run ruff check .            # lint  (rules: E, F, I, UP, B, S)
uv run ruff format --check .   # format
```

A recurring mistake is running only `ruff check` and being surprised when CI
fails on formatting. Run **both**, or `uv run ruff check --fix . && uv run ruff format .`.

- Imports go **at the top of the file**, one per line, isort-ordered
  (`force-single-line`). The `E402` (import-not-at-top) rule is active and is
  **not** auto-fixable — you have to move the import yourself.
- `S` (flake8-bandit) is on. `S101` (assert) is ignored globally; test files
  additionally ignore the hardcoded-password rules (see below).
- Migrations are excluded from ruff.

## Testing

- pytest via `pytest-django`; settings module is `config.settings.test` (pinned
  in `pyproject.toml`). Run with `uv run pytest`.
- Tests live in one top-level **`tests/`** package (not per-app), with
  `tests/factories.py` for factory-boy factories and helpers.
- **Never hardcode passwords.** Use `tests.factories.TEST_PASSWORD`. GitGuardian
  flags new password literals in CI, and ruff's `S105/S106/S107` are only ignored
  under `tests/`. Role-logged-in test clients: `make_pa`, `make_ca`,
  `make_teacher`, `make_student` (each seeds roles and logs in).
- **Browser e2e** tests are marked `e2e` and excluded by default
  (`addopts = "-q -m 'not e2e'"`). Run them with `uv run playwright install
  chromium` then `uv run pytest -m e2e`. e2e must drive the **real** UI gesture,
  not a `page.evaluate` shortcut — bypassing the gesture ships broken UX green.

## Internationalization

libli is bilingual (English + Polish). User-facing strings are translated; the
Polish catalog is real, not machine-noise.

```bash
uv run python manage.py makemessages -l pl
# …translate locale/pl/LC_MESSAGES/django.po…
uv run python manage.py compilemessages
```

- **Fuzzy-match gotcha:** `makemessages` will fuzzy-match a new string to an
  unrelated old one (e.g. "Send test event" → "Send reset link"). Always review
  new entries, clear the `#, fuzzy` flag, and write the real translation.
- Module-level translatable data (dicts of labels, choices) must use
  `gettext_lazy`, **not** `gettext` — eager `gettext` at import time freezes the
  string to whatever language was active then.
- The project forbids obsolete `#~` entries in the catalog; a test asserts the
  catalog is clean. When a change deletes translatable strings, re-run
  `makemessages` and remove the resulting `#~` lines.

## Adding content / question types

The content model is a `ContentNode` tree + an `Element` generic-FK join row
pointing at concrete per-type models (see
[`architecture.md`](architecture.md)). To add an element type: create the
concrete model, wire it into the `Element` GFK and the render/editor dispatch,
and add its label. New quiz question types subclass `QuestionElement` and reuse
the quiz persistence/scoring machinery rather than adding new views.

## Migrations & checks

```bash
uv run python manage.py makemigrations --check   # must report no missing migrations
uv run python manage.py check                    # system checks clean
```

Commit the migration in the same change as the model edit. Both checks are part
of the definition of done, alongside the ruff and pytest commands above.
