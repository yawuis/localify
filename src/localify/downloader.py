from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from .fixer import require_ffmpeg

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class DownloadOptions:
    output_dir: Path
    bitrate: str = "320k"
    square_cover: bool = True
    overwrite: bool = False
    artist_override: str | None = None
    title_override: str | None = None
    album_override: str | None = None


@dataclass
class ImportedTrack:
    path: Path
    title: str
    artist: str
    has_cover: bool


def sanitize_filename(name: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "track"


def _find_thumbnail(stage_dir: Path, stem: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = stage_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    for path in stage_dir.iterdir():
        if path.is_file() and path.stem == stem and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return path
    return None


def _encode_spotify_mp3(
    ffmpeg: str,
    audio_src: Path,
    thumb_src: Path | None,
    dest_path: Path,
    bitrate: str,
    square_cover: bool,
    title: str,
    artist: str,
    album: str | None,
) -> bool:
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(audio_src)]
    has_cover = thumb_src is not None and thumb_src.is_file()

    if has_cover:
        cmd += ["-i", str(thumb_src)]
        cmd += ["-map", "0:a:0", "-map", "1:v:0"]
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
        "-map_metadata",
        "-1",
        "-id3v2_version",
        "3",
        "-metadata",
        f"title={title}",
        "-metadata",
        f"artist={artist}",
    ]
    if album:
        cmd += ["-metadata", f"album={album}"]

    cmd.append(str(dest_path))

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {title}: {proc.stderr.strip()}")
    return has_cover


def _flatten_entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    if "entries" in info and info["entries"] is not None:
        out: list[dict[str, Any]] = []
        for entry in info["entries"]:
            if entry:
                out.extend(_flatten_entries(entry))
        return out
    return [info]


def download_url(url: str, opts: DownloadOptions) -> list[ImportedTrack]:
    """Download one or more tracks from any yt-dlp-supported non-DRM URL into Spotify Local Files."""
    ffmpeg, _ = require_ffmpeg()
    opts.output_dir.mkdir(parents=True, exist_ok=True)
    imported: list[ImportedTrack] = []

    with tempfile.TemporaryDirectory(prefix="localify_stage_") as tmp:
        stage_dir = Path(tmp)
        ydl_opts: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": str(stage_dir / "%(id)s.%(ext)s"),
            "writethumbnail": True,
            "noplaylist": False,
            "ignoreerrors": "only_download",
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc)
            if "DRM" in msg:
                raise RuntimeError("Track is DRM-protected and cannot be downloaded.") from exc
            raise RuntimeError(f"Download failed: {msg}") from exc

        if not info:
            raise RuntimeError("No downloadable tracks found at that URL.")

        entries = _flatten_entries(info)
        audio_exts = {".mp3", ".m4a", ".webm", ".opus", ".ogg", ".wav", ".flac", ".aac", ".mp4"}

        for entry in entries:
            track_id = str(entry.get("id", ""))
            if not track_id:
                continue

            audio_src: Path | None = None
            for candidate in stage_dir.iterdir():
                if candidate.is_file() and candidate.stem == track_id and candidate.suffix.lower() in audio_exts:
                    audio_src = candidate
                    break

            if not audio_src:
                continue

            title = opts.title_override or str(entry.get("track") or entry.get("title") or track_id).strip()
            artist = (
                opts.artist_override
                or str(entry.get("artist") or entry.get("uploader") or entry.get("channel") or "Unknown Artist").strip()
            )
            album = opts.album_override or (str(entry.get("album")).strip() if entry.get("album") else None)

            file_name = sanitize_filename(f"{artist} - {title}") + ".mp3"
            final_dest = opts.output_dir / file_name

            if final_dest.exists() and not opts.overwrite:
                print(f"[skipped] Already exists: {final_dest.name}")
                continue

            thumb_src = _find_thumbnail(stage_dir, track_id)
            staged_mp3 = stage_dir / f"{track_id}_final.mp3"

            has_cover = _encode_spotify_mp3(
                ffmpeg=ffmpeg,
                audio_src=audio_src,
                thumb_src=thumb_src,
                dest_path=staged_mp3,
                bitrate=opts.bitrate,
                square_cover=opts.square_cover,
                title=title,
                artist=artist,
                album=album,
            )

            shutil.move(str(staged_mp3), str(final_dest))
            imported.append(ImportedTrack(path=final_dest, title=title, artist=artist, has_cover=has_cover))

    return imported
