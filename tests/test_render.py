"""Tests for the static-site renderer.

These build a real Store in a temp dir, feed it observations + a poll, render the
site, and assert on the emitted HTML — exercising the full read path without a
network or a browser.
"""

from html.parser import HTMLParser
from pathlib import Path

from taifu.parse import Observation
from taifu.render import render_site
from taifu.store import Store

_GEN = "2026-06-25T07:00:00+00:00"


def _obs(valid_time, *, number="2607", name="MEKKHALA", pressure=None, wind=None, speed=None):
    return Observation(
        typhoon_number=number,
        name=name,
        name_kana="",
        report_time=valid_time,
        kind="analysis",
        valid_time=valid_time,
        pressure_hpa=pressure,
        max_wind_mps=wind,
        move_speed_kmh=speed,
        move_dir="北東" if speed else None,
        lat=23.9 if pressure else None,
        lon=125.9 if pressure else None,
    )


def _store_with_series(tmp_path: Path) -> Store:
    store = Store(tmp_path / "data")
    store.insert_observations(
        [
            _obs("2026-06-24T12:00:00+09:00", pressure=1000, wind=30, speed=30),
            _obs("2026-06-25T00:00:00+09:00", pressure=990, wind=40, speed=20),
            _obs("2026-06-25T12:00:00+09:00", pressure=985, wind=45, speed=15),
        ]
    )
    store.record_poll([{"typhoonNumber": "2607", "tropicalCyclone": "T2607", "category": "STS"}])
    return store


def _assert_parses(html: str) -> None:
    HTMLParser().feed(html)  # raises on malformed markup


def test_renders_index_and_detail(tmp_path):
    with _store_with_series(tmp_path) as store:
        written = render_site(store, tmp_path / "site", generated_at=_GEN)

    names = {p.name for p in written}
    assert "index.html" in names
    assert "typhoon-2607.html" in names

    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    _assert_parses(index)
    assert "MEKKHALA" in index
    assert "Severe Tropical Storm" in index  # grade code STS expanded
    assert "Active" in index
    # Pressure fell 1000 -> 985, so the verdict must be "intensifying".
    assert "Intensifying" in index
    assert 'href="typhoon-2607.html"' in index

    detail = (tmp_path / "site" / "typhoon-2607.html").read_text(encoding="utf-8")
    _assert_parses(detail)
    assert "<svg" in detail  # sparklines present
    assert "1000" in detail and "985" in detail  # history table values


def test_blank_number_gets_no_page(tmp_path):
    store = Store(tmp_path / "data")
    store.insert_observations(
        [
            _obs("2026-06-19T09:00:00+09:00", number="", name="", pressure=1006),
            _obs("2026-06-19T12:00:00+09:00", number="", name="", pressure=1004),
        ]
    )
    with store:
        written = render_site(store, tmp_path / "site", generated_at=_GEN)
    assert {p.name for p in written} == {"index.html"}
    assert not (tmp_path / "site" / "typhoon-.html").exists()


def test_empty_store_still_writes_index(tmp_path):
    store = Store(tmp_path / "data")
    with store:
        written = render_site(store, tmp_path / "site", generated_at=_GEN)
    assert [p.name for p in written] == ["index.html"]
    index = written[0].read_text(encoding="utf-8")
    _assert_parses(index)
    assert "No typhoon history yet" in index
