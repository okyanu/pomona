// Wi-Fi upload decisions for the SD log. Plain C++ (no Arduino calls) so it can be tested on a PC:
//   c++ -std=c++17 -Wall -Iinclude extras/test_upload_logic.cpp -o /tmp/t && /tmp/t
//
// The SD CSV is the queue and the source of truth. A small ack file holds the byte offset of the
// first row Core has not confirmed. Rows are sent oldest first and the offset only moves past a
// row once Core accepted it (HTTP 2xx) or can never accept it (a permanent 4xx or a row that
// cannot be sent). Core ignores a repeated boot_id + sequence, so resending after a lost reply is
// harmless; losing the ack file only causes a resend, never a gap.
#pragma once

#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum class RowResult { Ok, SkipNoTimestamp, SkipUnsupported, SkipMalformed };
enum class HttpAction { Ack, Skip, Retry };

// What to do with an HTTP status (<= 0 means no response: Wi-Fi, DNS, timeout).
//   2xx            Core stored it (or already had it): move on.
//   400, 413, 422  the row itself is bad and always will be: skip it so it cannot block the queue.
//   everything else (401/403 wrong API key, 404 wrong URL, 408, 429, 5xx, no response) is a problem
//   to fix or wait out, not with the row: stop, keep the offset, retry later with backoff.
inline HttpAction classifyHttpStatus(int status) {
  if (status >= 200 && status < 300) return HttpAction::Ack;
  if (status == 400 || status == 413 || status == 422) return HttpAction::Skip;
  return HttpAction::Retry;
}

// Wait before the next attempt after `failures` failed sessions in a row: 30 s, 1 min, 2 min ...
// capped at 15 min. Never zero, so a dead network is not hammered.
inline uint32_t uploadBackoffMs(uint8_t failures) {
  uint32_t ms = 30000UL;
  for (uint8_t i = 1; i < failures && ms < 900000UL; i++) ms *= 2;
  return ms > 900000UL ? 900000UL : ms;
}

inline bool isSafeToken(const char *s, size_t n) {  // ids, units, versions: no quotes or control chars
  if (n == 0 || n > 64) return false;
  for (size_t i = 0; i < n; i++) {
    char c = s[i];
    bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              c == '_' || c == '-' || c == '.' || c == ':' || c == '%' || c == '/';
    if (!ok) return false;
  }
  return true;
}

inline bool isNumberText(const char *s, size_t n) {
  if (n == 0 || n > 24) return false;
  bool digit = false;
  for (size_t i = 0; i < n; i++) {
    char c = s[i];
    if (c >= '0' && c <= '9') digit = true;
    else if (c != '.' && c != '-' && c != '+' && c != 'e' && c != 'E') return false;
  }
  return digit;
}

inline bool isSupportedMeasurement(const char *s, size_t n) {
  static const char *const kinds[] = {"air_temperature_c", "water_temperature_c", "humidity_pct", "ph",
                                      "ec_ms_cm", "soil_moisture_pct", "low_level_contact"};
  for (const char *k : kinds) if (strlen(k) == n && strncmp(k, s, n) == 0) return true;
  return false;  // e.g. substrate_temperature_c is logged on the SD card only (Core has no field)
}

// Turn one log line (timestamp_utc,boot_id,sequence,device_id,farm_id,zone_id,sensor_id,
// measurement,unit,raw,value,quality,firmware) into the JSON body of POST /v1/sensors/observations.
// `raw` stays on the SD card. Nothing is guessed: a row without a timestamp is skipped, never given one.
inline RowResult csvRowToObservationJson(const char *line, char *out, size_t cap) {
  const char *f[13];
  size_t len[13];
  size_t n = 0;
  const char *start = line;
  for (const char *p = line;; p++) {
    if (*p == ',' || *p == '\0' || *p == '\r' || *p == '\n') {
      if (n >= 13) return RowResult::SkipMalformed;
      f[n] = start;
      len[n++] = (size_t)(p - start);
      if (*p != ',') break;
      start = p + 1;
    }
  }
  if (n != 13) return RowResult::SkipMalformed;
  const size_t TS = 0, BOOT = 1, SEQ = 2, DEV = 3, FARM = 4, ZONE = 5, SENSOR = 6, MEAS = 7, UNIT = 8,
               VALUE = 10, QUALITY = 11, FW = 12;
  if (len[TS] == 0) return RowResult::SkipNoTimestamp;
  if (!isSafeToken(f[TS], len[TS]) || len[TS] < 20) return RowResult::SkipMalformed;
  for (size_t i : {BOOT, DEV, FARM, ZONE, SENSOR, UNIT, QUALITY, FW})
    if (!isSafeToken(f[i], len[i])) return RowResult::SkipMalformed;
  if (!isNumberText(f[SEQ], len[SEQ])) return RowResult::SkipMalformed;
  if (!isSupportedMeasurement(f[MEAS], len[MEAS])) return RowResult::SkipUnsupported;
  bool hasValue = len[VALUE] > 0;
  if (hasValue && !isNumberText(f[VALUE], len[VALUE])) return RowResult::SkipMalformed;
  if (!hasValue && len[QUALITY] == 5 && strncmp(f[QUALITY], "valid", 5) == 0) return RowResult::SkipMalformed;

  int w = snprintf(out, cap,
                   "{\"device_id\":\"%.*s\",\"farm_id\":\"%.*s\",\"zone_id\":\"%.*s\",\"sensor_id\":\"%.*s\","
                   "\"measurement\":\"%.*s\",\"unit\":\"%.*s\",\"timestamp\":\"%.*s\",\"quality\":\"%.*s\","
                   "%s%.*s%s\"sequence\":%.*s,\"boot_id\":\"%.*s\",\"firmware\":\"%.*s\",\"schema_version\":\"1.0\"}",
                   (int)len[DEV], f[DEV], (int)len[FARM], f[FARM], (int)len[ZONE], f[ZONE], (int)len[SENSOR], f[SENSOR],
                   (int)len[MEAS], f[MEAS], (int)len[UNIT], f[UNIT], (int)len[TS], f[TS], (int)len[QUALITY], f[QUALITY],
                   hasValue ? "\"value\":" : "", (int)(hasValue ? len[VALUE] : 0), f[VALUE], hasValue ? "," : "",
                   (int)len[SEQ], f[SEQ], (int)len[BOOT], f[BOOT], (int)len[FW], f[FW]);
  return (w > 0 && (size_t)w < cap) ? RowResult::Ok : RowResult::SkipMalformed;
}
