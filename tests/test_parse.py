"""Tests for the JMA payload parsers."""

from pathlib import Path

from taifu.parse import parse_bulletin, parse_target_tc

FIXTURE = Path(__file__).parent / "fixtures" / "typhoon_sample.xml"


def test_parse_bulletin_analysis_fields():
    obs = parse_bulletin(FIXTURE.read_bytes())
    analysis = [o for o in obs if o.kind == "analysis"]
    assert len(analysis) == 1
    a = analysis[0]
    assert a.typhoon_number == "2603"
    assert a.name == "JANGMI"
    assert a.name_kana == "チャンミー"
    assert a.report_time == "2026-06-06T09:00:00+09:00"
    assert a.valid_time == "2026-06-06T09:00:00+09:00"
    assert a.lat == 24.0
    assert a.lon == 135.0
    assert a.pressure_hpa == 990
    assert a.max_wind_mps == 30
    assert a.max_gust_mps == 45
    assert a.move_dir == "北東"
    assert a.move_speed_kmh == 20  # the km/h value, not the knots one
    assert a.intensity_class == "強い"
    assert a.size_class == "大型"


def test_parse_bulletin_includes_forecast():
    obs = parse_bulletin(FIXTURE.read_bytes())
    forecast = [o for o in obs if o.kind == "forecast"]
    assert len(forecast) == 1
    f = forecast[0]
    assert f.valid_time == "2026-06-07T09:00:00+09:00"
    assert f.pressure_hpa == 975
    assert f.max_wind_mps == 40
    # Name/number resolved at document level even though absent in this block.
    assert f.typhoon_number == "2603"


def test_parse_target_tc_dedupes_by_number():
    rows = [
        {"typhoonNumber": "2603", "tropicalCyclone": "T2603", "category": "TY"},
        {"typhoonNumber": "2603", "tropicalCyclone": "T2603", "category": "TY"},
        {"typhoonNumber": "2604", "tropicalCyclone": "T2604", "category": "TS"},
    ]
    active = parse_target_tc(rows)
    assert {a.number for a in active} == {"2603", "2604"}
    assert {a.category for a in active} == {"TY", "TS"}


def test_parse_target_tc_empty():
    assert parse_target_tc([]) == []
