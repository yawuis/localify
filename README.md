# localify

A cross-platform desktop app and CLI tool to import non-DRM audio tracks with embedded cover art and ID3v2.3 metadata directly into Spotify Local Files.

## Features

- **Desktop GUI and CLI:** Double-click the standalone `localify.exe` (or run `localify`) to open a desktop window with URL input, folder picker, auto-saved settings, and one-click tools. Full CLI support is also included for scripting.
- **Multi-platform support:** Works with SoundCloud, YouTube, YouTube Music, Bandcamp, Mixcloud, and other non-DRM sources supported by `yt-dlp`.
- **Spotify-compatible MP3 output:** Re-encodes audio to genuine 44.1 kHz MP3 (`libmp3lame`, 320 kbps default) so Spotify never greys out tracks with the `1193046:28:15` duration error.
- **Configurable cover art and tags:** Optionally embed cover art, center-crop thumbnails to 1:1 square JPEGs (ideal for YouTube 16:9 thumbnails), and write clean ID3v2.3 `title`, `artist`, `album`, and front-cover `APIC` frames.
- **Atomic staging:** Downloads and encodes in a temporary directory before moving finished `.mp3` files into your Spotify folder, preventing Spotify from caching `.part` or `.tmp` ghost entries.
- **Broken MP3 fixer:** Scan a folder and repair `.mp3` files that are actually M4A, AAC, Opus, or WebM containers.
- **Spotify cache reset:** Clear stale `local-files.bnk` caches on Windows, macOS, and Linux.

## Requirements

- `ffmpeg` and `ffprobe` on your `PATH`
  - **Windows:** `winget install Gyan.FFmpeg`
  - **macOS:** `brew install ffmpeg`
  - **Linux (Debian/Ubuntu):** `sudo apt install ffmpeg`
- Python 3.10+ (only needed if running from source; not required for the Windows `.exe` release)

## Quick Start

### Windows (Standalone `.exe`)

Download `localify-windows.exe` from GitHub Releases (or build it locally with `.\scripts\build_exe.ps1`) and double-click it. All settings (output folder, bitrate, cover art, square crop, overwrite) are configured and auto-saved directly inside the app.

### From Source (Windows, macOS, Linux)

```bash
git clone https://github.com/<your-username>/localify.git
cd localify
pip install .
```

Run the desktop window:

```bash
localify
# or
python -m localify
```

## CLI Usage

### Terminal interactive mode

```bash
localify cli
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
- `--no-cover` — Skip embedding cover art
- `--no-crop` — Keep original cover aspect ratio instead of 1:1 square crop
- `--overwrite` — Replace existing `.mp3` files with the same name

### Configure defaults

```bash
localify config --output "C:\Users\you\Music\Spotify Local Files" --bitrate 320k --embed-cover true --square-cover true
localify config
```

### Repair existing broken local files

```bash
localify fix --dry-run
localify fix
localify fix "/path/to/local/files"
```

### Reset Spotify's local files cache

Quit Spotify, run:

```bash
localify refresh-spotify
```

Then reopen Spotify.

## Building the Windows `.exe` Locally

```powershell
pip install -e ".[build]"
.\scripts\build_exe.ps1
```

The standalone executable is written to `dist\localify.exe`.

## Notes

- DRM-protected streams (such as SoundCloud Go+ encrypted tracks) are not supported and will be skipped with a clear error message.
- Make sure your configured output folder is added under **Spotify Settings > Local Files > Show songs from**.

## License

MIT
