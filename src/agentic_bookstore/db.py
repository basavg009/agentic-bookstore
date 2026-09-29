"""Database engine, session factory, and FTS5 setup."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        # Enable FK cascades + WAL for concurrent reads.
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.database_url
        if url.startswith("sqlite:///") and "memory" not in url:
            db_path = Path(url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = _make_engine(url)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    sm = get_sessionmaker()
    session = sm()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_FTS_SETUP = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
        isbn13 UNINDEXED,
        title,
        author,
        description,
        tokenize='porter unicode61'
    )""",
    """CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
        INSERT INTO books_fts(isbn13, title, author, description)
        VALUES (new.isbn13, new.title, new.author, new.description);
    END""",
    """CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
        DELETE FROM books_fts WHERE isbn13 = old.isbn13;
    END""",
    """CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
        DELETE FROM books_fts WHERE isbn13 = old.isbn13;
        INSERT INTO books_fts(isbn13, title, author, description)
        VALUES (new.isbn13, new.title, new.author, new.description);
    END""",
]


def init_db(*, drop: bool = False) -> None:
    """Create schema + FTS index. Set drop=True to reset."""
    engine = get_engine()
    if drop:
        Base.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS books_fts"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _FTS_SETUP:
            conn.execute(text(stmt))


def rebuild_fts() -> None:
    """Rebuild the FTS index from the books table (used after bulk seeding)."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM books_fts"))
        conn.execute(
            text(
                "INSERT INTO books_fts(isbn13, title, author, description) "
                "SELECT isbn13, title, author, description FROM books"
            )
        )


def reset_engine_for_tests() -> None:
    """Force engine recreation (tests swap DATABASE_URL between runs)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
