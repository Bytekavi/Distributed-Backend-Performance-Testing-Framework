from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_database: str = "performance"
    mysql_user: str = "perf"
    mysql_password: str = "perf_password"
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_max_connections: int = 64
    job_queue: str = "load-tests"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

