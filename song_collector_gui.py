from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import os
import json
import random
import tempfile
import tkinter as tk
from io import BytesIO
from tkinter import messagebox, filedialog, font as tkfont
import ttkbootstrap as ttk
from PIL import Image, ImageTk
from pathlib import Path, PureWindowsPath
from media_library import PROJECT_ROOT, LIBRARY_ERRORS, WorkingLibrary, atomic_write_json
from metadata_extractor import AudioMetadata, extract_audio_metadata, save_embedded_artwork


# ========== DATA MODEL ==========

@dataclass
class Song:
    """Represents a single song in the collection."""
    title: str
    artist: str
    duration_seconds: int
    genre: str
    rating: int  # 1–5
    filepath: str = ""      # path to audio file (optional)
    cover_path: str = ""    # path to album image (PNG preferred)
    id: int = field(default_factory=int)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip() or not isinstance(self.artist, str) or not self.artist.strip():
            raise ValueError("Title and artist are required text fields.")
        if any(not isinstance(value, str) for value in (self.genre, self.filepath, self.cover_path)):
            raise ValueError("Genre and file paths must be text.")
        if type(self.duration_seconds) is not int or type(self.rating) is not int:
            raise ValueError("Duration and rating must be integers.")
        if type(self.id) is not int or self.id < 0:
            raise ValueError("Song ID must be a non-negative integer.")
        if self.duration_seconds < 0:
            raise ValueError("Duration must be non-negative.")
        if not (1 <= self.rating <= 5):
            raise ValueError("Rating must be between 1 and 5.")

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    def similarity_score(self, keyword: str) -> float:
        """
        'Clever' algorithm:
        Computes how similar a keyword is to title+artist using words.
        Score 0..1 (higher = more similar).
        """
        kw_words = set(keyword.lower().split())
        text = f"{self.title} {self.artist}".lower()
        song_words = set(text.split())

        if not kw_words or not song_words:
            return 0.0

        common = kw_words & song_words
        union = kw_words | song_words
        return len(common) / len(union)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration_seconds": self.duration_seconds,
            "genre": self.genre,
            "rating": self.rating,
            "filepath": self.filepath,
            "cover_path": self.cover_path,
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Song":
        return cls(
            title=data["title"],
            artist=data["artist"],
            duration_seconds=data["duration_seconds"],
            genre=data["genre"],
            rating=data["rating"],
            filepath=data.get("filepath", ""),
            cover_path=data.get("cover_path", ""),
            id=data.get("id", 0),
        )


class SongCollector:
    """Stores all songs and provides operations over them."""

    def __init__(self) -> None:
        self._songs: List[Song] = []
        self._next_id: int = 1

    # ----- CRUD -----
    def add_song(
        self,
        title: str,
        artist: str,
        duration_seconds: int,
        genre: str,
        rating: int,
        filepath: str,
        cover_path: str,
    ) -> Song:
        song = Song(
            id=self._next_id,
            title=title,
            artist=artist,
            duration_seconds=duration_seconds,
            genre=genre,
            rating=rating,
            filepath=filepath,
            cover_path=cover_path,
        )
        self._songs.append(song)
        self._next_id += 1
        return song

    def remove_song_by_id(self, song_id: int) -> bool:
        for s in self._songs:
            if s.id == song_id:
                self._songs.remove(s)
                return True
        return False

    def get_song_by_id(self, song_id: int) -> Song | None:
        for s in self._songs:
            if s.id == song_id:
                return s
        return None

    def list_songs(self) -> List[Song]:
        return list(self._songs)

    def update_song(
        self,
        song_id: int,
        *,
        title: str,
        artist: str,
        duration_seconds: int,
        genre: str,
        rating: int,
        filepath: str,
        cover_path: str,
    ) -> bool:
        """
        Update properties of an existing song.
        Returns True on success, False if song_id not found.
        """
        song = self.get_song_by_id(song_id)
        if song is None:
            return False
        # Validate the full edit before changing the existing song.
        updated = Song(title, artist, duration_seconds, genre, rating, filepath, cover_path, song_id)
        for name, value in updated.to_dict().items():
            setattr(song, name, value)
        return True

    # ----- sorting -----
    def sort_songs(self, key: str) -> None:
        if key == "Title":
            self._songs.sort(key=lambda s: s.title.lower())
        elif key == "Duration":
            self._songs.sort(key=lambda s: s.duration_seconds)
        elif key == "Rating":
            self._songs.sort(key=lambda s: s.rating, reverse=True)
        elif key == "Newest":
            self._songs.sort(key=lambda s: s.id, reverse=True)
        elif key == "Oldest":
            self._songs.sort(key=lambda s: s.id)

    # ----- searching -----
    def search_smart(self, keyword: str) -> List[Song]:
        scored: List[Tuple[Song, float]] = [
            (s, s.similarity_score(keyword)) for s in self._songs
        ]
        scored = [(s, score) for s, score in scored if score > 0.0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [s for s, _ in scored]

    # ----- statistics -----
    def genre_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self._songs:
            counts[s.genre] = counts.get(s.genre, 0) + 1
        return counts

    def total_duration(self, songs: List[Song] | None = None) -> int:
        if songs is None:
            songs = self._songs
        return sum(s.duration_seconds for s in songs)

    # ----- save / load -----
    def save_to_file(self, filename: str) -> None:
        data = {
            "next_id": self._next_id,
            "songs": [s.to_dict() for s in self._songs],
        }
        atomic_write_json(filename, data)

    def load_from_file(self, filename: str) -> None:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
            raise ValueError("Library must contain a songs list.")
        songs = []
        for record in data["songs"]:
            if not isinstance(record, dict):
                raise ValueError("Each song must be an object.")
            songs.append(Song.from_dict(record))
        ids = [song.id for song in songs]
        if len(set(ids)) != len(ids):
            raise ValueError("Library contains duplicate song IDs.")
        max_id = max(ids, default=0)
        next_id = max(max_id + 1, int(data.get("next_id", max_id + 1)))
        # Commit only after the entire library has passed validation.
        self._songs = songs
        self._next_id = next_id



# ========== GUI APPLICATION ==========

class SongCollectorApp:
    PALETTES = {
        True: dict(bg="#171D24", surface="#252E38", accent="#E8A06C",
                   text="#F0F2F4", muted="#B7C1CC", border="#3D4B59", selected="#65432D"),
        False: dict(bg="#F5F2EC", surface="#FFFFFF", accent="#B9683B",
                    text="#25313B", muted="#536170", border="#CFC6BC", selected="#EFD9C9"),
    }

    def __init__(self, root: tk.Tk, project_root: Path = PROJECT_ROOT) -> None:
        self.root = root
        self.library = WorkingLibrary(project_root)
        root.title("Song Collector & Playlist Manager")
        root.geometry("1280x780")
        root.minsize(1040, 680)
        self.dark_mode = True
        self.collector = SongCollector()
        self.cover_image = None
        self.form_cover_image = None
        self.current_edit_id = None
        self.dialog = None
        self.dirty = False
        self.style = ttk.Style("darkly")
        for name in ("title", "artist", "duration", "genre", "rating", "filepath", "coverpath"):
            setattr(self, "var_" + name, tk.StringVar(root))
        self._automatic_cover_path = ""
        self._form_changes: set[str] = set()
        self._suppress_form_tracking = False
        for name in ("title", "artist", "duration", "genre", "rating", "filepath", "coverpath"):
            getattr(self, "var_" + name).trace_add("write", lambda *_args, field=name: self._track_form_change(field))
        self.var_search = tk.StringVar(root)
        self.var_sort = tk.StringVar(root, value="Title")
        self.var_total = tk.StringVar(root)
        self.var_status = tk.StringVar(root, value="Opening local library…")
        self._configure_style()
        self._create_widgets()
        self._load_working_library()
        self.refresh_list()
        root.bind("<Control-n>", lambda e: self.open_song_dialog())
        root.bind("<Control-f>", self._focus_search)
        root.bind("<Control-s>", lambda e: self.save_library())
        root.bind("<Control-o>", lambda e: self.load_library())
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        c = self.PALETTES[self.dark_mode]
        self.style.theme_use("darkly" if self.dark_mode else "flatly")
        self.root.configure(background=c["bg"])
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family="Segoe UI", size=10)
        self.root.option_add("*TCombobox*Listbox.background", c["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        for name, bg in (("TFrame", c["bg"]), ("Surface.TFrame", c["surface"])):
            self.style.configure(name, background=bg)
        self.style.configure("TLabel", background=c["bg"], foreground=c["text"], font=("Segoe UI", 10))
        self.style.configure("Muted.TLabel", foreground=c["muted"])
        self.style.configure("Title.TLabel", font=("Segoe UI Semibold", 23))
        self.style.configure("Heading.TLabel", font=("Segoe UI Semibold", 12))
        self.style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(12, 8),
                             background=c["surface"], foreground=c["text"], bordercolor=c["border"], focuscolor=c["accent"])
        if self.dark_mode:
            self.style.map("Secondary.TButton", background=[("active", c["selected"])],
                           foreground=[("disabled", c["muted"]), ("active", c["text"])],
                           bordercolor=[("focus", c["accent"]), ("active", c["accent"])])
        else:
            self.style.configure(
                "Secondary.TButton",
                background="#E6E0D7",
                foreground="#25313B",
                bordercolor="#CFC6BC",
                lightcolor="#CFC6BC",
                darkcolor="#CFC6BC",
            )
            self.style.map(
                "Secondary.TButton",
                background=[
                    ("disabled", "#EEEAE4"),
                    ("pressed", "#D8CBBE"),
                    ("active", "#EFD9C9"),
                ],
                foreground=[("disabled", "#81786E"), ("pressed", "#25313B"), ("active", "#25313B")],
                bordercolor=[
                    ("disabled", "#DDD5CC"),
                    ("focus", "#B9683B"),
                    ("pressed", "#B9683B"),
                    ("active", "#CFC6BC"),
                ],
            )
        self.style.configure("Accent.TButton", background=c["accent"], foreground="#171D24" if self.dark_mode else "#FFFFFF", bordercolor=c["accent"])
        self.style.map("Accent.TButton", background=[("active", "#F0B88F" if self.dark_mode else "#98512B")])
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            self.style.configure(name, fieldbackground=c["surface"], foreground=c["text"], bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"], padding=7)
            self.style.map(name, bordercolor=[("focus", c["accent"])])
        self.style.configure("Library.Treeview", background=c["surface"], fieldbackground=c["surface"], foreground=c["text"], rowheight=38, font=("Segoe UI", 10), borderwidth=0)
        self.style.configure("Library.Treeview.Heading", background=c["bg"], foreground=c["muted"], font=("Segoe UI Semibold", 10), padding=(10, 10))
        self.style.map("Library.Treeview", background=[("selected", c["selected"])], foreground=[("selected", c["text"])])

    def toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._configure_style()
        self.inspector_canvas.configure(background=self.PALETTES[self.dark_mode]["bg"])
        self.theme_button.configure(text="Light appearance" if self.dark_mode else "Dark appearance")
        if self.dialog is not None:
            self.dialog.configure(background=self.PALETTES[self.dark_mode]["bg"])

    def _play_double_clicked_row(self, event: tk.Event) -> str:
        row = self.tree.identify_row(event.y)
        if not row:
            return "break"
        self.tree.selection_set(row)
        self.tree.focus(row)
        self.play_selected()
        return "break"

    def _create_widgets(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        side = ttk.Frame(self.root, padding=(16, 24))
        side.grid(row=0, column=0, sticky="ns")
        side.rowconfigure(5, weight=1)
        ttk.Label(side, text="SONG COLLECTOR\n& PLAYLIST MANAGER", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 28))
        ttk.Button(side, text="Music library", command=self.show_all, style="Accent.TButton").grid(row=1, column=0, sticky="ew")
        ttk.Button(side, style="Secondary.TButton", text="Genre statistics", command=self.show_stats).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Separator(side).grid(row=3, column=0, sticky="ew", pady=20)
        files = ttk.Frame(side)
        files.grid(row=4, column=0, sticky="ew")
        ttk.Button(files, style="Secondary.TButton", text="Import library…", command=self.load_library).pack(fill="x", pady=(0, 8))
        ttk.Button(files, style="Secondary.TButton", text="Export library…", command=self.save_library).pack(fill="x")
        self.theme_button = ttk.Button(side, style="Secondary.TButton", text="Light appearance", command=self.toggle_theme)
        self.theme_button.grid(row=6, column=0, sticky="ew")
        ttk.Label(side, text="Local music · Your files", style="Muted.TLabel").grid(row=7, column=0, pady=(12, 0))
        ttk.Separator(self.root, orient="vertical").grid(row=0, column=0, sticky="nse")

        main = ttk.Frame(self.root, padding=(24, 24, 20, 12))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Music library", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.count_label = ttk.Label(header, style="Muted.TLabel")
        self.count_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(header, text="Add song", command=self.open_song_dialog, style="Accent.TButton").grid(row=0, column=1, rowspan=2)
        search = ttk.Frame(main)
        search.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Search").grid(row=0, column=0, padx=(0, 10))
        self.search_entry = ttk.Entry(search, textvariable=self.var_search)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self.smart_search())
        ttk.Button(search, style="Secondary.TButton", text="Search", command=self.smart_search).grid(row=0, column=2, padx=8)
        ttk.Button(search, style="Secondary.TButton", text="Clear", command=self.show_all).grid(row=0, column=3)
        toolbar = ttk.Frame(main)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, text="Title / artist keywords", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text="Sort by").grid(row=0, column=1, padx=(8, 8))
        combo = ttk.Combobox(toolbar, textvariable=self.var_sort, values=["Title", "Duration", "Rating", "Newest", "Oldest"], state="readonly", width=10)
        combo.grid(row=0, column=2)
        combo.bind("<<ComboboxSelected>>", lambda e: self.apply_sort())
        table = ttk.Frame(main)
        table.grid(row=3, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        columns = ("title", "artist", "genre", "duration", "rating")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended", style="Library.Treeview")
        for col, width, minimum in zip(columns, (200, 145, 130, 90, 85), (160, 130, 120, 90, 85)):
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=width, minwidth=minimum, stretch=col in ("title", "artist", "genre"), anchor="w" if col in ("title", "artist", "genre") else "center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_song_selected)
        self.tree.bind("<Double-1>", self._play_double_clicked_row)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.empty = ttk.Frame(table, padding=20)
        self.empty_title = ttk.Label(self.empty, style="Heading.TLabel", text="Your library starts here")
        self.empty_title.pack(pady=(0, 8))
        self.empty_hint = ttk.Label(self.empty, text="Add a song or load an existing JSON library.")
        self.empty_hint.pack(pady=(0, 16))
        self.empty_button = ttk.Button(self.empty, text="Add your first song", command=self.open_song_dialog, style="Accent.TButton")
        self.empty_button.pack()
        footer = ttk.Frame(main)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 8))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.var_total, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.play_all_button = ttk.Button(footer, style="Secondary.TButton", text="Play all", command=self.play_all)
        self.play_all_button.grid(row=0, column=1, padx=(8, 6))
        self.random_button = ttk.Button(footer, style="Secondary.TButton", text="Random", command=self.play_random)
        self.random_button.grid(row=0, column=2)
        ttk.Label(main, textvariable=self.var_status, style="Muted.TLabel").grid(row=5, column=0, sticky="w")

        inspector = ttk.Frame(self.root, width=280)
        inspector.grid(row=0, column=2, sticky="ns")
        inspector.grid_propagate(False)
        inspector.rowconfigure(0, weight=1)
        inspector.columnconfigure(0, weight=1)
        self.inspector_canvas = tk.Canvas(inspector, highlightthickness=0,
                                         background=self.PALETTES[self.dark_mode]["bg"])
        self.inspector_canvas.grid(row=0, column=0, sticky="nsew")
        inspector_scroll = ttk.Scrollbar(inspector, command=self.inspector_canvas.yview)
        inspector_scroll.grid(row=0, column=1, sticky="ns")
        self.inspector_canvas.configure(yscrollcommand=inspector_scroll.set)
        details = ttk.Frame(self.inspector_canvas, padding=(16, 28))
        details_window = self.inspector_canvas.create_window((0, 0), window=details, anchor="nw")
        details.bind("<Configure>", lambda e: self.inspector_canvas.configure(scrollregion=self.inspector_canvas.bbox("all")))
        self.inspector_canvas.bind("<Configure>", lambda e: self.inspector_canvas.itemconfigure(details_window, width=e.width))
        details.columnconfigure(0, weight=1)
        ttk.Label(details, text="SONG DETAILS", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 20))
        self.lbl_cover = ttk.Label(details, text="No cover selected", anchor="center", width=26)
        self.lbl_cover.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        self.detail_title = ttk.Label(details, text="Select a song", style="Heading.TLabel", wraplength=215)
        self.detail_title.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.detail_meta = ttk.Label(details, text="Browse your library to see details.", wraplength=215, style="Muted.TLabel")
        self.detail_meta.grid(row=3, column=0, sticky="w", pady=(0, 12))
        self.detail_file = ttk.Label(details, wraplength=215, style="Muted.TLabel")
        self.detail_file.grid(row=4, column=0, sticky="w", pady=(0, 20))
        self.selection_buttons = []
        for row, text, command in ((5, "Play selected", self.play_selected), (6, "Edit song", lambda: self.open_song_dialog(edit=True)), (7, "Remove from library", self.delete_selected)):
            button = ttk.Button(details, style="Secondary.TButton", text=text, command=command)
            button.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            self.selection_buttons.append(button)
        ttk.Label(details, text="Audio opens in your default player.\nRemoving a song keeps its files.", wraplength=215, style="Muted.TLabel").grid(row=8, column=0, sticky="w", pady=(12, 0))

        for widget in (details, *details.winfo_children()):
            widget.bind("<MouseWheel>", lambda e: self.inspector_canvas.yview_scroll(-int(e.delta / 120), "units"))

    def _focus_search(self, event=None):
        if self.dialog is None:
            self.search_entry.focus_set()
        return "break"

    def show_all(self):
        self.var_search.set("")
        self.refresh_list()

    def open_song_dialog(self, edit=False):
        if self.dialog is not None:
            self.dialog.lift()
            return
        ids = self._get_selected_ids()
        if edit and len(ids) != 1:
            return
        self.clear_form()
        if edit:
            self.current_edit_id = ids[0]
            self._load_song_into_form(self.collector.get_song_by_id(ids[0]))
        else:
            self._set_form_value("rating", "3")
            self._set_form_value("duration", "0")
        dialog = tk.Toplevel(self.root)
        self.dialog = dialog
        dialog.title("Edit song" if edit else "Add song")
        dialog.configure(background=self.PALETTES[self.dark_mode]["bg"])
        dialog.transient(self.root)
        dialog.resizable(True, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Edit song" if edit else "Add to your library", style="Heading.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 18))
        first = None
        for row, (label, name) in enumerate((("Title *", "title"), ("Artist *", "artist"), ("Duration (seconds)", "duration"), ("Genre", "genre"), ("Rating (1–5)", "rating"), ("Audio file", "filepath"), ("Cover image", "coverpath")), 1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=8)
            entry = ttk.Entry(body, textvariable=getattr(self, "var_" + name), width=42)
            entry.grid(row=row, column=1, sticky="ew", pady=8)
            if first is None:
                first = entry
            if name in ("filepath", "coverpath"):
                ttk.Button(body, style="Secondary.TButton", text="Browse…", command=self.browse_audio if name == "filepath" else self.browse_cover).grid(row=row, column=2, padx=(8, 0))
        self.form_cover_label = ttk.Label(body, text="No detected artwork", anchor="center")
        self.form_cover_label.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(6, 8))
        ttk.Label(body, text="Audio and cover files are optional. Rating remains manual.", style="Muted.TLabel").grid(row=9, column=0, columnspan=3, sticky="w", pady=(2, 16))
        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, style="Secondary.TButton", text="Cancel", command=self._close_dialog).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save changes" if edit else "Add song", style="Accent.TButton", command=self.update_selected_song if edit else self.add_song).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", self._close_dialog)
        dialog.bind("<Escape>", lambda e: self._close_dialog())
        dialog.bind("<Control-Return>", lambda e: self.update_selected_song() if edit else self.add_song())
        dialog.update_idletasks()
        dialog.geometry(f"+{self.root.winfo_rootx() + 100}+{self.root.winfo_rooty() + 70}")
        dialog.grab_set()
        self._update_form_cover_preview(self.var_coverpath.get())
        first.focus_set()

    def _close_dialog(self):
        if self.dialog is not None:
            self.dialog.grab_release()
            self.dialog.destroy()
            self.dialog = None
        self.current_edit_id = None
        self._form_changes.clear()
        self.on_song_selected()

    def _load_working_library(self):
        try:
            self.collector = self.library.startup(SongCollector)
            self.var_status.set("Automatic saving · data/library.json")
        except LIBRARY_ERRORS as error:
            if self.library.loaded_collector is not None:
                self.collector = self.library.loaded_collector
                self.dirty = True
            self.var_status.set("Library startup failed · Changes are not saved")
            messagebox.showerror("Library startup", f"Could not open or initialize the working library.\n{error}\n\nExisting files have been kept. Export any new edits before closing.", parent=self.root)

    def _mark_changed(self):
        self.dirty = True
        self._autosave()

    def _autosave(self):
        try:
            self.library.save(self.collector)
        except LIBRARY_ERRORS as error:
            self.dirty = True
            self.var_status.set("Automatic save failed · Unsaved changes in memory")
            messagebox.showerror("Automatic save failed", f"Your changes are still in memory.\n{error}\n\nExport to a new JSON file before closing if saving keeps failing.", parent=self.dialog or self.root)
            return False
        self.dirty = False
        self.var_status.set("Automatically saved · data/library.json")
        return True

    def close(self):
        if self.dirty:
            if not self._autosave() and not messagebox.askyesno("Unsaved library", "Automatic saving failed. Close and discard the changes still in memory? Export first if you need to keep them.", parent=self.root):
                return
        self.root.destroy()

    # ---------- file browsing ----------

    def browse_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Select audio file", parent=self.dialog or self.root,
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.flac *.m4a"),
                ("All files", "*.*"),
            ],
        )
        if path:
            source = Path(path).resolve()
            if not self._set_browsed_media(source, "audio", self.var_filepath):
                return
            detected = extract_audio_metadata(source, self._artwork_folders())
            cover_path = ""
            if self._can_detect_cover():
                try:
                    cover_path = self._store_detected_cover(source, detected)
                except OSError as error:
                    messagebox.showerror("Artwork import", f"Could not save artwork. The audio selection is still available.\n{error}", parent=self.dialog or self.root)
            self._apply_detected_metadata(detected, cover_path)

    def _artwork_folders(self):
        return (self.library.media.root, self.library.media.folder("covers"), self.library.media.folder("audio"))

    def _can_detect_cover(self):
        current = self.var_coverpath.get().strip()
        return "coverpath" not in self._form_changes and (not current or current == self._automatic_cover_path)

    def _store_detected_cover(self, source, metadata):
        if metadata.artwork:
            cover = save_embedded_artwork(metadata.artwork, metadata.artwork_extension,
                                          self.library.media.folder("covers"), source.stem)
            return self.library.media.reference(cover)
        if metadata.cover_path:
            return self.library.media.copy_asset(metadata.cover_path, "covers")
        return ""

    def browse_cover(self) -> None:
        path = filedialog.askopenfilename(
            title="Select album cover", parent=self.dialog or self.root,
            filetypes=[("Cover images", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if path and self._set_browsed_media(path, "covers", self.var_coverpath):
            self._update_form_cover_preview(self.var_coverpath.get())

    def _set_browsed_media(self, filename, kind, variable) -> bool:
        try:
            reference = self.library.media.copy_asset(filename, kind)
            variable.set(reference)
            return True
        except OSError as error:
            messagebox.showerror("Media import", f"Could not copy this file. The form has not changed.\n{error}", parent=self.dialog or self.root)
            return False

    # ---------- core actions ----------

    def add_song(self) -> None:
        data = self._read_form_data()
        if data is None:
            return
        song = self.collector.add_song(**data)
        self._mark_changed()
        self.refresh_list()
        self._close_dialog()
        if self.tree.exists(str(song.id)):
            self.tree.selection_set(str(song.id))
            self.tree.see(str(song.id))
            self.on_song_selected()

    def update_selected_song(self) -> None:
        if self.current_edit_id is None:
            messagebox.showinfo("Update", "Select one song in the list to edit.")
            return
        data = self._read_form_data()
        if data is None:
            return
        ok = self.collector.update_song(self.current_edit_id, **data)
        if not ok:
            messagebox.showerror("Update", "Could not find song to update.")
            return
        self._mark_changed()
        self.refresh_list()
        self._close_dialog()

    def _track_form_change(self, field: str) -> None:
        if not self._suppress_form_tracking:
            self._form_changes.add(field)

    def _set_form_value(self, field: str, value: str) -> None:
        self._suppress_form_tracking = True
        try:
            getattr(self, "var_" + field).set(value)
        finally:
            self._suppress_form_tracking = False

    def _apply_detected_metadata(self, metadata: AudioMetadata, cover_path: str) -> None:
        values = {
            "title": metadata.title,
            "artist": metadata.artist,
            "duration": str(metadata.duration_seconds) if metadata.duration_seconds is not None else "",
            "genre": metadata.genre,
        }
        for field, value in values.items():
            current = getattr(self, "var_" + field).get().strip()
            if value and field not in self._form_changes and not (self.current_edit_id is not None and current):
                self._set_form_value(field, value)
        if self._can_detect_cover():
            self._set_form_value("coverpath", cover_path)
            self._automatic_cover_path = cover_path
        self._update_form_cover_preview(self.var_coverpath.get())

    def _update_form_cover_preview(self, path: str = "", data: bytes | None = None) -> None:
        if self.dialog is None or not hasattr(self, "form_cover_label") or not self.form_cover_label.winfo_exists():
            return
        try:
            if data is not None:
                source = Image.open(BytesIO(data))
            elif path:
                resolved = self.library.media.resolve(path, "covers")
                if resolved is None or not resolved.is_file():
                    raise OSError("Cover image is missing.")
                source = Image.open(resolved)
            else:
                raise OSError("No cover image selected.")
            source = source.copy()
            source.thumbnail((210, 150), Image.Resampling.LANCZOS)
            self.form_cover_image = ImageTk.PhotoImage(source, master=self.dialog)
            self.form_cover_label.configure(image=self.form_cover_image, text="")
        except (OSError, ValueError):
            self.form_cover_image = None
            self.form_cover_label.configure(image="", text="No detected artwork")

    def clear_form(self) -> None:
        self._automatic_cover_path = ""
        for name in ("title", "artist", "duration", "genre", "rating", "filepath", "coverpath"):
            self._set_form_value(name, "")
        self._form_changes.clear()
        self.current_edit_id = None

    def _read_form_data(self) -> Dict[str, Any] | None:
        title = self.var_title.get().strip()
        artist = self.var_artist.get().strip()
        duration_text = self.var_duration.get().strip()
        genre = self.var_genre.get().strip()
        rating_text = self.var_rating.get().strip()
        filepath = self.var_filepath.get().strip()
        coverpath = self.var_coverpath.get().strip()

        if not title or not artist:
            messagebox.showwarning("Input error", "Title and Artist are required.")
            return None
        try:
            duration = int(duration_text)
            rating = int(rating_text)
        except ValueError:
            messagebox.showwarning("Input error", "Duration and rating must be integers.")
            return None
        if duration < 0:
            messagebox.showwarning("Input error", "Duration must be non-negative.")
            return None
        if not (1 <= rating <= 5):
            messagebox.showwarning("Input error", "Rating must be between 1 and 5.")
            return None

        return {
            "title": title,
            "artist": artist,
            "duration_seconds": duration,
            "genre": genre,
            "rating": rating,
            "filepath": self.library.media.normalize(filepath, "audio"),
            "cover_path": self.library.media.normalize(coverpath, "covers"),
        }

    def refresh_list(self, songs: List[Song] | None = None) -> None:
        selected = self.tree.selection()
        if songs is None:
            keyword = self.var_search.get().strip()
            songs = self.collector.search_smart(keyword) if keyword else self.collector.list_songs()
            key = self.var_sort.get()
            keys = {"Title": lambda s: s.title.lower(), "Duration": lambda s: s.duration_seconds,
                    "Rating": lambda s: -s.rating, "Newest": lambda s: -s.id, "Oldest": lambda s: s.id}
            songs.sort(key=keys[key])
        self.tree.delete(*self.tree.get_children())
        for song in songs:
            minutes, seconds = divmod(song.duration_seconds, 60)
            self.tree.insert("", "end", iid=str(song.id), values=(song.title, song.artist, song.genre, f"{minutes}:{seconds:02d}", f"{song.rating} / 5"))
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        self.count_label.configure(text=f"{len(self.collector.list_songs())} songs in your collection")
        self.update_total_duration_label(songs)
        if not songs:
            filtered = bool(self.collector.list_songs())
            self.empty_title.configure(text="No matching songs" if filtered else "Your library starts here")
            self.empty_hint.configure(text="Try another title or artist keyword." if filtered else "Add a song or load an existing JSON library.")
            self.empty_button.configure(text="Clear search" if filtered else "Add your first song", command=self.show_all if filtered else self.open_song_dialog)
            self.empty.place(relx=.5, rely=.5, anchor="center")
        else:
            self.empty.place_forget()
        for button in (self.play_all_button, self.random_button):
            button.configure(state="normal" if self.collector.list_songs() else "disabled")
        self.on_song_selected()

    def _get_selected_ids(self) -> List[int]:
        return [int(iid) for iid in self.tree.selection()]

    def delete_selected(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("Delete", "Please select at least one song.")
            return
        if not messagebox.askyesno("Remove songs", f"Remove {len(ids)} song(s) from the library? Their files will be kept."):
            return
        for song_id in ids:
            self.collector.remove_song_by_id(song_id)
        self._mark_changed()
        self.refresh_list()
        self.clear_form()

    # ---------- selection / editing ----------

    def on_song_selected(self, event: tk.Event | None = None) -> None:
        ids = self._get_selected_ids()
        for index, button in enumerate(self.selection_buttons):
            button.configure(state="normal" if ids and (index != 1 or len(ids) == 1) else "disabled")
        song = self.collector.get_song_by_id(ids[0]) if len(ids) == 1 else None
        self.cover_image = None
        self.lbl_cover.configure(image="", text="No cover selected")
        if song is None:
            self.detail_title.configure(text=f"{len(ids)} songs selected" if ids else "Select a song")
            self.detail_meta.configure(text="Play or remove the selected songs." if ids else "Browse your library to see details.")
            self.detail_file.configure(text="")
            return
        self.detail_title.configure(text=song.title)
        minutes, seconds = divmod(song.duration_seconds, 60)
        self.detail_meta.configure(text=f"{song.artist}\n\n{song.genre or 'No genre'}\n{minutes}:{seconds:02d}  ·  Rating {song.rating} / 5")
        audio = self.library.media.resolve(song.filepath, "audio")
        self.detail_file.configure(text=(PureWindowsPath(song.filepath).name + ("\nAudio file missing" if audio is None or not audio.is_file() else "")) if song.filepath else "No audio file linked")
        if not song.cover_path and audio is not None and audio.is_file():
            detected = extract_audio_metadata(audio, self._artwork_folders())
            try:
                cover = self._store_detected_cover(audio, detected)
            except OSError as error:
                messagebox.showerror("Artwork import", f"Could not save artwork.\n{error}", parent=self.root)
            else:
                if cover:
                    song.cover_path = cover
                    self._mark_changed()
        if song.cover_path:
            self.show_cover_image(song.cover_path)

    def _load_song_into_form(self, song: Song) -> None:
        for name, value in {
            "title": song.title,
            "artist": song.artist,
            "duration": str(song.duration_seconds),
            "genre": song.genre,
            "rating": str(song.rating),
            "filepath": song.filepath,
            "coverpath": song.cover_path,
        }.items():
            self._set_form_value(name, value)
        self._form_changes.clear()

    # ---------- playback ----------

    def play_selected(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("Play", "Please select at least one song.")
            return
        self._play_song_ids(ids)

    def play_all(self) -> None:
        songs = self.collector.list_songs()
        ids = [s.id for s in songs]
        if not ids:
            messagebox.showinfo("Play", "No songs in library.")
            return
        self._play_song_ids(ids)

    def play_random(self) -> None:
        songs = self.collector.list_songs()
        if not songs:
            messagebox.showinfo("Random", "No songs in library.")
            return
        song = random.choice(songs)
        if not song.filepath:
            messagebox.showinfo("Random", "Random song has no audio file.")
            return
        iid = str(song.id)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self.on_song_selected()
        audio = self.library.media.resolve(song.filepath, "audio")
        if audio is None or not audio.is_file():
            messagebox.showinfo("Play", "The linked audio file is missing.")
            return
        self._open_audio(str(audio))

    def _play_song_ids(self, ids: List[int]) -> None:
        paths: List[str] = []
        missing = 0
        for song_id in ids:
            song = self.collector.get_song_by_id(song_id)
            if not song or not song.filepath:
                missing += 1
                continue
            audio = self.library.media.resolve(song.filepath, "audio")
            if audio is not None and audio.is_file():
                paths.append(str(audio.resolve()))
            else:
                missing += 1

        if not paths:
            messagebox.showinfo("Play", "No valid audio files to play.")
            return

        if len(paths) == 1:
            self._open_audio(paths[0])
            return

        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".m3u", mode="w", encoding="utf-8-sig",
                newline="\n",
            ) as f:
                f.write("#EXTM3U\n")
                for p in paths:
                    f.write(p + "\n")
                playlist_path = f.name
            self._open_audio(playlist_path)
            if missing:
                self.var_status.set(
                    f"Playing {len(paths)} song(s) · {missing} missing or unlinked"
                )
        except OSError as e:
            messagebox.showerror("Play", f"Could not create playlist:\n{e}")

    def _open_audio(self, path: str) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except (OSError, AttributeError) as e:
            messagebox.showerror("Play", f"Cannot open file:\n{e}")

    # ---------- search / sort / stats ----------

    def smart_search(self) -> None:
        self.refresh_list()

    def apply_sort(self) -> None:
        self.collector.sort_songs(self.var_sort.get())
        self.refresh_list()

    def show_stats(self) -> None:
        stats = self.collector.genre_counts()
        if not stats:
            messagebox.showinfo("Statistics", "No songs in collection.")
            return
        lines = [f"{genre}: {count} song(s)" for genre, count in stats.items()]
        messagebox.showinfo("Genre statistics", "\n".join(lines))

    # ---------- save / load ----------

    def save_library(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Export library", parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not filename:
            return
        try:
            self.library.export(self.collector, filename)
            # An export is a copy; it must not hide a failed working-library save.
            if Path(filename).resolve() == self.library.path.resolve():
                self.dirty = False
            self.var_status.set(f"Exported · {Path(filename).name}" + (" · Working library still unsaved" if self.dirty else ""))
        except LIBRARY_ERRORS as error:
            messagebox.showerror("Export", f"Could not export library:\n{error}", parent=self.root)

    def load_library(self) -> None:
        if self.dirty and not messagebox.askyesno("Unsaved library", "Replace the current library and discard its unsaved changes? Export first to keep them.", parent=self.root):
            return
        filename = filedialog.askopenfilename(
            title="Import library", parent=self.root,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            candidate = self.library.read(filename, SongCollector)
        except LIBRARY_ERRORS as error:
            messagebox.showerror("Import", f"Could not import library. Your current songs have been kept.\n{error}", parent=self.root)
            return
        self.collector = candidate
        self.var_search.set("")
        self.tree.selection_remove(self.tree.selection())
        self.refresh_list()
        self._mark_changed()

    # ---------- cover & totals ----------

    def show_cover_image(self, path: str) -> None:
        try:
            resolved = self.library.media.resolve(path, "covers")
            if resolved is None:
                raise FileNotFoundError(path)
            with Image.open(resolved) as source:
                source.thumbnail((210, 210))
                self.cover_image = ImageTk.PhotoImage(source.copy(), master=self.root)
            self.lbl_cover.configure(image=self.cover_image, text="")
        except (OSError, ValueError, tk.TclError):
            self.lbl_cover.configure(text="Cover unavailable", image="")
            self.cover_image = None

    def update_total_duration_label(self, songs: List[Song]) -> None:
        total_sec = self.collector.total_duration(songs)
        minutes, seconds = divmod(total_sec, 60)
        hours, minutes = divmod(minutes, 60)
        self.var_total.set(
            f"Total: {len(songs)} song(s), {hours:d}:{minutes:02d}:{seconds:02d}"
        )


def main() -> None:
    ttk.utility.enable_high_dpi_awareness()
    root = tk.Tk()
    app = SongCollectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
