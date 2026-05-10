import os
from pathlib import Path

import pytest

from weather_station.config import Config, load_config


CONFIG_YAML = """\
location:
  latitude: 36.5
  longitude: -4.6
  altitude: 78
satellites:
  NOAA 15:
    frequency: 137620000
    norad_id: 25338
capture:
  rtl_sample_rate: 60000
  final_sample_rate: 11025
  gain: 44.5
  ppm: 0
  min_elevation: 20
  pre_record_seconds: 30
  post_record_seconds: 30
tle:
  file: "/tmp/tle.txt"
  max_age_hours: 24
paths:
  recordings_dir: "/tmp/recs"
  log_file: "/tmp/ws.log"
telegram:
  bot_token: ""
  chat_id: ""
cleanup:
  delete_wav: true
  delete_png: true
"""


@pytest.fixture
def config_file(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(CONFIG_YAML)
    return str(f)


def test_load_config_values(config_file):
    cfg = load_config(config_file)
    assert cfg.location.latitude == 36.5
    assert cfg.location.longitude == -4.6
    assert cfg.location.altitude == 78
    assert "NOAA 15" in cfg.satellites
    assert cfg.satellites["NOAA 15"].frequency == 137620000
    assert cfg.capture.min_elevation == 20
    assert cfg.tle.max_age_hours == 24


def test_load_config_telegram_from_env(config_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    cfg = load_config(config_file)
    assert cfg.telegram.bot_token == "tok123"
    assert cfg.telegram.chat_id == "chat456"


def test_load_config_telegram_env_overrides_yaml(tmp_path, monkeypatch):
    cfg_text = CONFIG_YAML.replace('bot_token: ""', 'bot_token: "yaml_token"')
    f = tmp_path / "config.yaml"
    f.write_text(cfg_text)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token")
    cfg = load_config(str(f))
    assert cfg.telegram.bot_token == "env_token"


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")


def test_load_config_default_path():
    """load_config() without args resolves to the project's config.yaml (line 70)."""
    cfg = load_config()  # uses default path
    assert cfg.location is not None
    assert len(cfg.satellites) > 0
