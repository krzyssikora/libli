"""Migration 0062: legacy plain-text captions become HTML.

Every caption stored before this migration is PLAIN TEXT -- it was rendered with
`{{ el.figcaption }}`, which escaped it on the way out. After this migration the
column is read as HTML (`|safe`), so the stored bytes have to change meaning:
`&` must become `&amp;` and `<` must become `&lt;`, or the caption either
renders wrong or is silently eaten by nh3 on the next save.

transaction=True is MANDATORY: these tests unapply and re-apply a migration,
which cannot run inside the test's atomic block. The `finally` restore targets
the migration graph HEAD (a bare `migrate courses`), never the pinned AFTER
name -- migrating back to a pinned node once 0063 exists is a BACKWARDS plan
that drops every column added since, poisoning every later transactional test.
"""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from courses.sanitize import sanitize_caption

BEFORE = [("courses", "0061_mediaasset_source_url")]
AFTER = [("courses", "0062_figcaption_richtext")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor


def _make_image(apps, caption):
    Course = apps.get_model("courses", "Course")
    MediaAsset = apps.get_model("courses", "MediaAsset")
    ImageElement = apps.get_model("courses", "ImageElement")
    course = Course.objects.create(title="c", slug=f"c-{caption!r:.8}-{id(caption)}")
    media = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )
    return ImageElement.objects.create(media=media, alt="a", figcaption=caption)


@pytest.mark.django_db(transaction=True)
def test_0062_escapes_the_characters_that_change_meaning_as_html():
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        amp = _make_image(old_apps, "Tom & Jerry")
        # A caption that LOOKS like markup. Before 0062 this rendered as the
        # literal characters "<b>x</b>"; unescaped, it would silently start
        # rendering as bold text.
        markup = _make_image(old_apps, "<b>x</b>")
        # The value nh3 EATS: an unescaped "<" followed by a letter opens a tag
        # that never closes, and everything after it is dropped. Left unescaped,
        # the author's next save would silently truncate this caption to "\\(a".
        math = _make_image(old_apps, "\\(a<b\\)")
        quoted = _make_image(old_apps, 'she said "hi"')
        blank = _make_image(old_apps, "")

        new_apps = _migrate(AFTER).loader.project_state(AFTER).apps
        New = new_apps.get_model("courses", "ImageElement")
        assert New.objects.get(pk=amp.pk).figcaption == "Tom &amp; Jerry"
        assert New.objects.get(pk=markup.pk).figcaption == "&lt;b&gt;x&lt;/b&gt;"
        assert New.objects.get(pk=math.pk).figcaption == "\\(a&lt;b\\)"
        # quote=False: a double quote is not special in TEXT content, and
        # escaping it would put a literal "&quot;" in front of every reader.
        assert New.objects.get(pk=quoted.pk).figcaption == 'she said "hi"'
        assert New.objects.get(pk=blank.pk).figcaption == ""
    finally:
        call_command("migrate", "courses", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_0062_output_survives_the_sanitiser_unchanged():
    """The migration's output is what the NEXT save re-sanitises. If escaping and
    sanitising disagree, the first edit of an untouched caption silently rewrites
    it -- so the escaped form must be a fixed point of sanitize_caption."""
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        rows = [_make_image(old_apps, v) for v in ("a & b", "\\(a<b\\)", "x > y")]

        new_apps = _migrate(AFTER).loader.project_state(AFTER).apps
        New = new_apps.get_model("courses", "ImageElement")
        for row in rows:
            stored = New.objects.get(pk=row.pk).figcaption
            assert sanitize_caption(stored) == stored, f"not a fixed point: {stored!r}"
    finally:
        call_command("migrate", "courses", verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_0062_reverse_restores_the_plain_text():
    """Reversible on purpose, unlike the irreversible cases that use
    RunPython.noop: escaping is information-preserving, so an operator rolling
    back to 0061 gets the exact bytes they had."""
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        row = _make_image(old_apps, "Tom & Jerry <b>x</b>")

        _migrate(AFTER)
        back_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        Old = back_apps.get_model("courses", "ImageElement")
        assert Old.objects.get(pk=row.pk).figcaption == "Tom & Jerry <b>x</b>"
    finally:
        call_command("migrate", "courses", verbosity=0)
