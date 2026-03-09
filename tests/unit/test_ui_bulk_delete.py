import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend

Base = declarative_base()


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


async def _make_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add(Tag(name="Python"))
        session.add(Tag(name="FastAPI"))
        session.add(Tag(name="SQLAlchemy"))
        await session.commit()

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Tag)
    return app


@pytest.mark.asyncio
async def test_list_page_has_checkboxes():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/tags/")
    assert response.status_code == 200
    assert 'type="checkbox"' in response.text
    assert 'name="pks"' in response.text


@pytest.mark.asyncio
async def test_list_page_has_delete_selected_button():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/ui/tags/")
    assert response.status_code == 200
    assert "Delete Selected" in response.text
    assert "bulk-delete" in response.text


@pytest.mark.asyncio
async def test_bulk_delete_confirm_returns_200_with_selected_records():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/ui/tags/bulk-delete/", data={"pks": ["1", "2"]})
    assert response.status_code == 200
    assert "Are you sure" in response.text
    assert "Python" in response.text
    assert "FastAPI" in response.text


@pytest.mark.asyncio
async def test_bulk_delete_confirm_shows_record_count():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/ui/tags/bulk-delete/", data={"pks": ["1", "2"]})
    assert response.status_code == 200
    assert "2" in response.text


@pytest.mark.asyncio
async def test_bulk_delete_confirm_404_when_all_pks_invalid():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/ui/tags/bulk-delete/", data={"pks": ["9998", "9999"]})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_delete_confirm_redirects_when_no_pks_selected():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post("/admin/ui/tags/bulk-delete/", data={})
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/tags/"


@pytest.mark.asyncio
async def test_bulk_delete_submit_removes_objects_and_redirects():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post("/admin/ui/tags/bulk-delete/confirm/", data={"pks": ["1", "2"]})
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/ui/tags/"


@pytest.mark.asyncio
async def test_bulk_delete_submit_removes_objects_from_db():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/ui/tags/bulk-delete/confirm/", data={"pks": ["1", "2"]})
        list_response = await client.get("/admin/ui/tags/")
    assert "Python" not in list_response.text
    assert "FastAPI" not in list_response.text
    assert "SQLAlchemy" in list_response.text


@pytest.mark.asyncio
async def test_bulk_delete_submit_partial_invalid_pks_deletes_valid_ones():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/ui/tags/bulk-delete/confirm/", data={"pks": ["1", "9999"]})
        list_response = await client.get("/admin/ui/tags/")
    assert "Python" not in list_response.text
    assert "FastAPI" in list_response.text


@pytest.mark.asyncio
async def test_bulk_delete_submit_404_when_all_pks_invalid():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/ui/tags/bulk-delete/confirm/", data={"pks": ["9998", "9999"]})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_delete_submit_redirects_when_no_pks():
    app = await _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post("/admin/ui/tags/bulk-delete/confirm/", data={})
    assert response.status_code == 303
