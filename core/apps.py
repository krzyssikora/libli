from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.db.models.signals import post_delete
        from django.db.models.signals import post_save

        from core.services import invalidate_site_config
        from institution.models import BrandColor
        from institution.models import Institution

        for model in (Institution, BrandColor):
            post_save.connect(invalidate_site_config, sender=model)
            post_delete.connect(invalidate_site_config, sender=model)

        from core import signals  # noqa: F401  (registers login/logout receivers)
