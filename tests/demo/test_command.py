from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_create_prints_both_logins_and_the_expiry_once():
    from tests.demo.fixtures import small_course

    small_course()
    out = StringIO()
    call_command(
        "demo_access",
        "create",
        "--label",
        "SP 12",
        "--course",
        "small",
        "--pupils",
        "5",
        "--seed",
        "1",
        stdout=out,
    )
    printed = out.getvalue()
    assert "sp-12-nauczyciel" in printed and "sp-12-uczen" in printed
    # "once" is in the test's NAME, so assert it: a build that printed the expiry
    # three times would otherwise stay green.
    assert printed.lower().count("expires") == 1


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_list_hides_closed_kits_until_all_and_prints_the_status_key():
    """T26 — list is Risk 5's early warning, and the assertion is on the machine
    key so it cannot follow the process locale."""
    from demo.services import revoke_kit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    live = provision_for_test(course, label="Live")
    dead = provision_for_test(course, label="Dead")
    revoke_kit(dead)

    out = StringIO()
    call_command("demo_access", "list", stdout=out)
    assert "Live" in out.getvalue() and "Dead" not in out.getvalue()
    assert "active" in out.getvalue()

    out_all = StringIO()
    call_command("demo_access", "list", "--all", stdout=out_all)
    assert "closed_revoked" in out_all.getvalue()
    assert live.teacher.username in out.getvalue()


@pytest.mark.django_db
def test_the_guarded_and_exempt_subcommands_are_split_as_specified():
    """T13 — enumerated FROM THE PARSER, never listed by hand and never pinned
    by count. A guard on `create` alone would keep a hand-written version green
    while `purge` refused to run on prod."""
    from demo.management.commands.demo_access import Command
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    parser = Command().create_parser("manage.py", "demo_access")
    actions = {
        choice
        for action in parser._actions
        if action.dest == "action"
        for choice in action.choices
    }
    guarded, exempt = {"create", "extend"}, {"purge", "revoke", "list"}
    assert actions == guarded | exempt

    # ⚠️ EVERY ARGUMENT MUST BE VALID, or the guard is never reached.
    # The earlier version of this test built no fixture and passed no kit id, so
    # `create` died on "no course with slug 'small'" and `extend` on KitNotFound
    # — both BEFORE the service was called. Both pytest.raises(CommandError)
    # assertions were green on a build with no vendor guard at all.
    course = small_course()
    kit = provision_for_test(course)  # provisions with the flag ON, then drops it

    for name, args in (
        ("create", ("--label", "SP 99", "--course", "small", "--pupils", "5")),
        ("extend", (str(kit.pk), "--days", "7")),
    ):
        with pytest.raises(CommandError) as exc:
            call_command("demo_access", name, *args)
        # The MESSAGE, not merely the class: it is what distinguishes the guard
        # from every other way these subcommands can fail.
        assert "LIBLI_VENDOR_INSTANCE" in str(exc.value), name

    call_command("demo_access", "purge", "--dry-run")  # must NOT raise
    call_command("demo_access", "list")
    call_command("demo_access", "revoke", str(kit.pk))  # exempt, and must work


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_missing_kit_id_is_a_clean_error():
    with pytest.raises(CommandError):
        call_command("demo_access", "revoke", "9999")


def test_the_warning_block_is_bounded_however_many_warnings_there_are():
    # No django_db: this builds DemoWarnings and a Command, and queries nothing.
    """The passwords are the two lines the operator needs. Warnings are emitted
    PER QUESTION and PER VARIANT, so on mat-pp an ungrouped list runs to
    thousands of lines and buries them. Grouping is what keeps the block
    readable; this pins it against a course of any size."""
    from demo.management.commands.demo_access import Command
    from demo.warnings import DemoWarning

    out = StringIO()
    # ⚠️ `Command(stdout=out)`, NOT `Command()` then `command.stdout = out`.
    # BaseCommand.__init__ wraps stdout in an OutputWrapper whose write() appends
    # the missing newline; assigning a bare StringIO over it removes that, so
    # every write concatenates, `splitlines()` returns ONE line, and the
    # line-count assertion below is green on any implementation — including the
    # 501-ungrouped-lines one this test exists to reject.
    command = Command(stdout=out)
    command._print_warnings(
        [DemoWarning("variant_dropped", n, str(n)) for n in range(1, 501)]
        + [DemoWarning("active_webhook_endpoint", None, "https://sis.example/hook")]
    )
    printed = out.getvalue()

    assert len(printed.splitlines()) < 20, "the block must not scale with the course"
    assert "variant_dropped x500" in printed  # the count survives grouping
    assert "https://sis.example/hook" in printed, (
        "the data-protection warning must never be the one summarised away"
    )


@pytest.mark.django_db
def test_a_failing_purge_reports_the_survivors_and_still_exits_non_zero(monkeypatch):
    """The COMMAND half of C4. Task 11 Step 5's third mutant covers the service
    (purge_expired attempts every kit, then re-raises); this covers what the cron
    log actually shows — the kits that DID close, printed before the non-zero
    exit — and that handle() turns PurgeFailed into a CommandError."""
    from datetime import timedelta

    from django.utils import timezone

    from demo import services
    from demo.models import DemoKit
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    doomed = provision_for_test(course, label="Doomed")
    survivor = provision_for_test(course, label="Survivor")
    DemoKit.objects.filter(pk__in=[doomed.pk, survivor.pk]).update(
        expires_at=timezone.now() - timedelta(days=1)
    )

    real_purge = services.purge_kit
    monkeypatch.setattr(
        services,
        "purge_kit",
        lambda kit, *, reason: (
            (_ for _ in ()).throw(RuntimeError("boom"))
            if kit.pk == doomed.pk
            else real_purge(kit, reason=reason)
        ),
    )

    out = StringIO()
    with pytest.raises(CommandError) as exc:
        call_command("demo_access", "purge", stdout=out)

    assert f"#{survivor.pk}" in out.getvalue(), "the survivor was never reported"
    assert f"#{doomed.pk}" in str(exc.value)
