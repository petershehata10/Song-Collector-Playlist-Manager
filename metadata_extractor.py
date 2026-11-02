"""Safe, local audio metadata and artwork extraction."""

from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
from PIL import Image
import re
from typing import Any

from mutagen import File as MutagenFile, MutagenError
from mutagen.id3 import ID3, ID3NoHeaderError


@dataclass(frozen=True)
class AudioMetadata:
    title: str = ""
    artist: str = ""
    genre: str = ""
    duration_seconds: int | None = None
    cover_path: str = ""
    artwork: bytes | None = None
    artwork_extension: str = ".jpg"
    error: str = ""


def _first_text(tags: Any, keys: tuple[str, ...]) -> str:
    if tags is None:
        return ""
    for key in keys:
        value = tags.get(key)
        if value:
            if isinstance(value, list):
                value = value[0]
            return str(value).strip()
    return ""


def _filename_suggestion(path: Path) -> tuple[str, str]:
    stem = re.sub(r"[_]+", " ", path.stem).strip()
    parts = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip()
    return stem, ""


def _cover_key(name: str) -> str:
    name = re.sub(r"\((?:official[^)]*|music video|lyrics?|audio)\)", "", name, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def _valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
            return image.format in ("JPEG", "PNG")
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def _sidecar_cover(path: Path, search_folders=(), title="", artist="") -> str:
    folders = list(dict.fromkeys([path.parent.resolve(), *(Path(p).resolve() for p in search_folders)]))
    images = {image.resolve() for folder in folders if folder.is_dir()
              for image in folder.iterdir()
              if image.is_file() and image.suffix.casefold() in (".jpg", ".jpeg", ".png")}
    keys = {_cover_key(path.stem)}
    if title:
        keys.add(_cover_key(title))
        if artist:
            keys.add(_cover_key(artist + title))
    def unique_artwork(matches):
        # The sidecar beside an external file and its imported copy may both
        # appear on a repeated selection. Identical bytes are the same artwork.
        if len(matches) == 1 or len({image.read_bytes() for image in matches}) == 1:
            return str(sorted(matches)[0])
        return ""

    matches = [image for image in images if _cover_key(image.stem) in keys and _valid_image(image)]
    if matches:
        return unique_artwork(matches)
    # Generic covers are album-level hints: prefer the audio's own directory,
    # and never pick one of several cover/folder images at the same priority.
    for group in ([path.parent.resolve()], folders[1:]):
        matches = [image for image in images if image.parent in group
                   and image.stem.casefold() in ("cover", "folder") and _valid_image(image)]
        if matches:
            return unique_artwork(matches)
    return ""


def _embedded_artwork(path: Path) -> tuple[bytes | None, str]:
    if path.suffix.casefold() != ".mp3":
        return None, ".jpg"
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return None, ".jpg"
    for frame in sorted(tags.getall("APIC"), key=lambda frame: frame.type != 3):
        data = getattr(frame, "data", None)
        if not data:
            continue
        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
                if image.format in ("PNG", "JPEG"):
                    return data, ".png" if image.format == "PNG" else ".jpg"
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    return None, ".jpg"


def extract_audio_metadata(filename: str | Path, search_folders=()) -> AudioMetadata:
    """Read tags and artwork independently; audio is always opened read-only."""
    path = Path(filename)
    title, artist = _filename_suggestion(path)
    result = {"title": title, "artist": artist}
    errors = []
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            tags = getattr(audio, "tags", None)
            result["title"] = _first_text(tags, ("title",)) or title
            result["artist"] = _first_text(tags, ("artist",)) or artist
            result["genre"] = _first_text(tags, ("genre",))
            length = getattr(getattr(audio, "info", None), "length", None)
            result["duration_seconds"] = int(round(length)) if length is not None else None
    except (OSError, ValueError, TypeError, MutagenError) as error:
        errors.append(str(error))
    artwork, extension = None, ".jpg"
    try:
        artwork, extension = _embedded_artwork(path)
    except (OSError, ValueError, MutagenError) as error:
        errors.append(str(error))
    cover = "" if artwork else _sidecar_cover(path, search_folders, result["title"], result["artist"])
    return AudioMetadata(**result, artwork=artwork, artwork_extension=extension,
                         cover_path=cover, error="; ".join(errors))


def save_embedded_artwork(data: bytes, extension: str, destination: str | Path, stem: str) -> Path:
    """Reuse identical artwork; exclusive creation never overwrites an image."""
    with Image.open(BytesIO(data)) as image:
        image.verify()
        if image.format not in ("JPEG", "PNG"):
            raise ValueError("Embedded artwork must be a JPEG or PNG image.")
        suffix = ".png" if image.format == "PNG" else ".jpg"
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    for existing in sorted(folder.iterdir()):
        if existing.is_file() and existing.suffix.casefold() in (".png", ".jpg", ".jpeg") and existing.read_bytes() == data:
            return existing
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "cover"
    number = 1
    while True:
        name = f"{safe_stem}{suffix}" if number == 1 else f"{safe_stem} ({number}){suffix}"
        target = folder / name
        try:
            with target.open("xb") as stream:
                stream.write(data)
            return target
        except FileExistsError:
            number += 1
