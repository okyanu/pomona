"""Live API checks, called only by the isolated temporary-state validation runner."""
import csv
import io
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main(core, dashboard):
    def request(base, path, payload=None, raw=False):
        req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as response:
            value = response.read().decode()
        return value if raw else json.loads(value)

    for zone, temperature in [("a", 24), ("b", 34)]:
        event = {"device_id": "scoped-" + zone, "farm_id": "validation-only", "zone_id": zone,
                 "air_temperature_c": temperature, "humidity_pct": 92, "ph": 6,
                 "ec_ms_cm": 4.5, "soil_moisture_pct": 45,
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        request(core, "/v1/sensors/events", event)
    for zone, temperature in [("a", 24), ("b", 34)]:
        query = "?" + urlencode({"farm_id": "validation-only", "zone_id": zone})
        overview = request(dashboard, "/api/overview" + query)
        assert overview["latest_event"]["air_temperature_c"] == temperature
        assert all(e["zone_id"] == zone for e in overview["recent_events"])
        devices = request(dashboard, "/api/devices" + query)["result"]["devices"]
        assert len(devices) == 1 and devices[0]["zone_id"] == zone
        rows = list(csv.DictReader(io.StringIO(request(dashboard, "/api/history/export.csv" + query, raw=True))))
        assert len(rows) == 1 and rows[0]["zone_id"] == zone
        first = request(dashboard, "/api/automation/evaluate" + query, {})
        second = request(dashboard, "/api/automation/evaluate" + query, {})
        assert first["available"] and second["available"]
        ids = lambda value: sorted(s["id"] for s in value["result"]["suggestions"])
        assert ids(first) and ids(first) == ids(second)
        visible = request(dashboard, "/api/automation" + query)["result"]["suggestions"]
        assert all(s["context"]["zone_id"] == zone for s in visible)
    print("Live scoped validation passed: two zones, device health, CSV, suggestion isolation and retry deduplication")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
