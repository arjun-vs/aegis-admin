import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from httpx import AsyncClient, ASGITransport


from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)


@pytest.mark.asyncio
async def test_list_endpoint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add(User(name="Arjun"))
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["results"][0]["name"] == "Arjun"

@pytest.mark.asyncio
async def test_list_pagination():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all([User(name="A"), User(name="B"), User(name="C")])
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/?limit=2")

    data = response.json()

    # total reflects full dataset (3), limit only affects results
    assert data["total"] == 3
    assert len(data["results"]) == 2
    assert data["limit"] == 2


@pytest.mark.asyncio
async def test_filter_by_valid_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all([User(name="Arjun"), User(name="Bob"), User(name="Arjun")])
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/?name=Arjun")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(r["name"] == "Arjun" for r in data["results"])


@pytest.mark.asyncio
async def test_filter_returns_empty_for_no_match():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all([User(name="Arjun"), User(name="Bob")])
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/?name=Charlie")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_filter_invalid_column_returns_400():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/?nonexistent=foo")

    assert response.status_code == 400
    assert "nonexistent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_filter_with_pagination():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all([
            User(name="Arjun"), User(name="Arjun"), User(name="Arjun"),
            User(name="Bob"),
        ])
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/users/?name=Arjun&limit=2&offset=0")

    assert response.status_code == 200
    data = response.json()
    # total reflects all matching records (3 Arjuns), not just current page
    assert data["total"] == 3
    assert len(data["results"]) == 2
    assert all(r["name"] == "Arjun" for r in data["results"])


@pytest.mark.asyncio
async def test_total_independent_of_offset():
    """total stays the same regardless of offset."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all([User(name=f"User{i}") for i in range(10)])
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(User)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/admin/users/?limit=3&offset=0")
        r2 = await client.get("/admin/users/?limit=3&offset=7")

    d1, d2 = r1.json(), r2.json()
    assert d1["total"] == 10
    assert d2["total"] == 10
    assert len(d1["results"]) == 3
    assert len(d2["results"]) == 3
