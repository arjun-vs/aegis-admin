# Aegis Admin

[![PyPI version](https://img.shields.io/pypi/v/aegis-admin.svg)](https://pypi.org/project/aegis-admin/)
[![Python](https://img.shields.io/pypi/pyversions/aegis-admin.svg)](https://pypi.org/project/aegis-admin/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Aegis** is an enterprise admin framework for FastAPI that auto-generates a full admin UI and JSON API for your SQLAlchemy models — with zero boilerplate.

---

## Features

- **Auto-generated admin UI** — list, create, edit, delete for every registered model
- **Searchable list views** — ILIKE search across all string columns
- **Bulk delete** — select multiple records and delete in one action
- **FK dropdowns & autocomplete** — foreign key fields render as `<select>` or live-search autocomplete
- **JSON API endpoints** — paginated, filterable, searchable REST endpoints alongside the UI
- **Pluggable auth** — bring your own session, JWT, OAuth2, or any custom backend
- **Multi-database support** — register models against different database engines
- **Async-first** — built on SQLAlchemy 2.0 async engine

---

## Installation

```bash
pip install aegis-admin
```

> Also install an async database driver, e.g. `aiosqlite` for SQLite or `asyncpg` for PostgreSQL.

---

## Quick Start

```python
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend   # swap for your own in production

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id     = Column(Integer, primary_key=True)
    name   = Column(String(100))
    email  = Column(String(200))

app    = FastAPI()
engine = create_async_engine("sqlite+aiosqlite:///./app.db")

aegis = Aegis(
    app=app,
    engines={"default": engine},
    auth_backend=AllowAllAuthBackend(),   # replace with your auth backend
    title="My Admin",
)

aegis.register(User)
```

Visit `http://localhost:8000/admin/ui/` to see the admin panel.

---

## Authentication

Aegis does **not** ship with a built-in login page — it integrates with your project's existing auth system via the `AuthBackend` interface.

```python
from fastapi import Request
from aegis.core.auth import AuthBackend

class MyAuthBackend(AuthBackend):
    async def get_current_user(self, request: Request):
        # Resolve the user from a cookie, JWT, session, etc.
        token = request.cookies.get("session")
        return await db.get_user_by_token(token)   # your existing logic

    async def is_authenticated(self, user) -> bool:
        # Return True only if this user may access the admin
        return user is not None and user.is_admin
```

**Common patterns:**

| Pattern | How |
|---------|-----|
| Cookie / session | Read `request.session["user_id"]` (requires `SessionMiddleware`) |
| JWT | Decode `request.headers["Authorization"]` or a cookie |
| Reuse existing dependency | Call your `verify_token()` / `get_current_user()` directly |

When a request is not authenticated, Aegis automatically redirects UI routes to `login_url` (default `/login`).

---

## Endpoints Generated

For every registered model, Aegis creates:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/{table}/` | JSON list — paginated, searchable, filterable |
| `GET` | `/admin/ui/{table}/` | HTML list view with search + bulk delete |
| `GET/POST` | `/admin/ui/{table}/create/` | Create form |
| `GET/POST` | `/admin/ui/{table}/{pk}/edit/` | Edit form |
| `GET/POST` | `/admin/ui/{table}/{pk}/delete/` | Delete confirmation |
| `POST` | `/admin/ui/{table}/bulk-delete/` | Bulk delete confirmation |
| `GET` | `/admin/api/{table}/autocomplete/` | FK autocomplete search |

### JSON API query parameters

```
GET /admin/users/?limit=50&offset=0&search=alice&role=admin
```

| Param | Description |
|-------|-------------|
| `limit` | Max 100, default 50 |
| `offset` | Pagination offset |
| `search` | ILIKE search across all string columns |
| `<column>` | Exact-match filter on any column |

---

## Multiple Databases

```python
aegis = Aegis(
    app=app,
    engines={
        "default": primary_engine,
        "analytics": analytics_engine,
    },
    auth_backend=MyAuthBackend(),
)

aegis.register(User)                        # uses "default"
aegis.register(Report, database="analytics")
```

---

## Configuration

```python
aegis = Aegis(
    app=app,
    engines={"default": engine},
    auth_backend=MyAuthBackend(),
    base_path="/admin",      # URL prefix (default: /admin)
    title="My Admin",        # Shown in the UI header
    login_url="/login",      # Redirect target when unauthenticated
)
```

---

## License

MIT
