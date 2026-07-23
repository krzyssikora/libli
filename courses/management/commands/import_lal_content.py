"""Load one seeded LAL part (manifest + unit JSON) into a course, idempotently."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.guards import assert_iframe_hosts_allowlisted
from courses.lal_loader.guards import assert_no_foreign_top_level
from courses.lal_loader.guards import ensure_depth_policy
from courses.lal_loader.guards import owned_part_orders
from courses.lal_loader.guards import resolve_course
from courses.lal_loader.tree import prune_orphans
from courses.lal_loader.tree import rebuild_unit_elements
from courses.lal_loader.tree import upsert_node
from courses.models import MediaAsset


class Command(BaseCommand):
    help = "Load one seeded LAL part into a course (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--course", default="matematyka")
        parser.add_argument("--part", required=True)
        parser.add_argument("--json-dir", default="scripts/lal_import/out")
        parser.add_argument("--source-root", required=True)
        parser.add_argument("--allow-html", action="store_true")
        parser.add_argument("--gc-media", action="store_true")
        parser.add_argument("--set-policy", action="store_true")

    def handle(self, *args, **o):
        try:
            self._run(o)
        except LoaderError as e:
            raise CommandError(str(e)) from e

    def _run(self, o):
        json_dir = Path(o["json_dir"])
        part_dir = json_dir / o["part"]
        manifest = json.loads((part_dir / "manifest.json").read_text("utf-8"))

        course = resolve_course(o["course"])
        ensure_depth_policy(course, o["set_policy"])
        assert_no_foreign_top_level(course, owned_part_orders(json_dir))

        missing = []  # (unit_title, kind, media_src) for skipped absent-source media
        with transaction.atomic():
            part = upsert_node(
                course,
                None,
                manifest["part"]["order"],
                "part",
                manifest["part"]["title"],
            )
            for ch in manifest["chapters"]:
                chapter = upsert_node(course, part, ch["order"], "chapter", ch["title"])
                for u in ch["units"]:
                    unit = upsert_node(
                        course,
                        chapter,
                        u["order"],
                        "unit",
                        u["title"],
                        unit_type=u["unit_type"],
                    )
                    payload = json.loads((part_dir / u["unit_json"]).read_text("utf-8"))
                    assert_iframe_hosts_allowlisted(payload["elements"])
                    rebuild_unit_elements(
                        course,
                        unit,
                        payload["elements"],
                        source_root=o["source_root"],
                        source_dir=u["source_dir"],
                        allow_html=o["allow_html"],
                        missing=missing,
                    )
                prune_orphans(course, chapter, len(ch["units"]))
            prune_orphans(course, part, len(manifest["chapters"]))

        if o["gc_media"]:
            self._gc_media(course)
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"skipped {len(missing)} element(s) with missing source media:"
                )
            )
            for title, kind, src in missing:
                self.stdout.write(f"  - [{kind}] {src}  (unit: {title})")
        self.stdout.write(
            self.style.SUCCESS(f"loaded part {o['part']} into course {course.slug}")
        )

    def _gc_media(self, course):
        from courses.models import ImageElement
        from courses.models import VideoElement

        used = set(
            ImageElement.objects.filter(media__course=course).values_list(
                "media_id", flat=True
            )
        )
        used |= set(
            VideoElement.objects.filter(
                media__isnull=False, media__course=course
            ).values_list("media_id", flat=True)
        )
        orphans = MediaAsset.objects.filter(course=course).exclude(pk__in=used)
        count = orphans.count()
        orphans.delete()
        self.stdout.write(f"gc-media: deleted {count} unreferenced assets")
