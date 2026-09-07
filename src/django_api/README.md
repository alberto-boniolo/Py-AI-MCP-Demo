# django_api

PostgreSQL-backed REST API for the bookings domain, built with Django + Django Ninja. Entities are `Building` → `Room` → `Booking`

## What's covered here

- **Domain models** (`bookings/models.py`): `Building`, `Room`, `Booking`, with explicit `on_delete` cascade behavior; Django Admin registration for sanity checks through Django web UI.
- **Seed data**: two buildings, four rooms, four bookings applied via data migrations (`bookings/migrations/0002_seed_bookings.py`), plus a Postgres id-sequence resync migration (`0003_reset_sequences.py`) needed because the seed uses explicit PKs.
- **REST API** `bookings/api.py`, mounted at `/api/` in `config/urls.py`.
   Endpoints backed by Pydantic style Ninja `Schema` classes in `bookings/schemas.py`, with explicit 404s instead of raw `IntegrityError` on a bad `room_id`.
   Auto-generated OpenAPI docs at `/api/docs`.
   Endpoints:
   - `GET /api/bookings` (filterable by `room_id`, `building_id`, `date`, `booked_by`),
   - `GET /api/bookings/{id}`,
   - `POST /api/bookings`
- **Structured JSON logging** (`config/logging_ext.py`): a `RequestIdMiddleware` + `contextvars` filter that tags every log line with a `request_id`, reads from an incoming `X-Request-Id` header when the MCP server forwards one, so the same id shows up on the MCP server's own log lines for that call.

## Packages used

| Package                                                  | Role                                           |
| -------------------------------------------------------- | ---------------------------------------------- |
| [`django`](https://pypi.org/project/Django/)             | Web framework, ORM, Admin UI                   |
| [`django-ninja`](https://pypi.org/project/django-ninja/) | Type-hint-driven REST API layer + OpenAPI docs |
| [`psycopg[binary]`](https://pypi.org/project/psycopg/)   | PostgreSQL driver                              |

(Ruff is used for linting across the whole workspace as a root-level dev dependency — see the root [`pyproject.toml`](../../pyproject.toml).)

## Running

Database start in case container is stopped

```powershell
docker compose ps
```

or

```powershell
docker compose up -d
```

run django

```powershell
cd src\django_api
uv run python manage.py runserver
```

Stop postgres database for test

```powershell
docker compose stop postgres
```

or

```powershell
docker compose down
```

data remains safe and persisted
