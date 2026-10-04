// pH calibration sanity checks. Plain C++ (no Arduino calls) so it can be tested on a PC:
//   c++ -std=c++17 -Wall -Iinclude extras/test_ph_calibration.cpp -o /tmp/t && /tmp/t
//
// pH = slope * volts + offset (two-point calibration, pH 7 and pH 4 buffers). A wrong
// calibration is silent: it still produces plausible-looking numbers. These checks catch the
// common ways to get one: identical or swapped buffers, a dead or unplugged probe, a value
// typed wrongly into config.h, and (with an expected sensitivity) a worn probe.
#pragma once

#include <math.h>
#include <stdint.h>

#ifndef PH_SENS_MIN_PCT
#define PH_SENS_MIN_PCT 75.0f   // allowed sensitivity vs PH_EXPECTED_MV_PER_PH, lower bound (%)
#endif
#ifndef PH_SENS_MAX_PCT
#define PH_SENS_MAX_PCT 125.0f  // upper bound (%)
#endif

// Without an expected value, any real pH board still lands in this loose window
// (a bare probe is ~59 mV/pH at 25 C, a typical amplifier board ~180 mV/pH).
static const float PH_ABS_MIN_MV_PER_PH = 20.0f;
static const float PH_ABS_MAX_MV_PER_PH = 600.0f;
// The pH 7 voltage must sit inside what an ADS1115 powered at 3.3 V can read.
static const float PH_V7_MIN = 0.05f;
static const float PH_V7_MAX = 3.4f;

enum class PhCalState { Uncalibrated, Ok, Suspect };

struct PhCalResult {
  PhCalState state;
  const char *reason;   // short text, "" when ok
  float mv_per_ph;      // probe sensitivity implied by the slope (0 if unknown)
  float v_at_ph7;       // volts the calibration expects in pH 7 buffer (0 if unknown)
};

// expected_mv_per_ph: sensitivity of YOUR board output (0 = only use the loose window).
// expected_slope_sign: +1 if the board's volts rise with pH, -1 if they fall (most boards: acid gives
// a higher voltage, so -1), 0 = do not check. A flipped sign means the two buffers were swapped.
inline PhCalResult phCalibrationCheck(float slope, float offset, float expected_mv_per_ph = 0.0f,
                                      int expected_slope_sign = 0) {
  if (slope == 0.0f) return {PhCalState::Uncalibrated, "uncalibrated: PH_SLOPE is 0", 0.0f, 0.0f};
  if (!isfinite(slope) || !isfinite(offset)) return {PhCalState::Suspect, "slope or offset is not a number", 0.0f, 0.0f};
  float mv = 1000.0f / fabsf(slope);
  float v7 = (7.0f - offset) / slope;
  if (mv < PH_ABS_MIN_MV_PER_PH || mv > PH_ABS_MAX_MV_PER_PH)
    return {PhCalState::Suspect, "sensitivity outside 20-600 mV/pH: identical, swapped or wrong buffers?", mv, v7};
  if (v7 < PH_V7_MIN || v7 > PH_V7_MAX)
    return {PhCalState::Suspect, "pH 7 voltage outside 0.05-3.4 V: check PH_OFFSET and the ADS1115 supply", mv, v7};
  if ((expected_slope_sign > 0 && slope < 0.0f) || (expected_slope_sign < 0 && slope > 0.0f))
    return {PhCalState::Suspect, "slope direction is opposite to the board: buffers swapped?", mv, v7};
  if (expected_mv_per_ph > 0.0f) {
    float pct = 100.0f * mv / expected_mv_per_ph;
    if (pct < PH_SENS_MIN_PCT) return {PhCalState::Suspect, "sensitivity too low vs expected: worn probe or bad buffer", mv, v7};
    if (pct > PH_SENS_MAX_PCT) return {PhCalState::Suspect, "sensitivity too high vs expected: wrong buffer or gain", mv, v7};
  }
  return {PhCalState::Ok, "", mv, v7};
}

// One ADS1115 reading at the rail means no usable probe signal: a single-ended input reads about
// 0 when floating or shorted and saturates near 32767 when over range.
inline bool phReadingAtRail(int16_t raw) { return raw <= 8 || raw >= 32700; }
