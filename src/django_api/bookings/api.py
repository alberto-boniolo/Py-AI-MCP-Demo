from http import HTTPStatus

from ninja import Query, Router
from ninja.errors import HttpError

from .models import Booking, Room
from .schemas import BookingCreate, BookingOut

router = Router()


@router.get("/bookings", response=list[BookingOut])
def list_bookings(
    request,
    room_id: int | None = None,
    building_id: int | None = None,
    date: str | None = None,
    booked_by: str | None = Query(  # type: ignore[operator]
        None, description="Case-insensitive contains match"
    ),
):
    qs = Booking.objects.all()

    if room_id is not None:
        qs = qs.filter(room_id=room_id)
    if building_id is not None:
        qs = qs.filter(room__building_id=building_id)
    if date is not None:
        qs = qs.filter(date=date)
    if booked_by is not None:
        qs = qs.filter(booked_by__icontains=booked_by)

    return qs.order_by("id")


@router.get("/bookings/{booking_id}", response=BookingOut)
def get_booking(request, booking_id: int):
    booking = Booking.objects.filter(id=booking_id).first()
    if booking is None:
        raise HttpError(HTTPStatus.NOT_FOUND, f"Booking {booking_id} not found")
    return booking


@router.post("/bookings", response={201: BookingOut})
def create_booking(request, payload: BookingCreate):
    if not Room.objects.filter(id=payload.room_id).exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"Room {payload.room_id} not found")

    booking = Booking.objects.create(**payload.dict())
    return HTTPStatus.CREATED, booking