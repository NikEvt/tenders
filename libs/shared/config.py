"""Конфигурация из окружения.

Каждый сервис собирает свой Settings из нужных ему блоков — так сервис не требует
переменных, которые ему не нужны (ISP на уровне конфигурации).
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from libs.shared.regions import RUSSIAN_REGIONS

#: Сентинел «все субъекты» для EIS_REGIONS.
ALL_REGIONS = "all"

_BASE = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)


class DatabaseSettings(BaseSettings):
    model_config = _BASE

    host: str = Field("postgres", alias="DB_HOST")
    port: int = Field(5432, alias="DB_PORT")
    name: str = Field("zakupki", alias="POSTGRES_DB")
    user: str = Field("zakupki", alias="POSTGRES_USER")
    password: SecretStr = Field(SecretStr(""), alias="POSTGRES_PASSWORD")

    @property
    def async_dsn(self) -> str:
        pwd = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_dsn(self) -> str:
        pwd = self.password.get_secret_value()
        return f"postgresql+psycopg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"


class RabbitSettings(BaseSettings):
    model_config = _BASE

    host: str = Field("rabbitmq", alias="RABBITMQ_HOST")
    port: int = Field(5672, alias="RABBITMQ_PORT")
    user: str = Field("zakupki", alias="RABBITMQ_USER")
    password: SecretStr = Field(SecretStr(""), alias="RABBITMQ_PASSWORD")

    @property
    def dsn(self) -> str:
        pwd = self.password.get_secret_value()
        return f"amqp://{self.user}:{pwd}@{self.host}:{self.port}/"


class MinioSettings(BaseSettings):
    model_config = _BASE

    endpoint: str = Field("minio:9000", alias="MINIO_ENDPOINT")
    access_key: str = Field("zakupki", alias="MINIO_ROOT_USER")
    secret_key: SecretStr = Field(SecretStr(""), alias="MINIO_ROOT_PASSWORD")
    bucket: str = Field("tender-documents", alias="MINIO_BUCKET")
    secure: bool = Field(False, alias="MINIO_SECURE")


class EisSettings(BaseSettings):
    model_config = _BASE

    token: SecretStr = Field(SecretStr(""), alias="EIS_TOKEN")
    #: Коды субъектов через запятую либо `all` — все 85. Второго списка
    #: регионов в проекте нет: `all` разворачивается по справочнику, который
    #: уже подписывает разрезы рынка и питает пикер.
    regions: str = Field("77", alias="EIS_REGIONS")
    document_types: str = Field("epNotificationEF2020", alias="EIS_DOCUMENT_TYPES")
    crawl_interval_minutes: int = Field(60, alias="EIS_CRAWL_INTERVAL_MINUTES")

    @property
    def region_list(self) -> list[str]:
        if self.regions.strip().lower() == ALL_REGIONS:
            return list(RUSSIAN_REGIONS)
        return [r.strip() for r in self.regions.split(",") if r.strip()]

    @property
    def document_type_list(self) -> list[str]:
        return [d.strip() for d in self.document_types.split(",") if d.strip()]


class LlmSettings(BaseSettings):
    model_config = _BASE

    base_url: str = Field("http://localhost:8080/v1", alias="LLM_BASE_URL")
    api_key: SecretStr = Field(SecretStr("dummy"), alias="LLM_API_KEY")
    model: str = Field("qwen3.6-35B-A3B", alias="LLM_MODEL")
    max_concurrency: int = Field(4, alias="LLM_MAX_CONCURRENCY")
    timeout_seconds: int = Field(180, alias="LLM_TIMEOUT_SECONDS")

    # Схема авторизации: "Bearer" — как шлёт OpenAI SDK, "Api-Key" — Yandex Cloud.
    auth_scheme: str = Field("Bearer", alias="LLM_AUTH_SCHEME")

    # Уровень рассуждений reasoning-моделей. На простых задачах Qwen3.6 тратит
    # сотни токенов на размышления ради односложного ответа, поэтому по умолчанию
    # они выключены, а судье, где рассуждение влияет на вердикт, даётся бюджет.
    reasoning_effort: str = Field("none", alias="LLM_REASONING_EFFORT")
    judge_reasoning_effort: str = Field("low", alias="LLM_JUDGE_REASONING_EFFORT")


class EmbeddingSettings(BaseSettings):
    model_config = _BASE

    model: str = Field("deepvk/USER-bge-m3", alias="EMBEDDING_MODEL")
    dim: int = Field(1024, alias="EMBEDDING_DIM")
    service_url: str = Field("http://embedding-service:8020", alias="EMBEDDING_SERVICE_URL")
    # Пусто — устройство выбирается автоматически (cuda → mps → cpu).
    # Явно задавайте, только если нужно принудить конкретный бэкенд.
    device: str | None = Field(None, alias="EMBEDDING_DEVICE")


class LogSettings(BaseSettings):
    model_config = _BASE

    level: str = Field("INFO", alias="LOG_LEVEL")
    json_output: bool = Field(True, alias="LOG_JSON")


@lru_cache
def database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def rabbit_settings() -> RabbitSettings:
    return RabbitSettings()


@lru_cache
def minio_settings() -> MinioSettings:
    return MinioSettings()


@lru_cache
def eis_settings() -> EisSettings:
    return EisSettings()


@lru_cache
def llm_settings() -> LlmSettings:
    return LlmSettings()


@lru_cache
def embedding_settings() -> EmbeddingSettings:
    return EmbeddingSettings()


@lru_cache
def log_settings() -> LogSettings:
    return LogSettings()
