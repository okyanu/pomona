// Pomona watercress pilot logger: ESP32-S3 -> SD card CSV, monitoring only.
//
// Writes one CSV row per measurement every LOG_INTERVAL_MS. The CSV matches
// scripts/import_sd_csv.py. There is no actuator output of any kind.
// Status: written for the pilot, NOT compiled or bench-verified yet.

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Wire.h>
#include <WiFi.h>
#include <time.h>
#include <Adafruit_SHT31.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#include "config.h"

static const char *FIRMWARE = "cress-logger-0.1.0";
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
char logPath[64];

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
  float volts = ads.computeVolts(ads.readADC_SingleEnded(PH_ADS_CHANNEL));
  // Two-point calibration: pH = PH_SLOPE * volts + PH_OFFSET. Until the
  // owner records a buffer calibration, log raw volts only.
  if (PH_SLOPE == 0.0f) {
    writeRow("ph-probe-1", "ph", "pH", String(volts, 4), NAN, "suspect");
    return;
  }
  float ph = PH_SLOPE * volts + PH_OFFSET;
  bool plausible = ph >= 0.0f && ph <= 14.0f;
  writeRow("ph-probe-1", "ph", "pH", String(volts, 4), plausible ? ph : NAN,
           plausible ? "valid" : "suspect");
#endif
}

void setup() {
  Serial.begin(115200);
  delay(500);
  snprintf(bootId, sizeof(bootId), "%08lx%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random());
  snprintf(logPath, sizeof(logPath), "/pomona_%s.csv", DEVICE_ID);

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
  delay(100);
}
