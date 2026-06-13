from institution.models import Institution
from tests.factories import TEST_PASSWORD


def _set_policy(policy):
    inst = Institution.load()
    inst.signup_policy = policy
    inst.save()


def test_signup_open_when_policy_open(client):
    _set_policy("open")
    response = client.get("/accounts/signup/")
    assert response.status_code == 200
    assert (
        b'name="phone_number"' in response.content
    )  # honeypot input is rendered on the open form


def test_signup_closed_when_policy_invite(client):
    from accounts.models import User

    _set_policy("invite")
    # GET shows allauth's default account/signup_closed.html (an allauth-provided
    # template, rendered at 200) instead of the form. Discriminate on the absence
    # of the signup form's username input rather than the honeypot field name.
    get_response = client.get("/accounts/signup/")
    assert get_response.status_code == 200
    assert (
        b'name="username"' not in get_response.content
    )  # the signup form is not rendered
    # POST must not create an account.
    client.post(
        "/accounts/signup/",
        {
            "username": "sneaky",
            "email": "s@x.edu",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert not User.objects.filter(username="sneaky").exists()


def test_signup_adds_user_to_student_group(client):
    from accounts.models import User

    _set_policy("open")
    response = client.post(
        "/accounts/signup/",
        {
            "username": "newbie",
            "email": "newbie@school.edu",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    # A successful signup redirects (to the verification-sent page under mandatory
    # verification); asserting 302 makes a rejected form fail at the POST, not the
    # ORM lookup.
    assert response.status_code == 302
    user = User.objects.get(username="newbie")
    assert user.groups.filter(name="Student").exists()
