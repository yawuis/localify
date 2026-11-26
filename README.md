# localify

A cross-platform CLI tool to import non-DRM audio tracks with embedded square cover art and ID3v2.3 metadata directly into Spotify Local Files.

## Features

- **Multi-platform support:** Works with SoundCloud, YouTube, YouTube Music, Bandcamp, Mixcloud, and other non-DRM sources supported by `yt-dlp`.
- **Spotify-compatible MP3 output:** Re-encodes audio to genuine 44.1 kHz MP3 (`libmp3lame`, 320 kbps default) so Spotify never greys out tracks with the `1193046:28:15` duration error.
- **Automatic cover art and tags:** Center-crops thumbnails to 1:1 square JPEGs (ideal for YouTube 16:9 thumbnails) and writes ID3v2.3 `title`, `artist`, `album`, and front-cover `APIC` frames.
- **Atomic staging:** Downloads and encodes in a temporary directory before moving the finished `.mp3` into your Spotify folder, preventing Spotify from caching `.part` or `.tmp` ghost entries.
- **Broken MP3 fixer:** Includes `localify fix` to scan a folder and repair `.mp3` files that are actually M4A, AAC, Opus, or WebM containers.
- **Spotify cache reset:** Includes `localify refresh-spotify` to remove stale `local-files.bnk` caches on Windows, macOS, and Linux.

## Requirements

- Python 3.10 or newer
- `ffmpeg` and `ffprobe` on your `PATH`
  - **Windows:** `winget install Gyan.FFmpeg`
  - **macOS:** `brew install ffmpeg`
  - **Linux (Debian/Ubuntu):** `sudo apt install ffmpeg`

## Installation

```bash
git clone https://github.com/<your-username>/localify.git
cd localify
pip install .
```

Or install in editable mode for development:

```bash
pip install -e .
```

## Usage

### Interactive mode

Run `localify` with no arguments to paste URLs one by one:

```bash
localify
```

### Download directly

```bash
localify "https://soundcloud.com/artist/track"
localify "https://www.youtube.com/watch?v=..." --artist "Artist Name" --title "Track Title"
localify "https://artist.bandcamp.com/album/album-name" --bitrate 320k
```

Options:
- `-o, --output DIR` — Override destination folder
- `-b, --bitrate RATE` — Target MP3 bitrate (default: `320k`)
- `--artist`, `--title`, `--album` — Override ID3 tags
- `--no-crop` — Keep original cover aspect ratio instead of 1:1 square crop
- `--overwrite` — Replace existing `.mp3` files with the same name

### Configure defaults

```bash
localify config --output "C:\Users\you\Music\Spotify Local Files" --bitrate 320k --square-cover true
localify config
```

### Repair existing broken local files

If Spotify shows `1193046:28:15` on existing `.mp3` files, inspect or repair them:

```bash
localify fix --dry-run
localify fix
localify fix "/path/to/local/files"
```

### Reset Spotify's local files cache

If Spotify keeps displaying deleted or outdated entries after fixing files, quit Spotify and run:

```bash
localify refresh-spotify
```

Then reopen Spotify.

## Notes

- DRM-protected streams (such as SoundCloud Go+ encrypted tracks) are not supported and will be skipped with a clear error message.
- Make sure your configured output folder is added under **Spotify Settings > Local Files > Show songs from**.

## License

MIT
