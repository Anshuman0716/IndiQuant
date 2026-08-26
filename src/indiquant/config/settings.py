from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IndiQuantSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IQ_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # -- Data paths --
    data_dir: Path = Path("data")
    parquet_dir: Path = Path("data/parquet")

    # -- Database --
    duckdb_path: Path = Path("data/indiquant.duckdb")
    postgres_dsn: str = "postgresql://localhost:5432/iq_meta"

    # -- API keys --
    nse_api_key: str = ""
    bse_api_key: str = ""

    # -- Broker --
    broker_api_key: str = ""
    broker_api_secret: str = ""

    # -- Observability --
    sentry_dsn: str = ""
    posthog_api_key: str = ""
    log_level: str = "INFO"
