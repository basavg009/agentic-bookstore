"""Shared fixtures: fresh SQLite DB per test session, minimal book set."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a temp SQLite DB before importing anything that uses config.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="agentic-bookstore-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["SESSION_SECRET"] = "test-secret"

from agentic_bookstore.db import get_engine, init_db, rebuild_fts  # noqa: E402
from agentic_bookstore.models import Book  # noqa: E402

SAMPLE_BOOKS = [
    dict(
        isbn13="9781000000017",
        title="Dragons of Vareth",
        author="Aria Ando",
        genre="Fantasy",
        description="A young apprentice mage discovers the shattered kingdom hides ancient dragons and a broken prophecy.",
        format="epub", medium="digital", price_cents=799, stock=-1, year=2022,
        cover_url="", language="en", page_count=320,
    ),
    dict(
        isbn13="9781000000024",
        title="The Kepler Run",
        author="Ben Blake",
        genre="Sci-Fi",
        description="A courier pilot intercepts an alien signal near Proxima Centauri that changes everything.",
        format="paperback", medium="physical", price_cents=1499, stock=7, year=2023,
        cover_url="", language="en", page_count=280,
    ),
    dict(
        isbn13="9781000000031",
        title="Kubernetes at Scale",
        author="Cai Costa",
        genre="Technical",
        description="A field guide to distributed systems in production with worked examples and runbooks.",
        format="pdf", medium="digital", price_cents=2499, stock=-1, year=2024,
        cover_url="", language="en", page_count=520,
    ),
    dict(
        isbn13="9781000000048",
        title="Fog on the Harbor",
        author="Dara Dumas",
        genre="Mystery",
        description="A disgraced detective returns to a foggy port town to reopen a decades-old cold case.",
        format="hardcover", medium="physical", price_cents=2999, stock=3, year=2021,
        cover_url="", language="en", page_count=340,
    ),
    dict(
        isbn13="9781000000055",
        title="Sold Out Story",
        author="Eli Evren",
        genre="Fiction",
        description="A test book that is out of stock.",
        format="hardcover", medium="physical", price_cents=1999, stock=0, year=2020,
        cover_url="", language="en", page_count=200,
    ),
]


@pytest.fixture(scope="session", autouse=True)
def _seed_db():
    init_db(drop=True)
    from agentic_bookstore.db import get_sessionmaker
    Session = get_sessionmaker()
    with Session() as s:
        s.bulk_insert_mappings(Book, SAMPLE_BOOKS)
        s.commit()
    rebuild_fts()
    yield
    get_engine().dispose()


@pytest.fixture
def sid() -> str:
    import uuid
    return f"test-{uuid.uuid4()}"
