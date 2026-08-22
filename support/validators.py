"""Screenshot upload validation.

Deliberately NOT courses.validators.validate_image_file: that one applies
Institution.allowed_image_extensions, which a PA may narrow for CONTENT uploads.
A PA restricting course images to jpg/webp would then silently break screenshot
paste, since clipboard images are PNG on Windows. Bug reporting must not depend
on an unrelated setting, so screenshots validate against the permanent ceiling.
"""

from django.utils.translation import gettext_lazy as _

from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import SAFE_IMAGE_EXTENSIONS
from courses.validators import _validate_file

MAX_SCREENSHOT_BYTES = MAX_IMAGE_MIB_CEILING * 1024 * 1024


def validate_screenshot_file(file):
    # Delegates to _validate_file so the `_committed` early-return is inherited:
    # without it, reading .size on an already-stored file raises FileNotFoundError
    # whenever the file is absent from storage (a DB restored against a fresh
    # volume), and any later full_clean() of an existing report would blow up.
    _validate_file(
        file,
        extensions=SAFE_IMAGE_EXTENSIONS,
        # The constant is a MiB COUNT, not bytes — passing it through verbatim
        # would cap screenshots at five bytes.
        max_bytes=MAX_SCREENSHOT_BYTES,
        too_big_msg=_("Screenshot too large (max %(mib)d MiB).")
        % {"mib": MAX_IMAGE_MIB_CEILING},
    )
