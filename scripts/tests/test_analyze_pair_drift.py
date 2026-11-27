"""Tests for the pair-drift evidence script (scripts/analyze_pair_drift.py). Fast: a made-up GrodanSens.csv.

Run with the model-router venv.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_pair_drift as apd

DAY = 1 / 288  # one 5-minute row, in Excel days
HEADER = "%time,EC_slab1,EC_slab2,WC_slab1,WC_slab2,t_slab1,t_slab2\n"


def write_compartment(folder, glitch=()):
    """400 rows: shared slow variation, slab 1 = slab 2 + 5 %; `glitch` rows get +20 % on slab 1."""
    folder.mkdir(parents=True)
    lines = [HEADER]
    for i in range(400):
        base = 60 + 4 * math.sin(i / 20) + 0.01 * (i % 7)
        slab1 = base + 5 + (20 if i in glitch else 0)
        lines.append(f"{43815 + i * DAY:.5f},  NaN,  NaN,  {slab1:.3f},  {base:.3f},  20.0,  20.5\n")
    (folder / "GrodanSens.csv").write_text("".join(lines))


def test_constant_offset_flags_nothing(tmp_path):
    write_compartment(tmp_path / "AICU")
    result = apd.lag0_table(tmp_path / "AICU")["moisture"]
    assert result["flagged"] == 0 and result["cards"] == 0
    assert result["pair_rows"] == 400 and result["judged"] == 400 - apd.MIN_N


def test_three_reading_glitch_is_three_flags_and_one_card(tmp_path):
    write_compartment(tmp_path / "Digilog", glitch=(200, 201, 202))
    result = apd.lag0_table(tmp_path / "Digilog")["moisture"]
    assert result["flagged"] == 3 and result["cards"] == 1
    assert result["pair"]["max"] > 19


def test_pair_rule_run_sees_the_glitch_and_nothing_else(tmp_path):
    write_compartment(tmp_path / "Digilog", glitch=(200, 201, 202))
    baseline = apd.load_module("trusted_baseline_test", apd.BASELINE_MODULE)
    one, two = apd.read_slabs(tmp_path / "Digilog", "WC_slab1", "WC_slab2")
    aligned = apd.run_pair_rule(baseline, one, two, 0)
    first = aligned["devices"]["slab-1"]
    # The jump itself is skipped as a fast change (and so is not vetoed); the two readings after it are flagged.
    assert first["skipped_fast"] >= 1 and first["flagged"] >= 2
    assert first["judged"] > 300
    clean = apd.run_pair_rule(baseline, one, one, 0)  # a probe against an identical one: nothing to flag
    assert clean["flagged"] == 0 and clean["cards"] == 0


def test_missing_uf_folder_is_skipped_and_exits_zero(tmp_path, capsys):
    write_compartment(tmp_path / "agc" / "AICU")
    code = apd.main([str(tmp_path / "no-uf"), str(tmp_path / "agc"), "--json", str(tmp_path / "out.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "UF skipped: folder not found" in out
    assert "BOUND EXCEEDED" not in out
    assert (tmp_path / "out.json").is_file()


def _lag0(flagged, cards):
    return {"Digilog": {"moisture": {"flagged": flagged, "cards": cards}},
            "AICU": {"moisture": {"flagged": 0, "cards": 0}}}


def test_bound_check():
    lag0 = _lag0(40, 2)

    def run(flagged, cards, name="Digilog"):
        return {"aligned": {name: {"flagged": flagged, "cards": cards}}}

    assert apd.bound_check(lag0, run(60, 2)) == []  # exactly 1.5x is within the bound
    assert "over 1.5x" in apd.bound_check(lag0, run(61, 2))[0]
    assert "cards where lag 0 had none" in apd.bound_check(lag0, run(0, 1, "AICU"))[0]


def test_bound_exceeded_exits_nonzero(tmp_path, capsys, monkeypatch):
    write_compartment(tmp_path / "agc" / "Digilog")
    monkeypatch.setattr(apd, "bound_check", lambda lag0, full: ["made-up problem"])
    code = apd.main([str(tmp_path / "no-uf"), str(tmp_path / "agc")])
    assert code == 2 and "BOUND EXCEEDED" in capsys.readouterr().out
