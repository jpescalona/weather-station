"""Tests for weather_station/cli.py — all four CLI commands + CSV parser."""
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from weather_station.cli import (
    _parse_rtl_power_csv,
    cmd_check,
    cmd_passes,
    cmd_receive,
    cmd_scan,
)
from weather_station.predictor import SatellitePass


# ─── fixtures / helpers ───────────────────────────────────────────────────────

def _sat_cfg(freq=137620000):
    s = MagicMock()
    s.frequency = freq
    s.norad_id = 25338
    return s


def _make_config():
    cfg = MagicMock()
    cfg.location.latitude = 36.5
    cfg.location.longitude = -4.6
    cfg.capture.min_elevation = 20
    cfg.capture.competing_services = []
    cfg.capture.gain = 44.5
    cfg.capture.rtl_sample_rate = 60000
    cfg.capture.final_sample_rate = 11025
    cfg.capture.ppm = 0
    cfg.telegram.bot_token = ""
    cfg.telegram.chat_id = ""
    cfg.paths.recordings_dir = "/tmp/test_ws"
    cfg.cleanup.delete_wav = True
    cfg.cleanup.delete_png = True
    cfg.satellites = {
        "NOAA 15": _sat_cfg(137620000),
        "NOAA 19": _sat_cfg(137100000),
    }
    return cfg


def _make_pass(satellite, offset_hours, max_elevation=45.0):
    now = datetime.now(timezone.utc)
    aos = now + timedelta(hours=offset_hours)
    los = aos + timedelta(minutes=12)
    return SatellitePass(satellite, aos, los, max_elevation, 137620000)


# ─── _parse_rtl_power_csv ────────────────────────────────────────────────────

class TestParseRtlPowerCsv:
    _CSV = "2024-01-01, 12:00:00, 137620000, 138000000, 5000, 64, -72.3\n"

    def test_returns_power_near_target(self):
        assert _parse_rtl_power_csv(self._CSV, 137620000) == pytest.approx(-72.3, abs=0.1)

    def test_returns_none_when_no_data_near_target(self):
        assert _parse_rtl_power_csv(self._CSV, 100_000_000) is None

    def test_returns_none_on_empty_csv(self):
        assert _parse_rtl_power_csv("", 137620000) is None

    def test_skips_rows_too_short(self):
        assert _parse_rtl_power_csv("a, b, c\n", 137620000) is None

    def test_skips_rows_with_invalid_number(self):
        csv_text = "2024-01-01, 12:00:00, not_int, 138000000, 5000, 64, -72.3\n"
        assert _parse_rtl_power_csv(csv_text, 137620000) is None

    def test_returns_peak_across_multiple_rows(self):
        csv_text = (
            "2024-01-01, 12:00:00, 137620000, 138000000, 5000, 64, -75.0\n"
            "2024-01-01, 12:00:02, 137620000, 138000000, 5000, 64, -70.0\n"
        )
        assert _parse_rtl_power_csv(csv_text, 137620000) == pytest.approx(-70.0, abs=0.1)

    def test_bin_within_step_hz_is_included(self):
        # bin at 137615000, target 137620000, delta = 5000 = step_hz → included
        csv_text = "2024-01-01, 12:00:00, 137615000, 138000000, 5000, 64, -68.0\n"
        assert _parse_rtl_power_csv(csv_text, 137620000, step_hz=5000) == pytest.approx(-68.0, abs=0.1)

    def test_bin_outside_step_hz_excluded(self):
        # bin at 137640000, delta = 20000 > 5000
        csv_text = "2024-01-01, 12:00:00, 137640000, 138000000, 5000, 64, -68.0\n"
        assert _parse_rtl_power_csv(csv_text, 137620000, step_hz=5000) is None

    def test_multiple_bins_per_row(self):
        # row with 2 db values; second bin at 137625000 is within range
        csv_text = "2024-01-01, 12:00:00, 137610000, 138000000, 5000, 64, -90.0, -65.0\n"
        # bin0 = 137610000 (delta 10000 > 5000, excluded)
        # bin1 = 137615000 (delta 5000 = step_hz, included)
        result = _parse_rtl_power_csv(csv_text, 137620000, step_hz=5000)
        assert result == pytest.approx(-65.0, abs=0.1)


# ─── cmd_check ───────────────────────────────────────────────────────────────

class TestCmdCheck:
    """Each test configures a scenario via the _run helper."""

    def _run(self, *, lsusb_out="Bus 001: ID 0bda:2838 Realtek\n",
             lsusb_raises=False, which_map=None, groups=None,
             rtl_out="Found 1 device(s)", rtl_timeout=False,
             groups_raises=False):
        if which_map is None:
            which_map = {
                "rtl_fm": "/usr/bin/rtl_fm",
                "sox": "/usr/bin/sox",
                "noaa-apt": "/usr/local/bin/noaa-apt",
                "rtl_test": "/usr/bin/rtl_test",
                "rtl_power": "/usr/bin/rtl_power",
            }
        if groups is None:
            g = MagicMock()
            g.gr_name = "plugdev"
            g.gr_mem = ["pi"]
            groups = [g]

        def run_side(cmd, **kw):
            r = MagicMock()
            if cmd[0] == "lsusb":
                if lsusb_raises:
                    raise FileNotFoundError
                r.stdout = lsusb_out
            else:
                if rtl_timeout:
                    raise subprocess.TimeoutExpired("rtl_test", 8)
                r.stderr = rtl_out
                r.stdout = ""
                r.returncode = 0
            return r

        def getgrall():
            if groups_raises:
                raise OSError("no grp")
            return groups

        with patch("weather_station.cli.subprocess.run", side_effect=run_side), \
             patch("weather_station.cli.shutil.which", side_effect=lambda t: which_map.get(t)), \
             patch("weather_station.cli.grp.getgrall", side_effect=getgrall):
            return cmd_check()

    def test_all_ok_returns_true(self):
        assert self._run() is True

    def test_rtl_sdr_not_in_lsusb_returns_false(self):
        assert self._run(lsusb_out="Bus 001: ID 1234:5678 Generic\n") is False

    def test_lsusb_not_available_continues_other_checks(self):
        assert self._run(lsusb_raises=True) is True

    def test_missing_required_tool_returns_false(self):
        which_map = {
            "sox": "/usr/bin/sox",
            "noaa-apt": "/usr/local/bin/noaa-apt",
            "rtl_test": "/usr/bin/rtl_test",
        }  # rtl_fm absent
        assert self._run(which_map=which_map) is False

    def test_missing_optional_tools_still_ok(self):
        which_map = {
            "rtl_fm": "/usr/bin/rtl_fm",
            "sox": "/usr/bin/sox",
            "noaa-apt": "/usr/local/bin/noaa-apt",
        }  # rtl_test, rtl_power absent (optional)
        assert self._run(which_map=which_map) is True

    def test_user_not_in_plugdev_returns_false(self):
        g = MagicMock()
        g.gr_name = "audio"
        g.gr_mem = ["pi"]
        assert self._run(groups=[g]) is False

    def test_rtl_test_no_supported_devices_returns_false(self):
        assert self._run(rtl_out="No supported devices found") is False

    def test_rtl_test_timeout_returns_false(self):
        assert self._run(rtl_timeout=True) is False

    def test_rtl_test_not_installed_is_skipped(self):
        which_map = {
            "rtl_fm": "/usr/bin/rtl_fm",
            "sox": "/usr/bin/sox",
            "noaa-apt": "/usr/local/bin/noaa-apt",
        }
        assert self._run(which_map=which_map) is True

    def test_rtl_test_logs_device_info(self, capsys):
        self._run(rtl_out="Found 1 device(s)\nTuner: Rafael Micro R820T")
        assert "[OK]" in capsys.readouterr().out

    def test_group_check_exception_is_swallowed(self):
        assert self._run(groups_raises=True) is True

    def test_prints_success_message_when_all_ok(self, capsys):
        self._run()
        assert "listo" in capsys.readouterr().out

    def test_prints_problem_message_when_not_ok(self, capsys):
        self._run(lsusb_out="nothing")
        assert "problemas" in capsys.readouterr().out


# ─── cmd_passes ──────────────────────────────────────────────────────────────

class TestCmdPasses:

    def test_passes_sorted_chronologically(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_tle.get_tle.return_value = ("tle1", "tle2")
        mock_pred = MagicMock()
        # NOAA 19 comes sooner
        pass_later = _make_pass("NOAA 15", offset_hours=2)
        pass_sooner = _make_pass("NOAA 19", offset_hours=1)
        mock_pred.get_next_pass.side_effect = [
            pass_later, None,   # NOAA 15: 1 pass then stop
            pass_sooner, None,  # NOAA 19: 1 pass then stop
        ]

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=mock_pred):
            cmd_passes(config)

        out = capsys.readouterr().out
        assert out.index("NOAA 19") < out.index("NOAA 15")

    def test_tle_update_failure_prints_error_and_returns(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = False
        mock_pred = MagicMock()

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=mock_pred):
            cmd_passes(config)

        assert "ERROR" in capsys.readouterr().out
        mock_pred.get_next_pass.assert_not_called()

    def test_missing_tle_prints_warning(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_tle.get_tle.return_value = None  # no TLE for any satellite

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=MagicMock()):
            cmd_passes(config)

        assert "[!!]" in capsys.readouterr().out

    def test_pass_in_progress_shows_en_curso(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_tle.get_tle.return_value = ("tle1", "tle2")
        mock_pred = MagicMock()

        now = datetime.now(timezone.utc)
        current_pass = SatellitePass(
            "NOAA 15",
            aos=now - timedelta(minutes=5),
            los=now + timedelta(minutes=7),
            max_elevation=45.0,
            frequency=137620000,
        )
        mock_pred.get_next_pass.side_effect = [current_pass, None, None, None, None, None]

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=mock_pred):
            cmd_passes(config)

        assert "EN CURSO" in capsys.readouterr().out

    def test_table_header_always_printed(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_tle.get_tle.return_value = ("tle1", "tle2")
        mock_pred = MagicMock()
        mock_pred.get_next_pass.return_value = None

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=mock_pred):
            cmd_passes(config)

        assert "Satelite" in capsys.readouterr().out

    def test_multiple_passes_per_satellite(self, capsys):
        config = _make_config()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_tle.get_tle.return_value = ("tle1", "tle2")
        mock_pred = MagicMock()

        p1 = _make_pass("NOAA 15", offset_hours=1)
        p2 = _make_pass("NOAA 15", offset_hours=3)
        p3 = _make_pass("NOAA 15", offset_hours=5)
        mock_pred.get_next_pass.side_effect = [
            p1, p2, p3,       # NOAA 15: 3 passes
            None, None, None,  # NOAA 19: no passes
        ]

        with patch("weather_station.cli._build_tle_manager", return_value=mock_tle), \
             patch("weather_station.cli._build_predictor", return_value=mock_pred):
            cmd_passes(config, per_satellite=3)

        out = capsys.readouterr().out
        assert out.count("NOAA 15") >= 3  # header row + 3 data rows


# ─── cmd_receive ─────────────────────────────────────────────────────────────

class TestCmdReceive:

    def _sat_map(self):
        return {"NOAA 19": _sat_cfg(137100000)}

    def test_unknown_satellite_returns_false(self, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        assert cmd_receive(config, "NOAA 99", 60) is False
        assert "no reconocido" in capsys.readouterr().out

    def test_available_satellites_listed_on_error(self, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        cmd_receive(config, "NOAA 99", 60)
        assert "NOAA 19" in capsys.readouterr().out

    def test_satellite_name_variants_accepted(self, tmp_path):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder"), \
             patch("weather_station.cleaner.Cleaner"), \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = None
            for variant in ("noaa-19", "NOAA_19", "noaa 19"):
                MockR.return_value.record.reset_mock()
                cmd_receive(config, variant, 60)
                MockR.return_value.record.assert_called_once()

    def test_recording_failure_returns_false(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder"), \
             patch("weather_station.cleaner.Cleaner"), \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = None
            result = cmd_receive(config, "NOAA 19", 60)

        assert result is False
        assert "fallida" in capsys.readouterr().out

    def test_decode_failure_returns_false_and_cleans_wav(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)
        wav = tmp_path / "test.wav"
        wav.write_bytes(b"\x00" * 100)

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder") as MockD, \
             patch("weather_station.cleaner.Cleaner") as MockC, \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = wav
            MockD.return_value.decode.return_value = (None, None)
            result = cmd_receive(config, "NOAA 19", 60)

        assert result is False
        MockC.return_value.cleanup.assert_called_once_with([wav])
        assert "fallida" in capsys.readouterr().out

    def test_success_with_telegram_sends_and_cleans(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)
        config.telegram.bot_token = "tok"
        config.telegram.chat_id = "chat"
        wav = tmp_path / "test.wav"
        img = tmp_path / "test_bw.png"
        wav.write_bytes(b"\x00" * 100)
        img.write_bytes(b"\x89PNG")

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder") as MockD, \
             patch("weather_station.cleaner.Cleaner") as MockC, \
             patch("weather_station.sender.TelegramSender") as MockS, \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = wav
            MockD.return_value.decode.return_value = (img, None)
            MockS.return_value.send.return_value = True
            result = cmd_receive(config, "NOAA 19", 60)

        assert result is True
        MockS.return_value.send.assert_called_once()
        MockC.return_value.cleanup.assert_called_once()

    def test_telegram_send_failure_keeps_files(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)
        config.telegram.bot_token = "tok"
        config.telegram.chat_id = "chat"
        wav = tmp_path / "test.wav"
        img = tmp_path / "test_bw.png"
        wav.write_bytes(b"\x00" * 100)
        img.write_bytes(b"\x89PNG")

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder") as MockD, \
             patch("weather_station.cleaner.Cleaner") as MockC, \
             patch("weather_station.sender.TelegramSender") as MockS, \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = wav
            MockD.return_value.decode.return_value = (img, None)
            MockS.return_value.send.return_value = False
            result = cmd_receive(config, "NOAA 19", 60)

        assert result is True
        MockC.return_value.cleanup.assert_not_called()
        assert "Error" in capsys.readouterr().out

    def test_no_telegram_config_skips_send(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)
        # telegram credentials empty → no sender
        wav = tmp_path / "test.wav"
        img = tmp_path / "test_bw.png"
        wav.write_bytes(b"\x00" * 100)
        img.write_bytes(b"\x89PNG")

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder") as MockD, \
             patch("weather_station.cleaner.Cleaner"), \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = wav
            MockD.return_value.decode.return_value = (img, None)
            result = cmd_receive(config, "NOAA 19", 60)

        assert result is True
        assert "Telegram" in capsys.readouterr().out

    def test_prints_image_paths(self, tmp_path, capsys):
        config = _make_config()
        config.satellites = self._sat_map()
        config.paths.recordings_dir = str(tmp_path)
        wav = tmp_path / "test.wav"
        img = tmp_path / "test_bw.png"
        wav.write_bytes(b"\x00" * 100)
        img.write_bytes(b"\x89PNG")

        with patch("weather_station.receiver.Receiver") as MockR, \
             patch("weather_station.decoder.Decoder") as MockD, \
             patch("weather_station.cleaner.Cleaner"), \
             patch("weather_station.main._paused_services"):
            MockR.return_value.record.return_value = wav
            MockD.return_value.decode.return_value = (img, None)
            cmd_receive(config, "NOAA 19", 60)

        assert "test_bw.png" in capsys.readouterr().out


# ─── cmd_scan ────────────────────────────────────────────────────────────────

_SCAN_CSV = (
    "2024-01-01, 12:00:00, 137620000, 138000000, 5000, 64, -72.3\n"
    "2024-01-01, 12:00:00, 137100000, 138000000, 5000, 64, -85.0\n"
)


class TestCmdScan:

    def test_rtl_power_not_installed_prints_message(self, capsys):
        config = _make_config()
        with patch("weather_station.cli.shutil.which", return_value=None):
            cmd_scan(config)
        assert "rtl_power" in capsys.readouterr().out

    def test_rtl_power_timeout_prints_message(self, capsys):
        config = _make_config()
        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("rtl_power", 20)):
            cmd_scan(config)
        assert "tardo" in capsys.readouterr().out

    def test_scan_file_not_generated_prints_message(self, capsys):
        config = _make_config()
        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run", return_value=MagicMock()):
            cmd_scan(config)
        assert "No se genero" in capsys.readouterr().out

    def test_rtl_power_file_not_found_prints_message(self, capsys):
        config = _make_config()
        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run", side_effect=FileNotFoundError):
            cmd_scan(config)
        assert "no disponible" in capsys.readouterr().out

    def test_successful_scan_prints_table(self, capsys):
        config = _make_config()
        config.satellites = {
            "NOAA 15": _sat_cfg(137620000),
            "NOAA 19": _sat_cfg(137100000),
        }

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text(_SCAN_CSV)
            return MagicMock()

        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run", side_effect=fake_run):
            cmd_scan(config)

        out = capsys.readouterr().out
        assert "NOAA 15" in out
        assert "dBm" in out
        assert "Ruido" in out

    def test_scan_passes_competing_services_to_paused(self):
        config = _make_config()
        config.capture.competing_services = ["dump1090-fa"]

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text(_SCAN_CSV)
            return MagicMock()

        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services") as mock_paused, \
             patch("weather_station.cli.subprocess.run", side_effect=fake_run):
            cmd_scan(config)

        mock_paused.assert_called_once_with(["dump1090-fa"])

    def test_signal_detected_when_power_10db_above_noise(self, capsys):
        config = _make_config()
        config.satellites = {
            "NOAA 15": _sat_cfg(137620000),
            "NOAA 19": _sat_cfg(137100000),
        }
        # NOAA 15 at -60 dBm vs noise floor -85 dBm → delta = 25 ≥ 10 → SENAL DETECTADA
        strong_csv = (
            "2024-01-01, 12:00:00, 137620000, 138000000, 5000, 64, -60.0\n"
            "2024-01-01, 12:00:00, 137100000, 138000000, 5000, 64, -85.0\n"
        )

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text(strong_csv)
            return MagicMock()

        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run", side_effect=fake_run):
            cmd_scan(config)

        assert "SENAL DETECTADA" in capsys.readouterr().out

    def test_no_data_in_csv_shows_sin_datos(self, capsys):
        config = _make_config()
        config.satellites = {"NOAA 15": _sat_cfg(137620000)}

        def fake_run(cmd, **kw):
            # Write CSV with data far from NOAA 15 frequency
            Path(cmd[-1]).write_text(
                "2024-01-01, 12:00:00, 100000000, 101000000, 5000, 64, -72.3\n"
            )
            return MagicMock()

        with patch("weather_station.cli.shutil.which", return_value="/usr/bin/rtl_power"), \
             patch("weather_station.main._paused_services"), \
             patch("weather_station.cli.subprocess.run", side_effect=fake_run):
            cmd_scan(config)

        assert "sin datos" in capsys.readouterr().out
