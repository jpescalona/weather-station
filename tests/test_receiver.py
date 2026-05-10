import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from weather_station.receiver import Receiver

# For record(duration_seconds=60.0): min_expected = 60 * 11025 * 2 * 0.5 = 661 500 bytes
_DURATION = 60.0
MIN_WAV_BYTES = int(_DURATION * 11025 * 2 * 0.5) + 1


def _make_procs(wav_path: Path | None = None):
    """Return (rtl_proc, sox_proc) mocks with sane defaults."""
    rtl_proc = MagicMock()
    sox_proc = MagicMock()
    rtl_proc.stdout = MagicMock()
    rtl_proc.returncode = 0
    sox_proc.returncode = 0
    rtl_proc.communicate.return_value = (b"", b"")
    sox_proc.communicate.return_value = (b"", b"")
    if wav_path is not None:
        wav_path.write_bytes(b"\x00" * MIN_WAV_BYTES)
    return rtl_proc, sox_proc


@pytest.fixture
def receiver(tmp_path):
    return Receiver(
        recordings_dir=str(tmp_path),
        gain=44.5,
        rtl_sample_rate=60000,
        final_sample_rate=11025,
        ppm=0,
    )


class TestBuildCommands:
    def test_rtl_fm_frequency(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        assert "-f" in rtl
        assert "137620000" in rtl

    def test_rtl_fm_uses_rtl_sample_rate(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        idx = rtl.index("-s")
        assert rtl[idx + 1] == "60000"

    def test_rtl_fm_wbfm_mode(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        assert "wbfm" in rtl

    def test_rtl_fm_no_dash_r(self, receiver, tmp_path):
        # Resampling is done by sox; rtl_fm must not duplicate it with -r
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        assert "-r" not in rtl

    def test_rtl_fm_ppm_flag(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        idx = rtl.index("-p")
        assert rtl[idx + 1] == "0"

    def test_no_wav_header_flag(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        assert "-E" not in rtl

    def test_gain_applied(self, receiver, tmp_path):
        rtl, _ = receiver._build_commands(137620000, tmp_path / "out.wav")
        idx = rtl.index("-g")
        assert rtl[idx + 1] == "44.5"

    def test_sox_reads_at_rtl_sample_rate(self, receiver, tmp_path):
        _, sox = receiver._build_commands(137620000, tmp_path / "out.wav")
        idx = sox.index("-r")
        assert sox[idx + 1] == "60000"

    def test_sox_resamples_to_final_rate(self, receiver, tmp_path):
        _, sox = receiver._build_commands(137620000, tmp_path / "out.wav")
        assert "rate" in sox
        idx = sox.index("rate")
        assert sox[idx + 1] == "11025"

    def test_sox_output_is_wav(self, receiver, tmp_path):
        out = tmp_path / "out.wav"
        _, sox = receiver._build_commands(137620000, out)
        assert "-t" in sox
        idx = sox.index("-t", sox.index("-t") + 1)  # second -t is the output format
        assert sox[idx + 1] == "wav"
        assert str(out) in sox

    def test_sox_output_file(self, receiver, tmp_path):
        out = tmp_path / "out.wav"
        _, sox = receiver._build_commands(137620000, out)
        assert str(out) in sox


class TestRecord:
    def test_successful_recording(self, receiver, tmp_path):
        rtl_proc, sox_proc = _make_procs()

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * MIN_WAV_BYTES)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is not None
        assert result.suffix == ".wav"
        assert "NOAA_15" in result.name

    def test_returns_none_when_rtl_fm_not_found(self, receiver):
        with patch("weather_station.receiver.subprocess.Popen", side_effect=FileNotFoundError("rtl_fm")):
            result = receiver.record(137620000, _DURATION, "NOAA 15")
        assert result is None

    def test_returns_none_when_output_file_too_small(self, receiver, tmp_path):
        rtl_proc, sox_proc = _make_procs()

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * 100)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is None

    def test_returns_none_when_output_file_missing(self, receiver):
        rtl_proc, sox_proc = _make_procs()
        with patch("weather_station.receiver.subprocess.Popen", side_effect=[rtl_proc, sox_proc]):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")
        assert result is None

    def test_creates_recordings_directory(self, tmp_path):
        new_dir = tmp_path / "deep" / "recordings"
        rec = Receiver(recordings_dir=str(new_dir))
        rtl_proc, sox_proc = _make_procs()
        with patch("weather_station.receiver.subprocess.Popen", side_effect=[rtl_proc, sox_proc]):
            with patch("weather_station.receiver.time.sleep"):
                rec.record(137620000, _DURATION, "NOAA 15")
        assert new_dir.exists()

    def test_sends_sigterm_on_completion(self, receiver, tmp_path):
        rtl_proc, sox_proc = _make_procs()

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * MIN_WAV_BYTES)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                receiver.record(137620000, _DURATION, "NOAA 15")

        rtl_proc.send_signal.assert_called_with(signal.SIGTERM)
        sox_proc.send_signal.assert_called_with(signal.SIGTERM)

    def test_logs_error_when_rtl_fm_exits_nonzero(self, receiver, tmp_path):
        rtl_proc, sox_proc = _make_procs()
        rtl_proc.returncode = 1  # non-zero, non-SIGTERM → log error but file may still be valid
        rtl_proc.communicate.return_value = (b"", b"rtl_fm error msg")

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * MIN_WAV_BYTES)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is not None  # file big enough → still returned

    def test_logs_error_when_sox_exits_nonzero(self, receiver, tmp_path):
        rtl_proc, sox_proc = _make_procs()
        sox_proc.returncode = 1
        sox_proc.communicate.return_value = (b"", b"sox error")

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * MIN_WAV_BYTES)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is not None  # file big enough → still returned

    def test_returns_none_on_communicate_timeout(self, receiver):
        import subprocess as sp

        rtl_proc, sox_proc = _make_procs()
        rtl_proc.communicate.side_effect = sp.TimeoutExpired("rtl_fm", 10)

        with patch("weather_station.receiver.subprocess.Popen",
                   side_effect=[rtl_proc, sox_proc]):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is None
        rtl_proc.kill.assert_called_once()
        sox_proc.kill.assert_called_once()

    def test_returns_none_on_unexpected_exception(self, receiver):
        rtl_proc, sox_proc = _make_procs()

        with patch("weather_station.receiver.subprocess.Popen",
                   side_effect=[rtl_proc, sox_proc]):
            with patch("weather_station.receiver.time.sleep",
                       side_effect=RuntimeError("unexpected")):
                result = receiver.record(137620000, _DURATION, "NOAA 15")

        assert result is None

    def test_minimum_size_proportional_to_duration(self, receiver, tmp_path):
        # For a 300s pass, minimum = 300 * 11025 * 2 * 0.5 = 3 307 500 bytes
        long_duration = 300.0
        small_size = 1_000_000  # 1 MB — below threshold for 300s
        rtl_proc, sox_proc = _make_procs()

        def popen_side(cmd, **kwargs):
            if "rtl_fm" in cmd[0]:
                return rtl_proc
            for arg in cmd:
                if arg.endswith(".wav"):
                    Path(arg).write_bytes(b"\x00" * small_size)
            return sox_proc

        with patch("weather_station.receiver.subprocess.Popen", side_effect=popen_side):
            with patch("weather_station.receiver.time.sleep"):
                result = receiver.record(137620000, long_duration, "NOAA 15")

        assert result is None
