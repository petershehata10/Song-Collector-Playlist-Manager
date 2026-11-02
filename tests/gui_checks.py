"""GUI integration checks. Run explicitly on a Windows graphical desktop."""
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from song_collector_gui import SongCollector, SongCollectorApp


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # ttkbootstrap owns one Style per process, matching the real app lifecycle.
        from ttkbootstrap.utility import enable_high_dpi_awareness
        enable_high_dpi_awareness()
        cls.root = tk.Tk()
        cls.app = SongCollectorApp(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

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
        self.assertTrue(self.app.dirty)

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
            self.app._mark_changed()
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

    def test_cancel_edit_keeps_original(self):
        song = self.add_song()
        self.app.tree.selection_set(str(song.id))
        self.app.open_song_dialog(edit=True)
        self.app.var_title.set('Cancelled')
        self.app._close_dialog()
        self.assertEqual(song.title, 'A title')


if __name__ == '__main__':
    unittest.main()
