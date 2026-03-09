from typing import Dict, Type, Optional, Any


class ModelRegistry:
    def __init__(self) -> None:
        self._registry: Dict[Type[Any], Dict[str, Any]] = {}

    def register(
        self,
        model: Type[Any],
        database: str = "default",
        admin_class: Optional[Type[Any]] = None,
    ) -> None:
        if model in self._registry:
            raise ValueError(
                f"Model '{model.__name__}' is already registered."
            )

        self._registry[model] = {
            "model": model,
            "database": database,
            "admin_class": admin_class,
        }

    def get(self, model: Type[Any]) -> Dict[str, Any]:
        if model not in self._registry:
            raise ValueError(
                f"Model '{model.__name__}' is not registered."
            )

        return self._registry[model]

    def all(self) -> Dict[Type[Any], Dict[str, Any]]:
        return self._registry

    def get_by_table_name(self, table_name: str) -> Optional[Type[Any]]:
        for model in self._registry:
            if getattr(model, "__tablename__", None) == table_name:
                return model
        return None