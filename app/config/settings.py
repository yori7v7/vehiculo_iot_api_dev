"""Configuración validada para desarrollo y producción."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_explicit_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    raise ValueError("Usa true o false de forma explícita.")


ExplicitBool = Annotated[bool, BeforeValidator(parse_explicit_bool)]
SimulatedVehicleId = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]


class Settings(BaseSettings):
    """Parámetros del proceso; RDS se valida al solicitar una conexión."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="Vehículo IoT API", min_length=1)
    app_env: Literal["development", "production"] = "development"
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)

    db_host: str = ""
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = Field(default="vehiculo_iot", min_length=1)
    db_user: str = ""
    db_password: SecretStr = Field(default=SecretStr(""), repr=False)
    db_ssl_ca: Path = PROJECT_ROOT / ".certs" / "rds-global-bundle.pem"
    db_connect_timeout: int = Field(default=5, ge=1, le=60)
    db_read_timeout: int = Field(default=10, ge=1, le=120)
    db_write_timeout: int = Field(default=10, ge=1, le=120)

    control_publico_enabled: ExplicitBool = False
    control_publico_simulation: ExplicitBool = False
    control_publico_sqlite_path: Path | None = None
    control_publico_vehicle_ids: tuple[SimulatedVehicleId, ...] = (1,)
    control_publico_rate_per_second: int = Field(default=5, ge=1, le=10)
    control_publico_turn_seconds: int = Field(default=120, ge=1, le=1200)
    control_publico_inactivity_seconds: int = Field(default=20, ge=1, le=1200)

    @model_validator(mode="after")
    def check_public_control_settings(self) -> "Settings":
        if self.control_publico_enabled != self.control_publico_simulation:
            raise ValueError("El control público exige habilitar explícitamente ambas opciones de simulación.")
        if self.control_publico_simulation and self.app_env != "development":
            raise ValueError("La simulación de control público solo está disponible en desarrollo local.")
        path = self.control_publico_sqlite_path
        if self.control_publico_simulation and path is None:
            raise ValueError("Configura una ruta SQLite absoluta fuera del repositorio.")
        if path is not None and (
            not path.is_absolute() or path.resolve().is_relative_to(PROJECT_ROOT.resolve())
        ):
            raise ValueError("La ruta SQLite debe ser absoluta y quedar fuera del repositorio.")
        vehicle_ids = self.control_publico_vehicle_ids
        if not vehicle_ids or len(set(vehicle_ids)) != len(vehicle_ids):
            raise ValueError("Los vehículos simulados deben ser únicos y contener al menos un ID.")
        if self.control_publico_inactivity_seconds > self.control_publico_turn_seconds:
            raise ValueError("La inactividad no puede superar la duración máxima de turno.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cargar la configuración una vez por proceso, sin imprimir secretos."""

    return Settings()
