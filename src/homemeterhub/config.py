from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class AppSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    timezone: str = Field(default="Europe/Amsterdam", alias="APP_TIMEZONE")
    enable_p1_collector: bool = Field(default=True, alias="ENABLE_P1_COLLECTOR")
    enable_water_collector: bool = Field(default=True, alias="ENABLE_WATER_COLLECTOR")
    enable_db_init: bool = Field(default=True, alias="ENABLE_DB_INIT")
    enable_status_server: bool = Field(default=True, alias="APP_STATUS_ENABLED")
    status_host: str = Field(default="0.0.0.0", alias="APP_STATUS_HOST")  # noqa: S104
    status_port: int = Field(default=8080, alias="APP_STATUS_PORT")
    health_startup_grace_seconds: int = Field(
        default=90, ge=0, alias="APP_HEALTH_STARTUP_GRACE_SECONDS"
    )
    health_p1_max_age_seconds: int = Field(default=120, ge=1, alias="APP_HEALTH_P1_MAX_AGE_SECONDS")
    health_water_max_age_seconds: int = Field(
        default=300, ge=1, alias="APP_HEALTH_WATER_MAX_AGE_SECONDS"
    )
    history_max_days: int = Field(default=365, ge=1, le=3650, alias="APP_HISTORY_MAX_DAYS")
    history_export_max_rows: int = Field(
        default=100_000, ge=1_000, le=1_000_000, alias="APP_HISTORY_EXPORT_MAX_ROWS"
    )


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    host: str = Field(alias="DB_HOST")
    port: int = Field(default=5432, alias="DB_PORT")
    name: str = Field(alias="DB_NAME")
    user: str = Field(alias="DB_USER")
    password: str = Field(alias="DB_PASSWORD")
    sslmode: str = Field(default="prefer", alias="DB_SSLMODE")
    connect_timeout_seconds: int = Field(default=10, alias="DB_CONNECT_TIMEOUT_SECONDS")
    application_name: str = Field(default="homemeterhub", alias="DB_APPLICATION_NAME")
    pool_min_size: int = Field(default=1, ge=1, alias="DB_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=5, ge=1, alias="DB_POOL_MAX_SIZE")

    @model_validator(mode="after")
    def validate_pool_size(self) -> DatabaseSettings:
        if self.pool_max_size < self.pool_min_size:
            raise ValueError("DB_POOL_MAX_SIZE must be greater than or equal to DB_POOL_MIN_SIZE")
        return self


class P1Settings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: str | None = Field(default=None, alias="P1_BASE_URL")
    poll_interval_seconds: int = Field(default=1, alias="P1_POLL_INTERVAL_SECONDS")
    http_timeout_seconds: int = Field(default=5, alias="P1_HTTP_TIMEOUT_SECONDS")
    endpoint_e: str = Field(default="/e", alias="P1_ENDPOINT_E")
    endpoint_f: str = Field(default="/f", alias="P1_ENDPOINT_F")
    endpoint_d: str = Field(default="/d", alias="P1_ENDPOINT_D")
    device_info_interval_seconds: int = Field(default=3600, alias="P1_DEVICE_INFO_INTERVAL_SECONDS")
    store_raw_json: bool = Field(default=True, alias="P1_STORE_RAW_JSON")
    retry_delay_seconds: int = Field(default=5, alias="P1_RETRY_DELAY_SECONDS")


class WaterKeySettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    water_status: int = Field(default=413848536, alias="S0TOOL_KEY_WATER_STATUS")
    water_flow: int = Field(default=3581156864, alias="S0TOOL_KEY_WATER_FLOW")
    water_stand: int = Field(default=2881466520, alias="S0TOOL_KEY_WATER_STAND")
    water_total: int = Field(default=2086030061, alias="S0TOOL_KEY_WATER_TOTAL")
    wifi_signal: int = Field(default=2038807002, alias="S0TOOL_KEY_WIFI_SIGNAL")


class WaterSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    host: str | None = Field(default=None, alias="S0TOOL_HOST")
    port: int = Field(default=6053, alias="S0TOOL_PORT")
    noise_psk: str | None = Field(default=None, alias="S0TOOL_NOISE_PSK")
    reconnect_delay_seconds: int = Field(default=10, alias="S0TOOL_RECONNECT_DELAY_SECONDS")
    store_raw_payload: bool = Field(default=True, alias="S0TOOL_STORE_RAW_PAYLOAD")
    keys: WaterKeySettings


class RetentionSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    enable_retention_cleanup: bool = Field(default=False, alias="ENABLE_RETENTION_CLEANUP")
    raw_seconds_data_days: int = Field(default=730, alias="RETENTION_RAW_SECONDS_DATA_DAYS")
    water_events_days: int = Field(default=730, alias="RETENTION_WATER_EVENTS_DAYS")


class SolarEdgeSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool = Field(default=False, alias="ENABLE_SOLAREDGE_COLLECTOR")
    source: Literal["home_assistant", "solaredge_api"] = Field(
        default="home_assistant", alias="SOLAREDGE_SOURCE"
    )
    site_id: int | None = Field(default=None, alias="SOLAREDGE_SITE_ID")
    api_key: str | None = Field(default=None, alias="SOLAREDGE_API_KEY")
    poll_interval_seconds: int = Field(default=300, ge=60, alias="SOLAREDGE_POLL_INTERVAL_SECONDS")
    http_timeout_seconds: int = Field(default=15, ge=1, alias="SOLAREDGE_HTTP_TIMEOUT_SECONDS")
    retry_delay_seconds: int = Field(default=300, ge=1, alias="SOLAREDGE_RETRY_DELAY_SECONDS")
    home_assistant_url: str | None = Field(default=None, alias="HOME_ASSISTANT_URL")
    home_assistant_token: str | None = Field(default=None, alias="HOME_ASSISTANT_TOKEN")
    home_assistant_current_power_entity: str = Field(
        default="sensor.solaredge_current_power",
        alias="HOME_ASSISTANT_SOLAREDGE_CURRENT_POWER_ENTITY",
    )
    home_assistant_today_energy_entity: str = Field(
        default="sensor.solaredge_energy_today",
        alias="HOME_ASSISTANT_SOLAREDGE_TODAY_ENERGY_ENTITY",
    )
    home_assistant_month_energy_entity: str = Field(
        default="sensor.solaredge_energy_this_month",
        alias="HOME_ASSISTANT_SOLAREDGE_MONTH_ENERGY_ENTITY",
    )
    home_assistant_year_energy_entity: str = Field(
        default="sensor.solaredge_energy_this_year",
        alias="HOME_ASSISTANT_SOLAREDGE_YEAR_ENERGY_ENTITY",
    )
    home_assistant_lifetime_energy_entity: str = Field(
        default="sensor.solaredge_lifetime_energy",
        alias="HOME_ASSISTANT_SOLAREDGE_LIFETIME_ENERGY_ENTITY",
    )

    @field_validator("site_id", mode="before")
    @classmethod
    def empty_site_id_is_none(cls, value: object) -> object:
        return None if value == "" else value


class Settings(BaseModel):
    app: AppSettings
    database: DatabaseSettings
    p1: P1Settings
    water: WaterSettings
    retention: RetentionSettings
    solaredge: SolarEdgeSettings

    @model_validator(mode="after")
    def validate_enabled_collectors(self) -> Settings:
        if self.app.enable_p1_collector and not self.p1.base_url:
            raise ValueError("P1_BASE_URL is required when ENABLE_P1_COLLECTOR=true")
        if self.app.enable_water_collector and not self.water.host:
            raise ValueError("S0TOOL_HOST is required when ENABLE_WATER_COLLECTOR=true")
        if self.solaredge.enabled:
            if self.solaredge.source == "solaredge_api" and (
                not self.solaredge.site_id or not self.solaredge.api_key
            ):
                raise ValueError(
                    "SOLAREDGE_SITE_ID and SOLAREDGE_API_KEY are required when "
                    "SOLAREDGE_SOURCE=solaredge_api"
                )
            if self.solaredge.source == "home_assistant" and (
                not self.solaredge.home_assistant_url or not self.solaredge.home_assistant_token
            ):
                raise ValueError(
                    "HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN are required when "
                    "SOLAREDGE_SOURCE=home_assistant"
                )
        return self


def _validation_error_to_message(error: ValidationError) -> str:
    lines = ["Configuration validation failed:"]
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        lines.append(f"- {location}: {item['msg']}")
    return "\n".join(lines)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = dict(os.environ if env is None else env)
    payload = {
        "app": source,
        "database": source,
        "p1": source,
        "water": {**source, "keys": source},
        "retention": source,
        "solaredge": source,
    }
    try:
        return Settings.model_validate(payload)
    except ValidationError as error:
        raise ValueError(_validation_error_to_message(error)) from error
