from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProbeInfo:
    format_name: str
    audio_codec: str | None
    has_attached_pic: bool
    duration: float | None


def require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "ffmpeg and ffprobe are required on PATH.\n"
            "Install them via:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )
    return ffmpeg, ffprobe


def probe_audio(file_path: Path, ffprobe_bin: str | None = None) -> ProbeInfo | None:
    ffprobe = ffprobe_bin or shutil.which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration:stream=codec_name,codec_type:stream_disposition=attached_pic",
            "-of",
            "json",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        check=False,
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


def fix_folder(folder: Path, bitrate: str = "320k", dry_run: bool = False) -> tuple[int, int, int]:
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
    for mp3 in mp3_files:
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
            print(f"[would fix] {mp3.name} ({reason})")
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
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0 and tmp_out.is_file():
                shutil.move(str(tmp_out), str(mp3))
                print(f"[fixed] {mp3.name} ({reason})")
                fixed += 1
            else:
                print(f"[failed] {mp3.name}: {proc.stderr.strip()}")
                failed += 1

    return fixed, skipped, failed
