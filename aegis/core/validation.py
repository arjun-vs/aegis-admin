from typing import Any, Dict, List, Optional, Tuple

from aegis.core.executor import DBExecutor


class ValidationService:
    """Centralized validation service for admin form submissions.

    Handles:
    - Required field enforcement (non-nullable columns)
    - Type coercion (integers for number/select widgets)
    - FK existence validation (verifies FK values exist in the related table)
    - M2M validation (verifies all M2M IDs exist in the related table)
    """

    def __init__(self, executor: DBExecutor) -> None:
        self.executor = executor

    async def validate_form(
        self,
        fields: List[Dict[str, Any]],
        column_map: Dict[str, Dict[str, Any]],
        form_data: Any,
        database: str,
        fk_info: Optional[Dict[str, Dict[str, Any]]] = None,
        m2m_info: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Validate and coerce form data for create/edit operations.

        Args:
            fields: Field metadata dicts (name, widget, readonly, multiple, ...).
            column_map: Mapping of column name -> column metadata (nullable, etc.).
            form_data: FastAPI FormData — supports .get() and .getlist().
            database: Database alias used for FK/M2M existence checks.
            fk_info: Optional {field_name: {related_model, pk}} for FK validation.
            m2m_info: Optional {field_name: {related_model, pk}} for M2M validation.

        Returns:
            (data, errors):
              data   — dict of validated/coerced field values (scalars and M2M lists).
              errors — dict of field_name -> error message (empty if all valid).
        """
        fk_info = fk_info or {}
        m2m_info = m2m_info or {}
        errors: Dict[str, str] = {}
        data: Dict[str, Any] = {}

        for field in fields:
            field_name = field["name"]
            widget = field.get("widget", "text")

            # ── M2M fields (multi-select / autocomplete with multiple=True) ──
            if widget == "autocomplete" and field.get("multiple"):
                raw_ids = (
                    form_data.getlist(field_name)
                    if hasattr(form_data, "getlist")
                    else []
                )
                error, coerced_ids = await self._validate_m2m(
                    field_name, raw_ids, m2m_info.get(field_name), database
                )
                if error:
                    errors[field_name] = error
                else:
                    data[field_name] = coerced_ids
                continue

            # ── Scalar fields ────────────────────────────────────────────────
            raw = form_data.get(field_name, "")
            if isinstance(raw, str):
                raw = raw.strip()

            col = column_map.get(field_name)

            # Required field enforcement
            if not raw:
                if col and col.get("nullable") is False:
                    errors[field_name] = "This field is required."
                    continue
                data[field_name] = None
                continue

            # Type coercion + FK existence check
            if widget in ("number", "select"):
                try:
                    coerced = int(raw)
                except ValueError:
                    errors[field_name] = "Must be a valid integer."
                    continue

                if widget == "select" and field_name in fk_info:
                    fk_error = await self._validate_fk(
                        coerced, fk_info[field_name], database
                    )
                    if fk_error:
                        errors[field_name] = fk_error
                        continue

                data[field_name] = coerced
            else:
                data[field_name] = raw

        return data, errors

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _validate_fk(
        self,
        value: int,
        info: Dict[str, Any],
        database: str,
    ) -> Optional[str]:
        """Return an error string if the FK value doesn't exist, else None."""
        related_model = info.get("related_model")
        pk = info.get("pk")
        if related_model is None or pk is None:
            return None  # Can't validate — let the DB enforce it

        obj = await self.executor.fetch_one(
            model=related_model,
            database=database,
            pk_name=pk,
            pk_value=str(value),
        )
        if obj is None:
            return "Selected record does not exist."
        return None

    async def _validate_m2m(
        self,
        field_name: str,
        raw_ids: List[str],
        info: Optional[Dict[str, Any]],
        database: str,
    ) -> Tuple[Optional[str], List[int]]:
        """Coerce and validate a list of M2M IDs.

        Returns:
            (error_string_or_None, list_of_valid_coerced_ids)
        """
        coerced_ids: List[int] = []
        bad_values: List[str] = []

        for raw_id in raw_ids:
            raw_id = str(raw_id).strip()
            if not raw_id:
                continue

            try:
                coerced = int(raw_id)
            except ValueError:
                bad_values.append(raw_id)
                continue

            if info:
                related_model = info.get("related_model")
                pk = info.get("pk")
                if related_model and pk:
                    obj = await self.executor.fetch_one(
                        model=related_model,
                        database=database,
                        pk_name=pk,
                        pk_value=str(coerced),
                    )
                    if obj is None:
                        bad_values.append(str(coerced))
                        continue

            coerced_ids.append(coerced)

        if bad_values:
            return f"Invalid values: {', '.join(bad_values)}.", coerced_ids
        return None, coerced_ids
