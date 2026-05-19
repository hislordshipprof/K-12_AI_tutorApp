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
    # Lesson-step read-aloud TTS (`model-strategy.md` §3b) — a dedicated
    # text-to-speech model that reads verbatim, replacing the Live
    # audio-to-audio hack. One-shot generate call per step.
    gemini_model_tts: str = Field(
        default="gemini-3.1-flash-tts-preview", alias="GEMINI_MODEL_TTS"
    )
    gemini_model_pro: str = Field(default="gemini-3.1-pro-preview", alias="GEMINI_MODEL_PRO")
    gemini_model_embed: str = Field(
        default="gemini-embedding-2", alias="GEMINI_MODEL_EMBED"
    )
    # Comprehend + segment a unit upload (`model-strategy.md` §6): a one-shot,
    # quality-critical multimodal call that sets the whole topic tree. Runs on
    # `gemini-3-flash-preview`, escalating to the pinned PRO model for a large
    # or messy deck. `segment_escalate_pages` is the combined-page threshold at
    # which a deck escalates to PRO; `segment_chunk_pages` is the page count
    # above which the combined payload is chunked and the breakdowns merged.
    gemini_model_segment: str = Field(
        default="gemini-3-flash-preview", alias="GEMINI_MODEL_SEGMENT"
    )
    segment_escalate_pages: int = Field(default=60, alias="SEGMENT_ESCALATE_PAGES")
    segment_chunk_pages: int = Field(default=200, alias="SEGMENT_CHUNK_PAGES")
    # Course cover art — Nano Banana 2 (`model-strategy.md` §4): the
    # high-volume / efficient image model, generated once per course at
    # publish. Pinned (a generation path — `model-strategy.md` §8).
    gemini_model_image: str = Field(
        default="gemini-3.1-flash-image-preview", alias="GEMINI_MODEL_IMAGE"
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

    # ── Teacher ingest pipeline (teacher-authoring.md §6 "Ingest") ───────────
    # Uploads are untrusted: a per-file size cap, the LibreOffice conversion
    # timeout, and a per-teacher rate-limit + daily quota bound the expensive
    # multimodal/Pro calls a runaway upload loop would otherwise trigger.
    ingest_max_file_mb: int = Field(default=50, alias="INGEST_MAX_FILE_MB")
    ingest_convert_timeout_s: int = Field(
        default=120, alias="INGEST_CONVERT_TIMEOUT_S"
    )
    ingest_rate_per_minute: int = Field(default=10, alias="INGEST_RATE_PER_MINUTE")
    ingest_quota_per_day: int = Field(default=100, alias="INGEST_QUOTA_PER_DAY")

    # ── Slide rendering (teacher-authoring.md §6 "Render", §7) ───────────────
    # `pymupdf` rasterises a claimed slide/figure page to a PNG that the
    # classroom shows as a backdrop under Aria's scene annotations. The DPI
    # sets the raster resolution — 150 DPI renders a US-letter slide to a
    # ~1275x1650 PNG, sharp enough for a full-screen backdrop without bloating
    # Storage.
    render_dpi: int = Field(default=150, alias="RENDER_DPI")

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
            "segment": self.gemini_model_segment,
        }

    @property
    def is_production(self) -> bool:
        """True when ENVIRONMENT is set to a recognised prod value."""
        return self.environment.lower() in {"production", "prod"}

    @property
    def is_local_environment(self) -> bool:
        """True only when ENVIRONMENT names a genuine local-development env.

        The relaxed-auth dev shortcut (`X-Dev-User-Id`) is allowed *only* in
        these environments. Anything else — production, staging, or an
        unrecognised value — is treated as non-local and the shortcut stays
        off, no matter what DEV_MODE says.
        """
        return self.environment.lower() in {"development", "dev", "local", "test"}

    @property
    def is_dev(self) -> bool:
        """True when relaxed-auth dev shortcuts (e.g. X-Dev-User-Id header) are allowed.

        Hard rule: the dev shortcut is honoured ONLY when DEV_MODE is on AND
        the process is running in a genuine local-development environment.
        Production and staging NEVER allow it, even if DEV_MODE=true was
        accidentally set. This is a defense-in-depth gate; pair with the
        startup assertion in `app.main` lifespan.
        """
        if not self.is_local_environment:
            return False
        return self.dev_mode


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — call this anywhere."""
    return Settings()


# Module-level singleton for convenience.
settings: Settings = get_settings()
