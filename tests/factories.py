import factory

from accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    display_name = factory.Faker("name")
    password = factory.PostGenerationMethodCall("set_password", "password123")
