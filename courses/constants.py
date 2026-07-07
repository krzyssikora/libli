"""Content-language constants, pinned per-course (separate from settings.LANGUAGES)."""

# Content language is monolingual-per-course and pinned here (NOT settings.LANGUAGES),
# so adding a future chrome language never silently becomes a valid content language.
COURSE_LANGUAGES = [("en", "English"), ("pl", "Polski")]
