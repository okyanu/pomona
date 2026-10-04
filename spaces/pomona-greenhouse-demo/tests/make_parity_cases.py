#!/usr/bin/env python3
"""Write parity_cases.json: random and boundary tomato inputs with the Python rules' answers.

Run with the model-router environment (it imports services/model-router/app/tomato_reasoner.py):
  services/model-router/.venv/bin/python spaces/pomona-greenhouse-demo/tests/make_parity_cases.py
parity.test.cjs then runs the demo page's own JavaScript rules on the same inputs.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/model-router"))
from app.tomato_reasoner import derive_tomato_risk  # noqa: E402

rng = random.Random(1004)
systems = ["controlled_greenhouse", "hydroponic", "greenhouse_substrate", "hydroponic_greenhouse"]


def pick(lo, hi, digits):
    return rng.choice([None, round(rng.uniform(lo, hi), digits)])


cases = [{"system_type": rng.choice(systems), "crop": "tomato", "growth_stage": "flowering",
          "air_temperature_c": pick(-10, 65, 1), "humidity_pct": pick(-5, 105, 1), "ph": pick(3, 10, 2),
          "ec_ms_cm": pick(0, 11, 2), "substrate_temperature_c": pick(5, 40, 1),
          "substrate_moisture_pct": pick(0, 100, 1)} for _ in range(20000)]
for temp in (-5, 0, 10, 17, 20, 24, 28, 35, 60):  # VPD threshold and range boundaries
    for humidity in (0, 35, 60, 75, 80, 84.9, 85, 90, 100):
        cases.append({"system_type": "controlled_greenhouse", "crop": "tomato", "growth_stage": "fruiting",
                      "air_temperature_c": temp, "humidity_pct": humidity, "ph": 6.2, "ec_ms_cm": 2.4,
                      "substrate_temperature_c": 22, "substrate_moisture_pct": 45})
expected = [derive_tomato_risk(case) for case in cases]
out = Path(__file__).with_name("parity_cases.json")
out.write_text(json.dumps({"cases": cases, "expected": expected}))
low_vpd = sum(1 for c, e in zip(cases, expected)
              if e["vpd_kpa"] is not None and e["vpd_kpa"] < 0.4 and (c["humidity_pct"] or 0) < 85)
print(f"{len(cases)} cases ({low_vpd} reach fungal_pressure only through low VPD) -> {out.name}")
