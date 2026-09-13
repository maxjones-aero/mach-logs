# mach-logs

`mach-logs` turns ArduPilot DataFlash telemetry into editor-ready broadcast graphics, diagnostic plots, and flight-path animations.

Raw flight logs and generated media are deliberately excluded from Git. The command line requires a reference latitude and longitude at runtime, so a private flying location does not need to be committed to the repository.

## Requirements

- Python 3.10 or newer
- FFmpeg on `PATH` when rendering video

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Place ArduPilot `.bin` files in `data/` or provide a path elsewhere. Files in `data/` remain untracked.

## Usage

### Broadcast overlay

Render a standalone 1080p editorial package:

```powershell
mach-logs --verbose overlay data\flight.bin `
  --reference-lat 48.000 `
  --reference-lon -3.000 `
  --start 750 `
  --end 930 `
  --title "TEST FLIGHT 01"
```

This produces:

- `out/flight-overlay.mov`: transparent ProRes 4444 master
- `out/flight-blur-matte.mov`: luma matte for optional background blur
- `out/flight-overlay-preview.mp4`: H.264 review copy over a neutral background
- `out/flight-overlay.json`: frame rate, resolution and log-time alignment metadata

Place the ProRes 4444 file above the footage using the editor's Normal blend mode. It has straight alpha, so Screen or Add is not required. For true frosted glass, use the matte to restrict an editor-native blur applied to the footage below, then place the transparent overlay above that result.

The overlay is independent of the selected footage. Frame zero corresponds to `log_time.first_frame_seconds` in the JSON metadata. If footage is cut, reordered or retimed, make matching edits to the overlay and matte.

Useful options include:

```powershell
mach-logs overlay --help

# 4K, 50 fps, metric units, custom accent, replacing prior exports
mach-logs overlay data\flight.bin `
  --reference-lat 48.000 --reference-lon -3.000 `
  --width 3840 --height 2160 --fps 50 `
  --units metric --accent "#62E6FF" --overwrite
```

### Diagnostic plots

Display telemetry plots:

```powershell
mach-logs plot data\flight.bin --reference-lat 48.000 --reference-lon -3.000
```

Save the plots to an image:

```powershell
mach-logs plot data\flight.bin --reference-lat 48.000 --reference-lon -3.000 --output out\plots.png
```

Render part of a flight as an MP4:

```powershell
mach-logs animate data\flight.bin --reference-lat 48.000 --reference-lon -3.000 --start 750 --end 930 --output out\flight.mp4 --sleek
```

Use the command-specific `--help` pages for all options. Coordinates must be decimal degrees. `pymavlink` must expose the log's `Lat` and `Lng` fields in decimal degrees rather than degrees multiplied by 1e7.

## Expected log data

- `GPS`: `TimeUS`, `Lat`, `Lng`, `Alt`, `Spd`, and `VZ`
- `ATT`: `TimeUS`, `Roll`, and `Pitch`
- `POS`: `TimeUS`, `Lat`, `Lng`, and `Alt`

The CLI reports a concise error if required message types, fields, time ranges, input files, or FFmpeg are unavailable.

## Repository layout

```text
src/mach_logs/       Installable Python package and runtime instrument assets
assets/source/       Original artwork retained for future edits
data/                Local raw logs (ignored except for .gitkeep)
out/                 Generated plots and videos (ignored except for .gitkeep)
tests/               Unit tests and anonymized telemetry fixtures
```

## Development

```powershell
ruff check .
pytest
```

The parser reads each selected message from the log once and returns a dictionary of pandas DataFrames keyed by MAVLink message type.

## License

MIT. See [LICENSE](LICENSE).
