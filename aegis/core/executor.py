from typing import Any, List, Optional
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class DBExecutor:
    def __init__(self, engine_manager):
        self.engine_manager = engine_manager

    async def fetch_all(
        self,
        model: Any,
        database: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        searchable_columns: Optional[List[str]] = None,
        filters: Optional[dict] = None,
        eager_loads: Optional[List] = None,
    ) -> List[Any]:
        engine = self.engine_manager.get_engine(database)

        stmt = select(model)

        if eager_loads:
            stmt = stmt.options(*eager_loads)

        if search and searchable_columns:
            search_filters = [
                getattr(model, col).ilike(f"%{search}%")
                for col in searchable_columns
            ]
            stmt = stmt.where(or_(*search_filters))

        if filters:
            for col_name, value in filters.items():
                stmt = stmt.where(getattr(model, col_name) == value)

        stmt = stmt.limit(limit).offset(offset)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                return result.scalars().all()
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                return result.scalars().all()

    async def count_all(
        self,
        model: Any,
        database: str,
        search: Optional[str] = None,
        searchable_columns: Optional[List[str]] = None,
        filters: Optional[dict] = None,
    ) -> int:
        engine = self.engine_manager.get_engine(database)

        stmt = select(func.count()).select_from(model)

        if search and searchable_columns:
            search_filters = [
                getattr(model, col).ilike(f"%{search}%")
                for col in searchable_columns
            ]
            stmt = stmt.where(or_(*search_filters))

        if filters:
            for col_name, value in filters.items():
                stmt = stmt.where(getattr(model, col_name) == value)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                return result.scalar()
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                return result.scalar()

    async def insert_one(
        self,
        model: Any,
        database: str,
        data: dict,
    ) -> Any:
        engine = self.engine_manager.get_engine(database)
        obj = model(**data)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                session.add(obj)
                await session.commit()
                await session.refresh(obj)
        else:
            with Session(engine) as session:
                session.add(obj)
                session.commit()
                session.refresh(obj)

        return obj

    async def fetch_one(
        self,
        model: Any,
        database: str,
        pk_name: str,
        pk_value: Any,
    ) -> Optional[Any]:
        engine = self.engine_manager.get_engine(database)
        stmt = select(model).where(getattr(model, pk_name) == pk_value)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                return result.scalars().first()
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                return result.scalars().first()

    async def delete_one(
        self,
        model: Any,
        database: str,
        pk_name: str,
        pk_value: Any,
    ) -> bool:
        engine = self.engine_manager.get_engine(database)
        stmt = select(model).where(getattr(model, pk_name) == pk_value)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                obj = result.scalars().first()
                if obj is None:
                    return False
                await session.delete(obj)
                await session.commit()
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                obj = result.scalars().first()
                if obj is None:
                    return False
                session.delete(obj)
                session.commit()

        return True

    async def delete_many(
        self,
        model: Any,
        database: str,
        pk_name: str,
        pk_values: List[Any],
    ) -> int:
        """Delete multiple records by PK. Returns the count of records actually deleted."""
        engine = self.engine_manager.get_engine(database)
        stmt = select(model).where(getattr(model, pk_name).in_(pk_values))

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                objects = result.scalars().all()
                for obj in objects:
                    await session.delete(obj)
                await session.commit()
                return len(objects)
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                objects = result.scalars().all()
                for obj in objects:
                    session.delete(obj)
                session.commit()
                return len(objects)

    async def update_one(
        self,
        model: Any,
        database: str,
        pk_name: str,
        pk_value: Any,
        data: dict,
    ) -> Optional[Any]:
        engine = self.engine_manager.get_engine(database)
        stmt = select(model).where(getattr(model, pk_name) == pk_value)

        if self.engine_manager.is_async(database):
            async with AsyncSession(engine) as session:
                result = await session.execute(stmt)
                obj = result.scalars().first()
                if obj is None:
                    return None
                for key, value in data.items():
                    setattr(obj, key, value)
                await session.commit()
                await session.refresh(obj)
                return obj
        else:
            with Session(engine) as session:
                result = session.execute(stmt)
                obj = result.scalars().first()
                if obj is None:
                    return None
                for key, value in data.items():
                    setattr(obj, key, value)
                session.commit()
                session.refresh(obj)
                return obj