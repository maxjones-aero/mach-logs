# mach-logs

`mach-logs` parses ArduPilot DataFlash logs and produces telemetry plots or animated flight-path videos.

Raw flight logs and generated media are deliberately excluded from Git. The command line requires a reference latitude and longitude at runtime, so a private flying location does not need to be committed to the repository.

## Requirements

- Python 3.10 or newer
- FFmpeg on `PATH` when rendering MP4 animations

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Place ArduPilot `.bin` files in `data/` or provide a path elsewhere. Files in `data/` remain untracked.

## Usage

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

Use `mach-logs --help`, `mach-logs plot --help`, or `mach-logs animate --help` for all options. Coordinates must be decimal degrees. `pymavlink` must expose the log's `Lat` and `Lng` fields in decimal degrees rather than degrees multiplied by 1e7.

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
