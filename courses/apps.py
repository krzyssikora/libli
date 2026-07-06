from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "courses"

    def ready(self):
        # Register post_delete receivers (e.g. MediaAsset file cleanup).
        from courses import signals  # noqa: F401
