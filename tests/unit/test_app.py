import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from aegis.core.app import Aegis
from aegis.core.auth import AllowAllAuthBackend
from sqlalchemy import Column, Integer
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DummyModel(Base):
    __tablename__ = "dummy"
    id = Column(Integer, primary_key=True)

def create_test_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


def test_aegis_initialization():
    app = FastAPI()
    engine = create_test_engine()

    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())

    assert aegis.base_path == "/admin"
    assert aegis.title == "Aegis Admin"


def test_register_model_success():
    app = FastAPI()
    engine = create_test_engine()

    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())

    aegis.register(DummyModel)

    config = aegis.registry.get(DummyModel)

    assert config["model"] is DummyModel


def test_register_with_invalid_database():
    app = FastAPI()
    engine = create_test_engine()

    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())

    with pytest.raises(ValueError):
        aegis.register(DummyModel, database="missing")

def test_registration_generates_metadata():
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    app = FastAPI()
    engine = create_test_engine()

    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())

    aegis.register(User)

    config = aegis.registry.get(User)

    assert "metadata" in config
    assert "fields" in config["metadata"]
    assert any(f["name"] == "name" for f in config["metadata"]["fields"])