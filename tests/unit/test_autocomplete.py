"""Tests for the autocomplete endpoint for large FK relations."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from aegis.core.app import Aegis, AUTOCOMPLETE_THRESHOLD
from aegis.core.auth import AllowAllAuthBackend

Base = declarative_base()


class Category(Base):
    __tablename__ = "ac_categories"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "ac_products"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    category_id = Column(Integer, ForeignKey("ac_categories.id"), nullable=True)
    category = relationship("Category", back_populates="products")


async def _setup_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_categories(engine, n: int):
    async with AsyncSession(engine) as session:
        for i in range(n):
            session.add(Category(name=f"Category {i}"))
        await session.commit()


def _make_app(engine):
    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Category)
    aegis.register(Product)
    return app, aegis


# ---------------------------------------------------------------------------
# AUTOCOMPLETE_THRESHOLD constant
# ---------------------------------------------------------------------------

def test_autocomplete_threshold_default():
    assert AUTOCOMPLETE_THRESHOLD == 100


# ---------------------------------------------------------------------------
# Small dataset: select dropdown (no autocomplete)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_small_relation_uses_select_widget():
    """When related count <= threshold, create form returns fk_options (not autocomplete)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, 5)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/ac_products/create/")

    assert response.status_code == 200
    html = response.text
    # Small dataset → <select> rendered, no autocomplete container
    assert 'name="category_id"' in html
    assert "<select" in html
    assert 'id="ac-container-category_id"' not in html


# ---------------------------------------------------------------------------
# Large dataset: autocomplete mode triggered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_large_relation_triggers_autocomplete_mode():
    """When related count > threshold, create form renders autocomplete widget."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, AUTOCOMPLETE_THRESHOLD + 1)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/ac_products/create/")

    assert response.status_code == 200
    html = response.text
    # Large dataset → autocomplete container rendered, no <select>
    assert 'id="ac-container-category_id"' in html
    assert 'id="ac-search-category_id"' in html
    assert 'type="hidden"' in html
    # The regular <select> for category_id must NOT appear
    assert "<select" not in html


@pytest.mark.asyncio
async def test_large_relation_triggers_autocomplete_on_edit():
    """Edit form also shows autocomplete widget for large relations."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, AUTOCOMPLETE_THRESHOLD + 1)

    async with AsyncSession(engine) as session:
        session.add(Product(title="Test Product", category_id=None))
        await session.commit()

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/ac_products/1/edit/")

    assert response.status_code == 200
    html = response.text
    assert 'id="ac-container-category_id"' in html
    assert "<select" not in html


# ---------------------------------------------------------------------------
# Autocomplete endpoint: valid field returns filtered results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_autocomplete_endpoint_returns_filtered_results():
    """GET /admin/api/{table}/autocomplete/?field=...&q=... returns matching records."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, AUTOCOMPLETE_THRESHOLD + 10)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=category_id&q=Category+5"
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    # All returned results must contain "5" in label
    for item in data["results"]:
        assert "5" in item["label"]
    assert all("value" in r and "label" in r for r in data["results"])


@pytest.mark.asyncio
async def test_autocomplete_endpoint_empty_query_returns_all_up_to_limit():
    """Empty q returns records up to limit without filtering."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, 30)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=category_id&q=&limit=10"
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 10
    assert data["total"] == 30


@pytest.mark.asyncio
async def test_autocomplete_endpoint_limit_capped_at_50():
    """limit parameter is capped at 50."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, 100)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=category_id&limit=200"
        )

    assert response.status_code == 422  # FastAPI rejects > 50


# ---------------------------------------------------------------------------
# Security: unauthorized / invalid field rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_autocomplete_endpoint_rejects_invalid_field():
    """Requesting a field that is not a registered FK returns 400."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=title"
        )

    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]


@pytest.mark.asyncio
async def test_autocomplete_endpoint_rejects_nonexistent_field():
    """Requesting an entirely nonexistent field name returns 400."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=__admin_hack__"
        )

    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]


@pytest.mark.asyncio
async def test_autocomplete_endpoint_rejects_pk_field():
    """The primary key field is not a valid FK autocomplete target."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/api/ac_products/autocomplete/?field=id"
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Boundary: exactly at threshold → select; one above → autocomplete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_at_threshold_uses_select_not_autocomplete():
    """Exactly AUTOCOMPLETE_THRESHOLD records → still uses <select>."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, AUTOCOMPLETE_THRESHOLD)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/ac_products/create/")

    assert response.status_code == 200
    html = response.text
    assert "<select" in html
    assert 'id="ac-container-category_id"' not in html


@pytest.mark.asyncio
async def test_one_above_threshold_uses_autocomplete():
    """AUTOCOMPLETE_THRESHOLD + 1 records → autocomplete widget."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_categories(engine, AUTOCOMPLETE_THRESHOLD + 1)

    app, aegis = _make_app(engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/ui/ac_products/create/")

    assert response.status_code == 200
    html = response.text
    assert 'id="ac-container-category_id"' in html
    assert "<select" not in html
