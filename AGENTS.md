## Overview
- Single-purpose Python service for Venus OS (Victron) that bridges TCP NMEA input to a D-Bus GPS service.
- No packaging, no tests, no build system. Runtime environment is Venus OS, not a typical dev machine.

## Entry Points
- `scripts/venus_tcp_gps_bridge.py`: main process (runs GLib main loop + TCP server thread).
- `scripts/start_gps_bridge.sh`: required wrapper that sets `PYTHONPATH` for Victron `velib_python`.
- `rc.local`: boot hook used by Venus OS (`/data/rc.local`).

## Critical Environment Assumptions
- Must run on Venus OS with:
  - `dbus` system bus available
  - `gi.repository.GLib`
  - Victron `vedbus` module from `velib_python`
- `PYTHONPATH` **must** include:
  - `/opt/victronenergy/dbus-systemcalc-py/ext/velib_python`
  - This is why the wrapper script exists; do not bypass it.

## Running / Debugging
- Typical execution (on device):
  - `/data/scripts/start_gps_bridge.sh &`
- Logs:
  - `tail -f /data/logs/venus_tcp_gps_bridge.log`
- D-Bus verification:
  - `dbus -y com.victronenergy.gps.tcp`

Local execution on macOS/Linux will fail unless you replicate the Venus OS D-Bus + velib environment.

## Data Flow (important for changes)
- TCP server (`NmeaServer`) receives raw lines
- `App.handle_sentence`:
  - optional prefix stripping
  - checksum validation (can drop data!)
  - dispatch to `parse_gprmc` / `parse_gpgga`
- Parsed dict is pushed via `GLib.idle_add` to D-Bus service
- `DbussGps.update` maps fields to Victron-required paths

## Non-Obvious Constraints
- D-Bus paths and names are **strict**; SystemCalc depends on exact keys like:
  - `/NrOfSatellites` (not a guessable name)
- Speed must default to `0.0` (not `None`) or SystemCalc may ignore it.
- Fix mapping is intentionally simplified:
  - GGA `fix >= 2` → treated as 3D
- Altitude presence can upgrade fix to 3D.

## Configuration (env vars)
- `NMEA_LISTEN_HOST`, `NMEA_LISTEN_PORT`
- `NMEA_STRIP_PREFIX`, `NMEA_STRICT_CHECKSUM`
- `GPS_DEVICE_INSTANCE`, `GPS_PRODUCT_NAME`, `GPS_DEVICE_LABEL`

Agents should not hardcode assumptions; these are runtime-configurable.

## Making Changes Safely
- Preserve GLib main loop + thread model (DBus must run on main loop).
- Do not introduce blocking work in `handle_sentence` or D-Bus update path.
- Be careful with logging volume; this runs continuously on embedded hardware.
- Maintain compatibility with both `GP*` and `GN*` talkers (multi-GNSS).

## Deployment Model
- Files are copied to `/data` on device (persistent partition).
- No installer; repo layout mirrors target filesystem.
- Any path changes must stay aligned with `/data/...` expectations.

## What’s Missing (intentional)
- No tests or CI
- No dependency management
- No packaging

Do not try to “modernize” structure unless explicitly requested; this is designed for constrained embedded deployment.
