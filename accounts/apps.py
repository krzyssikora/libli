from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Import registers the user_signed_up receiver.
        from accounts import signals  # noqa: F401
