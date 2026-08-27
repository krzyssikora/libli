"""Operational institution settings (branding colours admin is Phase 5)."""

import os
import re

from django import forms
from django.conf import settings
from django.db import transaction
from django.forms import renderers as form_renderers
from django.forms.widgets import ClearableFileInput
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from core.services import ACCENT_DEFAULT
from core.services import PRIMARY_DEFAULT
from courses import validators as _cv
from institution.models import BrandColor
from institution.models import Institution
from institution.site_domain import PLACEHOLDER_DOMAIN
from institution.site_domain import set_site_domain
from institution.site_domain import validate_site_domain


class BrandingFileInput(ClearableFileInput):
    """ClearableFileInput that renders via a styled project template.

    BoundField.as_widget() passes renderer=form.renderer (the default form
    renderer, which only looks in Django's built-in forms/templates dir).
    We override _render() to always use TemplatesSetting instead so the
    project's TEMPLATES dirs are searched for the custom widget template.
    The native checkbox_name ("<field>-clear") is preserved so Django's
    value_from_datadict / clear logic fires unchanged.

    Copy is per-field: the five labels default to the logo's wording so the logo
    field's msgids and rendered copy are unchanged by the generalization (its
    data-* hook names and CSS classes are deliberately renamed).
    icon_variant is a boolean, not a CSS-class string, because it forks
    accessibility markup as well as styling -- keying an aria decision off a
    class name would let the two drift.
    """

    template_name = "institution/manage/widgets/branding_file.html"

    def __init__(
        self,
        attrs=None,
        *,
        current_label=None,
        empty_label=None,
        replace_label=None,
        upload_label=None,
        remove_label=None,
        icon_variant=False,
    ):
        super().__init__(attrs)
        self.current_label = current_label or _("Current logo")
        self.empty_label = empty_label or _("No logo yet")
        self.replace_label = replace_label or _("Replace logo")
        self.upload_label = upload_label or _("Upload logo")
        self.remove_label = remove_label or _("Remove logo")
        self.icon_variant = icon_variant

    def get_context(self, name, value, attrs):
        # Constructor kwargs are invisible to the widget template without this.
        context = super().get_context(name, value, attrs)
        context["widget"].update(
            {
                "current_label": self.current_label,
                "empty_label": self.empty_label,
                "replace_label": self.replace_label,
                "upload_label": self.upload_label,
                "remove_label": self.remove_label,
                "icon_variant": self.icon_variant,
            }
        )
        return context

    def _render(self, template_name, context, renderer=None):
        return super()._render(
            template_name, context, form_renderers.TemplatesSetting()
        )


MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_FAVICON_BYTES = 256 * 1024  # 256 KB -- fetched by every visitor

FAVICON_CURRENT = _("Current favicon")
FAVICON_EMPTY = _("No favicon yet")
FAVICON_REPLACE = _("Replace favicon")
FAVICON_UPLOAD = _("Upload favicon")
FAVICON_REMOVE = _("Remove favicon")

ALLOWED_FAVICON_SUFFIX = ".png"
MIN_FAVICON_PX = 192
MAX_FAVICON_PX = 512

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")


def normalize_hex(value):
    """Return a lowercased #rrggbb hex, expanding #rgb; None if not coercible."""
    v = (value or "").strip()
    if _HEX3.match(v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    if _HEX6.match(v):
        return v.lower()
    return None


def _hex_field(label):
    field = forms.RegexField(
        regex=_HEX6,
        label=label,
        error_messages={"invalid": _("Enter a 6-digit hex colour like #147E78.")},
    )
    field.widget.attrs["data-hex"] = "1"  # JS hook to mirror the <input type=color>
    return field


class BrandingForm(forms.ModelForm):
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled languages"),
    )
    default_language = forms.ChoiceField(
        choices=settings.LANGUAGES, label=_("Default language")
    )
    primary = _hex_field(_("Primary colour"))
    accent = _hex_field(_("Accent colour"))
    # NOT an Institution field: this writes django.contrib.sites.Site, which is
    # where build_accept_url reads the host for invitation and reset links.
    public_hostname = forms.CharField(
        required=False,
        label=_("Public hostname"),
        help_text=_(
            "The address people use to reach this site, e.g. libli.example.org. "
            "Used to build invitation and password-reset links. It does not "
            "change which addresses the server accepts — your host set that up."
        ),
    )

    class Meta:
        model = Institution
        fields = [
            "name",
            "logo",
            "favicon",
            "enabled_languages",
            "default_language",
            "default_theme",
        ]
        widgets = {
            "logo": BrandingFileInput(),
            "favicon": BrandingFileInput(
                current_label=FAVICON_CURRENT,
                empty_label=FAVICON_EMPTY,
                replace_label=FAVICON_REPLACE,
                upload_label=FAVICON_UPLOAD,
                remove_label=FAVICON_REMOVE,
                icon_variant=True,
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed the colour fields from existing BrandColor rows, normalized to
        # 6-digit lowercase hex so a pre-existing #fff / #AABBCC / rgb() value can
        # never start the field in a state that rejects an unrelated save.
        rows = (
            {c.key: c.value for c in self.instance.brand_colors.all()}
            if self.instance.pk
            else {}
        )
        self.initial.setdefault(
            "primary", normalize_hex(rows.get("primary")) or PRIMARY_DEFAULT.lower()
        )
        self.initial.setdefault(
            "accent", normalize_hex(rows.get("accent")) or ACCENT_DEFAULT.lower()
        )
        # Seed from the live Site so the admin edits the current value rather
        # than a blank box. Same setdefault idiom as the colours above.
        #
        # EXCEPT for Django's "example.com" placeholder: that value passes
        # validate_site_domain, so pre-filling it would let an admin click Next
        # and write back the exact broken state this field exists to fix. A
        # blank box prompts them instead.
        from django.contrib.sites.models import Site

        current = Site.objects.get_current().domain
        self.initial.setdefault(
            "public_hostname", "" if current == PLACEHOLDER_DOMAIN else current
        )

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError(_("Enable at least one language."))
        return value

    def clean_public_hostname(self):
        value = (self.cleaned_data.get("public_hostname") or "").strip()
        if not value:
            return ""  # optional: blank leaves the Site record untouched
        return validate_site_domain(value)

    def clean_logo(self):
        value = self.cleaned_data.get("logo")
        if not value:
            return value
        if getattr(value, "size", 0) > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("Logo must be 2 MB or smaller."))
        return value

    def clean_favicon(self):
        value = self.cleaned_data.get("favicon")
        # Three different things land here: a fresh upload (which forms.ImageField
        # has given an .image), the sentinel False (clear ticked), or the existing
        # FieldFile (field untouched). Only the first carries .image; touching
        # .image on the others is a 500 on every ordinary Branding save.
        image = getattr(value, "image", None)
        if image is None:
            return value

        # Cheapest first, so a fixture violating two rules reports deterministically.
        if getattr(value, "size", 0) > MAX_FAVICON_BYTES:
            raise forms.ValidationError(_("The favicon must be 256 KB or smaller."))

        suffix = os.path.splitext(value.name or "")[1].lower()
        if suffix != ALLOWED_FAVICON_SUFFIX:
            raise forms.ValidationError(_("The favicon must be a .png file."))

        if image.format != "PNG":
            raise forms.ValidationError(_("The favicon must be a PNG image."))

        width, height = image.size
        if width != height:
            raise forms.ValidationError(
                _(
                    "The favicon must be square - crop it to equal width and "
                    "height first."
                )
            )

        if not (MIN_FAVICON_PX <= width <= MAX_FAVICON_PX):
            raise forms.ValidationError(
                _("The favicon must be between 192 and 512 pixels.")
            )

        return value

    def clean_primary(self):
        return self.cleaned_data["primary"].lower()

    def clean_accent(self):
        return self.cleaned_data["accent"].lower()

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language", _("Default language must be an enabled language.")
            )
        return cleaned

    def save(self, commit=True):
        with transaction.atomic():
            inst = super().save(commit=commit)
            for key in ("primary", "accent"):
                BrandColor.objects.update_or_create(
                    institution=inst,
                    key=key,
                    defaults={"value": self.cleaned_data[key]},
                )
            # Inside the same atomic block: a failed Site write must not leave
            # the colours committed against a half-applied identity change.
            #
            # name= too: Django ships Site #1 with name AND domain set to
            # "example.com", and allauth prefixes every account email subject
            # with "[{site.name}] " and renders it in the body. Leaving it would
            # keep the placeholder on the very surface this fixes.
            hostname = self.cleaned_data.get("public_hostname")
            if commit and hostname:
                set_site_domain(hostname, name=self.cleaned_data["name"])
        return inst


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*)(\.[a-z0-9](-?[a-z0-9])*)+$"
)


class AccessForm(forms.ModelForm):
    # allowed_email_domains is a JSONField; the default ModelForm widget would
    # demand literal JSON. Override with a plain textarea (one domain per line).
    allowed_email_domains = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        label=_("Allowed email domains"),
        help_text=_("One domain per line. Leave blank to allow any domain."),
    )

    class Meta:
        model = Institution
        fields = ["signup_policy"]  # allowed_email_domains handled manually below

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "allowed_email_domains" not in self.initial:
            self.initial["allowed_email_domains"] = "\n".join(
                self.instance.allowed_email_domains or []
            )

    def clean_allowed_email_domains(self):
        raw = self.cleaned_data.get("allowed_email_domains", "")
        out = []
        for line in raw.splitlines():
            d = line.strip().lower().lstrip("@").strip()
            if not d:
                continue
            if not _DOMAIN_RE.match(d):
                raise forms.ValidationError(
                    _('"%(d)s" is not a valid domain.') % {"d": d}
                )
            if d not in out:  # order-stable dedupe
                out.append(d)
        return out

    def save(self, commit=True):
        self.instance.allowed_email_domains = self.cleaned_data["allowed_email_domains"]
        return super().save(commit=commit)


class UploadsForm(forms.ModelForm):
    allowed_image_extensions = forms.MultipleChoiceField(
        choices=[(e, e) for e in _cv.SAFE_IMAGE_EXTENSIONS],
        widget=forms.CheckboxSelectMultiple,
        label=_("Allowed image types"),
    )
    allowed_video_extensions = forms.MultipleChoiceField(
        choices=[(e, e) for e in _cv.SAFE_VIDEO_EXTENSIONS],
        widget=forms.CheckboxSelectMultiple,
        label=_("Allowed video types"),
    )
    max_image_mib = forms.IntegerField(
        min_value=1,
        max_value=_cv.MAX_IMAGE_MIB_CEILING,
        label=_("Max image size (MiB)"),
        help_text=format_lazy(_("Up to {n} MiB."), n=_cv.MAX_IMAGE_MIB_CEILING),
    )
    max_video_mib = forms.IntegerField(
        min_value=1,
        max_value=_cv.MAX_VIDEO_MIB_CEILING,
        label=_("Max video size (MiB)"),
        help_text=format_lazy(_("Up to {n} MiB."), n=_cv.MAX_VIDEO_MIB_CEILING),
    )

    class Meta:
        model = Institution
        fields = [
            "allowed_image_extensions",
            "allowed_video_extensions",
            "max_image_mib",
            "max_video_mib",
        ]

    def clean_allowed_image_extensions(self):
        value = self.cleaned_data["allowed_image_extensions"]
        if not value:
            raise forms.ValidationError(_("Enable at least one image type."))
        return value

    def clean_allowed_video_extensions(self):
        value = self.cleaned_data["allowed_video_extensions"]
        if not value:
            raise forms.ValidationError(_("Enable at least one video type."))
        return value


class RetentionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = ["notification_retention_days"]
        labels = {"notification_retention_days": _("Retention window (days)")}
