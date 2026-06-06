"""Command-line interface for taifu.

Subcommands
-----------
``poll``    Fetch the current JMA data, archive + store anything new, print a
            short summary. This is what you run on a schedule (cron/launchd).
``report``  Print the intensification / slowing trend for each tracked typhoon.
``list``    List typhoons present in the local store.
``show``    Print the analysis time series for one typhoon number.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import sources
from .parse import parse_bulletin, parse_target_tc
from .store import IngestResult, Store
from .trends import Trend, compute_trend

_DEFAULT_DATA_DIR = "data"

_MOTION_LABEL = {
    "stalling": "STALLING (≈stationary)",
    "slowing": "slowing down",
    "accelerating": "speeding up",
    "steady": "steady speed",
    "unknown": "motion unknown",
}
_INTENSITY_LABEL = {
    "intensifying": "INTENSIFYING",
    "weakening": "weakening",
    "steady": "steady",
    "unknown": "intensity unknown",
}


def _store_from_args(args: argparse.Namespace) -> Store:
    data_dir = args.data_dir or os.environ.get("TAIFU_DATA_DIR") or _DEFAULT_DATA_DIR
    return Store(Path(data_dir))


# --- poll --------------------------------------------------------------------


def cmd_poll(args: argparse.Namespace) -> int:
    with _store_from_args(args) as store:
        result = poll(store, verbose=not args.quiet)
        _print_poll_summary(result, store)
    return 0


def poll(store: Store, *, verbose: bool = True) -> IngestResult:
    """Fetch sources, archive + ingest anything new, return an IngestResult."""
    # The two sources are fetched independently: a hiccup in one (JMA 404s the
    # bosai JSON fairly often) must never abort ingestion of the other.
    try:
        active_rows = sources.fetch_target_tc()
    except sources.FetchError as exc:
        if verbose:
            print(f"warning: targetTc.json unavailable: {exc}", file=sys.stderr)
        active_rows = []
    store.record_poll(active_rows)
    active = parse_target_tc(active_rows)
    result = IngestResult(active=active)

    try:
        entries = sources.fetch_feed_entries(typhoon_only=True)
    except sources.FetchError as exc:  # feed hiccup shouldn't lose the targetTc poll
        if verbose:
            print(f"warning: feed unavailable: {exc}", file=sys.stderr)
        entries = []

    for entry in entries:
        if store.already_ingested(entry.doc_url):
            result.skipped_documents += 1
            continue
        try:
            raw = sources.fetch_bulletin(entry.doc_url)
            observations = parse_bulletin(raw)
        except Exception as exc:  # one bad bulletin must not abort the poll
            if verbose:
                print(f"warning: could not ingest {entry.doc_url}: {exc}", file=sys.stderr)
            continue

        number = observations[0].typhoon_number if observations else ""
        report_time = observations[0].report_time if observations else entry.updated
        store.archive_raw(number, report_time, raw)
        result.new_observations += store.insert_observations(observations)
        store.record_document(entry.doc_url, entry.title, entry.updated)
        result.new_documents += 1

    return result


def _print_poll_summary(result: IngestResult, store: Store) -> None:
    if result.active:
        names = ", ".join(
            f"#{a.number}{f' ({a.category})' if a.category else ''}" for a in result.active
        )
        print(f"Active typhoons: {names}")
    else:
        print("No active typhoons reported by JMA.")
    print(
        f"Ingested {result.new_documents} new bulletin(s), "
        f"{result.new_observations} new observation(s); "
        f"{result.skipped_documents} already seen."
    )
    # Show a one-line trend for anything we now have a series for.
    trends = _all_trends(store, window_hours=24.0)
    if trends:
        print()
        for trend in trends:
            print(_trend_oneline(trend))


# --- report ------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    with _store_from_args(args) as store:
        trends = _all_trends(store, window_hours=args.window)
        if not trends:
            print("No typhoon has enough history yet (need ≥2 analysis bulletins).")
            return 0
        for i, trend in enumerate(trends):
            if i:
                print()
            _print_trend_detail(trend)
    return 0


def _all_trends(store: Store, *, window_hours: float) -> list[Trend]:
    trends = []
    for number in store.typhoon_numbers(kind="analysis"):
        obs = store.observations_for(number, kind="analysis")
        trend = compute_trend(obs, window_hours=window_hours)
        if trend is not None:
            trends.append(trend)
    return trends


def _trend_oneline(t: Trend) -> str:
    label = f"#{t.number}" + (f" {t.name}" if t.name else "")
    bits = [_INTENSITY_LABEL[t.intensification], _MOTION_LABEL[t.motion]]
    if t.pressure_delta is not None:
        bits.append(f"Δp {t.pressure_delta:+d} hPa/{t.span_hours:.0f}h")
    return f"{label}: " + "; ".join(bits)


def _print_trend_detail(t: Trend) -> None:
    title = f"Typhoon #{t.number}"
    if t.name:
        title += f" ({t.name})"
    print(title)
    print(
        f"  trend over last {t.span_hours:.0f}h "
        f"({t.n_window} of {t.n_obs} obs; window {t.window_hours:.0f}h)"
    )

    print(f"  intensity:    {_INTENSITY_LABEL[t.intensification]}")
    if t.pressure_delta is not None:
        rate = f", ~{t.pressure_rate_24h:+.0f} hPa/24h" if t.pressure_rate_24h is not None else ""
        print(
            f"                central pressure {t.ref.pressure_hpa} → {t.last.pressure_hpa} hPa "
            f"({t.pressure_delta:+d}{rate})"
        )
    if t.wind_delta is not None:
        print(
            f"                max wind {t.ref.max_wind_mps} → {t.last.max_wind_mps} m/s "
            f"({t.wind_delta:+d})"
        )
    if t.grade_change:
        print(f"                grade change: {t.grade_change}")

    print(f"  motion:       {_MOTION_LABEL[t.motion]}")
    speed_now = t.last.move_speed_kmh
    if speed_now is not None:
        delta = f" ({t.speed_delta:+d} km/h)" if t.speed_delta is not None else ""
        print(f"                speed now {speed_now} km/h{delta}, heading {t.last.move_dir or '?'}")
    elif t.last.move_speed_text:
        print(f"                speed: {t.last.move_speed_text}")

    if t.last.lat is not None and t.last.lon is not None:
        print(f"  position:     {t.last.lat:.1f}N {t.last.lon:.1f}E  @ {t.last.valid_time}")


# --- list / show -------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    with _store_from_args(args) as store:
        numbers = store.typhoon_numbers(kind="analysis")
        if not numbers:
            print("Store is empty. Run `taifu poll` (ideally on a schedule).")
            return 0
        for number in numbers:
            obs = store.observations_for(number, kind="analysis")
            name = store.latest_name(number) or ""
            span = ""
            if obs:
                span = f"{obs[0].valid_time} → {obs[-1].valid_time}"
            print(f"#{number} {name}  —  {len(obs)} analysis obs  [{span}]")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with _store_from_args(args) as store:
        obs = store.observations_for(args.number, kind="analysis")
        if not obs:
            print(f"No analysis observations stored for #{args.number}.")
            return 1
        print(f"#{args.number} analysis history ({len(obs)} obs):")
        print(f"  {'valid_time':25} {'pres':>5} {'wind':>5} {'gust':>5} {'spd':>5} {'dir':>5}  pos")
        for o in obs:
            pos = f"{o.lat:.1f}N {o.lon:.1f}E" if o.lat is not None else ""
            print(
                f"  {o.valid_time:25} "
                f"{_fmt(o.pressure_hpa):>5} {_fmt(o.max_wind_mps):>5} "
                f"{_fmt(o.max_gust_mps):>5} {_fmt(o.move_speed_kmh):>5} "
                f"{(o.move_dir or ''):>5}  {pos}"
            )
    return 0


def _fmt(value) -> str:
    return "-" if value is None else str(value)


# --- entry point -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # --data-dir is shared via a parent parser so it works both before and after
    # the subcommand (e.g. `taifu --data-dir X poll` and `taifu poll --data-dir X`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data-dir",
        default=None,
        help="Directory for the SQLite store and raw archive (default: ./data, "
        "or $TAIFU_DATA_DIR).",
    )

    parser = argparse.ArgumentParser(prog="taifu", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    p_poll = sub.add_parser("poll", parents=[common], help="Fetch + cache the latest JMA data.")
    p_poll.add_argument("-q", "--quiet", action="store_true", help="Suppress warnings.")
    p_poll.set_defaults(func=cmd_poll)

    p_report = sub.add_parser(
        "report", parents=[common], help="Show intensification / slowing trends."
    )
    p_report.add_argument(
        "--window", type=float, default=24.0, help="Trend comparison window in hours (default 24)."
    )
    p_report.set_defaults(func=cmd_report)

    p_list = sub.add_parser("list", parents=[common], help="List typhoons in the local store.")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser(
        "show", parents=[common], help="Print the analysis time series for one typhoon."
    )
    p_show.add_argument("number", help="JMA typhoon number, e.g. 2603.")
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
