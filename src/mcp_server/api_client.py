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