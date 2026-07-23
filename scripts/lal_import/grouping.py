"""Group a part's ordered .html files into chapters terminated by a *_quiz.html."""


def is_quiz(name):
    stem = name[:-5] if name.endswith(".html") else name
    return stem.endswith("_quiz")


def group_into_chapters(ordered_names):
    chapters = []
    current = []
    for name in ordered_names:
        unit_type = "quiz" if is_quiz(name) else "lesson"
        current.append({"source_html": name, "unit_type": unit_type})
        if unit_type == "quiz":
            chapters.append({"units": current, "ends_with_quiz": True})
            current = []
    if current:  # trailing lessons after the last quiz (or a quiz-less part)
        chapters.append({"units": current, "ends_with_quiz": False})
    return chapters
