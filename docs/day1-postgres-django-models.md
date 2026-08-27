# Day 1 — PostgreSQL + Django Project + Domain Models

> Companion guide to `python-mcp-4day-plan.md`. Rewritten against the real `BookingApi` entities (`Building` → `Room` → `Booking`) and a `uv` workspace layout that already accounts for the Day 3 `mcp_server` component, so nothing needs to move later. Written for: VS Code with the Python + Django extensions installed, `uv` installed, PowerShell 7 as your shell.

---

## 0. Objective for today

By the end of Day 1 you will have:

1. A `uv` **workspace** at the repo root — the container that will also hold `mcp_server` from Day 3 onward, set up now so folder names never change.
2. A PostgreSQL 16 instance running locally in Docker, defined once at the workspace root (shared infra, not owned by one component).
3. A Django project (`config`) with one app (`bookings`) living at `src/django_api/`.
4. `Building`, `Room`, and `Booking` models — a direct port of your C# entities, including the same two-level FK chain and the same deliberate string-typed `Date`/`StartTime`/`EndTime` fields.
5. Migrations applied, all three models registered and usable in the Django Admin.

**Definition of done:** `python manage.py runserver` starts cleanly from `src/django_api/`, the Django admin shows empty `Building`, `Room`, and `Booking` tables backed by Postgres, and you can create one of each by hand through the admin UI (a `Building`, then a `Room` inside it, then a `Booking` for that `Room`).

A note on `ConversationSession`: it doesn't appear in today's models, on purpose. In `BookingApi` it exists because the ASP.NET Web API is stateless between HTTP requests and needs somewhere to rehydrate MAF's serialized agent state. Your Day 4 Python client is a single long-running local process for the length of one conversation — the equivalent state can live in memory for now. This gets documented (not built) in the Day 4 README, the same way the auth/authz material is — see that day's notes when you get there.

---

## 1. Mental model before you type anything

| .NET/C# concept | Django/Python equivalent | Notes |
|---|---|---|
| `.sln` with multiple `.csproj`s | a `uv` **workspace** (root `pyproject.toml` + `[tool.uv.workspace]`) | One shared lockfile, independently runnable members — this is the piece we're adding today that wasn't in the original plan's Day 1 |
| `dotnet new webapi` | `django-admin startproject` | Scaffolds the project skeleton |
| `Program.cs` composition root | `config/settings.py` | Central config — DB connection, installed apps, middleware |
| A feature project (e.g. `BookingApi.Data`) | a Django **app** (e.g. `bookings/`) | Self-contained module: models, admin registration, migrations |
| Entity class + `DbSet<T>` on `DbContext` | a Django **model** class in `models.py` | Django infers the equivalent of `DbSet` by scanning `INSTALLED_APPS` — no central `DbContext`-like class |
| EF Core Fluent API / Data Annotations | Django model **field declarations** | The field type *is* the constraint — no separate config step |
| `dotnet ef migrations add` | `python manage.py makemigrations` | Diffs models against last known state, writes a migration file |
| `dotnet ef database update` | `python manage.py migrate` | Applies pending migrations |
| `modelBuilder.Entity<T>().HasData(...)` | a Django **data migration** (`RunPython`) or a fixture | Not used today — you already have a Day 2 "seed data" task in the plan; this is the Django equivalent when you get there |
| `appsettings.json` connection string | `DATABASES` dict in `settings.py` | Same idea, different shape |
| NuGet / `PackageReference` | `uv add` | Writes to `pyproject.toml` + lockfile, closest thing to `dotnet add package` |

Structural things that are genuinely different, not just renamed:

- **No `DbContext`.** There's no single class listing every entity set. Django discovers models by scanning installed apps.
- **`on_delete` is mandatory** on every `ForeignKey` — EF Core lets a convention decide; Django forces you to state cascade behavior explicitly, every time.
- **A `uv` workspace member is "virtual" or "real."** The root `pyproject.toml` today has no code of its own — it exists purely to declare the workspace, closer to a `.sln` file than to any one `.csproj`.

---

## 2. Prerequisites check

```powershell
uv --version
docker --version
docker compose version
```

If `docker compose version` fails but `docker-compose --version` works, you have the standalone binary — swap `docker compose` for `docker-compose` below.

---

## 3. Create the workspace root

```powershell
mkdir Py-AI-MCP-Demo
cd Py-AI-MCP-Demo
uv init --bare --python 3.12
```

`--bare` gives you a minimal `pyproject.toml` with no scaffold noise (no placeholder `main.py`) — appropriate since this root will never hold its own code, only orchestrate members.

Open the generated `pyproject.toml` and edit it to declare the workspace:

```toml
[project]
name = "bookings-workspace"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.uv]
package = false

[tool.uv.workspace]
members = ["src/*"]
```

`package = false` tells `uv` this root has no installable code of its own — it's the workspace container only (the `[project] name` still can't collide with any member's name, so don't reuse `bookings-workspace` below).

Reserve the Day 3 folder with a placeholder project now so the name is locked in and git sees it from commit one:

```powershell
mkdir src\mcp_server
cd src\mcp_server
uv init --bare --name mcp-server
```

---

## 4. PostgreSQL via Docker Compose (root level)

Create `docker-compose.yml` at the **workspace root** (`Py-AI-MCP-Demo/docker-compose.yml`) — not nested inside `django_api`. It's shared infrastructure; putting it at the root means neither component "owns" it and nothing needs to move if `mcp_server` ever needs direct DB access later.

```yaml
services:
  postgres:
    image: postgres:16
    container_name: bookings-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: bookings
      POSTGRES_USER: bookings_user
      POSTGRES_PASSWORD: bookings_dev_pw
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Start it:

```powershell
docker compose up -d
docker compose ps
docker exec -it bookings-postgres psql -U bookings_user -d bookings -c "SELECT version();"
```

> **Port 5432 already taken?** Change the host side to something like `"55432:5432"` and use that port in `settings.py` later.

---

## 5. Fix Pylance "could not be resolved from source" errors

If VS Code shows Pylance warnings like `reportMissingModuleSource` on imports such as `django.contrib` (red squiggles, but `uv run` works fine from the terminal), it's an editor misconfiguration, not something that resolves once you build or run the project — Pylance is looking at the wrong Python interpreter and can't see the packages installed in the workspace's `.venv`.

**Where `.venv` lives.** In a `uv` workspace, one `.venv` is created at the **workspace root** (`Py-AI-MCP-Demo\.venv`) and shared across every member.

**Fix it for everyone who clones the repo — commit an interpreter path.** Create `.vscode/settings.json` at the workspace root so every contributor gets a correctly configured Pylance without doing anything by hand. VS Code's `settings.json` has no built-in way to branch on OS, so the path is one literal string — pick the one matching your team:

```json
// Windows (PowerShell/cmd) — .venv created by uv on Windows
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe"
}
```

```json
// macOS / Linux — .venv created by uv on macOS/Linux
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
}
```

This guide targets Windows + PowerShell throughout, so `.vscode/settings.json` in this repo uses the `Scripts/python.exe` form. If you or a teammate clone it on macOS/Linux, swap that one line to the `bin/python` form (the `.venv` itself is also platform-specific — `uv sync`/`uv run` on a different OS regenerates it correctly there, you only need to fix the settings path to match).

After adding or editing the file, reload the VS Code window (`Developer: Reload Window`) so Pylance picks up the new interpreter. If the errors persist, confirm the path actually exists (`uv run` at least once to make sure `.venv` is created), then run `Python: Restart Language Server` from the command palette.

**Fallback / verifying it worked:** `Ctrl+Shift+P` → `Python: Select Interpreter` should show the workspace-root `.venv` pre-selected (checkmarked) once `defaultInterpreterPath` is picked up. You can also select it manually here instead of using `settings.json` — but that choice is local to your machine only and won't help the next person who clones the repo, which is why the committed file above is the preferred fix.

**Activating the venv in a terminal (optional).** You generally don't need this — `uv run` handles it for you, the same way `dotnet run` doesn't require manually setting `PATH`. If you want an activated shell anyway, from `src/django_api/`:

```powershell
# Windows PowerShell
..\..\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux (bash/zsh)
source ../../.venv/bin/activate
```

**Ask your AI assistant if you want more depth here:** *"Explain why a uv workspace puts one .venv at the root instead of one per member, and what that means if two members need different Python versions."*

---

## 6. Install and configure Ruff (workspace root)

`Ruff` is the closest equivalent to a Roslyn analyzer here — a linter (and formatter) that catches the kind of thing the C# compiler/analyzers would flag as a warning, except Python has no built-in equivalent, so nothing catches it unless you install one. The VS Code Ruff extension will still show squiggles without this step, but it'd be running whatever version happens to be bundled with the extension rather than one pinned in your lockfile — inconsistent for anyone else who clones the repo. Installing it as a real dependency now, before any app code exists, means every file from `django_api` and the future `mcp_server` gets linted the same way from commit one.

Install it as a **dev dependency of the workspace root**, not a member — one linter config should apply uniformly across every member, the same way one `.editorconfig` or one set of Roslyn analyzer rules would apply across every `.csproj` in a `.sln`, rather than each project pulling its own copy:

```powershell
# from the workspace root, Py-AI-MCP-Demo\
uv add --dev ruff
```

Add a `[tool.ruff.lint.per-file-ignores]` section to the root `pyproject.toml`:

```toml
[tool.ruff.lint.per-file-ignores]
"**/migrations/*.py" = ["RUF012"]
```

This matters specifically because of what's coming in §11 — Django's `makemigrations` generates migration files with class-level `dependencies`/`operations` lists, which Ruff's `RUF012` ("mutable class default") rule flags. That's Django's own generated convention, not something you'd hand-edit to satisfy a linter, so `RUF012` is silenced for migration files specifically. This is a known, common friction point for anyone pairing Ruff with Django — not something particular to this project — and every Django+Ruff project ends up adding some version of this rule.

Note this silences only `RUF012`, not linting of migrations entirely: hand-written data migrations (like Day 2's seed migration, which has real `RunPython` logic in it) still get checked for genuine bugs — unused imports, undefined names, and so on.

Verify it works from the workspace root:

```powershell
uv run ruff check .
```

Should report no issues yet (there's no app code), confirming Ruff is wired to the workspace `.venv` the same way `uv run python` is.

**Ask your AI assistant if you want more depth here:** *"Why does a uv workspace put shared dev tooling like Ruff at the root instead of installing it separately per member?"*

---

## 7. Create the `django_api` workspace member

```powershell
mkdir src\django_api
cd src\django_api
uv init --no-package --name django-api
```

`--no-package` gives a flat layout (a placeholder `main.py` you'll delete, not a nested `src/django_api/src/django_api/` structure) — Django's own scaffolding provides the real layout, so we don't want `uv`'s packaged-library layout fighting it. Because you're running `uv init` inside a directory under the workspace root's `src/*` glob, `uv` detects the parent workspace automatically — no extra flag needed to register it.

Delete the placeholder:

```powershell
Remove-Item .\main.py
```

Add dependencies (run from inside `src/django_api/` so they land in *this* member's `pyproject.toml`, while still resolving through the one shared workspace lockfile):

```powershell
uv add django django-ninja "psycopg[binary]"
```

| Package | .NET equivalent role |
|---|---|
| `django` | The framework itself — ASP.NET Core's role |
| `django-ninja` | Your Web API layer — arrives Day 2 |
| `psycopg[binary]` | The Postgres driver — `Npgsql`'s role |

---

## 8. Scaffold the Django project and app

Still inside `src/django_api/`:

```powershell
uv run django-admin startproject config .
uv run python manage.py startapp bookings
```

The trailing `.` on `startproject` scaffolds into the current directory rather than creating a redundant nested `config/config/` folder — easy to forget.

Resulting layout:

```
Py-AI-MCP-Demo/
├── src/
│   ├── django_api/
│   │   ├── config/
│   │   │   ├── settings.py
│   │   │   ├── urls.py
│   │   │   ├── asgi.py
│   │   │   └── wsgi.py
│   │   ├── bookings/
│   │   │   ├── admin.py
│   │   │   ├── apps.py
│   │   │   ├── models.py
│   │   │   ├── tests.py
│   │   │   ├── views.py
│   │   │   └── migrations/
│   │   ├── manage.py
│   │   └── pyproject.toml
│   └── mcp_server/
│       └── pyproject.toml
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── .gitignore
```

`startproject`/`startapp` scaffold all standard boilerplate, some info on the less known files:

| File | Role | Needed for Day 1? |
|---|---|---|
| `config/asgi.py` | Entry point for async servers (WebSockets, Uvicorn/Daphne) | No — `runserver` doesn't use it |
| `config/wsgi.py` | Entry point for traditional sync servers (Gunicorn, IIS) at real deploy time — the closest analog to `Program.cs`'s hosting bootstrap, kept separate from `settings.py`'s configuration concern | No — only matters when you deploy |
| `bookings/apps.py` | `AppConfig` class Django uses to register the app; what `"bookings"` in `INSTALLED_APPS` resolves to | Present but untouched — only edited later for app-ready hooks (e.g. signal handlers) |
| `bookings/tests.py` | Empty placeholder for the app's unit tests, analogous to a `BookingApi.Tests` project stub | No — not wired to anything until you write tests |
| `bookings/views.py` | Empty placeholder for view functions/classes | No — Day 2's `django-ninja` routers live in their own module instead of classic Django views |


---

## 9. Django Settings edit

**Register the app.** In `config/settings.py`, add `"bookings"` to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bookings',
]
```

---

In `config/settings.py`, replace the default SQLite `DATABASES` block:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "bookings",
        "USER": "bookings_user",
        "PASSWORD": "bookings_dev_pw",
        "HOST": "localhost",
        "PORT": "5432",
    }
}
```

Direct equivalent of your `DefaultConnection` string in `appsettings.json`. Hardcoded here for Day 1 speed — move to environment variables once things run, not a blocker today.

---

## 10. Define the domain models

Ported from your actual `Building.cs`, `Room.cs`, and `Booking.cs`, field for field:

```python
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
```

Field-by-field translation from the C# source:

| C# (`BookingApi.Data.Entities`) | Django (`bookings.models`) | Notes |
|---|---|---|
| `Building.Id` / `Room.Id` / `Booking.Id` | implicit `id` (Django auto-adds an `AutoField` PK) | You never declared `Id` in Django — it's automatic unless you override it |
| `Building.Rooms` (`ICollection<Room>`) | `related_name="rooms"` on `Room.building` | Django has no field *on* `Building` for this — the reverse accessor `building.rooms.all()` is generated from the FK's `related_name`, the mirror image of EF Core's inferred navigation property |
| `Room.BuildingId` + `Room.Building` (FK id + nav prop pair) | single `Room.building = models.ForeignKey(...)` | Django collapses both into one field; `room.building` gives the object, `room.building_id` gives the raw FK value if you need it without a join |
| `Room.Bookings` | `related_name="bookings"` on `Booking.room` | Same pattern as above, one level down |
| `Booking.Date` / `StartTime` / `EndTime` / `BookedBy` (all `string`) | `CharField` for all four | Deliberately mirrored, not "corrected" to `DateField`/`TimeField` — matches the C# comment about keeping the tool-layer boundary as plain strings |
| `on_delete: Cascade` (implicit via EF Core convention) | `on_delete=models.CASCADE` (explicit, required) | Django won't let you omit this — you must decide per relationship |

Your `BookingDbContext.OnModelCreating` seed data (Milan HQ, Building B, the four rooms, the four bookings) isn't ported today — that's a Day 2 task in the original plan ("Seed script or fixture with realistic sample data"), and its Django equivalent is either a **data migration** (`RunPython`, closest analog to `HasData`) or a fixture loaded via `loaddata`. Worth reusing the same names (`Milan HQ`, `Meeting room A`, etc.) when you get there, purely so the two sibling projects tell an obviously-consistent story in a portfolio walkthrough.

---

## 11. Generate and apply migrations

```powershell
uv run python manage.py makemigrations bookings
uv run python manage.py migrate
```

`makemigrations` writes `bookings/migrations/0001_initial.py` — Python code describing the schema change, the same role as a generated EF Core migration class. **Commit this file.**

`migrate` also applies Django's own built-in migrations (`auth`, `admin`, `sessions`) the first time — expected, and what the Admin UI's login system needs.

Verify:

```powershell
docker exec -it bookings-postgres psql -U bookings_user -d bookings -c "\dt"
```

You should see `bookings_building`, `bookings_room`, `bookings_booking`, plus `auth_*`/`django_*` tables.

---

## 12. Wire up the Admin UI

```python
# bookings/admin.py
from django.contrib import admin
from .models import Building, Room, Booking


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
```

Create a superuser:

```powershell
uv run python manage.py createsuperuser
```

---

## 13. Run it

```powershell
uv run python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/`, log in, and confirm — in order, since the FK chain is two levels deep:

1. Add a `Building` (e.g. "Milan HQ").
2. Add a `Room` (e.g. "Meeting room A"), picking that `Building` from the dropdown.
3. Add a `Booking`, picking that `Room` from the dropdown, filling in `date`/`start_time`/`end_time`/`booked_by`.

That three-step chain working end to end is your proof that Django ↔ psycopg ↔ Postgres is correctly wired, including the FK relationships.

---

## 14. End-of-day checklist

- [ ] `docker compose ps` shows `bookings-postgres` healthy
- [ ] `uv run python manage.py runserver` starts with no errors from `src/django_api/`
- [ ] `/admin/` login works
- [ ] `Building`, `Room`, `Booking` all appear in the admin, all empty initially
- [ ] Created one `Building` → one `Room` in it → one `Booking` for that `Room`, all through the admin UI
- [ ] `bookings/migrations/0001_initial.py` exists and is committed
- [ ] `uv run ruff check .` runs clean from the workspace root (migrations excluded via `[tool.ruff] extend-exclude`)
- [ ] `src/mcp_server/pyproject.toml` committed, reserving the Day 3 location
- [ ] Root `pyproject.toml`, `uv.lock`, `docker-compose.yml`, and `src/django_api/pyproject.toml` are all committed; `.venv/`, `__pycache__/`, `db.sqlite3` are gitignored

Suggested `.gitignore` (at the workspace root):

```
.venv/
__pycache__/
*.pyc
db.sqlite3
.env
```

---

## 15. Bridge to Day 2

Tomorrow's `django-ninja` routers go over these exact models — no schema changes expected, and the seed-data task is where `Building`/`Room`/`Booking` get populated with data mirroring `BookingDbContext`'s `HasData` seed. If you do add fields once you see the API shape, that's normal — just re-run `makemigrations`/`migrate`, same discipline as adding an EF Core migration after an entity change.
