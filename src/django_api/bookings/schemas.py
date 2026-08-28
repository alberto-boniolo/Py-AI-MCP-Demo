from ninja import Schema


class BuildingOut(Schema):
    id: int
    name: str


class RoomOut(Schema):
    id: int
    name: str
    building_id: int


class BookingOut(Schema):
    id: int
    room_id: int
    date: str
    start_time: str
    end_time: str
    booked_by: str


class BookingCreate(Schema):
    room_id: int
    date: str
    start_time: str
    end_time: str
    booked_by: str