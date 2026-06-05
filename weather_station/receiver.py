import logging
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Receiver:
    def __init__(
        self,
        recordings_dir: str,
        gain: float = 44.5,
        rtl_sample_rate: int = 60000,
        final_sample_rate: int = 11025,
        ppm: int = 0,
        device_index: int = 0,
    ):
        self.recordings_dir = Path(recordings_dir)
        self.gain = gain
        self.rtl_sample_rate = rtl_sample_rate
        self.final_sample_rate = final_sample_rate
        self.ppm = ppm
        self.device_index = device_index

    def _build_commands(self, frequency: int, output_file: Path) -> tuple[list[str], list[str]]:
        rtl_fm = [
            "rtl_fm",
            "-d", str(self.device_index),
            "-f", str(frequency),
            "-M", "wbfm",
            "-s", str(self.rtl_sample_rate),  # wide capture bandwidth for APT signal
            "-g", str(self.gain),
            "-p", str(self.ppm),
            # No -r: resampling is delegated to sox for better quality
        ]
        sox = [
            "sox",
            "-t", "raw",
            "-r", str(self.rtl_sample_rate),  # input: raw PCM at tuner rate
            "-e", "signed-integer",
            "-b", "16",
            "-c", "1",
            "-",
            "-t", "wav",
            str(output_file),
            "rate", str(self.final_sample_rate),  # resample to noaa-apt target rate
        ]
        return rtl_fm, sox

    def record(
        self,
        frequency: int,
        duration_seconds: float,
        satellite_name: str,
    ) -> Path | None:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = satellite_name.replace(" ", "_")
        output_file = self.recordings_dir / f"{safe_name}_{ts}.wav"

        rtl_cmd, sox_cmd = self._build_commands(frequency, output_file)
        logger.info(
            "Recording %s at %d Hz for %.0fs -> %s",
            satellite_name, frequency, duration_seconds, output_file.name,
        )

        rtl_proc = None
        sox_proc = None
        try:
            rtl_proc = subprocess.Popen(
                rtl_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            sox_proc = subprocess.Popen(
                sox_cmd,
                stdin=rtl_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            rtl_proc.stdout.close()

            time.sleep(duration_seconds)

            rtl_proc.send_signal(signal.SIGTERM)
            sox_proc.send_signal(signal.SIGTERM)
            _, rtl_stderr = rtl_proc.communicate(timeout=10)
            _, sox_stderr = sox_proc.communicate(timeout=10)

            if rtl_proc.returncode not in (0, -15):  # -15 = SIGTERM, expected
                logger.error("rtl_fm exited with code %d: %s",
                             rtl_proc.returncode, rtl_stderr.decode(errors="replace").strip())
            if sox_proc.returncode not in (0, -15):
                logger.error("sox exited with code %d: %s",
                             sox_proc.returncode, sox_stderr.decode(errors="replace").strip())

            size = output_file.stat().st_size if output_file.exists() else 0
            # Minimum: 50% of expected uncompressed PCM size at final_sample_rate
            min_expected = int(duration_seconds * self.final_sample_rate * 2 * 0.5)
            if size < min_expected:
                logger.error(
                    "Recording too small (%.1f MB, expected >%.1f MB for %.0fs) — "
                    "rtl_fm likely failed. Check: device connected? user in 'plugdev' group?",
                    size / 1e6, min_expected / 1e6, duration_seconds,
                )
                if output_file.exists():
                    output_file.unlink()
                return None

            logger.info("Recording saved: %s (%.1f MB)", output_file.name, size / 1e6)
            return output_file

        except FileNotFoundError as e:
            logger.error("Required command not found: %s", e)
            return None
        except subprocess.TimeoutExpired:
            logger.error("Processes did not terminate in time, killing")
            for proc in (rtl_proc, sox_proc):
                if proc:
                    proc.kill()
            return None
        except Exception as e:
            logger.error("Recording failed: %s", e)
            return None
