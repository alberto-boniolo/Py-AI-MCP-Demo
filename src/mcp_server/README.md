# mcp_server

A `fastmcp` MCP server exposing the [`django_api`](../django_api/README.md) bookings API as LLM tools, over the stdio transport. Talks to Django only over HTTP (via `httpx`) — it never imports Django code, even though both live in the same `uv` workspace, so this server allows to swtich to a different backend without changes to Django.

## What's covered here

- **`api_client.py`**: an async `httpx` client wrapping the three Django Ninja endpoints, with its own Pydantic models (`BookingOut`), not a shortcut reuse of Django's schemas. Raises domain-specific exceptions (`BookingNotFoundError`, `RoomNotFoundError`, `ApiError` for a non-404 failure, `ApiTimeoutError` for a request timing out) rather than leaking raw `httpx` exceptions.
- **`server.py`**: the `FastMCP` instance and three `@mcp.tool` functions — `list_bookings`, `get_booking`, `create_booking` — each mapping the `api_client` exceptions above to `ToolError` so the calling LLM gets a message instead of a stack trace or a silent failure.
- **Structured JSON logging** (`logging_setup.py`): every tool call logs a start/success line tagged with fastmcp's own per-call `ctx.request_id`, which is also forwarded to Django as an `X-Request-Id` header- This is the one identifier that actually crosses the MCP to Django process boundary and lets a single request be traced across both processes' logs. Necessary for logs correlation.
- 2 MCP hosts available: **MCP Inspector** (`fastmcp dev inspector`, a lightweight MCP host) and **Claude Desktop** (a full-featured MCP host), both exercising the same tools and the same error paths (missing booking/room, API unreachable, API timeout).

## Packages used

| Package | Role |
|---|---|
| [`fastmcp`](https://pypi.org/project/fastmcp/) | MCP server framework — `@mcp.tool` decorator, stdio transport, Inspector/Claude Desktop integration |
| [`httpx`](https://pypi.org/project/httpx/) | Async HTTP client used to call the Django Ninja API |

(Ruff is used for linting across the whole workspace as a root-level dev dependency — see the root [`pyproject.toml`](../../pyproject.toml).)

## Running

Requires the [`django_api`](../django_api/README.md) server running at `http://127.0.0.1:8000/api` (and Postgres up behind it).

How to launch with the MCP Inspector (browser-based tool for calling tools by hand):

```powershell
cd src\mcp_server
uv run fastmcp dev inspector server.py
```

will open browser with fast mcp web interface

### Connecting to Claude Desktop

```powershell
cd src\mcp_server
uv run fastmcp install claude-desktop server.py
```

If Claude Desktop is a Microsoft Store (MSIX) install, `fastmcp` can't find its sandboxed config path automatically. Find it and pass it explicitly:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Packages" -Filter "*Claude*"
uv run fastmcp install claude-desktop server.py --config-path "$env:LOCALAPPDATA\Packages\<found-folder>\LocalCache\Roaming\Claude"
```

Fully restart Claude Desktop afterward (exit from the system tray, not just close the window) so it picks up the new server. Tools are listed under **Settings → Connectors → Bookings MCP Server**.
