"""Write the two sample CSVs shipped with the checker (deterministic)."""
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "samples"
rng = random.Random(7)
start = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# 1) Pomona SD logger format (long): two nodes, 5-minute interval, with realistic faults.
rows = []
header = ["timestamp_utc", "boot_id", "sequence", "device_id", "farm_id", "zone_id", "sensor_id",
          "measurement", "unit", "raw", "value", "quality", "firmware"]
nodes = [("cress-hydro-node", "cress-hydro-a", ["air_temperature_c", "humidity_pct", "water_temperature_c", "ph"]),
         ("cress-soil-node", "cress-soil-a", ["air_temperature_c", "humidity_pct", "soil_moisture_pct"])]
units = {"air_temperature_c": "C", "humidity_pct": "%", "water_temperature_c": "C", "ph": "pH", "soil_moisture_pct": "%"}
sensors = {"air_temperature_c": "sht31-1", "humidity_pct": "sht31-1", "water_temperature_c": "ds18b20-1",
           "ph": "ph-probe-1", "soil_moisture_pct": "cap-moisture-1"}
for device, zone, fields in nodes:
    boot, seq = "a3f09c12", 0
    for step in range(36):
        t = start + timedelta(minutes=5 * step)
        if device == "cress-soil-node" and 14 <= step < 20:
            continue  # logging gap (SD card removed for 30 min)
        if device == "cress-hydro-node" and step == 24:
            boot, seq = "7b21e004", 0  # power cut: new boot id, sequence restarts
        for field in fields:
            seq += 1
            base = {"air_temperature_c": 19.5 + step * 0.05, "humidity_pct": 64 - step * 0.2,
                    "water_temperature_c": 17.2 + step * 0.02, "ph": 6.9 + rng.uniform(-0.03, 0.03),
                    "soil_moisture_pct": 48 - step * 0.15}[field]
            value, quality, raw, stamp = f"{base + rng.uniform(-0.1, 0.1):.2f}", "valid", "", iso(t)
            if field == "ph":
                raw = f"{1.52 + rng.uniform(-0.01, 0.01):.4f}"
            if device == "cress-soil-node" and field == "humidity_pct" and step >= 28:
                value = "58.40"  # stuck sensor
            if device == "cress-hydro-node" and field == "ph" and 8 <= step <= 10:
                value, quality = "", "disconnected"  # probe unplugged
            if device == "cress-soil-node" and field == "soil_moisture_pct" and step == 6:
                value = "err"
            if device == "cress-hydro-node" and step == 30 and field == "ph":
                value = "7.55"  # sudden jump worth a look
            if device == "cress-hydro-node" and 31 <= step and field == "ph":
                value = f"{7.5 + rng.uniform(-0.02, 0.02):.2f}"  # drifted away from start-up
            if device == "cress-soil-node" and step == 33:
                stamp = iso(t + timedelta(days=1))  # clock jumped a day ahead
            rows.append([stamp, boot, seq, device, "home-pilot", zone, sensors[field], field, units[field],
                         raw, value, quality, "cress-logger-0.1.0"])
with (OUT / "pomona_sd_log_example.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)

# 2) Wide spreadsheet-style hobby log: one row per reading time.
with (OUT / "wide_log_example.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time", "temperature", "humidity", "pH", "EC"])
    for step in range(48):
        t = datetime(2026, 10, 6, 0, 0, tzinfo=timezone(timedelta(hours=4))) + timedelta(minutes=15 * step)
        temp = 22 + step * 0.05 + rng.uniform(-0.3, 0.3)  # realistic cheap-sensor jitter
        hum = 70 - step * 0.1 + rng.uniform(-1.0, 1.0)
        ph, ec = 6.2 + rng.uniform(-0.05, 0.05), 1.4 + rng.uniform(-0.03, 0.03)
        row = [t.isoformat(), f"{temp:.2f}", f"{hum:.1f}", f"{ph:.2f}", f"{ec:.2f}"]
        if step == 10:
            row[3] = "14.9"  # impossible pH
        if step == 17:
            row[2] = "104.2"  # impossible humidity
        if step == 22:
            row[4] = ""  # missing EC
        if step == 30:
            row[0] = t.strftime("%Y-%m-%d %H:%M:%S")  # no timezone
        if step == 40:
            row[1] = "NaN"
        w.writerow(row)
print("wrote", sorted(p.name for p in OUT.iterdir()))
