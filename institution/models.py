from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.public_pages import normalize_lang
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

    # Ordered by openness. "sso_only" means: no local signup form at all, but a
    # brand-new SSO identity is provisioned just-in-time, still gated by
    # allowed_email_domains (accounts/provisioning.evaluate_sso_provisioning).
    # It exists because SSO auto-provisioning previously required "open", which
    # also threw the password signup form open to the public internet.
    # Invitations work under every policy -- accounts.views.accept_invite never
    # reads this field -- and so does password LOGIN for accounts that already
    # exist, which is what keeps the init_platform admin as a break-glass route.
    SIGNUP_CHOICES = [
        ("invite", _("Invite only")),
        ("sso_only", _("SSO only")),
        ("open", _("Open self-signup")),
    ]
    THEME_CHOICES = [("light", _("Light")), ("dark", _("Dark")), ("auto", _("Auto"))]

    name = models.CharField(
        max_length=200, default="My Institution", verbose_name=_("Name")
    )
    logo = models.ImageField(
        upload_to="branding/", blank=True, null=True, verbose_name=_("Logo")
    )
    favicon = models.ImageField(
        upload_to="branding/",
        blank=True,
        null=True,
        verbose_name=_("Favicon"),
        help_text=_(
            "Square PNG, 192-512 px, up to 256 KB. Replaces the libli icon in "
            "browser tabs and on home screens. Transparent areas show as black on "
            "iOS home screens - use a solid background for best results."
        ),
    )
    signup_policy = models.CharField(
        max_length=10,
        choices=SIGNUP_CHOICES,
        default="invite",
        verbose_name=_("Signup policy"),
        help_text=_(
            "Invite only: you create every account. SSO only: anyone signing in "
            "through your identity provider gets an account automatically, with "
            "no password form on the site. Open self-signup: anyone can register "
            "with a password. SSO only and Open are both restricted by the "
            "allowed email domains below. Invitations and existing logins keep "
            "working whichever you choose."
        ),
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
        max_length=5,
        choices=THEME_CHOICES,
        default="auto",
        verbose_name=_("Default theme"),
    )
    onboarded = models.BooleanField(
        default=False,
        help_text="Set True once the first-run setup wizard is completed.",
    )

    MAX_RETENTION_DAYS = 3650  # 10-year policy ceiling (mirrors the form validator).

    notification_retention_days = models.PositiveIntegerField(
        default=90,
        validators=[MaxValueValidator(MAX_RETENTION_DAYS)],
        help_text=_(
            "Delete read notifications older than this many days, measured from "
            "when each notification was created. 0 keeps read notifications "
            "indefinitely; orphaned notifications are removed regardless."
        ),
    )

    controller_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Data controller name"),
        help_text=_(
            "Shown on the public privacy notice. Falls back to the "
            "institution name when blank."
        ),
    )
    controller_address = models.TextField(
        blank=True,
        verbose_name=_("Data controller address"),
        help_text=_("Postal address. Omitted from the notice entirely when blank."),
    )
    contact_email = models.EmailField(
        blank=True,
        verbose_name=_("Contact address for data requests"),
    )
    supervisory_authority = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Supervisory authority"),
        help_text=_(
            "The data-protection regulator for your country (in Poland, "
            "UODO). A neutral phrase is used when blank."
        ),
    )
    demo_instance = models.BooleanField(
        default=False,
        verbose_name=_("This is a demonstration site"),
        help_text=_(
            "Adds a warning to the public pages telling visitors not to "
            "enter real pupil data."
        ),
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


MAX_RETENTION_DAYS = Institution.MAX_RETENTION_DAYS


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


class PublicPage(models.Model):
    """Per-(page, language) admin override of a shipped public page.

    Deleting a row IS the "revert to default" action -- there is no separate
    flag, so the two cannot diverge. `slug` carries no choices: Django
    serialises choices into migrations, and the PAGES titles are lazy strings
    with no business in a migration file. A row whose slug is no longer in
    PAGES is inert (invisible to the panel, unreachable by the resolver) and is
    cleaned up by hand here in the admin.
    """

    slug = models.CharField(max_length=32)
    language = models.CharField(max_length=5)
    body_markdown = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "language"], name="uniq_publicpage_slug_language"
            )
        ]

    def save(self, *args, **kwargs):
        # INVARIANT: always a bare code. Enforced here rather than only in the
        # settings panel, because the Django admin is a second write path and a
        # "pl-PL" row is one the normalised lookup can never match.
        self.language = normalize_lang(self.language)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.slug} [{self.language}]"
