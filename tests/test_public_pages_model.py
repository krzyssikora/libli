import pytest

from institution.models import Institution
from institution.models import PublicPage


@pytest.mark.django_db
def test_save_normalises_a_regional_language_code():
    # The Django admin is a second sanctioned write path, so the invariant must
    # live in save(), not only in the settings panel.
    row = PublicPage.objects.create(slug="privacy", language="pl-PL", body_markdown="x")
    row.refresh_from_db()
    assert row.language == "pl"


@pytest.mark.django_db
def test_str_and_ordering():
    PublicPage.objects.create(slug="privacy", language="pl", body_markdown="x")
    PublicPage.objects.create(slug="getting-started", language="en", body_markdown="y")
    assert [str(r) for r in PublicPage.objects.all()] == [
        "getting-started [en]",
        "privacy [pl]",
    ]


@pytest.mark.django_db
def test_slug_language_is_unique():
    from django.db import transaction
    from django.db.utils import IntegrityError

    PublicPage.objects.create(slug="privacy", language="en", body_markdown="a")
    # transaction.atomic is the standard idiom: without it the IntegrityError
    # leaves the test's outer atomic block needing rollback, and any assertion
    # added after this raises TransactionManagementError.
    with pytest.raises(IntegrityError), transaction.atomic():
        PublicPage.objects.create(slug="privacy", language="en", body_markdown="b")


@pytest.mark.django_db
def test_new_institution_fields_default_blank_and_false():
    inst = Institution.load()
    assert inst.controller_name == ""
    assert inst.controller_address == ""
    assert inst.contact_email == ""
    assert inst.supervisory_authority == ""
    assert inst.demo_instance is False
