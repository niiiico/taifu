"""Turn a time series of analysis observations into a trend verdict.

Headline questions this answers, per typhoon:

* **Growing?** Central pressure is the cleanest intensity proxy — *falling*
  pressure means intensifying. Maximum wind corroborates.
* **Slowing down?** Movement speed dropping (and how close to stationary it is)
  — JMA itself labels ≲15 km/h "ゆっくり" (slowly) and ≲5 km/h "ほとんど停滞"
  (almost stationary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .parse import Observation

# Thresholds (deliberately conservative to avoid noise from rounding).
_PRESSURE_HPA = 2  # min change over the window to call a pressure trend
_WIND_MPS = 5
_SPEED_KMH = 5
_STALL_KMH = 5  # at/below this, treat as effectively stationary
_SLOW_KMH = 15  # at/below this, "moving slowly"


@dataclass
class Trend:
    number: str
    name: str
    n_obs: int
    span_hours: float
    window_hours: float
    first: Observation
    last: Observation
    pressure_delta: Optional[int]  # last - reference; negative = deepening
    wind_delta: Optional[int]
    speed_delta: Optional[int]
    pressure_rate_24h: Optional[float]
    intensification: str  # "intensifying" | "weakening" | "steady" | "unknown"
    motion: str  # "accelerating" | "slowing" | "steady" | "stalling" | "unknown"
    grade_change: Optional[str]  # e.g. "強い → 非常に強い" or "大型 → 超大型"


def parse_time(value: str) -> Optional[datetime]:
    """Parse a JMA ISO-8601 timestamp (e.g. ``2026-06-06T09:00:00+09:00``)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:  # tolerate a trailing Z
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def compute_trend(observations: list[Observation], *, window_hours: float = 24.0) -> Optional[Trend]:
    """Compute a Trend over the most recent ``window_hours`` of analysis data.

    Returns ``None`` if there are not at least two observations to compare.
    """
    obs = _sorted_with_time(observations)
    if len(obs) < 2:
        return None

    last_t, last = obs[-1]
    first_t, first = obs[0]
    window_start = last_t - timedelta(hours=window_hours)

    # Reference = earliest observation still inside the window (else the oldest).
    ref_t, ref = next(((t, o) for t, o in obs if t >= window_start), obs[0])
    span_hours = (last_t - ref_t).total_seconds() / 3600.0

    pressure_delta = _delta(ref.pressure_hpa, last.pressure_hpa)
    wind_delta = _delta(ref.max_wind_mps, last.max_wind_mps)
    speed_delta = _delta(ref.move_speed_kmh, last.move_speed_kmh)

    pressure_rate = None
    if pressure_delta is not None and span_hours > 0:
        pressure_rate = pressure_delta / span_hours * 24.0

    return Trend(
        number=last.typhoon_number,
        name=last.name or first.name,
        n_obs=len(obs),
        span_hours=span_hours,
        window_hours=window_hours,
        first=first,
        last=last,
        pressure_delta=pressure_delta,
        wind_delta=wind_delta,
        speed_delta=speed_delta,
        pressure_rate_24h=pressure_rate,
        intensification=_classify_intensity(pressure_delta, wind_delta),
        motion=_classify_motion(last.move_speed_kmh, speed_delta),
        grade_change=_grade_change(ref, last),
    )


def _sorted_with_time(observations: list[Observation]) -> list[tuple[datetime, Observation]]:
    timed = [(parse_time(o.valid_time), o) for o in observations]
    timed = [(t, o) for t, o in timed if t is not None]
    timed.sort(key=lambda x: x[0])
    return timed


def _delta(start: Optional[float], end: Optional[float]) -> Optional[int]:
    if start is None or end is None:
        return None
    return int(round(end - start))


def _classify_intensity(pressure_delta: Optional[int], wind_delta: Optional[int]) -> str:
    if pressure_delta is None and wind_delta is None:
        return "unknown"
    # Falling pressure is the primary signal.
    if pressure_delta is not None and pressure_delta <= -_PRESSURE_HPA:
        return "intensifying"
    if pressure_delta is not None and pressure_delta >= _PRESSURE_HPA:
        return "weakening"
    # Pressure flat/unknown: fall back to wind.
    if wind_delta is not None and wind_delta >= _WIND_MPS:
        return "intensifying"
    if wind_delta is not None and wind_delta <= -_WIND_MPS:
        return "weakening"
    return "steady"


def _classify_motion(speed_now: Optional[int], speed_delta: Optional[int]) -> str:
    if speed_now is not None and speed_now <= _STALL_KMH:
        return "stalling"
    if speed_delta is None:
        # No trend available; still flag slow absolute motion if known.
        if speed_now is not None and speed_now <= _SLOW_KMH:
            return "slowing"
        return "unknown"
    if speed_delta <= -_SPEED_KMH:
        return "slowing"
    if speed_delta >= _SPEED_KMH:
        return "accelerating"
    return "steady"


def _grade_change(ref: Observation, last: Observation) -> Optional[str]:
    for attr in ("intensity_class", "size_class"):
        a = getattr(ref, attr)
        b = getattr(last, attr)
        if a and b and a != b:
            return f"{a} → {b}"
    return None
