from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from weather_station.main import (
    _paused_services,
    build_satellite_map,
    handle_pass,
    setup_logging,
)
from weather_station.predictor import SatellitePass


AOS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
LOS = datetime(2024, 1, 1, 12, 12, 0, tzinfo=timezone.utc)
SAMPLE_PASS = SatellitePass("NOAA 15", AOS, LOS, 45.0, 137620000)


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.capture.post_record_seconds = 30
    cfg.cleanup.delete_wav = True
    cfg.cleanup.delete_png = True
    return cfg


@pytest.fixture
def mock_receiver(tmp_path):
    receiver = MagicMock()
    wav = tmp_path / "NOAA_15_20240101.wav"
    wav.write_bytes(b"\x00" * 100)
    receiver.record.return_value = wav
    return receiver, wav


@pytest.fixture
def mock_decoder(tmp_path):
    decoder = MagicMock()
    bw = tmp_path / "img_bw.png"
    thermal = tmp_path / "img_thermal.png"
    bw.write_bytes(b"\x89PNG")
    thermal.write_bytes(b"\x89PNG")
    decoder.decode.return_value = (bw, thermal)
    return decoder, [bw, thermal]


class TestHandlePass:
    def test_full_success_cleans_all_files(self, mock_config, mock_receiver, mock_decoder):
        receiver, wav = mock_receiver
        decoder, images = mock_decoder
        sender = MagicMock()
        sender.send.return_value = True
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, sender, cleaner, mock_config)

        receiver.record.assert_called_once()
        decoder.decode.assert_called_once_with(wav)
        sender.send.assert_called_once()
        cleaner.cleanup.assert_called_once()
        cleaned = cleaner.cleanup.call_args[0][0]
        assert wav in cleaned
        assert all(img in cleaned for img in images)

    def test_recording_failure_aborts_pipeline(self, mock_config, mock_decoder):
        receiver = MagicMock()
        receiver.record.return_value = None
        decoder, _ = mock_decoder
        sender = MagicMock()
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, sender, cleaner, mock_config)

        decoder.decode.assert_not_called()
        sender.send.assert_not_called()

    def test_decode_failure_cleans_wav_only(self, mock_config, mock_receiver):
        receiver, wav = mock_receiver
        decoder = MagicMock()
        decoder.decode.return_value = (None, None)
        sender = MagicMock()
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, sender, cleaner, mock_config)

        sender.send.assert_not_called()
        cleaner.cleanup.assert_called_once_with([wav])

    def test_send_failure_keeps_files(self, mock_config, mock_receiver, mock_decoder):
        receiver, wav = mock_receiver
        decoder, images = mock_decoder
        sender = MagicMock()
        sender.send.return_value = False
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, sender, cleaner, mock_config)

        cleaner.cleanup.assert_not_called()

    def test_no_sender_skips_send_and_cleanup(self, mock_config, mock_receiver, mock_decoder):
        receiver, _ = mock_receiver
        decoder, _ = mock_decoder
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, None, cleaner, mock_config)

        cleaner.cleanup.assert_not_called()

    def test_duration_includes_post_record_seconds(self, mock_config, mock_receiver, mock_decoder):
        mock_config.capture.post_record_seconds = 60
        receiver, _ = mock_receiver
        decoder, _ = mock_decoder
        sender = MagicMock()
        sender.send.return_value = True
        cleaner = MagicMock()

        handle_pass(SAMPLE_PASS, receiver, decoder, sender, cleaner, mock_config)

        _, kwargs = receiver.record.call_args
        # SAMPLE_PASS duration is 720s, plus 60s post = 780s
        assert kwargs["duration_seconds"] == pytest.approx(780.0)


class TestBuildSatelliteMap:
    def test_includes_satellites_with_valid_tle(self):
        config = MagicMock()
        config.satellites = {
            "NOAA 15": MagicMock(frequency=137620000),
            "NOAA 18": MagicMock(frequency=137912500),
        }
        tle_manager = MagicMock()
        tle_manager.get_tle.side_effect = lambda name: ("tle1", "tle2") if "15" in name else None

        result = build_satellite_map(config, tle_manager)

        assert "NOAA 15" in result
        assert "NOAA 18" not in result
        assert result["NOAA 15"] == ("tle1", "tle2", 137620000)

    def test_returns_empty_when_no_tle_available(self):
        config = MagicMock()
        config.satellites = {"NOAA 15": MagicMock(frequency=137620000)}
        tle_manager = MagicMock()
        tle_manager.get_tle.return_value = None

        result = build_satellite_map(config, tle_manager)

        assert result == {}


# ─── setup_logging ────────────────────────────────────────────────────────────

class TestSetupLogging:
    def test_creates_log_parent_directory(self, tmp_path):
        log_file = str(tmp_path / "logs" / "app.log")
        setup_logging(log_file)
        assert (tmp_path / "logs").exists()

    def test_accepts_already_existing_directory(self, tmp_path):
        log_file = str(tmp_path / "app.log")
        setup_logging(log_file)  # should not raise


# ─── _paused_services ─────────────────────────────────────────────────────────

class TestPausedServices:
    def test_stops_and_restarts_service(self):
        with patch("weather_station.main.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with _paused_services(["dump1090-fa"]):
                pass

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert ["sudo", "systemctl", "stop", "dump1090-fa"] in cmds
        assert ["sudo", "systemctl", "start", "dump1090-fa"] in cmds

    def test_does_not_restart_if_stop_failed(self):
        with patch("weather_station.main.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            with _paused_services(["dump1090-fa"]):
                pass

        assert mock_run.call_count == 1  # only the stop attempt

    def test_restarts_even_when_body_raises(self):
        with patch("weather_station.main.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with pytest.raises(ValueError):
                with _paused_services(["dump1090-fa"]):
                    raise ValueError("body error")

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert ["sudo", "systemctl", "start", "dump1090-fa"] in cmds

    def test_exception_during_stop_is_swallowed(self):
        with patch("weather_station.main.subprocess.run", side_effect=OSError("no sudo")):
            with _paused_services(["dump1090-fa"]):
                pass  # must not raise

    def test_empty_services_list_makes_no_calls(self):
        with patch("weather_station.main.subprocess.run") as mock_run:
            with _paused_services([]):
                pass
        mock_run.assert_not_called()

    def test_multiple_services_all_stopped_and_restarted(self):
        with patch("weather_station.main.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with _paused_services(["svc1", "svc2"]):
                pass

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert ["sudo", "systemctl", "stop", "svc1"] in cmds
        assert ["sudo", "systemctl", "stop", "svc2"] in cmds
        assert ["sudo", "systemctl", "start", "svc1"] in cmds
        assert ["sudo", "systemctl", "start", "svc2"] in cmds

    def test_restart_exception_is_swallowed(self):
        stop_r = MagicMock()
        stop_r.returncode = 0

        def run_side(cmd, **kw):
            if cmd[2] == "stop":
                return stop_r
            raise OSError("cannot start")

        with patch("weather_station.main.subprocess.run", side_effect=run_side):
            with _paused_services(["dump1090-fa"]):
                pass  # must not raise on restart failure


# ─── main() loop ─────────────────────────────────────────────────────────────

class TestMainLoop:
    """Smoke-tests for the daemon loop via controlled SystemExit breaks."""

    def _common_patches(self, mock_cfg, mock_tle, mock_pred, sleep_side):
        return [
            patch("weather_station.main.load_config", return_value=mock_cfg),
            patch("weather_station.main.setup_logging"),
            patch("weather_station.main.TLEManager", return_value=mock_tle),
            patch("weather_station.main.Predictor", return_value=mock_pred),
            patch("weather_station.main.Receiver"),
            patch("weather_station.main.Decoder"),
            patch("weather_station.main.Cleaner"),
            patch("weather_station.main.time.sleep", side_effect=sleep_side),
        ]

    def _make_cfg(self):
        cfg = MagicMock()
        cfg.capture.pre_record_seconds = 30
        cfg.capture.competing_services = []
        cfg.telegram.bot_token = ""
        cfg.telegram.chat_id = ""
        cfg.satellites = {"NOAA 15": MagicMock(norad_id=25338)}
        return cfg

    def _run_main(self, mock_cfg, mock_tle, mock_pred, sleep_side, extra_patches=None):
        from weather_station.main import main

        with ExitStack() as stack:
            stack.enter_context(pytest.raises(SystemExit))
            for p in self._common_patches(mock_cfg, mock_tle, mock_pred, sleep_side):
                stack.enter_context(p)
            if extra_patches:
                for p in extra_patches:
                    stack.enter_context(p)
            main()

    def test_tle_failure_sleeps_300s(self):
        sleep_calls = []

        def mock_sleep(s):
            sleep_calls.append(s)
            raise SystemExit

        mock_cfg = self._make_cfg()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = False

        self._run_main(mock_cfg, mock_tle, MagicMock(), mock_sleep)
        assert 300 in sleep_calls

    def test_no_satellites_sleeps_1800s(self):
        sleep_calls = []

        def mock_sleep(s):
            sleep_calls.append(s)
            raise SystemExit

        mock_cfg = self._make_cfg()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True

        self._run_main(
            mock_cfg, mock_tle, MagicMock(), mock_sleep,
            extra_patches=[patch("weather_station.main.build_satellite_map", return_value={})],
        )
        assert 1800 in sleep_calls

    def test_no_passes_sleeps_1800s(self):
        sleep_calls = []

        def mock_sleep(s):
            sleep_calls.append(s)
            raise SystemExit

        mock_cfg = self._make_cfg()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_pred = MagicMock()
        mock_pred.get_all_next_passes.return_value = []

        self._run_main(
            mock_cfg, mock_tle, mock_pred, mock_sleep,
            extra_patches=[
                patch("weather_station.main.build_satellite_map",
                       return_value={"NOAA 15": ("t1", "t2", 137620000)}),
            ],
        )
        assert 1800 in sleep_calls

    def test_normal_flow_calls_handle_pass(self):
        call_count = [0]

        def mock_sleep(s):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise SystemExit

        mock_cfg = self._make_cfg()
        mock_tle = MagicMock()
        mock_tle.update_if_needed.return_value = True
        mock_pred = MagicMock()

        now = datetime.now(timezone.utc)
        sat_pass = SatellitePass(
            "NOAA 15",
            aos=now + timedelta(minutes=30),
            los=now + timedelta(minutes=42),
            max_elevation=45.0,
            frequency=137620000,
        )
        mock_pred.get_all_next_passes.return_value = [sat_pass]
        mock_handle = MagicMock()

        self._run_main(
            mock_cfg, mock_tle, mock_pred, mock_sleep,
            extra_patches=[
                patch("weather_station.main.build_satellite_map",
                       return_value={"NOAA 15": ("t1", "t2", 137620000)}),
                patch("weather_station.main.handle_pass", mock_handle),
            ],
        )
        mock_handle.assert_called_once()
