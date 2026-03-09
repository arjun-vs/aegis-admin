"""
Aegis Demo App
--------------
A simple FastAPI app with 3 models (User, Category, Post) to showcase
the Aegis admin framework.

Run:
    pip install aiosqlite uvicorn
    uvicorn demo.main:app --reload

Then visit:
    http://localhost:8000/            ← Redirects to login
    http://localhost:8000/login       ← Login page (aegis / aegis)
    http://localhost:8000/admin/ui/   ← Admin dashboard (after login)
    http://localhost:8000/docs        ← FastAPI Swagger UI
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from aegis.core.app import Aegis
from aegis.core.auth import AuthBackend


# ---------------------------------------------------------------------------
# Auth backend — cookie-based, username: aegis, password: aegis
# ---------------------------------------------------------------------------

DEMO_CREDENTIALS = {"aegis": "aegis"}
SESSION_COOKIE = "aegis_session"
SESSION_TOKEN = "aegis-demo-authenticated"


class CookieAuthBackend(AuthBackend):
    async def get_current_user(self, request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        if token == SESSION_TOKEN:
            return {"username": "aegis"}
        return None

    async def is_authenticated(self, user) -> bool:
        return user is not None


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

DATABASE_URL = "sqlite+aiosqlite:///./demo.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    posts = relationship("Post", back_populates="category")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, unique=True)
    email = Column(String(120), nullable=False, unique=True)
    full_name = Column(String(100), nullable=True)
    role = Column(String(20), default="viewer")

    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    status = Column(String(20), default="draft")

    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    author = relationship("User", back_populates="posts")
    category = relationship("Category", back_populates="posts")


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

async def seed_data():
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            return  # already seeded

        categories = [
            Category(name="Technology", description="Tech news and tutorials"),
            Category(name="Science", description="Science discoveries"),
            Category(name="Business", description="Business and finance"),
        ]
        session.add_all(categories)
        await session.flush()

        users = [
            User(username="alice", email="alice@example.com", full_name="Alice Smith", role="admin"),
            User(username="bob", email="bob@example.com", full_name="Bob Jones", role="editor"),
            User(username="carol", email="carol@example.com", full_name="Carol White", role="viewer"),
        ]
        session.add_all(users)
        await session.flush()

        posts = [
            Post(title="Getting Started with FastAPI", body="FastAPI is a modern web framework...", status="published", author_id=users[0].id, category_id=categories[0].id),
            Post(title="SQLAlchemy 2.0 Tips", body="Here are some tips for SQLAlchemy 2.0...", status="published", author_id=users[1].id, category_id=categories[0].id),
            Post(title="The Future of AI", body="Artificial intelligence is evolving rapidly...", status="draft", author_id=users[0].id, category_id=categories[1].id),
            Post(title="Market Trends 2025", body="The economy is showing signs of...", status="published", author_id=users[2].id, category_id=categories[2].id),
            Post(title="Quantum Computing Basics", body="Quantum computers use qubits...", status="draft", author_id=users[1].id, category_id=categories[1].id),
        ]
        session.add_all(posts)
        await session.commit()
        print("Demo data seeded successfully")


# ---------------------------------------------------------------------------
# App + Aegis setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_data()
    yield
    await engine.dispose()


app = FastAPI(
    title="Aegis Demo",
    description="Demo app showcasing the Aegis admin framework",
    version="0.1.0",
    lifespan=lifespan,
)

aegis = Aegis(
    app=app,
    engines={"default": engine},
    auth_backend=CookieAuthBackend(),
    title="Aegis Demo Admin",
    login_url="/login",
)

aegis.register(User)
aegis.register(Category)
aegis.register(Post)


# ---------------------------------------------------------------------------
# Login / Logout routes
# ---------------------------------------------------------------------------

_demo_templates_dir = os.path.join(os.path.dirname(__file__), "templates")
demo_templates = Jinja2Templates(directory=_demo_templates_dir)


@app.get("/login", include_in_schema=False)
async def login_form(request: Request):
    return demo_templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if DEMO_CREDENTIALS.get(username) == password:
        response = RedirectResponse(url="/admin/ui/", status_code=303)
        response.set_cookie(SESSION_COOKIE, SESSION_TOKEN, httponly=True, samesite="lax")
        return response
    return demo_templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid username or password."},
        status_code=401,
    )


@app.get("/logout", include_in_schema=False)
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/admin/ui/")
