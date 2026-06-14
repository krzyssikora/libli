from accounts.provisioning import Decision
from accounts.provisioning import email_domain
from accounts.provisioning import evaluate_sso_provisioning


class _Inv:
    """Stand-in for an Invitation (the decision fn treats it as already-valid)."""


def _eval(email, policy, domains, invitation=None):
    return evaluate_sso_provisioning(
        email,
        signup_policy=policy,
        allowed_email_domains=domains,
        invitation=invitation,
    )


def test_email_domain_extraction_lowercases():
    assert email_domain("Alice@Example.COM") == "example.com"
    assert email_domain("no-at-sign") == ""


def test_pre_invited_overrides_policy_and_domain():
    inv = _Inv()
    d = _eval("x@other.org", "invite", ["school.edu"], invitation=inv)
    assert d.allow and d.invitation_to_consume is inv


def test_open_policy_empty_domains_allows_any():
    d = _eval("anyone@anywhere.io", "open", [])
    assert d.allow and d.invitation_to_consume is None


def test_open_policy_matching_domain_allows():
    assert _eval("kid@school.edu", "open", ["school.edu"]).allow


def test_open_policy_nonmatching_domain_denies():
    d = _eval("kid@gmail.com", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_invite_policy_without_invite_denies():
    d = _eval("kid@school.edu", "invite", [])
    assert not d.allow and d.reason == "policy"


def test_domain_match_normalizes_stored_entries():
    # Stored entries may be messy: leading @, mixed case, surrounding spaces.
    assert _eval("kid@school.edu", "open", [" School.EDU "]).allow
    assert _eval("kid@school.edu", "open", ["@school.edu"]).allow


def test_domain_match_is_exact_not_subdomain():
    d = _eval("kid@sub.school.edu", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_no_at_email_denied_only_in_domain_branch():
    # With a domain allowlist a no-@ email is denied...
    assert not _eval("garbage", "open", ["school.edu"]).allow
    # ...but with no allowlist, open policy admits it (deny lives in the domain branch).
    assert _eval("garbage", "open", []).allow


def test_decision_is_a_dataclass_with_defaults():
    d = Decision(allow=True)
    assert d.reason == "" and d.invitation_to_consume is None
