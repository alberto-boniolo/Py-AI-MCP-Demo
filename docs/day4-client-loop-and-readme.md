# Day 4 — Claude API Client Loop, Error Handling, README

> Companion guide to `python-mcp-4day-plan.md`, `day1-postgres-django-models.md`, `day2-django-ninja-api.md`, and `day3-mcp-server-fastmcp.md`. Today's new code lives in a new workspace member, `src/claude_client/`, plus edits to Day 3's `src/mcp_server/` and Day 1's `config/settings.py`. Written for the same setup: VS Code, `uv`, PowerShell 7, workspace root `Py-AI-MCP-Demo\`.

**A mid-sprint substitution, stated up front:** the original plan (see `python-mcp-4day-plan.md`, Day 4 tasks) called for driving this loop with a local Ollama model on the RTX 4070 machine. Writing this guide, that machine wasn't available — a laptop with no local GPU inference and no path to install/run Ollama today. The Claude API (Anthropic's Messages API) replaces it as today's model backend: same programmatic, fully-scriptable client role Ollama would have played, same manual tool-calling loop you write and own yourself, just a hosted model over HTTPS instead of a local one over a Unix socket. This is a deliberate, reasoned swap, not a scope cut — worth stating plainly in the README too (§10), since "why Claude API and not Ollama here" is a legitimate interview question this project should already have a crisp answer to.

---

## 0. Objective for today

By the end of Day 4 you will have:

1. A real Claude API conversation, held from Python, that calls Day 3's MCP tools to answer natural-language questions against the Postgres-backed data.
2. The fuller error-handling pass Day 3 §8 deliberately deferred — a non-404 failure from Django (DB down, 500) and a timeout, both turned into actionable tool errors instead of raw tracebacks.
3. Structured JSON logging on stdout/stderr across all three processes (Django, the MCP server, the Claude API client), correlated where the two remote processes actually talk to each other (MCP → Django).
4. A complete, interview-ready `README.md`, including the documented-but-not-built auth/authz section and a C#/MAF vs. Python/Django/fastmcp reflection.

**Definition of done:** a live terminal session where you type a question in English (e.g. "What's booked in Meeting room A?"), Claude calls one or more MCP tools, and you get back a real, Postgres-backed answer — with `README.md` complete and the repo pushed to GitHub.

**A boundary decision worth stating up front:** the client you're building today is a **second MCP client**, not a replacement for Claude Desktop from Day 3. Claude Desktop proved the server works with a real, polished MCP host; today's script proves the same server works driven by a loop you fully control end to end — the request/response cycle, the tool-call round trip, the error handling — rather than a GUI host managing all of that for you. Both talk to the exact same `server.py` — nothing in `mcp_server` changes to support a second client, only to fix the two error-handling gaps in point 2 above.

---

## 1. Mental model before you type anything

| .NET/C# concept | Today's Python equivalent | Notes |
|---|---|---|
| A hand-rolled console client calling an internal API, `HttpClient` + a loop reading `Console.ReadLine()` | `client.py` in `src/claude_client/`, reading `input()` in a `while` loop | Same shape — no framework here either, just a loop |
| Calling Azure AI Foundry / MAF's model client with a tool/function list attached to the request | `anthropic.AsyncAnthropic().messages.create(model=..., messages=..., tools=[...])` | Same idea: the tool list rides along on every request; the model decides whether to use one |
| MAF's own MCP client plumbing, wrapping an `McpClientTool` for the model | `fastmcp.Client("server.py")` (the same package Day 3 used server-side; `fastmcp` ships a client too) | One package, two roles — server and client — the same way `Microsoft.Extensions.AI` gives you both server- and client-side MCP support from one package family |
| Manually mapping an OpenAPI/function schema into the shape a model's function-calling API expects | Renaming one key: MCP's `Tool.inputSchema` becomes Anthropic's `input_schema` field, `name`/`description` pass straight through | Anthropic's tool shape (`{"name", "description", "input_schema"}`) is a flatter, closer match to MCP's own `Tool` shape than most providers' nested `{"type": "function", "function": {...}}` wrapper — today's bridge is a rename, not a reshape |
| `ModelState.IsValid` / a `[FromBody]` DTO's automatic `400` | fastmcp validates a tool call's arguments against the same JSON Schema it published, *before* your function body runs, and raises `ValidationError` if they don't match | Same "type hint is the contract" story you already saw with Ninja's automatic `422` on Day 2 — nothing to build for "malformed tool arguments," see §5 |
| Serilog's `LogContext.PushProperty("CorrelationId", id)` enriching every log line for a request | a `contextvars.ContextVar` read by a custom `logging.Filter` in Django; an explicit `extra={"request_id": ...}` per call in the MCP server and client | Python's stdlib `logging` has no built-in context-scoped enrichment like Serilog's `LogContext` — you wire the equivalent yourself with `contextvars`, see §6 |
| `return NotFound()` mapped by a custom `ExceptionFilter` to a typed problem-details response | Anthropic's typed exception hierarchy (`anthropic.RateLimitError`, `anthropic.APIConnectionError`, `anthropic.APIStatusError`, ...) | Worth catching most-specific-first, same discipline as a C# `catch` chain ordered from derived to base — see §8 |

Structural things that are genuinely different, not just renamed:

- **The model decides when to call a tool, not your code.** Everything before today had you writing the call site (`GET /api/bookings?...`, `client.call_tool("list_bookings", {...})` by hand in the Inspector). Today, for the first time, *Claude's response* tells you which tool to call and with what arguments — your loop's job is just to execute what was asked for and hand the result back.
- **A "conversation" is just a growing `messages` list you resend every turn.** There's no session object on the wire — the Messages API is stateless per call; the entire history, including prior tool calls and their results, rides along in `messages` on every request. This is the same statelessness `BookingApi`'s `ConversationSession` exists to work around across HTTP requests — today's script sidesteps it by being one long-running process, exactly as flagged as deliberately out of scope back in Day 1 §0.
- **A tool result isn't a plain string message — it's a typed block that must reference the call it answers.** Ollama-style tool-calling APIs let you get away with a loose `{"role": "tool", "content": "..."}`. Anthropic's `tool_result` content block carries an explicit `tool_use_id` that must match the `id` on the `tool_use` block it answers, and — when a turn produced more than one tool call — *all* of that turn's results must be batched into a **single** user message, not one message per result. Getting this wrong doesn't error loudly; it quietly degrades Claude's willingness to make parallel tool calls on later turns. §8 builds this correctly from the start.
- **Two different stdout rules, for two different reasons.** `mcp_server/server.py` must never write structured logs to stdout — Day 3 §1 already covered why (it'd corrupt the JSON-RPC stream). Today's `client.py` *could* safely write logs to stdout — nothing else owns that stream for this process — but you'll still route them to stderr, for the ordinary reason of not interleaving JSON log lines with the human-readable chat transcript you're trying to read live.
- **Every call now costs real money and a real network round trip.** Ollama's local inference was free and offline; the Claude API is neither. Nothing about today's loop changes for that reason, but it's worth designing the manual test pass in §9 as a short, deliberate list of prompts rather than open-ended exploration — the same instinct as being deliberate about test-suite runs against a metered cloud resource.

**Ask your AI assistant if you want more depth here:** *"Anthropic's tool_result blocks require batching multiple results into one message — why does splitting them across separate messages actually degrade the model's future tool-calling behavior, not just look wrong?"*

---

## 2. Prerequisites check

All three earlier pieces need to be up, since today's client is a client of the MCP server, which is a client of Django:

```powershell
docker compose ps
```

Should show `bookings-postgres` running. If not, `docker compose up -d` from the workspace root.

```powershell
cd src\django_api
uv run python manage.py runserver
```

Confirm `/api/docs` still loads and returns the seeded bookings. Leave this running in its own terminal for the rest of today.

**An Anthropic API key.** Confirm you have one and it's reachable from this environment — it does *not* need to live in the shell's environment variables permanently; today's client loads it from a `.env` file (§4):

```powershell
notepad .env
```

Add (or confirm) a line:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is already gitignored from Day 1 §16 — never commit a real key. `.env.example` (already in the repo, currently empty) is the right place to document the *name* of the variable without its value; add `ANTHROPIC_API_KEY=` there as a template line for anyone else cloning the repo.

Quick sanity check that the key actually works, before wiring MCP into the loop — isolates "is my Anthropic account even reachable" from "is my tool-calling code wrong" if something breaks later:

```powershell
cd src\claude_client
uv run python -c "
import anthropic
client = anthropic.Anthropic()
msg = client.messages.create(model='claude-opus-5', max_tokens=32, messages=[{'role': 'user', 'content': 'Say hello in five words.'}])
print(msg.content[0].text)
"
```

(This only works after §4 creates `src/claude_client/` and adds `anthropic` as a dependency — come back to this check once that's done if you're reading top-to-bottom.)

---

## 3. Where the new files live

```
src/
├── django_api/        (Day 1/2 — gets one new file + a settings.py edit today)
│   └── config/
│       ├── settings.py          (edited — LOGGING dict added)
│       └── logging_ext.py        ← new: JSON formatter, request-id filter, middleware
├── mcp_server/         (Day 3 — gets two edits today, no new files)
│   ├── api_client.py    (edited — broader httpx error handling)
│   └── server.py         (edited — logging, new exception mappings)
└── claude_client/      ← new workspace member, created today
    ├── pyproject.toml
    ├── .env             (gitignored — holds ANTHROPIC_API_KEY; see §2)
    └── client.py
```

`src/claude_client/` wasn't reserved back on Day 1 the way `mcp_server` was, and that's fine — Day 1 §3's reservation trick only matters for members whose *existence* was already decided before their content; today's member is genuinely new, decided today (and, per the note at the top of this guide, decided differently than the original plan), so there's no folder-churn risk to plan around. The workspace root's `[tool.uv.workspace] members = ["src/*"]` glob picks it up automatically the same way it did `django_api` and `mcp_server`.

---

## 4. Create the `claude_client` workspace member

```powershell
mkdir src\claude_client
cd src\claude_client
uv init --no-package --name claude-client
Remove-Item .\main.py
uv add anthropic fastmcp python-dotenv
```

Same `--no-package` flat-layout choice as `django_api` and `mcp_server` — this is an application entry point, not a library. `fastmcp` is added here too, in its **client** role this time (`from fastmcp import Client`) — same package Day 3 used server-side, a different import path within it. `python-dotenv` is new: the Anthropic SDK reads `ANTHROPIC_API_KEY` straight from the process environment (no config-file support of its own), so `python-dotenv`'s `load_dotenv()` is what actually gets your `.env` file's contents *into* that environment at process start — the closest analog to `dotnet`'s user-secrets / `appsettings.Development.json` loading being handled by the framework instead of by hand.

Create `src/claude_client/.env` per §2 (or move the one you already created there).

---

## 5. Finish Day 3's deferred error handling

Day 3 §8 explicitly punted two failure modes to today: a non-404 failure from Django (a DB outage surfacing as a 500, or any other unhandled server error), and `httpx` timing out instead of connecting cleanly. Both get added to `api_client.py` now, informed by nothing more exotic than "what else can `httpx` raise here" — no need to invent hypothetical failure shapes. **Nothing in this section depends on which model backend drives the client** — it's fixing `mcp_server`, which Day 3 already proved works identically with Claude Desktop and will work identically with today's Claude-API-driven client.

**What's *not* being added, on purpose:** a blanket `except Exception` catch-all in each tool function. fastmcp already has a sensible default for a genuinely unexpected exception — it logs the real error server-side and returns the caller a generic, masked message (`mask_error_details`, mentioned in Day 3 §1) rather than leaking internals. That's the correct behavior for "something no one anticipated," and duplicating it with your own catch-all per tool would just be defensive code protecting against nothing new. Today's additions are for two *specific, real, reachable* failure modes — not a hedge against the unknown.

**What's also not being added:** anything for "malformed tool arguments." That failure mode from the plan's Day 4 task list is already handled — by the framework, not by you. Before your tool function body ever runs, fastmcp validates the incoming arguments against the exact JSON Schema it published for that tool (the same schema built from your type hints) and raises a `ValidationError` if they don't match, the same "type hint is the contract, invalid input never reaches your code" story as Ninja's automatic `422` on Day 2. You'll see this in action in §9 when Claude occasionally sends a slightly wrong argument shape and the conversation self-corrects instead of your Python code needing to catch anything.

Edit `api_client.py`:

```python
# api_client.py — additions to what Day 3 wrote
class ApiError(Exception):
    """A non-404 error response from the bookings API (e.g. a 500 from a DB failure)."""


class ApiTimeoutError(Exception):
    """The bookings API didn't respond in time."""
```

Then, in each of the three functions, wrap the request the same way — shown here for `get_booking`, apply the same shape to `list_bookings` and `create_booking`:

```python
async def get_booking(booking_id: int) -> BookingOut:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5.0) as client:
        try:
            response = await client.get(f"/bookings/{booking_id}")
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError("The bookings API took too long to respond") from exc

        if response.status_code == 404:
            raise BookingNotFoundError(booking_id)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(
                f"Bookings API returned {response.status_code}: {response.text[:200]}"
            ) from exc

        return BookingOut(**response.json())
```

Notes:

- **`timeout=5.0` is new** — Day 3's client had no explicit timeout, so `httpx`'s own default (also finite, but worth pinning explicitly here since today's whole point is reasoning about the timeout path) applies. Pinning it makes the behavior deterministic and documented, not "whatever `httpx` currently defaults to."
- **`raise_for_status()` moved inside its own `try`** — Day 3 already called it unconditionally after the 404 check; today it's wrapped so a 500 (or any other non-404 error status) becomes your own `ApiError` with the response body attached, instead of an opaque `HTTPStatusError` that `server.py` would have to know `httpx`-specific details to unpack.
- **`response.text[:200]`** — enough of a Django error page or DRF-style error body to be useful in a log line, short enough not to dump an entire HTML 500 page into a tool error message an LLM might echo back to a user.

Now update `server.py` to map both new exceptions to `ToolError`, alongside the existing ones — shown for `get_booking`, same pattern applies to the other two:

```python
@mcp.tool
async def get_booking(booking_id: int) -> dict:
    """Get a single booking by its id."""
    try:
        booking = await api_get_booking(booking_id)
    except BookingNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except ApiTimeoutError as exc:
        raise ToolError(str(exc)) from exc
    except ApiError as exc:
        raise ToolError(f"The bookings API returned an error: {exc}") from exc
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    return booking.model_dump()
```

**Verify by hand before moving on** — same "trigger it for real" discipline as Day 3 §6:

1. Stop `docker compose stop postgres` (leave Django running) and call any tool from the Inspector (`uv run fastmcp dev inspector server.py` from `src/mcp_server/`, same command as Day 3 §6). Django's own DB connection fails, Ninja surfaces a 500, and you should see your new `ApiError`'s message in the Inspector — not a raw traceback. Restart Postgres afterward (`docker compose start postgres`).
2. The timeout path is legitimately harder to trigger by hand without artificially slowing something down — trust the symmetry with the 404/`ConnectError` precedent Day 3 already proved works, rather than manufacturing an artificial delay just to exercise it today.

---

## 6. Structured logging across all three processes

The plan calls for a shared identifier that traces one request across Django, the MCP server, and the client — the same problem your OpenTelemetry work on `BookingApi` solves, scaled down to "just make the log lines correlatable," not a full tracing stack.

**Where the identifier can actually cross a process boundary — and where it can't, honestly.** MCP → Django is a real network call (`httpx` over HTTP), so an id can ride along as a header, the same way a `traceparent` header would. Client → MCP server is a local **stdio** pipe, not HTTP — there's no header to attach it to at that layer without reaching into MCP's lower-level `_meta` protocol field, which isn't something today's `fastmcp.Client` surface exposes simply. Rather than force an inaccurate abstraction, today's design uses two identifiers with an honest scope each:

| Identifier | Scope | Where it's set |
|---|---|---|
| `session_id` | one whole run of `client.py`, logged on every client-side log line | generated once at startup in `client.py` |
| `request_id` | one MCP tool call → its downstream Django API call, shared by both | fastmcp's own `ctx.request_id` (already assigned per call by the framework), forwarded to Django as an `X-Request-Id` header |

That's a real, followable trace for the hop that matters most (MCP → Django, the one that could actually fail independently), plus an honest per-run id at the client — not a fabricated single id pretending to span a boundary that doesn't carry one today.

### 6.1 A shared JSON formatter

Both `mcp_server` and `claude_client` want the same tiny formatter. Rather than a shared package (real overhead for two ~15-line classes in a 4-day sprint), duplicate it — the same "deliberate duplication at a process boundary" call Day 3 §0 already made for the `BookingOut` models:

```python
# logging_setup.py — add this file to both src/mcp_server/ and src/claude_client/
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id is not None:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
```

`sys.stderr` here for **two different reasons**, per §1: in `mcp_server`, it's mandatory (stdout is the JSON-RPC stream); in `claude_client`, it's a readability choice (keeps JSON log lines out of the human chat transcript on stdout). Same code, different justification — worth actually understanding both, not just copying the pattern.

### 6.2 Wire it into `server.py`

```python
# server.py — additions
from logging_setup import configure_logging
from fastmcp.server.context import Context

logger = configure_logging("mcp_server")
```

Then in each tool, accept a `Context` parameter (fastmcp injects it automatically — see §1's Ninja-schema-validation parallel; injected parameters like this are excluded from the tool's published schema, so the model calling this tool never sees or has to fill in `ctx`) and pass its `request_id` both into your log calls and down into `api_client.py`:

```python
@mcp.tool
async def get_booking(booking_id: int, ctx: Context) -> dict:
    """Get a single booking by its id."""
    logger.info("tool_call_start", extra={"request_id": ctx.request_id})
    try:
        booking = await api_get_booking(booking_id, request_id=ctx.request_id)
    except BookingNotFoundError as exc:
        raise ToolError(str(exc)) from exc
    except ApiTimeoutError as exc:
        raise ToolError(str(exc)) from exc
    except ApiError as exc:
        raise ToolError(f"The bookings API returned an error: {exc}") from exc
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    logger.info("tool_call_ok", extra={"request_id": ctx.request_id})
    return booking.model_dump()
```

Apply the same `ctx: Context` parameter and `request_id=ctx.request_id` pass-through to `list_bookings` and `create_booking`.

### 6.3 Forward the id in `api_client.py`

Each function gets one new keyword-only parameter and one new header:

```python
async def get_booking(booking_id: int, *, request_id: str | None = None) -> BookingOut:
    headers = {"X-Request-Id": request_id} if request_id else {}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5.0, headers=headers) as client:
        ...
```

### 6.4 Django's side: `config/logging_ext.py`

```python
# config/logging_ext.py
import contextvars
import json
import logging
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:8]
        token = request_id_var.set(incoming)
        try:
            return self.get_response(request)
        finally:
            request_id_var.reset(token)
```

This is the `contextvars`-based equivalent of Serilog's `LogContext.PushProperty` flagged in §1 — Django (and Python's stdlib `logging` generally) has no built-in request-scoped log enrichment, so the middleware + filter pair *is* the wiring, not a shortcut around it. `contextvars` (rather than a plain module-level global) matters specifically because Django can serve requests concurrently under ASGI — a plain global would leak one request's id into another's log lines under concurrent load; a `ContextVar` is isolated per async task/thread the same way `AsyncLocal<T>` is in .NET.

Wire it into `config/settings.py`:

```python
# config/settings.py — add to MIDDLEWARE, right after SecurityMiddleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'config.logging_ext.RequestIdMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # ...unchanged from here down
]

# config/settings.py — new section
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "config.logging_ext.RequestIdFilter"},
    },
    "formatters": {
        "json": {"()": "config.logging_ext.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
```

`LOGGING` is Django's dict-based config — the direct analog of Serilog's fluent `LoggerConfiguration`, just declarative instead of chained method calls, per the plan's own framing. `disable_existing_loggers: False` matters: Django registers its own loggers (`django.request`, `django.db.backends`, etc.) before your `LOGGING` dict is applied, and the default `True` would silently kill them.

**Verify:** restart everything (`docker compose up -d`, then Django's `runserver`, then the MCP Inspector or Day 3 Claude Desktop connection) and confirm `manage.py runserver`'s console output is now JSON lines, each with a `request_id` — and that a request driven through the MCP server shows the *same* `request_id` on both the Django console and (via your new `logger.info` calls) the MCP server's stderr output.

**Ask your AI assistant if you want more depth here:** *"Why does a ContextVar-based request id survive correctly under Django's ASGI async request handling, when a plain module-level variable wouldn't?"*

---

## 7. Bridge MCP tool schemas into Anthropic's tool format

MCP's `Tool` shape and Anthropic's tool shape are close enough that this is a field rename, not a reshape (§1):

```python
# client.py — first part
def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in mcp_tools
    ]
```

If your installed `fastmcp` version names that attribute something other than `inputSchema` on the object `list_tools()` returns, a quick `print(vars(mcp_tools[0]))` (or your editor's autocomplete on the `Tool` type) will show you the real field name — MCP's wire format calls it `inputSchema`, but don't take that as gospel against whatever version you actually have installed.

---

## 8. Build the chat loop

```python
# client.py — full file
import asyncio
import json
import uuid

import anthropic
from dotenv import load_dotenv
from fastmcp import Client

from logging_setup import configure_logging

load_dotenv()

MCP_SERVER_SCRIPT = "../mcp_server/server.py"
MODEL = "claude-opus-5"
MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You are a helpful assistant for a room-booking system. "
    "Use the available tools to answer questions about bookings, rooms, and buildings. "
    "Always call a tool to look up real data rather than guessing ids, dates, or names."
)

logger = configure_logging("claude_client")


def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in mcp_tools
    ]


async def run_chat_loop() -> None:
    session_id = uuid.uuid4().hex[:8]
    logger.info("session_start", extra={"request_id": session_id})

    claude = anthropic.AsyncAnthropic()

    async with Client(MCP_SERVER_SCRIPT) as mcp_client:
        mcp_tools = await mcp_client.list_tools()
        tools = mcp_tools_to_anthropic(mcp_tools)
        tool_names = {tool.name for tool in mcp_tools}

        messages: list[dict] = []
        print("Bookings assistant ready. Type a question, or 'exit' to quit.\n")

        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            try:
                response = await claude.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
            except anthropic.APIConnectionError:
                print("\nCould not reach the Claude API — check your network connection.\n")
                logger.warning("api_connect_error", extra={"request_id": session_id})
                messages.pop()  # drop the unanswered turn so the next attempt isn't corrupted
                continue
            except anthropic.RateLimitError:
                print("\nRate limited by the Claude API — wait a moment and try again.\n")
                logger.warning("api_rate_limited", extra={"request_id": session_id})
                messages.pop()
                continue

            messages.append({"role": "assistant", "content": response.content})

            while response.stop_reason == "tool_use":
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                tool_results = []

                for call in tool_use_blocks:
                    if call.name not in tool_names:
                        content = f"Unknown tool requested: {call.name}"
                        is_error = True
                        logger.warning("unknown_tool", extra={"request_id": session_id})
                    else:
                        try:
                            result = await mcp_client.call_tool(call.name, call.input)
                            content = json.dumps(result.data)
                            is_error = False
                            logger.info("tool_call_ok", extra={"request_id": session_id})
                        except Exception as exc:  # ToolError, ValidationError, etc.
                            content = f"Tool error: {exc}"
                            is_error = True
                            logger.warning(
                                "tool_call_failed", extra={"request_id": session_id}
                            )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": content,
                            "is_error": is_error,
                        }
                    )

                # All of this turn's results in ONE user message — see §1's pitfall note
                messages.append({"role": "user", "content": tool_results})

                response = await claude.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": response.content})

            final_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print(f"\nAssistant: {final_text}\n")


if __name__ == "__main__":
    asyncio.run(run_chat_loop())
```

Line-by-line, the parts worth understanding rather than just copying:

- **`except Exception as exc` around `call_tool`, not a narrower type** — unlike `server.py`'s precise exception mapping in §5, this is the one deliberately broad catch in today's whole build. The reason it's fine here and wasn't in §5: this is the *last* place in the whole chain, not an internal layer hiding detail from something upstream. Whatever comes out of `call_tool` — a `ToolError` from your own mapping, a `ValidationError` from a malformed argument, a transport-level error — the right move for a conversational loop is the same in every case: report it back as a `tool_result` with `is_error: True` and let Claude decide whether to apologize, retry with different arguments, or ask you for clarification. That's a UX decision (let the conversation self-correct), not error-handling laziness.
- **`is_error: True` on the `tool_result` block, not just an error string embedded in `content`** — this is a first-class part of Anthropic's tool-result shape (§1), not a convention you're inventing. It tells the model unambiguously "this tool call failed" versus "this tool call succeeded and its answer happens to contain the word error."
- **`messages.append({"role": "assistant", "content": response.content})` after every `create()` call, including ones with tool calls** — Claude's own response content (containing the `tool_use` blocks) has to go back into history verbatim before you can append the corresponding `tool_result` blocks, or the next `create()` call is missing the turn that justifies those results being there. Skipping this is the most common way this loop silently produces a `400` about a dangling `tool_result`.
- **All of one turn's `tool_result` blocks batched into a single `{"role": "user", ...}` message** — per §1's pitfall, sending them as separate messages doesn't error, it just quietly makes Claude less likely to make parallel tool calls on later turns. Worth deliberately testing a prompt that should trigger two tool calls in one turn (§9) to see this work correctly.
- **`while response.stop_reason == "tool_use":`, not a single `if`** — a single question can legitimately need more than one tool call before Claude has enough to answer (e.g. "what's booked in Milan HQ's rooms tomorrow" might resolve building → rooms → bookings across turns, depending on how the model decides to break it down). Looping until `stop_reason` stops being `"tool_use"` mirrors the multi-turn tool-use pattern, condensed into one conversational turn instead of spanning multiple user messages.
- **`messages.pop()` in the connection-error and rate-limit `except` blocks** — without it, the user message you just appended sits in history with no matching assistant turn, and the *next* successful request would look like two consecutive user messages (allowed by the API, but not what actually happened) rather than a clean retry of the same question.
- **No separate `try`/`except` around the `Client(...)` connection itself** — if `server.py` fails to even start (a syntax error, a missing dependency), `fastmcp.Client`'s `async with` block raises immediately and loudly on startup, before any conversation begins. That's the right failure mode for a startup-time problem — surfacing it as a garbled in-conversation tool error would only hide *when* things actually broke.
- **`MODEL = "claude-opus-5"`** — the strongest available model, used here so the tool-calling logic itself is never in question while you're debugging the loop. Once the loop is verified working (§9), swapping to `claude-sonnet-5` for cheaper/faster iterative testing is a reasonable choice — that's your call to make deliberately based on cost/quality tradeoffs for this small a task, not something to default into silently.

**Ask your AI assistant if you want more depth here:** *"Walk through why the tool-call loop needs response.content appended to history verbatim on the turn that contains tool_use blocks, not just the final text answer — what actually breaks in the next request if I only store the text?"*

---

## 9. Run the end-to-end demo

With Postgres and Django up (§2), from `src/claude_client/`:

```powershell
uv run python client.py
```

Work through a few prompts, cross-checking against what you already know is in the seeded data (Day 1 §14). Keep this list short and deliberate (§1) — each turn is a real, billed API call:

1. `"List all bookings."` — should trigger `list_bookings` with no filters, all 4+ rows come back.
2. `"What's booked in Meeting room A?"` — should trigger `list_bookings` with `room_id: 1` (or Claude may ask a clarifying question first if it isn't confident which room that name maps to — either behavior is legitimate, not a bug in your loop).
3. `"Book Room 101 for a client demo on 2025-08-10 from 14:00 to 15:00, booked by Alberto."` — should trigger `create_booking`; confirm the new row via Day 2's `/api/docs` or the Day 1 admin UI afterward.
4. `"What's booked in room 999?"` — should trigger `get_booking` or `list_bookings` with an id that doesn't exist, surface your `ToolError` message through the `tool_result`'s `is_error: True` path, and Claude should explain the room doesn't exist rather than fabricating an answer.
5. `"What's booked in Milan HQ, and separately, what's booked in Building B?"` — a good candidate for two tool calls in a single turn (parallel `list_bookings` calls, or a `list_bookings` plus a follow-up), exercising the "batch all of one turn's results into one message" path from §8.
6. Stop `docker compose stop postgres`, ask any booking question, confirm Claude reports the API is unreachable (via your Day 3 `ConnectError` → `ToolError` mapping, surfaced as `is_error: True`) instead of the script hanging or crashing. Restart Postgres afterward.

That loop is the actual proof the plan's Day 4 objective describes: prompt → tool call → real Postgres data → answer, with both failure paths degrading gracefully instead of crashing.

---

## 10. Write the README

`README.md` currently only has the two placeholder bullets from repo init. Replace it with the real one — this is the portfolio artifact, so write it as if a hiring manager will read it without any of today's context.

Sections to cover (content, not exact headers — write these in your own words, informed by what you actually built and any surprises along the way):

1. **What this is.** One paragraph: a Python-native sibling to `BookingApi` (link it if this repo is public alongside it), same bookings domain, built to prove direct Django/MCP fluency rather than proxying to the existing C# API.
2. **Architecture.** Django Ninja + Postgres (Days 1–2) → `fastmcp` MCP server over stdio (Day 3) → a Claude-API-driven client *or* Claude Desktop as the MCP host (Day 3 §7, Day 4). A short diagram (even ASCII) showing the four processes and which ones talk to which — Postgres ← Django ← (`httpx`) ← `mcp_server` ← (stdio) ← `claude_client` / Claude Desktop.
3. **Why the Claude API and not Ollama for the client loop.** State the substitution from the top of this guide plainly and briefly: the original design targeted a local Ollama model on a specific machine; this build used the Claude API instead for environment reasons (no local GPU inference available at the time), and the loop's actual design — schema bridging, the tool-call round trip, error handling — is portable to a local model with only the model-client call site changing. That portability claim is worth being honest and specific about, not hand-wavy.
4. **How to run it locally**, in order: `docker compose up -d` → `uv run python manage.py migrate` (first run only) → `uv run python manage.py runserver` in one terminal → `uv run python client.py` from `src/claude_client/` in another (needs `ANTHROPIC_API_KEY` in `src/claude_client/.env`) — or the Day 3 §7 Claude Desktop connection instead.
5. **The auth/authz section — documented, not implemented.** This is a deliberate scope decision from the plan document, not an oversight, and it's worth stating that explicitly. Cover, in your own words:
   - MCP servers act as OAuth 2.1 **resource servers**, never as the authorization server themselves — per the current MCP spec, a server validates tokens, it doesn't mint them.
   - Why authorization is explicitly out of scope *for stdio* specifically — the spec treats a local stdio process as already inside a trusted boundary (whoever can launch your subprocess already has your permissions), which is exactly why nothing in Days 1–4 needed to touch it.
   - The **confused-deputy risk**: an MCP server naively forwarding a client's own token to a downstream API can end up acting with more authority than the calling context should have, or against the wrong resource entirely — worth a sentence on why "just pass the token through" isn't automatically safe once a remote transport is in play.
   - **Elicitation** as the spec's mechanism for a tool to pause mid-call and prompt the human for a missing credential or an explicit consent, rather than silently failing or silently proceeding.
   - A forward-looking note on the **Entra ID → legacy-system identity-mapping pattern** (a mapping store + a credential vault + the legacy system remaining the actual authorization source of truth) as the shape a real enterprise version of this project — one with an actual legacy system behind it — would need. Flag plainly that it doesn't apply here (no legacy system in this project) and is included for completeness against prior discussion, not as a "coming soon."
6. **A comparative reflection: C#/MAF vs. Python/Django/fastmcp.** This is the part only you can write — pull from what actually surprised you across the four days (candidates worth considering, not a checklist to fill mechanically): Django's implicit model discovery vs. `DbSet<T>` being explicit; `on_delete` being mandatory everywhere vs. EF Core's convention; `uv`'s workspace model vs. a `.sln`; Ninja's binding-by-inference vs. attribute-driven binding in ASP.NET; fastmcp's `Context` injection being schema-invisible; writing your own manual tool-call loop against the raw Messages API vs. MAF's higher-level `McpClientTool` plumbing doing more of that for you; what felt like *less* ceremony in Python and what felt like it was missing real tooling maturity (e.g. no built-in linter/analyzer parity until you added Ruff yourself on Day 1 §6, no `LogContext`-equivalent enrichment for `logging` until you wired one by hand today).

**Ask your AI assistant if you want more depth here:** *"What's a good structure for a portfolio README that needs to read well both to a technical interviewer skimming it in two minutes and to someone who clones the repo and actually runs it?"*

---

## 11. Ruff check

```powershell
# from the workspace root
uv run ruff check .
```

Should report no issues across `client.py`, the edited `api_client.py`/`server.py`, and `config/logging_ext.py`. All hand-written app code — same expectation as Days 2–3, no exemption applies.

---

## 12. End-of-day checklist

- [ ] `src/claude_client/pyproject.toml` has `anthropic`, `fastmcp`, and `python-dotenv` as dependencies
- [ ] `src/claude_client/.env` holds a real `ANTHROPIC_API_KEY`; `.env.example` documents the variable name only
- [ ] `client.py` runs, discovers all three MCP tools, and holds a multi-turn conversation
- [ ] All 6 demo prompts in §9 verified, including both failure paths (missing id, Django unreachable) and the two-tool-calls-in-one-turn case
- [ ] `api_client.py` has `ApiError`/`ApiTimeoutError` and pinned `timeout=5.0`; `server.py` maps both to `ToolError`
- [ ] §5's DB-down scenario manually triggered and confirmed to surface as a clean tool error, not a traceback
- [ ] `logging_setup.py` exists in both `mcp_server` and `claude_client`; both processes emit JSON log lines to stderr
- [ ] `config/logging_ext.py` exists; Django's console output is JSON with a `request_id` field
- [ ] A single `request_id` confirmed present on both the Django console and the MCP server's stderr for the same tool call
- [ ] `README.md` covers: what this is, architecture, the Ollama→Claude API substitution and why, how to run it, the documented auth/authz section, and the comparative reflection
- [ ] `uv run ruff check .` runs clean from the workspace root
- [ ] Everything committed: `src/claude_client/` (excluding `.env`), the `mcp_server`/`django_api` edits, `README.md`, updated `.env.example`, updated root `uv.lock`
- [ ] Repo pushed to GitHub

---

## 13. Looking back at the sprint

Four days ago this was an empty workspace; now it's Postgres-backed Django Ninja API, wrapped by a real `fastmcp` MCP server, driven by both a hosted GUI client (Claude Desktop) and a fully scripted one (today's Claude-API loop) — the same full loop the plan document set out to prove, end to end, twice, with two different kinds of model client. The one deliberate deviation from the plan — Claude API instead of a local Ollama model, forced by not having access to the GPU machine — is exactly the kind of real-world constraint worth narrating honestly in an interview rather than glossing over; the loop you wrote is the same loop that would run against Ollama with one call site swapped. The stretch goals list in `python-mcp-4day-plan.md` (MCP resources/prompts beyond tools, a minimal bearer-token proof-of-concept over Streamable HTTP, containerizing the whole stack, a later separate pass at Django REST Framework, and — now genuinely worth adding to that list — actually running this same client against a local Ollama model once back on the RTX 4070 machine, to close the loop on the original plan) is exactly that — stretch, not a gap in what was promised. Everything in this sprint's actual definition of done is what today's checklist just verified.
