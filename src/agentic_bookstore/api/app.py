"""FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db import init_db
from .routes_books import router as books_router
from .routes_cart import router as cart_router
from .routes_chat import router as chat_router
from .routes_checkout import router as checkout_router
from .session import SessionMiddleware

_ROOT = Path(__file__).resolve().parents[3]
_WEB = _ROOT / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="Agentic Bookstore", version="0.1.0")

    @app.on_event("startup")
    def _startup() -> None:
        init_db()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SessionMiddleware)

    app.include_router(books_router)
    app.include_router(cart_router)
    app.include_router(checkout_router)
    app.include_router(chat_router)

    if (_WEB / "static").exists():
        app.mount("/static", StaticFiles(directory=_WEB / "static"), name="static")

    templates = Jinja2Templates(directory=_WEB / "templates")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
