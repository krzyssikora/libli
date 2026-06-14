from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Import registers signal receivers (user_signed_up, post_save→Invitation).
        from accounts import signals  # noqa: F401
