from __future__ import annotations

import os
import sys
from pathlib import Path


def find_spotify_user_dirs() -> list[Path]:
    """Locate Spotify user profile directories on Windows, macOS, and Linux."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Spotify" / "Users")
        if localappdata:
            packages = Path(localappdata) / "Packages"
            if packages.exists():
                for pkg in packages.glob("SpotifyAB.SpotifyMusic_*"):
                    candidates.append(pkg / "LocalState" / "Spotify" / "Users")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "Spotify" / "Users")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            candidates.append(Path(xdg) / "spotify" / "Users")
        candidates.append(Path.home() / ".config" / "spotify" / "Users")
        candidates.append(Path.home() / ".var" / "app" / "com.spotify.Client" / "config" / "spotify" / "Users")

    found: list[Path] = []
    for users_dir in candidates:
        if users_dir.is_dir():
            for child in users_dir.iterdir():
                if child.is_dir() and child.name.endswith("-user"):
                    found.append(child)
    return found


def reset_local_files_cache() -> list[Path]:
    """Delete Spotify's local-files.bnk cache files so Spotify rescans local folders."""
    removed: list[Path] = []
    for user_dir in find_spotify_user_dirs():
        bnk = user_dir / "local-files.bnk"
        if bnk.is_file():
            bnk.unlink()
            removed.append(bnk)
    return removed
