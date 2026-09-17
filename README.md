# mach-logs

`mach-logs` turns ArduPilot DataFlash telemetry into editor-ready broadcast graphics, diagnostic plots, and flight-path animations.

Raw flight logs and generated media are deliberately excluded from Git. Each overlay run is described by a small JSON file stored beside its `.bin` log, making an export reproducible without a long command line.

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

Render the included flight configuration:

```powershell
mach-logs --verbose overlay data\2026-09-12-flight.json --overwrite
```

This produces:

- `out/flight-overlay-1080p-h264.mp4`: H.264 colour overlay
- `out/flight-overlay-1080p-alpha-matte.mp4`: frame-aligned H.264 alpha/luma matte
- `out/flight-overlay-1080p-blur-matte.png`: static luma mask for optional background blur

In DaVinci Resolve, use the alpha-matte video as the colour overlay's external matte. Because it is rendered frame by frame, moving text, gauges and the progressively drawn flight path retain clean edges. Use the static blur matte to restrict an editor-native blur on the footage below, then place the colour overlay above it.

The colour and alpha videos have identical resolution, frame rate, frame count and timing. Keep them linked when cutting or retiming.

The run JSON controls the important inputs in one place:

```powershell
{
  "log": "flight.bin",
  "reference": {"latitude": 51.1, "longitude": -2.1},
  "selection": {
    "launch_speed_metres_per_second": 10.0,
    "before_seconds": 10.0,
    "after_seconds": 10.0
  },
  "video": {"width": 1920, "height": 1080, "fps": 30},
  "presentation": {
    "title": "FLIGHT TIME", "units": "imperial", "theme": "orbital",
    "accent": null, "trail_seconds": 12.0, "fade_seconds": 0.0
  },
  "fuel": {
    "idle_litres_per_minute": 0.179,
    "full_litres_per_minute": 0.98,
    "total_consumed_litres": 0.95,
    "final_remaining_litres": 1.2
  },
  "outputs": {
    "overlay": "../out/overlay.mp4",
    "alpha_matte": "../out/alpha-matte.mp4",
    "blur_matte": "../out/blur-matte.png"
  }
}
```

Paths are resolved relative to the JSON file. Launch is the first GPS sample above the configured threshold; the export begins and ends with the configured handles. Airspeed is intentionally not displayed.

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
- `IMU`: `TimeUS`, `AccX`, `AccY`, and `AccZ` for the overlay G meter
- `BAT`: `TimeUS`, `Volt`, and `RemPct` for LiPo cell-count inference and charge
- `RCOU`: `TimeUS` and the configured throttle output channel for estimated fuel use
- `PARM`: `SERVOx_FUNCTION`, `SERVOx_MIN`, and `SERVOx_MAX` parameters used to identify
  and normalize the throttle channel
- `POS`: `TimeUS`, `Lat`, `Lng`, and `Alt`

The CLI reports a concise error if required message types, fields, time ranges, input files, or FFmpeg are unavailable.
The fuel indicator displays estimated fuel remaining. It linearly maps throttle between
0.179 L/min at idle and 0.98 L/min at full power, begins ten seconds before launch, stops at
engine shutdown, and normalizes the curve to the measured 0.95 L consumption. With 1.20 L
remaining at shutdown, the model begins at 2.15 L.

## Repository layout

```text
src/mach_logs/       Installable Python package and runtime instrument assets
assets/source/       Original artwork retained for future edits
data/                Tracked run JSON files and ignored raw logs
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
