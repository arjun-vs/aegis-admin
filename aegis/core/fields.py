from typing import List, Dict, Any


class FieldStrategyEngine:
    def __init__(self, metadata: Dict[str, Any]) -> None:
        self.metadata = metadata

    def generate(self) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []

        # Process columns
        for column in self.metadata["columns"]:
            field = {
                "name": column["name"],
                "widget": self._map_column_widget(column),
                "readonly": column["primary_key"],
                "multiple": False,
            }
            fields.append(field)

        # Process relationships
        for relationship in self.metadata["relationships"]:
            field = {
                "name": relationship["name"],
                "widget": "autocomplete",
                "readonly": False,
                "multiple": relationship["uselist"],
            }
            fields.append(field)

        return fields

    def _map_column_widget(self, column: Dict[str, Any]) -> str:
        if column.get("foreign_keys"):
            return "select"

        column_type = column["type"].lower()

        if "int" in column_type:
            return "number"

        if "char" in column_type or "string" in column_type:
            return "text"

        return "text"