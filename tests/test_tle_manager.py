import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from weather_station.tle_manager import CELESTRAK_TLE_URL, TLEManager

SATELLITES = {"NOAA 15": 25338, "NOAA 18": 28654}

NOAA15_TLE = "NOAA 15\n1 25338U 98030A   24001.00000000  .00000000  00000-0  00000-0 0  9999\n2 25338  98.7196 130.1099 0010890 291.6060  68.4059 14.26006234800000"
NOAA18_TLE = "NOAA 18\n1 28654U 05018A   24001.00000000  .00000000  00000-0  00000-0 0  9999\n2 28654  99.0283 309.9780 0014127  48.0421 312.1890 14.12564618900000"


def _mock_response(text):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.text = text
    return resp


class TestNeedsUpdate:
    def test_true_when_file_missing(self, tmp_path):
        mgr = TLEManager(str(tmp_path / "tle.txt"), SATELLITES)
        assert mgr.needs_update() is True

    def test_true_when_file_is_stale(self, tmp_path):
        f = tmp_path / "tle.txt"
        f.write_text("data")
        old_ts = (datetime.now() - timedelta(hours=25)).timestamp()
        os.utime(f, (old_ts, old_ts))
        mgr = TLEManager(str(f), SATELLITES, max_age_hours=24)
        assert mgr.needs_update() is True

    def test_false_when_file_is_fresh(self, tmp_path):
        f = tmp_path / "tle.txt"
        f.write_text("data")
        mgr = TLEManager(str(f), SATELLITES, max_age_hours=24)
        assert mgr.needs_update() is False


class TestDownload:
    def test_fetches_each_satellite_individually(self, tmp_path):
        f = tmp_path / "tle.txt"
        mgr = TLEManager(str(f), SATELLITES)
        responses = [_mock_response(NOAA15_TLE), _mock_response(NOAA18_TLE)]

        with patch("weather_station.tle_manager.requests.get", side_effect=responses) as mock_get:
            assert mgr.download() is True

        assert mock_get.call_count == 2
        urls = [c.args[0] for c in mock_get.call_args_list]
        assert any("25338" in u for u in urls)
        assert any("28654" in u for u in urls)

    def test_concatenates_all_tle_blocks(self, tmp_path):
        f = tmp_path / "tle.txt"
        mgr = TLEManager(str(f), SATELLITES)
        responses = [_mock_response(NOAA15_TLE), _mock_response(NOAA18_TLE)]

        with patch("weather_station.tle_manager.requests.get", side_effect=responses):
            mgr.download()

        content = f.read_text()
        assert "NOAA 15" in content
        assert "NOAA 18" in content

    def test_creates_parent_directories(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "tle.txt"
        mgr = TLEManager(str(f), SATELLITES)
        responses = [_mock_response(NOAA15_TLE), _mock_response(NOAA18_TLE)]

        with patch("weather_station.tle_manager.requests.get", side_effect=responses):
            mgr.download()

        assert f.exists()

    def test_returns_false_on_http_error(self, tmp_path):
        import requests as req

        f = tmp_path / "tle.txt"
        mgr = TLEManager(str(f), SATELLITES)
        with patch("weather_station.tle_manager.requests.get", side_effect=req.RequestException("500")):
            assert mgr.download() is False

    def test_returns_false_on_connection_error(self, tmp_path):
        import requests as req

        f = tmp_path / "tle.txt"
        mgr = TLEManager(str(f), SATELLITES)
        with patch("weather_station.tle_manager.requests.get", side_effect=req.ConnectionError):
            assert mgr.download() is False


class TestUpdateIfNeeded:
    def test_downloads_when_stale(self, tmp_path):
        mgr = TLEManager(str(tmp_path / "tle.txt"), SATELLITES)
        with patch.object(mgr, "download", return_value=True) as mock_dl:
            result = mgr.update_if_needed()
        mock_dl.assert_called_once()
        assert result is True

    def test_skips_when_fresh(self, tmp_path):
        f = tmp_path / "tle.txt"
        f.write_text("data")
        mgr = TLEManager(str(f), SATELLITES, max_age_hours=24)
        with patch.object(mgr, "download") as mock_dl:
            result = mgr.update_if_needed()
        mock_dl.assert_not_called()
        assert result is True


class TestGetTLE:
    def test_returns_tle_lines(self, tle_file):
        mgr = TLEManager(str(tle_file), SATELLITES)
        result = mgr.get_tle("NOAA 15")
        assert result is not None
        tle1, tle2 = result
        assert tle1.startswith("1 25338")
        assert tle2.startswith("2 25338")

    def test_returns_none_for_unknown_satellite(self, tle_file):
        mgr = TLEManager(str(tle_file), SATELLITES)
        assert mgr.get_tle("NOAA 99") is None

    def test_returns_none_when_file_missing(self, tmp_path):
        mgr = TLEManager(str(tmp_path / "missing.txt"), SATELLITES)
        assert mgr.get_tle("NOAA 15") is None

    def test_case_insensitive_search(self, tle_file):
        mgr = TLEManager(str(tle_file), SATELLITES)
        assert mgr.get_tle("noaa 15") is not None
        assert mgr.get_tle("NOAA 15") is not None
