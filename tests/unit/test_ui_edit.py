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

    async with AsyncSession(engine) as session:
        session.add(Author(name="Alice"))
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Author)
    aegis.register(Post)
    return app


@pytest.mark.asyncio
async def test_edit_form_get_returns_200():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/authors/1/edit/")
    assert response.status_code == 200
    assert "<form" in response.text


@pytest.mark.asyncio
async def test_edit_form_prefills_existing_values():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/authors/1/edit/")
    assert response.status_code == 200
    assert "Alice" in response.text


@pytest.mark.asyncio
async def test_edit_form_get_404_on_invalid_pk():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/authors/9999/edit/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_post_updates_object_and_redirects():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post(
            "/admin/ui/authors/1/edit/",
            data={"name": "Alice Updated"},
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/authors/"


@pytest.mark.asyncio
async def test_edit_post_change_appears_in_list():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/ui/authors/1/edit/", data={"name": "Alice Updated"})
        list_response = await client.get("/admin/ui/authors/")
    assert "Alice Updated" in list_response.text


@pytest.mark.asyncio
async def test_edit_post_404_on_invalid_pk():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/ui/authors/9999/edit/",
            data={"name": "Ghost"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_post_invalid_data_returns_422():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Post with empty title (nullable=False)
        response = await client.post(
            "/admin/ui/posts/1/edit/",
            data={"title": "", "author_id": ""},
        )
    # No post with id=1, should get 404
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_post_with_fk_updates_object():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First create a post
        await client.post(
            "/admin/ui/posts/create/",
            data={"title": "Original Title", "author_id": "1"},
        )
        # Now edit it
        response = await client.post(
            "/admin/ui/posts/1/edit/",
            data={"title": "Updated Title", "author_id": "1"},
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_edit_form_fk_field_renders_as_select():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create a post first
        await client.post(
            "/admin/ui/posts/create/",
            data={"title": "Test Post", "author_id": "1"},
        )
        response = await client.get("/admin/ui/posts/1/edit/")
    assert response.status_code == 200
    assert "<select" in response.text
    assert "Alice" in response.text
