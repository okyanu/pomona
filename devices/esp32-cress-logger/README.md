# ESP32 cress logger (SD card, monitoring only)

Firmware for the [watercress pilot](../../docs/WATERCRESS_PILOT.md). One ESP32-S3
per zone writes sensor readings to a CSV file on a microSD card. Import the file
into Pomona Core afterwards with `scripts/import_sd_csv.py`.

**Status: compiles cleanly (PlatformIO 6.2, espressif32, 2026-09-27) for the hydro
node, the soil node and with Wi-Fi clock sync enabled: about 6 % RAM and 11 % flash. Not yet
bench-tested on hardware.** Treat the first 24–48 h dry run as the real test. The firmware drives no pumps, relays or dosing. Run
the air pump from its own plug.

## Sensors

| Zone | Sensor | Bus | Measurement written |
|---|---|---|---|
| both | SHT31 (0x44) | I2C | `air_temperature_c`, `humidity_pct` |
| hydro | DS18B20 in reservoir | OneWire + 4.7 kΩ pull-up | `water_temperature_c` |
| soil | DS18B20 in substrate | OneWire + 4.7 kΩ pull-up | `substrate_temperature_c` (SD only, not imported yet) |
| soil | capacitive moisture probe | ADC | `soil_moisture_pct` (+ raw ADC) |
| hydro | analog pH probe via ADS1115 (0x48) ch0 | I2C | `ph` (+ raw volts) |

The shopping list has no EC probe. Measure EC with a handheld meter and enter
it in the manual readings CSV (see the pilot doc).

## Build and flash

```bash
cp include/config.example.h include/config.h   # edit per node; gitignored
pio run -t upload && pio device monitor
```

`config.h` sets the device, farm and zone IDs, the pins (check them against your
board's pinout), the log interval and calibration constants. Wi-Fi is used only
for a one-time NTP clock sync at boot, then switched off. Without Wi-Fi or an RTC,
rows get an **empty timestamp** and the importer rejects them, rather than
storing a guessed time.

## CSV format

`/pomona_<device_id>.csv`, one row per measurement:

```text
timestamp_utc,boot_id,sequence,device_id,farm_id,zone_id,sensor_id,measurement,unit,raw,value,quality,firmware
```

- `boot_id` is a new random value on every power-up. `sequence` counts up
  within that boot. Together they make re-imports duplicate-free.
- `quality` is `valid`, `missing`, `suspect` (uncalibrated or no clock) or
  `disconnected`. Rows that are not valid have an empty `value`.
- `raw` keeps the ADC value or volts, so readings can be recalculated after a
  later calibration.

## Calibration

- **Moisture:** read the raw value with the probe in dry air, then in a glass of
  water. Put the two values in `MOISTURE_RAW_DRY` and `MOISTURE_RAW_WET`.
- **pH:** record the volts in pH 7 and pH 4 buffers. Set
  `PH_SLOPE = (7-4)/(V7-V4)` and `PH_OFFSET = 7 - PH_SLOPE*V7`. Then record the
  calibration in Core (see the pilot doc).
- Until calibrated, rows are `suspect`, with raw values only.
