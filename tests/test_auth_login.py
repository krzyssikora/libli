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
    assert b"<main>" in response.content
    assert (
        b"Sign In" in response.content
    )  # allauth's login content rendered inside our layout


def test_home_requires_login(client):
    response = client.get("/home/")
    # @login_required redirects anonymous users to the allauth login URL.
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
