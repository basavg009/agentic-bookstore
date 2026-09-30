"""Book search + lookup."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, column, func, literal_column, select, table, text
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Book


def _book_to_dict(book: Book) -> dict[str, Any]:
    return {
        "isbn13": book.isbn13,
        "title": book.title,
        "author": book.author,
        "genre": book.genre,
        "description": book.description,
        "format": book.format,
        "medium": book.medium,
        "price_cents": book.price_cents,
        "price": book.price_cents / 100,
        "stock": book.stock,
        "in_stock": book.medium == "digital" or book.stock > 0,
        "year": book.year,
        "cover_url": book.cover_url,
        "language": book.language,
        "page_count": book.page_count,
    }


def _apply_filters(
    stmt: Select,
    *,
    author: str | None,
    genre: str | None,
    medium: str | None,
    fmt: str | None,
    max_price_cents: int | None,
    min_price_cents: int | None,
) -> Select:
    conditions = []
    if author:
        conditions.append(Book.author.ilike(f"%{author}%"))
    if genre:
        conditions.append(Book.genre == genre)
    if medium:
        conditions.append(Book.medium == medium)
    if fmt:
        conditions.append(Book.format == fmt)
    if max_price_cents is not None:
        conditions.append(Book.price_cents <= max_price_cents)
    if min_price_cents is not None:
        conditions.append(Book.price_cents >= min_price_cents)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


_FTS = table("books_fts", column("isbn13"))
# BM25 with column weights (isbn13, title, author, description): title matches
# outrank author matches, which outrank description matches. Lower = better.
_FTS_RANK = literal_column("bm25(books_fts, 0.0, 10.0, 5.0, 1.0)")


def _sanitize_fts(query: str) -> str:
    # Strip FTS5 syntax characters and quote each term so words like AND/OR/NOT/NEAR
    # are matched literally, then add a prefix wildcard.
    keep = [c if c.isalnum() or c.isspace() else " " for c in query]
    terms = "".join(keep).split()
    if not terms:
        return ""
    return " ".join(f'"{t}"*' for t in terms)


def search_books(
    *,
    query: str | None = None,
    isbn: str | None = None,
    author: str | None = None,
    genre: str | None = None,
    medium: str | None = None,
    format: str | None = None,
    max_price_cents: int | None = None,
    min_price_cents: int | None = None,
    limit: int = 20,
    offset: int = 0,
    session: Session | None = None,
) -> dict[str, Any]:
    """Search the catalog. Returns `{items, total, limit, offset}`.

    - If `isbn` is provided, does an exact ISBN-13 lookup (ignores other filters).
    - Else if `query` is provided, uses SQLite FTS5 with prefix matching over
      title/author/description, applies structured filters, and orders by BM25.
    - Else returns the newest matching books ordered by year desc.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    def _run(sess: Session) -> dict[str, Any]:
        if isbn:
            book = sess.get(Book, isbn.strip())
            items = [_book_to_dict(book)] if book else []
            return {"items": items, "total": len(items), "limit": limit, "offset": 0}

        if query and query.strip():
            fts_query = _sanitize_fts(query)
            if not fts_query:
                return {"items": [], "total": 0, "limit": limit, "offset": offset}
            # Match, filter, rank and paginate in one SQL statement — no candidate
            # IDs are pulled into Python, so cost doesn't grow with match count.
            stmt = (
                select(Book)
                .join(_FTS, _FTS.c.isbn13 == Book.isbn13)
                .where(text("books_fts MATCH :q").bindparams(q=fts_query))
            )
            stmt = _apply_filters(
                stmt,
                author=author,
                genre=genre,
                medium=medium,
                fmt=format,
                max_price_cents=max_price_cents,
                min_price_cents=min_price_cents,
            )
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = sess.execute(count_stmt).scalar_one()
            stmt = stmt.order_by(_FTS_RANK, Book.isbn13).limit(limit).offset(offset)
            rows = sess.execute(stmt).scalars().all()
            return {
                "items": [_book_to_dict(b) for b in rows],
                "total": int(total),
                "limit": limit,
                "offset": offset,
            }

        stmt = select(Book)
        stmt = _apply_filters(
            stmt,
            author=author,
            genre=genre,
            medium=medium,
            fmt=format,
            max_price_cents=max_price_cents,
            min_price_cents=min_price_cents,
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = sess.execute(count_stmt).scalar_one()
        stmt = stmt.order_by(Book.year.desc(), Book.isbn13).limit(limit).offset(offset)
        rows = sess.execute(stmt).scalars().all()
        return {
            "items": [_book_to_dict(b) for b in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)


def get_book(isbn: str, *, session: Session | None = None) -> dict[str, Any] | None:
    def _run(sess: Session) -> dict[str, Any] | None:
        book = sess.get(Book, isbn.strip())
        return _book_to_dict(book) if book else None

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)
