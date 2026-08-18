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
    run_db_path: str = field(default_factory=lambda: os.environ.get("RUN_DB_PATH", "./data/runs.db"))
