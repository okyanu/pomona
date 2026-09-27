"""SD-card CSV importer against the real Core app (scripts/import_sd_csv.py)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from app.main import app  # noqa: E402
from app.store import event_store, SensorEventStore  # noqa: E402

spec = importlib.util.spec_from_file_location("import_sd_csv", REPO_ROOT / "scripts" / "import_sd_csv.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)

SD_CSV = """timestamp_utc,boot_id,sequence,device_id,farm_id,zone_id,sensor_id,measurement,unit,raw,value,quality,firmware
2026-10-01T08:00:00Z,b1,1,cress-hydro-node,home-pilot,cress-hydro-a,ds18b20-1,water_temperature_c,C,,18.2,valid,cress-logger-0.1
2026-10-01T08:00:00Z,b1,2,cress-hydro-node,home-pilot,cress-hydro-a,sht31-1,humidity_pct,%,,61.5,valid,cress-logger-0.1
2026-10-01T08:00:00Z,b1,2,cress-hydro-node,home-pilot,cress-hydro-a,sht31-1,humidity_pct,%,,61.5,valid,cress-logger-0.1
2026-10-01T08:05:00Z,b1,3,cress-hydro-node,home-pilot,cress-hydro-a,sht31-1,humidity_pct,C,,61.0,valid,cress-logger-0.1
,b1,4,cress-hydro-node,home-pilot,cress-hydro-a,sht31-1,air_temperature_c,C,,21.0,suspect,cress-logger-0.1
2026-10-01T08:10:00Z,b1,5,cress-soil-node,home-pilot,cress-soil-a,cap-1,soil_moisture_pct,%,2210,,disconnected,cress-logger-0.1
2026-10-01T08:10:00Z,b1,6,cress-soil-node,home-pilot,cress-soil-a,ds18b20-1,substrate_temperature_c,C,,17.9,valid,cress-logger-0.1
"""

MANUAL_CSV = """# hand-entered meter readings
timestamp_utc,zone_id,measurement,value
2026-10-01T09:00:00+04:00,cress-hydro-a,ph,6.9
2026-10-01T09:00:00+04:00,cress-hydro-a,ec_ms_cm,0.9
2026-10-01T09:00:00,cress-hydro-a,ph,6.8
"""


@pytest.fixture(autouse=True)
def clear_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    yield


@pytest.fixture
def post():
    with TestClient(app) as client:
        def _post(path, payload):
            response = client.post(path, json=payload)
            return response.status_code, response.text
        yield _post


def _run(tmp_path, text, post, defaults=None, name="LOG.CSV"):
    path = tmp_path / name
    path.write_text(text)
    return importer.import_rows(importer.read_csv_rows([path]), defaults or {}, post)


def test_sd_csv_import_reports_rejects_and_skips_duplicates(tmp_path, post):
    summary = _run(tmp_path, SD_CSV, post)

    assert summary["accepted"] == 3
    assert summary["duplicates"] == 1
    assert summary["sd_only_skipped"] == 1
    reasons = {item["row"]: item["reason"] for item in summary["rejected"]}
    assert reasons["LOG.CSV:5"].startswith("HTTP 422")  # wrong unit, rejected by Core
    assert reasons["LOG.CSV:6"] == "missing timestamp"

    stored = event_store.list_observations(50, "home-pilot", None)
    assert len(stored) == 3
    assert any(item.quality == "disconnected" and item.value is None for item in stored)


def test_reimport_is_idempotent(tmp_path, post):
    _run(tmp_path, SD_CSV, post)
    _run(tmp_path, SD_CSV, post)
    assert len(event_store.list_observations(50, "home-pilot", None)) == 3


def test_manual_readings_use_defaults_and_require_timezone(tmp_path, post):
    summary = _run(tmp_path, MANUAL_CSV, post, {"farm_id": "home-pilot"}, name="manual.csv")

    assert summary["accepted"] == 2
    assert summary["rejected"][0]["reason"].startswith("timestamp must include a timezone")
    stored = event_store.list_observations(50, "home-pilot", "cress-hydro-a")
    assert {item.sensor_id for item in stored} == {"manual-ph", "manual-ec_ms_cm"}
    assert {item.device_id for item in stored} == {"manual-log"}


def test_dry_run_posts_nothing(tmp_path):
    summary = _run(tmp_path, SD_CSV, None)
    assert summary["accepted"] == 4  # wrong unit is only caught by Core
    assert event_store.list_observations(50, None, None) == []
