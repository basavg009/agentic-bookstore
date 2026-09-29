"""SQLAlchemy models for books, carts, and orders."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

GENRES = (
    "Fiction",
    "Sci-Fi",
    "Fantasy",
    "Mystery",
    "Romance",
    "Biography",
    "History",
    "Self-Help",
    "Children's",
    "Technical",
    "Poetry",
    "Horror",
    "Thriller",
    "Cookbook",
    "Non-fiction",
)
FORMATS = ("hardcover", "paperback", "epub", "pdf", "audiobook")
DIGITAL_FORMATS = frozenset({"epub", "pdf", "audiobook"})


def medium_for(fmt: str) -> str:
    return "digital" if fmt in DIGITAL_FORMATS else "physical"


class Base(DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = "books"

    isbn13: Mapped[str] = mapped_column(String(13), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    author: Mapped[str] = mapped_column(String(200), index=True)
    genre: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(20), index=True)
    medium: Mapped[str] = mapped_column(String(10), index=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    # -1 means unlimited (digital titles)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    year: Mapped[int] = mapped_column(Integer)
    cover_url: Mapped[str] = mapped_column(String(300), default="")
    language: Mapped[str] = mapped_column(String(10), default="en")
    page_count: Mapped[int] = mapped_column(Integer, default=0)


Index("ix_books_genre_medium", Book.genre, Book.medium)


class Cart(Base):
    __tablename__ = "carts"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", lazy="selectin"
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("session_id", "isbn13", name="uq_cart_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("carts.session_id", ondelete="CASCADE"), index=True
    )
    isbn13: Mapped[str] = mapped_column(ForeignKey("books.isbn13"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    cart: Mapped[Cart] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    total_cents: Mapped[int] = mapped_column(Integer)
    shipping_name: Mapped[str] = mapped_column(String(200), default="")
    shipping_address: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    payment_status: Mapped[str] = mapped_column(String(20), default="paid")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id", ondelete="CASCADE"))
    isbn13: Mapped[str] = mapped_column(String(13))
    title: Mapped[str] = mapped_column(String(300))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
