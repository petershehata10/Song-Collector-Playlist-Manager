import json
from pathlib import Path
import tempfile
import unittest

from song_collector_gui import Song, SongCollector


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.collector = SongCollector()
        self.first = self.add('Dancing Queen', 'ABBA', 232, 'Pop', 5)
        self.second = self.add('Animals', 'Martin Garrix', 190, 'Dance', 3)

    def add(self, title, artist, duration, genre, rating):
        return self.collector.add_song(title, artist, duration, genre, rating, '', '')

    def test_crud_and_stable_ids(self):
        self.assertTrue(self.collector.update_song(self.first.id, title='Queen', artist='ABBA', duration_seconds=230, genre='Disco', rating=4, filepath='audio.mp3', cover_path='cover.png'))
        self.assertEqual(self.collector.get_song_by_id(self.first.id).title, 'Queen')
        self.assertTrue(self.collector.remove_song_by_id(self.first.id))
        self.assertFalse(self.collector.remove_song_by_id(self.first.id))
        self.assertGreater(self.add('New', 'Artist', 0, '', 1).id, self.second.id)

    def test_search_statistics_and_duration(self):
        self.assertEqual(self.collector.search_smart('ABBA dancing'), [self.first])
        self.assertEqual(self.collector.search_smart('missing'), [])
        self.assertEqual(self.collector.genre_counts(), {'Pop': 1, 'Dance': 1})
        self.assertEqual(self.collector.total_duration(), 422)
        self.assertEqual(self.collector.total_duration([self.second]), 190)

    def test_all_sort_modes(self):
        for mode, expected in [('Title', [2, 1]), ('Duration', [2, 1]), ('Rating', [1, 2]), ('Newest', [2, 1]), ('Oldest', [1, 2])]:
            with self.subTest(mode=mode):
                self.collector.sort_songs(mode)
                self.assertEqual([s.id for s in self.collector.list_songs()], expected)

    def test_json_round_trip_preserves_format_and_next_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.json'
            self.collector.save_to_file(path)
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(set(data), {'next_id', 'songs'})
            self.assertEqual(set(data['songs'][0]), {'title', 'artist', 'duration_seconds', 'genre', 'rating', 'filepath', 'cover_path', 'id'})
            loaded = SongCollector()
            loaded.load_from_file(path)
            self.assertEqual([s.to_dict() for s in loaded.list_songs()], data['songs'])
            self.assertEqual(loaded.add_song('New', 'Artist', 10, '', 2, '', '').id, 3)

    def test_failed_load_keeps_existing_library_and_id_counter(self):
        good = self.first.to_dict()
        for invalid in ({'songs': [good, good]}, {'songs': [dict(good, rating=8)]}, {'songs': [good], 'next_id': 'bad'}, {'songs': ['bad']}, [], {'songs': [dict(good, title=123)]}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'invalid.json'
                path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    self.collector.load_from_file(path)
                self.assertEqual(self.collector.list_songs(), [self.first, self.second])
                self.assertEqual(self.collector._next_id, 3)

    def test_invalid_edit_is_atomic(self):
        before = self.first.to_dict()
        with self.assertRaises(ValueError):
            self.collector.update_song(self.first.id, title='Changed', artist='ABBA', duration_seconds=-1, genre='', rating=3, filepath='', cover_path='')
        self.assertEqual(self.first.to_dict(), before)

    def test_model_rejects_invalid_values(self):
        for changes in ({'rating': 0}, {'rating': 6}, {'duration_seconds': -1}, {'duration_seconds': '30'}, {'title': ''}, {'filepath': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Song.from_dict(dict(self.first.to_dict(), **changes))

    def test_bundled_library_is_readable_without_modifying_it(self):
        path = Path(__file__).resolve().parents[1] / 'My Favourite Library.json'
        before = path.read_bytes()
        self.collector.load_from_file(path)
        self.assertEqual(len(self.collector.list_songs()), 8)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
