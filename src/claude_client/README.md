# claude_client

A scripted natural language chat loop that pilots [`mcp_server`](../mcp_server/README.md)'s tools via the Anthropic Claude API (Messages API), as a second MCP client alongside Claude Desktop. Proves the same MCP server works end to end under a loop controlled programmatically (request/response cycle, tool call round trip, and error handling), without a GUI host managing everything.

## What's covered here

- **`client.py`**: connects to `mcp_server` over stdio via `fastmcp.Client`, discovers its tools with `list_tools()`, and bridges MCP's `Tool.inputSchema` into Anthropic's `input_schema` tool format (`mcp_tools_to_anthropic`).
- A `while True` REPL loop reading `input()`, holds conversation history in a plain `messages` list since the Messages API is stateless per call.
- A `while response.stop_reason == "tool_use"` inner loop that executes every tool call Claude requests, batches **all** of one turn's `tool_result` blocks into a single user message, and marks failures with `is_error: True` so Claude can self-correct instead of the script crashing.
- Typed error handling for `anthropic.APIConnectionError` and `anthropic.RateLimitError`, and a deliberately broad `except Exception` around each individual tool call, where any failure (a `ToolError` from the MCP server, a `ValidationError` from malformed arguments, a transport error) is reported back into the conversation rather than crashing the loop.
- **Structured JSON logging** (`logging_setup.py`) to stderr, tagged with a `session_id`.

## Packages used

| Package                                                    | Role                                                                                      |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| [`anthropic`](https://pypi.org/project/anthropic/)         | Claude API (Messages API) client                                                          |
| [`fastmcp`](https://pypi.org/project/fastmcp/)             | Used here in its **client** role (`fastmcp.Client`) to connect to `mcp_server` over stdio |
| [`python-dotenv`](https://pypi.org/project/python-dotenv/) | Loads `ANTHROPIC_API_KEY` from a `.env` file into the process environment                 |

(Ruff is used for linting across the whole workspace as a root-level dev dependency — see the root [`pyproject.toml`](../../pyproject.toml).)

## Configuration

Needs `ANTHROPIC_API_KEY` set. Copy the workspace-root [`.env.example`](../../.env.example) to `.env` at the workspace root and fill in a real key — `python-dotenv`'s `load_dotenv()` searches upward from the current directory and finds it there.

## Running

Requires [`django_api`](../django_api/README.md) (and Postgres behind it) running, since `mcp_server`'s tools call it directly — `client.py` launches `mcp_server` itself as a subprocess over stdio, so that doesn't need to be started separately.

Running from root

```powershell
cd src/claude_client/
uv run python client.py
```

Type a question (e.g. `"What's booked in Meeting room A?"`), or `exit`/`quit` to leave the loop.
