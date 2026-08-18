from prcrew.settings import Settings


def test_database_url_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings().database_url == "sqlite+aiosqlite:///./data/app.db"


def test_database_url_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    assert Settings().database_url == "postgresql+psycopg://u:p@h/db"


def test_redis_url_default(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert Settings().redis_url == "redis://localhost:6379/0"
