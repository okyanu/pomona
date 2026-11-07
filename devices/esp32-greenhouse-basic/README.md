# ESP32 Greenhouse Basic

Firmware and wiring notes for a basic ESP32 greenhouse sensor node.

**Planned sensors:**
- pH
- EC
- Humidity
- Temperature
- Soil moisture

**Transport:** MQTT to Pomona Core. The broker requires a login: the firmware needs `MQTT_USER` / `MQTT_PASS` placeholders in its `config.example.h` (a real `config.h` stays out of git) and must pass them to the connect call. Plain MQTT, no TLS: local network only.

**Status:** Not implemented yet.
