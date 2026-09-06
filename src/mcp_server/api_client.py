from typing import Any

import httpx
from pydantic import BaseModel

BASE_URL = "http://127.0.0.1:8000/api"
REQUEST_TIMEOUT_SECONDS = 5.0
ERR_MESSAGE_MAX_CHARS = 200


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


class ApiError(Exception):
    """A non-404 error response from the bookings API (e.g. a 500 from a DB failure)."""


class ApiTimeoutError(Exception):
    """The bookings API didn't respond in time."""


async def list_bookings(
    *,
    room_id: int | None = None,
    building_id: int | None = None,
    date: str | None = None,
    booked_by: str | None = None,
    request_id: str | None = None,
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
    headers = {"X-Request-Id": request_id} if request_id else {}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
        try:
            response = await client.get("/bookings", params=params)
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError("The bookings API took too long to respond") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(
                f"Bookings API returned {response.status_code}: {response.text[:ERR_MESSAGE_MAX_CHARS]}"
            ) from exc

        return [BookingOut(**row) for row in response.json()]



async def get_booking(booking_id: int, *, request_id: str | None = None) -> BookingOut:
    headers = {"X-Request-Id": request_id} if request_id else {}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
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
                f"Bookings API returned {response.status_code}: {response.text[:ERR_MESSAGE_MAX_CHARS]}"
            ) from exc

        return BookingOut(**response.json())


async def create_booking(
    *, room_id: int, date: str, start_time: str, end_time: str, booked_by: str, request_id: str | None = None
) -> BookingOut:
    payload = {
        "room_id": room_id,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "booked_by": booked_by,
    }
    headers = {"X-Request-Id": request_id} if request_id else {}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
        try:
            response = await client.post("/bookings", json=payload)
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError("The bookings API took too long to respond") from exc

        if response.status_code == 404:
            raise RoomNotFoundError(room_id)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(
                f"Bookings API returned {response.status_code}: {response.text[:ERR_MESSAGE_MAX_CHARS]}"
            ) from exc

        return BookingOut(**response.json())