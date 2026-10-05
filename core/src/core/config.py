"""Central configuration loader for SETU-DRR."""

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Find repository root based on file location
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    """Application settings read from environment variables and .env file."""

    # Database
    DATABASE_URL: str = Field(
        default="postgresql://setu:setu@localhost:5432/setu",
        description="Main connection string (direct or pooled).",
    )
    DIRECT_DATABASE_URL: str | None = Field(
        default=None,
        description="Direct non-pooled connection string (required for migrations, Martin, and heavy ETL).",
    )
    TEST_DATABASE_URL: str | None = Field(
        default=None,
        description="Dedicated isolated test database connection string.",
    )

    # Runtime & Mode
    DEMO_MODE: bool = Field(
        default=True,
        description="Serve recorded snapshot with zero live external API calls.",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Application logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    MODEL_VERSION: str = Field(
        default="v1.0.0",
        description="Default machine learning model version tag.",
    )
    MAX_TRIGGER_AGE_HOURS: int = Field(
        default=24,
        description="Maximum dynamic live trigger age in hours to qualify as active alert.",
    )

    # Groq / LLM Decision Support Assistant
    GROQ_API_KEY: str | None = Field(
        default=None,
        description="Groq API key for LLM-powered decision support assistant.",
    )
    GROQ_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Model identifier for Groq LLM completion.",
    )
    GROQ_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for Groq OpenAI-compatible API.",
    )

    # Chat Orchestrator Settings (Phase 1)
    CHAT_MAX_ROUNDS: int = Field(
        default=3,
        description="Maximum tool rounds for the chat orchestrator LLM loop.",
    )
    CHAT_CLASSIFIER: str = Field(
        default="rules",
        description="Classifier mode: 'rules' or 'hybrid'.",
    )
    CHAT_CONFIDENCE_THRESHOLD: float = Field(
        default=0.7,
        description="Confidence threshold below which broad toolset is used.",
    )
    CHAT_TRUST_CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL for cached DataTrustContext in seconds.",
    )

    # Forecast Scheduler & Retention (Phase B8)
    FORECAST_SCHEDULER_ENABLED: bool = Field(
        default=False,
        description="Whether background forecast scheduling is active.",
    )
    FORECAST_SCHEDULE_CRON: str = Field(
        default="0 */6 * * *",
        description="Standard 5-field cron expression for forecast cycle ingestion.",
    )
    FORECAST_RETENTION_RUNS: int = Field(
        default=3,
        description="Number of recent successful forecast cycles to retain per district.",
    )
    FORECAST_MAX_RETRIES: int = Field(
        default=2,
        description="Maximum retry attempts on transient network failures during forecast acquisition.",
    )
    FORECAST_RETRY_DELAY_SECONDS: float = Field(
        default=10.0,
        description="Delay in seconds between retry attempts on provider acquisition failure.",
    )

    # ML Model Checkpoint Paths
    MODEL_CHECKPOINT_PATH: str | None = Field(
        default=None,
        description="Generic path to model checkpoint file or directory containing checkpoints.",
    )
    LANDSLIDE_MODEL_PATH: str | None = Field(
        default=None,
        description="Path to serialized trained landslide model checkpoint.",
    )
    FLOOD_MODEL_PATH: str | None = Field(
        default=None,
        description="Path to serialized trained flood model checkpoint.",
    )

    # File paths
    DATA_ROOT: Path = Field(
        default=DATA_DIR,
        description="Base directory for raw, interim, and processed data.",
    )

    # API & CORS
    API_PORT: int = Field(default=8000)
    API_HOST: str = Field(default="0.0.0.0")
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
        description="Allowed CORS origins for credentialed cookie-based requests.",
    )

    # Authentication & Session Cookies (Part 1)
    SESSION_COOKIE_NAME: str = Field(
        default="setu_session",
        description="Name of the HTTP-only session cookie.",
    )
    SESSION_DURATION_DAYS: int = Field(
        default=7,
        description="Session validity period in days before expiration.",
    )
    SESSION_COOKIE_SECURE: bool = Field(
        default=False,
        description="Whether to enforce HTTPS-only Secure flag on session cookie.",
    )
    SESSION_COOKIE_SAMESITE: str = Field(
        default="lax",
        description="SameSite cookie policy (lax, strict, none).",
    )

    # Google OAuth 2.0 / OpenID Connect
    GOOGLE_CLIENT_ID: str = Field(
        default="",
        description="Google OAuth 2.0 Web Client ID for token audience verification.",
    )
    GOOGLE_CLIENT_SECRET: str = Field(
        default="",
        description="Google OAuth 2.0 Web Client Secret.",
    )
    GOOGLE_OFFICIAL_DOMAINS: list[str] = Field(
        default=["gov.in", "nic.in"],
        description="Whitelisted email domains granted GOVERNMENT_OFFICIAL role on Google registration.",
    )
    GOOGLE_OFFICIAL_EMAILS: list[str] = Field(
        default=["sabitasinha57@gmail.com"],
        description="Explicit email addresses granted GOVERNMENT_OFFICIAL role on Google registration.",
    )

    # Login Rate Limiting (Batch E)
    LOGIN_RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Whether sliding-window rate limiting is enabled on POST /auth/login.",
    )
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = Field(
        default=5,
        description="Maximum failed login attempts allowed per account/email window before 429 lockout.",
    )
    LOGIN_RATE_LIMIT_MAX_IP_ATTEMPTS: int = Field(
        default=20,
        description="Maximum failed login attempts allowed per client IP window before 429 lockout.",
    )
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        description="Sliding window duration in seconds for login rate limiting.",
    )

    # Demo Account Passwords (Configurable / Dev Only)
    DEMO_CIVILIAN_PASSWORD: str = Field(
        default="DemoCivilian123!",
        description="Development password for seeded demo civilian account.",
    )
    DEMO_OFFICER_PASSWORD: str = Field(
        default="DemoOfficer123!",
        description="Development password for seeded demo government official account.",
    )
    DEMO_RESCUE_PASSWORD: str = Field(
        default="DemoRescue123!",
        description="Development password for seeded demo rescue officer account.",
    )

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_sqlalchemy_url(self, direct: bool = False, async_driver: bool = False) -> str:
        """Returns normalized SQLAlchemy connection URL using psycopg3 driver.
        
        Converts 'postgresql://' or 'postgres://' to 'postgresql+psycopg://' or 'postgresql+asyncpg://'.
        """
        raw_url = (self.DIRECT_DATABASE_URL if direct and self.DIRECT_DATABASE_URL else self.DATABASE_URL)
        if not raw_url:
            raw_url = "postgresql://setu:setu@localhost:5432/setu"

        # Normalize scheme
        driver = "postgresql+psycopg" if not async_driver else "postgresql+asyncpg"
        if raw_url.startswith("postgresql://"):
            return raw_url.replace("postgresql://", f"{driver}://", 1)
        elif raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", f"{driver}://", 1)
        return raw_url

    def get_direct_psycopg_conninfo(self) -> str:
        """Returns direct psycopg3 connection string (plain postgresql://)."""
        raw_url = self.DIRECT_DATABASE_URL if self.DIRECT_DATABASE_URL else self.DATABASE_URL
        if raw_url.startswith("postgresql+psycopg://"):
            return raw_url.replace("postgresql+psycopg://", "postgresql://", 1)
        if raw_url.startswith("postgresql+asyncpg://"):
            return raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return raw_url


# Global settings singleton
settings = Settings()
