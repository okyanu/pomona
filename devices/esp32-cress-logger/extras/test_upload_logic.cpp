// Host test for include/upload_logic.h. Build and run:
//   c++ -std=c++17 -Wall -Wextra -Iinclude extras/test_upload_logic.cpp -o /tmp/t && /tmp/t
#include <cstdio>
#include <cstring>
#include <string>
#include "upload_logic.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

static const char *GOOD = "2026-10-05T08:00:00Z,0a1b2c3d4e5f6071,42,cress-hydro-node,home-pilot,cress-hydro-a,"
                          "ds18b20-1,water_temperature_c,C,,18.250,valid,cress-logger-0.2.0";

int main() {
  char out[512];
  CHECK(csvRowToObservationJson(GOOD, out, sizeof out) == RowResult::Ok);
  const char *expected =
      "{\"device_id\":\"cress-hydro-node\",\"farm_id\":\"home-pilot\",\"zone_id\":\"cress-hydro-a\","
      "\"sensor_id\":\"ds18b20-1\",\"measurement\":\"water_temperature_c\",\"unit\":\"C\","
      "\"timestamp\":\"2026-10-05T08:00:00Z\",\"quality\":\"valid\",\"value\":18.250,\"sequence\":42,"
      "\"boot_id\":\"0a1b2c3d4e5f6071\",\"firmware\":\"cress-logger-0.2.0\",\"schema_version\":\"1.0\"}";
  CHECK(std::string(out) == expected);

  // Line endings from println are \r\n.
  CHECK(csvRowToObservationJson((std::string(GOOD) + "\r\n").c_str(), out, sizeof out) == RowResult::Ok);
  CHECK(std::string(out) == expected);

  // pH row with raw volts and a suspect (uncalibrated) status: no value is sent, raw stays on the card.
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n,f,z,ph-probe-1,ph,pH,2.5031,,suspect,fw", out, sizeof out) == RowResult::Ok);
  CHECK(std::strstr(out, "\"value\"") == nullptr && std::strstr(out, "2.5031") == nullptr);
  CHECK(std::strstr(out, "\"quality\":\"suspect\",\"sequence\":7") != nullptr);

  // Rows that can never be sent are classified, not guessed.
  CHECK(csvRowToObservationJson(",b,7,n,f,z,s,ph,pH,,6.5,suspect,fw", out, sizeof out) == RowResult::SkipNoTimestamp);
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n,f,z,ds18b20-1,substrate_temperature_c,C,,17.5,valid,fw", out, sizeof out) == RowResult::SkipUnsupported);
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n,f,z,s,ph,pH,,,valid,fw", out, sizeof out) == RowResult::SkipMalformed);  // valid without value
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n,f,z,s,ph,pH,,abc,suspect,fw", out, sizeof out) == RowResult::SkipMalformed);
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,x,n,f,z,s,ph,pH,,6.5,valid,fw", out, sizeof out) == RowResult::SkipMalformed);   // sequence
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n\",f,z,s,ph,pH,,6.5,valid,fw", out, sizeof out) == RowResult::SkipMalformed); // quote in a field
  CHECK(csvRowToObservationJson("timestamp_utc,boot_id,sequence,device_id,farm_id,zone_id,sensor_id,measurement,unit,raw,value,quality,firmware", out, sizeof out) == RowResult::SkipMalformed);
  CHECK(csvRowToObservationJson("2026-10-05T08:00:00Z,b,7,n", out, sizeof out) == RowResult::SkipMalformed);          // cut short by a power loss
  CHECK(csvRowToObservationJson("", out, sizeof out) == RowResult::SkipMalformed);
  CHECK(csvRowToObservationJson(GOOD, out, 40) == RowResult::SkipMalformed);                                            // buffer too small
  CHECK(csvRowToObservationJson((std::string(GOOD) + ",extra").c_str(), out, sizeof out) == RowResult::SkipMalformed);

  CHECK(classifyHttpStatus(200) == HttpAction::Ack && classifyHttpStatus(201) == HttpAction::Ack && classifyHttpStatus(204) == HttpAction::Ack);
  for (int s : {400, 413, 422}) CHECK(classifyHttpStatus(s) == HttpAction::Skip);
  for (int s : {-1, 0, 301, 401, 403, 404, 408, 429, 500, 502, 503}) CHECK(classifyHttpStatus(s) == HttpAction::Retry);

  CHECK(uploadBackoffMs(0) == 30000 && uploadBackoffMs(1) == 30000 && uploadBackoffMs(2) == 60000 && uploadBackoffMs(3) == 120000);
  CHECK(uploadBackoffMs(6) == 900000 && uploadBackoffMs(7) == 900000 && uploadBackoffMs(255) == 900000);

  std::printf(failures ? "FAILED: %d\n" : "all upload_logic checks pass\n", failures);
  return failures ? 1 : 0;
}
