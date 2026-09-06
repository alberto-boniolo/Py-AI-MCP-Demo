import httpx
from api_client import ApiError, ApiTimeoutError, BookingNotFoundError
from api_client import (
    create_booking as api_create_booking,
)
from api_client import (
    get_booking as api_get_booking,
)
from api_client import (
    list_bookings as api_list_bookings,
)
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from logging_setup import configure_logging

logger = configure_logging("mcp_server")
mcp = FastMCP("Bookings MCP Server")


@mcp.tool
async def list_bookings(
    room_id: int | None = None,
    building_id: int | None = None,
    date: str | None = None,
    booked_by: str | None = None,
    ctx: Context | None = None,
) -> list[dict]:
    """List bookings, optionally filtered by room, building, date, or who booked it."""
    request_id = ctx.request_id if ctx else None
    logger.info("tool_call_start", extra={"request_id": request_id})
    try:
        bookings = await api_list_bookings(
            room_id=room_id,
            building_id=building_id,
            date=date,
            booked_by=booked_by,
            request_id=request_id,
        )
    except ApiTimeoutError as exc:
        raise ToolError(str(exc)) from exc
    except ApiError as exc:
        raise ToolError(f"The bookings API returned an error: {exc}") from exc
    except httpx.ConnectError as exc:
        raise ToolError(
            "Could not reach the bookings API — is the Django server running?"
        ) from exc
    logger.info("tool_call_ok", extra={"request_id": request_id})
    return [b.model_dump() for b in bookings]


@mcp.tool
async def get_booking(booking_id: int, ctx: Context) -> dict:
    """Get a single booking by its id."""
    request_id = ctx.request_id
    logger.info("tool_call_start", extra={"request_id": request_id})
    try:
        booking = await api_get_booking(booking_id, request_id=request_id)
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
    logger.info("tool_call_ok", extra={"request_id": request_id})
    return booking.model_dump()


@mcp.tool
async def create_booking(
    room_id: int, date: str, start_time: str, end_time: str, booked_by: str, ctx: Context
) -> dict:
    """Create a booking for a room. date is yyyy-MM-dd, times are HH:mm."""
    request_id = ctx.request_id
    logger.info("tool_call_start", extra={"request_id": request_id})
    try:
        booking = await api_create_booking(
            room_id=room_id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            booked_by=booked_by,
            request_id=request_id,
        )
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
    logger.info("tool_call_ok", extra={"request_id": request_id})
    return booking.model_dump()


if __name__ == "__main__":
    mcp.run()