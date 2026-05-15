#!/usr/bin/env python3
# TCP NMEA GPS bridge for Venus OS
# Exposes a Victron-style GPS service that SystemCalc will use as the official GPS.

import socket
import threading
import time
import logging
import os

from gi.repository import GLib
import dbus
import dbus.mainloop.glib
from vedbus import VeDbusService

# ---- config via env ----
LISTEN_HOST = os.environ.get("NMEA_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("NMEA_LISTEN_PORT", "8500"))

# If RUTX11 adds a prefix before '$', strip it.
STRIP_PREFIX = os.environ.get("NMEA_STRIP_PREFIX", "1") not in ("0", "false", "False")
# Require checksum; set 0 to accept missing/invalid checksums.
STRICT_CHECKSUM = os.environ.get("NMEA_STRICT_CHECKSUM", "1") not in ("0", "false", "False")

DEVICE_INSTANCE = int(os.environ.get("GPS_DEVICE_INSTANCE", "0"))
PRODUCT_NAME = os.environ.get("GPS_PRODUCT_NAME", "TCP NMEA GPS Bridge")
DEVICE_LABEL = os.environ.get("GPS_DEVICE_LABEL", "tcp://<RUTX11>:8500")
FIRMWARE_VERSION = "1.3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tcp-gps-bridge")

# ---- helpers ----
def nmea_checksum_ok(sentence: str) -> bool:
    if "*" not in sentence:
        return False
    body = sentence[1:sentence.rfind("*")]
    given = sentence[sentence.rfind("*")+1:].strip()
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return int(given, 16) == calc
    except ValueError:
        return False

def _dm_to_deg(dm: str, hemi: str, is_lat: bool) -> float:
    if not dm or not hemi:
        raise ValueError("empty")
    if is_lat:
        deg = int(dm[0:2]); minutes = float(dm[2:])
        sign = -1 if hemi.upper() == "S" else 1
    else:
        deg = int(dm[0:3]); minutes = float(dm[3:])
        sign = -1 if hemi.upper() == "W" else 1
    return sign * (deg + minutes/60.0)

def knots_to_mps(knots: str):
    try:
        return float(knots) * 0.514444
    except Exception:
        return None

def parse_gprmc(parts):
    # $--RMC,hhmmss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,...*CS
    d = {}
    if len(parts) < 9:
        return d
    d["valid"] = (parts[2] == "A")
    try:
        d["lat"] = _dm_to_deg(parts[3], parts[4], True)
        d["lon"] = _dm_to_deg(parts[5], parts[6], False)
    except Exception:
        pass
    spd = knots_to_mps(parts[7])
    if spd is not None:
        d["speed"] = spd
    try:
        d["course"] = float(parts[8])
    except Exception:
        pass
    return d

def parse_gpgga(parts):
    # $--GGA,hhmmss,llll.ll,a,yyyyy.yy,a,fix,sats,hdop,alt,M,...
    d = {}
    if len(parts) < 10:
        return d
    try:
        d["lat"] = _dm_to_deg(parts[2], parts[3], True)
        d["lon"] = _dm_to_deg(parts[4], parts[5], False)
    except Exception:
        pass
    try:
        fixq = int(parts[6])  # 0=no, 1=GPS, 2=DGPS, >=2 => treat as 3D
        d["fix"] = 0 if fixq == 0 else (3 if fixq >= 2 else 2)
    except Exception:
        pass
    try:
        d["sats"] = int(parts[7])
    except Exception:
        pass
    try:
        d["hdop"] = float(parts[8])
    except Exception:
        pass
    try:
        d["alt"] = float(parts[9])  # meters
        # A valid altitude means we have a 3D fix, regardless of GGA quality field.
        if d.get("fix", 0) == 2:
            d["fix"] = 3
    except Exception:
        pass
    return d

# ---- D-Bus service ----
class DbussGps:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.service = VeDbusService("com.victronenergy.gps.tcp", bus=self.bus, register=False)

        # Identity
        self.service.add_path('/DeviceInstance', DEVICE_INSTANCE)
        self.service.add_path('/ProductId', 0)
        self.service.add_path('/ProductName', PRODUCT_NAME)
        self.service.add_path('/FirmwareVersion', FIRMWARE_VERSION)
        self.service.add_path('/HardwareVersion', '')
        self.service.add_path('/Connected', 1)
        self.service.add_path('/Device', DEVICE_LABEL)

        # Victron GPS layout that SystemCalc expects
        self.service.add_path('/Fix', 0)                           # 0=no, 2=2D, 3=3D
        self.service.add_path('/Hdop', None)
        self.service.add_path('/NrOfSatellites', None)             # <-- correct name
        self.service.add_path('/Position/Latitude', 0.0)
        self.service.add_path('/Position/Longitude', 0.0)
        self.service.add_path('/Position/Altitude', None)          # meters
        self.service.add_path('/Speed', 0.0)                       # m/s
        self.service.add_path('/Course', None)                     # deg

        self.service.register()
        self._last_log = 0

    def update(self, upd: dict):
        if "lat" in upd:
            self.service['/Position/Latitude'] = float(upd["lat"])
        if "lon" in upd:
            self.service['/Position/Longitude'] = float(upd["lon"])
        if "alt" in upd:
            self.service['/Position/Altitude'] = float(upd["alt"])

        if "speed" in upd:
            self.service['/Speed'] = float(upd["speed"])
        else:
            # Default speed to 0.0 if no update, so SystemCalc sees it as present
            if self.service['/Speed'] is None:
                self.service['/Speed'] = 0.0

        if "course" in upd:
            self.service['/Course'] = float(upd["course"])
        if "sats" in upd:
            self.service['/NrOfSatellites'] = int(upd["sats"])
        if "hdop" in upd:
            self.service['/Hdop'] = float(upd["hdop"])
        if "fix" in upd:
            self.service['/Fix'] = int(upd["fix"])
        elif "valid" in upd and not upd["valid"]:
            self.service['/Fix'] = 0

        now = time.time()
        if now - self._last_log >= 1:
            self._last_log = now
            log.info(
                "DBus update: Fix=%s Lat=%.6f Lon=%.6f Alt=%s Sats=%s Hdop=%s Spd=%s Crs=%s",
                self.service['/Fix'],
                self.service['/Position/Latitude'],
                self.service['/Position/Longitude'],
                self.service['/Position/Altitude'],
                self.service['/NrOfSatellites'],
                self.service['/Hdop'],
                self.service['/Speed'],
                self.service['/Course'],
            )

# ---- TCP server ----
class NmeaServer(threading.Thread):
    def __init__(self, host, port, on_sentence):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.on_sentence = on_sentence
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((self.host, self.port))
                    s.listen(1)
                    log.info("Listening for NMEA on %s:%s", self.host, self.port)
                    conn, addr = s.accept()
                    log.info("Client connected from %s:%s", *addr)
                    with conn:
                        buf = b""
                        while True:
                            chunk = conn.recv(4096)
                            if not chunk:
                                log.info("Client disconnected")
                                break
                            buf += chunk
                            while b'\n' in buf:
                                line, buf = buf.split(b'\n', 1)
                                line = line.strip().decode('ascii', errors='ignore')
                                self.on_sentence(line)
            except Exception as e:
                log.exception("Server error: %s", e)
                time.sleep(1)

    def stop(self):
        self._stop = True

# ---- glue ----
class App:
    def __init__(self):
        self.gps = DbussGps()
        self.server = NmeaServer(LISTEN_HOST, LISTEN_PORT, self.handle_sentence)

    def handle_sentence(self, raw_line: str):
        line = raw_line.strip()
        if STRIP_PREFIX and '$' in line and not line.startswith('$'):
            line = line[line.find('$'):]
        if not line.startswith('$'):
            return
        if STRICT_CHECKSUM and not nmea_checksum_ok(line):
            log.warning("Bad/missing checksum, dropping: %s", line)
            return

        body = line[1:line.find('*')] if '*' in line else line[1:]
        parts = body.split(',')
        talker = parts[0].upper()  # e.g., GPRMC/GNRMC, GPGGA/GNGGA

        upd = {}
        if talker.endswith("RMC"):
            upd = parse_gprmc(parts)
        elif talker.endswith("GGA"):
            upd = parse_gpgga(parts)

        if upd:
            log.info("Parsed %s -> %s", talker, upd)
            GLib.idle_add(self.gps.update, upd, priority=GLib.PRIORITY_DEFAULT)

    def run(self):
        self.server.start()
        GLib.MainLoop().run()

if __name__ == "__main__":
    App().run()