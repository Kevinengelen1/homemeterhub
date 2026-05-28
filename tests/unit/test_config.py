from __future__ import annotations

import pytest

from homemeterhub.config import load_settings


def base_env() -> dict[str, str]:
    return {
        "DB_HOST": "postgres",
        "DB_NAME": "energy",
        "DB_USER": "energy_user",
        "DB_PASSWORD": "secret",
        "P1_BASE_URL": "http://192.168.30.50",
        "S0TOOL_HOST": "192.168.30.57",
    }


def test_loads_environment_settings() -> None:
    settings = load_settings(base_env())
    assert settings.database.host == "postgres"
    assert settings.p1.base_url == "http://192.168.30.50"
    assert settings.water.host == "192.168.30.57"


def test_missing_db_host_raises_clear_error() -> None:
    env = base_env()
    env.pop("DB_HOST")
    with pytest.raises(ValueError) as error:
        load_settings(env)
    assert "DB_HOST" in str(error.value)


def test_p1_interval_defaults_to_one_second() -> None:
    settings = load_settings(base_env())
    assert settings.p1.poll_interval_seconds == 1


def test_custom_water_keys_override_defaults() -> None:
    env = base_env() | {"S0TOOL_KEY_WATER_TOTAL": "999"}
    settings = load_settings(env)
    assert settings.water.keys.water_total == 999


def test_disabled_collectors_do_not_require_source_hosts() -> None:
    env = {
        "DB_HOST": "postgres",
        "DB_NAME": "energy",
        "DB_USER": "energy_user",
        "DB_PASSWORD": "secret",
        "ENABLE_P1_COLLECTOR": "false",
        "ENABLE_WATER_COLLECTOR": "false",
    }
    settings = load_settings(env)
    assert settings.app.enable_p1_collector is False
    assert settings.app.enable_water_collector is False
