"""Configuración validada desde el entorno y el archivo .env local."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parámetros de desarrollo; las credenciales RDS no son necesarias aún."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="Vehículo IoT API", min_length=1)
    app_env: Literal["development"] = "development"

    db_host: str = ""
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = Field(default="vehiculo_iot", min_length=1)
    db_user: str = ""
    db_password: SecretStr = Field(default=SecretStr(""), repr=False)


@lru_cache
def get_settings() -> Settings:
    """Cargar la configuración una vez por proceso, sin imprimir secretos."""

    return Settings()
