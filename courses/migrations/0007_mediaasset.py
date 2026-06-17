import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0006_alter_imageelement_image_alter_videoelement_file"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("image", "Image"), ("video", "Video")], max_length=10)),
                ("file", models.FileField(upload_to="courses/media/")),
                ("original_filename", models.CharField(max_length=255)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="media_assets", to="courses.course")),
                ("uploaded_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL)),
            ],
        ),
        # NULLABLE media FKs added now; data migration (0008) populates + tightens to non-null.
        migrations.AddField(
            model_name="imageelement",
            name="media",
            field=models.ForeignKey(null=True, limit_choices_to={"kind": "image"},
                on_delete=django.db.models.deletion.PROTECT, to="courses.mediaasset"),
        ),
        migrations.AddField(
            model_name="videoelement",
            name="media",
            field=models.ForeignKey(null=True, blank=True, limit_choices_to={"kind": "video"},
                on_delete=django.db.models.deletion.PROTECT, to="courses.mediaasset"),
        ),
        # NOTE: the old image/file columns are deliberately RETAINED here — 0008 reads
        # them, then removes them. Do NOT add RemoveField for image/file in 0007.
    ]
