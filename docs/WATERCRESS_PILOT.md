# Watercress pilot (monitoring only)

A small two-zone trial to collect Pomona's first real sensor data: one
**hydroponic** and one **soil** zone of watercress (*Nasturtium officinale*),
sown at the same time. The aim is a trustworthy data set, not automation.
Pomona drives no pumps, dosing or relays in this pilot.

## Zones and IDs

| | Hydro | Soil |
|---|---|---|
| `farm_id` | `home-pilot` | `home-pilot` |
| `zone_id` | `cress-hydro-a` | `cress-soil-a` |
| `device_id` | `cress-hydro-node` | `cress-soil-node` |
| `crop` | `watercress` | `watercress` |
| `system_type` | `hydroponic_dwc` (or `hydroponic_passive`) | `soil_pot` |
| Logged by node | air temp, RH, water temp, pH (ADS1115) | air temp, RH, substrate temp, soil moisture |
| Logged by hand | EC, pH check, water temp check | — |

**Hydro method:** watercress naturally grows in cool, moving and oxygenated
water, so **DWC with the air pump and air stone** is the recommended setup.
Kratky/passive is an acceptable fallback if the pump or fittings aren't ready.
Record which one you used as `system_type`.

## Tools

- Firmware: [`devices/esp32-cress-logger`](https://github.com/okyanu/pomona/tree/main/devices/esp32-cress-logger)
  writes CSV to SD. It has not been bench-tested yet.
- Importer: `scripts/import_sd_csv.py` sends SD and manual CSV rows to Core. It
  reports rejected rows, and re-importing the same file is safe.
- 3D-printed mounts: [`hardware/a1mini-sensor-station`](https://github.com/okyanu/pomona/tree/main/hardware/a1mini-sensor-station)
  holds the probes on a rail (soil tray, SHT31). For the hydro zone, print its **probe lid**
  for a 1–2 L round container: pot seat plus pH, DS18B20, airline and float-switch ports that
  put the probes in the water. Print the fit ring first; not print-tested yet.
- Templates: `examples/pilot/manual_readings.csv` (meter readings) and
  `examples/pilot/watercress_plant_log.csv` (plant observations).

```bash
# Before the pilot: in .env set RETENTION_DAYS=120. The default of 7 counts
# from import time, so older pilot data would otherwise be pruned.
./scripts/up.sh
python3 scripts/import_sd_csv.py /Volumes/SD/pomona_cress-hydro-node.csv --dry-run
python3 scripts/import_sd_csv.py /Volumes/SD/pomona_cress-hydro-node.csv
python3 scripts/import_sd_csv.py examples/pilot/manual_readings.csv --farm-id home-pilot
```

**Always keep the original SD CSV files** (for example under
`private/pilot-data/`). They are the raw record. The Core database is a working
copy.

Record probe calibrations in Core so later readings have provenance (`raw` is the probe voltage
in volts; the dashboard's *pH probe health* panel then tracks sensitivity from one calibration to
the next):

```bash
curl -X POST localhost:8080/v1/sensors/calibrations -H 'Content-Type: application/json' -d '{
  "device_id":"cress-hydro-node","farm_id":"home-pilot","zone_id":"cress-hydro-a",
  "sensor_id":"ph-probe-1","measurement":"ph","method":"two_point_buffer",
  "points":[{"reference":7.0,"raw":1.50},{"reference":4.0,"raw":2.03}],
  "performed_at":"2026-10-04T18:00:00+04:00","notes":"example values - use your readings"}'
```

## Schedule

1. **Dry run (before sowing, 24–48 h, no plants).** Both nodes log with water and
   soil in place. Pull the power once to check that a new `boot_id` appears and
   the rows continue. Import, then check both zones in the dashboard's
   **Modular observations** history and in
   `/v1/sensors/export.csv?kind=observations&farm_id=home-pilot`. Fix wiring or pins before sowing.
2. **Day 0: sowing.** Record:
   - seed source and lot
   - sowing date and time
   - seeds per zone and sowing density
   - medium (soil type; hydro net pot and medium)
   - starting water pH, EC and temperature
   - a photo of each zone
   - a calibration record for each probe
3. **Daily.** Add a row to the plant log: germinated count, mean height,
   leaf colour 1–5, wilting or yellowing, water top-up, photo. Take one handheld
   pH/EC/water-temperature reading in the hydro zone and add it to
   `manual_readings.csv`.
4. **Every 2–3 days.** Copy the SD files to the Mac and import them. Check the
   import summary for rejected rows.
5. **Weekly.** Compare the probe pH with the handheld pH to spot drift, and
   recalibrate if they differ by more than about 0.3 pH.

## Reference ranges (advisory, not wired into rules)

The ranges below are commonly cited values for watercress. They have **not been
checked against a reviewed source** in this repo, so treat them as a note to
verify:

- water temperature roughly 10–20 °C (it dislikes warm water)
- pH roughly 6.5–7.5
- low to moderate EC

Imported readings are *modular observations*. They are stored, shown and
exported, but they do not feed the reasoner pipeline yet. That is intended for
a monitoring-only pilot. Pomona currently has **no watercress reasoner**. The tomato-risk endpoint
returns `source: not_applicable` for other crops. The generic nutrient pH/EC
reasoner still applies its general bands, such as `high_ph` at 7.2 and above.
For watercress those labels are review prompts, not crop advice.

## What this pilot does not claim

- It does not validate the sensors. The dry run and handheld cross-checks are
  the evidence.
- It does not use a watercress model or threshold rules.
- It has no actuator path. Approving a suggestion only records a decision.

After 2–3 weeks of clean data, the next steps are:

- replaying the digital twin against persistence on a real single-zone log
- a watercress simulator scenario (GitHub issue #3)
- possibly an anonymised dataset release, which needs separate approval
