"""Configuration loading: config.yaml (settings) + .env (secrets)."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


class Cfg(dict):
    """dict with attribute access for nested config."""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return Cfg(v) if isinstance(v, dict) else v


def load_config(path: str | None = None) -> Cfg:
    load_dotenv(ROOT / ".env")
    p = Path(path) if path else ROOT / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Cfg(data)


def env(name: str, required: bool = False) -> str:
    v = os.getenv(name, "").strip()
    if required and not v:
        raise RuntimeError(f"Missing required secret {name}. Set it in your .env file.")
    return v


def path_of(cfg: Cfg, key: str) -> Path:
    p = Path(cfg["paths"][key])
    p = p if p.is_absolute() else ROOT / p
    return p


def tz(cfg: Cfg) -> ZoneInfo:
    return ZoneInfo(cfg["schedule"]["timezone"])


def today_str(cfg: Cfg) -> str:
    return datetime.now(tz(cfg)).strftime("%Y-%m-%d")
