"""Tests for source fetching error handling (no real network access)."""

import pytest

from taifu import sources


def test_target_tc_404_means_no_typhoons(monkeypatch):
    def fake_get(url, **kwargs):
        raise sources.NotFound(f"not found: {url}")

    monkeypatch.setattr(sources, "_get", fake_get)
    # A 404 on targetTc.json is the off-season norm, not a failure.
    assert sources.fetch_target_tc() == []


def test_target_tc_other_errors_propagate(monkeypatch):
    def fake_get(url, **kwargs):
        raise sources.FetchError("boom")

    monkeypatch.setattr(sources, "_get", fake_get)
    with pytest.raises(sources.FetchError):
        sources.fetch_target_tc()


def test_target_tc_parses_payload(monkeypatch):
    monkeypatch.setattr(
        sources,
        "_get",
        lambda url, **kw: b'[{"typhoonNumber": "2603", "tropicalCyclone": "T2603", "category": "TY"}]',
    )
    rows = sources.fetch_target_tc()
    assert rows == [{"typhoonNumber": "2603", "tropicalCyclone": "T2603", "category": "TY"}]
