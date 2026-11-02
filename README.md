# Smart Song Collector & Playlist Manager

A local Windows desktop music library built with Python and Tkinter. Phase 1 modernized the GUI; Phase 2 adds project-local media references, automatic loading, and safe automatic saving; Phase 3 adds local Mutagen metadata and artwork extraction while retaining the Song / SongCollector model and JSON library format. Playlist creation and management are outside this phase.

## Setup and run (PowerShell)

Use Python 3.10 or newer with Tkinter installed. Python 3.13 was used for verification.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe song_collector_gui.py
```

If Python is not on PATH, use `py` instead of `python`. In the development workspace, Python was installed locally with uv:

```powershell
uv --cache-dir .uv-cache python install 3.13 --install-dir .python
uv --cache-dir .uv-cache venv --python .python/cpython-3.13.14-windows-x86_64-none/python.exe .venv
uv --cache-dir .uv-cache pip install --python .venv/Scripts/python.exe -r requirements.txt
```

Dependencies are pinned in `requirements.txt`: ttkbootstrap 1.20.4 provides modern ttk widgets and themes; Pillow 12.3.0 (also required by ttkbootstrap) resizes cover previews without distorting their proportions; Mutagen 1.47.0 reads local audio tags and embedded MP3 artwork. There are no network services or music downloads. See the [ttkbootstrap theme documentation](https://www.ttkbootstrap.org/en/latest/themes.html).

## Using the library

- The sidebar opens the library, displays genre counts, imports/exports JSON, and switches appearance. Only implemented actions are shown.
- Add songs with **Add song**. Edit a single selection with **Edit song** or by double-clicking its row. Choosing an audio file reads local title, artist, genre, duration, nearby JPEG/PNG artwork, and embedded MP3 APIC artwork. Missing tags produce filename suggestions. Manual fields and existing saved metadata are preserved automatically; selecting audio fills only eligible untouched fields. Rating stays manual. Title and artist are required; enter a non-negative integer duration in seconds and an integer rating from 1 to 5. Audio and cover paths are optional.
- Search title/artist words using **Search** or Enter. This retains the existing whole-word similarity search, so partial words such as `danc` do not match `Dancing`. Clear restores the full collection. Sorting preserves the active search; rating sorts highest first, duration shortest first.
- Use Ctrl/Shift selection for several rows. Play selected, play all, or choose a random song. Playback uses the Windows default player; multiple files are passed through a temporary M3U as before. Player support determines queue behavior.
- The inspector shows the selected song, a bounded cover preview, and audio-file availability. Common Pillow image formats work; PNG remains supported.
- Removing songs only removes their library records. It never deletes audio or cover files.
- The app automatically opens `data/library.json` at startup and saves after successful add, edit, delete, and JSON import operations. The footer reports success or unsaved changes.
- On first startup, if the working file does not exist, the bundled `My Favourite Library.json` is imported. Old absolute Windows paths are matched by filename to existing root media, with IDs, metadata, and the next ID retained. The original JSON and root media are never rewritten or moved. If neither JSON exists, an empty working library is created.
- **Import library…** replaces the displayed collection and automatically saves it to the working file. It does not modify the source JSON. Failed imports keep the current collection. If there are unsaved changes after a save failure, replacing them requires confirmation.
- **Export library…** writes a JSON copy to a chosen filename. Exporting never changes the working location. An export cannot overwrite the original `My Favourite Library.json` or use a non-JSON filename. Exporting a recovery copy does not hide a failed working save.
- Browsing external audio or covers automatically copies them into `media/audio` or `media/covers`, without a copy-or-link popup. Identical existing local copies are reused after a byte comparison. Name collisions use `name (2).ext`, `name (3).ext`, etc.; existing files and originals are kept. Files already in the project are referenced in place. Copying occurs when browsing; cancelling the song dialog afterwards leaves the copy in place.
- Startup persists verified local path repairs. Legacy Windows basenames are checked across the project root and the appropriate media folder together; ambiguous or missing matches keep their original reference. No existing library is replaced with the bundled sample.
- Artwork detection first reads embedded MP3 APIC pictures (front cover preferred), independently of audio-tag/duration parsing. Valid JPG/PNG sidecars with matching track names come next, followed by unambiguous `cover.jpg` / `folder.jpg` equivalents. Project media folders are searched too. Artwork is validated with Pillow, saved locally, and reused without overwriting files. A manually selected cover is never replaced; missing artwork shows the existing clean placeholder.
- Missing media keeps its path and metadata. The inspector shows missing audio and unavailable cover images; use Edit to reconnect files.

Keyboard: Ctrl+N adds, Ctrl+F focuses search, Ctrl+S exports, Ctrl+O imports; Delete removes selected table rows with confirmation. Escape cancels an add/edit dialog; Ctrl+Enter submits it. Tab moves through controls.

## Design and implementation

The default dark palette uses background `#171D24`, surface `#252E38`, accent `#E8A06C`, and text `#F0F2F4`. Light appearance uses `#F6F5F2`, `#FFFFFF`, `#B86B3F`, and `#232A32`. Typography uses Segoe UI with Semibold headings.

A compact sidebar, resizable center table, and right-hand song inspector replace the permanent input form. The window supports 1040×680 and larger; horizontal/vertical table scrollbars keep columns accessible at smaller widths. The inspector scrolls vertically to accommodate longer song details and Windows display scaling. Add/edit is a modal dialog. Treeview row IDs map directly to model IDs, so punctuation in song titles cannot break selection.

SongCollector retains CRUD, search, sorting, statistics, and persistence. Validation rejects malformed records and duplicate IDs before replacing the current library; invalid edits leave the original song untouched. JSON keys and file structure are unchanged.

`media_library.py` handles project paths and storage. `Path(__file__).resolve().parent` anchors the project, independent of the launch directory. `PureWindowsPath` extracts old filenames from either Windows slash style. Internal references use forward-slash relative paths; external links remain absolute. Manual imports first resolve relative references against this project, then fall back to the imported JSON's folder. Exports contain references, not copies of media; when moving to another computer, transfer the project media as well.

Saves serialize into a uniquely named temporary file in the destination directory, flush and sync it, then use `os.replace`. A failed write/replacement leaves the previous JSON intact and reports the error; edits remain in memory. Closing with unsaved changes retries saving and asks before discarding them if it still fails. Atomic replacement depends on the filesystem; keep separate exports for backups. This phase does not add multi-instance locking, so use one running app per project.

If startup finds corrupt or unreadable JSON, it reports an error and pauses automatic saving for that session. It does not fall back to the bundled library or overwrite the corrupt file with an empty collection. You can export new/recovered songs under a different JSON filename. To recover, close the app, **copy the unreadable file somewhere safe**, repair the working JSON or explicitly restore a known-good export, then restart. If only the legacy JSON exists and is corrupt, fix or back up that source before retrying first-start migration.

Precise Git ignore rules cover `/data/library.json`, its atomic-save temporary files, and newly imported contents of `/media/audio` and `/media/covers`. Placeholder files keep those directories in the repository. Already-tracked root MP3/PNG files and the original JSON remain tracked. Exports saved elsewhere in the repository are not automatically ignored; prefer an external backup folder.

## Verification

```powershell
.venv\Scripts\python.exe -m py_compile song_collector_gui.py media_library.py
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s tests -p gui_checks.py -v
```

The default suite has **34 tests** for the model, storage and metadata extraction, including migration of the eight-song fixture, Windows/relative paths, missing files, import/ID preservation, copying/collisions, corrupt JSON, and failed atomic replacement. The explicit GUI suite has **20 checks** covering the existing layout, metadata/manual-cover preservation, automatic media copying and the full autosave/import/recovery paths, real working-directory changes, media browsing choices, and relative cover/playback resolution. The GUI checks require a graphical Windows session. All test-library writes use temporary directories, and playback is mocked.

Verification also migrated the actual repository's eight-song library: all 16 relative audio/cover paths resolved. SHA-256 hashes confirmed that the original JSON and all 16 root media files were unchanged. `git check-ignore` confirmed that working data and imported media are ignored.

## Manual Phase 2 checks

1. From the project folder, run `.venv\Scripts\python.exe song_collector_gui.py`. Your current saved songs should appear without importing anything; startup never resets an existing library to the eight-song sample. Select each song: its cover should display and audio should play in your default Windows player. `data/library.json` should contain root-relative media filenames, IDs 1–8, and `next_id` 9 on the initial migration.
2. Add a song called `Phase 2 test` with artist `Test`, duration `10`, rating `3`, and no media. Check for the automatically-saved footer. Close and reopen: it should still exist. Edit its rating to `4`, reopen again, then remove it and reopen once more. Each operation should persist without exporting.
3. Add a test song and Browse to an audio file **outside the repository**. The file should copy automatically without a popup. Repeat for an external PNG/JPG cover. Check that copies exist under `media/audio` and `media/covers`, that original files still exist, and that the JSON uses relative paths. Select the same external filename again to check that an existing copy is not overwritten. Selecting the same file again should reuse the existing copy. Cancel the native file picker to leave the field unchanged. Check embedded artwork or matching sidecars, then manually select another cover and browse audio again: your manual cover should stay selected.
4. Export to a new JSON file **outside the repository**, then import that export. Song IDs, ratings, genres, and durations should match. Try importing a separate malformed JSON file: an error should appear and the current songs should stay unchanged. A failed working save must leave an unsaved warning even after a recovery export.
5. Edit only the test song's audio path to `media/audio/does-not-exist.mp3` and its cover path to `media/covers/does-not-exist.png`. The inspector should report missing/unavailable media and playback should give a useful message. The song must remain after reopening. Remove this test record when done.
6. Verify launch-directory independence with the following commands from the project folder. Check covers and playback again:

```powershell
$project = (Get-Location).Path
Push-Location $env:TEMP
try {
    & "$project\.venv\Scripts\python.exe" "$project\song_collector_gui.py"
} finally {
    Pop-Location
}
```

For a manual **corrupt-startup check**, use an isolated disposable copy rather than damaging your working library. Run this from the project folder:

```powershell
$project = (Get-Location).Path
$trial = Join-Path $env:TEMP ("SongCollector-trial-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $trial | Out-Null
Copy-Item -LiteralPath .\song_collector_gui.py,.\media_library.py,.\metadata_extractor.py -Destination $trial
New-Item -ItemType Directory -Path (Join-Path $trial 'data') | Out-Null
Set-Content -LiteralPath (Join-Path $trial 'data/library.json') -Value '{broken' -Encoding UTF8
& "$project\.venv\Scripts\python.exe" (Join-Path $trial 'song_collector_gui.py')
Get-Content -LiteralPath (Join-Path $trial 'data/library.json')
```

Expect a startup error. Add a test record: an autosave error should appear while the record remains visible. Export a recovery JSON to another filename. Closing should warn about unsaved changes, and the final `Get-Content` should still show `{broken`. Your real project library is unaffected.

## Author

Peter Shehata · Electrical Engineering Student · Brno University of Technology

Original academic result: 30/30.
