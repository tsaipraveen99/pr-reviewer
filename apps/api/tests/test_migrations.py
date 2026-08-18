import subprocess
import sys

import sqlalchemy as sa


def test_upgrade_head_on_empty_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/m.db")
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "m.db").exists()


def test_upgrade_head_creates_app_tables(tmp_path, monkeypatch):
    """Verify alembic upgrade head creates installations, repos, reviews with proper schema."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/mig.db")
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr

    # Inspect the database schema
    engine = sa.create_engine(f"sqlite:///{tmp_path}/mig.db")
    insp = sa.inspect(engine)

    # Check tables exist
    assert set(insp.get_table_names()) >= {"installations", "repos", "reviews"}

    # Check unique index on reviews
    idx = {i["name"]: i for i in insp.get_indexes("reviews")}
    assert idx["uq_reviews_repo_pr_sha"]["unique"]
    assert idx["uq_reviews_repo_pr_sha"]["column_names"] == [
        "repo_id",
        "pr_number",
        "head_sha",
    ]

    # Check foreign key from reviews to repos
    fks = insp.get_foreign_keys("reviews")
    assert any(fk["referred_table"] == "repos" for fk in fks)


def test_upgrade_head_creates_graph_tables(tmp_path, monkeypatch):
    """Verify alembic upgrade head creates files, symbols, edges with proper schema."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/mig2.db")
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr

    # Inspect the database schema
    engine = sa.create_engine(f"sqlite:///{tmp_path}/mig2.db")
    insp = sa.inspect(engine)

    # Check tables exist
    assert set(insp.get_table_names()) >= {"files", "symbols", "edges"}

    # Check unique index on files
    files_idx = {i["name"]: i for i in insp.get_indexes("files")}
    assert files_idx["ix_files_repo_path"]["unique"]

    # Check foreign keys on edges: one CASCADE, one SET NULL
    edge_fks = insp.get_foreign_keys("edges")
    deletes = {fk["options"].get("ondelete") for fk in edge_fks}
    assert deletes == {"CASCADE", "SET NULL"}
