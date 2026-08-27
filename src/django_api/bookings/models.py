# bookings/models.py
from django.db import models


class Building(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    name = models.CharField(max_length=200)
    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="rooms"
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.building.name})"


class Booking(models.Model):
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="bookings"
    )

    # Stored as strings to match the C# BookingApi tool-layer boundary
    # (see Booking.cs) — the MCP tools on Day 3 will receive/return these
    # the same shape, so keeping the representation consistent here avoids
    # a translation layer between the two sibling projects.
    date = models.CharField(max_length=10)        # yyyy-MM-dd
    start_time = models.CharField(max_length=5)    # HH:mm
    end_time = models.CharField(max_length=5)       # HH:mm
    booked_by = models.CharField(max_length=200)

    def __str__(self) -> str:
        return f"Booking #{self.pk} — {self.room.name} on {self.date}"