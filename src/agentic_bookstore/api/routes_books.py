"""Book search + detail endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services import books as books_svc

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("/search")
def search(
    query: str | None = Query(None),
    isbn: str | None = Query(None),
    author: str | None = Query(None),
    genre: str | None = Query(None),
    medium: str | None = Query(None, pattern="^(digital|physical)$"),
    format: str | None = Query(None),
    max_price_cents: int | None = Query(None, ge=0),
    min_price_cents: int | None = Query(None, ge=0),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    return books_svc.search_books(
        query=query,
        isbn=isbn,
        author=author,
        genre=genre,
        medium=medium,
        format=format,
        max_price_cents=max_price_cents,
        min_price_cents=min_price_cents,
        limit=limit,
        offset=offset,
    )


@router.get("/{isbn}")
def detail(isbn: str) -> dict:
    result = books_svc.get_book(isbn)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no book with ISBN {isbn}")
    return result
