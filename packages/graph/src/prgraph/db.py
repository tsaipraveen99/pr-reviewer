"""Database models and engine setup for the prgraph system."""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


class File(Base):
    """Represents a source code file.

    Attributes:
        id: Primary key
        repo_id: Repository ID (BigInteger)
        path: Relative path to the file within the repository
        lang: Programming language identifier
        content_hash: SHA256 hash of file content
        parsed_at: Timestamp when the file was parsed
    """

    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    repo_id = Column(BigInteger, nullable=False)
    path = Column(String(512), nullable=False)
    lang = Column(String(16), nullable=False)
    content_hash = Column(String(64), nullable=False)
    parsed_at = Column(DateTime, nullable=False)

    # Unique constraint on (repo_id, path)
    __table_args__ = (Index("ix_files_repo_path", "repo_id", "path", unique=True),)


class Symbol(Base):
    """Represents a symbol (function, class, variable, etc.) in source code.

    Attributes:
        id: Primary key
        repo_id: Repository ID
        file_id: Foreign key to the file containing this symbol
        name: Local name of the symbol
        qualified_name: Fully qualified name of the symbol
        kind: Type of symbol (function, class, variable, etc.)
        start_line: 1-indexed line number where symbol starts (inclusive)
        end_line: 1-indexed line number where symbol ends (inclusive)
    """

    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True)
    repo_id = Column(BigInteger, nullable=False)
    file_id = Column(
        Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(256), nullable=False)
    qualified_name = Column(String(512), nullable=False)
    kind = Column(String(16), nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)

    # Index on (repo_id, qualified_name)
    __table_args__ = (Index("ix_symbols_repo_qualified", "repo_id", "qualified_name"),)


class Edge(Base):
    """Represents a call or reference edge between symbols.

    Attributes:
        id: Primary key
        repo_id: Repository ID
        src_symbol_id: Foreign key to the source symbol (caller)
        dst_symbol_id: Foreign key to the destination symbol (callee), nullable
        dst_qualified_name: Fully qualified name of destination (for external/unresolved calls)
        kind: Type of edge (call, reference, etc.)
    """

    __tablename__ = "edges"

    id = Column(Integer, primary_key=True)
    repo_id = Column(BigInteger, nullable=False)
    src_symbol_id = Column(
        Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    dst_symbol_id = Column(
        Integer, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True
    )
    dst_qualified_name = Column(String(512), nullable=False)
    kind = Column(String(16), nullable=False)

    # Indexes on source and destination
    __table_args__ = (
        Index("ix_edges_src", "src_symbol_id"),
        Index("ix_edges_dst", "dst_symbol_id"),
    )


def make_engine(url: str) -> Engine:
    """Create a SQLAlchemy engine.

    Args:
        url: Database URL (required; caller must provide sqlite:/// or other URL).

    Returns:
        A SQLAlchemy Engine instance with foreign key constraints enabled for SQLite.
    """
    engine = create_engine(url)

    # For SQLite, enable foreign key constraints on each connection. This is
    # a SQLite-only pragma: on Postgres (or any other dialect) it's a syntax
    # error, so only register the listener when the engine is actually
    # sqlite -- never register it, rather than register-then-no-op, so a
    # non-sqlite engine never even attempts the statement.
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory for the given engine.

    Args:
        engine: SQLAlchemy Engine instance.

    Returns:
        A sessionmaker instance (callable that creates sessions).
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create all tables in the database.

    Args:
        engine: SQLAlchemy Engine instance.
    """
    Base.metadata.create_all(engine)
