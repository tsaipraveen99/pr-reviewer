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


def test_app_settings_defaults(monkeypatch):
    for var in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET",
                "REVIEWS_ENABLED", "ALLOWED_INSTALLATION_IDS"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.github_app_id == ""
    assert s.github_app_private_key == ""
    assert s.github_webhook_secret == ""
    assert s.reviews_enabled is True
    assert s.allowed_installations() == set()


def test_app_settings_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("REVIEWS_ENABLED", "false")
    monkeypatch.setenv("ALLOWED_INSTALLATION_IDS", "111, 222")
    s = Settings()
    assert s.github_app_id == "12345"
    assert s.reviews_enabled is False
    assert s.allowed_installations() == {111, 222}


def test_run_db_path_removed():
    assert not hasattr(Settings(), "run_db_path")


def test_phase4_settings_defaults(monkeypatch):
    for var in ("INTENT_MODEL", "CLONES_DIR", "MAX_PR_FILES", "MAX_PR_LINES", "DAILY_REPO_CAP"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.intent_model == "claude-sonnet-5"
    assert s.clones_dir == "./data/clones"
    assert (s.max_pr_files, s.max_pr_lines, s.daily_repo_cap) == (40, 1500, 20)


def test_phase4_settings_env(monkeypatch):
    monkeypatch.setenv("MAX_PR_FILES", "10")
    monkeypatch.setenv("DAILY_REPO_CAP", "3")
    s = Settings()
    assert s.max_pr_files == 10 and s.daily_repo_cap == 3


def test_intent_token_budget(monkeypatch):
    monkeypatch.delenv("INTENT_TOKEN_BUDGET", raising=False)
    assert Settings().intent_token_budget == 200000
    monkeypatch.setenv("INTENT_TOKEN_BUDGET", "50000")
    assert Settings().intent_token_budget == 50000
