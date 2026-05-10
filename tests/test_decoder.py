from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from weather_station.decoder import Decoder


@pytest.fixture
def decoder():
    return Decoder()


@pytest.fixture
def wav_file(tmp_path):
    f = tmp_path / "NOAA_15_20240101_120000.wav"
    f.write_bytes(b"\x00" * 512)
    return f


class TestDecode:
    def test_returns_none_when_wav_missing(self, decoder, tmp_path):
        bw, thermal = decoder.decode(tmp_path / "missing.wav")
        assert bw is None
        assert thermal is None

    def test_successful_decode_returns_both_images(self, decoder, wav_file):
        def fake_run_noaa_apt(wav, out, extra_args):
            out.write_bytes(b"\x89PNG")
            return True

        with patch.object(decoder, "_run_noaa_apt", side_effect=fake_run_noaa_apt):
            bw, thermal = decoder.decode(wav_file)

        assert bw is not None and bw.name.endswith("_bw.png")
        assert thermal is not None and thermal.name.endswith("_thermal.png")

    def test_returns_none_for_failed_decode(self, decoder, wav_file):
        with patch.object(decoder, "_run_noaa_apt", return_value=False):
            bw, thermal = decoder.decode(wav_file)
        assert bw is None
        assert thermal is None

    def test_partial_success(self, decoder, wav_file):
        def fake_run(wav, out, extra_args):
            if "_bw" in str(out):
                out.write_bytes(b"\x89PNG")
                return True
            return False

        with patch.object(decoder, "_run_noaa_apt", side_effect=fake_run):
            bw, thermal = decoder.decode(wav_file)

        assert bw is not None
        assert thermal is None


class TestRunNoaaApt:
    def test_success(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(cmd, **kwargs):
            out.write_bytes(b"\x89PNG")
            return mock_result

        with patch("weather_station.decoder.subprocess.run", side_effect=fake_run):
            result = decoder._run_noaa_apt(wav_file, out, [])

        assert result is True

    def test_returns_false_on_nonzero_exit(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error message"

        with patch("weather_station.decoder.subprocess.run", return_value=mock_result):
            result = decoder._run_noaa_apt(wav_file, out, [])

        assert result is False

    def test_returns_false_when_noaa_apt_not_found(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        with patch("weather_station.decoder.subprocess.run", side_effect=FileNotFoundError):
            result = decoder._run_noaa_apt(wav_file, out, [])
        assert result is False

    def test_returns_false_on_timeout(self, decoder, wav_file, tmp_path):
        import subprocess

        out = tmp_path / "out.png"
        with patch("weather_station.decoder.subprocess.run", side_effect=subprocess.TimeoutExpired("noaa-apt", 300)):
            result = decoder._run_noaa_apt(wav_file, out, [])
        assert result is False

    def test_returns_false_when_output_file_not_created(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        mock_result = MagicMock()
        mock_result.returncode = 0
        # Don't create out.png — noaa-apt returned 0 but wrote nothing

        with patch("weather_station.decoder.subprocess.run", return_value=mock_result):
            result = decoder._run_noaa_apt(wav_file, out, [])

        assert result is False

    def test_returns_false_on_generic_exception(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        with patch("weather_station.decoder.subprocess.run",
                   side_effect=RuntimeError("unexpected")):
            result = decoder._run_noaa_apt(wav_file, out, [])
        assert result is False

    def test_extra_args_passed_to_command(self, decoder, wav_file, tmp_path):
        out = tmp_path / "out.png"
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            out.write_bytes(b"\x89PNG")
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("weather_station.decoder.subprocess.run", side_effect=fake_run):
            decoder._run_noaa_apt(wav_file, out, ["--contrast", "telemetry"])

        assert "--contrast" in captured_cmd
        assert "telemetry" in captured_cmd
