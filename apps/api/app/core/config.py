"""Application configuration loaded from environment / .env file.

All secrets are wrapped in `SecretStr` so they never accidentally end up in
log lines or pydantic `model_dump()` output.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level settings — read once at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Gemini ──────────────────────────────────────────────────────────────
    # Defaults are STABLE GA models verified via the live `models.list()` API
    # on 2026-05-14. The Gemini 2.5 family deprecates on 2026-06-17 so the
    # defaults track 3.x where GA. LIVE stays on 2.5 native-audio until the
    # 3.1 live API leaves Preview.
    gemini_api_key: SecretStr = Field(default=SecretStr(""), alias="GEMINI_API_KEY")
    gemini_model_text: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL_TEXT")
    gemini_model_vision: str = Field(default="gemini-3.1-flash-lite", alias="GEMINI_MODEL_VISION")
    gemini_model_live: str = Field(
        default="gemini-3.1-flash-live-preview", alias="GEMINI_MODEL_LIVE"
    )
    gemini_model_pro: str = Field(default="gemini-3.1-pro-preview", alias="GEMINI_MODEL_PRO")
    gemini_model_embed: str = Field(
        default="gemini-embedding-2", alias="GEMINI_MODEL_EMBED"
    )

    # ── Supabase ────────────────────────────────────────────────────────────
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_anon_key: SecretStr = Field(default=SecretStr(""), alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_SERVICE_ROLE_KEY"
    )
    supabase_jwt_secret: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_JWT_SECRET"
    )

    # ── API server ──────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    dev_mode: bool = Field(default=False, alias="DEV_MODE")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # ── Validators / helpers ────────────────────────────────────────────────
    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        """Split comma-separated CORS_ORIGINS into a clean list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def model_map(self) -> dict[str, str]:
        """Public model identifiers (safe to return from /health)."""
        return {
            "text": self.gemini_model_text,
            "vision": self.gemini_model_vision,
            "live": self.gemini_model_live,
            "pro": self.gemini_model_pro,
            "embed": self.gemini_model_embed,
        }

    @property
    def is_production(self) -> bool:
        """True when ENVIRONMENT is set to a recognised prod value."""
        return self.environment.lower() in {"production", "prod"}

    @property
    def is_dev(self) -> bool:
        """True when relaxed-auth dev shortcuts (e.g. X-Dev-User-Id header) are allowed.

        Hard rule: production NEVER allows dev shortcuts even if DEV_MODE=true
        was accidentally set. This is a defense-in-depth gate; pair with the
        startup assertion in `app.main` lifespan.
        """
        if self.is_production:
            return False
        return self.dev_mode


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — call this anywhere."""
    return Settings()


# Module-level singleton for convenience.
settings: Settings = get_settings()
