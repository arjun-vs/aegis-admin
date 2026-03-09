"""Tests for the centralized ValidationService."""
import pytest
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, relationship

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend
from aegis.core.executor import DBExecutor
from aegis.core.engine import EngineManager
from aegis.core.validation import ValidationService


Base = declarative_base()

tags_posts = Table(
    "tags_posts",
    Base.metadata,
    Column("post_id", Integer, ForeignKey("posts.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)


class Author(Base):
    __tablename__ = "authors"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    label = Column(String)


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=True)
    author = relationship("Author")
    tags = relationship("Tag", secondary=tags_posts)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _make_executor():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add(Author(name="Alice"))
        session.add(Tag(label="python"))
        session.add(Tag(label="fastapi"))
        await session.commit()

    manager = EngineManager({"default": engine})
    executor = DBExecutor(manager)
    return executor


class FakeFormData(dict):
    """Minimal form-data mock that also supports getlist()."""

    def getlist(self, key):
        val = self.get(key, [])
        if isinstance(val, list):
            return val
        return [val] if val else []


# ── Required field enforcement ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_required_field_raises_error_when_empty():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "title", "widget": "text", "multiple": False}]
    column_map = {"title": {"nullable": False}}
    form_data = FakeFormData({"title": ""})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert "title" in errors
    assert "required" in errors["title"].lower()
    assert "title" not in data


@pytest.mark.asyncio
async def test_nullable_field_empty_becomes_none():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "author_id", "widget": "select", "multiple": False}]
    column_map = {"author_id": {"nullable": True}}
    form_data = FakeFormData({"author_id": ""})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert errors == {}
    assert data["author_id"] is None


@pytest.mark.asyncio
async def test_required_field_passes_with_value():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "title", "widget": "text", "multiple": False}]
    column_map = {"title": {"nullable": False}}
    form_data = FakeFormData({"title": "Hello"})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert errors == {}
    assert data["title"] == "Hello"


# ── Type coercion ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_integer_coercion_valid():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "count", "widget": "number", "multiple": False}]
    column_map = {"count": {"nullable": True}}
    form_data = FakeFormData({"count": "42"})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert errors == {}
    assert data["count"] == 42


@pytest.mark.asyncio
async def test_integer_coercion_invalid():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "count", "widget": "number", "multiple": False}]
    column_map = {"count": {"nullable": True}}
    form_data = FakeFormData({"count": "not_a_number"})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert "count" in errors
    assert "integer" in errors["count"].lower()


@pytest.mark.asyncio
async def test_text_field_stays_as_string():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "name", "widget": "text", "multiple": False}]
    column_map = {"name": {"nullable": True}}
    form_data = FakeFormData({"name": "  Bob  "})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert errors == {}
    assert data["name"] == "Bob"  # stripped


# ── FK validation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fk_validation_passes_for_existing_record():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "author_id", "widget": "select", "multiple": False}]
    column_map = {"author_id": {"nullable": True}}
    fk_info = {"author_id": {"related_model": Author, "pk": "id"}}
    form_data = FakeFormData({"author_id": "1"})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
        fk_info=fk_info,
    )

    assert errors == {}
    assert data["author_id"] == 1


@pytest.mark.asyncio
async def test_fk_validation_fails_for_nonexistent_record():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "author_id", "widget": "select", "multiple": False}]
    column_map = {"author_id": {"nullable": True}}
    fk_info = {"author_id": {"related_model": Author, "pk": "id"}}
    form_data = FakeFormData({"author_id": "9999"})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
        fk_info=fk_info,
    )

    assert "author_id" in errors
    assert "does not exist" in errors["author_id"].lower()


@pytest.mark.asyncio
async def test_fk_validation_skipped_when_no_fk_info():
    """Without fk_info, FK existence check is skipped (only type coercion applies)."""
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "author_id", "widget": "select", "multiple": False}]
    column_map = {"author_id": {"nullable": True}}
    form_data = FakeFormData({"author_id": "9999"})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
        # no fk_info
    )

    assert errors == {}
    assert data["author_id"] == 9999


# ── M2M validation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_m2m_validation_passes_for_existing_ids():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "tags", "widget": "autocomplete", "multiple": True}]
    column_map = {}
    m2m_info = {"tags": {"related_model": Tag, "pk": "id"}}
    form_data = FakeFormData({"tags": ["1", "2"]})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
        m2m_info=m2m_info,
    )

    assert errors == {}
    assert data["tags"] == [1, 2]


@pytest.mark.asyncio
async def test_m2m_validation_fails_for_nonexistent_ids():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "tags", "widget": "autocomplete", "multiple": True}]
    column_map = {}
    m2m_info = {"tags": {"related_model": Tag, "pk": "id"}}
    form_data = FakeFormData({"tags": ["1", "9999"]})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
        m2m_info=m2m_info,
    )

    assert "tags" in errors
    assert "9999" in errors["tags"]


@pytest.mark.asyncio
async def test_m2m_validation_fails_for_non_integer_ids():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "tags", "widget": "autocomplete", "multiple": True}]
    column_map = {}
    form_data = FakeFormData({"tags": ["abc", "1"]})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
    )

    assert "tags" in errors
    assert "abc" in errors["tags"]


@pytest.mark.asyncio
async def test_m2m_empty_list_is_valid():
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [{"name": "tags", "widget": "autocomplete", "multiple": True}]
    column_map = {}
    form_data = FakeFormData({"tags": []})

    data, errors = await validator.validate_form(
        fields=fields,
        column_map=column_map,
        form_data=form_data,
        database="default",
    )

    assert errors == {}
    assert data["tags"] == []


# ── Integration: ValidationService used via Aegis endpoints ──────────────────

from httpx import AsyncClient, ASGITransport


async def _make_aegis_app():
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
async def test_create_endpoint_rejects_invalid_fk():
    """POSTing a non-existent author_id should return 422 via FK validation."""
    app = await _make_aegis_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/ui/posts/create/",
            data={"title": "Test Post", "author_id": "9999"},
        )
    assert response.status_code == 422
    assert "does not exist" in response.text.lower()


@pytest.mark.asyncio
async def test_create_endpoint_accepts_valid_fk():
    """POSTing an existing author_id should succeed."""
    app = await _make_aegis_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.post(
            "/admin/ui/posts/create/",
            data={"title": "Test Post", "author_id": "1"},
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_edit_endpoint_rejects_invalid_fk():
    """Editing a post with a non-existent author_id should return 422."""
    app = await _make_aegis_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create post first
        await client.post(
            "/admin/ui/posts/create/",
            data={"title": "Original", "author_id": "1"},
        )
        response = await client.post(
            "/admin/ui/posts/1/edit/",
            data={"title": "Updated", "author_id": "9999"},
        )
    assert response.status_code == 422
    assert "does not exist" in response.text.lower()


@pytest.mark.asyncio
async def test_multiple_errors_reported_at_once():
    """All field errors should be collected and returned together."""
    executor = await _make_executor()
    validator = ValidationService(executor)

    fields = [
        {"name": "title", "widget": "text", "multiple": False},
        {"name": "count", "widget": "number", "multiple": False},
    ]
    column_map = {
        "title": {"nullable": False},
        "count": {"nullable": False},
    }
    form_data = FakeFormData({"title": "", "count": "bad"})

    data, errors = await validator.validate_form(
        fields=fields, column_map=column_map, form_data=form_data, database="default"
    )

    assert "title" in errors
    assert "count" in errors
