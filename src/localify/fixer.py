from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import get_config_dir

WINDOWS_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def subprocess_kwargs() -> dict[str, int]:
    """Hide console windows on Windows when invoked from the GUI."""
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


@dataclass
class ProbeInfo:
    format_name: str
    audio_codec: str | None
    has_attached_pic: bool
    duration: float | None
    title: str = ""
    artist: str = ""
    album: str = ""


def managed_bin_dir() -> Path:
    return get_config_dir() / "bin"


def find_ffmpeg() -> tuple[str, str] | None:
    """Locate ffmpeg and ffprobe from bundled resources, managed bin dir, or PATH."""
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    search_dirs: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        search_dirs.append(Path(meipass) / "bin")
        search_dirs.append(Path(meipass))

    search_dirs.append(managed_bin_dir())

    for directory in search_dirs:
        ff = directory / f"ffmpeg{exe_suffix}"
        fp = directory / f"ffprobe{exe_suffix}"
        if ff.is_file() and fp.is_file():
            return str(ff), str(fp)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    return None


def install_ffmpeg_windows(
    log: Callable[[str], None] = print,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[str, str]:
    """Download official Windows FFmpeg essentials and extract ffmpeg.exe + ffprobe.exe."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Automatic FFmpeg setup is currently Windows-only.\n"
            "Install FFmpeg via:\n"
            "  macOS: brew install ffmpeg\n"
            "  Linux: sudo apt install ffmpeg"
        )

    bin_dir = managed_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    log("Downloading FFmpeg essentials for Windows (one-time setup)...")

    with tempfile.TemporaryDirectory(prefix="localify_ffmpeg_") as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"

        def _reporthook(blocks: int, block_size: int, total_size: int) -> None:
            if progress and total_size > 0:
                pct = min(90.0, (blocks * block_size / total_size) * 90.0)
                progress(pct, f"Downloading FFmpeg... {int(pct)}%")

        try:
            urllib.request.urlretrieve(WINDOWS_FFMPEG_URL, zip_path, reporthook=_reporthook)
        except Exception as exc:
            raise RuntimeError(f"Failed to download FFmpeg: {exc}") from exc

        if progress:
            progress(92.0, "Extracting FFmpeg...")
        log("Extracting ffmpeg.exe and ffprobe.exe...")

        extracted: dict[str, Path] = {}
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                lower = member.lower()
                if lower.endswith("/bin/ffmpeg.exe"):
                    target = bin_dir / "ffmpeg.exe"
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted["ffmpeg"] = target
                elif lower.endswith("/bin/ffprobe.exe"):
                    target = bin_dir / "ffprobe.exe"
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted["ffprobe"] = target

        if "ffmpeg" not in extracted or "ffprobe" not in extracted:
            raise RuntimeError("Downloaded archive did not contain ffmpeg.exe and ffprobe.exe.")

    if progress:
        progress(100.0, "FFmpeg ready")
    log(f"Installed FFmpeg to {bin_dir}")
    return str(extracted["ffmpeg"]), str(extracted["ffprobe"])


def require_ffmpeg(
    auto_install: bool = False,
    log: Callable[[str], None] = print,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[str, str]:
    found = find_ffmpeg()
    if found:
        return found
    if auto_install and sys.platform == "win32":
        return install_ffmpeg_windows(log=log, progress=progress)
    raise RuntimeError(
        "ffmpeg and ffprobe are required.\n"
        "Install them via:\n"
        "  Windows: winget install Gyan.FFmpeg (or click 'Install FFmpeg' in Localify)\n"
        "  macOS:   brew install ffmpeg\n"
        "  Linux:   sudo apt install ffmpeg"
    )


def probe_audio(file_path: Path, ffprobe_bin: str | None = None) -> ProbeInfo | None:
    ffprobe = ffprobe_bin
    if not ffprobe:
        found = find_ffmpeg()
        ffprobe = found[1] if found else None
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:format_tags=title,artist,album:stream=codec_name,codec_type:stream_disposition=attached_pic",
            "-of",
            "json",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        **subprocess_kwargs(),
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    fmt = data.get("format", {})
    format_name = str(fmt.get("format_name", ""))
    duration_raw = fmt.get("duration")
    duration = float(duration_raw) if duration_raw is not None else None
    tags = fmt.get("tags", {}) or {}
    lower_tags = {str(k).lower(): str(v) for k, v in tags.items()}

    audio_codec: str | None = None
    has_attached_pic = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio" and not audio_codec:
            audio_codec = stream.get("codec_name")
        if stream.get("disposition", {}).get("attached_pic") == 1:
            has_attached_pic = True

    return ProbeInfo(
        format_name=format_name,
        audio_codec=audio_codec,
        has_attached_pic=has_attached_pic,
        duration=duration,
        title=lower_tags.get("title", ""),
        artist=lower_tags.get("artist", ""),
        album=lower_tags.get("album", ""),
    )


def needs_spotify_fix(info: ProbeInfo | None) -> bool:
    """Return True if an .mp3 file is not a genuine MP3 stream (causes Spotify 1193046:28:15)."""
    if info is None:
        return True
    formats = {part.strip().lower() for part in info.format_name.split(",")}
    if "mp3" not in formats:
        return True
    if info.audio_codec != "mp3":
        return True
    return False


def update_track_tags(
    mp3_path: Path,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    cover_path: Path | None = None,
    square_cover: bool = True,
    remove_cover: bool = False,
) -> None:
    """Update ID3v2.3 metadata and/or cover art on an existing MP3 atomically without re-encoding audio."""
    ffmpeg, ffprobe = require_ffmpeg()
    if not mp3_path.is_file():
        raise FileNotFoundError(f"File not found: {mp3_path}")

    info = probe_audio(mp3_path, ffprobe)
    if needs_spotify_fix(info):
        raise RuntimeError(f"{mp3_path.name} is not a valid MP3 stream. Run 'Fix Folder MP3s' first.")

    final_title = title if title is not None else (info.title if info else "")
    final_artist = artist if artist is not None else (info.artist if info else "")
    final_album = album if album is not None else (info.album if info else "")

    with tempfile.TemporaryDirectory(prefix="localify_tag_") as tmp_dir:
        tmp_out = Path(tmp_dir) / mp3_path.name
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(mp3_path)]

        if cover_path is not None:
            if not cover_path.is_file():
                raise FileNotFoundError(f"Cover image not found: {cover_path}")
            cmd += ["-i", str(cover_path), "-map", "0:a:0", "-map", "1:v:0"]
            if square_cover:
                cmd += ["-vf", "crop='min(iw,ih)':'min(iw,ih)'"]
            cmd += [
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-disposition:v:0",
                "attached_pic",
                "-metadata:s:v",
                "title=Album cover",
                "-metadata:s:v",
                "comment=Cover (front)",
            ]
        elif remove_cover or not (info and info.has_attached_pic):
            cmd += ["-map", "0:a:0"]
        else:
            cmd += ["-map", "0:a:0", "-map", "0:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]

        cmd += [
            "-c:a",
            "copy",
            "-map_metadata",
            "-1",
            "-id3v2_version",
            "3",
        ]
        if final_title:
            cmd += ["-metadata", f"title={final_title}"]
        if final_artist:
            cmd += ["-metadata", f"artist={final_artist}"]
        if final_album:
            cmd += ["-metadata", f"album={final_album}"]

        cmd.append(str(tmp_out))

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, **subprocess_kwargs())
        if proc.returncode != 0 or not tmp_out.is_file():
            raise RuntimeError(f"Failed to update tags for {mp3_path.name}: {proc.stderr.strip()}")
        shutil.move(str(tmp_out), str(mp3_path))


def fix_folder(
    folder: Path,
    bitrate: str = "320k",
    dry_run: bool = False,
    log: Callable[[str], None] = print,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[int, int, int]:
    """Scan folder for disguised or broken .mp3 files and re-encode them cleanly.

    Returns (fixed_count, skipped_count, failed_count).
    """
    ffmpeg, ffprobe = require_ffmpeg()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    fixed = 0
    skipped = 0
    failed = 0

    mp3_files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")
    total = len(mp3_files)
    for idx, mp3 in enumerate(mp3_files, start=1):
        if progress and total:
            progress((idx / total) * 100.0, f"Checking {idx}/{total}: {mp3.name}")

        info = probe_audio(mp3, ffprobe)
        if not needs_spotify_fix(info):
            skipped += 1
            continue

        reason = (
            f"format={info.format_name}, codec={info.audio_codec}"
            if info
            else "unreadable header"
        )
        if dry_run:
            log(f"[would fix] {mp3.name} ({reason})")
            fixed += 1
            continue

        with tempfile.TemporaryDirectory(prefix="localify_fix_") as tmp_dir:
            tmp_out = Path(tmp_dir) / mp3.name
            cmd = [ffmpeg, "-y", "-v", "error", "-i", str(mp3)]
            if info and info.has_attached_pic:
                cmd += ["-map", "0:a:0", "-map", "0:v:0", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
            else:
                cmd += ["-map", "0:a:0"]
            cmd += [
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-ar",
                "44100",
                "-ac",
                "2",
                "-id3v2_version",
                "3",
                str(tmp_out),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, **subprocess_kwargs())
            if proc.returncode == 0 and tmp_out.is_file():
                shutil.move(str(tmp_out), str(mp3))
                log(f"[fixed] {mp3.name} ({reason})")
                fixed += 1
            else:
                log(f"[failed] {mp3.name}: {proc.stderr.strip()}")
                failed += 1

    return fixed, skipped, failed
