# libli production image. Single-stage: uv makes the dependency install fast
# enough that a builder stage buys little, and the runtime needs the same
# interpreter anyway.
FROM python:3.13-slim

# UV_FROZEN: never re-resolve at runtime. Without it every `uv run` in the
# entrypoint re-checks the lockfile, which can become a network operation on a
# box with restricted egress.
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# curl for the compose healthcheck defined in Task 5. libpq5 is belt-and-braces:
# psycopg[binary] ships its own libpq, so it is only needed if that pin is ever
# swapped for a source build.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Pinned: :latest would let a uv release change `sync`/`run` behaviour and break
# the deploy with no diff in the repo.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# collectstatic MUST run at build time, not at boot: STORAGES["staticfiles"] is
# whitenoise's CompressedManifestStaticFilesStorage (config/settings/base.py:156),
# which is manifest-based -- without the manifest in the image every {% static %}
# reference raises at runtime.
#
# A throwaway SECRET_KEY and a dummy DATABASE_URL. NOT because settings import
# needs them -- base.py:14 and base.py:84 both carry defaults -- but so the build
# is explicit about its configuration and never bakes the insecure dev default
# into a compiled module or a build log.
#
# /app/.venv/bin/python, NOT `uv run`: uv run re-syncs the environment before
# executing and does NOT inherit the --no-dev above, so it would reinstall
# pytest, pytest-django, pytest-xdist and pytest-playwright into the production
# image -- and need network access on a layer that should need none.
RUN DJANGO_SECRET_KEY=build-only-not-a-runtime-secret \
    DATABASE_URL=postgres://u:p@localhost:5432/db \
    /app/.venv/bin/python manage.py collectstatic --noinput

# locale/*/LC_MESSAGES/*.mo are committed, so no compilemessages step.

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
