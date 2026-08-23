from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "support"

    def ready(self):
        from support import signals  # noqa: F401  (receivers register on import)
