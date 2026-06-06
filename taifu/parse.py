"""Parsers for the JMA payloads into flat, storable records.

The typhoon bulletin XML uses several XML namespaces (``jmaxml``,
``elementBasis`` …). Rather than bind to exact namespace URIs — which makes the
parser brittle if JMA bumps a schema minor version — we match on the *local*
element name and on the ``type`` attribute, which are the parts JMA keeps
stable. Anything we fail to recognise is simply left as ``None``; the raw XML is
always archived alongside, so a missed field can be back-filled later.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Optional

# --- targetTc.json -----------------------------------------------------------


@dataclass(frozen=True)
class ActiveTyphoon:
    """A row from ``targetTc.json`` (the cheap "what's active now" signal)."""

    number: str  # JMA typhoon number, e.g. "2603"
    tc_id: str  # internal id used in bosai URLs, e.g. "T2603"
    category: str  # grade code, e.g. "TD", "TS", "STS", "TY", "LOW"


def parse_target_tc(rows: list[dict]) -> list[ActiveTyphoon]:
    """Normalise raw ``targetTc.json`` rows, de-duplicating by typhoon number.

    The file can list a cyclone more than once (per ensemble member); we only
    care about the distinct storms and their grade.
    """
    seen: dict[str, ActiveTyphoon] = {}
    for row in rows:
        number = str(row.get("typhoonNumber") or row.get("number") or "").strip()
        if not number:
            continue
        tc_id = str(row.get("tropicalCyclone") or "").strip()
        category = str(row.get("category") or "").strip()
        seen.setdefault(number, ActiveTyphoon(number=number, tc_id=tc_id, category=category))
    return list(seen.values())


# --- typhoon bulletin XML ----------------------------------------------------


@dataclass
class Observation:
    """A single typhoon state at one time, from one bulletin.

    ``kind`` distinguishes 実況 (analysis — the actual current state, which is
    what trends are computed from) from 予報/推定 (forecast/estimate).
    """

    typhoon_number: str
    name: str
    name_kana: str
    report_time: str  # when the bulletin was issued (ISO-8601)
    kind: str  # "analysis" | "estimate" | "forecast"
    valid_time: str  # the time this state applies to (ISO-8601)
    lat: Optional[float] = None
    lon: Optional[float] = None
    pressure_hpa: Optional[int] = None
    max_wind_mps: Optional[int] = None
    max_gust_mps: Optional[int] = None
    move_dir: Optional[str] = None
    move_speed_kmh: Optional[int] = None
    move_speed_text: Optional[str] = None  # e.g. "ゆっくり", "ほとんど停滞"
    intensity_class: Optional[str] = None  # 強さ: 強い / 非常に強い / 猛烈な
    size_class: Optional[str] = None  # 大きさ: 大型 / 超大型

    def as_dict(self) -> dict:
        return asdict(self)


_KIND_MAP = {"実況": "analysis", "推定": "estimate", "予報": "forecast"}
_COORD_RE = re.compile(r"([+-]\d+(?:\.\d+)?)")


def parse_bulletin(raw: bytes) -> list[Observation]:
    """Parse one 台風解析・予報情報 XML document into Observation records."""
    root = ET.fromstring(raw)

    report_time = _first_text(root, "ReportDateTime") or _first_text(root, "TargetDateTime") or ""

    # Name/number live in the 呼称 property; they may appear only once in the
    # document, so resolve them at document level and apply to every entry.
    number = _first_text(root, "Number") or ""
    name = _first_text(root, "Name") or ""
    name_kana = _first_text(root, "NameKana") or ""

    observations: list[Observation] = []
    for info in _iter_local(root, "MeteorologicalInfo"):
        obs = _parse_info(info, report_time, number, name, name_kana)
        if obs is not None:
            observations.append(obs)
    return observations


def _parse_info(
    info: ET.Element, report_time: str, number: str, name: str, name_kana: str
) -> Optional[Observation]:
    dt = _find_local(info, "DateTime")
    valid_time = (dt.text or "").strip() if dt is not None else ""
    kind_attr = dt.get("type", "") if dt is not None else ""
    kind = _KIND_MAP.get(kind_attr, kind_attr or "unknown")

    obs = Observation(
        typhoon_number=number,
        name=name,
        name_kana=name_kana,
        report_time=report_time,
        kind=kind,
        valid_time=valid_time,
    )

    lat, lon = _coordinate(info)
    obs.lat, obs.lon = lat, lon
    obs.pressure_hpa = _int(_typed(info, "Pressure", "中心気圧"))
    obs.max_wind_mps = _int(_typed(info, "WindSpeed", "最大風速"))
    obs.max_gust_mps = _int(_typed(info, "WindSpeed", "最大瞬間風速"))

    direction = _find_typed(info, "Direction", "移動方向")
    if direction is not None:
        obs.move_dir = (direction.text or "").strip() or None

    speed = _find_typed(info, "Speed", "移動速度", unit_contains="km")
    if speed is not None:
        text = (speed.text or "").strip()
        obs.move_speed_kmh = _int(text)
        if obs.move_speed_kmh is None and text:
            obs.move_speed_text = text  # qualitative, e.g. "ゆっくり"
        # JMA also encodes a qualitative descriptor on the element.
        desc = speed.get("description")
        if desc:
            obs.move_speed_text = desc.strip()

    obs.intensity_class = _typed(info, None, "強さ") or _class_value(info, "強さの階級")
    obs.size_class = _typed(info, None, "大きさ") or _class_value(info, "大きさの階級")
    return obs


# --- small XML helpers (all namespace-agnostic) ------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_local(root: ET.Element, name: str):
    for el in root.iter():
        if _localname(el.tag) == name:
            yield el


def _find_local(root: ET.Element, name: str) -> Optional[ET.Element]:
    for el in root.iter():
        if _localname(el.tag) == name:
            return el
    return None


def _first_text(root: ET.Element, name: str) -> Optional[str]:
    el = _find_local(root, name)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _find_typed(
    root: ET.Element, name: Optional[str], type_contains: str, *, unit_contains: str = ""
) -> Optional[ET.Element]:
    """Find the first element (optionally by local name) whose ``type`` attribute
    contains ``type_contains`` and whose ``unit`` contains ``unit_contains``."""
    for el in root.iter():
        if name is not None and _localname(el.tag) != name:
            continue
        if type_contains not in el.get("type", ""):
            continue
        if unit_contains and unit_contains not in el.get("unit", ""):
            continue
        return el
    return None


def _typed(
    root: ET.Element, name: Optional[str], type_contains: str, *, unit_contains: str = ""
) -> Optional[str]:
    el = _find_typed(root, name, type_contains, unit_contains=unit_contains)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _class_value(root: ET.Element, kind: str) -> Optional[str]:
    """Resolve a typhoon classification (強さ/大きさ) given as a <Type>…</Type>
    sibling of a value element under a Property."""
    for prop in _iter_local(root, "Property"):
        type_el = _find_local(prop, "Type")
        if type_el is not None and (type_el.text or "").strip() == kind:
            for child in prop.iter():
                if child is type_el:
                    continue
                if child.text and child.text.strip() and _localname(child.tag) != "Type":
                    return child.text.strip()
    return None


def _coordinate(info: ET.Element) -> tuple[Optional[float], Optional[float]]:
    """Extract (lat, lon) in decimal degrees from the centre coordinate."""
    # Prefer the decimal-degree form (type contains "度"); fall back to any.
    el = _find_typed(info, "Coordinate", "度")
    if el is None:
        el = _find_local(info, "Coordinate")
    if el is None or not el.text:
        return None, None
    nums = _COORD_RE.findall(el.text)
    if len(nums) >= 2:
        try:
            return float(nums[0]), float(nums[1])
        except ValueError:
            return None, None
    return None, None


def _int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"-?\d+", text)
    return int(m.group()) if m else None
