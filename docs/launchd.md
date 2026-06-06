# Scheduling `taifu poll` on macOS with launchd

`launchd` is more reliable than cron on macOS (it catches up missed runs after
sleep/reboot). The agent below runs `taifu poll` every hour.

1. Create `~/Library/LaunchAgents/net.dev2.taifu.poll.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>net.dev2.taifu.poll</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>cd /Volumes/nicolas-data/Repositories/taifu &amp;&amp; /usr/bin/env uv run taifu poll --quiet</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>/Volumes/nicolas-data/Repositories/taifu/data/poll.log</string>
  <key>StandardErrorPath</key>
  <string>/Volumes/nicolas-data/Repositories/taifu/data/poll.err.log</string>

  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

2. Load it:

```sh
launchctl load ~/Library/LaunchAgents/net.dev2.taifu.poll.plist
```

3. Check / unload:

```sh
launchctl list | grep taifu
launchctl unload ~/Library/LaunchAgents/net.dev2.taifu.poll.plist
```

> `uv` must be on the `PATH` seen by launchd. If `which uv` lives under
> `~/.local/bin` or Homebrew, either hard-code its absolute path in the
> `ProgramArguments` string or add an `EnvironmentVariables` `PATH` key.

Hourly is plenty: JMA issues typhoon bulletins about every 3 hours, hourly when
a storm is close to Japan. During an active typhoon you can drop the interval to
e.g. every 20 minutes by adding more `StartCalendarInterval` entries — duplicate
bulletins are de-duplicated, so over-polling only costs a couple of HTTP calls.
