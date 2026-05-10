import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import ephem
import pytest

from weather_station.predictor import Predictor, SatellitePass


def _make_pass_info(aos_offset_days=0.1, max_alt_deg=45.0, duration_days=0.01):
    now = ephem.now()
    aos = now + aos_offset_days
    los = aos + duration_days
    max_alt_time = aos + duration_days / 2
    return (
        aos,
        ephem.degrees("0"),
        max_alt_time,
        ephem.degrees(math.radians(max_alt_deg)),  # float → ephem treats as radians
        los,
        ephem.degrees("180"),
    )


@pytest.fixture
def predictor():
    # ephem.Observer.next_pass is a read-only C-extension method; patch the
    # class so that self.observer becomes a MagicMock we can configure freely.
    with patch("weather_station.predictor.ephem.Observer"):
        p = Predictor(latitude=36.5, longitude=-4.6, altitude=78, min_elevation=20.0)
    return p  # p.observer is a MagicMock even after the context manager exits


class TestGetNextPass:
    def test_returns_pass_above_min_elevation(self, predictor):
        predictor.observer.next_pass.return_value = _make_pass_info(max_alt_deg=45.0)

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000)

        assert result is not None
        assert isinstance(result, SatellitePass)
        assert result.satellite == "NOAA 15"
        assert result.frequency == 137620000
        assert result.max_elevation == pytest.approx(45.0, abs=0.5)
        assert result.aos.tzinfo == timezone.utc
        assert result.los.tzinfo == timezone.utc

    def test_skips_passes_below_min_elevation(self, predictor):
        low_pass = _make_pass_info(max_alt_deg=5.0)
        high_pass = _make_pass_info(aos_offset_days=0.5, max_alt_deg=50.0)
        call_count = 0

        def side_effect(sat):
            nonlocal call_count
            call_count += 1
            return low_pass if call_count == 1 else high_pass

        predictor.observer.next_pass.side_effect = side_effect

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000)

        assert result is not None
        assert result.max_elevation == pytest.approx(50.0, abs=0.5)

    def test_returns_none_on_exception(self, predictor):
        with patch("weather_station.predictor.ephem.readtle", side_effect=ValueError("bad TLE")):
            result = predictor.get_next_pass("NOAA 15", "bad", "bad", 137620000)
        assert result is None

    def test_returns_none_when_all_passes_too_low(self, predictor):
        predictor.observer.next_pass.return_value = _make_pass_info(max_alt_deg=5.0)

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000)

        assert result is None


class TestSatellitePassProperties:
    def test_duration_seconds(self):
        aos = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        los = datetime(2024, 1, 1, 12, 12, 0, tzinfo=timezone.utc)
        sat_pass = SatellitePass("NOAA 15", aos, los, 45.0, 137620000)
        assert sat_pass.duration_seconds == 720.0


class TestGetNextPassAfterParam:
    def test_after_parameter_sets_observer_date(self, predictor):
        """Passing after= hits the `if after is not None` branch (line 52)."""
        predictor.observer.next_pass.return_value = _make_pass_info(max_alt_deg=45.0)
        after_dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000, after=after_dt)

        assert result is not None
        # observer.date was set from the after datetime
        assert predictor.observer.date is not None

    def test_circumpolar_error_breaks_loop_and_returns_none(self, predictor):
        """CircumpolarError from next_pass hits lines 72-73 (except/break)."""
        predictor.observer.next_pass.side_effect = ephem.CircumpolarError("circumpolar")

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000)

        assert result is None

    def test_value_error_from_next_pass_returns_none(self, predictor):
        predictor.observer.next_pass.side_effect = ValueError("invalid")

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            result = predictor.get_next_pass("NOAA 15", "tle1", "tle2", 137620000)

        assert result is None


class TestGetAllNextPasses:
    def test_returns_sorted_passes(self, predictor):
        pass_early = _make_pass_info(aos_offset_days=0.1, max_alt_deg=40.0)
        pass_late = _make_pass_info(aos_offset_days=0.5, max_alt_deg=60.0)
        call_count = [0]

        def side_effect(sat):
            call_count[0] += 1
            return pass_late if call_count[0] % 2 == 1 else pass_early

        predictor.observer.next_pass.side_effect = side_effect

        sats = {
            "NOAA 15": ("tle1", "tle2", 137620000),
            "NOAA 18": ("tle3", "tle4", 137912500),
        }

        with patch("weather_station.predictor.ephem.readtle", return_value=MagicMock()):
            passes = predictor.get_all_next_passes(sats)

        assert len(passes) == 2
        assert passes[0].aos <= passes[1].aos
