from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


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


class Settings(BaseModel):
    app: AppSettings
    database: DatabaseSettings
    p1: P1Settings
    water: WaterSettings
    retention: RetentionSettings

    @model_validator(mode="after")
    def validate_enabled_collectors(self) -> Settings:
        if self.app.enable_p1_collector and not self.p1.base_url:
            raise ValueError("P1_BASE_URL is required when ENABLE_P1_COLLECTOR=true")
        if self.app.enable_water_collector and not self.water.host:
            raise ValueError("S0TOOL_HOST is required when ENABLE_WATER_COLLECTOR=true")
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
    }
    try:
        return Settings.model_validate(payload)
    except ValidationError as error:
        raise ValueError(_validation_error_to_message(error)) from error
