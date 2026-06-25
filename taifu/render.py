"""Render the local store into a small static website (no JS, no CDN).

The output is plain HTML with inline CSS and inline-SVG sparklines, so it can be
served verbatim by GitHub Pages with no build step and no runtime dependencies —
matching the project's "zero dependencies" rule. Two kinds of page are written:

* ``index.html`` — an overview: every tracked typhoon with its current state and
  the intensifying/weakening + motion verdict, newest first, active storms on top.
* ``typhoon-<number>.html`` — one per storm: the full analysis time series as a
  table, plus sparklines for central pressure, maximum wind and movement speed.

Everything here is a pure function of the data passed in (including the
``generated_at`` stamp), so it is deterministic and testable off a fixture.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .parse import Observation
from .store import Store
from .trends import Trend, compute_trend, parse_time

# Friendly names for the targetTc.json grade codes.
_GRADE_NAME = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "STS": "Severe Tropical Storm",
    "TY": "Typhoon",
    "L": "Low",
    "LOW": "Low",
}

_INTENSITY_LABEL = {
    "intensifying": "Intensifying",
    "weakening": "Weakening",
    "steady": "Steady",
    "unknown": "Unknown",
}
_MOTION_LABEL = {
    "stalling": "Stalling (≈stationary)",
    "slowing": "Slowing down",
    "accelerating": "Speeding up",
    "steady": "Steady speed",
    "unknown": "Motion unknown",
}
# CSS class per verdict, for colour coding.
_INTENSITY_CLASS = {
    "intensifying": "bad",
    "weakening": "good",
    "steady": "neutral",
    "unknown": "muted",
}
_MOTION_CLASS = {
    "stalling": "bad",
    "slowing": "warn",
    "accelerating": "neutral",
    "steady": "neutral",
    "unknown": "muted",
}

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
       color: #1a1a1a; background: #f4f5f7; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e8ea; background: #15171b; }
  .card, header { background: #1f2228 !important; border-color: #2c3038 !important; }
  a { color: #6db3ff; }
  th { border-color: #2c3038 !important; }
  td { border-color: #23262c !important; }
}
header { background: #0b3d68; color: #fff; padding: 18px 20px; }
header.dark { background: #0b3d68; }
header h1 { margin: 0; font-size: 20px; }
header .sub { opacity: .8; font-size: 13px; margin-top: 4px; }
header a { color: #cfe6ff; }
main { max-width: 880px; margin: 0 auto; padding: 20px; }
.card { background: #fff; border: 1px solid #e2e4e8; border-radius: 10px;
        padding: 16px 18px; margin: 0 0 16px; }
.card h2 { margin: 0 0 2px; font-size: 18px; }
.card h2 a { text-decoration: none; }
.grade { font-size: 13px; opacity: .75; }
.badges { margin: 10px 0 4px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px;
         font-size: 13px; font-weight: 600; margin: 2px 6px 2px 0; }
.badge.bad { background: #fde0e0; color: #a31515; }
.badge.warn { background: #fdf0d8; color: #8a5a00; }
.badge.good { background: #dff3e2; color: #1d6b32; }
.badge.neutral { background: #e3e7ef; color: #33415c; }
.badge.muted { background: #e8e8ea; color: #555; }
.badge.active { background: #0b3d68; color: #fff; }
.badge.ended { background: #d8d8dc; color: #444; }
.facts { margin: 8px 0 0; font-size: 14px; }
.facts span { display: inline-block; margin-right: 16px; white-space: nowrap; }
.facts b { font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; width: 100%; font-size: 13px;
        font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid #eceef2; }
th:first-child, td:first-child { text-align: left; white-space: nowrap; }
th { border-bottom: 2px solid #d7dae0; }
.spark { margin: 6px 0 2px; }
.spark .lbl { font-size: 12px; opacity: .7; }
.muted-note { font-size: 13px; opacity: .7; }
footer { text-align: center; font-size: 12px; opacity: .6; padding: 24px 0; }
"""


@dataclass
class _StormView:
    number: str
    name: str
    grade: str  # category code from the latest poll ("" if not currently active)
    active: bool
    trend: Optional[Trend]
    obs: list  # list[Observation], analysis only, oldest→newest


def render_site(
    store: Store,
    out_dir: Path,
    *,
    generated_at: str,
    window_hours: float = 24.0,
) -> list[Path]:
    """Write the static site into ``out_dir`` and return the paths written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    active = {a.number: a.category for a in store.latest_active()}
    views: list[_StormView] = []
    for number in store.typhoon_numbers(kind="analysis"):
        if not number.strip():
            # Pre-numbering bulletins (a developing low before JMA assigns a
            # number) land under "". They have no stable identity to page on.
            continue
        obs = store.observations_for(number, kind="analysis")
        views.append(
            _StormView(
                number=number,
                name=store.latest_name(number) or "",
                grade=active.get(number, ""),
                active=number in active,
                trend=compute_trend(obs, window_hours=window_hours),
                obs=obs,
            )
        )
    # Active storms first, then by most recent observation.
    views.sort(key=lambda v: (v.active, _last_time(v.obs)), reverse=True)

    written: list[Path] = []
    index = out_dir / "index.html"
    index.write_text(_render_index(views, generated_at=generated_at), encoding="utf-8")
    written.append(index)
    for v in views:
        page = out_dir / f"typhoon-{v.number}.html"
        page.write_text(_render_detail(v, generated_at=generated_at), encoding="utf-8")
        written.append(page)
    return written


# --- pages -------------------------------------------------------------------


def _render_index(views: list[_StormView], *, generated_at: str) -> str:
    cards = [_index_card(v) for v in views] or [
        '<div class="card"><p class="muted-note">No typhoon history yet. '
        "Run <code>taifu poll</code> (ideally on a schedule).</p></div>"
    ]
    body = (
        _header(
            "台風 taifu — typhoon trends",
            'Caches JMA bulletins so you can see whether a storm is '
            '<b>intensifying</b> or <b>slowing/stalling</b>.',
            generated_at,
        )
        + '<main>\n' + "\n".join(cards) + "\n" + _footer() + "</main>"
    )
    return _doc("台風 taifu — typhoon trends", body)


def _index_card(v: _StormView) -> str:
    title = f"#{v.number}" + (f" {_esc(v.name)}" if v.name else "")
    grade = _GRADE_NAME.get(v.grade, v.grade)
    grade_line = f'<div class="grade">{_esc(grade)}</div>' if grade else ""
    status = (
        '<span class="badge active">Active</span>'
        if v.active
        else '<span class="badge ended">No longer listed active</span>'
    )

    badges = [status]
    facts = ""
    if v.trend is not None:
        t = v.trend
        badges.append(
            f'<span class="badge {_INTENSITY_CLASS[t.intensification]}">'
            f"{_INTENSITY_LABEL[t.intensification]}</span>"
        )
        badges.append(
            f'<span class="badge {_MOTION_CLASS[t.motion]}">{_MOTION_LABEL[t.motion]}</span>'
        )
        facts = _fact_line(t)
    else:
        badges.append('<span class="badge muted">Not enough history yet</span>')

    return (
        '<div class="card">\n'
        f'  <h2><a href="typhoon-{v.number}.html">{title}</a></h2>\n'
        f"  {grade_line}\n"
        f'  <div class="badges">{" ".join(badges)}</div>\n'
        f"  {facts}\n"
        "</div>"
    )


def _render_detail(v: _StormView, *, generated_at: str) -> str:
    title = f"#{v.number}" + (f" {_esc(v.name)}" if v.name else "")
    grade = _GRADE_NAME.get(v.grade, v.grade)
    sub = _esc(grade) if grade else "Analysis history"

    parts = [
        _header(f"台風 {title}", sub + ' &middot; <a href="index.html">← all storms</a>',
                generated_at)
    ]
    parts.append('<main>')

    if v.trend is not None:
        t = v.trend
        badges = (
            f'<span class="badge {_INTENSITY_CLASS[t.intensification]}">'
            f"{_INTENSITY_LABEL[t.intensification]}</span> "
            f'<span class="badge {_MOTION_CLASS[t.motion]}">{_MOTION_LABEL[t.motion]}</span>'
        )
        parts.append(
            '<div class="card">\n'
            f'  <div class="badges">{badges}</div>\n'
            f"  {_fact_line(t)}\n"
            f'  <p class="muted-note">Trend over the last {t.span_hours:.0f}h '
            f"({t.n_window} of {t.n_obs} analysis bulletins; window {t.window_hours:.0f}h).</p>\n"
            "</div>"
        )

    # Sparklines (need at least two points to be meaningful).
    spark_obs = v.obs
    if len(spark_obs) >= 2:
        parts.append(
            '<div class="card">\n'
            + _spark_block("Central pressure (hPa)", spark_obs, "pressure_hpa", invert=True)
            + _spark_block("Maximum wind (m/s)", spark_obs, "max_wind_mps")
            + _spark_block("Movement speed (km/h)", spark_obs, "move_speed_kmh")
            + "</div>"
        )

    parts.append('<div class="card">' + _history_table(v.obs) + "</div>")
    parts.append(_footer())
    parts.append("</main>")
    return _doc(f"台風 {title}", "\n".join(parts))


# --- fragments ---------------------------------------------------------------


def _fact_line(t: Trend) -> str:
    o = t.last
    bits: list[str] = []
    if o.pressure_hpa is not None:
        dp = f" ({t.pressure_delta:+d}/{t.span_hours:.0f}h)" if t.pressure_delta is not None else ""
        bits.append(f"<span>Pressure <b>{o.pressure_hpa}</b> hPa{dp}</span>")
    if o.max_wind_mps is not None:
        dw = f" ({t.wind_delta:+d})" if t.wind_delta is not None else ""
        bits.append(f"<span>Max wind <b>{o.max_wind_mps}</b> m/s{dw}</span>")
    if o.move_speed_kmh is not None:
        heading = f" {_esc(o.move_dir)}" if o.move_dir else ""
        bits.append(f"<span>Speed <b>{o.move_speed_kmh}</b> km/h{heading}</span>")
    elif o.move_speed_text:
        bits.append(f"<span>Speed <b>{_esc(o.move_speed_text)}</b></span>")
    if o.lat is not None and o.lon is not None:
        bits.append(f"<span>Position <b>{o.lat:.1f}N {o.lon:.1f}E</b></span>")
    if o.valid_time:
        bits.append(f'<span class="muted-note">@ {_esc(_short_time(o.valid_time))}</span>')
    return f'<div class="facts">{"".join(bits)}</div>' if bits else ""


def _history_table(obs: list[Observation]) -> str:
    head = (
        "<table>\n<thead><tr>"
        "<th>Valid time</th><th>Pres</th><th>Wind</th><th>Gust</th>"
        "<th>Speed</th><th>Dir</th><th>Position</th>"
        "</tr></thead>\n<tbody>\n"
    )
    rows = []
    for o in reversed(obs):  # newest first
        pos = f"{o.lat:.1f}N {o.lon:.1f}E" if o.lat is not None and o.lon is not None else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(_short_time(o.valid_time))}</td>"
            f"<td>{_num(o.pressure_hpa)}</td>"
            f"<td>{_num(o.max_wind_mps)}</td>"
            f"<td>{_num(o.max_gust_mps)}</td>"
            f"<td>{_num(o.move_speed_kmh)}</td>"
            f"<td>{_esc(o.move_dir or '')}</td>"
            f"<td>{_esc(pos)}</td>"
            "</tr>"
        )
    return head + "\n".join(rows) + "\n</tbody>\n</table>"


def _spark_block(label: str, obs: list[Observation], attr: str, *, invert: bool = False) -> str:
    pts = [(parse_time(o.valid_time), getattr(o, attr)) for o in obs]
    series = [(t, v) for t, v in pts if t is not None and v is not None]
    if len(series) < 2:
        return ""
    values = [v for _, v in series]
    svg = _sparkline([float(v) for v in values], invert=invert)
    return (
        f'<div class="spark"><div class="lbl">{_esc(label)}: '
        f"{values[0]} → {values[-1]}</div>{svg}</div>"
    )


def _sparkline(values: list[float], *, width: int = 720, height: int = 44, invert: bool = False) -> str:
    """Return an inline SVG line for ``values`` (x = even spacing by index)."""
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    pad = 4
    n = len(values)

    def y(v: float) -> float:
        frac = (v - lo) / span
        if invert:  # e.g. pressure: lower value = "stronger" = draw higher
            frac = 1 - frac
        return pad + (1 - frac) * (height - 2 * pad)

    def x(i: int) -> float:
        return pad + i * (width - 2 * pad) / (n - 1)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    last_x, last_y = x(n - 1), y(values[-1])
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        'preserveAspectRatio="none" role="img" aria-hidden="true">'
        f'<polyline fill="none" stroke="#0b78c2" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{pts}"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#0b78c2"/>'
        "</svg>"
    )


# --- chrome ------------------------------------------------------------------


def _doc(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _header(title: str, sub_html: str, generated_at: str) -> str:
    return (
        '<header class="dark">\n'
        f"  <h1>{_esc(title)}</h1>\n"
        f'  <div class="sub">{sub_html}</div>\n'
        f'  <div class="sub">Updated {_esc(_short_time(generated_at))} · data: '
        '<a href="https://www.jma.go.jp/bosai/map.html#typhoon">JMA</a></div>\n'
        "</header>\n"
    )


def _footer() -> str:
    return (
        "<footer>Generated by taifu from public JMA bulletins. "
        "Trends are computed locally and are not an official forecast.</footer>"
    )


# --- helpers -----------------------------------------------------------------


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _num(value: object) -> str:
    return "–" if value is None else _esc(value)


def _short_time(iso: str) -> str:
    """``2026-06-25T14:45:00+09:00`` → ``2026-06-25 14:45 JST`` (best effort)."""
    t = parse_time(iso)
    if t is None:
        return iso
    tz = ""
    off = t.utcoffset()
    if off is not None:
        hours = int(off.total_seconds() // 3600)
        tz = " JST" if hours == 9 else (f" UTC{hours:+d}" if hours else " UTC")
    return t.strftime("%Y-%m-%d %H:%M") + tz


def _last_time(obs: list[Observation]):
    """Sort key: the newest valid_time in a series (epoch seconds, -inf if none)."""
    times = [parse_time(o.valid_time) for o in obs]
    times = [t for t in times if t is not None]
    return max(times).timestamp() if times else float("-inf")
