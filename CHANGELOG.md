# Changelog

2026-06-07 - Made polling resilient: treat a 404 on targetTc.json as "no active typhoons" (JMA serves it inconsistently off-season) and fetch the two sources independently so one failing never aborts the other. Fixes intermittent GitHub Actions failures.


2026-06-06 - Initial version: poll JMA targetTc.json + 防災情報XML typhoon bulletins, archive raw payloads, store a SQLite time series, and report intensification / slowing-down trends (`poll`/`report`/`list`/`show` CLI). Namespace-agnostic XML parser with test fixture; zero runtime dependencies. Added a GitHub Actions workflow that polls hourly and persists the cache by committing data/ back to the repo.
