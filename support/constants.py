"""Every cap and limit the support app enforces, named so tests assert on a name."""

from datetime import timedelta

DESCRIPTION_MAX_LENGTH = 4000
PAGE_URL_MAX_LENGTH = 2000
PAGE_TITLE_MAX_LENGTH = 300
REPORTER_LABEL_MAX_LENGTH = 200
REPORTER_ROLES_MAX_LENGTH = 200
THROTTLE_MAX_REPORTS = 5  # per user, per window
THROTTLE_WINDOW = timedelta(hours=1)
EXTRA_EMAILS_MAX = 20
SUPPORT_CONFIG_CACHE_KEY = "support:config"
SUPPORT_CONFIG_TTL = 300  # seconds; mirrors core.services.CACHE_TTL
LIST_PAGE_SIZE = 25
