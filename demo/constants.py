"""Every tunable the demo generator has. Named, not inlined: the spec's
determinism rule (R5) is a claim about an exact draw sequence, and a literal
buried in a loop is a number nobody can change safely."""

import string

# --- operator bounds (spec §4.4). The service enforces these, not just the
# command, so PR 3's form inherits them by calling the service. ---
DEFAULT_DAYS = 14
DEFAULT_PUPILS = 20
MIN_DAYS = 1
MAX_DAYS = 90
# MIN_PUPILS is 5, not 2: the band partition is `pupils * 20 // 100`, which is
# ZERO for 2-4 pupils, making the whole class one band.
MIN_PUPILS = 5
# ⚠️ MAX_PUPILS is bounded by the NAME POOLS, which hold exactly 40 entries each
# (MIN_NAMES_PER_LIST below). Raising it without extending demo/names.py makes
# every provisioning at the new ceiling raise NamePoolExhausted — after the kit,
# group, teacher and student rows have been written.
# tests/demo/test_names.py::test_the_pools_cover_the_maximum_class pins the pair.
MAX_PUPILS = 40
LABEL_MAX = 200
LONG_LIVED_DAYS = 60  # extend_kit flags a kit alive longer than this

# --- identifiers (spec §4.2) ---
SLUG_MAX = 100  # leaves room for "-NNN-nauczyciel" inside username's 150
SLUG_FALLBACK = "demo"  # a label that slugifies to "" (pure punctuation, CJK)
MAX_DISAMBIGUATOR = 999
EMAIL_DOMAIN = "demo.invalid"

# --- credentials (spec §4.6) ---
PASSWORD_LENGTH = 14
# 56 symbols: letters+digits minus the visually ambiguous ones. ~81 bits.
PASSWORD_ALPHABET = "".join(
    c for c in (string.ascii_letters + string.digits) if c not in "Oo0Il1"
)

# --- the class (spec §4.5) ---
FRONTIER_FRACTION = 0.75
STRONG_PCT = 20
STRUGGLING_PCT = 20
JITTER = 0.08
IN_PROGRESS_PUPILS = 2
P_PARTIAL_GIVEN_WRONG = 0.4
WRONG_VARIANTS = 3
NAME_RETRY_LIMIT = 50
MIN_NAMES_PER_LIST = 40

# band -> {"p_correct", "depth" (a multiplier), "p_lesson", "p_optional"}.
# The class SHARES are not in here: they are STRONG_PCT / STRUGGLING_PCT above,
# because assign_bands partitions on integers while these four are probabilities.
STRONG = "strong"
AVERAGE = "average"
STRUGGLING = "struggling"
BANDS = {
    STRONG: {"p_correct": 0.90, "depth": 1.15, "p_lesson": 1.00, "p_optional": 0.50},
    AVERAGE: {"p_correct": 0.65, "depth": 1.00, "p_lesson": 0.95, "p_optional": 0.30},
    STRUGGLING: {
        "p_correct": 0.35,
        "depth": 0.70,
        "p_lesson": 0.80,
        "p_optional": 0.15,
    },
}

# Fixed nonsense strings for text-shaped wrong answers. Three, so a question can
# offer three distinct wrong variants (spec §3.1).
WRONG_TEXTS = ("nieprawidlowa-1", "nieprawidlowa-2", "nieprawidlowa-3")
