# agentic-bookstore

Open-source **agentic commerce** demo: a 10,000-book catalog exposed three ways from one shared Python service layer.

- **MCP server** — plug the store into Claude Desktop, VS Code Copilot, Cline, or any [Model Context Protocol](https://modelcontextprotocol.io) client so an LLM can search, cart, and check out on your behalf.
- **Web storefront** — classic search / add-to-cart / checkout for humans.
- **In-page chat UI** — powered by a **fully local Qwen 2.5 via [Ollama](https://ollama.com)**. No API keys, no cloud, no data leaves your machine.

Checkout is two-phase and payment is mocked (no real money moves). MIT-licensed.

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
It can search, fill the cart and prepare a quote, but **it cannot place orders**: a
"Confirm purchase" card appears in the chat and only your click places the order.
Conversations are remembered server-side per session ("New chat" forgets them).

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

Seven tools are exposed: `search_books`, `get_book`, `add_to_cart`, `view_cart`,
`remove_from_cart`, `prepare_checkout`, `confirm_checkout`.

- **No `session_id` argument.** A stdio server serves one MCP host, so the process is the
  principal: it acts on one cart (`MCP_SESSION_ID`, or a fresh one per process). A model
  can't reach another shopper's cart by naming it.
- **Orders need a human.** `confirm_checkout` is annotated `destructiveHint`, so hosts ask
  before running it. If the client supports elicitation, the server also asks the user
  directly and refuses without an explicit yes.

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

## Design guarantees

| Concern | How it is handled |
|---|---|
| Agent places an unwanted order | Two-phase checkout. The in-app agent only has `prepare_checkout`; confirming needs a human click (web) or host approval/elicitation (MCP). |
| Duplicate orders on retry | The quote token is the idempotency key: confirming twice returns the same order. |
| Overselling under concurrency | Quote claimed and stock decremented with conditional `UPDATE`s in one transaction; payment decline rolls everything back. |
| Price changes mid-checkout | Prices are locked in the quote; confirm refuses if the cart or prices changed, and quotes expire (15 min). |
| Model-supplied identity | `session_id` is never in a tool schema; the adapter injects it and drops any value the model sends. |
| Prompt injection via catalog text | Search results omit descriptions, `get_book` truncates them, and the system prompt marks tool output as data. The structural limits above hold even if the model is fooled. |
| Runaway agent | Per-turn budgets on iterations, tool calls, wall-clock time and tokens. |
| Session hijack by guessing ids | The session cookie is HMAC-signed; `ENV=production` refuses to start with the default secret and sets `Secure`. |
| Search relevance / scale | FTS5 match, filters, BM25 ranking (title > author > description) and paging run in one SQL statement. |
| Blocking the event loop | Synchronous DB work in the agent, MCP server and chat routes runs via `asyncio.to_thread`. |

Payment goes through a `PaymentProvider` protocol (`services/payments.py`); the mock
approves up to $10,000 so the declined path can be exercised.

Upgrading an existing database: new tables are created automatically on startup.

## Tests

```bash
pytest -q
```

## License

MIT — see [LICENSE](LICENSE).

This project was built with AI assistance. All code has been tested and reviewed by me.
