"""GUI integration checks. Run explicitly on a Windows graphical desktop."""
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from song_collector_gui import SongCollector, SongCollectorApp
from media_library import WorkingLibrary


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # ttkbootstrap owns one Style per process, matching the real app lifecycle.
        from ttkbootstrap.utility import enable_high_dpi_awareness
        enable_high_dpi_awareness()
        cls.root = tk.Tk()
        cls.project = tempfile.TemporaryDirectory()
        cls.app = SongCollectorApp(cls.root, project_root=Path(cls.project.name))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.project.cleanup()

    def setUp(self):
        self.app._close_dialog()
        self.app.collector = SongCollector()
        self.app.var_search.set("")
        self.app.var_sort.set("Title")
        self.app.dirty = False
        self.app.refresh_list()
        self.root.update()

    def add_song(self, title='A title', artist='An artist'):
        song = self.app.collector.add_song(title, artist, 125, 'Pop', 4, '', '')
        self.app.refresh_list()
        self.root.update()
        return song

    def test_empty_theme_and_resize(self):
        self.assertTrue(self.app.empty.winfo_ismapped())
        for width, height in ((1040, 680), (1600, 900)):
            self.root.geometry(f'{width}x{height}')
            self.app.toggle_theme()
            self.root.update()
            self.assertGreater(self.app.tree.winfo_width(), 200)
            self.assertEqual(self.app.style.lookup('Library.Treeview', 'fieldbackground'), self.app.PALETTES[self.app.dark_mode]['surface'])

    def test_dialog_add_edit_and_validation(self):
        self.app.open_song_dialog()
        self.app.var_title.set('Song with [brackets]')
        self.app.var_artist.set('Artist')
        self.app.var_duration.set('bad')
        with patch('song_collector_gui.messagebox.showwarning') as warning:
            self.app.add_song()
            warning.assert_called_once()
        self.assertIsNotNone(self.app.dialog)
        self.app.var_duration.set('125')
        self.app.add_song()
        self.root.update()
        self.assertIsNone(self.app.dialog)
        song = self.app.collector.list_songs()[0]
        self.assertEqual(self.app._get_selected_ids(), [song.id])
        self.app.open_song_dialog(edit=True)
        self.app.var_title.set('Edited')
        self.app.update_selected_song()
        self.root.update()
        self.assertEqual(song.title, 'Edited')
        self.assertEqual(self.app.detail_title.cget('text'), 'Edited')
        self.assertFalse(self.app.dirty)
        reopened = self.app.library.read(self.app.library.path, SongCollector)
        self.assertEqual(reopened.get_song_by_id(song.id).title, 'Edited')

    def test_filter_sort_selection_and_delete(self):
        first = self.add_song('Zulu', 'ABBA')
        second = self.add_song('Alpha', 'Adele')
        self.app.var_search.set('ABBA')
        self.app.smart_search()
        self.app.var_sort.set('Newest')
        self.app.apply_sort()
        self.assertEqual(self.app.tree.get_children(), (str(first.id),))
        self.app.var_search.set('missing')
        self.app.smart_search()
        self.root.update()
        self.assertTrue(self.app.empty.winfo_ismapped())
        self.app.show_all()
        self.app.tree.selection_set(str(second.id))
        with patch('song_collector_gui.messagebox.askyesno', return_value=True):
            self.app.delete_selected()
        self.assertEqual(self.app.collector.list_songs(), [first])

    def test_cover_is_bounded_and_missing_cover_clears(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.png'
            Image.new('RGB', (1200, 600), 'orange').save(path)
            self.app.show_cover_image(str(path))
            self.assertEqual(self.app.cover_image.width(), 210)
            self.assertEqual(self.app.cover_image.height(), 105)
            self.app.show_cover_image(str(Path(folder) / 'absent.png'))
            self.assertIsNone(self.app.cover_image)

    def test_playback_delegates_to_default_player(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.mp3'
            path.touch()
            song = self.add_song()
            song.filepath = str(path)
            self.app.tree.selection_set(str(song.id))
            with patch('song_collector_gui.os.startfile', create=True) as player:
                self.app.play_selected()
                player.assert_called_once_with(str(path))

    def test_manual_save_load_and_unsaved_cancel(self):
        song = self.add_song()
        self.app._mark_changed()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'library.json')
            with patch('song_collector_gui.filedialog.asksaveasfilename', return_value=path):
                self.app.save_library()
            self.assertFalse(self.app.dirty)
            self.app.collector.remove_song_by_id(song.id)
            self.app.dirty = True  # simulate changes retained after a failed autosave
            with patch('song_collector_gui.messagebox.askyesno', return_value=False), patch('song_collector_gui.filedialog.askopenfilename') as picker:
                self.app.load_library()
                picker.assert_not_called()
            self.assertTrue(self.app.dirty)
            with patch('song_collector_gui.messagebox.askyesno', return_value=True), patch('song_collector_gui.filedialog.askopenfilename', return_value=path):
                self.app.load_library()
            self.assertFalse(self.app.dirty)
            self.assertEqual(self.app.collector.list_songs()[0].title, song.title)

    def test_genre_statistics(self):
        self.add_song()
        with patch('song_collector_gui.messagebox.showinfo') as info:
            self.app.show_stats()
            self.assertIn('Pop: 1', info.call_args.args[1])

    def test_autosave_failure_keeps_edits_dirty_and_reports_error(self):
        self.app.library.save(self.app.collector)
        before = self.app.library.path.read_bytes()
        self.app.open_song_dialog()
        self.app.var_title.set('Retained after failure')
        self.app.var_artist.set('Artist')
        with patch('media_library.os.replace', side_effect=PermissionError('locked')), patch('song_collector_gui.messagebox.showerror') as error:
            self.app.add_song()
            error.assert_called_once()
        self.assertTrue(self.app.dirty)
        self.assertEqual(self.app.collector.list_songs()[0].title, 'Retained after failure')
        self.assertEqual(self.app.library.path.read_bytes(), before)
        self.assertTrue(self.app._autosave())
        self.assertFalse(self.app.dirty)

    def test_delete_is_automatically_saved(self):
        song = self.add_song()
        self.app._mark_changed()
        self.app.tree.selection_set(str(song.id))
        with patch('song_collector_gui.messagebox.askyesno', return_value=True):
            self.app.delete_selected()
        reopened = self.app.library.read(self.app.library.path, SongCollector)
        self.assertEqual(reopened.list_songs(), [])
        self.assertFalse(self.app.dirty)

    def test_browse_external_automatically_copies_and_reuses(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'external.mp3'
            source.write_bytes(b'original audio')
            self.app.open_song_dialog()
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(source)), patch('song_collector_gui.messagebox.askyesnocancel') as popup, patch('song_collector_gui.messagebox.showwarning') as warning:
                self.app.browse_audio()
                reference = self.app.var_filepath.get()
                self.app.browse_audio()
                popup.assert_not_called()
                warning.assert_not_called()
            self.assertEqual(self.app.var_filepath.get(), reference)
            self.assertTrue(reference.startswith('media/audio/'))
            self.assertEqual((self.app.library.media.root / reference).read_bytes(), source.read_bytes())
            self.assertTrue(source.exists())
            self.app._close_dialog()

    def test_relative_playback_and_cover_preview_from_other_directory(self):
        import os
        project = self.app.library.media.root
        audio = project / 'relative.mp3'
        audio.touch()
        cover = project / 'relative.png'
        Image.new('RGB', (20, 20), 'orange').save(cover)
        song = self.add_song()
        song.filepath = 'relative.mp3'
        song.cover_path = 'relative.png'
        self.app.tree.selection_set(str(song.id))
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                self.app.on_song_selected()
                self.assertIsNotNone(self.app.cover_image)
                with patch('song_collector_gui.os.startfile', create=True) as player:
                    self.app.play_selected()
                    player.assert_called_once_with(str(audio))
            finally:
                os.chdir(previous)

    def test_invalid_import_preserves_current_songs_and_disk(self):
        song = self.add_song()
        self.app._mark_changed()
        before = self.app.library.path.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / 'bad.json'
            bad.write_text('{broken', encoding='utf-8')
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(bad)), patch('song_collector_gui.messagebox.showerror') as error:
                self.app.load_library()
                error.assert_called_once()
            self.assertEqual(self.app.collector.list_songs(), [song])
            self.assertEqual(self.app.library.path.read_bytes(), before)

    def test_export_after_save_failure_does_not_hide_unsaved_state(self):
        self.add_song()
        self.app.dirty = True
        with tempfile.TemporaryDirectory() as folder:
            export = Path(folder) / 'rescue.json'
            with patch('song_collector_gui.filedialog.asksaveasfilename', return_value=str(export)):
                self.app.save_library()
            self.assertTrue(export.exists())
            self.assertTrue(self.app.dirty)

    def test_startup_reopens_automatically_saved_songs(self):
        song = self.add_song('Reopened title', 'Artist')
        self.app._mark_changed()
        self.app.collector = SongCollector()
        self.app._load_working_library()
        self.assertEqual(self.app.collector.get_song_by_id(song.id).title, 'Reopened title')

    def test_corrupt_startup_pauses_writes_and_preserves_file(self):
        previous_store = self.app.library
        with tempfile.TemporaryDirectory() as folder:
            store = WorkingLibrary(folder)
            store.path.parent.mkdir()
            store.path.write_bytes(b'{corrupt')
            try:
                self.app.library = store
                self.app.collector = SongCollector()
                with patch('song_collector_gui.messagebox.showerror') as error:
                    self.app._load_working_library()
                    error.assert_called_once()
                    self.app.collector.add_song('Recovery', 'Artist', 1, '', 1, '', '')
                    self.app._mark_changed()
                self.assertTrue(self.app.dirty)
                self.assertTrue(store.blocked)
                self.assertEqual(store.path.read_bytes(), b'{corrupt')
            finally:
                self.app.library = previous_store

    def test_first_startup_save_failure_retains_migrated_songs_for_retry(self):
        previous_store = self.app.library
        with tempfile.TemporaryDirectory() as folder:
            store = WorkingLibrary(folder)
            sample = Path(__file__).resolve().parents[1] / 'My Favourite Library.json'
            store.original.write_bytes(sample.read_bytes())
            try:
                self.app.library = store
                self.app.collector = SongCollector()
                with patch('media_library.os.replace', side_effect=PermissionError('locked')), patch('song_collector_gui.messagebox.showerror'):
                    self.app._load_working_library()
                self.assertTrue(self.app.dirty)
                self.assertEqual(len(self.app.collector.list_songs()), 8)
                self.assertFalse(store.path.exists())
                self.assertTrue(self.app._autosave())
                self.assertEqual(len(store.read(store.path, SongCollector).list_songs()), 8)
            finally:
                self.app.library = previous_store

    def test_cancel_edit_keeps_original(self):
        song = self.add_song()
        self.app.tree.selection_set(str(song.id))
        self.app.open_song_dialog(edit=True)
        self.app.var_title.set('Cancelled')
        self.app._close_dialog()
        self.assertEqual(song.title, 'A title')

    def test_autofill_keeps_manual_fields_rating_and_existing_edit_metadata(self):
        from metadata_extractor import AudioMetadata
        self.app.open_song_dialog()
        self.app.var_title.set('Manual title')
        self.app.var_genre.set('Manual genre')
        self.app.var_rating.set('5')
        detected = AudioMetadata(title='Detected', artist='Detected artist', duration_seconds=99, genre='Detected genre')
        with patch('song_collector_gui.messagebox.askyesno') as popup:
            self.app._apply_detected_metadata(detected, '')
            popup.assert_not_called()
        self.assertEqual(self.app.var_title.get(), 'Manual title')
        self.assertEqual(self.app.var_artist.get(), 'Detected artist')
        self.assertEqual(self.app.var_duration.get(), '99')
        self.assertEqual(self.app.var_genre.get(), 'Manual genre')
        self.assertEqual(self.app.var_rating.get(), '5')
        self.app._close_dialog()
        song = self.add_song('Saved title', 'Saved artist')
        self.app.tree.selection_set(str(song.id))
        self.app.open_song_dialog(edit=True)
        self.app._apply_detected_metadata(detected, '')
        self.assertEqual(self.app.var_title.get(), 'Saved title')
        self.assertEqual(self.app.var_artist.get(), 'Saved artist')
        self.app._close_dialog()

    def test_sidecar_is_copied_and_saved_while_manual_cover_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'Unique - Track.mp3'
            audio.write_bytes(b'audio without tags')
            cover = root / 'Unique - Track.png'
            Image.new('RGB', (20, 20), 'magenta').save(cover)
            self.app.open_song_dialog()
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(audio)):
                self.app.browse_audio()
            automatic = self.app.var_coverpath.get()
            self.assertTrue(automatic.startswith('media/covers/'))
            self.assertIsNotNone(self.app.form_cover_image)
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(audio)):
                self.app.browse_audio()
            self.assertEqual(self.app.var_coverpath.get(), automatic)
            manual = root / 'manual.png'
            Image.new('RGB', (20, 20), 'blue').save(manual)
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(manual)):
                self.app.browse_cover()
            selected = self.app.var_coverpath.get()
            with patch('song_collector_gui.filedialog.askopenfilename', return_value=str(audio)):
                self.app.browse_audio()
            self.assertEqual(self.app.var_coverpath.get(), selected)
            self.app.var_duration.set('10')
            self.app.add_song()
            reopened = self.app.library.read(self.app.library.path, SongCollector)
            self.assertEqual(reopened.list_songs()[0].cover_path, selected)
            self.assertEqual(audio.read_bytes(), b'audio without tags')

    def test_existing_song_without_cover_gets_local_artwork_without_metadata_changes(self):
        audio = self.app.library.media.root / 'Existing Artwork Song.mp3'
        audio.write_bytes(b'audio')
        sidecar = audio.with_suffix('.png')
        Image.new('RGB', (20, 20), 'orange').save(sidecar)
        song = self.add_song('User title', 'User artist')
        song.filepath = 'Existing Artwork Song.mp3'
        before = song.to_dict()
        self.app.tree.selection_set(str(song.id))
        self.app.on_song_selected()
        self.assertTrue(song.cover_path)
        self.assertIsNotNone(self.app.cover_image)
        for key in ('title', 'artist', 'duration_seconds', 'genre', 'rating', 'id'):
            self.assertEqual(song.to_dict()[key], before[key])
        self.assertEqual(self.app.library.read(self.app.library.path, SongCollector).get_song_by_id(song.id).cover_path, song.cover_path)


if __name__ == '__main__':
    unittest.main()
