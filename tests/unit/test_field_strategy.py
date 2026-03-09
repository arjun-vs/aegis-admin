from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship

from aegis.core.introspection import SQLAlchemyIntrospector
from aegis.core.fields import FieldStrategyEngine

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
    name = Column(String)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    roles = relationship("Role", secondary=association_table)


def test_string_field_maps_to_text_input():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    engine = FieldStrategyEngine(metadata)
    fields = engine.generate()

    name_field = next(f for f in fields if f["name"] == "name")

    assert name_field["widget"] == "text"


def test_primary_key_is_readonly():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    engine = FieldStrategyEngine(metadata)
    fields = engine.generate()

    id_field = next(f for f in fields if f["name"] == "id")

    assert id_field["readonly"] is True


def test_many_to_many_defaults_to_autocomplete():
    introspector = SQLAlchemyIntrospector(User)
    metadata = introspector.inspect()

    engine = FieldStrategyEngine(metadata)
    fields = engine.generate()

    roles_field = next(f for f in fields if f["name"] == "roles")

    assert roles_field["widget"] == "autocomplete"
    assert roles_field["multiple"] is True