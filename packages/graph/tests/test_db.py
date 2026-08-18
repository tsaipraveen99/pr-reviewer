"""Tests for database models and schema."""

import types
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

import prgraph.db as db_module
from prgraph.db import (
    Edge,
    File,
    Symbol,
    create_schema,
    make_engine,
    make_session_factory,
)


def _fake_pg8000_module() -> types.ModuleType:
    """A minimal fake `pg8000` DBAPI module -- just enough for SQLAlchemy's
    postgresql+pg8000 dialect to build an Engine and report dialect.name ==
    "postgresql", without the real `pg8000` package installed and without
    ever opening a real connection.
    """
    fake = types.ModuleType("fake_pg8000")
    fake.paramstyle = "format"

    class Error(Exception):
        pass

    fake.Error = Error
    fake.connect = lambda *a, **k: None
    fake.__version__ = "1.30.0"
    return fake


def test_db_cascade_deletes(tmp_path):
    """Test that deleting a File cascades to Symbols and their Edges."""
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_schema(engine)

    SessionFactory = make_session_factory(engine)
    session = SessionFactory()

    # Insert a File
    file = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="abc123",
        parsed_at=datetime.now(UTC),
    )
    session.add(file)
    session.flush()
    file_id = file.id

    # Insert a Symbol
    symbol = Symbol(
        repo_id=1,
        file_id=file_id,
        name="my_func",
        qualified_name="module.my_func",
        kind="function",
        start_line=1,
        end_line=5,
    )
    session.add(symbol)
    session.flush()
    symbol_id = symbol.id

    # Insert another symbol to test the nullable FK
    symbol2 = Symbol(
        repo_id=1,
        file_id=file_id,
        name="other_func",
        qualified_name="module.other_func",
        kind="function",
        start_line=7,
        end_line=10,
    )
    session.add(symbol2)
    session.flush()
    symbol2_id = symbol2.id

    # Insert an Edge from symbol to symbol2
    edge1 = Edge(
        repo_id=1,
        src_symbol_id=symbol_id,
        dst_symbol_id=symbol2_id,
        dst_qualified_name="module.other_func",
        kind="calls",
    )
    session.add(edge1)

    # Insert an Edge with unresolved destination (dst_symbol_id is None)
    edge2 = Edge(
        repo_id=1,
        src_symbol_id=symbol_id,
        dst_symbol_id=None,
        dst_qualified_name="external.func",
        kind="calls",
    )
    session.add(edge2)

    session.commit()

    # Verify initial state
    assert session.query(File).count() == 1
    assert session.query(Symbol).count() == 2
    assert session.query(Edge).count() == 2

    # Delete the file
    session.query(File).filter(File.id == file_id).delete()
    session.commit()

    # Verify cascading deletes
    # File is deleted
    assert session.query(File).count() == 0
    # Symbols referencing the file should be cascade-deleted
    assert session.query(Symbol).count() == 0
    # Edges from deleted symbols should be cascade-deleted
    assert session.query(Edge).count() == 0


def test_file_unique_constraint(tmp_path):
    """Test that File has a unique constraint on (repo_id, path)."""
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_schema(engine)

    SessionFactory = make_session_factory(engine)
    session = SessionFactory()

    # Insert first file
    file1 = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="abc123",
        parsed_at=datetime.now(UTC),
    )
    session.add(file1)
    session.commit()

    # Try to insert a duplicate (same repo_id and path) - should fail
    file2 = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="def456",
        parsed_at=datetime.now(UTC),
    )
    session.add(file2)

    with pytest.raises(IntegrityError):
        session.commit()


def test_symbol_file_cascade(tmp_path):
    """Test that deleting a File cascades to Symbols."""
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_schema(engine)

    SessionFactory = make_session_factory(engine)
    session = SessionFactory()

    # Insert a File
    file = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="abc123",
        parsed_at=datetime.now(UTC),
    )
    session.add(file)
    session.flush()
    file_id = file.id

    # Insert multiple Symbols
    for i in range(3):
        symbol = Symbol(
            repo_id=1,
            file_id=file_id,
            name=f"func{i}",
            qualified_name=f"module.func{i}",
            kind="function",
            start_line=i * 10 + 1,
            end_line=i * 10 + 5,
        )
        session.add(symbol)
    session.commit()

    assert session.query(Symbol).count() == 3

    # Delete the file
    session.query(File).filter(File.id == file_id).delete()
    session.commit()

    # All symbols should be cascade-deleted
    assert session.query(Symbol).count() == 0


def test_edge_cascade_delete_on_symbol(tmp_path):
    """Test that deleting a Symbol cascades to its outgoing Edges."""
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_schema(engine)

    SessionFactory = make_session_factory(engine)
    session = SessionFactory()

    # Insert a File
    file = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="abc123",
        parsed_at=datetime.now(UTC),
    )
    session.add(file)
    session.flush()
    file_id = file.id

    # Insert two Symbols
    symbol1 = Symbol(
        repo_id=1,
        file_id=file_id,
        name="func1",
        qualified_name="module.func1",
        kind="function",
        start_line=1,
        end_line=5,
    )
    session.add(symbol1)
    session.flush()
    symbol1_id = symbol1.id

    symbol2 = Symbol(
        repo_id=1,
        file_id=file_id,
        name="func2",
        qualified_name="module.func2",
        kind="function",
        start_line=7,
        end_line=10,
    )
    session.add(symbol2)
    session.flush()
    symbol2_id = symbol2.id

    # Insert an Edge from symbol1 to symbol2
    edge = Edge(
        repo_id=1,
        src_symbol_id=symbol1_id,
        dst_symbol_id=symbol2_id,
        dst_qualified_name="module.func2",
        kind="calls",
    )
    session.add(edge)
    session.commit()

    assert session.query(Edge).count() == 1

    # Delete symbol1 (source of the edge)
    session.query(Symbol).filter(Symbol.id == symbol1_id).delete()
    session.commit()

    # The edge should be cascade-deleted
    assert session.query(Edge).count() == 0
    # symbol2 should still exist
    assert session.query(Symbol).count() == 1


def test_edge_set_null_on_destination(tmp_path):
    """Test that deleting a destination Symbol sets Edge.dst_symbol_id to NULL."""
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_schema(engine)

    SessionFactory = make_session_factory(engine)
    session = SessionFactory()

    # Insert a File
    file = File(
        repo_id=1,
        path="test.py",
        lang="python",
        content_hash="abc123",
        parsed_at=datetime.now(UTC),
    )
    session.add(file)
    session.flush()
    file_id = file.id

    # Insert two Symbols
    symbol1 = Symbol(
        repo_id=1,
        file_id=file_id,
        name="func1",
        qualified_name="module.func1",
        kind="function",
        start_line=1,
        end_line=5,
    )
    session.add(symbol1)
    session.flush()
    symbol1_id = symbol1.id

    symbol2 = Symbol(
        repo_id=1,
        file_id=file_id,
        name="func2",
        qualified_name="module.func2",
        kind="function",
        start_line=7,
        end_line=10,
    )
    session.add(symbol2)
    session.flush()
    symbol2_id = symbol2.id

    # Insert an Edge from symbol1 to symbol2
    edge = Edge(
        repo_id=1,
        src_symbol_id=symbol1_id,
        dst_symbol_id=symbol2_id,
        dst_qualified_name="module.func2",
        kind="calls",
    )
    session.add(edge)
    session.commit()

    assert session.query(Edge).count() == 1
    assert session.query(Edge).first().dst_symbol_id == symbol2_id

    # Delete symbol2 (destination of the edge)
    session.query(Symbol).filter(Symbol.id == symbol2_id).delete()
    session.commit()

    # Create a new session to read fresh data from database
    session = SessionFactory()

    # The edge should still exist but with dst_symbol_id set to NULL
    assert session.query(Edge).count() == 1
    edge_after = session.query(Edge).first()
    assert edge_after.dst_symbol_id is None
    assert edge_after.dst_qualified_name == "module.func2"
    # symbol1 should still exist
    assert session.query(Symbol).count() == 1


def test_make_engine_sqlite_registers_connect_listener(tmp_path, monkeypatch):
    """The sqlite FK pragma listener is registered for a sqlite engine."""
    calls = []
    original_listens_for = db_module.event.listens_for

    def spy_listens_for(target, identifier):
        calls.append((target, identifier))
        return original_listens_for(target, identifier)

    monkeypatch.setattr(db_module.event, "listens_for", spy_listens_for)

    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")

    assert engine.dialect.name == "sqlite"
    assert any(
        target is engine and identifier == "connect" for target, identifier in calls
    )


def test_make_engine_postgres_does_not_register_sqlite_pragma_listener(
    tmp_path, monkeypatch
):
    """Non-sqlite engines must not get the sqlite-only FK pragma connect
    listener -- on Postgres, `PRAGMA foreign_keys=ON` is a syntax error on
    every connection. No live Postgres is needed: a fake `pg8000` DBAPI
    module lets SQLAlchemy build a real postgresql-dialect Engine without
    ever opening a socket.
    """
    real_create_engine = db_module.create_engine
    fake_dbapi = _fake_pg8000_module()

    def fake_create_engine(url, **kwargs):
        return real_create_engine(url, module=fake_dbapi, **kwargs)

    monkeypatch.setattr(db_module, "create_engine", fake_create_engine)

    calls = []
    original_listens_for = db_module.event.listens_for

    def spy_listens_for(target, identifier):
        calls.append((target, identifier))
        return original_listens_for(target, identifier)

    monkeypatch.setattr(db_module.event, "listens_for", spy_listens_for)

    engine = make_engine("postgresql+pg8000://user:pass@localhost/db")

    assert engine.dialect.name == "postgresql"
    assert not any(
        target is engine and identifier == "connect" for target, identifier in calls
    )
