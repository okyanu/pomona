# Pomona A1 mini sensor station (V6.3)

3D-printable parts for a small Pomona monitoring station, sized for a Bambu Lab A1 mini
(180 × 180 mm bed). They are open source under **Apache-2.0**, like the rest of Pomona:
anyone may print, modify, remix and sell them, keeping the licence and attribution.

- **Stations** (`src/pomona_dual_station.scad`): a hydroponic body (Hydro V2, 76 × 70 mm)
  and a soil catch tray (Soil V1, 76 × 25 mm). Both hold a 50 mm pot with a 52 mm rim, and
  both have three external T-rails.
- **Sensor mounts** (`src/pomona_sensor_mounts.scad`): clips that slide onto those rails and
  hold a pH probe, a DS18B20 temperature probe, an airline hose, a capacitive soil-moisture
  board and an SHT31 air sensor.

Every file in `stl/` and `3mf/` is generated from these two sources by `build.sh`.

## Files

| File | What it is | Print |
|---|---|---|
| `3mf/pomona_v6_3_mounts_plate_a1mini.3mf` | All six mounts on one plate | Open in Bambu Studio |
| `stl/pomona_v6_3_rail_fit.stl` | Rail fit test clip. **Print this first** | 1 |
| `stl/pomona_v6_3_ph.stl` | pH probe sleeve (12 mm probe) | 1 |
| `stl/pomona_v6_3_ds18b20.stl` | DS18B20 sleeve (6 mm probe) | 1 per probe |
| `stl/pomona_v6_3_hose.stl` | Vertical airline clip (6 mm tubing, snap-in) | 1–3 |
| `stl/pomona_v6_3_moisture.stl` | Capacitive moisture board slot (23 × 1.6 mm board) | 1 |
| `stl/pomona_v6_3_sht31.stl` | SHT31 post with vented, roofed cage | 1 per zone |
| `stl/pomona_station_hydro_v2.stl` | Hydroponic station body | 1 |
| `stl/pomona_station_soil_v1.stl` | Soil catch tray | 1 |

The 50 mm seedling pot itself is not included. Use any pot or net pot with a 50 mm body and a
52 mm rim.

## Print settings

- Scale 100 %, 0.4 mm nozzle, 0.20 mm layers, **supports off**. Every mount is modelled
  standing on the bed; `tests/check_geometry.py` confirms there is no unsupported overhang
  beyond short bridges (the SHT31 cage roof and vent slots).
- **PETG** for anything that touches nutrient solution or wet soil. PLA softens and degrades
  in warm water. Neither is certified food-safe.
- Brim recommended for the tall SHT31 post.

## Rail fit

The mounts use the locked `MASTER_RAIL_030` socket: 0.30 mm total clearance on the station's
T-rail (head 11.0 × 1.6 mm, neck 8.0 mm), chosen from the V5.7 fit test (0.25 / 0.40 / 0.55 mm).
Print `rail_fit` first. It should slide on without force and not wobble. If your printer
runs tighter or looser, change `total_clearance` in `MASTER_RAIL_030` and rebuild.

## Adjusting to your parts

Edit the parameters at the top of `src/pomona_sensor_mounts.scad`, then run `./build.sh`:

| Parameter | Default | Meaning |
|---|---|---|
| `PH_PROBE_D` | 12.0 | pH probe body diameter |
| `DS_PROBE_D` | 6.0 | DS18B20 sleeve diameter |
| `HOSE_OD` | 6.0 | Airline tubing outer diameter |
| `MOIST_BOARD_W`, `MOIST_BOARD_T` | 23.0, 1.6 | Moisture board width and thickness |
| `SHT_POCKET` | 20 × 12 × 16 | SHT31 module pocket (depth, width, height) |
| `PROBE_CLEAR`, `HOSE_CLEAR`, `SLOT_CLEAR` | 0.6, 0.4, 0.6 | Fit clearances |

## Rebuild and check

```bash
./build.sh            # needs OpenSCAD and python3
```

`build.sh` renders every STL and the 3MF plate, then runs `tests/check_geometry.py`, which
fails if any mount:

- reaches into the rail slot, or behind the socket into the vessel wall;
- blocks its own probe, hose or board path;
- is not a closed mesh, does not fit the A1 mini, or needs supports.

## Changes in V6.3 (from V6.2 MASTER030)

- **pH, DS18B20 and hose holders fixed.** In V5.9–V6.2 the rings were centred 3–4 mm in
  front of the socket, so the socket's front wall ran through the probe/hose hole, and the pH and DS18B20 rings reached 1.6–4.6 mm
  behind the socket into the vessel wall. Rings now sit fully in front, joined by a web.
- Hose clip is a vertical snap-in sleeve with 0.4 mm clearance (was a horizontal ring with
  no clearance that needed supports).
- SHT31 cage has side vents, a roof and an open front for airflow and drips. A tapered base
  and a 45° cone under the cage make it printable without supports.
- Moisture slot sized for 23 mm capacitive boards (was 10 × 8 mm).
- Parameters for probe sizes; geometry checks; reproducible build.

## Known limitations

- **The mounts hold probes beside the station, not in it.** A probe in the pH sleeve is
  about 14 mm outside the vessel wall, and the pot closes the top. To measure the water, the
  probe must reach the reservoir. For now, use the mounts with a larger container or bucket,
  or run the probe over the rim. A lid with probe ports is the next design step.
- The Hydro V2 reservoir holds about 0.24 L. That is fine for germination, but small for
  deep-water culture: temperature and nutrient levels swing quickly, and an air stone and probes need room.
- Not yet print-tested as V6.3. The rail socket is unchanged from the tested V5.7/V6.x
  clip; the other changes are verified geometrically, not on a printer.

## Credits

Designed by Okyanus for [Pomona](https://github.com/okyanu/pomona). Licensed under
Apache-2.0 (see the repository `LICENSE`). If you publish a remix, please link back to this folder.
