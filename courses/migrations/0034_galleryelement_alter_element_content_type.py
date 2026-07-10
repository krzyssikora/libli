import django.db.models.deletion
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("courses", "0033_tableelement_alter_element_content_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="GalleryElement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("data", models.JSONField(default=dict)),
            ],
            options={"abstract": False},
        ),
        migrations.AlterField(
            model_name="element",
            name="content_type",
            field=models.ForeignKey(
                limit_choices_to={
                    "app_label": "courses",
                    "model__in": [
                        "textelement",
                        "imageelement",
                        "videoelement",
                        "iframeelement",
                        "mathelement",
                        "htmlelement",
                        "choicequestionelement",
                        "shorttextquestionelement",
                        "extendedresponsequestionelement",
                        "shortnumericquestionelement",
                        "fillblankquestionelement",
                        "dragfillblankquestionelement",
                        "matchpairquestionelement",
                        "dragtoimagequestionelement",
                        "slidebreakelement",
                        "tableelement",
                        "galleryelement",
                    ],
                },
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
    ]
