import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from weather_station.cleaner import Cleaner


@pytest.fixture
def files(tmp_path):
    wav = tmp_path / "test.wav"
    png = tmp_path / "test.png"
    wav.write_bytes(b"\x00" * 100)
    png.write_bytes(b"\x89PNG")
    return wav, png


class TestCleanup:
    def test_deletes_wav_and_png_by_default(self, files):
        wav, png = files
        cleaner = Cleaner(delete_wav=True, delete_png=True)
        stats = cleaner.cleanup([wav, png])
        assert not wav.exists()
        assert not png.exists()
        assert stats["wav"] == 1
        assert stats["png"] == 1

    def test_skips_wav_when_disabled(self, files):
        wav, png = files
        cleaner = Cleaner(delete_wav=False, delete_png=True)
        stats = cleaner.cleanup([wav, png])
        assert wav.exists()
        assert not png.exists()
        assert stats["skipped"] == 1

    def test_skips_png_when_disabled(self, files):
        wav, png = files
        cleaner = Cleaner(delete_wav=True, delete_png=False)
        stats = cleaner.cleanup([wav, png])
        assert not wav.exists()
        assert png.exists()
        assert stats["skipped"] == 1

    def test_ignores_missing_files(self, tmp_path):
        cleaner = Cleaner()
        stats = cleaner.cleanup([tmp_path / "nonexistent.wav"])
        assert stats["wav"] == 0

    def test_other_extensions_counted_as_skipped(self, tmp_path):
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        cleaner = Cleaner()
        stats = cleaner.cleanup([txt])
        assert txt.exists()
        assert stats["skipped"] == 1


class TestCleanupOldFiles:
    def test_removes_old_files(self, tmp_path):
        old_file = tmp_path / "old.wav"
        old_file.write_bytes(b"\x00")
        old_ts = (datetime.now() - timedelta(hours=50)).timestamp()
        os.utime(old_file, (old_ts, old_ts))

        cleaner = Cleaner()
        count = cleaner.cleanup_old_files(tmp_path, max_age_hours=48)

        assert count == 1
        assert not old_file.exists()

    def test_keeps_recent_files(self, tmp_path):
        new_file = tmp_path / "new.wav"
        new_file.write_bytes(b"\x00")

        cleaner = Cleaner()
        count = cleaner.cleanup_old_files(tmp_path, max_age_hours=48)

        assert count == 0
        assert new_file.exists()

    def test_returns_zero_for_missing_directory(self, tmp_path):
        cleaner = Cleaner()
        count = cleaner.cleanup_old_files(tmp_path / "nonexistent", max_age_hours=24)
        assert count == 0
