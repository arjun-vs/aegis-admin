import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import create_engine

from aegis.core.engine import EngineManager


def test_requires_default_engine():
    with pytest.raises(ValueError):
        EngineManager({})


def test_engine_registration_and_retrieval():
    async_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sync_engine = create_engine("sqlite:///:memory:")

    manager = EngineManager(
        {
            "default": async_engine,
            "analytics": sync_engine,
        }
    )

    assert manager.get_engine("default") is async_engine
    assert manager.get_engine("analytics") is sync_engine


def test_missing_engine_raises_error():
    async_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    manager = EngineManager({"default": async_engine})

    with pytest.raises(ValueError):
        manager.get_engine("missing")


def test_detect_async_engine():
    async_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    manager = EngineManager({"default": async_engine})

    assert manager.is_async("default") is True


def test_detect_sync_engine():
    sync_engine = create_engine("sqlite:///:memory:")
    manager = EngineManager({"default": sync_engine})

    assert manager.is_async("default") is False