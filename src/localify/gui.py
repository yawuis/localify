from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__
from .config import Config, load_config, save_config
from .downloader import DownloadOptions, download_url
from .fixer import find_ffmpeg, fix_folder, install_ffmpeg_windows, probe_audio, update_track_tags
from .spotify import reset_local_files_cache

BG = "#121212"
SURFACE = "#1c1c1e"
SURFACE_ALT = "#26262a"
BORDER = "#333338"
FG = "#f2f2f5"
FG_MUTED = "#a0a0ab"
ACCENT = "#1db954"
ACCENT_HOVER = "#1ed760"

BITRATE_CHOICES = ("128k", "192k", "256k", "320k")
IMAGE_FILETYPES = [("Images", "*.jpg *.jpeg *.png *.webp *.bmp"), ("All files", "*.*")]
MP3_FILETYPES = [("MP3 files", "*.mp3"), ("All files", "*.*")]


def _open_folder_in_os(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class ToolTip:
    """Hover tooltip for Tkinter widgets."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 350) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip_window: tk.Toplevel | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event: tk.Event[tk.Misc]) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip_window is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=BORDER)

        label = tk.Label(
            tip,
            text=self.text,
            bg=SURFACE_ALT,
            fg=FG,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=270,
            padx=8,
            pady=5,
        )
        label.pack(padx=1, pady=1)

        tip.update_idletasks()
        screen_w = tip.winfo_screenwidth()
        tip_w = tip.winfo_reqwidth()
        if x + tip_w > screen_w - 8:
            x = max(8, screen_w - tip_w - 8)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip_window = tip

    def _hide(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._cancel()
        if self._tip_window is not None:
            try:
                self._tip_window.destroy()
            except tk.TclError:
                pass
            self._tip_window = None


class LocalifyApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"Localify {__version__}")
        self.root.geometry("780x760")
        self.root.minsize(680, 660)
        self.root.configure(bg=BG)

        self.cfg: Config = load_config()
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._progress_queue: queue.Queue[tuple[float, str]] = queue.Queue()
        self._busy = False

        # Shared settings variables
        self.output_dir_var = tk.StringVar(value=self.cfg.output_dir)
        self.bitrate_var = tk.StringVar(value=self.cfg.bitrate if self.cfg.bitrate in BITRATE_CHOICES else "320k")
        self.embed_cover_var = tk.BooleanVar(value=self.cfg.embed_cover)
        self.square_cover_var = tk.BooleanVar(value=self.cfg.square_cover)
        self.clean_titles_var = tk.BooleanVar(value=self.cfg.clean_titles)
        self.overwrite_var = tk.BooleanVar(value=self.cfg.overwrite)

        # Download tab variables
        self.artist_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.album_var = tk.StringVar()
        self.custom_cover_var = tk.StringVar()

        # Tag editor tab variables
        self.edit_file_var = tk.StringVar()
        self.edit_title_var = tk.StringVar()
        self.edit_artist_var = tk.StringVar()
        self.edit_album_var = tk.StringVar()
        self.edit_cover_var = tk.StringVar()
        self.edit_remove_cover_var = tk.BooleanVar(value=False)
        self.edit_cover_status_var = tk.StringVar(value="Select an MP3 file to view or edit its tags.")

        # Progress & status variables
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Ready")

        self._configure_styles()
        self._build_ui()
        self._sync_cover_checkbox_state()
        self._check_ffmpeg_on_startup()
        self._poll_queues()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE, relief="flat")
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Card.TLabel", background=SURFACE, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=FG_MUTED, font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=SURFACE, foreground=FG_MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 16))
        style.configure("Section.TLabel", background=SURFACE, foreground=FG, font=("Segoe UI Semibold", 10))

        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=SURFACE_ALT,
            foreground=FG_MUTED,
            padding=(14, 7),
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", SURFACE)],
            foreground=[("selected", FG)],
        )

        style.configure(
            "TEntry",
            fieldbackground=SURFACE_ALT,
            foreground=FG,
            insertcolor=FG,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=6,
        )
        style.configure(
            "TCombobox",
            fieldbackground=SURFACE_ALT,
            background=SURFACE_ALT,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", SURFACE_ALT)],
            foreground=[("readonly", FG)],
        )

        style.configure(
            "Card.TCheckbutton",
            background=SURFACE,
            foreground=FG,
            indicatorcolor=SURFACE_ALT,
            indicatordiameter=16,
            padding=2,
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", SURFACE)],
            foreground=[("disabled", FG_MUTED)],
            indicatorcolor=[("selected", ACCENT), ("disabled", BORDER)],
        )

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#0b0b0c",
            font=("Segoe UI Semibold", 10),
            borderwidth=0,
            padding=(16, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", BORDER)],
            foreground=[("disabled", FG_MUTED)],
        )

        style.configure(
            "Secondary.TButton",
            background=SURFACE_ALT,
            foreground=FG,
            borderwidth=0,
            padding=(12, 7),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", BORDER), ("disabled", SURFACE)],
            foreground=[("disabled", FG_MUTED)],
        )

        style.configure(
            "Localify.Horizontal.TProgressbar",
            troughcolor=SURFACE_ALT,
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=6,
        )

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        # Header
        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="Localify", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text=f"v{__version__}  |  Spotify Local Files Importer",
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0), pady=(5, 0))

        self.install_ffmpeg_btn = ttk.Button(
            header,
            text="Install FFmpeg",
            style="Accent.TButton",
            command=self._start_install_ffmpeg,
        )
        ToolTip(
            self.install_ffmpeg_btn,
            "Download and set up FFmpeg automatically for Localify (one-time Windows setup).",
        )

        # Tabs (Download / Edit Local Track)
        notebook = ttk.Notebook(container)
        notebook.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        dl_tab = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        edit_tab = ttk.Frame(notebook, style="Card.TFrame", padding=14)
        notebook.add(dl_tab, text="Download")
        notebook.add(edit_tab, text="Edit Local Track")

        self._build_download_tab(dl_tab)
        self._build_edit_tab(edit_tab)

        # Shared Settings Card
        self._build_settings_card(container)

        # Activity Log Card
        self._build_log_card(container)

        # Progress bar + status bar
        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(
            footer,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
            style="Localify.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w")

    def _build_download_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        dl_top = ttk.Frame(parent, style="Card.TFrame")
        dl_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(dl_top, text="Track, Playlist, or Artist URLs (one per line)", style="Section.TLabel").pack(
            side="left"
        )
        paste_btn = ttk.Button(dl_top, text="Paste", style="Secondary.TButton", command=self._paste_url)
        paste_btn.pack(side="right")
        ToolTip(paste_btn, "Paste a URL from your clipboard into the URL box.")

        self.url_text = tk.Text(
            parent,
            height=3,
            bg=SURFACE_ALT,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=("Consolas", 10),
            padx=8,
            pady=6,
            wrap="none",
        )
        self.url_text.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Optional metadata overrides
        meta_frame = ttk.Frame(parent, style="Card.TFrame")
        meta_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for col in (0, 1, 2):
            meta_frame.columnconfigure(col, weight=1)

        ttk.Label(meta_frame, text="Artist override (optional)", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(meta_frame, text="Title override (optional)", style="CardMuted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 6)
        )
        ttk.Label(meta_frame, text="Album override (optional)", style="CardMuted.TLabel").grid(
            row=0, column=2, sticky="w"
        )

        ttk.Entry(meta_frame, textvariable=self.artist_var).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(2, 0))
        ttk.Entry(meta_frame, textvariable=self.title_var).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(2, 0))
        ttk.Entry(meta_frame, textvariable=self.album_var).grid(row=1, column=2, sticky="ew", pady=(2, 0))

        # Custom cover image override
        cover_row = ttk.Frame(parent, style="Card.TFrame")
        cover_row.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        cover_row.columnconfigure(1, weight=1)

        ttk.Label(cover_row, text="Custom cover (optional):", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(cover_row, textvariable=self.custom_cover_var).grid(row=0, column=1, sticky="ew", padx=(0, 6))

        pick_cover_btn = ttk.Button(
            cover_row, text="Choose Image...", style="Secondary.TButton", command=self._browse_download_cover
        )
        pick_cover_btn.grid(row=0, column=2, padx=(0, 6))
        ToolTip(pick_cover_btn, "Use a local image instead of the track's default thumbnail.")

        clear_cover_btn = ttk.Button(
            cover_row,
            text="Clear",
            style="Secondary.TButton",
            command=lambda: self.custom_cover_var.set(""),
        )
        clear_cover_btn.grid(row=0, column=3)
        ToolTip(clear_cover_btn, "Revert to using the track's automatic thumbnail.")

        # Action buttons
        action_row = ttk.Frame(parent, style="Card.TFrame")
        action_row.grid(row=4, column=0, sticky="ew")

        self.download_btn = ttk.Button(
            action_row, text="Download to Spotify", style="Accent.TButton", command=self._start_download
        )
        self.download_btn.pack(side="left")
        ToolTip(
            self.download_btn,
            "Download the listed URLs as Spotify-compatible MP3s with tags and cover art.",
        )

        self.fix_btn = ttk.Button(
            action_row, text="Fix Folder MP3s", style="Secondary.TButton", command=self._start_fix_folder
        )
        self.fix_btn.pack(side="left", padx=(8, 0))
        ToolTip(
            self.fix_btn,
            "Scan your save folder and re-encode disguised or broken MP3s that show 1193046:28:15 in Spotify.",
        )

        self.refresh_btn = ttk.Button(
            action_row, text="Refresh Spotify Cache", style="Secondary.TButton", command=self._refresh_spotify
        )
        self.refresh_btn.pack(side="left", padx=(8, 0))
        ToolTip(
            self.refresh_btn,
            "Delete Spotify's stale local-files.bnk cache so Spotify rescans your folder on next launch.",
        )

    def _build_edit_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        file_row = ttk.Frame(parent, style="Card.TFrame")
        file_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        file_row.columnconfigure(1, weight=1)

        ttk.Label(file_row, text="MP3 file:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(file_row, textvariable=self.edit_file_var).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        pick_mp3_btn = ttk.Button(
            file_row, text="Choose MP3...", style="Secondary.TButton", command=self._browse_edit_mp3
        )
        pick_mp3_btn.grid(row=0, column=2)
        ToolTip(pick_mp3_btn, "Select an existing MP3 file from your Spotify folder to edit its tags or cover art.")

        meta_frame = ttk.Frame(parent, style="Card.TFrame")
        meta_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for col in (0, 1, 2):
            meta_frame.columnconfigure(col, weight=1)

        ttk.Label(meta_frame, text="Title", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(meta_frame, text="Artist", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Label(meta_frame, text="Album", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w")

        ttk.Entry(meta_frame, textvariable=self.edit_title_var).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(2, 0))
        ttk.Entry(meta_frame, textvariable=self.edit_artist_var).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(2, 0))
        ttk.Entry(meta_frame, textvariable=self.edit_album_var).grid(row=1, column=2, sticky="ew", pady=(2, 0))

        cover_row = ttk.Frame(parent, style="Card.TFrame")
        cover_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        cover_row.columnconfigure(1, weight=1)

        ttk.Label(cover_row, text="New cover image:", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(cover_row, textvariable=self.edit_cover_var).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        edit_cover_btn = ttk.Button(
            cover_row, text="Choose Image...", style="Secondary.TButton", command=self._browse_edit_cover
        )
        edit_cover_btn.grid(row=0, column=2, padx=(0, 6))
        ToolTip(edit_cover_btn, "Choose a new cover image to embed into this MP3.")

        clear_edit_cover_btn = ttk.Button(
            cover_row,
            text="Clear",
            style="Secondary.TButton",
            command=lambda: self.edit_cover_var.set(""),
        )
        clear_edit_cover_btn.grid(row=0, column=3)
        ToolTip(clear_edit_cover_btn, "Keep the current cover art unchanged.")

        bottom_row = ttk.Frame(parent, style="Card.TFrame")
        bottom_row.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        self.save_tags_btn = ttk.Button(
            bottom_row, text="Save Tags & Cover", style="Accent.TButton", command=self._start_save_tags
        )
        self.save_tags_btn.pack(side="left")
        ToolTip(
            self.save_tags_btn,
            "Write ID3v2.3 tags and cover art into the selected MP3 without re-encoding audio.",
        )

        remove_cb = ttk.Checkbutton(
            bottom_row,
            text="Remove existing cover",
            variable=self.edit_remove_cover_var,
            style="Card.TCheckbutton",
        )
        remove_cb.pack(side="left", padx=(14, 0))
        ToolTip(remove_cb, "Strip the embedded cover image from this MP3 when saving.")

        ttk.Label(parent, textvariable=self.edit_cover_status_var, style="CardMuted.TLabel").grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

    def _build_settings_card(self, container: ttk.Frame) -> None:
        settings_card = ttk.Frame(container, style="Card.TFrame", padding=14)
        settings_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        settings_card.columnconfigure(0, weight=1)

        ttk.Label(settings_card, text="Settings (auto-saved)", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        folder_row = ttk.Frame(settings_card, style="Card.TFrame")
        folder_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        folder_row.columnconfigure(1, weight=1)

        ttk.Label(folder_row, text="Save folder:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        folder_entry = ttk.Entry(folder_row, textvariable=self.output_dir_var)
        folder_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        folder_entry.bind("<FocusOut>", lambda _e: self._save_current_settings())

        browse_btn = ttk.Button(folder_row, text="Browse...", style="Secondary.TButton", command=self._browse_folder)
        browse_btn.grid(row=0, column=2, padx=(0, 6))
        ToolTip(browse_btn, "Choose the folder where downloaded MP3 files are saved.")

        open_btn = ttk.Button(folder_row, text="Open", style="Secondary.TButton", command=self._open_output_folder)
        open_btn.grid(row=0, column=3)
        ToolTip(open_btn, "Open the current save folder in your file manager.")

        opts_row = ttk.Frame(settings_card, style="Card.TFrame")
        opts_row.grid(row=2, column=0, sticky="ew")

        ttk.Label(opts_row, text="Bitrate:", style="Card.TLabel").pack(side="left", padx=(0, 6))
        bitrate_box = ttk.Combobox(
            opts_row,
            textvariable=self.bitrate_var,
            values=BITRATE_CHOICES,
            state="readonly",
            width=7,
        )
        bitrate_box.pack(side="left", padx=(0, 16))
        bitrate_box.bind("<<ComboboxSelected>>", lambda _e: self._save_current_settings())
        ToolTip(bitrate_box, "Target MP3 audio bitrate (320k is highest quality).")

        self.embed_cover_cb = ttk.Checkbutton(
            opts_row,
            text="Include cover art",
            variable=self.embed_cover_var,
            style="Card.TCheckbutton",
            command=self._on_cover_toggle,
        )
        self.embed_cover_cb.pack(side="left", padx=(0, 12))
        ToolTip(self.embed_cover_cb, "Embed the track's thumbnail as ID3v2.3 album art inside the MP3.")

        self.square_cover_cb = ttk.Checkbutton(
            opts_row,
            text="Square crop (1:1)",
            variable=self.square_cover_var,
            style="Card.TCheckbutton",
            command=self._save_current_settings,
        )
        self.square_cover_cb.pack(side="left", padx=(0, 12))
        ToolTip(self.square_cover_cb, "Center-crop rectangular thumbnails (such as YouTube 16:9) into a square cover.")

        self.clean_titles_cb = ttk.Checkbutton(
            opts_row,
            text="Clean titles",
            variable=self.clean_titles_var,
            style="Card.TCheckbutton",
            command=self._save_current_settings,
        )
        self.clean_titles_cb.pack(side="left", padx=(0, 12))
        ToolTip(
            self.clean_titles_cb,
            "Strip noisy upload tags like (Official Audio) and duplicate artist prefixes from track titles.",
        )

        self.overwrite_cb = ttk.Checkbutton(
            opts_row,
            text="Overwrite existing",
            variable=self.overwrite_var,
            style="Card.TCheckbutton",
            command=self._save_current_settings,
        )
        self.overwrite_cb.pack(side="left")
        ToolTip(self.overwrite_cb, "Replace an existing MP3 if a file with the same name already exists.")

    def _build_log_card(self, container: ttk.Frame) -> None:
        log_card = ttk.Frame(container, style="Card.TFrame", padding=14)
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        log_top = ttk.Frame(log_card, style="Card.TFrame")
        log_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(log_top, text="Activity Log", style="Section.TLabel").pack(side="left")
        clear_btn = ttk.Button(log_top, text="Clear", style="Secondary.TButton", command=self._clear_log)
        clear_btn.pack(side="right")
        ToolTip(clear_btn, "Clear all messages from the activity log.")

        log_wrap = ttk.Frame(log_card, style="Card.TFrame")
        log_wrap.grid(row=1, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_wrap,
            bg="#0d0d0f",
            fg=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=("Consolas", 9),
            padx=8,
            pady=6,
            state="disabled",
            wrap="word",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _report_progress(self, pct: float, text: str) -> None:
        self._progress_queue.put((pct, text))

    def _poll_queues(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        while True:
            try:
                pct, text = self._progress_queue.get_nowait()
            except queue.Empty:
                break
            self.progress_var.set(pct)
            self.status_var.set(text)

        self.root.after(80, self._poll_queues)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.download_btn.configure(state=state)
        self.fix_btn.configure(state=state)
        self.refresh_btn.configure(state=state)
        self.save_tags_btn.configure(state=state)
        self.install_ffmpeg_btn.configure(state=state)
        self.status_var.set(status)
        if not busy:
            self.progress_var.set(0.0)

    def _sync_cover_checkbox_state(self) -> None:
        if self.embed_cover_var.get():
            self.square_cover_cb.configure(state="normal")
        else:
            self.square_cover_cb.configure(state="disabled")

    def _on_cover_toggle(self) -> None:
        self._sync_cover_checkbox_state()
        self._save_current_settings()

    def _save_current_settings(self) -> Config:
        folder = self.output_dir_var.get().strip()
        if folder:
            self.cfg.output_dir = str(Path(folder).expanduser())
        self.cfg.bitrate = self.bitrate_var.get()
        self.cfg.embed_cover = self.embed_cover_var.get()
        self.cfg.square_cover = self.square_cover_var.get()
        self.cfg.clean_titles = self.clean_titles_var.get()
        self.cfg.overwrite = self.overwrite_var.get()
        save_config(self.cfg)
        return self.cfg

    def _check_ffmpeg_on_startup(self) -> None:
        if find_ffmpeg():
            self.install_ffmpeg_btn.pack_forget()
            self._log(f"Ready. Saving tracks to: {self.cfg.output_dir}")
        else:
            if sys.platform == "win32":
                self.install_ffmpeg_btn.pack(side="right")
                self._log("FFmpeg not found. Click 'Install FFmpeg' (or start a download to auto-install it).")
                self.status_var.set("FFmpeg not installed yet (auto-install available)")
            else:
                self._log("Warning: FFmpeg not found on PATH. Install it with brew/apt before downloading.")
                self.status_var.set("FFmpeg not found on PATH")

    def _start_install_ffmpeg(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Installing FFmpeg...")

        def worker() -> None:
            try:
                install_ffmpeg_windows(log=self._log, progress=self._report_progress)
                self.root.after(0, self._on_ffmpeg_installed)
            except RuntimeError as exc:
                self._log(f"Error: {exc}")
                self.root.after(0, lambda: self._set_busy(False, f"FFmpeg install failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ffmpeg_installed(self) -> None:
        self.install_ffmpeg_btn.pack_forget()
        self._set_busy(False, "FFmpeg installed and ready")

    def _paste_url(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        if not text:
            return
        existing = self.url_text.get("1.0", "end").strip()
        if existing:
            self.url_text.insert("end", "\n" + text)
        else:
            self.url_text.insert("1.0", text)

    def _browse_folder(self) -> None:
        initial = self.output_dir_var.get().strip() or str(Path.home())
        chosen = filedialog.askdirectory(initialdir=initial, title="Select Spotify Local Files Folder")
        if chosen:
            self.output_dir_var.set(str(Path(chosen)))
            self._save_current_settings()
            self._log(f"Output folder set to: {chosen}")

    def _browse_download_cover(self) -> None:
        chosen = filedialog.askopenfilename(title="Select Cover Image", filetypes=IMAGE_FILETYPES)
        if chosen:
            self.custom_cover_var.set(str(Path(chosen)))

    def _browse_edit_cover(self) -> None:
        chosen = filedialog.askopenfilename(title="Select New Cover Image", filetypes=IMAGE_FILETYPES)
        if chosen:
            self.edit_cover_var.set(str(Path(chosen)))
            self.edit_remove_cover_var.set(False)

    def _browse_edit_mp3(self) -> None:
        initial = self.output_dir_var.get().strip() or str(Path.home())
        chosen = filedialog.askopenfilename(
            initialdir=initial if Path(initial).is_dir() else str(Path.home()),
            title="Select MP3 Track to Edit",
            filetypes=MP3_FILETYPES,
        )
        if not chosen:
            return
        path = Path(chosen)
        self.edit_file_var.set(str(path))
        self.edit_cover_var.set("")
        self.edit_remove_cover_var.set(False)

        info = probe_audio(path)
        if info:
            self.edit_title_var.set(info.title)
            self.edit_artist_var.set(info.artist)
            self.edit_album_var.set(info.album)
            cover_state = "Has embedded cover art" if info.has_attached_pic else "No embedded cover art"
            self.edit_cover_status_var.set(f"Loaded {path.name} ({cover_state})")
        else:
            self.edit_cover_status_var.set(f"Loaded {path.name} (could not read existing tags)")

    def _open_output_folder(self) -> None:
        folder = Path(self.output_dir_var.get().strip() or self.cfg.output_dir).expanduser()
        try:
            _open_folder_in_os(folder)
        except OSError as exc:
            self._log(f"Could not open folder: {exc}")

    def _start_download(self) -> None:
        if self._busy:
            return
        raw = self.url_text.get("1.0", "end")
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        if not urls:
            self._log("Paste at least one URL before clicking Download.")
            return

        cfg = self._save_current_settings()
        cover_text = self.custom_cover_var.get().strip()
        opts = DownloadOptions(
            output_dir=Path(cfg.output_dir),
            bitrate=cfg.bitrate,
            embed_cover=cfg.embed_cover,
            square_cover=cfg.square_cover,
            clean_titles=cfg.clean_titles,
            overwrite=cfg.overwrite,
            artist_override=self.artist_var.get().strip() or None,
            title_override=self.title_var.get().strip() or None,
            album_override=self.album_var.get().strip() or None,
            cover_override=Path(cover_text).expanduser() if cover_text else None,
            auto_install_ffmpeg=(sys.platform == "win32"),
        )

        self._set_busy(True, f"Downloading {len(urls)} URL(s)...")

        def worker() -> None:
            added_total = 0
            errors = 0
            for url in urls:
                self._log(f"Downloading: {url}")
                try:
                    tracks = download_url(url, opts, log=self._log, progress=self._report_progress)
                    if not tracks:
                        self._log("  No new tracks added.")
                    for track in tracks:
                        cover_note = "with cover" if track.has_cover else "no cover"
                        self._log(f"  Added: {track.path.name} ({cover_note})")
                        added_total += 1
                except RuntimeError as exc:
                    self._log(f"  Error: {exc}")
                    errors += 1

            summary = f"Done: {added_total} track(s) added"
            if errors:
                summary += f", {errors} error(s)"
            self._log(summary)
            self.root.after(0, lambda: self._finish_download(errors == 0, summary))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_download(self, clear_inputs: bool, status: str) -> None:
        if find_ffmpeg():
            self.install_ffmpeg_btn.pack_forget()
        if clear_inputs:
            self.url_text.delete("1.0", "end")
            self.artist_var.set("")
            self.title_var.set("")
            self.album_var.set("")
            self.custom_cover_var.set("")
        self._set_busy(False, status)

    def _start_save_tags(self) -> None:
        if self._busy:
            return
        file_text = self.edit_file_var.get().strip()
        if not file_text:
            self._log("Select an MP3 file first.")
            return

        cfg = self._save_current_settings()
        mp3_path = Path(file_text).expanduser()
        cover_text = self.edit_cover_var.get().strip()
        cover_path = Path(cover_text).expanduser() if cover_text else None
        title = self.edit_title_var.get().strip()
        artist = self.edit_artist_var.get().strip()
        album = self.edit_album_var.get().strip()
        remove_cover = self.edit_remove_cover_var.get()

        self._set_busy(True, f"Updating {mp3_path.name}...")

        def worker() -> None:
            try:
                update_track_tags(
                    mp3_path=mp3_path,
                    title=title,
                    artist=artist,
                    album=album,
                    cover_path=cover_path,
                    square_cover=cfg.square_cover,
                    remove_cover=remove_cover,
                )
                msg = f"Updated tags/cover for {mp3_path.name}"
                self._log(msg)
                self.root.after(0, lambda: self._finish_save_tags(msg))
            except (RuntimeError, FileNotFoundError) as exc:
                msg = f"Error: {exc}"
                self._log(msg)
                self.root.after(0, lambda: self._set_busy(False, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_save_tags(self, msg: str) -> None:
        self.edit_cover_var.set("")
        self.edit_cover_status_var.set(f"{msg} (restart Spotify or click Refresh Spotify Cache if needed)")
        self._set_busy(False, msg)

    def _start_fix_folder(self) -> None:
        if self._busy:
            return
        cfg = self._save_current_settings()
        target = Path(cfg.output_dir)
        self._set_busy(True, "Scanning folder...")

        def worker() -> None:
            self._log(f"Scanning MP3s in: {target}")
            try:
                fixed, skipped, failed = fix_folder(
                    target, bitrate=cfg.bitrate, log=self._log, progress=self._report_progress
                )
                summary = f"Fix complete: {fixed} fixed, {skipped} already valid, {failed} failed"
            except (RuntimeError, FileNotFoundError) as exc:
                summary = f"Error: {exc}"
            self._log(summary)
            self.root.after(0, lambda: self._set_busy(False, summary))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_spotify(self) -> None:
        if self._busy:
            return
        removed = reset_local_files_cache()
        if not removed:
            self._log("No Spotify local-files.bnk cache files found.")
            self.status_var.set("No Spotify cache found")
            return
        for path in removed:
            self._log(f"Removed cache: {path}")
        self._log("Restart Spotify to rescan your Local Files folder.")
        self.status_var.set("Spotify cache cleared (restart Spotify)")


def launch_gui() -> int:
    root = tk.Tk()
    LocalifyApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch_gui())
