import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, relationship

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend

Base = declarative_base()


class Author(Base):
    __tablename__ = "authors"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    author_id = Column(Integer, ForeignKey("authors.id"))
    author = relationship("Author", back_populates="posts")


async def _make_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed an author for FK select tests
    async with AsyncSession(engine) as session:
        session.add(Author(name="Alice"))
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Author)
    aegis.register(Post)
    return app


@pytest.mark.asyncio
async def test_create_form_get_returns_200():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/authors/create/")
    assert response.status_code == 200
    assert "<form" in response.text
    assert 'name="name"' in response.text


@pytest.mark.asyncio
async def test_create_form_excludes_primary_key():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/authors/create/")
    assert response.status_code == 200
    # PK field "id" should not appear as an editable input
    assert 'name="id"' not in response.text


@pytest.mark.asyncio
async def test_post_creates_object_and_redirects():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post(
            "/admin/ui/authors/create/",
            data={"name": "Bob"},
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/authors/"


@pytest.mark.asyncio
async def test_post_created_object_appears_in_list():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/ui/authors/create/", data={"name": "Carol"})
        list_response = await client.get("/admin/ui/authors/")
    assert "Carol" in list_response.text


@pytest.mark.asyncio
async def test_invalid_post_returns_422_with_errors():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Post with empty title (nullable=False)
        response = await client.post(
            "/admin/ui/posts/create/",
            data={"title": "", "author_id": ""},
        )
    assert response.status_code == 422
    assert "required" in response.text.lower()


@pytest.mark.asyncio
async def test_fk_field_renders_as_select_with_options():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/posts/create/")
    assert response.status_code == 200
    # author_id FK should render as a <select>
    assert 'name="author_id"' in response.text
    assert "<select" in response.text
    # The seeded author "Alice" should appear as an option
    assert "Alice" in response.text


@pytest.mark.asyncio
async def test_post_with_fk_creates_object():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post(
            "/admin/ui/posts/create/",
            data={"title": "My Post", "author_id": "1"},
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/posts/"
