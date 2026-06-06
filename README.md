# taifu 台風

A small tool that **caches public JMA typhoon bulletins over time** so you can
see *trends* that the weather sites don't show you: is a typhoon **intensifying**
(central pressure falling / wind rising) or **slowing down / stalling**
(movement speed dropping)?

Japanese weather sites (and JMA itself) show the *current* situation and a
forecast, but you can't look back at how the storm evolved over the last hours
or days. `taifu` fills that gap: run `taifu poll` on a schedule, it archives
every JMA payload, and `taifu report` tells you the direction of travel.

## Data sources

Both are public and need no API key:

| Source | URL | Used for |
| --- | --- | --- |
| `targetTc.json` (bosai) | `https://www.jma.go.jp/bosai/typhoon/data/targetTc.json` | cheap "what's active now" + grade (TD/TS/STS/TY) |
| 防災情報XML feed (`extra.xml`, 随時) | `https://www.data.jma.go.jp/developer/xml/feed/extra.xml` | the「台風解析・予報情報」bulletins with **central pressure, max wind, position, movement speed/direction** |

The XML feed is the [officially documented](https://www.data.jma.go.jp/developer/index.html),
schema-stable feed — JMA commits to keeping it stable, unlike the bosai JSON
(which it explicitly says is *not* a guaranteed API). So the XML is the backbone
for trend fields; the JSON is just a lightweight liveness signal.

> Note: JMA only serves data while a typhoon is active and purges it afterwards.
> Nothing here back-fills history — the whole point is to start caching *now* so
> you have the time series later.

## Install

```sh
uv sync            # create the venv from pyproject
```

## Usage

```sh
# Fetch the latest data, archive + store anything new, print a summary.
# Run this on a schedule (see below).
uv run taifu poll

# Show the intensification / slowing trend for each tracked typhoon.
uv run taifu report
uv run taifu report --window 12      # compare over the last 12h instead of 24h

# Inspect the store.
uv run taifu list
uv run taifu show 2603               # full analysis time series for typhoon #2603
```

Data lives under `./data` by default (override with `--data-dir` or
`$TAIFU_DATA_DIR`):

```
data/
├── taifu.sqlite3      # flattened observations + ingest bookkeeping
└── raw/<number>/<report_time>.xml   # every bulletin, verbatim, never overwritten
```

The raw archive is the safety net: if the parser ever misses a field or JMA
tweaks the schema, the full history can be re-derived from `raw/`.

## Scheduling

JMA issues typhoon bulletins roughly every 3 hours (hourly when a storm is near
Japan). Polling hourly is plenty and gentle on their servers.

### Option A — GitHub Actions (no machine of your own to keep on)

[`.github/workflows/poll.yml`](.github/workflows/poll.yml) runs `taifu poll`
hourly on GitHub's runners. Because each run is a fresh VM, **the cache is
persisted by committing `data/` back to the repo** — the repo itself is the
database, and you get a versioned, off-site backup of every bulletin for free.

To use it: push this repo to GitHub and enable Actions. That's it — the workflow
already has `permissions: contents: write` to commit the cache, and you can also
trigger it manually from the **Actions** tab ("Run workflow"). Each run prints
the current trend report to the run summary.

Two caveats:

- **Run the poller in *one* place only** (Actions *or* a local cron/launchd, not
  both) — two pollers committing to `data/` would fight over the history.
- GitHub **auto-disables scheduled workflows after 60 days with no repo
  activity**, and commits made with the default `GITHUB_TOKEN` may not reset
  that timer. For a typhoon tool that mostly matters Jun–Oct, just re-enable it
  each season from the Actions tab — or have the commit step push with a
  Personal Access Token if you want it to stay alive year-round.

### Option B — launchd / cron on your own machine

See [`docs/launchd.md`](docs/launchd.md), or quick cron:

```cron
# every hour, on the hour
0 * * * * cd /Volumes/nicolas-data/Repositories/taifu && /usr/bin/env uv run taifu poll --quiet >> data/poll.log 2>&1
```

## How trends are decided

- **Intensifying / weakening** — primarily from central pressure change over the
  window (falling ≥ 2 hPa → intensifying); maximum wind corroborates.
- **Slowing / stalling** — movement speed change, plus absolute speed: ≤ 15 km/h
  is "slowly", ≤ 5 km/h is treated as effectively stationary (matching JMA's own
  ゆっくり / ほとんど停滞 wording).

Thresholds live at the top of [`taifu/trends.py`](taifu/trends.py).

## Development

```sh
uv run --extra dev pytest
```

Tests run against a fixture bulletin (`tests/fixtures/typhoon_sample.xml`) that
mirrors the real JMA schema, so the parser is exercised even out of typhoon
season. The parser matches on element *local names* and `type` attributes (not
exact XML namespaces) to tolerate JMA schema revisions.
