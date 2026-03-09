"""Tests for QueryOptimizer — N+1 protection via eager loading."""
import pytest
from sqlalchemy import Column, Integer, String, ForeignKey, event, select
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from aegis.core.optimizer import QueryOptimizer
from aegis.core.executor import DBExecutor
from aegis.core.engine import EngineManager

Base = declarative_base()


class Author(Base):
    __tablename__ = "authors_opt"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    books = relationship("BookOpt", back_populates="author")


class BookOpt(Base):
    __tablename__ = "books_opt"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    author_id = Column(Integer, ForeignKey("authors_opt.id"))
    author = relationship("Author", back_populates="books")


def make_query_counter(engine):
    """Attaches a before_cursor_execute listener and returns a mutable counter dict."""
    counter = {"value": 0}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["value"] += 1

    return counter


async def _setup_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_authors_with_books(engine, n_authors=5, books_per_author=3):
    async with AsyncSession(engine) as session:
        for i in range(n_authors):
            author = Author(name=f"Author {i}")
            author.books = [BookOpt(title=f"Book {i}-{j}") for j in range(books_per_author)]
            session.add(author)
        await session.commit()


# ---------------------------------------------------------------------------
# Unit tests for QueryOptimizer.build_options
# ---------------------------------------------------------------------------

def test_build_options_returns_selectinload_for_collection():
    optimizer = QueryOptimizer()
    relationships = [
        {"name": "books", "uselist": True, "target": "BookOpt", "secondary": False}
    ]
    options = optimizer.build_options(relationships, Author)

    assert len(options) == 1
    # selectinload produces a _SelectInLoad strategy
    from sqlalchemy.orm import selectinload
    expected = selectinload(Author.books)
    assert type(options[0]) == type(expected)


def test_build_options_returns_joinedload_for_scalar():
    optimizer = QueryOptimizer()
    relationships = [
        {"name": "author", "uselist": False, "target": "Author", "secondary": False}
    ]
    options = optimizer.build_options(relationships, BookOpt)

    assert len(options) == 1
    from sqlalchemy.orm import joinedload
    expected = joinedload(BookOpt.author)
    assert type(options[0]) == type(expected)


def test_build_options_skips_missing_attributes():
    optimizer = QueryOptimizer()
    relationships = [
        {"name": "nonexistent_rel", "uselist": True, "target": "X", "secondary": False}
    ]
    options = optimizer.build_options(relationships, Author)
    assert options == []


def test_build_options_empty_relationships():
    optimizer = QueryOptimizer()
    options = optimizer.build_options([], Author)
    assert options == []


def test_build_options_mixed_relationships():
    optimizer = QueryOptimizer()
    relationships = [
        {"name": "books", "uselist": True, "target": "BookOpt", "secondary": False},
        {"name": "author", "uselist": False, "target": "Author", "secondary": False},
    ]
    # Author has 'books', BookOpt has 'author' — use Author to test uselist=True branch
    options = optimizer.build_options(
        [{"name": "books", "uselist": True, "target": "BookOpt", "secondary": False}],
        Author,
    )
    assert len(options) == 1

    options2 = optimizer.build_options(
        [{"name": "author", "uselist": False, "target": "Author", "secondary": False}],
        BookOpt,
    )
    assert len(options2) == 1


# ---------------------------------------------------------------------------
# Integration tests: query count assertions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_selectinload_uses_two_queries_not_n_plus_1():
    """fetch_all with selectinload emits exactly 2 queries for 5 authors with books."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_authors_with_books(engine, n_authors=5, books_per_author=3)

    manager = EngineManager({"default": engine})
    executor = DBExecutor(manager)
    optimizer = QueryOptimizer()

    relationships = [{"name": "books", "uselist": True, "target": "BookOpt", "secondary": False}]
    eager_loads = optimizer.build_options(relationships, Author)

    counter = make_query_counter(engine)
    counter["value"] = 0

    records = await executor.fetch_all(
        model=Author,
        database="default",
        eager_loads=eager_loads,
    )

    # 1 query for SELECT authors + 1 IN-query for all books (selectinload)
    assert counter["value"] == 2
    assert len(records) == 5


@pytest.mark.asyncio
async def test_query_count_constant_regardless_of_dataset_size():
    """Query count stays at 2 whether we fetch 5 or 20 authors."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_authors_with_books(engine, n_authors=20, books_per_author=5)

    manager = EngineManager({"default": engine})
    executor = DBExecutor(manager)
    optimizer = QueryOptimizer()

    relationships = [{"name": "books", "uselist": True, "target": "BookOpt", "secondary": False}]
    eager_loads = optimizer.build_options(relationships, Author)

    counter = make_query_counter(engine)
    counter["value"] = 0

    records = await executor.fetch_all(
        model=Author,
        database="default",
        limit=20,
        eager_loads=eager_loads,
    )

    # Still exactly 2 queries regardless of 20 records (not 1 + 20)
    assert counter["value"] == 2
    assert len(records) == 20


@pytest.mark.asyncio
async def test_joinedload_uses_single_query_for_scalar_relationship():
    """fetch_all with joinedload emits exactly 1 query for books + their author."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)

    async with AsyncSession(engine) as session:
        for i in range(5):
            author = Author(name=f"AuthorJ {i}")
            session.add(author)
        await session.commit()

        authors = (await session.execute(select(Author))).scalars().all()
        for i, author in enumerate(authors):
            session.add(BookOpt(title=f"BookJ {i}", author_id=author.id))
        await session.commit()

    manager = EngineManager({"default": engine})
    executor = DBExecutor(manager)
    optimizer = QueryOptimizer()

    relationships = [{"name": "author", "uselist": False, "target": "Author", "secondary": False}]
    eager_loads = optimizer.build_options(relationships, BookOpt)

    counter = make_query_counter(engine)
    counter["value"] = 0

    records = await executor.fetch_all(
        model=BookOpt,
        database="default",
        eager_loads=eager_loads,
    )

    # joinedload collapses everything into a single JOIN query
    assert counter["value"] == 1
    assert len(records) == 5


@pytest.mark.asyncio
async def test_no_eager_loads_skips_relationship_loading():
    """Without eager_loads, fetch_all still works — just returns scalar columns."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_authors_with_books(engine, n_authors=3, books_per_author=2)

    manager = EngineManager({"default": engine})
    executor = DBExecutor(manager)

    counter = make_query_counter(engine)
    counter["value"] = 0

    records = await executor.fetch_all(
        model=Author,
        database="default",
    )

    # Without eager loading only 1 query is emitted (no relationship loading)
    assert counter["value"] == 1
    assert len(records) == 3


@pytest.mark.asyncio
async def test_eager_loads_integrated_via_aegis_register():
    """Aegis.register() auto-applies eager loads; list endpoint uses correct query count."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from aegis.core.app import Aegis
    from aegis.core.auth import AllowAllAuthBackend

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _setup_db(engine)
    await _seed_authors_with_books(engine, n_authors=4, books_per_author=3)

    app = FastAPI()
    aegis = Aegis(app=app, engines={"default": engine}, auth_backend=AllowAllAuthBackend())
    aegis.register(Author)

    # Confirm eager_loads was set in metadata
    metadata = aegis.registry.get(Author)["metadata"]
    assert "eager_loads" in metadata
    assert len(metadata["eager_loads"]) == 1  # one relationship: books

    counter = make_query_counter(engine)
    counter["value"] = 0

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/authors_opt/")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4

    # count_all (1) + fetch_all (1 main + 1 selectinload) = 3 queries
    assert counter["value"] == 3
