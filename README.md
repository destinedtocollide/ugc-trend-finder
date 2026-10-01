# UGC Trend Finder

A Windows app for Roblox UGC creators. It reads the Roblox marketplace, finds the themes and items that are selling right now, and suggests what to make next, with a price range, colors and example items for each idea.

## Download

Get **UGC-Trend-Finder-Setup.exe** from the [latest release](../../releases/latest) and run it. The app updates itself when a new version comes out.

Windows may show "Windows protected your PC" the first time. Click **More info → Run anyway**.

## Features

- **Ideas**: ranked item ideas with a score, suggested price, colors to try, the reasons behind each idea and example items.
- **Selling best right now**: the top UGC bestsellers from your latest scan, with pictures.
- **Trending themes**: every theme found, with demand, competition, momentum and how many bestsellers are new.
- **Momentum**: charts of how themes and items sell across your scans, with a slider to look back in time.
- **My list**: save ideas, track them (To do, Making, Uploaded, Skipped) and keep notes.
- **Automatic scans**: scan every 6, 12 or 24 hours in the background, with a notification when new ideas are ready.
- **Themes**: Midnight, Sakura pink, Violet, Emerald, Sunset, Graphite, Daylight and Blossom, or make your own in Settings by picking four colors.
- **Tray**: keeps running next to the clock when the window is closed.

## How it works

Each scan reads four Roblox catalog lists: bestselling today, bestselling this week, most favorited this week and the newest uploads. Requests are spaced a few seconds apart so Roblox doesn't rate-limit the app.

Themes come from item names (for example "cat ears", "y2k" or "angel wings"). A theme scores well when its items rank high in the bestseller lists while few new uploads use it. Roblox doesn't share exact sales numbers, so list position is the demand signal.

Ideas are data-backed suggestions, not guaranteed sales. Always check the example items, and don't copy other creators' designs or use brands you don't own.

## Files

| Where | What |
| --- | --- |
| Documents\UGC Trend Finder | Scan reports and scan history |
| %LOCALAPPDATA%\UGC Trend Finder | Saved ideas, picture cache and `app.log` |

## Project layout

```
src/
  app.py                  window, tray, updates and the bridge to the interface
  ugc_trend_finder.py     marketplace scanner and analysis
  updater.py              checks GitHub releases and installs updates
  make_icons.py           draws the app icon during the build
  UGC Trend Finder.pyw    runs the app from source
  ui/                     interface (index.html) and loading window (splash.html)
installer/
  installer.iss           Inno Setup script for the Windows installer
.github/workflows/
  build.yml               builds the installer for every release
```

## Releasing a new version

1. Commit the changes to `main`.
2. Create a release with a tag like `v2.0`.
3. The **Build installer** workflow builds `UGC-Trend-Finder-Setup.exe` and attaches it to the release. Installed apps pick up the new version on their next update check.

## Running from source

Install Python 3.12, then double-click `src/UGC Trend Finder.pyw`. The first start installs `pywebview`, `pystray` and `pillow`.
