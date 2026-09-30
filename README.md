# agentic-bookstore

Open-source **agentic commerce** demo: a 10,000-book catalog exposed three ways from one shared Python service layer.

- **MCP server** — plug the store into Claude Desktop, VS Code Copilot, Cline, or any [Model Context Protocol](https://modelcontextprotocol.io) client so an LLM can search, cart, and check out on your behalf.
- **Web storefront** — classic search / add-to-cart / checkout for humans.
- **In-page chat UI** — powered by a **fully local Qwen 2.5 via [Ollama](https://ollama.com)**. No API keys, no cloud, no data leaves your machine.

Checkout is mocked (no real payment). MIT-licensed.

## Quickstart

```bash
pip install -e .[dev]
python scripts/seed_catalog.py           # generates 10,000 books
uvicorn agentic_bookstore.api.app:app --reload
```

Open http://localhost:8000 — search, filter, add to cart, check out.

## Enable the local AI shopping agent

1. Install [Ollama](https://ollama.com).
2. Pull the model: `ollama pull qwen2.5:7b` (~4.5 GB, needs ~8 GB RAM).
3. Refresh the page — the chat panel on the right activates. Try:
   > "Find me a fantasy ebook under $10 and buy it."

The agent uses the same session cookie as the storefront, so its tool calls appear live in the cart drawer.

## Use as an MCP server

Register with Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agentic-bookstore": {
      "command": "python",
      "args": ["-m", "agentic_bookstore.mcp"]
    }
  }
}
```

Six tools are exposed: `search_books`, `get_book`, `add_to_cart`, `view_cart`, `remove_from_cart`, `checkout`. All cart/checkout tools take an explicit `session_id` argument.

## Architecture

```
        ┌──────────────────────────────────────────────┐
        │            shared service layer               │
        │   books.py · cart.py · checkout.py · agent.py │
        └───────┬─────────────────┬────────────────┬────┘
                │                 │                │
         REST + Web UI     MCP stdio server   Chat orchestrator
         (FastAPI)         (mcp SDK)          (Ollama · Qwen 2.5)
                │                 │                │
                ▼                 ▼                ▼
        browser / curl    any MCP client    /api/chat/stream (SSE)
```

## Tests

```bash
pytest -q
```

## License

MIT — see [LICENSE](LICENSE).

This project was built with AI assistance. All code has been tested and reviewed by me.
