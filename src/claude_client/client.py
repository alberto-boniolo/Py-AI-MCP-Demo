# client.py — full file
import asyncio
import json
import uuid

import anthropic
from anthropic.types import MessageParam, ToolParam
from dotenv import load_dotenv
from fastmcp import Client
from logging_setup import configure_logging

load_dotenv()

MCP_SERVER_SCRIPT = "../mcp_server/server.py"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You are a helpful assistant for a room-booking system. "
    "Use the available tools to answer questions about bookings, rooms, and buildings. "
    "Always call a tool to look up real data rather than guessing ids, dates, or names."
)

logger = configure_logging("claude_client")


def mcp_tools_to_anthropic(mcp_tools) -> list[ToolParam]:
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
        # print(vars(mcp_tools[0])) # DEBUG .inputSchema could change between fastMCP versions
        tools = mcp_tools_to_anthropic(mcp_tools)
        tool_names = {tool.name for tool in mcp_tools}

        messages: list[MessageParam] = []
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
                        except Exception as exc:  # ToolError, ValidationError, etc. It's ok to be a catch all  # noqa: BLE001
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