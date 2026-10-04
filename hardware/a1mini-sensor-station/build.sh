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
render pomona_dual_station.scad pomona_station_soil_v2 soil
render pomona_probe_lid.scad pomona_probe_lid_v1 lid
render pomona_probe_lid.scad pomona_probe_lid_v1_fit_ring fit_ring
render pomona_seed_box.scad pomona_seed_box_v1 box
render pomona_seed_box.scad pomona_seed_box_v1_lid lid
openscad -q -o 3mf/pomona_seed_box_v1_plate_a1mini.3mf -D 'part="plate"' src/pomona_seed_box.scad
openscad -q -o 3mf/pomona_v6_3_mounts_plate_a1mini.3mf -D 'part="plate"' src/pomona_sensor_mounts.scad
# Check the lid at the smallest and a large container size too (not shipped as files).
variants=$(mktemp -d)
trap 'rm -rf "$variants"' EXIT
for id in 90 150; do
  openscad -q --export-format binstl -o "$variants/lid_$id.stl" -D 'part="lid"' -D "CONTAINER_ID=$id" src/pomona_probe_lid.scad
done
python3 tests/check_geometry.py --lid-variant=90:"$variants/lid_90.stl" --lid-variant=150:"$variants/lid_150.stl"
