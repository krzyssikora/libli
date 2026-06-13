from config.settings.base import *  # noqa: F403

# DEBUG is driven by DJANGO_DEBUG in .env (read in base.py); .env.example sets it true.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
