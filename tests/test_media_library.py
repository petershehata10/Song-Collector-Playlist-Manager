import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from media_library import MediaPaths, WorkingLibrary
from song_collector_gui import SongCollector


SAMPLE = Path(__file__).resolve().parents[1] / 'My Favourite Library.json'


class LocalLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        self.root.mkdir()
        self.store = WorkingLibrary(self.root)

    def install_sample(self):
        original = self.root / SAMPLE.name
        original.write_bytes(SAMPLE.read_bytes())
        records = json.loads(original.read_text(encoding='utf-8'))
        for song in records['songs']:
            for field in ('filepath', 'cover_path'):
                (self.root / PureWindowsPath(song[field]).name).write_bytes(b'fixture media')
        return original, records

    def test_first_startup_migrates_all_eight_songs_without_touching_originals(self):
        original, data = self.install_sample()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        collector = self.store.startup(SongCollector)
        self.assertTrue(self.store.path.is_file())
        self.assertEqual(len(collector.list_songs()), 8)
        migrated = json.loads(self.store.path.read_text(encoding='utf-8'))
        self.assertEqual(migrated['next_id'], data['next_id'])
        for old, new in zip(data['songs'], migrated['songs']):
            for key, value in old.items():
                if key in ('filepath', 'cover_path'):
                    self.assertEqual(new[key], PureWindowsPath(value).name)
                    self.assertTrue((self.root / new[key]).is_file())
                else:
                    self.assertEqual(new[key], value)
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_reopen_saved_library_takes_precedence_over_legacy(self):
        self.install_sample()
        collector = self.store.startup(SongCollector)
        song = collector.add_song('New title', 'Artist', 123, 'New genre', 2, '', '')
        self.store.save(collector)
        reopened = WorkingLibrary(self.root).startup(SongCollector)
        self.assertEqual([s.to_dict() for s in reopened.list_songs()], [s.to_dict() for s in collector.list_songs()])
        self.assertEqual(reopened.get_song_by_id(song.id).rating, 2)
        self.assertEqual(reopened.add_song('Next', 'Artist', 0, '', 1, '', '').id, 10)

    def test_startup_without_any_library_creates_empty_working_file(self):
        collector = self.store.startup(SongCollector)
        self.assertEqual(collector.list_songs(), [])
        self.assertEqual(json.loads(self.store.path.read_text()), {'songs': [], 'next_id': 1})

    def test_old_windows_paths_with_both_slash_styles_and_case(self):
        (self.root / 'Track.mp3').write_bytes(b'audio')
        (self.root / 'Cover.png').write_bytes(b'cover')
        for value in (r'Q:\obsolete\TRACK.mp3', 'Q:/obsolete/TRACK.mp3'):
            self.assertEqual(self.store.media.normalize(value, 'audio'), 'Track.mp3')
        self.assertEqual(self.store.media.normalize(r'Q:\obsolete\Cover.png', 'covers'), 'Cover.png')

    def test_relative_audio_and_cover_paths_do_not_depend_on_cwd(self):
        for kind, name in (('audio', 'song.mp3'), ('covers', 'art.png')):
            folder = self.store.media.folder(kind)
            folder.mkdir(parents=True)
            asset = folder / name
            asset.touch()
            with patch('pathlib.Path.cwd', return_value=Path(self.temporary.name)):
                self.assertEqual(self.store.media.resolve(f'media/{kind}/{name}', kind), asset)
                self.assertEqual(self.store.media.resolve(f'media\\{kind}\\{name}', kind), asset)
            self.assertEqual(self.store.media.normalize(str(asset), kind), f'media/{kind}/{name}')

    def test_missing_media_preserves_song_and_original_reference(self):
        original, data = self.install_sample()
        for song in data['songs']:
            (self.root / PureWindowsPath(song['filepath']).name).unlink()
            (self.root / PureWindowsPath(song['cover_path']).name).unlink()
        collector = self.store.startup(SongCollector)
        self.assertEqual([s.to_dict() for s in collector.list_songs()], data['songs'])
        self.assertIsNone(self.store.media.resolve('', 'audio'))
        self.assertFalse(self.store.media.resolve('absent.mp3', 'audio').is_file())
        self.assertEqual(self.store.media.normalize('media/audio/absent.mp3', 'audio'), 'media/audio/absent.mp3')

    def test_corrupted_working_json_is_not_overwritten_or_replaced_by_legacy(self):
        self.install_sample()
        self.store.path.parent.mkdir()
        broken = b'{ this is not valid JSON'
        self.store.path.write_bytes(broken)
        with self.assertRaises(ValueError):
            self.store.startup(SongCollector)
        with self.assertRaises(OSError):
            self.store.save(SongCollector())
        with self.assertRaises(OSError):
            self.store.export(SongCollector(), self.store.path)
        self.assertEqual(self.store.path.read_bytes(), broken)
        # Recovery export remains available without unblocking the corrupt file.
        self.store.export(SongCollector(), self.root / 'recovery.json')
        self.assertEqual(self.store.path.read_bytes(), broken)

    def test_corrupted_legacy_json_is_not_imported_as_empty(self):
        self.store.original.write_text('{bad', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.store.startup(SongCollector)
        self.assertFalse(self.store.path.exists())
        with self.assertRaises(OSError):
            self.store.save(SongCollector())
        self.assertEqual(self.store.original.read_text(), '{bad')

    def test_import_preserves_ids_next_id_and_metadata_and_source_bytes(self):
        self.store.startup(SongCollector)
        source = self.root / 'import.json'
        data = json.loads(SAMPLE.read_text(encoding='utf-8'))
        data['next_id'] = 99
        source.write_text(json.dumps(data), encoding='utf-8')
        before = source.read_bytes()
        collector = self.store.read(source, SongCollector)
        self.store.save(collector)
        reopened = WorkingLibrary(self.root).startup(SongCollector)
        self.assertEqual([s.to_dict() for s in reopened.list_songs()], data['songs'])
        self.assertEqual(reopened.add_song('Next', 'Artist', 1, '', 1, '', '').id, 99)
        self.assertEqual(source.read_bytes(), before)

    def test_import_relative_external_paths_are_linked_without_copying(self):
        source_dir = Path(self.temporary.name) / 'external'
        source_dir.mkdir()
        asset = source_dir / 'track.mp3'
        asset.touch()
        song = json.loads(SAMPLE.read_text(encoding='utf-8'))['songs'][0]
        song['filepath'] = 'track.mp3'
        source = source_dir / 'library.json'
        source.write_text(json.dumps({'songs': [song]}), encoding='utf-8')
        collector = self.store.read(source, SongCollector)
        self.assertEqual(Path(collector.list_songs()[0].filepath), asset)

    def test_copy_assets_uses_safe_unique_names_and_keeps_originals(self):
        external = Path(self.temporary.name) / 'track.mp3'
        external.write_bytes(b'original')
        first = self.store.media.copy_asset(external, 'audio')
        external.write_bytes(b'new content')
        second = self.store.media.copy_asset(external, 'audio')
        self.assertEqual(first, 'media/audio/track.mp3')
        self.assertEqual(second, 'media/audio/track (2).mp3')
        self.assertEqual((self.root / first).read_bytes(), b'original')
        self.assertEqual((self.root / second).read_bytes(), b'new content')
        self.assertEqual(external.read_bytes(), b'new content')
        self.assertEqual(self.store.media.copy_asset(self.root / first, 'audio'), first)
        cover = Path(self.temporary.name) / 'cover.png'
        cover.write_bytes(b'cover')
        self.assertEqual(self.store.media.copy_asset(cover, 'covers'), 'media/covers/cover.png')
        with self.assertRaises(FileNotFoundError):
            self.store.media.copy_asset(cover.parent / 'missing.png', 'covers')

    def test_failed_atomic_replace_keeps_previous_file_and_cleans_temporary(self):
        collector = self.store.startup(SongCollector)
        before = self.store.path.read_bytes()
        collector.add_song('Title', 'Artist', 1, '', 1, '', '')
        with patch('media_library.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.store.save(collector)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(list(self.store.path.parent.glob('*.tmp')), [])
        self.store.save(collector)
        self.assertEqual(len(WorkingLibrary(self.root).startup(SongCollector).list_songs()), 1)

    def test_export_cannot_overwrite_legacy_or_audio_files(self):
        self.install_sample()
        collector = self.store.startup(SongCollector)
        before = self.store.original.read_bytes()
        with self.assertRaises(ValueError):
            self.store.export(collector, self.store.original)
        with self.assertRaises(ValueError):
            self.store.export(collector, self.root / 'song.mp3')
        self.assertEqual(self.store.original.read_bytes(), before)

    def test_repaired_paths_are_persisted_without_replacing_current_library(self):
        self.store.startup(SongCollector)
        audio = self.store.media.folder('audio') / 'kept.mp3'
        audio.write_bytes(b'kept audio')
        cover = self.store.media.folder('covers') / 'kept.png'
        cover.write_bytes(b'kept cover')
        collector = SongCollector()
        song = collector.add_song('User title', 'User artist', 42, 'User genre', 2,
                                  r'M:\Books VUT\old\kept.mp3', r'M:\Books VUT\old\kept.png')
        original = song.to_dict()
        self.store.save(collector)
        reopened = WorkingLibrary(self.root).startup(SongCollector)
        saved = json.loads(self.store.path.read_text())
        self.assertEqual(len(saved['songs']), 1)
        self.assertEqual(saved['songs'][0]['filepath'], 'media/audio/kept.mp3')
        self.assertEqual(saved['songs'][0]['cover_path'], 'media/covers/kept.png')
        for field in ('title', 'artist', 'duration_seconds', 'genre', 'rating', 'id'):
            self.assertEqual(saved['songs'][0][field], original[field])
        self.assertEqual(reopened.get_song_by_id(song.id).filepath, 'media/audio/kept.mp3')

    def test_ambiguous_legacy_paths_remain_unchanged_across_folders(self):
        self.store.startup(SongCollector)
        for path in (self.root / 'same.mp3', self.store.media.folder('audio') / 'same.mp3'):
            path.write_bytes(b'candidate')
        old = r'Q:\missing\same.mp3'
        self.assertEqual(self.store.media.normalize(old, 'audio'), old)
        self.assertEqual(self.store.media.normalize('media/audio/same.mp3', 'audio'), 'media/audio/same.mp3')

    def test_project_move_recovers_old_project_absolute_paths_and_reopens(self):
        self.store.startup(SongCollector)
        asset = self.store.media.folder('audio') / 'moved.mp3'
        asset.touch()
        self.assertEqual(self.store.media.normalize(r'Q:\previous-project\media\audio\moved.mp3', 'audio'), 'media/audio/moved.mp3')
        collector = SongCollector()
        collector.add_song('Moved', 'Artist', 1, '', 3, 'media/audio/moved.mp3', '')
        self.store.save(collector)
        # Copy the complete miniature project to a different directory.
        import shutil
        moved = Path(self.temporary.name) / 'new-project'
        shutil.copytree(self.root, moved)
        other = WorkingLibrary(moved)
        reopened = other.startup(SongCollector)
        self.assertEqual(other.media.resolve(reopened.list_songs()[0].filepath, 'audio'), moved / 'media/audio/moved.mp3')

    def test_repeated_external_selection_and_renamed_identical_file_reuse_copy(self):
        source = Path(self.temporary.name) / 'repeat.mp3'
        source.write_bytes(b'same recording')
        first = self.store.media.copy_asset(source, 'audio')
        self.assertEqual(self.store.media.copy_asset(source, 'audio'), first)
        renamed = source.with_name('renamed.mp3')
        renamed.write_bytes(source.read_bytes())
        self.assertEqual(self.store.media.copy_asset(renamed, 'audio'), first)
        self.assertEqual(len(list(self.store.media.folder('audio').glob('*.mp3'))), 1)


if __name__ == '__main__':
    unittest.main()
