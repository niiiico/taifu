"""Tests for trend classification."""

from taifu.parse import Observation
from taifu.trends import compute_trend


def _obs(valid_time, *, pressure=None, wind=None, speed=None, number="2603"):
    return Observation(
        typhoon_number=number,
        name="JANGMI",
        name_kana="チャンミー",
        report_time=valid_time,
        kind="analysis",
        valid_time=valid_time,
        pressure_hpa=pressure,
        max_wind_mps=wind,
        move_speed_kmh=speed,
    )


def test_needs_two_observations():
    assert compute_trend([_obs("2026-06-06T09:00:00+09:00", pressure=990)]) is None


def test_intensifying_when_pressure_falls():
    series = [
        _obs("2026-06-06T00:00:00+09:00", pressure=990, wind=30, speed=25),
        _obs("2026-06-06T12:00:00+09:00", pressure=975, wind=40, speed=25),
    ]
    t = compute_trend(series)
    assert t.intensification == "intensifying"
    assert t.pressure_delta == -15
    # 15 hPa drop over 12h -> ~ -30 hPa/24h
    assert round(t.pressure_rate_24h) == -30


def test_weakening_when_pressure_rises():
    series = [
        _obs("2026-06-06T00:00:00+09:00", pressure=960, wind=45),
        _obs("2026-06-06T12:00:00+09:00", pressure=985, wind=30),
    ]
    assert compute_trend(series).intensification == "weakening"


def test_slowing_motion():
    series = [
        _obs("2026-06-06T00:00:00+09:00", speed=30),
        _obs("2026-06-06T12:00:00+09:00", speed=15),
    ]
    assert compute_trend(series).motion == "slowing"


def test_stalling_when_near_zero():
    series = [
        _obs("2026-06-06T00:00:00+09:00", speed=10),
        _obs("2026-06-06T12:00:00+09:00", speed=5),
    ]
    assert compute_trend(series).motion == "stalling"


def test_window_limits_reference_point():
    # Oldest point is outside a 24h window, so it must be ignored.
    series = [
        _obs("2026-06-01T00:00:00+09:00", pressure=1000),  # far in the past
        _obs("2026-06-06T00:00:00+09:00", pressure=980),
        _obs("2026-06-06T12:00:00+09:00", pressure=979),
    ]
    t = compute_trend(series, window_hours=24.0)
    # Reference is the 06-06T00 point (-1 hPa), not the 06-01 point (-21).
    assert t.pressure_delta == -1
    assert t.intensification == "steady"
