import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# NOAA 15/18/19 are not in any CelesTrak group; must be fetched individually.
CELESTRAK_TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=tle"


class TLEManager:
    def __init__(
        self,
        tle_file: str,
        satellites: dict[str, int],  # {name: norad_id}
        max_age_hours: int = 24,
    ):
        self.tle_file = Path(tle_file)
        self.satellites = satellites
        self.max_age_hours = max_age_hours

    def needs_update(self) -> bool:
        if not self.tle_file.exists():
            return True
        mtime = datetime.fromtimestamp(self.tle_file.stat().st_mtime)
        return datetime.now() - mtime > timedelta(hours=self.max_age_hours)

    def download(self) -> bool:
        blocks = []
        for name, norad_id in self.satellites.items():
            url = CELESTRAK_TLE_URL.format(norad_id=norad_id)
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                blocks.append(response.text.strip())
                logger.info("Downloaded TLE for %s (NORAD %s)", name, norad_id)
            except requests.RequestException as e:
                logger.error("Failed to download TLE for %s (NORAD %s): %s", name, norad_id, e)
                return False

        self.tle_file.parent.mkdir(parents=True, exist_ok=True)
        self.tle_file.write_text("\n".join(blocks) + "\n")
        logger.info("TLE data saved to %s", self.tle_file)
        return True

    def update_if_needed(self) -> bool:
        if self.needs_update():
            return self.download()
        logger.debug("TLE data is up to date")
        return True

    def get_tle(self, satellite_name: str) -> tuple[str, str] | None:
        if not self.tle_file.exists():
            logger.error("TLE file not found: %s", self.tle_file)
            return None

        lines = [ln.strip() for ln in self.tle_file.read_text().splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            name_match = satellite_name.upper() in line.upper()
            is_name_line = not (line.startswith("1 ") or line.startswith("2 "))
            if name_match and is_name_line and i + 2 < len(lines):
                tle1, tle2 = lines[i + 1], lines[i + 2]
                if tle1.startswith("1 ") and tle2.startswith("2 "):
                    return tle1, tle2

        logger.error("TLE data for '%s' not found", satellite_name)
        return None
