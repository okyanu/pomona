import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app
from app.probe_health import assess_probe, fit_calibration, probe_health
from app.store import event_store, SensorEventStore

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def point(reference, raw):
    return SimpleNamespace(reference=reference, raw=raw)


def calibration(day, mv_per_ph=180.0, v7=2.50, sensor="ph-probe-1", extra=()):
    """Two-point calibration of a probe whose volts fall as pH rises (like most boards)."""
    slope = -mv_per_ph / 1000.0
    pts = [point(7.0, v7), point(4.0, v7 - 3 * slope), *extra]
    return SimpleNamespace(farm_id="f", zone_id="z", device_id="node", sensor_id=sensor, measurement="ph",
                           points=pts, performed_at=T0 + timedelta(days=day), id=f"cal-{sensor}-{day}")


def status_of(*calibrations):
    return probe_health(calibrations, now=T0 + timedelta(days=60))[0]


def test_fit_matches_a_two_point_calibration():
    fit = fit_calibration(calibration(0).points)
    assert fit["sensitivity_mv_per_ph"] == pytest.approx(180.0)
    assert fit["v_at_ph7"] == pytest.approx(2.50)
    assert fit["slope_v_per_ph"] < 0 and fit["worst_fit_error_ph"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("points", [[], [point(7.0, 2.5)], [point(7.0, 2.5), point(7.0, 2.6)], [point(7.0, 2.5), point(4.0, 2.5)]])
def test_fit_returns_none_when_the_points_cannot_give_a_slope(points):
    assert fit_calibration(points) is None


def test_three_buffers_report_the_worst_residual():
    pts = calibration(0).points + [point(10.0, 2.50 - 3 * 0.18 + 0.10)]  # pH 10 reads 0.1 V off the line
    assert fit_calibration(pts)["worst_fit_error_ph"] > 0.1


def test_healthy_probe_stays_ok():
    entry = status_of(calibration(0), calibration(30, 176.0), calibration(60, 172.0, v7=2.52))
    assert entry["status"] == "ok" and entry["reasons"] == []
    assert entry["sensitivity_vs_first_pct"] == pytest.approx(95.6, abs=0.1)
    assert entry["calibrations"] == 3 and entry["days_since_last_calibration"] == 0.0


def test_weakening_then_worn_by_share_of_first_calibration():
    assert status_of(calibration(0), calibration(30, 150.0))["status"] == "weakening"   # 83 %
    worn = status_of(calibration(0), calibration(60, 135.0))                              # 75 %
    assert worn["status"] == "worn" and "clean the probe" in worn["reasons"][0]
    assert worn["sensitivity_lost_pct_per_30_days"] == pytest.approx(12.5)


def test_single_calibration_is_baseline_only_unless_it_is_implausible():
    assert status_of(calibration(0))["status"] == "baseline_only"
    assert status_of(calibration(0, mv_per_ph=3.0))["status"] == "suspect"   # identical-ish buffers
    assert status_of(calibration(0, mv_per_ph=900.0))["status"] == "suspect"


def test_points_off_the_line_make_the_latest_calibration_suspect():
    bad = calibration(30, extra=[point(10.0, 2.50 - 3 * 0.18 + 0.15)])
    entry = status_of(calibration(0), bad)
    assert entry["status"] == "suspect" and "do not lie on a line" in entry["reasons"][0]


def test_ph7_voltage_shift_is_flagged_even_with_good_sensitivity():
    entry = status_of(calibration(0), calibration(30, 180.0, v7=2.65))
    assert entry["status"] == "weakening" and "pH 7 voltage moved" in entry["reasons"][0]


def test_probes_are_separate_and_worst_comes_first():
    entries = probe_health([calibration(0, sensor="a"), calibration(30, 180.0, sensor="a"),
                            calibration(0, sensor="b"), calibration(30, 120.0, sensor="b")], now=T0)
    assert [(e["sensor_id"], e["status"]) for e in entries] == [("b", "worn"), ("a", "ok")]


def test_only_ph_calibrations_count():
    ec = calibration(0)
    ec.measurement = "ec_ms_cm"
    assert probe_health([ec]) == []


def test_empty_history_has_no_data():
    assert assess_probe([])["status"] == "no_data"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    yield


def _post(client, day, mv_per_ph, sensor="ph-probe-1", zone="z"):
    slope = -mv_per_ph / 1000.0
    body = {"device_id": "node", "farm_id": "f", "zone_id": zone, "sensor_id": sensor, "measurement": "ph",
            "method": "two_point_buffer", "performed_at": (T0 + timedelta(days=day)).isoformat(),
            "points": [{"reference": 7.0, "raw": 2.5}, {"reference": 4.0, "raw": round(2.5 - 3 * slope, 4)}]}
    return client.post("/v1/sensors/calibrations", json=body)


def test_api_reports_probe_health_per_scope():
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/v1/sensors/probe-health").json() == {"count": 0, "probes": []}
        assert _post(client, 0, 180.0).status_code == 201
        assert _post(client, 30, 140.0).status_code == 201
        assert _post(client, 0, 180.0, zone="other").status_code == 201
        everything = client.get("/v1/sensors/probe-health").json()
        assert everything["count"] == 2
        scoped = client.get("/v1/sensors/probe-health", params={"farm_id": "f", "zone_id": "z"}).json()
        assert scoped["count"] == 1
        probe = scoped["probes"][0]
        assert probe["status"] == "worn" and probe["sensor_id"] == "ph-probe-1"
        assert probe["latest"]["sensitivity_mv_per_ph"] == pytest.approx(140.0, abs=0.1)
