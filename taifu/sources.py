"""Network access to public JMA typhoon data sources.

Two sources are used, each with a different reliability/richness trade-off:

* ``targetTc.json`` — a lightweight JSON list of currently active tropical
  cyclones with their JMA number and grade (TD/TS/STS/TY/...). JMA explicitly
  does *not* promise this "bosai" JSON is a stable API, so we only lean on it
  for the cheap "what is active right now" signal.

* The 防災情報XML feed (``extra.xml``, 高頻度/随時) — the officially documented and
  schema-stable feed. When a typhoon is active it carries
  「台風解析・予報情報」 bulletins that contain the trend-critical fields:
  centre position, central pressure, maximum wind, and movement speed/direction.

Both are public and require no authentication.
"""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

TARGET_TC_URL = "https://www.jma.go.jp/bosai/typhoon/data/targetTc.json"

# 高頻度（随時）feed — carries typhoon bulletins among other irregular reports.
EXTRA_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"

# Marker that identifies typhoon analysis/forecast bulletins in the feed title.
TYPHOON_TITLE_MARKER = "台風"

_USER_AGENT = "taifu/0.1 (+personal typhoon trend tracker)"
_TIMEOUT = 30


class FetchError(RuntimeError):
    """Raised when a source cannot be retrieved after the configured attempts."""


def _get(url: str, *, attempts: int = 3) -> bytes:
    """Fetch ``url`` and return the (decompressed) response body as bytes.

    Retries a few times on transient network/5xx errors. A custom User-Agent is
    sent because JMA throttles requests that look like bare scripts.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
            last_exc = exc
            # 4xx are not worth retrying.
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                break
    raise FetchError(f"failed to fetch {url}: {last_exc}")


def fetch_target_tc() -> list[dict]:
    """Return the parsed ``targetTc.json`` list (empty when no typhoon is active)."""
    raw = _get(TARGET_TC_URL)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise FetchError(f"unexpected targetTc.json payload: {type(data).__name__}")
    return data


@dataclass(frozen=True)
class FeedEntry:
    """One Atom ``<entry>`` from a JMA XML feed."""

    title: str
    doc_url: str  # the <id>, which is the URL of the actual bulletin XML
    updated: str  # ISO-8601 publication time of this revision


def fetch_feed_entries(*, typhoon_only: bool = True) -> list[FeedEntry]:
    """Fetch the extra feed and return its entries (typhoon bulletins by default)."""
    raw = _get(EXTRA_FEED_URL)
    entries = _parse_atom(raw)
    if typhoon_only:
        entries = [e for e in entries if TYPHOON_TITLE_MARKER in e.title]
    return entries


def fetch_bulletin(doc_url: str) -> bytes:
    """Download a single typhoon bulletin XML document (raw bytes, for archiving)."""
    return _get(doc_url)


def _parse_atom(raw: bytes) -> list[FeedEntry]:
    """Parse an Atom feed into FeedEntry records (namespace-agnostic)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw)
    entries: list[FeedEntry] = []
    for entry in root.iter():
        if _localname(entry.tag) != "entry":
            continue
        title = doc_url = updated = ""
        for child in entry:
            name = _localname(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "id":
                doc_url = (child.text or "").strip()
            elif name == "updated":
                updated = (child.text or "").strip()
        if doc_url:
            entries.append(FeedEntry(title=title, doc_url=doc_url, updated=updated))
    return entries


def _localname(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]
