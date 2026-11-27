// Per-cycle logging decisions for main.cpp. Plain C++ (no Arduino calls) so it can be tested on a PC:
//   c++ -std=c++17 -Wall -Wextra -Iinclude extras/test_cycle_logic.cpp -o /tmp/t && /tmp/t
//
// - One timestamp per logging cycle: loop() captures it once, every row of the cycle reuses it.
//   The offline Sensor Data Checker joins long-format rows into one packet per stream only when the
//   timestamp string is identical, and the DS18B20 conversion (~0.75 s) plus the pH median would
//   otherwise push the rows of one cycle into different seconds.
// - Retry of sensors that failed their boot init.
// - DS18B20 power-on value: the chip's temperature register reads exactly 85.0 C after power-up.
#pragma once

#include <math.h>
#include <stdio.h>
#include <time.h>

// The clock counts as set after 2024-01-01 00:00:00 UTC (strictly after: that second itself is not).
static const time_t CLOCK_VALID_AFTER = 1704067200;

struct CycleStamp {
  char text[25];  // "YYYY-MM-DDTHH:MM:SSZ", or "" when the clock is not set
  bool valid;     // false: rows are written with an empty timestamp and quality "suspect"
};

// Formats `now` once; the caller keeps the result for every row of the cycle.
inline CycleStamp makeCycleStamp(time_t now) {
  CycleStamp stamp;
  stamp.text[0] = '\0';
  stamp.valid = now > CLOCK_VALID_AFTER;
  if (stamp.valid) {
    struct tm utc;
    gmtime_r(&now, &utc);
    strftime(stamp.text, sizeof(stamp.text), "%Y-%m-%dT%H:%M:%SZ", &utc);
  }
  return stamp;
}

// Try a sensor's init again at the start of a cycle: only if it failed before and the build
// actually uses it (e.g. the ADS1115 only when the pH probe is fitted).
inline bool shouldRetryInit(bool alreadyOk, bool deviceInUse) { return !alreadyOk && deviceInUse; }

// DallasTemperature's DEVICE_DISCONNECTED_C (the library returns exactly this when the probe does not answer).
static const float DS18B20_DISCONNECTED_C = -127.0f;
// Power-on value of the DS18B20 temperature register (0x0550 = 85.0 C).
static const float DS18B20_POWER_ON_C = 85.0f;

struct Ds18b20Result {
  float value;              // NAN when no usable value (written as an empty value)
  const char *quality;      // "valid", "suspect" or "disconnected"
  char raw[8];              // "85.00" for a rejected power-on value, otherwise ""
  bool awaitingFirstGood;   // state to keep for the next read
};

// `awaitingFirstGood` is true at boot and after a read that came back disconnected (a re-plugged
// probe also powers up at 85 C). While it is true, an exact 85.0 is the power-on value, not a
// temperature: suspect, empty value, the reading kept in raw. Any other good read clears the state,
// so a later real 85.0 stays valid.
inline Ds18b20Result classifyDs18b20(float reading, bool awaitingFirstGood) {
  Ds18b20Result r;
  r.raw[0] = '\0';
  if (reading == DS18B20_DISCONNECTED_C) {
    r.value = NAN;
    r.quality = "disconnected";
    r.awaitingFirstGood = true;
    return r;
  }
  r.awaitingFirstGood = false;
  if (awaitingFirstGood && reading == DS18B20_POWER_ON_C) {
    r.value = NAN;
    r.quality = "suspect";
    snprintf(r.raw, sizeof(r.raw), "%.2f", (double)reading);
    return r;
  }
  r.value = reading;
  r.quality = "valid";
  return r;
}
