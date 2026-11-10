from __future__ import annotations

"""Planned module: settings. Implementation pending."""

"""
backend/settings.py

Autonomous Retail Supply Chain AI 5.0

Centralized, validated application settings.

Python 3.10+
Pydantic 2.x
pydantic-settings 2.x

Features:
- Environment-based configuration
- Database and Redis settings
- JWT security settings
- CORS configuration
- Rate limiting settings
- Logging and observability
- LLM provider configuration
- RAG and vector database settings
- AI agent execution policies
- Notification configuration
- External integration configuration
- Production security validation
- Cached settings instance

No credentials are hardcoded.
"""


from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
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

LLMProvider = Literal[
    "openai",
    "anthropic",
    "gemini",
    "ollama",
    "local",
]


class Settings(BaseSettings):

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

    app_name: str = (
        "Autonomous Retail Supply Chain AI"
    )

    app_version: str = "5.0"

    app_env: Environment = "development"

    debug: bool = False

    api_prefix: str = "/api/v1"

    host: str = "127.0.0.1"

    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
    )

    workers: int = Field(
        default=1,
        ge=1,
        le=64,
    )

    # ========================================================
    # DATABASE
    # ========================================================

    database_url: SecretStr | None = None

    database_echo: bool = False

    database_pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    database_max_overflow: int = Field(
        default=20,
        ge=0,
        le=200,
    )

    database_pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
    )

    database_pool_recycle: int = Field(
        default=1800,
        ge=30,
    )

    database_statement_timeout_ms: int = Field(
        default=30000,
        ge=100,
    )

    # ========================================================
    # REDIS
    # ========================================================

    redis_url: SecretStr | None = None

    redis_max_connections: int = Field(
        default=50,
        ge=1,
        le=1000,
    )

    redis_socket_timeout: float = Field(
        default=2.0,
        gt=0,
    )

    cache_enabled: bool = True

    cache_default_ttl: int = Field(
        default=300,
        ge=1,
    )

    # ========================================================
    # SECURITY
    # ========================================================

    jwt_secret_key: SecretStr | None = None

    jwt_algorithm: Literal[
        "HS256",
        "HS384",
        "HS512",
    ] = "HS256"

    jwt_access_token_expire_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,
    )

    jwt_refresh_token_expire_days: int = Field(
        default=7,
        ge=1,
        le=90,
    )

    password_min_length: int = Field(
        default=12,
        ge=8,
        le=128,
    )

    require_mfa_for_admin: bool = True

    enforce_tenant_isolation: bool = True

    allow_demo_seed: bool = False

    # ========================================================
    # CORS
    # ========================================================

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
        ]
    )

    cors_allow_credentials: bool = False

    # ========================================================
    # HTTP MIDDLEWARE
    # ========================================================

    max_request_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
    )

    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
    )

    # ========================================================
    # RATE LIMITING
    # ========================================================

    rate_limit_enabled: bool = True

    rate_limit_prefix: str = (
        "retail:rate_limit"
    )

    rate_limit_default_requests: int = Field(
        default=120,
        ge=1,
    )

    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
    )

    rate_limit_fail_closed: bool = True

    # ========================================================
    # LOGGING
    # ========================================================

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    log_json: bool = True

    log_file: str | None = None

    # ========================================================
    # OBSERVABILITY
    # ========================================================

    tracing_enabled: bool = True

    otel_service_name: str = (
        "autonomous-retail-ai"
    )

    otel_exporter: Literal[
        "console",
        "otlp",
        "none",
    ] = "console"

    otel_exporter_otlp_traces_endpoint: (
        str | None
    ) = None

    otel_sample_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
    )

    metrics_enabled: bool = True

    # ========================================================
    # LLM CONFIGURATION
    # ========================================================

    llm_provider: LLMProvider = "ollama"

    llm_model: str = "llama3.1"

    llm_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
    )

    llm_max_output_tokens: int = Field(
        default=2048,
        ge=1,
        le=32768,
    )

    llm_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
    )

    openai_api_key: SecretStr | None = None

    anthropic_api_key: SecretStr | None = None

    gemini_api_key: SecretStr | None = None

    ollama_base_url: str = (
        "http://localhost:11434"
    )

    # ========================================================
    # EMBEDDINGS AND RAG
    # ========================================================

    embedding_provider: Literal[
        "openai",
        "huggingface",
        "local",
    ] = "local"

    embedding_model: str = (
        "sentence-transformers/"
        "all-MiniLM-L6-v2"
    )

    rag_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
    )

    rag_chunk_size: int = Field(
        default=800,
        ge=100,
        le=10000,
    )

    rag_chunk_overlap: int = Field(
        default=120,
        ge=0,
    )

    rag_enable_reranking: bool = True

    rag_enable_citations: bool = True

    rag_enforce_permissions: bool = True

    # ========================================================
    # VECTOR DATABASE
    # ========================================================

    vector_store: Literal[
        "faiss",
        "qdrant",
        "pgvector",
    ] = "faiss"

    qdrant_url: str | None = None

    qdrant_api_key: SecretStr | None = None

    faiss_index_path: str = (
        "./data/faiss"
    )

    # ========================================================
    # AI AGENTS
    # ========================================================

    agents_enabled: bool = True

    agent_max_steps: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    agent_timeout_seconds: int = Field(
        default=120,
        ge=1,
    )

    agent_max_concurrent: int = Field(
        default=5,
        ge=1,
        le=100,
    )

    autonomous_actions_enabled: bool = False

    require_human_approval: bool = True

    allow_agent_external_writes: bool = False

    # ========================================================
    # MACHINE LEARNING
    # ========================================================

    ml_model_path: str = (
        "./models"
    )

    forecast_horizon_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    model_drift_detection_enabled: bool = True

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    email_notifications_enabled: bool = False

    sms_notifications_enabled: bool = False

    push_notifications_enabled: bool = False

    smtp_host: str | None = None

    smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
    )

    smtp_username: str | None = None

    smtp_password: SecretStr | None = None

    # ========================================================
    # EXTERNAL INTEGRATIONS
    # ========================================================

    erp_integration_enabled: bool = False

    wms_integration_enabled: bool = False

    supplier_api_enabled: bool = False

    logistics_api_enabled: bool = False

    external_write_enabled: bool = False

    # ========================================================
    # FEATURE FLAGS
    # ========================================================

    feature_flags_enabled: bool = True

    digital_twin_enabled: bool = True

    simulation_enabled: bool = True

    demand_forecasting_enabled: bool = True

    stockout_prediction_enabled: bool = True

    supplier_risk_enabled: bool = True

    route_optimization_enabled: bool = True

    # ========================================================
    # VALIDATORS
    # ========================================================

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(
        cls,
        value: list[str],
    ) -> list[str]:

        origins = [
            origin.rstrip("/")
            for origin in value
        ]

        if len(origins) != len(set(origins)):
            raise ValueError(
                "Duplicate CORS origins"
            )

        for origin in origins:

            if origin == "*":
                raise ValueError(
                    "Wildcard CORS is not permitted"
                )

            if not origin.startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    "Invalid CORS origin"
                )

        return origins

    @model_validator(mode="after")
    def validate_configuration(
        self,
    ) -> "Settings":

        if self.rag_chunk_overlap >= (
            self.rag_chunk_size
        ):
            raise ValueError(
                "RAG chunk overlap must be "
                "smaller than chunk size"
            )

        if self.app_env in {
            "staging",
            "production",
        }:

            if self.debug:
                raise ValueError(
                    "Debug mode cannot be "
                    "enabled in staging or production"
                )

            if self.database_echo:
                raise ValueError(
                    "SQL query echo cannot be "
                    "enabled in staging or production"
                )

            if self.database_url is None:
                raise ValueError(
                    "DATABASE_URL is required"
                )

            if self.redis_url is None:
                raise ValueError(
                    "REDIS_URL is required"
                )

            if self.jwt_secret_key is None:
                raise ValueError(
                    "JWT_SECRET_KEY is required"
                )

            secret = (
                self.jwt_secret_key
                .get_secret_value()
            )

            if len(secret) < 32:
                raise ValueError(
                    "JWT secret must contain "
                    "at least 32 characters"
                )

            if not self.enforce_tenant_isolation:
                raise ValueError(
                    "Tenant isolation must be enabled"
                )

            if self.allow_demo_seed:
                raise ValueError(
                    "Demo seeding is forbidden"
                )

            if self.autonomous_actions_enabled:
                raise ValueError(
                    "Autonomous actions require "
                    "separate production authorization"
                )

            if not self.require_human_approval:
                raise ValueError(
                    "Human approval must be enabled"
                )

            if self.allow_agent_external_writes:
                raise ValueError(
                    "Agent external writes require "
                    "separate production authorization"
                )

            if self.external_write_enabled:
                raise ValueError(
                    "External integration writes "
                    "require separate approval"
                )

            if self.otel_exporter == "console":
                raise ValueError(
                    "Console trace exporter is "
                    "not allowed in production-like "
                    "environments"
                )

            if (
                self.otel_exporter == "otlp"
                and not (
                    self.otel_exporter_otlp_traces_endpoint
                )
            ):
                raise ValueError(
                    "OTLP trace endpoint required"
                )

            for origin in self.cors_origins:

                if not origin.startswith(
                    "https://"
                ):
                    raise ValueError(
                        "Production-like CORS "
                        "origins must use HTTPS"
                    )

        if (
            self.llm_provider == "openai"
            and self.openai_api_key is None
        ):
            raise ValueError(
                "OPENAI_API_KEY is required"
            )

        if (
            self.llm_provider == "anthropic"
            and self.anthropic_api_key is None
        ):
            raise ValueError(
                "ANTHROPIC_API_KEY is required"
            )

        if (
            self.llm_provider == "gemini"
            and self.gemini_api_key is None
        ):
            raise ValueError(
                "GEMINI_API_KEY is required"
            )

        if (
            self.vector_store == "qdrant"
            and not self.qdrant_url
        ):
            raise ValueError(
                "QDRANT_URL is required"
            )

        return self

    # ========================================================
    # HELPERS
    # ========================================================

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def database_dsn(self) -> str:
        if self.database_url is None:
            raise RuntimeError(
                "DATABASE_URL not configured"
            )

        return (
            self.database_url.get_secret_value()
        )

    def redis_dsn(self) -> str:
        if self.redis_url is None:
            raise RuntimeError(
                "REDIS_URL not configured"
            )

        return (
            self.redis_url.get_secret_value()
        )

    def jwt_secret(self) -> str:
        if self.jwt_secret_key is None:
            raise RuntimeError(
                "JWT_SECRET_KEY not configured"
            )

        return (
            self.jwt_secret_key.get_secret_value()
        )

    def selected_llm_api_key(
        self,
    ) -> str | None:

        keys = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
        }

        key = keys.get(
            self.llm_provider
        )

        return (
            key.get_secret_value()
            if key is not None
            else None
        )


# ============================================================
# SETTINGS SINGLETON
# ============================================================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """
    Intended for tests and controlled
    configuration reloads.

    Existing clients and connections
    are not automatically reconfigured.
    """
    get_settings.cache_clear()
    return get_settings()
