import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # Note: the anthropic SDK reads ANTHROPIC_API_KEY from the environment
    # directly, so it is intentionally not mirrored here.
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    specialist_model: str = field(default_factory=lambda: os.environ.get(
        "SPECIALIST_MODEL", "claude-haiku-4-5-20251001"))
    synth_model: str = field(default_factory=lambda: os.environ.get("SYNTH_MODEL", "claude-sonnet-5"))
    daily_rate_limit: str = field(default_factory=lambda: os.environ.get("DAILY_RATE_LIMIT", "5/day"))
    cors_origins: str = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "*"))
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "sqlite+aiosqlite:///./data/app.db"))
    redis_url: str = field(default_factory=lambda: os.environ.get(
        "REDIS_URL", "redis://localhost:6379/0"))
    github_app_id: str = field(default_factory=lambda: os.environ.get("GITHUB_APP_ID", ""))
    github_app_private_key: str = field(default_factory=lambda: os.environ.get(
        "GITHUB_APP_PRIVATE_KEY", ""))
    github_webhook_secret: str = field(default_factory=lambda: os.environ.get(
        "GITHUB_WEBHOOK_SECRET", ""))
    reviews_enabled: bool = field(default_factory=lambda: os.environ.get(
        "REVIEWS_ENABLED", "true").strip().lower() not in ("0", "false", "no"))
    allowed_installation_ids: str = field(default_factory=lambda: os.environ.get(
        "ALLOWED_INSTALLATION_IDS", ""))

    def allowed_installations(self) -> set[int]:
        return {int(part) for part in self.allowed_installation_ids.split(",") if part.strip()}
