# Day 3 — MCP Server (fastmcp) Wrapping the Django API

> Companion guide to `python-mcp-4day-plan.md`, `day1-postgres-django-models.md`, and `day2-django-ninja-api.md`. Today's work lives in `src/mcp_server/`, the workspace member reserved (empty) back in Day 1 §3 — no folder moves, no renames. Written for the same setup: VS Code, `uv`, PowerShell 7, workspace root `Py-AI-MCP-Demo\`.

---

## 0. Objective for today

By the end of Day 3 you will have:

1. A real `fastmcp` project in `src/mcp_server/`, added as dependencies alongside `httpx`.
2. A thin async HTTP client (`api_client.py`) that talks to yesterday's Django Ninja API — the only place `httpx` appears.
3. Three `@mcp.tool` functions (`list_bookings`, `get_booking`, `create_booking`) exposed over stdio, each wrapping one Day 2 endpoint.
4. The server verified two ways: the MCP Inspector (CLI-driven, no host required) and Claude Desktop (a real MCP host).
5. Clean, actionable errors for the two failure modes that are cheap to handle today — a missing booking/room, and the Django API being unreachable — with the fuller error-handling pass deferred to Day 4 on purpose (see §8).

**Definition of done:** `fastmcp dev inspector server.py` lists all three tools, calling each one against the running Django API returns real Postgres-backed data, and Claude Desktop's tool picker shows the same three tools connected the same way.

**A boundary decision worth stating up front:** `mcp_server` does **not** import anything from `django_api`. They're siblings in the same `uv` workspace, but the MCP server only ever talks to Django over HTTP, through `httpx` — the same relationship your C# `BookingApi` MCP-equivalent would have to a downstream API it doesn't share a process with. That means `mcp_server` defines its own small Pydantic models for the JSON it gets back (§4), even though they look almost identical to Day 2's `schemas.py`. Duplication here is deliberate, not an oversight — it's the tool-boundary translation layer the plan document calls out, and it's what lets you point this same MCP server at a differently-implemented backend later without touching Django code.

---

## 1. Mental model before you type anything

| .NET/C# concept                                                                                    | fastmcp equivalent                                           | Notes                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| An MCP server would be a new ASP.NET-hosted process exposing tool endpoints over a custom protocol | `FastMCP("name")` instance in `server.py`                    | One object is the whole server, the same way `NinjaAPI()` was the whole API surface on Day 2                                                                            |
| `[HttpGet]`/`[HttpPost]` action, model-bound from the request                                      | `@mcp.tool` decorator on a plain function                    | The decorator inspects the function's type hints to build the tool's JSON-schema input — no separate DTO/attribute step, same "type hint is the contract" idea as Ninja |
| `HttpClient` injected via DI, calling a downstream API                                             | `httpx.AsyncClient` instantiated directly in `api_client.py` | No DI container — you construct and pass the client explicitly, or open one per call; see §3 for which                                                                  |
| `async Task<OrderDto> GetOrderAsync(int id)`                                                       | `async def get_booking(booking_id: int) -> BookingOut`       | Same execution model — `async def` tools run on fastmcp's event loop the way `async Task` methods run on ASP.NET's                                                      |
| `ILogger`/Serilog writing to console                                                               | fastmcp's own logger, and any `print()` you write            | Must go to **stderr**, not stdout — stdio transport uses stdout exclusively for the JSON-RPC protocol stream (§5)                                                       |
| Swagger UI for manually poking an API                                                              | **MCP Inspector** (`fastmcp dev inspector`)                  | Browser-based, but talks MCP's protocol instead of REST — the Day 3 analogue of Day 2's `/api/docs` loop                                                                |
| Registering a Web API's base URL in a client app's config                                          | Claude Desktop's `claude_desktop_config.json`                | Tells a real MCP *host* how to launch your server subprocess (§7)                                                                                                       |
| Custom exception + middleware mapping it to a 4xx                                                  | `raise ToolError("...")` from `fastmcp.exceptions`           | Message reaches the calling LLM verbatim; anything else raised gets logged and returned as a generic error                                                              |

Structural things that are genuinely different, not just renamed:

- **No routing table.** There's no `/bookings` URL a tool lives at — an MCP tool is identified by name (`list_bookings`) and discovered by the host calling `tools/list`, not by an HTTP verb+path pair.
- **The client, not the server, decides transport.** Today the server only speaks stdio: whatever process starts it (Inspector, Claude Desktop) owns its stdin/stdout pipes directly. There's no "port" to configure, unlike Day 1/2's `runserver` on `:8000`.
- **A tool's docstring is part of its contract.** The LLM calling the tool sees the docstring as the tool's description — it's not a code comment, it's user-facing (host-facing) documentation, closer in spirit to an OpenAPI `summary` than to a C# XML doc comment that only IntelliSense reads.

**Ask your AI assistant if you want more depth here:** *"Why does MCP's stdio transport reserve stdout exclusively for protocol messages — what actually breaks if a tool function calls print()?"*

---

## 2. Prerequisites check

Both halves of yesterday's stack need to be up, since today's server is a client of the Django API, not a replacement for it:

```powershell
docker compose ps
```

Should show `bookings-postgres` running. If not, `docker compose up -d` from the workspace root.

In one terminal, start the Django API and leave it running for the rest of today:

```powershell
cd src\django_api
uv run python manage.py runserver
```

Confirm `http://127.0.0.1:8000/api/docs` still loads and `GET /api/bookings` still returns the four seeded rows. Everything below assumes that server stays up at `http://127.0.0.1:8000/api` in a second terminal.

---

## 3. Where the new files live

`src/mcp_server/` currently holds only the placeholder `pyproject.toml` from Day 1 §3 (created with `uv init --bare --name mcp-server`, no source files). Today fills it in with a flat layout — matching `django_api`'s `--no-package` choice from Day 2, since this is an application, not a library other packages will import:

```
src/mcp_server/
├── pyproject.toml   (Day 1 — placeholder, dependencies added today)
├── api_client.py     ← new: httpx calls to the Django API + response models
└── server.py         ← new: FastMCP instance + the three @mcp.tool functions
```

No `startproject`/`startapp` equivalent today — `fastmcp` has no project scaffolding command; you write `server.py` by hand, the same way you'd hand-write a new minimal ASP.NET `Program.cs` for a small standalone service rather than scaffolding a full project template.

---

## 4. Add dependencies and the API client

From inside `src/mcp_server/`:

```powershell
cd src\mcp_server
uv add fastmcp httpx
```

Same pattern as Day 1 §7 — this writes to `src/mcp_server/pyproject.toml`, resolved through the one shared workspace lockfile at the root.

```python
# api_client.py
from typing import Any

import httpx
from pydantic import BaseModel

BASE_URL = "http://127.0.0.1:8000/api"


class BookingOut(BaseModel):
    id: int
    room_id: int
    date: str
    start_time: str
    end_time: str
    booked_by: str


class BookingNotFoundError(Exception):
    def __init__(self, booking_id: int) -> None:
        self.booking_id = booking_id
        super().__init__(f"Booking {booking_id} not found")


class RoomNotFoundError(Exception):
    def __init__(self, room_id: int) -> None:
        self.room_id = room_id
        super().__init__(f"Room {room_id} not found")


async def list_bookings(
    *,
    room_id: int | None = None,
    building_id: int | None = None,
    date: str | None = None,
    booked_by: str | None = None,
) -> list[BookingOut]:
    params: dict[str, Any] = {
        k: v
        for k, v in {
            "room_id": room_id,
            "building_id": building_id,
            "date": date,
            "booked_by": booked_by,
        }.items()
        if v is not None
    }
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get("/bookings", params=params)
        response.raise_for_status()
        return [BookingOut(**row) for row in response.json()]


async def get_booking(booking_id: int) -> BookingOut:
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get(f"/bookings/{booking_id}")
        if response.status_code == 404:
            raise BookingNotFoundError(booking_id)
        response.raise_for_status()
        return BookingOut(**response.json())


async def create_booking(
    *, room_id: int, date: str, start_time: str, end_time: str, booked_by: str
) -> BookingOut:
    payload = {
        "room_id": room_id,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "booked_by": booked_by,
    }
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.post("/bookings", json=payload)
        if response.status_code == 404:
            raise RoomNotFoundError(room_id)
        response.raise_for_status()
        return BookingOut(**response.json())
```

Notes:

- **A new `httpx.AsyncClient` per call, not one shared instance.** For a 4-day local sprint with three low-volume tools this is the simplest correct option — no lifecycle to manage. The tradeoff (a new TCP connection per call instead of a pooled, reused one) is exactly the kind of thing worth revisiting if this ever needed to handle real traffic; flagging it here rather than prematurely building connection-pool lifecycle management you don't need yet.
- **`BookingOut` here is not Day 2's `BookingOut`.** Same fields, same names — because both describe the same wire shape — but it's `pydantic.BaseModel`, not `ninja.Schema`, and it lives in a different package. This is the translation-layer boundary called out in §0.
- **`response.status_code == 404` is checked before `raise_for_status()`**, not after catching `HTTPStatusError` — turning the one status code you know how to handle meaningfully (a missing resource) into a domain-specific exception, while letting anything else (a 422, a 500) fall through to `raise_for_status()`'s generic `HTTPStatusError`. `server.py` maps both outcomes to `ToolError` in §5, but keeps them distinguishable at this layer in case Day 4 wants different messages for each.
- **`BookingNotFoundError`/`RoomNotFoundError` are plain Python exceptions, not `ToolError`.** `api_client.py` has no dependency on `fastmcp` — it's a reusable async HTTP client that could be unit-tested or reused outside an MCP context. Translating exceptions into MCP-specific errors is `server.py`'s job, next.

**Ask your AI assistant if you want more depth here:** *"What's the tradeoff between opening a new httpx.AsyncClient per request versus creating one long-lived client and reusing it across all the tool calls in a server's lifetime?"*

---

## 5. Define the server and the three tools

```python
# server.py
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from api_client import (
    BookingNotFoundError,
    RoomNotFoundError,
    create_booking as api_create_booking,
    get_booking as api_get_booking,
    list_bookings as api_list_bookings,
)
import httpx

mcp = FastMCP("Bookings MCP Server")


@mcp.tool
async def list_bookings(
    room_id: int | None = None,
    building_id: int | None = None,
    date: str | None = None,
    booked_by: str | None = None,
) -> list[dict]:
    """List bookings, optionally filtered by room, building, date, or who booked it."""
    try:
        bookings = await api_list_bookings(
            room_id=room_id, building_id=building_id, date=date, booked_by=booked_by
        )
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    return [b.model_dump() for b in bookings]


@mcp.tool
async def get_booking(booking_id: int) -> dict:
    """Get a single booking by its id."""
    try:
        booking = await api_get_booking(booking_id)
    except BookingNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    return booking.model_dump()


@mcp.tool
async def create_booking(
    room_id: int, date: str, start_time: str, end_time: str, booked_by: str
) -> dict:
    """Create a booking for a room. date is yyyy-MM-dd, times are HH:mm."""
    try:
        booking = await api_create_booking(
            room_id=room_id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            booked_by=booked_by,
        )
    except RoomNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    return booking.model_dump()


if __name__ == "__main__":
    mcp.run()
```

Line-by-line, the parts worth understanding:

- **`@mcp.tool` with no arguments** — fastmcp derives the tool's name from the function name and its JSON-schema input from the type hints, the same inference-over-declaration pattern you saw with Ninja's query/body binding on Day 2. No manual schema to write.
- **The docstring is the tool description** — this is what the connected LLM reads to decide when to call the tool and how to fill its arguments. Write these as if a stranger (the LLM, not a teammate) has to understand the tool from the docstring alone, since that's exactly what happens.
- **Return type is `dict`/`list[dict]`, not the `BookingOut` Pydantic model directly** — fastmcp can serialize a `BaseModel` return value directly, but returning the plain `.model_dump()` here keeps today's tool output exactly the same shape you already verified in Day 2's `/api/docs`, which makes cross-checking the two easier while you're still learning the stack. Once you're comfortable, returning the model instance directly works too and is slightly less code.
- **`raise ToolError(...)` for the two handled failure modes** — a missing booking/room, and the Django API being down. `ToolError`'s message is guaranteed to reach the calling LLM verbatim (see fastmcp's `mask_error_details` behavior), which is what turns "the tool silently returned garbage" into "the tool told the LLM exactly what went wrong and it can decide what to do next" — the MCP-layer equivalent of Day 2's `raise HttpError(404, ...)` before an `IntegrityError` could happen.
- **Nothing here calls `print()`.** See §1 — stdout is reserved for the JSON-RPC stream over stdio. fastmcp's own logging already goes to stderr; if you add debug output later, use `import logging` (or fastmcp's logger) rather than `print`, or a stray print statement will corrupt the protocol stream and manifest as a confusing client-side parse error, not an obvious Python exception.

**Ask your AI assistant if you want more depth here:** *"Show me how fastmcp turns a function's type hints into the JSON schema a host sees when it calls tools/list — what happens with a type hint it can't map, like a custom class that isn't a Pydantic model?"*

---

## 6. Run it and verify via the MCP Inspector

The Inspector is a browser-based tool that launches your server as a subprocess and lets you call its tools by hand — the Day 3 analogue of Day 2's `/api/docs` "Try it out" loop, except it speaks MCP instead of REST and needs no separate host application.

From `src/mcp_server/`, with the Django server from §2 still running in its own terminal:

```powershell
uv run fastmcp dev inspector server.py
```

This opens the Inspector in your browser, connected to `server.py` over stdio. Auto-reload is on by default — editing and saving `server.py` or `api_client.py` restarts the connection automatically.

Work through each tool from the Inspector's UI:

1. **`list_bookings`** with no arguments — should return all 4 seeded bookings, same rows Day 2 §7 step 1 verified.
2. **`list_bookings`** with `room_id: 1` — 2 bookings, matching Day 2 §7 step 2.
3. **`get_booking`** with `booking_id: 1` — returns that booking.
4. **`get_booking`** with `booking_id: 999` — confirm a clean tool error with your message ("Booking 999 not found"), not a raw traceback in the Inspector's response panel.
5. **`create_booking`** with a valid payload (e.g. `room_id: 3, date: "2025-08-02", start_time: "11:00", end_time: "12:00", booked_by: "Day 3 test"`) — confirm success, then re-run `list_bookings` and see the new row; cross-check it also shows up in Day 2's `/api/docs` or the Day 1 admin UI — same Postgres row, three different windows onto it.
6. **`create_booking`** with `room_id: 999` — confirm the clean "Room 999 not found" tool error.
7. Stop the Django server (`Ctrl+C` in its terminal) and re-run `list_bookings` — confirm you get the "Could not reach the bookings API" message, not a raw `ConnectError` traceback. Restart the Django server afterward before continuing.

That loop proves the full chain end to end: Inspector → fastmcp (stdio) → httpx → Django Ninja → Postgres, and back.

---

## 7. Connect to Claude Desktop

The Inspector proves the server works; Claude Desktop proves it works from a **real MCP host** — the scenario the whole sprint is building toward.

```powershell
uv run fastmcp install claude-desktop server.py
```

This registers the server in Claude Desktop's config, pointing at `uv run` with this project's dependencies — the same "launch via `uv run` in an isolated environment" approach Claude Desktop uses for any local stdio server, so you don't hand-edit JSON paths yourself. If you'd rather see (or need to hand-adjust) what that command wrote, Claude Desktop's config normally lives at:

```
%APPDATA%\Claude\claude_desktop_config.json
```

**Microsoft Store installs of Claude Desktop use a different path.** `fastmcp` only checks `%APPDATA%\Claude` (that's the `Path.home() / "AppData" / "Roaming" / "Claude"` it hardcodes for Windows). A Store-installed (MSIX) Claude Desktop is sandboxed by Windows and never writes there — instead its config sits under `%LOCALAPPDATA%\Packages\<package-name>\LocalCache\Roaming\Claude`. If `uv run fastmcp install claude-desktop server.py` fails with:

```
Claude Desktop config directory not found.
Please ensure Claude Desktop is installed and has been run at least once to initialize its config.
```

find the real path with:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Packages" -Filter "*Claude*"
```

That prints a folder name like `Claude_pzs8sxrjxfjjc`. Confirm the config lives inside it:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
```

then pass that folder to `fastmcp` explicitly with `--config-path`:

```powershell
uv run fastmcp install claude-desktop server.py --config-path "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
```

(swap `Claude_pzs8sxrjxfjjc` for whatever `Get-ChildItem` found on your machine). `--config-path` tells `fastmcp` to skip its own path guess entirely and read/write `claude_desktop_config.json` in the directory you give it, merging in an `mcpServers` entry alongside whatever else is already there.

Fully restart Claude Desktop (not just close the window — exit from the system tray) so it picks up the new server. Open a conversation, check the tools/plug icon, and confirm `list_bookings`, `get_booking`, and `create_booking` are listed under your server's name.

**As of 08/2026, the tool list isn't visible from the chat's "+" menu.** The "/" slash-command menu is for prompts, not MCP tools — tools are invoked automatically by the model based on your prompt, not picked manually. To actually see and confirm the three tools registered: in the Claude Desktop app, go to **Settings → Connectors → Bookings MCP Server**; that's where `list_bookings`, `get_booking`, and `create_booking` are listed (with per-tool enable toggles). 

With the Django server still running, try a real prompt, e.g.:

> "What bookings exist for Meeting room A?"

Claude Desktop should call `list_bookings` with `room_id: 1` (or discover the id itself if you ask by name — that depends on how much it infers versus asks you to clarify) and answer from the real response. This is the same full-loop proof as §6, just through the actual host application the plan's Day 4 client work builds toward conceptually.

---

## 8. Why error handling stops here today

§5 handles exactly two failure modes: a 404 from the API, and the API being completely unreachable. That's deliberately incomplete — the plan's Day 4 task list calls out a broader pass (malformed tool arguments, DB failures surfacing through the API, other `httpx` failure modes like timeouts) as its own dedicated step, alongside the natural-language client loop that will actually exercise those paths under realistic conditions. Building the full error taxonomy today, before anything has actually triggered most of those failure modes, risks guessing at error shapes instead of designing them around what Day 4's client genuinely produces. Today's two cases were worth handling now because both are trivial to trigger by hand in the Inspector (§6 steps 4, 6, 7) and both map directly to a check Day 2 already made server-side — everything past that waits.

---

## 9. Ruff check

```powershell
# from the workspace root
uv run ruff check .
```

Should report no issues in `server.py` or `api_client.py`. This is real, hand-written app code — same expectation as Day 2 §8, no migrations-style exemption applies here.

---

## 10. End-of-day checklist

- [ ] `src/mcp_server/pyproject.toml` has `fastmcp` and `httpx` as dependencies
- [ ] `api_client.py` exists with `list_bookings`, `get_booking`, `create_booking`, and the two domain exceptions
- [ ] `server.py` exists with `mcp = FastMCP(...)` and all three `@mcp.tool` functions
- [ ] `uv run fastmcp dev inspector server.py` starts cleanly and lists all three tools
- [ ] All 7 Inspector checks in §6 verified, including both `ToolError` paths and the Django-down path
- [ ] `uv run fastmcp install claude-desktop server.py` run, Claude Desktop restarted, tools visible in a conversation
- [ ] At least one real natural-language prompt in Claude Desktop successfully triggered a tool call and returned real Postgres-backed data
- [ ] `uv run ruff check .` runs clean from the workspace root
- [ ] `src/mcp_server/pyproject.toml`, `api_client.py`, `server.py`, and the updated root `uv.lock` are committed

---

## 11. Bridge to Day 4

Tomorrow's client script talks to this same server the way Claude Desktop just did today, except driven by a local Ollama model instead of a hosted Claude conversation, and in a loop rather than one-off prompts. That's also where the fuller error-handling pass from §8 lands — malformed tool arguments, the DB-failure path underneath the API, and the rest of `httpx`'s failure modes (timeouts, non-404 error responses) — now informed by whatever actually broke while wiring up a real client loop today's manual Inspector/Claude Desktop testing wouldn't have surfaced. `README.md` also starts today's `api_client.py`/`server.py` split as its architecture description's second layer, alongside Day 1/2's Django+Postgres layer.
