"""Report notification email. Fully implemented in Task 5."""

import logging

logger = logging.getLogger(__name__)


def send_issue_report_email(report):
    """MUST swallow and log every exception internally.

    Atomic.__exit__ commits and THEN runs the on-commit hooks, both still inside
    the `with` block — so an exception escaping here would propagate into
    report_create's rollback `except`, which is guarded only on saved_name and
    cannot tell a rollback from a post-commit failure. That would delete a
    COMMITTED report's screenshot and 500 a reporter whose report was saved. No
    test can catch it either: django_capture_on_commit_callbacks runs callbacks
    outside the atomic exit, so the interaction never reproduces in the suite.
    """
    return None
