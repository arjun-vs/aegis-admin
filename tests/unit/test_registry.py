import pytest

from aegis.core.registry import ModelRegistry


class DummyModel:
    pass


class AnotherModel:
    pass


class CustomAdmin:
    pass


def test_register_model_default_database():
    registry = ModelRegistry()

    registry.register(DummyModel)

    config = registry.get(DummyModel)

    assert config["model"] is DummyModel
    assert config["database"] == "default"
    assert config["admin_class"] is None


def test_register_model_with_custom_database():
    registry = ModelRegistry()

    registry.register(DummyModel, database="analytics")

    config = registry.get(DummyModel)

    assert config["database"] == "analytics"


def test_register_with_admin_class():
    registry = ModelRegistry()

    registry.register(DummyModel, admin_class=CustomAdmin)

    config = registry.get(DummyModel)

    assert config["admin_class"] is CustomAdmin


def test_duplicate_registration_raises_error():
    registry = ModelRegistry()

    registry.register(DummyModel)

    with pytest.raises(ValueError):
        registry.register(DummyModel)


def test_get_unregistered_model_raises_error():
    registry = ModelRegistry()

    with pytest.raises(ValueError):
        registry.get(AnotherModel)