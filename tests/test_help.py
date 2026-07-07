import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from core import help as core_help
from core.help import ROLE_FOLDER
from core.help import TOPICS
from core.help import get_topic
from core.help import localized_doc_path
from core.help import topics_for
from core.help import user_has_any_help
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import ROLE_LABELS
from institution.roles import TEACHER
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_student
from tests.factories import make_teacher


def test_renders_fenced_code_and_tables(tmp_path, monkeypatch):
    doc = tmp_path / "sample.md"
    doc.write_text(
        "# Title\n\n```python\nx = 1\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    html = core_help.render_markdown_doc("sample.md")
    assert "<pre>" in html and "<code" in html
    assert "<table>" in html and "<th>A</th>" in html


def test_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        core_help.render_markdown_doc("nope.md")


@pytest.mark.django_db
def test_make_ca_holds_ca_marker(client):
    user = make_ca(client)
    assert user.has_perm("grouping.change_group")
    assert not user.has_perm("courses.change_course")  # CA is NOT a PA


@pytest.mark.django_db
def test_make_teacher_holds_teacher_marker(client):
    user = make_teacher(client)
    assert user.has_perm("grouping.view_collection")
    assert not user.has_perm("grouping.change_group")  # Teacher is not a CA


@pytest.mark.django_db
def test_make_student_holds_no_markers(client):
    user = make_student(client)
    assert not user.has_perm("grouping.change_group")
    assert not user.has_perm("grouping.view_collection")
    assert not user.has_perm("accounts.view_user")


def test_slugs_are_globally_unique():
    slugs = [t.slug for t in TOPICS]
    assert len(set(slugs)) == len(slugs)


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_folder_matches_role(topic):
    assert topic.path.startswith(ROLE_FOLDER[topic.role]), topic.slug


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_english_file_exists_and_renders(topic):
    from core import help as core_help

    path = core_help.DOCS_ROOT / topic.path
    assert path.exists(), f"missing EN file for {topic.slug}: {topic.path}"
    html = core_help.render_markdown_doc(topic.path)
    assert html.strip()


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_polish_file_renders_if_present(topic):
    from core import help as core_help

    pl_rel = topic.path.removesuffix(".md") + ".pl.md"
    if (core_help.DOCS_ROOT / pl_rel).exists():
        assert core_help.render_markdown_doc(pl_rel).strip()


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_polish_file_is_not_an_english_copy(topic):
    # Guards against a mis-pasted English .pl.md shipping as "Polish" (I2).
    from core import help as core_help

    pl_rel = topic.path.removesuffix(".md") + ".pl.md"
    if (core_help.DOCS_ROOT / pl_rel).exists():
        en = core_help.render_markdown_doc(topic.path)
        pl = core_help.render_markdown_doc(pl_rel)
        assert pl != en, f"{pl_rel} looks identical to its English source"


@pytest.mark.django_db
@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.slug)
def test_topic_perm_is_real(topic):
    app_label, codename = topic.perm.split(".")
    assert Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).exists(), topic.perm


def test_get_topic_returns_none_for_unknown():
    assert get_topic("does-not-exist") is None


def test_localized_path_english_returns_base():
    assert localized_doc_path("help/teacher/analytics.md", "en") == (
        "help/teacher/analytics.md"
    )


def test_localized_path_none_lang_returns_base():
    # translation.get_language() can return None; must not raise.
    assert localized_doc_path("help/teacher/analytics.md", None) == (
        "help/teacher/analytics.md"
    )


def test_localized_path_pl_returns_sibling_when_present():
    # Seed topic analytics ships a .pl.md, so PL resolves to it (dir preserved).
    assert localized_doc_path("help/teacher/analytics.md", "pl") == (
        "help/teacher/analytics.pl.md"
    )


def test_localized_path_pl_falls_back_when_absent(tmp_path, monkeypatch):
    (tmp_path / "help").mkdir()
    (tmp_path / "help" / "x.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(core_help, "DOCS_ROOT", tmp_path)
    # No help/x.pl.md on disk -> fall back to the English base.
    assert core_help.localized_doc_path("help/x.md", "pl") == "help/x.md"


def test_localized_path_normalizes_regional_code():
    assert localized_doc_path("help/teacher/analytics.md", "pl-PL") == (
        "help/teacher/analytics.pl.md"
    )


def _slugs_by_role(groups):
    return {g["role"]: [t.slug for t in g["topics"]] for g in groups}


@pytest.mark.django_db
def test_topics_for_pa_sees_all_three_groups(client):
    user = make_pa(client)
    groups = topics_for(user)
    # Fixed order: PA, CA, Teacher.
    assert [g["role"] for g in groups] == [PLATFORM_ADMIN, COURSE_ADMIN, TEACHER]
    by_role = _slugs_by_role(groups)
    assert "users-roles" in by_role[PLATFORM_ADMIN]
    assert "builder" in by_role[COURSE_ADMIN]
    assert "analytics" in by_role[TEACHER]


@pytest.mark.django_db
def test_topics_for_teacher_sees_only_teacher(client):
    groups = topics_for(make_teacher(client))
    assert [g["role"] for g in groups] == [TEACHER]
    assert "analytics" in _slugs_by_role(groups)[TEACHER]


@pytest.mark.django_db
def test_topics_for_ca_sees_ca_and_teacher(client):
    groups = topics_for(make_ca(client))
    assert set(g["role"] for g in groups) == {COURSE_ADMIN, TEACHER}


@pytest.mark.django_db
def test_topics_for_student_sees_nothing(client):
    assert topics_for(make_student(client)) == []


@pytest.mark.django_db
def test_group_label_is_translated_string(client):
    groups = topics_for(make_pa(client))
    for g in groups:
        assert g["label"] == ROLE_LABELS[g["role"]]


@pytest.mark.django_db
def test_user_has_any_help(client):
    assert user_has_any_help(make_pa(client))
    assert user_has_any_help(make_teacher(client))
    assert not user_has_any_help(make_student(client))


@pytest.mark.django_db
def test_index_lists_permitted_topics(client):
    make_pa(client)
    resp = client.get(reverse("core:help_index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Users &amp; roles" in body or "Users & roles" in body


@pytest.mark.django_db
def test_index_empty_state_for_student(client):
    make_student(client)
    resp = client.get(reverse("core:help_index"))
    assert resp.status_code == 200
    assert "No manuals are available" in resp.content.decode()


@pytest.mark.django_db
def test_topic_renders_for_permitted_user(client):
    make_ca(client)
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 200
    assert "Building a course" in resp.content.decode()


@pytest.mark.django_db
def test_topic_404_for_unknown_slug(client):
    make_pa(client)
    resp = client.get(reverse("core:help_topic", args=["nope"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_topic_404_when_missing_marker_perm(client):
    make_teacher(client)  # no grouping.change_group
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_topic_requires_login(client):
    resp = client.get(reverse("core:help_topic", args=["builder"]))
    assert resp.status_code == 302  # @login_required redirect


@pytest.mark.django_db
def test_topic_renders_polish_via_session(client):
    make_teacher(client)
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(reverse("core:help_topic", args=["analytics"]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # PL_SENTINEL is the H1 of analytics.pl.md, designated in Task 3 Step 4 and kept
    # stable. It is present only in the Polish file (absent from analytics.md), so its
    # presence proves the .pl.md was served under a PL session.
    assert "Macierz analityczna" in body
