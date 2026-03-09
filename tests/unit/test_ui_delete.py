import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)


async def _make_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add(Article(title="First Article"))
        session.add(Article(title="Second Article"))
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Article)
    return app


@pytest.mark.asyncio
async def test_delete_confirm_get_returns_200():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/articles/1/delete/")
    assert response.status_code == 200
    assert "Delete" in response.text
    assert "Are you sure" in response.text


@pytest.mark.asyncio
async def test_delete_confirm_shows_record_details():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/articles/1/delete/")
    assert response.status_code == 200
    assert "First Article" in response.text


@pytest.mark.asyncio
async def test_delete_confirm_get_404_on_invalid_pk():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/articles/9999/delete/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_post_removes_object_and_redirects():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post("/admin/ui/articles/1/delete/")
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/articles/"


@pytest.mark.asyncio
async def test_delete_post_removes_object_from_db():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/ui/articles/1/delete/")
        list_response = await client.get("/admin/ui/articles/")
    assert "First Article" not in list_response.text
    assert "Second Article" in list_response.text


@pytest.mark.asyncio
async def test_delete_post_404_on_invalid_pk():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/ui/articles/9999/delete/")
    assert response.status_code == 404
