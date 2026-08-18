import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    specialist_model: str = field(default_factory=lambda: os.environ.get(
        "SPECIALIST_MODEL", "claude-haiku-4-5-20251001"))
    synth_model: str = field(default_factory=lambda: os.environ.get("SYNTH_MODEL", "claude-sonnet-5"))
    daily_rate_limit: str = field(default_factory=lambda: os.environ.get("DAILY_RATE_LIMIT", "5/day"))
    cors_origins: str = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "*"))
