from typing import Dict, Any, Union
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.engine import Engine


class EngineManager:
    def __init__(self, engines: Dict[str, Any]) -> None:
        if "default" not in engines:
            raise ValueError("A 'default' database engine must be provided.")
        self._engines = engines

    def get_engine(self, alias: str) -> Union[Engine, AsyncEngine]:
        if alias not in self._engines:
            raise ValueError(
                f"Database alias '{alias}' is not registered."
            )
        return self._engines[alias]

    def is_async(self, alias: str) -> bool:
        engine = self.get_engine(alias)
        return isinstance(engine, AsyncEngine)