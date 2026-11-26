from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def get_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "localify"


def get_default_output_dir() -> Path:
    downloads_spotify = Path.home() / "Downloads" / "spotify"
    if downloads_spotify.exists():
        return downloads_spotify
    return Path.home() / "Music" / "Spotify Local Files"


@dataclass
class Config:
    output_dir: str
    bitrate: str = "320k"
    square_cover: bool = True
    overwrite: bool = False

    @classmethod
    def default(cls) -> Config:
        return cls(output_dir=str(get_default_output_dir()))


def config_path() -> Path:
    return get_config_dir() / "config.json"


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config.default()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        defaults = asdict(Config.default())
        merged = {**defaults, **{k: v for k, v in raw.items() if k in defaults}}
        return Config(**merged)
    except (OSError, json.JSONDecodeError, TypeError):
        return Config.default()


def save_config(cfg: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    return path
