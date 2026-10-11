"""No print rule may hide a reveal gate.

Owner decision D8 (spec 2026-10-11-print-layout-for-units): gated content prints
exactly as the screen shows it, and an unconsumed gate -- a "Show more" button, a
fill gate's blanks + Confirm, a switch gate's cycler + Confirm, a gated fill-table
-- prints as the marker that more content waits behind it. A consumed gate hides
itself on screen ([hidden] / its own done state), so it is absent on paper too.

The previous rule here (`[data-reveal-gate]:not([data-filltablegate])` hidden in
print, with the gated fill-table carved out because its node IS the student's
work) is gone together with the print reveal it paired with.
"""

from tests.print_css_kit import all_print_css

# Comments are stripped by print_css_kit, so a comment mentioning these tokens
# can neither satisfy nor falsify the assertions; only real rules count.


def test_no_print_rule_mentions_a_reveal_gate():
    for token in ("data-reveal-gate", ".reveal-gate", "fillgate", "switchgate"):
        assert token not in all_print_css(), (
            f"a print rule targets {token!r}; D8 prints gates as on screen"
        )


def test_no_print_rule_reveals_prehidden_blocks():
    assert ".reveal-armed" not in all_print_css(), (
        "a print rule overrides the reveal-armed pre-hide"
    )
