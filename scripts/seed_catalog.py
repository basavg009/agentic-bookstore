"""Deterministic 10k-book seed generator.

Run:  python scripts/seed_catalog.py [--count 10000] [--force]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from description_templates import GENRE_BANKS, GENRE_TEMPLATES  # noqa: E402

from agentic_bookstore.db import get_engine, get_sessionmaker, init_db, rebuild_fts  # noqa: E402
from agentic_bookstore.models import FORMATS, GENRES, Book, medium_for  # noqa: E402

SEED = 20260929
DEFAULT_COUNT = 10_000

FIRST_NAMES = [
    "Aria", "Ben", "Cai", "Dara", "Eli", "Farah", "Gita", "Hugo", "Iris", "Jae",
    "Kira", "Leo", "Mira", "Nils", "Owen", "Priya", "Quinn", "Rhea", "Sam", "Tara",
    "Uma", "Viktor", "Wren", "Xiu", "Yara", "Zane", "Amelia", "Bram", "Cleo", "Devi",
    "Ezra", "Fenn", "Gwen", "Hana", "Idris", "Juno", "Kaya", "Liron", "Mateo", "Noa",
    "Osian", "Pia", "Rafi", "Sana", "Talia", "Uriel", "Vera", "Wei", "Xander", "Yusuf",
]
LAST_NAMES = [
    "Ando", "Blake", "Costa", "Dumas", "Evren", "Ferro", "Ghosh", "Hale", "Imai", "Jain",
    "Kane", "Larsen", "Meyer", "Novak", "Okafor", "Park", "Quan", "Reyes", "Silva", "Tanaka",
    "Ueno", "Vasquez", "Walsh", "Xu", "Young", "Zeller", "Abadi", "Bergen", "Chen", "Doran",
    "Elmore", "Farley", "Guo", "Hollis", "Ingham", "Jarvis", "Khan", "Leclerc", "Marín", "Nash",
    "Ortiz", "Popov", "Quintero", "Rossi", "Sato", "Tolentino", "Ustinov", "Vidal", "Wren", "Yamada",
]

_TITLE_ADJ = [
    "Silent", "Broken", "Hidden", "Last", "First", "Quiet", "Restless", "Forgotten",
    "Distant", "Ordinary", "Sudden", "Bright", "Iron", "Salt", "Winter", "Summer",
    "Small", "Wide", "Pale", "Northern",
]
_TITLE_NOUN = [
    "House", "River", "Ledger", "Compass", "Empire", "Garden", "Bureau", "Almanac",
    "Signal", "Anchor", "Threshold", "Country", "Season", "Language", "Debt",
    "Chorus", "Inheritance", "Orchard", "Blueprint", "Correspondence",
]
_TITLE_PATTERNS = [
    "The {adj} {noun}",
    "A {noun} of {noun2}",
    "{noun} & {noun2}",
    "Notes on the {adj} {noun}",
    "{adj} {noun}: A Novel",
    "The {noun} at {noun2}",
]

_TECH_TOPICS = [
    "Distributed Systems", "Kubernetes", "PostgreSQL", "Rust", "Python", "Systems Design",
    "Kafka", "gRPC", "Observability", "Serverless", "Data Engineering", "Site Reliability",
    "Compiler Design", "TypeScript", "Machine Learning Systems",
]
_TECH_SUFFIX = [
    "in Production", "at Scale", "for Working Engineers", "from First Principles",
    "the Hard Parts", "Under Load", "in Practice",
]
_COOK_TOPICS = [
    "Weeknight Dinners", "Sheet-Pan Suppers", "One-Pot Meals", "Slow Sundays",
    "The Working Cook", "Small-Batch Baking", "Meatless Mondays", "The Home Pantry",
    "Mediterranean Weeknights", "Modern Comfort Food",
]


def _isbn13(rng: random.Random) -> str:
    prefix = "978"
    body = "".join(str(rng.randint(0, 9)) for _ in range(9))
    core = prefix + body
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    check = (10 - total % 10) % 10
    return core + str(check)


def _make_title(rng: random.Random, genre: str) -> str:
    if genre == "Technical":
        return f"{rng.choice(_TECH_TOPICS)} {rng.choice(_TECH_SUFFIX)}"
    if genre == "Cookbook":
        return rng.choice(_COOK_TOPICS)
    if genre == "Children's":
        return f"{rng.choice(['Little', 'Tiny', 'Brave', 'Sleepy', 'Curious'])} " \
               f"{rng.choice(['Fox', 'Robot', 'Cloud', 'Star', 'Moon', 'Bear'])} " \
               f"and the {rng.choice(['Missing', 'Lost', 'Secret', 'Magic'])} " \
               f"{rng.choice(['Balloon', 'Cookie', 'Key', 'Song', 'Umbrella'])}"
    pattern = rng.choice(_TITLE_PATTERNS)
    return pattern.format(
        adj=rng.choice(_TITLE_ADJ),
        noun=rng.choice(_TITLE_NOUN),
        noun2=rng.choice(_TITLE_NOUN),
    )


def _make_author(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _make_description(rng: random.Random, genre: str) -> str:
    bank = GENRE_BANKS[genre]
    slots = {slot: rng.choice(values) for slot, values in bank.items()}
    sentences = [tpl.format(**slots) for tpl in GENRE_TEMPLATES[genre]]
    return " ".join(sentences)


def _price_cents(rng: random.Random, fmt: str) -> int:
    ranges = {
        "hardcover": (1999, 4999),
        "paperback": (999, 2499),
        "epub": (499, 1499),
        "pdf": (499, 1499),
        "audiobook": (999, 2999),
    }
    lo, hi = ranges[fmt]
    return rng.randint(lo // 100, hi // 100) * 100 - 1


def _stock(rng: random.Random, medium: str) -> int:
    return -1 if medium == "digital" else rng.randint(0, 150)


def generate_books(count: int, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    seen: set[str] = set()
    books: list[dict] = []
    while len(books) < count:
        isbn = _isbn13(rng)
        if isbn in seen:
            continue
        seen.add(isbn)
        genre = rng.choice(GENRES)
        # Bias format by genre for realism.
        if genre == "Technical":
            fmt = rng.choices(["epub", "pdf", "paperback"], weights=[3, 2, 1])[0]
        elif genre == "Children's":
            fmt = rng.choices(["hardcover", "paperback", "audiobook"], weights=[3, 2, 1])[0]
        elif genre == "Cookbook":
            fmt = rng.choices(["hardcover", "paperback", "pdf"], weights=[3, 2, 1])[0]
        else:
            fmt = rng.choices(FORMATS, weights=[2, 3, 2, 1, 2])[0]
        medium = medium_for(fmt)
        books.append({
            "isbn13": isbn,
            "title": _make_title(rng, genre),
            "author": _make_author(rng),
            "genre": genre,
            "description": _make_description(rng, genre),
            "format": fmt,
            "medium": medium,
            "price_cents": _price_cents(rng, fmt),
            "stock": _stock(rng, medium),
            "year": rng.randint(1998, 2025),
            "cover_url": f"https://placehold.co/200x300?text={isbn[-4:]}",
            "language": "en",
            "page_count": rng.randint(80, 700),
        })
    return books


def seed(count: int = DEFAULT_COUNT, force: bool = False) -> int:
    init_db(drop=force)
    books = generate_books(count)
    engine = get_engine()
    if not force:
        # Idempotent skip if catalog already at requested size.
        with engine.connect() as conn:
            from sqlalchemy import text
            existing = conn.execute(text("SELECT COUNT(*) FROM books")).scalar_one()
        if existing >= count:
            print(f"Catalog already has {existing} books (target {count}). "
                  "Use --force to reseed.")
            return existing
    Session = get_sessionmaker()
    with Session() as session:
        session.bulk_insert_mappings(Book, books)
        session.commit()
    rebuild_fts()
    with engine.connect() as conn:
        from sqlalchemy import text
        total = conn.execute(text("SELECT COUNT(*) FROM books")).scalar_one()
    print(f"Seeded {total} books into {engine.url}")
    return int(total)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the agentic-bookstore catalog.")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--force", action="store_true", help="Drop and recreate tables.")
    args = parser.parse_args()
    seed(count=args.count, force=args.force)


if __name__ == "__main__":
    main()
