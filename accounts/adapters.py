from allauth.account.adapter import DefaultAccountAdapter

from institution.models import Institution


class AccountAdapter(DefaultAccountAdapter):
    """Gate self-signup on the institution's runtime signup policy (spec §4).

    `open`  -> self-signup enabled (email required + confirmed; honeypot active).
    `invite` (or anything else) -> self-signup disabled; accounts arrive via the
    Django admin (Plan 0a) and, later, invite tokens (Plan 0c).
    """

    def is_open_for_signup(self, request):
        return Institution.load().signup_policy == "open"
