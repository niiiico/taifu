"""Local persistence: a SQLite time series plus a raw-payload archive.

Design rule: **never lose a payload**. Every bulletin XML is written verbatim to
the archive directory before it is parsed, so if the parser misses a field (or
JMA tweaks the schema) the history can be re-derived later. SQLite holds the
flattened observations that the trend code reads.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .parse import Observation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingested_docs (
    doc_url    TEXT PRIMARY KEY,
    title      TEXT,
    updated    TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    typhoon_number  TEXT NOT NULL,
    name            TEXT,
    name_kana       TEXT,
    report_time     TEXT NOT NULL,
    kind            TEXT NOT NULL,
    valid_time      TEXT NOT NULL,
    lat             REAL,
    lon             REAL,
    pressure_hpa    INTEGER,
    max_wind_mps    INTEGER,
    max_gust_mps    INTEGER,
    move_dir        TEXT,
    move_speed_kmh  INTEGER,
    move_speed_text TEXT,
    intensity_class TEXT,
    size_class      TEXT,
    PRIMARY KEY (typhoon_number, report_time, kind, valid_time)
);

CREATE INDEX IF NOT EXISTS idx_obs_number_kind_valid
    ON observations (typhoon_number, kind, valid_time);

CREATE TABLE IF NOT EXISTS polls (
    fetched_at  TEXT NOT NULL,
    active_json TEXT NOT NULL
);
"""


@dataclass
class IngestResult:
    """Outcome of one poll, for human-readable reporting."""

    active: list  # list[ActiveTyphoon]
    new_documents: int = 0
    new_observations: int = 0
    skipped_documents: int = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """SQLite-backed store with a sibling raw-XML archive."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "taifu.sqlite3"
        self.raw_dir = self.root / "raw"
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- writes --------------------------------------------------------------

    def already_ingested(self, doc_url: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM ingested_docs WHERE doc_url = ?", (doc_url,)
        )
        return cur.fetchone() is not None

    def archive_raw(self, typhoon_number: str, report_time: str, raw: bytes) -> Path:
        """Write a bulletin's raw bytes to the archive and return the path."""
        number = _safe(typhoon_number) or "unknown"
        stamp = _safe(report_time) or _safe(_now_iso())
        dest_dir = self.raw_dir / number
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stamp}.xml"
        dest.write_bytes(raw)
        return dest

    def record_document(self, doc_url: str, title: str, updated: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ingested_docs (doc_url, title, updated, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            (doc_url, title, updated, _now_iso()),
        )
        self._conn.commit()

    def insert_observations(self, observations: Iterable[Observation]) -> int:
        """Insert observations, ignoring exact duplicates. Returns rows added."""
        added = 0
        for obs in observations:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO observations ("
                "typhoon_number, name, name_kana, report_time, kind, valid_time,"
                "lat, lon, pressure_hpa, max_wind_mps, max_gust_mps,"
                "move_dir, move_speed_kmh, move_speed_text, intensity_class, size_class"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    obs.typhoon_number, obs.name, obs.name_kana, obs.report_time,
                    obs.kind, obs.valid_time, obs.lat, obs.lon, obs.pressure_hpa,
                    obs.max_wind_mps, obs.max_gust_mps, obs.move_dir,
                    obs.move_speed_kmh, obs.move_speed_text, obs.intensity_class,
                    obs.size_class,
                ),
            )
            added += cur.rowcount
        self._conn.commit()
        return added

    def record_poll(self, active_rows: list[dict]) -> None:
        self._conn.execute(
            "INSERT INTO polls (fetched_at, active_json) VALUES (?, ?)",
            (_now_iso(), json.dumps(active_rows, ensure_ascii=False)),
        )
        self._conn.commit()

    # --- reads ---------------------------------------------------------------

    def typhoon_numbers(self, *, kind: str = "analysis") -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT typhoon_number FROM observations WHERE kind = ? "
            "ORDER BY typhoon_number",
            (kind,),
        )
        return [r[0] for r in cur.fetchall()]

    def observations_for(
        self, typhoon_number: str, *, kind: str = "analysis"
    ) -> list[Observation]:
        cur = self._conn.execute(
            "SELECT typhoon_number, name, name_kana, report_time, kind, valid_time,"
            " lat, lon, pressure_hpa, max_wind_mps, max_gust_mps, move_dir,"
            " move_speed_kmh, move_speed_text, intensity_class, size_class "
            "FROM observations WHERE typhoon_number = ? AND kind = ? "
            "ORDER BY valid_time",
            (typhoon_number, kind),
        )
        return [Observation(**dict(row)) for row in cur.fetchall()]

    def latest_name(self, typhoon_number: str) -> Optional[str]:
        cur = self._conn.execute(
            "SELECT name FROM observations WHERE typhoon_number = ? AND name <> '' "
            "ORDER BY report_time DESC LIMIT 1",
            (typhoon_number,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _safe(text: str) -> str:
    """Make a string safe for use as a filename component."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", text or "").strip("_")
