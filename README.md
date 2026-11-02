# Smart Song Collector & Playlist Manager

A local Windows desktop music library built with Python and Tkinter. Phase 1 modernizes the GUI while retaining the existing Song / SongCollector model and JSON library format. Playlist creation and management are outside this phase.

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

Dependencies are pinned in `requirements.txt`: ttkbootstrap 1.20.4 provides modern ttk widgets and themes; Pillow 12.3.0 (also required by ttkbootstrap) resizes cover previews without distorting their proportions. There are no network services or music downloads. See the [ttkbootstrap theme documentation](https://www.ttkbootstrap.org/en/latest/themes.html).

## Using the library

- The sidebar opens the library, displays genre counts, saves/loads JSON, and switches appearance. Only implemented actions are shown.
- Add songs with **Add song**. Edit a single selection with **Edit song** or by double-clicking its row. Title and artist are required; enter a non-negative integer duration in seconds and an integer rating from 1 to 5. Audio and cover paths are optional.
- Search title/artist words using **Search** or Enter. This retains the existing whole-word similarity search, so partial words such as `danc` do not match `Dancing`. Clear restores the full collection. Sorting preserves the active search; rating sorts highest first, duration shortest first.
- Use Ctrl/Shift selection for several rows. Play selected, play all, or choose a random song. Playback uses the Windows default player; multiple files are passed through a temporary M3U as before. Player support determines queue behavior.
- The inspector shows the selected song, a bounded cover preview, and audio-file availability. Common Pillow image formats work; PNG remains supported.
- Removing songs only removes their library records. It never deletes audio or cover files.
- Save/load is manual. An unsaved-changes indicator and confirmation before replacing/closing the library help prevent accidental loss. Save a copy under a new JSON filename to retain the original library.
- The bundled `My Favourite Library.json` uses absolute paths from an older directory. Load it to see the metadata, then edit/browse to reconnect audio and covers if needed. The application does not rewrite these paths automatically.

Keyboard: Ctrl+N adds, Ctrl+F focuses search, Ctrl+S saves, Ctrl+O loads; Delete removes selected table rows with confirmation. Escape cancels an add/edit dialog; Ctrl+Enter submits it. Tab moves through controls.

## Design and implementation

The default dark palette uses background `#171D24`, surface `#252E38`, accent `#E8A06C`, and text `#F0F2F4`. Light appearance uses `#F6F5F2`, `#FFFFFF`, `#B86B3F`, and `#232A32`. Typography uses Segoe UI with Semibold headings.

A compact sidebar, resizable center table, and right-hand song inspector replace the permanent input form. The window supports 1040×680 and larger; horizontal/vertical table scrollbars keep columns accessible at smaller widths. The inspector scrolls vertically to accommodate longer song details and Windows display scaling. Add/edit is a modal dialog. Treeview row IDs map directly to model IDs, so punctuation in song titles cannot break selection.

SongCollector retains CRUD, search, sorting, statistics, and persistence. Small validation changes reject malformed records and duplicate IDs before replacing the current library; invalid edits also leave the original song untouched. JSON keys and file structure are unchanged.

## Verification

```powershell
.venv\Scripts\python.exe -m py_compile song_collector_gui.py
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s tests -p gui_checks.py -v
```

The first test suite checks the model, all sort modes, smart search, statistics, CRUD/IDs, unchanged JSON structure, successful round trips, failed-load safety, and the bundled library. The second opens Tk windows and requires a graphical Windows session; it checks add/edit/cancel, validation, filtering, selection, removal, theme/resize behavior, cover sizing, and mocked playback handoff. Tests write only to temporary folders; real music playback is not invoked.

Manual checks before everyday use:

1. Inspect both appearances at your Windows display scaling (100%, 125%, 150%, or higher), including focus outlines, dropdowns, long titles, and the add/edit dialog.
2. Browse to real audio/cover files, test an unreadable/missing file, and listen using Play selected, Play all, and Random in your chosen default player.
3. Save a test library under a new filename, load it back, and verify the close/load unsaved-change confirmations and overwrite behavior in native file dialogs.
4. Check Tab navigation, Ctrl/Shift multi-selection, search with Enter, dialog Escape/Ctrl+Enter, and genre statistics.

## Author

Peter Shehata · Electrical Engineering Student · Brno University of Technology

Original academic result: 30/30.
