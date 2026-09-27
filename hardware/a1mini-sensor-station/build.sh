#!/usr/bin/env bash
# Rebuild every printable file from the OpenSCAD sources, then run the geometry checks.
# Needs OpenSCAD (2021.01 or newer) on PATH and python3.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p stl 3mf
render() { openscad -q --export-format binstl -o "stl/$2.stl" -D "part=\"$3\"" "src/$1"; }
for part in rail_fit ph ds18b20 hose moisture sht31 plate; do
  render pomona_sensor_mounts.scad "pomona_v6_3_$part" "$part"
done
render pomona_dual_station.scad pomona_station_hydro_v2 hydro
render pomona_dual_station.scad pomona_station_soil_v1 soil
openscad -q -o 3mf/pomona_v6_3_mounts_plate_a1mini.3mf -D 'part="plate"' src/pomona_sensor_mounts.scad
python3 tests/check_geometry.py
