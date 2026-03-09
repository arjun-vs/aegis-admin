import pytest
from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine

from aegis.core.introspection import SQLAlchemyIntrospector

Base = declarative_base()

association_table = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("users.id")),
    Column("role_id", ForeignKey("roles.id")),
)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    roles = relationship("Role", secondary=association_table)


def test_introspect_columns():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    column_names = [field["name"] for field in metadata["columns"]]

    assert "id" in column_names
    assert "name" in column_names


def test_detect_primary_key():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    pk_fields = metadata["primary_keys"]

    assert "id" in pk_fields


def test_detect_relationships():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    relationship_names = [rel["name"] for rel in metadata["relationships"]]

    assert "roles" in relationship_names