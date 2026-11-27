// Host test for include/cycle_logic.h. Build and run:
//   c++ -std=c++17 -Wall -Wextra -Iinclude extras/test_cycle_logic.cpp -o /tmp/t && /tmp/t
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include "cycle_logic.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

// 2026-10-05T06:00:07Z
static const time_t T0 = 1791180007;

int main() {
  // Exact format.
  CycleStamp s = makeCycleStamp(T0);
  CHECK(s.valid);
  CHECK(std::string(s.text) == "2026-10-05T06:00:07Z");
  CHECK(std::strlen(s.text) == 20);

  // One timestamp shared by every row of a cycle, even when the clock advances mid-cycle
  // (DS18B20 conversion ~0.75 s, 15 pH reads): rows use the stamp captured at the start.
  // This only checks the stamp is a stable value. That every row of a cycle uses it comes from
  // writeRow taking the CycleStamp (main.cpp), which this host test does not reach.
  CycleStamp cycle = makeCycleStamp(T0);
  time_t clockNow = T0;
  std::string rows[4];
  for (int i = 0; i < 4; i++) {
    clockNow = T0 + i;  // the live clock moves on between rows...
    rows[i] = cycle.text;  // ...but rows only ever read the captured stamp
  }
  CHECK(clockNow == T0 + 3);
  for (int i = 1; i < 4; i++) CHECK(rows[i] == rows[0]);
  CHECK(rows[0] == "2026-10-05T06:00:07Z");
  // A stamp taken per row would have differed (this is what v0.2.0 did):
  CHECK(std::string(makeCycleStamp(T0 + 2).text) != std::string(cycle.text));

  // Clock not set: empty string and invalid.
  CycleStamp none = makeCycleStamp(0);
  CHECK(!none.valid && none.text[0] == '\0');
  CycleStamp early = makeCycleStamp(1000000);
  CHECK(!early.valid && early.text[0] == '\0');

  // Cutoff boundary: 2024-01-01T00:00:00Z itself is not valid, one second later is.
  CHECK(!makeCycleStamp(1704067200).valid);
  CHECK(makeCycleStamp(1704067200).text[0] == '\0');
  CycleStamp edge = makeCycleStamp(1704067201);
  CHECK(edge.valid && std::string(edge.text) == "2024-01-01T00:00:01Z");

  // Retry decision: only a failed sensor that the build uses.
  CHECK(shouldRetryInit(false, true));
  CHECK(!shouldRetryInit(true, true));
  CHECK(!shouldRetryInit(false, false));  // e.g. ADS1115 on a node without the pH probe
  CHECK(!shouldRetryInit(true, false));

  // DS18B20: first read exactly 85.0 is the power-on value.
  Ds18b20Result r = classifyDs18b20(85.0f, true);
  CHECK(std::isnan(r.value) && std::string(r.quality) == "suspect" && std::string(r.raw) == "85.00");
  CHECK(!r.awaitingFirstGood);
  // A second 85.0 is a real reading.
  Ds18b20Result r2 = classifyDs18b20(85.0f, r.awaitingFirstGood);
  CHECK(r2.value == 85.0f && std::string(r2.quality) == "valid" && r2.raw[0] == '\0');
  // First read 84.9375 is valid and clears the state, so a following 85.0 stays valid.
  Ds18b20Result g = classifyDs18b20(84.9375f, true);
  CHECK(g.value == 84.9375f && std::string(g.quality) == "valid" && g.raw[0] == '\0' && !g.awaitingFirstGood);
  CHECK(std::string(classifyDs18b20(85.0f, g.awaitingFirstGood).quality) == "valid");
  // Ordinary reading.
  Ds18b20Result n = classifyDs18b20(18.25f, true);
  CHECK(n.value == 18.25f && std::string(n.quality) == "valid" && !n.awaitingFirstGood);
  // Disconnected: no value, state is set again, so a re-plugged probe's 85.0 is suspect.
  Ds18b20Result d = classifyDs18b20(-127.0f, false);
  CHECK(std::isnan(d.value) && std::string(d.quality) == "disconnected" && d.raw[0] == '\0' && d.awaitingFirstGood);
  Ds18b20Result back = classifyDs18b20(85.0f, d.awaitingFirstGood);
  CHECK(std::isnan(back.value) && std::string(back.quality) == "suspect" && std::string(back.raw) == "85.00");
  // Disconnected on the very first read: still waiting for the first good one.
  Ds18b20Result d0 = classifyDs18b20(-127.0f, true);
  CHECK(std::string(d0.quality) == "disconnected" && d0.awaitingFirstGood);
  CHECK(std::string(classifyDs18b20(85.0f, d0.awaitingFirstGood).quality) == "suspect");
  // Only an exact 85.0 counts: 85.0625 (next step up) is valid even as the first read.
  CHECK(std::string(classifyDs18b20(85.0625f, true).quality) == "valid");

  std::printf(failures ? "FAILED: %d\n" : "all cycle_logic checks pass\n", failures);
  return failures ? 1 : 0;
}
