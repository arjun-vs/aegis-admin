from typing import Any, Dict, List

from sqlalchemy.orm import selectinload, joinedload


class QueryOptimizer:
    """Builds SQLAlchemy eager loading options to prevent N+1 queries.

    Strategy:
      - uselist=True  (one-to-many / many-to-many) → selectinload
        Emits one extra IN query regardless of parent count. Safe for collections.
      - uselist=False (many-to-one / one-to-one)   → joinedload
        Adds a LEFT OUTER JOIN. Safe for scalar relationships.
    """

    def build_options(self, relationships: List[Dict[str, Any]], model: Any) -> List:
        """Return a list of SQLAlchemy loading options for the given relationships.

        Args:
            relationships: List of relationship dicts from SQLAlchemyIntrospector.
            model: The SQLAlchemy mapped model class.

        Returns:
            List of orm loading options ready to pass to stmt.options(*options).
        """
        options = []
        for rel in relationships:
            attr = getattr(model, rel["name"], None)
            if attr is None:
                continue
            if rel["uselist"]:
                options.append(selectinload(attr))
            else:
                options.append(joinedload(attr))
        return options
