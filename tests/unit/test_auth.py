"""Tests for pluggable authentication in Aegis."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base

from aegis.core.app import Aegis
from aegis.core.auth import AuthBackend, AllowAllAuthBackend, RejectAllAuthBackend

Base = declarative_base()


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    name = Column(String)


async def _make_app(auth_backend):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=auth_backend)
    aegis.register(Item)
    return app


# ── Constructor validation ────────────────────────────────────────────────────

def test_aegis_raises_without_auth_backend():
    app = FastAPI()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    with pytest.raises(ValueError, match="auth_backend"):
        Aegis(app=app, engines={"default": engine}, auth_backend=None)


def test_aegis_raises_when_auth_backend_omitted():
    app = FastAPI()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    with pytest.raises(ValueError, match="auth_backend"):
        Aegis(app=app, engines={"default": engine})


def test_aegis_stores_auth_backend_and_login_url():
    app = FastAPI()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    backend = AllowAllAuthBackend()
    aegis = Aegis(
        app=app,
        engines={"default": engine},
        auth_backend=backend,
        login_url="/my-login",
    )
    assert aegis.auth_backend is backend
    assert aegis.login_url == "/my-login"


# ── Unauthenticated access ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_ui_route_redirects_to_login():
    app = await _make_app(RejectAllAuthBackend())
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/admin/ui/items/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_unauthenticated_ui_route_custom_login_url():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    aegis = Aegis(
        app=app,
        engines={"default": engine},
        auth_backend=RejectAllAuthBackend(),
        login_url="/auth/sign-in",
    )
    aegis.register(Item)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/admin/ui/items/")
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/sign-in"


@pytest.mark.asyncio
async def test_unauthenticated_api_route_returns_401():
    app = await _make_app(RejectAllAuthBackend())
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/items/")
    assert response.status_code == 401


# ── Authenticated access ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticated_ui_route_returns_200():
    app = await _make_app(AllowAllAuthBackend())
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/ui/items/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_api_route_returns_200():
    app = await _make_app(AllowAllAuthBackend())
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/items/")
    assert response.status_code == 200


# ── AuthBackend interface ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_backend_base_raises_not_implemented():
    from fastapi import Request
    from unittest.mock import MagicMock

    backend = AuthBackend()
    mock_request = MagicMock(spec=Request)

    with pytest.raises(NotImplementedError):
        await backend.get_current_user(mock_request)

    with pytest.raises(NotImplementedError):
        await backend.is_authenticated(None)
