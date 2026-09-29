from agentic_bookstore.services import books as books_svc


def test_isbn_exact_match():
    r = books_svc.search_books(isbn="9781000000017")
    assert r["total"] == 1
    assert r["items"][0]["title"] == "Dragons of Vareth"


def test_isbn_unknown_returns_empty():
    r = books_svc.search_books(isbn="9999999999999")
    assert r["total"] == 0
    assert r["items"] == []


def test_fts_matches_description():
    r = books_svc.search_books(query="dragons")
    titles = {b["title"] for b in r["items"]}
    assert "Dragons of Vareth" in titles


def test_fts_prefix_match():
    r = books_svc.search_books(query="detect")
    titles = {b["title"] for b in r["items"]}
    assert "Fog on the Harbor" in titles


def test_filter_by_genre_and_medium():
    r = books_svc.search_books(query="dragons", genre="Fantasy", medium="digital")
    assert r["total"] == 1
    assert r["items"][0]["genre"] == "Fantasy"
    assert r["items"][0]["medium"] == "digital"


def test_filter_max_price():
    r = books_svc.search_books(max_price_cents=1000)
    for b in r["items"]:
        assert b["price_cents"] <= 1000


def test_no_query_returns_ordered_list():
    r = books_svc.search_books(limit=100)
    assert r["total"] >= 4
    years = [b["year"] for b in r["items"]]
    assert years == sorted(years, reverse=True)


def test_get_book():
    b = books_svc.get_book("9781000000031")
    assert b is not None
    assert b["genre"] == "Technical"


def test_get_book_missing():
    assert books_svc.get_book("0000000000000") is None
