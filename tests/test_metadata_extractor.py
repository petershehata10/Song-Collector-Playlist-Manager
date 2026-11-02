from pathlib import Path
from io import BytesIO
from PIL import Image
import tempfile
import unittest
from unittest.mock import Mock, patch

from mutagen.id3 import APIC, ID3

from metadata_extractor import extract_audio_metadata, save_embedded_artwork


class MetadataExtractorTests(unittest.TestCase):
    def test_reads_tags_duration_and_nearby_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "ignored-name.mp3"
            audio.write_bytes(b"audio")
            cover = Path(folder) / "ignored-name.jpeg"
            Image.new("RGB", (20, 20), "orange").save(cover)
            fake = Mock(tags={"title": ["Tagged title"], "artist": ["Tagged artist"], "genre": ["Jazz"]})
            fake.info.length = 124.6
            with patch("metadata_extractor.MutagenFile", return_value=fake), patch(
                "metadata_extractor._embedded_artwork", return_value=(None, ".jpg")
            ):
                result = extract_audio_metadata(audio)
            self.assertEqual(result.title, "Tagged title")
            self.assertEqual(result.artist, "Tagged artist")
            self.assertEqual(result.genre, "Jazz")
            self.assertEqual(result.duration_seconds, 125)
            self.assertEqual(result.cover_path, str(cover.resolve()))

    def test_missing_tags_suggest_artist_and_title_from_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "The Artist - A Song.mp3"
            audio.touch()
            fake = Mock(tags={}, info=Mock(length=None))
            with patch("metadata_extractor.MutagenFile", return_value=fake), patch(
                "metadata_extractor._embedded_artwork", return_value=(None, ".jpg")
            ):
                result = extract_audio_metadata(audio)
            self.assertEqual((result.title, result.artist), ("A Song", "The Artist"))
            self.assertEqual(result.genre, "")
            self.assertIsNone(result.duration_seconds)

    def test_reads_png_embedded_artwork_and_saves_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "song.mp3"
            tags = ID3()
            buffer = BytesIO()
            Image.new("RGB", (20, 20), "orange").save(buffer, format="PNG")
            artwork = buffer.getvalue()
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=artwork))
            tags.save(audio)
            fake = Mock(tags={"title": ["Song"]}, info=Mock(length=1))
            with patch("metadata_extractor.MutagenFile", return_value=fake):
                result = extract_audio_metadata(audio)
            self.assertEqual(result.artwork, artwork)
            self.assertEqual(result.artwork_extension, ".png")
            destination = Path(folder) / "covers"
            first = save_embedded_artwork(result.artwork, result.artwork_extension, destination, "song")
            second = save_embedded_artwork(result.artwork, result.artwork_extension, destination, "song")
            self.assertEqual(first.read_bytes(), artwork)
            self.assertEqual(second, first)

    def test_malformed_audio_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "broken.mp3"
            audio.write_bytes(b"not an mp3")
            result = extract_audio_metadata(audio)
            self.assertTrue(result.error or result.title == "broken")

    def test_embedded_front_cover_wins_even_when_audio_stream_is_unreadable(self):
        from mutagen import MutagenError
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'song.mp3'
            def image_bytes(color):
                buffer = BytesIO()
                Image.new('RGB', (10, 10), color).save(buffer, format='PNG')
                return buffer.getvalue()
            tags = ID3()
            front, back = image_bytes('red'), image_bytes('blue')
            tags.add(APIC(encoding=3, mime='image/png', type=4, desc='back', data=back))
            tags.add(APIC(encoding=3, mime='image/png', type=3, desc='front', data=front))
            tags.save(audio)
            Image.new('RGB', (10, 10), 'green').save(audio.with_suffix('.png'))
            before = audio.read_bytes()
            with patch('metadata_extractor.MutagenFile', side_effect=MutagenError('no MPEG frames')):
                result = extract_audio_metadata(audio)
            self.assertEqual(result.artwork, front)
            self.assertEqual(result.cover_path, '')
            self.assertEqual(audio.read_bytes(), before)

    def test_matching_project_image_and_common_folder_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'Artist - Title (Official Music Video).mp3'
            audio.touch()
            covers = root / 'covers'
            covers.mkdir()
            cover = covers / 'Artist_-_Title.PNG'
            Image.new('RGB', (10, 10), 'orange').save(cover)
            result = extract_audio_metadata(audio, [covers])
            self.assertEqual(Path(result.cover_path), cover)
            # A distinct recording without a matching image can use folder.jpg.
            other = root / 'Other.mp3'
            other.touch()
            common = root / 'folder.jpg'
            Image.new('RGB', (10, 10), 'orange').save(common)
            self.assertEqual(Path(extract_audio_metadata(other, [covers]).cover_path), common)

    def test_ambiguous_sidecars_and_common_covers_do_not_guess(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'song.mp3'
            audio.touch()
            for name in ('song.png', 'song.jpg', 'cover.jpg'):
                Image.new('RGB', (10, 10), 'orange').save(root / name)
            self.assertEqual(extract_audio_metadata(audio).cover_path, '')
            other = root / 'other.mp3'
            other.touch()
            Image.new('RGB', (10, 10), 'blue').save(root / 'folder.jpg')
            self.assertEqual(extract_audio_metadata(other).cover_path, '')

    def test_invalid_embedded_image_falls_back_to_valid_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'song.mp3'
            tags = ID3()
            tags.add(APIC(encoding=3, mime='image/png', type=3, desc='', data=b'invalid image'))
            tags.save(audio)
            cover = audio.with_suffix('.png')
            Image.new('RGB', (10, 10), 'orange').save(cover)
            result = extract_audio_metadata(audio)
            self.assertIsNone(result.artwork)
            self.assertEqual(Path(result.cover_path), cover)

    def test_artwork_collision_preserves_previous_image(self):
        with tempfile.TemporaryDirectory() as folder:
            def image_bytes(color):
                buffer = BytesIO()
                Image.new('RGB', (10, 10), color).save(buffer, format='PNG')
                return buffer.getvalue()
            first_data, second_data = image_bytes('red'), image_bytes('blue')
            first = save_embedded_artwork(first_data, '.png', folder, 'song')
            second = save_embedded_artwork(second_data, '.png', folder, 'song')
            self.assertEqual(first.read_bytes(), first_data)
            self.assertEqual(second.name, 'song (2).png')
            self.assertEqual(second.read_bytes(), second_data)


if __name__ == "__main__":
    unittest.main()
