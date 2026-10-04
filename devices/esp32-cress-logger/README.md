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
| hydro | analog pH probe via ADS1115 (0x48) ch0 | I2C | `ph` (+ raw volts; median of 15 reads) |

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

## Wi-Fi upload (firmware 0.2.0, optional)

With `WIFI_SSID`, `WIFI_PASSWORD` and `CORE_URL` (for example `http://192.168.1.50:8080`) in
`config.h`, the logger also sends its SD log to Pomona Core. The SD card stays the source of truth:

- Rows go out **oldest first**, one `POST /v1/sensors/observations` each, and a small
  `/pomona_<device>.ack` file on the card records how far Core has confirmed. It moves forward only
  when Core answers 2xx, or for a row Core can never accept (HTTP 400/413/422, a row without a
  timestamp, or `substrate_temperature_c`, which Core has no field for). Those are counted as
  skipped and shown in the serial line `upload: sent=… skipped=…`; they stay in the CSV.
- Any other trouble (Wi-Fi down, Core off, wrong `CORE_API_KEY`, 5xx) stops the session and keeps
  the offset. The next try comes after 30 s, 1 min, 2 min … up to 15 min, then every
  `UPLOAD_INTERVAL_MS` (default: every log interval) once it works again. An outage only delays
  data. Core ignores a repeated boot_id + sequence, so a resend after a lost reply is harmless.
- Wi-Fi is on only during a session (at most `UPLOAD_MAX_ROWS` = 120 rows or 45 s). A late NTP sync
  there gives every following row a real timestamp; rows logged before the clock was set stay
  without one and are skipped (never given a guessed time).
- `http://` only: use it on a trusted LAN (or a reverse proxy). Set `CORE_API_KEY` to Core's
  `API_KEY` if Core requires one. `raw` volts never leave the card.
- Decision logic is in `include/upload_logic.h`; host test:
  `c++ -std=c++17 -Iinclude extras/test_upload_logic.cpp -o /tmp/t && /tmp/t`.
  Not bench-tested on the board.

## Calibration

- **Moisture:** read the raw value with the probe in dry air, then in a glass of
  water. Put the two values in `MOISTURE_RAW_DRY` and `MOISTURE_RAW_WET`.
- **pH:** record the volts in pH 7 and pH 4 buffers (the `raw` column, probe fully settled and
  rinsed between buffers), then run
  `python3 tools/ph_calibrate.py --v7 <volts> --v4 <volts>`. It prints `PH_SLOPE` and `PH_OFFSET`
  for `config.h` and checks them. Add `--v10 <volts>` with a pH 10 buffer to test linearity.
  Then record the calibration in Core (see the pilot doc).
- **Calibration check (firmware 0.1.2).** At boot the logger prints a `ph_cal=` line. If the
  slope implies a sensitivity outside 20-600 mV/pH (identical, swapped or wrong buffers) or a pH 7
  voltage outside 0.05-3.4 V, every pH row is `suspect`, so a bad calibration cannot pass as good
  data. For a stricter check, set `PH_EXPECTED_MV_PER_PH` and `PH_EXPECTED_SLOPE_SIGN` in
  `config.h` (the calibrator prints both from a good calibration); then swapped buffers and a worn
  probe are flagged too. A pH reading at the ADC rail (probe unplugged or shorted) logs the raw
  volts with no value. Host tests: `c++ -std=c++17 -Iinclude extras/test_ph_calibration.cpp -o /tmp/t && /tmp/t`.
- Until calibrated, rows are `suspect`, with raw values only.
