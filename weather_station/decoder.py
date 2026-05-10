import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class Decoder:
    def decode(self, wav_file: Path) -> tuple[Path | None, Path | None]:
        if not wav_file.exists():
            logger.error("WAV file not found: %s", wav_file)
            return None, None

        stem = wav_file.stem
        out_dir = wav_file.parent
        bw_image = out_dir / f"{stem}_bw.png"
        thermal_image = out_dir / f"{stem}_thermal.png"

        bw_ok = self._run_noaa_apt(wav_file, bw_image, extra_args=[])
        thermal_ok = self._run_noaa_apt(wav_file, thermal_image, extra_args=["--contrast", "telemetry"])

        return (
            bw_image if bw_ok else None,
            thermal_image if thermal_ok else None,
        )

    def _run_noaa_apt(self, wav_file: Path, output_file: Path, extra_args: list[str]) -> bool:
        cmd = ["noaa-apt", "--output", str(output_file)] + extra_args + [str(wav_file)]
        logger.info("Decoding %s -> %s", wav_file.name, output_file.name)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                output = (result.stderr or result.stdout).strip()
                logger.error("noaa-apt failed (exit %d): %s", result.returncode, output or "(no output)")
                return False
            if not output_file.exists():
                logger.error("noaa-apt produced no output file: %s", output_file)
                return False
            logger.info("Decoded image: %s", output_file.name)
            return True
        except FileNotFoundError:
            logger.error("noaa-apt not found. Install it via: make install-noaa-apt")
            return False
        except subprocess.TimeoutExpired:
            logger.error("noaa-apt timed out processing %s", wav_file.name)
            return False
        except Exception as e:
            logger.error("Decoding failed: %s", e)
            return False
