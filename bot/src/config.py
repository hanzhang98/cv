from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# bot/src/config.py → bot/
ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    twitter_bearer_token: str = ""
    openai_api_key: str = ""
    bot_mode: str = "demo"  # demo | live
    log_level: str = "INFO"

    @property
    def allowed_chat_ids(self) -> set[int]:
        if not self.telegram_allowed_chat_ids.strip():
            return set()
        return {
            int(x.strip())
            for x in self.telegram_allowed_chat_ids.split(",")
            if x.strip()
        }

    @property
    def is_demo(self) -> bool:
        return self.bot_mode.lower() != "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


@lru_cache
def load_themes() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "themes.yaml")


@lru_cache
def load_sources() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "sources.yaml")
