# Day 2 — API Layer with Django Ninja

> Companion guide to `python-mcp-4day-plan.md` and `day1-postgres-django-models.md`. Builds directly on yesterday's `Building` → `Room` → `Booking` models — no schema changes today. Written for the same setup: VS Code, `uv`, PowerShell 7, workspace root `Py-AI-MCP-Demo\`.

---

## 0. Objective for today

By the end of Day 2 you will have:

1. A `NinjaAPI` instance mounted at `/api/` inside the existing `django_api` project.
2. Pydantic-backed **schemas** (`bookings/schemas.py`) describing the request/response shapes for `Building`, `Room`, and `Booking`.
3. Three endpoints over `Booking`, matching the original plan's "list / get-by-id / create" shape:
   - `GET /api/bookings` — list, with query-param filters
   - `GET /api/bookings/{booking_id}` — get one, 404 if missing
   - `POST /api/bookings` — create, with request-body validation and an explicit `room_id` existence check
4. Everything verified and exercised through the auto-generated docs at `/api/docs` — no separate REST client needed today.

**Definition of done:** all three endpoints are callable and correct from `/api/docs`, list filters demonstrably narrow results, and an invalid `room_id` on create returns a clean 404 instead of a stack trace or a raw DB `IntegrityError`.

**A deliberate deviation from the plan document, worth stating explicitly so it doesn't cause confusion later:** the original plan describes filtering "orders... across a few cities". This project has no `city` field — it has the two-level `Building → Room` chain from `BookingApi`, seeded yesterday as `Milan HQ` / `Building B`. Today's location-style filter is therefore `building_id`, not `city`. Same intent (demonstrate a query-param filter), different field name — don't go looking for a `city` column, it doesn't exist here.

**Also already done, ahead of the original Day 2 task list:** the "seed script or fixture with realistic sample data" task from the plan was pulled forward into Day 1 as `bookings/migrations/0002_seed_bookings.py` (a data migration — the `RunPython`/`HasData` equivalent mentioned in yesterday's guide). Two buildings, four rooms, four bookings already exist with known ids (1–4) the moment `migrate` has run. Today's endpoints are built and tested against that existing data — nothing to seed today.

---

## 1. Mental model before you type anything

| .NET/C# concept (ASP.NET Web API)                                           | Django Ninja equivalent                                                                            | Notes                                                                                                                                                                                                              |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Program.cs` → `builder.Services.AddControllers()` + `app.MapControllers()` | a `NinjaAPI()` instance, mounted in `urls.py` via `path("api/", api.urls)`                         | One object *is* the whole API surface — no separate DI container step needed for routing itself                                                                                                                    |
| A `[ApiController]` class, one per resource                                 | a `Router()` instance per Django app, added to the `NinjaAPI` with `api.add_router(...)`           | Ninja's `Router` is the grouping unit — closer to "a controller's route table" than to the class itself, since there's no class, just decorated functions                                                          |
| `[HttpGet("orders")]` / `[HttpGet("orders/{id}")]` / `[HttpPost("orders")]` | `@router.get("/bookings")` / `@router.get("/bookings/{booking_id}")` / `@router.post("/bookings")` | Same decorator-over-function shape you already saw with `@admin.register` on Day 1                                                                                                                                 |
| A request DTO class (`record CreateBookingRequest(...)`)                    | a Pydantic `Schema` class in `schemas.py`                                                          | Field types *are* the validation, same principle as Django model fields on Day 1 — no separate `[Required]`/`[Range]` attributes, the type hint (and Pydantic's extra constraint helpers) do that job              |
| `[FromQuery] string? bookedBy` parameter                                    | a plain function parameter with a default, e.g. `booked_by: str \| None = None`                    | Ninja infers "query parameter" for any primitive-typed function argument that isn't part of the URL path — no attribute needed, similar in spirit to ASP.NET's own default query-binding for simple types          |
| `[FromRoute] int id`                                                        | `{booking_id}` in the route string **and** a matching `booking_id: int` function parameter         | The names must match; Ninja binds by parameter name, not by position                                                                                                                                               |
| `[FromBody] CreateBookingRequest body`                                      | a `Schema`-typed function parameter with no default                                                | Ninja infers "this comes from the JSON body" because the parameter's type is a `Schema`, not a primitive — this is the one binding rule most worth internalizing today, since it's *inferred* rather than declared |
| `ModelState.IsValid` check at the top of every action                       | nothing to write — invalid input never reaches your function body                                  | Pydantic validation runs before your code executes; a bad request short-circuits to an automatic `422`                                                                                                             |
| `return NotFound()` / `return BadRequest(...)`                              | `raise HttpError(404, "...")` (from `ninja.errors`)                                                | Exception-based, not return-based — closer to throwing a custom exception type that a middleware maps to a status code                                                                                             |
| Swashbuckle / `/swagger`                                                    | built-in `/api/docs`                                                                               | Ninja generates this from the same type hints and `Schema` classes you already wrote — nothing extra to configure                                                                                                  |
| `services.AddDbContext<T>()` + injected `DbContext` in the controller       | direct `Model.objects` calls inside the endpoint function                                          | No injection step — Django models are globally importable, the ORM manager (`.objects`) is already bound to the configured `DATABASES` connection from Day 1                                                       |

Structural things that are genuinely different, not just renamed:

- **No controller classes.** A Ninja endpoint is a plain function with a decorator — there's no `class BookingsController : ControllerBase` wrapper, and no `this`/`self` to reach for shared state (there isn't any per-request state to share; each function call is independent).
- **Binding source is inferred, not declared.** ASP.NET makes you write `[FromQuery]`/`[FromRoute]`/`[FromBody]` (or relies on convention with warnings). Ninja has one inference rule: path placeholder → route param, `Schema` type → body, anything else → query param. Worth remembering because it's the part most likely to surprise you the first time a parameter binds from the wrong place.
- **Response shape is declared via `response=`, not a return type alone.** `@router.get(..., response=BookingOut)` both documents *and* enforces/serializes the output — closer to combining `[ProducesResponseType(typeof(T))]` with the actual serialization step in one place.

**Ask your AI assistant if you want more depth here:** *"Walk through exactly how Django Ninja decides whether a function parameter is a path param, a query param, or a body — what are the precedence rules if a name could be ambiguous?"*

---

## 2. Prerequisites check

Confirm yesterday's environment still comes up clean before adding anything:

```powershell
docker compose ps
```

Should show `bookings-postgres` running. If not, `docker compose up -d` from the workspace root first.

```powershell
cd src\django_api
uv run python manage.py runserver
```

Confirm `/admin/` still loads and the seeded `Building`/`Room`/`Booking` rows from Day 1 are present, then stop the server (`Ctrl+C`) — you'll restart it after wiring the API in.

`django-ninja` is already installed — it was added to `src/django_api/pyproject.toml` back in Day 1 §7, ahead of when it's actually used. Confirm it's there:

```powershell
uv run python manage.py shell -c "import ninja; print(ninja.__version__)"
```

Use `manage.py shell -c`, not a bare `python -c`. Ninja reads Django settings at import time (`ninja/conf.py`), and a bare `python -c` never sets `DJANGO_SETTINGS_MODULE`, so `import ninja` fails with `ImproperlyConfigured: ... settings are not configured`. `manage.py shell` sets that up first, the same way `manage.py runserver` does, so the import succeeds.

---

## 3. Where the new files live

Everything for the API layer is added to the existing `bookings` app — no new Django app today, the same way you wouldn't spin up a new project for a new controller in ASP.NET:

```
src/django_api/bookings/
├── admin.py        (Day 1 — unchanged)
├── models.py       (Day 1 — unchanged)
├── schemas.py       ← new: Pydantic Schema classes (the DTOs)
├── api.py           ← new: Router + endpoint functions
└── migrations/
```

`config/urls.py` gets one addition: mounting the top-level `NinjaAPI` instance.

---

## 4. Define the schemas

```python
# bookings/schemas.py
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
```

Notes:

- `BookingOut` mirrors `Booking` field-for-field — Ninja can serialize a Django model instance straight into a matching `Schema` because it reads attributes by name (`booking.room_id`, `booking.date`, ...), no manual mapping code, no `AutoMapper`-equivalent needed.
- `room_id` (not `room`) on `BookingOut`/`BookingCreate` deliberately mirrors what you already saw on Day 1 — Django's FK field gives you both `booking.room` (the object, triggers a query) and `booking.room_id` (the raw int, free). Exposing the id keeps the API boundary flat and matches the C# `BookingApi` tool-layer's plain-string/id boundary philosophy called out in yesterday's models file.
- No `BuildingCreate`/`RoomCreate` today — creation is scoped to `Booking` only, per the plan's three endpoints. `Building`/`Room` stay admin-managed and read-only from the API for now.

**Ask your AI assistant if you want more depth here:** *"Why doesn't a Ninja Schema need something like AutoMapper's profile configuration to convert a Django model instance into a response DTO?"*

---

## 5. Define the router and endpoints

```python
# bookings/api.py
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
    booked_by: str | None = Query(None, description="Case-insensitive contains match"),
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
        raise HttpError(404, f"Booking {booking_id} not found")
    return booking


@router.post("/bookings", response={201: BookingOut})
def create_booking(request, payload: BookingCreate):
    if not Room.objects.filter(id=payload.room_id).exists():
        raise HttpError(404, f"Room {payload.room_id} not found")

    booking = Booking.objects.create(**payload.dict())
    return 201, booking
```

Line-by-line, the parts that don't have a direct ASP.NET counterpart:

- **`response=list[BookingOut]`** — a list-of-schema response type. Ninja handles the collection serialization for you; you don't loop and map manually.
- **`room__building_id=building_id`**  — the double-underscore is Django's ORM syntax for "follow the FK". `room__building_id` means "join `Booking → Room → Room.building_id`" in one filter call — the ORM-query equivalent of a LINQ `.Where(b => b.Room.BuildingId == buildingId)`, but expressed as a string-based path rather than a lambda over navigation properties.
- **`Query(None, description=...)`** — wrapping a query param in `Query(...)` is optional; a bare default (`= None`) works identically for binding. You reach for `Query(...)` only when you want to attach extra OpenAPI metadata (like `description` here) — it shows up in `/api/docs`. Skippable, included once so you see the pattern.
- **`response={201: BookingOut}`** on the `POST` — declares which schema applies to which status code, and setting a non-default status ties directly to the `return 201, booking` tuple below it. This is Ninja's way of expressing what `[ProducesResponseType(typeof(T), 201)]` plus `return CreatedAtAction(...)` would do together in ASP.NET, minus the `Location` header (skip that nuance for now — the plan's `create_booking` MCP tool on Day 3 doesn't need it, since it isn't driving browser redirects).
- **`raise HttpError(404, ...)` before `Room.objects.filter(...).exists()`** — this is the plan's "return actionable messages rather than raw stack traces" principle already in effect. Without this check, `Booking.objects.create(room_id=<bad id>)` would still succeed at the Python level (Django doesn't validate FK existence until the row hits Postgres) and surface as an ugly `IntegrityError` 500. Checking explicitly turns that into a clean, intentional 404 — the same reasoning Day 4's more general error-handling task will extend to the `httpx` calls from the MCP server.

**Ask your AI assistant if you want more depth here:** *"Why does Django let you call `Booking.objects.create(room_id=999)` in Python without an error, when the foreign key doesn't exist? At what point does that actually fail, and why?"*

---

## 6. Mount the API in `urls.py`

```python
# config/urls.py
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from bookings.api import router as bookings_router

api = NinjaAPI(title="Bookings API", version="1.0.0")
api.add_router("", bookings_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
```

`api.add_router("", bookings_router)` mounts the router's routes directly under `/api/` (an empty prefix) — you'd pass e.g. `"/bookings"` here instead if you wanted a second router namespaced separately, the same way ASP.NET's `[Route("api/[controller]")]` sets a base path per controller. One router is enough today; more would only matter once `Building`/`Room` get their own write endpoints, which is out of scope for Day 2.

---

## 7. Run it and verify via `/api/docs`

```powershell
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/api/docs`. This is Ninja's built-in Swagger UI — same purpose as Swashbuckle, generated from the same type hints you just wrote, nothing extra to enable.

Work through each endpoint directly in the browser UI ("Try it out"):

1. **`GET /api/bookings`** with no params — should return all 4 seeded bookings.
2. **`GET /api/bookings`** with `room_id=1` — should return only the 2 bookings for "Meeting room A".
3. **`GET /api/bookings`** with `building_id=2` — should return 0 (Building B's only room, "Conference Room", has no seeded bookings) — confirms the `room__building_id` join is real, not accidentally matching everything.
4. **`GET /api/bookings`** with `booked_by=review` — should return the "Project review" booking via the case-insensitive `icontains` match.
5. **`GET /api/bookings/1`** — returns that one booking.
6. **`GET /api/bookings/999`** — confirm you get a clean `404` with your message, not a 500.
7. **`POST /api/bookings`** with a valid body (e.g. `room_id: 3, date: "2025-08-01", start_time: "09:00", end_time: "10:00", booked_by: "Day 2 test"`) — confirm `201` and the new row appears in `GET /api/bookings` and in `/admin/`.
8. **`POST /api/bookings`** with `room_id: 999` — confirm the clean `404`, not an `IntegrityError` traceback.
9. **`POST /api/bookings`** with a missing field (e.g. no `booked_by`) — confirm Ninja's automatic `422` with a field-level validation message, and that you never wrote code for this case yourself.

That's the full verification loop for today — steps 1–4 prove the filters, 5–6 prove get-by-id and its error path, 7–9 prove create and both of its error paths.

---

## 8. Ruff check

```powershell
# from the workspace root
uv run ruff check .
```

Should still report no issues. If it flags anything in `api.py`/`schemas.py`, this is real app code (unlike the migrations exemption from Day 1 §6) — fix it rather than suppressing it.

---

## 9. End-of-day checklist

- [ ] `bookings/schemas.py` exists with `BuildingOut`, `RoomOut`, `BookingOut`, `BookingCreate`
- [ ] `bookings/api.py` exists with the `router` and all three endpoints
- [ ] `config/urls.py` mounts `api.urls` at `/api/`
- [ ] `/api/docs` loads and lists all three endpoints
- [ ] List filters verified: no filter, `room_id`, `building_id`, `booked_by` (contains)
- [ ] Get-by-id verified for both a real id and a missing one (404)
- [ ] Create verified for a valid payload (201), an invalid `room_id` (404), and a missing required field (422)
- [ ] `uv run ruff check .` runs clean from the workspace root
- [ ] `bookings/schemas.py`, `bookings/api.py`, and the updated `config/urls.py` are committed

---

## 10. Bridge to Day 3

Tomorrow's `fastmcp` server calls exactly these three endpoints over HTTP via `httpx.AsyncClient` — `GET /api/bookings` (with filters), `GET /api/bookings/{id}`, and `POST /api/bookings`. No API changes expected going in; if the MCP tool signatures end up wanting a shape these endpoints don't return (e.g. the room's name alongside its id, to avoid a second round trip from the LLM's perspective), that's a legitimate reason to revisit `BookingOut` before wrapping it — flag it rather than working around it in the MCP layer.
