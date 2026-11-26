from __future__ import annotations

import unittest
from pathlib import Path

from localify.cli import build_parser
from localify.downloader import sanitize_filename
from localify.fixer import ProbeInfo, needs_spotify_fix


class TestSanitizeFilename(unittest.TestCase):
    def test_strips_illegal_characters(self) -> None:
        self.assertEqual(sanitize_filename('untiljapan: "Come/Thru"?*'), "untiljapan ComeThru")

    def test_collapses_whitespace_and_trailing_dots(self) -> None:
        self.assertEqual(sanitize_filename("  song   name...  "), "song name")

    def test_fallback_when_empty(self) -> None:
        self.assertEqual(sanitize_filename('<>:"/\\|?*'), "track")


class TestNeedsSpotifyFix(unittest.TestCase):
    def test_valid_mp3_does_not_need_fix(self) -> None:
        info = ProbeInfo(format_name="mp3", audio_codec="mp3", has_attached_pic=True, duration=150.0)
        self.assertFalse(needs_spotify_fix(info))

    def test_m4a_disguised_as_mp3_needs_fix(self) -> None:
        info = ProbeInfo(
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            audio_codec="aac",
            has_attached_pic=False,
            duration=157.8,
        )
        self.assertTrue(needs_spotify_fix(info))

    def test_unreadable_file_needs_fix(self) -> None:
        self.assertTrue(needs_spotify_fix(None))


class TestCliParser(unittest.TestCase):
    def test_download_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["download", "https://soundcloud.com/example/track", "--bitrate", "256k", "--no-crop", "--artist", "test"]
        )
        self.assertEqual(args.command, "download")
        self.assertEqual(args.urls, ["https://soundcloud.com/example/track"])
        self.assertEqual(args.bitrate, "256k")
        self.assertTrue(args.no_crop)
        self.assertEqual(args.artist, "test")

    def test_fix_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["fix", str(Path(".")), "--dry-run"])
        self.assertEqual(args.command, "fix")
        self.assertTrue(args.dry_run)

    def test_config_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "--square-cover", "false", "--bitrate", "192k"])
        self.assertEqual(args.command, "config")
        self.assertFalse(args.square_cover)
        self.assertEqual(args.bitrate, "192k")


if __name__ == "__main__":
    unittest.main()
