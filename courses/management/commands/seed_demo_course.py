"""Management command: idempotently seed a demo course, tree, and enrolled student."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.emails import ensure_verified_primary_email
from accounts.services import set_user_role
from courses.models import CalloutElement
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import MediaAsset
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import Subject
from courses.models import TableElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.quiz import finalize_submission
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from courses.video_url import canonicalize_video_url
from grouping.models import Group
from grouping.models import GroupMembership
from institution.roles import COURSE_ADMIN
from institution.roles import seed_roles

User = get_user_model()

DEMO_PASSWORD = "demo-pass-123"  # noqa: S105 - single reused demo credential (not a test literal)


class Command(BaseCommand):
    help = "Create (idempotently) a demo course, content tree, and an enrolled student."

    @transaction.atomic
    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(
            slug="demo-subject", defaults={"title_en": "Demo Subject"}
        )
        course, _ = Course.objects.get_or_create(
            slug="demo-course",
            defaults={"title": "Demo Course", "language": "en"},
        )
        course.subjects.add(subject)

        self.course = course
        seed_roles()  # ensure the 4 role auth-groups + perms exist before set_user_role
        teacher = self._user(
            "demo_teacher",
            "Demo Teacher",
            email="demo_teacher@demo.example",
            role=COURSE_ADMIN,
        )
        course.owner = teacher  # builder access requires ownership (can_manage_course)
        course.save(update_fields=["owner"])

        student = self._user(
            "demo_student", "Demo Student", email="demo_student@demo.example"
        )
        s1 = self._user("demo_s1", "Ada Demo", email="demo_s1@demo.example")
        s2 = self._user("demo_s2", "Ben Demo", email="demo_s2@demo.example")
        s3 = self._user("demo_s3", "Cleo Demo", email="demo_s3@demo.example")
        for st in (student, s1, s2, s3):
            Enrollment.objects.get_or_create(student=st, course=course)
        self.teacher = teacher  # consumed by Task 4
        self.group_students = [s1, s2, s3]  # consumed by Task 4

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
        self._iframe(
            lesson,
            "core-iframe",
            "https://www.geogebra.org/material/iframe/id/egZJdjsC",
        )
        self._video(lesson, "core-video", "https://www.youtube.com/watch?v=psMMKgvpGfg")
        self._image(extra, "bonus-image", "Decorative diagram")
        self._callout(lesson)
        self._spoiler(lesson)
        self._table(lesson)

        quiz = self._quiz(chapter)
        self._group(quiz)

        self.stdout.write(self.style.SUCCESS("Demo course seeded (idempotent)."))

    def _user(self, username, display_name, *, email, is_staff=False, role=None):
        user, created = User.objects.get_or_create(
            username=username, defaults={"display_name": display_name}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
        user.theme = "light"
        user.language = "en"
        user.is_staff = is_staff or user.is_staff
        user.save()
        ensure_verified_primary_email(user, email)
        if role is not None:
            set_user_role(user, role)  # sets is_staff + role group idempotently
        return user

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
        # The seed writes VideoElement directly (no form), so canonicalize the
        # pasted watch/link form into a working /embed/ URL here — exactly what
        # the authoring form does — otherwise the stored watch?v= URL would not
        # embed on the consumption page.
        self._upsert(unit, VideoElement, url=canonicalize_video_url(url))

    def _image(self, unit, slug, alt):
        course = unit.course
        # filter().first()+create (not get_or_create): MediaAsset has no uniqueness,
        # so get_or_create could MultipleObjectsReturned on rerun — match _upsert.
        asset = MediaAsset.objects.filter(
            course=course, original_filename="demo.png"
        ).first()
        if asset is None:
            asset = MediaAsset.objects.create(
                course=course,
                kind="image",
                file="courses/images/demo.png",
                original_filename="demo.png",
            )
        self._upsert(unit, ImageElement, media=asset, alt=alt)

    def _callout(self, unit):
        self._upsert(
            unit,
            CalloutElement,
            kind="tip",
            heading="Remember",
            body="<p>Order of operations matters.</p>",
        )

    def _spoiler(self, unit):
        self._upsert(
            unit,
            SpoilerElement,
            label="Show the answer",
            body="<p>42</p>",
        )

    def _table(self, unit):
        self._upsert(
            unit,
            TableElement,
            data=TableElement.normalize_data(
                {
                    "header_row": True,
                    "border": "grid",
                    "cells": [
                        [{"html": "Symbol"}, {"html": "Meaning"}],
                        [{"html": "π"}, {"html": "pi"}],
                    ],
                }
            ),
        )

    def _quiz(self, chapter):
        quiz = self._node(self.course, chapter, "unit", "Demo quiz", "quiz")
        if not quiz.elements.exists():
            short = ShortTextQuestionElement.objects.create(
                stem="What is 2 + 2?",
                accepted="4",
                marking_mode=QuestionElement.MarkingMode.AUTO,
                max_marks=Decimal("1"),
            )
            self.q_short = Element.objects.create(unit=quiz, content_object=short)
            choice = ChoiceQuestionElement.objects.create(
                stem="Which are prime?",
                multiple=True,
                marking_mode=QuestionElement.MarkingMode.AUTO,
                max_marks=Decimal("1"),
            )
            Choice.objects.create(question=choice, text="2", is_correct=True)
            Choice.objects.create(question=choice, text="3", is_correct=True)
            Choice.objects.create(question=choice, text="4", is_correct=False)
            self.q_choice = Element.objects.create(unit=quiz, content_object=choice)
        else:
            self.q_short = quiz.elements.filter(
                content_type__model="shorttextquestionelement"
            ).first()
            self.q_choice = quiz.elements.filter(
                content_type__model="choicequestionelement"
            ).first()
        return quiz

    def _respond(self, submission, element, answer):
        question = element.content_object
        f = to_stored_fraction(question.mark(answer).fraction)
        QuestionResponse.objects.get_or_create(
            submission=submission,
            element=element,
            defaults={
                "fraction": f,
                "earned_marks": earned_marks(f, question.max_marks),
                "latest_answer": sorted(answer) if isinstance(answer, set) else answer,
                "attempt_count": 1,
            },
        )

    def _graded_submission(self, quiz, student, short_answer, choice_answer):
        submission, _ = QuizSubmission.objects.get_or_create(
            student=student,
            unit=quiz,
            defaults={"status": QuizSubmission.Status.IN_PROGRESS},
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return  # already graded on a prior run — idempotent
        self._respond(submission, self.q_short, short_answer)
        correct_ids = set(
            self.q_choice.content_object.choices.filter(is_correct=True).values_list(
                "pk", flat=True
            )
        )
        # choice_answer: "full" -> all correct, "partial" -> one correct only
        picks = correct_ids if choice_answer == "full" else set(list(correct_ids)[:1])
        self._respond(submission, self.q_choice, picks)
        finalize_submission(quiz, submission)  # freezes score/max_score, SUBMITTED

    def _group(self, quiz):
        group, _ = Group.objects.get_or_create(name="Demo Group", course=self.course)
        group.teachers.add(self.teacher)
        for st in self.group_students:
            GroupMembership.objects.get_or_create(group=group, student=st)
        # varied but fixed scores across the three students
        plans = [("4", "full"), ("4", "partial"), ("5", "partial")]
        for st, (short_ans, choice_ans) in zip(self.group_students, plans, strict=True):
            self._graded_submission(quiz, st, short_ans, choice_ans)
        return group

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
