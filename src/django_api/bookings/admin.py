# bookings/admin.py
from django.contrib import admin

from .models import Booking, Building, Room


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "building")
    list_filter = ("building",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "date", "start_time", "end_time", "booked_by")
    list_filter = ("room",)
    search_fields = ("booked_by",)