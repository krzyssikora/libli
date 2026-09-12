"""Issue and retire school demo kits.

The subcommand shape mirrors migrate_course_content: a positional `action` with
`choices`, dispatched in handle(). `create` and `extend` are vendor-guarded;
`purge`, `revoke` and `list` are NOT (spec R8) — guarding a cleanup path is the
one way the guard could leave stranger-known logins alive on prod.
"""

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from courses.models import Course
from demo import errors
from demo.constants import DEFAULT_DAYS
from demo.constants import DEFAULT_PUPILS
from demo.constants import LONG_LIVED_DAYS
from demo.models import DemoKit
from demo.services import extend_kit
from demo.services import provision_kit
from demo.services import purge_expired
from demo.services import revoke_kit


class Command(BaseCommand):
    help = "Create, list, extend, revoke and purge school demo kits."

    def add_arguments(self, parser):
        parser.add_argument(
            "action", choices=("create", "list", "extend", "revoke", "purge")
        )
        parser.add_argument("kit_id", nargs="?", type=int)
        parser.add_argument("--label")
        parser.add_argument("--course", help="course slug (required for create)")
        parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
        parser.add_argument("--pupils", type=int, default=DEFAULT_PUPILS)
        parser.add_argument("--frontier-part", type=int, default=None)
        parser.add_argument("--seed", type=int, default=None)
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        try:
            getattr(self, f"_{o['action']}")(o)
        # NAMED exceptions only. A blanket `except Exception` swallowed every
        # AttributeError, TypeError and IntegrityError from the services into a
        # CommandError with no traceback — the worst possible surface for
        # debugging a failed provision on prod, and it made the DemoKitError
        # clause above dead code.
        except (errors.DemoKitError, ImproperlyConfigured) as exc:
            raise CommandError(str(exc)) from exc

    def _kit(self, o):
        kit = DemoKit.objects.filter(pk=o["kit_id"]).first()
        if kit is None:
            raise errors.KitNotFound(f"no demo kit with id {o['kit_id']}")
        return kit

    def _create(self, o):
        # Both flags, symmetrically. Without the label check, omitting --label
        # surfaces as provision_kit's "label must be non-blank…", which never
        # names the flag the operator actually forgot.
        if not o["label"]:
            raise errors.DemoKitError('--label "<school>" is required')
        if not o["course"]:
            raise errors.DemoKitError("--course <slug> is required")
        course = Course.objects.filter(slug=o["course"]).first()
        if course is None:
            raise errors.DemoKitError(f"no course with slug {o['course']!r}")
        result = provision_kit(
            o["label"],
            course=course,
            days=o["days"],
            pupils=o["pupils"],
            frontier_part=o["frontier_part"],
            seed=o["seed"],
        )
        kit = result.kit
        self.stdout.write(self.style.SUCCESS(f"Demo kit #{kit.pk} for {kit.label}"))
        self.stdout.write(
            f"  teacher: {kit.teacher.username}  {result.teacher_password}"
        )
        self.stdout.write(
            f"  pupil:   {kit.student.username}  {result.student_password}"
        )
        self.stdout.write(f"  expires: {kit.expires_at:%Y-%m-%d %H:%M} UTC")
        self.stdout.write("  (the passwords are not stored; copy them now)")
        self._print_warnings(result.warnings)

    # Warnings are PER QUESTION and PER VARIANT over a whole course. On mat-pp —
    # hundreds of published quizzes — printing one line each buries the two lines
    # that matter (the passwords) and the one that is a data-protection signal
    # (active_webhook_endpoint) under thousands of lines of noise. Group them.
    # The full list stays on ProvisionResult.warnings for PR 3's tab.
    WARNING_SAMPLES = 3

    def _print_warnings(self, warnings):
        if not warnings:
            return
        by_kind = {}
        for warning in warnings:
            by_kind.setdefault(warning.kind, []).append(warning)
        self.stdout.write(self.style.WARNING(f"  {len(warnings)} warning(s):"))
        for kind in sorted(by_kind):
            group = by_kind[kind]
            self.stdout.write(self.style.WARNING(f"  ! {kind} x{len(group)}"))
            for warning in group[: self.WARNING_SAMPLES]:
                # `is not None`, not truthiness — the same falsy-zero rule this
                # plan applies to frontier_part and unit_count. Real pks are
                # never 0, so this is consistency rather than a live bug.
                where = (
                    f"unit {warning.unit_id}" if warning.unit_id is not None else "kit"
                )
                self.stdout.write(f"      {where}: {warning.reason}")
            if len(group) > self.WARNING_SAMPLES:
                self.stdout.write(
                    f"      ... and {len(group) - self.WARNING_SAMPLES} more"
                )

    def _list(self, o):
        kits = DemoKit.objects.all()
        if not o["all"]:
            kits = kits.filter(closed_at__isnull=True)
        for kit in kits:
            teacher = kit.teacher.username if kit.teacher else "-"
            # course_slug, not kit.course.slug — `course` is SET_NULL and a kit
            # can outlive its course, which would be an AttributeError here.
            self.stdout.write(
                f"#{kit.pk}\t{kit.label}\t{kit.course_slug}\t{kit.pupil_count}\t"
                f"{teacher}\t{kit.created_at:%Y-%m-%d}\t{kit.expires_at:%Y-%m-%d}\t"
                f"{kit.status_key}"
            )

    def _extend(self, o):
        result = extend_kit(self._kit(o), days=o["days"])
        self.stdout.write(
            f"#{result.kit.pk} now expires {result.new_expires_at:%Y-%m-%d}"
        )
        if result.long_lived:
            # The CONSTANT, not a literal 60 — same rule as LABEL_MAX above.
            self.stdout.write(
                self.style.WARNING(
                    f"  ! this kit has been alive for over {LONG_LIVED_DAYS} days"
                )
            )

    def _revoke(self, o):
        kit = self._kit(o)
        revoke_kit(kit)
        self.stdout.write(f"#{kit.pk} revoked")

    def _purge(self, o):
        verb = "would purge" if o["dry_run"] else "purged"
        try:
            due = purge_expired(dry_run=o["dry_run"])
        except errors.PurgeFailed as exc:
            # Report what DID close before the non-zero exit — handle() turns
            # this into a CommandError, and the cron log is the only place
            # anyone will see either half.
            for kit in exc.purged:
                self.stdout.write(f"{verb} #{kit.pk} {kit.label}")
            raise
        for kit in due:
            self.stdout.write(f"{verb} #{kit.pk} {kit.label}")
        self.stdout.write(f"{verb} {len(due)} kit(s)")
