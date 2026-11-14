"""The pipeline audit file is bounded (rotated to `<name>.1`) and read from its end."""

import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app import audit
from app.config import settings


@pytest.fixture
def log(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "audit_log_path", path)
    monkeypatch.setattr(settings, "audit_log_max_bytes", 0)
    return path


def write(n, start=0):
    for i in range(start, start + n):
        audit.write_pipeline_audit({"pipeline_id": f"p{i}", "padding": "x" * 40})


def test_default_limit_is_20_mb():
    assert settings.audit_log_max_bytes == 20 * 1024 * 1024


def test_file_is_rotated_to_one_old_file_when_it_reaches_the_limit(log, monkeypatch):
    monkeypatch.setattr(settings, "audit_log_max_bytes", 1000)
    write(100)
    rotated = log.with_name("audit.jsonl.1")
    assert rotated.exists() and sorted(p.name for p in log.parent.iterdir()) == ["audit.jsonl", "audit.jsonl.1"]
    assert log.stat().st_size < 1000 + 120 and rotated.stat().st_size < 1000 + 120
    newest = audit.read_pipeline_audit(3)
    assert [e["pipeline_id"] for e in newest] == ["p99", "p98", "p97"]


def test_rotation_off_keeps_one_growing_file(log):
    write(100)
    assert not log.with_name("audit.jsonl.1").exists()
    assert len(log.read_text().splitlines()) == 100


def test_read_takes_the_newest_lines_from_the_end_without_reading_the_whole_file(log, monkeypatch):
    write(3000)  # well over one 8 KiB chunk
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("the whole file was read"))
    events = audit.read_pipeline_audit(5)
    assert [e["pipeline_id"] for e in events] == ["p2999", "p2998", "p2997", "p2996", "p2995"]
    assert len(audit.read_pipeline_audit(200)) == 200


def test_read_skips_a_corrupt_line_and_handles_a_short_or_missing_file(log):
    assert audit.read_pipeline_audit(10) == [] and audit.read_pipeline_audit(0) == []
    log.write_text('{"pipeline_id": "a"}\nnot json\n{"pipeline_id": "b"}')
    assert [e["pipeline_id"] for e in audit.read_pipeline_audit(10)] == ["b", "a"]


def test_read_tops_up_from_the_rotated_file_right_after_a_rotation(log):
    log.with_name("audit.jsonl.1").write_text('{"pipeline_id": "old1"}\n{"pipeline_id": "old2"}\n')
    log.write_text('{"pipeline_id": "new1"}\n')
    assert [e["pipeline_id"] for e in audit.read_pipeline_audit(3)] == ["new1", "old2", "old1"]
    assert [e["pipeline_id"] for e in audit.read_pipeline_audit(1)] == ["new1"]
