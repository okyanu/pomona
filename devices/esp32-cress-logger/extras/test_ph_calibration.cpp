// Host test for include/ph_calibration.h. Build and run:
//   c++ -std=c++17 -Wall -Iinclude extras/test_ph_calibration.cpp -o /tmp/t && /tmp/t
#include <cstdio>
#include <cstdlib>
#include "ph_calibration.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

// slope/offset from two buffer readings, as the README formula does it.
static void cal(float v7, float v4, float &slope, float &offset) {
  slope = (7.0f - 4.0f) / (v7 - v4);
  offset = 7.0f - slope * v7;
}

int main() {
  float s, o;
  CHECK(phCalibrationCheck(0.0f, 0.0f).state == PhCalState::Uncalibrated);

  cal(2.50f, 3.04f, s, o);  // typical analog board: ~180 mV/pH, 2.5 V at pH 7
  PhCalResult r = phCalibrationCheck(s, o);
  CHECK(r.state == PhCalState::Ok && fabsf(r.mv_per_ph - 180.0f) < 1.0f && fabsf(r.v_at_ph7 - 2.5f) < 0.001f);
  CHECK(phCalibrationCheck(s, o, 180.0f).state == PhCalState::Ok);
  CHECK(phCalibrationCheck(s, o, 59.16f).state == PhCalState::Suspect);   // way above a bare probe
  CHECK(phCalibrationCheck(s, o, 250.0f).state == PhCalState::Suspect);   // worn: 72 % of expected

  cal(2.50f, 2.51f, s, o);  // same buffer twice (10 mV apart): slope huge, sensitivity ~3 mV/pH
  CHECK(phCalibrationCheck(s, o).state == PhCalState::Suspect);
  cal(2.50f, 2.50f, s, o);  // identical readings: division by zero gives inf
  CHECK(phCalibrationCheck(s, o).state == PhCalState::Suspect);

  cal(3.04f, 2.50f, s, o);  // buffers swapped: slope sign flips but magnitude still plausible
  CHECK(phCalibrationCheck(s, o).state == PhCalState::Ok);  // the magnitude check cannot see a sign flip
  CHECK(s > 0.0f);                                          // ...but the sign is visible to the caller
  CHECK(phCalibrationCheck(s, o, 0.0f, -1).state == PhCalState::Suspect);  // board falls with pH: swapped
  CHECK(phCalibrationCheck(s, o, 0.0f, +1).state == PhCalState::Ok);
  cal(2.50f, 3.04f, s, o);
  CHECK(s < 0.0f && phCalibrationCheck(s, o, 180.0f, -1).state == PhCalState::Ok);
  CHECK(phCalibrationCheck(s, o, 180.0f, +1).state == PhCalState::Suspect);

  cal(4.80f, 5.34f, s, o);  // pH 7 at 4.8 V: ADS1115 on 3.3 V cannot read that
  CHECK(phCalibrationCheck(s, o).state == PhCalState::Suspect);
  CHECK(phCalibrationCheck(NAN, 1.0f).state == PhCalState::Suspect);
  CHECK(phCalibrationCheck(5.0f, INFINITY).state == PhCalState::Suspect);

  CHECK(phReadingAtRail(0) && phReadingAtRail(-3) && phReadingAtRail(32767) && phReadingAtRail(8));
  CHECK(!phReadingAtRail(9) && !phReadingAtRail(15000) && !phReadingAtRail(32699));

  std::printf(failures ? "FAILED: %d\n" : "all ph_calibration checks pass\n", failures);
  return failures ? 1 : 0;
}
