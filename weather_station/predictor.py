import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import ephem

logger = logging.getLogger(__name__)


@dataclass
class SatellitePass:
    satellite: str
    aos: datetime
    los: datetime
    max_elevation: float
    frequency: int

    @property
    def duration_seconds(self) -> float:
        return (self.los - self.aos).total_seconds()


class Predictor:
    def __init__(
        self,
        latitude: float,
        longitude: float,
        altitude: float,
        min_elevation: float = 20.0,
    ):
        self.min_elevation = min_elevation
        self.observer = ephem.Observer()
        self.observer.lat = str(latitude)
        self.observer.long = str(longitude)
        self.observer.elevation = float(altitude)
        self.observer.pressure = 0  # disable atmospheric refraction
        self.observer.horizon = str(math.radians(min_elevation))

    def get_next_pass(
        self,
        satellite_name: str,
        tle1: str,
        tle2: str,
        frequency: int,
        after: datetime | None = None,
    ) -> SatellitePass | None:
        try:
            sat = ephem.readtle(satellite_name, tle1, tle2)
            # after allows callers to search beyond the current pass (e.g. to list several passes)
            if after is not None:
                self.observer.date = ephem.Date(after.replace(tzinfo=None))
            else:
                self.observer.date = ephem.now()

            # Search up to 20 consecutive passes to find one above min elevation
            for _ in range(20):
                try:
                    aos_t, _, _, max_alt, los_t, _ = self.observer.next_pass(sat)
                    max_elevation = math.degrees(float(max_alt))

                    if max_elevation >= self.min_elevation:
                        return SatellitePass(
                            satellite=satellite_name,
                            aos=ephem.Date(aos_t).datetime().replace(tzinfo=timezone.utc),
                            los=ephem.Date(los_t).datetime().replace(tzinfo=timezone.utc),
                            max_elevation=max_elevation,
                            frequency=frequency,
                        )
                    # Advance past this low pass and try next
                    self.observer.date = ephem.Date(los_t) + ephem.minute
                except (ValueError, ephem.CircumpolarError):
                    break

            logger.warning("No pass above %.0f° found for %s", self.min_elevation, satellite_name)
            return None

        except Exception as e:
            logger.error("Error predicting pass for %s: %s", satellite_name, e)
            return None

    def get_all_next_passes(
        self,
        satellites: dict[str, tuple[str, str, int]],
    ) -> list[SatellitePass]:
        passes = []
        for name, (tle1, tle2, frequency) in satellites.items():
            sat_pass = self.get_next_pass(name, tle1, tle2, frequency)
            if sat_pass:
                passes.append(sat_pass)
        return sorted(passes, key=lambda p: p.aos)
