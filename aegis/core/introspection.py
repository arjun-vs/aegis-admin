from typing import Any, Dict, List
from sqlalchemy.inspection import inspect
from sqlalchemy.exc import NoInspectionAvailable

class SQLAlchemyIntrospector:
    def __init__(self, model: Any) -> None:
        try:
            self.mapper = inspect(model)
        except NoInspectionAvailable:
            raise ValueError(
                f"Model '{model.__name__}' is not a valid SQLAlchemy mapped model."
            )

        self.model = model

    def inspect(self) -> Dict[str, Any]:
        return {
            "table": self.model.__tablename__,
            "columns": self._get_columns(),
            "primary_keys": self._get_primary_keys(),
            "relationships": self._get_relationships(),
        }

    def _get_columns(self) -> List[Dict[str, Any]]:
        columns = []

        for column in self.mapper.columns:
            columns.append(
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "foreign_keys": [str(fk.target_fullname) for fk in column.foreign_keys],
                }
            )

        return columns

    def _get_primary_keys(self) -> List[str]:
        return [col.name for col in self.mapper.primary_key]

    def _get_relationships(self) -> List[Dict[str, Any]]:
        relationships = []

        for rel in self.mapper.relationships:
            relationships.append(
                {
                    "name": rel.key,
                    "target": rel.mapper.class_.__name__,
                    "uselist": rel.uselist,
                    "secondary": rel.secondary is not None,
                }
            )

        return relationships