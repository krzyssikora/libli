from django.apps import AppConfig


class GroupingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "grouping"

    def ready(self):
        # Registers the post_save→default-cohort receiver (added in Task 2).
        from grouping import signals  # noqa: F401
