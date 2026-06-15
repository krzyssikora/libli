from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import Subject
from courses.models import TextElement
from courses.models import VideoElement

User = get_user_model()


class Command(BaseCommand):
    help = "Create (idempotently) a demo course, content tree, and an enrolled student."

    @transaction.atomic
    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(
            slug="demo-subject", defaults={"title": "Demo Subject"}
        )
        course, _ = Course.objects.get_or_create(
            slug="demo-course",
            defaults={"title": "Demo Course", "subject": subject, "language": "en"},
        )
        chapter = self._node(course, None, "chapter", "Chapter 1", None)
        intro = self._node(
            course, chapter, "unit", "Intro lesson", "lesson", obligatory=True
        )
        section = self._node(course, chapter, "section", "Section A", None)
        lesson = self._node(
            course, section, "unit", "Core lesson", "lesson", obligatory=True
        )
        extra = self._node(
            course, section, "unit", "Bonus lesson", "lesson", obligatory=False
        )

        self._text(
            intro, "intro-text", "<h2>Welcome</h2><p>This is the demo course.</p>"
        )
        self._text(lesson, "core-text", "<p>The core lesson body.</p>")
        self._math(lesson, "core-math", "c = \\pm\\sqrt{a^2 + b^2}")
        self._iframe(lesson, "core-iframe", "https://www.geogebra.org/m/abc")
        self._video(lesson, "core-video", "https://www.youtube.com/embed/dummy")
        self._image(extra, "bonus-image", "Decorative diagram")

        student, created = User.objects.get_or_create(
            username="demo_student", defaults={"display_name": "Demo Student"}
        )
        if created:
            student.set_password("demo-pass-123")
            student.save()
        Enrollment.objects.get_or_create(student=student, course=course)
        self.stdout.write(self.style.SUCCESS("Demo course seeded (idempotent)."))

    def _node(self, course, parent, kind, title, unit_type, obligatory=True):
        node, created = ContentNode.objects.get_or_create(
            course=course,
            parent=parent,
            title=title,
            defaults={"kind": kind, "unit_type": unit_type, "obligatory": obligatory},
        )
        return node

    def _text(self, unit, slug, body):
        self._upsert(unit, TextElement, body=body)

    def _math(self, unit, slug, latex):
        self._upsert(unit, MathElement, latex=latex)

    def _iframe(self, unit, slug, url):
        self._upsert(unit, IframeElement, url=url, title=slug)

    def _video(self, unit, slug, url):
        self._upsert(unit, VideoElement, url=url)

    def _image(self, unit, slug, alt):
        self._upsert(unit, ImageElement, alt=alt, image="courses/images/demo.png")

    def _upsert(self, unit, model, **fields):
        """Idempotently ensure `unit` has exactly one element of `model`.

        Reconciliation key = "the join-row from this unit to an instance of this model".
        On rerun we update the existing concrete row instead of creating a duplicate;
        otherwise we create the concrete row and its join-row.
        """
        existing = Element.objects.filter(
            unit=unit, content_type__model=model._meta.model_name
        ).first()
        if existing and isinstance(existing.content_object, model):
            obj = existing.content_object
            for key, value in fields.items():
                setattr(obj, key, value)
            obj.save()
            return
        obj = model(**fields)
        obj.save()
        Element.objects.create(unit=unit, content_object=obj)
