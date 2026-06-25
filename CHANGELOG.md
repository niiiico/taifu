# Changelog

2026-06-25 - Added `taifu html`: render the cache into a static, dependency-free site (overview + per-storm pages with sparklines) and publish it to GitHub Pages from the hourly poll workflow. Generated HTML is uploaded as a Pages artifact, not committed, so `data/` stays payload-only.

2026-06-07 - report: render the windowed reference observation so the printed "from → to" values match the reported delta (previously mixed the overall-first value with a windowed delta). Header now shows obs-in-window.

2026-06-07 - Made polling resilient: treat a 404 on targetTc.json as "no active typhoons" (JMA serves it inconsistently off-season) and fetch the two sources independently so one failing never aborts the other. Fixes intermittent GitHub Actions failures.


2026-06-06 - Initial version: poll JMA targetTc.json + 防災情報XML typhoon bulletins, archive raw payloads, store a SQLite time series, and report intensification / slowing-down trends (`poll`/`report`/`list`/`show` CLI). Namespace-agnostic XML parser with test fixture; zero runtime dependencies. Added a GitHub Actions workflow that polls hourly and persists the cache by committing data/ back to the repo.
