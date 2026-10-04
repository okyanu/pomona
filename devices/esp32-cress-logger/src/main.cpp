// Pomona watercress pilot logger: ESP32-S3 -> SD card CSV, monitoring only.
//
// Writes one CSV row per measurement every LOG_INTERVAL_MS. The CSV matches
// scripts/import_sd_csv.py. There is no actuator output of any kind.
// Status: compiles (PlatformIO, hydro and soil variants); NOT bench-verified yet.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <Adafruit_SHT31.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#include "config.h"
#include "ph_calibration.h"
#include "upload_logic.h"

// pH is logged as the median of several ADS1115 reads per interval. Analog pH
// boards (PH-4502C style) swing ~1.6 pH within 5 minutes on single reads in
// real logs; the median rejects pump/ground-loop spikes. config.h may override.
#ifndef PH_SAMPLES
#define PH_SAMPLES 15
#endif
#ifndef PH_SAMPLE_GAP_MS
#define PH_SAMPLE_GAP_MS 20
#endif

// Optional pH calibration sanity check settings (see config.example.h); 0 = only the loose window.
#ifndef PH_EXPECTED_MV_PER_PH
#define PH_EXPECTED_MV_PER_PH 0
#endif
#ifndef PH_EXPECTED_SLOPE_SIGN
#define PH_EXPECTED_SLOPE_SIGN 0
#endif

// Optional Wi-Fi upload of the SD log to Pomona Core (needs WIFI_SSID and CORE_URL in config.h).
// The SD card stays the source of truth; see include/upload_logic.h for the retry rules.
#ifndef UPLOAD_INTERVAL_MS
#define UPLOAD_INTERVAL_MS LOG_INTERVAL_MS
#endif
#ifndef UPLOAD_MAX_ROWS
#define UPLOAD_MAX_ROWS 120        // rows per session: one pass over a normal 5-minute interval is ~6
#endif
#ifndef UPLOAD_SESSION_MS
#define UPLOAD_SESSION_MS 45000UL  // stop a session after this long, whatever is left waits for the next
#endif
#if defined(WIFI_SSID) && defined(CORE_URL)
#define UPLOAD_ENABLED 1
#else
#define UPLOAD_ENABLED 0
#endif

static const char *FIRMWARE = "cress-logger-0.2.0";
static const char *CSV_HEADER =
    "timestamp_utc,boot_id,sequence,device_id,farm_id,zone_id,sensor_id,"
    "measurement,unit,raw,value,quality,firmware";

Adafruit_SHT31 sht31;
Adafruit_ADS1115 ads;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature ds18b20(&oneWire);

bool shtOk = false;
bool adsOk = false;
bool sdOk = false;
char bootId[17];
uint32_t sequenceNo = 0;
PhCalResult phCal = {PhCalState::Uncalibrated, "", 0.0f, 0.0f};
char logPath[64];
char ackPath[72];

// Returns false until the clock has been set (NTP); rows then get an empty
// timestamp, which the importer rejects instead of guessing a time.
bool clockValid() { return time(nullptr) > 1704067200; }  // after 2024-01-01

void isoNow(char *out, size_t len) {
  if (!clockValid()) { out[0] = '\0'; return; }
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  strftime(out, len, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

void syncClockOnce() {
#if defined(WIFI_SSID)
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    for (int i = 0; i < 40 && !clockValid(); i++) delay(250);
  }
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
#endif
}

// value may be NAN: it is then written empty (quality must not be "valid").
void writeRow(const char *sensorId, const char *measurement, const char *unit,
              const String &raw, float value, const char *quality) {
  char ts[25];
  isoNow(ts, sizeof(ts));
  String line;
  line.reserve(200);
  line += ts; line += ',';
  line += bootId; line += ',';
  line += String(++sequenceNo); line += ',';
  line += DEVICE_ID; line += ',';
  line += FARM_ID; line += ',';
  line += ZONE_ID; line += ',';
  line += sensorId; line += ',';
  line += measurement; line += ',';
  line += unit; line += ',';
  line += raw; line += ',';
  if (!isnan(value)) line += String(value, 3);
  line += ',';
  line += clockValid() ? quality : "suspect";
  line += ',';
  line += FIRMWARE;

  Serial.println(line);
  if (!sdOk) return;
  // Open/close per row so a power cut loses at most the row being written.
  File f = SD.open(logPath, FILE_APPEND);
  if (f) { f.println(line); f.close(); }
}

void logSht31() {
  if (!shtOk) {
    writeRow("sht31-1", "air_temperature_c", "C", "", NAN, "disconnected");
    writeRow("sht31-1", "humidity_pct", "%", "", NAN, "disconnected");
    return;
  }
  float t = sht31.readTemperature();
  float h = sht31.readHumidity();
  writeRow("sht31-1", "air_temperature_c", "C", "", t, isnan(t) ? "missing" : "valid");
  writeRow("sht31-1", "humidity_pct", "%", "", h, isnan(h) ? "missing" : "valid");
}

void logDs18b20() {
  ds18b20.requestTemperatures();
  float t = ds18b20.getTempCByIndex(0);
  bool gone = (t == DEVICE_DISCONNECTED_C);
  // Hydro: probe sits in the reservoir. Soil: substrate temperature, which
  // Core has no field for yet, so it is logged under its own measurement
  // name only on the SD card and skipped by the importer (see README).
  const char *measurement = ZONE_IS_HYDRO ? "water_temperature_c" : "substrate_temperature_c";
  writeRow("ds18b20-1", measurement, "C", "", gone ? NAN : t, gone ? "disconnected" : "valid");
}

void logMoisture() {
#if !ZONE_IS_HYDRO
  int raw = analogRead(PIN_MOISTURE);
  // Capacitive probes read lower when wetter. Uncalibrated -> raw only.
  if (MOISTURE_RAW_DRY == MOISTURE_RAW_WET) {
    writeRow("cap-moisture-1", "soil_moisture_pct", "%", String(raw), NAN, "suspect");
    return;
  }
  float pct = 100.0f * (MOISTURE_RAW_DRY - raw) / float(MOISTURE_RAW_DRY - MOISTURE_RAW_WET);
  pct = constrain(pct, 0.0f, 100.0f);
  writeRow("cap-moisture-1", "soil_moisture_pct", "%", String(raw), pct, "valid");
#endif
}

void logPh() {
#if ZONE_IS_HYDRO && PH_PROBE_FITTED
  if (!adsOk) {
    writeRow("ph-probe-1", "ph", "pH", "", NAN, "disconnected");
    return;
  }
  int16_t reads[PH_SAMPLES];
  for (int i = 0; i < PH_SAMPLES; i++) {
    int16_t value = ads.readADC_SingleEnded(PH_ADS_CHANNEL);
    int j = i;  // insertion sort as we go
    for (; j > 0 && reads[j - 1] > value; j--) reads[j] = reads[j - 1];
    reads[j] = value;
    if (i + 1 < PH_SAMPLES) delay(PH_SAMPLE_GAP_MS);
  }
  int16_t median = reads[PH_SAMPLES / 2];
  float volts = ads.computeVolts(median);
  // A reading at the ADC rail is a floating, shorted or over-range input, not a pH. Keep the
  // raw volts for the record and give no value.
  if (phReadingAtRail(median)) {
    writeRow("ph-probe-1", "ph", "pH", String(volts, 4), NAN, "suspect");
    return;
  }
  // Two-point calibration: pH = PH_SLOPE * volts + PH_OFFSET. Until the
  // owner records a buffer calibration, log raw volts only.
  if (PH_SLOPE == 0.0f) {
    writeRow("ph-probe-1", "ph", "pH", String(volts, 4), NAN, "suspect");
    return;
  }
  float ph = PH_SLOPE * volts + PH_OFFSET;
  bool plausible = ph >= 0.0f && ph <= 14.0f;
  // A calibration that failed its sanity check (see boot line "ph_cal=") keeps its numbers but
  // every row is "suspect", so nothing downstream treats them as trusted.
  bool trusted = plausible && phCal.state == PhCalState::Ok;
  writeRow("ph-probe-1", "ph", "pH", String(volts, 4), plausible ? ph : NAN,
           trusted ? "valid" : "suspect");
#endif
}

#if UPLOAD_ENABLED
uint8_t uploadFailures = 0;
uint32_t nextUploadAt = 0;
uint32_t uploadedTotal = 0, skippedTotal = 0;

uint32_t readAckOffset() {
  File f = SD.open(ackPath, FILE_READ);
  if (!f) return 0;
  String text = f.readStringUntil('\n');
  f.close();
  long value = text.toInt();
  return value > 0 ? (uint32_t)value : 0;
}

// Write the new offset next to the old one, then swap: a power cut leaves either the old or the
// new offset, never a half-written one. An old offset only means some rows are sent twice.
void writeAckOffset(uint32_t offset) {
  char tmp[76];
  snprintf(tmp, sizeof(tmp), "%s.tmp", ackPath);
  SD.remove(tmp);
  File f = SD.open(tmp, FILE_WRITE);
  if (!f) return;
  f.println(offset);
  f.close();
  SD.remove(ackPath);
  SD.rename(tmp, ackPath);
}

// Reads one '\n'-terminated line. Returns false at end of file or if the last line is not finished
// yet (power cut while writing): an unfinished line is never sent.
bool readLogLine(File &f, char *buf, size_t cap) {
  size_t n = 0;
  while (f.available()) {
    int c = f.read();
    if (c == '\n') { buf[n] = '\0'; return true; }
    if (n + 1 < cap) buf[n++] = (char)c;
  }
  return false;
}

bool connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

void wifiOff() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

// One upload session: oldest unsent rows first, stop at the first sign of trouble. Returns true
// when nothing went wrong (including "nothing to send").
bool uploadBacklog() {
  if (!sdOk) return true;
  if (strncmp(CORE_URL, "http://", 7) != 0) {
    Serial.println("upload: CORE_URL must start with http:// (trusted LAN); https is not supported");
    return true;
  }
  File f = SD.open(logPath, FILE_READ);
  if (!f) return true;
  uint32_t offset = readAckOffset();
  if (offset > f.size()) offset = 0;  // log replaced or card swapped: start over, Core drops repeats
  if (offset >= f.size()) { f.close(); return true; }

  if (!connectWifi()) {
    f.close();
    wifiOff();
    Serial.println("upload: Wi-Fi not connected, will retry");
    return false;
  }
  if (!clockValid()) {  // a late NTP sync still gives all following rows real timestamps
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    for (int i = 0; i < 40 && !clockValid(); i++) delay(250);
  }

  f.seek(offset);
  char line[260];
  char body[560];
  uint32_t started = millis(), sent = 0, skipped = 0;
  bool healthy = true;
  for (int rows = 0; rows < UPLOAD_MAX_ROWS && millis() - started < UPLOAD_SESSION_MS; rows++) {
    if (!readLogLine(f, line, sizeof(line))) break;
    uint32_t next = f.position();
    if (strncmp(line, "timestamp_utc", 13) == 0) { offset = next; continue; }  // header
    RowResult row = csvRowToObservationJson(line, body, sizeof(body));
    if (row != RowResult::Ok) { offset = next; skipped++; continue; }  // never sendable: do not block the queue
    HTTPClient http;
    http.setTimeout(5000);
    http.begin(String(CORE_URL) + "/v1/sensors/observations");
    http.addHeader("Content-Type", "application/json");
#ifdef CORE_API_KEY
    http.addHeader("Authorization", String("Bearer ") + CORE_API_KEY);
#endif
    int status = http.POST((uint8_t *)body, strlen(body));
    http.end();
    HttpAction action = classifyHttpStatus(status);
    if (action == HttpAction::Retry) {
      Serial.printf("upload: HTTP %d, will retry\n", status);
      healthy = false;
      break;
    }
    offset = next;
    if (action == HttpAction::Ack) sent++; else { skipped++; Serial.printf("upload: Core rejected a row (HTTP %d), skipped\n", status); }
  }
  f.close();
  writeAckOffset(offset);
  wifiOff();
  uploadedTotal += sent;
  skippedTotal += skipped;
  Serial.printf("upload: sent=%lu skipped=%lu total_sent=%lu total_skipped=%lu ok=%d\n",
                (unsigned long)sent, (unsigned long)skipped, (unsigned long)uploadedTotal,
                (unsigned long)skippedTotal, healthy);
  return healthy;
}

void uploadIfDue() {
  if ((int32_t)(millis() - nextUploadAt) < 0) return;
  bool ok = uploadBacklog();
  uploadFailures = ok ? 0 : (uploadFailures < 250 ? uploadFailures + 1 : 250);
  nextUploadAt = millis() + (ok ? UPLOAD_INTERVAL_MS : uploadBackoffMs(uploadFailures));
}
#endif

void setup() {
  Serial.begin(115200);
  delay(500);
  snprintf(bootId, sizeof(bootId), "%08lx%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random());
  snprintf(logPath, sizeof(logPath), "/pomona_%s.csv", DEVICE_ID);
  snprintf(ackPath, sizeof(ackPath), "/pomona_%s.ack", DEVICE_ID);

  Wire.begin(PIN_SDA, PIN_SCL);
  shtOk = sht31.begin(0x44);
  adsOk = ads.begin(0x48);
  ds18b20.begin();
  analogReadResolution(12);

  SPI.begin(PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, PIN_SD_CS);
  sdOk = SD.begin(PIN_SD_CS);
  if (sdOk && !SD.exists(logPath)) {
    File f = SD.open(logPath, FILE_WRITE);
    if (f) { f.println(CSV_HEADER); f.close(); }
  }
  Serial.printf("boot_id=%s sd=%d sht31=%d ads1115=%d\n", bootId, sdOk, shtOk, adsOk);
#if ZONE_IS_HYDRO && PH_PROBE_FITTED
  phCal = phCalibrationCheck(PH_SLOPE, PH_OFFSET, PH_EXPECTED_MV_PER_PH, PH_EXPECTED_SLOPE_SIGN);
  Serial.printf("ph_cal=%s sens=%.0f mV/pH v7=%.3f V %s\n",
                phCal.state == PhCalState::Ok ? "ok" : phCal.state == PhCalState::Suspect ? "SUSPECT" : "uncalibrated",
                phCal.mv_per_ph, phCal.v_at_ph7, phCal.reason);
#endif

  syncClockOnce();
  Serial.println(clockValid() ? "clock synced" : "clock NOT set: rows get empty timestamps");
}

void loop() {
  static uint32_t last = 0;
  if (last == 0 || millis() - last >= LOG_INTERVAL_MS) {
    last = millis();
    logSht31();
    logDs18b20();
    logMoisture();
    logPh();
  }
#if UPLOAD_ENABLED
  uploadIfDue();
#endif
  delay(100);
}
