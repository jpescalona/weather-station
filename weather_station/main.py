import logging
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from weather_station.cleaner import Cleaner
from weather_station.config import Config, load_config
from weather_station.decoder import Decoder
from weather_station.predictor import Predictor, SatellitePass
from weather_station.receiver import Receiver
from weather_station.sender import ImageSender, TelegramSender
from weather_station.tle_manager import TLEManager

logger = logging.getLogger(__name__)


def setup_logging(log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


@contextmanager
def _paused_services(services: list[str]):
    """Stop competing RTL-SDR services before recording, restart them after."""
    stopped = []
    for svc in services:
        try:
            result = subprocess.run(
                ["sudo", "systemctl", "stop", svc],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0:
                stopped.append(svc)
                logger.info("Stopped competing service: %s", svc)
            else:
                logger.warning("Could not stop %s (rc=%d): %s", svc, result.returncode,
                               result.stderr.decode(errors="replace").strip())
        except Exception as e:
            logger.warning("Failed to stop service %s: %s", svc, e)
    try:
        yield
    finally:
        for svc in stopped:
            try:
                subprocess.run(["sudo", "systemctl", "start", svc],
                               capture_output=True, timeout=15)
                logger.info("Restarted service: %s", svc)
            except Exception as e:
                logger.warning("Failed to restart service %s: %s", svc, e)


def handle_pass(
    sat_pass: SatellitePass,
    receiver: Receiver,
    decoder: Decoder,
    sender: ImageSender | None,
    cleaner: Cleaner,
    config: Config,
) -> None:
    logger.info(
        "Pass starting: %s (duration %.0fs, max el %.1f°)",
        sat_pass.satellite,
        sat_pass.duration_seconds,
        sat_pass.max_elevation,
    )

    duration = sat_pass.duration_seconds + config.capture.post_record_seconds
    with _paused_services(config.capture.competing_services):
        wav_file = receiver.record(
            frequency=sat_pass.frequency,
            duration_seconds=duration,
            satellite_name=sat_pass.satellite,
        )

    if not wav_file:
        logger.error("Recording failed for %s", sat_pass.satellite)
        return

    bw_image, thermal_image = decoder.decode(wav_file)
    images = [img for img in (bw_image, thermal_image) if img is not None]

    if not images:
        logger.error("Decoding produced no images for %s", sat_pass.satellite)
        cleaner.cleanup([wav_file])
        return

    if sender:
        sent_ok = sender.send(images, sat_pass.satellite, sat_pass.aos)
        if sent_ok:
            cleaner.cleanup([wav_file] + images)
        else:
            logger.warning("Send failed — files kept for manual retry: %s", wav_file.parent)
    else:
        logger.warning("No sender configured — images saved to %s", wav_file.parent)


def build_satellite_map(
    config: Config,
    tle_manager: TLEManager,
) -> dict[str, tuple[str, str, int]]:
    satellites = {}
    for name, sat_cfg in config.satellites.items():
        tle = tle_manager.get_tle(name)
        if tle:
            satellites[name] = (tle[0], tle[1], sat_cfg.frequency)
        else:
            logger.warning("Could not load TLE for %s — skipping", name)
    return satellites


def main() -> None:
    config = load_config()
    setup_logging(config.paths.log_file)
    logger.info("NOAA weather station starting (v%s)", "0.1.0")

    satellites_norad = {name: sat.norad_id for name, sat in config.satellites.items()}
    tle_manager = TLEManager(
        tle_file=config.tle.file,
        satellites=satellites_norad,
        max_age_hours=config.tle.max_age_hours,
    )
    predictor = Predictor(
        latitude=config.location.latitude,
        longitude=config.location.longitude,
        altitude=config.location.altitude,
        min_elevation=config.capture.min_elevation,
    )
    receiver = Receiver(
        recordings_dir=config.paths.recordings_dir,
        gain=config.capture.gain,
        rtl_sample_rate=config.capture.rtl_sample_rate,
        final_sample_rate=config.capture.final_sample_rate,
        ppm=config.capture.ppm,
    )
    decoder = Decoder()
    cleaner = Cleaner(
        delete_wav=config.cleanup.delete_wav,
        delete_png=config.cleanup.delete_png,
    )
    sender: ImageSender | None = None
    if config.telegram.bot_token and config.telegram.chat_id:
        sender = TelegramSender(config.telegram.bot_token, config.telegram.chat_id)
    else:
        logger.warning("Telegram credentials not set — images will not be sent")

    while True:
        if not tle_manager.update_if_needed():
            logger.error("TLE update failed, retrying in 5 minutes")
            time.sleep(300)
            continue

        satellites = build_satellite_map(config, tle_manager)
        if not satellites:
            logger.error("No TLE data available for any satellite, retrying in 30 minutes")
            time.sleep(1800)
            continue

        passes = predictor.get_all_next_passes(satellites)
        if not passes:
            logger.warning("No upcoming passes found, retrying in 30 minutes")
            time.sleep(1800)
            continue

        next_pass = passes[0]
        now = datetime.now(timezone.utc)
        wait_seconds = (next_pass.aos - now).total_seconds() - config.capture.pre_record_seconds

        if wait_seconds > 0:
            logger.info(
                "Next: %s at %s (in %.0f min, max el %.1f°)",
                next_pass.satellite,
                next_pass.aos.strftime("%Y-%m-%d %H:%M UTC"),
                wait_seconds / 60,
                next_pass.max_elevation,
            )
            time.sleep(wait_seconds)

        handle_pass(next_pass, receiver, decoder, sender, cleaner, config)

        # Brief pause between passes to avoid re-scheduling the same one
        time.sleep(10)


if __name__ == "__main__":
    main()
