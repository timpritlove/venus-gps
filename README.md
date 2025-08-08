# NMEA TCP GPS Bridge for VenusOS

A Python service that creates a TCP server to receive NMEA GPS data and exposes it as a Victron-compatible GPS service on the Venus OS D-Bus system. This allows external GPS sources (like cellular routers with GPS capabilities) to provide position data to Venus OS devices.

## Functionality

The bridge performs the following functions:

### TCP NMEA Server
- Listens on a configurable TCP port (default: 8500) for incoming NMEA sentences
- Accepts connections from GPS sources like cellular routers (e.g., Teltonika RUTX11)
- Handles client disconnections and automatically waits for new connections
- Processes standard NMEA sentences: GPRMC/GNRMC and GPGGA/GNGGA

### NMEA Data Processing
- **Checksum Validation**: Verifies NMEA sentence checksums (configurable)
- **Prefix Stripping**: Removes router-specific prefixes before '$' character
- **Coordinate Conversion**: Converts degrees-minutes format to decimal degrees
- **Unit Conversion**: Converts knots to meters per second for speed
- **Data Extraction**: Parses position, altitude, speed, course, satellite count, and fix quality

### Venus OS Integration
- Creates a D-Bus service (`com.victronenergy.gps.tcp`) compatible with Venus OS
- Exposes GPS data in the format expected by SystemCalc
- Provides real-time updates of:
  - Position (latitude/longitude)
  - Altitude
  - Speed (m/s)
  - Course/heading
  - Number of satellites
  - HDOP (horizontal dilution of precision)
  - Fix quality (0=no fix, 2=2D, 3=3D)

### Configuration Options
Environment variables allow customization:
- `NMEA_LISTEN_HOST`: Bind address (default: 0.0.0.0)
- `NMEA_LISTEN_PORT`: TCP port (default: 8500)
- `NMEA_STRIP_PREFIX`: Remove prefixes before '$' (default: enabled)
- `NMEA_STRICT_CHECKSUM`: Require valid checksums (default: enabled)
- `GPS_DEVICE_INSTANCE`: Device instance number (default: 0)
- `GPS_PRODUCT_NAME`: Product name displayed in Venus OS
- `GPS_DEVICE_LABEL`: Device label for identification

## Installation

All files need to be installed in the `/data` directory on your Venus OS device to persist across firmware updates.

### 1. Copy Files to Venus OS Device

Transfer the files maintaining the directory hierarchy:

```bash
# Copy to Venus OS device (replace <venus-ip> with your device's IP)
scp -r scripts/ root@<venus-ip>:/data/
scp rc.local root@<venus-ip>:/data/
```

### 2. Set Execute Permissions

```bash
# SSH into Venus OS device
ssh root@<venus-ip>

# Make scripts executable
chmod +x /data/scripts/start_gps_bridge.sh
chmod +x /data/scripts/venus_tcp_gps_bridge.py
chmod +x /data/rc.local
```

### 3. Create Log Directory

```bash
# Create directory for log files
mkdir -p /data/logs
```

### 4. Install Startup Script

```bash
# Link rc.local to run on boot
ln -sf /data/rc.local /etc/rc.local
```

### 5. Start the Service

You can either reboot the Venus OS device or start the service manually:

```bash
# Start manually (runs in background)
/data/scripts/start_gps_bridge.sh &

# Or reboot to start automatically
reboot
```

## Usage

1. **Configure your GPS source** (e.g., cellular router) to send NMEA data to the Venus OS device's IP address on port 8500
2. **Monitor logs** to verify operation: `tail -f /data/logs/venus_tcp_gps_bridge.log`
3. **Check Venus OS GUI** - the GPS device should appear in the device list and provide position data to SystemCalc

The GPS data will be available throughout the Venus OS system for navigation, logging, and other position-dependent functions.

## File Structure

```
/data/
├── scripts/
│   ├── venus_tcp_gps_bridge.py  # Main bridge service
│   └── start_gps_bridge.sh      # Startup wrapper script
├── rc.local                     # Boot-time startup script
└── logs/
    └── venus_tcp_gps_bridge.log # Service log file
```

## Troubleshooting

- Check log file for connection and parsing errors
- Verify TCP port 8500 is accessible from GPS source
- Ensure NMEA sentences include proper checksums if `NMEA_STRICT_CHECKSUM=1`
- Monitor D-Bus service registration: `dbus -y com.victronenergy.gps.tcp`