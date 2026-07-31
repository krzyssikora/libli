"""Restore the colour the LAL import dropped, matching on content, never on identity.

Dry-run by default. Run this LOCALLY, before the mat-pp -> prod export, so colour
ships inside the export bundle with no prod-side migration.

Take a dumpdata of the affected models before --apply: a transaction protects
against a PARTIAL write, not against a WRONG one.
"""

from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.guards import resolve_course
from courses.recolour.dbscan import MultiOwnerError
from courses.recolour.dbscan import ReadBackError
from courses.recolour.dbscan import apply_matches
from courses.recolour.dbscan import excluded_node_ids
from courses.recolour.dbscan import find_matches
from courses.recolour.source import NOT_UNIT_JSON
from courses.recolour.source import build_key_map
from courses.recolour.source import walk_source

GATE_MIN_RATE = 0.70
# How many matches the dry run lists before truncating. The listing exists to
# discharge spec safety property 3; the cap keeps a 270-match run readable.
MATCH_PREVIEW = 40


class Command(BaseCommand):
    help = "Restore imported text colour in a course (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--course", required=True)
        parser.add_argument("--json-dir", default="scripts/lal_import/out")
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="DIRNAME=PK",
            help=(
                "Exclude a part on BOTH sides: the out/ directory is not read and "
                "the paired node's subtree is filtered out of the candidates. "
                "Repeatable. An empty pk (DIRNAME=) excludes source-side only."
            ),
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--list-matches",
            action="store_true",
            help=(
                "List every matched field instead of the first "
                f"{MATCH_PREVIEW}. Use this to check for an ACCIDENTAL match: "
                "content-based matching (D6) will recolour author-written text "
                "that happens to be byte-identical to an imported key."
            ),
        )

    def handle(self, *args, **o):
        try:
            self._run(o)
        except (LoaderError, MultiOwnerError, ReadBackError) as e:
            raise CommandError(str(e)) from e

    # -- validation ---------------------------------------------------------

    def _validate_json_dir(self, json_dir):
        """Fail on a wrong --json-dir BEFORE any key work.

        Without this, a mistyped path yields zero occurrences, `producers == 0`, and
        the gate reports "key construction is broken" -- a confidently wrong
        diagnosis of an operator typo, which is exactly the misattribution this
        command works elsewhere to prevent.
        """
        root = Path(json_dir)
        if not root.is_dir():
            raise CommandError(f"--json-dir {json_dir!r} is not a directory")
        if not any(jf.name not in NOT_UNIT_JSON for jf in root.glob("*/*.json")):
            raise CommandError(
                f"--json-dir {json_dir!r} contains no <part>/<unit>.json files; "
                "this is a wrong path, not an empty corpus"
            )

    def _parse_exclusions(self, course, json_dir, raw_pairs):
        """([dirname], [node pk], [dirname reported as source-side only])."""
        from courses.models import ContentNode

        dirnames, pks, source_only = [], [], []
        for pair in raw_pairs:
            if "=" not in pair:
                raise CommandError(
                    f"--exclude {pair!r} must be given as dirname=pk (the pairing is "
                    "stated by the operator, never inferred)"
                )
            dirname, _sep, pk_text = pair.partition("=")
            dirname = dirname.strip()
            pk_text = pk_text.strip()
            if not (Path(json_dir) / dirname).is_dir():
                raise CommandError(
                    f"--exclude {pair!r}: no such part directory under {json_dir} "
                    "(a typo here silently disables the exclusion)"
                )
            dirnames.append(dirname)
            if not pk_text:
                source_only.append(dirname)
                continue
            try:
                pk = int(pk_text)
            except ValueError as e:
                raise CommandError(f"--exclude {pair!r}: pk must be an integer") from e
            node = ContentNode.objects.filter(pk=pk).first()
            if node is None:
                raise CommandError(f"--exclude {pair!r}: no ContentNode with pk {pk}")
            if node.course_id != course.pk:
                raise CommandError(
                    f"--exclude {pair!r}: node {pk} does not belong to course "
                    f"{course.slug!r}"
                )
            pks.append(pk)
        return dirnames, pks, source_only

    # -- run ----------------------------------------------------------------

    def _run(self, o):
        course = resolve_course(o["course"])
        json_dir = o["json_dir"]
        self._validate_json_dir(json_dir)
        dirnames, pks, source_only = self._parse_exclusions(
            course, json_dir, o["exclude"]
        )

        occurrences = walk_source(json_dir, excluded_dirs=dirnames)
        km = build_key_map(occurrences)
        excluded = excluded_node_ids(course, pks)
        matches = find_matches(course, km.entries, excluded)

        numerator, per_part = self._score(km, matches)
        self._report(o, km, matches, numerator, per_part, source_only)

        if numerator == 0 and self._already_applied(course, km, excluded):
            self.stdout.write(
                self.style.SUCCESS(
                    "already applied — every value is present in the database and no "
                    "key matches. Nothing to do."
                )
            )
            return

        self._check_gate(km, numerator, per_part)

        if not o["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN — nothing was written. Take a dumpdata of the affected "
                    "models, then re-run with --apply."
                )
            )
            return

        with transaction.atomic():
            changed = apply_matches(matches)
        self.stdout.write(self.style.SUCCESS(f"rewrote {changed} field(s)"))

    def _score(self, km, matches):
        """(numerator, per-part counters).

        The numerator counts OCCURRENCES, not distinct keys, and a form appearing in
        two parts must credit both. (Corpus-wide, BEFORE the D7 exclusion, the spec
        measures 257 distinct forms across 306 occurrences; after exclusion this
        command actually operates on 227 distinct keys across 265 occurrences, which
        is what its own report prints.) `km.produced` already excludes
        every occurrence whose value equalled its key, so the spec's `value != key`
        precondition is enforced here by construction -- which is what stops a
        span-only colouriser from scoring ~100% while delivering nothing.
        """
        matched_keys = {m.key for m in matches}
        per_part = defaultdict(
            lambda: {"producers": 0, "matched": 0, "emitted": 0, "rewritten": 0}
        )
        for part, stats in km.per_part.items():
            per_part[part]["producers"] = stats["producers"]
            per_part[part]["emitted"] = stats["emitted"]
        numerator = 0
        for occ, key in km.produced:
            if key in matched_keys:
                numerator += 1
                per_part[occ.part]["matched"] += 1
        # The spec asks for per-part REWRITTEN counts, and `matched` is not that: it
        # counts source occurrences, while a rewrite is one (model, pk, field). One
        # key can match several DB fields and one field can hold several matching
        # cells, so the two numbers legitimately differ.
        fields_by_key = defaultdict(set)
        for m in matches:
            fields_by_key[m.key].add((m.model.__name__, m.pk, m.field))
        # A key occurring in two source parts credits the same (model, pk, field) to
        # BOTH, so this column is "fields reachable from this part" and its sum can
        # exceed the reported total. On the measured run the two agree exactly (191),
        # which is why the overlap would first surface as an unexplained inconsistency
        # in some future report rather than now. Stated here so it is not a surprise.
        rewritten_by_part = defaultdict(set)
        for occ, key in km.produced:
            rewritten_by_part[occ.part] |= fields_by_key.get(key, set())
        for part, fields in rewritten_by_part.items():
            per_part[part]["rewritten"] = len(fields)
        return numerator, per_part

    def _already_applied(self, course, km, excluded):
        """True when the coloured VALUES are already in the database, at the same
        rate the gate demands of the keys.

        Without this the second run of an applied backfill halts on the gate, which
        reads as an error when it is in fact the intended no-op. But "at least one
        value is present" is too weak a predicate: after a hand-edit sweep that left
        one previously-applied value intact and destroyed every other match, it would
        report a clean no-op instead of halting. So the threshold reuses
        GATE_MIN_RATE, which a single survivor cannot satisfy.

        NOT symmetric with the gate, and the difference is worth stating: the gate's
        rate is matched OCCURRENCES over palette-bearing occurrences, while this one
        is distinct VALUES found over distinct values. On this corpus 227 distinct
        keys back 265 occurrences, so the denominators genuinely differ. The shared
        constant is a deliberate reuse of one threshold, not a claim that the two
        ratios measure the same thing.
        """
        if not km.entries:
            return False
        as_keys = {v: v for v in km.entries.values()}
        found = {m.key for m in find_matches(course, as_keys, excluded)}
        rate = len(found) / len(as_keys)
        self.stdout.write(
            f"values already present in the DB: {len(found)}/{len(as_keys)} "
            f"({rate:.1%})"
        )
        return rate >= GATE_MIN_RATE

    def _check_gate(self, km, numerator, per_part):
        if km.producers == 0:
            raise CommandError(
                "the source produced ZERO keys — key construction is broken, not the "
                "corpus. Halting."
            )
        rate = numerator / km.producers
        zero_parts = [
            p
            for p, s in sorted(per_part.items())
            if s["producers"] and not s["matched"]
        ]
        problems = []
        if rate < GATE_MIN_RATE:
            problems.append(
                f"match rate {rate:.1%} is below the {GATE_MIN_RATE:.0%} gate"
            )
        if zero_parts:
            problems.append(
                "these parts produced keys but matched ZERO: " + ", ".join(zero_parts)
            )
        if problems:
            raise CommandError(
                "acceptance gate NOT met, halting without writing:\n  - "
                + "\n  - ".join(problems)
                + "\nA zero-matching part almost always means key construction is "
                "wrong for a field type; a broad shortfall means edits are more "
                "widespread than assumed."
            )

    # -- report -------------------------------------------------------------

    def _report(self, o, km, matches, numerator, per_part, source_only):
        w = self.stdout.write
        list_matches = o["list_matches"]
        w(f"course:        {o['course']}")
        w(f"json-dir:      {o['json_dir']}")
        for dirname in source_only:
            w(f"exclusion:     {dirname} — source-side only (no DB node paired)")
        w("")
        w(f"palette occurrences (denom):  {km.producers}")
        # NOT "produced a key": an occurrence skipped as value-equals-key DID produce
        # one and is excluded here, as is a conflict-retracted one. This counts what
        # entered the map and is therefore eligible for the numerator.
        w(f"  ...entering the key map:    {len(km.produced)}")
        w(f"distinct keys:                {len(km.entries)}")
        w(f"tc-* classes (distinct keys): {km.emitted}")
        w(f"tc-* classes (occurrences):   {km.emitted_occurrences}")
        w(f"matched occurrences:          {numerator}")
        if km.producers:
            w(
                f"match rate:                   {numerator / km.producers:.1%} "
                f"(gate: >= {GATE_MIN_RATE:.0%})"
            )
        fields = {(m.model, m.pk, m.field) for m in matches}
        w(f"fields that would change:     {len(fields)}")
        w("")
        # Spec safety property 3 assigns the dry run a JOB: author-written content that
        # happens to be byte-identical to a key WILL be recoloured, because matching is
        # content-based by design (D6), and "the dry-run report is where an operator
        # spots it". A report of counts alone cannot discharge that -- nothing in it
        # names a row or shows the text -- so every match is listed, capped unless
        # --list-matches is passed.
        w("matches:")
        shown = sorted(matches, key=lambda m: (m.model.__name__, m.pk, m.field))
        cap = len(shown) if list_matches else MATCH_PREVIEW
        for m in shown[:cap]:
            cell = "" if m.cell is None else f"[{m.cell[0]}][{m.cell[1]}]"
            excerpt = m.key[:70].replace("\n", " ")
            w(f"  {m.model.__name__}({m.pk}).{m.field}{cell}  <- {excerpt!r}")
        if len(shown) > cap:
            w(f"  ... and {len(shown) - cap} more; pass --list-matches for all")
        w("")
        w("per part:")
        # 'occ' not 'keys': this column is per-part OCCURRENCES (km.producers), which
        # sums to the denominator, NOT to the distinct-key total printed above.
        w(f"  {'part':38s} {'occ':>6s} {'matched':>8s} {'fields':>7s} {'tc-*':>6s}")
        for part, s in sorted(per_part.items()):
            flag = "   <== ZERO" if s["producers"] and not s["matched"] else ""
            w(
                f"  {part:38s} {s['producers']:6d} {s['matched']:8d} "
                f"{s['rewritten']:7d} {s['emitted']:6d}{flag}"
            )
        w("")
        # The spec asks for per-part skip counts; this is a global histogram plus a
        # sample of the first ten, and the divergence is deliberate: the measured skip
        # count on the real corpus is ZERO, so a per-part breakdown would be an empty
        # column on every row. Each skip line names its part, so the information is
        # recoverable if a run ever produces one. Revisit if skips stop being rare.
        reasons = defaultdict(int)
        for _occ, reason in km.skips:
            reasons[reason.split(":")[0]] += 1
        if reasons:
            w("skipped:")
            for reason, n in sorted(reasons.items()):
                w(f"  {reason:24s} {n}")
            for occ, reason in km.skips[:10]:
                name = Path(occ.json_file).name
                w(f"    {occ.part}/{name} {occ.field_path} — {reason}")
        w("")
