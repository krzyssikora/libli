"""Polish class-list names for the fake pupils.

GENDERED ON PURPOSE: Polish surnames inflect (Kowalski/Kowalska; Nowak is
invariant), so drawing independently from one flat pair of lists produces
"Anna Kowalski" — obviously fake to any Polish reader, on the screen the spec
calls the demo's best moment. A library or generator is rejected for a
different reason: it would make the determinism test depend on a package
upgrade.
"""

from demo.constants import NAME_RETRY_LIMIT
from demo.errors import NamePoolExhausted

FEMININE_GIVEN = (
    "Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara",
    "Ewa", "Krystyna", "Magdalena", "Elżbieta", "Joanna", "Aleksandra",
    "Zofia", "Monika", "Teresa", "Danuta", "Natalia", "Julia",
    "Karolina", "Marta", "Beata", "Halina", "Irena", "Jadwiga",
    "Dorota", "Janina", "Iwona", "Justyna", "Renata", "Sylwia",
    "Paulina", "Emilia", "Weronika", "Klaudia", "Patrycja", "Wiktoria",
    "Oliwia", "Zuzanna", "Amelia", "Lena",
)  # fmt: skip

MASCULINE_GIVEN = (
    "Jan", "Andrzej", "Piotr", "Krzysztof", "Stanisław", "Tomasz",
    "Paweł", "Marcin", "Michał", "Marek", "Grzegorz", "Jerzy",
    "Tadeusz", "Adam", "Łukasz", "Zbigniew", "Ryszard", "Dariusz",
    "Henryk", "Mariusz", "Kazimierz", "Wojciech", "Robert", "Mateusz",
    "Marian", "Rafał", "Jacek", "Jakub", "Antoni", "Franciszek",
    "Filip", "Szymon", "Wiktor", "Oskar", "Igor", "Alan",
    "Nikodem", "Leon", "Borys", "Fabian",
)  # fmt: skip

# Paired by index with MASCULINE_SURNAMES: same surname, the form that agrees
# with the given name's gender. Invariant surnames (Nowak, Wójcik, Mazur...)
# repeat unchanged, which is correct Polish.
FEMININE_SURNAMES = (
    "Nowak", "Kowalska", "Wiśniewska", "Wójcik", "Kowalczyk", "Kamińska",
    "Lewandowska", "Zielińska", "Szymańska", "Woźniak", "Dąbrowska",
    "Kozłowska", "Jankowska", "Mazur", "Kwiatkowska", "Krawczyk",
    "Piotrowska", "Grabowska", "Nowakowska", "Pawłowska", "Michalska",
    "Nowicka", "Adamczyk", "Dudek", "Zając", "Wieczorek", "Jabłońska",
    "Król", "Majewska", "Olszewska", "Jaworska", "Wróbel", "Malinowska",
    "Pawlak", "Witkowska", "Walczak", "Stępień", "Górska", "Rutkowska",
    "Michalak",
)  # fmt: skip

MASCULINE_SURNAMES = (
    "Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kowalczyk", "Kamiński",
    "Lewandowski", "Zieliński", "Szymański", "Woźniak", "Dąbrowski",
    "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski", "Krawczyk",
    "Piotrowski", "Grabowski", "Nowakowski", "Pawłowski", "Michalski",
    "Nowicki", "Adamczyk", "Dudek", "Zając", "Wieczorek", "Jabłoński",
    "Król", "Majewski", "Olszewski", "Jaworski", "Wróbel", "Malinowski",
    "Pawlak", "Witkowski", "Walczak", "Stępień", "Górski", "Rutkowski",
    "Michalak",
)  # fmt: skip


def draw_names(rng, count):
    """`count` distinct, gender-consistent (first, last) pairs.

    `rng` is a `random.Random`. (Stated here rather than via a `noqa`'d unused
    `import random` at the top, which reads as an accident to the next person.)

    NAME_RETRY_LIMIT is read as a MODULE GLOBAL inside the loop below — never
    captured as a default argument — so the retry test can monkeypatch it.

    RNG contract (spec §4.5, order item 1) — per pupil in creation order:
    gender, then given name, then surname; a duplicate pair redraws THE SURNAME
    ONLY, costing exactly one further draw. Methods are pinned (`random()` for
    the Bernoulli, `randrange` for the indexes) because different methods
    consume the Mersenne stream differently and R5 is a claim about the stream.
    """
    shortest = min(
        len(FEMININE_GIVEN),
        len(MASCULINE_GIVEN),
        len(FEMININE_SURNAMES),
        len(MASCULINE_SURNAMES),
    )
    if shortest < count:
        # A runtime check, not only the test above: a service must not depend on
        # a test having run.
        raise NamePoolExhausted(
            f"the name lists are too short to draw {count} distinct pairs"
        )

    seen = set()
    drawn = []
    for _ in range(count):
        feminine = rng.random() < 0.5
        given_pool = FEMININE_GIVEN if feminine else MASCULINE_GIVEN
        surname_pool = FEMININE_SURNAMES if feminine else MASCULINE_SURNAMES
        first = given_pool[rng.randrange(len(given_pool))]
        last = surname_pool[rng.randrange(len(surname_pool))]
        tries = 0
        while (first, last) in seen:
            tries += 1
            if tries > NAME_RETRY_LIMIT:
                raise NamePoolExhausted(
                    "could not draw a distinct name pair within "
                    f"{NAME_RETRY_LIMIT} retries"
                )
            last = surname_pool[rng.randrange(len(surname_pool))]
        seen.add((first, last))
        drawn.append((first, last))
    return drawn
