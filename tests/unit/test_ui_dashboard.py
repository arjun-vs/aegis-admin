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
    title = Column(String)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    body = Column(String)


@pytest.fixture
async def client_with_models():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Article)
    aegis.register(Comment)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_dashboard_returns_200(client_with_models):
    response = await client_with_models.get("/admin/ui/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_shows_model_names(client_with_models):
    response = await client_with_models.get("/admin/ui/")
    assert "Article" in response.text
    assert "Comment" in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_links_to_model_lists(client_with_models):
    response = await client_with_models.get("/admin/ui/")
    assert "/admin/ui/articles/" in response.text
    assert "/admin/ui/comments/" in response.text


@pytest.mark.asyncio
async def test_dashboard_empty_with_no_models():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    app = FastAPI()
    Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/")

    assert response.status_code == 200
