import asyncio
from typing import Dict, Any, Type, Optional
from fastapi import FastAPI, Query, APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os
from sqlalchemy.orm import DeclarativeMeta
from aegis.core.executor import DBExecutor
from aegis.core.engine import EngineManager
from aegis.core.registry import ModelRegistry

from aegis.core.introspection import SQLAlchemyIntrospector
from aegis.core.fields import FieldStrategyEngine
from aegis.core.optimizer import QueryOptimizer
from aegis.core.validation import ValidationService
from aegis.core.auth import AuthBackend

AUTOCOMPLETE_THRESHOLD = 100

class Aegis:
    def __init__(
        self,
        app: FastAPI,
        engines: Dict[str, Any],
        auth_backend: Optional[AuthBackend] = None,
        permission_backend: Optional[Any] = None,
        base_path: str = "/admin",
        title: str = "Aegis Admin",
        login_url: str = "/login",
    ) -> None:
        if auth_backend is None:
            raise ValueError(
                "Aegis requires an auth_backend. Admin cannot run without authentication."
            )
        self.app = app
        self.base_path = base_path
        self.title = title
        self.login_url = login_url
        self.auth_backend = auth_backend
        self.engine_manager = EngineManager(engines)
        self.registry = ModelRegistry()
        self.executor = DBExecutor(self.engine_manager)
        self.validator = ValidationService(self.executor)
        self.router = APIRouter(
            prefix=self.base_path,
            dependencies=[Depends(self._require_auth)],
        )
        templates_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
        )
        self.templates = Jinja2Templates(directory=templates_path)
        self._create_index_endpoint()
        self.app.include_router(self.router)

    async def _require_auth(self, request: Request) -> None:
        user = await self.auth_backend.get_current_user(request)
        if not await self.auth_backend.is_authenticated(user):
            if request.url.path.startswith(f"{self.base_path}/ui/"):
                raise HTTPException(
                    status_code=302,
                    headers={"Location": self.login_url},
                )
            raise HTTPException(status_code=401, detail="Unauthorized")
        request.state.aegis_user = user

    def _create_index_endpoint(self) -> None:
        @self.router.get("/ui/")
        async def index_view(request: Request):
            models = [
                {
                    "name": model.__name__,
                    "table_name": model.__tablename__,
                }
                for model in self.registry.all()
            ]
            return self.templates.TemplateResponse(
                request,
                "admin/index.html",
                {
                    "title": self.title,
                    "models": models,
                },
            )

    def _build_fk_info(
        self,
        editable_fields: list,
        column_map: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Build FK info dict for validation: {field_name: {related_model, pk}}."""
        fk_info: Dict[str, Dict[str, Any]] = {}
        for field in editable_fields:
            if field["widget"] != "select":
                continue
            col = column_map.get(field["name"], {})
            fk_list = col.get("foreign_keys", [])
            if not fk_list:
                continue
            ref_table = fk_list[0].split(".")[0]
            related_model = self.registry.get_by_table_name(ref_table)
            if related_model is None:
                continue
            related_meta = self.registry.get(related_model)["metadata"]
            pk_names = related_meta["introspection"]["primary_keys"]
            pk = pk_names[0] if pk_names else None
            if pk:
                fk_info[field["name"]] = {"related_model": related_model, "pk": pk}
        return fk_info

    def _build_m2m_info(
        self,
        relationships: list,
    ) -> Dict[str, Dict[str, Any]]:
        """Build M2M info dict for validation: {field_name: {related_model, pk}}."""
        m2m_info: Dict[str, Dict[str, Any]] = {}
        for rel in relationships:
            if not rel.get("secondary"):
                continue
            target_name = rel["target"]
            related_model = next(
                (m for m in self.registry.all() if m.__name__ == target_name),
                None,
            )
            if related_model is None:
                continue
            related_meta = self.registry.get(related_model)["metadata"]
            pk_names = related_meta["introspection"]["primary_keys"]
            pk = pk_names[0] if pk_names else None
            if pk:
                m2m_info[rel["name"]] = {"related_model": related_model, "pk": pk}
        return m2m_info

    def _create_list_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        valid_column_names = {col["name"] for col in columns}
        eager_loads = metadata.get("eager_loads", [])

        # detect searchable string columns
        searchable_columns = [
            col["name"]
            for col in columns
            if "char" in col["type"].lower()
            or "string" in col["type"].lower()
        ]

        _RESERVED_PARAMS = {"limit", "offset", "search"}

        @self.router.get(f"/{table_name}/")
        async def list_view(
            request: Request,
            limit: int = Query(50, le=100),
            offset: int = 0,
            search: str = "",
        ):
            # Extract exact-match filters from query params (excluding reserved ones)
            filters: Dict[str, Any] = {}
            for key, value in request.query_params.items():
                if key in _RESERVED_PARAMS:
                    continue
                if key not in valid_column_names:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": f"Invalid filter column: '{key}'"},
                    )
                filters[key] = value

            search_arg = search if search else None
            filters_arg = filters if filters else None

            total, records = await asyncio.gather(
                self.executor.count_all(
                    model=model,
                    database=database,
                    search=search_arg,
                    searchable_columns=searchable_columns,
                    filters=filters_arg,
                ),
                self.executor.fetch_all(
                    model=model,
                    database=database,
                    limit=limit,
                    offset=offset,
                    search=search_arg,
                    searchable_columns=searchable_columns,
                    filters=filters_arg,
                    eager_loads=eager_loads,
                ),
            )

            results = []
            for obj in records:
                row = {}
                for column in columns:
                    row[column["name"]] = getattr(obj, column["name"])
                results.append(row)

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "results": results,
            }
        
    def register(self,
        model: Type[Any],
        database: str = "default",
        admin_class: Optional[Type[Any]] = None,
    ) -> None:
        # Validate database alias exists
        self.engine_manager.get_engine(database)

        # Introspect model
        introspector = SQLAlchemyIntrospector(model)
        model_metadata = introspector.inspect()

        # Generate field strategy
        field_engine = FieldStrategyEngine(model_metadata)
        fields = field_engine.generate()

        # Build eager loading options to prevent N+1 queries
        optimizer = QueryOptimizer()
        eager_loads = optimizer.build_options(model_metadata["relationships"], model)

        enriched_metadata = {
            "introspection": model_metadata,
            "fields": fields,
            "eager_loads": eager_loads,
        }

        # Register model
        self.registry.register(
            model=model,
            database=database,
            admin_class=admin_class,
        )

        # Attach metadata
        self.registry._registry[model]["metadata"] = enriched_metadata
        # Create endpoints
        self._create_list_endpoint(model, database)
        self._create_ui_list_endpoint(model, database)
        self._create_create_endpoint(model, database)
        self._create_edit_endpoint(model, database)
        self._create_delete_endpoint(model, database)
        self._create_bulk_delete_endpoint(model, database)
        self._create_autocomplete_endpoint(model, database)

        # Always include router AFTER endpoints are added
        self.app.include_router(self.router)
        
    def _create_ui_list_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        pk_names = metadata["introspection"]["primary_keys"]
        pk_name = pk_names[0] if pk_names else "id"
        eager_loads = metadata.get("eager_loads", [])

        searchable_columns = [
            col["name"]
            for col in columns
            if "char" in col["type"].lower() or "string" in col["type"].lower()
        ]

        @self.router.get(f"/ui/{table_name}/")
        async def ui_list_view(
            request: Request,
            search: str = "",
        ):
            search_arg = search if search else None

            total, records = await asyncio.gather(
                self.executor.count_all(
                    model=model,
                    database=database,
                    search=search_arg,
                    searchable_columns=searchable_columns,
                ),
                self.executor.fetch_all(
                    model=model,
                    database=database,
                    search=search_arg,
                    searchable_columns=searchable_columns,
                    eager_loads=eager_loads,
                ),
            )

            results = []
            for obj in records:
                row = {}
                for column in columns:
                    row[column["name"]] = getattr(obj, column["name"])
                results.append(row)

            return self.templates.TemplateResponse(
                request,
                "admin/list.html",
                {
                    "table_name": table_name,
                    "columns": [col["name"] for col in columns],
                    "results": results,
                    "pk_name": pk_name,
                    "title": self.title,
                    "search": search,
                    "total": total,
                },
            )

    def _create_create_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        fields = metadata["fields"]

        # Map column name → column meta for quick lookup
        column_map = {col["name"]: col for col in columns}

        # Only editable (non-PK) column fields — skip relationship fields
        editable_fields = [
            f for f in fields
            if not f["readonly"] and f["name"] in column_map
        ]

        # M2M relationship fields for validation
        m2m_fields = [
            f for f in fields
            if not f["readonly"] and f["name"] not in column_map and f.get("multiple")
        ]

        fk_info = self._build_fk_info(editable_fields, column_map)
        m2m_info = self._build_m2m_info(metadata["introspection"]["relationships"])

        async def _get_fk_options(field: Dict[str, Any]) -> Optional[list]:
            """Return list of options, or None if relation exceeds AUTOCOMPLETE_THRESHOLD."""
            col = column_map.get(field["name"], {})
            fk_list = col.get("foreign_keys", [])
            if not fk_list:
                return []
            # fk_list entries look like "table_name.column"
            ref_table = fk_list[0].split(".")[0]
            related_model = self.registry.get_by_table_name(ref_table)
            if related_model is None:
                return []
            count = await self.executor.count_all(
                model=related_model,
                database=database,
            )
            if count > AUTOCOMPLETE_THRESHOLD:
                return None  # Signal: use autocomplete widget
            records = await self.executor.fetch_all(
                model=related_model,
                database=database,
            )
            related_meta = self.registry.get(related_model)["metadata"]
            pk_names = related_meta["introspection"]["primary_keys"]
            pk = pk_names[0] if pk_names else None
            # Find first string column for label
            label_col = None
            for rc in related_meta["introspection"]["columns"]:
                if not rc["primary_key"] and (
                    "char" in rc["type"].lower() or "string" in rc["type"].lower()
                ):
                    label_col = rc["name"]
                    break
            options = []
            for obj in records:
                value = getattr(obj, pk) if pk else str(obj)
                label = getattr(obj, label_col) if label_col else str(value)
                options.append({"value": value, "label": label})
            return options

        async def _build_fk_context() -> tuple:
            """Returns (fk_options dict, autocomplete_fields set)."""
            fk_options: Dict[str, list] = {}
            autocomplete_fields: set = set()
            for field in editable_fields:
                if field["widget"] == "select":
                    opts = await _get_fk_options(field)
                    if opts is None:
                        autocomplete_fields.add(field["name"])
                        fk_options[field["name"]] = []
                    else:
                        fk_options[field["name"]] = opts
            return fk_options, autocomplete_fields

        @self.router.get(f"/ui/{table_name}/create/")
        async def create_form(request: Request):
            fk_options, autocomplete_fields = await _build_fk_context()

            return self.templates.TemplateResponse(
                request,
                "admin/create.html",
                {
                    "table_name": table_name,
                    "fields": editable_fields,
                    "fk_options": fk_options,
                    "autocomplete_fields": autocomplete_fields,
                    "errors": {},
                    "values": {},
                    "title": self.title,
                },
            )

        @self.router.post(f"/ui/{table_name}/create/")
        async def create_submit(request: Request):
            form_data = await request.form()

            data, errors = await self.validator.validate_form(
                fields=editable_fields + m2m_fields,
                column_map=column_map,
                form_data=form_data,
                database=database,
                fk_info=fk_info,
                m2m_info=m2m_info,
            )

            if errors:
                fk_options, autocomplete_fields = await _build_fk_context()

                return self.templates.TemplateResponse(
                    request,
                    "admin/create.html",
                    {
                        "table_name": table_name,
                        "fields": editable_fields,
                        "fk_options": fk_options,
                        "autocomplete_fields": autocomplete_fields,
                        "errors": errors,
                        "values": dict(form_data),
                        "title": self.title,
                    },
                    status_code=422,
                )

            # Separate scalar data from M2M data; executor handles columns only
            m2m_field_names = {f["name"] for f in m2m_fields}
            scalar_data = {k: v for k, v in data.items() if k not in m2m_field_names}

            await self.executor.insert_one(model=model, database=database, data=scalar_data)
            return RedirectResponse(
                url=f"{self.base_path}/ui/{table_name}/",
                status_code=303,
            )

    def _create_edit_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        fields = metadata["fields"]
        pk_names = metadata["introspection"]["primary_keys"]
        pk_name = pk_names[0] if pk_names else "id"

        column_map = {col["name"]: col for col in columns}

        editable_fields = [
            f for f in fields
            if not f["readonly"] and f["name"] in column_map
        ]

        # M2M relationship fields for validation
        m2m_fields = [
            f for f in fields
            if not f["readonly"] and f["name"] not in column_map and f.get("multiple")
        ]

        fk_info = self._build_fk_info(editable_fields, column_map)
        m2m_info = self._build_m2m_info(metadata["introspection"]["relationships"])

        async def _get_fk_options(field: Dict[str, Any]) -> Optional[list]:
            """Return list of options, or None if relation exceeds AUTOCOMPLETE_THRESHOLD."""
            col = column_map.get(field["name"], {})
            fk_list = col.get("foreign_keys", [])
            if not fk_list:
                return []
            ref_table = fk_list[0].split(".")[0]
            related_model = self.registry.get_by_table_name(ref_table)
            if related_model is None:
                return []
            count = await self.executor.count_all(
                model=related_model,
                database=database,
            )
            if count > AUTOCOMPLETE_THRESHOLD:
                return None  # Signal: use autocomplete widget
            records = await self.executor.fetch_all(
                model=related_model,
                database=database,
            )
            related_meta = self.registry.get(related_model)["metadata"]
            pk_names_rel = related_meta["introspection"]["primary_keys"]
            pk_rel = pk_names_rel[0] if pk_names_rel else None
            label_col = None
            for rc in related_meta["introspection"]["columns"]:
                if not rc["primary_key"] and (
                    "char" in rc["type"].lower() or "string" in rc["type"].lower()
                ):
                    label_col = rc["name"]
                    break
            options = []
            for obj in records:
                value = getattr(obj, pk_rel) if pk_rel else str(obj)
                label = getattr(obj, label_col) if label_col else str(value)
                options.append({"value": value, "label": label})
            return options

        async def _build_fk_context() -> tuple:
            """Returns (fk_options dict, autocomplete_fields set)."""
            fk_options: Dict[str, list] = {}
            autocomplete_fields: set = set()
            for field in editable_fields:
                if field["widget"] == "select":
                    opts = await _get_fk_options(field)
                    if opts is None:
                        autocomplete_fields.add(field["name"])
                        fk_options[field["name"]] = []
                    else:
                        fk_options[field["name"]] = opts
            return fk_options, autocomplete_fields

        @self.router.get(f"/ui/{table_name}/{{pk}}/edit/")
        async def edit_form(request: Request, pk: str):
            obj = await self.executor.fetch_one(
                model=model, database=database, pk_name=pk_name, pk_value=pk
            )
            if obj is None:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )

            values = {col["name"]: getattr(obj, col["name"]) for col in columns}

            fk_options, autocomplete_fields = await _build_fk_context()

            return self.templates.TemplateResponse(
                request,
                "admin/edit.html",
                {
                    "table_name": table_name,
                    "fields": editable_fields,
                    "fk_options": fk_options,
                    "autocomplete_fields": autocomplete_fields,
                    "errors": {},
                    "values": values,
                    "pk_name": pk_name,
                    "pk_value": pk,
                    "title": self.title,
                },
            )

        @self.router.post(f"/ui/{table_name}/{{pk}}/edit/")
        async def edit_submit(request: Request, pk: str):
            obj = await self.executor.fetch_one(
                model=model, database=database, pk_name=pk_name, pk_value=pk
            )
            if obj is None:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )

            form_data = await request.form()

            data, errors = await self.validator.validate_form(
                fields=editable_fields + m2m_fields,
                column_map=column_map,
                form_data=form_data,
                database=database,
                fk_info=fk_info,
                m2m_info=m2m_info,
            )

            if errors:
                fk_options, autocomplete_fields = await _build_fk_context()

                return self.templates.TemplateResponse(
                    request,
                    "admin/edit.html",
                    {
                        "table_name": table_name,
                        "fields": editable_fields,
                        "fk_options": fk_options,
                        "autocomplete_fields": autocomplete_fields,
                        "errors": errors,
                        "values": dict(form_data),
                        "pk_name": pk_name,
                        "pk_value": pk,
                        "title": self.title,
                    },
                    status_code=422,
                )

            # Separate scalar data from M2M data; executor handles columns only
            m2m_field_names = {f["name"] for f in m2m_fields}
            scalar_data = {k: v for k, v in data.items() if k not in m2m_field_names}

            await self.executor.update_one(
                model=model, database=database,
                pk_name=pk_name, pk_value=pk, data=scalar_data,
            )
            return RedirectResponse(
                url=f"{self.base_path}/ui/{table_name}/",
                status_code=303,
            )

    def _create_delete_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        pk_names = metadata["introspection"]["primary_keys"]
        pk_name = pk_names[0] if pk_names else "id"

        @self.router.get(f"/ui/{table_name}/{{pk}}/delete/")
        async def delete_confirm(request: Request, pk: str):
            obj = await self.executor.fetch_one(
                model=model, database=database, pk_name=pk_name, pk_value=pk
            )
            if obj is None:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )

            values = {col["name"]: getattr(obj, col["name"]) for col in columns}

            return self.templates.TemplateResponse(
                request,
                "admin/delete.html",
                {
                    "table_name": table_name,
                    "pk_name": pk_name,
                    "pk_value": pk,
                    "values": values,
                    "title": self.title,
                },
            )

        @self.router.post(f"/ui/{table_name}/{{pk}}/delete/")
        async def delete_submit(request: Request, pk: str):
            deleted = await self.executor.delete_one(
                model=model, database=database, pk_name=pk_name, pk_value=pk
            )
            if not deleted:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )
            return RedirectResponse(
                url=f"{self.base_path}/ui/{table_name}/",
                status_code=303,
            )

    def _create_bulk_delete_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        pk_names = metadata["introspection"]["primary_keys"]
        pk_name = pk_names[0] if pk_names else "id"

        @self.router.post(f"/ui/{table_name}/bulk-delete/")
        async def bulk_delete_confirm(request: Request):
            form_data = await request.form()
            raw_pks = form_data.getlist("pks")

            if not raw_pks:
                return RedirectResponse(
                    url=f"{self.base_path}/ui/{table_name}/",
                    status_code=303,
                )

            objects = []
            for raw_pk in raw_pks:
                obj = await self.executor.fetch_one(
                    model=model, database=database, pk_name=pk_name, pk_value=raw_pk
                )
                if obj is not None:
                    values = {col["name"]: getattr(obj, col["name"]) for col in columns}
                    objects.append({"pk": raw_pk, "values": values})

            if not objects:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )

            return self.templates.TemplateResponse(
                request,
                "admin/bulk_delete.html",
                {
                    "table_name": table_name,
                    "pk_name": pk_name,
                    "objects": objects,
                    "columns": [col["name"] for col in columns],
                    "title": self.title,
                },
            )

        @self.router.post(f"/ui/{table_name}/bulk-delete/confirm/")
        async def bulk_delete_submit(request: Request):
            form_data = await request.form()
            raw_pks = form_data.getlist("pks")

            if not raw_pks:
                return RedirectResponse(
                    url=f"{self.base_path}/ui/{table_name}/",
                    status_code=303,
                )

            deleted = await self.executor.delete_many(
                model=model, database=database, pk_name=pk_name, pk_values=raw_pks
            )

            if deleted == 0:
                return self.templates.TemplateResponse(
                    request,
                    "admin/404.html",
                    {"title": self.title, "table_name": table_name},
                    status_code=404,
                )

            return RedirectResponse(
                url=f"{self.base_path}/ui/{table_name}/",
                status_code=303,
            )

    def _create_autocomplete_endpoint(self, model: Type[Any], database: str) -> None:
        table_name = model.__tablename__

        metadata = self.registry.get(model)["metadata"]
        columns = metadata["introspection"]["columns"]
        fields = metadata["fields"]
        column_map = {col["name"]: col for col in columns}

        # Build a map of valid FK fields → related model info (resolved at registration time)
        fk_field_info: Dict[str, Dict[str, Any]] = {}
        for field in fields:
            if field["widget"] != "select":
                continue
            col = column_map.get(field["name"], {})
            fk_list = col.get("foreign_keys", [])
            if not fk_list:
                continue
            ref_table = fk_list[0].split(".")[0]
            related_model = self.registry.get_by_table_name(ref_table)
            if related_model is None:
                continue
            related_meta = self.registry.get(related_model)["metadata"]
            pk_names = related_meta["introspection"]["primary_keys"]
            pk = pk_names[0] if pk_names else None
            label_col = None
            for rc in related_meta["introspection"]["columns"]:
                if not rc["primary_key"] and (
                    "char" in rc["type"].lower() or "string" in rc["type"].lower()
                ):
                    label_col = rc["name"]
                    break
            fk_field_info[field["name"]] = {
                "related_model": related_model,
                "pk": pk,
                "label_col": label_col,
            }

        @self.router.get(f"/api/{table_name}/autocomplete/")
        async def autocomplete(
            field: str,
            q: str = "",
            limit: int = Query(20, le=50),
        ):
            if field not in fk_field_info:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid field: '{field}'"},
                )

            info = fk_field_info[field]
            related_model = info["related_model"]
            pk = info["pk"]
            label_col = info["label_col"]
            searchable = [label_col] if label_col else []

            search_arg = q if q else None
            total, records = await asyncio.gather(
                self.executor.count_all(
                    model=related_model,
                    database=database,
                    search=search_arg,
                    searchable_columns=searchable,
                ),
                self.executor.fetch_all(
                    model=related_model,
                    database=database,
                    limit=limit,
                    search=search_arg,
                    searchable_columns=searchable,
                ),
            )

            results = []
            for obj in records:
                value = getattr(obj, pk) if pk else str(obj)
                label = getattr(obj, label_col) if label_col else str(value)
                results.append({"value": value, "label": label})

            return {"results": results, "total": total}