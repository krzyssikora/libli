from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tags.models import TAG_NAME_MAX_LEN


def normalize_name(raw):
    """Collapse all whitespace runs to single spaces; strip ends."""
    return " ".join((raw or "").split())


def _clean_name(raw):
    name = normalize_name(raw)
    if not name:
        raise ValidationError(_("Enter a tag name."))
    if len(name) > TAG_NAME_MAX_LEN:
        raise ValidationError(
            _("Tag name is too long (max %(n)d characters).") % {"n": TAG_NAME_MAX_LEN}
        )
    return name
