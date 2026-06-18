from tests.factories import TEST_PASSWORD


def test_login_page_renders(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    # <main> comes from templates/base.html's body (Step 3), which allauth pages
    # reach ONLY through the allauth/layouts/base.html override (Step 4) — so its
    # presence proves our layout actually wrapped the allauth page. (Validated
    # against allauth 65.18.x, which Task 1 resolves under ">=65.0,<66.0":
    # entrance.html/manage.html both extend allauth/layouts/base.html, so the single
    # override covers every page.) We do NOT assert <title>libli</title> here:
    # account/login.html overrides {% block head_title %} to "Sign In", so the libli
    # default title only appears on pages that don't override it (e.g. our home page).
    assert b'<main class="auth-main">' in response.content
    assert (
        b"Sign In" in response.content
    )  # allauth's login content rendered inside our layout


def test_home_requires_login(client):
    response = client.get("/home/")
    # @login_required redirects anonymous users to the allauth login URL.
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_login_with_username(client):
    # A user with a verified email logs in via their USERNAME identifier (proves the
    # username login method). 0b uses email-bearing verified users for login tests;
    # emailless front-door login is deferred — see verification note in Task 5 Step 3.
    from tests.factories import make_verified_user

    make_verified_user(username="member", email="member@school.edu")
    response = client.post(
        "/accounts/login/", {"login": "member", "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")
    assert client.session.get("_auth_user_id")  # session is authenticated


def test_login_with_email(client):
    from tests.factories import make_verified_user

    make_verified_user(username="emailer", email="emailer@school.edu")
    response = client.post(
        "/accounts/login/", {"login": "emailer@school.edu", "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")
    assert client.session.get("_auth_user_id")


def test_logout(client):
    from tests.factories import make_verified_user

    make_verified_user(username="member", email="member@school.edu")
    client.post("/accounts/login/", {"login": "member", "password": TEST_PASSWORD})
    assert client.session.get("_auth_user_id")
    # allauth 65.x logs out on POST (a GET shows a confirmation page); assert the
    # response so a future verb change fails loudly instead of leaving the session set.
    logout_response = client.post("/accounts/logout/")
    assert logout_response.status_code in (200, 302)
    assert not client.session.get("_auth_user_id")


def test_password_change_requires_login(client):
    response = client.get("/accounts/password/change/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
