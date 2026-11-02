"""Project-local media references and safe JSON storage (no GUI dependencies)."""
from pathlib import Path, PureWindowsPath
import json
import os
import shutil
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parent
LIBRARY_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError)


def atomic_write_json(filename, data):
    """Keep the previous file intact unless the complete new file can replace it."""
    target = Path(filename)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class MediaPaths:
    def __init__(self, project_root=PROJECT_ROOT):
        self.root = Path(project_root).resolve()

    def folder(self, kind):
        if kind not in ("audio", "covers"):
            raise ValueError("Media kind must be audio or covers.")
        return self.root / "media" / kind

    def reference(self, path):
        """Store internal files relative to the project, external links absolute."""
        path = Path(path).resolve()
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def resolve(self, value, kind, source_dir=None):
        """Resolve references independently of cwd, including obsolete Windows paths.

        Filename recovery is restricted to absolute legacy paths and known media
        folders. Missing relative references keep their intended location.
        """
        if not value:
            return None
        windows = PureWindowsPath(value)
        path = Path(value.replace("\\", "/"))
        absolute = path.is_absolute() or bool(windows.drive) or windows.is_absolute()
        foreign_windows = bool(windows.drive) and os.name != "nt"
        candidate = path if path.is_absolute() else self.root / path
        if not foreign_windows and candidate.is_file():
            return candidate.resolve()
        if not absolute and source_dir is not None:
            imported = Path(source_dir) / path
            if imported.is_file():
                return imported.resolve()
        if absolute:
            # PureWindowsPath handles both slash styles even on other platforms.
            name = windows.name.casefold()
            for folder in (self.root, self.folder(kind)):
                if folder.is_dir():
                    matches = [p for p in folder.iterdir() if p.is_file() and p.name.casefold() == name]
                    if len(matches) == 1:
                        return matches[0].resolve()
        return None if foreign_windows else candidate

    def normalize(self, value, kind, source_dir=None):
        if not value:
            return ""
        path = self.resolve(value, kind, source_dir)
        # Retain missing links rather than discarding a user's path information.
        return self.reference(path) if path is not None and path.is_file() else value

    def copy_asset(self, filename, kind):
        """Copy an external asset without ever overwriting an existing filename."""
        source = Path(filename).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Media file is missing: {source}")
        try:
            source.relative_to(self.root)
            return self.reference(source)
        except ValueError:
            pass
        folder = self.folder(kind)
        folder.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            name = source.name if number == 1 else f"{source.stem} ({number}){source.suffix}"
            target = folder / name
            if any(p.name.casefold() == name.casefold() for p in folder.iterdir()):
                number += 1
                continue
            try:
                destination = target.open("xb")  # exclusive creation also handles races
            except FileExistsError:
                number += 1
                continue
            try:
                with destination, source.open("rb") as original:
                    shutil.copyfileobj(original, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
            except OSError:
                target.unlink(missing_ok=True)  # only our incomplete copy
                raise
            return self.reference(target)


class WorkingLibrary:
    """Own the working location while leaving SongCollector's schema unchanged."""
    def __init__(self, project_root=PROJECT_ROOT):
        self.media = MediaPaths(project_root)
        self.path = self.media.root / "data" / "library.json"
        self.original = self.media.root / "My Favourite Library.json"
        self.blocked = True
        self.loaded_collector = None

    def read(self, filename, collector_type):
        candidate = collector_type()
        candidate.load_from_file(filename)
        for song in candidate.list_songs():
            song.filepath = self.media.normalize(song.filepath, "audio", Path(filename).resolve().parent)
            song.cover_path = self.media.normalize(song.cover_path, "covers", Path(filename).resolve().parent)
        return candidate

    def startup(self, collector_type):
        # A failed read must never enable saving an empty replacement library.
        self.blocked = True
        self.loaded_collector = None
        if self.path.exists():
            collector = self.read(self.path, collector_type)
        elif self.original.exists():
            collector = self.read(self.original, collector_type)
        else:
            collector = collector_type()
        self.loaded_collector = collector
        for kind in ("audio", "covers"):
            self.media.folder(kind).mkdir(parents=True, exist_ok=True)
        self.blocked = False
        if not self.path.exists():
            self.save(collector)
        return collector

    def save(self, collector):
        if self.blocked:
            raise OSError("Automatic saving is paused after a startup error. Repair or back up the unreadable library and restart. You can export your current songs to another JSON file.")
        collector.save_to_file(self.path)

    def export(self, collector, filename):
        target = Path(filename).resolve()
        if target == self.original.resolve():
            raise ValueError("The original My Favourite Library.json is protected. Choose a different export filename.")
        if target == self.path.resolve():
            self.save(collector)
        else:
            if target.suffix.lower() != ".json":
                raise ValueError("Choose a .json export filename.")
            collector.save_to_file(target)
