import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Location:
    latitude: float
    longitude: float
    altitude: float


@dataclass
class SatelliteConfig:
    frequency: int
    norad_id: int


@dataclass
class CaptureConfig:
    rtl_sample_rate: int = 60000
    final_sample_rate: int = 11025
    gain: float = 44.5
    ppm: int = 0
    min_elevation: float = 20.0
    pre_record_seconds: int = 30
    post_record_seconds: int = 30
    competing_services: list = field(default_factory=list)


@dataclass
class TLEConfig:
    file: str
    max_age_hours: int = 24


@dataclass
class PathsConfig:
    recordings_dir: str
    log_file: str


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass
class CleanupConfig:
    delete_wav: bool = True
    delete_png: bool = True


@dataclass
class Config:
    location: Location
    satellites: dict
    capture: CaptureConfig
    tle: TLEConfig
    paths: PathsConfig
    telegram: TelegramConfig
    cleanup: CleanupConfig


def load_config(config_path: str | None = None) -> Config:
    if config_path is None:
        config_path = str(Path(__file__).parent.parent / "config.yaml")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return Config(
        location=Location(**data["location"]),
        satellites={
            name: SatelliteConfig(**sat)
            for name, sat in data["satellites"].items()
        },
        capture=CaptureConfig(**data["capture"]),
        tle=TLEConfig(**data["tle"]),
        paths=PathsConfig(**data["paths"]),
        telegram=TelegramConfig(
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or data["telegram"].get("bot_token", ""),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID") or data["telegram"].get("chat_id", ""),
        ),
        cleanup=CleanupConfig(**data["cleanup"]),
    )
