"""Course transfer archive format: constants, error type, document validation.

Format spec: docs/superpowers/specs/2026-07-05-course-export-import-design.md §2/§5.
"""

FORMAT_VERSION = 1
KIND_COURSE = "course"
KIND_SUBTREE = "subtree"


class TransferError(Exception):
    """Any export/import rejection. `message` is user-facing and translated."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)
