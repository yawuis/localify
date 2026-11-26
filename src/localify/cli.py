from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config, config_path, load_config, save_config
from .downloader import DownloadOptions, download_url
from .fixer import fix_folder, require_ffmpeg, update_track_tags
from .spotify import reset_local_files_cache


def _parse_bool(val: str) -> bool:
    lowered = val.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected true or false, got: {val}")


def _run_downloads(urls: list[str], opts: DownloadOptions) -> int:
    had_error = False
    for url in urls:
        print(f"Downloading: {url}")
        try:
            tracks = download_url(url, opts)
            if not tracks:
                print("  No new tracks added.")
            for track in tracks:
                cover_note = "with cover" if track.has_cover else "no cover"
                print(f"  Added: {track.path.name} ({cover_note})")
        except RuntimeError as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            had_error = True
    return 1 if had_error else 0


def _interactive_loop(opts: DownloadOptions) -> int:
    try:
        require_ffmpeg()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"localify {__version__}")
    print(f"Output folder: {opts.output_dir}")
    print("Paste a SoundCloud, YouTube, Bandcamp, or other supported URL (press Enter to exit).")

    while True:
        try:
            url = input("\nURL> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not url:
            break
        _run_downloads([url], opts)

    return 0


def _handle_config(args: argparse.Namespace, cfg: Config) -> int:
    changed = False
    if args.output is not None:
        cfg.output_dir = str(Path(args.output).expanduser().resolve())
        changed = True
    if args.bitrate is not None:
        cfg.bitrate = args.bitrate
        changed = True
    if args.embed_cover is not None:
        cfg.embed_cover = args.embed_cover
        changed = True
    if args.square_cover is not None:
        cfg.square_cover = args.square_cover
        changed = True
    if args.clean_titles is not None:
        cfg.clean_titles = args.clean_titles
        changed = True
    if args.overwrite is not None:
        cfg.overwrite = args.overwrite
        changed = True

    if changed:
        saved = save_config(cfg)
        print(f"Saved config to {saved}")

    print(f"Config file:  {config_path()}")
    print(f"output_dir:   {cfg.output_dir}")
    print(f"bitrate:      {cfg.bitrate}")
    print(f"embed_cover:  {cfg.embed_cover}")
    print(f"square_cover: {cfg.square_cover}")
    print(f"clean_titles: {cfg.clean_titles}")
    print(f"overwrite:    {cfg.overwrite}")
    return 0


def _handle_fix(args: argparse.Namespace, cfg: Config) -> int:
    target = Path(args.folder).expanduser() if args.folder else Path(cfg.output_dir)
    bitrate = args.bitrate or cfg.bitrate
    try:
        fixed, skipped, failed = fix_folder(target, bitrate=bitrate, dry_run=args.dry_run)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    verb = "Would fix" if args.dry_run else "Fixed"
    print(f"{verb}: {fixed} | Already valid: {skipped} | Failed: {failed}")
    return 1 if failed else 0


def _handle_tag(args: argparse.Namespace, cfg: Config) -> int:
    target = Path(args.file).expanduser()
    cover = Path(args.cover).expanduser() if args.cover else None
    try:
        update_track_tags(
            mp3_path=target,
            title=args.title,
            artist=args.artist,
            album=args.album,
            cover_path=cover,
            square_cover=False if args.no_crop else cfg.square_cover,
            remove_cover=args.remove_cover,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Updated tags: {target.name}")
    return 0


def _handle_refresh_spotify() -> int:
    removed = reset_local_files_cache()
    if not removed:
        print("No Spotify local-files.bnk cache files found.")
        return 0
    for path in removed:
        print(f"Removed cache: {path}")
    print("Restart Spotify to rescan your Local Files folders.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localify",
        description="Import non-DRM tracks from SoundCloud, YouTube, Bandcamp, and more into Spotify Local Files.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # localify download (also default when passing URLs directly)
    dl_parser = subparsers.add_parser("download", help="Download one or more track/playlist URLs")
    dl_parser.add_argument("urls", nargs="+", help="Track, playlist, or artist URLs")
    dl_parser.add_argument("-o", "--output", help="Override output folder")
    dl_parser.add_argument("-b", "--bitrate", help="MP3 bitrate (e.g. 192k, 256k, 320k)")
    dl_parser.add_argument("--artist", help="Override artist ID3 tag")
    dl_parser.add_argument("--title", help="Override title ID3 tag")
    dl_parser.add_argument("--album", help="Override album ID3 tag")
    dl_parser.add_argument("--cover", help="Embed a custom local image as cover art")
    dl_parser.add_argument("--no-cover", action="store_true", help="Do not embed cover art")
    dl_parser.add_argument("--no-crop", action="store_true", help="Do not square-crop cover art")
    dl_parser.add_argument("--no-clean-title", action="store_true", help="Keep original title without stripping tags")
    dl_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing MP3 files")

    # localify fix
    fix_parser = subparsers.add_parser("fix", help="Repair disguised/corrupt MP3 files in a folder")
    fix_parser.add_argument("folder", nargs="?", help="Folder to scan (defaults to configured output_dir)")
    fix_parser.add_argument("-b", "--bitrate", help="Target MP3 bitrate")
    fix_parser.add_argument("--dry-run", action="store_true", help="Report files that need fixing without modifying them")

    # localify tag
    tag_parser = subparsers.add_parser("tag", help="Edit ID3v2.3 tags or cover art on an existing MP3")
    tag_parser.add_argument("file", help="Path to an existing .mp3 file")
    tag_parser.add_argument("--title", help="Set title tag")
    tag_parser.add_argument("--artist", help="Set artist tag")
    tag_parser.add_argument("--album", help="Set album tag")
    tag_parser.add_argument("--cover", help="Path to cover image (.jpg/.png/.webp)")
    tag_parser.add_argument("--no-crop", action="store_true", help="Do not square-crop the cover image")
    tag_parser.add_argument("--remove-cover", action="store_true", help="Remove existing embedded cover art")

    # localify config
    cfg_parser = subparsers.add_parser("config", help="View or update saved localify settings")
    cfg_parser.add_argument("-o", "--output", help="Set default Spotify Local Files folder")
    cfg_parser.add_argument("-b", "--bitrate", help="Set default MP3 bitrate (e.g. 320k)")
    cfg_parser.add_argument("--embed-cover", type=_parse_bool, help="Embed cover art in MP3s (true/false)")
    cfg_parser.add_argument("--square-cover", type=_parse_bool, help="Square-crop cover art (true/false)")
    cfg_parser.add_argument("--clean-titles", type=_parse_bool, help="Clean noisy upload tags from titles (true/false)")
    cfg_parser.add_argument("--overwrite", type=_parse_bool, help="Overwrite existing files by default (true/false)")

    # localify refresh-spotify
    subparsers.add_parser("refresh-spotify", help="Clear Spotify's stale local-files.bnk cache")

    # localify gui / cli
    subparsers.add_parser("gui", help="Open the desktop GUI window")
    subparsers.add_parser("cli", help="Open interactive terminal mode")

    return parser


def _try_launch_gui() -> int | None:
    try:
        from .gui import launch_gui

        return launch_gui()
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()

    known_commands = {
        "download",
        "fix",
        "tag",
        "config",
        "refresh-spotify",
        "gui",
        "cli",
        "-h",
        "--help",
        "-v",
        "--version",
    }

    # Allow shorthand: `localify <url> [url ...]`
    if raw_args and raw_args[0] not in known_commands and not raw_args[0].startswith("-"):
        raw_args = ["download", *raw_args]

    if not raw_args:
        gui_rc = _try_launch_gui()
        if gui_rc is not None:
            return gui_rc
        opts = DownloadOptions(
            output_dir=Path(cfg.output_dir),
            bitrate=cfg.bitrate,
            embed_cover=cfg.embed_cover,
            square_cover=cfg.square_cover,
            clean_titles=cfg.clean_titles,
            overwrite=cfg.overwrite,
        )
        return _interactive_loop(opts)

    parser = build_parser()
    args = parser.parse_args(raw_args)

    if args.command == "gui":
        from .gui import launch_gui

        return launch_gui()
    if args.command == "cli":
        opts = DownloadOptions(
            output_dir=Path(cfg.output_dir),
            bitrate=cfg.bitrate,
            embed_cover=cfg.embed_cover,
            square_cover=cfg.square_cover,
            clean_titles=cfg.clean_titles,
            overwrite=cfg.overwrite,
        )
        return _interactive_loop(opts)
    if args.command == "config":
        return _handle_config(args, cfg)
    if args.command == "fix":
        return _handle_fix(args, cfg)
    if args.command == "tag":
        return _handle_tag(args, cfg)
    if args.command == "refresh-spotify":
        return _handle_refresh_spotify()
    if args.command == "download":
        opts = DownloadOptions(
            output_dir=Path(args.output).expanduser() if args.output else Path(cfg.output_dir),
            bitrate=args.bitrate or cfg.bitrate,
            embed_cover=False if args.no_cover else cfg.embed_cover,
            square_cover=False if args.no_crop else cfg.square_cover,
            clean_titles=False if args.no_clean_title else cfg.clean_titles,
            overwrite=True if args.overwrite else cfg.overwrite,
            artist_override=args.artist,
            title_override=args.title,
            album_override=args.album,
            cover_override=Path(args.cover).expanduser() if args.cover else None,
        )
        return _run_downloads(args.urls, opts)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
