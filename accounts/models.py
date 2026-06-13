from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """libli user. Extra fields (email override, display_name, language, theme)
    are added in Task 4."""
