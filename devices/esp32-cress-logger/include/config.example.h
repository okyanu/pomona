// Copy to include/config.h (gitignored) and edit per node.
#pragma once

// Identity: one node per zone. zone_id values match docs/WATERCRESS_PILOT.md.
#define DEVICE_ID "cress-hydro-node"   // or "cress-soil-node"
#define FARM_ID   "home-pilot"
#define ZONE_ID   "cress-hydro-a"      // or "cress-soil-a"
#define ZONE_IS_HYDRO 1                // 1 = hydro (water temp, pH), 0 = soil (moisture)
#define PH_PROBE_FITTED 1              // hydro only: analog pH probe via ADS1115

// Optional one-time NTP clock sync at boot; Wi-Fi is switched off afterwards.
// Leave commented out to disable (rows will then have empty timestamps).
// #define WIFI_SSID     "your-ssid"
// #define WIFI_PASSWORD "your-password"

#define LOG_INTERVAL_MS (5UL * 60UL * 1000UL)

// Pins: common ESP32-S3 DevKit defaults. Check against your board's pinout.
#define PIN_SDA 8
#define PIN_SCL 9
#define PIN_ONEWIRE 4        // DS18B20 data, 4.7k pull-up to 3.3V
#define PIN_MOISTURE 1       // capacitive probe analog out (ADC1)
#define PIN_SD_CS 10
#define PIN_SD_MOSI 11
#define PIN_SD_SCK 12
#define PIN_SD_MISO 13

// Moisture calibration: raw ADC reading in dry air and in water.
// Equal values = uncalibrated, so only raw is logged (quality=suspect).
#define MOISTURE_RAW_DRY 0
#define MOISTURE_RAW_WET 0

// pH calibration: pH = PH_SLOPE * volts + PH_OFFSET, from pH 7 and pH 4
// buffers. PH_SLOPE 0 = uncalibrated, so only raw volts are logged.
#define PH_ADS_CHANNEL 0
// Each logged pH is the median of PH_SAMPLES reads, PH_SAMPLE_GAP_MS apart
// (defaults 15 and 20 ms, about 0.4 s). Use an odd count.
// #define PH_SAMPLES 15
// #define PH_SAMPLE_GAP_MS 20
#define PH_SLOPE 0.0f
#define PH_OFFSET 0.0f
