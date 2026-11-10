from __future__ import annotations

"""Planned module: settings. Implementation pending."""

"""
backend/settings.py

Autonomous Retail Supply Chain AI 5.0
Centralized Application Configuration

Python 3.11+

Dependencies:
    pip install pydantic pydantic-settings

Features:
    - Environment-based configuration
    - PostgreSQL and Redis
    - JWT authentication settings
    - AI/ML and RAG configuration
    - Agent execution limits
    - AWS storage configuration
    - Security and CORS
    - Observability
    - Feature flags
    - Production configuration validation
    - Secret-safe configuration summaries

Do not commit real credentials to source control.
"""


from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


Environment = Literal[
    "development",
    "testing",
    "staging",
    "production",
]


class Settings(BaseSettings):
    """
    Central application settings.

    Environment variables override .env values.

    Example:
        APP_ENV=development
        DATABASE_URL=postgresql+asyncpg://...
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    # ========================================================
    # APPLICATION
    # ========================================================

    APP_NAME: str = (
        "Autonomous Retail Supply Chain AI 5.0"
    )

    APP_VERSION: str = "5.0.0"

    APP_ENV: Environment = "development"

    DEBUG: bool = False

    API_V1_PREFIX: str = "/api/v1"

    HOST: str = "127.0.0.1"

    PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
    )

    WORKERS: int = Field(
        default=1,
        ge=1,
        le=32,
    )

    LOG_LEVEL: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    # ========================================================
    # DATABASE
    # ========================================================

    DATABASE_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://"
        "retail:retail@localhost:5432/retail_ai"
    )

    DATABASE_POOL_SIZE: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    DATABASE_MAX_OVERFLOW: int = Field(
        default=20,
        ge=0,
        le=100,
    )

    DATABASE_POOL_TIMEOUT: int = Field(
        default=30,
        ge=1,
        le=300,
    )

    DATABASE_ECHO: bool = False

    # ========================================================
    # REDIS
    # ========================================================

    REDIS_URL: SecretStr = SecretStr(
        "redis://localhost:6379/0"
    )

    REDIS_ENABLED: bool = True

    CACHE_TTL_SECONDS: int = Field(
        default=300,
        ge=1,
        le=86400,
    )

    RATE_LIMIT_ENABLED: bool = True

    RATE_LIMIT_REQUESTS: int = Field(
        default=100,
        ge=1,
        le=100000,
    )

    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        le=3600,
    )

    # ========================================================
    # AUTHENTICATION
    # ========================================================

    JWT_SECRET_KEY: SecretStr = SecretStr(
        "CHANGE_ME_DEVELOPMENT_ONLY"
    )

    JWT_ALGORITHM: Literal[
        "HS256",
        "HS384",
        "HS512",
    ] = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        ge=1,
        le=1440,
    )

    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        ge=1,
        le=90,
    )

    MFA_ENABLED: bool = False

    AUTH_MAX_LOGIN_ATTEMPTS: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    # ========================================================
    # CORS
    # ========================================================

    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
        ]
    )

    CORS_ALLOW_CREDENTIALS: bool = True

    # ========================================================
    # AI / LLM
    # ========================================================

    AI_ENABLED: bool = True

    LLM_PROVIDER: Literal[
        "openai",
        "azure_openai",
        "anthropic",
        "ollama",
        "custom",
    ] = "openai"

    LLM_MODEL: str = "configured-model"

    LLM_API_KEY: SecretStr | None = None

    LLM_BASE_URL: str | None = None

    LLM_TIMEOUT_SECONDS: int = Field(
        default=60,
        ge=1,
        le=300,
    )

    LLM_MAX_OUTPUT_TOKENS: int = Field(
        default=2048,
        ge=64,
        le=32768,
    )

    LLM_TEMPERATURE: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
    )

    # ========================================================
    # RAG
    # ========================================================

    RAG_ENABLED: bool = True

    RAG_VECTOR_BACKEND: Literal[
        "qdrant",
        "pgvector",
        "faiss",
        "memory",
    ] = "memory"

    RAG_EMBEDDING_MODEL: str = (
        "sentence-transformers/"
        "all-MiniLM-L6-v2"
    )

    RAG_CHUNK_SIZE: int = Field(
        default=1000,
        ge=200,
        le=4000,
    )

    RAG_CHUNK_OVERLAP: int = Field(
        default=150,
        ge=0,
        le=2000,
    )

    RAG_TOP_K: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    RAG_MIN_SCORE: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
    )

    RAG_HYBRID_SEARCH: bool = True

    RAG_RERANKING_ENABLED: bool = True

    RAG_CITATIONS_REQUIRED: bool = True

    QDRANT_URL: str | None = None

    QDRANT_API_KEY: SecretStr | None = None

    QDRANT_COLLECTION: str = (
        "retail_supply_chain_documents"
    )

    # ========================================================
    # AGENTIC AI
    # ========================================================

    AGENTS_ENABLED: bool = True

    AGENT_MAX_STEPS: int = Field(
        default=15,
        ge=1,
        le=100,
    )

    AGENT_MAX_TOOL_CALLS: int = Field(
        default=30,
        ge=1,
        le=200,
    )

    AGENT_TIMEOUT_SECONDS: int = Field(
        default=120,
        ge=5,
        le=1800,
    )

    AGENT_HUMAN_APPROVAL_REQUIRED: bool = True

    AGENT_ALLOW_AUTONOMOUS_WRITES: bool = False

    AGENT_MEMORY_ENABLED: bool = True

    AGENT_CHECKPOINT_ENABLED: bool = True

    # ========================================================
    # MACHINE LEARNING
    # ========================================================

    ML_ENABLED: bool = True

    MLOPS_ENABLED: bool = True

    MODEL_REGISTRY_BACKEND: Literal[
        "mlflow",
        "database",
        "local",
    ] = "local"

    MLFLOW_TRACKING_URI: str | None = None

    MODEL_DRIFT_MONITORING_ENABLED: bool = True

    FORECAST_HORIZON_DAYS: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    # ========================================================
    # AWS / STORAGE
    # ========================================================

    STORAGE_BACKEND: Literal[
        "local",
        "s3",
    ] = "local"

    AWS_REGION: str = "ap-south-1"

    AWS_ACCESS_KEY_ID: SecretStr | None = None

    AWS_SECRET_ACCESS_KEY: SecretStr | None = None

    AWS_S3_BUCKET: str | None = None

    LOCAL_STORAGE_PATH: str = "./storage"

    MAX_UPLOAD_SIZE_MB: int = Field(
        default=25,
        ge=1,
        le=500,
    )

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    NOTIFICATIONS_ENABLED: bool = True

    EMAIL_NOTIFICATIONS_ENABLED: bool = False

    SMS_NOTIFICATIONS_ENABLED: bool = False

    PUSH_NOTIFICATIONS_ENABLED: bool = False

    SMTP_HOST: str | None = None

    SMTP_PORT: int = Field(
        default=587,
        ge=1,
        le=65535,
    )

    SMTP_USERNAME: str | None = None

    SMTP_PASSWORD: SecretStr | None = None

    # ========================================================
    # OBSERVABILITY
    # ========================================================

    METRICS_ENABLED: bool = True

    TRACING_ENABLED: bool = True

    OTEL_SERVICE_NAME: str = (
        "retail-supply-chain-ai"
    )

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    AUDIT_LOGGING_ENABLED: bool = True

    LOG_PII_REDACTION_ENABLED: bool = True

    # ========================================================
    # SECURITY
    # ========================================================

    TENANT_ISOLATION_ENABLED: bool = True

    RBAC_ENABLED: bool = True

    PROMPT_INJECTION_PROTECTION_ENABLED: bool = True

    DLP_ENABLED: bool = True

    FILE_SCANNING_ENABLED: bool = True

    REQUIRE_HTTPS: bool = False

    # ========================================================
    # FEATURE FLAGS
    # ========================================================

    FEATURE_DEMAND_FORECASTING: bool = True

    FEATURE_INVENTORY_OPTIMIZATION: bool = True

    FEATURE_SUPPLIER_RISK: bool = True

    FEATURE_ROUTE_OPTIMIZATION: bool = True

    FEATURE_PRODUCT_QUALITY: bool = True

    FEATURE_DIGITAL_TWIN: bool = True

    FEATURE_FINANCIAL_ANALYTICS: bool = True

    FEATURE_AI_COPILOT: bool = True

    FEATURE_RAG: bool = True

    FEATURE_AGENTIC_WORKFLOWS: bool = True

    # ========================================================
    # VALIDATION
    # ========================================================

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors(
        cls,
        origins: list[str],
    ) -> list[str]:

        cleaned = [
            origin.rstrip("/")
            for origin in origins
        ]

        if len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "Duplicate CORS origins"
            )

        for origin in cleaned:
            if not origin.startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    "Invalid CORS origin"
                )

        return cleaned

    @model_validator(mode="after")
    def validate_configuration(self):

        if (
            self.RAG_CHUNK_OVERLAP
            >= self.RAG_CHUNK_SIZE
        ):
            raise ValueError(
                "RAG overlap must be smaller than chunk size"
            )

        if self.APP_ENV == "production":

            if self.DEBUG:
                raise ValueError(
                    "DEBUG must be disabled in production"
                )

            if not self.REQUIRE_HTTPS:
                raise ValueError(
                    "HTTPS must be required in production"
                )

            if not self.RBAC_ENABLED:
                raise ValueError(
                    "RBAC must be enabled in production"
                )

            if not self.TENANT_ISOLATION_ENABLED:
                raise ValueError(
                    "Tenant isolation must be enabled"
                )

            if not self.AUDIT_LOGGING_ENABLED:
                raise ValueError(
                    "Audit logging must be enabled"
                )

            if self.AGENT_ALLOW_AUTONOMOUS_WRITES:
                raise ValueError(
                    "Unapproved autonomous writes "
                    "are not allowed in production"
                )

            if not self.AGENT_HUMAN_APPROVAL_REQUIRED:
                raise ValueError(
                    "Human approval must be enabled"
                )

            secret = (
                self.JWT_SECRET_KEY.get_secret_value()
            )

            if (
                len(secret) < 32
                or secret == "CHANGE_ME_DEVELOPMENT_ONLY"
            ):
                raise ValueError(
                    "Set a strong production JWT secret"
                )

            if not self.LLM_API_KEY and (
                self.AI_ENABLED
                and self.LLM_PROVIDER
                in {
                    "openai",
                    "azure_openai",
                    "anthropic",
                }
            ):
                raise ValueError(
                    "LLM API key is required"
                )

            if (
                self.STORAGE_BACKEND == "s3"
                and not self.AWS_S3_BUCKET
            ):
                raise ValueError(
                    "S3 bucket is required"
                )

            if (
                self.RAG_ENABLED
                and self.RAG_VECTOR_BACKEND == "memory"
            ):
                raise ValueError(
                    "Use persistent RAG storage in production"
                )

            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "Wildcard CORS is not permitted"
                )

        return self

    # ========================================================
    # HELPERS
    # ========================================================

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def database_dsn(self) -> str:
        return self.DATABASE_URL.get_secret_value()

    @property
    def redis_dsn(self) -> str:
        return self.REDIS_URL.get_secret_value()

    def public_summary(self) -> dict:
        """
        Safe configuration summary.

        Does not expose credentials, API keys,
        connection URLs, or secret values.
        """

        return {
            "app_name": self.APP_NAME,
            "app_version": self.APP_VERSION,
            "environment": self.APP_ENV,
            "debug": self.DEBUG,
            "ai_enabled": self.AI_ENABLED,
            "rag_enabled": self.RAG_ENABLED,
            "agents_enabled": self.AGENTS_ENABLED,
            "ml_enabled": self.ML_ENABLED,
            "mlops_enabled": self.MLOPS_ENABLED,
            "storage_backend": self.STORAGE_BACKEND,
            "vector_backend": self.RAG_VECTOR_BACKEND,
            "rbac_enabled": self.RBAC_ENABLED,
            "tenant_isolation_enabled": (
                self.TENANT_ISOLATION_ENABLED
            ),
            "audit_logging_enabled": (
                self.AUDIT_LOGGING_ENABLED
            ),
            "metrics_enabled": self.METRICS_ENABLED,
            "tracing_enabled": self.TRACING_ENABLED,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached application configuration.

    For tests:
        get_settings.cache_clear()
    """

    return Settings()


settings = get_settings()


__all__ = [
    "Settings",
    "get_settings",
    "settings",
]
