#!/bin/sh
export PYTHONPATH=/opt/victronenergy/dbus-systemcalc-py/ext/velib_python
exec /data/scripts/venus_tcp_gps_bridge.py >> /data/logs/venus_tcp_gps_bridge.log 2>&1
