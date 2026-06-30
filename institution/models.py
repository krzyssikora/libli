from django.db import models
from django.utils.translation import gettext_lazy as _

from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import MAX_VIDEO_MIB_CEILING
from courses.validators import default_image_extensions
from courses.validators import default_video_extensions
from institution.validators import validate_css_color


def default_languages():
    # Module-level (not a lambda): migrations must be able to serialize the default.
    return ["en", "pl"]


class Institution(models.Model):
    """Single-row, runtime-editable institution config. Use Institution.load()."""

    SIGNUP_CHOICES = [("invite", _("Invite only")), ("open", _("Open self-signup"))]
    THEME_CHOICES = [("light", _("Light")), ("dark", _("Dark")), ("auto", _("Auto"))]

    name = models.CharField(max_length=200, default="My Institution")
    logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    signup_policy = models.CharField(
        max_length=10, choices=SIGNUP_CHOICES, default="invite"
    )
    allowed_email_domains = models.JSONField(default=list, blank=True)
    allowed_image_extensions = models.JSONField(
        default=default_image_extensions, blank=True
    )
    allowed_video_extensions = models.JSONField(
        default=default_video_extensions, blank=True
    )
    max_image_mib = models.PositiveIntegerField(default=MAX_IMAGE_MIB_CEILING)
    max_video_mib = models.PositiveIntegerField(default=MAX_VIDEO_MIB_CEILING)
    enabled_languages = models.JSONField(default=default_languages, blank=True)
    default_language = models.CharField(max_length=5, default="en")
    default_theme = models.CharField(
        max_length=5, choices=THEME_CHOICES, default="auto"
    )
    onboarded = models.BooleanField(
        default=False,
        help_text="Set True once the first-run setup wizard is completed.",
    )

    def save(self, *args, **kwargs):
        # Enforce singleton: always row pk=1. A second save() updates that one
        # row rather than inserting a duplicate.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.name


class BrandColor(models.Model):
    """Named brand color (e.g. 'primary', 'accent').

    New color keys need no schema change.
    """

    institution = models.ForeignKey(
        Institution, related_name="brand_colors", on_delete=models.CASCADE
    )
    key = models.SlugField(max_length=40)
    value = models.CharField(
        max_length=64, validators=[validate_css_color]
    )  # CSS color string; validated (anchored) before admin save + inline emit

    class Meta:
        unique_together = [("institution", "key")]

    def __str__(self):
        return f"{self.key}={self.value}"
