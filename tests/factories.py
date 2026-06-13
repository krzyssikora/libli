import factory

from accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    display_name = factory.Faker("name")
    password = factory.PostGenerationMethodCall("set_password", "password123")


def make_verified_user(
    username="member", email="member@school.edu", password="Sup3r!pass9"
):
    """Create a user with a *verified, primary* allauth EmailAddress so that, under
    mandatory email verification, they can log in via username OR email. allauth
    resolves email-login against the `EmailAddress` table (not `auth_user.email`), so
    this row must exist for email login to succeed."""
    # Local import keeps shared test infra (UserFactory) from importing allauth at
    # module load.
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(username=username, email=email, password=password)
    # create_user does not trigger allauth's EmailAddress sync, so get_or_create simply
    # yields (and then forces verified + primary on) the EmailAddress that email login
    # needs.
    email_address, _ = EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    if not (email_address.verified and email_address.primary):
        email_address.verified = True
        email_address.primary = True
        email_address.save()
    return user
